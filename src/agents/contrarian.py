# ============================================================
# FILE: src/agents/contrarian.py
# PURPOSE: Contrarian analyst agent — Burry/Druckenmiller lens.
#          Surfaces risks others ignore: pledging, debt stress,
#          earnings quality gaps, and cash flow deterioration.
#          Pre-computes debt service coverage in Python, then asks
#          GPT-4o to assess downside risk from this lens.
#          Never re-computes signals.
# INPUT:   data (dict) — scraper output
#          signals (dict) — output of signals.py
#          news (dict | None) — output of news.py
# OUTPUT:  dict: lens, score, thesis, key_signals, risks, action
# DEPENDS: openai, .env (OPENAI_API_KEY)
# ============================================================

# Philosophy: Michael Burry's adversarial research (find the stress others miss)
# combined with Stanley Druckenmiller's macro-aware risk discipline. This analyst
# treats every investment as guilty until proven innocent. High promoter pledging,
# deteriorating interest coverage, and accrual earnings are near-disqualifiers.
# The score here is a RISK score — a low score means high risk, high score means
# few red flags found.

import json
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def _safe(values, idx):
    """
    Safely retrieve values[idx], returning None on any failure.

    Args:
        values: A list (or anything else).
        idx:    Integer index (positive or negative).

    Returns:
        The value at that index, or None if out-of-range / not a list / None value.
    """
    if not isinstance(values, list) or len(values) == 0:
        return None
    try:
        v = values[idx]
        return v if v is not None else None
    except IndexError:
        return None


def _compute_debt_service_coverage(data: dict) -> dict:
    """
    Compute Debt Service Coverage Ratio (DSCR) from scraper data.

    DSCR = Operating Cash Flow / Interest Expense
    DSCR >= 2.0 = comfortable; DSCR < 1.0 = distress (can't cover interest from ops).

    Args:
        data: Full scraper output dict.

    Returns:
        dict with keys: dscr (float|None), dscr_verdict (str|None),
        dscr_reason (str|None).
    """
    result = {"dscr": None, "dscr_verdict": None, "dscr_reason": None}

    cf = data.get("cash_flow", {})
    pl = data.get("pl_table", {})

    ocf      = _safe(cf.get("operating"), 0)
    interest = _safe(pl.get("interest"), 0)

    if ocf is None:
        result["dscr_reason"] = "operating cash flow unavailable"
        return result
    if interest is None:
        result["dscr_reason"] = "interest expense unavailable"
        return result
    if interest <= 0:
        # Zero or negative interest means debt-free or negligible debt — great signal.
        result["dscr"] = None
        result["dscr_verdict"] = "debt_free_or_negligible"
        result["dscr_reason"] = f"interest expense = {interest} (near zero — debt is minimal)"
        return result

    dscr = ocf / interest
    result["dscr"] = round(dscr, 2)

    if dscr >= 3.0:
        result["dscr_verdict"] = "comfortable"
    elif dscr >= 1.5:
        result["dscr_verdict"] = "adequate"
    elif dscr >= 1.0:
        result["dscr_verdict"] = "tight"
    else:
        result["dscr_verdict"] = "distress"

    return result


