#!/usr/bin/env python3
"""
backtest_ema_trail.py — the "buy below EMA200, exit on an armed 2% trailing stop" rule.

The viral retail rule, exactly as specified (single entry per cycle, long-only,
fully invested):

  ENTRY : while flat, buy at the daily close when close < EMA200 (the "dip").
  ARM   : once long, arm a trailing stop the first day close >= EMA200 * 1.02
          (i.e. once price has "recovered" 2% above the trend line).
  EXIT  : after arming, track the running peak; sell at the close when
          price <= peak * 0.98 (a 2% pullback from the post-recovery high).
          Then go flat and wait for the next close below EMA200.

It is compared against buy & hold over the SAME window. Reports: trades,
total return, CAGR, MAR (CAGR / MaxDD), Sortino, profit factor, win rate,
time in market, and the KPI bar (MAR >= 0.50 AND Sortino >= 1.00).

------------------------------------------------------------------------------
DATA / CREDENTIALS — you supply your own
------------------------------------------------------------------------------
Prices come from Alpaca's free IEX daily-bar feed (split-adjusted). You need
your own Alpaca market-data key. The script reads two environment variables:

    export ALPACA_KEY=your_key_id
    export ALPACA_SECRET=your_secret

(No keys are stored in this file, and none are needed to read it.) The free
IEX history only reaches ~mid-2020, so the usable window is ~5 years — but it
does contain a full cycle: 2022 bear -> 2023-24 recovery -> 2025.

QQQM and QQQ track the same Nasdaq-100 index; QQQ is the longer-history twin.

Usage:
    python3 backtest_ema_trail.py --symbol QQQ
    python3 backtest_ema_trail.py --symbol QQQM --start 2015-01-01
"""

import argparse
import os
import sys
from datetime import datetime

import requests

DATA_BASE = "https://data.alpaca.markets/v2"
EMA_PERIOD = 200
ARM_PCT = 0.02      # arm trailing stop when close >= EMA200 * (1 + ARM_PCT)
TRAIL_PCT = 0.02    # sell when close drops TRAIL_PCT below the post-arm peak
TRADING_DAYS = 252


# ── credentials (env vars only) ───────────────────────────────────────────────
def resolve_creds():
    key = os.environ.get("ALPACA_KEY") or os.environ.get("APCA_API_KEY_ID")
    secret = os.environ.get("ALPACA_SECRET") or os.environ.get("APCA_API_SECRET_KEY")
    return key, secret


