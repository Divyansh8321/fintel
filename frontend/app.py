# ============================================================
# FILE: frontend/app.py
# PURPOSE: Streamlit UI for Fintel v2. Deep research brief
#          dashboard: signal panel, single deep brief with
#          bull/base/bear scenarios, conviction drivers, red
#          flags, moat, verdict + sizing, and conversational
#          follow-up chat. Replaces the five-analyst panel.
# INPUT:   User-entered NSE ticker + optional thesis string
# OUTPUT:  Full research dashboard + brief + chat interface
# DEPENDS: streamlit, requests, src/api.py running on :8000
# ============================================================

import os

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

_API_BASE    = os.getenv("FINTEL_API_BASE", "http://localhost:8000")
API_URL      = f"{_API_BASE}/analyze"
CHAT_URL     = f"{_API_BASE}/chat"
_API_HEADERS = {"X-API-Key": os.getenv("FINTEL_API_KEY", "")}

st.set_page_config(page_title="Fintel", page_icon="📈", layout="wide")
st.title("Fintel — AI Investment Research")
st.caption("Indian stocks · Screener.in data · DeepSeek deep brief engine · v2")

# ---------------------------------------------------------------------------
# Sidebar — Watchlist panel
# ---------------------------------------------------------------------------

with st.sidebar:
    # -----------------------------------------------------------------------
    # Telemetry panel — cost + latency at a glance
    # -----------------------------------------------------------------------
    st.header("API Telemetry")
    try:
        tm_resp = requests.get(f"{_API_BASE}/telemetry", headers=_API_HEADERS, timeout=5)
        tm = tm_resp.json() if tm_resp.status_code == 200 else {}
    except requests.exceptions.ConnectionError:
        tm = {}

    if tm:
        tm_c1, tm_c2 = st.columns(2)
        tm_c1.metric("Total calls", tm.get("total_calls", 0))
        tm_c2.metric("Total cost", f"${tm.get('total_cost_usd', 0):.4f}")
        st.metric("Avg latency", f"{tm.get('avg_latency_ms', 0):.0f} ms")

        by_type = tm.get("by_type", [])
        if by_type:
            with st.expander("By call type"):
                for row in by_type:
                    st.write(
                        f"**{row['call_type']}** — "
                        f"{row['calls']} calls · "
                        f"${row['cost_usd']:.4f} · "
                        f"{row['avg_latency_ms']:.0f} ms avg"
                    )

        recent = tm.get("recent", [])
        if recent:
            with st.expander("Last 10 calls"):
                for r in recent[:10]:
                    st.caption(
                        f"{r['called_at'][11:19]} UTC · "
                        f"**{r['call_type']}** · "
                        f"{r['ticker'] or '—'} · "
                        f"{r['tokens_in']}→{r['tokens_out']} tok · "
                        f"${r['cost_usd']:.5f} · "
                        f"{r['latency_ms']:.0f} ms"
                    )
    else:
        st.caption("No telemetry yet — run an analysis first.")

    st.divider()

    st.header("Watchlist")

    try:
        wl_resp  = requests.get(f"{_API_BASE}/watchlist", headers=_API_HEADERS, timeout=5)
        watchlist = wl_resp.json().get("watchlist", []) if wl_resp.status_code == 200 else []
    except requests.exceptions.ConnectionError:
        watchlist = []

    if watchlist:
        for item in watchlist:
            wl_col1, wl_col2 = st.columns([3, 1])
            wl_col1.markdown(f"**{item['ticker']}**")
            if item.get("note"):
                wl_col1.caption(item["note"])
            if wl_col2.button("✕", key=f"rm_{item['ticker']}", help=f"Remove {item['ticker']}"):
                try:
                    rm_resp = requests.delete(
                        f"{_API_BASE}/watchlist/{item['ticker']}",
                        headers=_API_HEADERS,
                        timeout=5,
                    )
                    if rm_resp.status_code == 200:
                        st.rerun()
                    else:
                        st.error(f"Failed to remove {item['ticker']}")
                except requests.exceptions.ConnectionError:
                    st.error("API not reachable.")
    else:
        st.caption("No tickers yet. Add one below.")

    st.divider()

    with st.form("add_watchlist_form", clear_on_submit=True):
        new_ticker = st.text_input("Ticker", placeholder="e.g. INFY").strip().upper()
        new_note   = st.text_input("Note (optional)", placeholder="e.g. Watch Q3 results")
        add_submitted = st.form_submit_button("Add to Watchlist")

    if add_submitted and new_ticker:
        try:
            add_resp = requests.post(
                f"{_API_BASE}/watchlist",
                json={"ticker": new_ticker, "note": new_note},
                headers=_API_HEADERS,
                timeout=5,
            )
            if add_resp.status_code == 200:
                st.success(f"{new_ticker} added.")
                st.rerun()
            else:
                st.error(f"Failed: {add_resp.text}")
        except requests.exceptions.ConnectionError:
            st.error("API not reachable.")

