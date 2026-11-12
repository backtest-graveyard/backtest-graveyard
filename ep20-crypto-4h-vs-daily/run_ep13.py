"""
Ep13 driver — 4-hour vs daily crypto Donchian, BTC/ETH.
Reuses crypto_backtester's EXACT functions + timeframe scaling (main() parity):
  bars_per_day = BARS_PER_DAY[tf]; atr_period = 14*bpd;
  donchian periods scaled days->bars; BTC regime always daily.
Exports full per-asset + combined stat blocks and normalized equity curves.
"""
import json, sys, os
from collections import Counter
from datetime import datetime, timedelta

# crypto_client, crypto_backtester and config are private modules (see README); they must be importable.
import crypto_client as cc
import crypto_backtester as cb
from config import CRYPTO_SPOT_BUDGET

WARMUP_DAYS = cb.WARMUP_DAYS
ATR_PERIOD  = cb.ATR_PERIOD
SYSTEMS     = cb.SYSTEMS            # [(20,10),(30,15),(55,20)] in DAYS
BARS_PER_DAY = cb.BARS_PER_DAY
PAIRS = ["BTC/USD", "ETH/USD"]

START = "2021-09-16"
END   = "2026-09-16"

def build_equity_curve(trades, budget):
    """Daily normalized-to-1.0 equity from PnL bucketed by exit day."""
    if not trades:
        return [], []
    by_date = {}
    for t in trades:
        ed = (t.get("exit_time") or t["entry_time"])[:10]
        by_date[ed] = by_date.get(ed, 0.0) + t["pnl"]
    first = datetime.strptime(START, "%Y-%m-%d").date()
    last  = datetime.strptime(END, "%Y-%m-%d").date()
    dates, series = [], []
    cum = 0.0
    cur = first
    while cur <= last:
        cum += by_date.get(cur.isoformat(), 0.0)
        dates.append(cur.isoformat())
        series.append(round(1.0 + cum / budget, 6))
        cur += timedelta(days=1)
    return dates, series

def run_tf(tf):
    bpd        = BARS_PER_DAY[tf]
    atr_period = ATR_PERIOD * bpd
    systems    = [(en * bpd, ex * bpd) for en, ex in SYSTEMS]  # scaled to bars

    start_dt  = datetime.strptime(START, "%Y-%m-%d")
    warmup_dt = start_dt - timedelta(days=WARMUP_DAYS)
    start_iso = f"{warmup_dt.strftime('%Y-%m-%d')}T00:00:00Z"
    end_iso   = f"{END}T23:59:59Z"

    btc_daily = cc.get_crypto_bars("BTC/USD", timeframe="1Day", start=start_iso, end=end_iso)
    regime    = cb.build_btc_regime(btc_daily)

    pair_bars = {}
    for s in PAIRS:
        pair_bars[s] = cc.get_crypto_bars(s, timeframe=tf, start=start_iso, end=end_iso)

    out = {"timeframe": tf, "bars_per_day": bpd, "atr_period_bars": atr_period,
           "systems": {}, "n_bars": {s: len(b) for s, b in pair_bars.items()}}

    # per (system_days): trades per pair + combined, with stats
    for (en_b, ex_b), (en_d, ex_d) in zip(systems, SYSTEMS):
        per_pair_trades = {}
        combined = []
        for s in PAIRS:
            tr = cb._simulate_pair(s, pair_bars[s], regime, START, en_b, ex_b,
                                   atr_period=atr_period)
            per_pair_trades[s] = tr
            combined += tr
        key = f"{en_d}d/{ex_d}d"
        out["systems"][key] = {
            "combined": {"stats": cb._stats(combined), "n": len(combined)},
            "per_pair": {s: {"stats": cb._stats(per_pair_trades[s]),
                             "n": len(per_pair_trades[s])} for s in PAIRS},
            "_trades_combined": combined,
            "_trades_pair": per_pair_trades,
        }
    return out

def best_mar_key(tf_out):
    return max(tf_out["systems"], key=lambda k: tf_out["systems"][k]["combined"]["stats"]["mar"])

def main():
    result = {"window": {"start": START, "end": END},
              "budget": CRYPTO_SPOT_BUDGET, "pairs": PAIRS,
              "data_source": "Alpaca v1beta3 crypto (BTC/USD, ETH/USD); BTC daily 200SMA regime",
              "timeframes": {}}
    curves = {"window": {"start": START, "end": END}, "normalization": "equity=1.0 at window start, +PnL/budget cumulative (non-compounding fixed budget)", "series": {}}

    for tf in ["1Day", "4Hour"]:
        tfo = run_tf(tf)
        bk  = best_mar_key(tfo)
        # slim copy without raw trades for the stats JSON
        slim = {"bars_per_day": tfo["bars_per_day"], "atr_period_bars": tfo["atr_period_bars"],
                "n_bars": tfo["n_bars"], "best_mar_system": bk, "systems": {}}
        for k, v in tfo["systems"].items():
            slim["systems"][k] = {"combined": v["combined"],
                                  "per_pair": v["per_pair"]}
        result["timeframes"][tf] = slim

        # curves: best combined + per asset for best system
        bsys = tfo["systems"][bk]
        tag = "daily" if tf == "1Day" else "4h"
        d, s = build_equity_curve(bsys["_trades_combined"], CRYPTO_SPOT_BUDGET)
        curves["series"][f"{tag}_combined"] = {"system": bk, "dates": d, "equity": s}
        for pair in PAIRS:
            pd, ps = build_equity_curve(bsys["_trades_pair"][pair], CRYPTO_SPOT_BUDGET)
            curves["series"][f"{tag}_{pair.split('/')[0].lower()}"] = {"system": bk, "dates": pd, "equity": ps}

    outdir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(outdir, "stats_full.json"), "w") as f:
        json.dump(result, f, indent=2)
    with open(os.path.join(outdir, "curve_data.json"), "w") as f:
        json.dump(curves, f, indent=2)

    # console summary
    for tf in ["1Day", "4Hour"]:
        t = result["timeframes"][tf]
        bk = t["best_mar_system"]
        c = t["systems"][bk]["combined"]["stats"]
        print(f"\n== {tf}  best-MAR={bk} ==")
        print(f"   combined: PnL ${c['pnl']:,.0f}  MAR {c['mar']:.2f}  Sortino {c['sortino']:.2f}  "
              f"MaxDD {c['max_dd_pct']:.1f}%  win {c['win_pct']:.0f}%  n={c['n']}  avghold {c['avg_bars']/t['bars_per_day']:.1f}d")
        for p in PAIRS:
            ps = t["systems"][bk]["per_pair"][p]["stats"]
            print(f"     {p}: PnL ${ps['pnl']:,.0f}  MAR {ps['mar']:.2f}  Sortino {ps['sortino']:.2f}  "
                  f"MaxDD {ps['max_dd_pct']:.1f}%  win {ps['win_pct']:.0f}%  n={ps['n']}  avghold {ps['avg_bars']/t['bars_per_day']:.1f}d")
    print("\nWrote stats_full.json + curve_data.json")

if __name__ == "__main__":
    main()
