# Kronos Foundation Model — Quant Evaluation

*Assessed 2026-07-09. Sources: arXiv 2508.02739, GitHub shiyu-coder/Kronos, HuggingFace NeoQuasar/Kronos-*, Jonathan Kinlay's independent review (Feb 2026). The X/quantscience_ post itself is paywalled (HTTP 402); this assessment is built from the primary paper + repo + one skeptical practitioner review.*

## What Kronos actually is

Kronos is **not a trading strategy.** It is a *forecasting primitive* — an open-source, decoder-only transformer (a "GPT for candlesticks") from Tsinghua that predicts the next K-lines given a window of OHLCV history. Two-stage design: a learned tokenizer quantizes continuous OHLCV bars into discrete hierarchical tokens, then an autoregressive transformer predicts the next token, analogous to next-word prediction.

- **Model sizes:** mini 4.1M params / 2048 context, small 24.7M / 512, base 102.3M / 512. These are *tiny* by LLM standards.
- **Training:** ~12B K-line records across 45 global exchanges, autoregressive objective.
- **Outputs:** probabilistic multi-step forecasts of price + volume (demo uses `pred_len=120`).

So the question "how profitable is this strategy" is really two questions: (1) how good is the *forecast*, and (2) can that forecast be turned into economically exploitable alpha. The paper answers (1) well and (2) barely at all.

## Strategy mechanics / edge source

The paper's own "strategy" is a demo: use Kronos forecasts as a cross-sectional signal to rank/pick stocks for a long (or long-short) portfolio. The claimed edge is a **better short-horizon conditional forecast** of the return/vol distribution than prior time-series foundation models (TSFMs) or per-task baselines (ARIMA, LSTM, PatchTST, etc.).

Is the logic sound? **Partly.** The pretraining premise — that cross-asset, cross-market K-line structure transfers — is legitimate and is where the model genuinely shines (zero-shot generalization, volatility shape, synthetic-data fidelity). But the leap from "lower next-candle error" to "tradable alpha" is exactly the leap the paper does not make. Price returns are ~IID noise at the margin; training on 12B samples of near-noise mostly teaches the *shape of the noise distribution*, not an exploitable directional edge. Volatility and higher-moment structure are far more learnable than direction — which is why the vol and synthetic-generation results are more credible than the price-picking result.

## Profit potential — theoretical ceiling vs. realistic

**Headline numbers and what they hide:**
- "+93% RankIC vs. the leading TSFM, +87% vs. best non-pretrained baseline." These are **relative** improvements on a **statistical** metric. A 93% lift can mean RankIC 0.01 → 0.02. Both are tradable only cross-sectionally, at scale, with near-zero costs. The paper reports the portfolio sim had the *highest* annualized return and Sharpe of the compared methods — but publishes **no absolute Sharpe, return, drawdown, or turnover.** That omission is the whole ballgame.
- "9% lower MAE in volatility forecasting" and "22% better synthetic fidelity" — believable and genuinely useful, but these feed risk sizing and stress testing, not a P&L signal.

**Honest expectation:** As a standalone signal, treat realistic IC in the **0.02–0.05** range for a well-fit cross-sectional deployment — i.e., a *weak* alpha that only monetizes as one factor among many in a diversified, low-cost, high-breadth book. Gross Sharpe in a clean academic sim might look 1–2; **net** of realistic costs and capacity it is far more likely **0.3–0.8, and plausibly ≤0 at retail scale and cost structure.** This is a factor-blending input for a systematic desk, not a push-button money printer.

- **Best regime:** liquid, mean-reverting / vol-clustering environments; broad cross-sectional universes where many small edges aggregate; risk/vol forecasting and scenario generation.
- **Worst regime:** novel regimes with no historical analog (COVID crash, 2022 LDI/gilt crisis, 2023 regional-bank stress). A model that has only ever seen "normal-ish" candles is least reliable precisely when it matters most.

## Scalability & capacity

Capacity is governed by the *strategy*, not the model. Short-horizon cross-sectional signals with IC ~0.02–0.05 are **retail-to-mid-prop scale at best**. The edge is thin per name, so it needs breadth (hundreds of names) and low turnover to survive costs — the opposite of a concentrated retail book. At institutional AUM the signal decays under market impact well before it moves the needle. Verdict: **retail/small-prop as a research input; not an institutional capacity story on its own.**

## Execution realities

This is where most of the theoretical edge dies:
- **Costs vs. IC:** if per-trade edge is a few bps of expected return and round-trip cost (spread + commission + slippage) is comparable, the strategy is net-flat. The paper models none of this.
- **Turnover:** next-candle/short-horizon signals imply high turnover — the most cost-sensitive profile there is.
- **Latency/serving:** the base model is 102M params — cheap to run, but multi-sample ensembling (the paper improves IC by ensembling forecasts) multiplies inference cost and adds lag.
- **Point-in-time / leakage:** any real deployment must avoid survivorship and look-ahead bias in the universe and features — not addressed.
- **Black box:** unlike GARCH's interpretable parameters, Kronos gives no transparent risk decomposition, complicating sizing, risk management, and any compliance sign-off.

## Key risks & failure modes

