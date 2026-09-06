# Parity Re-Audit — Track 1 Results

**Date:** 2026-06-03
**What:** Fast, real-data parity check on the live gap-trader window (2026-04-15 → 05-22, ~5 weeks), now that the Alpaca key is fixed.

## Track 1a — Realized expectancy of the ACTUAL live trades

Simulated all 21 real live entries (`gap_log_trades.csv`) forward through their own 1-min bars (first-touch bracket: entry → stop −1R / target +rr, else EOD close).

| Metric | Live real trades | IEX-daily backtest (B 24mo) |
|---|---|---|
| Win rate | **48%** (10W / 11L) | 34% |
| Avg R | **+0.75R / trade** | −0.10R |
| Sum R | **+15.8R** | negative |

**The live trades are clearly positive where the backtest said negative.**

**Honest caveats (material):**
- **Bracket model is optimistic on wins** — 1-min bars don't reveal intra-minute stop-vs-target ordering on volatile small-caps; first-touch can credit a +3R target that intraminute might have stopped first. (I assumed stop-first on straddle bars to partly counter this.)
- **Ignores the bot's real trail/scale logic** — the logged `close` rows show FCHL/OCG/AMST/LFS actually trailed to ~**breakeven**, not the clean ±results the bracket assigns. So the *shape* differs from reality in both directions.
- **21 trades / 5 weeks = directional only**, not statistically conclusive.

Net: encouraging, model-optimistic, small sample. Not proof of edge — but a strong signal the live universe behaves nothing like the backtest universe.

## Track 1b — Universe parity diff

Of the 114 live candidates (113 with daily-bar data), how many does the backtest's daily-open gap screen even see?

- **SEEN by backtest screen: 66 (58%)**
- **MISSED: 47 (42%)** — 24 priced outside $2–$20 *at the open*, 23 with *daily-open* gap < 5%.

**Why:** the live "gap" is an **intraday / pre-market RVOL spike**; the backtest screens the **daily-open** gap (open vs prev close). They diverge wildly:

| Symbol | Date | Backtest daily-open gap | Live scanner |
|---|---|---|---|
| AGPU | 2026-04-23 | **−21.9%** (gap *down*) | +79% / 25× RVOL — *a Track-1a +2.97R winner* |
| SKLZ | 2026-04-23 | −10.8% | +236% / 238× RVOL |
| LOCL | 2026-04-22 | −24.1% | +82% / 59× RVOL |
| CLIK | 2026-04-22 | −10.9% | +36% / 28× RVOL |
| AUUD | 2026-04-24 | −60.7% | +27% / 50× RVOL |

The backtest screen rejects these as gap-downs or flat. The live bot traded them — some profitably.

## Verdict on Track 1

Both halves confirm the parity-gap thesis with real numbers:
1. **The backtest screen cannot see ~42% of the live setups** (different gap definition).
2. **On the live universe, the real trades show positive realized R** (+0.75R, model-optimistic) vs the backtest's −0.10R.

This validates re-examining the audit: the three prior "no edge" conclusions were drawn on a backtest universe that systematically excludes nearly half of what the live strategy actually trades. **It does NOT prove the gap trader is profitable** (small sample, optimistic model) — but it removes the basis for confidently calling it dead, and it justifies Track 2 (a faithful long-window rebuild).

## Track 2 v1 — INVALID (look-ahead bug caught, not a result)

Built the intraday-aware screen (intraday high ≥ +5% vs prev close, RVOL ≥ 2, $2–20). **Screen phase succeeded:** median **4 candidates/active day** (mean 4.4) — live-like, vs the old daily-open screen's ~1/day, 2× more candidates on the same 662-symbol cached set. That part is sound and confirms the universe fix works.

**Simulation phase produced impossible numbers — 74.9% WR, +1.69R avg, MAR 97, Sortino 29, PF 9.4 — which means it's broken, not brilliant.** Root cause (diagnosed on 223 simulated trades):
- **65%** of entries fired on the **9:30 open bar** — the names *gapped open above* the fictional "+5% breakout" entry level, so the sim just buys the gap-up open.
- **28%** opened **above the +14% target** — impossible to fill at +5%; instant fake-win.
- **31%** hit target **within the trigger minute** — intra-bar ordering unknown, scored optimistically.

