# ============================================================
# FILE: src/analysis.py
# PURPOSE: Generates a structured investment brief by asking
#          GPT-4o to EXPLAIN pre-computed quantitative signals.
#          The LLM does NOT compute scores — Python already did
#          that in signals.py. The LLM's job is plain-English
#          interpretation of what those signals mean for THIS
#          specific company.
# INPUT:   data (dict)    — output of fetch_company_data()
#          signals (dict) — output of compute_signals()
#          news (dict)    — output of fetch_news() or None
# OUTPUT:  dict with verdict, explanations, risk_flags, etc.
# DEPENDS: openai, .env (OPENAI_API_KEY)
# ============================================================

import json
from datetime import datetime, timezone

from openai import OpenAI

# Module-level client — instantiated once, reused for all calls.
# OpenAI() automatically reads OPENAI_API_KEY from the environment.
_client = OpenAI()

SYSTEM_PROMPT = """\
You are a senior equity analyst explaining pre-computed quantitative signals to an investor.

You will receive a JSON object with:
  - "company": basic company info (name, price, market_cap, sector)
  - "key_ratios": current PE, ROE, ROCE, book_value, debt_to_equity
  - "pros_cons": Screener.in's machine-generated list of strengths and weaknesses
  - "signals": pre-computed signals from Python (Piotroski, DuPont, earnings quality, etc.)
  - "scores": mechanically derived fundamentals_score (1-10) and valuation_score (1-10)
  - "news": recent headlines and aggregate sentiment (may be null)

STRICT REQUIREMENTS:
1. You MUST NOT recompute or second-guess the scores — they are mechanically derived in Python.
2. Your job is to explain what the signals mean for THIS company in plain English.
3. Return ONLY valid JSON, no markdown, no code fences, no preamble.
4. Every field in the schema is required. Do not omit any field.
5. risk_flags must be a list of strings (empty list if no material risks).
6. All strings must be in English.

Output schema:
{
  "fundamentals_explanation": "<2 sentences explaining what drove the fundamentals_score>",
  "valuation_explanation": "<2 sentences explaining what drove the valuation_score>",
  "piotroski_interpretation": "<1 sentence: what does this F-score mean for this specific company>",
  "earnings_quality_note": "<1 sentence on OCF vs reported profit — is profit backed by cash?>",
  "dupont_note": "<1 sentence on what is driving ROE for this company>",
  "valuation_note": "<1 sentence: Graham Number context — why the premium or discount makes or does not make sense>",
  "quarterly_trend": "<1 sentence on what recent quarters tell us about business momentum>",
  "risk_flags": ["<risk 1>", "<risk 2>", ...],
  "verdict": "<3-5 sentence investment case summary integrating signals and news>",
  "data_freshness": "<ISO 8601 UTC timestamp>"
}

Fill data_freshness with the current UTC timestamp provided in the user message.
"""

# Required fields in the LLM output
_REQUIRED_FIELDS = {
    "fundamentals_explanation",
    "valuation_explanation",
    "piotroski_interpretation",
    "earnings_quality_note",
    "dupont_note",
    "valuation_note",
    "quarterly_trend",
    "risk_flags",
    "verdict",
    "data_freshness",
}


def generate_brief(data: dict, signals: dict, news: dict | None = None) -> dict:
    """
    Calls OpenAI gpt-4o with pre-computed signals and asks it to explain them.

    GPT-4o receives a compact payload — header, key_ratios, pros_cons, signals,
    and news. It does NOT receive the full 10-year P&L/balance sheet tables.
    This makes the LLM's job well-defined: explain, don't recompute.

    Args:
        data: Full company data dict as returned by fetch_company_data().
        signals: Pre-computed signals dict as returned by compute_signals().
        news: News dict as returned by fetch_news(), or None if unavailable.

    Returns:
        dict with keys: fundamentals_explanation, valuation_explanation,
        piotroski_interpretation, earnings_quality_note, dupont_note,
        valuation_note, quarterly_trend, risk_flags, verdict, data_freshness.

    Raises:
        ValueError: if the LLM response is not valid JSON or missing required fields.
        openai.OpenAIError: on API errors (auth failure, quota exceeded, etc.).
    """
    ticker = (
        data.get("header", {}).get("nse_code")
        or data.get("header", {}).get("name", "UNKNOWN")
    )
    now_utc = datetime.now(timezone.utc).isoformat()

    # Build a compact payload — only what the LLM needs to explain the signals.
    # Passing the full 10-year tables would waste tokens and encourage recomputation.
    payload = {
        "company": data.get("header", {}),
        "key_ratios": data.get("key_ratios", {}),
        "pros_cons": data.get("pros_cons", {}),
        "signals": signals,
        "scores": {
            "fundamentals_score": signals.get("fundamentals_score"),
            "valuation_score": signals.get("valuation_score"),
        },
        "news": news,
    }

    user_message = (
        f"Current UTC time: {now_utc}\n\n"
        f"Company data and signals:\n{json.dumps(payload, indent=2)}"
    )

    response = _client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
        temperature=0.2,
        max_tokens=1500,
    )

    raw = response.choices[0].message.content or ""

    try:
        brief = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError(
            f"LLM returned malformed JSON for ticker '{ticker}'. "
            f"Raw response (first 200 chars): {raw[:200]}"
        )

    missing = _REQUIRED_FIELDS - set(brief.keys())
    if missing:
        raise ValueError(
            f"LLM response for ticker '{ticker}' is missing required fields: "
            f"{sorted(missing)}. Raw response (first 200 chars): {raw[:200]}"
        )

    return brief
