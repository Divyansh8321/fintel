# ============================================================
# FILE: src/models.py
# PURPOSE: Pydantic model definitions for the signal pipeline.
#          This is the contract layer — every downstream module
#          (signals.py, agents, synthesis) imports from here.
#          All signal fields are Optional[float] = None so that
#          data gaps are represented as None, never as exceptions
#          (see TRADEOFFS.md T-011).
# INPUT:   n/a — module-level definitions only
# OUTPUT:  SignalsModel (top-level) + 16 nested sub-models
# DEPENDS: pydantic>=2.0
# ============================================================

from typing import Optional

from pydantic import BaseModel, field_validator, model_validator


# ---------------------------------------------------------------------------
# Sub-model: company metadata
# ---------------------------------------------------------------------------

class MetaModel(BaseModel):
    """
    Company identity and price data populated from the scraper header.

    All fields are required — a SignalsModel without valid metadata is
    meaningless and should be rejected before reaching the agents.
    """

    name: str
    sector: str
    current_price: float
    market_cap: float
    is_bank: bool
    high_52w: float
    low_52w: float

    @field_validator("name", "sector")
    @classmethod
    def must_be_non_empty(cls, v: str, info) -> str:
        """Reject empty or whitespace-only strings for name and sector."""
        if not v or not v.strip():
            raise ValueError(f"{info.field_name} must be a non-empty string")
        return v

    @field_validator("current_price", "market_cap")
    @classmethod
    def must_be_positive(cls, v: float, info) -> float:
        """Reject zero or negative prices and market caps."""
        if v <= 0:
            raise ValueError(f"{info.field_name} must be a positive float, got {v}")
        return v


# ---------------------------------------------------------------------------
# Sub-model: Piotroski F-Score
# ---------------------------------------------------------------------------

class PiotroskiModel(BaseModel):
    """Piotroski F-Score (0–9) and per-signal breakdown."""

    score: Optional[int] = None
    label: Optional[str] = None
    signals: Optional[dict] = None


# ---------------------------------------------------------------------------
# Sub-model: DuPont Decomposition
# ---------------------------------------------------------------------------

class DupontModel(BaseModel):
    """ROE decomposed into margin × asset turnover × leverage."""

    latest_year: Optional[str] = None
    net_margin: Optional[float] = None
    net_margin_reason: Optional[str] = None
    asset_turnover: Optional[float] = None
    asset_turnover_reason: Optional[str] = None
    leverage: Optional[float] = None
    leverage_reason: Optional[str] = None
    roe_computed: Optional[float] = None
    roe_driver: Optional[str] = None


# ---------------------------------------------------------------------------
# Sub-model: Earnings Quality
# ---------------------------------------------------------------------------

class EarningsQualityModel(BaseModel):
    """OCF/NP and FCF/NP ratios — how well reported profit is backed by cash."""

    ocf_to_net_profit: Optional[float] = None
    ocf_to_net_profit_reason: Optional[str] = None
    fcf_to_net_profit: Optional[float] = None
    fcf_to_net_profit_reason: Optional[str] = None
    quality_flag: Optional[str] = None


# ---------------------------------------------------------------------------
# Sub-model: Growth Quality
# ---------------------------------------------------------------------------

class GrowthQualityModel(BaseModel):
    """Revenue and profit CAGR trends, margin trend, and acceleration label."""

    revenue_cagr_10yr: Optional[float] = None
    revenue_cagr_5yr: Optional[float] = None
    revenue_cagr_3yr: Optional[float] = None
    profit_cagr_10yr: Optional[float] = None
    profit_cagr_5yr: Optional[float] = None
    profit_cagr_3yr: Optional[float] = None
    margin_trend: Optional[str] = None
    acceleration: Optional[str] = None


# ---------------------------------------------------------------------------
# Sub-model: Capital Efficiency
# ---------------------------------------------------------------------------

class CapitalEfficiencyModel(BaseModel):
    """ROCE trend, interest coverage, and working capital cycle trend."""

    roce_latest: Optional[float] = None
    roce_latest_reason: Optional[str] = None
    roce_3yr_avg: Optional[float] = None
    roce_3yr_avg_reason: Optional[str] = None
    roce_trend: Optional[str] = None
    interest_coverage: Optional[float] = None
    interest_coverage_reason: Optional[str] = None
    working_capital_days_trend: Optional[str] = None


# ---------------------------------------------------------------------------
# Sub-model: Balance Sheet Health
# ---------------------------------------------------------------------------

class BalanceSheetHealthModel(BaseModel):
    """Debt-to-equity ratio, debt trend, and interest burden."""

    debt_to_equity_latest: Optional[float] = None
    debt_to_equity_latest_reason: Optional[str] = None
    debt_trend: Optional[str] = None
    interest_coverage: Optional[float] = None


# ---------------------------------------------------------------------------
# Sub-model: Valuation
# ---------------------------------------------------------------------------

class ValuationModel(BaseModel):
    """Graham Number, PE, earnings yield, DCF, and relative multiples."""

    graham_number: Optional[float] = None
    graham_number_reason: Optional[str] = None
    price_to_graham: Optional[float] = None
    graham_verdict: Optional[str] = None
    pe_current: Optional[float] = None
    earnings_yield: Optional[float] = None
    ev_ebitda: Optional[float] = None
    price_to_sales: Optional[float] = None
    industry_pe: Optional[float] = None
    # DCF fields (merged in by compute_signals after _compute_dcf)
    dcf_intrinsic_value: Optional[float] = None
    dcf_intrinsic_value_reason: Optional[str] = None
    dcf_margin_of_safety: Optional[float] = None
    dcf_stage1_growth: Optional[float] = None
    dcf_method: Optional[str] = None


