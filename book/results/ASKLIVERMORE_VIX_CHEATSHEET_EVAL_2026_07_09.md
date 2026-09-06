# AskLivermore "VIX Cheat Sheet" — Quant Evaluation

**Source:** @AskLivermore on X, posted 2026-07-07 (status 2074494353905713531).
**Evaluated:** 2026-07-09.
**Claim:** *"This is all you need to do to make millions in the stock market… Every major spike above 35 was a buying opportunity. Every drop below 15 preceded a selloff."*

---

## Executive summary

**One line: the cheat sheet is a real but modest risk-management idea buried under marketing. The salvageable core — "after a VIX panic, buy large-caps when they reclaim the 200-day, hold until vol normalizes" — halves drawdowns versus buy-and-hold but never beats it on return and never clears our ship bar. "Make millions" is false.**

**What's actually there.** Two legs. The *buy-the-panic* leg (VIX>35 → buy) is genuine, well-documented edge — VIX mean reversion + forced-selling reversal + the volatility risk premium. The *sell-below-15* leg is a textbook base-rate fallacy (P(low VIX | selloff) is high, but P(selloff | low VIX) is not) and would have pulled you out of every low-vol bull melt-up. As written the sheet has no holding rule, no sizing, no drawdown control, and its "every single time since 2018" record rests on ~5 signals in the friendliest era on record.

**What we did.** Took the *only* defensible leg (buy the panic) and stress-tested it on real VIX + SPY/QQQ/IWM data across the 2000–09 secular bear, the 2010–25 low-vol bull, and the full 25-year cycle — building up the entry/exit rules the sheet omits, then sweeping instruments and costs. Long-only, cash@0%, 5 bps/side base.

**What we found (full cycle 2000–2025, best config = plain CONFIRM):**

| | SPY | QQQ | vs Buy & Hold |
|---|--:|--:|---|
| Total return | +128% | +217% | **loses** (BH +644% / +668%) |
| Max drawdown | −28% | −33% | **wins** (BH −55% / −83%) |
| MAR | 0.11 | 0.14 | ~tie (BH 0.15 / 0.10) |
| Ship bar (MAR ≥ 0.5) | ✗ | ✗ | — |

**Five findings that shaped the verdict:**
1. **Buy-the-panic survives the acid test.** In the 2000–09 bear it turned a −9%/−50% buy-and-hold decade positive and cut drawdowns — the crisis-alpha is real (§7).
2. **A naïve VIX-spike stop is regime-fragile.** A 200-DMA *stop* rescued 2008 (MAR 0.05→0.33) but was a wrecking ball in the bull era (+13% vs +702% buy-and-hold, whipsawed) — no single parameterization wins both regimes (§8–9).
3. **The fix is a re-entry *confirmation*, not a stop.** Waiting to enter until price reclaims its 200-DMA ("buy the recovery, not the knife") is the only all-weather version — it's competitive in both regimes and halves buy-and-hold drawdowns (§10). This is the winning design.
4. **Both of the sheet's headline instructions are net-negative.** "Buy high-beta small caps" (IWM) is where the overlay performs *worst* — the noisier signal fakes out, and even a patched-in stop can't make it beat buying and holding IWM (§11–12). And adding an in/out *stop* is pure harm on the clean large caps where the overlay actually works (§13). What survives is the quiet part: confirmed-reclaim entry on SPY/QQQ, no stop, no small caps.
5. **It's cost-immune but that doesn't save it.** ~1 round-trip/year → realistic execution costs −0.02 pp/year; the sub-0.5 MAR is *structural* (in cash most of the time, misses the bull), not frictional (§14).

**Bottom line.** The best honest version of the AskLivermore sheet is a **large-cap drawdown-management overlay** — worth running only as a small tactical sleeve, and only if you value cutting crash drawdowns roughly in half at the cost of most of the bull-market upside. It is **not** a standalone alpha engine (best full-cycle MAR 0.14 vs. our 0.5 gate), it **loses to buy-and-hold on total return** over the full cycle, and over 2010–25 the strategy that would actually have cleared our bar was *just buy-and-hold QQQ* (MAR 0.53). The edge is real, durable, and known — and precisely because it's known, it's priced as "sensible rebalancing," not "millions."

---

## The strategy, as stated

A single-variable regime allocator keyed off the CBOE VIX:

| VIX zone | Action | Instruments |
|---|---|---|
| **35+** | Buy aggressively | High-beta tech, growth, small caps |
| **25–35** | Scale in | Quality tech, financials, cyclicals |
| **15–25** | Hold / stay positioned | Tech + defensives, dividend growers |
| **< 15** | Sell / reduce exposure | Utilities, healthcare, staples, bonds |

No holding period, exit rule, position-sizing rule, or drawdown control is specified. "Aggressively" is a vibe, not a parameter.

---

## 1. Strategy mechanics — is the logic sound?

**Partly. It bundles one genuinely robust effect with one that is a textbook base-rate fallacy.**

**The buy-the-spike leg (VIX ≥ 35) is real edge.** It exploits three overlapping, well-documented regularities:
- **VIX mean reversion.** VIX is one of the most mean-reverting series in finance. Prints above 35 are rare and short-lived; the index is pulled back toward its ~15–20 median within weeks.
- **Forced-selling reversal.** VIX>35 coincides with margin calls, risk-parity deleveraging, and vol-target funds dumping — price-insensitive selling that overshoots fundamentals and reverts.
- **Volatility risk premium.** You are effectively getting paid to supply liquidity/insurance when everyone wants it. Conditioning equity entry on high VIX has historically lifted forward 6–12mo returns materially above the unconditional mean.

This leg is directionally correct and is the durable part of the sheet.

**The sell-below-15 leg is mostly wrong as stated.** "Every drop below 15 preceded a selloff" confuses P(low VIX | selloff) with P(selloff | low VIX). The market spends the *majority* of its time with VIX under 20, so of course every selloff was "preceded" by low VIX — but low VIX is a terrible *timing* signal to exit. Low VIX can persist for **years** (2017, H2-2019, most of 2021, most of 2024), and those are precisely the strong grind-up periods. Selling into VIX<15 would have pulled you out of the best up-years of the exact window the chart shows.

**Net:** "add risk in panics, trim into euphoria" is sensible rebalancing discipline. The specific claim of infallibility on both legs is marketing.

---

## 2. Profit potential — theoretical ceiling vs realistic expectation

