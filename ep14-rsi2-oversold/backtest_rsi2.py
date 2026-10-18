#!/usr/bin/env python3
"""
backtest_rsi2.py — Honest kill-test of the "RSI-2 calls the bottom" belief,
for "The Backtest Graveyard" (Ep14).

THE VIRAL BELIEF (implemented faithfully, taken at face value):
  Larry Connors' 2-period-RSI oversold bounce. In an uptrend, when a stock gets
  deeply oversold on the 2-day RSI, buy it — it is about to bounce — and sell a
  few days later when it recovers. Famous for a very high win rate.

STRATEGY (Connors' canonical RSI-2 mean reversion, long-only):
  Universe pre-filter : close > 200-day SMA  ("buy dips in an uptrend").
  ENTRY  : RSI(2) closes BELOW an oversold threshold (base 10; grid tests 5/10/15).
  EXIT   : RSI(2) closes ABOVE an exit threshold (base 70), OR the "close > 5-day
           SMA" exit Connors also used; max-hold cap (base 10 trading days) as the
           only backstop. Connors' classic system has NO stop-loss — that omission
           is the whole point of the win-rate-mirage test below.
  SIZING : equal-dollar slices, up to max_positions parallel names; when more
           signals fire than open slots, take the MOST oversold (lowest RSI-2).
           Idle cash earns 0% (conservative).
  COSTS  : realistic per-side bps applied on entry and exit (base 5 bps one-way =
           10 bps round trip; cost test also runs 0x and 2x).

RESEARCH ONLY. Read-only market data (Alpaca IEX daily bars). Places no orders,
touches no live bot, reveals no live signal. Reproducible & PII-clean.

Yardsticks (the honest ones): Buy&Hold SPY, and equal-weight Buy&Hold of the same
55-name universe. Ranked by MAR = CAGR / MaxDD%. Bar to pass: MAR>=0.5 AND Sortino>=1.0.

Usage:
  python3 backtest_rsi2.py            # base run + full kill-test battery + curve_data.json
  python3 backtest_rsi2.py --refresh  # re-fetch bars (ignore cache)
"""

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

BASE_DIR = Path(__file__).resolve().parent
CACHE = BASE_DIR / "scratchpad_rsi2_bars.pkl"
DATA_BASE = "https://data.alpaca.markets/v2"

# ─────────────────────────── universe & window ───────────────────────────────
# Same ~55 most-liquid US large-caps (S&P 100 core) used by the channel's MACD
# kill-test. All clear any $-volume floor by a wide margin, so liquidity is not
# what's being tested. (No survivorship claim: these are today's large caps.)
UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "JPM", "V",
    "MA", "UNH", "HD", "PG", "JNJ", "XOM", "CVX", "LLY", "ABBV", "MRK",
    "PEP", "KO", "COST", "WMT", "BAC", "WFC", "CRM", "ADBE", "NFLX", "AMD",
    "INTC", "CSCO", "ORCL", "QCOM", "TXN", "HON", "GE", "CAT", "BA", "DIS",
    "VZ", "T", "CMCSA", "NKE", "MCD", "PFE", "TMO", "ABT", "ACN", "LIN",
    "DHR", "PM", "IBM", "GS", "MS",
]
BENCH = "SPY"

# IEX free feed reaches ~mid-2020. Use the longest clean window: 2020-08 -> now.
START = "2020-08-01"
END = (date.today() - timedelta(days=1)).isoformat()

TRADING_DAYS = 252

# ───────────────────────────── strategy config ───────────────────────────────
DEFAULTS = dict(
    rsi_period=2,
    entry_rsi=10.0,          # buy when RSI(2) closes below this
    exit_mode="rsi70",       # "rsi70"  or "sma5"
    exit_rsi=70.0,           # sell when RSI(2) closes above this
    sma_exit=5,              # "sma5" exit: sell when close > 5-day SMA
    sma_trend=200,           # only buy when close > 200-day SMA
    use_trend_filter=True,   # the 200-SMA regime gate (isolated in a kill-test)
    max_hold=10,             # trading-day backstop (Connors uses no hard stop)
    max_positions=10,        # parallel names; equal-dollar slices
    cost_bps=5.0,            # ONE-WAY cost (spread/2 + slippage), bps of notional
    start_equity=100_000.0,
)


