# ============================================================
# FILE: src/api.py
# PURPOSE: FastAPI backend. Exposes:
#            GET  /health
#            POST /analyze    — scrape + signals + news + deep brief (v2)
#            POST /chat       — conversational follow-up (DeepSeek, no re-fetch)
#            DELETE /cache/{ticker}
#            GET  /history/{ticker}
#            GET  /watchlist
#            POST /watchlist
#            DELETE /watchlist/{ticker}
# INPUT:   POST /analyze body: {"ticker": str, "thesis": str (optional)}
#          POST /chat    body: {"ticker": str, "question": str,
#                               "brief": dict, "signals_summary": dict}
# OUTPUT:  JSON with source, scraped_at, data, signals, news, brief, filings
# DEPENDS: fastapi, uvicorn, src/scraper.py, src/signals.py, src/news.py,
#          src/cache.py, src/brief.py, src/filings.py, src/memory.py,
#          .env (OPENAI_API_KEY, DEEPSEEK_API_KEY, SCREENER_EMAIL,
#                SCREENER_PASSWORD, NEWS_API_KEY)
# ============================================================

import logging
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

import requests as req_lib
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel, ValidationError
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from src.brief import generate_brief, generate_chat_reply
from src.cache import DB_PATH, get_cached, init_db, set_cached
from src.telemetry import get_stats, init_telemetry_table
from src.filings import fetch_filings
from src.memory import (
    add_to_watchlist,
    get_history,
    get_watchlist,
    init_memory_tables,
    remove_from_watchlist,
    save_analysis,
)
from src.news import fetch_news
from src.scraper import fetch_company_data
from src.signals import compute_signals

load_dotenv()

# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------
_RATE_LIMIT = os.getenv("ANALYZE_RATE_LIMIT", "20/minute")
limiter = Limiter(key_func=get_remote_address, default_limits=[])

# ---------------------------------------------------------------------------
# Auth — static API key via X-API-Key header
# ---------------------------------------------------------------------------
_API_KEY = os.getenv("FINTEL_API_KEY") or None
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def _verify_key(key: str = Depends(_api_key_header)) -> None:
    """
    FastAPI dependency that enforces API key auth when FINTEL_API_KEY is set.

    Args:
        key: Value of the X-API-Key request header (None if absent).

    Raises:
        HTTPException 401 if FINTEL_API_KEY is set and the header is wrong/missing.
    """
    if _API_KEY and key != _API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