def analyze(data: dict, signals: dict, news: dict | None) -> dict:
    """
    Contrarian analyst agent — Burry/Druckenmiller investing lens.

    Pre-computes debt service coverage in Python, then sends a compact
    payload focused on downside risks to GPT-4o asking it to evaluate
    the stock from an adversarial, risk-first perspective.

    All numerical signals have been computed by signals.py. This function
    does NOT ask GPT-4o to recompute or second-guess them.

    Note on scoring: A HIGH score (8–10) from this analyst means FEW red flags
    found. A LOW score (1–3) means serious risk signals. This is consistent with
    all other agents — score represents conviction to own, not level of risk.

    Args:
        data:    Full scraper output from fetch_company_data().
        signals: Pre-computed signal dict from compute_signals().
        news:    News + sentiment dict from fetch_news(), or None.

    Returns:
        dict with keys:
            lens (str):         "contrarian"
            score (int):        1–10 conviction score (high = few red flags)
            thesis (str):       2–3 sentence risk thesis
            key_signals (list): 3 risk signals that drove the score
            risks (list):       1–3 most serious risks identified
            action (str):       "buy" | "hold" | "sell" | "avoid"

        On any failure, returns {"lens": "contrarian", "error": str(e)}.
    """
    try:
        # --- Extract relevant sub-dicts from pre-computed signals ---
        pr  = signals.get("promoter_risk", {})
        bsh = signals.get("balance_sheet_health", {})
        eq  = signals.get("earnings_quality", {})
        pit = signals.get("piotroski", {})
        qm  = signals.get("quarterly_momentum", {})

        # --- Python pre-computation: Debt Service Coverage Ratio ---
        dscr = _compute_debt_service_coverage(data)

        # --- Build compact payload for GPT-4o ---
        # Contrarian payload is deliberately risk-focused — only the signals
        # that surface stress, distress, or governance concerns.
        payload = {
            "company":  data.get("header", {}).get("name", "Unknown"),
            "sector":   data.get("header", {}).get("sector", "Unknown"),
            "current_price_inr": data.get("header", {}).get("current_price"),
            "promoter_risk": {
                "pledged_pct":             pr.get("pledged_pct"),
                "pledge_flag":             pr.get("pledge_flag"),
                "pledge_trend":            pr.get("pledge_trend"),
                "promoter_holding":        pr.get("promoter_holding"),
                "promoter_holding_change": pr.get("promoter_holding_change"),
            },
            "balance_sheet_stress": {
                "debt_to_equity":    bsh.get("debt_to_equity_latest"),
                "debt_trend":        bsh.get("debt_trend"),
                "interest_coverage": bsh.get("interest_coverage"),
            },
            "debt_service_coverage": {
                "dscr":         dscr["dscr"],
                "dscr_verdict": dscr["dscr_verdict"],
                "dscr_reason":  dscr["dscr_reason"],
            },
            "earnings_quality": {
                "quality_flag":      eq.get("quality_flag"),
                "ocf_to_net_profit": eq.get("ocf_to_net_profit"),
                "fcf_to_net_profit": eq.get("fcf_to_net_profit"),
            },
            "piotroski": {
                "score": pit.get("score"),
                "label": pit.get("label"),
            },
            "quarterly_deceleration": {
                "revenue_yoy_pct": qm.get("revenue_yoy_pct"),
                "profit_yoy_pct":  qm.get("profit_yoy_pct"),
                "opm_trend":       qm.get("opm_trend"),
            },
            "news_sentiment": news.get("sentiment") if news else None,
            "news_reason":    news.get("sentiment_reason") if news else None,
        }

        # --- System prompt: Burry/Druckenmiller adversarial risk philosophy ---
        system_prompt = (
            "You are a senior risk analyst and contrarian investor, trained in the "
            "methods of Michael Burry and Stanley Druckenmiller. "
            "You invest in Indian public companies listed on NSE/BSE. "
            "\n\n"
            "Your investment philosophy:\n"
            "- Every investment is guilty until proven innocent. You look for the risks "
            "  that consensus investors overlook.\n"
            "- Promoter pledging above 15% is a serious governance red flag — pledged "
            "  shares can trigger forced sales if the stock falls, creating a doom loop.\n"
            "- Debt Service Coverage < 1.5x means the business cannot comfortably cover "
            "  interest from operations — a rate rise or revenue dip could cause distress.\n"
            "- Earnings quality (OCF < NI) means reported profits exceed actual cash "
            "  generation — this is a classic precursor to earnings restatements.\n"
            "- You produce a RISK SCORE: 9–10 means very few red flags found (it's safe "
            "  to own). 1–3 means serious risks that should keep most investors away.\n"
            "- You explicitly name the downside scenario: what would have to go wrong, "
            "  and what would happen to the stock if it did.\n"
            "\n\n"
            "CRITICAL RULES:\n"
            "1. All numerical signals have been pre-computed in Python. Do NOT "
            "   recompute or second-guess them. If a value is null, acknowledge it.\n"
            "2. Your score (1–10): 9–10 = clean bill of health, 7–8 = minor concerns, "
            "   5–6 = notable risk present, 3–4 = serious risk, 1–2 = avoid.\n"
            "3. Return ONLY valid JSON matching the schema. No prose outside JSON.\n"
            "4. key_signals must be 3 specific risk data points (e.g. "
            "   'Promoter pledging 28% — increasing trend — high flag').\n"
        )

        user_prompt = (
            f"Analyse this Indian stock from a Burry/Druckenmiller contrarian risk lens.\n\n"
            f"Pre-computed signals:\n{json.dumps(payload, indent=2)}\n\n"
            f"Return JSON matching exactly this schema:\n"
            f'{{"lens": "contrarian", "score": <int 1-10>, "thesis": "<2-3 sentences>", '
            f'"key_signals": ["<risk 1>", "<risk 2>", "<risk 3>"], '
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
            "lens":        "contrarian",
            "score":       int(raw.get("score", 5)),
            "thesis":      raw.get("thesis", ""),
            "key_signals": raw.get("key_signals", []),
            "risks":       raw.get("risks", []),
            "action":      raw.get("action", "hold"),
        }

    except Exception as e:
        # Per CLAUDE.md Rule 5 (agent exception): one agent failure must never
        # abort the whole pipeline.
        return {"lens": "contrarian", "error": str(e)}
