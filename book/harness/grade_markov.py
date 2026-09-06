"""
grade_markov.py — grade the Markov bot on the SAME A+ rubric harness used for the
trend-follower, independently (not trusting the README's claimed 1.70/2.69).

What it does:
  - Runs the Markov backtest per asset via the bot's own primitives (yfinance, offline).
  - Builds the equal-weight portfolio the same way scripts/portfolio.py does.
  - Grades BOTH fleets honestly:
      6-asset (README headline, survivorship-selected): BTC SOL NVDA AAPL QQQ GLD
      4-asset (active, cost-aware):                     BTC SOL NVDA AAPL
  - Reports two metric conventions:
      (a) Markov-native: rf=0, 365 periods/yr  -> should reproduce README ~1.70/2.69
      (b) Rubric harness: rf=2%, 365 periods/yr -> apples-to-apples with the trend grading
  - Robustness gates from trend_analytics: rolling-12mo hit rate, per-asset attribution
    (no asset > 35% of P&L), strip-top-5-MONTHS concentration, 2x-cost stress (reconstructed
    from the position series, exact — no re-run needed).

Run:  python3 grade_markov.py
"""

import os
import sys
import numpy as np
import pandas as pd

# Markov backtest reads sizing config from env at import time — set before importing.
os.environ.setdefault("PORT_SIZING", "vol_target")
os.environ.setdefault("PORT_VOL_TARGET", "0.40")
os.environ.setdefault("PORT_MAX_LEV", "1.0")
os.environ.setdefault("PORT_WEIGHTING", "equal")

sys.path.insert(0, os.environ.get("MARKOV_ROOT", "./markov"))
sys.path.insert(0, "<set MARKOV_ROOT>")

import trend_analytics as ta
from portfolio import run_single_asset  # noqa: E402

FLEETS = {
    "6-asset (README headline)": ["BTC-USD", "SOL-USD", "NVDA", "AAPL", "QQQ", "GLD"],
    "4-asset (active fleet)":     ["BTC-USD", "SOL-USD", "NVDA", "AAPL"],
}
YEARS = 10
EXTRA_COST_PER_SIDE = 5.0 / 10_000.0   # +5bps/side to simulate 2x of the 5bps baseline
PPY = 365                              # calendar-daily series (crypto fills weekends)


def build_portfolio(tickers):
    """Return (port_ret, port_ret_2x, per_asset_ret dict) — equal-weight, weekend-0-filled."""
    frames = {}
    for tk in tickers:
        df = run_single_asset(tk, YEARS)
        ret = df[f"{tk}_ret"]
        pos = df[f"{tk}_pos"]
        # exact 2x-cost: subtract an extra 5bps/side * |turnover|
        extra = EXTRA_COST_PER_SIDE * pos.diff().abs().fillna(0)
        frames[tk] = pd.DataFrame({"ret": ret, "ret2x": ret - extra})
    idx = sorted(set().union(*[f.index for f in frames.values()]))
    rets = pd.DataFrame({tk: frames[tk]["ret"] for tk in tickers}).reindex(idx).fillna(0.0)
    rets2x = pd.DataFrame({tk: frames[tk]["ret2x"] for tk in tickers}).reindex(idx).fillna(0.0)
    w = np.ones(len(tickers)) / len(tickers)
    port = pd.Series(rets.to_numpy() @ w, index=rets.index)
    port2x = pd.Series(rets2x.to_numpy() @ w, index=rets2x.index)
    per_asset = {tk: rets[tk] for tk in tickers}
    return port, port2x, per_asset


def monthly_trades(port):
    """Concentration analog for a continuous strategy: monthly P&L sums as 'trades'."""
    eq = (1 + port).cumprod()
    monthly = eq.resample("ME").last().pct_change().dropna()
    return [{"return": float(r)} for r in monthly.values]


