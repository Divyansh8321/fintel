# ============================================================
# FILE: src/brief.py
# PURPOSE: Single unified deep research brief, replacing the five
#          analyst agents + synthesis.py. One DeepSeek V3 call
#          produces a structured brief covering situation, bull/
#          base/bear cases, buy-on-dip level, conviction drivers,
#          red flags, moat assessment, verdict, and position sizing.
#          Also provides generate_chat_reply() for conversational
#          follow-up questions after the brief is generated.
# INPUT:   signals (SignalsModel), news (dict | None), thesis (str)
# OUTPUT:  dict matching the brief schema in the plan
# DEPENDS: src/llm.py (call_deepseek), src/models.py
# ============================================================

import json
import logging

from src.llm import call_deepseek
from src.models import SignalsModel

logger = logging.getLogger(__name__)

# 10-year Indian G-Sec yield used as risk-free benchmark.
_GSEC_10YR = 7.2  # percent


def _build_payload(signals: SignalsModel, news: dict | None, thesis: str) -> dict:
    """
    Assemble the compact signal payload passed to DeepSeek.

    Consolidates all signals across former value/growth/quality/contrarian/
    momentum agents into one flat dict. Bank/NBFC-specific signals included
    when is_bank is True. Mirrors the per-agent payload patterns but in one
    place.

    Args:
        signals: Pre-computed SignalsModel from compute_signals().
        news:    News + sentiment dict from fetch_news(), or None.
        thesis:  Free-text user thesis (may be empty string).

    Returns:
        dict ready for json.dumps() into the DeepSeek prompt.
    """
    meta = signals.meta
    val  = signals.valuation
    eq   = signals.earnings_quality
    bsh  = signals.balance_sheet_health
    pit  = signals.piotroski
    pr   = signals.promoter_risk
    oe   = signals.owner_earnings
    gq   = signals.growth_quality
    qm   = signals.quarterly_momentum
    dup  = signals.dupont
    peg  = signals.peg
    ce   = signals.capital_efficiency
    pm   = signals.price_momentum
    rw   = signals.roce_wacc
    dscr = signals.dscr

    payload: dict = {
        "meta": {
            "name":          meta.name,
            "sector":        meta.sector,
            "company_type":  "bank_or_nbfc" if meta.is_bank else "non_financial",
            "current_price_inr": meta.current_price,
            "market_cap_cr": meta.market_cap,
            "high_52w":      meta.high_52w,
            "low_52w":       meta.low_52w,
        },
        "valuation": {
            "graham_number":              val.graham_number if val else None,
            "graham_verdict":             val.graham_verdict if val else None,
            "price_to_graham_pct": round(val.price_to_graham * 100, 1)
                if val and val.price_to_graham is not None else None,
            "pe_current":                 val.pe_current if val else None,
            "industry_pe":                val.industry_pe if val else None,
            "pe_vs_industry": round(val.pe_current / val.industry_pe, 2)
                if val and val.pe_current and val.industry_pe else None,
            "ev_ebitda":                  val.ev_ebitda if val else None,
            "price_to_sales":             val.price_to_sales if val else None,
            "earnings_yield_pct":         val.earnings_yield if val else None,
            "dcf_intrinsic_value":        val.dcf_intrinsic_value if val else None,
            "dcf_method":                 val.dcf_method if val else None,
            "dcf_margin_of_safety_pct": round(val.dcf_margin_of_safety * 100, 1)
                if val and val.dcf_margin_of_safety is not None else None,
            "dcf_note": val.dcf_intrinsic_value_reason
                if val and val.dcf_method == "epv" else None,
        },
        "owner_earnings": {
            "owner_earnings_cr":          oe.owner_earnings_cr if oe else None,
            "owner_earnings_per_share":   oe.owner_earnings_per_share if oe else None,
            "owner_earnings_yield_pct":   oe.owner_earnings_yield_pct if oe else None,
            "oe_vs_gsec_10yr": round(oe.owner_earnings_yield_pct - _GSEC_10YR, 2)
                if oe and oe.owner_earnings_yield_pct is not None else None,
            "oe_reason":                  oe.oe_reason if oe else None,
        },
        "growth": {
            "revenue_cagr_3yr_pct":       gq.revenue_cagr_3yr if gq else None,
            "revenue_cagr_5yr_pct":       gq.revenue_cagr_5yr if gq else None,
            "profit_cagr_3yr_pct":        gq.profit_cagr_3yr if gq else None,
            "profit_cagr_5yr_pct":        gq.profit_cagr_5yr if gq else None,
            "acceleration":               gq.acceleration if gq else None,
            "margin_trend":               gq.margin_trend if gq else None,
            "revenue_yoy_pct":            qm.revenue_yoy_pct if qm else None,
            "profit_yoy_pct":             qm.profit_yoy_pct if qm else None,
            "opm_trend":                  qm.opm_trend if qm else None,
            "peg_ratio":                  peg.peg_ratio if peg else None,
            "peg_verdict":                peg.peg_verdict if peg else None,
        },
        "quality": {
            "roce_latest_pct":            ce.roce_latest if ce else None,
            "roce_trend":                 ce.roce_trend if ce else None,
            "roce_wacc_spread_pct":       rw.roce_wacc_spread if rw else None,
            "spread_verdict":             rw.spread_verdict if rw else None,
            "dupont_roe_driver":          dup.roe_driver if dup else None,
            "dupont_net_margin_pct":      dup.net_margin if dup else None,
            "dupont_roe_computed_pct":    dup.roe_computed if dup else None,
            "earnings_quality_flag":      eq.quality_flag if eq else None,
            "ocf_to_net_profit":          eq.ocf_to_net_profit if eq else None,
            "fcf_to_net_profit":          eq.fcf_to_net_profit if eq else None,
            "piotroski_score":            pit.score if pit else None,
            "piotroski_label":            pit.label if pit else None,
            "working_capital_days_trend": ce.working_capital_days_trend if ce else None,
        },
        "balance_sheet": {
            "debt_to_equity":             bsh.debt_to_equity_latest if bsh else None,
            "debt_trend":                 bsh.debt_trend if bsh else None,
            "ebit_interest_coverage":     bsh.ebit_interest_coverage if bsh else None,
            "ocf_interest_coverage":      dscr.ocf_interest_coverage if dscr else None,
            "ocf_coverage_verdict":       dscr.ocf_interest_coverage_verdict if dscr else None,
        },
        "momentum": {
            "52w_position_pct":           pm.position_pct if pm else None,
            "52w_verdict":                pm.position_verdict if pm else None,
        },
        "promoter": {
            "pledged_pct":                pr.pledged_pct if pr else None,
            "pledge_flag":                pr.pledge_flag if pr else None,
            "pledge_trend":               pr.pledge_trend if pr else None,
            "promoter_holding_pct":       pr.promoter_holding if pr else None,
            "promoter_holding_change_pct": pr.promoter_holding_change if pr else None,
        },
        "news": {
            "sentiment":         news.get("sentiment") if news else None,
            "sentiment_reason":  news.get("sentiment_reason") if news else None,
        },
        "gsec_10yr_yield_pct":  _GSEC_10YR,
        "user_thesis":          thesis or None,
    }

    # Bank/NBFC-specific signals — append when applicable
    if meta.is_bank and signals.bank_signals:
        bs = signals.bank_signals
        payload["bank_signals"] = {
            "gross_npa_pct":      bs.gross_npa_pct,
            "net_npa_pct":        bs.net_npa_pct,
            "npa_flag":           bs.npa_flag,
            "nim_pct":            bs.nim_pct,
            "nim_trend":          bs.nim_trend,
            "car_pct":            bs.car_pct,
            "car_vs_minimum":     bs.car_vs_minimum,
            "price_to_book":      bs.price_to_book,
            "roe_latest_pct":     bs.roe_latest,
            "deposit_growth_pct": bs.deposit_growth_pct,
            "note": (
                "Piotroski F-Score is NOT applicable for banks/NBFCs. "
                "Graham Number and DCF are unreliable — use P/B and NIM as primary signals."
            ),
        }

    return payload


