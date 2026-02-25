# TRADEOFFS.md — Fintel Architectural Decision Log

Every significant fork in the road during development is documented here.
Format: context → options considered → decision → implication.
Useful for code reviews, interviews, and future contributors.

---

## T-001: Screener.in Session Management

**Phase:** 1 — Scraper
**Context:** Every scrape requires an authenticated Screener.in session. We needed to decide whether to authenticate once and reuse the session or authenticate fresh on every request.

**Option A: Module-level singleton session**
Authenticate once when the module is first imported. Store in a `_session` global. Reuse for all subsequent calls within the process lifetime.
Pros: fast (auth costs 2 HTTP round-trips); simple; auth overhead is once per process.
Cons: if the session cookie expires mid-run, calls fail until process restart.

**Option B: Per-request authentication**
Authenticate at the start of every `fetch_company_data()` call.
Pros: no stale session risk.
Cons: 2 extra HTTP round-trips on every scrape (LOGIN GET + POST); unnecessary overhead for a single-user tool.

**Option C: Caller-injected session**
`fetch_company_data(ticker, session)` — caller manages the session.
Pros: explicit, testable.
Cons: leaks session management into `api.py`; adds complexity at every call site.

**Decision:** Option A (module singleton).
Screener.in sessions last days, not minutes. The stale session risk is negligible for a single-user dev tool. Simplicity wins.

**Implication:** If the tool is ever run in a multi-process environment (e.g. Gunicorn with multiple workers), each worker gets its own session. That is correct behaviour — no shared state issues.

---

## T-002: Cache Backend

**Phase:** 1 — Cache
**Context:** We needed a cache to avoid re-scraping Screener.in and re-calling OpenAI on every request. TTL of 24 hours.

**Option A: SQLite (stdlib)**
Single file DB at `data/cache/fintel.db`. Zero infrastructure. Ships with Python.
Pros: no pip install, no running server, no Docker, no config; single file is easy to inspect and clear.
Cons: not suitable for concurrent writes (fine for single-user tool); no built-in TTL (we implement it ourselves).

**Option B: Redis**
External Redis server with native TTL via `EXPIRE`.
Pros: built-in TTL, fast, production-grade.
Cons: requires running Redis server (infra dependency); adds `redis` pip dependency; overkill for a single-user tool.

**Option C: In-memory dict**
Simple Python `dict` in `api.py`.
Pros: zero overhead, zero code.
Cons: cache lost on every server restart; not durable.

**Decision:** Option A (SQLite).
For a single-user research tool, SQLite is exactly right. No infra, no deps, durable, inspectable with any SQLite client.

**Implication:** If Fintel is ever deployed as a multi-user service with concurrent requests, SQLite's write lock will be a bottleneck. Migration path: swap `cache.py` to Redis with minimal change (same 3-function interface).

---

## T-003: Consolidated vs Standalone Scraping Strategy

**Phase:** 1 — Scraper
**Context:** Screener.in has two URLs per company: `/company/{TICKER}/` (standalone) and `/company/{TICKER}/consolidated/`. Investors almost always want consolidated figures.

**Option A: Try consolidated first, fall back to standalone**
Attempt the consolidated URL. If Screener returns a "does not have consolidated financials" alert, retry the standalone URL.
Pros: returns consolidated data for the vast majority of companies; automatically handles standalone-only companies.
Cons: two HTTP requests for standalone-only companies.

**Option B: Always use standalone URL**
Simpler — one URL pattern.
Pros: no conditional logic.
Cons: returns incomplete data for every company that has subsidiaries (which is most large-caps). RELIANCE standalone would exclude Jio, Retail, etc. — useless for investors.

**Decision:** Option A (consolidated-first).
Consolidated is the correct view for investment analysis. The extra HTTP request for standalone-only companies is acceptable.

**Implication:** The scraper always returns an `is_consolidated: bool` field so callers know which view was used.

---

## T-004: Test Strategy — Live vs Mocked

**Phase:** 1 — Tests
**Context:** The scraper's entire value is that it correctly parses real Screener.in HTML. Tests need to verify this.

**Option A: Live tests only**
Tests hit real Screener.in with real credentials from `.env`. Tests are skipped (not failed) if credentials are absent.
Pros: tests verify the real thing — if Screener.in changes their HTML, tests catch it; no fixture drift (mocked HTML becomes stale over time).
Cons: tests are slower (network); tests fail if Screener.in is down.

