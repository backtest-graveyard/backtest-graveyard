# Market-Neutral Statistical Arbitrage Bot — Post-Mortem

**Dates:** 2026-07-18 → 2026-07-19 · **Outcome:** shelved as a validated negative
**Verdict in one line:** no robust, deployable retail edge was found; the reusable, cost-first,
default-to-reject research pipeline (`statarb/`) is the real deliverable.

---

## 1. What we set out to build

A market-neutral (net beta ≈ 0) statistical-arbitrage bot: alpha from mean-reversion / cointegration /
cross-sectional mispricing, not market direction. Non-negotiables set at the start: model transaction cost
*before* hunting signal; validate ruthlessly with a default-to-reject pipeline; keep any LLM layer
subordinate. Venue Alpaca, paper-first, willing to fund six figures *if* it cleared validation.

**KPI bar (held throughout):** MAR ≥ 0.5 **and** Sortino ≥ 1.0, net of 2× modeled cost, on an untouched
holdout, after multiple-testing deflation. Win rate is a descriptor, never a gate.

---

## 2. What we built (the rig — this is what survives)

A self-contained package, `Claude Trading/statarb/`:

| Module | Role |
|---|---|
| `costs.py` | Shared cost model (vol-aware sqrt impact, mixed-fill spread, borrow, stress multiplier, no-trade band). One source of truth imported by backtest *and* (would-be) live. |
| `data.py` | Point-in-time daily panel: yfinance (consolidated prices/ADV) + Alpaca fetcher; per-name σ, ADV, spread. |
| `cointegration.py` | Engle-Granger + Johansen + OU half-life + amplitude "kill-test". |
| `scan.py` | Curated market-wide amplitude sweep (economic-prior gated, trials counted). |
| `backtest.py` | Causal event-driven pair backtester (rolling hedge ratio + rolling z, realized reversion, cost-charged, train/holdout, cost-stress). |
| `pca_book.py` | Avellaneda-Lee PCA factor-residual book (rolling factors → OU s-scores → dollar-neutral reversion), with per-name contribution + subset-trading hooks. |
| `phase0_spreads.py` | Real SIP intraday spread measurement across a universe. |

**Data:** the SIP feed (Alpaca Algo Trader Plus, ~$1,089/yr) turned out to be **already owned** and
org-wide — so measured quotes cost $0 marginal.

---

## 3. What we tested, and what killed each candidate

Every strategy family failed a *different* honest gate — none was tuned to force a pass.

**A. ETF / basket cointegration pairs — spurious.**
- Amplitude screen (47 curated spreads) correctly killed near-redundant twins (SPY/IVV/VOO cost > edge) and
  flagged a precious-metals-miner family + credit spreads.
- **Realized** backtest: the metals family book scored **holdout 2× Sortino 0.08 / MAR 0.07** (≈ flat).
  Credit sleeve was net-negative. **All 15 amplitude-passers → 0 cleared the bar.**
- Root cause: reversion didn't materialize (holds ran 42–52d vs 17–29d half-lives), edges non-stationary,
  and the family was really one factor. **Lesson banked: amplitude ≠ edge (confirmed three independent ways).**

**B. PCA single-name residual book — real gross edge, killed by fragility.**
- **Gross** edge was real and the only genuine signal found all session: holdout Sortino ~1.1–1.3.
- First verdict "fails" was **wrong** — it charged Corwin-Schultz spread estimates that were garbage for a
  third of names (mean 21.5 bps; HON estimated at 108 bps vs ~27 real). Fixing to **measured** spreads
  (~6 bps) flipped it to a borderline **pass**: holdout 2× Sortino 1.53 / MAR 0.94.
- Pressure test #1 (time-varying historical spreads, measured 2020–26) — **survived** (Sortino ~1.81);
  spreads were consistently tight, so "today's spreads on old history" was not the optimism feared.
- Pressure test #2 (breadth/robustness) — **failed decisively.** Only 55/96 names net-positive; the top-5
  names were 27% of positive P&L; **dropping the top 5 flipped the book to a loss (Sortino 1.53 → −0.51).**
  The "edge" was carried by a handful of names.

**C. "Trade the winning names" agent — adds nothing.**
- Winner P&L does not persist train→holdout (Spearman −0.12; train-top-15 did *worse* than train-bottom-15).
- No ex-ante feature pinpoints winners: best was idiosyncratic volatility (Spearman +0.25) — fails
  Bonferroni, explains ~6%, and missed 3 of the 5 winners. Crucially it predicts P&L **magnitude, not sign**
  (which *is* the source of the fragility).
- A "both-lenses" filter (12 names) looked good per-name, but the **past-year backtest with a random control
  settled it**: Sortino 0.73 = **55th percentile of random 12-name books**, and concentrating was *worse*
  than the full book (0.73 vs 0.97 Sortino, 2× the drawdown). Identification added nothing; the return was
  the base rate of concentrated books, not skill.

---

## 4. The two reversals (documented honestly)