# ---------------------------------------------------------------------------
# Input row — ticker + thesis + buttons
# ---------------------------------------------------------------------------

ticker_col, btn_col1, btn_col2 = st.columns([4, 1, 1])
ticker = ticker_col.text_input(
    "NSE Ticker", placeholder="e.g. RELIANCE, INFY, TCS", label_visibility="collapsed"
).strip().upper()
analyze_clicked = btn_col1.button("Analyze", disabled=not ticker, use_container_width=True)
clear_clicked   = btn_col2.button("Clear Cache", disabled=not ticker, use_container_width=True)

thesis = st.text_area(
    "Your thesis (optional)",
    placeholder=(
        "What's drawing you to this stock? "
        "e.g. 'I think the new management will drive margin expansion' "
        "or 'I'm bearish — worried about the debt load'. Leave blank for a neutral view."
    ),
    height=80,
    label_visibility="visible",
)

if clear_clicked and ticker:
    try:
        resp = requests.delete(f"{_API_BASE}/cache/{ticker}", headers=_API_HEADERS, timeout=10)
        if resp.status_code == 200:
            st.success(f"Cache cleared for **{ticker}**. Next Analyze will fetch live data.")
        elif resp.status_code == 404:
            st.info(f"No cached entry for **{ticker}** — nothing to clear.")
        else:
            st.error(f"Failed to clear cache: {resp.text}")
    except requests.exceptions.ConnectionError:
        st.error("Cannot connect to the API.")

if not analyze_clicked:
    st.stop()

# ---------------------------------------------------------------------------
# Fetch data
# ---------------------------------------------------------------------------

with st.spinner(f"Fetching data for **{ticker}** — scraping + signals + news + deep brief…"):
    try:
        resp = requests.post(
            API_URL,
            json={"ticker": ticker, "thesis": thesis},
            headers=_API_HEADERS,
            timeout=300,
        )
        resp.raise_for_status()
        result = resp.json()
    except requests.exceptions.ConnectionError:
        st.error("Cannot connect to the API. Is `uvicorn src.api:app --reload` running?")
        st.stop()
    except requests.exceptions.HTTPError as e:
        detail = resp.json().get("detail", str(e))
        st.error(f"Error {resp.status_code}: {detail}")
        st.stop()

source  = result.get("source", "live")
data    = result.get("data")
signals = result.get("signals")
news    = result.get("news")
filings = result.get("filings")
brief   = result.get("brief", {})

if data is None or signals is None:
    st.error("Unexpected API response — missing 'data' or 'signals'. Try clearing the cache.")
    st.stop()

# Store brief + signals in session_state for the chat interface
st.session_state["brief"]   = brief
st.session_state["signals"] = signals
st.session_state["ticker"]  = ticker
if "chat_history" not in st.session_state or st.session_state.get("ticker") != ticker:
    st.session_state["chat_history"] = []

header       = data.get("header", {})
source_label = "cached" if source == "cache" else "live scrape"
st.success(f"**{header.get('name', ticker)}** — served from **{source}** ({source_label})")

