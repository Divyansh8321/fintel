# ============================================================
# FILE: src/agents/momentum.py
# PURPOSE: Momentum analyst agent — quantitative momentum lens.
#          Evaluates a stock through price momentum (52w position),
#          earnings acceleration, and sentiment alignment. Pre-computes
#          52-week range position in Python, then asks GPT-4o to
#          interpret signals from this lens. Never re-computes signals.
# INPUT:   data (dict) — scraper output
#          signals (dict) — output of signals.py
#          news (dict | None) — output of news.py
# OUTPUT:  dict: lens, score, thesis, key_signals, risks, action
# DEPENDS: openai, .env (OPENAI_API_KEY)
# ============================================================

# Philosophy: Quantitative momentum investing — the empirical observation that
# stocks with strong recent price and earnings momentum tend to continue
# outperforming in the near term. This analyst cares about trend direction,
# not intrinsic value. A stock at 52w highs with accelerating earnings and
# positive news sentiment is a strong momentum buy.

import json
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def _compute_52w_position(data: dict) -> dict:
    """
    Compute the stock's current price position within its 52-week range.

    Position = (current_price - 52w_low) / (52w_high - 52w_low) × 100
    0% = at 52-week low, 100% = at 52-week high.
    Stocks above 50% are in the upper half of their range (positive momentum).

    Args:
        data: Full scraper output dict.

    Returns:
        dict with keys: position_pct (float|None), high_52w (float|None),
        low_52w (float|None), current_price (float|None),
        position_verdict (str|None), position_reason (str|None).
    """
    result = {
        "position_pct":      None,
        "high_52w":          None,
        "low_52w":           None,
        "current_price":     None,
        "position_verdict":  None,
        "position_reason":   None,
    }

    hdr   = data.get("header", {})
    hi    = hdr.get("high_52w")
    lo    = hdr.get("low_52w")
    price = hdr.get("current_price")

    result["high_52w"]      = hi
    result["low_52w"]       = lo
    result["current_price"] = price

    if hi is None or lo is None or price is None:
        result["position_reason"] = "52w high/low or current price unavailable"
        return result
    if hi <= lo:
        result["position_reason"] = f"52w high ({hi}) <= low ({lo}) — data anomaly"
        return result

    pos = (price - lo) / (hi - lo) * 100
    result["position_pct"] = round(pos, 1)

    # Interpretation: above 70% = near 52w high (strong momentum)
    if pos >= 70.0:
        result["position_verdict"] = "near_52w_high"
    elif pos >= 50.0:
        result["position_verdict"] = "upper_half"
    elif pos >= 30.0:
        result["position_verdict"] = "lower_half"
    else:
        result["position_verdict"] = "near_52w_low"

    return result


def analyze(data: dict, signals: dict, news: dict | None) -> dict:
    """
    Momentum analyst agent — quantitative momentum lens.

    Pre-computes the 52-week price range position in Python, then sends
    a compact payload of momentum signals to GPT-4o asking it to evaluate
    the stock's trend strength and near-term momentum outlook.

    All numerical signals have been computed by signals.py. This function
    does NOT ask GPT-4o to recompute or second-guess them.

    Args:
        data:    Full scraper output from fetch_company_data().
        signals: Pre-computed signal dict from compute_signals().
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
        # --- Extract relevant sub-dicts from pre-computed signals ---
        qm  = signals.get("quarterly_momentum", {})
        val = signals.get("valuation", {})
        gq  = signals.get("growth_quality", {})

        # --- Python pre-computation: 52-week range position ---
        w52 = _compute_52w_position(data)

        # --- Build compact payload for GPT-4o ---
        payload = {
            "company": data.get("header", {}).get("name", "Unknown"),
            "sector":  data.get("header", {}).get("sector", "Unknown"),
            "price_momentum": {
                "current_price_inr": w52["current_price"],
                "high_52w_inr":      w52["high_52w"],
                "low_52w_inr":       w52["low_52w"],
                "position_pct":      w52["position_pct"],
                "position_verdict":  w52["position_verdict"],
                "position_reason":   w52["position_reason"],
            },
            "earnings_momentum": {
                "revenue_yoy_pct": qm.get("revenue_yoy_pct"),
                "profit_yoy_pct":  qm.get("profit_yoy_pct"),
                "opm_trend":       qm.get("opm_trend"),
            },
            "growth_acceleration": {
                "acceleration":  gq.get("acceleration"),
                "margin_trend":  gq.get("margin_trend"),
            },
            "valuation_context": {
                "earnings_yield_pct": val.get("earnings_yield"),
                "pe_current":         val.get("pe_current"),
                "industry_pe":        val.get("industry_pe"),
                "pe_vs_industry": (
                    round(val.get("pe_current") / val.get("industry_pe"), 2)
                    if val.get("pe_current") and val.get("industry_pe") else None
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

        # --- GPT-4o call ---
        response = _client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=500,
            response_format={"type": "json_object"},
        )

        # --- Parse and validate response ---
        raw = json.loads(response.choices[0].message.content)

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
