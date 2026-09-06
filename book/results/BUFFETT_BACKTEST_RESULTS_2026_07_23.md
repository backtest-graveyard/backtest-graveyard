# Buffett Bot — First Point-in-Time Backtest

**Date:** 2026-07-23 · **Harness:** `buffett_bot/backtest.py`
**Verdict in one line:** clears the KPI bar on the headline number, **fails the
robustness kill-test on MAR**, and carries a *concrete, named* survivorship
artifact — so: **not validated, not disproven.**

---

## 1. Setup

| | |
|---|---|
| Window | 2015-01-02 → 2025-01-02 (10 rebalances, annual) |
| Universe | today's S&P 500 (503 names) — **survivorship-biased** |
| Portfolio | top-15 by final score among gate-passers, equal weight |
| Fundamentals | SEC EDGAR, **point-in-time** (only filings dated ≤ rebalance date) |
| Prices | raw close for valuation ratios, adjusted close for returns |
| Costs | 10 bps charged on turnover each rebalance |

## 2. Headline result

```
STRATEGY   CAGR 21.44% | MaxDD -35.15% | MAR 0.61 | Sortino 1.31 | total +595.6%
SPY        CAGR 13.00% | MaxDD -33.72% | MAR 0.39 | Sortino 0.95 | total +238.7%
DROP-TOP5  CAGR 17.66% | MaxDD -37.42% | MAR 0.47 | Sortino 1.14 | total +407.0%
```

KPI bar (MAR ≥ 0.5 **and** Sortino ≥ 1.0): **PASS** on the headline.
Kill-test (best 5 names removed): **MAR 0.47 → FAILS the bar.**

## 3. Look-ahead audit — CLEAN

The point-in-time gate was audited directly: across 25 companies at two as-of
dates, **804,046 facts** were admitted and **0** had a filed date after the as-of
date. Spot-check confirms the mechanism bites — AAPL net income reads $48.4B as
of 2018 (FY2017), $94.7B as of 2022 (FY2021), $112.0B live. Restated figures do
not leak backwards.

## 4. Breadth — better than prior failures, still concentration-sensitive

```
names held: 56 | net-positive: 42 (75%)
top-5 share of gross positive P&L: 39%
top contributors: NVDA +32%, COIN +24%, LRCX +17%, AVGO +16%, AAPL +15%,
                  META +12%, TSCO +11%, GOOGL +9%
worst: INTC -3%, NUE -2%, GILD -2%, MOS -2%, QCOM -2%
```

Context against this project's prior rejects:

| | top-N share of P&L | net-positive names | drop-top-5 outcome |
|---|---|---|---|
| Gap trader | top-3 = **92%** | — | lottery, rejected |
| Stat-arb PCA | top-5 = 27% | 55/96 (57%) | Sortino 1.53 → **−0.51** (sign flip) |
| **Buffett bot** | top-5 = **39%** | 42/56 (**75%**) | MAR 0.61 → 0.47 (**degrades, survives**) |

This is **not** a gap-trader-style lottery. 75% of held names were net-positive
and removing the five best still leaves +17.66% CAGR, beating SPY. But it does
lean on its winners enough to drop below the MAR bar — real, not robust.

## 5. The survivorship artifact, made concrete

**COIN is the #2 contributor at +24%** — and Coinbase did not join the S&P 500
until **2025**, four years after its 2021 listing. The backtest let a 2021–2024
screener pick a name that was not in its universe at the time. That is the
index-membership half of survivorship bias, caught red-handed in a single row.
NVDA / AVGO / META push the same direction more subtly: today's index is a list
of things that *won*.

The point-in-time *fundamentals* problem is solved. The point-in-time *universe*
problem is not, and it flatters every number above.

## 5b. Re-run with the $0 survivorship mitigation (5-year filing history)

Requiring 5 years of filing history at each rebalance excludes recent listings.
It worked mechanically — **COIN disappears from the contributor list entirely** —
and the edge shrank with it:

| | CAGR | MaxDD | MAR | Sortino |
|---|---|---|---|---|
| Unfiltered | 21.44% | −35.15% | 0.61 | 1.31 |
| **5y-history filter** | **18.77%** | **−37.25%** | **0.50** | **1.15** |
| 5y filter, drop-top-5 | 15.71% | −36.34% | **0.43** | 1.05 |
| SPY | 13.00% | −33.72% | 0.39 | 0.95 |