# ---------------------------------------------------------------------------
# Row 1 — Key metrics snapshot
# ---------------------------------------------------------------------------

st.divider()
r1c1, r1c2, r1c3, r1c4, r1c5 = st.columns(5)

r1c1.metric("Fundamentals", f"{signals.get('fundamentals_score', '—')} / 10")
r1c2.metric("Valuation", f"{signals.get('valuation_score', '—')} / 10")

news_sentiment = news.get("sentiment", "neutral") if news else "unavailable"
_SENTIMENT_ICON = {"bullish": "🟢", "neutral": "⚪", "bearish": "🔴", "unavailable": "⚫"}
r1c3.metric("News Sentiment", f"{_SENTIMENT_ICON.get(news_sentiment, '')} {news_sentiment.title()}")

kr = data.get("key_ratios", {})
r1c4.metric("PE", f"{kr.get('pe', '—')}x" if kr.get("pe") else "—")
r1c5.metric("ROCE", f"{kr.get('roce', '—')}%" if kr.get("roce") else "—")

# ---------------------------------------------------------------------------
# Row 2 — Piotroski F-Score
# ---------------------------------------------------------------------------

st.divider()
p = signals.get("piotroski", {})
piotroski_score = p.get("score")
piotroski_label = p.get("label", "")

st.subheader(f"Piotroski F-Score: {piotroski_score if piotroski_score is not None else '—'} / 9 — {piotroski_label}")

_SIGNAL_LABELS = {
    "roa_positive":             "ROA positive",
    "ocf_positive":             "Operating cash flow positive",
    "roa_improving":            "ROA improving YoY",
    "ocf_exceeds_net_income":   "OCF > Net income (earnings quality)",
    "leverage_decreasing":      "Leverage decreasing",
    "current_ratio_improving":  "Current ratio improving YoY",
    "no_dilution":              "No share dilution",
    "gross_margin_improving":   "Gross margin improving",
    "asset_turnover_improving": "Asset turnover improving",
}

p_sigs = p.get("signals", {})
p_cols = st.columns(3)
for i, (key, label) in enumerate(_SIGNAL_LABELS.items()):
    val = p_sigs.get(key)
    icon = "✅" if val == 1 else ("❌" if val == 0 else "➖")
    p_cols[i % 3].write(f"{icon} {label}")

# ---------------------------------------------------------------------------
# Row 3 — DuPont + Earnings Quality
# ---------------------------------------------------------------------------

st.divider()
dc1, dc2 = st.columns(2)

with dc1:
    st.subheader("DuPont Decomposition")
    dup = signals.get("dupont", {})
    if dup.get("net_margin") is not None:
        st.markdown(
            f"**Net Margin** {dup['net_margin']:.1f}% × "
            f"**Asset Turnover** {dup['asset_turnover']:.2f}x × "
            f"**Leverage** {dup['leverage']:.2f}x = "
            f"**ROE** {dup['roe_computed']:.1f}%"
        )
        st.caption(f"ROE driver: **{dup.get('roe_driver', '—')}**")
    else:
        st.write("DuPont data unavailable.")

with dc2:
    st.subheader("Earnings Quality")
    eq = signals.get("earnings_quality", {})
    flag = eq.get("quality_flag")
    _EQ_ICON = {"high": "🟢 High", "medium": "🟡 Medium", "low": "🔴 Low"}
    st.markdown(f"**Quality:** {_EQ_ICON.get(flag, '—')}")
    if eq.get("ocf_to_net_profit") is not None:
        st.write(f"OCF / Net Profit: **{eq['ocf_to_net_profit']:.2f}x**")
    if eq.get("fcf_to_net_profit") is not None:
        st.write(f"FCF / Net Profit: **{eq['fcf_to_net_profit']:.2f}x**")

# ---------------------------------------------------------------------------
# Row 4 — Valuation (Graham Number + DCF)
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Valuation")

vc1, vc2, vc3 = st.columns(3)
val = signals.get("valuation", {})

