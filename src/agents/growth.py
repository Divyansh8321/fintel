# ============================================================
# FILE: src/agents/growth.py
# PURPOSE: Growth analyst agent — Lynch/Fisher investing lens.
#          Evaluates a stock through revenue acceleration, PEG
#          ratio, and margin expansion. Reads pre-computed PEG
#          from signals.peg, then asks GPT-4o to interpret signals
#          from this lens. Never re-computes signals.
# INPUT:   signals (SignalsModel) — output of signals.py
#          news (dict | None) — output of news.py
# OUTPUT:  dict: lens, score, thesis, key_signals, risks, action
# DEPENDS: src/llm.py, src/models.py
# ============================================================

# Philosophy: Peter Lynch's GARP (Growth at a Reasonable Price) combined with
# Phil Fisher's emphasis on durable, compounding revenue growth and widening
# margins. This analyst pays up for growth — but only when growth is real,
# accelerating, and not overpriced relative to the growth rate (PEG < 1.0).

import json

from src.llm import call_analysis_model
from src.models import SignalsModel


def analyze(signals: SignalsModel, news: dict | None) -> dict:
    """
    Growth analyst agent — Lynch/Fisher investing lens.

    Reads pre-computed PEG ratio from signals.peg, then sends a compact
    payload of pre-computed growth signals to GPT-4o asking it to evaluate
    the stock from a GARP (Growth at a Reasonable Price) perspective.

    All numerical signals have been computed by signals.py. This function
    does NOT ask GPT-4o to recompute or second-guess them.

    Args:
        signals: Pre-computed SignalsModel from compute_signals().
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
        # --- Extract relevant sub-models from pre-computed signals ---
        gq  = signals.growth_quality
        qm  = signals.quarterly_momentum
        dup = signals.dupont
        val = signals.valuation
        peg = signals.peg

        # --- Build compact payload for GPT-4o ---
        payload = {
            "company":      signals.meta.name,
            "sector":       signals.meta.sector,
            "company_type": "bank_or_nbfc" if signals.meta.is_bank else "non_financial",
            "current_price_inr": signals.meta.current_price,
            "growth_rates": {
                "revenue_cagr_3yr_pct":  gq.revenue_cagr_3yr if gq else None,
                "revenue_cagr_5yr_pct":  gq.revenue_cagr_5yr if gq else None,
                "profit_cagr_3yr_pct":   gq.profit_cagr_3yr if gq else None,
                "profit_cagr_5yr_pct":   gq.profit_cagr_5yr if gq else None,
            },
            "growth_quality": {
                "acceleration":    gq.acceleration if gq else None,
                "margin_trend":    gq.margin_trend if gq else None,
            },
            "quarterly_momentum": {
                "revenue_yoy_pct": qm.revenue_yoy_pct if qm else None,
                "profit_yoy_pct":  qm.profit_yoy_pct if qm else None,
                "opm_trend":       qm.opm_trend if qm else None,
            },
            "peg": {
                "peg_ratio":   peg.peg_ratio if peg else None,
                "peg_verdict": peg.peg_verdict if peg else None,
                "peg_reason":  peg.peg_reason if peg else None,
            },
            "dupont": {
                "roe_driver":    dup.roe_driver if dup else None,
                "net_margin_pct": dup.net_margin if dup else None,
                "roe_computed_pct": dup.roe_computed if dup else None,
            },
            "pe_current": val.pe_current if val else None,
            "industry_pe": val.industry_pe if val else None,
            "pe_vs_industry": (
                round(val.pe_current / val.industry_pe, 2)
                if val and val.pe_current and val.industry_pe else None
            ),
            "price_to_sales": val.price_to_sales if val else None,
            "earnings_yield_pct": val.earnings_yield if val else None,
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
            "BANKS AND NBFCs — read this if company_type = 'bank_or_nbfc':\n"
            "- Revenue for banks = interest income + fee income (not product sales). "
            "  Revenue growth reflects loan book expansion and rate environment, not "
            "  organic product demand — contextualise accordingly.\n"
            "- OPM % for banks is 'Financing Margin %' (net interest margin proxy). "
            "  It is typically negative in Screener's format because interest expense is "
            "  subtracted — do NOT treat a negative OPM as a red flag for banks.\n"
            "- PEG ratio is less meaningful for banks — loan growth and NIM expansion "
            "  are better growth quality signals than profit CAGR alone.\n"
            "- Margin trend for banks means NIM trend (net interest margin) — "
            "  expanding NIM means the bank is repricing loans faster than deposits.\n"
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

        # --- Analysis model call ---
        raw = json.loads(call_analysis_model(
            system=system_prompt,
            user=user_prompt,
            max_tokens=500,
            response_format={"type": "json_object"},
        ))

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
