# RSI-2 "It Calls The Bottom" — Kill-Test (Backtest Graveyard source)

**Date:** 2026-09-16 · **Channel:** The Backtest Graveyard · **Episode:** Ep14
**Question:** the viral retail belief — *"the 2-period RSI (Larry Connors' RSI-2) calls the bottom of a selloff. When a stock is deeply oversold on the 2-day RSI, buy it, and sell a few days later when it bounces."* Does it?
**Data:** daily, **split-adjusted** closes for **55 of the most liquid US large-caps** (S&P 100 core) + **SPY**, from **Alpaca's free IEX feed**, window **2020-08-03 → 2026-09-16** (1,538 trading days, ~6.1 yrs). Code: `backtest_rsi2.py` (stdlib + numpy/pandas/requests, no secrets, PII-clean, re-runnable).
**Data caveat (read this):** the free IEX feed only reaches ~mid-2020, so this window is **mostly a bull market** and **excludes 2008, 2018, and the Feb–Mar 2020 COVID crash** — the exact V-bottoms the myth loves. It *does* contain the entire 2022 bear market, which turns out to be the most important test (see KT4). A window this bull-heavy is, if anything, the **friendliest** possible sample for a "buy the dip" system; the strategy still can't beat holding.
**Strategy (Connors' canonical RSI-2, implemented faithfully):** long-only; buy only when close > 200-day SMA ("dips in an uptrend"); **entry** when RSI(2) closes below an oversold threshold; **exit** when RSI(2) closes back above 70 (or the "close > 5-day SMA" exit Connors also used); **max-hold 10 trading days** as the only backstop — Connors' classic system carries **no stop-loss**, and that omission is the whole point of the win-rate mirage. Equal-dollar slices, up to 10 parallel names, most-oversold filled first. Realistic costs (5 bps one-way = 10 bps round trip) applied on entry and exit. Idle cash earns 0%.
**Method:** decided and filled on the daily close, ranked by **MAR = CAGR / MaxDD%** — the channel standard. Bar to pass: **MAR ≥ 0.50 AND Sortino ≥ 1.00.**

## Headline

**RSI-2 bounces are real — and they lose to doing nothing.** In its popular "RSI(2) < 10" form the strategy technically *clears* the channel's risk bar (MAR 0.59, Sortino 1.22). But it returned **+92%** over the window while simply **equal-weight holding the same 55 stocks returned +178%** — at a *better* MAR (0.69) and Sortino (1.48). It wins **66.8%** of its trades, yet its **average loss is 1.4× its average win.** Half its profit comes from **5 names.** It drops below the bar the moment you **double its (already tiny) costs.** And in the one real selloff in the sample — 2022 — it **lost money.** The bounce exists. The edge doesn't.

## Results (ranked by MAR — the channel standard, not raw return)

| Rank | Strategy | Total Ret | CAGR | **MAR** | Sortino | Max DD | Win Rate | PF | Trades | Bar |
|--:|---|--:|--:|--:|--:|--:|--:|--:|--:|:--:|
| 1 | RSI-2 **tuned** (entry <5, exit >70, 5-day hold) | ~+64% | 8.4% | **0.89** | 1.24 | −9.4% | 62.3% | — | 992 | **PASS** |
| 2 | **Buy&Hold EW-universe (the yardstick)** | **+177.7%** | **18.2%** | **0.69** | 1.48 | −26.4% | — | — | — | **PASS** |
| 3 | RSI-2 **base** (entry <10, exit >70, 10-day hold) | +92.2% | 11.3% | **0.59** | 1.22 | −19.2% | 66.8% | 1.44 | 1,452 | **PASS** |
| 4 | **Buy&Hold SPY (the yardstick)** | +129.4% | 14.6% | **0.57** | 1.25 | −25.4% | — | — | — | PASS |

Bar to "pass": **MAR ≥ 0.50 AND Sortino ≥ 1.00.** Read this table honestly: the *only* way RSI-2 tops the MAR ranking (row 1) is by trading a **strict** oversold trigger that is in the market so rarely its drawdown is tiny — and it earns just **8.4% CAGR**, less than half of buy-and-hold, to get there. The popular version (row 3) makes more money but is beaten by the equal-weight basket of *the very same names* on **every** risk metric **and** on raw return. RSI-2 never actually wins.

## Kill-Test 1 — Drop-Top-5 (the channel's signature test)

- Total net trade P&L: **+$92,092** on a $100k book.
- **Top-5 NAMES = $47,304 = 51% of all net profit** → AMD $13.6k, NVDA $12.1k, GS $8.3k, AVGO $7.3k, NFLX $6.1k.
- Re-run with those 5 names removed: **MAR 0.30, Sortino 0.70 → FAIL.** CAGR collapses 11.3% → 5.6%.
- The top-5 single *trades* are only 12% of net P&L (RSI-2 makes 1,452 tiny trades, so no one trade dominates) — but the concentration by **name** is fatal. This wasn't "buy any oversold large-cap and bounce." It was "have happened to be trading the handful of 2023–2026 AI/mega-cap winners." Strip the survivors and the edge is gone.

## Kill-Test 2 — Cost Sensitivity (RSI-2 trades a LOT)

| Cost (one-way) | Total Ret | CAGR | MAR | Sortino | Bar |
|---|--:|--:|--:|--:|:--:|
| 0 bps (frictionless) | +121.7% | 13.9% | 0.75 | 1.46 | PASS |
| **5 bps (base, 10 bps round trip)** | +92.2% | 11.3% | 0.59 | 1.22 | **PASS** |
| 10 bps (2×, 20 bps round trip) | +66.4% | 8.7% | **0.44** | **0.96** | **FAIL** |

- 1,452 round trips over 6 years. At a frictionless 0 bps the strategy looks genuinely good (MAR 0.75). At a *realistic* 5 bps it's marginal. At **2× cost it fails outright.** The gap between the frictionless and 2×-cost run is **−45% of total return** (121.7% → 66.4%) — pure friction. A high-turnover mean-reversion system lives or dies on the spread, and a retail account paying real spreads, odd-lot slippage, and (in a taxable account) short-term rates is closer to the 2× column than the 0× one.

## Kill-Test 3 — Parameter Sweep (robust edge vs curve-fit)

Entry {5, 10, 15} × exit {RSI>70, close>5-day SMA} × max-hold {5, 10} = 12 configs. **6 of 12 pass** the bar.

| entry | exit | hold | CAGR | MaxDD | MAR | Sortino | WR | n | Bar |
|--:|---|--:|--:|--:|--:|--:|--:|--:|:--:|
| <5 | RSI>70 | 5 | 8.4% | −9.4% | **0.89** | 1.24 | 62.3% | 992 | PASS |
| <5 | RSI>70 | 10 | 8.2% | −12.6% | 0.65 | 1.10 | 66.4% | 895 | PASS |
| <5 | SMA5 | 5 | 7.7% | −8.9% | 0.86 | 1.18 | 65.5% | 1005 | PASS |
| <5 | SMA5 | 10 | 7.1% | −9.2% | 0.77 | 1.08 | 66.4% | 931 | PASS |
| <10 | RSI>70 | 5 | 6.4% | −20.5% | 0.31 | 0.74 | 59.9% | 1712 | fail |
| <10 | RSI>70 | 10 | 11.3% | −19.2% | 0.59 | 1.22 | 66.8% | 1452 | PASS |
| <10 | SMA5 | 5 | 7.1% | −17.3% | 0.41 | 0.86 | 63.6% | 1771 | fail |
| <10 | SMA5 | 10 | 9.5% | −15.7% | 0.61 | 1.10 | 66.6% | 1586 | PASS |
| <15 | RSI>70 | 5 | 5.0% | −24.6% | 0.20 | 0.55 | 60.2% | 2204 | fail |
| <15 | RSI>70 | 10 | 8.0% | −20.4% | 0.39 | 0.82 | 65.7% | 1779 | fail |
| <15 | SMA5 | 5 | 5.8% | −21.2% | 0.27 | 0.63 | 63.2% | 2311 | fail |
| <15 | SMA5 | 10 | 7.6% | −19.2% | 0.39 | 0.80 | 65.6% | 1999 | fail |

**The pattern is the one honest, real signal in this whole test:** *all four* of the strict **entry <5** corners pass; loosening to <10 is a coin-flip (2 of 4 pass); every **<15** corner fails. The deeper and rarer you demand the oversold, the better the risk-adjusted result and the smaller the drawdown — exactly what you'd expect if there's a small, genuine short-term mean-reversion effect that only lives in the tail. But "passes the bar" and "worth trading" are different sentences: the best config earns **8.4% CAGR**, roughly half of buy-and-hold.

## Kill-Test 4 — Regime Dependence (does it actually "call the bottom of a selloff"?)

P&L by the year the trade was *entered*:

| Year | Net P&L | Trades |
|---|--:|--:|
| 2021 | +$15,824 | 197 |
| **2022 (the one real bear market)** | **−$7,367** | 166 |
| 2023 | +$3,060 | 247 |
| 2024 | +$37,770 | 342 |
| 2025 | +$6,226 | 261 |
| 2026 | +$36,580 | 239 |

- **The myth's core claim is that RSI-2 "calls the bottom of a selloff." In the one genuine selloff in the sample — 2022 — the strategy LOST money.** The 200-day filter kept it out of the deepest part of the decline (good for drawdown), but every shallow dip it *did* buy on the way down kept dipping.
- Nearly all the profit came from **2024 (+$37.8k) and 2026 (+$36.6k)** — bull years — plus a single month (**2026-07 = 15% of all net P&L**). This isn't a bottom-caller; it's a **bull-market shallow-dip buyer** that works when the trend bails it out and bleeds when it doesn't. The name on the tin is wrong.

## The Win-Rate Mirage (the heart of the episode)

RSI-2's whole reputation is its win rate. Here it is, and here's why it doesn't matter:

- **Win rate: 66.8%.** Two out of three trades close green. That *feels* like an edge.
- **Average win: +$313 (+2.5%). Average loss: −$438 (−3.3%).** The average loss is **1.40× the average win.** Profit factor is only **1.44.**
- Because there's **no stop-loss**, when "oversold gets more oversold" the position just rides down to the 10-day backstop. **145 such falling-knife trades lost a combined −$121,751** (avg −6.4%) — more than the entire net profit of the book. The wins are capped by a quick bounce; the losses are not.
- **Worst single trade: TSLA, bought 2025-02-25 at RSI(2) deeply oversold, out 10 days later at −23.9% (−$3,479).** It was "oversold" the whole way down.
- This is the mean-reversion trap in one line: **a high win rate is a distribution shape, not an edge.** You can win 67% of the time and still make less than buy-and-hold, because the 33% of losers are each bigger than the winners. Anyone selling you a strategy on its win rate is showing you the half of the distribution that flatters it.

## The GREEN keeper (what the data actually supports)

- **A genuinely real, small effect: demanding *deep* oversold (RSI(2) < 5) is a real short-term mean-reversion edge.** Every strict-<5 config passed the risk bar with low drawdowns (MAR 0.65–0.89); the effect strengthens monotonically as you tighten the trigger and vanishes as you loosen it. That monotonic gradient is the fingerprint of a real signal, not a curve-fit. It is transferable as a *timing overlay* — if you were going to buy a large-cap you already want to own, waiting for RSI(2)<5 is a marginally better entry than buying blind.
- **What is NOT load-bearing:** surprisingly, the 200-day trend filter. Removing it barely moved the numbers (MAR 0.58 vs 0.59) — because in a 2020–2026 window most large-caps sit above their 200-day most of the time, so the filter rarely binds. Credit the *depth of the oversold trigger*, not the trend gate, for what edge exists.
- **The honest transferable line:** *deep short-term oversold snaps back — a little.* That effect is real, it is small, it is fragile to costs, and it is not a strategy. It's a slightly-better limit price on something you were buying anyway. "RSI-2 calls the bottom and prints money" is the mirage; "RSI(2)<5 is a decent entry tick for a name you'd hold regardless" is the keeper.

## Verdict

**A HIGH WIN RATE IS NOT AN EDGE.** RSI-2 does exactly what its fans say — it wins about two-thirds of its trades and bounces oversold names — and it *still* loses to equal-weight buy-and-hold of the same 55 stocks on total return, CAGR, MAR, and Sortino. The 67% win rate hides an average loss 40% bigger than the average win, an edge that's half-concentrated in 5 mega-cap winners, a cost curve that fails at 2× realistic frictions, and a 2022 in which the supposed "bottom-caller" lost money. The one real thing here — that deep (RSI<5) oversold snaps back a little — is a marginal entry tweak, not a system. The myth isn't a lie about the win rate. It's a lie about what a win rate *means*.

*Not investment advice. Split-adjusted daily IEX data, 55 large-caps + SPY, 2020-08 → 2026-09 (a bull-heavy window that flatters dip-buying; earlier crashes excluded — see data caveat). Costs 5 bps one-way base; cash earns 0%. One person's research — could be wrong. If you find an error, open an issue.*
