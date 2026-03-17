# CLAUDE.md — Fintel Project Instructions
# Read this entire file before writing any code.

---

## What This Project Is

Fintel is an AI-powered investment research tool for Indian stocks. Given an NSE ticker, it:
1. Fetches 10+ years of fundamental data from Screener.in (scraper)
2. Computes ~40 quantitative signals in Python (Piotroski, DuPont, DCF, Graham Number, FCF, etc.)
3. Fetches recent news and classifies sentiment via gpt-4o-mini
4. Runs five analyst agents — each from a distinct investing philosophy (Value/Graham, Growth/Lynch, Quality/Munger, Contrarian/Burry, Momentum) — each writing a structured note
5. Synthesises the five notes into a consensus score, bull/bear case, and verdict
6. Reads recent BSE corporate filings and summarises them (Phase 5)
7. Remembers every analysis it has ever run for a ticker (Phase 6)

See `INSPIRATION.md` for the reference projects that shaped this design.

## Current Phase

**ALL 6 PHASES COMPLETE ✅**

Phase 1 (scraper + LLM wrapper) ✅ COMPLETE
Phase 2 (signal engine + news + signal dashboard) ✅ COMPLETE
Phase 3 (multi-analyst engine + synthesis + frontend) ✅ COMPLETE
Phase 4 (DCF valuation) ✅ COMPLETE — 3-stage DCF in signals.py, WACC=12%
Phase 5 (BSE filings RAG) ✅ COMPLETE — filings.py + wired into API + frontend
Phase 6 (memory + watchlist) ✅ COMPLETE — memory.py, history chart, watchlist panel

**Next (post-Phase 6 improvements):**
- Banks/NBFCs support: scraper breaks on different P&L structure (no "Sales" row)
- DCF alternatives for negative-FCF companies: EV/EBITDA relative, P/S, dividend yield

### Current Architecture

```
scraper.py → signals.py → news.py → agents/ → synthesis.py → api.py → frontend
[scrape]    [Python maths] [NewsAPI]  [5×GPT-4o] [1×GPT-4o]
```

**The core principle:** Python does the maths. GPT-4o explains the maths. Never the other way around.

**Phase 3 principle:** Multiple analyst lenses. One set of signals, five explanations —
each from a distinct investing philosophy adapted for Indian markets.

---

## STRICT RULES — Follow These Exactly

### 1. KISS — Keep It Simple, Stupid
- No unnecessary files. If a job can be done in an existing file, do it there.
- No design patterns, no abstractions, no "future-proofing" unless asked.
- No unnecessary dependencies. Check requirements.txt before adding anything new.
- Readable > clever. If there are two ways to do something, pick the simpler one.

### 2. File Limit
- Files should be as minimum as possible in number.
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

For any agent or orchestration code:
- Add a comment above every logical block explaining what it does in plain English.
- Add a comment at the top of every agent function explaining the investing philosophy it embodies.

### 5. No Silent Failures — Fail Hard, Always
- Always raise named exceptions with helpful messages.
- Example: `raise ValueError(f"Could not find P&L table for ticker {ticker}.")`
- Never use bare `except: pass`
- **Every field in the scraper output is required.** If any field cannot be extracted, raise immediately.
- **Exception for signals.py:** Signal computation gaps are a property of the data, not a bug. If a signal cannot be computed, set it to `None` with a reason string. Do NOT raise. See TRADEOFFS.md T-011.
- **Exception for agents:** If an analyst agent's LLM call fails, set that agent's note to `{"error": str(e)}` and continue. Never let one agent failure abort the whole pipeline.

### 6. API Keys
- All keys go in `.env` only.
- Use python-dotenv to load them.
- Keys required: `OPENAI_API_KEY`, `SCREENER_EMAIL`, `SCREENER_PASSWORD`, `NEWS_API_KEY`
- Phase 5 adds: `BSE_CODE` mapping (no new key needed — scraped from Screener header)
- Never hardcode keys or commit `.env` to version control.

### 7. LLM Model
- Use OpenAI API only (not Anthropic) for demo purposes.
- Model: `gpt-4o` for all analyst + synthesis calls.
- Model: `gpt-4o-mini` for cheaper/simpler calls (sentiment classification, filing summaries).
- Import pattern: `from openai import OpenAI`
- Each analyst agent makes exactly 1 GPT-4o call. Synthesis makes 1. Total: 6 calls per analysis.

### 8. Caching
- SQLite cache with 24-hour TTL for full analysis results.
- DB file lives at: `data/cache/fintel.db` (never in `src/`).
- Cache layer is `src/cache.py` — exactly 3 functions: `init_db()`, `get_cached()`, `set_cached()`.
- Phase 6 adds `src/memory.py` which extends the same DB with two new tables (`analyst_history`, `watchlist`).
- No ORM, no extra deps — stdlib `sqlite3` + `json` only.