**Option B: Mocked tests with fixture HTML**
Save HTML snapshots of Screener pages. Parse the snapshots in tests.
Pros: fast, offline, no credentials needed.
Cons: fixtures become stale when Screener.in updates their HTML — the tests pass but the real scraper is broken. This is the worst failure mode: green CI with a broken scraper.

**Decision:** Option A (live only).
The purpose of the tests is to catch when Screener.in changes its HTML structure. Mocked tests cannot do that. We accept slower tests in exchange for real signal.

**Implication:** Tests require `SCREENER_EMAIL` and `SCREENER_PASSWORD` in `.env`. CI will skip them unless the env vars are set.

---

## T-005: LLM Role — Analyst vs Explainer

**Phase:** 2 — Signal Engine
**Context:** Phase 1's `analysis.py` dumps all 13 sections of raw financial data into GPT-4o and asks it to "score the fundamentals 1-10." This is a black box — the LLM produces scores based on its training, not on computed signals. Scores are not reproducible (same input can yield slightly different scores across runs) and cannot be explained or audited.

**Option A: LLM as black-box analyst (Phase 1 approach)**
Send all raw data to GPT-4o. Ask it to score and explain.
Pros: simple; the LLM has broad financial knowledge.
Cons: not reproducible; not auditable; the LLM may ignore some signals or overweight others inconsistently; can't be explained in an interview.

**Option B: Python computes signals, LLM explains them (Phase 2 approach)**
A dedicated `signals.py` module computes every quantitative signal (Piotroski, DuPont, Graham Number, earnings quality, etc.) from the raw data. The LLM receives the pre-computed signals and explains what they mean in plain English. Scores are derived mechanically from the signals in Python.
Pros: reproducible, auditable, explainable; the LLM's job is narrow and well-defined; signals have published academic backing; the system behaves like a real analyst, not a chatbot.
Cons: more code to write and maintain; signal formulas must be validated.

**Decision:** Option B (Python computes, LLM explains).
This is the fundamental difference between a research tool and an LLM wrapper. The intelligence lives in the signal engine, not in GPT-4o's weights.

**Implication:** `signals.py` becomes the intellectual heart of the project. `analysis.py` becomes a thin prompt wrapper whose job is narrating what Python found. If GPT-4o is ever swapped for a different LLM, the analysis quality doesn't change meaningfully.

---

## T-006: Earnings Documents — PDF Scraping vs Existing Quarterly Data

**Phase:** 2 — Data Sources
**Context:** The project goal mentions "earnings documents." Options ranged from BSE PDF filing scraping to simply using the quarterly data already scraped.

**Option A: Scrape BSE PDF filings**
BSE India hosts quarterly earnings PDFs. Extract PDF URLs, download, parse with pdfplumber or PyMuPDF.
Pros: access to full earnings text, management commentary, guidance.
Cons: requires new dependency (pdfplumber/PyMuPDF); BSE's HTML/API is undocumented and fragile; PDF parsing is brittle; PDFs may be scanned images; adds significant complexity.

**Option B: BSE announcements HTML page**
BSE's `ann.html` page lists announcement titles and short descriptions in HTML.
Pros: no PDF dependency; plain HTML scraping.
Cons: BSE's anti-bot posture is aggressive; requires a new authenticated scraping target; announcement text is brief and may lack financial detail.

**Option C: Use existing quarterly data from Screener.in**
The scraper already fetches 8+ quarters of Sales, Operating Profit, Net Profit, EPS. Feed this to the LLM with an explicit prompt asking for quarterly momentum analysis.
Pros: zero new scraping; zero new dependencies; data is already structured and parsed; delivers the core insight (are earnings trending up or down?) without the complexity of document parsing.
Cons: no management commentary or forward guidance.

**Decision:** Option C (existing quarterly data).
The quarterly data already in Phase 1 contains all the factual momentum signal an investor needs. The incremental value of management commentary (Option A/B) does not justify the fragility and complexity cost.

**Implication:** "Earnings documents" in the project goal is fulfilled via the `quarterly_trend` field in the LLM brief, derived from the existing `quarterly` scraper data.

---

## T-007: News Source — NewsAPI vs Scraping vs Twitter

