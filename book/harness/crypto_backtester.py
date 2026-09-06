"""
Crypto Trend Backtester — Donchian Breakout
============================================
Entry signal: Donchian channel breakout
  BUY  when close > highest close of prior ENTRY_N days  (new N-day high)
  SELL when close < lowest  close of prior EXIT_N  days  (new N-day low)
        OR 4× ATR trailing stop fires first

BTC regime filter: no entries when BTC < SMA(200) on daily bars.
Exit is always allowed regardless of regime.

Three lookback pairs tested in one pass (classic Turtle Trading parameters):
  Fast   — 20-day entry / 10-day exit
  Medium — 30-day entry / 15-day exit
  Slow   — 55-day entry / 20-day exit

Usage:
  python3 crypto_backtester.py
  python3 crypto_backtester.py --start 2021-01-01 --end 2026-04-22
  python3 crypto_backtester.py --pairs BTC/USD ETH/USD
  python3 crypto_backtester.py --entry 20 --exit 10   # single lookback pair
"""

import argparse
import logging
from collections import Counter
from datetime import datetime, date, timedelta, timezone
from typing import Optional

import crypto_client as cc
from config import (
    CRYPTO_ATR_MULT,
    CRYPTO_ATR_TRAIL_MULT,
    CRYPTO_BULL_MAX_POS,
    CRYPTO_BULL_RISK_MULT,
    CRYPTO_BULL_SMA_RATIO,
    CRYPTO_MAX_POSITIONS,
    CRYPTO_PAIRS,
    CRYPTO_PARTIAL_R,
    CRYPTO_PARTIAL_SIZE,
    CRYPTO_REGIME_SMA,
    CRYPTO_RISK_PER_TRADE,
    CRYPTO_SLIPPAGE_PCT,
    CRYPTO_SPOT_BUDGET,
    CRYPTO_VOL_CONFIRM_MULT,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s",
                    datefmt="%H:%M:%S")

WARMUP_DAYS   = CRYPTO_REGIME_SMA + 20   # bars fetched before user start to seed SMA
ATR_PERIOD    = 14
_RISK_DOLLARS = CRYPTO_SPOT_BUDGET * CRYPTO_RISK_PER_TRADE   # e.g. $2,498
_SLOT_CAP     = CRYPTO_SPOT_BUDGET / CRYPTO_MAX_POSITIONS     # e.g. $83,257

# Lookback pairs: (entry_days, exit_days)
SYSTEMS = [
    (20, 10),   # Fast   — Turtle System 1
    (30, 15),   # Medium
    (55, 20),   # Slow   — Turtle System 2
]


# ── Sizing ────────────────────────────────────────────────────────────────────

def _calc_notional(atr_val: float, price: float, risk_mult: float = 1.0) -> float:
    """
    risk_mult = 1.0 in NEUTRAL, CRYPTO_BULL_RISK_MULT (1.5) in BULL.
    Slot cap narrows in BULL because max_positions expands from 3 → 4.
    """
    stop_pct = (CRYPTO_ATR_MULT * atr_val) / price
    if stop_pct <= 0:
        return 0.0
    if risk_mult > 1.0:
        slot_cap = CRYPTO_SPOT_BUDGET / CRYPTO_BULL_MAX_POS
    else:
        slot_cap = _SLOT_CAP
    return min((_RISK_DOLLARS * risk_mult) / stop_pct, slot_cap)


# ── BTC regime ────────────────────────────────────────────────────────────────

def build_btc_regime(btc_bars: list[dict]) -> dict[str, str]:
    """
    Returns {date: regime} where regime is one of 'bull' / 'neutral' / 'bear'.

    BULL    — BTC close > SMA(200) AND close/SMA ≥ CRYPTO_BULL_SMA_RATIO (1.05)
    NEUTRAL — BTC close > SMA(200) but ratio below threshold
    BEAR    — BTC close ≤ SMA(200) → entries blocked

    O(n) running sum — avoids O(n×200) slice-per-bar.
    """
    closes = [b["c"] for b in btc_bars]
    result: dict[str, str] = {}
    n = CRYPTO_REGIME_SMA
    if len(closes) < n:
        return result
    window = sum(closes[:n])
    for i in range(n - 1, len(btc_bars)):
        if i >= n:
            window += closes[i] - closes[i - n]
        sma   = window / n
        cur   = closes[i]
        ratio = cur / sma
        if cur < sma:
            regime = "bear"
        elif ratio >= CRYPTO_BULL_SMA_RATIO:
            regime = "bull"
        else:
            regime = "neutral"
        result[btc_bars[i]["t"][:10]] = regime
    return result


