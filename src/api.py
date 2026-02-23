# ============================================================
# FILE: src/api.py
# PURPOSE: FastAPI backend that ties together the scraper,
#          cache, and analysis layers. Exposes two endpoints:
#          GET /health and POST /analyze.
# INPUT:   POST /analyze body: {"ticker": str}
# OUTPUT:  JSON dict with scraped data + investment brief,
#          plus a "source" field ("cache" or "live")
# DEPENDS: fastapi, uvicorn, src/scraper.py, src/cache.py,
#          src/analysis.py, .env (all keys)
# ============================================================

from contextlib import asynccontextmanager

import requests as req_lib
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from openai import OpenAIError
from pydantic import BaseModel

import sqlite3

from src.analysis import generate_brief
from src.cache import DB_PATH, get_cached, init_db, set_cached
from src.scraper import fetch_company_data

load_dotenv()


# ---------------------------------------------------------------------------
# Startup / shutdown lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager.

    On startup: initialises the SQLite cache database (creates the table
    if it doesn't exist). This runs once before the first request is served.
    On shutdown: nothing to clean up — SQLite connections are per-request.
    """
    init_db()
    yield


app = FastAPI(
    title="Fintel API",
    description="AI-powered investment research for Indian stocks.",
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    """Request body for POST /analyze."""
    ticker: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.delete("/cache/{ticker}")
def clear_cache(ticker: str):
    """
    Deletes the cached entry for a ticker so the next /analyze call
    fetches fresh data from Screener.in and re-runs the AI brief.

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


@app.get("/health")
def health():
    """
    Health check endpoint.

    Returns:
        {"status": "ok"} — always, as long as the server is running.
    """
    return {"status": "ok"}


@app.post("/analyze")
def analyze(body: AnalyzeRequest):
    """
    Main analysis endpoint. Fetches fundamental data for a ticker,
    generates an AI investment brief, and returns the combined result.

    Checks the SQLite cache first. If a fresh entry (< 24hr) exists,
    returns it immediately without hitting Screener.in or OpenAI.
    Otherwise scrapes live data, generates the brief, caches the result,
    and returns it.

    Args:
        body: AnalyzeRequest with field "ticker" (NSE/BSE symbol).

    Returns:
        JSON dict with keys:
            source  (str)  — "cache" if served from cache, "live" if freshly scraped
            data    (dict) — full output of fetch_company_data()
            brief   (dict) — output of generate_brief(): scores, risk flags, verdict

    Raises:
        400: if the ticker is not found on Screener.in or any required field
             is missing from the scraped data (ValueError from scraper/analysis).
        503: if Screener.in authentication fails (RuntimeError) or a network
             error occurs while fetching the page.
        502: if the OpenAI API call fails.
    """
    ticker = body.ticker.strip().upper()

    # --- Cache hit ---
    cached = get_cached(ticker)
    if cached is not None:
        return {"source": "cache", **cached}

    # --- Live scrape ---
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

    # --- AI brief ---
    try:
        brief = generate_brief(company_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OpenAIError as e:
        raise HTTPException(
            status_code=502,
            detail=f"OpenAI API error while generating brief for '{ticker}': {e}",
        )

    # --- Cache and return ---
    result = {"data": company_data, "brief": brief}
    # Cache write failure (disk full, DB locked, etc.) must never break the
    # response — the user already paid for the scrape + LLM call.
    try:
        set_cached(ticker, result)
    except Exception as e:
        print(f"Warning: cache write failed for '{ticker}': {e}")

    return {"source": "live", **result}
