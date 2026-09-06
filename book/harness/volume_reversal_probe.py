#!/usr/bin/env python3
"""
volume_reversal_probe.py — Step-1 "is there anything here" probe for the
red-to-green reversal strategy (VOLUME_REVERSAL_BACKTEST_FRAMEWORK.md).

WHAT THIS TESTS (and what it deliberately does NOT):
  Tests the PRICE leg only:
    Entry  : 2+ consecutive red 1-min bars, then a green-closing bar
             -> enter at the NEXT bar's open (no look-ahead).
    Exit   : 4% trailing stop, OR force-flat at session close.
  It does NOT test the buy/sell volume >= 1.5x gates. Minute OHLCV bars do
  not contain a buyer-/seller-initiated volume split — getting that honestly
  needs trade-level (tick) classification, which is the EXPENSIVE step. The
  whole point of this probe is to spend an afternoon, not a week: if the price
  pattern alone is a coin flip after slippage, the volume gate won't save it.

  Therefore the numbers here are an UPPER-ish bound on the price pattern, NOT
  a strategy validation. Read the printed caveats.

HONESTY GUARDS baked in (per repo conventions):
  - Next-bar-open entry (no entering at the signal bar's close).
  - Slippage modeled and stress-tested at 1x / 2x / 3x.
  - Strip-top-5-trades re-run (this repo has been burned by fat-tail lotteries).
  - Ranks on MAR / Sortino, not win rate.
  - Zero/near-zero trades is flagged as a red flag, not reported as a result.

USAGE:
  python3 volume_reversal_probe.py
  python3 volume_reversal_probe.py --symbols AAPL,MSFT,NVDA --start 2024-06-01 --end 2026-06-01
  python3 volume_reversal_probe.py --min-red 2 --trail-pct 4 --slippage-bps 2 --feed sip

OUTPUT:
  Console summary + writes VOLUME_REVERSAL_PROBE_RESULTS.md next to this file.
"""

import argparse
import math
import os
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import alpaca_client as ac
from config import DATA_FEED

ET = ZoneInfo("America/New_York")

# Default universe: liquid large-caps / ETFs. The volume-ratio idea needs depth;
# thin names give meaningless per-minute volume. Keep v1 in liquid territory.
DEFAULT_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMD", "TSLA", "AMZN", "META", "GOOGL",
    "SPY", "QQQ", "NFLX", "AVGO", "CRM", "INTC", "MU", "COIN",
    "SMH", "XLF", "BAC", "JPM",
]

RESULTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "VOLUME_REVERSAL_PROBE_RESULTS.md")


# ─────────────────────────────────────────────────────────────────────────────
# Data
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_raw_bars(symbol: str, start: str, end: str, feed: str) -> list[dict]:
    """
    Paginated 1-min bar fetch via the shared Alpaca session.

    NOTE: we do NOT use ac.get_bars() here — its internal 15s timeout dies on
    large SIP ranges and then SWALLOWS the error, returning [] silently (this
    cost us a "0 bars" red herring during development). We page ourselves with
    a 60s timeout and a non-midnight start (a 00:00:00Z start makes SIP crawl
    through sparse overnight bars and time out). Errors here are NOT swallowed.
    """
    from config import ALPACA_DATA
    url = f"{ALPACA_DATA}/stocks/{symbol}/bars"
    params = {
        "timeframe":  "1Min",
        "start":      f"{start}T08:00:00Z",   # pre-market-ish; we filter to RTH below
        "end":        f"{end}T23:59:59Z",
        "feed":       feed,
        "adjustment": "raw",
        "limit":      10000,
    }
    bars: list[dict] = []
    while True:
        r = ac._SESSION.get(url, params=params, timeout=60)
        if r.status_code == 403 and feed != "iex":
            params["feed"] = feed = "iex"      # SIP not subscribed -> fall back
            continue
        r.raise_for_status()
        j = r.json()
        bars.extend(j.get("bars") or [])
        token = j.get("next_page_token")
        if not token:
            break
        params["page_token"] = token
    return bars


