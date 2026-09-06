# Markov Bot — Independent Grade on the A+ Rubric Harness

_grade_markov.py · same harness used to grade the IBKR trend-follower · 10y, vol-target, equal-weight, 365/yr_

> **⚠ CORRECTION — DO NOT DELETE (restored 2026-09-06 after a re-run overwrote it).**
> The MAR figures below are computed on the **ragged full window** (2017-10-03 onward),
> where in 2017–2020 the "portfolio" is really just BTC/NVDA — the other slots are
> 0-filled. That flatters every number here.
>
> The honest **common-history** figure recorded on 2026-06-07 was
> **equal-weight MAR 1.18 / Sortino 2.07** (4 slots, 2021-04-08 → 2026), materially below
> the ragged number and below the README's claimed 1.70. It also **retracted** an earlier
> "inverse-vol → MAR 1.75" nugget: on the common window inverse-vol *underperforms*
> equal-weight (0.79 vs 1.18).
>
> **As of 2026-09-06 that 1.18 figure CANNOT BE REPRODUCED** — it came from
> `Markov Bot/scripts/test_portfolio_weights.py`, which no longer exists. Treat 1.18 as
> a point-in-time record, not a verified current number, until a common-window harness
> is rebuilt.
>
> The **grade is A− either way**; the concentration gate fails on both windows.
> This block was lost once already because `grade_markov.py` rewrites this file wholesale.
> The script should append or write to a dated file instead.



Rubric A+ bar: MAR>=1.0 & Sortino>=1.5 (rf=2%) + no asset >35% P&L + strip-top-5 positive + rolling-12mo hit >=70% + survives 2x cost.

## 6-asset (README headline)

- Markov-native (rf=0, 365/yr): **MAR 1.59 / Sortino 2.36 / Sharpe 1.89 / CAGR 17.6% / MaxDD -11.0%**
- Rubric harness (rf=2%, 365/yr): MAR 1.59 / Sortino 2.07 / Sharpe 1.66
- Rolling-12mo hit 95% | max per-asset share 39% | strip-top-5-months+ True | 2x-cost MAR 1.41/Sortino 1.94
- **RUBRIC GRADE: A-** (one market = 39% of P&L)

## 4-asset (active fleet)

- Markov-native (rf=0, 365/yr): **MAR 1.75 / Sortino 2.45 / Sharpe 1.92 / CAGR 23.0% / MaxDD -13.2%**
- Rubric harness (rf=2%, 365/yr): MAR 1.75 / Sortino 2.22 / Sharpe 1.74
- Rolling-12mo hit 95% | max per-asset share 42% | strip-top-5-months+ True | 2x-cost MAR 1.63/Sortino 2.13
- **RUBRIC GRADE: A-** (one market = 42% of P&L)

## Honest caveats

- **Survivorship:** the 6-asset fleet was hand-picked from names already known to pass the gate (README + sweep.py admit 6/12 of the broader universe fail). The 4-asset active fleet is the cost-aware survivor set — still selected, so treat as 'best-of', not universe-wide.
- **Weekend 0-fill:** equities get 0 return on weekends while crypto trades, which lowers blended vol and can flatter Sortino. Standard for mixed crypto/equity books but worth stating.
- **Backtest, not live:** realized paper P&L is ~16 days and statistically meaningless. This grade is the backtest's, not proof of live edge. Stage-2 live gate (realized MAR>=0.5/Sortino>=1.0) is the real test.
