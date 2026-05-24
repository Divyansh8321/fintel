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
    _compute_piotroski,
    _compute_dupont,
    _compute_earnings_quality,
    _annual_offset,
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
# OCF Interest Coverage (previously mislabeled DSCR — see issue #14)
# ---------------------------------------------------------------------------

def _dscr_data(ocf=200.0, interest=50.0):
    return {
        "cash_flow": {"operating": [ocf]},
        "pl_table":  {"interest": [interest]},
    }


def test_dscr_comfortable():
    result = _compute_debt_service_coverage(_dscr_data(ocf=300.0, interest=50.0))
    assert result["ocf_interest_coverage"] == pytest.approx(6.0, rel=1e-3)
    assert result["ocf_interest_coverage_verdict"] == "comfortable"


def test_dscr_adequate():
    result = _compute_debt_service_coverage(_dscr_data(ocf=90.0, interest=50.0))
    assert result["ocf_interest_coverage"] == pytest.approx(1.8, rel=1e-3)
    assert result["ocf_interest_coverage_verdict"] == "adequate"


def test_dscr_tight():
    result = _compute_debt_service_coverage(_dscr_data(ocf=55.0, interest=50.0))
    assert result["ocf_interest_coverage"] == pytest.approx(1.1, rel=1e-3)
    assert result["ocf_interest_coverage_verdict"] == "tight"


def test_dscr_distress():
    result = _compute_debt_service_coverage(_dscr_data(ocf=30.0, interest=50.0))
    assert result["ocf_interest_coverage"] == pytest.approx(0.6, rel=1e-3)
    assert result["ocf_interest_coverage_verdict"] == "distress"


def test_dscr_zero_interest():
    result = _compute_debt_service_coverage(_dscr_data(ocf=200.0, interest=0.0))
    assert result["ocf_interest_coverage"] is None
    assert result["ocf_interest_coverage_verdict"] == "debt_free_or_negligible"


def test_dscr_missing_ocf():
    data = {"cash_flow": {}, "pl_table": {"interest": [50.0]}}
    result = _compute_debt_service_coverage(data)
    assert result["ocf_interest_coverage"] is None
    assert result["ocf_interest_coverage_reason"] is not None


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


# ---------------------------------------------------------------------------
# TTM offset — _annual_offset and affected signal functions
# ---------------------------------------------------------------------------

def _ttm_data(ttm_np=200.0, annual_np=100.0, annual_np_prior=80.0):
    """
    Minimal scraper dict where pl_table.years[0] == 'TTM'.
    TTM net_profit=200 (inflated), annual=100, prior=80.

    OPM after offset: [19.0, 20.0] → annual[0]=19.0 < annual[1]=20.0 → F8=0 (declining).
    If TTM were used without offset: [20.0, 19.0] → F8=1 (improving). This is the
    observable difference used to verify the offset is applied.

    FCF = OCF + capex = 90 + (-20) = 70 → fcf_to_np = 70/100 = 0.7 → quality "high"
    (ocf_to_np=0.9 >= 0.9 AND fcf_to_np=0.7 >= 0.7).
    If TTM used: np=200 → ocf_to_np=0.45 → "medium" (wrong).
    """
    return {
        "pl_table": {
            "years":            ["TTM", "Mar 2025", "Mar 2024"],
            "net_profit":       [ttm_np, annual_np, annual_np_prior],
            "sales":            [2000.0, 1000.0, 900.0],
            "operating_profit": [400.0, 200.0, 180.0],
            "interest":         [20.0, 20.0, 18.0],
            # TTM opm=20.0; annual[0]=19.0, annual[1]=20.0
            # After offset: [19.0, 20.0] → F8 = 0 (declining)
            # Without offset: [20.0, 19.0] → F8 = 1 (improving) — would be wrong
            "opm_pct":          [20.0, 19.0, 20.0],
            "eps":              [40.0, 20.0, 16.0],
            "depreciation":     [50.0, 25.0, 22.0],
        },
        "balance_sheet": {
            "years":        ["Mar 2025", "Mar 2024", "Mar 2023"],
            "total_assets": [1000.0, 900.0, 800.0],
            "borrowings":   [200.0, 220.0, 240.0],
            "equity_capital": [50.0, 50.0, 50.0],
            "reserves":       [450.0, 400.0, 350.0],
            "long_term_borrowings":  [150.0, 170.0, 190.0],
            "short_term_borrowings": [50.0, 50.0, 50.0],
            "lease_liabilities":     [0.0, 0.0, 0.0],
        },
        "cash_flow": {
            "operating": [90.0, 80.0, 70.0],
            "investing":  [-20.0, -25.0, -20.0],
            # capex=-20 → FCF = 90 + (-20) = 70 → fcf_to_np = 70/100 = 0.7 → "high"
            "capex":      [-20.0, -25.0, -20.0],
        },
        "key_ratios": {"current_ratio": 1.5},
        "header": {"current_price": 500.0, "market_cap": 5000.0},
        "ratios_table": {"roce": [20.0, 18.0, 16.0], "working_capital_days": []},
    }


def test_annual_offset_detects_ttm():
    """_annual_offset returns 1 when years[0] == 'TTM'."""
    data = _ttm_data()
    assert _annual_offset(data) == 1


def test_annual_offset_no_ttm():
    """_annual_offset returns 0 when no TTM present."""
    data = _ttm_data()
    data["pl_table"]["years"][0] = "Mar 2026"
    assert _annual_offset(data) == 0


def test_piotroski_uses_annual_not_ttm():
    """
    F8 (gross margin): after offset opm=[19.0, 20.0] → annual[0]=19.0 < annual[1]=20.0
    → F8=0 (declining margin).
    Without the offset opm=[20.0, 19.0] → F8=1 (improving) — which would be wrong.
    This directly verifies the TTM entry is skipped.
    """
    data = _ttm_data()
    result = _compute_piotroski(data)
    assert result["score"] is not None
    assert result["signals"]["gross_margin_improving"] == 0


def test_dupont_uses_annual_not_ttm():
    """
    DuPont latest_year must be 'Mar 2025' (first annual), not 'TTM'.
    Net margin must be computed on annual sales/np, not TTM values.
    """
    data = _ttm_data()
    result = _compute_dupont(data)
    assert result["latest_year"] == "Mar 2025"
    # net_margin = (100 / 1000) * 100 = 10.0%
    assert result["net_margin"] == pytest.approx(10.0, rel=1e-3)


def test_earnings_quality_uses_annual_not_ttm():
    """
    OCF/NP ratio must use annual NP (100), not TTM NP (200).
    ocf_to_net_profit = 90 / 100 = 0.9 (high quality).
    If TTM used: 90 / 200 = 0.45 → medium quality (wrong).
    """
    data = _ttm_data()
    result = _compute_earnings_quality(data)
    assert result["ocf_to_net_profit"] == pytest.approx(0.9, rel=1e-3)
    assert result["quality_flag"] == "high"


def test_owner_earnings_uses_annual_not_ttm():
    """
    Owner earnings must use annual NP (100) and depreciation (25), not TTM values.
    OE = 100 + 25 + (-20) = 105 Cr.
    If TTM used: 200 + 50 + (-20) = 230 Cr (wrong).
    """
    from src.signals import _compute_owner_earnings
    data = _ttm_data()
    result = _compute_owner_earnings(data)
    assert result["owner_earnings_cr"] == pytest.approx(105.0, rel=1e-3)
    assert result["oe_reason"] is None