**Phase:** 2 — News
**Context:** The project goal mentions "news." We needed a reliable, structured news feed for Indian stocks.

**Option A: NewsAPI**
REST API returning JSON. `NEWS_API_KEY` was already in `.env.example` from the start. Free tier: 100 requests/day.
Pros: clean JSON; known rate limits; no scraping; reliable; coverage of major Indian business news sources (ET, Mint, LiveMint, etc.); one HTTP call per ticker.
Cons: free tier limited to 100 requests/day; articles may be delayed by up to 24 hours on free tier.

**Option B: Google News scraping**
Scrape Google News RSS or HTML for company-related news.
Pros: free, no key required; comprehensive.
Cons: Google aggressively blocks scrapers; brittle HTML structure; violates ToS.

**Option C: Twitter/X API**
Real-time market sentiment from tweets.
Pros: fastest signal; high volume.
Cons: Twitter API v2 is expensive (basic tier: $100/month); free tier is severely rate-limited; noisy (harder to separate signal from noise for Indian stocks).

**Decision:** Option A (NewsAPI).
Clean JSON API, already keyed in `.env.example`, zero scraping complexity, and the 24h TTL cache ensures we use at most 1 request per ticker per day (well within the 100/day free limit).

**Implication:** The 100 requests/day free limit means testing with >100 unique tickers per day will hit the ceiling. For a personal research tool, this is not a practical concern.

---

## T-008: Valuation Anchor — Graham Number vs DCF

**Phase:** 2 — Signals
**Context:** We needed an objective valuation anchor — a way to say "this stock is cheap/expensive" without relying on the LLM's judgment.

**Option A: Graham Number**
`sqrt(22.5 × EPS × Book Value per Share)` — Benjamin Graham's intrinsic value formula.
Pros: objective; no assumption inputs required; only requires EPS and Book Value (both available from scraper); well-known in value investing; computable in one line of Python.
Cons: a conservative metric — growth companies (e.g. FMCG, tech) will almost always trade far above Graham Number; not meaningful for financial companies (banks, NBFCs) where book value is the core metric.

**Option B: DCF (Discounted Cash Flow)**
PV = FCF × (1+g) / (WACC - g) — intrinsic value as present value of future cash flows.
Pros: theoretically rigorous; accounts for growth.
Cons: requires growth rate (g) and discount rate (WACC) as assumptions; tiny changes in g produce wildly different outputs; these assumptions must come from somewhere (LLM? user?); not reproducible without fixed inputs.

**Option C: PE-based relative valuation**
Compare current PE to historical average PE or sector median PE.
Pros: widely used; intuitive; sector-relative.
Cons: requires historical PE data (we have current PE but not 10yr PE series) or peer data (Phase 3); not absolute.

