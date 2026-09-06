#!/usr/bin/env python3
"""common_window_grade.py — grade the Markov fleet on an HONEST common window.

Why this exists
---------------
`grade_markov.py` builds its portfolio from the UNION of every asset's date index
and fills the gaps with 0.0:

    idx  = sorted(set().union(*[f.index for f in frames.values()]))
    rets = ...reindex(idx).fillna(0.0)

So in the years before an asset existed, that slot contributes a flat 0% every
day. Zeros are not neutral: they dilute portfolio volatility and drawdown while
the assets that DO exist keep supplying return. The result is a headline that
flatters itself, and it is the artifact behind the MAR 1.70 this project
published for months.

This script grades the same fleets on the intersection window — the range where
every slot is genuinely live — and prints both, so the size of the artifact is
visible rather than argued about.

It replaces `Markov Bot/scripts/test_portfolio_weights.py`, which produced the
corrected MAR 1.18 figure and was subsequently deleted from the repo, leaving
the most conservative number in The Backtest Graveyard with no reproducible
source. Run:  python3 common_window_grade.py
"""
import os
import sys
import numpy as np
import pandas as pd

os.environ.setdefault("PORT_SIZING", "vol_target")
os.environ.setdefault("PORT_VOL_TARGET", "0.40")
os.environ.setdefault("PORT_MAX_LEV", "1.0")
os.environ.setdefault("PORT_WEIGHTING", "equal")

MB = os.environ.get("MARKOV_ROOT", "<set MARKOV_ROOT>")
sys.path.insert(0, MB)
sys.path.insert(0, os.path.join(MB, "scripts"))

import trend_analytics as ta                      # noqa: E402
from portfolio import run_single_asset            # noqa: E402

YEARS = 10
PPY = 365
EXTRA_COST_PER_SIDE = 5.0 / 10_000.0

FLEETS = {
    "6-asset (README headline)": ["BTC-USD", "SOL-USD", "NVDA", "AAPL", "QQQ", "GLD"],
    "4-asset (active fleet)":    ["BTC-USD", "SOL-USD", "NVDA", "AAPL"],
}


def per_asset_frames(tickers):
    frames = {}
    for tk in tickers:
        df = run_single_asset(tk, YEARS)
        ret, pos = df[f"{tk}_ret"], df[f"{tk}_pos"]
        extra = EXTRA_COST_PER_SIDE * pos.diff().abs().fillna(0)
        frames[tk] = pd.DataFrame({"ret": ret, "ret2x": ret - extra})
    return frames


def assemble(frames, tickers, mode):
    """mode='ragged' reproduces grade_markov (union + fillna(0));
       mode='common' uses the intersection — every slot genuinely live."""
    if mode == "ragged":
        idx = sorted(set().union(*[f.index for f in frames.values()]))
        r = pd.DataFrame({tk: frames[tk]["ret"] for tk in tickers}).reindex(idx).fillna(0.0)
        r2 = pd.DataFrame({tk: frames[tk]["ret2x"] for tk in tickers}).reindex(idx).fillna(0.0)
    else:
        start = max(f["ret"].first_valid_index() for f in frames.values())
        end = min(f["ret"].last_valid_index() for f in frames.values())
        idx = sorted(set().union(*[f.index for f in frames.values()]))
        idx = [d for d in idx if start <= d <= end]
        r = pd.DataFrame({tk: frames[tk]["ret"] for tk in tickers}).reindex(idx).fillna(0.0)
        r2 = pd.DataFrame({tk: frames[tk]["ret2x"] for tk in tickers}).reindex(idx).fillna(0.0)
    w = np.ones(len(tickers)) / len(tickers)
    port = pd.Series(r.to_numpy() @ w, index=r.index)
    port2x = pd.Series(r2.to_numpy() @ w, index=r2.index)
    return port, port2x, {tk: r[tk] for tk in tickers}


