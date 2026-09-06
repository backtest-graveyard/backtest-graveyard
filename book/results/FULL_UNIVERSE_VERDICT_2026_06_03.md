# Full-Universe Re-Audit — Final Verdict

**Date:** 2026-06-03
**Run:** full 11,033-symbol universe, parity-faithful intraday screen + causal entry gate, RVOL≥5×, 2025-09-11 → 2026-04-18 (~7 months, 157 trading days). **537 trades** — finally real shot count (vs 33 on the narrow cache).

## Headline scorecard — it CLEARS the bar
| Metric | Value | Bar |
|---|---|---|
| Trades | 537 | — |
| Win rate | 44% | — |
| Avg R | +0.068R | — |
| Total | +$12,505 | — |
| **MAR** | **+1.56** | ≥ 0.5 ✓ |
| **Sortino (annualized)** | **+1.87** | ≥ 1.0 ✓ |

On headline metrics, with real shot count, it passes both gates for the first time ever.

## Robustness check — it FAILS decisively
The pre-committed honest test: does it survive stripping the top handful of trades?

| | Removes | % of total profit | Remainder |
|---|---|---|---|
| Strip top 3 | +33.6R | **92%** | +3.0R over 534 trades = **+0.006R/trade (≈0)** |
| Strip top 5 | +51.3R | **140%** | **−14.7R (NEGATIVE)** |
| Strip top 10 | +85.7R | 234% | −49.1R |

Top 5 winners: PHOE +12.2R, CRCD +11.2R, PTN +10.2R, AMCI +9.2R, BTTC +8.5R.

**The entire 7-month, 537-trade profit is 3 trades. Miss the top 5 (0.9% of trades) and it's a loser.** More shots did not make the edge robust — it just added more scratches (avg R fell from +0.20 to +0.068) while the P&L stayed concentrated in a few ~10R parabolic runners.

## Verdict: it's a fat-tail lottery — now PROVEN at scale, not small-sample noise
This is the definitive answer to "what would it take to make the gap trader profitable." The honest conclusion from the start of the session — that this strategy has no *robust* edge — survives the most favorable test we could build (parity-fixed universe, full market, your own RVOL rule, real shot count):

- The strategy's expectancy lives **entirely** in rare ~10R+ runners. Catch them → MAR 1.56. Miss 5 of 537 → flat-to-negative.
- That is not a statistical edge you can size into. It's a bet that you will **perfectly capture a handful of parabolic small-cap moves per year**, on exactly the thin, low-float names where:
  - **Execution is hardest** (halts, gaps, slippage, the runner blows through your fill),
  - **The backtest is least trustworthy** — those +10R fills are on Alpaca **IEX 1-min data (~2–3% of volume)**; the real high/low and fill quality on a halting $3 ripper are not what the bars show.
- **Survivorship bias** likely flatters it further (dead pumps removed from the symbol list).

## What it would *actually* take (and the honest recommendation)
To turn this from a lottery into a deployable edge you would need **all** of:
1. **Reliable runner capture** — full-volume (SIP) data + low-latency execution that can actually fill the ~10R moves live, not retail IEX. (~$99/mo+ data, and execution infra.)
2. **Acceptance of extreme lumpiness** — months flat-or-down waiting for the 3 trades that make the year; brutal path dependency.
3. **Survivorship-clean validation** — point-in-time universe to confirm the tails aren't an artifact.

Even with all three, you're sizing into a strategy whose entire return is 0.9% of its trades. For someone whose goal is to live off return-of-capital (per the finance profile), **this is not a core allocation — it's a small satellite at most, and only if execution can be proven to capture the tails.**

## Bottom line
The parity work was worth it: it proved the audits *were* undersold (the strategy isn't "dead" — there's a real fat-tail signature, and on headline numbers it clears MAR 0.5 / Sortino 1.0). But the deeper truth is harsher and now well-established: **the edge is not robust — it is a handful of runners, and at retail data/execution you cannot count on catching them.** Don't deploy real size on this. If the gap-and-go itch needs scratching, it's a tiny, execution-gated satellite funded only after SIP data + survivorship-clean validation — not before.

*(Numbers reproducible: `state/cache/trades_2025-09-11_2026-04-18_*.csv`; run log `state/catalyst_exp/fulluniverse_7mo.log`.)*
