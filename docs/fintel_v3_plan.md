# Fintel v3 — Session State & Resumption Doc

> Read this at the start of every new session. Last updated: 2026-06-27.

---

## What Fintel Is

AI-powered investment research tool. Original version: scraped Screener.in (Indian stocks, NSE tickers) → computed ~40 signals in Python → ran a single brief agent → returned structured investment brief.

**Pivot decided (2026-06-27):** Moved from Indian equities to **US equities (NYSE/NASDAQ)**. Reason: user actively invests in US markets, yfinance makes data layer trivial vs Screener.in scraping, and all threshold literature (Piotroski, Graham, Damodaran, Altman) is written for US markets — no Indian recalibration layer needed.

---

## Bugs Fixed (all closed, committed, pushed)

All 5 bugs from the pre-v3 audit are resolved:

| Bug | File | Status |
|-----|------|--------|
| Interest coverage UI showed "—" always | `frontend/app.py:371` | Already fixed before session |
| Cache hits wrote duplicate history rows | `src/api.py`, `src/memory.py` | Already fixed before session |
| `compute_signals()` mutated caller's input dict | `src/signals.py:1805-1806` | **Fixed this session** — commit `1bc429d` |
| No schema validation after JSON parse in brief | `src/brief.py:291-305` | Already fixed before session |
| Schedule API failures were silent | `src/scraper.py:227-238` | Already fixed before session |

---

## v3 Architecture (target state)

```
yfinance + SEC EDGAR          (replaces Screener.in scraper)
        ↓
Signals (same logic, US field names + WACC updated)
        ↓
Tool-Use Research Agent       (src/agent.py — NEW)
  ├── get_signal_context()    → Neo4j knowledge graph
  ├── get_peer_multiples()    → live yfinance
  ├── get_sec_filings_summary() → SEC EDGAR
  ├── get_momentum()          → signals.py
  └── get_news_sentiment()    → yfinance.news
        ↓
LLM-as-Judge Evals            (src/evals.py — NEW)
        ↓
Brief output                  (existing schema, USD)
```

---

## Phases

### Phase 0 — Research Week (IN PROGRESS — user doing this now)
**Goal:** Build knowledge graph schema on paper before touching Neo4j or writing code.

