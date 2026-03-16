# ============================================================
# FILE: src/signals.py
# PURPOSE: Computes quantitative investment signals from the
#          raw financial data returned by src/scraper.py.
#          Pure Python -- no LLM, no network calls, no I/O.
#          All formulas are documented with their source and
#          interpretation. Missing data yields None + reason,
#          never an exception (see TRADEOFFS.md T-011).
# INPUT:   data (dict) -- full output of fetch_company_data()
# OUTPUT:  dict with 9 signal groups + 2 derived scores + DCF
# DEPENDS: math (stdlib only)
# ============================================================

import math


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _safe(values, idx):
    """
    Return values[idx] if it exists and is not None, else None.

    Used for all list accesses throughout signals computation to
    avoid IndexError on short time series.

    Args:
        values: list of values (may contain None entries)
        idx:    integer index (negative indices supported)

    Returns:
        values[idx] if valid, else None
    """
    if not isinstance(values, list) or len(values) == 0:
        return None
    try:
        v = values[idx]
        return v if v is not None else None
    except IndexError:
        return None


def _non_none(values):
    """
    Filter None values from a list and return a list of non-None floats.

    Args:
        values: list that may contain None entries

    Returns:
        list with all None entries removed
    """
    if not isinstance(values, list):
        return []
    return [v for v in values if v is not None]


def _trend(series, n):
    """
    Compute linear trend direction over the most recent n points of a
    newest-first series.

    Compares the oldest of the n points to the newest. A 5% tolerance
    band prevents noise from being labelled as a trend.

    Args:
        series: list of floats, newest-first (index 0 = most recent)
        n:      number of points to use

    Returns:
        "improving" | "stable" | "declining"
        Returns "stable" if insufficient data.
    """
    clean = _non_none(series[:n])
    if len(clean) < 2:
        return "stable"
    newest = clean[0]
    oldest = clean[-1]
    if oldest == 0:
        return "stable"
    change = (newest - oldest) / abs(oldest)
    if change > 0.05:
        return "improving"
    elif change < -0.05:
        return "declining"
    return "stable"


def _pct_change(new_val, old_val):
    """
    Safe percentage change: (new - old) / abs(old).

    Args:
        new_val: the more recent value
        old_val: the earlier value (denominator)

    Returns:
        float percentage change, or None if old_val is 0 or either is None
    """
    if new_val is None or old_val is None:
        return None
    if old_val == 0:
        return None
    return (new_val - old_val) / abs(old_val)


# ---------------------------------------------------------------------------
# Signal 1: Piotroski F-Score
# ---------------------------------------------------------------------------
# Source: Piotroski (2000), "Value Investing: The Use of Historical Financial
#         Statement Information to Separate Winners from Losers"
#
# 9 binary signals -- each is 1 (pass) or 0 (fail) or None (data missing).
# Score = sum of non-None signals (missing signals excluded from max).
# Labels: 0-2 = Distressed, 3-5 = Moderate, 6-9 = Financially strong.

