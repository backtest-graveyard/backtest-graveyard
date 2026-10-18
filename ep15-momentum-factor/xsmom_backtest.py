#!/usr/bin/env python3
"""
xsmom_backtest.py -- Cross-sectional momentum, run on 16.5 years of public data.
The Backtest Graveyard, Ep15 ("The Momentum Factor, Retail Edition").

QUESTION: the academic momentum factor -- rank a basket by trailing return, buy the top third,
short the bottom third, rebalance monthly -- is the most documented anomaly in finance. Does the
version a regular person could run clear the channel's bar?

BAR: MAR (CAGR / |MaxDD|) >= 0.5 AND Sortino >= 1.0. Also reported: 2x-cost MAR, the strip-the-
5-best-months test, per-name P&L concentration, and the whole thing re-run with crypto removed.

CONSTRUCTION (standard academic XSMOM; params NOT tuned to this data):
  signal_t   = trailing return over LOOKBACK days, skipping the most recent SKIP days
               (12-1 month momentum: LOOKBACK=252, SKIP=21 -- the skip avoids 1-month reversal).
  Each REBAL (monthly = 21 trading days): rank the available names by signal_t.
     L/S mode:  long the top TERCILE (eq-wt, sums to +1), short the bottom tercile (sums to -1)
                -> dollar-neutral, gross 2.
     Long-only: long the top tercile (eq-wt, +1); no shorts.
  Weights set at close_t, HELD to the next rebal; P&L earns w.shift(1)*ret (no look-ahead).
  Cost: 3 bps per unit of turnover at each rebalance (6 bps in the 2x-cost run).
  RAGGED universe: at each rebal only names with a valid signal AND a price that day are ranked,
  so crypto (BTC ~2014, ETH ~2017) joins when it exists instead of truncating the equity history.
  Fixed gross exposure (no vol-targeting): MAR and Sortino are ~invariant to constant leverage,
  so this isolates the signal's risk-adjusted quality, which is exactly what the bar measures.

DATA: Yahoo Finance daily bars via yfinance, auto-adjusted (total return), 2010-01-01 -> 2026-06-30,
restricted to days SPY trades so crypto weekend bars don't desync the panel. Downloads are
cached to ./cache/ (pickles) so re-runs are deterministic; delete the folder or pass --refresh to
re-pull. Yahoo revises history occasionally, so a fresh pull can move the second decimal.

Run:  pip install numpy pandas yfinance
      python3 xsmom_backtest.py            # writes RESULTS.md beside this file
"""
import os
import sys
import numpy as np
import pandas as pd

START, END = "2010-01-01", "2026-06-30"
REFRESH = "--refresh" in sys.argv
COST_BPS = 3                     # per unit of turnover
REBAL = 21                       # monthly
TERCILE = 1.0 / 3.0
RISK_FREE_RATE = 0.02            # Sortino/Sharpe hurdle
TRADING_DAYS = 252
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.environ.get("XSMOM_CACHE", os.path.join(HERE, "cache"))

# 29 liquid names: broad indices, all SPDR sectors, metals/energy/commodity, the Treasury/credit
# complex, mega-cap single names, + BTC/ETH.
UNIVERSE = [
    "SPY", "QQQ", "IWM", "DIA", "MDY",                       # broad equity indices
    "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLU", "XLB",  # SPDR sectors
    "GLD", "SLV", "DBC", "USO", "UNG",                       # metals / energy / commodity
    "TLT", "IEF", "LQD", "HYG",                              # rates / credit
    "AAPL", "NVDA", "MSFT", "AMZN",                          # mega-cap single names
    "BTC-USD", "ETH-USD",                                    # crypto (ragged history)
]
CRYPTO = ["BTC-USD", "ETH-USD"]