def grade_fleet(name, tickers):
    print("=" * 100)
    print(f"FLEET: {name}  ->  {', '.join(tickers)}")
    print("=" * 100)
    port, port2x, per_asset = build_portfolio(tickers)

    # (a) Markov-native convention: rf=0, 365/yr
    mn = ta.perf_metrics((1 + port).cumprod(), port, periods_per_year=PPY, rf=0.0)
    # (b) Rubric convention: rf=2%, 365/yr
    mr = ta.perf_metrics((1 + port).cumprod(), port, periods_per_year=PPY, rf=0.02)

    m2x = ta.perf_metrics((1 + port2x).cumprod(), port2x, periods_per_year=PPY, rf=0.02)
    cost2x_pass = (m2x["mar"] >= 0.5 and m2x["sortino"] >= 1.0)

    hr = ta.rolling_hit_rate(port, window=PPY)
    attr = ta.market_attribution(per_asset)
    conc = ta.concentration(monthly_trades(port), top_n=5)

    grade, reasons = ta.grade_profitability(mr, conc, hr, attr, cost2x_pass)

    print(f"  Bars: {len(port)} | window {port.index[0].date()} -> {port.index[-1].date()}\n")
    print(f"  (a) Markov-native (rf=0,  365/yr):  MAR {mn['mar']:.2f} | Sortino {mn['sortino']:.2f} | "
          f"Sharpe {mn['sharpe']:.2f} | CAGR {mn['cagr']*100:.1f}% | MaxDD {mn['max_dd']*100:.1f}%")
    print(f"  (b) Rubric harness (rf=2%, 365/yr): MAR {mr['mar']:.2f} | Sortino {mr['sortino']:.2f} | "
          f"Sharpe {mr['sharpe']:.2f} | CAGR {mr['cagr']*100:.1f}% | MaxDD {mr['max_dd']*100:.1f}%")
    print(f"\n  Robustness:")
    print(f"    rolling-12mo hit rate:     {hr*100:.0f}%   (A+ bar >=70%)")
    print(f"    max per-asset P&L share:   {attr['max_share']*100:.0f}%   "
          f"({attr['n_positive']}/{attr['n_markets']} positive)   (A+ bar <=35%)")
    gross = sum(abs(v) for v in attr["totals"].values())
    shares = sorted(((k, v / gross) for k, v in attr["totals"].items()), key=lambda x: -x[1])
    print("    per-asset P&L share:       " +
          ", ".join(f"{k} {s*100:.0f}%" for k, s in shares))
    print(f"    strip-top-5-months stays +: {conc['strip_topN_positive']}   "
          f"(top-5-month share {conc['topN_share']*100:.0f}%)")
    print(f"    2x-cost (10bps/side): MAR {m2x['mar']:.2f} / Sortino {m2x['sortino']:.2f} "
          f"-> {'PASS' if cost2x_pass else 'FAIL'}")
    print(f"\n  >>> RUBRIC GRADE (rf=2%): {grade}   ({'; '.join(reasons)})")
    # also report vs Markov's own stated A+ bars (MAR>=1.5, Sortino>=2.0, native conv)
    own_aplus = mn["mar"] >= 1.5 and mn["sortino"] >= 2.0
    print(f"  >>> vs README's own A+ bars (MAR>=1.5 & Sortino>=2.0, native): "
          f"{'MATCHES A+' if own_aplus else 'does NOT match A+'}\n")
    return {"name": name, "native": mn, "rubric": mr, "cost2x": m2x, "hit": hr,
            "attr": attr, "conc": conc, "grade": grade, "reasons": reasons}


def main():
    print("\nGrading Markov on the trend-follower's A+ rubric harness (independent verification)\n")
    results = [grade_fleet(name, tk) for name, tk in FLEETS.items()]
    _write(results)
    print("Written to MARKOV_GRADE_RESULTS.md")


def _write(results):
    lines = ["# Markov Bot — Independent Grade on the A+ Rubric Harness", "",
             "_grade_markov.py · same harness used to grade the IBKR trend-follower · 10y, vol-target, "
             "equal-weight, 365/yr_", "",
             "Rubric A+ bar: MAR>=1.0 & Sortino>=1.5 (rf=2%) + no asset >35% P&L + strip-top-5 positive "
             "+ rolling-12mo hit >=70% + survives 2x cost.", ""]
    for r in results:
        mn, mr = r["native"], r["rubric"]
        lines += [
            f"## {r['name']}", "",
            f"- Markov-native (rf=0, 365/yr): **MAR {mn['mar']:.2f} / Sortino {mn['sortino']:.2f} / "
            f"Sharpe {mn['sharpe']:.2f} / CAGR {mn['cagr']*100:.1f}% / MaxDD {mn['max_dd']*100:.1f}%**",
            f"- Rubric harness (rf=2%, 365/yr): MAR {mr['mar']:.2f} / Sortino {mr['sortino']:.2f} / "
            f"Sharpe {mr['sharpe']:.2f}",
            f"- Rolling-12mo hit {r['hit']*100:.0f}% | max per-asset share {r['attr']['max_share']*100:.0f}% "
            f"| strip-top-5-months+ {r['conc']['strip_topN_positive']} | "
            f"2x-cost MAR {r['cost2x']['mar']:.2f}/Sortino {r['cost2x']['sortino']:.2f}",
            f"- **RUBRIC GRADE: {r['grade']}** ({'; '.join(r['reasons'])})", "",
        ]
    lines += [
        "## Honest caveats", "",
        "- **Survivorship:** the 6-asset fleet was hand-picked from names already known to pass the gate "
        "(README + sweep.py admit 6/12 of the broader universe fail). The 4-asset active fleet is the "
        "cost-aware survivor set — still selected, so treat as 'best-of', not universe-wide.",
        "- **Weekend 0-fill:** equities get 0 return on weekends while crypto trades, which lowers blended "
        "vol and can flatter Sortino. Standard for mixed crypto/equity books but worth stating.",
        "- **Backtest, not live:** realized paper P&L is ~16 days and statistically meaningless. This grade "
        "is the backtest's, not proof of live edge. Stage-2 live gate (realized MAR>=0.5/Sortino>=1.0) is "
        "the real test.",
    ]
    with open("MARKOV_GRADE_RESULTS.md", "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