def _compute_piotroski(data):
    """
    Compute Piotroski F-Score from annual financial data.

    Data mapping (all annual series are newest-first, index 0 = most recent):
    - pl_table.net_profit[0/1]        this/last year net profit
    - balance_sheet.total_assets[0/1] this/last year total assets
    - cash_flow.operating[0]          this year operating cash flow
    - balance_sheet.borrowings[0/1]   this/last year debt
    - balance_sheet.other_assets[0/1] / other_liabilities[0/1] -- YoY current ratio
    - key_ratios.current_ratio        fallback if schedule data absent
    - pl_table.eps[0/1]               this/last year EPS (dilution proxy)
    - pl_table.opm_pct[0/1]           operating margin proxy for gross margin
    - pl_table.sales[0/1]             for asset turnover computation

    Args:
        data: full dict from fetch_company_data()

    Returns:
        dict with keys: score (int|None), signals (dict), label (str)
    """
    pl = data.get("pl_table", {})
    bs = data.get("balance_sheet", {})
    cf = data.get("cash_flow", {})
    kr = data.get("key_ratios", {})

    signals = {}

    # F1: ROA positive (net income / total assets > 0)
    np0 = _safe(pl.get("net_profit"), 0)
    ta0 = _safe(bs.get("total_assets"), 0)
    if np0 is not None and ta0 is not None and ta0 != 0:
        signals["roa_positive"] = 1 if (np0 / ta0) > 0 else 0
    else:
        signals["roa_positive"] = None

    # F2: Operating cash flow positive
    ocf0 = _safe(cf.get("operating"), 0)
    if ocf0 is not None:
        signals["ocf_positive"] = 1 if ocf0 > 0 else 0
    else:
        signals["ocf_positive"] = None

    # F3: ROA improving year-over-year
    np1 = _safe(pl.get("net_profit"), 1)
    ta1 = _safe(bs.get("total_assets"), 1)
    if (np0 is not None and ta0 is not None and ta0 != 0 and
            np1 is not None and ta1 is not None and ta1 != 0):
        signals["roa_improving"] = 1 if (np0 / ta0) > (np1 / ta1) else 0
    else:
        signals["roa_improving"] = None

    # F4: OCF > Net Income (earnings quality -- cash backs reported profit)
    if ocf0 is not None and np0 is not None:
        signals["ocf_exceeds_net_income"] = 1 if ocf0 > np0 else 0
    else:
        signals["ocf_exceeds_net_income"] = None

    # F5: Long-term leverage ratio decreased (borrowings / total_assets)
    b0 = _safe(bs.get("borrowings"), 0)
    b1 = _safe(bs.get("borrowings"), 1)
    if (b0 is not None and ta0 is not None and ta0 != 0 and
            b1 is not None and ta1 is not None and ta1 != 0):
        signals["leverage_decreasing"] = 1 if (b0 / ta0) < (b1 / ta1) else 0
    else:
        signals["leverage_decreasing"] = None

    # F6: Current ratio improving YoY.
    # Current ratio = other_assets / other_liabilities (both now available as
    # time series from the balance sheet schedule API). Falls back to the single
    # key_ratios.current_ratio > 1.0 threshold if schedule data is absent.
    oa0 = _safe(bs.get("other_assets"), 0)
    oa1 = _safe(bs.get("other_assets"), 1)
    ol0 = _safe(bs.get("other_liabilities"), 0)
    ol1 = _safe(bs.get("other_liabilities"), 1)

    if (oa0 is not None and ol0 is not None and ol0 > 0 and
            oa1 is not None and ol1 is not None and ol1 > 0):
        cr0 = oa0 / ol0
        cr1 = oa1 / ol1
        signals["current_ratio_improving"] = 1 if cr0 > cr1 else 0
    else:
        # Fallback: single point from key_ratios, use > 1.0 threshold
        cr = kr.get("current_ratio")
        if cr is not None:
            signals["current_ratio_improving"] = 1 if cr > 1.0 else 0
        else:
            signals["current_ratio_improving"] = None

    # F7: No share dilution (EPS/NP ratio rising means fewer shares outstanding)
    eps0 = _safe(pl.get("eps"), 0)
    eps1 = _safe(pl.get("eps"), 1)
    if (eps0 is not None and np0 is not None and np0 != 0 and
            eps1 is not None and np1 is not None and np1 != 0):
        signals["no_dilution"] = 1 if (eps0 / np0) >= (eps1 / np1) else 0
    else:
        signals["no_dilution"] = None

    # F8: Gross margin improved (proxy: OPM% -- no gross profit field available)
    opm0 = _safe(pl.get("opm_pct"), 0)
    opm1 = _safe(pl.get("opm_pct"), 1)
    if opm0 is not None and opm1 is not None:
        signals["gross_margin_improving"] = 1 if opm0 > opm1 else 0
    else:
        signals["gross_margin_improving"] = None

    # F9: Asset turnover improved (sales / total_assets)
    s0 = _safe(pl.get("sales"), 0)
    s1 = _safe(pl.get("sales"), 1)
    if (s0 is not None and ta0 is not None and ta0 != 0 and
            s1 is not None and ta1 is not None and ta1 != 0):
        signals["asset_turnover_improving"] = 1 if (s0 / ta0) > (s1 / ta1) else 0
    else:
        signals["asset_turnover_improving"] = None

    computed = [v for v in signals.values() if v is not None]
    score = sum(computed) if computed else None

    if score is None:
        label = "Insufficient data"
    elif score <= 2:
        label = "Distressed"
    elif score <= 5:
        label = "Moderate"
    else:
        label = "Financially strong"

    return {"score": score, "signals": signals, "label": label}


# ---------------------------------------------------------------------------
# Signal 2: DuPont Decomposition
# ---------------------------------------------------------------------------
# ROE = Net Profit Margin x Asset Turnover x Equity Multiplier (Leverage)
# Source: DuPont Corporation analysis framework, 1920s; widely used in CFA.
#
# Decomposes ROE into three drivers -- knowing *why* ROE is high or low is
# more informative than the ROE number alone.

