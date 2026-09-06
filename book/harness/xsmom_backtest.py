"""
xsmom_backtest.py — Cross-Sectional Momentum (the video's strategy #4), graded on the fleet bar.
================================================================================================
Video `nLQhKkjkuWI` @13:44: "instead of asking is this one stock trending, you RANK a whole
basket of assets against each other and only go long the strongest and short the weakest."
This is the one strategy from that video with NO fleet equivalent (Markov is regime/time-series
long-only; this is a cross-sectional long/short rank book). Testing whether it clears MY bar.

BAR (CLAUDE.md): MAR >= 0.5 AND Sortino >= 1.0 on the validation window, top-5 stripped still
positive, survives 2x cost. Grader = trend_analytics.perf_metrics (same MAR/Sortino the fleet uses).

CONSTRUCTION (faithful to the video, standard academic XSMOM — params NOT tuned to this data):
  signal_t   = trailing return over LOOKBACK days, skipping the most recent SKIP days
               (12-1 month momentum: LOOKBACK=252, SKIP=21 — skip avoids 1mo reversal).
  Each REBAL (monthly = 21 trading days): rank the available names by signal_t.
     L/S mode:  long the top TERCILE (eq-wt, sums to +1), short the bottom tercile (sums to -1)  -> dollar-neutral, gross 2.
     Long-only: long the top tercile (eq-wt, +1); no shorts (the variant YOU could actually run — paper accts don't model shorting).
  Weights set at close_t, HELD to next rebal; P&L earns w.shift(1)*ret (no look-ahead). Cost on turnover at rebal.
  RAGGED universe: at each rebal only names with a valid signal AND price that day are ranked, so
  crypto (BTC ~2014, ETH ~2017) joins when it exists instead of truncating 15y of equities/bonds.

Fixed gross exposure (no dynamic vol-target): MAR & Sortino are ~invariant to CONSTANT leverage,
so this isolates the signal's risk-adjusted quality — which is exactly what the bar measures.

Run:  python3 xsmom_backtest.py            (uses trend_core parquet cache; --refresh to re-pull)
"""
import sys
import numpy as np
import pandas as pd

import trend_core as tc
import trend_analytics as ta

START, END = "2010-01-01", "2026-06-30"
REFRESH = "--refresh" in sys.argv
COST_BPS = tc.COST_BPS          # 3 bps per unit turnover (fleet default)
REBAL = 21                       # monthly
TERCILE = 1.0 / 3.0

# ~28 liquid names spanning the video's stated universe: broad indices, all SPDR sectors,
# metals/energy/commodity, the Treasury/credit complex, mega-cap single names, + BTC/ETH.
UNIVERSE = [
    "SPY", "QQQ", "IWM", "DIA", "MDY",                       # broad equity indices
    "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLU", "XLB",  # SPDR sectors
    "GLD", "SLV", "DBC", "USO", "UNG",                       # metals / energy / commodity
    "TLT", "IEF", "LQD", "HYG",                              # rates / credit
    "AAPL", "NVDA", "MSFT", "AMZN",                          # mega-cap single names
    "BTC-USD", "ETH-USD",                                    # crypto (ragged history)
]


def load_closes(universe, start, end, refresh):
    cols = {}
    for sym in universe:
        try:
            df = tc.load(sym, start, end, auto_adjust=True, refresh=refresh)
            cols[sym] = df["Close"]
        except Exception as e:
            print(f"  {sym:<9} FAILED ({e})")
    close = pd.DataFrame(cols).sort_index()
    # business-day index; crypto trades weekends — restrict to days SPY trades so all
    # assets share one calendar (weekend crypto bars would desync the panel).
    close = close.loc[close["SPY"].notna()]
    return close


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
    """Zero the 5 best calendar months; recompute MAR/Sortino. Robustness analog of the
    fleet's 'strip top-5 names still positive' — is the edge broad or a few lucky windows?"""
    s = strat.dropna()
    monthly = s.groupby([s.index.year, s.index.month]).sum().sort_values(ascending=False)
    kill = set(monthly.index[:5])
    s2 = s.copy()
    mask = [( (idx.year, idx.month) in kill) for idx in s2.index]
    s2[mask] = 0.0
    eq = (1 + s2).cumprod()
    return ta.perf_metrics(eq, s2)


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
    m = ta.perf_metrics(r["equity"], r["daily_ret"])
    m2x = ta.perf_metrics(r2["equity"], r2["daily_ret"])
    strip = strip_top5_months(r["daily_ret"])
    verdict, reasons = grade(m, m2x, strip)
    return {"label": label, "m": m, "m2x": m2x, "strip": strip,
            "verdict": verdict, "reasons": reasons, "r": r}


