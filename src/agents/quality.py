# ============================================================
# FILE: src/agents/quality.py
# PURPOSE: Quality analyst agent — Munger/Pabrai investing lens.
#          Evaluates a stock through ROCE vs WACC spread, durable
#          competitive advantages, and earnings quality. Reads pre-
#          computed ROCE-WACC spread from signals.roce_wacc, then
#          asks GPT-4o to interpret signals from this lens.
#          Never re-computes signals.
# INPUT:   signals (SignalsModel) — output of signals.py
#          news (dict | None) — output of news.py
# OUTPUT:  dict: lens, score, thesis, key_signals, risks, action
# DEPENDS: src/llm.py, src/models.py
# ============================================================

# Philosophy: Charlie Munger's "wonderful company at a fair price" combined
# with Mohnish Pabrai's checklist-driven quality investing. This analyst
# prizes businesses that consistently earn above their cost of capital (ROCE
# > WACC), have high earnings quality (OCF > NI), and are run by managers
# who allocate capital well (stable/improving margins, no unnecessary debt).

import json

from src.llm import call_analysis_model
from src.models import SignalsModel


def analyze(signals: SignalsModel, news: dict | None) -> dict:
    """
    Quality analyst agent — Munger/Pabrai investing lens.

    Reads pre-computed ROCE vs WACC spread from signals.roce_wacc, then sends
    a compact payload of pre-computed quality signals to GPT-4o asking it to
    evaluate the stock from a quality-at-fair-price perspective.

    All numerical signals have been computed by signals.py. This function
    does NOT ask GPT-4o to recompute or second-guess them.

    Args:
        signals: Pre-computed SignalsModel from compute_signals().
        news:    News + sentiment dict from fetch_news(), or None.

    Returns:
        dict with keys:
            lens (str):         "quality"
            score (int):        1–10 conviction score
            thesis (str):       2–3 sentence investment thesis
            key_signals (list): 3 signals that drove the score
            risks (list):       1–3 risks this analyst highlights
            action (str):       "buy" | "hold" | "sell" | "avoid"

        On any failure, returns {"lens": "quality", "error": str(e)}.
    """
    try:
        # --- Extract relevant sub-models from pre-computed signals ---
        ce    = signals.capital_efficiency
        eq    = signals.earnings_quality
        dup   = signals.dupont
        pit   = signals.piotroski
        gq    = signals.growth_quality
        val   = signals.valuation
        pr    = signals.promoter_risk
        spread = signals.roce_wacc

        # --- Build compact payload for GPT-4o ---
        payload = {
            "company":      signals.meta.name,
            "sector":       signals.meta.sector,
            "company_type": "bank_or_nbfc" if signals.meta.is_bank else "non_financial",
            "current_price_inr": signals.meta.current_price,
            "capital_efficiency": {
                "roce_latest_pct":  spread.roce_latest if spread else None,
                "roce_trend":       ce.roce_trend if ce else None,
                "roce_3yr_avg_pct": ce.roce_3yr_avg if ce else None,
                "wacc_proxy_pct":   spread.wacc_proxy if spread else None,
                "roce_wacc_spread":  spread.roce_wacc_spread if spread else None,
                "spread_verdict":   spread.spread_verdict if spread else None,
                "interest_coverage": ce.interest_coverage if ce else None,
                "wc_trend":         ce.working_capital_days_trend if ce else None,
            },
            "earnings_quality": {
                "quality_flag":        eq.quality_flag if eq else None,
                "ocf_to_net_profit":   eq.ocf_to_net_profit if eq else None,
                "fcf_to_net_profit":   eq.fcf_to_net_profit if eq else None,
            },
            "dupont": {
                "net_margin_pct":    dup.net_margin if dup else None,
                "roe_computed_pct":  dup.roe_computed if dup else None,
                "roe_driver":        dup.roe_driver if dup else None,
                "asset_turnover":    dup.asset_turnover if dup else None,
            },
            "piotroski": {
                "score": pit.score if pit else None,
                "label": pit.label if pit else None,
            },
            "growth_quality": {
                "margin_trend":   gq.margin_trend if gq else None,
                "acceleration":   gq.acceleration if gq else None,
            },
            "pe_current":       val.pe_current if val else None,
            "industry_pe":      val.industry_pe if val else None,
            "ev_ebitda":        val.ev_ebitda if val else None,
            "promoter": {
                "promoter_holding":        pr.promoter_holding if pr else None,
                "promoter_holding_change": pr.promoter_holding_change if pr else None,
            },
            "news_sentiment":   news.get("sentiment") if news else None,
        }

        # --- System prompt: Munger/Pabrai quality investing philosophy ---
        system_prompt = (
            "You are a senior equity analyst at a quality-focused investment fund, "
            "trained in the methods of Charlie Munger and Mohnish Pabrai. "
            "You invest in Indian public companies listed on NSE/BSE. "
            "\n\n"
            "Your investment philosophy:\n"
            "- You seek businesses with durable competitive advantages (moats): "
            "  pricing power, switching costs, brand value, cost advantages.\n"
            "- ROCE consistently above WACC (12% proxy for Indian equities) is your "
            "  primary signal of a quality compounder. A business earning 20%+ ROCE "
            "  consistently is rare and valuable.\n"
            "- You prize earnings quality: OCF > Net Income means profits are real cash. "
            "  A business where profits consistently exceed cash flows is a red flag.\n"
            "- You prefer management that allocates capital well: reinvests at high ROCE, "
            "  avoids unnecessary debt, doesn't dilute shareholders.\n"
            "- You pay a fair price for quality, not a premium — PE should be justifiable "
            "  by the ROCE and growth combination.\n"
            "- A high Piotroski score (7+) confirms financial discipline.\n"
            "\n\n"
            "BANKS AND NBFCs — read this if company_type = 'bank_or_nbfc':\n"
            "- ROCE is not reported for banks — they don't distinguish operating vs "
            "  financing activities the way industrials do. Use ROE as the efficiency "
            "  metric instead. A quality Indian bank sustains ROE of 15–20%+.\n"
            "- Piotroski F-Score is invalid for banks (it tests inventory turns, "
            "  gross margin, current ratio — none apply to financial intermediaries). "
            "  It is marked 'not_applicable' in the data — do not reference it.\n"
            "- Earnings quality (OCF vs Net Income) is harder to interpret for banks "
            "  because loan disbursements show as operating outflows. Focus on "
            "  consistency of ROE and whether reported profits convert to dividends.\n"
            "- Capital efficiency for a bank = ROE vs cost of equity (~14% for Indian "
            "  banks). A bank earning ROE > 18% consistently is a quality compounder.\n"
            "\n\n"
            "CRITICAL RULES:\n"
            "1. All numerical signals have been pre-computed in Python. Do NOT "
            "   recompute or second-guess them. If a value is null, acknowledge it.\n"
            "2. If piotroski.label is 'not_applicable', this is a bank or NBFC. "
            "   Do NOT reference Piotroski score. For banks, ROE trend and "
            "   earnings quality (OCF vs NI) are the best proxies for financial discipline.\n"
            "3. Your score (1–10) must follow from the signals provided:\n"
            "   9–10 = ROCE >> WACC, high quality, strong moat signals\n"
            "   7–8  = ROCE > WACC, decent earnings quality\n"
            "   5–6  = ROCE near WACC or mixed quality signals\n"
            "   3–4  = ROCE < WACC or earnings quality concerns\n"
            "   1–2  = Value destroyer or serious quality deterioration\n"
            "4. Return ONLY valid JSON matching the schema. No prose outside JSON.\n"
            "5. key_signals must be 3 specific data points (e.g. "
            "'ROCE 24% vs WACC 12% — 12pp spread, stable trend over 5yr').\n"
        )

        user_prompt = (
            f"Analyse this Indian stock from a Munger/Pabrai quality investing lens.\n\n"
            f"Pre-computed signals:\n{json.dumps(payload, indent=2)}\n\n"
            f"Return JSON matching exactly this schema:\n"
            f'{{"lens": "quality", "score": <int 1-10>, "thesis": "<2-3 sentences>", '
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

        return {
            "lens":        "quality",
            "score":       int(raw.get("score", 5)),
            "thesis":      raw.get("thesis", ""),
            "key_signals": raw.get("key_signals", []),
            "risks":       raw.get("risks", []),
            "action":      raw.get("action", "hold"),
        }

    except Exception as e:
        # Per CLAUDE.md Rule 5 (agent exception): one agent failure must never
        # abort the whole pipeline.
        return {"lens": "quality", "error": str(e)}
