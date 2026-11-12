# 4-Hour vs Daily, Crypto: The Re-Test (Backtest Graveyard source)

**Episode:** Ep20 · **Channel:** The Backtest Graveyard
**Question:** crypto traders say it constantly. Drop down to the 4-hour chart, it beats the daily. In May 2026 I tested that, and my research notes said no, the daily edged it (MAR 0.31 vs 0.27). That note was never a video. Before making this one I re-ran the same test on my current code, and it came out the other way. So the real question here is which answer to believe, and why a test flips when the market didn't change.
**Data:** Alpaca v1beta3 crypto bars, **BTC/USD and ETH/USD**. Window **2021-09-16 → 2026-09-16**, 5 years: 2,047 daily bars and 12,281 4-hour bars per pair, plus a 220-day warmup to seed the 200-day average.
**Method:** a Donchian breakout trend follower, long only. Buy when price closes above its highest close of the prior N days, exit on a 4× ATR trailing stop or a close below the lowest close of the prior M days. A BTC daily 200-day average sets the regime for both timeframes:

- **BULL** (BTC ≥ 1.05× its 200-day): 1.5% risk per trade, up to 4 positions.
- **NEUTRAL** (BTC between its 200-day and 1.05× it): 1% risk, up to 3 positions.
- **BEAR** (BTC below its 200-day): no new entries.

Non-compounding **$249,771** fixed budget, **0.10% slippage per side** on every fill. Both timeframes run the identical rules. The one thing that differs is the bar size.

**The fair-fight part:** lookbacks are set in days and scaled to bars, and the 14-period ATR is held to **14 calendar days** on both charts: 14 bars on the daily, 84 bars on the 4-hour. Without that, the 4-hour would get a stop about six times tighter just because its bars are smaller, and it would win for a dumb reason.

Ranked by **MAR = CAGR / max drawdown**, the channel standard.

## Headline

**The 4-hour won, and it wasn't close.** +$82,798 vs +$54,489 over five years, MAR **0.64 vs 0.32**, Sortino 1.76 vs 0.92, and a shallower worst drop, **9.4% vs 12.7%**. Re-running the May note's own dates with full data still flips it (MAR 0.70 vs 0.31), so it wasn't the window rolling forward. It wasn't the code either: the May code is the same code. The May 4-hour run was missing almost all of its Ethereum data. My old answer just doesn't hold any more.

Before anyone switches charts, it's thinner than that. **Ethereum carries it.** The Bitcoin half leans on one trade. The 4-hour does about 3× the trades at the same per-trade cost, which real execution wouldn't give it. And it's one five-year sample with 49% of its days in the BULL regime.

## Results

### Combined (BTC + ETH), each timeframe's best setting

| Rank | Timeframe | Setting | P&L | Return | CAGR | **MAR** | Sortino | Max DD | Win% | Trades | Avg hold | PF |
|--:|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | **4-hour** | 30d / 15d | **+$82,798** | +33.1% | 6.0% | **0.64** | 1.76 | 9.4% | 42% | 107 | 4.8 d | 1.56 |
| 2 | Daily | 55d / 20d | +$54,489 | +21.8% | 4.1% | 0.32 | 0.92 | 12.7% | 43% | 37 | 24.6 d | 1.71 |

**Read this before you quote that table.** Each row is that timeframe's **best of three lookbacks** (20/10, 30/15 and 55/20 days), picked on MAR after the fact. The 4-hour's best was 30/15. The daily's best was 55/20. So the headline compares two different settings. That's why the full sweep is right below.

### All six runs (combined)

| Timeframe | Setting | P&L | **MAR** | Sortino | Max DD | Win% | Trades |
|---|---|--:|--:|--:|--:|--:|--:|
| Daily | 20d / 10d | +$47,473 | 0.29 | 0.87 | 12.3% | 42% | 60 |
| Daily | 30d / 15d | +$30,647 | 0.19 | 0.53 | 12.3% | 48% | 46 |
| Daily | **55d / 20d** | +$54,489 | **0.32** | 0.92 | 12.7% | 43% | 37 |
| 4-hour | 20d / 10d | +$78,062 | 0.44 | 1.46 | 13.0% | 40% | 121 |
| 4-hour | **30d / 15d** | +$82,798 | **0.64** | 1.76 | 9.4% | 42% | 107 |
| 4-hour | 55d / 20d | +$73,696 | 0.57 | 1.66 | 9.4% | 38% | 98 |

