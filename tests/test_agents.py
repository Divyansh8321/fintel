# ============================================================
# FILE: tests/test_agents.py
# PURPOSE: Smoke tests for all 5 analyst agents.
#          LLM calls are mocked — tests verify output shape only,
#          never LLM content. Per CLAUDE.md: silent failures are
#          unacceptable; agents must return the expected schema.
# INPUT:   n/a (uses minimal SignalsModel fixture + mock LLM)
# OUTPUT:  pytest pass/fail
# DEPENDS: pytest, pytest-mock, src/agents/*, src/models.py
# ============================================================

import json
import pytest
from unittest.mock import patch

from src.models import (
    MetaModel,
    SignalsModel,
    ValuationModel,
    PiotroskiModel,
    EarningsQualityModel,
    BalanceSheetHealthModel,
    PromoterRiskModel,
    QuarterlyMomentumModel,
    GrowthQualityModel,
    CapitalEfficiencyModel,
    DupontModel,
    PegModel,
    OwnerEarningsModel,
    DscrModel,
    RoceWaccModel,
    PriceMomentumModel,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def minimal_signals() -> SignalsModel:
    """
    Minimal but fully-populated SignalsModel for agent smoke tests.
    All sub-models are provided so agents don't hit None guards.
    """
    meta = MetaModel(
        name="TESTCO",
        sector="Technology",
        current_price=1000.0,
        market_cap=50_000.0,
        is_bank=False,
        high_52w=1200.0,
        low_52w=800.0,
    )
    return SignalsModel(
        meta=meta,
        piotroski=PiotroskiModel(score=6, label="strong"),
        dupont=DupontModel(net_margin=15.0, roe_computed=18.0, roe_driver="margin"),
        earnings_quality=EarningsQualityModel(ocf_to_net_profit=1.1, fcf_to_net_profit=0.9, quality_flag="high"),
        growth_quality=GrowthQualityModel(revenue_cagr_3yr=12.0, profit_cagr_3yr=15.0, margin_trend="expanding", acceleration="accelerating"),
        capital_efficiency=CapitalEfficiencyModel(roce_latest=18.0, roce_trend="improving", interest_coverage=5.0),
        balance_sheet_health=BalanceSheetHealthModel(debt_to_equity_latest=0.3, debt_trend="declining", interest_coverage=5.0),
        valuation=ValuationModel(pe_current=22.0, industry_pe=25.0, earnings_yield=4.5, graham_number=900.0, graham_verdict="undervalued"),
        promoter_risk=PromoterRiskModel(pledged_pct=2.0, pledge_flag="low", promoter_holding=55.0, promoter_holding_change=0.0),
        quarterly_momentum=QuarterlyMomentumModel(revenue_yoy_pct=14.0, profit_yoy_pct=18.0, opm_trend="improving"),
        peg=PegModel(peg_ratio=1.5, peg_verdict="fair"),
        owner_earnings=OwnerEarningsModel(owner_earnings_cr=500.0, owner_earnings_per_share=10.0, owner_earnings_yield_pct=1.0),
        dscr=DscrModel(dscr=4.0, dscr_verdict="comfortable"),
        roce_wacc=RoceWaccModel(roce_latest=18.0, wacc_proxy=12.0, roce_wacc_spread=6.0, spread_verdict="strong_value_creator"),
        price_momentum=PriceMomentumModel(position_pct=75.0, position_verdict="near_52w_high", current_price=1000.0, high_52w=1200.0, low_52w=800.0),
    )


_MOCK_LLM_RESPONSE = json.dumps({
    "lens": "value",
    "score": 7,
    "thesis": "Solid fundamentals.",
    "key_signals": ["low PE", "high ROCE"],
    "risks": ["macro slowdown"],
    "action": "buy",
})

EXPECTED_KEYS = {"lens", "score", "thesis", "key_signals", "risks", "action"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_llm(monkeypatch):
    """Patch call_analysis_model in each agent module to return fixed JSON."""
    for module in ("src.agents.value", "src.agents.growth", "src.agents.quality",
                   "src.agents.momentum", "src.agents.contrarian"):
        monkeypatch.setattr(f"{module}.call_analysis_model", lambda *a, **kw: _MOCK_LLM_RESPONSE)


def _break_llm(monkeypatch):
    """Patch call_analysis_model in each agent module to raise RuntimeError."""
    for module in ("src.agents.value", "src.agents.growth", "src.agents.quality",
                   "src.agents.momentum", "src.agents.contrarian"):
        monkeypatch.setattr(f"{module}.call_analysis_model",
                            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("LLM down")))


# ---------------------------------------------------------------------------
# Value agent
# ---------------------------------------------------------------------------

def test_value_agent_output_shape(minimal_signals, monkeypatch):
    _mock_llm(monkeypatch)
    from src.agents.value import analyze
    result = analyze(minimal_signals, news=None)
    assert EXPECTED_KEYS.issubset(result.keys()), f"Missing keys: {EXPECTED_KEYS - result.keys()}"
    assert "error" not in result


def test_value_agent_error_isolation(minimal_signals, monkeypatch):
    _break_llm(monkeypatch)
    from src.agents.value import analyze
    result = analyze(minimal_signals, news=None)
    assert "error" in result
    assert result.get("lens") == "value"


# ---------------------------------------------------------------------------
# Growth agent
# ---------------------------------------------------------------------------

def test_growth_agent_output_shape(minimal_signals, monkeypatch):
    _mock_llm(monkeypatch)
    from src.agents.growth import analyze
    result = analyze(minimal_signals, news=None)
    assert EXPECTED_KEYS.issubset(result.keys())
    assert "error" not in result


def test_growth_agent_error_isolation(minimal_signals, monkeypatch):
    _break_llm(monkeypatch)
    from src.agents.growth import analyze
    result = analyze(minimal_signals, news=None)
    assert "error" in result
    assert result.get("lens") == "growth"


# ---------------------------------------------------------------------------
# Quality agent
# ---------------------------------------------------------------------------

def test_quality_agent_output_shape(minimal_signals, monkeypatch):
    _mock_llm(monkeypatch)
    from src.agents.quality import analyze
    result = analyze(minimal_signals, news=None)
    assert EXPECTED_KEYS.issubset(result.keys())
    assert "error" not in result


def test_quality_agent_error_isolation(minimal_signals, monkeypatch):
    _break_llm(monkeypatch)
    from src.agents.quality import analyze
    result = analyze(minimal_signals, news=None)
    assert "error" in result
    assert result.get("lens") == "quality"


# ---------------------------------------------------------------------------
# Momentum agent
# ---------------------------------------------------------------------------

def test_momentum_agent_output_shape(minimal_signals, monkeypatch):
    _mock_llm(monkeypatch)
    from src.agents.momentum import analyze
    result = analyze(minimal_signals, news=None)
    assert EXPECTED_KEYS.issubset(result.keys())
    assert "error" not in result


def test_momentum_agent_error_isolation(minimal_signals, monkeypatch):
    _break_llm(monkeypatch)
    from src.agents.momentum import analyze
    result = analyze(minimal_signals, news=None)
    assert "error" in result
    assert result.get("lens") == "momentum"


# ---------------------------------------------------------------------------
# Contrarian agent
# ---------------------------------------------------------------------------

def test_contrarian_agent_output_shape(minimal_signals, monkeypatch):
    _mock_llm(monkeypatch)
    from src.agents.contrarian import analyze
    result = analyze(minimal_signals, news=None)
    assert EXPECTED_KEYS.issubset(result.keys())
    assert "error" not in result


def test_contrarian_agent_error_isolation(minimal_signals, monkeypatch):
    _break_llm(monkeypatch)
    from src.agents.contrarian import analyze
    result = analyze(minimal_signals, news=None)
    assert "error" in result
    assert result.get("lens") == "contrarian"