if val.get("graham_number") is not None:
    prem     = val["price_to_graham"]
    prem_pct = prem * 100
    direction = "premium" if prem > 0 else "discount"
    vc1.metric(
        "Graham Number",
        f"₹{val['graham_number']:,.0f}",
        delta=f"{abs(prem_pct):.1f}% {direction}",
        delta_color="inverse",
    )
else:
    vc1.metric("Graham Number", "—")

vc2.metric("PE Ratio", f"{val.get('pe_current', '—')}x" if val.get("pe_current") else "—")
vc3.metric(
    "Earnings Yield",
    f"{val['earnings_yield']:.2f}%" if val.get("earnings_yield") is not None else "—"
)

_DCF_VERDICT_ICON = {
    "undervalued":   "🟢 Undervalued",
    "fairly_valued": "🟡 Fairly valued",
    "overvalued":    "🔴 Overvalued",
}
dcf_intrinsic = val.get("dcf_intrinsic_value")
dcf_verdict   = val.get("dcf_verdict")
dcf_mos       = val.get("dcf_margin_of_safety")
dcf_g1        = val.get("dcf_stage1_growth")
dcf_reason    = val.get("dcf_intrinsic_value_reason")

dc1v, dc2v, dc3v = st.columns(3)
if dcf_intrinsic is not None:
    dc1v.metric("DCF Intrinsic Value", f"₹{dcf_intrinsic:,.0f}")
    dc2v.metric(
        "Margin of Safety",
        f"{dcf_mos * 100:+.1f}%" if dcf_mos is not None else "—",
        delta_color="normal",
    )
    dc3v.metric("DCF Verdict", _DCF_VERDICT_ICON.get(dcf_verdict, dcf_verdict or "—"))
    if dcf_g1 is not None:
        st.caption(f"Stage-1 growth rate used: **{dcf_g1:.1f}%** · WACC: 12% · Terminal: 4%")
else:
    dc1v.metric("DCF Intrinsic Value", "—")
    if dcf_reason:
        st.caption(f"DCF unavailable: {dcf_reason}")

# ---------------------------------------------------------------------------
# Row 5 — Quarterly Momentum + Balance Sheet
# ---------------------------------------------------------------------------

st.divider()
mc1, mc2 = st.columns(2)

with mc1:
    st.subheader("Quarterly Momentum")
    qm = signals.get("quarterly_momentum", {})
    rev_yoy  = qm.get("revenue_yoy_pct")
    pnl_yoy  = qm.get("profit_yoy_pct")
    opm_trend = qm.get("opm_trend", "—")
    mc1.metric("Revenue YoY", f"{rev_yoy:+.1f}%" if rev_yoy is not None else "—")
    mc1.metric("Profit YoY",  f"{pnl_yoy:+.1f}%" if pnl_yoy is not None else "—")
    mc1.caption(f"OPM trend: **{opm_trend}**")

with mc2:
    st.subheader("Balance Sheet Health")
    bsh = signals.get("balance_sheet_health", {})
    ce  = signals.get("capital_efficiency", {})
    mc2.metric("Debt/Equity", f"{bsh.get('debt_to_equity_latest', '—')}x" if bsh.get("debt_to_equity_latest") is not None else "—")
    mc2.metric("Interest Coverage", f"{bsh.get('interest_coverage', '—')}x" if bsh.get("interest_coverage") is not None else "—")
    mc2.caption(f"Debt trend: **{bsh.get('debt_trend', '—')}** · ROCE trend: **{ce.get('roce_trend', '—')}**")

# ---------------------------------------------------------------------------
# Row 6 — Promoter Risk
# ---------------------------------------------------------------------------

pr = signals.get("promoter_risk", {})
pledge_pct   = pr.get("pledged_pct", 0)
pledge_flag  = pr.get("pledge_flag", "none")
pledge_trend = pr.get("pledge_trend", "stable")
if pledge_flag != "none":
    st.warning(f"⚠️ Promoter pledging: {pledge_pct:.1f}% ({pledge_flag}) — trend: {pledge_trend}")