def _compute_dupont(data):
    """
    Decompose ROE into its three components for the most recent annual year.

    Components:
        net_margin      = net_profit / sales (as %)
        asset_turnover  = sales / total_assets
        leverage        = total_assets / total_equity
        roe_computed    = net_margin x asset_turnover x leverage

    ROE driver:
        leverage > 2.5 AND leverage contribution > 40% of ROE: "leverage"
        net_margin > 20% AND asset_turnover < 0.8:              "margins"
        asset_turnover > 1.5 AND net_margin < 10%:              "efficiency"
        otherwise:                                               "mixed"

    Args:
        data: full dict from fetch_company_data()

    Returns:
        dict with DuPont components and ROE driver label
    """
    pl = data.get("pl_table", {})
    bs = data.get("balance_sheet", {})

    result = {
        "latest_year":           _safe(pl.get("years"), 0),
        "net_margin":            None,
        "net_margin_reason":     None,
        "asset_turnover":        None,
        "asset_turnover_reason": None,
        "leverage":              None,
        "leverage_reason":       None,
        "roe_computed":          None,
        "roe_driver":            None,
    }

    try:
        np0  = _safe(pl.get("net_profit"), 0)
        s0   = _safe(pl.get("sales"), 0)
        ta0  = _safe(bs.get("total_assets"), 0)
        eq0  = _safe(bs.get("equity_capital"), 0)
        res0 = _safe(bs.get("reserves"), 0)

        if np0 is None or s0 is None or s0 == 0:
            result["net_margin_reason"] = "net_profit or sales unavailable"
        else:
            result["net_margin"] = round((np0 / s0) * 100, 2)

        if s0 is None or ta0 is None or ta0 == 0:
            result["asset_turnover_reason"] = "sales or total_assets unavailable"
        else:
            result["asset_turnover"] = round(s0 / ta0, 3)

        if ta0 is None or eq0 is None or res0 is None:
            result["leverage_reason"] = "total_assets or equity fields unavailable"
        else:
            total_equity = eq0 + res0
            if total_equity <= 0:
                result["leverage_reason"] = "total_equity <= 0 (negative book value)"
            else:
                result["leverage"] = round(ta0 / total_equity, 2)

        nm  = result["net_margin"]
        at  = result["asset_turnover"]
        lev = result["leverage"]

        if nm is not None and at is not None and lev is not None:
            roe = (nm / 100) * at * lev * 100
            result["roe_computed"] = round(roe, 2)

            if lev > 2.5:
                roe_no_lev = (nm / 100) * at * 1.0 * 100
                if roe != 0 and abs(roe - roe_no_lev) > abs(roe) * 0.4:
                    result["roe_driver"] = "leverage"
                    return result

            if nm > 20 and at < 0.8:
                result["roe_driver"] = "margins"
            elif at > 1.5 and nm < 10:
                result["roe_driver"] = "efficiency"
            else:
                result["roe_driver"] = "mixed"

    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# Signal 3: Earnings Quality
# ---------------------------------------------------------------------------
# Core question: is reported net profit backed by actual cash generation?
# FCF = Operating Cash Flow + Investing Cash Flow (investing is typically negative)

def _compute_earnings_quality(data):
    """
    Assess whether reported profits are backed by operating and free cash flows.

    Ratios:
        ocf_to_net_profit = cash_flow.operating[0] / pl_table.net_profit[0]
        fcf_to_net_profit = (operating[0] + investing[0]) / net_profit[0]

    Quality flags:
        "high"   -- ocf_to_np >= 0.9 AND fcf_to_np >= 0.7
        "medium" -- ocf_to_np >= 0.5
        "low"    -- otherwise

    Args:
        data: full dict from fetch_company_data()

    Returns:
        dict with ratios, quality_flag, and reason strings for any None fields
    """
    pl = data.get("pl_table", {})
    cf = data.get("cash_flow", {})

    result = {
        "ocf_to_net_profit":        None,
        "ocf_to_net_profit_reason": None,
        "fcf_to_net_profit":        None,
        "fcf_to_net_profit_reason": None,
        "quality_flag":             None,
    }

    try:
        np0  = _safe(pl.get("net_profit"), 0)
        ocf0 = _safe(cf.get("operating"), 0)
        inv0 = _safe(cf.get("investing"), 0)

        if np0 is None or np0 == 0:
            result["ocf_to_net_profit_reason"] = "net_profit unavailable or zero"
            result["fcf_to_net_profit_reason"] = "net_profit unavailable or zero"
            return result

        if ocf0 is None:
            result["ocf_to_net_profit_reason"] = "operating cash flow unavailable"
        else:
            result["ocf_to_net_profit"] = round(ocf0 / np0, 3)

        # FCF = OCF - CapEx. Use explicit capex field (negative = outflow).
        # Falls back to OCF + investing subtotal if capex schedule unavailable.
        capex0 = _safe(cf.get("capex"), 0)
        if capex0 is not None and ocf0 is not None:
            fcf = ocf0 + capex0  # capex is already negative
            result["fcf_to_net_profit"] = round(fcf / np0, 3)
        elif ocf0 is None or inv0 is None:
            result["fcf_to_net_profit_reason"] = "operating or investing cash flow unavailable"
        else:
            result["fcf_to_net_profit"] = round((ocf0 + inv0) / np0, 3)

        ocf_r = result["ocf_to_net_profit"]
        fcf_r = result["fcf_to_net_profit"]

        if ocf_r is None:
            pass
        elif ocf_r >= 0.9 and (fcf_r is None or fcf_r >= 0.7):
            result["quality_flag"] = "high"
        elif ocf_r >= 0.5:
            result["quality_flag"] = "medium"
        else:
            result["quality_flag"] = "low"

    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# Signal 4: Growth Quality
# ---------------------------------------------------------------------------
# Uses the pre-computed CAGR fields from the scraper (all guaranteed floats).

