# Evaluation — "3-state HMM crushes factor investing" tweet (@RitOnchain, 2026-07-20)

**Source tweet:** https://x.com/ritonchain/status/2079121302502408512 — claims a Northwestern
study shows a 3-state Hidden Markov Model beats traditional factor investing on the S&P 500,
"dodges major crashes," and delivers ~2% annual alpha over standard factors.

**The actual paper:** Wang, Lin & Mikhelson, *Regime-Switching Factor Investing with Hidden
Markov Models*, Journal of Risk and Financial Management 13(12):311, Dec 2020 (MDPI).
Northwestern MSiA-affiliated. https://www.mdpi.com/1911-8074/13/12/311

---

## 1. What the paper actually does

- Trains a **Hidden Markov Model** on SPY history (Jan 2007 – Sep 2017) to infer *latent*
  market regimes — states are not observed, they're fit by expectation-maximization from
  return/volatility observations.
- Separately backtests a set of **factor long/short books** on S&P 500 constituents:
  value (book-value-per-share ÷ price), quality (operating income ÷ revenue), momentum
  (1-month price change), leveraged long/short.
- Measures which factor book performs best **conditional on each regime**, then builds a
  strategy that **switches which factor model is live** based on the currently detected regime.
- Out-of-sample test: **Sep 2017 – Apr 2020** (~31 months). Reports higher absolute returns
  and better benchmark metrics than any individual static factor model.

## 2. Credibility discount — read this before getting excited

| Issue | Why it matters |
|---|---|
| **OOS window is 31 months and ends April 2020** | It terminates *on the COVID crash*. A regime-switching model that goes defensive in Feb–Mar 2020 books an enormous one-event win. The "dodges major crashes" claim rests on essentially **one crash**. |
| **Venue** | MDPI/JRFM is a low-barrier open-access journal, not JF/JFE/RFS. This is a competent student-tier project, not a replicated result. |
| **Regime→factor mapping is fit in-sample** | "Which factor works in which regime" is chosen on 2007–2017 — 3 states × ~4 factor books is a small but real search space, and the mapping is exactly the kind of thing that decays. |
| **"2% annual alpha"** | That's the tweet's number, not a headline the abstract carries. Even taken at face value, 2%/yr over factors is inside the noise band of a 31-month sample. |
| **Smoothing / look-ahead risk** | HMM papers routinely report *Viterbi-smoothed* states, which use future observations to label the past. Only **filtered** (time-t) state probabilities are tradeable. The paper's write-up does not make this unambiguous. |

Bottom line: the finding is directionally plausible (regime conditioning helps) but the
evidence is thin, single-crash-driven, and the specific alpha figure should not be planned around.

## 3. How this compares to our Markov bot

Our bot (`~/Markov Bot/`) is **not** an HMM. Concretely:

| Dimension | Our Markov bot | Paper |
|---|---|---|
| State model | **Observable** Markov chain — regime labeled deterministically from trailing 20-day return vs a vol-adaptive threshold (`markov_bot.label_regimes:175`) | **Hidden** Markov Model — latent states inferred by EM from return/vol observations |
| States | 3 (Bull / Sideways / Bear) | 3 |
| What the regime drives | **Position size** — signal = `P(bull tomorrow) − P(bear tomorrow)` from a walk-forward 3×3 transition matrix, scaled by vol-target sizing | **Which factor model is live** — a strategy selector, not a sizer |
| Universe | 9 equal-weight slots, cross-asset (BTC, SOL, NVDA, AAPL, GLD, SLV, DBC, URA, USO) | S&P 500 constituents only, long/short with leverage |
| Where the edge comes from | Low cross-asset correlation (mean off-diag 0.117) + trend persistence in the transition matrix | Factor premia, conditionally selected |
| Evidence | 10y walk-forward, honest costs (15/8 bps), MAR 1.70 / Sortino 2.69 headline; cost-aware live config re-validated | 31 months OOS, one crash |

Same family name, different machine. Our regime label is the **input to sizing**; theirs is a
**switch between books**. The honest read is that our backtest evidence base is *stronger* than
the paper's, not weaker.

## 4. Is any of it adaptable?

**Two separable ideas. One is dead on arrival here, one is a cheap experiment.**

### 4a. Factor-model switching — not adaptable. Skip.
We have no factor book to switch between. Building one means an S&P-500-wide long/short
value/quality/momentum engine — a whole new bot, needing fundamental data we don't buy. And
our recent adjacent attempts all failed: stat-arb (validated-negative, commit 7fdf169),
equities MR dip-buy (rejected 2026-07-10), Markov concentration/core-tilt (rejected 2026-07-10).
Nothing here justifies opening that front.

### 4b. Swap our threshold label for an HMM label — a legitimate, cheap test.
This is the one genuinely portable piece. Replace `label_regimes()` (threshold on trailing
20-day return) with a Gaussian HMM fit on (return, realized-vol), emitting **filtered** state
probabilities. Everything downstream — transition matrix, `P(bull) − P(bear)` signal,
vol-target sizing, fleet, execution — stays identical. It is a pure label swap, which is
exactly the shape of the harness we already built for the regime-ensemble test
(`scripts/regime_ensemble_test.py`).

Arguments for:
- An HMM infers the vol/return *joint* structure rather than thresholding one statistic; it
  can separate "quiet grind up" from "violent rally" — our label cannot.
- It emits soft probabilities natively, which composes more cleanly with conviction sizing
  than a hard 3-way label.

Arguments against (why the prior is low, ~20–25%):
- **We already tested the nearest neighbour and it failed.** The regime-window ensemble
  (`REGIME_ENSEMBLE_FINDINGS_2026_07_08.md`) improved the full window and **lost the recent
  12 months** — the out-of-sample-decay signature. Conclusion recorded then: *"the regime
  label is not where remaining edge lives."* Combined with dead-band (rejected) and Kelly
  sizing (rejected), Phase-3 signal levers are documented as exhausted.
- **HMM adds real failure modes we don't have today:** state relabeling across refits (state 0
  is "bull" one day and "bear" the next), EM non-convergence, sensitivity to init seed, and
  the look-ahead trap if anyone reaches for smoothed states. Our current label is a two-line
  deterministic function with automatic live↔backtest parity.
- New dependency: `hmmlearn` + `sklearn` are **not installed** in the Markov venv today.

## 5. Recommendation

1. **Do not build the factor-switching strategy.** No data, no book, adjacent attempts all
   rejected.
2. **Optionally run one pre-registered HMM label-swap test** — a day of work, gated on the
   same six criteria as the regime-ensemble test (Sortino and matched-MAR must beat the
   incumbent on **both** the full window and the trailing-12mo window; robust across ≥3 of 4
   HMM configs; no turnover/concentration blowup; no badly degraded year). Filtered
   probabilities only — hard-fail the test if any smoothed state touches the signal path.
   Pre-register the ~20–25% prior so a marginal pass isn't talked into a ship.
3. **Do not change any live/paper config on the strength of a tweet.** Our incumbent label is
   backed by more evidence than the paper is.

## 6. Footnote worth knowing

Our Markov bot's strategy lineage traces to **Roan (@RohOnChain)** — see `Markov Bot/README.md`
line 4. The tweet under review is quote-tweeting that same account's "Trillion Dollar Equation"
thread. We are not looking at an independent discovery; we are looking at the same content
stream that produced the bot we already run.
