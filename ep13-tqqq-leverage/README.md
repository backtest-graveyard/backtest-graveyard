# TQQQ "Just Buy 3x And Hold" — Kill-Test (Backtest Graveyard source)

**Date:** 2026-09-16 · **Channel:** The Backtest Graveyard
**Question:** the viral retail belief — *"just buy TQQQ (3x leveraged QQQ) and hold forever; leverage means more money."* Does it?
**Data:** daily, split- **and dividend-adjusted** (total return) closes for **TQQQ** and **QQQ** from **Alpaca SIP**, window **2016-01-04 → 2026-09-16** (2,691 trading days, 10.7 yrs). Code: `backtest_tqqq.py` (stdlib + no secrets, PII-clean, re-runnable).
**Data caveat (read this):** TQQQ's true inception is 2010-02-11, but the two free full-history feeds were unusable at run time — stooq.com now sits behind a JavaScript proof-of-work bot wall (I won't bypass bot-detection), and Yahoo's chart API hard-rate-limited this IP. Alpaca and Nasdaq both cap at ~10 years. So this test **omits the 2010-2015 bull run** — the exact stretch that turned ~$10k into ~$200k and makes the myth most seductive. Every result below therefore *understates* TQQQ's raw upside and is *conservative for the believer*. The drawdown, MAR, and verdict do not change: 2016-2026 already contains the −81.7% 2022 collapse, which is the whole point.
**Method:** all four strategies long-only, decided on the daily close, cash earns 0% (conservative). Ranked by **MAR = CAGR / MaxDD%** — the channel standard — because a strategy that makes more money while risking near-total ruin has not made you richer in any usable way.

## Headline

**TQQQ buy-and-hold had the highest total return AND the highest CAGR in the window — and still FAILED the channel's bar, finishing dead last but one on MAR.** It turned $1 into ~$32 (+3,097%) versus QQQ's ~$7 (+596%). That's the seductive part, and it's real. Then it lost **81.7%** peak-to-trough in 2022, stayed underwater for **1,111 days (3.0 years)**, and needed a **+445% gain just to break even.** More money — until it isn't.

## Results (ranked by MAR — the channel standard, not raw return)

| Rank | Strategy | Total Ret | CAGR | **MAR** | Sortino | Max DD | Worst Yr | Underwater | Vol | Bar |
|--:|---|--:|--:|--:|--:|--:|--:|--:|--:|:--:|
| 1 | TQQQ, only when QQQ > 200d SMA | +2,710% | 36.6% | **0.65** | 1.24 | −55.9% | 2022 −43.3% | 605 d | 48.2% | **PASS** |
| 2 | **QQQ buy & hold (the yardstick)** | +596% | 19.9% | **0.57** | 1.32 | −35.0% | 2022 −32.5% | 715 d | 22.2% | **PASS** |
| 3 | **TQQQ buy & hold (the myth)** | **+3,097%** | **38.2%** | **0.47** | 1.17 | **−81.7%** | 2022 −79.1% | **1,111 d** | 65.8% | **fail** |
| 4 | 50/50 TQQQ/cash, monthly rebal | +854% | 23.5% | 0.45 | 1.16 | −52.5% | 2022 −49.5% | 908 d | 31.4% | fail |

Bar to "pass": **MAR ≥ 0.50 AND Sortino ≥ 1.00.** The naked-leverage myth (row 3) is the only *TQQQ* strategy that fails outright, and it fails on the risk-adjusted number despite winning the raw-dollars contest. QQQ — boring, unleveraged, one-third the volatility — beats it on MAR by 21%.

## Kill-Test 1 — The Drawdown Reality

- TQQQ max drawdown: **−81.7%** (peak 2021-11-19 → trough 2022-12-28).
- A −81.7% drawdown needs a **+445%** gain to get back to even. QQQ's worst DD in the same window was −35.0% (needs +54%).
- Longest time underwater: **1,111 calendar days (~3.0 years)** — from the Nov-2021 peak, TQQQ did not make a new high until Dec-2024. Three years of holding a "winner" and being down the entire time.
- This is the number the myth never mentions. The person who bought the top in Nov-2021 was still underwater in late 2024 while the S&P was printing all-time highs.

## Kill-Test 2 — Volatility Decay / Path Dependence (3x daily ≠ 3x the index)

