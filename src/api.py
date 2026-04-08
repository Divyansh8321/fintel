# ============================================================
# FILE: src/api.py
# PURPOSE: FastAPI backend that ties together the scraper,
#          signals, news, five analyst agents, synthesis layer,
#          BSE filings, and memory (Phase 6).
#          Exposes GET /health, POST /analyze,
#          DELETE /cache/{ticker}, GET /history/{ticker},
#          GET /watchlist, POST /watchlist,
#          DELETE /watchlist/{ticker}.
# INPUT:   POST /analyze body: {"ticker": str}
#          POST /watchlist body: {"ticker": str, "note": str}
# OUTPUT:  JSON dict with scraped data + signals + news + analyst_notes
#          + synthesis + filings, plus a "source" field ("cache" or "live")
# DEPENDS: fastapi, uvicorn, src/scraper.py, src/signals.py,
#          src/news.py, src/cache.py, src/agents/*, src/synthesis.py,
#          src/filings.py, src/memory.py,
#          .env (OPENAI_API_KEY, SCREENER_EMAIL, SCREENER_PASSWORD, NEWS_API_KEY)
# ============================================================

import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import requests as req_lib
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from openai import OpenAIError
from pydantic import BaseModel, ValidationError

from src.agents.contrarian import analyze as contrarian_analyze
from src.agents.growth import analyze as growth_analyze
from src.agents.momentum import analyze as momentum_analyze
from src.agents.quality import analyze as quality_analyze
from src.agents.value import analyze as value_analyze
from src.cache import DB_PATH, get_cached, init_db, set_cached
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
from src.synthesis import synthesise

load_dotenv()


# ---------------------------------------------------------------------------
# Startup / shutdown lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager.

    On startup: initialises the SQLite cache database and the two new
    memory tables (analyst_history, watchlist). All calls are idempotent —
    safe to run on every restart.
    On shutdown: nothing to clean up — SQLite connections are per-request.
    """
    init_db()
    init_memory_tables()
    yield


app = FastAPI(
    title="Fintel API",
    description="AI-powered investment research for Indian stocks.",
    version="6.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    """Request body for POST /analyze."""
    ticker: str


class WatchlistAddRequest(BaseModel):
    """Request body for POST /watchlist."""
    ticker: str
    note: Optional[str] = ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run_agents_parallel(signals, news: dict | None) -> list[dict]:
    """
    Run all five analyst agents in parallel using a thread pool.

    Each agent makes one GPT-4o call. Running them concurrently cuts total
    latency from ~5×agent_time to ~1×agent_time (the slowest agent).

    Per CLAUDE.md Rule 5 (agent exception): if any agent raises, its error
    is captured in the returned dict — never propagated. The pipeline
    continues with however many agents succeeded.

    Args:
        signals: SignalsModel instance from compute_signals().
        news:    News + sentiment dict from fetch_news(), or None.

    Returns:
        List of 5 dicts — one per agent. Each either has the full agent
        schema (lens, score, thesis, key_signals, risks, action) or
        {"lens": "<name>", "error": "<message>"}.
    """
    # Map lens name → agent function for clean parallel dispatch
    agent_fns = {
        "value":      value_analyze,
        "growth":     growth_analyze,
        "quality":    quality_analyze,
        "contrarian": contrarian_analyze,
        "momentum":   momentum_analyze,
    }

    notes = {}

    # Run all 5 agents concurrently — each blocks on an OpenAI API call
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(fn, signals, news): lens
            for lens, fn in agent_fns.items()
        }
        for future in as_completed(futures):
            lens = futures[future]
            try:
                notes[lens] = future.result()
            except Exception as e:
                # Should not reach here (agents catch internally), but be safe
                notes[lens] = {"lens": lens, "error": str(e)}

    # Return in a consistent order matching CLAUDE.md weights table
    return [notes[lens] for lens in ("value", "growth", "quality", "contrarian", "momentum")]


# ---------------------------------------------------------------------------
# Endpoints — cache management
# ---------------------------------------------------------------------------

@app.delete("/cache/{ticker}")
def clear_cache(ticker: str):
    """
    Deletes the cached entry for a ticker so the next /analyze call
    fetches fresh data from Screener.in and re-runs the full pipeline.

    Args:
        ticker: NSE/BSE stock symbol in the URL path, e.g. /cache/RELIANCE.

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
# Endpoints — analysis
# ---------------------------------------------------------------------------