def make_session(key, secret):
    s = requests.Session()
    s.headers.update({"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret})
    return s


# ── data ──────────────────────────────────────────────────────────────────────
def fetch_bars(session, symbol, start="2015-01-01"):
    url = f"{DATA_BASE}/stocks/{symbol}/bars"
    params = {"timeframe": "1Day", "start": f"{start}T00:00:00Z",
              "adjustment": "split", "feed": "iex", "limit": 10000}
    bars = []
    while True:
        r = session.get(url, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        bars.extend(data.get("bars") or [])
        token = data.get("next_page_token")
        if not token:
            break
        params["page_token"] = token
    bars.sort(key=lambda b: b["t"])
    dates = [b["t"][:10] for b in bars]
    closes = [float(b["c"]) for b in bars]
    return dates, closes


def ema_series(closes, period):
    out = [None] * len(closes)
    if len(closes) < period:
        return out
    sma = sum(closes[:period]) / period
    out[period - 1] = sma
    k = 2.0 / (period + 1)
    prev = sma
    for i in range(period, len(closes)):
        prev = closes[i] * k + prev * (1 - k)
        out[i] = prev
    return out


# ── simulation ──────────────────────────────────────────────────────────────
def simulate(dates, closes, ema):
    cash = 1.0
    shares = 0.0
    in_pos = False
    armed = False
    peak = 0.0
    entry_price = 0.0
    entry_date = None
    trades = []          # (entry_date, exit_date, ret, days, exit_reason)
    equity = []          # daily mark-to-market equity

    for i in range(len(closes)):
        px = closes[i]
        e = ema[i]
        if e is None:
            equity.append(cash + shares * px)
            continue

        if in_pos:
            if not armed and px >= e * (1 + ARM_PCT):
                armed = True
                peak = px
            if armed:
                peak = max(peak, px)
                if px <= peak * (1 - TRAIL_PCT):
                    # exit at close
                    cash = shares * px
                    ret = px / entry_price - 1
                    days = (datetime.fromisoformat(dates[i]) -
                            datetime.fromisoformat(entry_date)).days
                    trades.append((entry_date, dates[i], ret, days, "trail"))
                    shares = 0.0
                    in_pos = False
                    armed = False
                    peak = 0.0
        else:
            if px < e:
                shares = cash / px
                cash = 0.0
                in_pos = True
                armed = False
                peak = px
                entry_price = px
                entry_date = dates[i]

        equity.append(cash + shares * px)

    # mark any open position to the last close (unrealized); note it separately
    open_trade = None
    if in_pos:
        px = closes[-1]
        ret = px / entry_price - 1
        days = (datetime.fromisoformat(dates[-1]) -
                datetime.fromisoformat(entry_date)).days
        open_trade = (entry_date, dates[-1], ret, days, "OPEN")

    return equity, trades, open_trade


# ── metrics ───────────────────────────────────────────────────────────────────
def daily_returns(equity):
    out = []
    for i in range(1, len(equity)):
        if equity[i - 1] > 0:
            out.append(equity[i] / equity[i - 1] - 1)
        else:
            out.append(0.0)
    return out


def max_drawdown(equity):
    peak = equity[0]
    mdd = 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1)
    return mdd


def sortino(rets):
    if not rets:
        return 0.0
    mean = sum(rets) / len(rets)
    downside = [min(r, 0.0) ** 2 for r in rets]
    dd = (sum(downside) / len(downside)) ** 0.5
    if dd == 0:
        return float("inf")
    return (mean / dd) * (TRADING_DAYS ** 0.5)


def cagr(equity, n_days):
    if n_days <= 0 or equity[0] <= 0:
        return 0.0
    years = n_days / TRADING_DAYS
    return (equity[-1] / equity[0]) ** (1 / years) - 1


def summarize(name, equity, n_days, trades=None):
    rets = daily_returns(equity)
    tot = equity[-1] / equity[0] - 1
    cg = cagr(equity, n_days)
    mdd = max_drawdown(equity)
    mar = (cg / abs(mdd)) if mdd != 0 else float("inf")
    sor = sortino(rets)
    time_in = None
    pf = wr = avg_hold = None
    if trades is not None:
        time_in = sum(1 for r in rets if r != 0) / len(rets) if rets else 0
        closed = list(trades)
        wins = [t[2] for t in closed if t[2] > 0]
        losses = [t[2] for t in closed if t[2] <= 0]
        gross_win = sum(wins)
        gross_loss = -sum(losses)
        pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
        wr = (len(wins) / len(closed)) if closed else 0
        avg_hold = (sum(t[3] for t in closed) / len(closed)) if closed else 0
    return {
        "name": name, "total": tot, "cagr": cg, "mdd": mdd, "mar": mar,
        "sortino": sor, "time_in": time_in, "pf": pf, "wr": wr, "avg_hold": avg_hold,
    }


def print_row(m):
    line = (f"  {m['name']:<16} ret {m['total']*100:>8.1f}%  CAGR {m['cagr']*100:>6.2f}%  "
            f"MaxDD {m['mdd']*100:>6.1f}%  MAR {m['mar']:>5.2f}  Sortino {m['sortino']:>5.2f}")
    if m["time_in"] is not None:
        line += (f"\n  {'':16} time-in-mkt {m['time_in']*100:>4.0f}%  "
                 f"PF {m['pf']:>4.2f}  win {m['wr']*100:>4.0f}%  avg-hold {m['avg_hold']:>4.0f}d")
    print(line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="QQQ")
    ap.add_argument("--start", default="2015-01-01")
    args = ap.parse_args()
    sym = args.symbol.upper()

    key, secret = resolve_creds()
    if not (key and secret):
        print("ERROR: set ALPACA_KEY and ALPACA_SECRET in your environment.",
              file=sys.stderr)
        return 2
    session = make_session(key, secret)

    dates, closes = fetch_bars(session, sym, args.start)
    if len(closes) < EMA_PERIOD + 50:
        print(f"ERROR: only {len(closes)} bars for {sym} — need > {EMA_PERIOD+50} "
              f"(free IEX history is short; try QQQ).", file=sys.stderr)
        return 2
    ema = ema_series(closes, EMA_PERIOD)
    equity, trades, open_trade = simulate(dates, closes, ema)

    # buy & hold over the same window (start at first day EMA exists, for fairness)
    first = EMA_PERIOD - 1
    bh = [closes[i] / closes[first] for i in range(first, len(closes))]
    strat_eq = equity[first:]
    n_days = len(strat_eq)

    print(f"\n=== {sym} — buy-below-EMA200 / armed 2% trailing-stop exit ===")
    print(f"data: {dates[0]} → {dates[-1]}  ({len(closes)} bars, IEX feed)")
    print(f"window used (post-EMA warmup): {dates[first]} → {dates[-1]}  ({n_days} days)\n")

    m_strat = summarize("strategy", strat_eq, n_days, trades)
    m_bh = summarize("buy & hold", bh, n_days)
    print_row(m_strat)
    print()
    print_row(m_bh)

    print(f"\n  closed trades: {len(trades)}")
    if open_trade:
        print(f"  OPEN position since {open_trade[0]}  ({open_trade[2]*100:+.1f}%, {open_trade[3]}d)")
    print("\n  trade log (entry → exit, return, hold days):")
    for t in trades:
        print(f"    {t[0]} → {t[1]}  {t[2]*100:>7.1f}%  {t[3]:>4}d  [{t[4]}]")

    print(f"\n  KPI bar: MAR >= 0.50 and Sortino >= 1.00")
    passed = m_strat["mar"] >= 0.5 and m_strat["sortino"] >= 1.0
    beats_bh = m_strat["total"] > m_bh["total"]
    print(f"  strategy clears bar: {'YES' if passed else 'NO'}   |   "
          f"beats buy & hold: {'YES' if beats_bh else 'NO'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
