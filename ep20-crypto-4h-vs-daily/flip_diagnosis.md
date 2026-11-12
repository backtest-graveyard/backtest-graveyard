# Why the May verdict flipped: a truncated ETH download

My May 2026 note said the daily beat the 4-hour (MAR 0.31 vs 0.27). The September re-run said the opposite. The first version of this folder blamed a code change between the two runs. That was wrong. The strategy code is the same in both, and the May 4-hour run was missing almost all of its Ethereum data.

## The numbers

All runs use the May code, the May note's window **2021-01-01 → 2026-05-12**, and the rules described in the README.

| Run | Setting | P&L | MAR | What it shows |
|---|---|--:|--:|---|
| Daily, full data | 20d / 10d | +$46,777 | 0.31 | The May note's daily number, to the dollar |
| 4-hour, full data | 30d / 15d | +$86,462 | 0.70 | Same code, same window, full data: the 4-hour wins |
| 4-hour, ETH cut at 706 bars | 30d / 15d | +$31,622 | 0.27 | The May note's 4-hour number, to the dollar |

The 4-hour row with the cut: ETH/USD keeps its first **706** 4-hour bars (last bar **2021-04-28 16:00 UTC**), about 4 months of a 5-year window. BTC/USD also has to be cut, at its first 10,425 bars (last bar 2025-10-04 16:00 UTC), to land on the exact dollar. The BTC cut is worth +$178. The ETH cut is the whole story.

Two more checks:

- **The May code on September's windows reproduces September's numbers to the dollar** (the tables in the README). Nothing in the strategy changed between the runs.
- **Alpaca's BTC/USD and ETH/USD history begins 2021-01-01**, the first day of the May window. So the BTC 200-day regime had no reading for roughly the window's first 200 days. That's true of every run on this window, full data or cut.

## What's measured and what's inferred

- **Measured:** the three rows above, and the September reproduction.
- **Found by search:** the cut points. I scanned ETH cuts from 400 to 900 bars against BTC cuts from 9,600 to 10,500 bars for a combined 30/15 P&L within $0.50 of $31,622. Exactly one pair matched. Its MAR (0.27) and its best setting (30/15 beat 20/10 at 0.24 and 55/20 at 0.15) also match the note.
- **Inferred, not observed:** why the download stopped. A 5-year 4-hour pull comes down in many paginated chunks, and the likeliest story is that one stopped partway and the backtester ran on what it got without complaint. I can't replay the May download, so the exact-dollar match is the evidence, not a log of the failure.

## Reproduce

You need the same three private modules the README lists, so this isn't runnable from the repo alone. The steps:

1. Fetch Alpaca v1beta3 bars for BTC/USD and ETH/USD, 1Day and 4Hour, from 2021-01-01 to 2026-05-12 (UTC dates, inclusive).
2. Build the BTC regime from the BTC/USD daily bars in that window.
3. Run each Turtle setting (20/10, 30/15, 55/20 days) with lookbacks and the 14-day ATR scaled to bars (×6 on the 4-hour), as in `run_ep13.py`.
4. Full data gives the first two rows. For the third, keep only the first 706 ETH/USD 4-hour bars and the first 10,425 BTC/USD 4-hour bars, and run 30/15.

The lesson: count the bars and check the first and last date per symbol before you trust any backtest's numbers.