**Theoretical ceiling (buy-leg only, best case):** Historically, entering broad equity when VIX>30–35 has produced forward-12-month returns in a rough **+15% to +20% average** range vs. ~+9% unconditional — *but with enormous dispersion* (COVID +70% off the low vs. 2008 −40% further before the low). Add high-beta/small-caps and you amplify both tails. Figures here are approximate, from memory of the historical distribution — **not** a fresh data pull; treat as order-of-magnitude, not precise.

**Realistic expectation as a standalone system: modest.** Three reasons it does not "make millions":
1. **Signal scarcity.** Since 2018 there are only ~4–5 distinct VIX>35 events (Feb-2018 Volmageddon, Dec-2018, Mar-2020 COVID, Aug-2024 yen-carry, Apr-2025 tariff shock). The entire "alpha" is 4–5 data points. Most of the time the sheet just says HOLD or SELL.
2. **The sell-low-vol rule is a return-killer.** In the 2018–2025 window it would have had you under-exposed through 2019, 2021, 2023H2, and 2024 — the biggest low-vol melt-ups. Time out of market during those years likely *costs* more than the buy-leg adds.
3. **Benchmark reality.** For this window, naive buy-and-hold SPX/QQQ beats most VIX-timing overlays on total return, precisely because the overlay makes you sell strength. A vol overlay's honest value is *drawdown reduction and re-entry discipline*, not excess CAGR.

**Estimated risk-adjusted result:** As a full four-zone system, Sharpe probably lands around **0.5–0.8** — comparable to or slightly below buy-and-hold, with better tail behavior only if you keep the buy leg and *drop* the sell leg. The buy-leg-only "lean in during panics" variant is the version worth keeping.

**Best conditions:** V-shaped, central-bank-backstopped corrections (2018, 2020, 2025). **Worst conditions:** grinding secular bears where VIX>35 is a bull trap (2000–02, 2008–09, 1973–74) — see §5.

---

## 3. Scalability & capacity

**Institutional-scale, effectively unlimited capacity — which is also the tell that it's not proprietary alpha.** It trades the most liquid instruments on earth (index ETFs, mega-cap tech, sector ETFs) at very low turnover (a handful of regime shifts per decade). Capital does not degrade the edge because there's no crowding at the microstructure level.

But the flip side: this is *common knowledge*. "Buy the panic, VIX mean-reverts" is taught in every vol desk and CTA shop. There is no informational moat. It scales because it's a beta-timing overlay, not because it's a discovered inefficiency. Retail can run it in a brokerage account; a pod can run it in size; neither gets a secret.

---

## 4. Execution realities

**Microstructure cost is near-zero; the real costs are behavioral and opportunity-based.**
- **Transaction cost / slippage:** negligible. Liquid ETFs, low turnover, daily/weekly signal — no latency requirement whatsoever.
- **The genuine cost is psychological.** "Buy aggressively" when VIX is 45 and the tape is in free-fall is the single hardest execution in investing. Most people who "screenshot this" will freeze at exactly the signal.
- **Path risk on the buy leg.** A VIX>35 print is *not* the bottom. In Sep-2008 VIX crossed 35 and the market fell ~40% more into Mar-2009. "Buy aggressively" + high-beta/small-caps + any leverage into that = forced liquidation before the payoff. The strategy has no stop and no staging rule, so it silently assumes infinite balance-sheet and infinite patience.
- **Whipsaw on the 15 line.** VIX oscillates across 15 constantly; a literal sell-below-15 trigger churns.

---

## 5. Key risks & failure modes

1. **Cherry-picked regime (the big one).** The chart starts in 2018 — the era of maximal Fed put and V-shaped recoveries. It excludes 2008 (buy VIX>35 in Sept, endure −40% more) and 2000–02 (VIX spiked repeatedly through a three-year bear). In those regimes the buy leg bleeds for months to years before working. "Every single time since 2018" is a claim conditioned on the friendliest 8 years in market history.
2. **Sample size n≈5.** No statistical robustness. One or two contrary episodes (a real secular bear) flips the record.
3. **No exit / no sizing / no drawdown control.** Unfalsifiable as written. "Buy aggressively" and "make millions" have no defined trade.
4. **Base-rate fallacy on the sell leg** (§1) → chronic underperformance in low-vol bull markets.
5. **Regime-shift risk.** The V-shaped-recovery backdrop depends on aggressive central-bank/fiscal backstop. Higher-for-longer rates or a fiscal constraint could produce a grinding bear where this strategy's whole thesis breaks.
6. **Leverage + high-beta interaction.** The recommended instruments (high-beta tech, small caps) maximize path risk exactly when you're told to "buy aggressively" — worst possible time to add fragility.

---

## 6. Verdict

**Half-true, and the true half isn't a secret.**

- The **buy-the-panic leg is a real, durable, well-understood effect** (mean reversion + forced-selling reversal + vol risk premium). It survives out of sample *in direction*, though not in magnitude and not without deep drawdowns in secular bears.
- The **sell-below-15 leg is a base-rate fallacy** that would have hurt you in the very window used to sell it.
- Framed as "all you need to make millions," it's **marketing**: no holding rule, no sizing, no risk control, n≈5, and a backtest window hand-picked from the most V-shaped-recovery-friendly era on record.

**Is the edge durable?** The *discipline* is (lean into fear, trim euphoria — a sound rebalancing prior). The *literal system* is not, because it's fully known, signals are rare, the sell leg is negative-value, and it has no drawdown control for the one regime (secular bear) that would blow it up.

**What it would take to actually capitalize on it:**
1. **Keep the buy leg, kill the sell leg.** Use VIX>30–35 as a "scale into risk over N tranches" signal; do *not* de-risk on low VIX (use valuation/trend for that instead).
2. **Stage entries** (e.g., add on VIX>30, >40, >50) so a second leg down averages you in rather than wiping you out.
3. **Define holding + sizing** — e.g., hold to VIX<20 or a fixed 6–12mo horizon, cap position at a risk budget, no leverage on the high-beta sleeve.
4. **Add a secular-bear circuit-breaker** (price trend / 200-day filter) so you're not "buying aggressively" all the way down a 2008/2000-style decline.
5. **Backtest across 2000–2002 and 2008–2009**, not just 2018–present, and report MAR / Sortino / max-DD — not "millions."

**Bottom line:** A useful *risk-management heuristic* dressed up as an *alpha engine*. As a rebalancing prior it beats performance-chasing. As a literal money-printer it fails the same bars our own strategies must clear (defined edge, out-of-sample robustness, drawdown control, MAR/Sortino). Realistic contribution of the salvageable buy-leg overlay: maybe +1–3% annualized and better tail behavior vs. naive buy-and-hold — not life-changing, and only if disciplined.

