# INSPIRATION.md — Reference Projects for Fintel's Ambitious Design

This file documents the two open-source projects that inspired Fintel's Phase 3–6 architecture.
Read this when you want to understand what we're trying to build and why specific design decisions were made.

Repos:
- **ai-hedge-fund**: https://github.com/virattt/ai-hedge-fund
- **dexter**: https://github.com/virattt/dexter

---

## 1. ai-hedge-fund

### What It Is

A simulation of an AI-powered hedge fund. Given a ticker and date range, it runs a panel of
21 analyst agents inspired by legendary investors. Each agent analyses the stock from its own
lens (value, growth, quality, momentum, etc.) and produces a structured investment signal.
A Risk Manager and Portfolio Manager then combine the signals into a final portfolio action
(buy/sell/hold + position sizing).

The project is explicitly educational — it is NOT a real trading system. It demonstrates
multi-agent orchestration for financial analysis.

---

### Architecture

```
                    ┌─────────────────────────────────┐
                    │         LangGraph Graph          │
                    │                                  │
  ticker + date ───▶│  start_node                     │
                    │     │                           │
                    │     ▼ (parallel fan-out)        │
                    │  [11 investor agents]            │
                    │  [5 analytical agents]           │
                    │     │                           │
                    │     ▼ (fan-in)                  │
                    │  risk_management_node            │
                    │     │                           │
                    │     ▼                           │
                    │  portfolio_management_node       │
                    │     │                           │
                    └─────┼───────────────────────────┘
                          ▼
                   final decision + rationale
```

**Orchestration:** LangGraph — a directed acyclic graph where nodes are agent calls and edges
define execution order. Investor agents can fan out in parallel. Risk and Portfolio nodes
are sequential (they need all investor signals before running).

**State:** A shared `AgentState` TypedDict flows through the graph. Each agent appends its
signal to `state["analyst_signals"]`. The Risk Manager reads all signals. The Portfolio Manager
reads all signals + risk assessment.

**Data source:** `yfinance` for US stock prices and fundamentals (not applicable to Indian markets).

---

### The 11 Investor-Philosophy Agents

Each agent is a LangGraph node. It receives the shared state (price data, fundamentals, news)
and returns a structured signal `{"action": "buy"|"sell"|"hold", "confidence": 0.0–1.0, "reasoning": str}`.

| Agent | Philosophy | Key heuristics |
|-------|-----------|---------------|
| **Warren Buffett** | Economic moat + owner earnings | ROIC > 15%; FCF yield; moat analysis via LLM narrative |
| **Charlie Munger** | Mental models + quality at fair price | Compounding ROCE; management quality signals; avoid complexity |
| **Benjamin Graham** | Deep value + margin of safety | Graham Number; net-net working capital; earnings stability over 10yr |
| **Peter Lynch** | Growth at reasonable price (GARP) | PEG ratio < 1.0; insider ownership; "invest in what you know" |
| **Phil Fisher** | Scuttlebutt + growth quality | R&D spend trend; management retention; profit margin durability |
| **Michael Burry** | Contrarian + hidden risk | High short interest; balance sheet stress; FCF vs reported earnings delta |
| **Bill Ackman** | Concentrated activist | Business quality score; management accountability signals; capital allocation |
| **Cathie Wood** | Disruptive innovation + TAM | Revenue growth acceleration; R&D / revenue ratio; addressable market |
| **Stanley Druckenmiller** | Macro-driven + momentum | Earnings estimate revisions; macro regime; price momentum |
| **Mohnish Pabrai** | Clone investing + low risk | Cloning other great investors' positions; Pabrai checklist (moat, mgmt, price) |
| **Rakesh Jhunjhunwala** | India-specific value + growth | Indian market cycles; promoter holding; sector tailwinds |

**Note:** Jhunjhunwala is the only India-adapted agent in ai-hedge-fund. Fintel adapts ALL agents
for Indian markets (NSE/BSE data, Indian macro rates, Indian GAAP).

---

### The 5 Analytical Agents

These are data-processing agents, not philosophy agents. They compute structured outputs
from raw data to feed the investor agents.

