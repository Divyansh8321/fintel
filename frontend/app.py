# ============================================================
# FILE: frontend/app.py
# PURPOSE: Streamlit UI for Fintel. Accepts an NSE ticker,
#          calls the FastAPI backend, and displays the
#          investment brief and raw company data.
# INPUT:   User-entered ticker string
# OUTPUT:  Rendered investment brief + full JSON data
# DEPENDS: streamlit, requests, src/api.py running on :8000
# ============================================================

import requests
import streamlit as st

API_URL = "http://localhost:8000/analyze"

st.title("Fintel — AI Investment Research")
st.caption("Indian stocks powered by Screener.in + GPT-4o")

ticker = st.text_input("NSE Ticker", placeholder="e.g. RELIANCE, INFY, TCS").strip().upper()

col_btn1, col_btn2 = st.columns([3, 1])
analyze_clicked = col_btn1.button("Analyze", disabled=not ticker)
clear_clicked   = col_btn2.button("Clear Cache", disabled=not ticker)

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

if analyze_clicked:
    with st.spinner(f"Fetching data for {ticker}…"):
        try:
            resp = requests.post(API_URL, json={"ticker": ticker}, timeout=120)
            resp.raise_for_status()
            result = resp.json()
        except requests.exceptions.ConnectionError:
            st.error("Cannot connect to the API. Is `uvicorn src.api:app --reload` running?")
            st.stop()
        except requests.exceptions.HTTPError as e:
            detail = resp.json().get("detail", str(e))
            st.error(f"Error {resp.status_code}: {detail}")
            st.stop()

    source = result.get("source", "live")
    st.success(f"Served from **{source}** {'(cached)' if source == 'cache' else '(live scrape)'}")

    brief = result.get("brief", {})

    col1, col2 = st.columns(2)
    col1.metric("Fundamentals", f"{brief.get('fundamentals_score', '—')} / 10")
    col2.metric("Valuation", f"{brief.get('valuation_score', '—')} / 10")

    st.subheader("Verdict")
    st.write(brief.get("verdict", ""))

    if brief.get("risk_flags"):
        st.subheader("Risk Flags")
        for flag in brief["risk_flags"]:
            st.warning(flag)

    with st.expander("Fundamentals detail"):
        st.write(brief.get("fundamentals_explanation", ""))

    with st.expander("Valuation detail"):
        st.write(brief.get("valuation_explanation", ""))

    with st.expander("Full raw data (JSON)"):
        st.json(result.get("data", {}))