---

## 7. Backtest: buy-leg-only across the lost decade (2000-01-01 → 2009-12-31)

**Setup.** Long-only, no "sell below 15" leg. Enter long when VIX closes above the entry threshold; exit when VIX closes below the exit level *or* after a max hold; cash earns **0%** when flat (conservative — real T-bills yielded ~2–4% over this decade and the book is in cash most of the time, so this *understates* the strategy). Fills at signal-day close, **5 bps/side** cost. Data: yfinance `^VIX`, `SPY`, `QQQ` (auto-adjusted). Staged variant adds equal-third tranches at VIX 30/40/50. Metrics are fresh from this run — figures elsewhere in this doc labeled "approximate" were not.

### S&P 500 (SPY)

| Variant | Trades | Total | CAGR | MaxDD | MAR | Sortino | Sharpe | WR | PF |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| **Buy & hold** | — | **−8.7%** | −0.91% | −55.2% | −0.02 | 0.10 | 0.07 | — | — |
| buy VIX>30, exit<20 or 252d | 9 | +26.7% | 2.40% | −44.7% | 0.05 | 0.20 | 0.22 | 67% | 2.93 |
| buy VIX>30, exit<25 or 252d | 14 | +32.2% | 2.83% | −44.7% | 0.06 | 0.17 | 0.25 | 86% | 2.51 |
| buy VIX>35, exit<20 or 252d | 3 | +6.3% | 0.62% | −44.7% | 0.01 | 0.08 | 0.12 | 67% | 2.19 |
| **STAGED 30/40/50, exit<20 or 252d** | 9 | +19.3% | 1.78% | **−39.2%** | 0.05 | 0.15 | 0.19 | 78% | 7.63 |

### Nasdaq-100 (QQQ) — the "high-beta/growth" sleeve the sheet recommends

| Variant | Trades | Total | CAGR | MaxDD | MAR | Sortino | Sharpe | WR | PF |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| **Buy & hold** | — | **−50.3%** | −6.76% | −83.0% | −0.08 | −0.04 | −0.03 | — | — |
| buy VIX>30, exit<20 or 252d | 9 | +21.3% | 1.95% | −60.6% | 0.03 | 0.20 | 0.21 | 78% | 1.86 |
| **buy VIX>30, exit<25 or 252d** | 14 | **+130.8%** | 8.73% | −40.4% | **0.22** | 0.36 | 0.48 | 86% | 8.20 |
| buy VIX>35, exit<20 or 252d | 3 | +34.5% | 3.01% | −41.3% | 0.07 | 0.19 | 0.25 | 100% | ∞ |
| STAGED 30/40/50, exit<20 or 252d | 9 | +40.4% | 3.45% | **−33.3%** | 0.10 | 0.26 | 0.28 | 89% | 2.35 |

### What this shows

1. **The buy-leg is real crisis-alpha — it survived the acid test.** Every variant beat buy-and-hold on both instruments. On QQQ it flipped a **−50% "lost decade" into +21% to +131%** and cut max drawdown from −83% to −33/−40%. Vindicates the core instinct: *lean into panic, don't buy-and-hold blindly through a secular bear.*

2. **But it fails our ship bar, and not by a little.** Best-case MAR = **0.22**, best-case Sortino = **0.36** — versus our gates of **MAR ≥ 0.5 and Sortino ≥ 1.0**. It is a *drawdown-reducer relative to a disastrous benchmark*, not a strategy that clears the bar on its own.

3. **"Buy the panic" still ate the second leg of 2008.** Every SPY variant shows the *same* −44.7% max drawdown — one trade drives it: entering on the Sept-2008 VIX>30 print and holding SPY down to the March-2009 bottom (VIX never fell below the exit, so the 252-day hold ran). This is exactly the failure mode flagged in §4/§5 — the spike is not the bottom.

4. **Staging worked as predicted.** The 30/40/50 tranche variant cut max DD the most (SPY −44.7%→−39.2%, QQQ −60.6%→−33.3%) and posted the best profit factors — confirming recommendation #2 (stage entries so a second leg averages you in instead of maximizing pain at the first spike).

