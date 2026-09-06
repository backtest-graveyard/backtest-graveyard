"""
trend_analytics.py — Step 0 rubric/analytics harness for the IBKR trend-follower.
================================================================================
You can't grade what you don't measure. Every phase of the F->A+ remediation
plan runs its equity curve through this module so the same numbers are reported
each time, including the robustness stats that separate a real edge from a
fat-tail lottery (the gap-trader lesson).

Pure functions: they take an equity curve / daily-return series / trade list and
return metrics. No data download, no strategy logic here.

A+ profitability rubric (all must hold):
  - MAR >= 1.0 AND Sortino >= 1.5 on a >= 20y backtest
  - No single market > 35% of total P&L
  - Strip-top-5 trades stays positive
  - Positive in >= 70% of rolling 12-month windows
  - Still clears MAR>=0.5/Sortino>=1.0 at 2x modeled cost
"""

import numpy as np
import pandas as pd

RISK_FREE_RATE = 0.02
TRADING_DAYS = 252


# ----------------------------------------------------------------------------- core perf
def perf_metrics(equity: pd.Series, daily_ret: pd.Series,
                 periods_per_year: int = TRADING_DAYS, rf: float = RISK_FREE_RATE) -> dict:
    """Headline performance metrics from an equity curve + its daily returns.
    periods_per_year: 252 for business-day series, 365 for calendar-daily (e.g. crypto)."""
    equity = equity.dropna()
    daily_ret = daily_ret.fillna(0)
    start, end = equity.iloc[0], equity.iloc[-1]
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    total_ret = end / start - 1
    cagr = (end / start) ** (1 / years) - 1 if years > 0 and end > 0 else float("nan")

    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max
    max_dd = drawdown.min()
    mar = cagr / abs(max_dd) if max_dd != 0 and not np.isnan(cagr) else float("nan")

    ann_ret = daily_ret.mean() * periods_per_year
    downside = daily_ret[daily_ret < 0]
    downside_std = downside.std() * np.sqrt(periods_per_year) if len(downside) else 0.0
    daily_std = daily_ret.std() * np.sqrt(periods_per_year)
    sortino = (ann_ret - rf) / downside_std if downside_std > 0 else float("nan")
    sharpe = (ann_ret - rf) / daily_std if daily_std > 0 else float("nan")

    return {
        "start_equity": start, "end_equity": end, "total_return": total_ret,
        "cagr": cagr, "max_dd": max_dd, "mar": mar, "sortino": sortino,
        "sharpe": sharpe, "ann_vol": daily_std, "years": years,
    }


def trade_stats(trades: list) -> dict:
    """Win rate / profit factor / hold time from a list of trade dicts with 'return'."""
    n = len(trades)
    if n == 0:
        return {"n_trades": 0, "win_rate": 0.0, "profit_factor": 0.0, "avg_bars": 0.0}
    wins = [t for t in trades if t["return"] > 0]
    losses = [t for t in trades if t["return"] <= 0]
    gross_w = sum(t["return"] for t in wins)
    gross_l = abs(sum(t["return"] for t in losses))
    return {
        "n_trades": n,
        "win_rate": len(wins) / n,
        "profit_factor": gross_w / gross_l if gross_l > 0 else float("inf"),
        "avg_bars": float(np.mean([t.get("bars_held", 0) for t in trades])),
    }


# ----------------------------------------------------------------------------- robustness
def rolling_hit_rate(daily_ret: pd.Series, window: int = TRADING_DAYS) -> float:
    """Fraction of rolling `window`-period windows with positive cumulative return."""
    """Fraction of rolling `window`-day windows with positive cumulative return."""
    daily_ret = daily_ret.fillna(0)
    if len(daily_ret) < window:
        return float("nan")
    cum = (1 + daily_ret).cumprod()
    roll = cum / cum.shift(window) - 1
    roll = roll.dropna()
    return float((roll > 0).mean()) if len(roll) else float("nan")


def concentration(trades: list, top_n: int = 5) -> dict:
    """How much of total P&L comes from the top-N trades; does stripping them stay positive."""
    if not trades:
        return {"total": 0.0, "topN_share": float("nan"), "strip_topN_total": 0.0,
                "strip_topN_positive": False, "top_n": top_n}
    rets = sorted((t["return"] for t in trades), reverse=True)
    total = sum(rets)
    top_sum = sum(rets[:top_n])
    strip = total - top_sum
    return {
        "total": total,
        "topN_share": top_sum / total if total != 0 else float("nan"),
        "strip_topN_total": strip,
        "strip_topN_positive": strip > 0,
        "top_n": top_n,
    }


