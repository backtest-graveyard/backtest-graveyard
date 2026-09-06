# VTI — DCA vs DCA + EMA200 dip-buy (daily chart)

- Window: 2016-10-17 → 2026-06-17  (9.6 yrs, 2,430 trading days)
- Baseline DCA: $20/day | Dip buy: $1,000 on each day price < EMA200 | Slippage 1bp | Commission $0
- Days below EMA200 (dip-buy days): 441 of 2,430 (18.1%)
- Final VTI price used: $365.76

| Strategy | Total deployed | Shares | Avg cost/share | Shares per $10k | End value |
|---|---|---|---|---|---|
| A) Plain DCA $20/day | $48,600 | 263.29 | $184.59 | 54.176 | $96,302 |
| B) DCA $20 + $1000 dip | $489,600 | 2,719.99 | $180.00 | 55.555 | $994,862 |
| C) Equal-$ DCA ($201.48/day) | $489,600 | 2,652.44 | $184.59 | 54.176 | $970,155 |

## The honest read

**Tilt benefit (B vs C, equal $489600 deployed):** the dip-tilt buys at an average cost of $180.00/share vs $184.59/share for plain DCA of the same dollars — a **+2.55%** improvement in shares-per-dollar (= +67.5 shares on $489,600).

**Funding reality:** the $1,000 dip rule deployed **$441,000** total over the 441 below-EMA days. The largest single below-EMA stretch demanded **$83,000** of cash sitting ready to deploy — on top of the $48,600 of daily DCA. You can only dip-buy if that cash actually exists when the dip comes.

**Plain-English:** B ends with the most shares, but mostly because it spent 10.1× more money. Comparing fairly (same dollars, row C), the EMA200 dip-tilt is worth a small, real edge — below-EMA days are genuinely cheaper on average, so you get a lower cost basis. It is not a huge effect, and it only works if you have the lump-sum cash ready during long drawdowns. It never sells, so unlike the flip strategy it cannot fall behind buy-and-hold.
