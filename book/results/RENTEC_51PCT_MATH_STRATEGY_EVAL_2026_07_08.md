# Evaluation — "The Math That Turns a 51% Win Rate Into $100 Billion"

**Source:** @thedelost, X post 2065849372592537803 (June 13, 2026; ~1.28M views, 1,601 bookmarks). Links an article using Renaissance Technologies' Medallion Fund to explain three concepts: Expected Value (1654), the Kelly Criterion (1956), and the Law of Large Numbers (1713).
**Evaluated:** 2026-07-08.
**Bottom line:** The math is correct and genuinely important, but the post commits the field's most common error — presenting the *position-sizing / portfolio machinery* as if it were the *edge*. It is not. These three formulas create zero alpha. Their profit potential "at full deployment," on their own, is **zero to negative**, because full-Kelly sizing applied to a non-edge accelerates ruin rather than wealth. Their real value is strictly as a risk overlay on a separately-discovered, genuinely uncorrelated, cost-surviving signal — and finding/maintaining that signal is 99% of the problem and entirely absent from what's described.

---

## 1. Strategy mechanics — what's the edge?

The described "system" is: find a bet that is right slightly more than half the time, size it with Kelly, repeat across enough independent trials that the Law of Large Numbers turns the thin edge into near-certain compounding. Medallion's own quote (Mercer, via Zuckerman's *The Man Who Solved the Market*) is the anchor: *"We're right 50.75% of the time… but we're 100% right 50.75% of the time. You can make billions that way."*

The three formulas, precisely:

- **Expected Value** — `EV = p·(win) − (1−p)·(loss)`. With p = 50.75% and symmetric payoffs, gross edge ≈ **1.5% of stake per trade** (0.5075 − 0.4925). Trivially true accounting; it tells you *whether* to bet, not *what* to bet on.
- **Kelly Criterion** — optimal fraction `f* = edge/odds`. Maximizes long-run geometric growth. For a 1.5% edge the per-bet fraction is tiny. The nuance the post skips: RenTec runs ~12.5× leverage not by over-betting one signal but because it holds *thousands of near-uncorrelated positions* — aggregate portfolio Kelly is large even though each bet is microscopic.
- **Law of Large Numbers** — the realized win rate converges to the true rate as N grows, so the edge "shows up." Convergence requires two conditions the post never states: **(a) low correlation across bets** and **(b) stationarity** (the edge must persist). Both are the hard, fragile parts.

**Verdict on mechanics:** Logically sound, but this is the *bookkeeping layer* of quant trading, not an alpha source. EV/Kelly/LLN are necessary to turn an edge into compounded wealth; they manufacture no edge. The 50.75% signal — the actual secret — is exactly what the post does not provide and what RenTec has never disclosed.

## 2. Profit potential

Two very different numbers depending on who's implementing:

- **Theoretical ceiling (RenTec's own result):** ~66% gross / ~39% net annual (after 5-and-44 fees), 1988–2018, no losing year, blended Sharpe roughly ~2 (materially higher on the core signal over short windows). This is real — but it is *their* signals, *their* execution, *their* 90+ PhDs and multi-decade data moat.
- **Realistic expectation of deploying "this post":** the framework contributes **0% alpha**. Applied on top of a genuine edge it improves geometric growth (real value). Applied to a break-even or losing strategy — which is what you have if you only have the formulas and not the signal — Kelly sizing **increases the speed at which you lose**. Expected outcome: negative.

The math is a **risk/sizing layer, not an alpha layer.** That distinction is the entire evaluation.

**Best conditions:** a large population of genuinely independent, stationary, low-cost, short-horizon bets (statistical arbitrage). **Worst conditions:** few correlated bets, non-stationary edge, meaningful transaction costs, or leverage without the ability to hold through variance — i.e., almost every retail or small-prop setup.

## 3. Scalability and capacity — the killer

This is where the "$100 Billion" framing is most misleading. The mechanism that makes the LLN work — high turnover, thousands of small bets — is **inherently capacity-constrained.** Medallion **caps AUM at roughly $10B and forcibly returns outside capital and profits to employees**, *precisely because the edge does not scale.* Short-horizon statistical arbitrage decays as size grows: your own orders move the price and become your dominant cost.

So the honest capacity read is the opposite of the headline: this style is **retail-to-mid-prop scale**, not institutional-AUM scale. The "$100B" is *cumulative fund profits compounded over three decades on deliberately capped capital* — not a pool of capital the approach could absorb. Anyone reading "51% → $100B" as "this scales" has it backwards.

## 4. Execution realities

The thin edge is exactly what makes execution decisive:

- **Costs vs. edge.** A 50.75% win rate on symmetric payoffs is a ~1.5%-of-stake gross edge per trade, but on the round trip the realized edge is far smaller. Across thousands of trades, all-in costs (spread + commission + slippage + borrow) must sit at **single-digit basis points per side** or the edge is entirely consumed. RenTec's genuine, underappreciated moat is partly *execution and cost minimization at scale* plus ultra-short-horizon signals — not the formulas. Retail pays spread + 1–5 bps and the edge evaporates.
- **Leverage and financing.** ~12× leverage means financing cost and gap/margin risk. Portfolio-Kelly assumes you can hold through variance; a broker margin call during a normal drawdown converts a temporary loss into **permanent ruin** — Kelly's core blind spot (it assumes continuous, infinitely-divisible rebalancing with no ruin barrier).
- **Latency/infra.** Thousands of near-independent short-horizon bets implies colocation, smart routing, rebate capture, prime-broker financing. This is an infrastructure business, not a formula.

## 5. Key risks and failure modes

1. **Non-stationarity / edge decay** — the 50.75% is not a constant of nature; real edges erode. RenTec counters with a large research org constantly re-estimating. Without that, your measured edge is a decaying, possibly already-dead number.
2. **Correlation blowup** — LLN only rewards *independent* trials. In a crisis, "independent" bets correlate toward 1, effective N collapses, and the law fails *exactly when you need it* (the LTCM lesson).
3. **Over-betting Kelly on estimation error** — your `p` is an estimate with error; true Kelly < estimated Kelly, and full-Kelly on an overestimated edge produces *negative* long-run growth. Serious practitioners use ¼–½ Kelly. The post never mentions this — arguably its most dangerous omission.
4. **Cost/slippage creep with size** — see §3–4.
5. **Survivorship/selection bias** — Medallion is the one shop out of thousands that worked. Building a thesis by conditioning on the single biggest winner is textbook survivorship bias.

## 6. Verdict

The formulas are real, correct, and worth internalizing — but as **infrastructure, not as a strategy.** EV tells you *whether* a known edge is worth betting; Kelly tells you *how much*; LLN tells you *why it compounds if the trials are independent and the edge is stationary.* None of them tells you *what to trade*, which is the only hard part and the entire content of RenTec's moat.

- **Durable edge?** The *math* is permanently durable (it's arithmetic). The *edge the math operates on* is the opposite of durable — it decays, and sustaining it is a capital-intensive research-and-execution problem.
- **Profit potential at full deployment of what's described:** **zero to negative**, because the piece supplies sizing without signal, and aggressive sizing of a non-signal is a wealth-destruction machine.
- **What it would take to actually capitalize:** a genuinely uncorrelated, stationary, low-cost signal (the 99% that's missing) + single-digit-bps execution + fractional-Kelly discipline + capacity humility (return capital before you become your own counterparty). That is a firm, not a formula.

---

## Tie-in to this project's own history

The post is a clean lens on why the **gap trader was archived**. The 2026-06-03 parity re-audit found its headline MAR 1.56 / Sortino 1.87 was a **fat-tail lottery: top-3 trades = 92% of profit; strip the top 5 → negative.** In this post's language, that strategy's **effective N ≈ 3, not 537** — it violates the independence condition the LLN requires, so the "many small edges converge" machinery never engages. That's the precise reason it was correctly judged undeployable, and it's the same trap the post's framing would lead a reader straight into.

The genuinely portable lessons, all already consistent with the project's MAR-over-win-rate doctrine:
1. Win rate is a descriptor, not a target — optimize EV and geometric growth. (Already codified in CLAUDE.md.)
2. Size with **fractional** Kelly; full Kelly assumes a perfectly known edge you never have.
3. LLN only pays you if trades are actually independent and the edge is stationary — so measure **effective N** (are your winners concentrated?) before trusting any "high-N" backtest.