def market_attribution(per_market_ret: dict) -> dict:
    """Each market's share of summed total return. per_market_ret: label -> daily_ret series."""
    totals = {lbl: float((1 + r.fillna(0)).prod() - 1) for lbl, r in per_market_ret.items()}
    gross = sum(abs(v) for v in totals.values())
    return {
        "totals": totals,
        "max_share": max((abs(v) / gross for v in totals.values()), default=float("nan")) if gross > 0 else float("nan"),
        "n_positive": sum(1 for v in totals.values() if v > 0),
        "n_markets": len(totals),
    }


# ----------------------------------------------------------------------------- grading
def grade_profitability(m: dict, conc: dict, hit_rate: float,
                        attribution: dict | None = None,
                        cost2x_pass: bool | None = None) -> tuple[str, list]:
    """Map metrics to a letter grade against the remediation-plan rubric. Returns (grade, reasons)."""
    mar, sortino = m.get("mar", float("nan")), m.get("sortino", float("nan"))
    reasons = []

    def ok(x, bar):
        return (x is not None) and (not np.isnan(x)) and x >= bar

    # Hard floors first
    if np.isnan(mar) or np.isnan(sortino) or m["total_return"] <= 0:
        return "F", ["net-negative or undefined returns"]
    if not (ok(mar, 0.5) and ok(sortino, 1.0)):
        return "D", [f"below ship bar (MAR {mar:.2f}/Sortino {sortino:.2f} vs 0.5/1.0)"]

    # Above ship bar — grade the climb
    aplus = (ok(mar, 1.0) and ok(sortino, 1.5)
             and (attribution is None or attribution.get("max_share", 1) <= 0.35)
             and conc.get("strip_topN_positive", False)
             and ok(hit_rate, 0.70)
             and (cost2x_pass is not False))
    if aplus:
        return "A+", ["clears MAR>=1.0/Sortino>=1.5 + all robustness gates"]

    if ok(mar, 1.0) and ok(sortino, 1.5):
        if not conc.get("strip_topN_positive", False):
            reasons.append("fails strip-top-5 (fat-tailed)")
        if not ok(hit_rate, 0.70):
            reasons.append(f"rolling-12mo hit rate {hit_rate:.0%} < 70%")
        if attribution and attribution.get("max_share", 1) > 0.35:
            reasons.append(f"one market = {attribution['max_share']:.0%} of P&L")
        if cost2x_pass is False:
            reasons.append("fails 2x-cost stress")
        return "A-", reasons or ["strong but one robustness gate soft"]
    if ok(mar, 0.8) and ok(sortino, 1.2):
        return "B", [f"solid (MAR {mar:.2f}/Sortino {sortino:.2f}) but below A bar"]
    return "C", [f"clears ship bar only (MAR {mar:.2f}/Sortino {sortino:.2f})"]


# ----------------------------------------------------------------------------- reporting
def full_report(equity, daily_ret, trades, per_market_ret=None,
                cost2x_pass=None, label="STRATEGY",
                periods_per_year=TRADING_DAYS, rf=RISK_FREE_RATE, hit_window=TRADING_DAYS) -> dict:
    """One-call bundle: perf + trades + robustness + grade. Returns a dict; also printable."""
    m = perf_metrics(equity, daily_ret, periods_per_year=periods_per_year, rf=rf)
    ts = trade_stats(trades)
    hr = rolling_hit_rate(daily_ret, window=hit_window)
    conc = concentration(trades)
    attr = market_attribution(per_market_ret) if per_market_ret else None
    grade, reasons = grade_profitability(m, conc, hr, attr, cost2x_pass)
    return {"label": label, "perf": m, "trades": ts, "hit_rate": hr,
            "concentration": conc, "attribution": attr,
            "grade": grade, "grade_reasons": reasons}


def print_report(rep: dict):
    m, ts, conc = rep["perf"], rep["trades"], rep["concentration"]
    print(f"  {rep['label']:<22} | Ret: {m['total_return']*100:>7.1f}% | "
          f"CAGR: {m['cagr']*100:>5.1f}% | MaxDD: {m['max_dd']*100:>6.1f}% | "
          f"MAR: {m['mar']:>5.2f} | Sortino: {m['sortino']:>5.2f} | "
          f"Sharpe: {m['sharpe']:>5.2f}")
    extra = ""
    if not np.isnan(rep["hit_rate"]):
        extra += f"12mo-hit: {rep['hit_rate']*100:>4.0f}% | "
    if conc["n_trades"] if "n_trades" in conc else False:
        pass
    if not np.isnan(conc.get("topN_share", float("nan"))):
        extra += f"top5-share: {conc['topN_share']*100:>4.0f}% | strip5+: {conc['strip_topN_positive']} | "
    extra += f"WR: {ts['win_rate']*100:>4.0f}% | trades: {ts['n_trades']}"
    print(f"  {'':<22} | {extra}")
    print(f"  {'':<22} | GRADE: {rep['grade']}  ({'; '.join(rep['grade_reasons'])})")
