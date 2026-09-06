# Overnight Effect — Earnings-Night-Only Evaluation (2026-08-23)

**Verdict: REJECTED.** The viral overnight-return anomaly is real, but it cannot be
concentrated into earnings nights. Earnings-night-only trading fixes the cost problem
and loses the edge: MAR 0.46 (MU) / 0.26 (NVDA), both under the 0.5 ship bar, and the
drop-top-5 kill test collapses returns to ~1% CAGR. Do not deploy either form.

---

## Origin

Viral Dividendology post (X, 2026-08-22): buying Micron at every close and selling at
every open since inception returns +138,330,342%; the reverse (open→close) returns
−99.2%. Source dataset: Bruce Knuteson's overnight/intraday research; related academic
work: Cooper, Cliff & Gulen (2008), Lou, Polk & Skouras (2019 JFE).

Two questions evaluated:
1. Is the claimed overnight/intraday split real? (**Yes.**)
2. Can it be harvested by trading only around earnings, where costs are negligible?
   (**No.**)

## Data & method

- **Prices:** Alpaca SIP daily bars, `adjustment=all`, 2016-01-04 → 2026-08-21
  (2,674 trading days). Independent of the tweet's dataset.
- **Earnings dates/times:** SEC EDGAR 8-K filings with Item 2.02, using
  `acceptanceDateTime` to classify AMC vs BMO. MU: 42/42 after-hours; NVDA: 42/44.
  No third-party earnings calendar involved.
- **Overnight return:** open(t+1)/close(t) spanning the announcement. **Intraday:**
  close(t)/open(t). Compounded, zero costs (i.e., best case for the strategy).
- Scripts: scratchpad `night_check.py`, `earnings_nights.py`, `kill_tests.py`
  (session-temporary; method fully described here).

## Result 1 — the anomaly replicates (2016 → 2026-08-21)

| Ticker | Overnight only | Intraday only | Buy & hold |
|---|---|---|---|
| MU   | +6,660% | +6.0%  | +7,067% |
| NVDA | +7,920% | +240%  | +27,194% |
| SPY  | +158%   | +74%   | +349% |

Essentially all of MU's decade return accrued while the market was closed. The tweet's
headline numbers are honest arithmetic — but assume ~2 frictionless auction fills per
day for decades. At even 5 bps per round trip, 2,674 days of daily trading multiplies
equity by ~0.26 (e^(−2674×0.0005)); at 10 bps, ~0.07. Every gain is short-term taxable.
Real-money proof: NightShares NSPY/NIWM launched June 2022 to harvest exactly this,
returned −6.9% vs S&P +22%, liquidated August 2023.

## Result 2 — earnings-night-only fails

Hold only over each earnings announcement night (~4 trades/yr, costs genuinely
negligible):

| | MU (42 nights) | NVDA (44 nights) |
|---|---|---|
| Cumulative | +125% (2.26x) | +146% (2.46x) |
| CAGR | +7.9% | +8.8% |
| Win rate | 57% | 52% |
| Avg gap | +2.2% | +2.4% |
| Best / worst single night | +18.1% / −13.3% | +26.1% / −19.3% |
| MaxDD | 17.4% | 34.3% |
| **MAR** | **0.46** | **0.26** |
| Sortino (annualized, per-event) | ~1.24 | ~1.15 |
| **Drop-top-5 winners** | **+0.7% CAGR** | **+1.6% CAGR** |

### Why it fails

1. **The anomaly doesn't live in earnings nights.** MU's 42 earnings nights compound
   to +125%; the other ~2,630 ordinary nights compound to roughly 30x. The overnight
   effect is a thin drip (~13 bps/night avg) spread across nearly every night — it
   cannot be concentrated into a few events, and concentration is the only way around
   the cost wall.
2. **Per-night edge is real but is just the known earnings-announcement premium.**
   ~2.2%/event ≈ 17× an ordinary night — but delivered as a coin-flip (52–57% WR)
   with −13% to −19% single-night tails.
3. **Fat-tail lottery profile.** Drop-top-5 collapses both books to ~1% CAGR — the
   same failure mode as the gap trader (2026-06-03 parity re-audit: top-3 trades =
   92% of profit). A handful of monster gaps (MU +18.1% 2024-09-26, +17.6%
   2026-06-25) ARE the strategy.
4. **Friendliest-possible sample.** 2016–2026 is an AI supercycle for both names;
   buy-and-hold MU did +7,067% over the same window. Even with that tailwind the
   strategy roughly earns T-bill-plus-a-bit while carrying pure gap risk.

## Result 3 — full pooled backtest (added same day, evening session)

Harness: `overnight_earnings_backtest.py` (new, 2026-08-23). Strategy version: pooled
earnings-night overnight hold, 25% of equity per event (same-night events share, cap
100%), MOC buy + MOO sell. Universe: 14 high-attention names (MU NVDA TSLA AMD MSTR
AAPL AMZN META GOOGL MSFT NFLX COIN PLTR SMCI), 396 events, 2016 → 2026-08-21.
Idle cash earns 0% (no T-bill carry credited).

**Headline (5 bps RT cost): PASSES both bars — but see the ex-ante kill test.**