The fixed "+5% above prev close" entry price is fictional for gap-up names. **The MAR 97 result is void and must not be cited as edge.** (Logged here as a caught bug per the "absurdly-good = red flag" rule.)

## Where Track 2 actually stands → needs v2
The **universe reconstruction works** (live-like candidate counts). The **entry/exit simulation does not** — it needs a realistic, causal model:
- Fill at the **actual breakout level** (opening-range high / pre-market high), not a fixed +5%.
- **Next-bar-open fills**, evaluate stop/target only on strictly *subsequent* bars (no within-bar credit).
- Handle gap-up opens explicitly (if it opens above the breakout, model a pullback entry or skip — mirror the live bot's actual entry logic).
- Ideally share the live `gap_scanner`/entry code path rather than a reimplementation, per the CLAUDE.md parity directive.

Until v2, the long-window faithful re-audit is **not yet done**. The trustworthy evidence remains Track 1a (real logged fills, +0.75R, small sample) and Track 1b (42% universe miss).

## Track 2 v2 — VALID re-audit (parity-fixed universe + real entry/exit sim)

v2 fixes v1 by keeping the intraday-aware **screen** but feeding it into the backtester's own **real, causal entry/exit simulation** (proper next-bar fills, scale-ins, trailing stops) — the only change vs the original audit is the screen's gap definition (`BT_INTRADAY_GAP=1` in `backtester.py`). The numbers came back **sane** (not v1's MAR 97), and entries stayed selective (~0.5/week despite 16 candidates/day), confirming the causal entry logic — not fake fills — drives the result.

| Config | Window | Trades | WR | Avg R | Total | MAR | Sortino |
|---|---|---:|---:|---:|---:|---:|---:|
| Original A (daily-open) | 12mo | 38 | 39% | +0.11 | +$2,749 | 0.49 | — |
| Original B (daily-open, shipped) | 12mo | 22 | 55% | −0.02 | +$1,371 | 0.32 | — |
| **v2 (intraday screen)** | **12mo** | 25 | 52% | **+0.20** | **+$3,701** | **0.74 ✓** | 0.76 ✗ |
| Original B (daily-open) | 24mo | 41 | 34% | −0.10 | −$3,476 | −0.35 | — |
| **v2 (intraday screen)** | **24mo** | 45 | 33% | −0.14 | −$5,137 | **−0.38 ✗** | −0.58 ✗ |

Bar = MAR ≥ 0.5 **AND** Sortino ≥ 1.0.

### Verdict
- **The user was right that the audit undersold the bot.** The parity fix more than doubles the recent-12mo MAR (0.32 → **0.74**) and flips expectancy positive (−0.02R → **+0.20R**). The daily-open screen *was* hiding real, tradeable setups (Track 1b: 42% miss). This is the first time the gap trader shows a positive-expectancy, MAR-clearing backtest.
- **But it still does not clear the full bar.** Even the strong 12mo misses **Sortino (0.76 < 1.0)** — downside variance (a few large losers) is too high. And the **24mo is negative (MAR −0.38)**, essentially unchanged from the original −0.35: the earlier 12 months drag it down.
- **Honest status: not dead, materially closer than three audits claimed, recent window genuinely promising — but not validated over a full cycle.** A marginal, regime-sensitive strategy, not a confirmed edge.

### Caveats (still live)
- **Residual look-ahead:** the screen selects on the realized intraday high, which can mildly inflate v2 — true numbers may be a touch lower.
- **Small sample** (25 / 45 trades) and **662-symbol cached universe** (not the full market).
- **Sortino computed externally** (backtester doesn't emit it); annualization approximate.
- 12mo-positive / 24mo-negative could be recent-regime favorability, not durable improvement.

### If pursued further (concrete next levers)
1. **Lift Sortino, not MAR** — the 12mo passes MAR but fails Sortino; the gap is downside variance. Tighter stop geometry / faster cut on failed breakouts / capping per-trade loss could raise Sortino above 1.0 without hurting MAR.
2. **Diagnose the 24mo drag** — isolate the earlier-12mo losers: regime (was small-cap momentum dead in 2024-25?) or a fixable setup subtype?
3. **Kill the residual look-ahead** — re-run with a causal intraday-spike-time gate (entries only allowed after the spike bar) to confirm the 12mo MAR 0.74 survives.
4. **Widen the universe** to the full market (not the 662-symbol cache) for a real-power sample.
