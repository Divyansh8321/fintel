# ============================================================
# FILE: src/api.py
# PURPOSE: FastAPI backend that ties together the scraper,
#          signals, news, five analyst agents, and synthesis layer.
#          Exposes GET /health, POST /analyze, DELETE /cache/{ticker}.
# INPUT:   POST /analyze body: {"ticker": str}
# OUTPUT:  JSON dict with scraped data + signals + news + analyst_notes
#          + synthesis, plus a "source" field ("cache" or "live")
# DEPENDS: fastapi, uvicorn, src/scraper.py, src/signals.py,
#          src/news.py, src/cache.py, src/agents/*, src/synthesis.py,
#          .env (OPENAI_API_KEY, SCREENER_EMAIL, SCREENER_PASSWORD, NEWS_API_KEY)
# ============================================================

import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import asynccontextmanager

import requests as req_lib
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from openai import OpenAIError
from pydantic import BaseModel

from src.agents.contrarian import analyze as contrarian_analyze
from src.agents.growth import analyze as growth_analyze
from src.agents.momentum import analyze as momentum_analyze
from src.agents.quality import analyze as quality_analyze
from src.agents.value import analyze as value_analyze
from src.cache import DB_PATH, get_cached, init_db, set_cached
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

    On startup: initialises the SQLite cache database (creates the table
    if it doesn't exist). This runs once before the first request is served.
    On shutdown: nothing to clean up — SQLite connections are per-request.
    """
    init_db()
    yield


app = FastAPI(
    title="Fintel API",
    description="AI-powered investment research for Indian stocks.",
    version="3.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    """Request body for POST /analyze."""
    ticker: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run_agents_parallel(data: dict, signals: dict, news: dict | None) -> list[dict]:
    """
    Run all five analyst agents in parallel using a thread pool.

    Each agent makes one GPT-4o call. Running them concurrently cuts total
    latency from ~5×agent_time to ~1×agent_time (the slowest agent).

    Per CLAUDE.md Rule 5 (agent exception): if any agent raises, its error
    is captured in the returned dict — never propagated. The pipeline
    continues with however many agents succeeded.

    Args:
        data:    Full scraper output from fetch_company_data().
        signals: Pre-computed signal dict from compute_signals().
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
            pool.submit(fn, data, signals, news): lens
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
    Main analysis endpoint. Runs the full Phase 3 pipeline:
      1. Scrape fundamental data from Screener.in
      2. Compute quantitative signals in Python (Piotroski, DuPont, etc.)
      3. Fetch recent news and classify sentiment via gpt-4o-mini
      4. Run 5 analyst agents in parallel (each makes 1 GPT-4o call)
      5. Synthesise the 5 notes into a consensus verdict (1 GPT-4o call)

    Checks the SQLite cache first. Cache hits skip all 5 steps.
    Total GPT-4o calls on a cache miss: 6 (5 agents + 1 synthesis).

    Args:
        body: AnalyzeRequest with field "ticker" (NSE/BSE symbol).

    Returns:
        JSON dict with keys:
            source          (str)  — "cache" or "live"
            data            (dict) — full output of fetch_company_data()
            signals         (dict) — output of compute_signals()
            news            (dict) — output of fetch_news(), or None
            analyst_notes   (list) — list of 5 agent output dicts
            synthesis       (dict) — output of synthesise(): weighted score,
                                     bull/bear case, verdict

    Raises:
        400: if the ticker is not found on Screener.in or any required field
             is missing from the scraped data (ValueError from scraper).
        503: if Screener.in authentication fails (RuntimeError) or a network
             error occurs while fetching the page.
        502: if the OpenAI synthesis call fails (agent failures are non-fatal).
    """
    ticker = body.ticker.strip().upper()

    # --- Cache hit: return immediately without any network calls ---
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

    # --- Step 3: Fetch news (non-blocking — failure returns None) ---
    news = None
    company_name = company_data.get("header", {}).get("name", ticker)
    try:
        news = fetch_news(company_name, ticker)
    except Exception as e:
        # News failure is non-fatal — analysis proceeds without it
        print(f"Warning: news fetch failed for '{ticker}': {e}")

    # --- Step 4: Run 5 analyst agents in parallel ---
    # Each agent makes 1 GPT-4o call. Parallel execution keeps total latency
    # close to a single call rather than 5× serial latency.
    analyst_notes = _run_agents_parallel(company_data, signals, news)

    # --- Step 5: Synthesise the 5 analyst notes into a consensus verdict ---
    try:
        synthesis = synthesise(analyst_notes, company_data)
    except RuntimeError as e:
        raise HTTPException(
            status_code=502,
            detail=f"OpenAI synthesis call failed for '{ticker}': {e}",
        )
    except OpenAIError as e:
        raise HTTPException(
            status_code=502,
            detail=f"OpenAI API error during synthesis for '{ticker}': {e}",
        )

    # --- Cache and return ---
    result = {
        "data":           company_data,
        "signals":        signals,
        "news":           news,
        "analyst_notes":  analyst_notes,
        "synthesis":      synthesis,
    }
    # Cache write failure must never break the response
    try:
        set_cached(ticker, result)
    except Exception as e:
        print(f"Warning: cache write failed for '{ticker}': {e}")

    return {"source": "live", **result}
