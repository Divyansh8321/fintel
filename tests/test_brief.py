# ============================================================
# FILE: tests/test_brief.py
# PURPOSE: Unit tests for src/brief.py.
#          Tests generate_brief() and generate_chat_reply() using
#          mocked DeepSeek responses. Verifies output schema,
#          fallback on LLM failure, and bank/non-bank payload
#          differences. Per CLAUDE.md TDD override: mocks are
#          permitted for pure functions over dicts.
# INPUT:   Fabricated SignalsModel instances; patched call_deepseek
# OUTPUT:  pytest pass/fail
# DEPENDS: pytest, unittest.mock, src/brief.py, src/models.py
# ============================================================

import json
from unittest.mock import patch

import pytest

from src.brief import generate_brief, generate_chat_reply, _build_payload
from src.models import (
    SignalsModel,
    MetaModel,
    ValuationModel,
    GrowthQualityModel,
    EarningsQualityModel,
    BalanceSheetHealthModel,
    PiotroskiModel,
    PromoterRiskModel,
    QuarterlyMomentumModel,
    CapitalEfficiencyModel,
    BankSignalsModel,
    PegModel,
    OwnerEarningsModel,
    DupontModel,
    DscrModel,
    RoceWaccModel,
    PriceMomentumModel,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_signals(is_bank: bool = False) -> SignalsModel:
    """Build a minimal but complete SignalsModel for testing."""
    meta = MetaModel(
        name="Test Corp",
        sector="Technology",
        current_price=500.0,
        market_cap=50000.0,
        is_bank=is_bank,
        high_52w=600.0,
        low_52w=400.0,
    )
    bank_signals = None
    if is_bank:
        bank_signals = BankSignalsModel(
            gross_npa_pct=2.5,
            net_npa_pct=0.8,
            car_pct=16.0,
            nim_pct=3.2,
            npa_flag="low",
            car_vs_minimum=4.5,
            price_to_book=2.1,
            roe_latest=15.0,
        )

    return SignalsModel(
        meta=meta,
        bank_signals=bank_signals,
        valuation=ValuationModel(
            graham_number=450.0,
            price_to_graham=0.11,
            graham_verdict="slight_premium",
            pe_current=25.0,
            industry_pe=30.0,
            earnings_yield=4.0,
            dcf_intrinsic_value=480.0,
            dcf_margin_of_safety=-0.04,
            dcf_method="fcf_dcf",
        ),
        growth_quality=GrowthQualityModel(
            revenue_cagr_3yr=15.0,
            revenue_cagr_5yr=12.0,
            profit_cagr_3yr=18.0,
            profit_cagr_5yr=14.0,
            acceleration="accelerating",
            margin_trend="expanding",
        ),
        earnings_quality=EarningsQualityModel(
            ocf_to_net_profit=1.2,
            fcf_to_net_profit=0.9,
            quality_flag="high",
        ),
        balance_sheet_health=BalanceSheetHealthModel(
            debt_to_equity_latest=0.3,
            debt_trend="decreasing",
            ebit_interest_coverage=15.0,
        ),
        piotroski=PiotroskiModel(score=7, label="strong"),
        promoter_risk=PromoterRiskModel(
            pledged_pct=5.0,
            pledge_flag="low",
            pledge_trend="stable",
            promoter_holding=52.0,
        ),
        quarterly_momentum=QuarterlyMomentumModel(
            revenue_yoy_pct=20.0,
            profit_yoy_pct=25.0,
            opm_trend="expanding",
        ),
        peg=PegModel(peg_ratio=1.4, peg_verdict="fair"),
        owner_earnings=OwnerEarningsModel(
            owner_earnings_cr=800.0,
            owner_earnings_per_share=40.0,
            owner_earnings_yield_pct=8.0,
        ),
        dupont=DupontModel(
            net_margin=12.0,
            asset_turnover=1.5,
            leverage=1.8,
            roe_computed=32.0,
            roe_driver="margin",
        ),
        capital_efficiency=CapitalEfficiencyModel(
            roce_latest=22.0,
            roce_trend="improving",
        ),
        dscr=DscrModel(ocf_interest_coverage=12.0, ocf_interest_coverage_verdict="strong"),
        roce_wacc=RoceWaccModel(
            roce_latest=22.0,
            wacc_proxy=12.0,
            roce_wacc_spread=10.0,
            spread_verdict="value_creation",
        ),
        price_momentum=PriceMomentumModel(
            position_pct=50.0,
            position_verdict="mid_range",
            high_52w=600.0,
            low_52w=400.0,
            current_price=500.0,
        ),
    )


_VALID_BRIEF_JSON = json.dumps({
    "situation": "Test Corp is a technology company trading at ₹500.",
    "bull_case": {
        "narrative": "Strong growth with expanding margins.",
        "price_target_inr": 650.0,
    },
    "base_case": {
        "narrative": "Steady growth continues at current rates.",
        "price_target_inr": 520.0,
    },
    "bear_case": {
        "narrative": "Margin compression if competition intensifies.",
        "price_target_inr": 380.0,
    },
    "buy_on_dip": {
        "level_inr": 430.0,
        "rationale": "Graham Number support at ₹450.",
    },
    "conviction_drivers": ["Strong ROCE-WACC spread", "Accelerating revenue", "Low debt"],
    "red_flags": ["PE at premium to industry", "DCF margin of safety thin", "Pledging non-zero"],
    "moat": "Moderate — proprietary software platform with switching costs.",
    "verdict": "hold",
    "sizing": "3% position appropriate given thin margin of safety.",
    "user_thesis_addressed": None,
})


# ---------------------------------------------------------------------------
# Tests: generate_brief()
# ---------------------------------------------------------------------------

class TestGenerateBrief:

    def test_returns_valid_schema_on_success(self):
        """generate_brief() returns a dict with all required keys."""
        signals = _make_signals()
        with patch("src.brief.call_deepseek", return_value=_VALID_BRIEF_JSON):
            result = generate_brief(signals, news=None, thesis="")

        required_keys = [
            "situation", "bull_case", "base_case", "bear_case",
            "buy_on_dip", "conviction_drivers", "red_flags",
            "moat", "verdict", "sizing", "user_thesis_addressed",
        ]
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

    def test_verdict_is_string(self):
        """verdict field is a non-empty string."""
        signals = _make_signals()
        with patch("src.brief.call_deepseek", return_value=_VALID_BRIEF_JSON):
            result = generate_brief(signals, news=None, thesis="")
        assert isinstance(result["verdict"], str)
        assert result["verdict"] in ("buy", "hold", "sell", "avoid")

    def test_conviction_drivers_has_three_items(self):
        """conviction_drivers list has exactly 3 items (as required by schema)."""
        signals = _make_signals()
        with patch("src.brief.call_deepseek", return_value=_VALID_BRIEF_JSON):
            result = generate_brief(signals, news=None, thesis="")
        assert len(result["conviction_drivers"]) == 3

    def test_red_flags_has_three_items(self):
        """red_flags list has exactly 3 items."""
        signals = _make_signals()
        with patch("src.brief.call_deepseek", return_value=_VALID_BRIEF_JSON):
            result = generate_brief(signals, news=None, thesis="")
        assert len(result["red_flags"]) == 3

    def test_returns_error_dict_on_llm_failure(self):
        """generate_brief() returns {"error": ...} when DeepSeek call raises, never re-raises."""
        signals = _make_signals()
        with patch("src.brief.call_deepseek", side_effect=RuntimeError("API timeout")):
            result = generate_brief(signals, news=None, thesis="")
        assert "error" in result
        assert "API timeout" in result["error"]

    def test_returns_error_dict_on_invalid_json(self):
        """generate_brief() returns {"error": ...} when DeepSeek returns non-JSON."""
        signals = _make_signals()
        with patch("src.brief.call_deepseek", return_value="not valid json {{{"):
            result = generate_brief(signals, news=None, thesis="")
        assert "error" in result

    def test_passes_thesis_to_payload(self):
        """User thesis is included in the prompt sent to DeepSeek."""
        signals = _make_signals()
        captured = {}

        def mock_deepseek(system, user, max_tokens, response_format=None, ticker=""):
            captured["user"] = user
            return _VALID_BRIEF_JSON

        with patch("src.brief.call_deepseek", side_effect=mock_deepseek):
            generate_brief(signals, news=None, thesis="I think margins will expand")

        assert "I think margins will expand" in captured["user"]

    def test_empty_thesis_does_not_crash(self):
        """Empty thesis string is handled without errors."""
        signals = _make_signals()
        with patch("src.brief.call_deepseek", return_value=_VALID_BRIEF_JSON):
            result = generate_brief(signals, news=None, thesis="")
        assert "error" not in result

    def test_news_sentiment_included_in_payload(self):
        """News sentiment is passed through to the DeepSeek payload."""
        signals = _make_signals()
        news    = {"sentiment": "bullish", "sentiment_reason": "Strong quarterly results"}
        captured = {}

        def mock_deepseek(system, user, max_tokens, response_format=None, ticker=""):
            captured["user"] = user
            return _VALID_BRIEF_JSON

        with patch("src.brief.call_deepseek", side_effect=mock_deepseek):
            generate_brief(signals, news=news, thesis="")

        assert "bullish" in captured["user"]


# ---------------------------------------------------------------------------
# Tests: _build_payload() — bank vs non-bank
# ---------------------------------------------------------------------------

class TestBuildPayload:

    def test_non_bank_has_no_bank_signals_key(self):
        """Non-bank payload must not include bank_signals."""
        signals = _make_signals(is_bank=False)
        payload = _build_payload(signals, news=None, thesis="")
        assert "bank_signals" not in payload

    def test_bank_has_bank_signals_key(self):
        """Bank payload must include bank_signals with NPA/CAR/NIM fields."""
        signals = _make_signals(is_bank=True)
        payload = _build_payload(signals, news=None, thesis="")
        assert "bank_signals" in payload
        assert "gross_npa_pct" in payload["bank_signals"]
        assert "car_pct" in payload["bank_signals"]
        assert "nim_pct" in payload["bank_signals"]

    def test_payload_includes_all_required_sections(self):
        """Payload has all major signal sections."""
        signals = _make_signals()
        payload = _build_payload(signals, news=None, thesis="")
        for section in ("meta", "valuation", "growth", "quality", "balance_sheet",
                        "momentum", "promoter", "news"):
            assert section in payload, f"Missing section: {section}"


# ---------------------------------------------------------------------------
# Tests: generate_chat_reply()
# ---------------------------------------------------------------------------

class TestGenerateChatReply:

    def test_returns_string_on_success(self):
        """generate_chat_reply() returns a non-empty string."""
        with patch("src.brief.call_deepseek", return_value="The ROCE-WACC spread is 10%."):
            result = generate_chat_reply(
                question="What is the ROCE spread?",
                brief={"verdict": "hold"},
                signals_summary={"meta": {"name": "Test Corp"}},
            )
        assert isinstance(result, str)
        assert len(result) > 0

    def test_returns_error_string_on_failure(self):
        """generate_chat_reply() returns an error string (not raises) on DeepSeek failure."""
        with patch("src.brief.call_deepseek", side_effect=RuntimeError("timeout")):
            result = generate_chat_reply(
                question="What is the PE ratio?",
                brief={},
                signals_summary={},
            )
        assert "Error" in result or "error" in result.lower()