# ──────────────────────────────── data ───────────────────────────────────────
def _resolve_creds():
    """Read-only market-data creds: env first, else ~/.alpaca/credentials (paper
    key pair; market data is identical for paper/live and we place no orders).
    PII-clean: no keys are printed or stored."""
    key, sec = os.getenv("ALPACA_KEY"), os.getenv("ALPACA_SECRET")
    if not (key and sec):
        path = Path.home() / ".alpaca" / "credentials"
        if path.exists():
            for line in path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = (s.strip() for s in line.split("=", 1))
                if k == "ALPACA_KEY" and not key:
                    key = v
                elif k == "ALPACA_SECRET" and not sec:
                    sec = v
    if not (key and sec):
        sys.exit("ERROR: no Alpaca creds (ALPACA_KEY/ALPACA_SECRET) in env or ~/.alpaca/credentials.")
    return key, sec


def fetch_bars(symbols, start, end, refresh=False):
    """Daily bars, split-adjusted, free IEX feed. Returns {sym: DataFrame(index=date,
    cols=[open,high,low,close,volume])}. Caches to disk for fast re-runs."""
    if CACHE.exists() and not refresh:
        cached = pd.read_pickle(CACHE)
        if set(symbols) <= set(cached.keys()) and cached.get("__meta__") == (start, end):
            print(f"[data] using cache {CACHE.name} ({len(symbols)} syms, {start}..{end})")
            return {s: cached[s] for s in symbols}

    key, sec = _resolve_creds()
    sess = requests.Session()
    sess.headers.update({"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec})
    url = f"{DATA_BASE}/stocks/bars"
    out = {}
    allsyms = list(symbols)
    print(f"[data] fetching {len(allsyms)} symbols from Alpaca IEX daily bars {start}..{end} ...")
    for i in range(0, len(allsyms), 100):
        batch = allsyms[i:i + 100]
        params = {
            "symbols": ",".join(batch), "timeframe": "1Day",
            "start": f"{start}T00:00:00Z", "end": f"{end}T23:59:59Z",
            "adjustment": "split", "feed": "iex", "limit": 10000,
        }
        while True:
            r = sess.get(url, params=params, timeout=40)
            r.raise_for_status()
            data = r.json()
            for sym, bars in (data.get("bars") or {}).items():
                out.setdefault(sym, []).extend(bars)
            token = data.get("next_page_token")
            if not token:
                break
            params["page_token"] = token
        time.sleep(0.2)

    frames = {}
    for sym, bars in out.items():
        if not bars:
            continue
        df = pd.DataFrame(bars)
        df["date"] = pd.to_datetime(df["t"]).dt.tz_convert("America/New_York").dt.date
        df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
        df = df[["date", "open", "high", "low", "close", "volume"]].drop_duplicates("date")
        df = df.set_index("date").sort_index()
        frames[sym] = df

    cached = {**frames, "__meta__": (start, end)}
    pd.to_pickle(cached, CACHE)
    print(f"[data] fetched {len(frames)} symbols, cached to {CACHE.name}")
    return {s: frames[s] for s in symbols if s in frames}


# ──────────────────────────── indicators ─────────────────────────────────────
def wilder_rsi(close, period):
    """Wilder's RSI (the standard Connors uses). period=2 -> alpha=0.5."""
    delta = close.diff()
    up = delta.clip(lower=0.0)
    down = (-delta).clip(lower=0.0)
    roll_up = up.ewm(alpha=1.0 / period, adjust=False).mean()
    roll_down = down.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = roll_up / roll_down
    rsi = 100.0 - 100.0 / (1.0 + rs)
    rsi = rsi.where(roll_down != 0, 100.0)   # all-up window -> 100
    rsi = rsi.where(roll_up != 0, 0.0)       # all-down window -> 0
    return rsi


def compute_indicators(df, cfg):
    d = df.copy()
    c = d["close"]
    d["rsi"] = wilder_rsi(c, cfg["rsi_period"])
    d["sma_trend"] = c.rolling(cfg["sma_trend"]).mean()
    d["sma_exit"] = c.rolling(cfg["sma_exit"]).mean()
    return d


def entry_signal(row, cfg):
    if cfg["use_trend_filter"]:
        if pd.isna(row["sma_trend"]) or not (row["close"] > row["sma_trend"]):
            return False
    return (not pd.isna(row["rsi"])) and row["rsi"] < cfg["entry_rsi"]


# ──────────────────────────── portfolio backtest ─────────────────────────────
def run_backtest(data, cfg, drop_names=None):
    """Event-driven daily portfolio sim. Returns (equity_series, trades_df)."""
    drop_names = set(drop_names or [])
    syms = [s for s in data if s not in drop_names and s != BENCH]

    ind = {s: compute_indicators(data[s], cfg) for s in syms}
    pos_map = {s: {dt: i for i, dt in enumerate(ind[s].index)} for s in syms}
    all_dates = sorted(set().union(*[set(ind[s].index) for s in syms]))

    cash = cfg["start_equity"]
    positions = {}   # sym -> dict(shares, entry, entry_date)
    equity_curve = {}
    trades = []
    cost = cfg["cost_bps"] / 1e4
    alloc_frac = 1.0 / cfg["max_positions"]

    for dt in all_dates:
        # ---- manage open positions (exits) ----
        for sym in list(positions.keys()):
            p = positions[sym]
            if dt not in pos_map[sym]:
                continue
            row = ind[sym].loc[dt]
            bars_held = pos_map[sym][dt] - pos_map[sym][p["entry_date"]]
            if bars_held < 1:
                continue  # no same-day exit
            exit_now = False
            reason = None
            if cfg["exit_mode"] == "rsi70":
                if not pd.isna(row["rsi"]) and row["rsi"] > cfg["exit_rsi"]:
                    exit_now, reason = True, "rsi_up"
            else:  # sma5 exit
                if not pd.isna(row["sma_exit"]) and row["close"] > row["sma_exit"]:
                    exit_now, reason = True, "sma5"
            if not exit_now and bars_held >= cfg["max_hold"]:
                exit_now, reason = True, "max_hold"
            if exit_now:
                exit_price = row["close"]
                proceeds = p["shares"] * exit_price
                cash += proceeds - proceeds * cost
                pnl = (p["shares"] * (exit_price - p["entry"])
                       - (p["shares"] * p["entry"] + proceeds) * cost)
                trades.append(dict(
                    sym=sym, entry_date=p["entry_date"], exit_date=dt,
                    entry=p["entry"], exit=exit_price, shares=p["shares"],
                    pnl=pnl, ret_pct=exit_price / p["entry"] - 1.0,
                    hold_days=bars_held, reason=reason,
                    entry_rsi=p["entry_rsi"],
                ))
                del positions[sym]

        # ---- mark-to-market ----
        mtm = cash
        for sym, p in positions.items():
            px = ind[sym].loc[dt, "close"] if dt in pos_map[sym] else p["entry"]
            mtm += p["shares"] * px
        equity_curve[dt] = mtm

        # ---- entries (rank by most-oversold, fill open slots) ----
        free = cfg["max_positions"] - len(positions)
        if free <= 0:
            continue
        candidates = []
        for sym in syms:
            if sym in positions or dt not in pos_map[sym]:
                continue
            row = ind[sym].loc[dt]
            if entry_signal(row, cfg):
                candidates.append((row["rsi"], sym, row))
        candidates.sort(key=lambda x: x[0])   # lowest RSI (most oversold) first
        for _rv, sym, row in candidates[:free]:
            entry = row["close"]
            alloc = alloc_frac * mtm
            shares = int(alloc / entry)
            if shares <= 0:
                continue
            notional = shares * entry
            if notional + notional * cost > cash:
                shares = int(cash / (entry * (1 + cost)))
                notional = shares * entry
            if shares <= 0:
                continue
            cash -= notional + notional * cost
            positions[sym] = dict(shares=shares, entry=entry, entry_date=dt,
                                  entry_rsi=float(row["rsi"]))

    # close any still-open at last price
    last_dt = all_dates[-1]
    for sym, p in list(positions.items()):
        px = ind[sym].loc[last_dt, "close"] if last_dt in pos_map[sym] else p["entry"]
        proceeds = p["shares"] * px
        cash += proceeds - proceeds * cost
        pnl = p["shares"] * (px - p["entry"]) - (p["shares"] * p["entry"] + proceeds) * cost
        trades.append(dict(
            sym=sym, entry_date=p["entry_date"], exit_date=last_dt,
            entry=p["entry"], exit=px, shares=p["shares"], pnl=pnl,
            ret_pct=px / p["entry"] - 1.0,
            hold_days=pos_map[sym].get(last_dt, 0) - pos_map[sym][p["entry_date"]],
            reason="eod_close", entry_rsi=p["entry_rsi"],
        ))
    eq = pd.Series(equity_curve).sort_index()
    return eq, pd.DataFrame(trades)


# ──────────────────────────── metrics ────────────────────────────────────────
def perf_metrics(eq):
    eq = eq.dropna()
    if len(eq) < 2:
        return {}
    rets = eq.pct_change().dropna()
    years = len(eq) / TRADING_DAYS
    total_ret = eq.iloc[-1] / eq.iloc[0] - 1
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1 if years > 0 else 0
    dd = eq / eq.cummax() - 1
    max_dd = dd.min()
    mar = cagr / abs(max_dd) if max_dd < 0 else float("nan")
    downside = rets[rets < 0]
    dd_std = downside.std()
    sortino = (rets.mean() / dd_std) * np.sqrt(TRADING_DAYS) if dd_std and dd_std > 0 else float("nan")
    vol = rets.std() * np.sqrt(TRADING_DAYS)
    return dict(total_return=total_ret, cagr=cagr, max_dd=max_dd, mar=mar,
                sortino=sortino, vol=vol, end_equity=eq.iloc[-1])


def trade_stats(trades):
    if trades is None or len(trades) == 0:
        return dict(n_trades=0, win_rate=float("nan"), profit_factor=float("nan"),
                    avg_hold=float("nan"), avg_win=float("nan"), avg_loss=float("nan"),
                    avg_win_pct=float("nan"), avg_loss_pct=float("nan"),
                    worst_pnl=float("nan"), worst_pct=float("nan"))
    wins = trades[trades["pnl"] > 0]
    losses = trades[trades["pnl"] < 0]
    gross_win = wins["pnl"].sum()
    gross_loss = -losses["pnl"].sum()
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    return dict(
        n_trades=len(trades),
        win_rate=(trades["pnl"] > 0).mean(),
        profit_factor=pf,
        avg_hold=trades["hold_days"].mean(),
        avg_win=wins["pnl"].mean() if len(wins) else float("nan"),
        avg_loss=losses["pnl"].mean() if len(losses) else float("nan"),
        avg_win_pct=wins["ret_pct"].mean() if len(wins) else float("nan"),
        avg_loss_pct=losses["ret_pct"].mean() if len(losses) else float("nan"),
        worst_pnl=trades["pnl"].min(),
        worst_pct=trades["ret_pct"].min(),
    )


def spy_buyhold(spy_df, dates, start_equity):
    dates = list(dates)
    d0 = spy_df.index[spy_df.index >= dates[0]][0]
    sh = start_equity / spy_df.loc[d0, "close"]
    curve = {}
    for dt in dates:
        idx = spy_df.index[spy_df.index <= dt]
        if len(idx):
            curve[dt] = sh * spy_df.loc[idx[-1], "close"]
    return pd.Series(curve).sort_index()


def ew_buyhold(data, syms, dates, start_equity):
    dates = list(dates)
    per = start_equity / len(syms)
    shares, curve = {}, {}
    for s in syms:
        df = data[s]
        avail = df.index[df.index >= dates[0]]
        if len(avail):
            shares[s] = per / df.loc[avail[0], "close"]
    for dt in dates:
        v = 0.0
        for s, sh in shares.items():
            idx = data[s].index[data[s].index <= dt]
            if len(idx):
                v += sh * data[s].loc[idx[-1], "close"]
        curve[dt] = v
    return pd.Series(curve).sort_index()


# ──────────────────────────── reporting ──────────────────────────────────────
def _p(x, pct=True, d=1):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    return f"{x*100:.{d}f}%" if pct else f"{x:.2f}"


def fmt_row(name, m, ts=None):
    line = (f"{name:<30} tot={_p(m.get('total_return')):>8}  CAGR={_p(m.get('cagr')):>7}  "
            f"maxDD={_p(m.get('max_dd')):>7}  MAR={_p(m.get('mar'), False):>5}  "
            f"Sortino={_p(m.get('sortino'), False):>5}")
    if ts:
        line += (f"  WR={_p(ts.get('win_rate')):>6}  PF={_p(ts.get('profit_factor'), False):>5}  "
                 f"n={ts.get('n_trades')}  hold={ts.get('avg_hold', float('nan')):.1f}d")
    return line


def kpi(m):
    mar, sor = m.get("mar", float("nan")), m.get("sortino", float("nan"))
    ok = (not np.isnan(mar) and mar >= 0.5) and (not np.isnan(sor) and sor >= 1.0)
    return "PASS" if ok else "FAIL"


# ──────────────────────────────── main ───────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    print(f"RSI-2 oversold kill-test | window {START}..{END} | universe {len(UNIVERSE)} liquid large-caps")
    data = fetch_bars(UNIVERSE + [BENCH], START, END, refresh=args.refresh)
    uni = [s for s in UNIVERSE if s in data]
    spy_df = data[BENCH]
    missing = [s for s in UNIVERSE if s not in data]
    if missing:
        print(f"[warn] missing bars for: {missing}")
    sample = {s: (data[s].index.min(), data[s].index.max(), len(data[s])) for s in uni[:2]}
    print(f"[data] {len(uni)} names, sample coverage: {sample}")

    results = {}

    # ---------- BASE RUN ----------
    cfg = dict(DEFAULTS)
    eq, trades = run_backtest(data, cfg)
    m = perf_metrics(eq); ts = trade_stats(trades)
    dates = eq.index
    spy_eq = spy_buyhold(spy_df, dates, cfg["start_equity"])
    ew_eq = ew_buyhold(data, uni, dates, cfg["start_equity"])
    m_spy, m_ew = perf_metrics(spy_eq), perf_metrics(ew_eq)

    print("\n=== BASE RUN (entry RSI(2)<10, exit RSI(2)>70, max-hold 10d, cost 5bps 1-way) ===")
    print(fmt_row("RSI-2 strategy", m, ts) + f"   [{kpi(m)}]")
    print(fmt_row("Buy&Hold SPY (yardstick)", m_spy))
    print(fmt_row("Buy&Hold EW-universe (yardstick)", m_ew))

    results["base"] = dict(strategy=m, strat_trades=ts, spy=m_spy, ew=m_ew, verdict=kpi(m))

    # ---------- WIN-RATE MIRAGE ----------
    print("\n=== WIN-RATE MIRAGE (many small wins vs the rare falling knife) ===")
    print(f"  Win rate: {_p(ts['win_rate'])}   Profit factor: {_p(ts['profit_factor'], False)}   "
          f"trades: {ts['n_trades']}   avg hold: {ts['avg_hold']:.1f} trading days")
    print(f"  Avg WIN : ${ts['avg_win']:,.0f}  ({_p(ts['avg_win_pct'])} per trade)")
    print(f"  Avg LOSS: ${ts['avg_loss']:,.0f}  ({_p(ts['avg_loss_pct'])} per trade)")
    ratio = abs(ts['avg_loss'] / ts['avg_win']) if ts['avg_win'] else float('nan')
    print(f"  Avg loss / avg win = {ratio:.2f}x   (the classic mean-reversion asymmetry)")
    worst = trades.nsmallest(5, "pnl")
    print(f"  Worst single trade: {worst.iloc[0]['sym']} {worst.iloc[0]['entry_date']}"
          f"->{worst.iloc[0]['exit_date']}  {_p(worst.iloc[0]['ret_pct'])}  "
          f"(${worst.iloc[0]['pnl']:,.0f}, held {int(worst.iloc[0]['hold_days'])}d, "
          f"exit={worst.iloc[0]['reason']})")
    knives = trades[(trades["pnl"] < 0) & (trades["reason"] == "max_hold")]
    print(f"  'Oversold got MORE oversold' (losers that hit the max-hold backstop, never recovered): "
          f"{len(knives)} trades, total ${knives['pnl'].sum():,.0f}, "
          f"avg {_p(knives['ret_pct'].mean()) if len(knives) else '—'}")

    results["winrate_mirage"] = dict(
        win_rate=ts["win_rate"], profit_factor=ts["profit_factor"],
        avg_win=ts["avg_win"], avg_loss=ts["avg_loss"],
        avg_win_pct=ts["avg_win_pct"], avg_loss_pct=ts["avg_loss_pct"],
        loss_win_ratio=ratio, worst_pct=ts["worst_pct"], worst_pnl=ts["worst_pnl"],
        n_knives=len(knives), knives_pnl=float(knives["pnl"].sum()),
        worst5=[dict(sym=r["sym"], entry=str(r["entry_date"]), exit=str(r["exit_date"]),
                     ret_pct=r["ret_pct"], pnl=r["pnl"], hold=int(r["hold_days"]),
                     reason=r["reason"]) for _, r in worst.iterrows()],
    )

    # ---------- KILL-TEST 1: DROP TOP-5 ----------
    print("\n=== KILL-TEST 1: drop-top-5 (trades and names) ===")
    total_pnl = trades["pnl"].sum()
    top5_trades = trades.nlargest(5, "pnl")
    top5_trades_pnl = top5_trades["pnl"].sum()
    pnl_by_name = trades.groupby("sym")["pnl"].sum().sort_values(ascending=False)
    top5_names = list(pnl_by_name.head(5).index)
    top5_names_pnl = pnl_by_name.head(5).sum()
    print(f"  Total NET trade P&L: ${total_pnl:,.0f}")
    print(f"  Top-5 TRADES = ${top5_trades_pnl:,.0f} ({top5_trades_pnl/total_pnl*100:.0f}% of net P&L)")
    print(f"  Top-5 NAMES  = ${top5_names_pnl:,.0f} ({top5_names_pnl/total_pnl*100:.0f}% of net P&L) "
          f"-> {list(zip(top5_names, pnl_by_name.head(5).round(0).astype(int).tolist()))}")
    eq_dn, tr_dn = run_backtest(data, cfg, drop_names=top5_names)
    m_dn = perf_metrics(eq_dn); ts_dn = trade_stats(tr_dn)
    print(fmt_row("  re-run w/o top-5 NAMES", m_dn, ts_dn) + f"   [{kpi(m_dn)}]")
    # drop the top-5 individual trades from the equity contribution (approx via P&L removal)
    approx_end = cfg["start_equity"] + (total_pnl - top5_trades_pnl)
    print(f"  If the 5 single best trades are removed, ending equity ~${approx_end:,.0f} "
          f"vs base ${m['end_equity']:,.0f} (net P&L falls {top5_trades_pnl/total_pnl*100:.0f}%).")
    results["drop_top5"] = dict(
        total_pnl=total_pnl, top5_trades_pnl=top5_trades_pnl,
        top5_trades_share=top5_trades_pnl / total_pnl,
        top5_names=top5_names, top5_names_pnl=top5_names_pnl,
        top5_names_share=top5_names_pnl / total_pnl,
        drop_names_metrics=m_dn, drop_names_verdict=kpi(m_dn),
    )

    # ---------- KILL-TEST 2: COST SENSITIVITY ----------
    print("\n=== KILL-TEST 2: cost sensitivity (RSI-2 trades a LOT) ===")
    cost_rows = {}
    for cb in [0.0, 5.0, 10.0]:
        c = dict(DEFAULTS); c["cost_bps"] = cb
        e, t = run_backtest(data, c)
        mm = perf_metrics(e)
        label = {0.0: "0 bps (frictionless)", 5.0: "5 bps 1-way (base, 10 rt)",
                 10.0: "10 bps 1-way (2x, 20 rt)"}[cb]
        print(fmt_row(label, mm, trade_stats(t)) + f"   [{kpi(mm)}]")
        cost_rows[str(cb)] = dict(m=mm, verdict=kpi(mm), n_trades=len(t))
    results["cost"] = cost_rows

    # ---------- KILL-TEST 3: PARAMETER SWEEP ----------
    print("\n=== KILL-TEST 3: parameter sweep (entry x exit x max-hold) ===")
    sweep = {}
    n_pass = 0
    print(f"  {'entry':<7}{'exit':<8}{'hold':<6}{'CAGR':>8}{'maxDD':>8}{'MAR':>7}{'Sortino':>9}{'WR':>7}{'n':>6}  bar")
    for entry in [5, 10, 15]:
        for exit_mode in ["rsi70", "sma5"]:
            for hold in [5, 10]:
                c = dict(DEFAULTS)
                c["entry_rsi"] = float(entry); c["exit_mode"] = exit_mode; c["max_hold"] = hold
                e, t = run_backtest(data, c)
                mm = perf_metrics(e); tt = trade_stats(t)
                v = kpi(mm)
                if v == "PASS":
                    n_pass += 1
                key = f"entry{entry}|{exit_mode}|hold{hold}"
                sweep[key] = dict(cagr=mm.get("cagr"), max_dd=mm.get("max_dd"),
                                  mar=mm.get("mar"), sortino=mm.get("sortino"),
                                  win_rate=tt.get("win_rate"), n=len(t), verdict=v)
                print(f"  <{entry:<6}{exit_mode:<8}{hold:<6}{_p(mm.get('cagr')):>8}"
                      f"{_p(mm.get('max_dd')):>8}{_p(mm.get('mar'), False):>7}"
                      f"{_p(mm.get('sortino'), False):>9}{_p(tt.get('win_rate')):>7}{len(t):>6}  [{v}]")
    print(f"  Configs passing MAR>=0.5 AND Sortino>=1.0: {n_pass}/{len(sweep)}")
    results["sweep"] = dict(n_pass=n_pass, n_total=len(sweep), grid=sweep)

    # ---------- KILL-TEST 4: REGIME DEPENDENCE ----------
    print("\n=== KILL-TEST 4: regime dependence (does it need V-shaped recoveries?) ===")
    tr = trades.copy()
    tr["entry_year"] = pd.to_datetime(tr["entry_date"]).dt.year
    by_year = tr.groupby("entry_year")["pnl"].agg(["sum", "count"])
    for yr, r in by_year.iterrows():
        print(f"  {int(yr)}: P&L ${r['sum']:>10,.0f}   ({int(r['count'])} trades)")
    # P&L from trades ENTERED during the two big V-recoveries
    ed = pd.to_datetime(tr["entry_date"])
    v2020 = tr[(ed >= "2020-08-01") & (ed <= "2020-12-31")]["pnl"].sum()  # tail of COVID rip
    v2022 = tr[(ed >= "2022-01-01") & (ed <= "2022-12-31")]["pnl"].sum()  # 2022 bear dips
    best_month = tr.assign(ym=ed.dt.to_period("M")).groupby("ym")["pnl"].sum().sort_values(ascending=False)
    print(f"  P&L from trades entered in 2022 (bear-market dips): ${v2022:,.0f} "
          f"({v2022/total_pnl*100:.0f}% of net)")
    print(f"  Best single month by entry-cohort P&L: {best_month.index[0]} = ${best_month.iloc[0]:,.0f} "
          f"({best_month.iloc[0]/total_pnl*100:.0f}% of net)")
    results["regime"] = dict(
        by_year={int(y): dict(pnl=float(r["sum"]), n=int(r["count"])) for y, r in by_year.iterrows()},
        pnl_2022=float(v2022), pnl_2022_share=float(v2022 / total_pnl),
        best_month=str(best_month.index[0]), best_month_pnl=float(best_month.iloc[0]),
        best_month_share=float(best_month.iloc[0] / total_pnl),
    )

    # ---------- GREEN KEEPER: what's load-bearing? ----------
    print("\n=== GREEN KEEPER: component isolation (what is actually doing the work?) ===")
    c_nofilter = dict(DEFAULTS); c_nofilter["use_trend_filter"] = False
    e_nf, t_nf = run_backtest(data, c_nofilter)
    m_nf = perf_metrics(e_nf); ts_nf = trade_stats(t_nf)
    print(fmt_row("Full RSI-2 (200d filter ON)", m, ts) + f"   [{kpi(m)}]")
    print(fmt_row("RSI-2, NO 200d filter", m_nf, ts_nf) + f"   [{kpi(m_nf)}]")
    print("  -> If removing the 200-day trend filter guts the risk-adjusted numbers, the filter —")
    print("     not the 2-period RSI timing — is carrying the strategy.")
    results["keeper"] = dict(full=dict(m=m, ts=ts), no_trend_filter=dict(m=m_nf, ts=ts_nf))

    # ---------- export curve_data.json ----------
    def norm(series):
        s = series.dropna()
        base = s.iloc[0]
        return [round(float(x / base), 6) for x in s.values]

    common = eq.index
    curve = {
        "meta": dict(
            generated=date.today().isoformat(), source="alpaca-iex-split-adjusted",
            window_start=str(common[0]), window_end=str(common[-1]),
            trading_days=len(common), universe_size=len(uni),
            base_config="entry RSI(2)<10, exit RSI(2)>70, max-hold 10d, 5bps 1-way cost",
            kpi_bar="MAR>=0.5 AND Sortino>=1.0",
        ),
        "dates": [str(d) for d in common],
        "curves": dict(
            rsi2_base=norm(eq),
            spy_buyhold=norm(spy_eq.reindex(common).ffill()),
            ew_universe_buyhold=norm(ew_eq.reindex(common).ffill()),
        ),
        "stats": dict(
            rsi2_base=_clean(m), spy_buyhold=_clean(m_spy), ew_universe=_clean(m_ew),
            rsi2_trades=_clean(ts),
        ),
        "killtests": _clean(dict(
            winrate_mirage=results["winrate_mirage"],
            drop_top5=results["drop_top5"],
            cost=results["cost"],
            sweep=results["sweep"],
            regime=results["regime"],
            keeper=dict(full=_clean(m), no_trend_filter=_clean(m_nf)),
        )),
    }
    (BASE_DIR / "curve_data.json").write_text(json.dumps(curve, default=str))
    print(f"\nWrote curve_data.json ({len(common)} dates, 3 curves + stats + kill-tests).")
    return results


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(x) for x in o]
    if isinstance(o, float):
        return None if np.isnan(o) else round(o, 6)
    if isinstance(o, (np.floating, np.integer)):
        return _clean(float(o))
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


if __name__ == "__main__":
    main()
