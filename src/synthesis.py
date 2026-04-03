# ============================================================
# FILE: src/synthesis.py
# PURPOSE: Aggregates the five analyst notes (value, growth,
#          quality, contrarian, momentum) into a single weighted
#          consensus score, bull case, bear case, and final verdict.
#          Makes exactly 1 GPT-4o call. Python computes the weighted
#          score; GPT-4o writes the narrative synthesis only.
# INPUT:   analyst_notes (list[dict]) — output of all 5 agent analyze()
#          data (dict) — scraper output (for company name/sector)
# OUTPUT:  dict: consensus_score, weighted_score, action_tally,
#                bull_case, bear_case, verdict, analyst_notes
# DEPENDS: src/llm.py
# ============================================================

import json

from src.llm import call_analysis_model

# Synthesis weights per CLAUDE.md spec.
# Must sum to 1.0.
_WEIGHTS = {
    "value":      0.25,
    "quality":    0.25,
    "growth":     0.20,
    "contrarian": 0.20,
    "momentum":   0.10,
}

# Minimum valid score for an agent note to be included in the weighted average.
# Notes with an "error" key are excluded and their weight is redistributed.
_MIN_SCORE = 1
_MAX_SCORE = 10


def compute_weighted_score(notes: list[dict]) -> dict:
    """
    Compute the weighted consensus score from analyst notes in Python.

    Only notes without an "error" key are included. If an agent errored,
    its weight is redistributed proportionally across the remaining agents.

    Args:
        notes: List of agent output dicts, each with at least "lens" and "score".

    Returns:
        dict with keys:
            weighted_score (float | None): the weighted average score (1–10),
                None if all agents failed.
            included_agents (list[str]): lenses that contributed to the score.
            excluded_agents (list[str]): lenses that errored and were skipped.
            effective_weights (dict): actual weight used per included lens.
    """
    # Separate valid notes from errored ones
    valid   = [n for n in notes if "error" not in n and "score" in n]
    errored = [n for n in notes if "error" in n]

    included = [n["lens"] for n in valid]
    excluded = [n.get("lens", "unknown") for n in errored]

    if not valid:
        return {
            "weighted_score":    None,
            "included_agents":   included,
            "excluded_agents":   excluded,
            "effective_weights": {},
        }

    # Redistribute weight from errored agents proportionally to valid ones
    total_valid_weight = sum(_WEIGHTS.get(n["lens"], 0.0) for n in valid)

    effective_weights = {}
    if total_valid_weight > 0:
        for n in valid:
            raw_w = _WEIGHTS.get(n["lens"], 0.0)
            # Scale so that included agents' weights still sum to 1.0
            effective_weights[n["lens"]] = raw_w / total_valid_weight
    else:
        # Fallback: equal weight if lens names are unrecognised
        equal_w = 1.0 / len(valid)
        for n in valid:
            effective_weights[n["lens"]] = equal_w

    # Weighted average
    weighted_score = sum(
        n["score"] * effective_weights[n["lens"]]
        for n in valid
    )

    return {
        "weighted_score":    round(weighted_score, 2),
        "included_agents":   included,
        "excluded_agents":   excluded,
        "effective_weights": {k: round(v, 4) for k, v in effective_weights.items()},
    }


def tally_actions(notes: list[dict]) -> dict:
    """
    Count how many analysts recommend each action (buy/hold/sell/avoid).

    Args:
        notes: List of agent output dicts.

    Returns:
        dict mapping action string to count, e.g. {"buy": 3, "hold": 1, "sell": 1}.
    """
    tally = {"buy": 0, "hold": 0, "sell": 0, "avoid": 0}
    for n in notes:
        action = n.get("action", "").lower()
        if action in tally:
            tally[action] += 1
    return tally


