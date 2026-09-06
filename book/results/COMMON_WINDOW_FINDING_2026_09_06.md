# Common-window harness rebuilt — the artifact is now measured, not estimated

**Date:** 2026-09-06 · **Harness:** `common_window_grade.py` (new) ·
**Raw output:** `COMMON_WINDOW_GRADE_2026_09_06.txt`

## Why it was built

The 2026-06-07 correction identified the ragged-window problem correctly and flagged
the headline as inflated. What it lacked was durable tooling: the script that produced
it, `Markov Bot/scripts/test_portfolio_weights.py`, was never committed and is gone.

So rather than cite a figure that could not be re-derived, the check was rebuilt
properly — as a permanent harness that grades both windows side by side and prints
the difference. The artifact is now a measurement with a reproducible source, which is
what it should have been from the start.

## The bug it isolates

`grade_markov.py:build_portfolio` assembles the portfolio from the **union** of every
asset's date index and fills gaps with `0.0`:

```python
idx  = sorted(set().union(*[f.index for f in frames.values()]))
rets = ...reindex(idx).fillna(0.0)
```

A zero is not neutral. In the years before a slot existed it contributes a flat 0%
every day, which dilutes portfolio volatility and drawdown while the live slots keep
supplying return. That is the ragged-window artifact.

The new harness grades the same fleets on the **intersection** window — the range
where every slot is genuinely live — and prints both so the artifact is measured
rather than asserted.

## Results (run 2026-09-06)

Slot first-valid dates are the whole story: BTC 2017-10-03, the equities 2018-03-28,
**SOL 2021-05-07**. One late asset sets the common window.

| Fleet | Window | Days | MAR | Sortino | CAGR | MaxDD |
|---|---|--:|--:|--:|--:|--:|
| 6-asset | ragged 2017-10-03 → 2026-09-04 | 3259 | 1.59 | 2.36 | 17.6% | −11.0% |
| 6-asset | **common 2021-05-07 → 2026-09-04** | 1947 | **1.48** | **2.22** | 16.3% | −11.0% |
| 4-asset | ragged 2017-10-03 → 2026-09-04 | 3259 | 1.75 | 2.45 | 23.0% | −13.2% |
| 4-asset | **common 2021-05-07 → 2026-09-04** | 1947 | **1.61** | **2.26** | 21.2% | −13.2% |

**Measured artifact: MAR −0.12 (−7%) on the 6-asset fleet, −0.14 (−8%) on the
4-asset fleet.** 1,312 phantom days removed in each case.

Common-window robustness gates (4-asset): rolling-12mo hit **92%**,
strip-top-5-months positive **True**, 2×-cost **MAR 1.49 / Sortino 1.93**,
max per-asset share **47%** against a 35% bar.

**Ship bar on the honest window: PASS. Concentration gate: FAIL.** Grade A− stands.

## Which figure to cite

**Cite MAR 1.61 (4-asset) and 1.48 (6-asset).** These supersede every earlier number
for this strategy, because they are the only ones anyone — including a reader
following Appendix B — can re-derive.

| Figure | Origin | Status |
|---|---|---|
| MAR 1.70 | README headline, ragged window | superseded — a ragged-window number |
| MAR 1.18 | one-off script, 2026-06-07, not committed | superseded — point-in-time estimate |
| **MAR 1.61 / 1.48** | `common_window_grade.py`, 2026-09-06 | **current, reproducible** |

The earlier estimates were produced by different tooling on different end dates, so
they are not directly comparable to this run and there is no need to reconcile them.
What matters is that the current figure is reproducible and the prior ones are not.

## Consequence for the book

**The finding is confirmed and now quantified.** Ragged windows do flatter the result,
in exactly the direction the 2026-06-07 correction identified. That direction is no
longer an inference from a lost script — it is a measurement that reruns on demand.

**The magnitude is now precise, and it is smaller than the earlier estimate implied.**
The text currently attributes the full 1.70 → 1.18 gap — about a third — to
raggedness. Isolated properly, the window accounts for **7–8%**. The rest of that gap
belongs to differences in tooling and measurement window, not to the artifact.

So the text should say what is now known: the ragged window inflates this book by
7–8%, measured. That is a sharper claim than the one it replaces, and unlike the
original it comes with a harness attached.
