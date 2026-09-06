# QQQM — "buy below EMA200, exit on armed 2% trailing stop" backtest

**Date:** 2026-06-18
**Strategy version under test:** single entry per cycle, long-only, fully invested.
**Code:** [backtest_ema_trail.py](backtest_ema_trail.py) (EMA200 plumbing reused from [etf_accumulator.py](etf_accumulator.py)).

## Rule tested (exactly as specified)
- **Entry:** while flat, buy at the daily close when close < EMA200 (the shaded zone).
- **Arm:** once long, arm a trailing stop the first day close ≥ EMA200 × 1.02.
- **Exit:** after armed, track the running peak; sell at the close when price ≤ peak × 0.98
  (2% pullback from the post-recovery high). Then go flat, wait for the next close below EMA200.

## Data
Alpaca daily bars, split-adjusted, free IEX feed. **IEX history only reaches mid-2020**, so the
usable window is ~5 years. It does contain a full cycle: 2022 bear → 2023–24 recovery → 2025.
Backtested both QQQM (actual) and QQQ (same Nasdaq-100 index, used as the longer-history twin) —
results are nearly identical.

## Results (window 2021–2026)

| Metric | Strategy (QQQM) | Buy & hold (QQQM) | Strategy (QQQ) | Buy & hold (QQQ) |
|---|---|---|---|---|
| Total return | **+35.9%** | +106.9% | +35.0% | +127.3% |
| CAGR | 6.75% | 16.73% | 6.07% | 17.50% |
| Max drawdown | −28.0% | −35.6% | −28.2% | −35.6% |
| **MAR (CAGR/MaxDD)** | **0.24** | 0.47 | 0.22 | 0.49 |
| **Sortino** | **0.66** | 1.20 | 0.63 | 1.14 |
| Time in market | 37% | 100% | 34% | 100% |
| Profit factor | 3.52 | — | 3.46 | — |
| Win rate | 83% (5/6) | — | 83% | — |
| Avg hold | 105 d | — | 105 d | — |

**KPI bar (MAR ≥ 0.50 AND Sortino ≥ 1.00): FAILED.**
**Beats buy & hold: NO** (loses on both absolute return and risk-adjusted return).

## Why it fails (structural, not a parameter-tuning miss)
1. **It's out of the market ~65% of the time.** Entry only fires when price is *below* EMA200,
   which on a secular-uptrend index is the minority of days. The strategy sits in cash through the
   strongest trend legs (when price rides *above* the EMA) — exactly when buy & hold compounds.
2. **The 83% win rate / 3.5 profit factor are a mirage.** Lots of small green round-trips, but the
   absolute capital captured is small because the position is flat during the big up-moves.
3. **One trade poisons the curve:** the 2022-04 entry held **306 days at −14%** — it bought into the
   bear, then had to wait ~10 months for a recovery to EMA200+2% before the trailing stop could even
   arm. A dip-buyer with no stop-loss on the *entry* side carries open-ended downside during bears.

This is the fundamental tension: **a below-EMA200 dip-buyer is a mean-reversion bet, and the
Nasdaq-100 trends rather than mean-reverts.** No 2%-vs-3% trailing tweak fixes being absent for the
trend. Matches the project's prior findings (SMH dip overlay ≈ 0% edge; EMA200 flip rejected).

## Verdict
Do **not** deploy this rule as specified on QQQM. For Nasdaq-100 exposure, buy & hold (or the
existing never-sell accumulator) is strictly better on this window.