# ── Donchian signal ───────────────────────────────────────────────────────────

def _donchian_signal(
    closes:  list[float],
    i:       int,
    entry_n: int,
    exit_n:  int,
) -> Optional[str]:
    """
    At bar index i, using only data up to and including i:
      'long' — close[i] > max(close[i-entry_n : i])   (new entry_n-day high)
      'exit' — close[i] < min(close[i-exit_n  : i])   (new exit_n-day low)
      None   — neither condition met

    Requires at least entry_n + 1 bars available before i.
    """
    if i < entry_n:
        return None

    cur = closes[i]
    prior_entry_high = max(closes[i - entry_n : i])   # prior N bars, excluding current
    prior_exit_low   = min(closes[i - exit_n  : i])

    if cur > prior_entry_high:
        return "long"
    if cur < prior_exit_low:
        return "exit"
    return None


# ── Per-pair simulation ───────────────────────────────────────────────────────

def _simulate_pair(
    symbol:        str,
    bars:          list[dict],
    btc_regime:    dict[str, str],
    record_from:   str,
    entry_n:       int,
    exit_n:        int,
    atr_period:    int = ATR_PERIOD,
) -> list[dict]:
    """
    Walk forward bar-by-bar. Baseline Donchian:
      - BTC regime filter (bear blocks entries)
      - Optional volume confirmation
      - 4×ATR Chandelier trailing stop  (ATR window scaled to calendar units)
      - Donchian breakdown exit
      - Partial profit-taking if CRYPTO_PARTIAL_R > 0
    """
    closes = [b["c"] for b in bars]
    atrs   = cc.precompute_atr(bars, atr_period)
    trades:   list[dict] = []
    position: Optional[dict] = None

    start_i = max(entry_n, atr_period + 1)

    for i in range(start_i, len(bars)):
        bar   = bars[i]
        close = bar["c"]
        high  = bar["h"]
        low   = bar["l"]
        date  = bar["t"][:10]

        current_atr = atrs[i]
        signal = _donchian_signal(closes, i, entry_n, exit_n)

        if position:
            if high > position["peak"]:
                position["peak"] = high

            if CRYPTO_PARTIAL_R > 0 and not position.get("partial_taken"):
                partial_target = position["entry_price"] + CRYPTO_PARTIAL_R * position["atr"]
                if high >= partial_target:
                    partial_qty = position["qty"] * CRYPTO_PARTIAL_SIZE
                    position["partial_pnl"]  = (partial_target - position["entry_price"]) * partial_qty
                    position["qty"]         -= partial_qty
                    position["partial_taken"] = True
                    position["stop_floor"]    = position["entry_price"]

            trail_stop = max(
                position["peak"] - CRYPTO_ATR_TRAIL_MULT * current_atr,
                position.get("stop_floor", 0.0),
            )

            if low <= trail_stop:
                exit_price = max(trail_stop, low) * (1.0 - CRYPTO_SLIPPAGE_PCT)
                pnl = position.get("partial_pnl", 0.0) + \
                      (exit_price - position["entry_price"]) * position["qty"]
                trades.append(_make_trade(
                    symbol, position, exit_price, pnl,
                    "trail_stop", i - position["entry_bar"], bar["t"],
                ))
                position = None
                continue

            if signal == "exit":
                exit_price = close * (1.0 - CRYPTO_SLIPPAGE_PCT)
                pnl = position.get("partial_pnl", 0.0) + \
                      (exit_price - position["entry_price"]) * position["qty"]
                trades.append(_make_trade(
                    symbol, position, exit_price, pnl,
                    "donchian_exit", i - position["entry_bar"], bar["t"],
                ))
                position = None

        else:
            if date < record_from:
                continue
            if signal != "long":
                continue

            regime = btc_regime.get(date, "neutral")
            if regime == "bear":
                continue

            if CRYPTO_VOL_CONFIRM_MULT > 0:
                avg_vol = sum(b["v"] for b in bars[i - 20 : i]) / 20
                if avg_vol > 0 and bar["v"] < avg_vol * CRYPTO_VOL_CONFIRM_MULT:
                    continue

            risk_mult = CRYPTO_BULL_RISK_MULT if regime == "bull" else 1.0
            entry_price = close * (1.0 + CRYPTO_SLIPPAGE_PCT)
            notional    = _calc_notional(current_atr, entry_price, risk_mult=risk_mult)
            if notional < 100 or current_atr == 0:
                continue

            position = {
                "entry_price":   entry_price,
                "peak":          entry_price,
                "qty":           notional / entry_price,
                "notional":      notional,
                "entry_time":    bar["t"],
                "entry_bar":     i,
                "atr":           current_atr,
                "regime":        regime,
                "partial_taken": False,
                "partial_pnl":   0.0,
                "stop_floor":    0.0,
            }

    # Force-close any open position at last bar (with sell-side slippage)
    if position:
        exit_price = bars[-1]["c"] * (1.0 - CRYPTO_SLIPPAGE_PCT)
        pnl = position.get("partial_pnl", 0.0) + \
              (exit_price - position["entry_price"]) * position["qty"]
        trades.append(_make_trade(
            symbol, position, exit_price, pnl,
            "end_of_data", len(bars) - 1 - position["entry_bar"],
            bars[-1]["t"],
        ))

    return trades