def load(symbol, start, end, refresh=False):
    """Download once (auto-adjusted daily bars), cache to a pickle."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"{symbol}_{start}_{end}_1.pkl")
    if os.path.exists(path) and not refresh:
        return pd.read_pickle(path)
    import yfinance as yf
    df = yf.download(symbol, start=start, end=end, interval="1d", progress=False, auto_adjust=True)
    if df.empty:
        raise RuntimeError(f"No data for {symbol}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close"]].dropna()
    df.to_pickle(path)
    return df


def load_closes(universe, start, end, refresh):
    cols = {}
    for sym in universe:
        try:
            cols[sym] = load(sym, start, end, refresh=refresh)["Close"]
        except Exception as e:
            print(f"  {sym:<9} FAILED ({e})")
    close = pd.DataFrame(cols).sort_index()
    close = close.loc[close["SPY"].notna()]
    return close


def perf_metrics(equity, daily_ret, periods_per_year=TRADING_DAYS, rf=RISK_FREE_RATE):
    """CAGR, max drawdown, MAR, Sortino, Sharpe from an equity curve + its daily returns."""
    equity = equity.dropna()
    daily_ret = daily_ret.fillna(0)
    start, end = equity.iloc[0], equity.iloc[-1]
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    total_ret = end / start - 1
    cagr = (end / start) ** (1 / years) - 1 if years > 0 and end > 0 else float("nan")
    drawdown = (equity - equity.cummax()) / equity.cummax()
    max_dd = drawdown.min()
    mar = cagr / abs(max_dd) if max_dd != 0 and not np.isnan(cagr) else float("nan")
    ann_ret = daily_ret.mean() * periods_per_year
    downside = daily_ret[daily_ret < 0]
    downside_std = downside.std() * np.sqrt(periods_per_year) if len(downside) else 0.0
    daily_std = daily_ret.std() * np.sqrt(periods_per_year)
    sortino = (ann_ret - rf) / downside_std if downside_std > 0 else float("nan")
    sharpe = (ann_ret - rf) / daily_std if daily_std > 0 else float("nan")
    return {"total_return": total_ret, "cagr": cagr, "max_dd": max_dd, "mar": mar,
            "sortino": sortino, "sharpe": sharpe, "years": years}


def backtest(close, lookback, skip, mode="ls", cost_bps=COST_BPS, rebal=REBAL):
    """Returns dict with equity, daily_ret, weights, per-asset contribution."""
    rets = close.pct_change()
    # signal at t uses prices up to t (close_{t-skip} / close_{t-skip-lookback} - 1) -> no look-ahead
    signal = close.shift(skip) / close.shift(skip + lookback) - 1.0

    dates = close.index
    W = pd.DataFrame(0.0, index=dates, columns=close.columns)
    warmup = lookback + skip + 5
    rebal_dates = dates[warmup::rebal]

    for dt in rebal_dates:
        s = signal.loc[dt]
        avail = s.dropna()
        # require the name to be actively priced at t (not a dead/pre-inception series)
        avail = avail[close.loc[dt, avail.index].notna()]
        n = len(avail)
        if n < 6:                       # need enough names to form terciles
            continue
        k = max(1, int(round(n * TERCILE)))
        ranked = avail.sort_values()
        longs = ranked.index[-k:]
        w = pd.Series(0.0, index=close.columns)
        w[longs] = 1.0 / k              # long leg sums to +1
        if mode == "ls":
            shorts = ranked.index[:k]
            w[shorts] = -1.0 / k        # short leg sums to -1 (dollar-neutral, gross 2)
        W.loc[dt] = w.values

    # hold target weights between rebalances
    W = W.replace(0.0, np.nan)
    W.loc[rebal_dates[0]:] = W.loc[rebal_dates[0]:].ffill()
    W = W.fillna(0.0)

    held = W.shift(1).fillna(0.0)                       # earn next-day return on yesterday's weights
    contrib = held * rets                               # per-asset daily P&L contribution
    gross = contrib.sum(axis=1)

    # turnover cost only on rebalance transitions (weights change)
    turnover = W.diff().abs().sum(axis=1).fillna(0.0)
    strat = gross - turnover * (cost_bps / 10_000.0)
    strat.iloc[:warmup] = np.nan

    equity = (1 + strat.fillna(0)).cumprod()
    asset_pnl = contrib.sum(axis=0)                    # total contribution per asset
    return {"equity": equity, "daily_ret": strat, "weights": W,
            "asset_pnl": asset_pnl, "turnover": turnover}


def strip_top5_months(strat):
    """Zero the 5 best calendar months; recompute MAR/Sortino. Is the edge broad, or a few
    lucky windows?"""
    s = strat.dropna()
    monthly = s.groupby([s.index.year, s.index.month]).sum().sort_values(ascending=False)
    kill = set(monthly.index[:5])
    s2 = s.copy()
    mask = [( (idx.year, idx.month) in kill) for idx in s2.index]
    s2[mask] = 0.0
    eq = (1 + s2).cumprod()
    return perf_metrics(eq, s2)


def grade(m, m2x, strip):
    reasons = []
    ok = True
    if np.isnan(m["mar"]) or m["mar"] < 0.5:
        ok = False; reasons.append(f"MAR {m['mar']:.2f}<0.5")
    if np.isnan(m["sortino"]) or m["sortino"] < 1.0:
        ok = False; reasons.append(f"Sortino {m['sortino']:.2f}<1.0")
    if np.isnan(m2x["mar"]) or m2x["mar"] < 0.5 or m2x["sortino"] < 1.0:
        reasons.append(f"2x-cost fails (MAR {m2x['mar']:.2f}/Sort {m2x['sortino']:.2f})")
    if strip["total_return"] <= 0:
        reasons.append("strip-top5-months goes negative")
    return ("PASS" if ok and not reasons else "FAIL"), reasons


def run_config(close, label, lookback, skip, mode):
    r = backtest(close, lookback, skip, mode=mode)
    r2 = backtest(close, lookback, skip, mode=mode, cost_bps=COST_BPS * 2)
    m = perf_metrics(r["equity"], r["daily_ret"])
    m2x = perf_metrics(r2["equity"], r2["daily_ret"])
    strip = strip_top5_months(r["daily_ret"])
    verdict, reasons = grade(m, m2x, strip)
    return {"label": label, "m": m, "m2x": m2x, "strip": strip,
            "verdict": verdict, "reasons": reasons, "r": r}


CONFIGS = [
    ("12-1 long/short (dollar-neutral)", 252, 21, "ls"),
    ("6-1 long/short (dollar-neutral)", 126, 21, "ls"),
    ("12-1 long-only top third", 252, 21, "long"),
    ("6-1 long-only top third", 126, 21, "long"),
]


def table(results):
    out = ["| Config | MAR | Sortino | CAGR | MaxDD | 2x-cost MAR | Verdict |", "|---|--:|--:|--:|--:|--:|:--:|"]
    for x in results:
        m, m2x = x["m"], x["m2x"]
        v = "PASS" if (m["mar"] >= 0.5 and m["sortino"] >= 1.0) else "FAIL"
        out.append(f"| {x['label']} | {m['mar']:.2f} | {m['sortino']:.2f} | {m['cagr']*100:.1f}% | "
                   f"{m['max_dd']*100:.1f}% | {m2x['mar']:.2f} | {v} |")
    return out


def main():
    close = load_closes(UNIVERSE, START, END, REFRESH)
    print(f"Loaded {close.shape[1]} names, {close.index[0].date()} -> {close.index[-1].date()}, {close.shape[0]} bars")
    results = [run_config(close, *c) for c in CONFIGS]
    no_crypto = close.drop(columns=[c for c in CRYPTO if c in close.columns])
    results_nc = [run_config(no_crypto, *c) for c in CONFIGS]

    best = max(results, key=lambda x: (x["m"]["mar"] if not np.isnan(x["m"]["mar"]) else -9))
    strip = best["strip"]
    ap = best["r"]["asset_pnl"].sort_values(ascending=False)
    tot = ap.sum()
    btc = close["BTC-USD"].dropna()

    lines = ["# Results (generated by xsmom_backtest.py)", "",
             f"Window {close.index[0].date()} -> {close.index[-1].date()}, {close.shape[1]} names. "
             "Bar = MAR >= 0.5 AND Sortino >= 1.0.", "", "## All four configs, full universe", ""]
    lines += table(results)
    lines += ["", f"## Strongest config: {best['label']}", "",
              f"- Strip the 5 best calendar months: MAR {strip['mar']:.2f}, Sortino {strip['sortino']:.2f}.",
              f"- Top-5 names = {ap.head(5).sum()/tot*100:.0f}% of gross P&L: "
              + ", ".join(f"{k} {v*100:+.0f}%" for k, v in ap.head(5).items()) + " (contribution).",
              f"- Bitcoin's own price move over its history in this panel: {(btc.iloc[-1]/btc.iloc[0]-1)*100:+,.0f}%.",
              "", "## Same four configs with BTC and ETH removed", ""]
    lines += table(results_nc)
    with open(os.path.join(HERE, "RESULTS.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
