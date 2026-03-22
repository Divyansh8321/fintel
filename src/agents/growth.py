# ============================================================
# FILE: src/agents/growth.py
# PURPOSE: Growth analyst agent — Lynch/Fisher investing lens.
#          Evaluates a stock through revenue acceleration, PEG
#          ratio, and margin expansion. Pre-computes PEG ratio
#          in Python, then asks GPT-4o to interpret signals
#          from this lens. Never re-computes signals.
# INPUT:   data (dict) — scraper output
#          signals (dict) — output of signals.py
#          news (dict | None) — output of news.py
# OUTPUT:  dict: lens, score, thesis, key_signals, risks, action
# DEPENDS: openai, .env (OPENAI_API_KEY)
# ============================================================

# Philosophy: Peter Lynch's GARP (Growth at a Reasonable Price) combined with
# Phil Fisher's emphasis on durable, compounding revenue growth and widening
# margins. This analyst pays up for growth — but only when growth is real,
# accelerating, and not overpriced relative to the growth rate (PEG < 1.0).

import json
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def _compute_peg(signals: dict, data: dict) -> dict:
    """
    Compute the PEG (Price/Earnings to Growth) ratio.

    PEG = PE / profit_cagr_3yr
    A PEG < 1.0 signals that the stock may be cheap relative to its growth rate.
    A PEG > 2.0 signals the growth is priced in (or overpriced).

    Args:
        signals: Pre-computed signal dict from compute_signals().
        data:    Full scraper output dict.

    Returns:
        dict with keys: peg_ratio (float | None), peg_verdict (str | None),
        peg_reason (str | None).
    """
    result = {"peg_ratio": None, "peg_verdict": None, "peg_reason": None}

    pe = signals.get("valuation", {}).get("pe_current")
    cagr = data.get("growth_rates", {}).get("profit_cagr_3yr")

    if pe is None:
        result["peg_reason"] = "PE ratio unavailable"
        return result
    if pe <= 0:
        result["peg_reason"] = f"PE is non-positive ({pe})"
        return result
    if cagr is None:
        result["peg_reason"] = "3-year profit CAGR unavailable"
        return result
    if cagr <= 0:
        result["peg_reason"] = f"3yr profit CAGR is non-positive ({cagr}%)"
        return result

    peg = pe / cagr
    result["peg_ratio"] = round(peg, 2)

    # PEG interpretation: Lynch considered < 1.0 cheap, > 2.0 expensive
    if peg < 1.0:
        result["peg_verdict"] = "attractive"
    elif peg < 2.0:
        result["peg_verdict"] = "fair"
    else:
        result["peg_verdict"] = "expensive"

    return result