Breadth after filtering: 60 names held, 44 net-positive (73%), top-5 = 37% of
gross positive P&L. Top contributors: NVDA +32%, LRCX +17%, AAPL +15%, WSM +12%,
META +12%.

**Removing one artifact — recent IPOs — cost 2.7pp of CAGR and 0.11 of MAR, and
parked the strategy at exactly 0.50, the bar itself.** The kill-test still fails
(MAR 0.43). And the *remaining* bias (established companies added to the index
mid-window) is still present and still points the same direction: down.

## 5c. Re-run after business-model-aware gates + financials valuation (2026-08-10)

Two model corrections shipped after the original run: gates that skip
structurally-inapplicable tests (current ratio for a bank, FCF for a bank), and
a justified price-to-book model so balance-sheet financials are valuable at all
(previously 76 names — 15% of the universe — could never be selected).

| | CAGR | MaxDD | MAR | Sortino | drop-top-5 MAR |
|---|---|---|---|---|---|
| 5y-history filter (2026-07-23) | 18.77% | −37.25% | 0.50 | 1.15 | 0.43 |
| **+ gates & financials (2026-08-10)** | **18.74%** | **−36.29%** | **0.52** | **1.16** | **0.44** |
| SPY | 13.00% | −33.72% | 0.39 | 0.95 | — |

**The corrections changed almost nothing.** MAR 0.50 → 0.52, Sortino 1.15 → 1.16,
CAGR flat. Breadth essentially unchanged (58 names held, 72% net-positive, top-5
= 39% of gross positive P&L). The kill-test still fails at MAR 0.44.

Why so little effect: no financial appears among the top contributors (NVDA +32%,
LRCX +17%, WSM +15%, AAPL +15%, META +12%). Making 15% of the universe valuable
closed a real correctness gap in the **live screen**, but historically those names
rarely scored into the top 15, so measured performance barely moved.

**Verdict unchanged: not validated.** Passes the headline bar, fails the
robustness kill-test, survivorship still unfixed. The corrections made the tool
*more correct*, not the strategy *more profitable* — worth doing on its own terms,
but it does not change the capital decision.

## 6. Honest verdict

- **Not validated.** The headline pass is on a biased universe and dies on the
  kill-test's MAR leg.
- **Not disproven either.** Breadth is genuinely decent, the stressed version
  still beats SPY, and Sortino stays above 1.0 even after removing the winners.
- **Low statistical power regardless** — 10 annual rebalances is a handful of
  independent observations. Neither a pass nor a fail would be strong evidence.
- The sell discipline (`monitor.py`) is **not** simulated; positions are held to
  the next rebalance.

## 7. What would actually settle it

1. **Point-in-time index membership + delisted names** (Sharadar / Norgate,
   ~$50–70/mo). This is the binding constraint. Until then every result is an
   upper bound.
2. **Cheap partial mitigation first:** require N years of filing history at the
   as-of date to exclude recent IPOs like COIN. Doesn't fix membership, removes
   the worst offenders, costs $0. Worth running before spending money.
3. Longer window + quarterly rebalance for more observations.
4. Simulate the actual sell rules instead of hold-to-rebalance.

**Recommendation (updated after §5b):** the $0 mitigation has been run. It cost
2.7pp of CAGR and left the strategy sitting **exactly on** the MAR bar (0.50),
still failing the kill-test (0.43), with more upward bias still in the universe.

The trend across every honest correction is monotone downward:

```
raw + dual-class bug   MAR 0.70
dual-class fixed       MAR 0.61
+ recent-IPO filter    MAR 0.50   <- the bar
+ drop best 5 names    MAR 0.43
(index membership still unfixed — points the same way)
```

Each time we removed a source of flattery, the edge shrank. Nothing so far has
made it *more* robust. That is the signature of an artifact, not an edge.

**Call: treat as NOT VALIDATED — do not allocate capital.** Buying survivorship-
safe data (~$50–70/mo) is the only way to settle it, but the expected outcome is
confirmation that it falls below the bar, so the spend is hard to justify on
these numbers. Keep the bot as what it demonstrably is: a **discovery and
monitoring tool** that surfaces fundamentally sound, reasonably priced companies
for human review — which is exactly how it's deployed (weekly email, no orders).