### 9. Frontend
- Streamlit only, one file: `frontend/app.py`.
- Phase 3+ frontend is information-dense — this is intentional for a research tool.
- Structured panels per section (signal dashboard, analyst notes, news, filings, memory).
- Charts are allowed (`st.bar_chart`) for the analyst score comparison panel.
- No custom CSS, no multi-page setup.

### 10. Scraper Memory Skill
- A skill called `scraper-memory` is configured at `~/.claude/skills/scraper-memory/SKILL.md`.
- It MUST be activated before reading or modifying `src/scraper.py` or any scraper-related file.
- It maintains `~/.claude/scraper-notes/screener.md` — a persistent log of Screener.in quirks,
  undocumented API endpoints, field-level gotchas, and session auth notes.
- Read the notes file before writing scraper code. Update it only when something new is discovered.

### 11. GitHub
- After I approve a set of files, automatically commit and push to GitHub.
- Commit message format: `"Phase N BatchN: add/update {filename(s)} — {one line description}"`
- Never push unapproved code.

---

## How To Run

```bash
pip install -r requirements.txt
cp .env.example .env        # fill in your API keys
uvicorn src.api:app --reload            # backend on :8000
streamlit run frontend/app.py           # frontend on :8501
```

---

## Build Order

### Phase 1 ✅ COMPLETE
**Batch 1:** requirements.txt + .env.example + CLAUDE.md
**Batch 2:** src/scraper.py
**Batch 3:** src/cache.py + src/analysis.py
**Batch 4:** src/api.py
**Batch 5:** frontend/app.py
**Batch 6:** tests/test_scraper.py

### Phase 2 ✅ COMPLETE
**Batch 1:** src/signals.py — signal engine (pure Python, no LLM)
**Batch 2:** src/news.py + src/analysis.py — news + rewritten LLM explainer
**Batch 3:** src/api.py + frontend/app.py — wire pipeline + full signal dashboard
Also done: scraper.py major rewrite (schedule sub-row API for CapEx, inventories, trade receivables, etc.)

### Phase 3 — Multi-Analyst Engine ✅ COMPLETE
All 4 batches done — agents, synthesis, API v3.0.0, frontend multi-analyst UI.

### Phase 4 — DCF Valuation ✅ COMPLETE
3-stage DCF in signals.py with fixed WACC=12%. Returns None for negative-FCF companies.

### Phase 5 — BSE Filing RAG ✅ COMPLETE
src/filings.py + API + frontend wired.

### Phase 6 — Memory + Watchlist ✅ COMPLETE
src/memory.py, history chart, watchlist panel in frontend.

### Post-Phase 6 — Ongoing Improvements
Work on these next, one at a time, with approval after each:
1. **Banks/NBFCs support** — scraper assumes "Sales" row; banks use "Revenue from operations" / "Interest earned"
2. **DCF alternatives for negative-FCF companies** — when DCF is None, show EV/EBITDA relative, P/S, dividend yield

Wait for approval after each improvement batch.

---

## Folder Structure

```
fintel/
├── CLAUDE.md               ← this file
├── TRADEOFFS.md            ← architectural decision log
├── INSPIRATION.md          ← reference details for ai-hedge-fund and dexter
├── .env.example
├── requirements.txt
├── data/
│   └── cache/              ← SQLite DB lives here (fintel.db)
├── src/
│   ├── scraper.py          ← Screener.in scraper (stable; quick_ratios API added post-Phase 3)
│   ├── cache.py            ← SQLite cache layer, 3 functions (Phase 1, stable)
│   ├── signals.py          ← quantitative signal engine (Phase 2 + DCF Phase 4, stable)
│   ├── news.py             ← NewsAPI + gpt-4o-mini sentiment (Phase 2, stable)
│   ├── analysis.py         ← single-analyst LLM brief (Phase 2; retired in Phase 3 Batch 3)
│   ├── agents/             ← NEW Phase 3
│   │   ├── __init__.py
│   │   ├── value.py        ← Graham/Buffett analyst
│   │   ├── growth.py       ← Lynch/Fisher analyst
│   │   ├── quality.py      ← Munger/Pabrai analyst
│   │   ├── contrarian.py   ← Burry/Druckenmiller analyst
│   │   └── momentum.py     ← quantitative momentum analyst
│   ├── synthesis.py        ← NEW Phase 3: aggregates 5 notes → consensus verdict
│   ├── filings.py          ← NEW Phase 5: BSE announcements + PDF summaries
│   ├── memory.py           ← NEW Phase 6: history + watchlist (extends fintel.db)
│   └── api.py              ← FastAPI backend (updated per phase)
├── frontend/
│   └── app.py              ← Streamlit UI (updated per phase)
└── tests/
    └── test_scraper.py
```

---

## Analyst Agent Reference (Phase 3)

