# Fintel — Complete Financial Metrics Reference

## How to read this table
- **Source:** "Screener" = scraped directly | "Python" = computed in signals.py
- **Tier:** 1 = always present, crash if missing | 2 = expected, validate range if present | 3 = genuinely optional, None is normal
- **Formula:** exact computation or Screener field name

---

## SECTION A — Header / Meta (scraper.py)

| # | Metric | Source | Formula / Screener Field | Unit | Tier |
|---|--------|--------|--------------------------|------|------|
| 1 | Company Name | Screener | `h1` tag | text | 1 |
| 2 | Sector | Screener | `section#peers` link | text | 1 |
| 3 | Current Price | Screener | `ul#top-ratios` current price | INR | 1 |
| 4 | Market Cap | Screener | `ul#top-ratios` Market Cap | INR Cr | 1 |
| 5 | 52-Week High | Screener | `ul#top-ratios` High / Low (first) | INR | 1 |
| 6 | 52-Week Low | Screener | `ul#top-ratios` High / Low (second) | INR | 1 |
| 7 | Face Value | Screener | `ul#top-ratios` Face Value | INR | 1 |
| 8 | Dividend Yield | Screener | `ul#top-ratios` Dividend Yield | % | 2 |
| 9 | Price Change % | Screener | `span.up` / `span.down` | % | 2 |
| 10 | BSE Code | Screener | `.company-links` anchor href | code | 3 |
| 11 | NSE Code | Screener | `.company-links` anchor href | code | 3 |

---

## SECTION B — Key Ratios (scraper.py, quick_ratios API)

| # | Metric | Source | Formula / Screener Field | Unit | Tier |
|---|--------|--------|--------------------------|------|------|
| 12 | P/E Ratio | Screener | `ul#top-ratios` Stock P/E | x | 2 |
| 13 | Book Value per Share | Screener | `ul#top-ratios` Book Value | INR | 2 |
| 14 | ROCE | Screener | `ul#top-ratios` ROCE | % | 2 |
| 15 | ROE | Screener | `ul#top-ratios` ROE | % | 2 |
| 16 | Debt to Equity | Screener | quick_ratios "Debt / Equity" | x | 2 |
| 17 | Current Ratio | Screener | quick_ratios "Current ratio" | x | 3 |
| 18 | Pledged % | Screener | quick_ratios "Pledged percentage" | % | 2 |
| 19 | EV/EBITDA | Screener | quick_ratios "EV / EBITDA" | x | 3 |
| 20 | Price to Sales | Screener | quick_ratios "Price to Sales" | x | 3 |
| 21 | Promoter Holding | Screener | quick_ratios "Promoter holding" | % | 2 |
| 22 | Promoter Holding Change | Screener | quick_ratios "Change in promoter holding" | % | 3 |
| 23 | Industry PE | Screener | quick_ratios "Industry PE" | x | 3 |
| 24 | Price to Book | Screener | quick_ratios "Price to Book" | x | 3 |

---

## SECTION C — P&L Statement (Annual, 10 years) (scraper.py)

| # | Metric | Source | Formula / Screener Field | Unit | Tier |
|---|--------|--------|--------------------------|------|------|
| 25 | Sales | Screener | "Sales" row | INR Cr | 1 |
| 26 | Operating Profit | Screener | "Operating Profit" row | INR Cr | 1 |
| 27 | OPM % | Screener | "OPM %" row | % | 1 |
| 28 | Other Income | Screener | "Other Income" row | INR Cr | 2 |
| 29 | Interest Expense | Screener | "Interest" row | INR Cr | 2 |
| 30 | Depreciation | Screener | "Depreciation" row | INR Cr | 2 |
| 31 | Net Profit | Screener | "Net Profit" row | INR Cr | 1 |
| 32 | EPS | Screener | "EPS" row | INR/share | 1 |
| 33 | Dividend Payout % | Screener | "Dividend Payout" row | % | 3 |
| 34 | Tax % | Screener | "Tax %" row | % | 3 |

---

## SECTION D — Growth Rates (scraper.py, Screener CAGR tables)

| # | Metric | Source | Formula / Screener Field | Unit | Tier |
|---|--------|--------|--------------------------|------|------|
| 35 | Revenue CAGR 10yr | Screener | Compounded Sales Growth (10 years) | % | 2 |
| 36 | Revenue CAGR 5yr | Screener | Compounded Sales Growth (5 years) | % | 2 |
| 37 | Revenue CAGR 3yr | Screener | Compounded Sales Growth (3 years) | % | 2 |
| 38 | Revenue TTM | Screener | Compounded Sales Growth (TTM) | % | 3 |
| 39 | Profit CAGR 10yr | Screener | Compounded Profit Growth (10 years) | % | 2 |
| 40 | Profit CAGR 5yr | Screener | Compounded Profit Growth (5 years) | % | 2 |
| 41 | Profit CAGR 3yr | Screener | Compounded Profit Growth (3 years) | % | 2 |
| 42 | Profit TTM | Screener | Compounded Profit Growth (TTM) | % | 3 |