5. **Most of the "outperformance" is bear-avoidance, not alpha.** The book sits in cash for most of the decade and only deploys on panics. Against a −9%/−50% benchmark, *being mostly in cash* is a large part of the win. In a normal or bull decade that same cash drag would make it *lag* buy-and-hold (see the eval's main point about the sell-leg / low exposure).

6. **Thin and parameter-fragile.** 3–14 trades per variant over 10 years. Changing the exit from `<20` to `<25` swings QQQ from +21% to +131% — a huge sensitivity on ~14 trades. Treat the point estimates as illustrative, not as a robust edge; the honest takeaway is the *sign and the drawdown behavior*, not the specific CAGR.

**2000–2009 verdict:** The buy-leg-only version **passes the "does it break in a secular bear?" test in the sense that it doesn't blow up and it beats blind buy-and-hold** — but it **does not clear a shippable KPI bar** (MAR 0.05–0.22, Sortino 0.08–0.36 vs. 0.5/1.0), it still carries 33–60% drawdowns, and its edge over the benchmark is largely "held cash through the worst decade in a century." It's a legitimate **risk-management overlay**, exactly as the eval concluded — not a standalone alpha engine, and nowhere near "make millions."

---

## 8. Adding the 200-day trend filter (the secular-bear circuit-breaker)

A naive "only buy above the 200-DMA" gate has a known pathology: during a VIX spike price is almost always *below* its 200-DMA, so the gate throws away most panic entries. So I tested the trend filter three ways, all on the base config (buy VIX>30, exit<20 or 252d):

- **GATE** — enter a spike only if price > 200-DMA (classic trend gate)
- **STOP** — buy the panic in any trend, but exit if price closes below its 200-DMA; re-arm only after price reclaims it (the true circuit-breaker)
- **GATE+STOP** — both

### S&P 500 (SPY)

| Variant | Trades | Total | CAGR | MaxDD | MAR | Sharpe | WR | PF |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| no filter (base) | 9 | +26.7% | 2.44% | −44.7% | 0.05 | 0.22 | 67% | 2.93 |
| GATE | 2 | +22.7% | 2.11% | −9.4% | 0.22 | 0.45 | 100% | ∞ |
| **STOP** | 9 | **+28.7%** | 2.61% | **−7.8%** | **0.33** | 0.51 | 89% | 8.27 |
| GATE+STOP | 2 | +17.3% | 1.64% | −10.3% | 0.16 | 0.41 | 50% | 10.0 |

### Nasdaq-100 (QQQ)

| Variant | Trades | Total | CAGR | MaxDD | MAR | Sharpe | WR | PF |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| no filter (base) | 9 | +21.3% | 1.99% | −60.6% | 0.03 | 0.21 | 78% | 1.86 |
| GATE | 5 | +94.8% | 7.04% | −21.8% | 0.32 | 0.64 | 100% | ∞ |
| **STOP** | 13 | +69.4% | 5.53% | **−16.7%** | 0.33 | 0.61 | 54% | 6.71 |
| GATE+STOP | 6 | +63.3% | 5.14% | −17.9% | 0.29 | 0.60 | 67% | 12.8 |

### What the filter does

1. **The circuit-breaker is the single biggest improvement in the whole study.** On SPY, STOP cut max drawdown from **−44.7% to −7.8%** while slightly *increasing* return (+26.7%→+28.7%). MAR jumped ~**6×** (0.05→0.33) and Sharpe more than doubled (0.22→0.51). On QQQ, drawdown fell from −60.6% to −16.7% and MAR from 0.03 to 0.33 (~**10×**). This directly neutralizes the §7 failure — the 2008 "buy the panic and ride it to the March-2009 bottom" trade gets cut when price loses its 200-DMA, instead of bleeding −40%.

2. **STOP beats GATE for robustness.** GATE looks great on drawdown but is too restrictive — only **2 trades on SPY** over the decade (it sits out nearly every panic because price is below trend during spikes). Its record rests on a tiny sample. STOP keeps the full 9–13 trades — you still buy the panic — but bails if it turns into a grinder. STOP is the design worth keeping.

3. **But it still does not clear our ship bar.** Best MAR ≈ **0.33** vs. our **0.5** gate. The drawdowns are finally *controlled* (single-digit to high-teens) and the profit factors are strong (6–13), but over this bear decade the return is modest and MAR/Sortino remain sub-gate. (Note: Sortino reads oddly low — ~0.2–0.3, *below* Sharpe — because the return stream is mostly zero-return cash days, which distorts the downside-deviation denominator on a small sample. Treat MAR / Sharpe / MaxDD as the cleaner reads here; Sortino is noisy for a mostly-in-cash book.)

### Revised recommendation

The trend circuit-breaker (STOP) is the fix that makes buy-the-panic genuinely **investable as a risk overlay**: it turns a −45%/−60% drawdown into −8%/−17% with equal-or-better return, converting the strategy from "beats a disastrous benchmark" into "beats it *with controlled risk*." That is a real, defensible improvement and validates eval recommendation #4. It is still **not** a standalone alpha engine — MAR ~0.33 over the 2000s bear falls short of our 0.5 bar — but as a *drawdown-aware tactical add-risk overlay* on top of a core allocation, the VIX>30-spike + 200-DMA-stop combination is the version that survives contact with a secular bear.

---

## 9. The low-vol era (2010–2025) and the full cycle — the regime trap

Same engine, window moved to **2010-01-01 → 2025-12-31** (the post-GFC bull / low-vol regime), then the **full 2000–2025 cycle**. Same rules, costs, cash@0%.

### 2010–2025 (bull / low-vol)

| SPY | Trades | Total | CAGR | MaxDD | MAR | Sortino | Sharpe | WR |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| **Buy & hold** | — | **+702.0%** | 13.91% | −33.7% | **0.41** | 1.04 | 0.84 | — |
| no filter | 13 | +170.8% | 6.43% | −28.3% | 0.23 | 0.31 | 0.56 | 100% |
| **STOP** | 23 | **+12.9%** | 0.76% | −20.5% | 0.04 | 0.05 | 0.18 | 39% |

| QQQ | Trades | Total | CAGR | MaxDD | MAR | Sortino | Sharpe | WR |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| **Buy & hold** | — | **+1422.8%** | 18.57% | −35.1% | **0.53** | 1.19 | 0.93 | — |
| no filter | 13 | +276.4% | 8.64% | −22.4% | 0.39 | 0.39 | 0.67 | 100% |
| **STOP** | 20 | **+34.0%** | 1.85% | −27.6% | 0.07 | 0.10 | 0.28 | 25% |

### Full cycle 2000–2025

| | Total | CAGR | MaxDD | MAR | Sortino | Sharpe |
|---|--:|--:|--:|--:|--:|--:|
| SPY buy & hold | **+644.3%** | 8.03% | −55.2% | 0.15 | 0.63 | 0.50 |
| SPY no filter | +243.1% | 4.89% | −44.7% | 0.11 | 0.27 | 0.39 |
| SPY STOP | +45.4% | 1.46% | **−20.5%** | 0.07 | 0.10 | 0.32 |
| QQQ buy & hold | **+667.6%** | 8.16% | −83.0% | 0.10 | 0.56 | 0.43 |
| QQQ no filter | +356.6% | 6.06% | −60.6% | 0.10 | 0.29 | 0.39 |
| QQQ STOP | +127.0% | 3.23% | **−27.6%** | 0.12 | 0.17 | 0.42 |

### What this proves

1. **The circuit-breaker that saved 2008 is a wrecking ball in the low-vol era.** SPY STOP returned **+12.9% over 16 years** vs. buy-and-hold **+702%** — it captured under **2%** of the market's return. Its win rate *collapsed to 25–39%* (from 89–100% without the stop). Mechanism: in a low-vol bull, VIX>30 events are brief scares that V-recover, and the 200-DMA stop ejects you *at the bottom* right before the bounce. The exact device that neutralized the 2008 grinder is poison against fast whipsaw corrections. There is no free lunch — a stop that protects secular bears must whipsaw V-recoveries.

2. **Even the best buy-leg version badly lags in the bull era.** No-filter captured +171%/+276% vs. +702%/+1423%. Sitting in cash ~70–80% of the time means you miss the bull — which is where essentially all the money is.

3. **Over the full 25-year cycle, buy-and-hold wins decisively on return** (+644%/+668% vs. STOP's +45%/+127%) and **roughly ties or beats every overlay on MAR** (SPY: BH 0.15 > STOP 0.07; QQQ: BH 0.10 < STOP 0.12 — a wash, and only because QQQ's −83% dot-com crash was so extreme that halving it barely rescues the ratio). **Nothing clears the 0.5 MAR bar over the full cycle.** The overlay's *entire* value proposition reduces to: *give up 60–90% of total return to cut max drawdown roughly in half* — and even that is instrument-dependent.

4. **The decisive point — there is no single parameterization that wins in both regimes.** STOP: MAR 0.33 in 2000–09, 0.04 in 2010–25. No-filter is roughly the reverse. Success is *entirely a bet on which regime you're in*, and the VIX level at the moment you must act does **not** tell you whether a spike is COVID (buy it) or September-2008 (don't). That is the signature of a regime-timing tool with no durable standalone edge.

