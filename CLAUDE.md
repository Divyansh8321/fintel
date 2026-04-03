# CLAUDE.md — Fintel

## What This Is
AI-powered investment research tool for Indian stocks (NSE tickers).
Scrapes Screener.in → computes ~40 signals in Python → runs 5 analyst agents → synthesises verdict.

**Core principle:** Python does the maths. GPT-4o explains the maths. Never the other way around.

**Status:** All 6 phases complete. Active work tracked via GitHub Issues.

## Architecture
```
scraper.py → signals.py → news.py → agents/ → synthesis.py → api.py → frontend/app.py
```

## How To Run
```bash
pip install -r requirements.txt && cp .env.example .env
uvicorn src.api:app --reload      # :8000
streamlit run frontend/app.py     # :8501
```

## Folder Structure
```
src/scraper.py       ← Screener.in scraper
src/cache.py         ← SQLite cache (3 functions only)
src/signals.py       ← quantitative signal engine
src/news.py          ← NewsAPI + sentiment
src/agents/          ← value, growth, quality, contrarian, momentum
src/synthesis.py     ← aggregates 5 agent notes → verdict
src/filings.py       ← BSE announcements
src/memory.py        ← history + watchlist
src/api.py           ← FastAPI backend
frontend/app.py      ← Streamlit UI
data/cache/          ← fintel.db lives here
tests/test_scraper.py
```

---

## Rules

**1. KISS** — Readable > clever. No unnecessary deps (check requirements.txt first). When in doubt about adding an abstraction, ask before doing it. A new file is fine when it gives a module a clear, single responsibility — it's not fine to future-proof or over-engineer.

**2. File limit** — If a new file is needed, say so and explain why. Do not just create it.

**3. Documentation** — Every file gets a header block (FILE / PURPOSE / INPUT / OUTPUT / DEPENDS). Every function gets a docstring (Args / Returns / Raises). Every agent function gets a comment explaining its investing philosophy.

**4. Fail hard** — Always raise named exceptions. No bare `except: pass`.
   Exception: signals.py sets missing signals to `None` with a reason string (data gap, not a bug).
   Exception: agent LLM failures set `{"error": str(e)}` and continue.
   → Read TRADEOFFS.md T-011 before changing signal error handling.

**5. API Keys** — `.env` only. Never hardcoded. Required: `OPENAI_API_KEY`, `SCREENER_EMAIL`, `SCREENER_PASSWORD`, `NEWS_API_KEY`.

**6. LLM** — OpenAI only. `gpt-4o` for analysts + synthesis. `gpt-4o-mini` for sentiment + filing summaries. 6 total calls per analysis.
   → Read TRADEOFFS.md T-009 before switching LLM providers.

**7. Caching** — SQLite, 24h TTL, `data/cache/fintel.db`. `cache.py` has exactly 3 functions. No ORM.
   → Read TRADEOFFS.md T-002 before changing cache backend.

**8. Frontend** — Streamlit only, one file. No custom CSS, no multi-page.

**9. Scraper memory skill** — Run `/scraper-memory` before touching `src/scraper.py`. Updates `~/.claude/scraper-notes/screener.md`.
   → Read TRADEOFFS.md T-001 and T-003 before changing scraper session or URL strategy.

**10. GitHub** — Commit and push only after explicit approval. Format: `"IssueName: update {files} — {description}"`.

**11. Plans** — Make plans extremely concise. Sacrifice grammar for concision. At the end of each plan, list any unresolved questions.

---

## Skills Workflow
For any new feature: `/grill-me` → `/write-a-prd` → `/prd-to-issues` → implement with `/tdd`.
Run `/improve-codebase` after any surge of development.

**`/tdd` fintel override:** This is a financial system — silent failures are unacceptable.
- Scraper tests: live only, no mocks, real Screener.in credentials from `.env`, skipped (not failed) if `SCREENER_EMAIL` absent. Tests exist to catch when Screener.in changes its HTML — mocks cannot do this.
- Signal/agent/synthesis tests: mocks permitted — these are pure functions over dicts. TDD red-green-refactor applies normally.
- A crash or wrong output must always surface as a failure, never pass silently.

---

## When To Read TRADEOFFS.md
- Before any significant architectural decision → read the full file
- Changing scraper session management → T-001
- Changing cache backend → T-002
- Changing consolidated vs standalone scraping → T-003
- Changing test strategy → T-004
- Changing what LLM computes vs what Python computes → T-005
- Changing news data source → T-007
- Changing valuation anchor (Graham Number / DCF) → T-008
- Switching LLM provider → T-009
- Changing how scores are derived → T-010
- Changing signal error handling → T-011
- After any decision not covered above → **add a new entry to TRADEOFFS.md** using the same format

## Known Limitations
- Screener.in HTML may change without notice (no official API)
- Custom ratios only appear if added via Screener's "Edit Ratios" panel
- NewsAPI free tier: 100 req/day
- DCF returns None for negative-FCF companies — correct by design
- Banks/NBFCs break the scraper (different P&L structure)
- 6 GPT-4o calls ≈ 30–40s per analysis, not streamed