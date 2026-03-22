# ============================================================
# FILE: src/agents/quality.py
# PURPOSE: Quality analyst agent — Munger/Pabrai investing lens.
#          Evaluates a stock through ROCE vs WACC spread, durable
#          competitive advantages, and earnings quality. Pre-computes
#          ROCE-WACC spread in Python, then asks GPT-4o to interpret
#          signals from this lens. Never re-computes signals.
# INPUT:   data (dict) — scraper output
#          signals (dict) — output of signals.py
#          news (dict | None) — output of news.py
# OUTPUT:  dict: lens, score, thesis, key_signals, risks, action
# DEPENDS: openai, .env (OPENAI_API_KEY)
# ============================================================

# Philosophy: Charlie Munger's "wonderful company at a fair price" combined
# with Mohnish Pabrai's checklist-driven quality investing. This analyst
# prizes businesses that consistently earn above their cost of capital (ROCE
# > WACC), have high earnings quality (OCF > NI), and are run by managers
# who allocate capital well (stable/improving margins, no unnecessary debt).

import json
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Proxy for Indian equity WACC — 10yr Gsec (7.2%) + equity risk premium (~4.8%).
# Fixed at 12% consistent with DCF assumptions across the project.
_WACC_PROXY = 12.0


def _compute_roce_wacc_spread(signals: dict) -> dict:
    """
    Compute the spread between ROCE and the WACC proxy.

    A positive spread means the business is creating value above its cost of
    capital — the hallmark of a quality compounder. A negative spread means
    the business is destroying value even as it grows.

    Args:
        signals: Pre-computed signal dict from compute_signals().

    Returns:
        dict with keys: roce_latest (float|None), wacc_proxy (float),
        roce_wacc_spread (float|None), spread_verdict (str|None),
        spread_reason (str|None).
    """
    result = {
        "roce_latest": None,
        "wacc_proxy": _WACC_PROXY,
        "roce_wacc_spread": None,
        "spread_verdict": None,
        "spread_reason": None,
    }

    roce = signals.get("capital_efficiency", {}).get("roce_latest")
    if roce is None:
        result["spread_reason"] = "ROCE data unavailable"
        return result

    spread = roce - _WACC_PROXY
    result["roce_latest"] = round(roce, 2)
    result["roce_wacc_spread"] = round(spread, 2)

    # Interpretation: > 5% spread = clear value creator, < 0% = value destroyer
    if spread >= 5.0:
        result["spread_verdict"] = "strong_value_creator"
    elif spread >= 0.0:
        result["spread_verdict"] = "marginal_value_creator"
    else:
        result["spread_verdict"] = "value_destroyer"

    return result


def analyze(data: dict, signals: dict, news: dict | None) -> dict:
    """
    Quality analyst agent — Munger/Pabrai investing lens.

    Pre-computes ROCE vs WACC spread in Python, then sends a compact
    payload of pre-computed quality signals to GPT-4o asking it to
    evaluate the stock from a quality-at-fair-price perspective.

    All numerical signals have been computed by signals.py. This function
    does NOT ask GPT-4o to recompute or second-guess them.

    Args:
        data:    Full scraper output from fetch_company_data().
        signals: Pre-computed signal dict from compute_signals().
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
        # --- Extract relevant sub-dicts from pre-computed signals ---
        ce  = signals.get("capital_efficiency", {})
        eq  = signals.get("earnings_quality", {})
        dup = signals.get("dupont", {})
        pit = signals.get("piotroski", {})
        gq  = signals.get("growth_quality", {})
        val = signals.get("valuation", {})

        # --- Python pre-computation: ROCE vs WACC spread ---
        spread = _compute_roce_wacc_spread(signals)

        # --- Build compact payload for GPT-4o ---
        payload = {
            "company": data.get("header", {}).get("name", "Unknown"),
            "sector":  data.get("header", {}).get("sector", "Unknown"),
            "current_price_inr": data.get("header", {}).get("current_price"),
            "capital_efficiency": {
                "roce_latest_pct":  spread["roce_latest"],
                "roce_trend":       ce.get("roce_trend"),
                "roce_3yr_avg_pct": ce.get("roce_3yr_avg"),
                "wacc_proxy_pct":   spread["wacc_proxy"],
                "roce_wacc_spread":  spread["roce_wacc_spread"],
                "spread_verdict":   spread["spread_verdict"],
                "interest_coverage": ce.get("interest_coverage"),
                "wc_trend":         ce.get("wc_trend"),
            },
            "earnings_quality": {
                "quality_flag":        eq.get("quality_flag"),
                "ocf_to_net_profit":   eq.get("ocf_to_net_profit"),
                "fcf_to_net_profit":   eq.get("fcf_to_net_profit"),
            },
            "dupont": {
                "net_margin_pct":    dup.get("net_margin"),
                "roe_computed_pct":  dup.get("roe_computed"),
                "roe_driver":        dup.get("roe_driver"),
                "asset_turnover":    dup.get("asset_turnover"),
            },
            "piotroski": {
                "score": pit.get("score"),
                "label": pit.get("label"),
            },
            "growth_quality": {
                "margin_trend":   gq.get("margin_trend"),
                "acceleration":   gq.get("acceleration"),
            },
            "pe_current":       val.get("pe_current"),
            "industry_pe":      val.get("industry_pe"),
            "ev_ebitda":        val.get("ev_ebitda"),
            "promoter": {
                "promoter_holding":        signals.get("promoter_risk", {}).get("promoter_holding"),
                "promoter_holding_change": signals.get("promoter_risk", {}).get("promoter_holding_change"),
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