def _compute_growth_quality(data):
    """
    Assess revenue and profit CAGR trends and margin trajectory.

    Uses growth_rates dict (all guaranteed floats from scraper).
    Margin trend: latest OPM vs average of prior 3 years (5% threshold).
    Acceleration: 3yr CAGR vs 10yr CAGR (2pp threshold).

    Args:
        data: full dict from fetch_company_data()

    Returns:
        dict with CAGR fields, margin_trend, acceleration label
    """
    gr = data.get("growth_rates", {})
    pl = data.get("pl_table", {})

    result = {
        "revenue_cagr_10yr": gr.get("sales_cagr_10yr"),
        "revenue_cagr_5yr":  gr.get("sales_cagr_5yr"),
        "revenue_cagr_3yr":  gr.get("sales_cagr_3yr"),
        "profit_cagr_10yr":  gr.get("profit_cagr_10yr"),
        "profit_cagr_5yr":   gr.get("profit_cagr_5yr"),
        "profit_cagr_3yr":   gr.get("profit_cagr_3yr"),
        "margin_trend":      "stable",
        "acceleration":      "stable",
    }

    try:
        opm_series = pl.get("opm_pct", [])
        opm_now    = _safe(opm_series, 0)
        opm_prev   = _non_none(opm_series[1:4])

        if opm_now is not None and len(opm_prev) >= 1:
            avg_prev = sum(opm_prev) / len(opm_prev)
            if avg_prev != 0:
                change = (opm_now - avg_prev) / abs(avg_prev)
                if change > 0.05:
                    result["margin_trend"] = "expanding"
                elif change < -0.05:
                    result["margin_trend"] = "contracting"

        r3  = result["revenue_cagr_3yr"]
        r10 = result["revenue_cagr_10yr"]
        if r3 is not None and r10 is not None:
            diff = r3 - r10
            if diff > 2.0:
                result["acceleration"] = "accelerating"
            elif diff < -2.0:
                result["acceleration"] = "decelerating"

    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# Signal 5: Capital Efficiency
# ---------------------------------------------------------------------------

def _compute_capital_efficiency(data):
    """
    Assess ROCE trend, interest coverage, and working capital cycle trend.

    ROCE trend: ratios_table.roce (newest-first), last 5 points.
    Interest coverage: operating_profit[0] / interest[0].
    WC days: rising = "worsening" (more capital tied up in operations).

    Args:
        data: full dict from fetch_company_data()

    Returns:
        dict with roce_latest, roce_3yr_avg, roce_trend, interest_coverage, wc_trend
    """
    pl = data.get("pl_table", {})
    rt = data.get("ratios_table", {})

    result = {
        "roce_latest":                None,
        "roce_latest_reason":         None,
        "roce_3yr_avg":               None,
        "roce_3yr_avg_reason":        None,
        "roce_trend":                 None,
        "interest_coverage":          None,
        "interest_coverage_reason":   None,
        "working_capital_days_trend": None,
    }

    try:
        roce_series = rt.get("roce", [])
        roce_latest = _safe(roce_series, 0)

        if roce_latest is None:
            result["roce_latest_reason"] = "ROCE series unavailable in ratios_table"
        else:
            result["roce_latest"] = round(roce_latest, 2)

        recent = _non_none(roce_series[:3])
        if recent:
            result["roce_3yr_avg"] = round(sum(recent) / len(recent), 2)
        else:
            result["roce_3yr_avg_reason"] = "Insufficient ROCE data for 3yr average"

        result["roce_trend"] = _trend(roce_series, 5)

        op0  = _safe(pl.get("operating_profit"), 0)
        int0 = _safe(pl.get("interest"), 0)

        if op0 is None:
            result["interest_coverage_reason"] = "operating_profit unavailable"
        elif int0 is None:
            result["interest_coverage_reason"] = "interest expense unavailable"
        elif int0 == 0:
            result["interest_coverage"] = 9999.0  # debt-free
        else:
            result["interest_coverage"] = round(op0 / int0, 2)

        # Working capital days: rising = "worsening" (inverted from _trend)
        wc = rt.get("working_capital_days", [])
        if wc:
            raw = _trend(wc, 5)
            result["working_capital_days_trend"] = {
                "improving": "worsening",
                "declining": "improving",
                "stable":    "stable",
            }.get(raw, "stable")

    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# Signal 6: Balance Sheet Health
# ---------------------------------------------------------------------------

def _compute_balance_sheet_health(data, interest_coverage):
    """
    Assess debt trend and interest burden.

    Debt trend: borrowings[0] vs borrowings[2] (newest-first, 2 years ago).
    10% change threshold for "reducing" / "increasing".
    Interest coverage: reused from capital_efficiency.

    Args:
        data:               full dict from fetch_company_data()
        interest_coverage:  pre-computed float from _compute_capital_efficiency()

    Returns:
        dict with debt_to_equity_latest, debt_trend, interest_coverage
    """
    bs = data.get("balance_sheet", {})
    kr = data.get("key_ratios", {})

    result = {
        "debt_to_equity_latest":        None,
        "debt_to_equity_latest_reason": None,
        "debt_trend":                   None,
        "interest_coverage":            interest_coverage,
    }

    try:
        de = kr.get("debt_to_equity")
        if de is None:
            result["debt_to_equity_latest_reason"] = "None -- likely debt-free company"
            result["debt_to_equity_latest"] = 0.0
        else:
            result["debt_to_equity_latest"] = de

        b0 = _safe(bs.get("borrowings"), 0)
        b2 = _safe(bs.get("borrowings"), 2)

        if b0 is None or b2 is None:
            result["debt_trend"] = "stable"
        elif b2 == 0:
            result["debt_trend"] = "increasing" if b0 > 0 else "stable"
        else:
            chg = (b0 - b2) / abs(b2)
            if chg < -0.10:
                result["debt_trend"] = "reducing"
            elif chg > 0.10:
                result["debt_trend"] = "increasing"
            else:
                result["debt_trend"] = "stable"

    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# Signal 7a: 3-Stage DCF Valuation (Phase 4)