def _make_trade(symbol, position, exit_price, pnl, reason, bars_held, exit_time) -> dict:
    return {
        "symbol":        symbol,
        "entry_time":    position["entry_time"],
        "exit_time":     exit_time,
        "entry_price":   position["entry_price"],
        "exit_price":    exit_price,
        "qty":           position["qty"],
        "notional":      position["notional"],
        "pnl":           pnl,
        "partial_pnl":   position.get("partial_pnl", 0.0),
        "partial_taken": position.get("partial_taken", False),
        "pnl_pct":       pnl / position["notional"] * 100,
        "exit_reason":   reason,
        "bars_held":     bars_held,
        "regime":        position.get("regime", "neutral"),
    }


# ── Reporting ─────────────────────────────────────────────────────────────────

def _fmt(v: float) -> str:
    return f"{'+'if v>=0 else ''}${v:,.0f}"


def _stats(trades: list[dict]) -> dict:
    """
    Returns headline metrics for a trade list.

    For a non-compounding fixed-budget strategy, returns are PnL/budget per
    trade. Daily equity series is reconstructed from exit timestamps and
    used for drawdown, Sortino (downside-deviation-only), MAR (CAGR/MaxDD%),
    and Calmar (same as MAR for backtest windows ≥ 1y; aliased for <1y).
    """
    import math
    if not trades:
        return {"n": 0, "wins": 0, "win_pct": 0, "pnl": 0, "max_dd": 0,
                "max_dd_pct": 0, "avg_bars": 0, "cagr": 0, "sortino": 0,
                "mar": 0, "calmar": 0, "profit_factor": 0,
                "avg_win": 0, "avg_loss": 0}

    n    = len(trades)
    wins = sum(1 for t in trades if t["pnl"] > 0)
    pnl  = sum(t["pnl"] for t in trades)
    avg_bars = sum(t["bars_held"] for t in trades) / n
    win_pnls  = [t["pnl"] for t in trades if t["pnl"] > 0]
    loss_pnls = [t["pnl"] for t in trades if t["pnl"] < 0]
    avg_win   = sum(win_pnls)  / len(win_pnls)  if win_pnls  else 0.0
    avg_loss  = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0.0
    profit_factor = (sum(win_pnls) / abs(sum(loss_pnls))) if loss_pnls else float("inf") if win_pnls else 0.0

    # ── Build daily equity series → MaxDD, returns series ───────────────────
    by_date: dict[str, float] = {}
    for t in trades:
        d = t["entry_time"][:10] if isinstance(t["entry_time"], str) else str(t["entry_time"])[:10]
        # bucket PnL by EXIT day (PnL is realized at exit)
        end_date = (t.get("exit_time") or t["entry_time"])[:10] if isinstance(t.get("exit_time") or t["entry_time"], str) else d
        by_date[end_date] = by_date.get(end_date, 0.0) + t["pnl"]

    sorted_dates = sorted(by_date.keys())
    first_dt = datetime.strptime(sorted_dates[0], "%Y-%m-%d").date()
    last_dt  = datetime.strptime(sorted_dates[-1], "%Y-%m-%d").date()
    total_days = max((last_dt - first_dt).days + 1, 1)
    years = total_days / 365.25

    cum = peak = max_dd = 0.0
    daily_returns: list[float] = []
    cur = first_dt
    for _ in range(total_days):
        day_pnl = by_date.get(cur.isoformat(), 0.0)
        cum  += day_pnl
        peak  = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
        daily_returns.append(day_pnl / CRYPTO_SPOT_BUDGET)
        cur = cur + timedelta(days=1)

    total_return_pct = pnl / CRYPTO_SPOT_BUDGET
    cagr = (1 + total_return_pct) ** (1 / years) - 1 if years > 0 and (1 + total_return_pct) > 0 else 0.0
    max_dd_pct = max_dd / CRYPTO_SPOT_BUDGET

    # Sortino: daily returns, downside deviation vs target=0, ×sqrt(365) for 24/7 crypto
    downside = [r for r in daily_returns if r < 0]
    if downside and len(daily_returns) > 1:
        dd_sq_mean = sum(r * r for r in downside) / len(daily_returns)
        downside_dev = math.sqrt(dd_sq_mean)
        mean_r = sum(daily_returns) / len(daily_returns)
        sortino = (mean_r / downside_dev) * math.sqrt(365) if downside_dev > 0 else 0.0
    else:
        sortino = 0.0

    # MAR / Calmar: CAGR / MaxDD%
    mar = (cagr / max_dd_pct) if max_dd_pct > 0 else 0.0
    calmar = mar   # same definition; standard Calmar uses 3y window when available

    return {"n": n, "wins": wins, "win_pct": wins/n*100,
            "pnl": pnl, "max_dd": max_dd, "max_dd_pct": max_dd_pct * 100,
            "avg_bars": avg_bars, "cagr": cagr * 100,
            "sortino": sortino, "mar": mar, "calmar": calmar,
            "profit_factor": profit_factor,
            "avg_win": avg_win, "avg_loss": avg_loss}