---

## SECTION E — Balance Sheet (Annual, 10 years) (scraper.py)

| # | Metric | Source | Formula / Screener Field | Unit | Tier |
|---|--------|--------|--------------------------|------|------|
| 43 | Equity Capital | Screener | "Equity Capital" row | INR Cr | 1 |
| 44 | Reserves | Screener | "Reserves" row | INR Cr | 1 |
| 45 | Borrowings | Screener | "Borrowings" row | INR Cr | 1 |
| 46 | Other Liabilities | Screener | "Other Liabilities" row | INR Cr | 2 |
| 47 | Total Liabilities | Screener | "Total Liabilities" row | INR Cr | 1 |
| 48 | Fixed Assets | Screener | "Fixed Assets" row | INR Cr | 2 |
| 49 | CWIP | Screener | "CWIP" row | INR Cr | 3 |
| 50 | Investments | Screener | "Investments" row | INR Cr | 2 |
| 51 | Other Assets | Screener | "Other Assets" row | INR Cr | 2 |
| 52 | Total Assets | Screener | "Total Assets" row | INR Cr | 1 |
| 53 | Inventories | Screener / Python | Schedule API OR derived from inventory_days × sales/365 | INR Cr | 3 |
| 54 | Trade Receivables | Screener / Python | Schedule API OR debtor_days × sales/365 | INR Cr | 3 |
| 55 | Cash Equivalents | Screener | Schedule API | INR Cr | 3 |
| 56 | Trade Payables | Screener / Python | Schedule API OR days_payable × COGS/365 | INR Cr | 3 |
| 57 | Long-term Borrowings | Screener | Borrowings schedule | INR Cr | 3 |
| 58 | Short-term Borrowings | Screener | Borrowings schedule | INR Cr | 3 |
| 59 | Lease Liabilities | Screener | Borrowings schedule | INR Cr | 3 |
| 60 | Gross Block | Screener | Fixed Assets schedule | INR Cr | 3 |
| 61 | Accumulated Depreciation | Screener | Fixed Assets schedule | INR Cr | 3 |
| 62 | Deposits (banks only) | Screener | "Deposits" row | INR Cr | 1 (banks) |

---

## SECTION F — Cash Flow (Annual, 10 years) (scraper.py)

| # | Metric | Source | Formula / Screener Field | Unit | Tier |
|---|--------|--------|--------------------------|------|------|
| 63 | Operating Cash Flow | Screener | "Cash from Operating" row | INR Cr | 1 |
| 64 | Investing Cash Flow | Screener | "Cash from Investing" row | INR Cr | 1 |
| 65 | Financing Cash Flow | Screener | "Cash from Financing" row | INR Cr | 1 |
| 66 | Net Cash Flow | Screener | "Net Cash Flow" row | INR Cr | 1 |
| 67 | CapEx | Screener | Investing schedule "Fixed assets purchased" (negative) | INR Cr | 2 |
| 68 | Fixed Assets Sold | Screener | Investing schedule "Fixed assets sold" | INR Cr | 3 |
| 69 | Investments Purchased | Screener | Investing schedule "Investments purchased" | INR Cr | 3 |
| 70 | Investments Sold | Screener | Investing schedule "Investments sold" | INR Cr | 3 |

---

## SECTION G — Ratios Table (Annual, 10 years) (scraper.py)

| # | Metric | Source | Formula / Screener Field | Unit | Tier |
|---|--------|--------|--------------------------|------|------|
| 71 | Debtor Days | Screener | "Debtor Days" row | days | 2 |
| 72 | Inventory Days | Screener | "Inventory Days" row | days | 2 |
| 73 | Days Payable | Screener | "Days Payable" row | days | 2 |
| 74 | Cash Conversion Cycle | Screener | "Cash Conversion Cycle" row | days | 2 |
| 75 | Working Capital Days | Screener | "Working Capital Days" row | days | 2 |
| 76 | ROCE (annual series) | Screener | "ROCE" row | % | 2 |

---

## SECTION H — Quarterly Results (scraper.py)