**Reversal 1 — cost & data assumptions (early, healthy).** A flat impact coefficient over-charged small
trades 5–10×; switched to a volatility-aware sqrt-impact law. Separately, the initial "Alpaca IEX primary"
data call was **walked back on evidence**: IEX daily volume is venue-local (understated ADV 30–150×, per-name
varying) and IEX quotes were stale/crossed (SPY snapshotted at 601 bps). Moved to yfinance for
prices/ADV and SIP for measured spreads.

**Reversal 2 — the PCA verdict: fail → pass → fail.** This is the one that matters, and it exposed a real
process weakness:
- "Fail" was an **artifact of garbage spread estimates** (Corwin-Schultz), not a real result — and it
  poisoned a whole confident "uneconomic at retail" narrative (including the beginner-level "toll" analogy)
  that was mechanically wrong.
- "Pass" was arithmetically correct once real spreads were used — but was stated **too confidently**. It
  should always have read "clears the threshold, untrusted pending robustness testing."
- "Fail" (final) came from an **adversarial** test (remove the best names) that a real edge survives and
  this one didn't.

The trajectory was convergence-through-testing, not random flip-flopping — each step removed an error. But
the intermediate "pass" language over-claimed, and that is the single biggest process lesson (see §5).

---

## 5. Process lessons

**What worked (keep doing):**
- **Cost-first.** Modeling realistic cost before signal-hunting killed the un-tradeable ideas cheaply.
- **Necessary-not-sufficient screens.** The amplitude screen was a filter, never a verdict; the realized
  backtest was the judge.
- **Causality / point-in-time everywhere.** Rolling hedge ratios and rolling z-scores; no full-sample fit.
- **Adversarial verification + controls.** Drop-top-names and random-subset controls are what caught the
  fragility and the selection illusion. A "pass" is weak evidence; a result that *dies under stress* is
  strong evidence. This asymmetry is the backbone of trusting any backtest.
- **Measured data over estimators.** Corwin-Schultz was dangerous; one month of real SIP quotes flipped a
  verdict. Estimators are a fallback, never a foundation for a go/no-go.

**What to do better:**
- **Don't say "pass" before robustness.** State a threshold-clearing result as provisional until it survives
  adversarial stress. The confident intermediate "pass" cost credibility and had to be walked back.
- **Distrust free micro-structure estimators sooner.** CS spreads should have been measured before, not
  after, they drove a conclusion.
- **Watch overfitting-by-iteration.** Trying successive selection rules against one holdout *is* the
  overfitting machine. Random-subset controls and a hard "the holdout is spent" rule are the guards.

---

## 6. What would have to be structurally different for this to work

The PCA edge was **real but two things doom it at retail:**

1. **Execution cost.** The edge lives at high turnover, where the spread you pay rivals the edge per trade.
   Institutional desks clear this with sub-basis-point cost — co-location, internalized crossing, and being
   *paid* to provide liquidity. The only retail lever that could flip the sign is **passive, liquidity-
   providing execution** (earn the spread instead of paying it). A full study protocol exists
   (`STATARB_PASSIVE_EXECUTION_STUDY_2026_07_19.md`), but it is a long shot: liquidity provision is exactly
   where retail's lack of speed hurts most (you get picked off), and it needs live fill data no backtest can
   supply.

2. **A genuinely broad signal.** Real stat-arb is the law of large numbers — thousands of small, weakly-
   correlated bets. This book's edge concentrated in ~5 names; that is the opposite, and it is why it is both
   fragile and un-diversifiable. A deployable version would need an edge that is broad by construction, not
   one that happens to be carried by a few survivors.

For single-name work at scale, a **survivorship-safe dataset** (point-in-time membership + delisted names)
is also mandatory — deferred here because the free breadth check already showed fragility, making the spend
unnecessary.

---

## 7. Recommendation

- **Shelve stat-arb as a validated negative.** The bar is honest; it correctly rejected a lot of plausible
  ideas. That is a feature, not a disappointment.
- **Keep the rig.** `statarb/` is a reusable, cost-first, default-to-reject harness for vetting any future
  signal to the same standard.
- **Capital stays with what clears the bar.** The Markov bot remains the only strategy that passes; this
  exercise is good evidence the bar is real.
- If ever revisited: the *only* live thread is the passive-execution study — pursued as a small, bounded,
  live fill-rate experiment, with eyes open that it will most likely confirm "uneconomic for us."

---

## Appendix — key numbers

- Cost (vol-aware): liquid 3-bps-spread pair ≈ 15 bps round-trip; spread dominates cost → universe liquidity
  filter is the #1 cost lever.
- ETF pairs: 47 curated spreads screened, 15 amplitude-passed, **0** survived realized backtest.
- PCA book gross Sortino ~1.1–1.3; net (measured spread, 2× cost) holdout Sortino 1.53 → **−0.51 after
  dropping top-5 names.**
- Name selection: persistence Spearman −0.12; best feature (idio-vol) Spearman +0.25 (fails correction);
  both-high past-year Sortino 0.73 = 55th percentile of random 12-name books.
- Data: SIP already owned; measured large-cap spreads ~2–5 bps midday (not the 2 bps floor guessed, nor the
  CS-garbage 20+ bps).