def synthesise(analyst_notes: list[dict], data: dict, signals: dict | None = None) -> dict:
    """
    Synthesise five analyst notes into a consensus verdict.

    Python computes the weighted score and action tally. GPT-4o is called
    exactly once to write a narrative bull case, bear case, and one-line
    verdict drawing on all five analyst views.

    Args:
        analyst_notes: List of 5 dicts, each the output of an agent's analyze().
                       May include error dicts if an agent failed.
        data:          Full scraper output from fetch_company_data() — used
                       for company name and sector context.

    Returns:
        dict with keys:
            weighted_score   (float | None): Python-computed consensus score 1–10.
            action_tally     (dict):  count of buy/hold/sell/avoid across agents.
            included_agents  (list):  lenses that contributed to the score.
            excluded_agents  (list):  lenses that errored.
            effective_weights (dict): actual weight per included lens.
            bull_case        (str):   GPT-4o narrative of the bull thesis.
            bear_case        (str):   GPT-4o narrative of the bear thesis.
            verdict          (str):   GPT-4o one-line final verdict.
            analyst_notes    (list):  the original 5 agent notes, passed through.

    Raises:
        ValueError: if analyst_notes is empty or not a list.
        RuntimeError: if the GPT-4o synthesis call fails (wraps the OpenAI error).
    """
    if not isinstance(analyst_notes, list) or len(analyst_notes) == 0:
        raise ValueError(
            f"synthesise() requires a non-empty list of analyst notes, "
            f"got: {type(analyst_notes)}"
        )

    company  = data.get("header", {}).get("name", "Unknown Company")
    sector   = data.get("header", {}).get("sector", "Unknown Sector")
    is_bank  = data.get("is_bank", False)
    bank_sig = (signals or {}).get("bank_signals") if is_bank else None

    # --- Python: compute weighted score and action tally ---
    score_result = compute_weighted_score(analyst_notes)
    action_tally = tally_actions(analyst_notes)

    # --- Build a compact payload for GPT-4o ---
    # Only pass the narrative fields — GPT-4o must not re-derive the score.
    notes_for_llm = []
    for n in analyst_notes:
        if "error" in n:
            # Include errored agents so GPT-4o knows which lenses are missing
            notes_for_llm.append({
                "lens":  n.get("lens", "unknown"),
                "error": n["error"],
            })
        else:
            notes_for_llm.append({
                "lens":        n["lens"],
                "score":       n["score"],
                "thesis":      n.get("thesis", ""),
                "key_signals": n.get("key_signals", []),
                "risks":       n.get("risks", []),
                "action":      n.get("action", "hold"),
            })

    payload = {
        "company":        company,
        "sector":         sector,
        "is_bank":        is_bank,
        "weighted_score": score_result["weighted_score"],
        "action_tally":   action_tally,
        "analyst_notes":  notes_for_llm,
    }

    # For banks, include key bank-specific metrics directly in the payload so
    # the synthesis CIO can reference them even if individual agents missed them.
    if is_bank and bank_sig:
        payload["bank_context"] = {
            "gross_npa_pct":      bank_sig.get("gross_npa_pct"),
            "net_npa_pct":        bank_sig.get("net_npa_pct"),
            "npa_flag":           bank_sig.get("npa_flag"),
            "nim_pct":            bank_sig.get("nim_pct"),
            "car_pct":            bank_sig.get("car_pct"),
            "car_vs_minimum":     bank_sig.get("car_vs_minimum"),
            "price_to_book":      bank_sig.get("price_to_book"),
            "roe_latest":         bank_sig.get("roe_latest"),
            "deposit_growth_pct": bank_sig.get("deposit_growth_pct"),
            "note": (
                "Piotroski F-Score is NOT applicable for this bank/NBFC — "
                "model was designed for non-financials. Do not reference it."
            ),
        }

    # --- System prompt: synthesis chair, not an analyst ---
    bank_addendum = ""
    if is_bank:
        bank_addendum = (
            "\n\nThis company is a BANK or NBFC. Key differences for your synthesis:\n"
            "- Piotroski F-Score is invalid for banks — ignore any references to it.\n"
            "- Primary valuation metric is Price-to-Book (not Graham Number or DCF).\n"
            "- Asset quality (Gross NPA%, Net NPA%) is the single most important risk signal.\n"
            "- NIM (Net Interest Margin) drives profitability — trend matters as much as level.\n"
            "- Capital Adequacy Ratio (CAR) vs the 11.5% minimum shows the safety buffer.\n"
            "- Use bank_context data in your synthesis alongside analyst notes.\n"
        )

    system_prompt = (
        "You are the chief investment officer of a multi-strategy equity fund "
        "focused on Indian public companies (NSE/BSE). "
        "You have just received research notes from five specialist analysts: "
        "a value analyst (Graham/Buffett), a growth analyst (Lynch/Fisher), "
        "a quality analyst (Munger/Pabrai), a contrarian risk analyst (Burry/Druckenmiller), "
        "and a quantitative momentum analyst. "
        + bank_addendum +
        "\n\n"
        "Your job is to synthesise their views into three outputs:\n"
        "1. bull_case: 2–3 sentences summarising the strongest arguments FOR owning "
        "   this stock, drawn from the analyst notes provided.\n"
        "2. bear_case: 2–3 sentences summarising the most serious risks AGAINST "
        "   owning this stock, drawn from the analyst notes provided.\n"
        "3. verdict: One sentence final assessment — what should a rational long-term "
        "   investor do? Reference the weighted score and action tally.\n"
        "\n\n"
        "CRITICAL RULES:\n"
        "1. The weighted_score has already been computed by Python. Do NOT recompute "
        "   or reinterpret it. Reference it as the objective consensus.\n"
        "2. Draw your narrative directly from the analyst notes provided. Do not "
        "   introduce signals or facts not present in the data.\n"
        "3. If an agent errored (has an 'error' key), acknowledge its absence briefly "
        "   and note that its lens is missing from the synthesis.\n"
        "4. Be direct, specific, and quantitative. Name actual signal values.\n"
        "5. Return ONLY valid JSON matching the schema. No prose outside JSON.\n"
    )

    user_prompt = (
        f"Synthesise the following five analyst notes for {company} ({sector}).\n\n"
        f"Data:\n{json.dumps(payload, indent=2)}\n\n"
        f"Return JSON matching exactly this schema:\n"
        f'{{"bull_case": "<2-3 sentences>", '
        f'"bear_case": "<2-3 sentences>", '
        f'"verdict": "<1 sentence>"}}'
    )

    # --- Analysis model synthesis call (exactly 1 call per CLAUDE.md Rule 7) ---
    try:
        raw_str = call_analysis_model(
            system=system_prompt,
            user=user_prompt,
            max_tokens=600,
            response_format={"type": "json_object"},
        )
    except Exception as e:
        raise RuntimeError(
            f"Analysis model synthesis call failed for '{company}': {e}"
        ) from e

    # --- Parse response ---
    raw = json.loads(raw_str)

    # --- Assemble and return the full synthesis result ---
    return {
        "weighted_score":    score_result["weighted_score"],
        "action_tally":      action_tally,
        "included_agents":   score_result["included_agents"],
        "excluded_agents":   score_result["excluded_agents"],
        "effective_weights": score_result["effective_weights"],
        "bull_case":         raw.get("bull_case", ""),
        "bear_case":         raw.get("bear_case", ""),
        "verdict":           raw.get("verdict", ""),
        "analyst_notes":     analyst_notes,
    }