@app.post("/analyze")
def analyze(body: AnalyzeRequest):
    """
    Main analysis endpoint. Runs the full Phase 5 pipeline + Phase 6 memory:
      1. Scrape fundamental data from Screener.in
      2. Compute quantitative signals in Python (Piotroski, DuPont, DCF, etc.)
      3. Fetch recent news and classify sentiment via gpt-4o-mini
      4. Run 5 analyst agents in parallel (each makes 1 GPT-4o call)
      5. Synthesise the 5 notes into a consensus verdict (1 GPT-4o call)
      6. Fetch and summarise recent BSE corporate filings via gpt-4o-mini
      7. Persist the result to analyst_history (Phase 6)

    Checks the SQLite cache first. Cache hits skip steps 1–6 but still
    record a history entry so every "view" is tracked.
    Total GPT-4o/mini calls on a cache miss: 6 agents/synthesis + up to 5 filing summaries.

    Args:
        body: AnalyzeRequest with field "ticker" (NSE/BSE symbol).

    Returns:
        JSON dict with keys:
            source           (str)   — "cache" or "live"
            scraped_at       (str)   — UTC ISO-8601 timestamp of when data was scraped
            cache_age_hours  (float) — hours since data was scraped (0.0 for live)
            data             (dict)  — full output of fetch_company_data()
            signals          (dict)  — output of compute_signals()
            news             (dict)  — output of fetch_news(), or None
            analyst_notes    (list)  — list of 5 agent output dicts
            synthesis        (dict)  — output of synthesise(): weighted score,
                                      bull/bear case, verdict; null if both
                                      synthesis attempts failed
            filings          (dict)  — output of fetch_filings(): BSE announcements
                                      + gpt-4o-mini summaries, or None

    Raises:
        400: if the ticker is not found on Screener.in or any required field
             is missing from the scraped data (ValueError from scraper).
        503: if Screener.in authentication fails (RuntimeError) or a network
             error occurs while fetching the page.
    """
    ticker = body.ticker.strip().upper()

    # --- Cache hit: return immediately but still record the history entry ---
    cached = get_cached(ticker)
    if cached is not None:
        cached_data, fetched_at_str = cached
        fetched_at = datetime.fromisoformat(fetched_at_str)
        age_hours = round((datetime.now(timezone.utc) - fetched_at).total_seconds() / 3600, 1)
        # Record even cache-served views so history shows all lookups
        try:
            save_analysis(ticker, cached_data)
        except Exception as e:
            print(f"Warning: memory write failed for '{ticker}': {e}")
        return {"source": "cache", "scraped_at": fetched_at_str, "cache_age_hours": age_hours, **cached_data}

    # --- Step 1: Scrape Screener.in ---
    try:
        company_data = fetch_company_data(ticker)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except req_lib.exceptions.RequestException as e:
        raise HTTPException(
            status_code=503,
            detail=f"Network error while fetching data for '{ticker}': {e}",
        )

    scraped_at = datetime.now(timezone.utc).isoformat()

    # --- Step 2: Compute quantitative signals (pure Python, no network) ---
    # ValidationError here means scraper returned bad data (e.g. empty name) — surface as 422.
    try:
        signals = compute_signals(company_data)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # --- Step 3: Fetch news (non-blocking — failure returns None) ---
    news = None
    try:
        news = fetch_news(signals.meta.name, ticker)
    except Exception as e:
        # News failure is non-fatal — analysis proceeds without it
        print(f"Warning: news fetch failed for '{ticker}': {e}")

    # --- Step 4: Run 5 analyst agents in parallel ---
    # Each agent makes 1 GPT-4o call. Parallel execution keeps total latency
    # close to a single call rather than 5× serial latency.
    analyst_notes = _run_agents_parallel(signals, news)

    # --- Step 5: Synthesise the 5 analyst notes into a consensus verdict ---
    # Retry once on failure; if both attempts fail, return partial result with synthesis=None
    # rather than raising 502 — all agent work is preserved in the response.
    synthesis = None
    for attempt in range(2):
        try:
            synthesis = synthesise(analyst_notes, signals)
            break
        except (RuntimeError, OpenAIError) as e:
            if attempt == 1:
                print(f"Warning: synthesis failed after 2 attempts for '{ticker}': {e}")

    # --- Step 6: Fetch BSE filings (non-blocking — failure captured in error field) ---
    # bse_code comes from the scraper header (extracted from the Screener company page).
    # If the BSE code is absent (e.g. NSE-only listing), filings are skipped gracefully.
    filings = None
    bse_code = company_data.get("header", {}).get("bse_code")
    if bse_code:
        try:
            filings = fetch_filings(bse_code)
        except Exception as e:
            # Filings failure is non-fatal — a BSE API outage must never break analysis
            print(f"Warning: filings fetch failed for '{ticker}' (BSE {bse_code}): {e}")
    else:
        print(f"Warning: no BSE code found for '{ticker}' — skipping filings.")

    result = {
        "scraped_at":     scraped_at,
        "cache_age_hours": 0.0,
        "data":           company_data,
        "signals":        signals.model_dump(),
        "news":           news,
        "analyst_notes":  analyst_notes,
        "synthesis":      synthesis,
        "filings":        filings,
    }

    # --- Cache write — failure must never break the response ---
    try:
        set_cached(ticker, result)
    except Exception as e:
        print(f"Warning: cache write failed for '{ticker}': {e}")

    # --- Step 7: Persist to analyst_history (Phase 6) ---
    try:
        save_analysis(ticker, result)
    except Exception as e:
        print(f"Warning: memory write failed for '{ticker}': {e}")

    return {"source": "live", **result}


# ---------------------------------------------------------------------------
# Endpoints — memory: history
# ---------------------------------------------------------------------------

@app.get("/history/{ticker}")
def history(ticker: str):
    """
    Returns all historical analysis runs for a ticker, newest first.

    Each item contains the run timestamp, consensus score, verdict,
    per-agent scores, and the full signals dict for that run.

    Args:
        ticker: NSE/BSE symbol in the URL path, e.g. /history/RELIANCE.

    Returns:
        {"ticker": str, "runs": list[dict]} — runs is empty if no history.

    Raises:
        No 404 — an empty list is returned for unknown tickers.
    """
    ticker = ticker.strip().upper()
    runs = get_history(ticker)
    return {"ticker": ticker, "runs": runs}


# ---------------------------------------------------------------------------
# Endpoints — memory: watchlist
# ---------------------------------------------------------------------------

@app.get("/watchlist")
def list_watchlist():
    """
    Returns all tickers currently in the watchlist, alphabetically.

    Returns:
        {"watchlist": list[dict]} — each item has ticker, added_at, note.
    """
    return {"watchlist": get_watchlist()}


@app.post("/watchlist")
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


@app.delete("/watchlist/{ticker}")
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
