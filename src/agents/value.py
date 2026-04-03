# ============================================================
# FILE: src/agents/value.py
# PURPOSE: Value analyst agent — Graham/Buffett investing lens.
#          Evaluates a stock through margin of safety, owner
#          earnings, and debt discipline. Pre-computes owner
#          earnings in Python, then asks GPT-4o to interpret
#          signals from this lens. Never re-computes signals.
# INPUT:   data (dict) — scraper output
#          signals (dict) — output of signals.py
#          news (dict | None) — output of news.py
# OUTPUT:  dict: lens, score, thesis, key_signals, risks, action
# DEPENDS: src/llm.py, src/agents/base.py
# ============================================================

# Philosophy: Benjamin Graham's margin of safety + Warren Buffett's owner
# earnings concept. This analyst only buys when the price is substantially
# below intrinsic value, prefers debt-light businesses with high earnings
# quality, and treats pledged promoter shares as a near-disqualifier.

import json

from src.agents.base import _safe
from src.llm import call_analysis_model

# 10-year Indian government bond yield used as the risk-free rate benchmark
# for owner earnings yield comparison.
_GSEC_10YR = 7.2  # percent



def _compute_owner_earnings(data: dict) -> dict:
    """
    Compute Buffett's Owner Earnings from scraper data.

    Owner Earnings = Net Income + Depreciation + CapEx (negative) - ΔWorking Capital
    ΔWC = (Trade Receivables + Inventories - Trade Payables)_current
          - (Trade Receivables + Inventories - Trade Payables)_prior

    All values are in INR Cr (same scale as P&L).

    Args:
        data: Full scraper output dict.

    Returns:
        dict with keys: owner_earnings_cr, owner_earnings_per_share,
        owner_earnings_yield_pct, oe_reason (None if computed, str if skipped).
    """
    result = {
        "owner_earnings_cr": None,
        "owner_earnings_per_share": None,
        "owner_earnings_yield_pct": None,
        "oe_reason": None,
    }

    pl = data.get("pl_table", {})
    cf = data.get("cash_flow", {})
    bs = data.get("balance_sheet", {})
    hdr = data.get("header", {})

    # --- Gather components ---
    ni = _safe(pl.get("net_profit"), 0)
    dep = _safe(pl.get("depreciation"), 0)
    capex = _safe(cf.get("capex"), 0)          # negative = outflow
    price = hdr.get("current_price")
    mktcap = hdr.get("market_cap")             # INR Cr

    # Validate essentials
    if ni is None:
        result["oe_reason"] = "net_profit unavailable"
        return result
    if dep is None:
        result["oe_reason"] = "depreciation unavailable"
        return result
    if capex is None:
        result["oe_reason"] = "capex unavailable"
        return result
    if not price or price <= 0:
        result["oe_reason"] = "current_price unavailable"
        return result
    if not mktcap or mktcap <= 0:
        result["oe_reason"] = "market_cap unavailable"
        return result

    # --- Compute ΔWorking Capital (optional — skip if data missing) ---
    # WC = Trade Receivables + Inventories - Trade Payables
    tr0 = _safe(bs.get("trade_receivables"), 0)
    tr1 = _safe(bs.get("trade_receivables"), 1)
    inv0 = _safe(bs.get("inventories"), 0)
    inv1 = _safe(bs.get("inventories"), 1)
    tp0 = _safe(bs.get("trade_payables"), 0)
    tp1 = _safe(bs.get("trade_payables"), 1)

    delta_wc = 0.0
    if all(v is not None for v in [tr0, tr1, inv0, inv1, tp0, tp1]):
        wc_current = tr0 + inv0 - tp0
        wc_prior   = tr1 + inv1 - tp1
        delta_wc   = wc_current - wc_prior

    # --- Owner Earnings ---
    # capex is negative (outflow), so + capex subtracts it from earnings.
    oe = ni + dep + capex - delta_wc

    # --- Per share and yield ---
    # market_cap is in INR Cr; price is in INR.
    # shares (in units) = (mktcap * 1e7) / price
    shares = (mktcap * 1e7) / price
    oe_per_share = oe * 1e7 / shares          # convert Cr back to INR per share
    oe_yield = (oe_per_share / price) * 100   # as percent

    result["owner_earnings_cr"] = round(oe, 2)
    result["owner_earnings_per_share"] = round(oe_per_share, 2)
    result["owner_earnings_yield_pct"] = round(oe_yield, 2)
    return result


