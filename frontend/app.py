# ============================================================
# FILE: frontend/app.py
# PURPOSE: Streamlit UI for Fintel. Phase 3 information-dense
#          research dashboard: signal panel (Piotroski, DuPont,
#          Graham Number, earnings quality, quarterly momentum),
#          five analyst note panels, synthesis verdict panel,
#          analyst score comparison bar chart, and recent news.
# INPUT:   User-entered NSE ticker string
# OUTPUT:  Full multi-analyst research dashboard
# DEPENDS: streamlit, requests, src/api.py running on :8000
# ============================================================

import requests
import streamlit as st

API_URL = "http://localhost:8000/analyze"

st.set_page_config(page_title="Fintel", page_icon="📈", layout="wide")
st.title("Fintel — AI Investment Research")
st.caption("Indian stocks · Screener.in data · GPT-4o multi-analyst engine · Phase 3")

# ---------------------------------------------------------------------------
# Input row
# ---------------------------------------------------------------------------

ticker_col, btn_col1, btn_col2 = st.columns([4, 1, 1])
ticker = ticker_col.text_input(
    "NSE Ticker", placeholder="e.g. RELIANCE, INFY, TCS", label_visibility="collapsed"
).strip().upper()
analyze_clicked = btn_col1.button("Analyze", disabled=not ticker, use_container_width=True)
clear_clicked   = btn_col2.button("Clear Cache", disabled=not ticker, use_container_width=True)

if clear_clicked and ticker:
    try:
        resp = requests.delete(f"http://localhost:8000/cache/{ticker}", timeout=10)
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

with st.spinner(f"Fetching data for **{ticker}** — scraping + signals + news + 5 analysts + synthesis…"):
    try:
        resp = requests.post(API_URL, json={"ticker": ticker}, timeout=300)
        resp.raise_for_status()
        result = resp.json()
    except requests.exceptions.ConnectionError:
        st.error("Cannot connect to the API. Is `uvicorn src.api:app --reload` running?")
        st.stop()
    except requests.exceptions.HTTPError as e:
        detail = resp.json().get("detail", str(e))
        st.error(f"Error {resp.status_code}: {detail}")
        st.stop()

# Hard-index required keys — KeyError surfaces immediately if API shape is wrong.
source    = result.get("source", "live")
data      = result["data"]
signals   = result["signals"]
news      = result.get("news")
# API returns analyst_notes as a list; convert to dict keyed by lens for easy lookup.
agents    = {n["lens"]: n for n in result["analyst_notes"]}
synthesis = result["synthesis"]   # consensus verdict dict

header = data.get("header", {})

source_label = "cached" if source == "cache" else "live scrape"
st.success(f"**{header.get('name', ticker)}** — served from **{source}** ({source_label})")

# ---------------------------------------------------------------------------
# Row 1 — Scores + company snapshot
# ---------------------------------------------------------------------------

st.divider()
r1c1, r1c2, r1c3, r1c4, r1c5 = st.columns(5)

r1c1.metric("Fundamentals", f"{signals.get('fundamentals_score', '—')} / 10")
r1c2.metric("Valuation", f"{signals.get('valuation_score', '—')} / 10")

# News sentiment badge
news_sentiment = news.get("sentiment", "neutral") if news else "unavailable"
_SENTIMENT_ICON = {"bullish": "🟢", "neutral": "⚪", "bearish": "🔴", "unavailable": "⚫"}
r1c3.metric("News Sentiment", f"{_SENTIMENT_ICON.get(news_sentiment, '')} {news_sentiment.title()}")

kr = data.get("key_ratios", {})
r1c4.metric("PE", f"{kr.get('pe', '—')}x" if kr.get("pe") else "—")
r1c5.metric("ROCE", f"{kr.get('roce', '—')}%"  if kr.get("roce") else "—")

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
# Row 4 — Valuation (Graham Number)
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Valuation")

vc1, vc2, vc3 = st.columns(3)
val = signals.get("valuation", {})

if val.get("graham_number") is not None:
    prem = val["price_to_graham"]
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

# ---------------------------------------------------------------------------
# Row 5 — Quarterly Momentum + Balance Sheet
# ---------------------------------------------------------------------------

st.divider()
mc1, mc2 = st.columns(2)

with mc1:
    st.subheader("Quarterly Momentum")
    qm = signals.get("quarterly_momentum", {})
    rev_yoy = qm.get("revenue_yoy_pct")
    pnl_yoy = qm.get("profit_yoy_pct")
    opm_trend = qm.get("opm_trend", "—")
    mc1.metric("Revenue YoY", f"{rev_yoy:+.1f}%" if rev_yoy is not None else "—")
    mc1.metric("Profit YoY",  f"{pnl_yoy:+.1f}%" if pnl_yoy is not None else "—")
    mc1.caption(f"OPM trend: **{opm_trend}**")

with mc2:
    st.subheader("Balance Sheet Health")
    bsh = signals.get("balance_sheet_health", {})
    ce = signals.get("capital_efficiency", {})
    mc2.metric("Debt/Equity", f"{bsh.get('debt_to_equity_latest', '—')}x" if bsh.get("debt_to_equity_latest") is not None else "—")
    mc2.metric("Interest Coverage", f"{bsh.get('interest_coverage', '—')}x" if bsh.get("interest_coverage") is not None else "—")
    mc2.caption(f"Debt trend: **{bsh.get('debt_trend', '—')}** · ROCE trend: **{ce.get('roce_trend', '—')}**")

