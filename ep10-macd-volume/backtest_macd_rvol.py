#!/usr/bin/env python3
"""
backtest_macd_rvol.py — Honest kill-test of the MACD + RVOL momentum strategy
described in MACD_RVOL_MOMENTUM_STRATEGY.md, for "The Backtest Graveyard".

RESEARCH ONLY. Read-only market data (Alpaca IEX daily bars). Places no orders,
touches no live bot, reveals no live signal. Reproducible & PII-clean.

Strategy implemented as specified (defaults: MACD 12/26/9, RVOL>=1.5, ATR 1.5x):
  ENTRY (long, all true on the decision close):
    1. MACD histogram crosses negative->positive (bullish MACD/signal crossover).
    2. Regime: crossover at/above zero line, OR close>EMA50 with EMA50 rising.
    3. RVOL = vol / trailing-20d-avg-vol >= threshold (configurable; the gate).
    4. Liquidity: 20d avg $-volume >= $20M and 20d avg shares >= 1M (universe pre-filter).
    5. Price action: close in upper half of the bar's range (reject exhaustion candles).
  EXIT (asymmetric):
    - Structural stop below recent swing low, ATR-floor as backstop (per-trade risk cap).
    - ATR trailing stop ratchets up under the running high (let winners run).
    - MACD bearish crossover WITH elevated RVOL = distribution -> exit.
    - Time/decay stop: held > N days, not in profit, RVOL collapsed -> recycle.
  SIZING: fixed-fractional risk; shares = risk$ / (entry-stop). Many parallel names.

Configurable so the robustness sweep (RVOL 1.2/1.5/2.0/2.5; MACD 8/21/5 & 19/39/9)
and the RVOL-isolation test (MACD-only vs MACD+RVOL) run from one code path.

Usage:
  python3 backtest_macd_rvol.py --all           # base run + all kill-tests + charts
  python3 backtest_macd_rvol.py --base          # just the headline base run
  python3 backtest_macd_rvol.py --refresh        # re-fetch bars (ignore cache)
"""

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

BASE_DIR = Path(__file__).resolve().parent
CACHE = BASE_DIR / "scratchpad_macd_rvol_bars.pkl"  # local bar cache for fast re-runs
DATA_BASE = "https://data.alpaca.markets/v2"

# ─────────────────────────── universe & window ───────────────────────────────
# ~55 of the most liquid US large-caps (S&P 100 core). All clear the $-volume
# floor by a wide margin, so the liquidity gate is not what's being tested here.
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

# ───────────────────────────── strategy config ───────────────────────────────
DEFAULTS = dict(
    macd_fast=12, macd_slow=26, macd_signal=9,
    rvol_thresh=1.5, rvol_lookback=20,
    ema_trend=50, swing_lookback=10, atr_period=14, atr_mult=1.5,
    risk_frac=0.0075,          # 0.75% of equity risked per trade
    max_positions=12,          # parallel uncorrelated names
    max_pos_frac=0.15,         # cap any single position at 15% of equity
    # Liquidity floor: the doc specifies >=$20M ADV / >=1M shares as a UNIVERSE
    # pre-filter. Our universe is 55 pre-screened liquid large-caps, so it passes
    # by construction. Critically, the free IEX feed reports only IEX-exchange
    # volume (~2-3% of consolidated), so an absolute $20M/1M floor mis-scales and
    # would wrongly drop ~85% of valid signals (3284->510 crossovers). We set the
    # floor to 0 (universe IS the liquidity filter) and rely on the RVOL *ratio*,
    # which is unaffected because numerator and baseline share the same IEX scale.
    dollar_vol_floor=0.0, share_vol_floor=0.0,
    exit_rvol=1.5,             # bearish MACD cross must come with elevated RVOL
    time_stop_days=60,         # decay stop window
    use_rvol_gate=True,        # RVOL-isolation switch
    cost_bps=5.0,              # one-way cost (spread+slippage+commission), bps of notional
    start_equity=100_000.0,
)