| # | Metric | Source | Formula / Screener Field | Unit | Tier |
|---|--------|--------|--------------------------|------|------|
| 77 | Quarterly Sales | Screener | "Sales" row (quarterly) | INR Cr | 1 |
| 78 | Quarterly Operating Profit | Screener | "Operating Profit" row (quarterly) | INR Cr | 1 |
| 79 | Quarterly OPM % | Screener | "OPM %" row (quarterly) | % | 1 |
| 80 | Quarterly Net Profit | Screener | "Net Profit" row (quarterly) | INR Cr | 1 |
| 81 | Quarterly EPS | Screener | "EPS" row (quarterly) | INR/share | 1 |

---

## SECTION I — Shareholding (scraper.py)

| # | Metric | Source | Formula / Screener Field | Unit | Tier |
|---|--------|--------|--------------------------|------|------|
| 82 | Promoter % | Screener | "Promoters" row | % | 1 |
| 83 | FII % | Screener | "FIIs" row | % | 1 |
| 84 | DII % | Screener | "DIIs" row | % | 1 |
| 85 | Public % | Screener | "Public" row | % | 1 |
| 86 | Pledged % (history) | Screener | "Pledged" row per quarter | % | 2 |

---

## SECTION J — Piotroski F-Score (signals.py → _compute_piotroski)

| # | Metric | Source | Formula | Unit | Tier |
|---|--------|--------|---------|------|------|
| 87 | F1: ROA Positive | Python | net_profit[0] / total_assets[0] > 0 | binary 0/1 | 2 |
| 88 | F2: OCF Positive | Python | cash_flow.operating[0] > 0 | binary 0/1 | 2 |
| 89 | F3: ROA Improving | Python | (NP[0]/TA[0]) > (NP[1]/TA[1]) | binary 0/1 | 2 |
| 90 | F4: OCF > Net Income | Python | operating_cf[0] > net_profit[0] | binary 0/1 | 2 |
| 91 | F5: Leverage Decreasing | Python | (borrowings[0]/TA[0]) < (borrowings[1]/TA[1]) | binary 0/1 | 2 |
| 92 | F6: Current Ratio > 1.0 | Python | key_ratios.current_ratio > 1.0 (single-point; YoY series unavailable from Screener) | binary 0/1 | 2 |
| 93 | F7: No Share Dilution | Python | (eps[0]/NP[0]) >= (eps[1]/NP[1]) | binary 0/1 | 2 |
| 94 | F8: Gross Margin Improving | Python | opm_pct[0] > opm_pct[1] | binary 0/1 | 2 |
| 95 | F9: Asset Turnover Improving | Python | (sales[0]/TA[0]) > (sales[1]/TA[1]) | binary 0/1 | 2 |
| 96 | Piotroski Score | Python | sum(F1…F9) | 0–9 | 2 |
| 97 | Piotroski Label | Python | 0-2 "Distressed" / 3-5 "Moderate" / 6-9 "Financially strong" | text | 2 |

---

## SECTION K — DuPont Decomposition (signals.py → _compute_dupont)

| # | Metric | Source | Formula | Unit | Tier |
|---|--------|--------|---------|------|------|
| 98 | Net Margin | Python | (net_profit[0] / sales[0]) × 100 | % | 2 |
| 99 | Asset Turnover | Python | sales[0] / total_assets[0] | x | 2 |
| 100 | Leverage | Python | total_assets[0] / (equity_capital[0] + reserves[0]) | x | 2 |
| 101 | ROE (computed) | Python | (net_margin/100) × asset_turnover × leverage × 100 | % | 2 |
| 102 | ROE Driver | Python | Dominant DuPont component: "leverage" / "margins" / "efficiency" / "mixed" | text | 2 |

---

## SECTION L — Earnings Quality (signals.py → _compute_earnings_quality)

| # | Metric | Source | Formula | Unit | Tier |
|---|--------|--------|---------|------|------|
| 103 | OCF to Net Profit | Python | operating_cf[0] / net_profit[0] | x | 2 |
| 104 | FCF to Net Profit | Python | (operating_cf[0] + capex[0]) / net_profit[0] | x | 2 |
| 105 | Quality Flag | Python | OCF/NP≥1 & FCF/NP≥0.7 → "high" / OCF/NP≥0.7 → "medium" / else "low" | text | 2 |

---

## SECTION M — Growth Quality (signals.py → _compute_growth_quality)

| # | Metric | Source | Formula | Unit | Tier |
|---|--------|--------|---------|------|------|
| 106 | Margin Trend | Python | (opm_now - avg(opm_prev_3yr)) / abs(avg(opm_prev_3yr)) → >5% "expanding" / <-5% "contracting" / else "stable" | text | 2 |
| 107 | Acceleration | Python | revenue_cagr_3yr - revenue_cagr_10yr → >3% "accelerating" / <-3% "decelerating" / else "stable" | text | 2 |