_SYSTEM_PROMPT = """\
You are a senior buy-side equity analyst covering Indian public companies (NSE/BSE).
Your job is to produce a single, rigorous, opinionated deep research brief based on
pre-computed quantitative signals. Python has already done all the maths — you interpret,
contextualise, and form a view.

INVESTMENT PHILOSOPHY:
- Valuation matters. You never own a stock without knowing what it's worth.
- Quality of earnings > headline profit. OCF backing reported profit is essential.
- Balance sheet is the foundation. High debt with falling coverage is disqualifying.
- Growth without ROCE > WACC is value destruction, not creation.
- Promoter pledging > 20% is a near-disqualifier.
- The best businesses have durable competitive moats — not just good numbers.

BANK / NBFC HANDLING (when company_type = "bank_or_nbfc"):
- Primary valuation: Price-to-Book (P/B). Fair value: 2–3x book. >4x = expensive; <1x = distressed.
- Ignore D/E ratio for banks — leverage is their raw material, not a risk signal.
- Gross NPA% and Net NPA% are the single most important risk signals.
- NIM (Net Interest Margin) drives profitability — trend matters as much as level.
- CAR vs 11.5% minimum shows the safety buffer.
- Piotroski F-Score is NOT applicable — do not reference it.
- Graham Number and FCF-based DCF are NOT reliable for banks.

CRITICAL RULES:
1. All numerical signals are pre-computed by Python. Do NOT recompute or second-guess them.
   If a value is null, note it as unavailable and work around it.
2. Price targets must be derived from the signals provided (Graham Number, DCF, P/B multiples,
   earnings yield). Do not fabricate targets.
3. If a user thesis is provided, explicitly address it — stress-test it if bullish,
   probe for the bear case if bearish.
4. Be specific and quantitative. Name actual signal values in your narrative.
5. Return ONLY valid JSON matching the schema below. No prose outside JSON.
6. verdict must be exactly one of: "buy", "hold", "sell", "avoid".
7. conviction_drivers and red_flags must each have exactly 3 items.
"""