def fetch_minute_bars(symbol: str, start: str, end: str, feed: str) -> list[dict]:
    """
    Fetch 1-min bars for [start, end] (YYYY-MM-DD), regular session only
    (09:30-16:00 ET). Returns bars with parsed ET datetime in 'dt' and a
    'session' date key, sorted oldest->newest. The ET conversion handles
    EST/EDT automatically, so the RTH filter is correct year-round.
    """
    raw = _fetch_raw_bars(symbol, start, end, feed)

    out = []
    for b in raw:
        # Alpaca bar: t (RFC3339), o,h,l,c,v
        ts = b.get("t")
        if not ts:
            continue
        dt_utc = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
        dt_et  = dt_utc.astimezone(ET)
        # Regular session only: 09:30 inclusive .. 16:00 exclusive.
        mins = dt_et.hour * 60 + dt_et.minute
        if mins < 9 * 60 + 30 or mins >= 16 * 60:
            continue
        out.append({
            "dt":      dt_et,
            "session": dt_et.date(),
            "o": float(b["o"]), "h": float(b["h"]),
            "l": float(b["l"]), "c": float(b["c"]),
            "v": float(b.get("v", 0)),
        })
    out.sort(key=lambda x: x["dt"])
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Signal + simulation (one symbol-day at a time; flat at close)
# ─────────────────────────────────────────────────────────────────────────────

def simulate_day(bars: list[dict], min_red: int, trail_pct: float,
                 slippage_bps: float) -> list[dict]:
    """
    Walk one session's bars, generate red->green entries, manage a 4% trailing
    stop, force-flat on the last bar. Returns a list of trade dicts (in R-free
    absolute %% return terms, after slippage).

    Look-ahead discipline:
      * The signal is only known at a green bar's CLOSE.
      * Entry fills at the NEXT bar's OPEN.
      * Trailing peak includes the entry bar's high onward.
    """
    trades = []
    n = len(bars)
    if n < min_red + 2:
        return trades

    slip = slippage_bps / 10_000.0
    red_run = 0
    i = 0
    while i < n:
        bar = bars[i]
        is_red   = bar["c"] < bar["o"]
        is_green = bar["c"] > bar["o"]

        # Evaluate the trigger on a green bar BEFORE resetting the red counter.
        if is_green and red_run >= min_red and i + 1 < n:
            # Enter at next bar's open, with slippage paid crossing the spread up.
            entry_bar = bars[i + 1]
            entry_px  = entry_bar["o"] * (1 + slip)
            peak      = entry_bar["h"]
            exit_px   = None
            exit_reason = None
            j = i + 1
            while j < n:
                b = bars[j]
                peak = max(peak, b["h"])
                stop = peak * (1 - trail_pct / 100.0)
                if b["l"] <= stop:
                    # Optimistic intrabar fill AT the stop, then slippage down.
                    exit_px = stop * (1 - slip)
                    exit_reason = "trail"
                    break
                if j == n - 1:
                    # Force-flat at session close (intraday strategy).
                    exit_px = b["c"] * (1 - slip)
                    exit_reason = "eod"
                    break
                j += 1

            if exit_px is not None:
                ret = (exit_px - entry_px) / entry_px
                trades.append({
                    "session":  bar["session"],
                    "entry_dt": entry_bar["dt"],
                    "exit_dt":  bars[j]["dt"],
                    "entry_px": entry_px,
                    "exit_px":  exit_px,
                    "ret":      ret,
                    "reason":   exit_reason,
                    "hold_min": j - (i + 1) + 1,
                })
            # Resume scanning AFTER this trade closed (no overlapping positions).
            red_run = 0
            i = j + 1
            continue

        # Update the consecutive-red counter.
        if is_red:
            red_run += 1
        else:
            red_run = 0
        i += 1

    return trades


# ─────────────────────────────────────────────────────────────────────────────
# Metrics
# ─────────────────────────────────────────────────────────────────────────────