| Agent | What it computes |
|-------|----------------|
| **Fundamentals** | Revenue growth, margin trends, ROIC, debt ratios, payout ratio |
| **Technicals** | RSI, MACD, Bollinger Bands, volume trends, 52w position |
| **Valuation** | DCF intrinsic value, PE/PB/EV-EBITDA vs peers, PEG ratio |
| **Sentiment** | Insider transactions, short interest, news sentiment, analyst revisions |
| **Growth** | Revenue CAGR (1/3/5yr), earnings acceleration, margin expansion rate |

In Fintel, the equivalent analytical work is done by `signals.py` (pure Python, no LLM)
which produces all the quantitative signals these agents would compute.

---

### The 2 Orchestration Agents

| Agent | What it does |
|-------|-------------|
| **Risk Manager** | Reads all 11 investor signals + 5 analytical outputs. Produces a risk assessment: position sizing limits, portfolio concentration flags, tail risk warnings. |
| **Portfolio Manager** | Reads all signals + risk assessment. Makes final decision: action (buy/sell/hold), quantity (shares), confidence, and combined rationale from all agents. |

In Fintel, `synthesis.py` plays the combined role of Risk Manager + Portfolio Manager.

---

### Valuation Models in ai-hedge-fund

**Multi-stage DCF (used by Valuation agent and Buffett agent):**
- Stage 1 (years 1–5): analyst's growth forecast
- Stage 2 (years 6–10): mean-reversion growth (half of stage 1)
- Terminal: Gordon Growth Model (risk-free rate + modest premium)
- Discount rate: WACC computed from beta, risk-free rate (10yr Treasury), equity risk premium
- Output: intrinsic value per share, margin of safety %

**Owner Earnings Model (Buffett agent):**
- Owner Earnings = Net Income + Depreciation/Amortization − Maintenance Capex − ΔWorking Capital
- Represents true cash generation available to owners
- More conservative than FCF because it excludes growth capex

