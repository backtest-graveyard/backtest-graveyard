# DBMR v1 — Dip-Buy Mean-Reversion in Uptrends (equities pivot)

Window 2000-01-01 → 2026-06-30. Universe: 14 liquid ETFs (broad indices + SPDR sectors).
Long-only: buy RSI2<10 dips above SMA200; exit RSI2>70 / close>SMA5 / regime-off. Vol-targeted.
Standard Connors-style params (NOT tuned here); same params on every ETF. Grader: trend_analytics.

**Portfolio: MAR 0.12 | Sortino -0.23 | Sharpe -0.31 | CAGR 1.2% | MaxDD -10.2% | 2x-cost MAR 0.08/Sortino -0.33 | GRADE D**

Ship bar = MAR ≥ 0.5 AND Sortino ≥ 1.0. Grade reasons: below ship bar (MAR 0.12/Sortino -0.23 vs 0.5/1.0).

| ETF | MAR | Sortino | Total Ret | trades |
|---|---|---|---|---|
| Tech | 0.19 | -0.03 | +57.1% | 180 |
| Nasdaq100 | 0.15 | 0.00 | +66.9% | 202 |
| Dow | 0.14 | -0.09 | +35.0% | 205 |
| Discretionary | 0.12 | -0.01 | +63.1% | 227 |
| SP500 | 0.11 | -0.02 | +56.0% | 188 |
| Financials | 0.11 | -0.11 | +29.9% | 182 |
| Health | 0.09 | -0.09 | +37.9% | 205 |
| Industrials | 0.09 | -0.07 | +43.1% | 208 |
| MidCap | 0.09 | -0.10 | +32.8% | 206 |
| Energy | 0.08 | -0.14 | +25.5% | 180 |
| Staples | 0.07 | -0.16 | +19.2% | 206 |
| SmallCap | 0.06 | -0.12 | +29.1% | 190 |
| Materials | 0.01 | -0.22 | +3.8% | 199 |
| Utilities | 0.00 | -0.22 | +1.7% | 172 |

## Variant sweep + VERDICT (2026-07-10)

| Variant | MAR | Sortino | CAGR | MaxDD | WR | Grade |
|---|---|---|---|---|---|---|
| v1 (cash=0%) | 0.12 | −0.23 | 1.2% | −10.2% | 70% | D |
| v1 + rf carry 2% | 0.46 | 0.28 | 3.1% | −6.7% | 70% | D |
| v1 + rf carry 4% | 0.90 | 0.72 | 5.0% | −5.6% | 71% | D |
| wide RSI2<25 + rf 4% | 0.67 | 0.63 | 4.8% | −7.2% | 69% | D |
| wide RSI2<35 + rf 4% | 0.64 | 0.61 | 4.8% | −7.5% | 70% | D |

**REJECTED as a standalone bot.** The reversal edge is REAL and robust (70% WR, positive on all 14 ETFs,
top-5 trades = 3% of P&L, walk-forward stable — NOT a fat-tail lottery). But its active contribution is only
~1.2% CAGR because it sits in cash ~90% of the time. Fails Sortino ≥ 1.0 in every variant. The only MAR
"pass" (0.90 at 4% cash carry) is ~80% T-bill yield, not strategy alpha, and collapses to MAR 0.46 at 2%
carry — it's rate-regime-dependent carry, not an equity edge. Root cause: MR signals cluster in time (all
ETFs oversold together in selloffs) → feast-or-famine deployment; ETFs too correlated to stay invested. The
fix (many uncorrelated single names) needs survivorship-safe data, closed for $0 here.

**Salvage value:** the edge could serve as a CASH-DEPLOYMENT OVERLAY (dip-buy the idle cash in an existing
account) or a drawdown-reducer on a core long — NOT a standalone MAR/Sortino bot. Do not productionize as-is.