def main():
    print("=" * 100)
    print("CROSS-SECTIONAL MOMENTUM (video strategy #4) vs the fleet bar (MAR>=0.5 & Sortino>=1.0)")
    print("=" * 100)
    close = load_closes(UNIVERSE, START, END, REFRESH)
    print(f"Loaded {close.shape[1]} names, {close.index[0].date()} -> {close.index[-1].date()}, "
          f"{close.shape[0]} bars\n")

    configs = [
        ("12-1 L/S  (long/short tercile, dollar-neutral)", 252, 21, "ls"),
        ("6-1  L/S  (long/short tercile, dollar-neutral)", 126, 21, "ls"),
        ("12-1 Long-only tercile (the variant YOU could run)", 252, 21, "long"),
        ("6-1  Long-only tercile",                          126, 21, "long"),
    ]
    results = [run_config(close, *c) for c in configs]

    print(f"{'Config':<52} {'MAR':>6} {'Sort':>6} {'Sharpe':>7} {'CAGR':>7} {'MaxDD':>7} {'2xMAR':>6} {'verdict':>8}")
    print("-" * 100)
    for x in results:
        m, m2x = x["m"], x["m2x"]
        print(f"{x['label']:<52} {m['mar']:>6.2f} {m['sortino']:>6.2f} {m['sharpe']:>7.2f} "
              f"{m['cagr']*100:>6.1f}% {m['max_dd']*100:>6.1f}% {m2x['mar']:>6.2f} {x['verdict']:>8}")

    # detail on the strongest config for the write-up
    best = max(results, key=lambda x: (x['m']['mar'] if not np.isnan(x['m']['mar']) else -9))
    print("\n" + "=" * 100)
    print(f"DETAIL — strongest config: {best['label']}")
    print("=" * 100)
    m, strip = best["m"], best["strip"]
    print(f"  Full:            MAR {m['mar']:.2f} | Sortino {m['sortino']:.2f} | CAGR {m['cagr']*100:.1f}% | MaxDD {m['max_dd']*100:.1f}%")
    print(f"  Strip top-5 mo:  MAR {strip['mar']:.2f} | Sortino {strip['sortino']:.2f} | total {strip['total_return']*100:+.1f}%  "
          f"({'still positive' if strip['total_return']>0 else 'GOES NEGATIVE'})")
    ap = best["r"]["asset_pnl"].sort_values(ascending=False)
    tot = ap.sum()
    top5 = ap.head(5).sum()
    print(f"  Per-asset P&L concentration: top-5 names = {top5/tot*100:.0f}% of gross P&L" if tot != 0 else "")
    print("    top +:", ", ".join(f"{k}:{v*100:+.0f}%" for k, v in ap.head(5).items()))
    print("    top -:", ", ".join(f"{k}:{v*100:+.0f}%" for k, v in ap.tail(3).items()))

    # walk-forward halves on the best config
    print("\n  Walk-forward halves:")
    pr = best["r"]["daily_ret"]
    for name, lo, hi in [("2011-2018", "2011", "2018"), ("2019-2026", "2019", "2026")]:
        seg = pr.loc[lo:hi].dropna()
        if len(seg) < 250:
            continue
        mm = ta.perf_metrics((1 + seg).cumprod(), seg)
        print(f"    {name}: MAR {mm['mar']:>5.2f} | Sortino {mm['sortino']:>5.2f} | CAGR {mm['cagr']*100:>5.1f}% | MaxDD {mm['max_dd']*100:>6.1f}%")

    _write(close, results, best)
    print("\nResults written to XSMOM_RESULTS.md")


def _write(close, results, best):
    lines = [
        "# Cross-Sectional Momentum — video strategy #4 vs the fleet bar", "",
        f"Window {START} → {END}. Universe: {close.shape[1]} liquid names (broad indices, SPDR sectors, "
        "commodities, rates/credit, mega-cap singles, BTC/ETH ragged).",
        "Standard 12-1 / 6-1 momentum, monthly rebalance, tercile legs, eq-weight, fixed gross. "
        "Params NOT tuned to this data. Grader: trend_analytics (fleet MAR/Sortino).", "",
        "Bar = **MAR ≥ 0.5 AND Sortino ≥ 1.0**, top-5 stripped still positive, survives 2× cost.", "",
        "| Config | MAR | Sortino | Sharpe | CAGR | MaxDD | 2×MAR | Verdict |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for x in results:
        m, m2x = x["m"], x["m2x"]
        lines.append(f"| {x['label']} | {m['mar']:.2f} | {m['sortino']:.2f} | {m['sharpe']:.2f} | "
                     f"{m['cagr']*100:.1f}% | {m['max_dd']*100:.1f}% | {m2x['mar']:.2f} | {x['verdict']} |")
    m, strip = best["m"], best["strip"]
    ap = best["r"]["asset_pnl"].sort_values(ascending=False); tot = ap.sum()
    lines += ["", f"**Strongest config:** {best['label']} — "
              f"strip-top-5-months MAR {strip['mar']:.2f} / total {strip['total_return']*100:+.1f}% "
              f"({'positive' if strip['total_return']>0 else 'NEGATIVE'}); "
              f"top-5 names = {ap.head(5).sum()/tot*100:.0f}% of gross P&L." if tot != 0 else ""]
    if best["reasons"]:
        lines.append(f"Fail reasons: {'; '.join(best['reasons'])}.")
    with open("XSMOM_RESULTS.md", "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