# ---------------------------------------------------------------------------
# Discounted Cash Flow model using free cash flow to firm (FCFF).
# WACC is fixed at 12% (Indian equity market baseline -- see TRADEOFFS.md).
#
# Stage structure (per CLAUDE.md Phase 4 spec):
#   Stage 1 (years  1–5) : high growth    = min(revenue_cagr_3yr, 25%)
#   Stage 2 (years  6–10): tapering growth = linearly decays from stage1 rate → terminal rate
#   Stage 3 (terminal)   : perpetuity at 4% (India nominal GDP proxy)
#
# FCF base = most recent OCF + capex (capex is negative, so this is OCF − |capex|).
# If capex unavailable, falls back to OCF + investing cash flow.
# Intrinsic value per share = PV(all future FCFs) / shares_outstanding.
#
# Margin of safety = (intrinsic_value − current_price) / intrinsic_value.
#   > 0: stock trades below intrinsic value (discount)
#   < 0: stock trades above intrinsic value (premium)

_DCF_WACC           = 0.12   # fixed WACC for all Indian equities
_DCF_TERMINAL_RATE  = 0.04   # terminal growth rate (India nominal GDP proxy)
_DCF_STAGE1_CAP     = 0.25   # cap stage-1 growth at 25% to avoid fantasy scenarios
_DCF_STAGE1_YEARS   = 5
_DCF_STAGE2_YEARS   = 5      # years 6–10