5. **Humbling footnote:** over 2010–2025, the strategy that *would* have cleared our ship bar was **buy-and-hold QQQ** (MAR 0.53, Sortino 1.19). Every clever VIX overlay destroyed value against simply owning the index.

### Final synthesis (both eras)

| Regime | Winner | Why |
|---|---|---|
| Secular bear (2000–09) | STOP overlay | Cuts −45%/−60% DD to −8%/−17%, beats a negative buy-and-hold |
| Bull / low-vol (2010–25) | Buy-and-hold | Overlay captures <25% of return; STOP whipsaws to near-zero |
| Full cycle (2000–25) | Buy-and-hold on return; ~wash on MAR | Bull era dominates; overlay only ever bought drawdown reduction |

This closes the loop on the eval's thesis. The AskLivermore buy-the-panic idea is a **real but regime-contingent risk-management overlay**, not a standalone alpha engine. Its best-case device (VIX-spike entry + 200-DMA circuit-breaker) is genuinely valuable *if and only if you already know you're entering a secular bear* — the one thing the VIX cannot tell you in advance. Absent that foresight, disciplined buy-and-hold beat every version of the strategy over the full 25-year sample. Deploy it, if at all, as a **tactical drawdown hedge you switch on when you have an independent macro view of regime**, sized small — never as the core engine, and never with the "make millions" framing.

---

## 10. Re-entry confirmation instead of a spike-stop — the all-weather fix

**Design change.** Instead of buying the panic and cutting on a 200-DMA break (STOP), a VIX>30 spike merely *arms* the setup; you enter **only when price closes back above its 200-DMA** (confirmation the downtrend has actually turned). Arm expires if no reclaim within 252 days of the last spike. You sacrifice the sharp initial bounce in exchange for **never catching a falling knife** — you buy the recovery, not the crash. Same exit (VIX<20 or 252d), costs, cash@0%.

### CONFIRM vs the other overlays, all three windows

| Window / Instrument | Metric | Buy&Hold | no-filter | STOP | **CONFIRM** |
|---|---|--:|--:|--:|--:|
| **2000–09 SPY** | Total / MaxDD / MAR | −8.7% / −55% / −0.02 | +26.7% / −44.7% / 0.05 | +28.7% / −7.8% / 0.33 | **+35.2% / −10.3% / 0.30** |
| **2000–09 QQQ** | Total / MaxDD / MAR | −50.3% / −83% / −0.08 | +21.3% / −60.6% / 0.03 | +69.4% / −16.7% / 0.33 | **+55.0% / −33.2% / 0.14** |
| **2010–25 SPY** | Total / MaxDD / MAR | +702% / −34% / 0.41 | +170.8% / −28.3% / 0.23 | +12.9% / −20.5% / 0.04 | **+68.8% / −28.3% / 0.12** |
| **2010–25 QQQ** | Total / MaxDD / MAR | +1423% / −35% / 0.53 | +276.4% / −22.4% / 0.39 | +34.0% / −27.6% / 0.07 | **+104.8% / −22.4% / 0.20** |
| **2000–25 SPY** | Total / MaxDD / MAR | +644% / −55% / 0.15 | +243.1% / −44.7% / 0.11 | +45.4% / −20.5% / 0.07 | **+128.1% / −28.3% / 0.11** |
| **2000–25 QQQ** | Total / MaxDD / MAR | +668% / −83% / 0.10 | +356.6% / −60.6% / 0.10 | +127.0% / −27.6% / 0.12 | **+217.4% / −33.2% / 0.14** |

(Win rates: CONFIRM 80–91% except QQQ-bull 65%; STOP collapses to 25–39% in the bull era. Full-cycle CONFIRM Sharpe 0.41–0.43, profit factor 6.5–17.)

### Why this is the best-engineered version

1. **CONFIRM resolves STOP's fatal flaw.** STOP whipsaws to near-zero in the bull era (+12.9% SPY) because it ejects you at the bottom of every fast dip. CONFIRM doesn't hold-then-stop — it *waits to enter* until the trend turns, so in a V-recovery it still gets in (a bit late) instead of getting shaken out. Bull-era return jumps from STOP's +13%/+34% to **+69%/+105%**, win rate from 39%/25% to **89%/65%**.

2. **It keeps most of STOP's bear protection.** In 2000–09 CONFIRM posts MAR 0.30 (SPY) with a −10% drawdown — nearly identical to STOP's 0.33/−8% — and actually *higher return* on SPY (+35% vs +29%). The only place STOP clearly wins is QQQ's 2000–09 drawdown (−16.7% vs CONFIRM's −33.2%), because CONFIRM re-entered into the choppy 2001–02 Nasdaq bear a few times before the real bottom.

3. **It's the only overlay that's competitive in BOTH regimes** — the definition of regime-robust. STOP is a bear specialist that's poison in bulls; no-filter is the reverse (fine in bulls, −45%/−61% DD in bears). CONFIRM is decent everywhere. Over the full cycle it delivers the best or tied MAR of any overlay (QQQ 0.14 — beats buy-and-hold's 0.10) while roughly **halving buy-and-hold's drawdown** (−28%/−33% vs −55%/−83%).

### But the ceiling is unchanged

- **CONFIRM still badly lags buy-and-hold on return** over the full cycle: +128%/+217% vs. +644%/+668%. Being in cash ~70% of the time is still the dominant fact — you avoid the crashes but forfeit most of the compounding.
- **It never clears our ship bar.** Best CONFIRM MAR is 0.30 (SPY bear) and 0.20 (QQQ bull); full-cycle 0.11–0.14. Sortino tops out ~0.25. Versus MAR ≥ 0.5 / Sortino ≥ 1.0, it's not close — and over 2010–25 plain buy-and-hold QQQ (MAR 0.53, Sortino 1.19) beat every version.

### Revised final synthesis