def monthly_trades(port):
    eq = (1 + port).cumprod()
    m = eq.resample("ME").last().pct_change().dropna()
    return [{"return": float(x)} for x in m.values]


def grade(port, port2x, per_asset):
    mn = ta.perf_metrics((1 + port).cumprod(), port, periods_per_year=PPY, rf=0.0)
    m2 = ta.perf_metrics((1 + port2x).cumprod(), port2x, periods_per_year=PPY, rf=0.02)
    hr = ta.rolling_hit_rate(port, window=PPY)
    attr = ta.market_attribution(per_asset)
    conc = ta.concentration(monthly_trades(port), top_n=5)
    def g(d, *keys, default=None):
        for k in keys:
            if isinstance(d, dict) and k in d:
                return d[k]
        return default
    return {
        "start": port.index[0], "end": port.index[-1], "days": len(port),
        "mar": mn["mar"], "sortino": mn["sortino"], "cagr": mn.get("cagr"),
        "maxdd": mn["max_dd"],
        "mar2x": m2["mar"], "sortino2x": m2["sortino"],
        "hit": float(hr),   # rolling_hit_rate returns a bare float
        "maxshare": g(attr, "max_share", "max_pct", default=float("nan")),
        "strip_ok": conc["strip_topN_positive"],
        "top5": conc["topN_share"],
    }


def row(tag, m):
    dd = m["maxdd"] if m["maxdd"] is not None else float("nan")
    return (f"  {tag:<10} {str(m['start'])[:10]} -> {str(m['end'])[:10]}  "
            f"n={m['days']:<5} MAR {m['mar']:>5.2f} | Sortino {m['sortino']:>5.2f} | "
            f"CAGR {100*m['cagr']:>6.1f}% | MaxDD {100*dd:>6.1f}%")


def main():
    print("=" * 104)
    print("COMMON-WINDOW GRADE — the ragged-window artifact, measured")
    print("=" * 104)
    for name, tickers in FLEETS.items():
        frames = per_asset_frames(tickers)
        firsts = {tk: frames[tk]["ret"].first_valid_index() for tk in tickers}
        print(f"\nFLEET: {name}  ->  {', '.join(tickers)}")
        print("  slot first-valid dates:")
        for tk, d in sorted(firsts.items(), key=lambda kv: str(kv[1])):
            print(f"      {tk:<10} {str(d)[:10]}")

        out = {}
        for mode in ("ragged", "common"):
            out[mode] = grade(*assemble(frames, tickers, mode))
        print()
        print(row("RAGGED", out["ragged"]))
        print(row("COMMON", out["common"]))

        dm = out["common"]["mar"] - out["ragged"]["mar"]
        ds = out["common"]["sortino"] - out["ragged"]["sortino"]
        pct = 100 * dm / out["ragged"]["mar"] if out["ragged"]["mar"] else float("nan")
        print(f"\n  ARTIFACT: MAR {dm:+.2f} ({pct:+.0f}%) | Sortino {ds:+.2f} "
              f"| {out['ragged']['days'] - out['common']['days']} phantom days removed")

        c = out["common"]
        print(f"  Common-window gates: rolling-12mo hit {c['hit']:.0%} | "
              f"max per-asset share {c['maxshare']:.0%} | "
              f"strip-top-5-months positive {c['strip_ok']} | "
              f"2x-cost MAR {c['mar2x']:.2f} / Sortino {c['sortino2x']:.2f}")
        gates = [c["mar"] >= 0.5, c["sortino"] >= 1.0,
                 c["mar2x"] >= 0.5 and c["sortino2x"] >= 1.0]
        print(f"  Ship bar on the honest window: "
              f"{'PASS' if all(gates) else 'FAIL'} "
              f"(concentration gate {'PASS' if c['maxshare'] <= 0.35 else 'FAIL'} "
              f"at {c['maxshare']:.0%} vs 35% bar)")
    print("\n" + "=" * 104)
    print("Report the COMMON row. The ragged row is shown only to size the artifact.")


if __name__ == "__main__":
    main()