---

## SECTION N — Capital Efficiency (signals.py → _compute_capital_efficiency)

| # | Metric | Source | Formula | Unit | Tier |
|---|--------|--------|---------|------|------|
| 108 | ROCE Latest | Screener | ratios_table.roce[0] | % | 2 |
| 109 | ROCE 3yr Average | Python | mean(roce_series[:3]) | % | 2 |
| 110 | ROCE Trend | Python | Linear slope over 5 points → "improving" / "stable" / "declining" | text | 2 |
| 111 | Interest Coverage | Python | operating_profit[0] / interest[0] (9999 if debt-free) | x | 2 |
| 112 | Working Capital Days Trend | Python | Inverted WC days slope → "improving" / "stable" / "worsening" | text | 3 |

---

## SECTION O — Balance Sheet Health (signals.py → _compute_balance_sheet_health)

| # | Metric | Source | Formula | Unit | Tier |
|---|--------|--------|---------|------|------|
| 113 | Debt to Equity | Screener or Python | (LT borrowings + ST borrowings + lease) / (equity + reserves) | x | 2 |
| 114 | Debt Trend | Python | (borrowings[0] - borrowings[2]) / abs(borrowings[2]) → >10% "increasing" / <-10% "reducing" / else "stable" | text | 2 |

---

## SECTION P — Valuation (signals.py → _compute_valuation)

| # | Metric | Source | Formula | Unit | Tier |
|---|--------|--------|---------|------|------|
| 115 | Graham Number | Python | √(22.5 × EPS × Book Value per Share) | INR | 2 |
| 116 | Price to Graham | Python | (current_price / graham_number) − 1 | decimal | 2 |
| 117 | Graham Verdict | Python | <-10% "undervalued" / ±10% "fairly_valued" / >+10% "overvalued" | text | 2 |
| 118 | Earnings Yield | Python | (EPS / current_price) × 100 | % | 2 |

---

## SECTION Q — DCF Valuation (signals.py → _compute_dcf)

| # | Metric | Source | Formula | Unit | Tier |
|---|--------|--------|---------|------|------|
| 119 | FCF Base | Python | operating_cf[0] + capex[0] | INR Cr | 3 |
| 120 | Stage 1 Growth Rate | Python | min(sales_cagr_3yr / 100, 0.25) | decimal | 3 |
| 121 | DCF Intrinsic Value | Python | PV(Stage1 FCFs, 5yr) + PV(Stage2 FCFs, 5yr) + PV(Terminal) / shares | INR/share | 3 |
| 122 | DCF Margin of Safety | Python | (intrinsic_value − current_price) / intrinsic_value | decimal | 3 |
| 123 | DCF Method | Python | "fcf_dcf" (normal) / "epv" (EPV fallback when FCF ≤ 0) | text | 3 |
| 124 | EPV (fallback) | Python | EPS[0] / 0.12 (WACC proxy) | INR/share | 3 |

---

## SECTION R — Promoter Risk (signals.py → _compute_promoter_risk)

| # | Metric | Source | Formula | Unit | Tier |
|---|--------|--------|---------|------|------|
| 125 | Pledged % | Screener | key_ratios.pledged_pct or shareholding.pledged_pct | % | 2 |
| 126 | Pledge Flag | Python | <5% "none" / 5–20% "moderate" / >20% "high" | text | 2 |
| 127 | Pledge Trend | Python | latest_pledged − oldest_pledged → >2% "increasing" / <-2% "decreasing" / else "stable" | text | 2 |
| 128 | Promoter Holding | Screener | key_ratios.promoter_holding | % | 2 |
| 129 | Promoter Holding Change | Screener | key_ratios.promoter_holding_change | % | 3 |

---

## SECTION S — Quarterly Momentum (signals.py → _compute_quarterly_momentum)

| # | Metric | Source | Formula | Unit | Tier |
|---|--------|--------|---------|------|------|
| 130 | Revenue YoY % | Python | (sales[−1] − sales[−5]) / abs(sales[−5]) × 100 | % | 2 |
| 131 | Profit YoY % | Python | (profit[−1] − profit[−5]) / abs(profit[−5]) × 100 | % | 2 |
| 132 | OPM Trend | Python | (opm[−1] − opm[−4]) / abs(opm[−4]) → >5% "expanding" / <-5% "contracting" / else "stable" | text | 2 |

---

## SECTION T — Agent Pre-Computations (signals.py)