**Reading list (user's task):**

| Source | What to extract | Status |
|--------|----------------|--------|
| Piotroski 2000 paper, sections 2-4 | 9 F-score components + score ≥ 8 = strong, ≤ 2 = distressed | To read |
| Graham "Intelligent Investor" Ch.14-15 | PE < 15 AND PB < 1.5 (joint condition), Graham Number derivation, margin of safety | To read |
| Altman 1968 paper + Altman 1995 revised | Z > 2.99 = safe, 1.81-2.99 = grey, < 1.81 = distress. 1995 version for non-manufacturing | To read |
| Damodaran data files (Jan 2026) | Sector medians for PE, PB, PS, WACC, margins, ROIC | IN PROGRESS |

**Damodaran files to download** from `pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/`:
- `pedata.xls` → PE by sector (column: Median PE)
- `pbdata.xls` → PB by sector
- `mgnroc.xls` → margins + ROIC by sector (Net Margin, Pre-tax Operating Margin, ROIC)
- `wacc.xls` → WACC + Cost of Equity + Beta by sector
- `psdata.xls` → PS ratio by sector

**5 sectors chosen to start:**
1. Software (Internet) — SaaS, big tech
2. Semiconductor — NVDA, AMD
3. Retail (General) — WMT, TGT, AMZN
4. Biotechnology — high-risk health
5. Banks (Regional) — mid-size US banks

**For each sector, record:**
- Exact Damodaran industry label (his names are specific, e.g. "Software (System & Application)")
- Median PE, PB, PS, EV/EBITDA, Net Margin, ROIC, WACC
- Number of companies in sample (more = more reliable)

**Where user left off:** Couldn't find `wacc.xls` and `mgnroc.xls` directly. Explanation given: these are on the datafile page, labelled "Cost of Capital by Sector" and "Margins by Sector". User needs to download these, note values for 5 sectors, then return to start Phase 1.

**Output of Phase 0:** `docs/knowledge_graph_schema.md` — every node type + properties, every edge + meaning, every threshold with citation, sector overrides.

---

### Phase 1 — Replace Scraper with yfinance + SEC EDGAR (NOT STARTED)

**New file:** `src/data_fetcher.py` (replaces `src/scraper.py`)
**New file:** `src/sec_filings.py` (replaces `src/filings.py`)
**Remove:** `src/scraper.py`, `src/filings.py`

**Key data structure changes:**
- `sales` → `revenue`
- `net_profit` → `net_income`
- `promoter_holding` → `insider_ownership_pct`
- `pledged_pct` → `short_interest_pct`
- All currency: INR/Cr → USD/M
- `bank_ratios`: NPA/NIM/CAR → NPL ratio / NIM / Tier 1 capital (US equivalents)

**Signal changes in `src/signals.py`:**
- WACC proxy: 12% (India hardcoded) → sector-specific from Neo4j (default fallback 9%)
- DCF terminal growth: 4% → 2.5% (US long-run GDP)
- `_compute_promoter_risk()` → `_compute_insider_risk()`
- Remove `.env` vars: `SCREENER_EMAIL`, `SCREENER_PASSWORD`
- Add `.env` vars: nothing new (yfinance is unauthenticated)

---

### Phase 2 — Neo4j Knowledge Graph (NOT STARTED)

**Setup:**
```bash
docker run -p 7474:7474 -p 7687:7687 neo4j
```
Add to `requirements.txt`: `neo4j`
Add to `.env`: `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`

**Node types:**
```
Signal       {name: str, description: str, unit: str}
Sector       {name: str, gics_code: str, damodaran_label: str}
MacroFactor  {name: str}
Threshold    {value: float, operator: str, label: str, source: str, year: int}
PeerGroup    {name: str, tickers: list[str]}
```

**Edge types:**
```
(Signal)-[:HAS_THRESHOLD {sector: str, macro_condition: str}]->(Threshold)
(Signal)-[:DEPENDS_ON]->(Signal)
(Signal)-[:VARIES_BY]->(Sector)
(Signal)-[:VARIES_BY]->(MacroFactor)
(Sector)-[:HAS_HISTORICAL_RANGE {metric: str, p25: float, median: float, p75: float, period: str}]->(Sector)
```

**New file:** `src/knowledge_graph.py` — 3 tool-callable functions:
```python
get_signal_context(signal: str, sector: str) -> dict
get_peer_multiples(ticker: str, metric: str) -> dict
get_signal_dependencies(signal: str) -> list[str]
```

---

### Phase 3 — Tool-Use Research Agent (NOT STARTED)

**New file:** `src/agent.py` (replaces `generate_brief()` logic in `src/brief.py`)
**Modified:** `src/api.py` (call agent instead of `generate_brief`)
**Modified:** `src/llm.py` (add tool-use capable call function)

**Agent loop pattern:**
```python
messages = [system_prompt, user_message_with_thesis]
while True:
    response = client.chat.completions.create(model="gpt-4o", tools=tools, messages=messages)
    if response.choices[0].finish_reason == "stop":
        break
    tool_results = execute_tool_calls(response.choices[0].message.tool_calls)
    messages.extend([response.choices[0].message, tool_results])
# Safety cap: max 10 tool calls, log warning if hit
```

**Tools available to agent:**
```python
get_signal_context(signal, sector)       # → Neo4j
get_peer_multiples(ticker, metric)       # → yfinance
get_momentum(ticker)                     # → signals.py
get_sec_filings_summary(ticker)          # → SEC EDGAR
get_news_sentiment(ticker)               # → yfinance.news
get_signal_dependencies(signal)          # → Neo4j
```

---

### Phase 4 — LLM-as-Judge Eval Framework (NOT STARTED)

**New files:** `src/evals.py`, `tests/test_evals.py`

**Rubric (5 dimensions, 1-5 each):**
- CONSISTENCY — verdict matches signals (Piotroski, ROCE, DCF all support it)
- SPECIFICITY — price targets grounded in actual numbers
- RED_FLAG_VALIDITY — red flags supported by signal data, not hallucinated
- THESIS_ADDRESSED — user thesis directly engaged
- INTERNAL_CONSISTENCY — bull > base > bear price targets, scenarios coherent

**Bias corrections:**
- Strip prose to bullets before scoring (verbosity bias)
- Position randomisation when comparing two briefs (position bias)
- CoT forcing: judge must cite specific signal before each score (sycophancy)

**Meta-eval:**
- 5 deliberately bad briefs → must score < 2.5 avg
- 5 deliberately good briefs → must score > 4.0 avg

---

## How to Resume in a New Session

Start a new Claude Code session in the fintel repo and say:

> "Read `docs/fintel_v3_plan.md` and resume Fintel v3 from where we left off."

Claude will read this file and have full context. No need to re-explain the project, the pivot, the bugs, or the architecture.

---

## Key Decisions Made (don't re-litigate these)

| Decision | Rationale |
|----------|-----------|
| Pivot to US equities | User invests in US markets; yfinance removes scraper fragility; all threshold literature is US-based |
| Keep signals.py logic | ~80% reusable; only field names and constants change |
| Neo4j for thresholds | Agent needs grounded, citable reasoning — not hallucinated cutoffs |
| Tool-use agent over single brief call | LLM decides what to investigate based on user's thesis — more agentic, better CV story |
| 5 sectors to start | Software, Semiconductor, Retail, Biotech, Regional Banks — covers most retail investor use cases; expand later |
| yfinance unauthenticated | No API key needed; free; covers all US equities |
| SEC EDGAR for filings | Structured XBRL, free API, replaces BSE scraping |