def analyze(data: dict, signals: dict, news: dict | None) -> dict:
    """
    Growth analyst agent — Lynch/Fisher investing lens.

    Pre-computes PEG ratio in Python, then sends a compact payload of
    pre-computed growth signals to GPT-4o asking it to evaluate the stock
    from a GARP (Growth at a Reasonable Price) perspective.

    All numerical signals have been computed by signals.py. This function
    does NOT ask GPT-4o to recompute or second-guess them.

    Args:
        data:    Full scraper output from fetch_company_data().
        signals: Pre-computed signal dict from compute_signals().
        news:    News + sentiment dict from fetch_news(), or None.

    Returns:
        dict with keys:
            lens (str):         "growth"
            score (int):        1–10 conviction score
            thesis (str):       2–3 sentence investment thesis
            key_signals (list): 3 signals that drove the score
            risks (list):       1–3 risks this analyst highlights
            action (str):       "buy" | "hold" | "sell" | "avoid"

        On any failure, returns {"lens": "growth", "error": str(e)}.
    """
    try:
        # --- Extract relevant sub-dicts from pre-computed signals ---
        gq  = signals.get("growth_quality", {})
        qm  = signals.get("quarterly_momentum", {})
        dup = signals.get("dupont", {})
        val = signals.get("valuation", {})
        gr  = data.get("growth_rates", {})

        # --- Python pre-computation: PEG ratio ---
        peg = _compute_peg(signals, data)

        # --- Build compact payload for GPT-4o ---
        payload = {
            "company":      data.get("header", {}).get("name", "Unknown"),
            "sector":       data.get("header", {}).get("sector", "Unknown"),
            "company_type": "bank_or_nbfc" if data.get("is_bank") else "non_financial",
            "current_price_inr": data.get("header", {}).get("current_price"),
            "growth_rates": {
                "revenue_cagr_3yr_pct":  gr.get("sales_cagr_3yr"),
                "revenue_cagr_5yr_pct":  gr.get("sales_cagr_5yr"),
                "profit_cagr_3yr_pct":   gr.get("profit_cagr_3yr"),
                "profit_cagr_5yr_pct":   gr.get("profit_cagr_5yr"),
            },
            "growth_quality": {
                "acceleration":    gq.get("acceleration"),
                "margin_trend":    gq.get("margin_trend"),
            },
            "quarterly_momentum": {
                "revenue_yoy_pct": qm.get("revenue_yoy_pct"),
                "profit_yoy_pct":  qm.get("profit_yoy_pct"),
                "opm_trend":       qm.get("opm_trend"),
            },
            "peg": {
                "peg_ratio":   peg["peg_ratio"],
                "peg_verdict": peg["peg_verdict"],
                "peg_reason":  peg["peg_reason"],
            },
            "dupont": {
                "roe_driver":    dup.get("roe_driver"),
                "net_margin_pct": dup.get("net_margin"),
                "roe_computed_pct": dup.get("roe_computed"),
            },
            "pe_current": val.get("pe_current"),
            "industry_pe": val.get("industry_pe"),
            "pe_vs_industry": (
                round(val.get("pe_current") / val.get("industry_pe"), 2)
                if val.get("pe_current") and val.get("industry_pe") else None
            ),
            "price_to_sales": val.get("price_to_sales"),
            "earnings_yield_pct": val.get("earnings_yield"),
            "news_sentiment": news.get("sentiment") if news else None,
        }

        # --- System prompt: Lynch/Fisher growth investing philosophy ---
        system_prompt = (
            "You are a senior equity analyst at a growth investment fund, "
            "trained in the methods of Peter Lynch and Phil Fisher. "
            "You invest in Indian public companies listed on NSE/BSE. "
            "\n\n"
            "Your investment philosophy:\n"
            "- You seek businesses with durable, compounding revenue and profit growth.\n"
            "- You use the PEG ratio (PE / profit_cagr_3yr) as your primary valuation tool. "
            "  PEG < 1.0 = growth is cheap. PEG > 2.0 = growth is priced in.\n"
            "- You prize margin expansion — a business that is both growing and improving "
            "  margins is compounding its earning power.\n"
            "- Revenue acceleration (growth rate increasing, not just positive) is a strong "
            "  positive signal — it suggests the business has pricing power and operating leverage.\n"
            "- You are willing to pay a premium PE for a truly exceptional grower, but never "
            "  for a stagnating business.\n"
            "- Quarterly momentum (YoY revenue and profit growth) is your leading indicator.\n"
            "\n\n"
            "CRITICAL RULES:\n"
            "1. All numerical signals have been pre-computed in Python. Do NOT "
            "   recompute or second-guess them. If a value is null, acknowledge it.\n"
            "2. Your score (1–10) must follow from the signals provided:\n"
            "   9–10 = strong acceleration, PEG < 1.0, widening margins\n"
            "   7–8  = solid growth, reasonable PEG\n"
            "   5–6  = moderate growth or mixed margin trend\n"
            "   3–4  = decelerating growth or expensive PEG\n"
            "   1–2  = declining revenue/profit or no growth\n"
            "3. Return ONLY valid JSON matching the schema. No prose outside JSON.\n"
            "4. key_signals must be 3 specific data points (e.g. "
            "   'Revenue CAGR 3yr: 22%, accelerating — margins expanding from 14% to 18%').\n"
        )

        user_prompt = (
            f"Analyse this Indian stock from a Lynch/Fisher growth investing lens.\n\n"
            f"Pre-computed signals:\n{json.dumps(payload, indent=2)}\n\n"
            f"Return JSON matching exactly this schema:\n"
            f'{{"lens": "growth", "score": <int 1-10>, "thesis": "<2-3 sentences>", '
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
            "lens":        "growth",
            "score":       int(raw.get("score", 5)),
            "thesis":      raw.get("thesis", ""),
            "key_signals": raw.get("key_signals", []),
            "risks":       raw.get("risks", []),
            "action":      raw.get("action", "hold"),
        }

    except Exception as e:
        # Per CLAUDE.md Rule 5 (agent exception): one agent failure must never
        # abort the whole pipeline.
        return {"lens": "growth", "error": str(e)}
