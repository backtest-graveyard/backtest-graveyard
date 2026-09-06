# The Backtest Graveyard

Receipts for the YouTube channel **[The Backtest Graveyard](https://www.youtube.com/@TheBacktestGraveyard)** — where viral trading strategies get tested with real data and honest kill tests, and the failures get published.

Each episode folder contains the full write-up, the backtest code, and the charts, so you can check the work. That's the whole point.

| Episode | Verdict |
|---|---|
| [01 — The Overnight Effect](ep01-overnight-effect/) | real anomaly, no tradable edge. DEAD. |
| [02 — Gap-and-Go](ep02-gap-and-go/) | real edge, not bottle-able. Teachable, not deployable. |
| [03 — The Kelly Criterion](ep03-kelly-sizing/) | the "optimal" bet size made a working bot worse. Keep boring sizing. |
| [04 — The 51% → $100B Math](ep04-rentec-51pct/) | every number's real, the edge is zero. Infrastructure, not a strategy. |
| [05 — GEX / Dealer Hedging](ep05-gex-dealer-hedging/) | half-real. A genuine vol-regime read, wrapped in a survivorship jackpot and a stale 0DTE signal. |
| [07 — Kronos, the "GPT for candlesticks" AI](ep07-kronos-foundation-model/) | a real forecaster, no proven edge — and 4–5× worse at vol than a 1990s one-liner. |
| [08 — The Viral "VIX Cheat Sheet"](ep08-vix-cheatsheet/) | half-true. "Buy the panic" is a real seatbelt, not an engine — and it still loses to buy-and-hold. |

## The book

**[The Backtest Graveyard](book/)** — the same method applied to fourteen strategies,
with the failures published. Thirteen are dead. The fourteenth is boring.

[`book/`](book/) holds the result file behind every figure in the book, the harnesses
that produced them, and — start here — [`book/killtests/killtests.py`](book/killtests/killtests.py),
the kill tests as importable functions with no dependencies beyond the standard
library. [`book/MANIFEST.md`](book/MANIFEST.md) maps every chapter to its sources.

The book and the channel overlap: several episodes above are chapters, and the
result files are shared. Where a verdict differs in wording, the book is the later
and more careful statement.

## Ground rules

- **Nothing is for sale.** No course, no Discord, no signals.
- **Nothing here is investment advice.** Not licensed for that. This is one person's research — could be right, could be wrong. If you find an error, open an issue; corrections get pinned.
- Code runs against your own market-data credentials (see each episode's notes). No data files with redistribution restrictions are included.
- AI tools assist in producing the videos and code; the experiments and opinions are the author's.

## License

Code: MIT (see [LICENSE](LICENSE)). Write-ups and charts: CC BY 4.0 — reuse with attribution to The Backtest Graveyard.
