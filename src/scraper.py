# ============================================================
# FILE: src/scraper.py
# PURPOSE: Authenticates with Screener.in and scrapes complete
#          fundamental data for a given NSE/BSE ticker.
#          Tries the consolidated view first; falls back to
#          standalone if consolidated is unavailable.
#          Uses Screener's schedule sub-row API to get granular
#          line items (CapEx, inventories, trade payables, etc.)
#          that are only accessible via AJAX expansion.
# INPUT:   ticker (str) — e.g. "RELIANCE", "INFY"
# OUTPUT:  dict with all financial data sections (see
#          fetch_company_data docstring for full schema)
# DEPENDS: requests, beautifulsoup4, lxml, python-dotenv
#          .env must contain: SCREENER_EMAIL, SCREENER_PASSWORD
# ============================================================

import os
import re
import time

import requests
from bs4 import BeautifulSoup, NavigableString
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOGIN_URL    = "https://www.screener.in/login/"
COMPANY_URL  = "https://www.screener.in/company/{ticker}/{variant}"
SCHEDULE_URL = "https://www.screener.in/api/company/{company_id}/schedules/"
REQUEST_DELAY_SECONDS = 2.5

# Module-level authenticated session — created once on first use, reused
# for all subsequent requests within the same process lifetime.
_session: requests.Session | None = None


# ---------------------------------------------------------------------------
# Internal helpers — authentication & page fetching
# ---------------------------------------------------------------------------

