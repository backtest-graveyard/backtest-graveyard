# Findings — Fractional-Kelly Sizing on the Markov Fleet

**Date:** 2026-07-08
**Spec:** `FRACTIONAL_KELLY_SIZING_TEST_SPEC_2026_07_08.md`
**Harness:** `scripts/kelly_sizing_test.py` (reads live `fleet.json`, 9 enabled slots, vol-adaptive k=0.5 path — parity with `fleet_backtest.py`, 5y history, honest cost 15/8 bps).
**Result:** **REJECTED. Keep vol_target sizing.** Kelly improves Sortino modestly but *degrades* MAR at matched exposure, and the project ranks by MAR. No config change made.

---

## Numbers (matched average gross exposure — the MAR-fair comparison)

| Variant | avg grs | turn | Full ROI | Full MAR | Full Sortino | MaxDD | 12mo MAR | 12mo Sortino | top-5% |
|---|---|---|---|---|---|---|---|---|---|
| **vol_target (incumbent)** | 0.35 | 8.9% | +51.2% | **2.05** | 1.96 | **−6.2%** | 3.09 | 2.18 | 22% |
| kelly λ=0.25 | 0.49 | 9.8% | +56.2% | 1.73 | **2.20** | −8.0% | **3.16** | **2.40** | 21% |
| kelly λ=0.50 | 0.54 | 9.8% | +50.6% | 1.52 | 2.07 | −8.3% | 2.91 | 2.31 | 21% |
| kelly λ=1.00 (ruin check) | 0.58 | 9.9% | +47.6% | 1.42 | 2.05 | −8.5% | 2.72 | 2.19 | 21% |

*(Raw, un-matched Kelly ROI is much higher — e.g. +416% vs +196% on NVDA single-asset — but that is almost entirely higher average exposure, 0.80 vs 0.38, not better risk-adjustment. The matched-exposure rows strip that leverage effect out. That's the whole reason the control exists.)*

## Decision against the spec's five criteria (matched exposure)

1. **MAR ≥ incumbent, full window** — ❌ **FAIL.** 2.05 → 1.73 / 1.52 / 1.42. Kelly *loses* MAR, monotonically worse as λ rises.
2. **MAR & Sortino ≥ incumbent, OOS-12mo** — ⚠️ Split: 12mo MAR ties/edges up (3.16 vs 3.09 at λ=0.25) and 12mo Sortino improves, but full-window MAR fails, so the "both windows" test is not met.
3. **No worse max drawdown** — ❌ **FAIL.** MaxDD deepens −6.2% → −8.5% as λ rises.
4. **Concentration not materially higher** — ✅ Flat ~21–22% across all variants (see below).
5. **Parity green** — ✅ Incumbent series bit-identical with/without the new code path; Kelly positions well-formed in [0, 1].

Requires ALL to ship. Fails 1 and 3. **Reject.**

## Why (the mechanism, not just the numbers)

- Kelly sizes by **edge/variance**, so it piles size into high-conviction regime states. That **smooths day-to-day downside** → Sortino improves (λ=0.25: 1.96 → 2.20, +12%).
- But drawdowns are **path-dependent tail events**: when a big-conviction bet is wrong, the position is larger, so peak-to-trough **MaxDD deepens** → MAR falls. Sortino (per-day downside vol) and MAR (worst cumulative path) reward different things, and Kelly trades the latter for the former.
- **Full Kelly (λ=1) is strictly worse than λ=0.5 is worse than λ=0.25** on MAR — textbook over-betting of a noisy `μ̂` estimate. Exactly the failure mode the spec predicted; healthy confirmation the harness is behaving.
- The project gate is **MAR-primary** (MAR ≥ 0.5 is the ship bar; strategy selection ranks by MAR). vol_target's constant-risk scaling is already near-optimal for MAR on this fleet.

## The genuinely useful side finding

**Concentration is ~22% (top-5 days / total P&L) and flat across every variant.** Markov's edge is **broad-based, not a fat-tail lottery** — the opposite of the gap trader (top-3 trades = 92% of profit). In the RenTec/LLN language from the originating question: Markov actually *satisfies* the many-near-independent-bets condition that makes the "thin edge × large N" machinery work, which is *why* it clears the bar. The framing validates Markov's **structure** — it just doesn't follow that Kelly **sizing** helps, because vol-targeting already captures the risk-scaling benefit without over-betting the noisy per-state return estimate.

## Bottom line

The RenTec math ceiling for *our* fleet is already essentially realized by vol_target. Fractional Kelly is not a free MAR upgrade here — at matched risk it's a MAR downgrade for a Sortino uptick, and we rank by MAR. **Keep vol_target.** This lands right where the pre-registered prior put it (~30%: "most likely in-noise-to-negative on MAR"). Documented negative, filed alongside `PHASE_TIER2_FINDINGS.md` (inverse-vol, also rejected).

**No live/paper config touched.** `fleet.json` unchanged. New code (`kelly` mode in `position_size`, `sizing`/`return_pos` params in `strat_returns`, `scripts/kelly_sizing_test.py`) is additive and dormant unless explicitly invoked.