Five analyst agents, each a pure function `analyze(data, signals, news) -> dict`.
All receive the same pre-computed `signals` dict. System prompt changes per agent.

| Agent | File | Philosophy | Key signals used | Extra Python computation |
|-------|------|-----------|-----------------|--------------------------|
| Value | agents/value.py | Graham + Buffett | graham_number, price_to_graham, earnings_quality, debt_trend, piotroski, ev_ebitda, price_to_sales, pe_vs_industry | Owner Earnings = NI + dep − capex − ΔWC; OE yield vs 10yr Gsec |
| Growth | agents/growth.py | Lynch + Fisher | growth_quality.acceleration, revenue_yoy_pct, margin_trend, dupont.roe_driver, industry_pe, price_to_sales | PEG = PE / profit_cagr_3yr |
| Quality | agents/quality.py | Munger + Pabrai | roce_latest, roce_trend, net_margin, earnings_quality, piotroski, ev_ebitda, promoter_holding | ROCE vs WACC (12%) spread |
| Contrarian | agents/contrarian.py | Burry + Druckenmiller | promoter_risk, balance_sheet_health, pledge_trend, promoter_holding_change | Debt service coverage = OCF / interest expense |
| Momentum | agents/momentum.py | Quantitative | quarterly_momentum, earnings_yield, 52w price position, industry_pe, news sentiment | Price % vs 52w high/low range |

Agent output schema (all 5 identical):
```python
{
  "lens": str,          # "value"|"growth"|"quality"|"contrarian"|"momentum"
  "score": int,         # 1–10, this analyst's conviction
  "thesis": str,        # 2–3 sentence investment thesis from this lens
  "key_signals": [str], # 3 specific signals that drove the score
  "risks": [str],       # 1–3 risks this analyst highlights
  "action": str         # "buy"|"hold"|"sell"|"avoid"
}
```

Synthesis weights (default): value=25%, quality=25%, growth=20%, contrarian=20%, momentum=10%.

---

## Signal Engine Reference (Phase 2, stable)

`src/signals.py` computes 9 signal groups from scraper output:
1. **Piotroski F-Score** (0–9): 9 binary signals for financial health
2. **DuPont Decomposition**: ROE = margin × asset turnover × leverage
3. **Earnings Quality**: OCF/NP and FCF/NP ratios (> 1.0 = high quality; uses explicit capex)
4. **Growth Quality**: Revenue/profit CAGR acceleration/deceleration + margin trend
5. **Capital Efficiency**: ROCE trend over 5 years + working capital cycle trend
6. **Balance Sheet Health**: D/E trend + interest coverage (EBIT/Interest)
7. **Valuation**: Graham Number + price premium/discount + PE + earnings yield + DCF (3-stage, WACC=12%) + EV/EBITDA + Price/Sales + Industry PE
8. **Promoter Risk**: Pledged % + pledge flag + trend + promoter holding % + QoQ change
9. **Quarterly Momentum**: Revenue YoY%, profit YoY%, OPM trend

Scores are mechanically derived from signals in Python — GPT-4o explains them, does not compute them.

---

## Testing Rules
- **Live tests only.** Tests must hit real Screener.in with real credentials loaded from `.env`.
- No mocks, no fixture HTML, no dummy/hardcoded values anywhere in tests or in the codebase.
- Tests are skipped (not failed) if `SCREENER_EMAIL` is not set in the environment.
- The purpose of tests is to verify the scraper works against the real live website — not to test logic in isolation.

---

## Known Limitations
- Screener.in has no official API — HTML structure may change.
- Screener schedule sub-row API (`/api/company/{id}/schedules/`) is undocumented — may change.
- Screener quick_ratios API (`/api/company/{warehouse_id}/quick_ratios/`) is undocumented — may change.
- Custom ratios (pledged_pct, ev_ebitda, price_to_sales, promoter_holding, industry_pe) only appear
  if the user has added them via Screener's "Edit Ratios" panel — they won't populate otherwise.
- Add 2–3 second delays between Screener requests to avoid IP blocks.
- Indian stocks only (Phase 1–6).
- NewsAPI free tier: 100 requests/day (24h cache limits usage to ~1 call/ticker/day).
- Graham Number undervalues high-growth companies by design — analysts must contextualise.
- Signal gaps (missing data fields) produce null signals, not errors — see TRADEOFFS.md T-011.
- 6 GPT-4o calls per analysis (~30–40s response time, not streamed yet).
- DCF: WACC fixed at 12% (Indian equities baseline) — no company-specific WACC.
- DCF returns None for companies with negative FCF (e.g. DMART) — correct by design.
- Phase 5 BSE filings: BSE API is undocumented; PDF parsing is brittle for scanned documents.
- No finance-specific LLM available as public API — GPT-4o used per Rule 7 — see TRADEOFFS.md T-009.
- Banks/NBFCs may break scraper (different P&L structure — "Revenue from operations" not "Sales").