def daily_equity_curve(trades: list[dict]) -> list[tuple]:
    """
    Build an equal-weight daily return series. Each trade contributes its %%
    return; within a day, trades are averaged (one unit of capital, sequential
    setups don't compound intraday in this simple probe). Returns
    [(date, daily_return), ...] sorted by date.
    """
    by_day = defaultdict(list)
    for t in trades:
        by_day[t["session"]].append(t["ret"])
    series = []
    for d in sorted(by_day):
        rets = by_day[d]
        series.append((d, sum(rets) / len(rets)))
    return series


def compute_metrics(trades: list[dict], n_days_span: int) -> dict:
    if not trades:
        return {"n_trades": 0}

    rets = [t["ret"] for t in trades]
    wins = [r for r in rets if r > 0]
    loss = [r for r in rets if r <= 0]

    gross_win  = sum(wins)
    gross_loss = -sum(loss)
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else float("inf")

    # Equity curve (equal-weight daily) for drawdown / Sortino / MAR.
    series = daily_equity_curve(trades)
    eq = 1.0
    curve = [1.0]
    daily_rets = []
    for _, dr in series:
        eq *= (1 + dr)
        curve.append(eq)
        daily_rets.append(dr)

    # Max drawdown on the equity curve.
    peak = curve[0]
    max_dd = 0.0
    for v in curve:
        peak = max(peak, v)
        dd = (peak - v) / peak
        max_dd = max(max_dd, dd)

    total_return = curve[-1] - 1.0

    # CAGR from the calendar span actually covered.
    years = max(n_days_span / 365.25, 1e-9)
    cagr = (curve[-1]) ** (1 / years) - 1 if curve[-1] > 0 else -1.0
    mar = (cagr / max_dd) if max_dd > 1e-9 else float("inf")

    # Sortino on daily returns (downside deviation vs 0 target), annualized ~252d.
    if daily_rets:
        mean_d = sum(daily_rets) / len(daily_rets)
        downside = [min(r, 0.0) ** 2 for r in daily_rets]
        dd_dev = math.sqrt(sum(downside) / len(downside)) if downside else 0.0
        sortino = (mean_d / dd_dev * math.sqrt(252)) if dd_dev > 1e-12 else float("inf")
    else:
        sortino = 0.0

    return {
        "n_trades":     len(trades),
        "win_rate":     len(wins) / len(rets),
        "avg_win":      (sum(wins) / len(wins)) if wins else 0.0,
        "avg_loss":     (sum(loss) / len(loss)) if loss else 0.0,
        "profit_factor": profit_factor,
        "total_return": total_return,
        "cagr":         cagr,
        "max_dd":       max_dd,
        "mar":          mar,
        "sortino":      sortino,
        "trade_days":   len(series),
        "eod_exits":    sum(1 for t in trades if t["reason"] == "eod"),
        "trail_exits":  sum(1 for t in trades if t["reason"] == "trail"),
        "avg_hold_min": sum(t["hold_min"] for t in trades) / len(trades),
    }


def strip_top_n(trades: list[dict], n: int) -> list[dict]:
    """Return trades with the n best (by %% return) removed — fat-tail check."""
    if len(trades) <= n:
        return []
    ranked = sorted(trades, key=lambda t: t["ret"], reverse=True)
    return ranked[n:]


# ─────────────────────────────────────────────────────────────────────────────
# Report
# ─────────────────────────────────────────────────────────────────────────────

def fmt_metrics(m: dict) -> str:
    if m.get("n_trades", 0) == 0:
        return "  (no trades)"
    def pf(x): return "inf" if x == float("inf") else f"{x:.2f}"
    return (
        f"  trades={m['n_trades']}  trade-days={m['trade_days']}\n"
        f"  total_return={m['total_return']*100:+.1f}%  CAGR={m['cagr']*100:+.1f}%\n"
        f"  MAR={pf(m['mar'])}  Sortino={pf(m['sortino'])}  maxDD={m['max_dd']*100:.1f}%\n"
        f"  win_rate={m['win_rate']*100:.1f}%  profit_factor={pf(m['profit_factor'])}\n"
        f"  avg_win={m['avg_win']*100:+.2f}%  avg_loss={m['avg_loss']*100:+.2f}%\n"
        f"  exits: trail={m['trail_exits']} eod={m['eod_exits']}  avg_hold={m['avg_hold_min']:.0f}min"
    )