**Every 4-hour setting beat every daily setting on MAR.** The worst 4-hour run (0.44) is still above the best daily run (0.32). Picking the best of three flatters both sides, but it doesn't decide the winner.

### Per coin (each timeframe's best setting)

| Timeframe | Coin | P&L | **MAR** | Sortino | Max DD | Win% | Trades | PF |
|---|---|--:|--:|--:|--:|--:|--:|--:|
| 4-hour (30/15) | ETH | +$54,280 | **0.74** | 1.60 | 5.5% | 43% | 51 | 1.74 |
| Daily (55/20) | ETH | +$42,396 | 0.58 | 1.31 | 5.6% | 50% | 18 | 2.20 |
| 4-hour (30/15) | BTC | +$28,518 | 0.23 | 0.93 | 9.6% | 41% | 56 | 1.38 |
| Daily (55/20) | BTC | +$12,094 | 0.11 | 0.34 | 8.9% | 37% | 19 | 1.29 |

## Kill-Test 1: Is it just the window?

The obvious excuse. Four months passed, the window rolled forward, of course the numbers moved. So I ran a **May-dated window (2021-05-12 → 2026-05-12)** on today's code. (The May note itself started on 2021-01-01; on that window, full data, the 4-hour wins too, MAR 0.70 vs 0.31. See `flip_diagnosis.md`.)

| Timeframe | 20d / 10d | 30d / 15d | 55d / 20d | Best P&L |
|---|--:|--:|--:|--:|
| Daily (MAR) | 0.26 | 0.14 | **0.28** | +$42,383 |
| 4-hour (MAR) | 0.38 | **0.57** | 0.44 | +$64,509 |

Still flipped, and every 4-hour setting beats every daily setting again. It wasn't the window. The first version of this README concluded "it was the code" from this. That was wrong, and the next section is the correction.

## Kill-Test 2: Why did it flip? A truncated download (corrected 2026-11-12)

**The first version of this section was wrong.** It said the May result came from an earlier, unpinned version of the code, and that regime sizing and the ATR trailing exit were added between the two runs. I found the May code since. It's the same code. What was different was the data.

The May 4-hour run sat on an ETH/USD 4-hour download that stopped at **2021-04-28**, about 4 months of a 5-year test. The backtester didn't complain. Evidence, all on the May note's window (2021-01-01 → 2026-05-12) with the May code:

- Full data: daily 20/10 **+$46,777, MAR 0.31**, the May note's number to the dollar. 4-hour 30/15 **+$86,462, MAR 0.70**.
- Keep only the first 706 ETH 4-hour bars (plus a BTC cut worth +$178): 4-hour 30/15 **+$31,622, MAR 0.27**, the May note's number to the dollar.
- The May code on September's windows reproduces September's numbers to the dollar.

The cut points came from a search, and why the download stopped isn't observed: the likeliest story is a paginated fetch that died partway. The exact-dollar match is the evidence. Details and steps are in `flip_diagnosis.md`.

The logs already disagreed with the old "bull-market size-up" story, and I'd rather you see it here than find it. Most of the profit came from the **NEUTRAL** regime, the one with the *smaller* size:

| Run | BULL trades | BULL P&L | NEUTRAL trades | NEUTRAL P&L |
|---|--:|--:|--:|--:|
| 4-hour 30/15 | 99 | +$30,680 | 8 | **+$52,118** |
| Daily 55/20 | 30 | +$15,738 | 7 | **+$38,751** |

So "the bull-market size-up is the engine" was at best part of it, even before the correction. Eight trades did most of the 4-hour's work.

## Kill-Test 3: Who's actually carrying the win?

**Ethereum.** The ETH 4-hour book made +$54,280 of the +$82,798, about two thirds, at MAR 0.74 across 51 trades. That's broad, not one lucky fill.

