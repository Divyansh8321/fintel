# ============================================================
# FILE: tests/test_signals.py
# PURPOSE: Unit tests for the 5 agent pre-computation helpers in signals.py.
#          Uses minimal scraper-output dicts — no live network calls.
# INPUT:   n/a
# OUTPUT:  pytest pass/fail
# DEPENDS: pytest, src/signals.py
# ============================================================

import pytest

from src.signals import (
    _compute_peg,
    _compute_owner_earnings,
    _compute_debt_service_coverage,
    _compute_roce_wacc_spread,
    _compute_52w_position,
)


# ---------------------------------------------------------------------------
# PEG ratio
# ---------------------------------------------------------------------------

def test_peg_attractive():
    val = {"pe_current": 15.0}
    data = {"growth_rates": {"profit_cagr_3yr": 20.0}}
    result = _compute_peg(data, val)
    assert result["peg_ratio"] == pytest.approx(0.75, rel=1e-3)
    assert result["peg_verdict"] == "attractive"


def test_peg_fair():
    val = {"pe_current": 25.0}
    data = {"growth_rates": {"profit_cagr_3yr": 20.0}}
    result = _compute_peg(data, val)
    assert result["peg_ratio"] == pytest.approx(1.25, rel=1e-3)
    assert result["peg_verdict"] == "fair"


def test_peg_expensive():
    val = {"pe_current": 50.0}
    data = {"growth_rates": {"profit_cagr_3yr": 10.0}}
    result = _compute_peg(data, val)
    assert result["peg_ratio"] == pytest.approx(5.0, rel=1e-3)
    assert result["peg_verdict"] == "expensive"


def test_peg_missing_pe():
    result = _compute_peg({"growth_rates": {"profit_cagr_3yr": 20.0}}, {})
    assert result["peg_ratio"] is None
    assert "PE" in result["peg_reason"]


def test_peg_negative_pe():
    val = {"pe_current": -5.0}
    data = {"growth_rates": {"profit_cagr_3yr": 20.0}}
    result = _compute_peg(data, val)
    assert result["peg_ratio"] is None
    assert result["peg_reason"] is not None


def test_peg_zero_cagr():
    val = {"pe_current": 20.0}
    data = {"growth_rates": {"profit_cagr_3yr": 0.0}}
    result = _compute_peg(data, val)
    assert result["peg_ratio"] is None
    assert result["peg_reason"] is not None


# ---------------------------------------------------------------------------
# Owner Earnings
# ---------------------------------------------------------------------------

def _oe_data(ni=100.0, dep=20.0, capex=-30.0, price=500.0, mktcap=5000.0):
    """Minimal scraper dict for owner earnings computation."""
    return {
        "pl_table":  {"net_profit": [ni], "depreciation": [dep]},
        "cash_flow": {"capex": [capex]},
        "balance_sheet": {},
        "header":    {"current_price": price, "market_cap": mktcap},
    }


def test_owner_earnings_computed():
    data = _oe_data(ni=100.0, dep=20.0, capex=-30.0, price=500.0, mktcap=5000.0)
    result = _compute_owner_earnings(data)
    # OE = 100 + 20 + (-30) - 0 = 90 Cr
    assert result["owner_earnings_cr"] == pytest.approx(90.0, rel=1e-3)
    assert result["oe_reason"] is None


def test_owner_earnings_yield():
    data = _oe_data(ni=100.0, dep=20.0, capex=-30.0, price=500.0, mktcap=5000.0)
    result = _compute_owner_earnings(data)
    # shares = (5000 * 1e7) / 500 = 1e8
    # oe_per_share = 90 * 1e7 / 1e8 = 9.0
    # oe_yield = 9/500 * 100 = 1.8%
    assert result["owner_earnings_per_share"] == pytest.approx(9.0, rel=1e-3)
    assert result["owner_earnings_yield_pct"] == pytest.approx(1.8, rel=1e-3)


def test_owner_earnings_missing_price():
    data = _oe_data(price=None)
    result = _compute_owner_earnings(data)
    assert result["owner_earnings_cr"] is None
    assert result["oe_reason"] is not None


def test_owner_earnings_zero_mktcap():
    data = _oe_data(mktcap=0.0)
    result = _compute_owner_earnings(data)
    assert result["owner_earnings_cr"] is None
    assert result["oe_reason"] is not None


# ---------------------------------------------------------------------------
# Debt Service Coverage Ratio
# ---------------------------------------------------------------------------

