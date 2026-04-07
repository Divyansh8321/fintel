# ============================================================
# FILE: src/agents/contrarian.py
# PURPOSE: Contrarian analyst agent — Burry/Druckenmiller lens.
#          Surfaces risks others ignore: pledging, debt stress,
#          earnings quality gaps, and cash flow deterioration.
#          Reads pre-computed debt service coverage from signals.dscr,
#          then asks GPT-4o to assess downside risk from this lens.
#          Never re-computes signals.
# INPUT:   signals (SignalsModel) — output of signals.py
#          news (dict | None) — output of news.py
# OUTPUT:  dict: lens, score, thesis, key_signals, risks, action
# DEPENDS: src/llm.py, src/models.py
# ============================================================

# Philosophy: Michael Burry's adversarial research (find the stress others miss)
# combined with Stanley Druckenmiller's macro-aware risk discipline. This analyst
# treats every investment as guilty until proven innocent. High promoter pledging,
# deteriorating interest coverage, and accrual earnings are near-disqualifiers.
# The score here is a RISK score — a low score means high risk, high score means
# few red flags found.

import json

from src.llm import call_analysis_model
from src.models import SignalsModel


def analyze(signals: SignalsModel, news: dict | None) -> dict:
    """
    Contrarian analyst agent — Burry/Druckenmiller investing lens.

    Reads pre-computed debt service coverage from signals.dscr, then sends a
    compact payload focused on downside risks to GPT-4o asking it to evaluate
    the stock from an adversarial, risk-first perspective.

    All numerical signals have been computed by signals.py. This function
    does NOT ask GPT-4o to recompute or second-guess them.

    Note on scoring: A HIGH score (8–10) from this analyst means FEW red flags
    found. A LOW score (1–3) means serious risk signals. This is consistent with
    all other agents — score represents conviction to own, not level of risk.

    Args:
        signals: Pre-computed SignalsModel from compute_signals().
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
        # --- Extract relevant sub-models from pre-computed signals ---
        pr   = signals.promoter_risk
        bsh  = signals.balance_sheet_health
        eq   = signals.earnings_quality
        pit  = signals.piotroski
        qm   = signals.quarterly_momentum
        dscr = signals.dscr

        # --- Build compact payload for GPT-4o ---
        # Contrarian payload is deliberately risk-focused — only the signals
        # that surface stress, distress, or governance concerns.
        payload = {
            "company":      signals.meta.name,
            "sector":       signals.meta.sector,
            "company_type": "bank_or_nbfc" if signals.meta.is_bank else "non_financial",
            "current_price_inr": signals.meta.current_price,
            "promoter_risk": {
                "pledged_pct":             pr.pledged_pct if pr else None,
                "pledge_flag":             pr.pledge_flag if pr else None,
                "pledge_trend":            pr.pledge_trend if pr else None,
                "promoter_holding":        pr.promoter_holding if pr else None,
                "promoter_holding_change": pr.promoter_holding_change if pr else None,
            },
            "balance_sheet_stress": {
                "debt_to_equity":    bsh.debt_to_equity_latest if bsh else None,
                "debt_trend":        bsh.debt_trend if bsh else None,
                "interest_coverage": bsh.interest_coverage if bsh else None,
            },
            "debt_service_coverage": {
                "dscr":         dscr.dscr if dscr else None,
                "dscr_verdict": dscr.dscr_verdict if dscr else None,
                "dscr_reason":  dscr.dscr_reason if dscr else None,
            },
            "earnings_quality": {
                "quality_flag":      eq.quality_flag if eq else None,
                "ocf_to_net_profit": eq.ocf_to_net_profit if eq else None,
                "fcf_to_net_profit": eq.fcf_to_net_profit if eq else None,
            },
            "piotroski": {
                "score": pit.score if pit else None,
                "label": pit.label if pit else None,
            },
            "quarterly_deceleration": {
                "revenue_yoy_pct": qm.revenue_yoy_pct if qm else None,
                "profit_yoy_pct":  qm.profit_yoy_pct if qm else None,
                "opm_trend":       qm.opm_trend if qm else None,
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
            "BANKS AND NBFCs — read this if company_type = 'bank_or_nbfc':\n"
            "- High D/E is NORMAL for banks — ignore D/E as a risk signal. "
            "  Banks fund themselves with deposits and bonds; D/E of 8–12x is standard.\n"
            "- The key risk signals for banks are: "
            "  (1) Gross NPA % — non-performing loans as % of total loans. "
            "      <2% = clean, 2–5% = watch, >5% = distress. "
            "  (2) Net NPA % — after provisioning. >2% means under-provisioned. "
            "  (3) Capital Adequacy Ratio (CAR/CRAR) — RBI minimum ~11.5%. "
            "      A bank with CAR <12% has thin buffer against loan losses. "
            "  (4) NIM compression — falling net interest margin means pricing power "
            "      is eroding or funding costs are rising faster than loan yields.\n"
            "- DSCR (debt service coverage) is not meaningful for banks — interest "
            "  expense is their primary operating cost, not a coverage concern.\n"
            "- Promoter pledging remains a red flag regardless of company type.\n"
            "\n\n"
            "CRITICAL RULES:\n"
            "1. All numerical signals have been pre-computed in Python. Do NOT "
            "   recompute or second-guess them. If a value is null, acknowledge it.\n"
            "2. If piotroski.label is 'not_applicable', this is a bank or NBFC. "
            "   Do NOT reference or penalise based on Piotroski score. For banks, "
            "   focus your risk assessment on NPA quality, DSCR, and pledging instead.\n"
            "3. Your score (1–10): 9–10 = clean bill of health, 7–8 = minor concerns, "
            "   5–6 = notable risk present, 3–4 = serious risk, 1–2 = avoid.\n"
            "4. Return ONLY valid JSON matching the schema. No prose outside JSON.\n"
            "5. key_signals must be 3 specific risk data points (e.g. "
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

        # --- Analysis model call ---
        raw = json.loads(call_analysis_model(
            system=system_prompt,
            user=user_prompt,
            max_tokens=500,
            response_format={"type": "json_object"},
        ))

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
