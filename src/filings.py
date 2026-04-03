# ============================================================
# FILE: src/filings.py
# PURPOSE: Fetches recent BSE corporate announcements for a
#          company and summarises each PDF filing via gpt-4o-mini.
#          Provides the "Recent filings" section of the research brief.
# INPUT:   bse_code (str) — e.g. "500325" for Reliance
# OUTPUT:  dict with list of filings, each with title/date/summary
# DEPENDS: requests, pdfplumber, src/cache.py, src/llm.py
# ============================================================

import io

import pdfplumber
import requests

from src.cache import get_cached, set_cached
from src.llm import call_fast_model

# BSE announcements API — undocumented; Referer header required or requests are rejected.
_BSE_ANNOUNCEMENTS_URL = (
    "https://api.bseindia.com/BseIndiaAPI/api/AnnGetAnnouncemnt/w"
    "?strPno=1&strScrip={bse_code}&Category=Corp.Action&subcategory=-1"
)

# Headers required by BSE API and CDN.
_BSE_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.bseindia.com/",
}

# Base URL for attachment PDFs on BSE's filing archive.
_PDF_BASE_URL = "https://www.bseindia.com/xml-data/corpfiling/AttachHis/{attachment_name}"

# PDF text is truncated to this length before the LLM call to control token cost.
_MAX_TEXT_CHARS = 3000


def fetch_filings(bse_code: str, n: int = 5) -> dict:
    """
    Fetches the n most recent BSE corporate announcements for a company and
    summarises each available PDF filing via gpt-4o-mini.

    Workflow:
        1. Return cached result immediately if a fresh entry exists.
        2. Call the BSE announcements API for the given bse_code.
        3. For each of the first n announcements, build the attachment PDF URL.
        4. Download each PDF, extract text with pdfplumber, summarise with gpt-4o-mini.
        5. Cache and return the result dict.

    Individual PDF failures (download errors, empty text, OpenAI errors) set that
    filing's summary to None and processing continues — a single bad PDF never aborts
    the batch. BSE API failure returns immediately with an error field and no filings.

    Args:
        bse_code: BSE numeric company code, e.g. "500325" for Reliance Industries.
        n:        Maximum number of filings to fetch and summarise (default 5).

    Returns:
        dict with keys:
            bse_code  (str):  The input BSE code.
            filings   (list): Up to n filing dicts, each containing:
                title    (str)       — announcement subject line
                date     (str)       — "YYYY-MM-DD"
                category (str)       — BSE category label
                pdf_url  (str|None)  — direct URL to the PDF, or None
                summary  (str|None)  — 3-sentence gpt-4o-mini summary, or None
            error     (str|None): None on success; human-readable message on failure.

    Raises:
        Nothing — all failures are captured in the returned dict's error field.
    """
    # --- Step 1: return cache hit immediately ---
    cache_key = f"filings_{bse_code}"
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    # --- Step 2: call the BSE announcements API ---
    url = _BSE_ANNOUNCEMENTS_URL.format(bse_code=bse_code)
    try:
        response = requests.get(url, headers=_BSE_HEADERS, timeout=15)
    except requests.exceptions.RequestException as exc:
        return {"bse_code": bse_code, "filings": [], "error": str(exc)}

    if response.status_code != 200:
        return {
            "bse_code": bse_code,
            "filings": [],
            "error": f"BSE API returned {response.status_code}",
        }

    # --- Step 3: parse the response JSON ---
    try:
        payload = response.json()
    except ValueError as exc:
        return {
            "bse_code": bse_code,
            "filings": [],
            "error": f"BSE API returned non-JSON response: {exc}",
        }

    # The BSE API wraps results in a "Table" key.
    raw_items = payload.get("Table", [])
    if not isinstance(raw_items, list):
        return {
            "bse_code": bse_code,
            "filings": [],
            "error": 'BSE API response missing expected "Table" key.',
        }

    # Take only the first n announcements.
    raw_items = raw_items[:n]

    # --- Step 4: build filing records and summarise each PDF ---
    filings = []
    for item in raw_items:
        title           = item.get("NEWSSUB", "").strip()
        raw_date        = item.get("NEWS_DT", "")
        category        = item.get("CATEGORYNAME", "").strip()
        attachment_name = item.get("ATTACHMENTNAME", "").strip()

        # Normalise date to "YYYY-MM-DD" regardless of the timestamp format returned.
        date = _parse_date(raw_date)

        # Build the PDF URL only when an attachment filename is present.
        pdf_url = (
            _PDF_BASE_URL.format(attachment_name=attachment_name)
            if attachment_name
            else None
        )

        # Attempt to download and summarise the PDF; failures yield summary=None.
        summary = _summarise_pdf(pdf_url, title) if pdf_url else None

        filings.append({
            "title":    title,
            "date":     date,
            "category": category,
            "pdf_url":  pdf_url,
            "summary":  summary,
        })

    result = {"bse_code": bse_code, "filings": filings, "error": None}

    # --- Step 5: cache and return ---
    try:
        set_cached(cache_key, result)
    except Exception as e:
        print(f"Warning: cache write failed for filings_{bse_code}: {e}")

    return result


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _parse_date(raw_date: str) -> str:
    """
    Extracts the "YYYY-MM-DD" portion from a BSE date string.

    The BSE API returns dates in varying formats, most commonly ISO-8601
    with a time component, e.g. "2024-01-15T00:00:00". We take the
    substring before the "T" separator and strip surrounding whitespace.

    Args:
        raw_date: Date string as returned by the BSE API.

    Returns:
        "YYYY-MM-DD" string, or "" if the input is empty or unparseable.
    """
    if not raw_date:
        return ""
    return raw_date.split("T")[0].strip()


def _summarise_pdf(pdf_url: str, title: str) -> str | None:
    """
    Downloads a BSE filing PDF, extracts text, and summarises it via gpt-4o-mini.

    This function is intentionally defensive: every failure mode (network error,
    non-200 response, empty PDF, OpenAI error) returns None rather than raising,
    so a single bad filing never aborts the batch in fetch_filings().

    Args:
        pdf_url: Direct URL to the PDF hosted on bseindia.com.
        title:   Announcement title used as context in the LLM prompt.

    Returns:
        A 3-sentence summary string on success, or None on any failure.
    """
    # --- Download the PDF bytes ---
    try:
        pdf_response = requests.get(
            pdf_url,
            timeout=30,
            headers={"Referer": "https://www.bseindia.com/"},
        )
    except requests.exceptions.RequestException:
        return None

    if pdf_response.status_code != 200:
        return None

    # --- Extract text from the PDF using pdfplumber ---
    try:
        pdf_bytes = io.BytesIO(pdf_response.content)
        with pdfplumber.open(pdf_bytes) as pdf:
            pages_text = [page.extract_text() or "" for page in pdf.pages]
        text = "\n".join(pages_text).strip()
    except Exception:
        return None

    # Skip PDFs that are image-only scans or otherwise yield no usable text.
    if not text or len(text) < 50:
        return None

    # Truncate to control gpt-4o-mini token cost.
    text = text[:_MAX_TEXT_CHARS]

    # --- Call fast model for a concise 3-sentence summary ---
    try:
        return call_fast_model(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a concise financial analyst. "
                        "Summarise the BSE corporate filing in exactly 3 sentences. "
                        "Focus on: (1) what was announced, "
                        "(2) the key financial or operational detail, "
                        "(3) significance for shareholders."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Filing title: {title}\n\n{text}",
                },
            ],
            max_tokens=200,
            temperature=0.1,
        ).strip()
    except Exception:
        return None
