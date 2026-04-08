# ============================================================
# FILE: tests/test_models.py
# PURPOSE: Unit tests for src/models.py Pydantic validators.
#          Pure tests — no I/O, no mocks, no network.
# INPUT:   n/a
# OUTPUT:  pytest pass/fail
# DEPENDS: pytest, pydantic, src/models.py
# ============================================================

import pytest
from pydantic import ValidationError

from src.models import (
    BankSignalsModel,
    MetaModel,
    SignalsModel,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_meta(**overrides) -> dict:
    """Return a valid MetaModel kwargs dict, with optional overrides."""
    base = {
        "name": "RELIANCE",
        "sector": "Energy",
        "current_price": 2500.0,
        "market_cap": 1_600_000.0,
        "is_bank": False,
        "high_52w": 3000.0,
        "low_52w": 2000.0,
    }
    base.update(overrides)
    return base


def _valid_signals(**overrides) -> dict:
    """Return a valid SignalsModel kwargs dict (non-bank, all optionals omitted)."""
    base = {"meta": MetaModel(**_valid_meta())}
    base.update(overrides)
    return base


def _valid_bank_signals(**overrides) -> dict:
    """Return a valid BankSignalsModel kwargs dict."""
    base = {
        "gross_npa_pct": 2.5,
        "net_npa_pct": 1.0,
        "car_pct": 16.0,
        "nim_pct": 3.2,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# MetaModel validators
# ---------------------------------------------------------------------------

def test_empty_name_raises():
    with pytest.raises(ValidationError, match="name"):
        MetaModel(**_valid_meta(name=""))


def test_whitespace_name_raises():
    with pytest.raises(ValidationError, match="name"):
        MetaModel(**_valid_meta(name="   "))


def test_empty_sector_raises():
    with pytest.raises(ValidationError, match="sector"):
        MetaModel(**_valid_meta(sector=""))


def test_zero_current_price_raises():
    with pytest.raises(ValidationError, match="current_price"):
        MetaModel(**_valid_meta(current_price=0.0))


def test_negative_current_price_raises():
    with pytest.raises(ValidationError, match="current_price"):
        MetaModel(**_valid_meta(current_price=-100.0))


# ---------------------------------------------------------------------------
# SignalsModel — bank_signals validator
# ---------------------------------------------------------------------------

def test_bank_without_bank_signals_raises():
    meta = MetaModel(**_valid_meta(is_bank=True))
    with pytest.raises(ValidationError, match="bank_signals"):
        SignalsModel(meta=meta)


def test_bank_with_bank_signals_constructs():
    meta = MetaModel(**_valid_meta(is_bank=True))
    bank = BankSignalsModel(**_valid_bank_signals())
    sm = SignalsModel(meta=meta, bank_signals=bank)
    assert sm.meta.is_bank is True
    assert sm.bank_signals.gross_npa_pct == 2.5


def test_non_bank_constructs_without_bank_signals():
    sm = SignalsModel(**_valid_signals())
    assert sm.meta.is_bank is False
    assert sm.bank_signals is None


def test_valid_non_bank_all_optionals_none():
    sm = SignalsModel(**_valid_signals())
    assert sm.piotroski is None
    assert sm.valuation is None
    assert sm.peg is None
    assert sm.dscr is None


# ---------------------------------------------------------------------------
# BankSignalsModel — required fields
# ---------------------------------------------------------------------------

def test_bank_signals_missing_gross_npa_raises():
    with pytest.raises(ValidationError):
        BankSignalsModel(**_valid_bank_signals(gross_npa_pct=None))


def test_bank_signals_missing_car_raises():
    with pytest.raises(ValidationError):
        BankSignalsModel(**_valid_bank_signals(car_pct=None))