| Design | Bear (2000–09) | Bull (2010–25) | Full cycle | Character |
|---|---|---|---|---|
| Buy & hold | Awful (−9%/−50%) | **Best** (MAR 0.41/0.53) | **Best return** | Wins whenever there's no secular bear |
| no-filter buy-leg | OK return, −45/−61% DD | Lags, 100% WR | +243/+357%, deep DD | Bull-tilted, no crash control |
| STOP | **Best** (MAR 0.33, −8% DD) | **Worst** (+13%, whipsawed) | Low return, best DD | Bear specialist, bull poison |
| **CONFIRM** | Strong (MAR 0.30, −10% DD) | Decent (MAR 0.12/0.20) | **Best overlay MAR/DD balance** | **All-weather — the one to actually run** |

**Bottom line:** Re-entry confirmation is the correct fix. It converts the buy-the-panic idea from a regime-specialist (STOP) into a **regime-robust drawdown overlay** that behaves acceptably whether or not a secular bear shows up — precisely because it doesn't need to predict the regime; it waits for price to confirm it. If this strategy is deployed at all, **CONFIRM is the version to use.** It is still, unavoidably, a *drawdown-reduction overlay that trades away most of the bull-market upside* — not a standalone alpha engine, and nowhere near "make millions." The honest one-line summary of the whole exercise: *the salvageable core of the AskLivermore sheet is "after a VIX panic, buy when price reclaims its 200-day" — a real, all-weather risk-management rule that halves drawdowns, and that is the entire edge.*

---

## 11. CONFIRM on high-beta small caps (IWM) — where the overlay breaks

The sheet's headline instruction is to buy the *highest-beta* sleeve in a panic — "high-beta tech, growth, **small caps**." So the decisive test is running the best overlay (CONFIRM) on IWM (Russell 2000). Same rules, costs, cash@0%. (IWM inception May 2000, so its 2000–09 series effectively begins ~2001 after the 200-DMA warmup.)

### IWM, all three windows

| Window | Metric | Buy&Hold | no-filter | STOP | **CONFIRM** |
|---|---|--:|--:|--:|--:|
| **2000–09** | Total / MaxDD / MAR | +53.5% / −58.6% / 0.08 | +45.2% / −53.7% / 0.08 | +22.1% / −12.9% / 0.18 | **+7.2% / −53.7% / 0.01** |
| **2010–25** | Total / MaxDD / MAR | +378% / −41.1% / 0.25 | +217% / −34.3% / 0.22 | +17.0% / −25.6% / 0.04 | **+73.4% / −17.3% / 0.20** |
| **2000–25** | Total / MaxDD / MAR | +652% / −58.6% / 0.14 | +360% / −53.7% / 0.12 | +42.8% / −25.6% / 0.06 | **+85.8% / −53.7% / 0.05** |

### CONFIRM's drawdown protection — instrument by instrument (full cycle 2000–25)

| Instrument | CONFIRM MaxDD | Buy&Hold MaxDD | Protection | CONFIRM MAR |
|---|--:|--:|--:|--:|
| SPY | −28.3% | −55.2% | **halved** | 0.11 |
| QQQ | −33.2% | −83.0% | **more than halved** | 0.14 |
| **IWM** | **−53.7%** | −58.6% | **almost none** | **0.05 (worst)** |

### What breaks, and why

1. **The crash protection that defined CONFIRM on SPY/QQQ collapses on IWM.** Full-cycle CONFIRM drawdown is **−53.7% — essentially identical to no-filter (−53.7%) and buy-and-hold (−58.6%)**. The whole point of the overlay was to cut crash drawdowns roughly in half; on small caps it delivers almost no protection.

2. **Mechanism: false 200-DMA reclaims on a noisier index.** The −53.7% is the 2008 collapse. On choppy, higher-beta IWM the 200-DMA reclaim throws a *head-fake* — IWM (armed by an Aug-2007 VIX spike) reclaimed its 200-DMA in late 2007, CONFIRM bought the "confirmation," and then IWM fell ~54% through 2008 while VIX stayed above the exit the whole way down. CONFIRM has **no post-entry stop**, so a fakeout reclaim *before* the real bear is catastrophic. Higher beta = more whipsaw = more false confirmations. Beta makes the *timing harder*, not the payoff bigger.

