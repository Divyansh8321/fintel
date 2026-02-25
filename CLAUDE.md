# CLAUDE.md — Fintel Project Instructions
# Read this entire file before writing any code.

---

## What This Project Is
Fintel is an AI-powered investment research tool for Indian stocks.
Given an NSE ticker, it fetches fundamental data, earnings documents,
and news, then produces a structured investment brief using GPT-4o.

## Current Phase
PHASE 2 — Signal Engine + News.
Phase 1 (scraper + LLM wrapper) is complete. Phase 2 adds:
- `src/signals.py` — Python computes quantitative signals (Piotroski, DuPont, earnings quality, Graham Number, etc.)
- `src/news.py` — NewsAPI headlines + gpt-4o-mini sentiment
- Rewrite `src/analysis.py` — GPT-4o now explains pre-computed signals, does NOT compute them
- Update `src/api.py` and `frontend/app.py` to wire the new pipeline

DO NOT build Phase 3 (peer comparison) or Phase 4 (backtester) unless explicitly told to.

### Phase 2 Architecture
```
scraper.py → signals.py → (news.py) → analysis.py → api.py → frontend
             [Python maths]  [NewsAPI]   [LLM explains]
```
**The core principle:** Python does the maths. GPT-4o explains the maths. Never the other way around.

---

## STRICT RULES — Follow These Exactly

### 1. KISS — Keep It Simple, Stupid
- No unnecessary files. If a job can be done in an existing file, do it there.
- No design patterns, no abstractions, no "future-proofing" unless asked.
- No unnecessary dependencies. Check requirements.txt before adding anything new.
- Readable > clever. If there are two ways to do something, pick the simpler one.

### 2. File Limit
- the files should be as minimum as possible in number
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

### 5. No Silent Failures — Fail Hard, Always
- Always raise named exceptions with helpful messages.
- Example: raise ValueError(f"Could not find P&L table for ticker {ticker}. Check if Screener page structure has changed.")
- Never use bare except: pass
- **Every field in the scraper output is required.** If any field cannot be extracted, raise immediately.
- Never return partial data or substitute None for a missing field. The caller must get either complete data or a clear exception — never something in between.
- This rule exists so every scraping failure is visible and fixable. It will be relaxed explicitly once the scraper is stable.
- **Exception for signals.py:** Signal computation gaps are a property of the data, not a bug. If a signal cannot be computed (e.g. no cash flow data), set it to `None` with a reason string. Do NOT raise. See TRADEOFFS.md T-011.

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

## Build Order (Phase 1) ✅ COMPLETE
**Batch 1:** requirements.txt + .env.example + CLAUDE.md  ✅
**Batch 2:** src/scraper.py  ✅
**Batch 3:** src/cache.py + src/analysis.py  ✅
**Batch 4:** src/api.py  ✅
**Batch 5:** frontend/app.py  ✅
**Batch 6:** tests/test_scraper.py  ✅

## Build Order (Phase 2)
Build in this exact order, 2–3 files at a time:

**Batch 1:** src/signals.py  ← signal engine (pure Python, no LLM)
**Batch 2:** src/news.py + src/analysis.py  ← news + rewritten LLM explainer
**Batch 3:** src/api.py + frontend/app.py  ← wire pipeline + full signal UI

Wait for approval after each batch.

## Folder Structure
```
fintel/
├── CLAUDE.md
├── TRADEOFFS.md            ← architectural decision log
├── .env.example
├── requirements.txt
├── data/
│   └── cache/              ← SQLite DB lives here (fintel.db)
├── src/
│   ├── scraper.py          ← Screener.in scraper (Phase 1, stable)
│   ├── cache.py            ← SQLite cache layer, 3 functions (Phase 1, stable)
│   ├── signals.py          ← quantitative signal engine (Phase 2, NEW)
│   ├── news.py             ← NewsAPI + gpt-4o-mini sentiment (Phase 2, NEW)
│   ├── analysis.py         ← GPT-4o explainer of pre-computed signals (Phase 2, rewritten)
│   └── api.py              ← FastAPI backend (Phase 2, updated)
├── frontend/
│   └── app.py              ← Streamlit UI (Phase 2, updated)
└── tests/
    └── test_scraper.py
```

## Testing Rules
- **Live tests only.** Tests must hit real Screener.in with real credentials loaded from .env.
- No mocks, no fixture HTML, no dummy/hardcoded values anywhere in tests or in the codebase.
- Tests are skipped (not failed) if SCREENER_EMAIL is not set in the environment.
- The purpose of tests is to verify the scraper works against the real live website — not to test logic in isolation.

## Known Limitations
- Screener.in has no official API — HTML structure may change
- Add 2–3 second delays between Screener requests to avoid IP blocks
- Indian stocks only (Phase 1–2)
- NewsAPI free tier: 100 requests/day (24h cache limits usage to 1 call/ticker/day)
- Graham Number undervalues high-growth companies by design — LLM must contextualise
- Signal gaps (missing data fields) produce null signals, not errors — see TRADEOFFS.md T-011
- No finance-specific LLM available as a public API — GPT-4o used per Rule 7 — see TRADEOFFS.md T-009

## Signal Engine Reference (Phase 2)
`src/signals.py` computes 9 signal groups from scraper output:
1. **Piotroski F-Score** (0-9): 9 binary signals for financial health
2. **DuPont Decomposition**: ROE = margin × asset turnover × leverage (identifies ROE driver)
3. **Earnings Quality**: OCF/NP and FCF/NP ratios (> 1.0 = high quality)
4. **Growth Quality**: Revenue/profit CAGR acceleration/deceleration + margin trend
5. **Capital Efficiency**: ROCE trend over 5 years + working capital cycle trend
6. **Balance Sheet Health**: D/E trend + interest coverage (EBIT/Interest)
7. **Valuation**: Graham Number + price premium/discount + PE + earnings yield
8. **Promoter Risk**: Pledged % flag (none/moderate/high)
9. **Quarterly Momentum**: Revenue YoY%, profit YoY%, OPM trend

Scores are mechanically derived from signals in Python — GPT-4o explains them, does not compute them.