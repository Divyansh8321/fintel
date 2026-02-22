# CLAUDE.md — Fintel Project Instructions
# Read this entire file before writing any code.

---

## What This Project Is
Fintel is an AI-powered investment research tool for Indian stocks.
Given an NSE ticker, it fetches fundamental data, earnings documents,
and news, then produces a structured investment brief using GPT-4o.

## Current Phase
PHASE 1 — Scraper + Analysis only.
DO NOT build Phase 2, 3, or the backtester unless explicitly told to.

---

## STRICT RULES — Follow These Exactly

### 1. KISS — Keep It Simple, Stupid
- No unnecessary files. If a job can be done in an existing file, do it there.
- No design patterns, no abstractions, no "future-proofing" unless asked.
- No unnecessary dependencies. Check requirements.txt before adding anything new.
- Readable > clever. If there are two ways to do something, pick the simpler one.

### 2. File Limit
- The entire project should stay under 12 files of actual code.
- If you think a new file is needed, say so and explain why. Do not just create it.

### 3. Write 2–3 Files At A Time Maximum
- Never write more than 3 files in one response.
- After writing 2–3 files, STOP and wait for explicit approval before continuing.
- Do not proceed to the next set of files until told "looks good, continue" or similar.

### 4. Documentation Is Mandatory — No Exceptions
Every single file must start with a header block like this:

    # ============================================================
    # FILE: src/scraper.py
    # PURPOSE: Fetches fundamental data for a given NSE ticker
    #          from Screener.in via authenticated HTML scraping.
    # INPUT:   ticker (str) — e.g. "RELIANCE"
    # OUTPUT:  dict containing P&L, ratios, shareholding, pros/cons
    # DEPENDS: requests, beautifulsoup4, .env (SCREENER_EMAIL, SCREENER_PASSWORD)
    # ============================================================

Every function must have a docstring like this:

    def get_pl_table(soup: BeautifulSoup) -> dict:
        """
        Extracts the 10-year Profit & Loss table from a Screener company page.
        
        Args:
            soup: Parsed HTML of the Screener company page
            
        Returns:
            dict with keys: years (list), revenue (list), net_profit (list), opm (list)
            
        Raises:
            ValueError: if P&L table is not found in the HTML
        """

Every class must have a docstring explaining what it represents.

For any LangGraph, agent, or orchestration code:
- Add a comment above EVERY node/edge explaining what it does in plain English
- Add a comment explaining the overall graph flow at the top of the function

### 5. No Silent Failures
- Always raise named exceptions with helpful messages.
- Example: raise ValueError(f"Could not find P&L table for ticker {ticker}. Check if Screener page structure has changed.")
- Never use bare except: pass

### 6. API Keys
- All keys go in .env only
- Use python-dotenv to load them
- Keys required: OPENAI_API_KEY, SCREENER_EMAIL, SCREENER_PASSWORD, NEWS_API_KEY
- Never hardcode keys or commit .env to version control

### 7. LLM Model
- Use OpenAI API only (not Anthropic) for demo purposes
- Model: gpt-4o for all analysis calls
- Model: gpt-4o-mini for cheaper/simpler calls (e.g. classifying sentiment)
- Import pattern: from openai import OpenAI

### 8. Caching
- SQLite cache with 24-hour TTL
- DB file lives at: data/cache/fintel.db (never in src/)
- Cache layer is src/cache.py — exactly 3 functions: init_db(), get_cached(), set_cached()
- No ORM, no extra deps — stdlib sqlite3 + json only
- Keep it minimal: single table, no indexes, no migrations

### 9. Frontend
- Streamlit only, one file: frontend/app.py
- Keep it minimal — input box, submit button, display JSON output prettily
- No custom CSS, no charts, no multi-page setup
- It should take under 50 lines

### 10. GitHub
- After I approve a set of files, automatically commit and push to GitHub
- Commit message format: "Phase 1: add {filename}" or "Phase 1: update {filename}"
- Never push unapproved code

---

## How To Run
```bash
pip install -r requirements.txt
cp .env.example .env        # fill in your API keys
uvicorn src.api:app --reload            # backend on :8000
streamlit run frontend/app.py           # frontend on :8501
```

## Build Order (Phase 1)
Build in this exact order, 2–3 files at a time:

**Batch 1:** requirements.txt + .env.example + CLAUDE.md  ✅
**Batch 2:** src/scraper.py
**Batch 3:** src/cache.py + src/analysis.py
**Batch 4:** src/api.py
**Batch 5:** frontend/app.py
**Batch 6:** tests/test_scraper.py

Wait for approval after each batch.

## Folder Structure
```
fintel/
├── CLAUDE.md
├── .env.example
├── requirements.txt
├── data/
│   └── cache/              ← SQLite DB lives here (fintel.db)
├── src/
│   ├── scraper.py          ← Screener.in scraper
│   ├── cache.py            ← SQLite cache layer (3 functions)
│   ├── analysis.py         ← OpenAI gpt-4o brief generator
│   └── api.py              ← FastAPI backend
├── frontend/
│   └── app.py              ← Streamlit UI
└── tests/
    └── test_scraper.py
```

## Known Limitations
[Update this as you build]
- Screener.in has no official API — HTML structure may change
- Add 2–3 second delays between Screener requests to avoid IP blocks
- Indian stocks only in Phase 1
- NewsAPI free tier: 100 requests/days