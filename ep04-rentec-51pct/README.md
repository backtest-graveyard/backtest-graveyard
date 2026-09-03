# Episode 4 — The 51% → $100 Billion Math

**Verdict: every number in the viral post is real, and the "system" it describes still has zero edge. Expected Value, Kelly, and the Law of Large Numbers are infrastructure — they size and count your bets. They don't make the money. What to bet on is the entire game, and that's the one thing the post doesn't give you.**

Video: https://www.youtube.com/@TheBacktestGraveyard

## The claim tested

A post went viral (June 2026, ~1.28M views) using Renaissance Technologies' Medallion Fund to argue that a **51% win rate** plus three pieces of math turns into **$100 billion**. Anchored on the famous Mercer quote: *"We're right 50.75% of the time… but we're 100% right 50.75% of the time. You can make billions that way."*

Every factual claim in it is correct. The math is real. The quote is real. Renaissance is real, and Medallion really did make roughly that much. The question is whether *what's described* is a strategy you could follow.

## The three formulas (all real, all accounting)

- **Expected Value** — `EV = p·win − (1−p)·loss`. At p = 50.75% with symmetric payoffs the gross edge is ≈ **1.5% of stake per trade**. Tells you *whether* to bet, not *what* to bet on.
- **Kelly Criterion** — the growth-optimal bet fraction, `f* = edge/odds`. Tells you *how much*. For a 1.5% edge the per-bet fraction is tiny; Medallion's large aggregate leverage comes from holding *thousands of near-uncorrelated positions*, not from over-betting one signal.
- **Law of Large Numbers** — the realized win rate converges to the true rate as N grows, *if* two conditions hold: **(a) the bets are independent** and **(b) the edge is stationary.** Those are the hard, fragile parts, and the post never states them.

Add all three together and they create **exactly zero edge.** They are the bookkeeping layer of quant trading. They manufacture no alpha. The 50.75% signal — a thousand PhDs, 40 years of data, and a pattern nobody outside that building has ever seen — is the actual secret, and it is exactly what the post does not contain.

## The trap that makes it dangerous

If you take the framework and apply it to an edge you don't actually have (your "51%" is really 50% or 49%, as it is for almost everyone), **full-Kelly sizing makes you lose faster.** The exact same machinery that compounds a real edge blows up a fake one. Sizing without signal, sized aggressively, is a wealth-destruction machine. (This is the same result Episode 3 found empirically: [Kelly on a noisy edge estimate was a downgrade](../ep03-kelly-sizing/).)

## Why "$100 billion" is the tell, not the flex

The headline number is the most misleading part. The mechanism that makes the Law of Large Numbers work — high turnover, thousands of tiny bets — is **inherently capacity-constrained.** Medallion **caps outside AUM at ~$10B and forcibly returns capital and profits to employees**, *precisely because the edge does not scale*: at size, your own orders move the price against you. So the $100B is **~30 years of profit compounded on deliberately capped capital** — not a pool of money the approach could ever hold. Read "51% → $100B" as "this scales" and you have it exactly backwards. ([charts/chart5_capacity.png](charts/chart5_capacity.png))

## The cost wall

A ~1.5% gross edge across thousands of trades survives only if all-in costs (spread + commission + slippage + borrow) sit at **single-digit basis points per side.** Renaissance's real, underappreciated moat is partly that they trade cheaper and faster than anyone alive. Sitting at a normal broker paying a normal spread, you've lost the edge before you started.

## The rules worth keeping

The math is real — keep all three, as **infrastructure**, not as a strategy:

1. **Rank on Expected Value, not win rate.** Being right 60% of the time means nothing if your losers are bigger than your winners.
2. **Size with a *fraction* of Kelly, never full.** You never know your own edge as well as you think; full Kelly bets the estimate as if it were a fact, and being a little wrong is punished hardest at full strength.
3. **Count your *effective* bets, not your total bets.** The LLN only pays you if the bets are actually independent. A thousand bets that secretly do the same thing is one bet wearing a costume.

## The confession: my own gap trader

Rule 3 is one I failed. My archived gap trader looked like a big, healthy sample — **537 trades.** But when I pulled it apart, the **top 3 trades were ~92% of all profit; strip the top 5 and it went negative** ([charts/chart8_gaptrader.png](charts/chart8_gaptrader.png)). Its **effective N was about 3, not 537.** The independence condition the Law of Large Numbers needs was never there, so the "many small edges converge" machinery never engaged. That's the precise reason it was archived — and the exact trap this post's framing walks a reader into. The full gap-trader receipts are in [Episode 2](../ep02-gap-and-go/).

## Reproducibility

This episode is a math teardown, not a new backtest — there's no proprietary strategy here to publish. The formulas (EV, Kelly, LLN) are standard and derived above. The Medallion capacity and cost facts are public (Zuckerman, *The Man Who Solved the Market*). The gap-trader concentration numbers are the same ones published with [Episode 2](../ep02-gap-and-go/).

To apply the one portable test to **your own** backtest: **delete your five best trades and re-run it.** If the edge falls apart, your effective N was tiny and the Law of Large Numbers was never on your side — no matter how many trades you had.

---

*Nothing here is investment advice. One person's research — could be right, could be wrong. Found an error? Open an issue; corrections get pinned.*