def _get_authenticated_session() -> requests.Session:
    """
    Returns a requests.Session authenticated with Screener.in.

    On first call, performs the full login handshake (GET login page to
    obtain CSRF token, then POST credentials). The session is stored in the
    module-level _session variable and reused on all subsequent calls —
    authentication happens exactly once per process lifetime.

    Returns:
        An authenticated requests.Session with sessionid cookie set.

    Raises:
        RuntimeError: if SCREENER_EMAIL or SCREENER_PASSWORD are missing
                      from the environment, or if login fails.
    """
    global _session
    if _session is not None:
        return _session

    email    = os.getenv("SCREENER_EMAIL")
    password = os.getenv("SCREENER_PASSWORD")

    if not email or not password:
        raise RuntimeError(
            "SCREENER_EMAIL and SCREENER_PASSWORD must be set in .env. "
            "Copy .env.example to .env and fill in your Screener.in credentials."
        )

    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    })

    # Step 1: GET login page to obtain CSRF token
    time.sleep(REQUEST_DELAY_SECONDS)
    resp = session.get(LOGIN_URL, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    csrf_input = soup.find("input", {"name": "csrfmiddlewaretoken"})
    if not csrf_input:
        raise RuntimeError(
            "Could not find csrfmiddlewaretoken on Screener.in login page. "
            "The login page structure may have changed."
        )
    csrf_token = csrf_input["value"]

    # Step 2: POST credentials
    time.sleep(REQUEST_DELAY_SECONDS)
    login_resp = session.post(
        LOGIN_URL,
        data={
            "csrfmiddlewaretoken": csrf_token,
            "username": email,
            "password": password,
        },
        headers={"Referer": LOGIN_URL},
        timeout=15,
    )
    login_resp.raise_for_status()

    # Verify login succeeded: failed login stays on /login/, success redirects away
    if "/login/" in login_resp.url:
        raise RuntimeError(
            "Screener.in login failed — still on login page after POST. "
            "Check SCREENER_EMAIL and SCREENER_PASSWORD in .env."
        )

    _session = session
    return _session


def _fetch_page(ticker: str) -> tuple[BeautifulSoup, bool, str, str]:
    """
    Fetches the Screener.in company page for the given ticker.

    Tries the consolidated view first. If Screener indicates consolidated
    data is unavailable for this company, falls back to the standalone view.

    Args:
        ticker: NSE/BSE stock symbol, e.g. "RELIANCE"

    Returns:
        A tuple of (BeautifulSoup, is_consolidated, company_id) where
        is_consolidated is True if the consolidated page was used, and
        company_id is Screener's internal integer ID (needed for schedule API).

    Raises:
        ValueError: if the ticker is not found on Screener.in (HTTP 404).
        RuntimeError: if authentication fails or company_id cannot be found.
    """
    session = _get_authenticated_session()

    for variant, is_consolidated in [("consolidated/", True), ("", False)]:
        url = COMPANY_URL.format(ticker=ticker, variant=variant)
        time.sleep(REQUEST_DELAY_SECONDS)
        resp = session.get(url, timeout=15)

        if resp.status_code == 404:
            raise ValueError(
                f"Ticker '{ticker}' not found on Screener.in. "
                "Verify the NSE/BSE symbol is correct."
            )

        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Screener shows an alert when consolidated data doesn't exist
        alerts = soup.select("div.alert-warning, p.alert-warning")
        no_consolidated = any(
            "does not have consolidated" in (a.get_text() or "").lower()
            for a in alerts
        )

        if is_consolidated and no_consolidated:
            continue  # retry with standalone

        # Extract Screener's internal company ID and warehouse ID from the
        # data attributes on div#company-info.
        # company_id is needed for the schedule sub-row API.
        # warehouse_id is needed for the quick_ratios API (user's custom ratios).
        company_div = soup.find(attrs={"data-company-id": True})
        if not company_div:
            raise RuntimeError(
                f"Could not find data-company-id attribute for ticker '{ticker}'. "
                "Screener.in page structure may have changed."
            )
        company_id   = company_div["data-company-id"]
        warehouse_id = company_div.get("data-warehouse-id", "")

        return soup, is_consolidated, company_id, warehouse_id

    raise ValueError(
        f"Could not load any page for ticker '{ticker}' on Screener.in."
    )


def _fetch_schedule(
    company_id: str,
    parent: str,
    section: str,
    is_consolidated: bool,
) -> dict[str, dict[str, str]]:
    """
    Calls Screener's schedule sub-row API to fetch granular line items
    hidden behind expandable '+' buttons on the company page.

    The API returns a JSON object mapping row label → {period: value_str}.
    Example: {"Inventories": {"Mar 2024": "152,770", ...}, ...}

    Args:
        company_id:     Screener's internal company ID (from data-company-id).
        parent:         Parent row label, e.g. "Other Assets", "Fixed Assets".
        section:        Section name, e.g. "balance-sheet", "cash-flow".
        is_consolidated: Whether to request consolidated data.

    Returns:
        Dict mapping sub-row label to a period→value_string dict.
        Returns empty dict if the API returns a non-200 response (graceful
        degradation — sub-rows are enrichment, not required data).
    """
    session = _get_authenticated_session()
    params: dict[str, str] = {"parent": parent, "section": section}
    if is_consolidated:
        params["consolidated"] = ""

    time.sleep(REQUEST_DELAY_SECONDS)
    resp = session.get(
        SCHEDULE_URL.format(company_id=company_id),
        params=params,
        timeout=15,
    )
    if resp.status_code != 200:
        return {}
    try:
        return resp.json()
    except Exception:
        return {}


def _schedule_series(
    schedule_data: dict[str, dict[str, str]],
    row_label: str,
    years: list[str],
) -> list[float | None]:
    """
    Extracts a time-series list from a schedule API response, aligned to
    the given year/period headers.

    Args:
        schedule_data: Dict returned by _fetch_schedule.
        row_label:     The sub-row label to extract (case-insensitive prefix).
        years:         List of period strings to align to (e.g. ["Mar 2024", ...]).

    Returns:
        List of float | None values aligned to years. Returns list of None
        values if the row_label is not found in schedule_data.
    """
    label_lower = row_label.lower()
    data: dict[str, str] = {}
    for key, val in schedule_data.items():
        if key.lower().startswith(label_lower):
            data = val
            break

    if not data:
        return [None] * len(years)

    result = []
    for yr in years:
        raw = data.get(yr, "")
        result.append(_parse_number_or_none(raw))
    return result


# ---------------------------------------------------------------------------
# Unit metadata constants
# ---------------------------------------------------------------------------

# Static unit map for all header and key_ratios fields.
# These are fixed for Indian companies on Screener.in — always INR.
_HEADER_UNITS: dict[str, str] = {
    "current_price":    "INR",
    "market_cap":       "INR_Cr",
    "high_52w":         "INR",
    "low_52w":          "INR",
    "book_value":       "INR",
    "face_value":       "INR",
    "dividend_yield":   "%",
    "price_change_pct": "%",
    "pe":               "x",
    "roce":             "%",
    "roe":              "%",
    "debt_to_equity":   "x",
    "current_ratio":    "x",
}


# ---------------------------------------------------------------------------
# Internal helpers — data extraction utilities
# ---------------------------------------------------------------------------

def _parse_number(text: str, field: str, ticker: str) -> float:
    """
    Parses a formatted Indian number string (e.g. "1,23,456.78") to float.

    Handles Indian comma formatting, percentage signs, negative parentheses
    like "(12.3)" → -12.3, and rupee symbols.

    Args:
        text:   Raw string from the HTML cell.
        field:  Field name, used only in the error message.
        ticker: Ticker symbol, used only in the error message.

    Returns:
        Parsed float value.

    Raises:
        ValueError: if the string is empty/dash or cannot be parsed as a number.
    """
    cleaned = text.replace(",", "").replace("%", "").replace("₹", "").strip()
    cleaned = re.sub(r"^\((.+)\)$", r"-\1", cleaned)
    if cleaned in ("", "-", "--", "—"):
        raise ValueError(
            f"Field '{field}' for ticker '{ticker}' is empty or a dash. "
            "Screener.in may not have this data point for this company."
        )
    try:
        return float(cleaned)
    except ValueError:
        raise ValueError(
            f"Could not parse '{text}' as a number for field '{field}', "
            f"ticker '{ticker}'. Screener.in page structure may have changed."
        )


def _parse_number_or_none(text: str) -> float | None:
    """
    Parses a number string, returning None if the cell is empty or a dash.

    Used for time-series table rows where some columns may be blank because
    Screener hasn't computed the value yet.

    Args:
        text: Raw string from the HTML cell or API response.

    Returns:
        Parsed float, or None if the cell is empty/dash.
    """
    cleaned = text.replace(",", "").replace("%", "").replace("₹", "").strip()
    cleaned = re.sub(r"^\((.+)\)$", r"-\1", cleaned)
    if cleaned in ("", "-", "--", "—"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_table_rows(
    container: BeautifulSoup, section_name: str, ticker: str
) -> dict[str, list[str]]:
    """
    Extracts all rows from the first data-table inside a BeautifulSoup element.

    Builds a dict mapping the row label (first cell text) to a list of raw
    string values (remaining cells). Column headers are stored under the
    special key "__headers__".

    Args:
        container:    BeautifulSoup element to search within.
        section_name: Human-readable name used in error messages.
        ticker:       Ticker symbol used in error messages.

    Returns:
        dict where each key is a row label and value is list of cell strings.
        The special key "__headers__" holds the column header texts.

    Raises:
        ValueError: if no data-table or tbody is found.
    """
    table = container.find("table", class_="data-table")
    if not table:
        raise ValueError(
            f"Could not find data-table in '{section_name}' for ticker '{ticker}'. "
            "Screener.in page structure may have changed."
        )

    result: dict[str, list[str]] = {}

    thead = table.find("thead")
    if thead:
        headers = [th.get_text(strip=True) for th in thead.find_all("th")]
        result["__headers__"] = headers[1:] if headers else []

    tbody = table.find("tbody")
    if not tbody:
        raise ValueError(
            f"Could not find tbody in '{section_name}' table for ticker '{ticker}'."
        )

    for tr in tbody.find_all("tr"):
        cells = tr.find_all("td")
        if not cells:
            continue
        label = cells[0].get_text(strip=True)
        values = [td.get_text(strip=True) for td in cells[1:]]
        if label:
            result[label] = values

    return result


def _require_row(rows: dict, row_label: str, section: str, ticker: str) -> list[str]:
    """
    Returns the values for a required row label, raising if missing.

    Uses case-insensitive prefix matching so minor Screener label wording
    changes don't immediately break the scraper.

    Args:
        rows:       Dict returned by _extract_table_rows.
        row_label:  The label to search for (case-insensitive prefix match).
        section:    Section name for the error message.
        ticker:     Ticker symbol for the error message.

    Returns:
        List of raw string cell values for that row.

    Raises:
        ValueError: if no matching row label is found.
    """
    label_lower = row_label.lower()
    for key, values in rows.items():
        if key.lower().startswith(label_lower):
            return values
    raise ValueError(
        f"Could not find row '{row_label}' in '{section}' for ticker '{ticker}'. "
        "Screener.in page structure may have changed."
    )


def _extract_section_units(section: BeautifulSoup, ticker: str) -> dict:
    """
    Extracts the scale and currency from a section's subtitle paragraph.

    Screener.in renders a line like "Consolidated Figures in Rs. Crores"
    inside a <p class="sub"> at the top of each financial table section.

    Args:
        section: BeautifulSoup element for the section.
        ticker:  Ticker symbol used in error messages.

    Returns:
        dict with keys: scale (str) — "Cr" or "L"; currency (str) — "INR".

    Raises:
        ValueError: if the <p class="sub"> subtitle paragraph is missing.
    """
    sub_p = section.select_one("p.sub")
    if not sub_p:
        raise ValueError(
            f"Could not find unit subtitle (p.sub) in section "
            f"'{section.get('id', '?')}' for ticker '{ticker}'. "
            "Screener.in page structure may have changed."
        )

    first_text_node = next(
        (str(node) for node in sub_p.children if isinstance(node, NavigableString)),
        "",
    )
    raw_text = first_text_node.split("/")[0].strip()

    currency = "INR" if "rs." in raw_text.lower() else raw_text

    text_lower = raw_text.lower()
    if "crore" in text_lower:
        scale = "Cr"
    elif "lakh" in text_lower:
        scale = "L"
    else:
        parts = text_lower.split()
        in_idx = next((i for i, p in enumerate(parts) if p == "in"), -1)
        scale = parts[in_idx + 1] if in_idx >= 0 and in_idx + 1 < len(parts) else "unknown"

    return {"scale": scale, "currency": currency}


# ---------------------------------------------------------------------------
# Internal helpers — section extractors
# ---------------------------------------------------------------------------

def _get_company_header(soup: BeautifulSoup, ticker: str) -> dict:
    """
    Extracts company identity and headline metrics from the page header.

    Sources:
    - Company name: h1 tag
    - Sector: section#peers p.sub a[title="Sector"]
    - BSE/NSE codes: div#top .company-links anchors
    - Price + change: div#top price flex div and span.up/span.down
    - Market cap, 52W high/low, face value, dividend yield: ul#top-ratios

    Args:
        soup:   Parsed HTML of the Screener company page.
        ticker: Ticker symbol used in error messages.

    Returns:
        dict with keys: name, sector, bse_code, nse_code, current_price,
        price_change_pct, market_cap, high_52w, low_52w, face_value,
        dividend_yield.

    Raises:
        ValueError: if any required field cannot be extracted.
    """
    name_tag = soup.find("h1")
    if not name_tag:
        raise ValueError(
            f"Could not find company name (h1) for ticker '{ticker}'. "
            "Screener.in page structure may have changed."
        )
    name = name_tag.get_text(strip=True)

    sector_tag = soup.select_one('section#peers p.sub a[title="Sector"]')
    if not sector_tag:
        raise ValueError(
            f"Could not find sector link in peers section for ticker '{ticker}'. "
            "Screener.in page structure may have changed."
        )
    sector = sector_tag.get_text(strip=True)

    top_div = soup.find("div", id="top")
    if not top_div:
        raise ValueError(
            f"Could not find div#top for ticker '{ticker}'. "
            "Screener.in page structure may have changed."
        )

    bse_code: str | None = None
    nse_code: str | None = None
    for a in top_div.select(".company-links a"):
        href = a.get("href", "")
        span = a.find("span")
        if not span:
            continue
        tokens = span.get_text().split()
        if len(tokens) >= 2:
            code = tokens[-1]
        else:
            continue
        if "bseindia" in href:
            bse_code = code
        elif "nseindia" in href:
            nse_code = code

    price_div = top_div.select_one("div.font-size-18")
    if not price_div:
        raise ValueError(
            f"Could not find price div (div.font-size-18) for ticker '{ticker}'. "
            "Screener.in page structure may have changed."
        )
    price_span = price_div.find("span")
    if not price_span:
        raise ValueError(
            f"Could not find price span inside price div for ticker '{ticker}'."
        )
    current_price = _parse_number(price_span.get_text(), "current_price", ticker)

    change_tag = top_div.select_one("span.up, span.down")
    if not change_tag:
        raise ValueError(
            f"Could not find price change span (span.up or span.down) for ticker '{ticker}'. "
            "Screener.in page structure may have changed."
        )
    price_change_pct = _parse_number(change_tag.get_text(), "price_change_pct", ticker)

    ratios_ul = soup.find("ul", id="top-ratios")
    if not ratios_ul:
        raise ValueError(
            f"Could not find ul#top-ratios for ticker '{ticker}'. "
            "Screener.in page structure may have changed."
        )

    ratio_map: dict[str, str] = {}
    for li in ratios_ul.find_all("li"):
        name_span = li.find("span", class_="name")
        number_spans = li.find_all("span", class_="number")
        if name_span and number_spans:
            key = name_span.get_text(strip=True).lower()
            ratio_map[key] = number_spans[0].get_text(strip=True)
            if len(number_spans) > 1:
                ratio_map[key + "_low"] = number_spans[1].get_text(strip=True)

    def _r(key: str, field: str) -> float:
        for k, v in ratio_map.items():
            if key.lower() in k:
                return _parse_number(v, field, ticker)
        raise ValueError(
            f"Could not find '{key}' in ul#top-ratios for ticker '{ticker}'. "
            "Screener.in page structure may have changed."
        )

    market_cap     = _r("market cap", "market_cap")
    high_52w       = _r("high / low", "high_52w")
    low_52w        = _parse_number(
        ratio_map.get("high / low_low", ""),
        "low_52w", ticker
    ) if "high / low_low" in ratio_map else _r("low", "low_52w")
    face_value     = _r("face value", "face_value")
    dividend_yield = _r("dividend yield", "dividend_yield")

    return {
        "name":             name,
        "sector":           sector,
        "bse_code":         bse_code,
        "nse_code":         nse_code,
        "current_price":    current_price,
        "price_change_pct": price_change_pct,
        "market_cap":       market_cap,
        "high_52w":         high_52w,
        "low_52w":          low_52w,
        "face_value":       face_value,
        "dividend_yield":   dividend_yield,
    }


def _get_key_ratios(soup: BeautifulSoup, ticker: str, warehouse_id: str = "") -> dict:
    """
    Extracts headline valuation and return ratios from ul#top-ratios.

    PE, Book Value, ROCE, ROE always present. Debt/Equity and Current Ratio
    pulled from ul#top-ratios (when user has added them via Edit Ratios) or
    fall back to section#ratios table.

    Also calls /api/company/{warehouseId}/quick_ratios/ to fetch user-customised
    ratios (e.g. Pledged percentage, Industry PE, Debt to equity) that Screener
    injects via JS and are not in the static HTML. Merged into top_map so the
    same _top_or_table() logic picks them up automatically.

    Args:
        soup:         Parsed HTML of the Screener company page.
        ticker:       Ticker symbol used in error messages.
        warehouse_id: Screener's warehouse ID (data-warehouse-id on div#company-info).
                      If empty, the quick_ratios API call is skipped gracefully.

    Returns:
        dict with keys: pe, book_value, roce, roe (float),
        debt_to_equity, current_ratio, pledged_pct (float or None).

    Raises:
        ValueError: if the panels are missing or values cannot be parsed.
    """
    ratios_ul = soup.find("ul", id="top-ratios")
    if not ratios_ul:
        raise ValueError(
            f"Could not find ul#top-ratios for ticker '{ticker}'. "
            "Screener.in page structure may have changed."
        )

    top_map: dict[str, str] = {}
    for li in ratios_ul.find_all("li"):
        name_span = li.find("span", class_="name")
        value_span = li.find("span", class_="number")
        if name_span and value_span:
            top_map[name_span.get_text(strip=True).lower()] = value_span.get_text(strip=True)

    # Fetch user-customised quick ratios via the JS API endpoint.
    # Screener renders these client-side so they are absent from the static HTML.
    # On failure (no warehouse_id, network error, etc.) we skip silently — the
    # fallback logic below will read D/E from the ratios table instead.
    if warehouse_id:
        try:
            session = _get_authenticated_session()
            qr_resp = session.get(
                f"https://www.screener.in/api/company/{warehouse_id}/quick_ratios/",
                timeout=10,
            )
            if qr_resp.status_code == 200 and qr_resp.text.strip():
                qr_soup = BeautifulSoup(qr_resp.text, "lxml")
                for li in qr_soup.find_all("li"):
                    name_span = li.find("span", class_="name")
                    value_span = li.find("span", class_="number")
                    if name_span and value_span:
                        key = name_span.get_text(strip=True).lower()
                        top_map[key] = value_span.get_text(strip=True)
        except Exception:
            pass  # quick_ratios is enrichment — never fatal

    def _top(key: str, field: str) -> float:
        for k, v in top_map.items():
            if key.lower() in k:
                return _parse_number(v, field, ticker)
        raise ValueError(
            f"Could not find '{key}' in ul#top-ratios for ticker '{ticker}'. "
            "Screener.in page structure may have changed."
        )

    pe         = _top("stock p/e", "pe")
    book_value = _top("book value", "book_value")
    roce       = _top("roce", "roce")
    roe        = _top("roe", "roe")

    ratios_section = soup.find("section", id="ratios")
    if not ratios_section:
        raise ValueError(
            f"Could not find section#ratios for ticker '{ticker}'. "
            "Screener.in page structure may have changed."
        )
    ratios_rows = _extract_table_rows(ratios_section, "ratios", ticker)

    def _optional_latest(label: str, field: str) -> float | None:
        label_lower = label.lower()
        for key, values in ratios_rows.items():
            if key.lower().startswith(label_lower):
                return _parse_number_or_none(values[-1])
        return None

    # D/E and Current Ratio: check ul#top-ratios first (populated when user has
    # added them via Edit Ratios), then fall back to section#ratios table.
    def _top_or_table(top_key: str, table_label: str) -> float | None:
        for k, v in top_map.items():
            if top_key.lower() in k:
                return _parse_number_or_none(v)
        return _optional_latest(table_label, table_label)

    debt_to_equity = _top_or_table("debt to equity", "Debt to Equity")
    current_ratio  = _top_or_table("current ratio",  "Current Ratio")

    # Pledged percentage: only available via quick_ratios API (JS-rendered).
    # Will be None if user hasn't added it to their Edit Ratios panel.
    pledged_pct: float | None = None
    for k, v in top_map.items():
        if "pledged" in k:
            pledged_pct = _parse_number_or_none(v)
            break

    return {
        "pe":             pe,
        "book_value":     book_value,
        "roce":           roce,
        "roe":            roe,
        "debt_to_equity": debt_to_equity,
        "current_ratio":  current_ratio,
        "pledged_pct":    pledged_pct,
    }


def _get_pl_table(soup: BeautifulSoup, ticker: str) -> dict:
    """
    Extracts the annual Profit & Loss statement (10 years + TTM).

    Captures: Sales, Operating Profit, OPM %, Other Income, Interest,
    Depreciation, Net Profit, EPS, Dividend Payout %, Tax %.

    Args:
        soup:   Parsed HTML of the Screener company page.
        ticker: Ticker symbol used in error messages.

    Returns:
        dict with keys: units, years, sales, operating_profit, opm_pct,
        other_income, interest, depreciation, net_profit, eps,
        dividend_payout_pct, tax_pct — each a list[float|None].

    Raises:
        ValueError: if the section or any required row is missing.
    """
    section = soup.find("section", id="profit-loss")
    if not section:
        raise ValueError(
            f"Could not find section#profit-loss for ticker '{ticker}'. "
            "Screener.in page structure may have changed."
        )

    rows = _extract_table_rows(section, "profit-loss", ticker)
    # Screener renders columns oldest-first; reverse so index 0 = most recent.
    years = list(reversed(rows.get("__headers__", [])))
    if not years:
        raise ValueError(
            f"Could not extract year headers from P&L table for ticker '{ticker}'."
        )

    def _row(label: str) -> list[float | None]:
        raw = _require_row(rows, label, "profit-loss", ticker)
        return list(reversed([_parse_number_or_none(v) for v in raw[: len(years)]]))

    return {
        "units":               _extract_section_units(section, ticker),
        "years":               years,
        "sales":               _row("Sales"),
        "operating_profit":    _row("Operating Profit"),
        "opm_pct":             _row("OPM %"),
        "other_income":        _row("Other Income"),
        "interest":            _row("Interest"),
        "depreciation":        _row("Depreciation"),
        "net_profit":          _row("Net Profit"),
        "eps":                 _row("EPS"),
        "dividend_payout_pct": _row("Dividend Payout"),
        "tax_pct":             _row("Tax %"),
    }


def _get_growth_rates(soup: BeautifulSoup, ticker: str) -> dict:
    """
    Extracts compounded annual growth rates from the ranges-tables inside
    the profit-loss section.

    Screener renders four table.ranges-table elements below the main P&L:
    Compounded Sales Growth, Compounded Profit Growth, Stock Price CAGR,
    Return on Equity. We extract the first two.

    Args:
        soup:   Parsed HTML of the Screener company page.
        ticker: Ticker symbol used in error messages.

    Returns:
        dict with keys: sales_cagr_10yr, sales_cagr_5yr, sales_cagr_3yr,
        sales_ttm, profit_cagr_10yr, profit_cagr_5yr, profit_cagr_3yr,
        profit_ttm — all floats (percentage points).

    Raises:
        ValueError: if the growth rate tables or any row is missing.
    """
    section = soup.find("section", id="profit-loss")
    if not section:
        raise ValueError(
            f"Could not find section#profit-loss for ticker '{ticker}'."
        )

    ranges_tables = section.find_all("table", class_="ranges-table")
    if len(ranges_tables) < 2:
        raise ValueError(
            f"Could not find growth rate tables (table.ranges-table) for ticker '{ticker}'. "
            f"Found {len(ranges_tables)}, expected at least 2. "
            "Screener.in page structure may have changed."
        )

    def _find_table(header_text: str) -> BeautifulSoup:
        for t in ranges_tables:
            th = t.find("th")
            if th and header_text.lower() in th.get_text(strip=True).lower():
                return t
        raise ValueError(
            f"Could not find '{header_text}' table in profit-loss section "
            f"for ticker '{ticker}'. Screener.in page structure may have changed."
        )

    def _parse_ranges(table: BeautifulSoup, label: str) -> dict[str, float]:
        result: dict[str, float] = {}
        for tr in table.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) == 2:
                period = cells[0].get_text(strip=True).lower().rstrip(":")
                result[period] = _parse_number(
                    cells[1].get_text(strip=True), f"{label} {period}", ticker
                )
        return result

    sales  = _parse_ranges(_find_table("Compounded Sales Growth"),  "sales_cagr")
    profit = _parse_ranges(_find_table("Compounded Profit Growth"), "profit_cagr")

    def _get(d: dict, key: str, field: str) -> float:
        for k, v in d.items():
            if key in k:
                return v
        raise ValueError(
            f"Could not find period '{key}' in growth table for "
            f"field '{field}', ticker '{ticker}'."
        )

    return {
        "sales_cagr_10yr":  _get(sales,  "10",  "sales_cagr_10yr"),
        "sales_cagr_5yr":   _get(sales,  "5",   "sales_cagr_5yr"),
        "sales_cagr_3yr":   _get(sales,  "3",   "sales_cagr_3yr"),
        "sales_ttm":        _get(sales,  "ttm", "sales_ttm"),
        "profit_cagr_10yr": _get(profit, "10",  "profit_cagr_10yr"),
        "profit_cagr_5yr":  _get(profit, "5",   "profit_cagr_5yr"),
        "profit_cagr_3yr":  _get(profit, "3",   "profit_cagr_3yr"),
        "profit_ttm":       _get(profit, "ttm", "profit_ttm"),
    }


def _get_balance_sheet(
    soup: BeautifulSoup,
    ticker: str,
    company_id: str,
    is_consolidated: bool,
) -> dict:
    """
    Extracts the annual Balance Sheet (10 years) plus sub-row schedules.

    Base rows: Equity Capital, Reserves, Borrowings, Other Liabilities,
    Total Liabilities, Fixed Assets, CWIP, Investments, Other Assets,
    Total Assets.

    Schedule sub-rows (fetched via API):
    - Other Assets schedule: Inventories, Trade Receivables, Cash Equivalents
    - Other Liabilities schedule: Trade Payables
    - Borrowings schedule: Long Term Borrowings, Short Term Borrowings
    - Fixed Assets schedule: Gross Block, Accumulated Depreciation

    Args:
        soup:           Parsed HTML of the Screener company page.
        ticker:         Ticker symbol used in error messages.
        company_id:     Screener internal company ID for the schedule API.
        is_consolidated: Whether to request consolidated schedule data.

    Returns:
        dict with keys: units, years, and one list[float|None] per line item.
        Schedule fields are also lists aligned to the same years list.

    Raises:
        ValueError: if the section or any required row is missing.
    """
    section = soup.find("section", id="balance-sheet")
    if not section:
        raise ValueError(
            f"Could not find section#balance-sheet for ticker '{ticker}'. "
            "Screener.in page structure may have changed."
        )

    rows = _extract_table_rows(section, "balance-sheet", ticker)
    # Screener renders columns oldest-first; reverse so index 0 = most recent.
    years = list(reversed(rows.get("__headers__", [])))
    if not years:
        raise ValueError(
            f"Could not extract year headers from balance sheet for ticker '{ticker}'."
        )

    def _row(label: str) -> list[float | None]:
        raw = _require_row(rows, label, "balance-sheet", ticker)
        return list(reversed([_parse_number_or_none(v) for v in raw[: len(years)]]))

    # Fetch schedule sub-rows via API
    other_assets_sched = _fetch_schedule(company_id, "Other Assets",      "balance-sheet", is_consolidated)
    other_liab_sched   = _fetch_schedule(company_id, "Other Liabilities",  "balance-sheet", is_consolidated)
    borrowings_sched   = _fetch_schedule(company_id, "Borrowings",         "balance-sheet", is_consolidated)
    fixed_assets_sched = _fetch_schedule(company_id, "Fixed Assets",       "balance-sheet", is_consolidated)

    def _sched(sched_data: dict, label: str) -> list[float | None]:
        return _schedule_series(sched_data, label, years)

    return {
        "units":                  _extract_section_units(section, ticker),
        "years":                  years,
        # Base balance sheet rows
        "equity_capital":         _row("Equity Capital"),
        "reserves":               _row("Reserves"),
        "borrowings":             _row("Borrowings"),
        "other_liabilities":      _row("Other Liabilities"),
        "total_liabilities":      _row("Total Liabilities"),
        "fixed_assets":           _row("Fixed Assets"),
        "cwip":                   _row("CWIP"),
        "investments":            _row("Investments"),
        "other_assets":           _row("Other Assets"),
        "total_assets":           _row("Total Assets"),
        # Other Assets schedule: current asset components
        "inventories":            _sched(other_assets_sched, "Inventories"),
        "trade_receivables":      _sched(other_assets_sched, "Trade receivables"),
        "cash_equivalents":       _sched(other_assets_sched, "Cash Equivalents"),
        # Other Liabilities schedule: current liability component
        "trade_payables":         _sched(other_liab_sched, "Trade Payables"),
        # Borrowings schedule: debt structure (lease liabilities included to match
        # Screener's D/E definition: total debt = LT + ST + lease liabilities)
        "long_term_borrowings":   _sched(borrowings_sched, "Long term Borrowings"),
        "short_term_borrowings":  _sched(borrowings_sched, "Short term Borrowings"),
        "lease_liabilities":      _sched(borrowings_sched, "Lease Liabilities"),
        # Fixed Assets schedule: gross/net block
        "gross_block":            _sched(fixed_assets_sched, "Gross Block"),
        "accumulated_depreciation": _sched(fixed_assets_sched, "Accumulated Depreciation"),
    }


def _get_cash_flow(
    soup: BeautifulSoup,
    ticker: str,
    company_id: str,
    is_consolidated: bool,
) -> dict:
    """
    Extracts the annual Cash Flow statement (10 years) plus investing
    sub-row schedule to get explicit CapEx.

    Base rows: Cash from Operating, Investing, Financing, Net Cash Flow.

    Schedule sub-rows (fetched via API):
    - Investing schedule: Fixed Assets Purchased (CapEx), Fixed Assets Sold,
      Investments Purchased, Investments Sold

    CapEx = Fixed assets purchased (sign-adjusted — Screener reports it as
    negative outflow, so we store as-is; signals.py interprets the sign).

    Args:
        soup:           Parsed HTML of the Screener company page.
        ticker:         Ticker symbol used in error messages.
        company_id:     Screener internal company ID for the schedule API.
        is_consolidated: Whether to request consolidated schedule data.

    Returns:
        dict with keys: units, years, operating, investing, financing,
        net_cash_flow, capex (negative = outflow), fixed_assets_sold,
        investments_purchased, investments_sold.

    Raises:
        ValueError: if the section or any required row is missing.
    """
    section = soup.find("section", id="cash-flow")
    if not section:
        raise ValueError(
            f"Could not find section#cash-flow for ticker '{ticker}'. "
            "Screener.in page structure may have changed."
        )

    rows = _extract_table_rows(section, "cash-flow", ticker)
    # Screener renders columns oldest-first; reverse so index 0 = most recent.
    years = list(reversed(rows.get("__headers__", [])))
    if not years:
        raise ValueError(
            f"Could not extract year headers from cash flow for ticker '{ticker}'."
        )

    def _row(label: str) -> list[float | None]:
        raw = _require_row(rows, label, "cash-flow", ticker)
        return list(reversed([_parse_number_or_none(v) for v in raw[: len(years)]]))

    # Fetch investing sub-schedule for explicit CapEx
    investing_sched = _fetch_schedule(company_id, "Cash from Investing Activity", "cash-flow", is_consolidated)

    def _sched(label: str) -> list[float | None]:
        return _schedule_series(investing_sched, label, years)

    return {
        "units":                  _extract_section_units(section, ticker),
        "years":                  years,
        "operating":              _row("Cash from Operating"),
        "investing":              _row("Cash from Investing"),
        "financing":              _row("Cash from Financing"),
        "net_cash_flow":          _row("Net Cash Flow"),
        # CapEx: "Fixed assets purchased" — negative value means cash outflow
        "capex":                  _sched("Fixed assets purchased"),
        "fixed_assets_sold":      _sched("Fixed assets sold"),
        "investments_purchased":  _sched("Investments purchased"),
        "investments_sold":       _sched("Investments sold"),
    }


def _get_ratios_table(soup: BeautifulSoup, ticker: str) -> dict:
    """
    Extracts the financial efficiency ratios table (10 years).

    Captures: Debtor Days, Inventory Days, Days Payable,
    Cash Conversion Cycle, Working Capital Days, ROCE.

    Args:
        soup:   Parsed HTML of the Screener company page.
        ticker: Ticker symbol used in error messages.

    Returns:
        dict with keys: units, years, and one list[float|None] per ratio.

    Raises:
        ValueError: if the section or any required row is missing.
    """
    section = soup.find("section", id="ratios")
    if not section:
        raise ValueError(
            f"Could not find section#ratios for ticker '{ticker}'. "
            "Screener.in page structure may have changed."
        )

    rows = _extract_table_rows(section, "ratios", ticker)
    # Screener renders columns oldest-first; reverse so index 0 = most recent.
    years = list(reversed(rows.get("__headers__", [])))
    if not years:
        raise ValueError(
            f"Could not extract year headers from ratios table for ticker '{ticker}'."
        )

    def _row(label: str) -> list[float | None]:
        raw = _require_row(rows, label, "ratios", ticker)
        return list(reversed([_parse_number_or_none(v) for v in raw[: len(years)]]))

    return {
        "units":                 _extract_section_units(section, ticker),
        "years":                 years,
        "debtor_days":           _row("Debtor Days"),
        "inventory_days":        _row("Inventory Days"),
        "days_payable":          _row("Days Payable"),
        "cash_conversion_cycle": _row("Cash Conversion Cycle"),
        "working_capital_days":  _row("Working Capital Days"),
        "roce":                  _row("ROCE"),
    }


def _get_quarterly_results(soup: BeautifulSoup, ticker: str) -> dict:
    """
    Extracts the quarterly results table (most recent quarters available).

    Captures per quarter: Sales, Operating Profit, OPM %, Net Profit, EPS.

    Args:
        soup:   Parsed HTML of the Screener company page.
        ticker: Ticker symbol used in error messages.

    Returns:
        dict with keys: quarters (list[str]), units, sales, operating_profit,
        opm_pct, net_profit, eps — each a list[float|None].

    Raises:
        ValueError: if the section or any required row is missing.
    """
    section = soup.find("section", id="quarters")
    if not section:
        raise ValueError(
            f"Could not find section#quarters for ticker '{ticker}'. "
            "Screener.in page structure may have changed."
        )

    rows = _extract_table_rows(section, "quarters", ticker)
    quarters = rows.get("__headers__", [])
    if not quarters:
        raise ValueError(
            f"Could not extract quarter headers from quarterly results for ticker '{ticker}'."
        )

    def _row(label: str) -> list[float | None]:
        raw = _require_row(rows, label, "quarters", ticker)
        return [_parse_number_or_none(v) for v in raw[: len(quarters)]]

    return {
        "units":            _extract_section_units(section, ticker),
        "quarters":         quarters,
        "sales":            _row("Sales"),
        "operating_profit": _row("Operating Profit"),
        "opm_pct":          _row("OPM %"),
        "net_profit":       _row("Net Profit"),
        "eps":              _row("EPS"),
    }


def _get_shareholding(soup: BeautifulSoup, ticker: str) -> dict:
    """
    Extracts the shareholding pattern — latest quarter and up to 8 quarters
    of history for trend analysis.

    Scopes to div#quarterly-shp. Captures Promoter %, FII %, DII %,
    Public %, and Pledged % for each quarter.

    Pledged %: 0.0 when the row is absent (Screener omits it when 0%).

    Args:
        soup:   Parsed HTML of the Screener company page.
        ticker: Ticker symbol used in error messages.

    Returns:
        dict with keys:
            quarter (str)        — latest quarter label
            promoter_pct (float) — latest promoter holding
            fii_pct (float)      — latest FII holding
            dii_pct (float)      — latest DII holding
            public_pct (float)   — latest public holding
            pledged_pct (float)  — latest pledged % (0.0 if absent)
            history (dict)       — {quarter_label: {promoter, fii, dii, public, pledged}}
                                   for all available quarters, newest-first

    Raises:
        ValueError: if the section or any required row is missing.
    """
    section = soup.find("section", id="shareholding")
    if not section:
        raise ValueError(
            f"Could not find section#shareholding for ticker '{ticker}'. "
            "Screener.in page structure may have changed."
        )

    quarterly_div = section.find("div", id="quarterly-shp")
    if not quarterly_div:
        raise ValueError(
            f"Could not find div#quarterly-shp in shareholding section "
            f"for ticker '{ticker}'. Screener.in page structure may have changed."
        )

    rows = _extract_table_rows(quarterly_div, "shareholding", ticker)
    quarters = rows.get("__headers__", [])
    if not quarters:
        raise ValueError(
            f"Could not extract quarter headers from shareholding table for ticker '{ticker}'."
        )

    latest_idx = -1
    latest_quarter = quarters[-1]

    def _pct(label: str) -> list[float | None]:
        """Return full time-series for a shareholding row."""
        raw = _require_row(rows, label, "shareholding", ticker)
        return [_parse_number_or_none(v) for v in raw[: len(quarters)]]

    promoter_series = _pct("Promoters")
    fii_series      = _pct("FIIs")
    dii_series      = _pct("DIIs")
    public_series   = _pct("Public")

    # Pledged % row absent = 0% pledged for all periods
    pledged_series: list[float | None] = [0.0] * len(quarters)
    for key, values in rows.items():
        if key.lower().startswith("pledged"):
            pledged_series = [_parse_number_or_none(v) for v in values[: len(quarters)]]
            break

    # Build history dict keyed by quarter label (newest quarter last in list → reverse)
    history: dict[str, dict] = {}
    for i, q in enumerate(quarters):
        history[q] = {
            "promoter_pct": promoter_series[i],
            "fii_pct":      fii_series[i],
            "dii_pct":      dii_series[i],
            "public_pct":   public_series[i],
            "pledged_pct":  pledged_series[i] if pledged_series[i] is not None else 0.0,
        }

    return {
        "quarter":      latest_quarter,
        "promoter_pct": promoter_series[latest_idx] or 0.0,
        "fii_pct":      fii_series[latest_idx]      or 0.0,
        "dii_pct":      dii_series[latest_idx]      or 0.0,
        "public_pct":   public_series[latest_idx]   or 0.0,
        "pledged_pct":  pledged_series[latest_idx]  if pledged_series[latest_idx] is not None else 0.0,
        "history":      history,
    }


def _get_pros_cons(soup: BeautifulSoup, ticker: str) -> dict:
    """
    Extracts Screener's machine-generated Pros and Cons lists.

    Args:
        soup:   Parsed HTML of the Screener company page.
        ticker: Ticker symbol used in error messages.

    Returns:
        dict with keys: pros (list[str]), cons (list[str]).

    Raises:
        ValueError: if div.pros or div.cons container is not found.
    """
    pros_div = soup.select_one("div.pros")
    cons_div = soup.select_one("div.cons")

    if pros_div is None:
        raise ValueError(
            f"Could not find div.pros container for ticker '{ticker}'. "
            "Screener.in page structure may have changed."
        )
    if cons_div is None:
        raise ValueError(
            f"Could not find div.cons container for ticker '{ticker}'. "
            "Screener.in page structure may have changed."
        )

    pros = [li.get_text(strip=True) for li in pros_div.find_all("li")]
    cons = [li.get_text(strip=True) for li in cons_div.find_all("li")]

    return {"pros": pros, "cons": cons}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_company_data(ticker: str) -> dict:
    """
    Fetches and returns complete fundamental data for a given NSE/BSE ticker
    from Screener.in.

    This is the only function external modules should call. It orchestrates
    all private helpers, tries consolidated financials first, and falls back
    to standalone if needed. Includes schedule sub-row API calls for granular
    line items (CapEx, inventories, trade payables, etc.).

    Every field in the output is guaranteed to be present and fully populated.
    If any field cannot be extracted, this function raises immediately with a
    descriptive error — never returns partial data.

    Args:
        ticker: NSE or BSE stock symbol, e.g. "RELIANCE" or "INFY".
                Case-insensitive — normalised to uppercase internally.

    Returns:
        dict with keys:
            is_consolidated (bool)
            currency (str)
            header (dict)         — name, sector, codes, price, market cap, etc.
            header_units (dict)   — unit per header/key_ratios field
            key_ratios (dict)     — pe, book_value, roce, roe, debt_to_equity,
                                    current_ratio
            pl_table (dict)       — 10-year annual P&L + tax_pct
            growth_rates (dict)   — sales and profit CAGR at 3/5/10yr and TTM
            balance_sheet (dict)  — 10-year balance sheet + inventories,
                                    trade_receivables, cash_equivalents,
                                    trade_payables, long/short_term_borrowings,
                                    gross_block, accumulated_depreciation
            cash_flow (dict)      — 10-year cash flow + capex,
                                    fixed_assets_sold, investments_purchased,
                                    investments_sold
            ratios_table (dict)   — 10-year efficiency ratios
            quarterly (dict)      — recent quarterly results
            shareholding (dict)   — latest + full history of shareholding pattern
            pros_cons (dict)      — Screener's generated pros and cons

    Raises:
        ValueError:  if ticker not found or any required field is missing.
        RuntimeError: if Screener.in authentication fails.
        requests.exceptions.RequestException: on network errors.
    """
    ticker = ticker.strip().upper()

    soup, is_consolidated, company_id, warehouse_id = _fetch_page(ticker)

    pl_section = soup.find("section", id="profit-loss")
    if not pl_section:
        raise ValueError(
            f"Could not find section#profit-loss to determine currency for ticker '{ticker}'."
        )
    pl_units     = _extract_section_units(pl_section, ticker)
    top_currency = pl_units["currency"]

    return {
        "is_consolidated": is_consolidated,
        "currency":        top_currency,
        "header":          _get_company_header(soup, ticker),
        "header_units":    _HEADER_UNITS,
        "key_ratios":      _get_key_ratios(soup, ticker, warehouse_id),
        "pl_table":        _get_pl_table(soup, ticker),
        "growth_rates":    _get_growth_rates(soup, ticker),
        "balance_sheet":   _get_balance_sheet(soup, ticker, company_id, is_consolidated),
        "cash_flow":       _get_cash_flow(soup, ticker, company_id, is_consolidated),
        "ratios_table":    _get_ratios_table(soup, ticker),
        "quarterly":       _get_quarterly_results(soup, ticker),
        "shareholding":    _get_shareholding(soup, ticker),
        "pros_cons":       _get_pros_cons(soup, ticker),
    }