# ---------------------------------------------------------------------------
# Row 6 — Promoter Risk
# ---------------------------------------------------------------------------

pr = signals.get("promoter_risk", {})
pledge_pct = pr.get("pledged_pct", 0)
pledge_flag = pr.get("pledge_flag", "none")
pledge_trend = pr.get("pledge_trend", "stable")
if pledge_flag != "none":
    st.warning(f"⚠️ Promoter pledging: {pledge_pct:.1f}% ({pledge_flag}) — trend: {pledge_trend}")

# ---------------------------------------------------------------------------
# Phase 3 — Multi-Analyst Panel
# ---------------------------------------------------------------------------

st.divider()
st.header("Multi-Analyst Research Panel")

_LENS_LABELS = {
    "value":      "Value (Graham)",
    "growth":     "Growth (Lynch)",
    "quality":    "Quality (Munger)",
    "contrarian": "Contrarian (Burry)",
    "momentum":   "Momentum",
}
_ACTION_ICON = {"buy": "🟢 Buy", "hold": "🟡 Hold", "sell": "🔴 Sell", "avoid": "⚫ Avoid"}

# -----------------------------------------------------------------------
# Analyst score comparison bar chart
# Each analyst returns a score 1–10. We plot them side by side so the
# reader can immediately see which lenses are bullish vs bearish.
# -----------------------------------------------------------------------

# Build {label: score} dict, skipping any agent that errored out.
score_data = {}
for lens, note in agents.items():
    if "error" not in note and note.get("score") is not None:
        score_data[_LENS_LABELS.get(lens, lens.title())] = note["score"]

st.subheader("Analyst Score Comparison (1–10)")
st.bar_chart(score_data, height=250)

# -----------------------------------------------------------------------
# Five analyst note panels — rendered in a fixed 5-column grid.
# Each panel shows: score, action badge, thesis, key signals, risks.
# -----------------------------------------------------------------------

st.subheader("Analyst Notes")
note_cols = st.columns(5)

_DISPLAY_ORDER = ["value", "growth", "quality", "contrarian", "momentum"]
for col_idx, lens in enumerate(_DISPLAY_ORDER):
    note  = agents.get(lens, {})
    col   = note_cols[col_idx]
    label = _LENS_LABELS.get(lens, lens.title())

    with col:
        st.markdown(f"**{label}**")

        # If this agent errored, show a minimal error state.
        if "error" in note:
            st.error(f"Agent error: {note['error']}")
            continue

        # Score and action in compact form.
        score  = note.get("score", "—")
        action = note.get("action", "")
        st.metric("Score", f"{score} / 10")
        st.write(_ACTION_ICON.get(action, action.title()))

        # Investment thesis (full text — primary read).
        thesis = note.get("thesis", "")
        if thesis:
            st.caption(thesis)

        # Key signals that drove the score.
        key_signals = note.get("key_signals", [])
        if key_signals:
            st.markdown("**Key signals:**")
            for sig in key_signals:
                st.write(f"• {sig}")

        # Risks flagged by this analyst.
        risks = note.get("risks", [])
        if risks:
            st.markdown("**Risks:**")
            for risk in risks:
                st.write(f"⚠ {risk}")

# -----------------------------------------------------------------------
# Synthesis verdict panel
# Shows the weighted consensus score, bull/bear case, and final verdict.
# -----------------------------------------------------------------------

st.divider()
st.subheader("Synthesis — Consensus Verdict")

syn_score   = synthesis.get("weighted_score")
# Derive the display action from the action_tally (most-voted action wins).
_tally      = synthesis.get("action_tally", {})
syn_action  = max(_tally, key=_tally.get) if _tally else ""
syn_verdict = synthesis.get("verdict", "")

sv1, sv2 = st.columns([1, 4])
sv1.metric(
    "Consensus Score",
    f"{syn_score:.1f} / 10" if syn_score is not None else "—",
)
sv2.markdown(f"### {_ACTION_ICON.get(syn_action, syn_action.title())}")

if syn_verdict:
    st.write(syn_verdict)

# Bull / bear case in two columns.
bull = synthesis.get("bull_case", "")
bear = synthesis.get("bear_case", "")
if bull or bear:
    bc1, bc2 = st.columns(2)
    with bc1:
        st.markdown("**Bull case**")
        st.write(bull or "—")
    with bc2:
        st.markdown("**Bear case**")
        st.write(bear or "—")

# Per-analyst weight breakdown — in an expander to keep the main view clean.
weights = synthesis.get("effective_weights", {})
if weights:
    with st.expander("Score weights breakdown"):
        for lens, w in weights.items():
            lbl  = _LENS_LABELS.get(lens, lens.title())
            note = agents.get(lens, {})
            sc   = note.get("score", "—") if "error" not in note else "error"
            st.write(f"**{lbl}**: score {sc}/10 · weight {w*100:.0f}%")

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
# Raw data expanders — useful for debugging
# ---------------------------------------------------------------------------

st.divider()
with st.expander("Full raw data (JSON)"):
    st.json(data)

with st.expander("Full signals (JSON)"):
    st.json(signals)

with st.expander("Full agent notes (JSON)"):
    st.json(agents)

with st.expander("Full synthesis (JSON)"):
    st.json(synthesis)