Bitcoin is the soft spot. Its 4-hour book made +$28,518 at MAR 0.23, and the single best trade was **+$43,078**, one October 2023 breakout. Take that one trade out and the BTC 4-hour book is down about $14,560. The 4-hour does beat the daily on BTC too (+$28,518 vs +$12,094), but "4-hour beats daily" is a statement about a two-coin basket, not a law for any coin you pick.

## Kill-Test 4: Costs held per side

Both timeframes pay the same **0.10% per side (0.20% round trip)** on every fill. The 4-hour makes 107 trades to the daily's 37, about 3×. In real life the 4-hour pays more in spread and slippage than the daily does, because it trades about three times as often. **This model doesn't charge it for that.** The gap is wide enough that a realistic cost bump probably narrows it rather than erases it, but I didn't test a higher cost for the 4-hour, so treat that as a guess.

## Kill-Test 5: One window, half of it in a bull

Five years, one sample. Of the window's days, **49% were BULL** (908), 4% NEUTRAL (80) and 47% BEAR (860), by the BTC 200-day rule above. A long-only trend system that sits out bear markets will tend to look decent in a window like that. It says nothing about whether the 4-hour edge holds somewhere else.

## The GREEN keeper

**Check the data, not just the code.** My May test ran a "5-year" backtest on 4 months of Ethereum and printed tidy numbers without a word of complaint. Count your candles, and check each symbol's first and last bar against the window you asked for. A backtest on missing data still prints confident numbers.

**And the real one: a backtest you ran once and wrote down is a photograph, not a fact.** My note said daily wins. It was quietly broken from the start, and I only found out because I re-ran it before quoting it. If I'd trusted the note I'd have made this video confidently wrong.

## Verdict

**REVERSED.** Should you believe the 4-hour beats the daily? Not the way it's sold. It won here, by a lot, on every setting. But it won with Ethereum doing the work, Bitcoin leaning on one trade, costs it didn't fully pay, and one five-year window. The only clean verdict is about me: my old answer was wrong, and I only know because I checked.

## What's in this folder

- `run_ep13.py`: the driver that produced everything here. It keeps its working name from when this test was slotted as an earlier episode. Two local paths in it were replaced with a comment and the script's own folder. The logic is untouched.
- `stats_full.json`: every scalar, both timeframes, all three lookbacks, per coin and combined. Floats are rounded to 6 decimal places (long float tails trip the repo's card-number check). No value changes at any precision quoted here.
- `curve_data.json`: equity curves normalized to 1.0 at the start (+P&L / budget, non-compounding) for each timeframe's best setting, combined and per coin.
- `charts/chart_flip.png`: the hero chart from the episode, drawn from `curve_data.json`.
- `flip_diagnosis.md`: why the May verdict flipped (a truncated ETH 4-hour download), with the reproduction numbers and steps.
- `logs/`: raw console output for the four runs. `daily_combined.log` and `4hour_combined.log` are the main window, `prior_window_daily.log` and `prior_window_4hour.log` are the May window. A three-line broker-connection banner at the top of each log was removed. Nothing else was edited.

## Reproduce (you can't, fully, and here's why)

`run_ep13.py` imports three modules from my private trading code, which isn't published:

- `crypto_client`: fetches the Alpaca crypto bars (`get_crypto_bars`).
- `crypto_backtester`: the simulation itself (`_simulate_pair`, `build_btc_regime`, `_stats`, plus `WARMUP_DAYS`, `ATR_PERIOD`, `SYSTEMS`, `BARS_PER_DAY`). The same file is already public in this repo at `book/harness/crypto_backtester.py`, so you can read the rules line by line. It still imports the other two.
- `config`: the budget and strategy constants (`CRYPTO_SPOT_BUDGET` and the regime, ATR and slippage settings listed in Method).

Without those, the driver won't run. **The results are reproducible only from the logs and stats in this folder.** Every number in this README traces to `stats_full.json` or the logs, except the May-window figures (0.27, 0.31, 0.70, +$31,622, +$46,777, +$86,462), which come from my research note and from the diagnosis runs in `flip_diagnosis.md`; those runs' raw logs aren't in this folder. The two derived figures are arithmetic on the logs: ETH's share (54,280 / 82,798) and BTC without its best trade (28,518 − 43,078).

Not investment advice. One person's research on two coins, and it could be wrong again. If you find an error, open an issue.