def print_report(
    results:       dict[tuple, list[dict]],
    start:         str,
    end:           str,
    pairs:         list[str],
    regime_counts: dict[str, int],
    timeframe:     str = "1Day",
):
    bull_days    = regime_counts.get("bull",    0)
    neutral_days = regime_counts.get("neutral", 0)
    bear_days    = regime_counts.get("bear",    0)
    total_days   = bull_days + neutral_days + bear_days or 1
    bars_per_day = BARS_PER_DAY.get(timeframe, 1)

    print()
    print("=" * 75)
    print(f"  Crypto Backtest  |  Donchian Breakout  |  {timeframe} bars  |  THREE-REGIME")
    print(f"  Regime: BULL≥{CRYPTO_BULL_SMA_RATIO:.2f}×SMA{CRYPTO_REGIME_SMA} ({CRYPTO_BULL_RISK_MULT:.1f}× risk, {CRYPTO_BULL_MAX_POS} slots)  "
          f"NEUTRAL (1.0× risk, {CRYPTO_MAX_POSITIONS} slots)  BEAR=blocked")
    print(f"  Exit: {CRYPTO_ATR_TRAIL_MULT:.0f}× ATR trail stop OR Donchian breakdown")
    print(f"  Period: {start} → {end}")
    print(f"  Days:   BULL={bull_days} ({bull_days/total_days:.0%})  "
          f"NEUTRAL={neutral_days} ({neutral_days/total_days:.0%})  "
          f"BEAR={bear_days} ({bear_days/total_days:.0%})")
    print(f"  Budget: ${CRYPTO_SPOT_BUDGET:,.0f}  |  Base risk/trade: {CRYPTO_RISK_PER_TRADE:.0%}  "
          f"|  Bull risk/trade: {CRYPTO_RISK_PER_TRADE * CRYPTO_BULL_RISK_MULT:.1%}")
    print(f"  Slippage: {CRYPTO_SLIPPAGE_PCT*100:.2f}% per side  "
          f"({CRYPTO_SLIPPAGE_PCT*200:.2f}% round-trip cost before spread)")
    print("=" * 75)

    # ── System comparison (P&L table) ────────────────────────────────────────
    print()
    print("  SYSTEM COMPARISON — P&L")
    print()
    hdr = f"  {'System':<20}  {'Trades':>6}  {'Win%':>6}  {'P&L':>12}  {'Return':>8}  {'Max DD':>12}  {'Avg hold':>9}"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))

    # Best system is now ranked by MAR (CAGR / MaxDD%), not raw P&L —
    # see CLAUDE.md: KPI for trend-following is risk-adjusted, not absolute.
    stats_by_key = {k: _stats(v) for k, v in results.items()}
    best_key = max(stats_by_key, key=lambda k: stats_by_key[k]["mar"])

    for (en, ex), trades in sorted(results.items()):
        s    = stats_by_key[(en, ex)]
        name = f"{en}d entry / {ex}d exit"
        flag = "  ◄" if (en, ex) == best_key else ""
        print(
            f"  {name:<20}  {s['n']:>6}  {s['win_pct']:>5.0f}%  "
            f"{_fmt(s['pnl']):>12}  {s['pnl']/CRYPTO_SPOT_BUDGET*100:>+7.1f}%  "
            f"-${s['max_dd']:>10,.0f}  {s['avg_bars']/bars_per_day:>7.1f}d{flag}"
        )

    # ── Risk-adjusted metrics ────────────────────────────────────────────────
    print()
    print("  SYSTEM COMPARISON — RISK-ADJUSTED  (◄ = best MAR)")
    print()
    hdr_r = f"  {'System':<20}  {'CAGR':>7}  {'MaxDD%':>7}  {'MAR':>6}  {'Sortino':>8}  {'PF':>6}  {'Avg W':>10}  {'Avg L':>10}"
    print(hdr_r)
    print("  " + "-" * (len(hdr_r) - 2))
    for (en, ex), _ in sorted(results.items()):
        s    = stats_by_key[(en, ex)]
        name = f"{en}d entry / {ex}d exit"
        flag = "  ◄" if (en, ex) == best_key else ""
        pf_str = f"{s['profit_factor']:.2f}" if s["profit_factor"] != float("inf") else "  ∞"
        print(
            f"  {name:<20}  {s['cagr']:>+6.1f}%  {s['max_dd_pct']:>6.1f}%  "
            f"{s['mar']:>6.2f}  {s['sortino']:>+8.2f}  {pf_str:>6}  "
            f"{_fmt(s['avg_win']):>10}  {_fmt(s['avg_loss']):>10}{flag}"
        )
    print()
    print("    MAR = CAGR / |Max DD%|  (target ≥ 0.5; trend systems often 0.3-1.5)")
    print("    Sortino = annualized return / downside deviation  (target ≥ 1.0)")
    print("    PF = profit factor = gross wins / |gross losses|  (target ≥ 1.5)")

    # ── Per-pair detail for best system ──────────────────────────────────────
    best_trades = results[best_key]
    ben, bex    = best_key

    print()
    print(f"  PER-PAIR DETAIL  (best: {ben}d entry / {bex}d exit)")
    print()
    hdr2 = f"  {'Pair':<12}  {'Trades':>6}  {'Wins':>5}  {'Win%':>6}  {'P&L':>12}  {'Best':>10}  {'Worst':>10}"
    print(hdr2)
    print("  " + "-" * (len(hdr2) - 2))

    total_n = total_wins = 0
    total_pnl = 0.0
    for symbol in pairs:
        trades = [t for t in best_trades if t["symbol"] == symbol]
        if not trades:
            print(f"  {symbol:<12}  {'—':>6}")
            continue
        n     = len(trades)
        wins  = sum(1 for t in trades if t["pnl"] > 0)
        pnl   = sum(t["pnl"] for t in trades)
        best  = max(t["pnl"] for t in trades)
        worst = min(t["pnl"] for t in trades)
        print(
            f"  {symbol:<12}  {n:>6}  {wins:>5}  {wins/n*100:>5.0f}%  "
            f"{_fmt(pnl):>12}  {_fmt(best):>10}  {_fmt(worst):>10}"
        )
        total_n += n; total_wins += wins; total_pnl += pnl
    print("  " + "-" * (len(hdr2) - 2))
    print(
        f"  {'TOTAL':<12}  {total_n:>6}  {total_wins:>5}  "
        f"{total_wins/total_n*100 if total_n else 0:>5.0f}%  {_fmt(total_pnl):>12}"
    )

    # ── Top 5 winners / losers ────────────────────────────────────────────────
    sorted_trades = sorted(best_trades, key=lambda x: x["pnl"], reverse=True)
    print()
    print(f"  TOP 5 WINNERS  ({ben}d / {bex}d):")
    for t in sorted_trades[:5]:
        print(
            f"    {t['symbol']:<10}  entry={t['entry_price']:>10.4f}  "
            f"exit={t['exit_price']:>10.4f}  "
            f"P&L={_fmt(t['pnl']):>10}  ({t['pnl_pct']:+.1f}%)  "
            f"{t['bars_held']/bars_per_day:>3.0f}d  [{t['exit_reason']}]  {t['entry_time'][:10]}"
        )
    print()
    print(f"  TOP 5 LOSERS  ({ben}d / {bex}d):")
    for t in sorted_trades[-5:]:
        print(
            f"    {t['symbol']:<10}  entry={t['entry_price']:>10.4f}  "
            f"exit={t['exit_price']:>10.4f}  "
            f"P&L={_fmt(t['pnl']):>10}  ({t['pnl_pct']:+.1f}%)  "
            f"{t['bars_held']/bars_per_day:>3.0f}d  [{t['exit_reason']}]  {t['entry_time'][:10]}"
        )

    # ── Exit reasons + partial profit stats ───────────────────────────────────
    print()
    print(f"  EXIT REASONS  ({ben}d / {bex}d):")
    for reason, count in sorted(Counter(t["exit_reason"] for t in best_trades).items()):
        print(f"    {reason:<20} {count}")
    partials = [t for t in best_trades if t.get("partial_taken")]
    if partials:
        partial_total = sum(t["partial_pnl"] for t in partials)
        print(f"\n  PARTIAL EXITS: {len(partials)} trades triggered 2×ATR target  "
              f"(locked in {_fmt(partial_total)} before final exit)")

    # ── Per-regime P&L breakdown ──────────────────────────────────────────────
    print()
    print(f"  REGIME BREAKDOWN  ({ben}d / {bex}d):")
    hdr3 = f"  {'Regime':<10}  {'Trades':>6}  {'Win%':>6}  {'P&L':>12}  {'Avg notional':>14}"
    print(hdr3)
    print("  " + "-" * (len(hdr3) - 2))
    for reg in ("bull", "neutral", "bear"):
        rt = [t for t in best_trades if t.get("regime") == reg]
        if not rt:
            continue
        rn   = len(rt)
        rwins = sum(1 for t in rt if t["pnl"] > 0)
        rpnl = sum(t["pnl"] for t in rt)
        ravg = sum(t["notional"] for t in rt) / rn
        print(f"  {reg.upper():<10}  {rn:>6}  {rwins/rn*100:>5.0f}%  "
              f"{_fmt(rpnl):>12}  ${ravg:>12,.0f}")

    print()
    print("=" * 75)