def _compute_dcf(data):
    """
    Compute a 3-stage DCF intrinsic value per share.

    All inputs are sourced from the scraper output dict; no LLM, no network.
    WACC is fixed at 12% (see TRADEOFFS.md T-012 for rationale).

    FCF base:
        - Preferred: cash_flow.operating[0] + cash_flow.capex[0]
          (capex field is negative so addition subtracts it from OCF)
        - Fallback:  cash_flow.operating[0] + cash_flow.investing[0]

    Growth rates:
        - Stage 1 (yrs 1-5):  min(growth_rates.revenue_cagr_3yr / 100, 0.25)
          Falls back to growth_rates.revenue_cagr_5yr, then profit_cagr_3yr.
          If all are None, stage-1 rate defaults to terminal rate (conservative).
        - Stage 2 (yrs 6-10): linearly tapers from stage-1 rate to terminal rate.
        - Stage 3 (terminal): _DCF_TERMINAL_RATE in perpetuity.

    Shares outstanding:
        - Derived as: net_profit[0] / eps[0]   (both in same currency unit)
        - Expressed in crores (same unit as net_profit in Screener data).

    Args:
        data: full dict from fetch_company_data()

    Returns:
        dict with:
            dcf_intrinsic_value      float|None  — per share in INR
            dcf_intrinsic_value_reason str|None  — why it's None
            dcf_margin_of_safety     float|None  — fraction, positive = undervalued
            dcf_verdict              str|None    — "undervalued"|"fairly_valued"|"overvalued"
            dcf_stage1_growth        float|None  — actual stage-1 growth rate used
            dcf_fcf_base             float|None  — FCF (crore INR) used as base
    """
    pl = data.get("pl_table", {})
    cf = data.get("cash_flow", {})
    gr = data.get("growth_rates", {})
    h  = data.get("header", {})

    result = {
        "dcf_intrinsic_value":        None,
        "dcf_intrinsic_value_reason": None,
        "dcf_margin_of_safety":       None,
        "dcf_verdict":                None,
        "dcf_stage1_growth":          None,
        "dcf_fcf_base":               None,
    }

    # --- Step 1: Establish FCF base (most recent year) ---
    ocf0   = _safe(cf.get("operating"), 0)
    capex0 = _safe(cf.get("capex"), 0)
    inv0   = _safe(cf.get("investing"), 0)

    if ocf0 is None:
        result["dcf_intrinsic_value_reason"] = "operating cash flow unavailable"
        return result

    if capex0 is not None:
        # capex field is already negative (cash outflow), so OCF + capex = FCF
        fcf_base = ocf0 + capex0
    elif inv0 is not None:
        # Fallback: OCF + total investing (investing includes non-capex items too)
        fcf_base = ocf0 + inv0
    else:
        result["dcf_intrinsic_value_reason"] = "capex and investing cash flow both unavailable"
        return result

    if fcf_base <= 0:
        # Negative FCF companies cannot be valued via DCF -- too speculative
        result["dcf_intrinsic_value_reason"] = (
            f"FCF base non-positive ({round(fcf_base, 1)} cr) -- DCF not applicable"
        )
        return result

    result["dcf_fcf_base"] = round(fcf_base, 2)

    # --- Step 2: Determine stage-1 growth rate ---
    # Prefer 3yr revenue CAGR; fall back to 5yr, then 3yr profit CAGR.
    raw_growth = (
        gr.get("revenue_cagr_3yr")
        or gr.get("revenue_cagr_5yr")
        or gr.get("profit_cagr_3yr")
    )

    if raw_growth is not None:
        # CAGR values are stored as percentages (e.g., 15.2 means 15.2%)
        stage1_rate = min(raw_growth / 100.0, _DCF_STAGE1_CAP)
    else:
        # No historical growth data -- use terminal rate as conservative proxy
        stage1_rate = _DCF_TERMINAL_RATE

    result["dcf_stage1_growth"] = round(stage1_rate * 100, 2)  # store as %

    # --- Step 3: Project FCFs for stages 1 and 2 ---
    total_pv   = 0.0
    fcf_now    = fcf_base

    # Stage 1: years 1 to 5 at constant stage1_rate
    for yr in range(1, _DCF_STAGE1_YEARS + 1):
        fcf_now  = fcf_now * (1 + stage1_rate)
        discount = (1 + _DCF_WACC) ** yr
        total_pv += fcf_now / discount

    # Stage 2: years 6 to 10, growth tapers linearly from stage1_rate → terminal
    # At year 6 growth = stage1_rate - 1 step; at year 10 = terminal_rate
    step = (stage1_rate - _DCF_TERMINAL_RATE) / _DCF_STAGE2_YEARS
    for yr_offset in range(1, _DCF_STAGE2_YEARS + 1):
        taper_rate  = stage1_rate - (step * yr_offset)
        taper_rate  = max(taper_rate, _DCF_TERMINAL_RATE)  # floor at terminal
        fcf_now     = fcf_now * (1 + taper_rate)
        yr_abs      = _DCF_STAGE1_YEARS + yr_offset
        discount    = (1 + _DCF_WACC) ** yr_abs
        total_pv   += fcf_now / discount

    # Stage 3: terminal value using Gordon Growth Model
    # TV = FCF_yr10 × (1 + g) / (WACC − g)  →  discounted back to today
    terminal_fcf = fcf_now * (1 + _DCF_TERMINAL_RATE)
    terminal_val = terminal_fcf / (_DCF_WACC - _DCF_TERMINAL_RATE)
    tv_discount  = (1 + _DCF_WACC) ** (_DCF_STAGE1_YEARS + _DCF_STAGE2_YEARS)
    total_pv    += terminal_val / tv_discount

    # --- Step 4: Convert total PV (in crore INR) to per-share intrinsic value ---
    np0  = _safe(pl.get("net_profit"), 0)
    eps0 = _safe(pl.get("eps"), 0)

    if np0 is None or eps0 is None:
        result["dcf_intrinsic_value_reason"] = (
            "net_profit or EPS unavailable -- cannot derive shares outstanding"
        )
        return result

    if eps0 == 0:
        result["dcf_intrinsic_value_reason"] = "EPS is zero -- cannot derive shares outstanding"
        return result

    # shares_outstanding (crore) = net_profit (crore) / EPS (INR per share)
    # This gives shares in crore units, matching Screener's data convention.
    shares_cr = np0 / eps0

    if shares_cr <= 0:
        result["dcf_intrinsic_value_reason"] = (
            f"Derived shares outstanding non-positive ({round(shares_cr, 4)} cr)"
        )
        return result

    # total_pv is in crore INR; shares_cr is in crore shares.
    # intrinsic_value_per_share (INR) = total_pv_crore / shares_crore
    # The crore units cancel: (crore INR) / (crore shares) = INR/share ✓
    intrinsic_value = total_pv / shares_cr
    result["dcf_intrinsic_value"] = round(intrinsic_value, 2)

    # --- Step 5: Compute margin of safety vs current price ---
    price = h.get("current_price")

    if price is not None and price > 0:
        mos = (intrinsic_value - price) / intrinsic_value
        result["dcf_margin_of_safety"] = round(mos, 4)

        # Verdict: >20% discount = undervalued; within ±20% = fairly_valued; else overvalued
        if mos > 0.20:
            result["dcf_verdict"] = "undervalued"
        elif mos >= -0.20:
            result["dcf_verdict"] = "fairly_valued"
        else:
            result["dcf_verdict"] = "overvalued"

    return result


# ---------------------------------------------------------------------------
# Signal 7: Valuation
# ---------------------------------------------------------------------------
# Graham Number = sqrt(22.5 x EPS x Book Value per Share)
# Source: Benjamin Graham, "The Intelligent Investor" (1949).
# Note: systematically undervalues growth companies by design -- see T-008.