_SCHEMA = """\
{
  "situation": "<2-3 sentences: what is this company, where does it stand right now>",
  "bull_case": {
    "narrative": "<2-3 sentences: what has to go right>",
    "price_target_inr": <float or null>
  },
  "base_case": {
    "narrative": "<2-3 sentences: fair value scenario>",
    "price_target_inr": <float or null>
  },
  "bear_case": {
    "narrative": "<2-3 sentences: what breaks the thesis>",
    "price_target_inr": <float or null>
  },
  "buy_on_dip": {
    "level_inr": <float or null>,
    "rationale": "<1 sentence>"
  },
  "conviction_drivers": ["<driver 1>", "<driver 2>", "<driver 3>"],
  "red_flags": ["<flag 1>", "<flag 2>", "<flag 3>"],
  "moat": "<1-2 sentences: durable edge or commodity business>",
  "verdict": "buy|hold|sell|avoid",
  "sizing": "<1 sentence: e.g. '2% position, not 10%' or 'full position appropriate'>",
  "user_thesis_addressed": "<1-2 sentences addressing the user thesis, or null if no thesis provided>"
}"""


def generate_brief(
    signals: SignalsModel,
    news: dict | None,
    thesis: str,
    ticker: str = "",
) -> dict:
    """
    Generate a deep research brief via a single DeepSeek V3 call.

    Replaces the five analyst agents + synthesis.py. Builds a consolidated
    signal payload from all sub-models, then asks DeepSeek to produce a
    structured brief covering situation, three scenarios, conviction drivers,
    red flags, moat, verdict, and position sizing.

    Args:
        signals: Pre-computed SignalsModel from compute_signals().
        news:    News + sentiment dict from fetch_news(), or None.
        thesis:  Free-text user thesis (may be empty string "").
                 If non-empty, shapes whether the brief stress-tests a bull
                 thesis or probes a bear one.

    Returns:
        dict matching the brief schema:
            situation, bull_case, base_case, bear_case, buy_on_dip,
            conviction_drivers, red_flags, moat, verdict, sizing,
            user_thesis_addressed.
        On any failure, returns {"error": str(e)}.

    Raises:
        Nothing — all exceptions are caught and returned as error dicts.
        Per CLAUDE.md Rule 5 (agent exception): LLM failures set
        {"error": str(e)} and continue.
    """
    try:
        payload = _build_payload(signals, news, thesis)

        user_prompt = (
            f"Generate a deep research brief for {signals.meta.name} "
            f"({signals.meta.sector}).\n\n"
            f"Pre-computed signals:\n{json.dumps(payload, indent=2)}\n\n"
            f"Return JSON matching exactly this schema:\n{_SCHEMA}"
        )

        raw_str = call_deepseek(
            system=_SYSTEM_PROMPT,
            user=user_prompt,
            max_tokens=5000,
            response_format={"type": "json_object"},
            ticker=ticker,
        )
        raw = json.loads(raw_str)

        # Ensure required keys are present with safe defaults
        return {
            "situation":            raw.get("situation", ""),
            "bull_case":            raw.get("bull_case", {"narrative": "", "price_target_inr": None}),
            "base_case":            raw.get("base_case", {"narrative": "", "price_target_inr": None}),
            "bear_case":            raw.get("bear_case", {"narrative": "", "price_target_inr": None}),
            "buy_on_dip":           raw.get("buy_on_dip", {"level_inr": None, "rationale": ""}),
            "conviction_drivers":   raw.get("conviction_drivers", []),
            "red_flags":            raw.get("red_flags", []),
            "moat":                 raw.get("moat", ""),
            "verdict":              raw.get("verdict", "hold"),
            "sizing":               raw.get("sizing", ""),
            "user_thesis_addressed": raw.get("user_thesis_addressed"),
        }

    except Exception as e:
        # Per CLAUDE.md Rule 5: LLM failures return error dict, never raise.
        logger.warning("generate_brief() failed for '%s': %s", signals.meta.name, e)
        return {"error": str(e)}


