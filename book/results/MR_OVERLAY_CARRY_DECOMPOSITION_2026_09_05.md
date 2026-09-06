# DBMR Overlay on Markov — carry decomposition (re-run with durable artifact)

**Date:** 2026-09-05 · **Harness:** `mr_overlay_on_markov.py`, plus a 0%-carry variant
(`rf_annual=0.04` → `0.0`, line 46) to isolate the interest component.
**Why:** the original 2026-07-10 run printed to stdout and wrote no results file, so the
"~57% of the lift is T-bill carry" claim had no artifact behind it. This is that artifact.

## Window and correlation

- Common window **2023-03-29 → 2026-06-29 (815 days)**, capped by Markov's crypto slot history.
- **corr(Markov, DBMR) = +0.115** — unchanged from the original run. Structural, not a fluke.

## Baselines

| Book | MAR | Sortino | Sharpe | CAGR | MaxDD |
|---|--:|--:|--:|--:|--:|
| Markov (EQUAL-9) | 2.27 | 1.86 | 1.45 | 14.2% | −6.3% |
| DBMR standalone **@ 4% carry** | 3.56 | 1.72 | 1.97 | 6.1% | −1.7% |
| DBMR standalone **@ 0% carry** | 1.24 | **0.16** | 0.15 | 2.3% | −1.9% |

The carry alone moves DBMR from Sortino **0.16 → 1.72**. The strategy sits ~90% in cash;
at 4% that idle balance is most of the return.

## Additive overlay (Markov 100% + DBMR on idle cash)

| Overlay | MAR @4% carry | MAR @0% carry |
|---|--:|--:|
| none | 2.27 | 2.27 |
| +0.25× | 2.65 | 2.44 |
| **+0.50×** | **3.05** | **2.62** |
| +1.00× | 3.84 | 2.99 |

## Decomposition at +0.50×

- Total lift: 2.27 → 3.05 = **+0.78 MAR**
- Alpha-only lift (0% carry): 2.27 → 2.62 = **+0.35 MAR**
- Carry portion: 0.78 − 0.35 = **+0.43 MAR**
- **Carry share of the lift = 55%**

## Verdict

The original **~57%** claim is **confirmed at 55%** on a re-run with a fully isolated
carry component. The conclusion is unchanged and now has an artifact: **park idle cash in
a short-term Treasury fund**; that captures the majority of the measured benefit with no
strategy, no code, and no execution risk. The residual DBMR alpha (+0.35 MAR) is real but
is the smaller half, and standalone the strategy is a Sortino-0.16 book once you stop
counting interest as skill.

*Note: in the 0%-carry run the printed row label still reads "DBMR book (4% carry)" — that
string is hardcoded in the print statement and was not changed by the parameter override.
The data in that row is the 0%-carry result.*

Raw output: `mr_overlay_rerun.txt` (4% carry), `mr_overlay_zerocarry.txt` (0% carry).
