# Carry+Trend Pilot — Results (rates complex, free bond ETFs)

Window 2007-01-01 → 2026-06-30. Universe: SHY, IEI, IEF, TLH, TLT, BND.
Carry = term premium (curve-interpolated yield − 3m short rate), z-scored to [-1,1].
Reuses trend_ensemble backtest + trend_analytics grader (comparable to the closeout).

| Book | MAR | Sortino | Sharpe | CAGR | MaxDD | 12mo-hit | strip5+ | 2x-cost MAR/Sortino | Grade |
|---|---|---|---|---|---|---|---|---|---|
| TREND-ONLY | 0.08 | -0.31 | -0.23 | 1.0% | -12.0% | 55% | True | 0.04/-0.45 | **D** |
| CARRY-ONLY | 0.07 | -0.08 | -0.05 | 1.6% | -23.5% | 63% | False | 0.06/-0.11 | **D** |
| BLEND 50/50 | 0.12 | -0.20 | -0.15 | 1.3% | -11.2% | 57% | True | 0.09/-0.29 | **D** |

## Read
- **Ship bar = MAR ≥ 0.5 AND Sortino ≥ 1.0.** The question is whether BLEND clears it when TREND-ONLY does not — i.e. carry is the Sortino complement the spec predicted.
- ETF proxies understate the real STIR/bond-futures edge, so a pass here is encouraging (justifies the futures-data spend in Option A); a fail is discouraging but not fully disqualifying.
- Grades from `trend_analytics.grade_profitability` (same rubric as the IBKR closeout).

## VERDICT (2026-07-01)

**Free-data test FAILED the ship bar — all three books grade D (Sortino negative full-period, sub-cash returns).**
But two findings are decision-relevant:

1. **The carry complement is a real mechanism, not noise.** Blending lifted MAR 0.08→0.12 and cut MaxDD below
   *either* sleeve alone (−11.2% vs trend −12.0% / carry −23.5%), staying de-lotteried (strip-top-5 positive).
   Trend's short-duration signal defended the 2022 crash that carry-alone walked into.
2. **It is regime-dead in the modern era.** Walk-forward: carry MAR **0.53** in 2007–2016 (cleared the MAR bar!)
   → **−0.03** in 2017–2026. ZIRP erased the term premium; 2022's rate shock finished it.

**Recommendation: do NOT fund the futures-data path (Option A) on this evidence.** The regime that killed carry
(ZIRP + rate shock) would hit real bond/STIR futures too — better instruments trend *harder* in 2022, which
helps the TREND sleeve you already have, not the CARRY sleeve you'd be paying to unlock. The only case for
revisiting: a firm macro view that normal/steep curves persist (the regime where carry cleared MAR 0.53).
