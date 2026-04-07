# ============================================================
# FILE: src/agents/momentum.py
# PURPOSE: Momentum analyst agent — quantitative momentum lens.
#          Evaluates a stock through price momentum (52w position),
#          earnings acceleration, and sentiment alignment. Reads pre-
#          computed 52-week range position from signals.price_momentum,
#          then asks GPT-4o to interpret signals from this lens.
#          Never re-computes signals.
# INPUT:   signals (SignalsModel) — output of signals.py
#          news (dict | None) — output of news.py
# OUTPUT:  dict: lens, score, thesis, key_signals, risks, action
# DEPENDS: src/llm.py, src/models.py
# ============================================================

# Philosophy: Quantitative momentum investing — the empirical observation that
# stocks with strong recent price and earnings momentum tend to continue
# outperforming in the near term. This analyst cares about trend direction,
# not intrinsic value. A stock at 52w highs with accelerating earnings and
# positive news sentiment is a strong momentum buy.

import json

from src.llm import call_analysis_model
from src.models import SignalsModel


def analyze(signals: SignalsModel, news: dict | None) -> dict:
    """
    Momentum analyst agent — quantitative momentum lens.

    Reads pre-computed 52-week price range position from signals.price_momentum,
    then sends a compact payload of momentum signals to GPT-4o asking it to
    evaluate the stock's trend strength and near-term momentum outlook.

    All numerical signals have been computed by signals.py. This function
    does NOT ask GPT-4o to recompute or second-guess them.

    Args:
        signals: Pre-computed SignalsModel from compute_signals().
        news:    News + sentiment dict from fetch_news(), or None.

    Returns:
        dict with keys:
            lens (str):         "momentum"
            score (int):        1–10 conviction score
            thesis (str):       2–3 sentence momentum thesis
            key_signals (list): 3 signals that drove the score
            risks (list):       1–3 risks this analyst highlights
            action (str):       "buy" | "hold" | "sell" | "avoid"

        On any failure, returns {"lens": "momentum", "error": str(e)}.
    """
    try:
        # --- Extract relevant sub-models from pre-computed signals ---
        qm  = signals.quarterly_momentum
        val = signals.valuation
        gq  = signals.growth_quality
        w52 = signals.price_momentum

        # --- Build compact payload for GPT-4o ---
        payload = {
            "company":      signals.meta.name,
            "sector":       signals.meta.sector,
            "company_type": "bank_or_nbfc" if signals.meta.is_bank else "non_financial",
            "price_momentum": {
                "current_price_inr": w52.current_price if w52 else None,
                "high_52w_inr":      w52.high_52w if w52 else None,
                "low_52w_inr":       w52.low_52w if w52 else None,
                "position_pct":      w52.position_pct if w52 else None,
                "position_verdict":  w52.position_verdict if w52 else None,
                "position_reason":   w52.position_reason if w52 else None,
            },
            "earnings_momentum": {
                "revenue_yoy_pct": qm.revenue_yoy_pct if qm else None,
                "profit_yoy_pct":  qm.profit_yoy_pct if qm else None,
                "opm_trend":       qm.opm_trend if qm else None,
            },
            "growth_acceleration": {
                "acceleration":  gq.acceleration if gq else None,
                "margin_trend":  gq.margin_trend if gq else None,
            },
            "valuation_context": {
                "earnings_yield_pct": val.earnings_yield if val else None,
                "pe_current":         val.pe_current if val else None,
                "industry_pe":        val.industry_pe if val else None,
                "pe_vs_industry": (
                    round(val.pe_current / val.industry_pe, 2)
                    if val and val.pe_current and val.industry_pe else None
                ),
            },
            "news_sentiment":        news.get("sentiment") if news else None,
            "news_sentiment_reason": news.get("sentiment_reason") if news else None,
        }

        # --- System prompt: quantitative momentum philosophy ---
        system_prompt = (
            "You are a quantitative momentum analyst at a systematic equity fund. "
            "You invest in Indian public companies listed on NSE/BSE. "
            "\n\n"
            "Your investment philosophy:\n"
            "- Trend is your friend. Stocks with strong positive price and earnings "
            "  momentum tend to continue outperforming in the near term (3–12 months).\n"
            "- 52-week range position is your primary price signal: a stock in the "
            "  upper 30% of its 52w range shows accumulation by institutional buyers.\n"
            "- Earnings momentum (YoY revenue and profit growth accelerating) confirms "
            "  that the price trend is backed by fundamental improvement.\n"
            "- News sentiment alignment (bullish news + strong price + earnings growth) "
            "  is the ideal setup — all three signals pointing the same direction.\n"
            "- You are NOT a valuation investor — you do not care if the stock is "
            "  'cheap' by Graham Number. You care about the direction of the trend.\n"
            "- Trend reversals (stock near 52w low, decelerating earnings, bearish news) "
            "  are strong sell signals.\n"
            "\n\n"
            "BANKS AND NBFCs — read this if company_type = 'bank_or_nbfc':\n"
            "- Momentum signals (52w range, earnings YoY) apply normally to banks — "
            "  price momentum is price momentum regardless of sector.\n"
            "- OPM % for banks is 'Financing Margin %' and is typically reported as "
            "  negative by Screener — do NOT interpret a negative OPM trend as margin "
            "  deterioration. Focus on revenue YoY and profit YoY for earnings momentum.\n"
            "- Valuation context: for banks ignore earnings yield as primary metric; "
            "  P/B ratio is more meaningful — a bank near 52w highs with P/B < 2x "
            "  still has valuation headroom; P/B > 4x with slowing growth is a risk.\n"
            "\n\n"
            "CRITICAL RULES:\n"
            "1. All numerical signals have been pre-computed in Python. Do NOT "
            "   recompute or second-guess them. If a value is null, acknowledge it.\n"
            "2. Your score (1–10) must follow from momentum signals:\n"
            "   9–10 = near 52w high, accelerating earnings, bullish news\n"
            "   7–8  = strong earnings momentum, upper half of 52w range\n"
            "   5–6  = mixed momentum signals\n"
            "   3–4  = decelerating earnings or stock in lower half of range\n"
            "   1–2  = near 52w low, declining earnings, bearish news\n"
            "3. Return ONLY valid JSON matching the schema. No prose outside JSON.\n"
            "4. key_signals must be 3 specific data points (e.g. "
            "   'Price at 82% of 52w range — near highs, institutional accumulation likely').\n"
        )

        user_prompt = (
            f"Analyse this Indian stock from a quantitative momentum lens.\n\n"
            f"Pre-computed signals:\n{json.dumps(payload, indent=2)}\n\n"
            f"Return JSON matching exactly this schema:\n"
            f'{{"lens": "momentum", "score": <int 1-10>, "thesis": "<2-3 sentences>", '
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
            "lens":        "momentum",
            "score":       int(raw.get("score", 5)),
            "thesis":      raw.get("thesis", ""),
            "key_signals": raw.get("key_signals", []),
            "risks":       raw.get("risks", []),
            "action":      raw.get("action", "hold"),
        }

    except Exception as e:
        # Per CLAUDE.md Rule 5 (agent exception): one agent failure must never
        # abort the whole pipeline.
        return {"lens": "momentum", "error": str(e)}