def _compute_valuation(data):
    """
    Compute Graham Number, price premium/discount, PE, and earnings yield.

    Graham Number = sqrt(22.5 x EPS x BVPS)
    Only valid when EPS > 0 and book_value > 0.

    price_to_graham = (current_price / graham_number) - 1
        Negative = below Graham Number (potential undervaluation)
        Positive = above Graham Number

    Verdicts: < -0.10 "undervalued" | -0.10 to +0.10 "fairly_valued" | > +0.10 "overvalued"

    Args:
        data: full dict from fetch_company_data()

    Returns:
        dict with graham_number, price_to_graham, graham_verdict, pe_current, earnings_yield
    """
    pl = data.get("pl_table", {})
    kr = data.get("key_ratios", {})
    h  = data.get("header", {})

    result = {
        "graham_number":        None,
        "graham_number_reason": None,
        "price_to_graham":      None,
        "graham_verdict":       None,
        "pe_current":           kr.get("pe"),
        "earnings_yield":       None,
        # DCF fields are merged in by compute_signals after _compute_dcf runs
    }

    try:
        eps0  = _safe(pl.get("eps"), 0)
        bv    = kr.get("book_value")
        price = h.get("current_price")

        if eps0 is None:
            result["graham_number_reason"] = "EPS unavailable"
        elif eps0 <= 0:
            result["graham_number_reason"] = f"EPS non-positive ({eps0})"
        elif bv is None:
            result["graham_number_reason"] = "book_value (BVPS) unavailable"
        elif bv <= 0:
            result["graham_number_reason"] = f"book_value non-positive ({bv})"
        else:
            gn = math.sqrt(22.5 * eps0 * bv)
            result["graham_number"] = round(gn, 2)

            if price is not None and price > 0:
                ptg = (price / gn) - 1
                result["price_to_graham"] = round(ptg, 4)
                if ptg < -0.10:
                    result["graham_verdict"] = "undervalued"
                elif ptg <= 0.10:
                    result["graham_verdict"] = "fairly_valued"
                else:
                    result["graham_verdict"] = "overvalued"

        if eps0 is not None and price is not None and price > 0:
            result["earnings_yield"] = round((eps0 / price) * 100, 2)

    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# Signal 8: Promoter Risk
# ---------------------------------------------------------------------------

def _compute_promoter_risk(data):
    """
    Assess promoter pledging risk. Pledged shares can be sold by lenders on
    price drops, creating a self-reinforcing crash.

    Pledge flags: < 5% "none" | 5-20% "moderate" | > 20% "high"

    Args:
        data: full dict from fetch_company_data()

    Returns:
        dict with pledged_pct and pledge_flag
    """
    sh = data.get("shareholding", {})
    pledged = sh.get("pledged_pct", 0.0) or 0.0

    if pledged < 5.0:
        flag = "none"
    elif pledged <= 20.0:
        flag = "moderate"
    else:
        flag = "high"

    # Pledging trend: compare latest pledged% vs oldest available in history.
    # Rising pledging is a red flag even if absolute level is low.
    pledge_trend = "stable"
    history = sh.get("history", {})
    if history:
        quarters_sorted = list(history.keys())  # in order scraped (oldest first)
        if len(quarters_sorted) >= 2:
            oldest_pct = (history[quarters_sorted[0]].get("pledged_pct") or 0.0)
            latest_pct = pledged
            diff = latest_pct - oldest_pct
            if diff > 2.0:
                pledge_trend = "increasing"
            elif diff < -2.0:
                pledge_trend = "decreasing"

    return {"pledged_pct": pledged, "pledge_flag": flag, "pledge_trend": pledge_trend}


# ---------------------------------------------------------------------------
# Signal 9: Quarterly Momentum
# ---------------------------------------------------------------------------
# Quarterly data is oldest-first (index -1 = most recent quarter).
# YoY: [-1] vs [-5] (same quarter one year ago).

def _compute_quarterly_momentum(data):
    """
    Compute YoY revenue/profit growth and OPM trend from quarterly data.

    Quarterly data ordering: oldest-first (index -1 = most recent quarter).
    YoY: index [-1] vs index [-5] (same quarter, prior year).
    Requires at least 5 quarters for YoY comparison.

    Args:
        data: full dict from fetch_company_data()

    Returns:
        dict with revenue_yoy_pct, profit_yoy_pct, opm_trend, reason strings
    """
    q = data.get("quarterly", {})

    result = {
        "revenue_yoy_pct":        None,
        "revenue_yoy_pct_reason": None,
        "profit_yoy_pct":         None,
        "profit_yoy_pct_reason":  None,
        "opm_trend":              "stable",
    }

    try:
        sales  = q.get("sales", [])
        profit = q.get("net_profit", [])
        opm    = q.get("opm_pct", [])

        if len(_non_none(sales)) >= 5:
            chg = _pct_change(_safe(sales, -1), _safe(sales, -5))
            if chg is not None:
                result["revenue_yoy_pct"] = round(chg * 100, 2)
            else:
                result["revenue_yoy_pct_reason"] = "Zero or None base value"
        else:
            result["revenue_yoy_pct_reason"] = (
                f"Insufficient quarters ({len(_non_none(sales))}) -- need 5 for YoY"
            )

        if len(_non_none(profit)) >= 5:
            chg = _pct_change(_safe(profit, -1), _safe(profit, -5))
            if chg is not None:
                result["profit_yoy_pct"] = round(chg * 100, 2)
            else:
                result["profit_yoy_pct_reason"] = "Zero or None base value"
        else:
            result["profit_yoy_pct_reason"] = (
                f"Insufficient quarters ({len(_non_none(profit))}) -- need 5 for YoY"
            )

        if len(_non_none(opm)) >= 4:
            o_now  = _safe(opm, -1)
            o_prev = _safe(opm, -4)
            if o_now is not None and o_prev is not None and o_prev != 0:
                chg = (o_now - o_prev) / abs(o_prev)
                if chg > 0.05:
                    result["opm_trend"] = "expanding"
                elif chg < -0.05:
                    result["opm_trend"] = "contracting"

    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# Derived scores -- mechanical, NOT LLM (see TRADEOFFS.md T-010)
