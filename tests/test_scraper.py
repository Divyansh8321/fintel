# ============================================================
# FILE: tests/test_scraper.py
# PURPOSE: Live integration tests for src/scraper.py.
#          Hits real Screener.in with real credentials to verify
#          the scraper returns complete, correctly-structured data.
# INPUT:   SCREENER_EMAIL + SCREENER_PASSWORD in .env
# OUTPUT:  pytest pass/fail
# DEPENDS: pytest, src/scraper.py, .env (SCREENER_EMAIL, SCREENER_PASSWORD)
# NOTE:    All tests are SKIPPED (not failed) if SCREENER_EMAIL is not set.
#          No mocks, no fixtures, no hardcoded values — live data only.
# ============================================================

import os

import pytest
from dotenv import load_dotenv

load_dotenv()

# Skip every test in this module if credentials are absent.
# This prevents CI from failing when .env is not configured.
pytestmark = pytest.mark.skipif(
    not os.getenv("SCREENER_EMAIL"),
    reason="SCREENER_EMAIL not set — live tests require Screener.in credentials in .env",
)

# ---------------------------------------------------------------------------
# Module-level fixture — fetch RELIANCE once, reuse across tests.
# Avoids hitting Screener.in 5 times for the same data.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def reliance():
    """
    Fetches RELIANCE (consolidated) data once per test module run.

    Using scope="module" means Screener.in is hit once and the result
    is shared across all tests that use this fixture.

    Returns:
        Full dict from fetch_company_data("RELIANCE").
    """
    from src.scraper import fetch_company_data
    return fetch_company_data("RELIANCE")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_reliance_returns_all_top_level_keys(reliance):
    """
    Every top-level key must be present in the output.

    This is the most important test — if any section is missing, the
    downstream analysis and API will break.
    """
    expected_keys = {
        "is_consolidated",
        "currency",
        "header",
        "header_units",
        "key_ratios",
        "pl_table",
        "growth_rates",
        "balance_sheet",
        "cash_flow",
        "ratios_table",
        "quarterly",
        "shareholding",
        "pros_cons",
    }
    assert set(reliance.keys()) == expected_keys


def test_reliance_is_consolidated(reliance):
    """RELIANCE has consolidated financials — must use the consolidated page."""
    assert reliance["is_consolidated"] is True


def test_reliance_header_fields_present_and_non_empty(reliance):
    """
    All header fields must be present and have non-None, non-zero values
    (except price_change_pct which can legitimately be 0 on a flat day).
    """
    h = reliance["header"]
    required = ["name", "sector", "bse_code", "nse_code", "current_price",
                "market_cap", "high_52w", "low_52w", "face_value"]
    for field in required:
        assert field in h, f"Missing header field: {field}"
        assert h[field] is not None, f"header.{field} is None"
        assert h[field] != "", f"header.{field} is empty string"

    # Numeric fields must be positive
    for field in ["current_price", "market_cap", "high_52w", "low_52w", "face_value"]:
        assert h[field] > 0, f"header.{field} should be > 0, got {h[field]}"


def test_reliance_pl_table_has_at_least_ten_years(reliance):
    """P&L table must cover at least 10 annual periods (Screener shows 10yr + TTM)."""
    pl = reliance["pl_table"]
    assert "years" in pl
    assert len(pl["years"]) >= 10, f"Expected >=10 years, got {len(pl['years'])}"


def test_reliance_pl_table_all_rows_present(reliance):
    """Every expected P&L row must be present in the output."""
    pl = reliance["pl_table"]
    for field in ["sales", "operating_profit", "opm_pct", "other_income",
                  "interest", "depreciation", "net_profit", "eps", "dividend_payout_pct"]:
        assert field in pl, f"Missing P&L field: {field}"
        assert isinstance(pl[field], list), f"pl_table.{field} should be a list"
        assert len(pl[field]) == len(pl["years"]), \
            f"pl_table.{field} length mismatch: {len(pl[field])} vs {len(pl['years'])} years"


def test_reliance_growth_rates_all_present(reliance):
    """All 8 CAGR values must be present and be numbers."""
    gr = reliance["growth_rates"]
    for field in ["sales_cagr_10yr", "sales_cagr_5yr", "sales_cagr_3yr", "sales_ttm",
                  "profit_cagr_10yr", "profit_cagr_5yr", "profit_cagr_3yr", "profit_ttm"]:
        assert field in gr, f"Missing growth rate: {field}"
        assert isinstance(gr[field], (int, float)), f"growth_rates.{field} is not a number"


def test_reliance_shareholding_fields_present(reliance):
    """Shareholding must have all required fields with valid percentage values."""
    sh = reliance["shareholding"]
    for field in ["quarter", "promoter_pct", "fii_pct", "dii_pct", "public_pct", "pledged_pct"]:
        assert field in sh, f"Missing shareholding field: {field}"

    # Percentages must be in [0, 100]
    for field in ["promoter_pct", "fii_pct", "dii_pct", "public_pct", "pledged_pct"]:
        assert 0 <= sh[field] <= 100, \
            f"shareholding.{field} = {sh[field]} is outside [0, 100]"


def test_reliance_units_metadata_correct(reliance):
    """Unit metadata must reflect INR Crores for all financial table sections."""
    assert reliance["currency"] == "INR"
    for section in ["pl_table", "balance_sheet", "cash_flow", "ratios_table", "quarterly"]:
        units = reliance[section].get("units")
        assert units is not None, f"{section} missing 'units' key"
        assert units["currency"] == "INR", f"{section}.units.currency is not INR"
        assert units["scale"] == "Cr", f"{section}.units.scale is not Cr"


def test_invalid_ticker_raises_value_error():
    """
    A nonsense ticker must raise ValueError, not return partial data or crash.

    This verifies the fail-hard error policy — callers must always get either
    complete data or a clear exception, never a silent failure.
    """
    from src.scraper import fetch_company_data
    with pytest.raises(ValueError, match="not found"):
        fetch_company_data("ZZZZINVALIDTICKER99999")


def test_all_required_keys_present_regardless_of_consolidation(reliance):
    """
    The scraper must return all required top-level keys whether it fetched
    consolidated or standalone data. RELIANCE (consolidated) is used here —
    the is_consolidated field itself is verified in test_reliance_is_consolidated.

    This test is not tied to any specific company being standalone-only,
    which would be fragile (companies gain/lose consolidated status over time).
    """
    required_keys = {
        "is_consolidated", "currency", "header", "header_units",
        "key_ratios", "pl_table", "growth_rates", "balance_sheet",
        "cash_flow", "ratios_table", "quarterly", "shareholding", "pros_cons",
    }
    assert required_keys.issubset(set(reliance.keys()))
    # is_consolidated must be a bool — either path is valid
    assert isinstance(reliance["is_consolidated"], bool)
    # Financial tables must have data
    assert len(reliance["pl_table"]["years"]) >= 10
    assert len(reliance["balance_sheet"]["years"]) >= 10