def generate_chat_reply(
    question: str,
    brief: dict,
    signals_summary: dict,
) -> str:
    """
    Answer a follow-up question using the already-generated brief and signals.

    No re-scraping or re-fetching — context is the brief + signals already in
    memory. One DeepSeek V3 call per question.

    Args:
        question:         User's follow-up question string.
        brief:            Full brief dict returned by generate_brief().
        signals_summary:  Compact signals dict (from the /analyze response).

    Returns:
        Answer string. On failure, returns an error string (never raises).
    """
    context_prompt = (
        f"You are a senior equity analyst. You have already produced the following "
        f"deep research brief and have the underlying quantitative signals available.\n\n"
        f"BRIEF:\n{json.dumps(brief, indent=2)}\n\n"
        f"SIGNALS SUMMARY:\n{json.dumps(signals_summary, indent=2)}\n\n"
        f"Answer the analyst's follow-up question concisely and quantitatively. "
        f"Reference specific numbers from the brief or signals where relevant. "
        f"Do not re-fetch or re-scrape anything — use only the context provided."
    )

    try:
        return call_deepseek(
            system=context_prompt,
            user=question,
            max_tokens=2000,
        )
    except Exception as e:
        logger.warning("generate_chat_reply() failed: %s", e)
        return f"Error generating reply: {e}"