# ---------------------------------------------------------------------------
# Deep Research Brief
# ---------------------------------------------------------------------------

st.divider()
st.header("Deep Research Brief")

if brief.get("error"):
    st.error(f"Brief generation failed: {brief['error']}")
else:
    _ACTION_ICON = {"buy": "🟢 Buy", "hold": "🟡 Hold", "sell": "🔴 Sell", "avoid": "⚫ Avoid"}
    verdict = brief.get("verdict", "")
    sizing  = brief.get("sizing", "")

    # Verdict + sizing — top of brief
    verdict_col, sizing_col = st.columns([1, 3])
    with verdict_col:
        st.markdown(f"### {_ACTION_ICON.get(verdict, verdict.title())}")
    with sizing_col:
        if sizing:
            st.markdown(f"**Position sizing:** {sizing}")

    # Situation
    situation = brief.get("situation", "")
    if situation:
        st.markdown(f"**Situation:** {situation}")

    # User thesis addressed
    utha = brief.get("user_thesis_addressed")
    if utha:
        st.info(f"**On your thesis:** {utha}")

    st.divider()

    # Bull / Base / Bear cases
    case_col1, case_col2, case_col3 = st.columns(3)

    bull = brief.get("bull_case", {})
    with case_col1:
        st.markdown("**Bull Case**")
        st.write(bull.get("narrative", "—"))
        target = bull.get("price_target_inr")
        if target:
            st.metric("Target", f"₹{target:,.0f}")

    base = brief.get("base_case", {})
    with case_col2:
        st.markdown("**Base Case**")
        st.write(base.get("narrative", "—"))
        target = base.get("price_target_inr")
        if target:
            st.metric("Target", f"₹{target:,.0f}")

    bear = brief.get("bear_case", {})
    with case_col3:
        st.markdown("**Bear Case**")
        st.write(bear.get("narrative", "—"))
        target = bear.get("price_target_inr")
        if target:
            st.metric("Target", f"₹{target:,.0f}")

    st.divider()

    # Buy on dip
    dip = brief.get("buy_on_dip", {})
    dip_level = dip.get("level_inr")
    dip_rationale = dip.get("rationale", "")
    if dip_level or dip_rationale:
        dip_txt = f"**Buy on dip:**"
        if dip_level:
            dip_txt += f" ₹{dip_level:,.0f} —"
        if dip_rationale:
            dip_txt += f" {dip_rationale}"
        st.markdown(dip_txt)

    # Conviction drivers + Red flags
    drivers_col, flags_col = st.columns(2)

    with drivers_col:
        st.markdown("**Top 3 Conviction Drivers**")
        for driver in brief.get("conviction_drivers", []):
            st.write(f"✅ {driver}")

    with flags_col:
        st.markdown("**Top 3 Red Flags**")
        for flag in brief.get("red_flags", []):
            st.write(f"⚠️ {flag}")

    # Moat assessment
    moat = brief.get("moat", "")
    if moat:
        st.markdown(f"**Moat:** {moat}")

# ---------------------------------------------------------------------------
# News panel
# ---------------------------------------------------------------------------

if news and news.get("articles"):
    st.divider()
    st.subheader(f"Recent News — {_SENTIMENT_ICON.get(news_sentiment, '')} {news_sentiment.title()}")
    st.caption(news.get("sentiment_reason", ""))
    for article in news["articles"]:
        pub   = article.get("published_at", "")[:10]
        src   = article.get("source", "")
        url   = article.get("url", "")
        title = article.get("title", "")
        if url:
            st.markdown(f"- [{title}]({url}) — *{src}*, {pub}")
        else:
            st.markdown(f"- {title} — *{src}*, {pub}")

# ---------------------------------------------------------------------------
# BSE Filings panel
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Recent BSE Filings")

if filings is None:
    bse_code_display = data.get("header", {}).get("bse_code", "")
    if not bse_code_display:
        st.caption("BSE code not found for this ticker — filings unavailable.")
    else:
        st.caption("Filings could not be fetched.")
elif filings.get("error"):
    st.warning(f"Could not fetch BSE filings: {filings['error']}")