# ---------------------------------------------------------------------------
# Startup / shutdown lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager.

    On startup: initialises the SQLite cache database and memory tables.
    On shutdown: nothing to clean up — SQLite connections are per-request.
    """
    init_db()
    init_memory_tables()
    init_telemetry_table()
    yield


app = FastAPI(
    title="Fintel API",
    description="AI-powered investment research for Indian stocks.",
    version="7.0.0",
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    """Request body for POST /analyze."""
    ticker: str
    thesis: Optional[str] = ""


class ChatRequest(BaseModel):
    """Request body for POST /chat."""
    ticker: str
    question: str
    brief: dict
    signals_summary: dict


class WatchlistAddRequest(BaseModel):
    """Request body for POST /watchlist."""
    ticker: str
    note: Optional[str] = ""


# ---------------------------------------------------------------------------
# Endpoints — health
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    """
    Health check endpoint.

    Returns:
        {"status": "ok"} — always, as long as the server is running.
    """
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Endpoints — telemetry
# ---------------------------------------------------------------------------

@app.get("/telemetry", dependencies=[Depends(_verify_key)])
def telemetry():
    """
    Returns aggregated LLM cost and latency telemetry.

    Returns:
        dict with keys:
            total_calls    (int)   — all-time call count
            total_cost_usd (float) — all-time total cost in USD
            avg_latency_ms (float) — all-time average latency in ms
            by_model       (list)  — per-model aggregates
            by_type        (list)  — per-call-type aggregates
            recent         (list)  — last 50 individual call rows
    """
    return get_stats()


# ---------------------------------------------------------------------------
# Endpoints — cache management
# ---------------------------------------------------------------------------

@app.delete("/cache/{ticker}", dependencies=[Depends(_verify_key)])
def clear_cache(ticker: str):
    """
    Deletes the cached entry for a ticker so the next /analyze call
    fetches fresh data from Screener.in and re-runs the full pipeline.

    Args:
        ticker: NSE/BSE symbol in the URL path, e.g. /cache/RELIANCE.

    Returns:
        {"cleared": True, "ticker": "RELIANCE"} on success.

    Raises:
        404: if there is no cached entry for the ticker.
    """
    ticker = ticker.strip().upper()
    with sqlite3.connect(DB_PATH) as conn:
        deleted = conn.execute(
            "DELETE FROM cache WHERE ticker = ?", (ticker,)
        ).rowcount
        conn.commit()
    if deleted == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No cached entry found for '{ticker}'.",
        )
    return {"cleared": True, "ticker": ticker}


# ---------------------------------------------------------------------------
# Endpoints — analysis
# ---------------------------------------------------------------------------

@app.post("/analyze", dependencies=[Depends(_verify_key)])
@limiter.limit(_RATE_LIMIT)
def analyze(request: Request, body: AnalyzeRequest):
    """
    Main analysis endpoint. Runs the full v2 pipeline:
      1. Scrape fundamental data from Screener.in
      2. Compute quantitative signals in Python (Piotroski, DuPont, DCF, etc.)
      3. Fetch recent news and classify sentiment via gpt-4o-mini
      4. Generate a single deep research brief via DeepSeek V3 (1 call)
      5. Fetch and summarise recent BSE corporate filings via gpt-4o-mini
      6. Persist the result to analyst_history

    Checks the SQLite cache first (24h TTL). Cache hits skip steps 1–5.

    Args:
        body: AnalyzeRequest with fields "ticker" and optional "thesis".

    Returns:
        JSON dict with keys:
            source           (str)   — "cache" or "live"
            scraped_at       (str)   — UTC ISO-8601 timestamp
            cache_age_hours  (float) — hours since data was scraped (0.0 for live)
            data             (dict)  — full output of fetch_company_data()
            signals          (dict)  — output of compute_signals()
            news             (dict)  — output of fetch_news(), or None
            brief            (dict)  — deep research brief from DeepSeek
            filings          (dict)  — BSE announcements + summaries, or None

    Raises:
        400: ticker not found or data unavailable.
        422: scraper returned bad data (ValidationError).
        503: Screener.in auth failed or network error.
    """
    ticker = body.ticker.strip().upper()
    thesis = (body.thesis or "").strip()

    # --- Cache hit ---
    cached = get_cached(ticker)
    if cached is not None:
        cached_data, fetched_at_str = cached
        fetched_at = datetime.fromisoformat(fetched_at_str)
        age_hours = round((datetime.now(timezone.utc) - fetched_at).total_seconds() / 3600, 1)
        try:
            save_analysis(ticker, cached_data)
        except Exception as e:
            logger.warning("Memory write failed for '%s': %s", ticker, e)
        return {"source": "cache", "scraped_at": fetched_at_str, "cache_age_hours": age_hours, **cached_data}

    # --- Step 1: Scrape Screener.in ---
    try:
        company_data = fetch_company_data(ticker)
    except ValueError as e:
        logger.warning("Scraper validation error for '%s': %s", ticker, e)
        raise HTTPException(status_code=400, detail=f"Invalid ticker or data unavailable for '{ticker}'.")
    except RuntimeError as e:
        logger.warning("Scraper runtime error for '%s': %s", ticker, e)
        raise HTTPException(status_code=503, detail="Data fetch failed — check the ticker and try again.")
    except req_lib.exceptions.RequestException as e:
        logger.warning("Scraper network error for '%s': %s", ticker, e)
        raise HTTPException(status_code=503, detail="Network error while fetching data — please try again.")

    scraped_at = datetime.now(timezone.utc).isoformat()

    # --- Step 2: Compute quantitative signals ---
    try:
        signals = compute_signals(company_data)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # --- Step 3: Fetch news (non-blocking) ---
    news = None
    try:
        news = fetch_news(signals.meta.name, ticker)
    except Exception as e:
        logger.warning("News fetch failed for '%s': %s", ticker, e)

    # --- Step 4: Generate deep research brief (1 LLM call) ---
    # Per CLAUDE.md Rule 5 (agent exception): LLM failures return {"error": ...}
    # and never raise — the pipeline continues with whatever was produced.
    brief = generate_brief(signals, news, thesis, ticker=ticker)

    # --- Step 5: Fetch BSE filings (non-blocking) ---
    filings = None
    bse_code = company_data.get("header", {}).get("bse_code")
    if bse_code:
        try:
            filings = fetch_filings(bse_code)
        except Exception as e:
            logger.warning("Filings fetch failed for '%s' (BSE %s): %s", ticker, bse_code, e)
    else:
        logger.warning("No BSE code found for '%s' — skipping filings.", ticker)

    result = {
        "scraped_at":      scraped_at,
        "cache_age_hours": 0.0,
        "data":            company_data,
        "signals":         signals.model_dump(),
        "news":            news,
        "brief":           brief,
        "filings":         filings,
    }

    # --- Cache write ---
    try:
        set_cached(ticker, result)
    except Exception as e:
        logger.warning("Cache write failed for '%s': %s", ticker, e)

    # --- Step 6: Persist to analyst_history ---
    try:
        save_analysis(ticker, result)
    except Exception as e:
        logger.warning("Memory write failed for '%s': %s", ticker, e)

    return {"source": "live", **result}


# ---------------------------------------------------------------------------
# Endpoints — chat follow-up
# ---------------------------------------------------------------------------

@app.post("/chat", dependencies=[Depends(_verify_key)])
@limiter.limit(_RATE_LIMIT)
def chat(request: Request, body: ChatRequest):
    """
    Conversational follow-up endpoint. Answers a question using the already-
    generated brief and signals — no re-scraping or re-fetching.

    One DeepSeek V3 call per question.

    Args:
        body: ChatRequest with fields:
            ticker          (str)  — for logging only
            question        (str)  — user's follow-up question
            brief           (dict) — the full brief from a prior /analyze call
            signals_summary (dict) — the signals dict from the same call

    Returns:
        {"answer": str}
    """
    answer = generate_chat_reply(
        question=body.question,
        brief=body.brief,
        signals_summary=body.signals_summary,
    )
    return {"answer": answer}


# ---------------------------------------------------------------------------
# Endpoints — memory: history
# ---------------------------------------------------------------------------

@app.get("/history/{ticker}", dependencies=[Depends(_verify_key)])
def history(ticker: str):
    """
    Returns all historical analysis runs for a ticker, newest first.

    Args:
        ticker: NSE/BSE symbol in the URL path, e.g. /history/RELIANCE.

    Returns:
        {"ticker": str, "runs": list[dict]}
    """
    ticker = ticker.strip().upper()
    runs = get_history(ticker)
    return {"ticker": ticker, "runs": runs}


# ---------------------------------------------------------------------------
# Endpoints — memory: watchlist
# ---------------------------------------------------------------------------

@app.get("/watchlist", dependencies=[Depends(_verify_key)])
def list_watchlist():
    """
    Returns all tickers currently in the watchlist, alphabetically.

    Returns:
        {"watchlist": list[dict]} — each item has ticker, added_at, note.
    """
    return {"watchlist": get_watchlist()}


@app.post("/watchlist", dependencies=[Depends(_verify_key)])
def add_watchlist(body: WatchlistAddRequest):
    """
    Adds a ticker to the watchlist (or updates its note if already present).

    Args:
        body: WatchlistAddRequest with fields "ticker" and optional "note".

    Returns:
        {"added": True, "ticker": str}
    """
    ticker = body.ticker.strip().upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker must not be empty.")
    add_to_watchlist(ticker, body.note or "")
    return {"added": True, "ticker": ticker}


@app.delete("/watchlist/{ticker}", dependencies=[Depends(_verify_key)])
def delete_watchlist(ticker: str):
    """
    Removes a ticker from the watchlist.

    Args:
        ticker: NSE/BSE symbol in the URL path, e.g. /watchlist/RELIANCE.

    Returns:
        {"removed": True, "ticker": str} on success.

    Raises:
        404: if the ticker is not in the watchlist.
    """
    ticker = ticker.strip().upper()
    removed = remove_from_watchlist(ticker)
    if not removed:
        raise HTTPException(
            status_code=404,
            detail=f"'{ticker}' is not in the watchlist.",
        )
    return {"removed": True, "ticker": ticker}