# ── Helpers ───────────────────────────────────────────────────────────────────

def date_iso_to_date(iso: str) -> date:
    """Convert a YYYY-MM-DD string to a date object."""
    return datetime.strptime(iso, "%Y-%m-%d").date()


# ── Main ──────────────────────────────────────────────────────────────────────

BARS_PER_DAY = {"1Day": 1, "4Hour": 6, "1Hour": 24}


def main():
    import time as _time
    parser = argparse.ArgumentParser(description="Crypto Donchian Breakout Backtester")
    parser.add_argument("--start",  default="2021-01-01")
    parser.add_argument("--end",    default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    parser.add_argument("--pairs",  nargs="+", default=CRYPTO_PAIRS)
    parser.add_argument("--entry",  type=int, default=None, help="Single entry lookback (DAYS)")
    parser.add_argument("--exit",   type=int, default=None, help="Single exit lookback (DAYS)")
    parser.add_argument("--timeframe", default="1Day", choices=["1Day", "4Hour", "1Hour"],
                        help="Bar timeframe for pair signals. BTC regime stays Daily.")
    parser.add_argument("--combo", action="store_true",
                        help="Turtle dual-system: run both 20/10 (S1) and 55/20 (S2) "
                             "with overlap dedup (S2 takes precedence on same pair). "
                             "Compare combo vs each system alone.")
    args = parser.parse_args()

    # Donchian periods are always specified in DAYS; we scale to bars internally.
    # ATR window is held constant in CALENDAR days (14d) so the trail-stop
    # geometry is invariant across timeframes — without this scaling, 4H bars
    # produce 6× tighter stops in dollar terms.
    bars_per_day  = BARS_PER_DAY[args.timeframe]
    atr_period    = ATR_PERIOD * bars_per_day
    systems_days  = [(args.entry, args.exit)] if args.entry and args.exit else SYSTEMS
    systems       = [(en * bars_per_day, ex * bars_per_day) for en, ex in systems_days]

    start_dt  = datetime.strptime(args.start, "%Y-%m-%d")
    warmup_dt = start_dt - timedelta(days=WARMUP_DAYS)
    start_iso = f"{warmup_dt.strftime('%Y-%m-%d')}T00:00:00Z"
    end_iso   = f"{args.end}T23:59:59Z"

    print(
        f"\nFetching {args.timeframe} bars for {len(args.pairs)} pairs"
        f"  ({args.start} → {args.end},  +{WARMUP_DAYS}d warmup) …"
    )

    # BTC regime always uses Daily bars — slow context independent of pair timeframe
    print("  BTC/USD daily regime … ", end="", flush=True)
    btc_daily_bars = cc.get_crypto_bars("BTC/USD", timeframe="1Day", start=start_iso, end=end_iso)
    btc_regime     = build_btc_regime(btc_daily_bars)
    regime_counts  = Counter(btc_regime.values())
    print(
        f"{len(btc_daily_bars)} daily bars  "
        f"(BULL={regime_counts['bull']}  "
        f"NEUTRAL={regime_counts['neutral']}  "
        f"BEAR={regime_counts['bear']})"
    )

    pair_bars: dict[str, list[dict]] = {}
    for symbol in args.pairs:
        print(f"  {symbol} ({args.timeframe}) … ", end="", flush=True)
        bars = cc.get_crypto_bars(symbol, timeframe=args.timeframe, start=start_iso, end=end_iso)
        max_n = max(en for en, _ in systems)
        if len(bars) >= max_n + ATR_PERIOD + 2:
            pair_bars[symbol] = bars
            print(f"{len(bars)} bars")
        else:
            print(f"{len(bars)} bars  ← insufficient, skipping")
        # gentle pacing — Alpaca rate-limits at finer timeframes
        if args.timeframe != "1Day":
            _time.sleep(0.5)

    # ── Run simulation ────────────────────────────────────────────────────────
    print(f"\nSimulating {len(systems)} system(s) × {len(pair_bars)} pairs "
          f"on {args.timeframe} bars …")
    results: dict[tuple, list[dict]] = {}
    for (entry_n, exit_n), (en_d, ex_d) in zip(systems, systems_days):
        all_trades: list[dict] = []
        for symbol, bars in pair_bars.items():
            trades = _simulate_pair(
                symbol, bars, btc_regime, args.start, entry_n, exit_n,
                atr_period=atr_period,
            )
            all_trades.extend(trades)
        # Key results by the human-friendly DAYS pair (so report headers stay readable)
        results[(en_d, ex_d)] = all_trades
        s = _stats(all_trades)
        print(f"  {en_d}d/{ex_d}d ({entry_n}/{exit_n} bars)  →  {s['n']} trades  "
              f"{_fmt(s['pnl'])}  ({s['win_pct']:.0f}% win rate)  MAR={s['mar']:.2f}")

    # ── Turtle dual-system combo (S1 + S2 with S2 precedence on overlap) ─────
    if args.combo:
        s1_days = (20, 10)
        s2_days = (55, 20)
        s1_bars = (20 * bars_per_day, 10 * bars_per_day)
        s2_bars = (55 * bars_per_day, 20 * bars_per_day)

        def _run(en, ex, system_tag):
            out: list[dict] = []
            for symbol, bars in pair_bars.items():
                tr = _simulate_pair(
                    symbol, bars, btc_regime, args.start, en, ex,
                    atr_period=atr_period,
                )
                for t in tr:
                    t["system"] = system_tag
                out.extend(tr)
            return out

        print(f"\nCOMBO: running both S1 ({s1_days[0]}d/{s1_days[1]}d) and "
              f"S2 ({s2_days[0]}d/{s2_days[1]}d) …")
        s1_trades = _run(*s1_bars, "S1")
        s2_trades = _run(*s2_bars, "S2")

        # Dedupe: drop any S1 trade whose hold-window overlaps an S2 trade on
        # the same pair. S2 takes precedence (higher conviction, longer
        # channel). This matches real-bot semantics (one position per pair).
        s2_by_sym: dict[str, list[dict]] = {}
        for t in s2_trades:
            s2_by_sym.setdefault(t["symbol"], []).append(t)

        combo: list[dict] = list(s2_trades)
        dropped = 0
        for t in s1_trades:
            entry_t = t["entry_time"]
            exit_t  = t.get("exit_time", entry_t)
            overlaps = any(
                s["entry_time"] <= exit_t and entry_t <= s.get("exit_time", s["entry_time"])
                for s in s2_by_sym.get(t["symbol"], [])
            )
            if overlaps:
                dropped += 1
            else:
                combo.append(t)

        # Drop any S1 trades that overlap *each other* on the same pair (the
        # per-pair simulator already enforces this within a single system,
        # so no work needed here — _simulate_pair only opens one trade at a
        # time per call).

        s_s1    = _stats(s1_trades)
        s_s2    = _stats(s2_trades)
        s_combo = _stats(combo)

        print()
        print("=" * 90)
        print(f"  TURTLE COMBO COMPARISON  ({args.start} → {args.end})")
        print("=" * 90)
        print(f"  S1 alone (20d/10d):  {s_s1['n']:>3} trades  "
              f"{_fmt(s_s1['pnl']):>10}  MAR={s_s1['mar']:>5.2f}  "
              f"Sortino={s_s1['sortino']:>+5.2f}  MaxDD%={s_s1['max_dd_pct']:>4.1f}")
        print(f"  S2 alone (55d/20d):  {s_s2['n']:>3} trades  "
              f"{_fmt(s_s2['pnl']):>10}  MAR={s_s2['mar']:>5.2f}  "
              f"Sortino={s_s2['sortino']:>+5.2f}  MaxDD%={s_s2['max_dd_pct']:>4.1f}")
        print(f"  COMBO  (S2-priority): {s_combo['n']:>3} trades  "
              f"{_fmt(s_combo['pnl']):>10}  MAR={s_combo['mar']:>5.2f}  "
              f"Sortino={s_combo['sortino']:>+5.2f}  MaxDD%={s_combo['max_dd_pct']:>4.1f}")
        print(f"  ({dropped} S1 trades dropped due to S2 overlap on same pair)")
        best_solo_mar = max(s_s1['mar'], s_s2['mar'])
        verdict = "BEATS" if s_combo['mar'] > best_solo_mar else "DOES NOT BEAT"
        print(f"\n  Verdict: combo {verdict} the better single system "
              f"(MAR {s_combo['mar']:.2f} vs {best_solo_mar:.2f})")
        print("=" * 90)
        return

    print_report(results, args.start, args.end, args.pairs, regime_counts, args.timeframe)


if __name__ == "__main__":
    main()
