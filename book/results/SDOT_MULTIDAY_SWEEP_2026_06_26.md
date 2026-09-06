# SDOT MACD + Lee-Ready — Multi-Day Parameter Sweep (Option B)

**Run:** 2026-06-26 ~1:30 PM ET · **Window:** 22 post-reverse-split sessions, 2026-05-27 → 2026-06-26
**Data:** Alpaca SIP tape per day (bars + RTH trades + RTH quotes); Lee-Ready buy/sell volume.
**Model:** intraday only — flat at each open, forced-flat ~15:55 ET; MACD 12/26/9; exits = 2% trailing stop OR sell/buy ≥ 1.75×. **Gross, no commission/slippage.**

> Window starts at the reverse split (~1-for-20, $0.14→$2.87 on 05-27). Pre-split penny-stock data was excluded — different price scale would corrupt MACD and the volume profile.

## Sweep result — lowering buy/sell makes it strictly worse

| buy/sell gate | zero filter | trades | win% | total ret% | avg/trade | profit factor | Sortino |
|---:|:--|---:|---:|---:|---:|---:|---:|
| **2.5** (orig) | both>0 | 36 | 33 | **+2.5** | +0.07 | **1.07** | 0.06 |
| 2.5 | macd>0 | 40 | 35 | +1.4 | +0.03 | 1.04 | 0.03 |
| 2.0 | both>0 | 41 | 32 | −1.3 | −0.03 | 0.97 | −0.03 |
| 2.0 | macd>0 | 45 | 33 | −2.4 | −0.05 | 0.95 | −0.05 |
| 1.75 | both>0 | 46 | 28 | −13.6 | −0.30 | 0.74 | −0.25 |
| 1.75 | macd>0 | 50 | 30 | −14.7 | −0.29 | 0.74 | −0.25 |
| 1.5 | both>0 | 50 | 28 | −20.3 | −0.41 | 0.67 | −0.31 |
| 1.5 | macd>0 | 56 | 29 | −27.5 | −0.49 | 0.61 | −0.36 |

**Performance degrades monotonically as the gate is lowered.** Every entry you add by relaxing 2.5→1.5 is, on average, a net loser — the extra trades have worse expectancy than the ones the strict gate already let through. Relaxing the zero-line filter (both>0 → macd>0) is also slightly worse at every gate. **The tweak we discussed (lower buy/sell to ~2.0, relax zero filter) is rejected by the data.** Good thing we tested instead of shipping it.

## But the "winning" baseline has no real edge either

The best cell (original 2.5×/both>0) is barely above breakeven, and that thin profit is a **fat-tail lottery**, not an edge:

- Total **+2.47%** over 22 days / 36 trades · avg **+0.07%**/trade · **median trade −0.66%** (the typical trade loses)
- Win rate **33%** · profit factor **1.07** · Sortino **0.06**
- **Two trades** (+18.9% on 06-10, +9.88% on 06-16) = **+28.8%**, vs net total of +2.5%
  - Strip top 1 → **−16.4%** · strip top 2 → **−26.3%** · strip top 3 → **−28.3%**

Remove the two luckiest prints and the strategy is deeply negative. This is the same signature flagged in the gap-trader audit (top-few trades = ~all the profit) — a few outsized winners carrying a sea of small losers, with no robustness.

It fails the project bar (**MAR ≥ 0.5 AND Sortino ≥ 1.0**) by a wide margin, and that's *before* costs. On a $2–$28 name with ~2-minute holds and spread-crossing exits, commission + slippage would sink even the +2.5% baseline below zero.

## Why it behaves this way

- **Exits dominate by sell-volume, not the stop.** Across variants ~55% of exits fire on the 1.75× sell-volume trigger, often 1–2 minutes after entry. On a violent low-float runner, buy- and sell-pressure flip minute-to-minute, so most entries get spat out almost immediately for a small loss. The MACD cross + buy-volume confirmation does not select minutes that keep running.
- Lowering the buy gate just lets in lower-conviction crosses that flip even faster → more, worse trades.

## Bottom line

1. **Don't lower the buy/sell gate.** Out-of-sample, it strictly hurts.
2. **Don't ship this strategy as-is.** Even the best parameterization has no robust edge — profit is 2 lottery trades out of 36, median trade is a loss, fails MAR/Sortino, negative after costs.
3. The single-day SDOT exercise that started this was a coincidence of one strong name on one day; across 22 sessions the structure doesn't hold.

### If you want to keep pulling the thread (not recommended without a new idea)
- The real lever isn't the entry gate — it's the **exit**. A 1.75× sell-volume exit guarantees you bail on noise. Testing a wider/slower exit (e.g. ATR trail, or ignore sell-volume for N minutes after entry) is the only change with a chance of altering the outcome — but that's a different strategy needing its own validation.
- N=22 days, one symbol. Even a "good" result here would need a basket of similar runners + costs before it meant anything.

*Scripts: `scratchpad/sweep.py`, `scratchpad/fetch_days.py`; per-day tape cached in `scratchpad/days/`.*
