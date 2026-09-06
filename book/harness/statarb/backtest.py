"""Event-driven spread backtester — realized reversion, causal, cost-charged.

Everything is point-in-time to avoid the classic cointegration backtest lies:
* Hedge ratio beta_t is a ROLLING OLS slope on a trailing window (not full-sample).
* z-score uses a trailing rolling mean/std (not full-sample moments).
* Position set from z known at close_t is applied to returns over t+1 (beta and position
  both shifted). No future information touches any decision.

P&L is beta-weighted and dollar-neutral-ish: long leg $1, short leg $beta, so the daily
per-unit return is  pos * (ret_y - beta * ret_x)  — i.e. the realized spread move, not an
assumed full reversion. Transaction cost (from the shared CostModel, borrow excluded) is
charged at entry and exit; borrow accrues daily while short.

Params are TEXTBOOK DEFAULTS and deliberately NOT tuned (tuning here is how overfitting
gets baked in). The train/holdout split is a robustness check, reported separately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math

import numpy as np
import pandas as pd

from .costs import CostModel


@dataclass
class Trade:
    entry_i: int
    exit_i: int
    side: int          # +1 long-spread (long y / short x), -1 short-spread
    pnl: float         # net, per unit of y-leg notional
    hold_days: int
    reason: str        # 'revert' | 'stop' | 'time'


@dataclass
class BacktestResult:
    spread: str
    ret: pd.Series           # daily net return series, per $1 y-leg notional (0 when flat)
    trades: list[Trade]
    metrics: dict
    segments: dict = field(default_factory=dict)  # {'train':metrics, 'holdout':metrics}


def _metrics(ret: pd.Series, trades: list[Trade]) -> dict:
    r = ret.dropna()
    if len(r) < 20 or r.abs().sum() == 0:
        return {"n_trades": len(trades), "ann_ret": 0.0, "ann_vol": 0.0, "sharpe": 0.0,
                "sortino": 0.0, "max_dd": 0.0, "mar": 0.0, "profit_factor": 0.0,
                "win_rate": 0.0, "avg_hold": 0.0, "exposure": 0.0}
    ann_ret = float(r.mean() * 252)
    ann_vol = float(r.std() * math.sqrt(252))
    downside = r[r < 0]
    dstd = float(downside.std() * math.sqrt(252)) if len(downside) > 1 else 0.0
    equity = 1.0 + r.cumsum()
    dd = equity - equity.cummax()
    max_dd = float(-dd.min())
    pnl = np.array([t.pnl for t in trades], dtype=float)
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    pf = float(wins.sum() / -losses.sum()) if losses.sum() != 0 else (math.inf if wins.sum() > 0 else 0.0)
    return {
        "n_trades": len(trades),
        "ann_ret": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": ann_ret / ann_vol if ann_vol else 0.0,
        "sortino": ann_ret / dstd if dstd else 0.0,
        "max_dd": max_dd,
        "mar": ann_ret / max_dd if max_dd else 0.0,
        "profit_factor": pf,
        "win_rate": float((pnl > 0).mean()) if len(pnl) else 0.0,
        "avg_hold": float(np.mean([t.hold_days for t in trades])) if trades else 0.0,
        "exposure": float((r != 0).mean()),
    }


def backtest_spread(
    y: str,
    x: str,
    close: pd.DataFrame,
    cost_model: CostModel,
    stats: pd.DataFrame,
    notional_per_leg: float = 50_000.0,
    beta_window: int = 252,
    z_window: int = 60,
    z_entry: float = 2.0,
    z_exit: float = 0.5,
    z_stop: float = 4.0,
    max_hold_days: int = 60,
    holdout_frac: float = 0.30,
) -> BacktestResult:
    ly, lx = np.log(close[y]), np.log(close[x])
    ret_y, ret_x = close[y].pct_change(), close[x].pct_change()

    # Rolling OLS slope on log-levels = Cov/Var over the trailing window (with intercept).
    cov = ly.rolling(beta_window).cov(lx)
    var = lx.rolling(beta_window).var()
    beta = (cov / var).rename("beta")

    spread = (ly - beta * lx)
    zmean = spread.rolling(z_window).mean()
    zstd = spread.rolling(z_window).std()
    z = (spread - zmean) / zstd

    n = len(close)
    warmup = beta_window + z_window
    pos = np.zeros(n)

    # per-transaction cost (bps of avg leg notional): open+close crossing, borrow excluded
    txn_bps = cost_model.pair_roundtrip_bps(
        long_notional=notional_per_leg, short_notional=notional_per_leg,
        long_adv=float(stats.loc[y, "dollar_adv"]), short_adv=float(stats.loc[x, "dollar_adv"]),
        long_spread_bps=float(stats.loc[y, "spread_bps"]), short_spread_bps=float(stats.loc[x, "spread_bps"]),
        long_sigma_daily_bps=float(stats.loc[y, "sigma_daily_bps"]),
        short_sigma_daily_bps=float(stats.loc[x, "sigma_daily_bps"]),
        holding_days=0.0,
    )
    txn_frac = (txn_bps / 2.0) / 10_000.0          # half at entry, half at exit
    borrow_day_frac = cost_model.borrow_bps(0.3, 1.0) / 10_000.0

    zv = z.values
    trades: list[Trade] = []
    entry_i = -1
    for t in range(warmup, n):
        zt = zv[t]
        if not math.isfinite(zt):
            pos[t] = pos[t - 1]
            continue
        p = pos[t - 1]
        if p == 0:
            if zt > z_entry:
                pos[t], entry_i = -1, t
            elif zt < -z_entry:
                pos[t], entry_i = 1, t
            else:
                pos[t] = 0
        elif p == 1:   # long spread (entered z<-entry), profit as z -> 0 from below
            if zt >= -z_exit or zt < -z_stop or (t - entry_i) >= max_hold_days:
                pos[t] = 0
            else:
                pos[t] = 1
        else:          # p == -1 short spread
            if zt <= z_exit or zt > z_stop or (t - entry_i) >= max_hold_days:
                pos[t] = 0
            else:
                pos[t] = -1

    pos_s = pd.Series(pos, index=close.index)
    # realized daily return: yesterday's position on today's beta-weighted spread move
    daily = pos_s.shift(1) * (ret_y - beta.shift(1) * ret_x)
    # costs: charge txn on any change to/from flat; borrow while in a position
    changed = (pos_s != pos_s.shift(1)).astype(float)
    cost_series = changed * txn_frac + (pos_s != 0).astype(float) * borrow_day_frac
    net = (daily.fillna(0.0) - cost_series).rename(f"{y}~{x}")

    # reconstruct per-trade P&L from the net series
    in_trade, e_i, side = False, -1, 0
    parr = pos_s.values
    narr = net.values
    for t in range(warmup, n):
        if not in_trade and parr[t] != 0:
            in_trade, e_i, side = True, t, int(parr[t])
        elif in_trade and parr[t] == 0:
            pnl = float(np.nansum(narr[e_i:t + 1]))
            trades.append(Trade(e_i, t, side, pnl, t - e_i, "revert"))
            in_trade = False

    # train / holdout split on the live (post-warmup) window
    live = net.iloc[warmup:]
    split = int(len(live) * (1 - holdout_frac))
    train_idx, hold_idx = live.index[:split], live.index[split:]
    tr_trades = [t for t in trades if close.index[t.entry_i] in train_idx]
    ho_trades = [t for t in trades if close.index[t.entry_i] in hold_idx]

    return BacktestResult(
        spread=f"{y}~{x}",
        ret=net,
        trades=trades,
        metrics=_metrics(live, trades),
        segments={
            "train": _metrics(net.loc[train_idx], tr_trades),
            "holdout": _metrics(net.loc[hold_idx], ho_trades),
        },
    )


def combine_equal_weight(results: list[BacktestResult]) -> pd.Series:
    """Equal-weight book of the per-spread net return series (diversification view)."""
    mat = pd.concat([r.ret for r in results], axis=1).fillna(0.0)
    return mat.mean(axis=1).rename("book")


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    from .data import load_panel

    cm = CostModel()
    family = [("GDXJ", "GDX"), ("GLD", "GDXJ"), ("SLV", "SILJ"), ("SLV", "SIL")]
    syms = sorted({s for p in family for s in p})
    panel = load_panel(syms, lookback_days=7 * 365)
    print(f"source={panel.source}  {panel.close.shape[0]} sessions  "
          f"{panel.close.index[0].date()} -> {panel.close.index[-1].date()}\n")

    def line(name, m, cost2x=False):
        return (f"  {name:12s} n={m['n_trades']:3d} annRet={m['ann_ret']*100:6.1f}% "
                f"Sharpe={m['sharpe']:5.2f} Sortino={m['sortino']:5.2f} "
                f"MAR={m['mar']:5.2f} MaxDD={m['max_dd']*100:5.1f}% "
                f"PF={m['profit_factor']:4.2f} WR={m['win_rate']*100:4.0f}% "
                f"hold={m['avg_hold']:3.0f}d exp={m['exposure']*100:3.0f}%")

    results = []
    print("=== Tier 1 metals-miner family — FULL live window (1x cost) ===")
    for y, x in family:
        r = backtest_spread(y, x, panel.close, cm, panel.stats)
        results.append(r)
        print(line(r.spread, r.metrics))

    print("\n=== TRAIN vs HOLDOUT (does it survive out-of-sample?) ===")
    for r in results:
        print(line(r.spread + " [tr]", r.segments["train"]))
        print(line(r.spread + " [ho]", r.segments["holdout"]))

    print("\n=== Equal-weight BOOK (diversification) ===")
    book = combine_equal_weight(results)
    print(line("book (full)", _metrics(book.iloc[252 + 60:], [t for r in results for t in r.trades])))

    print("\n=== COST STRESS on the book (Gate 5): 1x / 2x / 4x ===")
    from .costs import stressed
    for mult in (1.0, 2.0, 4.0):
        rs = [backtest_spread(y, x, panel.close, stressed(cm, mult), panel.stats) for y, x in family]
        bk = combine_equal_weight(rs)
        m = _metrics(bk.iloc[252 + 60:], [t for r in rs for t in r.trades])
        print(f"  {mult:.0f}x  annRet={m['ann_ret']*100:6.1f}%  Sortino={m['sortino']:5.2f}  "
              f"MAR={m['mar']:5.2f}  MaxDD={m['max_dd']*100:5.1f}%")

    print("\nKPI bar: MAR>=0.5 AND Sortino>=1.0, net of 2x cost, on the HOLDOUT.")