| # | Metric | Source | Formula | Unit | Tier |
|---|--------|--------|---------|------|------|
| 133 | PEG Ratio | Python | PE / profit_cagr_3yr | x | 2 |
| 134 | PEG Verdict | Python | <1.0 "attractive" / <2.0 "fair" / ≥2.0 "expensive" | text | 2 |
| 135 | Owner Earnings (Cr) | Python | net_income + depreciation + capex − ΔWC | INR Cr | 3 |
| 136 | Owner Earnings per Share | Python | (owner_earnings_cr × 1e7) / shares_outstanding | INR/share | 3 |
| 137 | Owner Earnings Yield % | Python | (OE_per_share / current_price) × 100 | % | 3 |
| 138 | DSCR | Python | operating_cf[0] / interest_expense[0] | x | 2 |
| 139 | DSCR Verdict | Python | ≥3.0 "comfortable" / ≥1.5 "adequate" / ≥1.0 "tight" / <1.0 "distress" | text | 2 |
| 140 | WACC Proxy | Python | Fixed 12.0% (10yr Gsec 7.2% + equity risk premium 4.8%) | % | 1 |
| 141 | ROCE-WACC Spread | Python | roce_latest − wacc_proxy | % | 2 |
| 142 | Spread Verdict | Python | ≥5% "strong_value_creator" / ≥0% "marginal_value_creator" / <0% "value_destroyer" | text | 2 |
| 143 | 52w Position % | Python | (current_price − 52w_low) / (52w_high − 52w_low) × 100 | % | 2 |
| 144 | 52w Position Verdict | Python | ≥70% "near_52w_high" / ≥50% "upper_half" / ≥30% "lower_half" / <30% "near_52w_low" | text | 2 |

---

## SECTION U — Derived Scores (signals.py)

| # | Metric | Source | Formula | Unit | Tier |
|---|--------|--------|---------|------|------|
| 145 | Fundamentals Score | Python | base = round(piotroski × 10/9); +1 if ROCE>15%, −1 if ROCE<8%; +1 if quality_flag="high", −1 if "low"; clamp [1,10] | 1–10 | 1 |
| 146 | Valuation Score | Python | price_to_graham brackets → 9/7/5/3/1; ±1 PE modifier; clamp [1,10] | 1–10 | 1 |

---

## SECTION V — Bank / NBFC Signals (signals.py → _compute_bank_signals)

| # | Metric | Source | Formula | Unit | Tier |
|---|--------|--------|---------|------|------|
| 147 | Gross NPA % | Screener | wiki_ratios "Gross NPA" | % | 1 (banks) |
| 148 | Net NPA % | Screener | wiki_ratios "Net NPA" | % | 1 (banks) |
| 149 | CAR % | Screener | wiki_ratios "Capital Adequacy Ratio / CRAR" | % | 1 (banks) |
| 150 | NIM % | Screener | wiki_ratios "Net Interest Margin" | % | 1 (banks) |
| 151 | NPA Flag | Python | <2% "low" / 2–5% "medium" / >5% "high" | text | 1 (banks) |
| 152 | CAR vs RBI Minimum | Python | car_pct − 11.5 (RBI minimum) | % | 1 (banks) |
| 153 | Price to Book | Screener | key_ratios "Price to Book" | x | 2 (banks) |
| 154 | ROE Latest (banks) | Screener | key_ratios ROE | % | 2 (banks) |
| 155 | ROE Trend (banks) | Python | Slope of net_profit series | text | 3 (banks) |
| 156 | Deposit Growth % | Python | (deposits[0] − deposits[1]) / abs(deposits[1]) × 100 | % | 2 (banks) |
| 157 | NIM Trend | Python | Not yet implemented (placeholder) | text | 3 |

---

## Summary

| Category | Count | Source |
|----------|-------|--------|
| Header / Meta | 11 | Screener |
| Key Ratios | 13 | Screener |
| P&L (annual) | 10 | Screener |
| Growth Rates | 8 | Screener |
| Balance Sheet | 20 | Screener |
| Cash Flow | 8 | Screener |
| Ratios Table | 6 | Screener |
| Quarterly | 5 | Screener |
| Shareholding | 5 | Screener |
| Piotroski | 11 | Python |
| DuPont | 5 | Python |
| Earnings Quality | 3 | Python |
| Growth Quality | 2 | Python |
| Capital Efficiency | 5 | Python |
| Balance Sheet Health | 2 | Python |
| Valuation | 4 | Python |
| DCF | 6 | Python |
| Promoter Risk | 5 | Python / Screener |
| Quarterly Momentum | 3 | Python |
| Agent Pre-computations | 12 | Python |
| Derived Scores | 2 | Python |
| Bank Signals | 11 | Python / Screener |
| **TOTAL** | **157** | |