def _dscr_data(ocf=200.0, interest=50.0):
    return {
        "cash_flow": {"operating": [ocf]},
        "pl_table":  {"interest": [interest]},
    }


def test_dscr_comfortable():
    result = _compute_debt_service_coverage(_dscr_data(ocf=300.0, interest=50.0))
    assert result["dscr"] == pytest.approx(6.0, rel=1e-3)
    assert result["dscr_verdict"] == "comfortable"


def test_dscr_adequate():
    result = _compute_debt_service_coverage(_dscr_data(ocf=90.0, interest=50.0))
    assert result["dscr"] == pytest.approx(1.8, rel=1e-3)
    assert result["dscr_verdict"] == "adequate"


def test_dscr_tight():
    result = _compute_debt_service_coverage(_dscr_data(ocf=55.0, interest=50.0))
    assert result["dscr"] == pytest.approx(1.1, rel=1e-3)
    assert result["dscr_verdict"] == "tight"


def test_dscr_distress():
    result = _compute_debt_service_coverage(_dscr_data(ocf=30.0, interest=50.0))
    assert result["dscr"] == pytest.approx(0.6, rel=1e-3)
    assert result["dscr_verdict"] == "distress"


def test_dscr_zero_interest():
    result = _compute_debt_service_coverage(_dscr_data(ocf=200.0, interest=0.0))
    assert result["dscr"] is None
    assert result["dscr_verdict"] == "debt_free_or_negligible"


def test_dscr_missing_ocf():
    data = {"cash_flow": {}, "pl_table": {"interest": [50.0]}}
    result = _compute_debt_service_coverage(data)
    assert result["dscr"] is None
    assert result["dscr_reason"] is not None


# ---------------------------------------------------------------------------
# ROCE-WACC spread
# ---------------------------------------------------------------------------

def test_roce_wacc_strong_value_creator():
    result = _compute_roce_wacc_spread({"roce_latest": 20.0})
    assert result["roce_wacc_spread"] == pytest.approx(8.0, rel=1e-3)
    assert result["spread_verdict"] == "strong_value_creator"


def test_roce_wacc_marginal():
    result = _compute_roce_wacc_spread({"roce_latest": 13.0})
    assert result["spread_verdict"] == "marginal_value_creator"


def test_roce_wacc_value_destroyer():
    result = _compute_roce_wacc_spread({"roce_latest": 8.0})
    assert result["roce_wacc_spread"] == pytest.approx(-4.0, rel=1e-3)
    assert result["spread_verdict"] == "value_destroyer"


def test_roce_wacc_missing_roce():
    result = _compute_roce_wacc_spread({})
    assert result["roce_wacc_spread"] is None
    assert result["spread_reason"] is not None


# ---------------------------------------------------------------------------
# 52-week price position
# ---------------------------------------------------------------------------

def _52w_data(price=150.0, high=200.0, low=100.0):
    return {"header": {"current_price": price, "high_52w": high, "low_52w": low}}


def test_52w_near_high():
    result = _compute_52w_position(_52w_data(price=180.0, high=200.0, low=100.0))
    assert result["position_pct"] == pytest.approx(80.0, rel=1e-3)
    assert result["position_verdict"] == "near_52w_high"


def test_52w_upper_half():
    result = _compute_52w_position(_52w_data(price=160.0, high=200.0, low=100.0))
    assert result["position_pct"] == pytest.approx(60.0, rel=1e-3)
    assert result["position_verdict"] == "upper_half"


def test_52w_lower_half():
    result = _compute_52w_position(_52w_data(price=140.0, high=200.0, low=100.0))
    assert result["position_pct"] == pytest.approx(40.0, rel=1e-3)
    assert result["position_verdict"] == "lower_half"


def test_52w_near_low():
    result = _compute_52w_position(_52w_data(price=115.0, high=200.0, low=100.0))
    assert result["position_pct"] == pytest.approx(15.0, rel=1e-3)
    assert result["position_verdict"] == "near_52w_low"


def test_52w_missing_price():
    result = _compute_52w_position({"header": {"high_52w": 200.0, "low_52w": 100.0}})
    assert result["position_pct"] is None
    assert result["position_reason"] is not None


def test_52w_high_equals_low_anomaly():
    result = _compute_52w_position(_52w_data(price=100.0, high=100.0, low=100.0))
    assert result["position_pct"] is None
    assert result["position_reason"] is not None