3. **On IWM, CONFIRM is the worst-of-both-worlds overlay.** Full-cycle it has the lowest MAR of any overlay (0.05 vs STOP 0.06, no-filter 0.12): it eats the full no-filter drawdown (−53.7%) *and* sacrifices the bull upside (+86% vs no-filter's +360%). STOP protected the drawdown (−25.6%) but killed return (+43%); no-filter kept return (+360%) but had no protection. **There is no good overlay on IWM** — and the confirmation design is actively the weakest on the exact instrument the sheet tells you to prefer.

4. **The bull era alone looked fine — which is the trap.** 2010–25 IWM CONFIRM was respectable (MAR 0.20, −17.3% DD, 79% WR). The failure is concentrated entirely in the 2008 crash — i.e., *the one event the overlay exists to protect against*. An overlay that works in calm whipsaws but fails in the actual crisis is worse than useless; it lulls you into trusting protection that isn't there when it matters.

5. **The instrument recommendation was doubly wrong for the modern era.** Beyond the overlay mechanics, buy-and-hold IWM (+378%, MAR 0.25) badly lagged SPY (+702%, MAR 0.41) and QQQ (+1423%, MAR 0.53) over 2010–25 — the small-cap premium was simply absent post-GFC. So the sheet's "tilt to small caps in the rebound" advice hurt on *both* axes: lower base returns and a trend-confirmation signal that misfires on small-cap noise.

### Verdict on the high-beta sleeve

**The buy-the-panic overlay is only as good as the trend-confirmation signal, and that signal degrades exactly as you move up the beta ladder the sheet recommends.** On liquid, less-noisy large-cap indices (SPY/QQQ) CONFIRM is a legitimate all-weather drawdown overlay. On high-beta small caps (IWM) — the sheet's *preferred* rebound vehicle — the confirmation fakes out, the drawdown protection vanishes, and you're left holding the worst risk-adjusted profile of any version tested. If the CONFIRM overlay is deployed at all, it should be run on **SPY/QQQ, explicitly not on the high-beta small-cap sleeve the cheat sheet tells you to buy** — and even then it needs a post-entry stop to survive a false reclaim into a real bear. This is the sharpest piece of honest pushback in the whole evaluation: the sheet's single most emphatic instruction ("buy high-beta small caps aggressively") is where its salvageable core performs *worst*.

---

## 12. Adding a post-entry stop to CONFIRM on IWM — the fix works, but it's a regime trade

§11 diagnosed the failure: CONFIRM has no post-entry stop, so a *false* 200-DMA reclaim into a real bear (IWM late-2007 → −54% through 2008) is eaten in full. Fix: **CONFIRM+STOP** — keep the confirmed-reclaim entry, but exit if price closes back below the 200-DMA; the setup stays armed after a stop and re-enters on the next genuine reclaim. Retested on IWM, all three windows. (Plain CONFIRM numbers verified unchanged.)

### IWM: CONFIRM vs CONFIRM+STOP

| Window | Variant | Total | MaxDD | MAR | Sortino | Sharpe | WR | Trades |
|---|---|--:|--:|--:|--:|--:|--:|--:|
| **2000–09** | CONFIRM | +7.2% | −53.7% | 0.01 | 0.08 | 0.13 | 88% | 8 |
| | **CONFIRM+STOP** | **+33.7%** | **−12.9%** | **0.26** | 0.25 | 0.48 | 64% | 11 |
| **2010–25** | CONFIRM | +73.4% | −17.3% | 0.20 | 0.21 | 0.48 | 79% | 14 |
| | **CONFIRM+STOP** | +31.1% | −24.9% | 0.07 | 0.12 | 0.31 | 29% | 24 |
| **2000–25** | CONFIRM | +85.8% | −53.7% | 0.05 | 0.13 | 0.26 | 82% | 22 |
| | **CONFIRM+STOP** | +75.3% | **−24.9%** | **0.09** | 0.16 | 0.37 | 40% | 35 |

Full-cycle IWM ranking by MAR: Buy&Hold 0.14 > no-filter 0.12 > **CONFIRM+STOP 0.09** > STOP 0.06 > CONFIRM 0.05.

### What the stop did

1. **It fixed the exact failure §11 identified.** In the 2000–09 bear, the false-reclaim catastrophe is gone: drawdown **−53.7% → −12.9%**, return **+7.2% → +33.7%**, MAR **0.01 → 0.26**. The stop cuts the position when the late-2007 reclaim rolls over, instead of riding IWM down 54%. Full-cycle it roughly **halves CONFIRM's drawdown (−53.7% → −24.9%)** and nearly doubles its MAR (0.05 → 0.09). As a crash fix, it works exactly as intended — CONFIRM+STOP goes from *worst* overlay to the best of the crash-protected variants.

2. **But it re-imports bull-market whipsaw — the same tax STOP paid.** In 2010–25 the stop made things *worse*: MAR **0.20 → 0.07**, win rate **79% → 29%**, drawdown **−17.3% → −24.9%**, trade count 14 → 24. On the noisy small-cap index, the stop that saves you in a real bear chops you to pieces in low-vol ranges — you get knocked out below the 200-DMA on every shallow pullback, then re-enter higher. (Drawdown got *worse* not from any single position but from a long string of whipsaw losers stacking up on the equity curve.)

3. **Net full-cycle, it's a modest positive that still loses to owning the index.** The 2008 rescue outweighs the bull-era drag in ratio terms (MAR 0.05 → 0.09, Sharpe 0.26 → 0.37, drawdown roughly halved), but return slips (+85.8% → +75.3%) and CONFIRM+STOP still trails **both no-filter (MAR 0.12) and plain buy-and-hold (MAR 0.14, +652%)**. The stop makes CONFIRM *survivable* on IWM; it does not make IWM *worth trading* with this overlay.

### The honest resolution

**The post-entry stop is the correct fix and it works — but it confirms §11's deeper verdict rather than overturning it.** High-beta small caps are simply too noisy for 200-DMA-based timing, and the two failure modes trade off against each other:

- **No stop** → false reclaims into bears (−54% drawdown, the §11 problem).
- **With stop** → range whipsaw in bulls (29% win rate, MAR collapses in 2010–25).

There is no parameterization in this overlay family that makes IWM behave as cleanly as SPY/QQQ, where plain CONFIRM already halved drawdowns *without* needing a stop and *without* the whipsaw tax. The practical takeaways:

- **If you must hold the high-beta sleeve, CONFIRM+STOP is the right configuration** — you'd far rather eat −25% than −54% when the next 2008 hits, and the stop buys exactly that insurance for a modest full-cycle cost.
- **But the cleaner answer is still: run the overlay on SPY/QQQ, not IWM.** The sheet's flagship instruction — "buy high-beta small caps aggressively" — remains the weakest link. The best you can do on IWM (CONFIRM+STOP, MAR 0.09) is worse than the *worst* thing you can do on large caps under this family, and worse than simply buying and holding IWM itself.
- **Nothing here clears the ship bar** (MAR ≥ 0.5 / Sortino ≥ 1.0). Best IWM figure is MAR 0.26 in one bear decade; full-cycle 0.09. This stays a drawdown-management overlay, full stop.

---

## 13. CONFIRM+STOP on SPY/QQQ — the stop is pure harm on clean large caps

Running the same post-entry stop on SPY and QQQ completes the picture — and the result is the exact mirror of IWM.

### CONFIRM vs CONFIRM+STOP, large caps

| Window | Instrument | Variant | Total | MaxDD | MAR | WR |
|---|---|---|--:|--:|--:|--:|
| **2000–09** | SPY | CONFIRM | +35.2% | −10.3% | **0.30** | 80% |
| | SPY | CONFIRM+STOP | +12.6% | −16.6% | 0.07 | 30% |
| | QQQ | CONFIRM | +55.0% | −33.2% | **0.14** | 91% |
| | QQQ | CONFIRM+STOP | +9.6% | −44.9% | 0.02 | 32% |
| **2010–25** | SPY | CONFIRM | +68.8% | −28.3% | **0.12** | 89% |
| | SPY | CONFIRM+STOP | +24.5% | −23.1% | 0.06 | 42% |
| | QQQ | CONFIRM | +104.8% | −22.4% | **0.20** | 65% |
| | QQQ | CONFIRM+STOP | +36.4% | −23.8% | 0.08 | 31% |
| **2000–25** | SPY | CONFIRM | +128.1% | −28.3% | **0.11** | 86% |
| | SPY | CONFIRM+STOP | +40.2% | −23.1% | 0.06 | 37% |
| | QQQ | CONFIRM | +217.4% | −33.2% | **0.14** | 75% |
| | QQQ | CONFIRM+STOP | +49.5% | −44.9% | 0.03 | 31% |

### The stop is counterproductive on large caps — in every single window

On SPY and QQQ, adding the stop **lowers return, halves-or-worse the MAR, and collapses win rate to ~30–42%** in all three windows. On QQQ it even makes **drawdown worse** (−33.2% → −44.9% full cycle). There is no window and no metric where the stop helps a large-cap index.

Why: plain CONFIRM's confirmed-reclaim entry is already *clean* on SPY/QQQ — a 200-DMA reclaim there rarely fails, so there is no false-reclaim catastrophe to fix. The stop solves a problem large caps don't have, while importing the one problem they otherwise avoid — getting chopped out on every shallow dip below the 200-DMA and re-entering higher (the whipsaw churn that also lengthens the equity drawdown).

### The unifying insight — the stop's value is inverse to signal cleanliness

| Instrument | Plain CONFIRM (full cycle) | Effect of adding the stop | Root cause |
|---|---|---|---|
| **SPY** | Best: MAR 0.11, DD −28% (halved) | **Harmful in every window** | Clean confirmation → no false reclaim to fix; stop = pure whipsaw |
| **QQQ** | Best: MAR 0.14, DD −33% (halved) | **Harmful, even worsens DD** | Same |
| **IWM** | Fails: MAR 0.05, DD −54% (false reclaim) | Helps full-cycle (0.05→0.09), fixes 2008 | Dirty confirmation → stop needed, but pays bull whipsaw tax |

The post-entry stop is only worth adding on an instrument whose trend signal is *noisy enough to fake out* — and precisely those instruments (IWM) then pay a whipsaw tax that leaves the whole overlay underperforming buy-and-hold anyway. On instruments where the overlay actually works (SPY/QQQ), the stop is strictly harmful.

### Final configuration verdict

**The single best version of the entire AskLivermore idea is: plain CONFIRM on SPY/QQQ — no stop, no small caps.**

- On clean large caps, the 200-DMA *entry* confirmation already delivers the crash protection (drawdowns halved vs buy-and-hold) **without** a stop and **without** the whipsaw tax. Adding a stop only degrades it.
- The stop is a patch for a problem that only exists on the noisy, high-beta instruments the sheet tells you to prefer — and on those instruments even the patched version loses to buying and holding.
- So the two headline instructions of the cheat sheet are *both* net-negative refinements: "buy small caps" (§11–12) and, implicitly, "trade aggressively in and out" (the stop, §13). The value that survives is the quiet part: *after a VIX panic, wait for SPY/QQQ to reclaim its 200-day, then hold until vol normalizes.*
- And it still doesn't clear the ship bar (best full-cycle MAR 0.14 vs. 0.5 required), and buy-and-hold still wins on total return. This remains a **drawdown-management overlay for large-cap equity — nothing more, and specifically not what the cheat sheet advertises.**

---

## 14. Cost & slippage sensitivity — plain CONFIRM on SPY/QQQ

The winning configuration (§13) trades rarely — ~10–11 round-trips in a decade, 28 over the full 25 years (~1.1/year). Low turnover should make it nearly cost-immune. Swept per-side cost from 0 to 50 bps (round-trip = 2×) on plain CONFIRM.

### Full cycle 2000–2025 (per-side bps, round-trip = 2×)

| Cost/side (RT) | SPY CAGR | SPY ΔCAGR | SPY MAR | QQQ CAGR | QQQ ΔCAGR | QQQ MAR |
|---|--:|--:|--:|--:|--:|--:|
| 0 bps (0) | 3.36% | — | 0.12 | 4.69% | — | 0.14 |
| **1 bps (2)** — realistic retail SPY/QQQ | 3.34% | −0.02 | 0.12 | 4.67% | −0.02 | 0.14 |
| 2 bps (4) | 3.32% | −0.04 | 0.12 | 4.65% | −0.05 | 0.14 |
| **5 bps (10)** — base case used throughout | 3.25% | −0.11 | 0.11 | 4.58% | −0.11 | 0.14 |
| 10 bps (20) — conservative | 3.14% | −0.22 | 0.11 | 4.47% | −0.23 | 0.13 |
| 25 bps (50) — pessimistic | 2.80% | −0.56 | 0.10 | 4.13% | −0.57 | 0.12 |
| 50 bps (100) — stress / bad fills | 2.24% | −1.12 | 0.08 | 3.56% | −1.13 | 0.10 |

(Bear and bull sub-periods behave identically: trade count is fixed per window, so the drag is the same linear function of cost.)

### Reading

1. **The strategy is effectively cost-immune at any realistic execution.** SPY and QQQ are the two most liquid ETFs on the planet — sub-penny spreads, zero retail commission — so realistic per-side cost is well under 1 bp. At 1 bp/side the CAGR drag is **−0.02 pp/year** and MAR is unchanged. Even the deliberately conservative 5-bp base case used in the whole evaluation costs only **−0.11 pp/year**. Nothing in the headline results is a cost artifact.

2. **The drag is exactly linear and tiny.** With ~1.1 round-trips/year, annual cost ≈ `2 × cost_bps × trades/yr` ≈ `2.2 × cost_bps` per year in bps — i.e. **~1.1 pp/year even at an absurd 50 bps/side** (100 bps round-trip, the kind of number you'd only see on illiquid single names or in a genuine liquidity crisis, not SPY/QQQ). The MAR holds at ~0.11–0.14 across 0–25 bps and only slips to 0.08–0.10 at the 50-bp stress point.

3. **Costs are not what stands between this and the ship bar.** MAR stays ~0.11–0.14 full-cycle no matter the cost assumption; the sub-0.5 MAR is *structural* (mostly-in-cash, misses the bull), not frictional. You cannot cost-optimize your way to a better verdict — and conversely, the modest edge that exists **survives execution fully**, unlike higher-frequency ideas that evaporate at 4 bps (cf. the red→green reversal probe). Low turnover is the one unambiguous virtue here: whatever CONFIRM earns, it keeps net of friction.

**Verdict:** cost/slippage is a non-issue for plain CONFIRM on large caps. The base-case numbers throughout this evaluation are robust to realistic and even pessimistic execution assumptions — the conclusions rest on the strategy's structure, not on optimistic fills.

---

*Note for our own stack: this is a crude, single-variable cousin of the Markov regime allocator — same instinct (condition exposure on regime), far less rigor. Nothing here suggests adding a VIX zone to Markov; the buy-the-panic instinct is already implicit in a vol-target sizing scheme that leans in as realized vol normalizes.*
