# Cross-Sectional Momentum — video strategy #4 vs the fleet bar

Window 2010-01-01 → 2026-06-30. Universe: 29 liquid names (broad indices, SPDR sectors, commodities, rates/credit, mega-cap singles, BTC/ETH ragged).
Standard 12-1 / 6-1 momentum, monthly rebalance, tercile legs, eq-weight, fixed gross. Params NOT tuned to this data. Grader: trend_analytics (fleet MAR/Sortino).

Bar = **MAR ≥ 0.5 AND Sortino ≥ 1.0**, top-5 stripped still positive, survives 2× cost.

| Config | MAR | Sortino | Sharpe | CAGR | MaxDD | 2×MAR | Verdict |
|---|---|---|---|---|---|---|---|
| 12-1 L/S  (long/short tercile, dollar-neutral) | 0.12 | 0.39 | 0.30 | 6.3% | -51.5% | 0.12 | FAIL |
| 6-1  L/S  (long/short tercile, dollar-neutral) | 0.32 | 0.75 | 0.52 | 11.1% | -34.6% | 0.31 | FAIL |
| 12-1 Long-only tercile (the variant YOU could run) | 0.55 | 1.13 | 0.97 | 37.9% | -69.2% | 0.55 | PASS |
| 6-1  Long-only tercile | 0.58 | 1.19 | 0.99 | 39.9% | -68.3% | 0.58 | PASS |

**Strongest config:** 6-1  Long-only tercile — strip-top-5-months MAR 0.44 / total +6413.0% (positive); top-5 names = 42% of gross P&L.

---

## Verdict: REJECTED — the two "passes" fail on their own terms

**1. The video's actual strategy (long/short, "long strongest, short weakest") FAILS clearly.** Both L/S configs: MAR 0.12 / 0.32, Sortino 0.39 / 0.75. The short leg is a persistent drag — shorting the weakest names in a 15-year mostly-up tape bleeds. This is the construction the video pitches at 13:44, and it does not clear the bar. (It also can't be run in your paper accounts, which don't model shorting.)

**2. The long-only "passes" violate the video's OWN drawdown filter.** MaxDD −68% to −69%. The video's funnel throws out anything with drawdown > 35% (03:33). These "passing" configs would be *cut by the video's own test* — they are exactly the fragile, high-drawdown momentum the video's bootstrap warned about (08:54, dual-momentum-on-NVDA −61%, "would have cut your account in half"). For reference, every live/shipped fleet book runs MaxDD in the single digits to ~−11%. A −68% drawdown is a non-starter regardless of the MAR arithmetic.

**3. Strip-top-5-months knocks it below the bar.** 6-1 long-only strip test → **MAR 0.44 / Sortino 0.97** — both under the line. The nominal pass leans on a handful of months.

**4. It's redundant crypto/mega-cap beta, not a new edge.** Top-5 names = 42% of gross P&L, led by **BTC +83%, NVDA +80%, AMZN +46%, AAPL +45%, ETH +39%.** Remove crypto and *every* config fails:

| Config (no crypto, 27 names) | MAR | Sortino | CAGR | MaxDD | Verdict |
|---|---|---|---|---|---|
| 12-1 L/S | 0.10 | 0.27 | 4.2% | −42.3% | FAIL |
| 6-1 L/S | 0.27 | 0.61 | 8.6% | −32.2% | FAIL |
| 12-1 Long-only | 0.46 | 1.01 | 31.4% | −68.3% | FAIL |
| 6-1 Long-only | 0.49 | 1.06 | 33.3% | −68.3% | FAIL |

The entire "pass" was the crypto+megacap-tech ride — the **same beta Markov already harvests** (BTC/SOL/NVDA/AAPL), but here with a −68% drawdown and no vol-targeting or regime gate to control it. Cross-sectional momentum adds nothing Markov doesn't already own, and adds it worse.

**Disposition:** the one genuinely untested idea from the video is now tested and rejected. The video's own two guardrails (35% max-drawdown filter, bootstrap-fragility check) independently kill it. No fleet slot warranted. Harness kept: `xsmom_backtest.py`.
