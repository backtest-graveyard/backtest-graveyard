# Findings — Regime-Window Ensemble for the Markov Label

**Date:** 2026-07-08
**Spec:** `REGIME_ENSEMBLE_TEST_SPEC_2026_07_08.md`
**Harness:** `scripts/regime_ensemble_test.py` (live `fleet.json`, 9 slots, vol-adaptive k=0.5, vol_target sizing, honest 15/8 bps, 5y). Label swap only; common evaluation window 2023-03-28 → 2026-07-07 (821 days).
**Result:** **REJECTED. Keep the single 20-day window.** The best ensembles improve the full-window number modestly but **lose on the OOS-12mo window**, and the improvement is **not robust** across window sets. No config change.

---

## Numbers (matched-exposure MAR; Sortino leverage-invariant)

| Variant | avg grs | turn | Full ROI | Full MAR | Full Sortino | MaxDD | 12mo MAR | 12mo Sortino | top-5% |
|---|---|---|---|---|---|---|---|---|---|
| **incumbent {20}** | 0.36 | 8.9% | +55.5% | 2.31 | 2.17 | −6.2% | **3.09** | **2.18** | 21% |
| ens-A {10,20,40} | 0.34 | 8.9% | +58.1% | 2.47 | 2.23 | −6.1% | 2.91 | 2.00 | 22% |
| ens-B {10,20,40,60} | 0.41 | 8.5% | +53.2% | 2.51 | 2.27 | **−5.5%** | 2.96 | 2.06 | 22% |
| ens-C {5,20,60} | 0.31 | 11.2% | +39.4% | 1.26 | 1.59 | −8.5% | 2.27 | 1.75 | 28% |
| ens-D {15,20,30} | 0.35 | 8.4% | +50.6% | 2.01 | 1.95 | −6.6% | 2.19 | 1.60 | 24% |

**Per-year ROI (matched exposure):**

| Year | incum | ens-A | ens-B | ens-C | ens-D |
|---|---|---|---|---|---|
| 2023 | +9.1% | +12.5% | +14.4% | +8.4% | +11.5% |
| 2024 | +9.1% | +12.9% | +11.6% | +6.1% | +10.9% |
| 2025 | **+18.1%** | +14.7% | +10.2% | +16.6% | +11.7% |
| 2026 | **+10.6%** | +8.6% | +8.9% | +3.9% | +9.1% |

## Decision against the spec's six criteria

1. **Sortino ≥ incumbent, full AND 12mo** — ❌ FAIL. ens-A/B beat full-window Sortino (2.23/2.27 vs 2.17) but **lose 12mo Sortino** (2.00/2.06 vs 2.18). Every variant is worse on the recent window.
2. **Matched-MAR ≥ incumbent, full AND 12mo** — ❌ FAIL. ens-A/B win full MAR (2.47/2.51 vs 2.31) but **lose 12mo MAR** (2.91/2.96 vs 3.09). Same reversal.
3. **≥3 of 4 sets beat incumbent on Sortino (robustness)** — ❌ FAIL. Only 2 of 4 (ens-A, ens-B) beat even on the *full* window; on 12mo, **0 of 4**. The "win" is window-set-dependent — exactly the cherry-pick the criterion guards against.
4. **Turnover not materially higher** — ✅ mostly (ens-A/B flat-to-lower; ens-C worse at 11.2%).
5. **Concentration not higher** — ✅ ens-A/B flat (~22%); ens-C/D worse (28/24%).
6. **No badly degraded year** — ❌ ens-A/B give up 2025–2026 (the recent, most-relevant period).

Requires ALL. Fails 1, 2, 3, 6. **Reject.**

## Why (the mechanism)

- **The improvement is in the past, the degradation is recent.** ens-A/B beat the incumbent in 2023–2024 and lose in 2025–2026. A lever that helps on older data and hurts on newer data is the textbook out-of-sample-decay signature — adopting it would be fitting the label to a regime that's already gone. This is *the* reason to reject.
- **Short windows whipsaw (H0 confirmed).** ens-C, which includes w=5, is markedly worst (MAR 1.26, Sortino 1.59, turnover 11.2%, concentration 28%) — the fast window flips regime too often, adding cost and false signals.
- **Tight clustering adds nothing.** ens-D {15,20,30} is worse than the single 20 — windows near 20 are near-collinear, so "blending" them just averages noise.
- **The wider ensemble does smooth drawdowns** — ens-B has the lowest MaxDD (−5.5%) and slightly lower turnover — but not enough to clear the bar, and it pays for the smoothness in recent-year upside. Consistent with the vol-adaptive finding ("smoother, worse in strong-trend years").

## Interpretation

The single 20-day vol-adaptive window is **already near-optimal** for this book. The vol-adaptive change (2026-06-11) had already de-fragilized the *scale* knob; window-diversification is the residual, and this test shows the residual is ~zero-to-negative out-of-sample. The regime label is not where remaining edge lives.

Lands on the "no" side of the pre-registered ~35% prior. This exhausts the Phase-3 signal levers named in `PROFITABILITY_A_PLUS_PLAN.md`: **conviction dead-band** (rejected, commit f8b44f7), **Kelly sizing** (rejected, `KELLY_SIZING_FINDINGS_2026_07_08.md`), and now **regime-window ensemble** (rejected). The plan's conclusion stands: the backtest is at its honest ceiling; real improvement is **realized confirmation + execution fidelity + IBKR cost/access**, not signal engineering.

**No live/paper config touched.** `fleet.json` and `markov_bot.label_regimes` unchanged. New code (`label_ensemble` + `windows=`/`consensus=` params on `strat_returns`, `scripts/regime_ensemble_test.py`) is additive and dormant unless invoked.