**Decision:** Option A (Graham Number) as primary anchor, Option C as secondary signal in Phase 3.
Graham Number is fully computable from data we already have, is objective, and has a 70-year track record. We acknowledge its limitations (growth companies trade above it — that's expected and the LLM notes it in the valuation explanation). DCF is deferred because its output depends entirely on assumptions we can't objectively source.

**Implication:** Valuation score for high-growth companies will systematically skew lower (they trade above Graham Number by design). The LLM explanation must contextualise this — a high-quality growth company trading at 2x Graham Number is not necessarily overvalued.

---

## T-009: LLM Model Selection — GPT-4o vs Finance-Specific Alternatives

**Phase:** 2 — Analysis
**Context:** We researched whether a finance-specific or higher-performing LLM should replace GPT-4o.

**Researched alternatives:**
- BloombergGPT: embedded in Bloomberg Terminal ($30K/user/year). No public API. Not viable.
- FinGPT: open-source, HuggingFace only. Self-hosted. No public API.
- Claude Sonnet 4.6: 63.3% on Finance Agent benchmark — state of the art. $3/$15 per M tokens.
- Claude Opus 4.6: 87.82% on FinanceReasoning benchmark, 60.7% on Finance Agent. $5/$25 per M tokens.
- Gemini 3.1 Pro: 86.55% on FinanceReasoning. Competitive.
- GPT-4o: solid baseline, good mathematical reasoning, well-established.

**Constraint:** CLAUDE.md Rule 7 mandates "Use OpenAI API only (not Anthropic) for demo purposes."

**Decision:** Keep GPT-4o, constrained by Rule 7.
The LLM's role in Phase 2 is narrow: it receives pre-computed signals and explains them in plain English. The quality difference between GPT-4o and Claude Sonnet 4.6 for narrating a Piotroski score is marginal. The intelligence lives in `signals.py`, not the LLM.

**Upgrade path:** If Rule 7 is lifted, swap to Claude Sonnet 4.6 — better financial reasoning benchmarks, larger context window, similar pricing to GPT-4o.

**Implication:** This decision can be reversed by changing a single model string in `analysis.py` and updating CLAUDE.md Rule 7. It does not affect any other part of the system.

---

## T-010: Score Derivation — Mechanical vs LLM Opinion

**Phase:** 2 — Signals
**Context:** Phase 1's `fundamentals_score` (1-10) and `valuation_score` (1-10) are produced by GPT-4o. They are not reproducible — the same input can yield a 7 one day and a 6 the next.

**Option A: Mechanically derived from signals (Python)**
`fundamentals_score` = formula over Piotroski score, ROCE trend, earnings quality flag.
`valuation_score` = formula over Graham Number discount/premium.
Pros: deterministic; auditable; explainable ("score is 8 because Piotroski=7, ROCE improving, high earnings quality"); interviewable.
Cons: formula is a simplification; may not capture nuance for unusual companies.

**Option B: LLM-generated (status quo)**
GPT-4o reads the signals and produces 1-10 scores.
Pros: holistic; can weight signals contextually.
Cons: not reproducible; changes with LLM updates; can't be explained precisely.

**Decision:** Option A (mechanical).
A score that can't be explained is not a score — it's a guess. For a research tool used to make investment decisions, reproducibility and explainability are non-negotiable.

**Implication:** The scoring formula is a simplification. We acknowledge this. The formula is documented in `signals.py` with comments explaining the rationale for each coefficient and threshold.

---

## T-011: Handling Missing Signal Data — Fail Hard vs Skip+Null

**Phase:** 2 — Signals
**Context:** Phase 1 uses a strict fail-hard policy (if any field is missing, raise immediately). Should `signals.py` follow the same policy?

**Option A: Fail hard**
If any signal cannot be computed (e.g. no cash flow data → can't compute OCF/NP ratio), raise `ValueError`.
Pros: consistent with Phase 1 philosophy; every gap is visible.
Cons: real Screener.in data has gaps — some companies don't report certain line items; this would make `compute_signals()` unusable for many valid tickers.

**Option B: Skip + mark null**
If a signal cannot be computed, set it to `None` with a `reason` string explaining why (e.g. `{"value": None, "reason": "cash flow data unavailable"}`). Compute all other signals normally.
Pros: robust; real tickers work even with partial data; the LLM's explanation acknowledges gaps.
Cons: produces partial signal output; the LLM must handle `None` gracefully.

**Decision:** Option B (skip + null).
Phase 1's fail-hard policy is correct for the scraper — HTML structure gaps are bugs to fix. Signal computation gaps are a property of the data, not a bug. Failing hard would make the signal engine useless for a significant portion of real tickers.

**Implication:** Every signal field in `signals.py` output can be `None`. The LLM prompt must explicitly handle this case and not hallucinate values for missing signals.

---

## T-012: Piotroski UI — Summary Badge vs Full Breakdown

**Phase:** 2 — Frontend
**Context:** The Piotroski F-Score has 9 individual binary sub-signals. How much detail to show in the UI?

**Option A: Summary only**
Show the total score (e.g. "7/9") and a label ("Financially strong"). Sub-signals hidden in an expander.
Pros: clean; scannable; doesn't overwhelm casual users.
Cons: hides the specific signals that passed or failed — less useful for research.

**Option B: Full breakdown visible**
Show all 9 sub-signals as ✓/✗ with labels. Total score and DuPont table also visible without expanding.
Pros: full transparency; each signal tells the user something specific ("OCF > Net Income ✗ — earnings quality concern"); useful for research.
Cons: dense; information-heavy.

**Decision:** Option B (full breakdown).
This is a research tool for an analyst, not a consumer app. The user explicitly requested maximum transparency. Dense information is a feature, not a bug.

**Implication:** The Streamlit UI for Phase 2 will be substantially more information-dense than Phase 1. This is intentional.