| Book (5 bps) | Nights | Cum | CAGR | MaxDD | MAR | Sortino | PF | WR |
|---|---|---|---|---|---|---|---|---|
| POOLED 25%/event | 396 | 3.97x | +13.8% | 17.3% | **0.80** | **1.52** | 1.52 | 53% |
| drop-top-5 events | 396 | 3.02x | +11.0% | 17.3% | 0.63 | 1.23 | 1.42 | 51% |
| minus NVDA (best name) | 359 | 2.94x | +10.7% | 15.2% | 0.70 | 1.23 | 1.43 | 52% |

Costs barely matter at this trade count (~37 events/yr): MAR 0.85 / 0.80 / 0.74 at
0 / 5 / 10 bps. Per-year: positive 10 of 11 years (worst 2018 −1.4%). Halves looked
stable (MAR 0.88 first, 0.92 second). Per-name at full capital: only NVDA/PLTR/MU/MSFT
have real books; 10 of 14 names are noise or negative — the pooled pass is breadth.

**Ex-ante universe kill test — FAILS.** PLTR, COIN, MSTR, SMCI only became
"high-attention" after their runs (two didn't trade in 2016). Restricting to the 10
names a 2016 investor could plausibly have listed (MU NVDA TSLA AMD AAPL AMZN META
GOOGL MSFT NFLX):

| Ex-ante 10-name book (5 bps) | Cum | CAGR | MaxDD | MAR | Sortino |
|---|---|---|---|---|---|
| Full window | 2.74x | +10.0% | 15.9% | 0.62 | 1.40 |
| First half (2016-01 → 2021-04) | 2.12x | +15.2% | 13.8% | **1.10** | **2.52** |
| Second half (2021-05 → 2026-08) | 1.29x | +4.9% | 15.9% | **0.31** | **0.66** |
| Drop-top-5 events | 2.13x | +7.4% | 15.9% | **0.46** | 1.06 |

The ex-ante edge decayed by more than half after 2021 (below both bars), and drop-top-5
takes the full window under the MAR bar. The 14-name book's stable second half is
manufactured by hindsight names that were selected *because* they were hot in that
window. Classic post-publication decay hidden by universe selection.

**Backtest verdict: NOT SHIPPABLE.** The earnings-announcement premium was real and
strong pre-2021 in this universe; in the honestly-choosable universe it now sits at
roughly T-bill-plus-carry-risk levels.

## Result 4 — point-in-time dollar-volume universe (the salvage test) — FAILS

Harness: `overnight_earnings_ptuniverse.py` (2026-08-23). Spec declared before
running: 150-ticker broad US base list (megacaps, meme/retail names, fallen angels;
ADRs excluded by rule since foreign issuers file 6-Ks, not Item-2.02 8-Ks), ranked
by trailing 252-day mean dollar volume, top-N rebalanced quarterly, earnings nights
traded only for current members. Top-20 primary; top-10/30 disclosed robustness.
Same pooled book (25%/event, 5 bps). Window 2016-07 → 2026-08 (Alpaca lookback).

| Point-in-time book (5 bps) | Nights | CAGR | MAR | Sortino |
|---|---|---|---|---|
| TOP-10 full | 282 | +7.7% | 0.48 | 1.09 |
| TOP-10 second half | 141 | +5.4% | 0.34 | 0.69 |
| **TOP-20 full (primary)** | 437 | **+2.0%** | **0.07** | 0.30 |
| TOP-20 second half | 219 | −2.2% | −0.08 | −0.06 |
| TOP-20 last 3y | 137 | −5.5% | −0.19 | −0.32 |
| TOP-20 drop-top-5 events | 437 | −0.7% | −0.02 | 0.02 |
| TOP-30 full | 576 | −1.3% | −0.03 | 0.02 |
| TOP-30 second half | 288 | −9.2% | −0.25 | −0.49 |

Monotone: the wider (more honest) the universe, the worse the book. The sample
universes look right (2016: AAPL/META/AMZN/BAC...; 2021: TSLA/ZM/SHOP/ROKU/MRNA;
2026: NVDA/MU/PLTR/MSTR/HOOD), so the proxy is capturing attention — the edge just
isn't there ex-ante. Together with Result 3: the hand-picked 14-name "pass" was
hindsight selection (owning AI winners overnight = beta, not an earnings-night
effect). **Strategy CLOSED.**

Known residual holes (both favor the strategy, so the fail stands): TWTR/SQ had no
current CIK mapping → ~24 TWTR earnings nights missing 2016-22; base list written
today. Notable byproduct: **Alpaca SIP retains bars for delisted symbols** — all 144
base names returned data incl. TWTR, BBBY, SIVB, FIT, EXPR, RIDE, FSR. Survivorship-
aware backtests are possible for $0 when the ticker list is known; what's still
missing for free is point-in-time index membership.

## Standing conclusions

- Overnight/intraday split: **confirmed, not tradeable** (cost wall daily; lottery
  profile event-only). Same retail cost/speed wall that killed stat-arb
  (`STATARB_POSTMORTEM_2026_07_19.md`).
- Correct takeaway from the anomaly: returns accrue overnight → **stay invested**;
  do not day-trade the gap in either direction.
- FMP MCP note: `chart` and `calendar` endpoints are plan-gated as of 2026-08-23
  (all date ranges denied). EDGAR Item-2.02 8-Ks + `acceptanceDateTime` is a free,
  authoritative substitute for earnings dates/times.