# ---------------------------------------------------------------------------

def _compute_fundamentals_score(piotroski_score, roce_trend, eq_flag):
    """
    Derive 1-10 fundamentals score from Piotroski, ROCE trend, earnings quality.

    Formula:
        base     = round(piotroski * 10/9), clamped [1, 10]
        roce_mod = +1 improving | 0 stable | -1 declining
        eq_mod   = +1 high | 0 medium | -1 low
        score    = clamp(base + roce_mod + eq_mod, 1, 10)

    Defaults to 5 (neutral) for any None input.

    Args:
        piotroski_score: int 0-9 or None
        roce_trend:      "improving"|"stable"|"declining"|None
        eq_flag:         "high"|"medium"|"low"|None

    Returns:
        int in [1, 10]
    """
    base     = 5 if piotroski_score is None else max(1, round(piotroski_score * 10 / 9))
    roce_mod = {"improving": +1, "stable": 0, "declining": -1}.get(roce_trend, 0)
    eq_mod   = {"high": +1, "medium": 0, "low": -1}.get(eq_flag, 0)
    return max(1, min(10, base + roce_mod + eq_mod))


def _compute_valuation_score(price_to_graham, pe_current):
    """
    Derive 1-10 valuation score from Graham discount/premium and PE.

    Graham brackets:
        <= -0.30  base=9  (>30% discount)
        <= -0.10  base=7  (10-30% discount)
        <=  0.10  base=5  (within 10%)
        <=  0.30  base=3  (10-30% premium)
        >   0.30  base=1  (>30% premium)

    PE modifier: < 15 gives +1, > 40 gives -1.
    Defaults to 5 if price_to_graham is None.

    Args:
        price_to_graham: float or None
        pe_current:      float or None

    Returns:
        int in [1, 10]
    """
    if price_to_graham is None:
        base = 5
    elif price_to_graham <= -0.30:
        base = 9
    elif price_to_graham <= -0.10:
        base = 7
    elif price_to_graham <= 0.10:
        base = 5
    elif price_to_graham <= 0.30:
        base = 3
    else:
        base = 1

    if pe_current is not None:
        if pe_current < 15:
            base = min(10, base + 1)
        elif pe_current > 40:
            base = max(1, base - 1)

    return base


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_signals(data):
    """
    Compute all quantitative investment signals from scraper output.

    Single public function. Pure Python -- no LLM, no network, no I/O.
    Missing data yields None + companion *_reason string -- never raises.
    See TRADEOFFS.md T-011.

    Data ordering (critical):
        Annual (pl_table, balance_sheet, cash_flow, ratios_table):
            index [0] = most recent year (newest-first)
        Quarterly:
            index [-1] = most recent quarter (oldest-first)

    Args:
        data: dict -- full output of src/scraper.fetch_company_data()

    Returns:
        dict with keys:
            piotroski            Piotroski F-Score (0-9) + 9 binary signals + label
            dupont               DuPont ROE decomposition + driver label
            earnings_quality     OCF/NP and FCF/NP ratios + quality flag
            growth_quality       Revenue/profit CAGR trends + margin trend
            capital_efficiency   ROCE trend + interest coverage + WC trend
            balance_sheet_health D/E trend + interest coverage
            valuation            Graham Number + PE + earnings yield + DCF fields
            promoter_risk        Pledged pct + flag
            quarterly_momentum   Revenue YoY + profit YoY + OPM trend
            fundamentals_score   int 1-10, mechanically derived
            valuation_score      int 1-10, mechanically derived
    """
    piotroski        = _compute_piotroski(data)
    dupont           = _compute_dupont(data)
    earnings_quality = _compute_earnings_quality(data)
    growth_quality   = _compute_growth_quality(data)
    capital_eff      = _compute_capital_efficiency(data)
    balance_sheet    = _compute_balance_sheet_health(
                           data, capital_eff.get("interest_coverage"))
    valuation        = _compute_valuation(data)
    dcf              = _compute_dcf(data)
    promoter_risk    = _compute_promoter_risk(data)
    quarterly_mom    = _compute_quarterly_momentum(data)

    # Merge DCF results into the valuation dict so all price-target signals
    # are co-located and agents can access them via signals["valuation"].
    valuation.update(dcf)

    fundamentals_score = _compute_fundamentals_score(
        piotroski.get("score"),
        capital_eff.get("roce_trend"),
        earnings_quality.get("quality_flag"),
    )
    valuation_score = _compute_valuation_score(
        valuation.get("price_to_graham"),
        valuation.get("pe_current"),
    )

    return {
        "piotroski":            piotroski,
        "dupont":               dupont,
        "earnings_quality":     earnings_quality,
        "growth_quality":       growth_quality,
        "capital_efficiency":   capital_eff,
        "balance_sheet_health": balance_sheet,
        "valuation":            valuation,
        "promoter_risk":        promoter_risk,
        "quarterly_momentum":   quarterly_mom,
        "fundamentals_score":   fundamentals_score,
        "valuation_score":      valuation_score,
    }
