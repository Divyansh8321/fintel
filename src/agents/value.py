# ============================================================
# FILE: src/agents/value.py
# PURPOSE: Value analyst agent — Graham/Buffett investing lens.
#          Evaluates a stock through margin of safety, owner
#          earnings, and debt discipline. Reads pre-computed owner
#          earnings from signals.owner_earnings, then asks GPT-4o
#          to interpret signals from this lens. Never re-computes signals.
# INPUT:   signals (SignalsModel) — output of signals.py
#          news (dict | None) — output of news.py
# OUTPUT:  dict: lens, score, thesis, key_signals, risks, action
# DEPENDS: src/llm.py, src/models.py
# ============================================================

# Philosophy: Benjamin Graham's margin of safety + Warren Buffett's owner
# earnings concept. This analyst only buys when the price is substantially
# below intrinsic value, prefers debt-light businesses with high earnings
# quality, and treats pledged promoter shares as a near-disqualifier.

import json

from src.llm import call_analysis_model
from src.models import SignalsModel

# 10-year Indian government bond yield used as the risk-free rate benchmark
# for owner earnings yield comparison. Kept here for the payload construction
# below; the authoritative value lives in signals.py as _GSEC_10YR.
_GSEC_10YR = 7.2  # percent


def analyze(signals: SignalsModel, news: dict | None) -> dict:
    """
    Value analyst agent — Graham/Buffett investing lens.

    Reads pre-computed owner earnings from signals.owner_earnings, then sends
    a compact payload of pre-computed signals to GPT-4o asking it to evaluate
    the stock from a deep value perspective.

    All numerical signals have been computed by signals.py. This function
    does NOT ask GPT-4o to recompute or second-guess them — only to interpret
    them through the value investing lens and assign a conviction score.

    Args:
        signals: Pre-computed SignalsModel from compute_signals().
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
        # --- Extract relevant sub-models from pre-computed signals ---
        val = signals.valuation
        eq  = signals.earnings_quality
        bsh = signals.balance_sheet_health
        pit = signals.piotroski
        pr  = signals.promoter_risk
        oe  = signals.owner_earnings

        # --- Build compact payload for GPT-4o ---
        # Only the signals this lens cares about. Keep it small to reduce tokens.
        payload = {
            "company": signals.meta.name,
            "sector":  signals.meta.sector,
            "company_type": "bank_or_nbfc" if signals.meta.is_bank else "non_financial",
            "current_price_inr": signals.meta.current_price,
            "valuation": {
                "graham_number": val.graham_number if val else None,
                "price_to_graham_pct": round(val.price_to_graham * 100, 1)
                    if val and val.price_to_graham is not None else None,
                "graham_verdict": val.graham_verdict if val else None,
                "pe_current": val.pe_current if val else None,
                "industry_pe": val.industry_pe if val else None,
                "pe_vs_industry": (
                    round(val.pe_current / val.industry_pe, 2)
                    if val and val.pe_current and val.industry_pe else None
                ),
                "ev_ebitda": val.ev_ebitda if val else None,
                "price_to_sales": val.price_to_sales if val else None,
                "earnings_yield_pct": val.earnings_yield if val else None,
                # DCF fields — method may be "fcf_dcf" (normal) or "epv" (negative-FCF fallback)
                "dcf_intrinsic_value": val.dcf_intrinsic_value if val else None,
                "dcf_method": val.dcf_method if val else None,
                "dcf_margin_of_safety_pct": round(val.dcf_margin_of_safety * 100, 1)
                    if val and val.dcf_margin_of_safety is not None else None,
                # dcf_verdict not stored in ValuationModel (filtered at construction)
                "dcf_verdict": None,
                "dcf_note": val.dcf_intrinsic_value_reason
                    if val and val.dcf_method == "epv" else None,
            },
            "owner_earnings": {
                "owner_earnings_cr": oe.owner_earnings_cr if oe else None,
                "owner_earnings_per_share_inr": oe.owner_earnings_per_share if oe else None,
                "owner_earnings_yield_pct": oe.owner_earnings_yield_pct if oe else None,
                "oe_vs_gsec_10yr": (
                    round(oe.owner_earnings_yield_pct - _GSEC_10YR, 2)
                    if oe and oe.owner_earnings_yield_pct is not None else None
                ),
                "oe_reason": oe.oe_reason if oe else None,
            },
            "earnings_quality": {
                "quality_flag": eq.quality_flag if eq else None,
                "ocf_to_net_profit": eq.ocf_to_net_profit if eq else None,
                "fcf_to_net_profit": eq.fcf_to_net_profit if eq else None,
            },
            "balance_sheet": {
                "debt_to_equity": bsh.debt_to_equity_latest if bsh else None,
                "debt_trend": bsh.debt_trend if bsh else None,
                "interest_coverage": bsh.interest_coverage if bsh else None,
            },
            "piotroski": {
                "score": pit.score if pit else None,
                "label": pit.label if pit else None,
            },
            "promoter_risk": {
                "pledged_pct": pr.pledged_pct if pr else None,
                "pledge_flag": pr.pledge_flag if pr else None,
                "pledge_trend": pr.pledge_trend if pr else None,
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
