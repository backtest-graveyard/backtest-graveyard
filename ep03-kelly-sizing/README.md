# Episode 3 — The Kelly Criterion

**Verdict: on a bot that already works, swapping constant-risk sizing for the Kelly criterion was a downgrade. At full strength it was the worst. Keep boring, constant-risk sizing.**

Video: https://www.youtube.com/@TheBacktestGraveyard

## The claim tested

The Kelly criterion is sold online as the *mathematically optimal* bet size: once you have an edge, Kelly tells you the perfect fraction of your bankroll to bet, and betting anything else leaves money on the table. Ed Thorp used it to beat blackjack, then Wall Street. The pitch is that it turns any real edge into the most money math allows.

So: does handing a working strategy's position sizing to Kelly make it better?

## The test

Take the one live paper-traded bot I've built that clears my bar — a real, positive, risk-adjusted edge. **Leave its signal completely untouched** (this experiment is about *sizing*, not the strategy). Change only how much it bets:

- **Constant-risk (volatility-target)** — the incumbent. Aims for a steady amount of risk; shrinks in choppy markets, grows in calm ones.
- **Fractional Kelly** at a **quarter**, a **half**, and **full** strength.

The catch that makes this honest: **every variant is matched to the same average gross exposure.** Kelly naturally wants to run more leverage, and more leverage flatters raw returns. Matching exposure means no version can "win" just by betting bigger — you only see the effect of *how* it allocates, per unit of risk. 5 years of history, honest costs (15 bps entry / 8 bps exit).

Scorecard: **MAR = return ÷ worst drawdown** (the number that decides), plus **Sortino** (downside-wobble) and **max drawdown**.

## The result (matched for exposure)

| Variant | Avg gross exposure | Return | **MAR** | Sortino | Max drawdown |
|---|---|---|---|---|---|
| Constant-risk (vol-target) | 0.35 | +51.2% | **2.05** | 1.96 | −6.2% |
| Kelly ×0.25 (quarter) | 0.49 | +56.2% | 1.73 | **2.20** | −8.0% |
| Kelly ×0.50 (half) | 0.54 | +50.6% | 1.52 | 2.07 | −8.3% |
| Kelly ×1.00 (full) | 0.58 | +47.6% | 1.42 | 2.05 | −8.5% |

Full numbers in [`kelly_sizing_results.csv`](kelly_sizing_results.csv).

**More Kelly → worse return-to-drawdown, and a deeper hole.** Full worse than half worse than a quarter — the textbook signature of over-betting a noisy edge estimate. On the number I care about most, the "optimal" formula was a straight downgrade. ([chart4_mar_ladder.png](charts/chart4_mar_ladder.png))

## The "it doubled my return!" trap

Unmatched, on a single representative asset, full Kelly returned **+416%** vs **+196%** for constant-risk sizing over 5 years — a headline "double." But it got there by running roughly **2× the average exposure** (0.80 vs 0.38). That isn't smarter sizing; it's leverage with the risk hidden. Match the exposure and the "win" disappears. Any demo showing you Kelly's huge return *without matching risk* is showing you leverage and calling it genius. ([chart3_leverage_trap.png](charts/chart3_leverage_trap.png))

## What Kelly actually won

One thing, and it's real: a **smoother daily ride** — Sortino rose from 1.96 to 2.20 at quarter-Kelly. Kelly piles more onto its highest-conviction bets, which feels great on the average day. It pays for that with a **deeper worst day** (−6.2% → −8.5%): when a high-conviction bet is wrong, the bigger position digs a bigger hole. Smoother most days, uglier on the ugly day — not a trade worth making here.

## Why "optimal" loses in real trading

Kelly is optimal *only if you know your exact edge.* In blackjack you do — the deck is the deck. In trading, your edge is an estimate scraped off noisy history, and it drifts. Full Kelly bets that estimate as if it were a proven fact, and being a little wrong (which you always are) is punished hardest at full strength. That's why full was worse than half was worse than a quarter: plain over-betting, right on schedule.

## The rule worth keeping

If you use Kelly at all, **use a fraction of it.** Quarter-Kelly was least-bad here by a wide margin. Betting a fraction is admitting, out loud, that you don't actually know your edge — humility, not weakness. Nobody serious runs full Kelly.

## The bonus finding: broad, not a lottery

Across *every* sizing variant, the bot made about **22% of its total profit on its five best days** — flat, no matter how it was sized ([chart7_broad_vs_lottery.png](charts/chart7_broad_vs_lottery.png)). That's a **broad-based edge**: hundreds of small, mostly-independent wins, the law-of-large-numbers condition that lets a thin edge compound.

Contrast [Episode 2](../ep02-gap-and-go/)'s gap trader: its **top 3 trades were 92% of all profit** — a lottery. Broad edges compound. Lottery edges don't, no matter how cleverly you size them. The Kelly test didn't make the bot better; it accidentally confirmed the bot's *structure* was sound — which is the real reason it clears the bar and the gap trader didn't.

## Reproducibility

These numbers come from a **private, live paper-traded bot; its signal and code are not published** — this channel is testing *sizing* here, not giving away a strategy. So the table above is not independently re-runnable. But every figure shown in the video is in [`kelly_sizing_results.csv`](kelly_sizing_results.csv), and the method is fully described above.

To run the same test on **your own** strategy: size each variant to **equal average gross exposure**, then compare **return ÷ max drawdown** — never raw returns. If you skip the exposure-matching step, you're just measuring leverage.

---

*Nothing here is investment advice. One person's research on his own bots — could be right, could be wrong. Found an error? Open an issue; corrections get pinned.*