elif not filings.get("filings"):
    st.caption("No recent BSE announcements found.")
else:
    for filing in filings["filings"]:
        f_title    = filing.get("title", "Untitled")
        f_date     = filing.get("date", "")
        f_category = filing.get("category", "")
        f_pdf_url  = filing.get("pdf_url")
        f_summary  = filing.get("summary")
        header_line = f"{f_date}  ·  {f_category}  ·  {f_title}" if (f_date or f_category) else f_title
        with st.expander(header_line):
            if f_summary:
                st.write(f_summary)
            else:
                st.caption("Summary unavailable (image-only PDF or download failed).")
            if f_pdf_url:
                st.markdown(f"[View PDF on BSE]({f_pdf_url})")

# ---------------------------------------------------------------------------
# Historical Score Chart
# ---------------------------------------------------------------------------

st.divider()
st.subheader(f"Analysis History — {ticker}")

try:
    hist_resp    = requests.get(f"{_API_BASE}/history/{ticker}", headers=_API_HEADERS, timeout=5)
    history_runs = hist_resp.json().get("runs", []) if hist_resp.status_code == 200 else []
except requests.exceptions.ConnectionError:
    history_runs = []

if history_runs:
    chart_rows = []
    for run in reversed(history_runs):
        score = run.get("consensus")
        if score is not None:
            label = run["run_at"][:16].replace("T", " ")
            chart_rows.append({"date": label, "consensus": score})

    if chart_rows:
        chart_data = {row["date"]: row["consensus"] for row in chart_rows}
        st.bar_chart(chart_data, y_label="Consensus Score (1–10)", x_label="Run date (UTC)")
        st.caption(
            f"{len(history_runs)} run(s) recorded · latest consensus: "
            f"{history_runs[0].get('consensus', '—')} · "
            f"verdict: **{history_runs[0].get('verdict', '—')}**"
        )
    else:
        st.info("Runs recorded but no consensus scores yet.")

    with st.expander(f"All runs ({len(history_runs)})"):
        for run in history_runs:
            cols = st.columns([3, 2, 2])
            cols[0].write(run["run_at"][:19].replace("T", " ") + " UTC")
            cols[1].write(f"Score: **{run['consensus'] or '—'}**")
            cols[2].write(f"Verdict: **{run['verdict'] or '—'}**")
else:
    st.info("No history yet for this ticker. Run an analysis to start tracking.")

# ---------------------------------------------------------------------------
# Conversational Follow-up Chat
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Ask a follow-up question")
st.caption(
    "Ask anything about this company — the analyst will answer using the brief and signals already in memory. "
    "No re-fetching."
)

# Render existing chat history
for msg in st.session_state.get("chat_history", []):
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# Chat input
question = st.chat_input("Ask a follow-up question about this stock…")
if question:
    # Append user message immediately
    st.session_state["chat_history"].append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.write(question)

    # Call /chat endpoint
    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            try:
                chat_resp = requests.post(
                    CHAT_URL,
                    json={
                        "ticker":          st.session_state.get("ticker", ticker),
                        "question":        question,
                        "brief":           st.session_state.get("brief", {}),
                        "signals_summary": st.session_state.get("signals", {}),
                    },
                    headers=_API_HEADERS,
                    timeout=60,
                )
                chat_resp.raise_for_status()
                answer = chat_resp.json().get("answer", "No answer returned.")
            except requests.exceptions.ConnectionError:
                answer = "Cannot connect to the API."
            except requests.exceptions.HTTPError as e:
                answer = f"API error: {e}"

        st.write(answer)
        st.session_state["chat_history"].append({"role": "assistant", "content": answer})

# ---------------------------------------------------------------------------
# Raw data expanders — useful for debugging
# ---------------------------------------------------------------------------

st.divider()
with st.expander("Full raw data (JSON)"):
    st.json(data)

with st.expander("Full signals (JSON)"):
    st.json(signals)

with st.expander("Full brief (JSON)"):
    st.json(brief)