# Realistic one-way cost for liquid large caps: ~2-3 bps spread/2 + ~2 bps
# slippage + ~0 commission. 5 bps one-way (10 bps round-trip) is a fair base;
# the cost test also runs 0x and 2x (10 bps one-way / 20 bps round-trip).

TRADING_DAYS = 252


# ──────────────────────────────── data ───────────────────────────────────────
def _resolve_creds():
    """Read-only market-data creds. Prefers env, falls back to ~/.alpaca/credentials.
    Uses the paper key pair (ALPACA_KEY/SECRET); market data is identical for
    paper & live and we place no orders. PII-clean: no keys printed or stored."""
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
    cols=[open,high,low,close,volume])}. Caches to disk for fast sweep re-runs."""
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
def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def compute_indicators(df, cfg):
    d = df.copy()
    c = d["close"]
    macd = ema(c, cfg["macd_fast"]) - ema(c, cfg["macd_slow"])
    sig = ema(macd, cfg["macd_signal"])
    d["macd"] = macd
    d["signal"] = sig
    d["hist"] = macd - sig
    d["hist_prev"] = d["hist"].shift(1)
    d["ema_trend"] = ema(c, cfg["ema_trend"])
    d["ema_trend_prev5"] = d["ema_trend"].shift(5)
    # ATR (Wilder)
    prev_close = c.shift(1)
    tr = pd.concat([
        d["high"] - d["low"],
        (d["high"] - prev_close).abs(),
        (d["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1 / cfg["atr_period"], adjust=False).mean()
    # RVOL vs trailing-N avg volume (excluding today)
    d["avg_vol"] = d["volume"].shift(1).rolling(cfg["rvol_lookback"]).mean()
    d["rvol"] = d["volume"] / d["avg_vol"]
    d["avg_dollar_vol"] = (d["close"] * d["volume"]).shift(1).rolling(cfg["rvol_lookback"]).mean()
    # structural swing low (excluding today)
    d["swing_low"] = d["low"].shift(1).rolling(cfg["swing_lookback"]).min()
    # price-action: close position within the bar's range
    rng = (d["high"] - d["low"]).replace(0, np.nan)
    d["close_pos"] = (d["close"] - d["low"]) / rng
    return d


def entry_signal(row, cfg):
    """All entry conditions on the decision close. Returns True/False."""
    # 1. momentum trigger: histogram crosses negative -> positive
    if not (row["hist"] > 0 and row["hist_prev"] <= 0):
        return False
    # 4. liquidity pre-filter
    if not (row["avg_dollar_vol"] >= cfg["dollar_vol_floor"] and row["avg_vol"] >= cfg["share_vol_floor"]):
        return False
    # 2. regime / trend alignment
    regime = (row["macd"] >= 0) or (
        row["close"] > row["ema_trend"] and row["ema_trend"] >= row["ema_trend_prev5"]
    )
    if not regime:
        return False
    # 3. RVOL conviction gate (the switch under test)
    if cfg["use_rvol_gate"] and not (row["rvol"] >= cfg["rvol_thresh"]):
        return False
    # 5. price-action confirmation: close in upper half (reject exhaustion)
    if not (row["close_pos"] >= 0.5):
        return False
    return True


# ──────────────────────────── portfolio backtest ─────────────────────────────
def run_backtest(data, cfg, drop_names=None, verbose=False):
    """Event-driven daily portfolio sim. Returns (equity_series, trades_df)."""
    drop_names = set(drop_names or [])
    syms = [s for s in data if s not in drop_names]

    ind = {s: compute_indicators(data[s], cfg) for s in syms}
    # union of all dates
    all_dates = sorted(set().union(*[set(ind[s].index) for s in syms]))

    cash = cfg["start_equity"]
    positions = {}  # sym -> dict(shares, entry, stop, high, entry_date, entry_rvol)
    equity_curve = {}
    trades = []
    cost = cfg["cost_bps"] / 1e4

    for dt in all_dates:
        # ---- manage open positions (exits) ----
        for sym in list(positions.keys()):
            p = positions[sym]
            if dt not in ind[sym].index:
                continue
            row = ind[sym].loc[dt]
            exit_price = None
            reason = None
            # 1. stop-loss (intraday). Gap-through -> fill at open.
            if row["low"] <= p["stop"]:
                exit_price = min(row["open"], p["stop"]) if row["open"] < p["stop"] else p["stop"]
                reason = "stop"
            else:
                # 2. MACD bearish cross WITH elevated RVOL
                bearish = (row["hist"] < 0 and row["hist_prev"] >= 0)
                if bearish and row["rvol"] >= cfg["exit_rvol"]:
                    exit_price = row["close"]
                    reason = "macd_bear"
                else:
                    # 3. time/decay stop
                    held = (dt - p["entry_date"]).days
                    if (held > cfg["time_stop_days"] and row["close"] <= p["entry"]
                            and row["rvol"] < 1.0):
                        exit_price = row["close"]
                        reason = "time_decay"
            if exit_price is not None:
                proceeds = p["shares"] * exit_price
                cash += proceeds - proceeds * cost
                pnl = p["shares"] * (exit_price - p["entry"]) - (
                    p["shares"] * p["entry"] + proceeds) * cost
                trades.append(dict(
                    sym=sym, entry_date=p["entry_date"], exit_date=dt,
                    entry=p["entry"], exit=exit_price, shares=p["shares"],
                    pnl=pnl, r_mult=pnl / p["risk_dollars"] if p["risk_dollars"] else 0,
                    hold_days=(dt - p["entry_date"]).days, reason=reason,
                ))
                del positions[sym]
            else:
                # ratchet ATR trailing stop under running high
                p["high"] = max(p["high"], row["high"])
                trail = p["high"] - cfg["atr_mult"] * row["atr"]
                p["stop"] = max(p["stop"], trail)

        # ---- mark-to-market equity ----
        mtm = cash
        for sym, p in positions.items():
            px = ind[sym].loc[dt, "close"] if dt in ind[sym].index else p["entry"]
            mtm += p["shares"] * px
        equity_curve[dt] = mtm

        # ---- entries (rank candidates by RVOL, fill open slots) ----
        free = cfg["max_positions"] - len(positions)
        if free <= 0:
            continue
        candidates = []
        for sym in syms:
            if sym in positions or dt not in ind[sym].index:
                continue
            row = ind[sym].loc[dt]
            if row.isna().get("atr", True) or pd.isna(row["swing_low"]) or pd.isna(row["rvol"]):
                continue
            if entry_signal(row, cfg):
                candidates.append((row["rvol"], sym, row))
        candidates.sort(key=lambda x: -x[0])
        for _rv, sym, row in candidates[:free]:
            entry = row["close"]
            atr_floor_stop = entry - cfg["atr_mult"] * row["atr"]
            stop = max(row["swing_low"], atr_floor_stop)  # tighter (higher) = risk cap
            if stop >= entry:
                continue
            risk_dollars = cfg["risk_frac"] * mtm
            per_share_risk = entry - stop
            shares = int(risk_dollars / per_share_risk)
            if shares <= 0:
                continue
            notional = shares * entry
            # cap single position size
            if notional > cfg["max_pos_frac"] * mtm:
                shares = int((cfg["max_pos_frac"] * mtm) / entry)
                notional = shares * entry
            if shares <= 0 or notional + notional * cost > cash:
                continue
            cash -= notional + notional * cost
            positions[sym] = dict(
                shares=shares, entry=entry, stop=stop, high=row["high"],
                entry_date=dt, entry_rvol=row["rvol"],
                risk_dollars=shares * per_share_risk,
            )

    # close any still-open at last price
    last_dt = all_dates[-1]
    for sym, p in list(positions.items()):
        px = ind[sym].loc[last_dt, "close"] if last_dt in ind[sym].index else p["entry"]
        proceeds = p["shares"] * px
        cash += proceeds - proceeds * cost
        pnl = p["shares"] * (px - p["entry"]) - (p["shares"] * p["entry"] + proceeds) * cost
        trades.append(dict(
            sym=sym, entry_date=p["entry_date"], exit_date=last_dt,
            entry=p["entry"], exit=px, shares=p["shares"], pnl=pnl,
            r_mult=pnl / p["risk_dollars"] if p["risk_dollars"] else 0,
            hold_days=(last_dt - p["entry_date"]).days, reason="eod_close",
        ))
    eq = pd.Series(equity_curve).sort_index()
    return eq, pd.DataFrame(trades)


# ──────────────────────────── metrics ────────────────────────────────────────
def perf_metrics(eq):
    eq = eq.dropna()
    if len(eq) < 2:
        return {}
    rets = eq.pct_change().dropna()
    n_days = len(eq)
    years = n_days / TRADING_DAYS
    total_ret = eq.iloc[-1] / eq.iloc[0] - 1
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1 if years > 0 else 0
    roll_max = eq.cummax()
    dd = eq / roll_max - 1
    max_dd = dd.min()
    mar = cagr / abs(max_dd) if max_dd < 0 else float("nan")
    downside = rets[rets < 0]
    dd_std = downside.std()
    sortino = (rets.mean() / dd_std) * np.sqrt(TRADING_DAYS) if dd_std and dd_std > 0 else float("nan")
    return dict(
        total_return=total_ret, cagr=cagr, max_dd=max_dd, mar=mar,
        sortino=sortino, end_equity=eq.iloc[-1],
    )


def trade_stats(trades, eq):
    if trades is None or len(trades) == 0:
        return dict(n_trades=0, win_rate=float("nan"), profit_factor=float("nan"),
                    avg_hold=float("nan"), pct_in_market=float("nan"))
    wins = trades[trades["pnl"] > 0]["pnl"].sum()
    losses = -trades[trades["pnl"] < 0]["pnl"].sum()
    pf = wins / losses if losses > 0 else float("inf")
    win_rate = (trades["pnl"] > 0).mean()
    avg_hold = trades["hold_days"].mean()
    # % time in market: avg fraction of days at least one position was open,
    # approximated by summed hold-days / (n_days * max_positions) is misleading;
    # instead report exposure = mean daily invested fraction via trade overlap.
    return dict(
        n_trades=len(trades), win_rate=win_rate, profit_factor=pf,
        avg_hold=avg_hold,
    )


def exposure_pct(eq, trades):
    """Fraction of trading days with >=1 open position."""
    if len(trades) == 0:
        return 0.0
    days = set()
    for _, t in trades.iterrows():
        rng = pd.bdate_range(t["entry_date"], t["exit_date"])
        for d in rng:
            days.add(d.date())
    return len(days & set(eq.index)) / len(eq)


def benchmark_buyhold(data, syms, dates, start_equity):
    """Equal-weight buy&hold of `syms`, rebalanced never (initial equal $)."""
    dates = list(dates)
    # align each to available closes; equal dollar at first common date
    per = start_equity / len(syms)
    shares = {}
    first_px = {}
    for s in syms:
        df = data[s]
        avail = df.index[df.index >= dates[0]]
        if len(avail) == 0:
            continue
        d0 = avail[0]
        first_px[s] = df.loc[d0, "close"]
        shares[s] = per / first_px[s]
    curve = {}
    for dt in dates:
        v = 0.0
        for s, sh in shares.items():
            df = data[s]
            idx = df.index[df.index <= dt]
            if len(idx):
                v += sh * df.loc[idx[-1], "close"]
        curve[dt] = v
    return pd.Series(curve).sort_index()


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


# ──────────────────────────── reporting ──────────────────────────────────────
def fmt_row(name, m, ts=None, exp=None):
    def p(x, pct=True, d=1):
        if x is None or (isinstance(x, float) and (np.isnan(x))):
            return "—"
        return f"{x*100:.{d}f}%" if pct else f"{x:.2f}"
    line = (f"{name:<26} tot={p(m.get('total_return')):>8}  CAGR={p(m.get('cagr')):>7}  "
            f"maxDD={p(m.get('max_dd')):>7}  MAR={p(m.get('mar'),False):>5}  "
            f"Sortino={p(m.get('sortino'),False):>5}")
    if ts:
        line += (f"  PF={p(ts.get('profit_factor'),False):>5}  WR={p(ts.get('win_rate')):>6}  "
                 f"n={ts.get('n_trades')}  hold={ts.get('avg_hold',float('nan')):.0f}d")
    if exp is not None:
        line += f"  inMkt={exp*100:.0f}%"
    return line


def kpi_verdict(m):
    mar = m.get("mar", float("nan"))
    sor = m.get("sortino", float("nan"))
    ok = (not np.isnan(mar) and mar >= 0.5) and (not np.isnan(sor) and sor >= 1.0)
    return "PASS" if ok else "FAIL", mar, sor


# ──────────────────────────────── main ───────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--base", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    if not (args.all or args.base):
        args.all = True

    print(f"MACD+RVOL kill-test | window {START}..{END} | universe {len(UNIVERSE)} liquid large-caps")
    allsyms = UNIVERSE + [BENCH]
    data = fetch_bars(allsyms, START, END, refresh=args.refresh)
    missing = [s for s in UNIVERSE if s not in data]
    if missing:
        print(f"[warn] missing bars for: {missing}")
    uni = [s for s in UNIVERSE if s in data]
    spy_df = data[BENCH]
    # coverage
    cov = {s: (data[s].index.min(), data[s].index.max(), len(data[s])) for s in uni[:3]}
    print(f"[data] sample coverage: {cov}")

    results = {}

    # ---- base run ----
    cfg = dict(DEFAULTS)
    eq, trades = run_backtest(data, cfg)
    m = perf_metrics(eq); ts = trade_stats(trades, eq); exp = exposure_pct(eq, trades)
    verdict, mar, sor = kpi_verdict(m)
    print("\n=== BASE RUN (MACD 12/26/9, RVOL>=1.5, ATR 1.5x, cost 5bps one-way) ===")
    print(fmt_row("Strategy", m, ts, exp))

    # benchmarks over the strategy's date span
    dates = eq.index
    spy_eq = spy_buyhold(spy_df, dates, cfg["start_equity"])
    ew_eq = benchmark_buyhold(data, uni, dates, cfg["start_equity"])
    m_spy = perf_metrics(spy_eq); m_ew = perf_metrics(ew_eq)
    print(fmt_row("Buy&Hold SPY", m_spy))
    print(fmt_row("Buy&Hold EW-universe", m_ew))
    print(f"KPI (MAR>=0.5 & Sortino>=1.0): {verdict}  (MAR={mar:.2f}, Sortino={sor:.2f})")

    results["base"] = dict(strategy=m, strat_trades=ts, exposure=exp,
                           spy=m_spy, ew=m_ew, verdict=verdict)

    # ---- kill-test 1: drop top-5 names & top-5 trades ----
    print("\n=== KILL-TEST 1: drop-top-5 ===")
    pnl_by_name = trades.groupby("sym")["pnl"].sum().sort_values(ascending=False)
    top5_names = list(pnl_by_name.head(5).index)
    eq_dn, tr_dn = run_backtest(data, cfg, drop_names=top5_names)
    m_dn = perf_metrics(eq_dn); v_dn, _, _ = kpi_verdict(m_dn)
    print(f"Top-5 names by P&L: {list(zip(top5_names, pnl_by_name.head(5).round(0).tolist()))}")
    print(fmt_row(f"Drop top-5 NAMES", m_dn, trade_stats(tr_dn, eq_dn)))
    # drop top-5 individual trades: recompute equity delta
    top5_trades_pnl = trades.nlargest(5, "pnl")["pnl"].sum()
    top5_names_pnl = pnl_by_name.head(5).sum()
    total_trade_pnl = trades["pnl"].sum()
    rest_names_pnl = total_trade_pnl - top5_names_pnl
    share_top5_trades = top5_trades_pnl / total_trade_pnl if abs(total_trade_pnl) > 1e-6 else float("nan")
    share_top5_names = top5_names_pnl / total_trade_pnl if abs(total_trade_pnl) > 1e-6 else float("nan")
    # When net P&L ~ 0, percentages explode; report absolute $ which tells the real story.
    print(f"Net trade P&L total = ${total_trade_pnl:,.0f}  |  top-5 NAMES = ${top5_names_pnl:,.0f}  "
          f"|  other {len(pnl_by_name)-5} names = ${rest_names_pnl:,.0f}  |  top-5 TRADES = ${top5_trades_pnl:,.0f}")
    if abs(total_trade_pnl) > 1e-6:
        print(f"Top-5 NAMES = {share_top5_names*100:.0f}% of net trade P&L; "
              f"Top-5 TRADES = {share_top5_trades*100:.0f}% of net trade P&L (base near zero -> % unstable)")
    results["drop_top5"] = dict(names=top5_names, m_drop_names=m_dn, verdict_drop=v_dn,
                                share_top5_names=share_top5_names,
                                share_top5_trades=share_top5_trades)

    # ---- kill-test 2: cost sensitivity ----
    print("\n=== KILL-TEST 2: cost sensitivity ===")
    cost_rows = {}
    for cb in [0.0, 5.0, 10.0]:
        c = dict(DEFAULTS); c["cost_bps"] = cb
        e, t = run_backtest(data, c)
        mm = perf_metrics(e)
        v, _, _ = kpi_verdict(mm)
        cost_rows[cb] = dict(m=mm, verdict=v, n=len(t))
        label = {0.0: "0 bps (frictionless)", 5.0: "5 bps 1-way (base 10 rt)", 10.0: "10 bps 1-way (2x, 20 rt)"}[cb]
        print(fmt_row(label, mm) + f"  [{v}]")
    results["cost"] = {str(k): dict(m=v["m"], verdict=v["verdict"]) for k, v in cost_rows.items()}

    # ---- kill-test 3: robustness sweep ----
    print("\n=== KILL-TEST 3: robustness sweep (RVOL x MACD periods) ===")
    macd_sets = {"12/26/9": (12, 26, 9), "8/21/5": (8, 21, 5), "19/39/9": (19, 39, 9)}
    sweep = {}
    for mname, (f, s, sg) in macd_sets.items():
        for rv in [1.2, 1.5, 2.0, 2.5]:
            c = dict(DEFAULTS)
            c["macd_fast"], c["macd_slow"], c["macd_signal"] = f, s, sg
            c["rvol_thresh"] = rv; c["exit_rvol"] = rv
            e, t = run_backtest(data, c)
            mm = perf_metrics(e)
            v, mar_, sor_ = kpi_verdict(mm)
            sweep[f"{mname}|RVOL{rv}"] = dict(mar=mm.get("mar"), sortino=mm.get("sortino"),
                                              cagr=mm.get("cagr"), maxdd=mm.get("max_dd"),
                                              n=len(t), verdict=v)
    # print as grid
    print(f"{'MACD\\RVOL':<12}" + "".join(f"{rv:>18}" for rv in [1.2, 1.5, 2.0, 2.5]))
    for mname in macd_sets:
        cells = []
        for rv in [1.2, 1.5, 2.0, 2.5]:
            k = f"{mname}|RVOL{rv}"
            r = sweep[k]
            mar_ = r["mar"]; sor_ = r["sortino"]
            cells.append(f"MAR{mar_:.2f}/So{sor_:.2f}" if mar_ == mar_ else "   —   ")
        print(f"{mname:<12}" + "".join(f"{c:>18}" for c in cells))
    n_pass = sum(1 for r in sweep.values() if r["verdict"] == "PASS")
    print(f"Configs passing KPI bar: {n_pass}/{len(sweep)}")
    results["sweep"] = sweep

    # ---- kill-test 4: RVOL isolation ----
    print("\n=== KILL-TEST 4: RVOL isolation (MACD-only vs MACD+RVOL) ===")
    c_off = dict(DEFAULTS); c_off["use_rvol_gate"] = False
    e_off, t_off = run_backtest(data, c_off)
    m_off = perf_metrics(e_off); ts_off = trade_stats(t_off, e_off)
    print(fmt_row("MACD-only (no RVOL)", m_off, ts_off))
    print(fmt_row("MACD + RVOL>=1.5", m, ts))
    results["rvol_isolation"] = dict(macd_only=dict(m=m_off, ts=ts_off),
                                     macd_rvol=dict(m=m, ts=ts))

    # ---- charts ----
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(11, 6))
        ax.plot(eq.index, eq.values, label="MACD+RVOL strategy", lw=1.8)
        ax.plot(spy_eq.index, spy_eq.values, label="Buy&Hold SPY", lw=1.3, alpha=0.8)
        ax.plot(ew_eq.index, ew_eq.values, label="Buy&Hold EW-universe", lw=1.3, alpha=0.8)
        ax.plot(e_off.index, e_off.values, label="MACD-only (no RVOL)", lw=1.1, ls="--", alpha=0.7)
        ax.set_title(f"MACD+RVOL momentum vs benchmarks  ({START}..{END})")
        ax.set_ylabel("Equity ($)"); ax.legend(); ax.grid(alpha=0.3)
        fig.tight_layout()
        p1 = BASE_DIR / "macd_rvol_equity_curves.png"
        fig.savefig(p1, dpi=110); print(f"\n[chart] {p1.name}")

        # sweep heatmap (MAR)
        fig2, ax2 = plt.subplots(figsize=(7, 4))
        rvs = [1.2, 1.5, 2.0, 2.5]; mnames = list(macd_sets)
        grid = np.array([[sweep[f"{mn}|RVOL{rv}"]["mar"] for rv in rvs] for mn in mnames], dtype=float)
        im = ax2.imshow(grid, cmap="RdYlGn", vmin=-0.5, vmax=1.0, aspect="auto")
        ax2.set_xticks(range(len(rvs))); ax2.set_xticklabels([f"RVOL {r}" for r in rvs])
        ax2.set_yticks(range(len(mnames))); ax2.set_yticklabels(mnames)
        for i in range(len(mnames)):
            for j in range(len(rvs)):
                ax2.text(j, i, f"{grid[i,j]:.2f}", ha="center", va="center", fontsize=9)
        ax2.set_title("Robustness sweep — MAR (green=passes 0.5)")
        fig2.colorbar(im); fig2.tight_layout()
        p2 = BASE_DIR / "macd_rvol_sweep_heatmap.png"
        fig2.savefig(p2, dpi=110); print(f"[chart] {p2.name}")
    except Exception as e:
        print(f"[chart] skipped: {e}")

    # dump machine-readable results
    def clean(o):
        if isinstance(o, dict):
            return {k: clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [clean(x) for x in o]
        if isinstance(o, float):
            return None if np.isnan(o) else round(o, 6)
        if isinstance(o, (np.floating, np.integer)):
            return clean(float(o))
        return o
    (BASE_DIR / "macd_rvol_results.json").write_text(json.dumps(clean(results), indent=2, default=str))
    print(f"[out] macd_rvol_results.json")
    return results


if __name__ == "__main__":
    main()