1. **Statistical-not-economic gap** — the central flaw. Better MSE/RankIC ≠ profit after costs.
2. **Regime break / non-stationarity** — worst exactly when tail events hit; no evidence it handles unseen regimes.
3. **Crowding** — it's open-source and viral on X; any easy signal gets arbitraged fast.
4. **Overfitting the backtest** — no reported turnover/DD/capacity means the sim could be an artifact (small-cap, high-turnover, cost-free).
5. **Implementation drift** — the repo explicitly says the pipeline is a *demonstration, not a production system* and requires "portfolio optimization, risk-factor neutralization, position sizing, risk management" to be added by you.

## Verdict

**As a trading strategy: unproven and probably not profitable net-of-costs at retail scale. As a research tool: genuinely useful and worth a weekend.** The authors and the one serious independent reviewer agree: it's a promising forecasting model, *not* a production alpha engine. Kinlay's line is the right bar — "don't deploy for live trading until someone demonstrates economically exploitable returns after costs," and no one has yet published those.

**Theoretical ceiling:** a modest incremental factor (IC ~0.02–0.05) inside a diversified, low-cost systematic book, plus real value in **volatility forecasting and synthetic-data stress testing.**
**Realistic expectation at full deployment for a retail/small operator:** net Sharpe roughly **0.3–0.8, with a live-fails-to-replicate risk that is high.** The durable edge here is in **risk modeling and scenario generation, not directional signal.**

### If you want to test it honestly (cheap, in-house)
1. Zero-shot IC/RankIC on *your* universe, point-in-time, no fine-tuning — get the absolute number, not a relative lift.
2. Convert to a portfolio with **realistic costs, turnover caps, and capacity limits**; rank by **MAR and Sortino**, not raw return (per this project's bar: MAR ≥ 0.5, Sortino ≥ 1.0).
3. Stress the forecast across 2020 / 2022 / 2023 regime windows — measure degradation, not just full-sample averages.
4. Highest-value use first: feed Kronos **volatility** forecasts into position sizing for an *existing* strategy (e.g., Markov's vol_target), which is lower-risk than trusting its price direction.

Net: don't fund data or infra for this as a signal source. It's a "measure it in a notebook, maybe borrow its vol/synthetic capabilities" tool — not a deployable edge.

---

## EMPIRICAL TEST — Kronos vol forecast vs Markov's vol_target input (2026-07-10)

The one "maybe useful" thread above was Kronos's **volatility** forecast. I tested it head-to-head against Markov's actual sizing estimator. **Result: Kronos loses decisively — it is a materially worse vol forecaster than what Markov already uses, and worse than a one-line EWMA.**

**Setup (real inference, not asserted):**
- Model: **Kronos-base** (102M, full capability), CPU, cloned from source, weights from HuggingFace. Vol forecast = mean over 5 stochastic sample paths of the annualised std of predicted close-to-close returns over the horizon.
- Baselines: **incumbent(30)** = Markov's exact `rolling_annualised_vol` (trailing 30d, ddof=1, √365); **EWMA(0.94)** = RiskMetrics.
- Target: forward realised vol, horizon **h=10** trading days (the sizing-relevant multi-day horizon). Loss: MAE, RMSE, and **QLIKE** (robust vol loss). **409 eval points** across all 9 Markov assets (BTC, SOL, NVDA, AAPL, GLD, SLV, DBC, URA, USO), ~6-weekly grid over 2021–2026.

**Headline (lower = better):**

| Model | MAE | RMSE | QLIKE |
|---|---|---|---|
| Kronos-base | 0.553 | 1.216 | 0.706 |
| incumbent(30) | **0.137** | **0.224** | 0.304 |
| EWMA(0.94) | 0.137 | 0.227 | **0.268** |

- Kronos is **~4× worse on MAE, ~5× worse on RMSE, ~2.3× worse on QLIKE** than Markov's current estimator.
- Kronos beats the incumbent in only **27.6%** of cells, beats EWMA in **27.4%**.
- **Worse than BOTH baselines on all 9 assets** — no asset where Kronos wins. Worst case NVDA (QLIKE 1.42 vs incumbent 0.19): Kronos wildly mis-forecasts single-name equity vol.
- The RMSE of 1.22 (vs ~0.22) means Kronos periodically emits **catastrophically wrong** vol forecasts — its sampled paths sometimes explode or collapse. Feeding that into `vol_target / realized_vol` would drive position size 4–5× wrong on those bars. That's not a marginal loss; it's a sizing hazard.

**Phase-1 corollary (the free win):** across all assets/horizons, **EWMA(0.94) beat Markov's trailing-30d incumbent in 36/36 cells** on QLIKE (pooled horizons); at the specific h=10 monthly grid it still wins on aggregate QLIKE (0.268 vs 0.304) and on 6 of 9 assets. So the actual improvement available to Markov's sizing is **not Kronos — it's swapping the trailing-30d estimator for EWMA.** That is a one-line change with a real (if modest, ~12% QLIKE) forecast-accuracy edge.

**Verdict on the vol thread: REJECTED.** Kronos does not improve — it degrades — Markov's vol_target input. Don't wire it in. If anything is worth pursuing on Markov sizing, it's an **EWMA vol estimator**, gated the normal way (does it lift realized MAR/Sortino in a full backtest, with live↔backtest parity) before shipping. Combined with the signal test above, Kronos has now failed on both the only two plausible use cases for this fleet (directional signal: unproven/uneconomic; vol input: empirically worse). **Close the Kronos thread.**

*Repro: `scratchpad/kronos_test/` — `vol_harness.py` (baselines), `kr_grid.py` (Kronos), `kronos_results.csv` (409 rows), `baseline_results.csv`.*