**PE/PB Comparables (Valuation agent):**
- Current PE vs 5-year historical average PE
- Current PB vs sector peers
- EV/EBITDA vs peers
- Requires peer data (Phase 3 / peer comparison in Fintel's roadmap)

---

### Backtesting Engine

ai-hedge-fund includes a full backtesting module:
- Run the multi-agent pipeline over historical dates
- Track hypothetical portfolio value day by day
- Metrics: Sharpe ratio, Sortino ratio, max drawdown, win rate, total return
- Output: equity curve chart, trade log, summary statistics

**Fintel does NOT implement backtesting in Phase 3–6.** It is a future phase (Phase 7+).

---

### Tech Stack

| Component | Technology |
|-----------|-----------|
| Agent orchestration | LangGraph (Python) |
| LLM calls | OpenAI GPT-4o via LangChain |
| Data | yfinance (US stocks) |
| Backend | FastAPI |
| Frontend | React + TypeScript (full SPA) |
| Portfolio state | Python TypedDict passed through LangGraph |

**Why Fintel chose a simpler stack:**
- LangGraph adds a dependency and graph abstraction for what is 5 sequential Python function calls.
  Fintel uses a plain pipeline in `synthesis.py`. Migrate to LangGraph if agentic loops are needed.
- React frontend adds complexity. Fintel uses Streamlit (much faster to iterate on for a research tool).
- yfinance doesn't work for Indian stocks. Fintel uses Screener.in.

See TRADEOFFS.md T-014 for the full LangGraph vs simple pipeline decision.

---

## 2. Dexter

### What It Is

An autonomous financial research agent. You give it a question or company name and it
autonomously uses 16 tools to research the answer — searching the web, reading SEC filings,
querying financial databases, using its own persistent memory — and streams a detailed
research report back to you in real time.

Dexter is NOT a pre-defined pipeline. It is a true agentic loop: it decides which tools to call,
in what order, how many times, based on what it finds. The agent keeps going until it has
a comprehensive answer or hits a tool call limit.

**Tech stack:** TypeScript + Bun (not Python). Uses Anthropic's Claude models (not GPT-4o).

---

### Architecture

```
user question
     │
     ▼
  Agent Loop (tool-calling)
     │
     │  ┌──────────────────────────────────────────────┐
     │  │  Claude (claude-opus-4-5 or sonnet)          │
     │  │  receives: question + conversation history   │
     │  │  + available tools + SOUL.md instructions    │
     │  │  produces: <thinking> + tool calls           │
     └──│──────────────────────────────────────────────│
        │                                              │
        ▼ (tool call)                                  │
   [tool execution]                                    │
        │                                              │
        └──────── tool result → back to Claude ────────┘
                        (loop until done)
     │
     ▼
  streamed output (Server-Sent Events)
     │
     ▼
  frontend (React)
```

The agent loop continues until Claude outputs a final answer (no more tool calls) or hits
the soft tool limit (enforced by Jaccard similarity check — stops circular tool use).

---

### All 16 Tools

| Tool | What it does |
|------|-------------|
| `financial_search` | Queries financial databases (Polygon.io, Alpha Vantage) for price data, fundamentals, ratios |
| `read_filings` | Downloads and parses SEC EDGAR filings (10-K, 10-Q, 8-K) — two-stage LLM planning |
| `browser` | Headless browser (Playwright) for any web page — reads financial news, company sites |
| `memory_search` | Semantic vector search over all past research the agent has done |
| `memory_save` | Saves a research finding to persistent memory (SQLite + vector embeddings) |
| `web_search` | DuckDuckGo/Bing web search for general research |
| `calculate` | Safe Python expression evaluator — arithmetic, ratios, DCF computations |
| `get_price_history` | Historical OHLCV data for a ticker |
| `get_fundamentals` | Key financial ratios and annual financials for a ticker |
| `get_news` | Recent news headlines for a company or topic |
| `get_earnings` | Historical EPS and earnings surprise data |
| `get_insiders` | Insider buy/sell transactions |
| `get_short_interest` | Short interest % and days to cover |
| `run_skill` | Executes a pre-defined research skill (markdown workflow file) |
| `get_company_info` | Basic company metadata (sector, market cap, description, CIK number) |
| `list_skills` | Lists available skills the agent can run |

**India adaptation for Fintel:**
- `financial_search` → Screener.in scraper (`scraper.py`) — already built
- `read_filings` → BSE announcements API + PDF reader (`filings.py`) — Phase 5
- `memory_search` / `memory_save` → `memory.py` with SQLite history — Phase 6
- `calculate` → `signals.py` (Python computes all signals) — already built
- `get_news` → `news.py` via NewsAPI — already built
- `browser`, `web_search` — not needed for current phases (Screener + BSE cover data needs)

---

### Persistent Memory System

**The problem:** Each conversation is stateless. The agent forgets everything between sessions.
Research that took 10 minutes to produce is lost.

**Dexter's solution:**
1. **SQLite table `memories`:** stores every saved finding as text
2. **Vector embeddings:** each memory is embedded (OpenAI `text-embedding-3-small`)
3. **Semantic search:** `memory_search` tool finds the top-K most relevant memories via cosine similarity
4. **Usage:** When researching a company, the agent first searches memory: "What do I know about AAPL?"
   If it finds prior research, it uses it as context and only fetches what's changed.

**What Fintel implements in Phase 6 (simplified):**
- No vector embeddings (overkill for a single-user tool with <100 tickers).
- Instead: SQLite `analyst_history` table stores every analysis result by ticker + date.
- `memory.py` exposes `get_history(ticker)` which retrieves the last N analysis snapshots.
- The synthesis prompt in Phase 6+ receives prior scores: "Last 3 analyses of RELIANCE: 7.2 (hold), 7.8 (hold), 8.1 (buy) — trend improving."
- Watchlist: `watchlist` table tracks user-added tickers with target prices and notes.

See TRADEOFFS.md for why we chose simple SQLite history over vector embeddings.

---

### SEC Filing RAG (Two-Stage LLM Planning)

**The challenge:** A 10-K filing is 100–300 pages. Feeding the whole PDF to an LLM is expensive
and exceeds context windows. You need to find the relevant sections first.

**Dexter's two-stage approach:**
1. **Stage 1 — Planning:** Send the filing's table of contents + the user's question to a cheap LLM
   (`claude-haiku`). Ask it: "Which sections are relevant to this question?" Returns a list of
   section numbers/page ranges.
2. **Stage 2 — Extraction:** Extract only the relevant sections from the PDF using `pdfplumber`.
   Send extracted text to a more capable LLM (`claude-sonnet`) for the actual analysis.

**Cost saving:** Stage 1 costs ~$0.001 (haiku, ToC only). Stage 2 costs ~$0.02 (sonnet, relevant sections only).
Without this, sending the whole PDF would cost ~$0.50+ per filing.

**What Fintel implements in Phase 5 (simplified for BSE):**
- BSE PDFs are typically 1–10 pages (earnings releases, dividend announcements) — not 200-page 10-Ks.
- Single-stage: download PDF → extract all text → send to `gpt-4o-mini` for 3-sentence summary.
- No table-of-contents planning needed for short BSE announcements.
- Cache aggressively (7-day TTL — filings don't change after publication).

---

### Skills System

Skills are markdown files that define reusable research workflows. Example skill `dcf_analysis.md`:

```markdown
# DCF Analysis Skill

## Steps
1. Use `get_fundamentals` to fetch revenue, FCF, CapEx for the last 5 years
2. Use `calculate` to compute average FCF margin and revenue CAGR
3. Use `calculate` to build a 3-stage DCF: growth phase (5yr), transition (5yr), terminal
4. Use `calculate` to discount all cash flows at WACC = 10%
5. Compare DCF value to current market cap and report margin of safety

## Output format
Return: intrinsic_value (float), market_cap (float), margin_of_safety_pct (float), assumptions (dict)
```

The agent calls `run_skill("dcf_analysis")` and the skill runs as a sub-loop.

**Fintel equivalent:** The five analyst agents in `src/agents/` are the Fintel equivalent of skills —
pre-defined research workflows, each from a specific investing lens. They are Python functions
rather than markdown files, but serve the same purpose: reusable, structured analysis patterns.

---

### Event Streaming

Dexter streams its output as Server-Sent Events (SSE) in real time:
- `thinking` events: the agent's internal reasoning (shown in a collapsible panel)
- `tool_call` events: which tool is being called and with what arguments
- `tool_result` events: what the tool returned
- `text` events: the agent's narrative output as it writes

The React frontend updates in real time as events arrive — users see the agent working live.

**Fintel Phase 3+:** Currently blocking (no streaming). The 5 analyst calls + 1 synthesis call
take ~30–40s total. Phase 3 does not stream — you see a spinner then the full result.
Future phase: add SSE streaming to FastAPI endpoint + Streamlit `st.empty()` live updates.

---

### SOUL.md — Agent Philosophy

Dexter has a `SOUL.md` file — a set of principles baked into the agent's system prompt:

> "You are a rigorous financial analyst. You never make claims you can't support with data.
> When data is missing, you say so explicitly rather than guessing.
> You distinguish between facts (from filings/data) and your analysis (your interpretation).
> You never confuse a price target with an investment recommendation.
> You always show your work."

Key principles:
1. **Source everything** — every claim must cite which tool/document it came from
2. **Uncertainty is explicit** — "I cannot find cash flow data for this period"
3. **Separate facts from interpretation** — data vs analysis are clearly labelled
4. **Never hallucinate numbers** — if data is unavailable, return null not a guess
5. **Progressive refinement** — start broad, get specific as evidence accumulates

**How Fintel embeds these principles:**
- Rule 5 (No Silent Failures) = principle 2: null signals rather than guesses
- Agent system prompts include: "You MUST NOT recompute signals. If a signal is null, say so."
- TRADEOFFS.md = principle 1: every architectural choice is sourced and reasoned
- signals.py `reason` strings = principle 2: "cash flow data unavailable" not 0

---

### Prompt Caching (Anthropic-specific)

Dexter uses Anthropic's prompt caching feature:
- The system prompt (SOUL.md + tool definitions + company context) is ~4,000 tokens
- This is sent with every tool call in the agent loop
- With prompt caching, only the first call pays full price — subsequent calls in the same
  conversation are served from cache at 90% cost reduction
- For a 20-tool-call research session, this saves ~$0.15–0.50 per analysis

**Fintel note:** Fintel uses OpenAI (not Anthropic), so this specific feature doesn't apply.
If Rule 7 is ever changed to allow Anthropic models, prompt caching would significantly
reduce the cost of 6 GPT-4o calls per analysis.

---

### Immutable Audit Trail (JSONL Scratchpad)

Every tool call and result in a Dexter session is appended to an immutable JSONL file:
```
{"timestamp": "2024-01-15T10:23:01Z", "event": "tool_call", "tool": "read_filings", "args": {...}}
{"timestamp": "2024-01-15T10:23:05Z", "event": "tool_result", "tool": "read_filings", "result": "..."}
```

This creates a complete, replayable audit trail of how any conclusion was reached.

**Fintel equivalent:** The `analyst_history` table in Phase 6 `memory.py` stores the full signals
snapshot alongside every analysis — so you can see exactly what data drove a past recommendation.

---

## 3. How Fintel Maps to These Projects

### ai-hedge-fund → Fintel Mapping

| ai-hedge-fund feature | Fintel equivalent | Phase |
|----------------------|------------------|-------|
| 11 investor agents | 5 analyst agents (Value, Growth, Quality, Contrarian, Momentum) | Phase 3 |
| 5 analytical agents | `signals.py` — pure Python, no LLM | Phase 2 ✅ |
| Risk Manager agent | Contrarian analyst (surfaces red flags) | Phase 3 |
| Portfolio Manager agent | `synthesis.py` (weighted consensus) | Phase 3 |
| LangGraph orchestration | Simple sequential pipeline in `synthesis.py` | Phase 3 |
| Multi-stage DCF | 3-stage DCF with fixed WACC=12% in `signals.py` | Phase 4 |
| Owner Earnings model | Value agent computes OE = NI + D&A − capex − ΔWC | Phase 3 |
| Backtesting engine | Future (Phase 7+) | — |
| React frontend | Streamlit (simpler, faster to iterate) | Phase 3 Batch 4 |
| yfinance data | Screener.in scraper | Phase 1 ✅ |

**What we deliberately didn't copy:**
- LangGraph: adds a dependency for what is 5 sequential function calls. Not needed yet.
- 21 agents: 5 is sufficient for the investing philosophy coverage we need. More agents = more latency + cost.
- Backtesting: significant scope addition; deferred to Phase 7.
- React frontend: Streamlit is faster for a single-user research tool.

---

### dexter → Fintel Mapping

| dexter feature | Fintel equivalent | Phase |
|---------------|------------------|-------|
| `financial_search` tool | `scraper.py` (Screener.in) | Phase 1 ✅ |
| `get_news` tool | `news.py` (NewsAPI) | Phase 2 ✅ |
| `calculate` tool | `signals.py` (all quantitative signals) | Phase 2 ✅ |
| `read_filings` tool (SEC) | `filings.py` (BSE announcements API) | Phase 5 |
| `memory_save` / `memory_search` | `memory.py` (SQLite history, no vectors) | Phase 6 |
| Skills system | `src/agents/` (5 analyst agents as Python functions) | Phase 3 |
| Two-stage filing RAG | Single-stage (BSE PDFs are short, not 200-page 10-Ks) | Phase 5 |
| Event streaming (SSE) | Blocking for now; future phase to add SSE | Future |
| Agentic loop (tool-calling) | Static pipeline (scrape → signals → agents → synthesis) | Current |
| Vector embeddings memory | Not needed — simple SQLite history suffices for <100 tickers | Phase 6 |
| Prompt caching | N/A (OpenAI, not Anthropic) | — |
| SOUL.md philosophy | Rule 5 + agent system prompts + signals.py `reason` strings | Throughout |

**What we deliberately didn't copy:**
- Autonomous agentic loop: Fintel uses a fixed pipeline, not open-ended tool-calling. For a
  research tool with a known workflow (scrape → signal → explain), a fixed pipeline is more
  predictable, cheaper, and easier to debug.
- TypeScript/Bun: Fintel is Python throughout. No reason to split stacks.
- Vector embeddings: For <100 tickers, SQLite full-text search is fast enough. Vectors would
  add `sentence-transformers` or an OpenAI embeddings API call as a new dependency.
- 16 tools: Fintel's data needs are fully covered by Screener.in + NewsAPI + BSE. No need for
  the full tool suite that Dexter needs for arbitrary US stock research.