def analyze(data: dict, signals: dict, news: dict | None) -> dict:
    """
    Value analyst agent — Graham/Buffett investing lens.

    Pre-computes owner earnings in Python, then sends a compact payload
    of pre-computed signals to GPT-4o asking it to evaluate the stock
    from a deep value perspective.

    All numerical signals have been computed by signals.py. This function
    does NOT ask GPT-4o to recompute or second-guess them — only to interpret
    them through the value investing lens and assign a conviction score.

    Args:
        data:    Full scraper output from fetch_company_data().
        signals: Pre-computed signal dict from compute_signals().
        news:    News + sentiment dict from fetch_news(), or None.

    Returns:
        dict with keys:
            lens (str):         "value"
            score (int):        1–10 conviction score
            thesis (str):       2–3 sentence investment thesis
            key_signals (list): 3 signals that drove the score
            risks (list):       1–3 risks this analyst highlights
            action (str):       "buy" | "hold" | "sell" | "avoid"

        On any failure, returns {"lens": "value", "error": str(e)}.
    """
    try:
        # --- Extract relevant sub-dicts from pre-computed signals ---
        val = signals.get("valuation", {})
        eq  = signals.get("earnings_quality", {})
        bsh = signals.get("balance_sheet_health", {})
        pit = signals.get("piotroski", {})
        pr  = signals.get("promoter_risk", {})

        # --- Python pre-computation: owner earnings (not in signals.py yet) ---
        oe = _compute_owner_earnings(data)

        # --- Build compact payload for GPT-4o ---
        # Only the signals this lens cares about. Keep it small to reduce tokens.
        payload = {
            "company": data.get("header", {}).get("name", "Unknown"),
            "sector":  data.get("header", {}).get("sector", "Unknown"),
            "company_type": "bank_or_nbfc" if data.get("is_bank") else "non_financial",
            "current_price_inr": data.get("header", {}).get("current_price"),
            "valuation": {
                "graham_number": val.get("graham_number"),
                "price_to_graham_pct": round(val.get("price_to_graham", 0) * 100, 1)
                    if val.get("price_to_graham") is not None else None,
                "graham_verdict": val.get("graham_verdict"),
                "pe_current": val.get("pe_current"),
                "industry_pe": val.get("industry_pe"),
                "pe_vs_industry": (
                    round(val.get("pe_current") / val.get("industry_pe"), 2)
                    if val.get("pe_current") and val.get("industry_pe") else None
                ),
                "ev_ebitda": val.get("ev_ebitda"),
                "price_to_sales": val.get("price_to_sales"),
                "earnings_yield_pct": val.get("earnings_yield"),
                # DCF fields — method may be "fcf_dcf" (normal) or "epv" (negative-FCF fallback)
                "dcf_intrinsic_value": val.get("dcf_intrinsic_value"),
                "dcf_method": val.get("dcf_method"),
                "dcf_margin_of_safety_pct": round(val.get("dcf_margin_of_safety", 0) * 100, 1)
                    if val.get("dcf_margin_of_safety") is not None else None,
                "dcf_verdict": val.get("dcf_verdict"),
                "dcf_note": val.get("dcf_intrinsic_value_reason") if val.get("dcf_method") == "epv" else None,
            },
            "owner_earnings": {
                "owner_earnings_cr": oe["owner_earnings_cr"],
                "owner_earnings_per_share_inr": oe["owner_earnings_per_share"],
                "owner_earnings_yield_pct": oe["owner_earnings_yield_pct"],
                "oe_vs_gsec_10yr": (
                    round(oe["owner_earnings_yield_pct"] - _GSEC_10YR, 2)
                    if oe["owner_earnings_yield_pct"] is not None else None
                ),
                "oe_reason": oe["oe_reason"],
            },
            "earnings_quality": {
                "quality_flag": eq.get("quality_flag"),
                "ocf_to_net_profit": eq.get("ocf_to_net_profit"),
                "fcf_to_net_profit": eq.get("fcf_to_net_profit"),
            },
            "balance_sheet": {
                "debt_to_equity": bsh.get("debt_to_equity_latest"),
                "debt_trend": bsh.get("debt_trend"),
                "interest_coverage": bsh.get("interest_coverage"),
            },
            "piotroski": {
                "score": pit.get("score"),
                "label": pit.get("label"),
            },
            "promoter_risk": {
                "pledged_pct": pr.get("pledged_pct"),
                "pledge_flag": pr.get("pledge_flag"),
                "pledge_trend": pr.get("pledge_trend"),
            },
            "news_sentiment": news.get("sentiment") if news else None,
            "gsec_10yr_yield_pct": _GSEC_10YR,
        }

        # --- System prompt: Graham/Buffett value investing philosophy ---
        system_prompt = (
            "You are a senior equity analyst at a deep value investment fund, "
            "trained in the methods of Benjamin Graham and Warren Buffett. "
            "You invest exclusively in Indian public companies listed on NSE/BSE. "
            "\n\n"
            "Your investment philosophy:\n"
            "- You only buy when there is a significant margin of safety — price "
            "  substantially below intrinsic value (Graham Number or DCF).\n"
            "- You treat earnings quality (OCF > Net Income) as essential. Accrual-heavy "
            "  earnings are a red flag.\n"
            "- You regard high debt (D/E > 1.5) and falling interest coverage as "
            "  near-disqualifying unless the business has predictable cash flows.\n"
            "- You regard promoter pledging above 20% as a serious risk.\n"
            "- Owner earnings yield vs 10-year Gsec (7.2%) is your primary return metric.\n"
            "- You never pay for growth. You pay for assets and earnings power.\n"
            "\n\n"
            "BANKS AND NBFCs — read this if company_type = 'bank_or_nbfc':\n"
            "- Banks and NBFCs are financial intermediaries: they borrow money (deposits, "
            "  bonds) and lend it out at a spread. Their 'debt' is their raw material, "
            "  not leverage in the traditional sense — D/E ratios of 8–10x are normal.\n"
            "- Graham Number and DCF intrinsic value are NOT reliable for banks because: "
            "  (1) FCF is negative by design — banks continuously deploy capital as loans; "
            "  (2) Graham Number was designed for asset-heavy industrials, not financial firms.\n"
            "- The correct value lens for banks is Price-to-Book (P/B). Fair value for a "
            "  quality Indian bank is ~2–3x book; >4x = expensive; <1x = distressed.\n"
            "- Interest coverage is meaningless for banks — interest IS their business cost.\n"
            "- Instead of Graham Number, use earnings yield vs Gsec as the value signal.\n"
            "\n\n"
            "CRITICAL RULES:\n"
            "1. All numerical signals have been pre-computed in Python. Do NOT "
            "   recompute or second-guess them. If a value is null, say so.\n"
            "2. DCF method: if dcf_method='epv', the intrinsic value is an Earnings "
            "   Power Value (EPS/WACC) — a zero-growth floor because FCF was negative. "
            "   For banks/NBFCs this is ALWAYS the case — EPV is structurally not a "
            "   fair valuation; use P/B and earnings yield instead as primary signals.\n"
            "3. Your score (1–10) must follow from the signals provided:\n"
            "   9–10 = deep value, high margin of safety, strong balance sheet\n"
            "   7–8  = fair value, decent quality\n"
            "   5–6  = fairly valued or mixed signals\n"
            "   3–4  = overvalued or balance sheet concern\n"
            "   1–2  = significant overvaluation or major red flag\n"
            "4. Return ONLY valid JSON matching the schema. No prose outside JSON.\n"
            "5. key_signals must be 3 specific data points (e.g. "
            "   'Graham Number ₹450 vs price ₹380 — 16% discount').\n"
        )

        user_prompt = (
            f"Analyse this Indian stock from a Graham/Buffett value investing lens.\n\n"
            f"Pre-computed signals:\n{json.dumps(payload, indent=2)}\n\n"
            f"Return JSON matching exactly this schema:\n"
            f'{{"lens": "value", "score": <int 1-10>, "thesis": "<2-3 sentences>", '
            f'"key_signals": ["<signal 1>", "<signal 2>", "<signal 3>"], '
            f'"risks": ["<risk 1>", "<risk 2>"], "action": "<buy|hold|sell|avoid>"}}'
        )

        # --- Analysis model call ---
        raw = json.loads(call_analysis_model(
            system=system_prompt,
            user=user_prompt,
            max_tokens=500,
            response_format={"type": "json_object"},
        ))

        # Ensure required keys are present; fill defaults if GPT omitted any
        return {
            "lens":        "value",
            "score":       int(raw.get("score", 5)),
            "thesis":      raw.get("thesis", ""),
            "key_signals": raw.get("key_signals", []),
            "risks":       raw.get("risks", []),
            "action":      raw.get("action", "hold"),
        }

    except Exception as e:
        # Per CLAUDE.md Rule 5 (agent exception): one agent failure must never
        # abort the whole pipeline. Return error dict; synthesis.py handles it.
        return {"lens": "value", "error": str(e)}
