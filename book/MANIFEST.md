# Manifest — chapter → source

Every figure in the book traces to a file below. Chapter numbers are the book's final
numbering (1–24). Where a harness is marked in parentheses the runner is not yet
extracted into this repo; the result file carries the parameters it was run with.

| Chapter(s) | What | Result file | Harness |
|---|---|---|---|
| 4, 11, 24 | Gap trader — headline MAR 1.56, top-3 = 92% | `results/FULL_UNIVERSE_VERDICT_2026_06_03.md` | `harness/backtester.py` |
| 7, 11 | Gap trader — parity re-audit, 42% screen miss, MAR 97 bug | `results/PARITY_REAUDIT_TRACK1_RESULTS_2026_06_03.md` | `harness/backtester.py` |
| 3, 4, 15 | Pairs trading / PCA residual book — fail→pass→fail | `results/STATARB_POSTMORTEM_2026_07_19.md` | `harness/statarb/` |
| 4, 5, 19 | Value screener — 0.61→0.47, COIN artifact | `results/BUFFETT_BACKTEST_RESULTS_2026_07_23.md` | `harness/buffett_bot/` |
| 4, 16 | Cross-sectional momentum — incl. crypto-removal sweep | `results/XSMOM_RESULTS.md` | `harness/xsmom_backtest.py` |
| 10, 22 | Kronos vs EWMA vs incumbent — QLIKE table | `results/KRONOS_FOUNDATION_MODEL_EVAL_2026_07_09.md` | `harness/(vol harness)` |
| 9 | VIX cheat sheet — SPY and QQQ variants, 2000–2025 | `results/ASKLIVERMORE_VIX_CHEATSHEET_EVAL_2026_07_09.md` | `harness/(vix harness)` |
| 3, 13 | Volume/red-green reversals — cost curve + strip ladder | `results/VOLUME_REVERSAL_PROBE_RESULTS.md` | `harness/volume_reversal_probe.py` |
| 21 | Equities MR dip-buy — standalone rejection | `results/MR_DIPBUY_RESULTS.md` | `harness/(mr harness)` |
| 21 | Rates carry + trend pilot | `results/RATES_CARRY_PILOT_RESULTS.md` | `harness/(rates harness)` |
| 4, 5, 12 | Overnight / earnings-night premium | `results/OVERNIGHT_EFFECT_EARNINGS_NIGHT_RESULTS_2026_08_23.md` | `harness/(overnight harness)` |
| 4, 14 | MACD + RVOL — 22-day sweep | `results/SDOT_MULTIDAY_SWEEP_2026_06_26.md` | `harness/(sdot harness)` |
| 17 | HMM regime paper — evidence review | `results/HMM_REGIME_FACTOR_PAPER_EVAL_2026_07_20.md` | `harness/(not built)` |
| 18 | GEX / dealer gamma — mechanics review | `results/GEX_DEALER_HEDGING_STRATEGY_EVAL_2026_07_08.md` | `harness/(not built)` |
| 8 | RenTec 51% — mechanics audit | `results/RENTEC_51PCT_MATH_STRATEGY_EVAL_2026_07_08.md` | `harness/(no backtest)` |
| 2, 20 | Fractional Kelly vs vol-target, matched exposure | `results/KELLY_SIZING_FINDINGS_2026_07_08.md` | `harness/(markov scripts)` |
| 6, 20 | Regime-window ensemble — OOS decay | `results/REGIME_ENSEMBLE_FINDINGS_2026_07_08.md` | `harness/(markov scripts)` |
| 2, 22 | Survivor grade + ragged-window correction | `results/MARKOV_GRADE_RESULTS.md / grade_rerun.txt` | `harness/grade_markov.py` |
| 21 | Overlay carry decomposition (4% vs 0% carry) | `results/MR_OVERLAY_CARRY_DECOMPOSITION_2026_09_05.md` | `harness/mr_overlay_on_markov.py` |
| 22 | DCA + dip-buy accumulation | `results/VTI_DCA_DIP_BACKTEST.md / QQQM_EMA_TRAIL_BACKTEST.md` | `harness/(accumulator harness)` |

## Verification

The book ships with `crosscheck.py`, which verifies that every figure in the
manuscript still matches the result file it cites and that no superseded number
survived a revision. It has caught real errors, including four introduced by a single
corrected figure rippling through chapters that referenced it.