# ---------------------------------------------------------------------------
# Sub-model: Promoter Risk
# ---------------------------------------------------------------------------

class PromoterRiskModel(BaseModel):
    """Pledged share percentage, flag, trend, and promoter holding."""

    pledged_pct: Optional[float] = None
    pledge_flag: Optional[str] = None
    pledge_trend: Optional[str] = None
    promoter_holding: Optional[float] = None
    promoter_holding_change: Optional[float] = None


# ---------------------------------------------------------------------------
# Sub-model: Quarterly Momentum
# ---------------------------------------------------------------------------

class QuarterlyMomentumModel(BaseModel):
    """YoY revenue/profit growth and OPM trend from quarterly data."""

    revenue_yoy_pct: Optional[float] = None
    revenue_yoy_pct_reason: Optional[str] = None
    profit_yoy_pct: Optional[float] = None
    profit_yoy_pct_reason: Optional[str] = None
    opm_trend: Optional[str] = None


# ---------------------------------------------------------------------------
# Sub-model: Bank / NBFC Signals
# ---------------------------------------------------------------------------

class BankSignalsModel(BaseModel):
    """
    Bank/NBFC-specific signals covering NPA, CAR, NIM, and P/B.

    All four core fields (gross_npa_pct, net_npa_pct, car_pct, nim_pct)
    are required when this model is constructed — callers must not pass
    None for these because they are the primary diagnostics for a bank.
    """

    gross_npa_pct: float
    net_npa_pct: float
    car_pct: float
    nim_pct: float
    # Derived / trend fields remain optional
    npa_flag: Optional[str] = None
    car_vs_minimum: Optional[float] = None
    price_to_book: Optional[float] = None
    roe_latest: Optional[float] = None
    roe_trend: Optional[str] = None
    deposit_growth_pct: Optional[float] = None
    nim_trend: Optional[str] = None


# ---------------------------------------------------------------------------
# Sub-models: agent pre-computations (moved from agent files in #8)
# ---------------------------------------------------------------------------

class PegModel(BaseModel):
    """PEG ratio = PE / 3yr profit CAGR (Lynch metric)."""

    peg_ratio: Optional[float] = None
    peg_verdict: Optional[str] = None
    peg_reason: Optional[str] = None


class OwnerEarningsModel(BaseModel):
    """Buffett owner earnings = NI + dep + capex - ΔWC."""

    owner_earnings_cr: Optional[float] = None
    owner_earnings_per_share: Optional[float] = None
    owner_earnings_yield_pct: Optional[float] = None
    oe_reason: Optional[str] = None


class DscrModel(BaseModel):
    """Debt Service Coverage Ratio = OCF / interest expense."""

    dscr: Optional[float] = None
    dscr_verdict: Optional[str] = None
    dscr_reason: Optional[str] = None


class RoceWaccModel(BaseModel):
    """ROCE minus WACC proxy — positive spread = value creation."""

    roce_latest: Optional[float] = None
    wacc_proxy: Optional[float] = None
    roce_wacc_spread: Optional[float] = None
    spread_verdict: Optional[str] = None
    spread_reason: Optional[str] = None


class PriceMomentumModel(BaseModel):
    """52-week price position as a percentage of the high–low range."""

    position_pct: Optional[float] = None
    high_52w: Optional[float] = None
    low_52w: Optional[float] = None
    current_price: Optional[float] = None
    position_verdict: Optional[str] = None
    position_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Top-level model
# ---------------------------------------------------------------------------

class SignalsModel(BaseModel):
    """
    Top-level typed contract for the signal pipeline.

    Produced by compute_signals() and consumed by all five analyst agents
    and synthesis.py. Agents access fields via dot-notation (signals.meta.name,
    signals.valuation.pe_current, etc.) — no chained .get() calls.

    All computed signal sub-models default to None-populated instances.
    Agent pre-computation sub-models (peg, owner_earnings, dscr, roce_wacc,
    price_momentum) are populated by compute_signals() in issue #8.
    """

    # Company metadata — required, validated by MetaModel
    meta: MetaModel

    # Signal groups — all optional at construction (data gaps are normal)
    piotroski: Optional[PiotroskiModel] = None
    dupont: Optional[DupontModel] = None
    earnings_quality: Optional[EarningsQualityModel] = None
    growth_quality: Optional[GrowthQualityModel] = None
    capital_efficiency: Optional[CapitalEfficiencyModel] = None
    balance_sheet_health: Optional[BalanceSheetHealthModel] = None
    valuation: Optional[ValuationModel] = None
    promoter_risk: Optional[PromoterRiskModel] = None
    quarterly_momentum: Optional[QuarterlyMomentumModel] = None

    # Bank-specific signals — None for non-banks, required for banks (see validator)
    bank_signals: Optional[BankSignalsModel] = None

    # Agent pre-computation sub-models (populated by compute_signals in #8)
    peg: Optional[PegModel] = None
    owner_earnings: Optional[OwnerEarningsModel] = None
    dscr: Optional[DscrModel] = None
    roce_wacc: Optional[RoceWaccModel] = None
    price_momentum: Optional[PriceMomentumModel] = None

    # Derived scores — plain ints (mechanical Python, not LLM)
    fundamentals_score: int = 5
    valuation_score: int = 5

    # Working capital source flag
    wc_source: str = "unavailable"

    @model_validator(mode="after")
    def bank_signals_required_for_banks(self) -> "SignalsModel":
        """
        Enforce that bank_signals is populated whenever is_bank is True.

        A SignalsModel for a bank without bank_signals is incomplete and
        should be rejected at construction time, not silently ignored.
        """
        if self.meta.is_bank and self.bank_signals is None:
            raise ValueError(
                "bank_signals must not be None when meta.is_bank is True"
            )
        return self