- QQQ total return: **+596%** (×6.96). TQQQ total return: **+3,097%** (×31.97).
- "Naive 3× on the return" would be +1,787% (×18.87). **Actual TQQQ multiple of QQQ's total return: 5.20× — NOT 3.0×.** In a bull-*dominated* window, sustained uptrends compound daily leverage *above* 3× on the way up. That's the trap: for years the myth looks *better* than advertised.
- The other face of path-dependence — the 2022 collapse (2021-11-19 → 2022-12-28): QQQ **−34.9%**, TQQQ **−81.7% = 2.34× the loss.** Same wrapper: >3× more money in the climb, ~2.3× more pain in the crash, and the crash is what ends the game.
- **The costless-3x comparison (the mechanic, self-built):** compounding 3×(QQQ daily return) with **no** cost would have made **×67**; real TQQQ made **×32 — barely half.** Implied all-in drag of the real wrapper vs a costless 3×: **~6.7%/yr.**

## Kill-Test 3 — Entry / Sequence Sensitivity (skill is not what's happening)

Same asset, same "buy and hold" rule, different start date:

| Bought | Total Ret to 2026-09-16 | CAGR | Max DD |
|---|--:|--:|--:|
| 2016-01-04 | +3,097% | 38.2% | −81.7% |
| 2018-01-02 | +1,076% | 32.7% | −81.7% |
| 2021-01-04 (near top) | +228% | 23.2% | −81.7% |
| 2022-01-03 (into the crash) | +67% | 11.5% | −81.0% |
| 2022-12-28 (the bottom) | +778% | **79.4%** | −58.0% |

Outcome is dominated by **when** you bought, not by any skill. Buying the 2021 top (+228%, 23% CAGR) versus the 2022 bottom (+778%, **79%** CAGR) is a different universe from the identical strategy. A YouTuber who "held TQQQ" and got rich mostly got a start date.

## Kill-Test 4 — Cost Sensitivity

- Even the **sticker** cost (~0.95%/yr: 0.84% expense ratio + a light financing assumption) shaves **10.6%** off the synthetic 3× terminal wealth over 10.7 years (×67 → ×61).
- But the **real** implied drag was **~6.7%/yr** (KT2). Why so much bigger? Financing on the ~2× *borrowed* notional scales with interest rates, so the drag was largest in 2022-2024 — exactly the years the leveraged long was already bleeding. (A slice of the gap is also that my synthetic uses QQQ *total return* as its base, ~1.5-2%/yr richer than the price index TQQQ actually tracks.) Cost compounds silently every single day; it is the rent you pay for the wrapper, and it is not fixed.

## The GREEN keeper (what the data actually supports)

- **A 200-day regime filter is the one honest partial win.** Holding TQQQ only while QQQ closed above its 200-day SMA, else cash: **MAR 0.65 vs 0.47**, max DD **−55.9% vs −81.7%**, Sortino **1.24 vs 1.17** — and it *passes* the bar while beating QQQ on MAR. It is not free money and it is not "buy and hold": it whipsaws, it still lost 44% in 2022, and it depends on a filter that can fail in the next regime. But it makes the honest point — **you have to actively manage leverage; you cannot just hold it.**
- The transferable line: **leverage multiplies your PATH, not your edge.** 3× a coin flip is still a coin flip, now with fatter tails. The only defensible use of a 3× sleeve is *small, capped, and on a bet you can stomach taking to near-zero* — never your core, never "just hold it forever."

## Verdict

**MORE MONEY, UNTIL IT ISN'T.** Buy-and-hold TQQQ genuinely made the most money and the highest CAGR in this window — and still failed the risk bar, because an 81.7% drawdown that needs +445% to recover and 3 years underwater is a game most humans get shaken out of before the payoff. Boring unleveraged QQQ beat it on every risk-adjusted measure. The myth isn't a lie about returns; it's a lie about *survival* — it quietly assumes you're a diamond-handed robot with no start-date luck and no financing bill. A managed 3× sleeve behind a trend filter is a real, if fragile, tool. "Just buy 3x and hold" is a way to turn a bull market into a story you tell in bankruptcy.

*Not investment advice. Total-return (split+dividend adjusted) daily data, TQQQ & QQQ, 2016-2026 (2010-2015 omitted — see data caveat; its omission only understates the myth's upside). Cash earns 0%. One person's research — could be wrong. If you find an error, open an issue.*