def build_report(args, all_trades, span_days, metrics_by_slip, stripped) -> str:
    lines = []
    lines.append("# Red-to-Green Reversal — Step-1 PRICE-LEG Probe Results\n")
    lines.append(f"_Generated {datetime.now(ET).isoformat(timespec='seconds')}_\n")
    lines.append("## What was tested\n")
    lines.append(
        "- **PRICE leg only.** Entry: %d+ consecutive red 1-min bars -> green close "
        "-> enter next bar open. Exit: %.1f%% trailing stop OR force-flat at 16:00 ET.\n"
        "- **NOT tested:** the buy-vol >= 1.5x sell-vol entry gate and the "
        "sell-vol >= 1.5x buy-vol exit. Minute bars have no buy/sell split; that "
        "needs tick classification (the expensive Step 2).\n"
        "- Regular session only (09:30-16:00 ET). Flat at close. No overlapping positions.\n"
        % (args.min_red, args.trail_pct)
    )
    lines.append(f"- Universe: {', '.join(args.symbols)}\n")
    lines.append(f"- Window: {args.start} -> {args.end}  (~{span_days} calendar days)\n")
    lines.append(f"- Data feed: {args.feed}\n")

    lines.append("\n## Slippage stress (per side, bps)\n")
    for bps in sorted(metrics_by_slip):
        m = metrics_by_slip[bps]
        lines.append(f"\n### Slippage {bps:.0f} bps/side\n```\n{fmt_metrics(m)}\n```\n")

    lines.append("\n## Fat-tail check (base slippage, top trades stripped)\n")
    lines.append("```\n")
    for n, m in stripped:
        lines.append(f"strip top {n}:\n{fmt_metrics(m)}\n\n")
    lines.append("```\n")

    lines.append("\n## How to read this\n")
    lines.append(
        "- These are **price-pattern** numbers, an optimistic ceiling — the real "
        "strategy adds two volume gates that can only cut trades, plus more cost.\n"
        "- **Decision rule:** if the edge already fails to clear MAR ~0.5 / Sortino "
        "~1.0 here, or it collapses at 2x slippage, or it goes negative when the top "
        "5 trades are stripped, **stop** — don't build the tick-classification step. "
        "The volume gate is unlikely to rescue a price pattern that's already a coin "
        "flip.\n"
        "- If it shows a real, robust signal, THEN the buy/sell tick classification "
        "(Step 2 in the framework) is worth the effort.\n"
        "- Reminder (repo rule): near-zero trades = broken gate, not a result.\n"
    )
    return "".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    today = date.today()
    default_start = (today - timedelta(days=730)).isoformat()
    default_end   = today.isoformat()

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", default=",".join(DEFAULT_UNIVERSE),
                    help="comma-separated tickers")
    ap.add_argument("--start", default=default_start, help="YYYY-MM-DD")
    ap.add_argument("--end",   default=default_end,   help="YYYY-MM-DD")
    ap.add_argument("--min-red", type=int, default=2,
                    help="consecutive red bars required before the green trigger")
    ap.add_argument("--trail-pct", type=float, default=4.0,
                    help="trailing stop percent")
    ap.add_argument("--slippage-bps", type=float, default=2.0,
                    help="base per-side slippage in bps (also stressed at 2x/3x)")
    ap.add_argument("--feed", default=DATA_FEED,
                    help="alpaca data feed (sip|iex). iex minute history is sparse.")
    args = ap.parse_args()
    args.symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    span_days = (date.fromisoformat(args.end) - date.fromisoformat(args.start)).days

    print(f"Probe: {len(args.symbols)} symbols, {args.start} -> {args.end}, "
          f"min_red={args.min_red}, trail={args.trail_pct}%, feed={args.feed}")
    if args.feed.lower() == "iex":
        print("  WARNING: iex feed has sparse minute coverage (single-exchange "
              "prints). Use --feed sip if your account is subscribed.")

    # Base-slippage trades drive the fat-tail check; we recompute metrics at 2x/3x.
    base_trades = []
    bars_cache = {}
    for sym in args.symbols:
        bars = fetch_minute_bars(sym, args.start, args.end, args.feed)
        bars_cache[sym] = bars
        if not bars:
            print(f"  {sym}: 0 bars (feed/coverage?) — skipped")
            continue
        # group by session
        by_day = defaultdict(list)
        for b in bars:
            by_day[b["session"]].append(b)
        sym_trades = []
        for d in sorted(by_day):
            sym_trades += simulate_day(by_day[d], args.min_red, args.trail_pct,
                                       args.slippage_bps)
        for t in sym_trades:
            t["symbol"] = sym
        base_trades += sym_trades
        print(f"  {sym}: {len(bars)} bars, {len(sym_trades)} trades")

    if len(base_trades) < 30:
        print(f"\n*** RED FLAG: only {len(base_trades)} trades across the whole "
              f"universe/window. That's too few to mean anything — check feed "
              f"coverage and that the red-run counter is firing before reporting "
              f"any 'result'. ***")

    # Metrics at 1x / 2x / 3x slippage (re-simulate; slippage changes fills).
    metrics_by_slip = {}
    for mult in (1, 2, 3):
        bps = args.slippage_bps * mult
        trades = []
        for sym, bars in bars_cache.items():
            if not bars:
                continue
            by_day = defaultdict(list)
            for b in bars:
                by_day[b["session"]].append(b)
            for d in sorted(by_day):
                trades += simulate_day(by_day[d], args.min_red, args.trail_pct, bps)
        metrics_by_slip[bps] = compute_metrics(trades, span_days)

    # Fat-tail check on base slippage.
    base_metrics = metrics_by_slip[args.slippage_bps]
    stripped = []
    for n in (0, 1, 3, 5, 10):
        sub = base_trades if n == 0 else strip_top_n(base_trades, n)
        stripped.append((n, compute_metrics(sub, span_days)))

    # ── Console summary ──
    print("\n" + "=" * 64)
    print("PRICE-LEG PROBE — base slippage")
    print("=" * 64)
    print(fmt_metrics(base_metrics))
    print("\nSlippage stress:")
    for bps in sorted(metrics_by_slip):
        m = metrics_by_slip[bps]
        if m.get("n_trades"):
            print(f"  {bps:>4.0f} bps/side -> MAR={m['mar'] if m['mar']!=float('inf') else 'inf'}"
                  f"  Sortino={m['sortino'] if m['sortino']!=float('inf') else 'inf'}"
                  f"  total={m['total_return']*100:+.1f}%  PF={m['profit_factor']:.2f}"
                  if m['mar'] != float('inf') and m['profit_factor'] != float('inf')
                  else f"  {bps:>4.0f} bps/side -> trades={m['n_trades']} (inf metric, check)")
    print("\nFat-tail (strip top N, base slippage):")
    for n, m in stripped:
        if m.get("n_trades"):
            tr = m["total_return"] * 100
            print(f"  strip {n:>2}: total={tr:+.1f}%  PF={m['profit_factor'] if m['profit_factor']!=float('inf') else float('nan'):.2f}  trades={m['n_trades']}")

    report = build_report(args, base_trades, span_days, metrics_by_slip, stripped)
    with open(RESULTS_PATH, "w") as f:
        f.write(report)
    print(f"\nFull report -> {RESULTS_PATH}")
    print("\nREMINDER: price leg only. The volume gates are NOT tested here and "
          "can only reduce/cost more. Treat these as an optimistic ceiling.")


if __name__ == "__main__":
    main()
