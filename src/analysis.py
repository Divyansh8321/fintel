# ============================================================
# FILE: src/analysis.py
# PURPOSE: Generates a structured investment brief for a given
#          stock using OpenAI gpt-4o. Takes the full scraped
#          company data dict and returns a structured JSON brief.
# INPUT:   data (dict) — output of fetch_company_data()
# OUTPUT:  dict with fundamentals_score, valuation_score,
#          risk_flags, verdict, data_freshness
# DEPENDS: openai==1.35.0, .env (OPENAI_API_KEY)
# ============================================================

import json
from datetime import datetime, timezone

from openai import OpenAI

# Module-level client — instantiated once, reused for all calls.
# OpenAI() automatically reads OPENAI_API_KEY from the environment.
_client = OpenAI()

SYSTEM_PROMPT = """\
You are a professional equity research analyst specialising in Indian public markets.

You will receive a JSON object containing scraped financial data for a publicly listed Indian company.
The data includes unit metadata — pay attention to the "currency", "header_units", and per-section
"units" keys (e.g. {"scale": "Cr", "currency": "INR"}) so you correctly interpret the scale of numbers.

Your task is to produce a structured investment brief in JSON format.

STRICT REQUIREMENTS:
- Return ONLY valid JSON. No markdown, no code fences, no preamble, no explanation outside the JSON.
- Every field in the schema below is required. Do not omit any field.
- Scores must be integers in the range 1-10 (inclusive).
- risk_flags must be a list of strings (can be an empty list if no material risks).
- All string values must be in English.

Output schema:
{
  "fundamentals_score": <integer 1-10>,
  "fundamentals_explanation": "<exactly 2 sentences explaining the score>",
  "valuation_score": <integer 1-10>,
  "valuation_explanation": "<exactly 2 sentences explaining the score>",
  "risk_flags": ["<risk 1>", "<risk 2>", ...],
  "verdict": "<one paragraph (3-5 sentences) summarising the investment case>",
  "data_freshness": "<ISO 8601 UTC timestamp when this brief was generated>"
}

Scoring guide:
- fundamentals_score: 1 = very poor (declining revenue, losses, high debt), 10 = exceptional (strong growth, high ROCE, clean balance sheet)
- valuation_score: 1 = extremely overvalued, 10 = deeply undervalued relative to growth and quality

Fill data_freshness with the current UTC timestamp you receive in the user message.
"""


def generate_brief(data: dict) -> dict:
    """
    Calls OpenAI gpt-4o with the scraped company data and returns a
    structured investment brief as a Python dict.

    The LLM is instructed (via system prompt) to return ONLY valid JSON.
    If the response cannot be parsed as JSON, raises ValueError immediately
    — never returns malformed output.

    Args:
        data: Full company data dict as returned by fetch_company_data().
              Must contain at minimum the 'header' key so the ticker
              name can be referenced in error messages.

    Returns:
        dict with keys: fundamentals_score (int), fundamentals_explanation (str),
        valuation_score (int), valuation_explanation (str), risk_flags (list[str]),
        verdict (str), data_freshness (str ISO timestamp).

    Raises:
        ValueError:  if the LLM response is not valid JSON or is missing
                     required fields.
        openai.OpenAIError: on API errors (auth failure, quota exceeded, etc.).
    """
    ticker = data.get("header", {}).get("nse_code") or data.get("header", {}).get("name", "UNKNOWN")
    now_utc = datetime.now(timezone.utc).isoformat()

    user_message = (
        f"Current UTC time: {now_utc}\n\n"
        f"Company data:\n{json.dumps(data, indent=2)}"
    )

    response = _client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
        temperature=0.2,   # low temperature for consistent structured output
        max_tokens=1024,
    )

    raw = response.choices[0].message.content or ""

    try:
        brief = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError(
            f"LLM returned malformed JSON for ticker '{ticker}'. "
            f"Raw response (first 300 chars): {raw[:300]}"
        )

    # Validate all required fields are present
    required_keys = {
        "fundamentals_score",
        "fundamentals_explanation",
        "valuation_score",
        "valuation_explanation",
        "risk_flags",
        "verdict",
        "data_freshness",
    }
    missing = required_keys - set(brief.keys())
    if missing:
        raise ValueError(
            f"LLM response for ticker '{ticker}' is missing required fields: "
            f"{sorted(missing)}. Raw response (first 300 chars): {raw[:300]}"
        )

    return brief
