# ============================================================
# FILE: src/api.py
# PURPOSE: FastAPI backend that ties together the scraper,
#          signals, news, cache, and analysis layers.
#          Exposes GET /health, POST /analyze, DELETE /cache/{ticker}.
# INPUT:   POST /analyze body: {"ticker": str}
# OUTPUT:  JSON dict with scraped data + signals + news + brief,
#          plus a "source" field ("cache" or "live")
# DEPENDS: fastapi, uvicorn, src/scraper.py, src/signals.py,
#          src/news.py, src/cache.py, src/analysis.py,
#          .env (OPENAI_API_KEY, SCREENER_EMAIL, SCREENER_PASSWORD, NEWS_API_KEY)
# ============================================================

import sqlite3
from contextlib import asynccontextmanager

import requests as req_lib
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from openai import OpenAIError
from pydantic import BaseModel

from src.analysis import generate_brief
from src.cache import DB_PATH, get_cached, init_db, set_cached
from src.news import fetch_news
from src.scraper import fetch_company_data
from src.signals import compute_signals

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
    version="2.0.0",
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
    Main analysis endpoint. Runs the full Phase 2 pipeline:
      1. Scrape fundamental data from Screener.in
      2. Compute quantitative signals in Python (Piotroski, DuPont, DCF, etc.)
      3. Fetch recent news and classify sentiment via gpt-4o-mini
      4. Ask GPT-4o to explain the pre-computed signals in plain English

    Checks the SQLite cache first. Cache hits skip all 4 steps.

    Args:
        body: AnalyzeRequest with field "ticker" (NSE/BSE symbol).

    Returns:
        JSON dict with keys:
            source   (str)  — "cache" if served from cache, "live" if freshly fetched
            data     (dict) — full output of fetch_company_data()
            signals  (dict) — output of compute_signals(): 9 signal groups + scores
            news     (dict) — output of fetch_news(): articles + sentiment, or None
            brief    (dict) — output of generate_brief(): LLM explanations + verdict

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

    # --- Step 2: Compute quantitative signals (pure Python, no network) ---
    signals = compute_signals(company_data)

    # --- Step 3: Fetch news (non-blocking — failure returns None, never breaks) ---
    news = None
    company_name = company_data.get("header", {}).get("name", ticker)
    try:
        news = fetch_news(company_name, ticker)
    except Exception as e:
        # News failure is non-fatal — analysis proceeds without it
        print(f"Warning: news fetch failed for '{ticker}': {e}")

    # --- Step 4: LLM explains pre-computed signals ---
    try:
        brief = generate_brief(company_data, signals, news)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OpenAIError as e:
        raise HTTPException(
            status_code=502,
            detail=f"OpenAI API error while generating brief for '{ticker}': {e}",
        )

    # --- Cache and return ---
    result = {
        "data": company_data,
        "signals": signals,
        "news": news,
        "brief": brief,
    }
    # Cache write failure (disk full, DB locked, etc.) must never break the
    # response — the user already paid for the scrape + LLM call.
    try:
        set_cached(ticker, result)
    except Exception as e:
        print(f"Warning: cache write failed for '{ticker}': {e}")

    return {"source": "live", **result}
