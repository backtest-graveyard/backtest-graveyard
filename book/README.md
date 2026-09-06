# The Backtest Graveyard — the book's receipts

Code and result files behind every number in *The Backtest Graveyard*.

The book's central claim is that you should not take anyone's word for a backtest,
including mine. This repository is what makes that checkable.

```
results/     the result file behind every figure in Appendix C, with its run date
harness/     the backtesters that produced them
killtests/   the kill tests as reusable functions — start here
MANIFEST.md  every chapter mapped to its result file and harness
```

Ground rules, licence, and the channel's per-episode receipts are in the
[repository root](../).

## Start here

If you run one thing from this repo, run `killtests/killtests.py` against your own
strategy. It has no dependencies beyond the standard library.

```python
from killtests import drop_top_n, matched_exposure, breadth, summary

# per-contributor P&L: per trade, per name, or per month — whichever unit
# your strategy actually makes decisions in
drop_top_n(pnl, n=5)
```

`drop_top_n` is the test that killed six of the fourteen strategies in this book,
*after* conventional metrics had cleared them. It reads the **shape** of the failure:

| Shape | Meaning |
|---|---|
| sign flip | no edge — losers were always losing, a few winners masked it |
| collapse to ~0 | the pattern may be real, the business is not |
| degrades, survives | a real edge, possibly too concentrated to trade |

`matched_exposure` is the second most valuable and the least known. In the book a
challenger returned +416% against an incumbent's +196% — at average gross exposure of
0.80 against 0.38. The entire advantage was leverage. Nothing in a standard
performance summary reveals that; you have to log exposure and look.

## What is here, and what is not

**Published:** result files with their original run dates; the harnesses; the shared
cost models; the kill tests.

**Not published, deliberately:**

- **Vendor data.** Licence terms do not permit redistributing Alpaca or FMP feeds.
  The code fetches; it does not ship the data.
- **Credentials and account identifiers.** Every key is read from the environment.
- **Live position history**, and the live-execution paths of any bot
  (`buffett_bot/bot.py`, `emailer.py`, `monitor.py` are omitted for this reason).

This is research tooling, not trading infrastructure. There is no order management,
no risk layer, and no live-trading path in what is published here.

## Reproducing a figure

Every result file carries the date it was produced and the harness that produced it.
`MANIFEST.md` maps each chapter to its sources.

Where a chapter's figures come from more than one run — the value screener has three
successive corrections, the pairs-trading book has a fail → pass → fail sequence —
**every stage is published, not just the final one.** The intermediate results are
where the method is visible.

## If you get a different answer

In rough order of likelihood:

1. **Data vintage.** Fundamentals get restated; vendor calendars get revised. If your
   source hands you today's version of an old filing, you will beat these numbers.
2. **Cost assumptions.** Check basis points per side *and* the cash rate.
3. **Window.** Ragged versus common windows move MAR substantially. Ours moved by a
   third — see `MARKOV_GRADE_RESULTS.md`, which carries the correction in full.
4. **Exposure.** If average gross exposure differs, it is not the same test.
5. **Universe.** The single largest source of divergence.

If you have checked all five and still disagree, open an issue with the run date and
parameters. I would rather be corrected in public than cited incorrectly.

## Known limitations

Stated here as well as in the book, because a repo that only advertises its strengths
is marketing:

- **One figure has no reproducible source.** The honest common-window MAR of 1.18 came
  from a script that no longer exists. It is flagged in Chapter 22, Appendix E, and in
  the results file itself.
- **Residual look-ahead in the gap screen.** It selects on the realised intraday high,
  which inflates the rebuilt figures by an unknown amount. Accepted and disclosed
  rather than fixed, because that strategy is rejected on concentration regardless.
- **Universe survivorship is only partially fixed** in the value screener. The
  five-year filing-history filter removes recent listings but not established
  companies added to an index mid-window.
- **Some samples are small**, and say so — the MACD probe is 22 days and 36 trades.

## Before publishing anything here

```bash
python3 scrub_audit.py     # from the repo root; exit 0 required
```

It refuses on secrets, credentials, contact details, and local filesystem paths, and
Luhn-validates candidate card numbers so the public post IDs cited as provenance do
not trip it.

## Licence

Code MIT, write-ups CC BY 4.0 — see the [repository root](../). Nothing here is
financial advice, and the results are historical simulations, which are not
predictions. See the book's front matter.
