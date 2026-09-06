#!/usr/bin/env python3
"""
Backtester — Historical Gap Strategy Replay
============================================
Simulates what gap_watcher + gap_trader would have done on any past week
using actual OHLCV data from Alpaca.

Methodology
-----------
For each trading day in the range:
  1. Fetch daily bars for the full Alpaca universe (batched, IEX feed)
  2. Screen: gap ≥ 10% (open vs prev close), price $2–$20, RVOL ≥ 5×
  3. Enrich via yfinance: float < 10M, no resistance within 3% overhead
  4. Multi-day runner detection (same logic as gap_scanner.py)
  5. For each qualified candidate, fetch 1-min bars for that day
  6. Scan bars in the entry window (9:30–10:30 AM ET) for bull flag / breakout
  7. Simulate bracket order: enter at bar AFTER pattern, walk forward to
     find stop hit (loss), target hit (win), or EOD exit (close price)
  8. Aggregate P&L, win rate, R-multiple across all trades

Entry simulation assumptions
-----------------------------
  - Pattern detected at bar N close → bracket fills at bar N+1 open
    (market order placed at bar completion, filled on next print)
  - Within a bar: stop is checked before target (conservative)
  - EOD cutoff: first bar at or after 3:55 PM ET → exit at that bar's close
  - Sizing: same calculate_entry() as live system (25% tranche, 3:1 R:R)

Caching
-------
  Raw data (Alpaca daily bars, yfinance enrichment, 1-min bars) is cached to
  disk so repeated simulation runs (e.g. after tweaking a filter) are instant.

  Cache layout:
    state/cache/daily_{start}_{end}.pkl.gz   — all Alpaca daily bars (RVOL + resistance source)
    state/cache/yf/{SYMBOL}.pkl.gz           — float shares only from yfinance (7-day TTL)
    state/cache/1min/{SYMBOL}_{DATE}.pkl.gz  — 1-min bars per symbol per day

  RVOL and resistance are computed from cached Alpaca bars so yfinance rate
  limits cannot block the enrichment step. yfinance is only called for float
  shares (a single .info lookup per symbol, not a full history fetch).

  Use --refresh to force a full data re-fetch (clears all cache for the range).
  Use --refresh-yf to re-fetch only float share data from yfinance.

Usage
-----
  python3 backtester.py                                      # last 5 trading days
  python3 backtester.py --start 2025-10-21 --end 2026-04-18
  python3 backtester.py --start 2025-10-21 --end 2026-04-18 --top 25
  python3 backtester.py --start 2025-10-21 --end 2026-04-18 --refresh
  python3 backtester.py --start 2025-10-21 --end 2026-04-18 --refresh-yf
"""

import argparse
import csv
import gzip
import os
import pickle
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

import alpaca_client as alpaca
from safe_pickle import safe_load
from config import (
    EASTERN, FLOAT_MAX, GAP_MIN_PCT, GAP_NOTIONAL, MIN_DOLLAR_VOLUME,
    PRICE_MAX, PRICE_MIN, RATE_LIMIT_SLEEP, RESISTANCE_WINDOW, RESISTANCE_ZONE,
    RVOL_MIN, SPY_DOWN_THRESHOLD,
    PM_LIMIT_SLIP,
    # Slippage realism (Path 2)
    EQUITY_SLIPPAGE_PCT, EQUITY_SLIPPAGE_LIMIT, EQUITY_SLIPPAGE_STOP,
    # Conviction-based sizing constants (open session)
    OPEN_CONVICTION_GAP_STRONG, OPEN_CONVICTION_GAP_EXCEPTIONAL,
    OPEN_CONVICTION_RVOL_STRONG, OPEN_CONVICTION_RVOL_EXCEPTIONAL,
    OPEN_CONVICTION_STANDARD_MULT, OPEN_CONVICTION_STRONG_MULT, OPEN_CONVICTION_EXCEPTIONAL_MULT,
    # Conviction-based sizing constants (pre-market session)
    PM_CONVICTION_STANDARD_MULT, PM_CONVICTION_STRONG_MULT, PM_CONVICTION_EXCEPTIONAL_MULT,
)
from gap_trader import (
    DAILY_MAX_LOSS, TRANCHE_1_PCT, TRANCHE_2_PCT, TRANCHE_3_PCT,
    MAX_RISK_PCT, RR_RATIO,
    SCALE2_TRIGGER_PCT, SCALE3_TRIGGER_PCT, TRAIL_PCT,
    MONDAY_WAIT_MINS, calculate_entry,
)
from config import BREAKEVEN_TRIGGER_R
import gap_filters as _gf
from gap_filters import (
    POLE_BARS, FLAG_BARS_MIN, POLE_MIN_PCT, FLAG_MAX_RATIO, FLAG_VOL_SLACK,
    EMA9_TOL_PCT_DEFAULT,
    check_multi_day_runner,
    detect_bull_flag_core, detect_breakout_core,
    detect_candle_exit_signal, check_entry_gates,
    has_retraced_past_halfway,
    ross_gate_size_multiplier,
    score_catalyst_quality,
)

# Entry-quality gate config — overridden by --entry-gates / --ema-tol-pct CLI
ENTRY_GATES_MODE  = "none"    # "none" | "hard" | "majority" | "score"
EMA9_TOL_PCT      = EMA9_TOL_PCT_DEFAULT

# T2 trail tightens from TRAIL_PCT (3%) to this on first candle-reversal signal.
TRAIL_PCT_TIGHTENED = 1.0
# T1 post-breakeven trail tightens from 1.0R to this multiple of risk_per_share
# on first candle-reversal signal. Same signal that tightens T2.
T1_TRAIL_R_TIGHTENED = 0.5


# ── Constants — regular session ───────────────────────────────────────────────
# NOTE: UTC equivalents of ET times shift by one hour at DST boundaries
# (second Sunday in March: EDT starts, UTC offset −4;
#  first Sunday in November: EST starts, UTC offset −5).
# Use _et_utc(day, h, m) for per-date UTC strings instead of module constants.
LOOKBACK_DAYS = 40   # calendar days before test start for RVOL/runner calc


def _et_utc(day: date, h: int, m: int) -> str:
    """Return 'THH:MM:SSZ' for Eastern Time h:m on the given date, respecting DST."""
    et_dt = datetime(day.year, day.month, day.day, h, m, tzinfo=EASTERN)
    return et_dt.astimezone(timezone.utc).strftime("T%H:%M:%SZ")


def _utc_hhmm_to_et_str(day: date, hhmm: str) -> str:
    """
    Convert a UTC 'HH:MM' string to 'HH:MM ET', respecting DST on the given date.
    hhmm is extracted from bar["t"][11:16], e.g. '13:30'.
    """
    hh, mm = int(hhmm[:2]), int(hhmm[3:])
    utc_dt = datetime(day.year, day.month, day.day, hh, mm, tzinfo=timezone.utc)
    return utc_dt.astimezone(EASTERN).strftime("%H:%M ET")


def _market_open_mins_utc(day: date) -> int:
    """UTC minute-of-day when the US market opens on this date (accounts for DST)."""
    et_dt = datetime(day.year, day.month, day.day, 9, 30, tzinfo=EASTERN)
    u = et_dt.astimezone(timezone.utc)
    return u.hour * 60 + u.minute

# News catalyst scoring is now gap_filters.score_catalyst_quality (imported
# above) — single source of truth for live scanner + news_watcher + backtest.
# Score tiers: 0=none, 1=red flag, 3=unclassified, 6=moderate, 9=strong.


def _fetch_day_news(
    symbols:   list[str],
    day:       date,
    cache_dir: Path,
    refresh:   bool,
) -> dict[str, list[str]]:
    """
    Fetch / return cached news headlines for `symbols` on `day`.
    Window: (day - 1) 06:30 ET → day 16:30 ET, i.e. ~34h covering the
    24h that live's 6:45 AM scanner sees PLUS the regular session.
    Mirrors gap_scanner._lookback_cutoff() (CATALYST_LOOKBACK_HOURS=24)
    so prior-evening wire releases (8:00 PM ET, etc.) reach the scorer
    in the backtest the same way they do live. Cache key bumped to v2
    to invalidate the prior narrow-window caches.
    """
    day_str    = day.isoformat()
    cache_path = _cache_path(cache_dir, "news_v2", day_str)

    if not refresh and cache_path.exists():
        cached = _load_cache(cache_path)
        if cached is not None:
            return cached

    # Window mirrors live scan: (day - 1) 06:30 ET → day 16:30 ET. The 24h
    # of prior-evening news that gap_scanner._lookback_cutoff() returns at
    # the 6:45 AM scan time fits inside this window, and the regular-session
    # tail is preserved so intraday-news trades are still scored.
    prior_day = day - timedelta(days=1)
    et_start = datetime(prior_day.year, prior_day.month, prior_day.day, 6, 30, tzinfo=EASTERN)
    et_end   = datetime(day.year, day.month, day.day, 16, 30, tzinfo=EASTERN)
    iso_start = et_start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    iso_end   = et_end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    result = alpaca.get_news_batch(symbols, iso_start, iso_end, limit=200)
    _save_cache(cache_path, result)
    return result


# ── Entry quality filters ─────────────────────────────────────────────────────
# Optimized from 6-month backtest (Oct 2025 – Apr 2026):
#   • First 20 min after open (9:30–9:50 AM) has 24% WR → below break-even
#   • 20 min+ entries: 69% WR, avg +1.77R
#   • Multi-day runner stocks: 0/12 wins, -$4,496 → always skip
#   • Resistance overhead: 19% WR vs 28% without → skip
#   • Gap 10–15%: 10% WR → skip; 15%+ is baseline quality
MIN_ENTRY_OFFSET_MINS = 0        # default OFF — Ross's primary setup (FCMNH /
                                 # micro pullback) often fires inside the first
                                 # 5 minutes. The prior 20-min guard structurally
                                 # excluded the bot's strategy from existing.
                                 # Override via --min-offset for legacy mode.
SKIP_RUNNERS          = True     # skip stocks flagged as multi-day runners
SKIP_RESISTANCE       = True     # skip stocks with resistance overhead
GAP_ENTRY_MIN_PCT     = 15.0    # minimum gap at open for entry (filters out 10–14.9%)
RVOL_ENTRY_MIN        = 20.0    # minimum RVOL for entry (5–20x bucket: 17% WR, negative PnL)

YF_CACHE_TTL_DAYS = 7            # refresh yfinance data after this many days

# Scale-in / live-parity simulation toggle.
# True  → mirror live T1+T2+T3 (breakeven trail on T1, 3% trail on T2,
#         fixed breakeven stop on T3). Default for new backtests.
# False → legacy T1-only mode (single bracket, no trail, no scale-ins). Use
#         --no-scaleins to reproduce pre-2026-05-14 baselines.
# T3 is always exited at EOD here; backtest never models overnight T3 holds
# (see memory: project_backtest_no_overnight_t3.md). This is intentional and
# permanent — the overnight asymmetry stays a live-only signal.
SCALEINS_ENABLED = True

# Ross-style scale-OUT ladder (item 5b). Mutually exclusive with SCALEINS_ENABLED.
# When True, enters full T1 conviction size, then sells 25% at each of
# +1R/+2R/+3R, runs the last 25% with a $1R dollar trail above a +2R floor.
# Stop ratchets: flag_low → entry → +1R → +2R (floor) after each tier fires.
# Use --scaleouts on the CLI to enable.
SCALEOUTS_ENABLED = False

# The harvest ladder: list of (R_multiple_target, fraction_of_initial_shares).
# Default 25/25/25/25 across +1R/+2R/+3R + runner — Ross's archetypal pattern.
# Tuned at the module level so a single CLI run uses one fixed ladder; future
# work could parameterize per-trade based on chart context (round numbers,
# prior daily high, gap-fill zones).
SCALEOUT_LADDER = [(1.0, 0.25), (2.0, 0.25), (3.0, 0.25)]

# ── Short-side parameters (gap-down breakdown shorts — Option 2 spec) ────────
# Asymmetric risk to longs: shorts have unlimited upside risk, sharper reversals.
# Thresholds are LOOSER than longs because gap-downs are rarer and quieter than
# gap-ups (ratio ~1:6 in our data). Strict filters produce too few setups for
# the strategy to be operationally meaningful.
SHORT_GAP_ENTRY_MIN_PCT  = 10.0    # gap-down ≥ 10% (vs 15% for longs)
SHORT_RVOL_ENTRY_MIN     = 5.0     # RVOL ≥ 5× (vs 20× for longs)
SHORT_TRANCHE_1_PCT      = 0.15    # 15% tranche vs 25% for longs
SHORT_MAX_RISK_PCT       = 0.02    # 2% max risk per trade vs 3% for longs
SHORT_RR_RATIO           = 2.0     # 2:1 reward-to-risk vs 3:1 for longs
SHORT_TIME_STOP_HHMM     = (12, 30)  # force-close at 12:30 PM ET
SHORT_FLOAT_MIN          = 5_000_000   # avoid tiny-float squeeze candidates
SHORT_FLOAT_MAX          = 50_000_000  # looser than longs (large-cap shorts work too)
# Squeeze-protection: force-cover if price moves ≥ N×R against us in first M bars
SHORT_SQUEEZE_R_MULT     = 1.5
SHORT_SQUEEZE_BARS       = 5

# ── Constants — pre-market session ────────────────────────────────────────────
# Strategy: scan from 6:45 AM ET. Press releases drop at 7:30 / 8:00 / 8:30 AM.
# When a release hits, RVOL spikes on a single 1-min bar. That spike is the
# entry trigger. We stop taking new pre-market entries at 9:20 AM (10 min
# before open) to avoid the chaotic last-minute pre-market flush.
PM_SPIKE_RVOL_EQUIV = 5.0           # spike bar must pace ≥ 5× daily avg per-min rate
PM_GAP_AT_ENTRY_MIN = 25.0          # stock must be ≥ 25% above prior close at entry (matches live PM_GAP_MIN_PCT)

# Disabled 2026-05-22 after the formal MAR/Sortino audit on 2026-05-22.
# Standalone PM-spike contribution over 24mo (2024-05-12 → 2026-05-12) at
# baseline-strategy settings: 64/72 trades, 8.3% WR, dominant driver of the
# -$12,757 / MAR -0.39 result. The "first spike bar wins" mechanic
# structurally chases the top of the PM pump. PM scanning (watchlist
# build) is untouched; only the automated entry is gated. Re-enable when a
# validated PM pattern exists (5-min PM FCMNH? halt-resume? — TBD).
PM_SPIKE_ENTRIES_ENABLED = False

MINS_IN_SESSION     = 390           # regular session minutes (9:30–4:00 PM)


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _cache_path(cache_dir: Path, *parts: str) -> Path:
    p = cache_dir.joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return Path(str(p) + ".pkl.gz")


def _load_cache(path: Path) -> Optional[object]:
    if not path.exists():
        return None
    try:
        with gzip.open(path, "rb") as f:
            return safe_load(f)
    except Exception:
        return None


def _save_cache(path: Path, data: object) -> None:
    try:
        with gzip.open(path, "wb", compresslevel=3) as f:
            pickle.dump(data, f, protocol=4)
    except Exception as e:
        print(f"  [cache] warning: could not save {path.name}: {e}")


def _cache_stale(path: Path, ttl_days: int) -> bool:
    """True if cache file is older than ttl_days or doesn't exist."""
    if not path.exists():
        return True
    age = datetime.now().timestamp() - path.stat().st_mtime
    return age > ttl_days * 86_400


# ── Date helpers ──────────────────────────────────────────────────────────────

def last_n_trading_days(n: int = 5) -> tuple[date, date]:
    today = date.today()
    days  = []
    d     = today - timedelta(days=1)
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return days[-1], days[0]


def trading_days_in_range(start: date, end: date) -> list[date]:
    days, d = [], start
    while d <= end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


# ── Pattern detection on pre-fetched bars ────────────────────────────────────

# Bull flag and breakout detection delegate to gap_filters core functions.
# Live (gap_trader.detect_bull_flag) and backtest both call the same core.

def _detect_bull_flag_hist(bars: list[dict]) -> Optional[dict]:
    return detect_bull_flag_core(bars)


def _detect_breakout_hist(bars: list[dict], prev_close: float) -> Optional[dict]:
    return detect_breakout_core(bars, prev_close)


# ── Inverse pattern detection — shorts (Option 2 spec) ───────────────────────

def _detect_bear_flag_hist(bars: list[dict]) -> Optional[dict]:
    """
    Inverse of _detect_bull_flag_hist for short setups.
      Pole = sharp DOWN move (≥3% drop)
      Flag = consolidation drifting UP (range ≤ 60% of pole, drift up not down)
      Trigger = current bar low BREAKS BELOW flag low (resumption of decline)
      Volume contracting in flag (panic-then-quiet pattern)
    """
    if len(bars) < POLE_BARS + FLAG_BARS_MIN + 1:
        return None

    trigger_bar    = bars[-1]
    max_pole_start = len(bars) - POLE_BARS - FLAG_BARS_MIN - 1

    for p in range(max_pole_start, -1, -1):
        pole_b = bars[p : p + POLE_BARS]
        flag_b = bars[p + POLE_BARS : -1]

        if len(flag_b) < FLAG_BARS_MIN:
            continue

        pole_open = pole_b[0]["o"]
        if pole_open <= 0:
            continue

        pole_low  = min(b["l"] for b in pole_b)
        pole_vol  = sum(b["v"] for b in pole_b)
        pole_move = pole_open - pole_low                # positive number = magnitude of drop
        pole_pct  = pole_move / pole_open * 100

        if pole_pct < POLE_MIN_PCT:                     # not enough downward thrust
            continue

        flag_high  = max(b["h"] for b in flag_b)
        flag_low   = min(b["l"] for b in flag_b)
        flag_range = flag_high - flag_low

        if pole_move > 0 and flag_range > pole_move * FLAG_MAX_RATIO:
            continue                                    # flag too wide — failed pattern

        # Inverse of bull-flag direction check: flag must DRIFT UP (or stay flat),
        # not continue down. Flag avg close > pole's last close confirms the
        # bounce-then-distribution pattern.
        flag_avg_close  = sum(b["c"] for b in flag_b) / len(flag_b)
        pole_last_close = pole_b[-1]["c"]
        if flag_avg_close < pole_last_close:
            continue

        # Trigger: current bar's low must break below the flag low.
        if trigger_bar["l"] >= flag_low:
            continue

        # Volume contraction in flag (panic then quiet), with same 30% slack.
        flag_avg_vol       = sum(b["v"] for b in flag_b) / len(flag_b)
        pole_avg_vol       = pole_vol / POLE_BARS
        volume_contracting = flag_avg_vol < pole_avg_vol * 1.30
        if not volume_contracting:
            continue

        return {
            "pole_pct":           round(pole_pct, 2),
            "pole_low":           round(pole_low, 4),
            "flag_high":          round(flag_high, 4),
            "flag_low":           round(flag_low, 4),
            "volume_contracting": True,
        }

    return None


def _detect_breakdown_hist(bars: list[dict], prev_close: float) -> Optional[dict]:
    """
    Inverse of _detect_breakout_hist: price closes ≥ 5% below prev_close, and
    we're at a new session low. The simple breakdown trigger (no flag pattern).
    """
    if not bars:
        return None

    current_price = bars[-1]["c"]
    if current_price >= prev_close * 0.95:               # need 5%+ below
        return None

    stop_ref     = max(b["h"] for b in bars)             # for shorts, stop is the high
    current_low  = min(b["l"] for b in bars)

    return {
        "pole_pct":           round((prev_close - current_price) / prev_close * 100, 2),
        "pole_low":           round(current_low, 4),
        "flag_high":          round(stop_ref, 4),         # stop reference (above entry)
        "flag_low":           round(current_price, 4),
        "volume_contracting": False,
    }


# ── Inverse bracket simulation (shorts) ──────────────────────────────────────

def _simulate_bracket_short(
    entry_price:   float,
    stop_price:    float,    # ABOVE entry — buy-to-cover stop
    take_profit:   float,    # BELOW entry — buy-to-cover target
    bars:          list[dict],
    eod_cutoff:    str,
    time_stop_utc: Optional[str] = None,
    squeeze_r:     float = SHORT_SQUEEZE_R_MULT,
    squeeze_bars:  int   = SHORT_SQUEEZE_BARS,
) -> tuple[str, float]:
    """
    Returns (outcome_tag, fill_price) for a short bracket. Fill price is the
    cost we pay to close the position — lower is better for our P&L.

      WIN     → bar.l ≤ take_profit (price dropped to target; cover at limit)
      LOSS    → bar.h ≥ stop_price  (price rose to stop; cover at stop, slipped)
      SQUEEZE → within first squeeze_bars, price moves ≥ squeeze_r × R against
                us. Force-cover at that bar's high (worst-case slippage).
      TIME    → at time_stop_utc, force-cover at bar's close.
      EOD     → at eod_cutoff, force-cover at bar's close.

    Slippage model:
      WIN  = limit fill, no slip (we covered at our take-profit limit)
      LOSS = stop converts to market on trigger; small-cap slips ABOVE the stop
             on the way out, so we pay MORE than stop_price.
      EOD/TIME = market cover, slipped against us by EQUITY_SLIPPAGE_PCT.
    """
    # R magnitude (always positive)
    r_dollars = stop_price - entry_price                    # > 0 by construction
    squeeze_trigger_price = entry_price + squeeze_r * r_dollars

    for i, bar in enumerate(bars):
        if bar["t"] >= eod_cutoff:
            return "EOD", bar["c"] * (1.0 + EQUITY_SLIPPAGE_PCT)
        if time_stop_utc and bar["t"] >= time_stop_utc:
            return "TIME", bar["c"] * (1.0 + EQUITY_SLIPPAGE_PCT)
        # Squeeze check — only first N bars after entry
        if i < squeeze_bars and bar["h"] >= squeeze_trigger_price:
            # Force-cover at the squeeze trigger (better than waiting for stop)
            return "SQUEEZE", bar["h"] * (1.0 + EQUITY_SLIPPAGE_STOP)
        if bar["h"] >= stop_price:
            return "LOSS", stop_price * (1.0 + EQUITY_SLIPPAGE_STOP)
        if bar["l"] <= take_profit:
            return "WIN", take_profit * (1.0 + EQUITY_SLIPPAGE_LIMIT)
    if bars:
        return "EOD", bars[-1]["c"] * (1.0 + EQUITY_SLIPPAGE_PCT)
    return "EOD", entry_price


# ── Bracket simulation ────────────────────────────────────────────────────────

def _simulate_bracket(
    entry_price: float,
    stop_price:  float,
    take_profit: float,
    bars:        list[dict],
    eod_cutoff:  str,
) -> tuple[str, float]:
    """
    Returns (outcome_tag, fill_price) where fill_price already includes the
    appropriate sell-side slippage:
      - WIN  → take_profit × (1 - EQUITY_SLIPPAGE_LIMIT) — limit fill, ~0 slip
      - LOSS → stop_price  × (1 - EQUITY_SLIPPAGE_STOP)  — stop converts to
        market on trigger; sub-$20 small caps gap through the stop, costing
        a real haircut on the way out.
      - EOD  → close × (1 - EQUITY_SLIPPAGE_PCT) — market sell at the bell
    """
    for bar in bars:
        if bar["t"] >= eod_cutoff:
            return "EOD", bar["c"] * (1.0 - EQUITY_SLIPPAGE_PCT)
        if bar["l"] <= stop_price:
            return "LOSS", stop_price * (1.0 - EQUITY_SLIPPAGE_STOP)
        if bar["h"] >= take_profit:
            return "WIN", take_profit * (1.0 - EQUITY_SLIPPAGE_LIMIT)
    if bars:
        return "EOD", bars[-1]["c"] * (1.0 - EQUITY_SLIPPAGE_PCT)
    return "EOD", entry_price


# ── Scale-in-aware bracket simulation ────────────────────────────────────────
#
# Models the full live T1+T2+T3 lifecycle so backtest P&L matches what the
# live bot would actually realize. See live source of truth:
#   gap_trader.run_scale()              — T2/T3 fill triggers at 9:45 + 10:00 ET
#   gap_scanner.py:951-1009             — T1 breakeven→trail at +1R
# Lifecycle (long side):
#   T1:  initial 25% × conv_mult. Bracket stop=flag_low, target=entry+3R.
#        On +1R, cancel both bracket legs and replace with a dollar trailing
#        stop trailing risk_per_sh below HWM (initial stop = entry).
#   T2:  +50% (base TRANCHE_2_PCT × GAP_NOTIONAL — no conv mult) at 9:45 OR
#        10:00 ET if price >= flag_high × (1 + SCALE2_TRIGGER_PCT). 3% Alpaca
#        percent-trail; no fixed target.
#   T3:  +25% (base TRANCHE_3_PCT × GAP_NOTIONAL) at 10:00 ET if T2 already
#        filled and price >= T2_entry × (1 + SCALE3_TRIGGER_PCT). Fixed stop
#        at T1 entry price (breakeven of the original entry). No target.
#        Always exits at EOD; overnight rules are deliberately not modeled.

def _t1_breakeven_level(entry_price: float, risk_per_sh: float) -> float:
    """Price at which T1's bracket converts to a dollar trailing stop."""
    return entry_price + BREAKEVEN_TRIGGER_R * risk_per_sh


def _simulate_bracket_with_scaleins(
    entry_price:     float,
    t1_stop:         float,
    t1_target:       float,
    t1_shares:       int,
    t1_risk_per_sh:  float,
    flag_low:        float,
    flag_high:       float,
    bars:            list[dict],
    day:             date,
) -> dict:
    """
    Simulate one symbol's full intraday lifecycle across T1, T2, and T3.

    Inputs are the pre-computed T1 sizing (already includes conviction mult)
    and the pattern's flag bounds; T2/T3 are sized internally using
    calculate_entry against base TRANCHE_2_PCT / TRANCHE_3_PCT.

    Returns a dict with per-tranche outcomes and a blended total P&L. R-multiple
    is reported as total_pnl / (t1_shares × t1_risk_per_sh) — i.e., scaled to
    the same "R units" the T1-only mode reports, so cross-mode comparison is
    apples-to-apples on a per-trade basis. T2 and T3 add to that R when they
    contribute profit.
    """
    day_str = day.isoformat()
    eod_cutoff = day_str + _et_utc(day, 15, 55)
    t2_check_1 = day_str + _et_utc(day, 9, 45)
    t2_check_2 = day_str + _et_utc(day, 10, 0)
    t3_check   = day_str + _et_utc(day, 10, 0)

    t2_trigger = flag_high * (1.0 + SCALE2_TRIGGER_PCT)
    breakeven_level = _t1_breakeven_level(entry_price, t1_risk_per_sh)

    # T1 state
    t1_open = True
    t1_outcome: Optional[str] = None
    t1_exit_price = 0.0
    t1_breakeven_armed = False
    t1_trail_hwm = 0.0
    t1_trail_risk_mult = 1.0               # mutable; tightens on candle-reversal signal
    t1_candle_signal: Optional[str] = None  # records which signal fired (telemetry)

    # T2 state
    t2_filled = False
    t2_entry  = 0.0
    t2_shares = 0
    t2_open   = False
    t2_outcome: Optional[str] = None
    t2_exit_price = 0.0
    t2_trail_hwm  = 0.0
    t2_trail_pct  = TRAIL_PCT              # mutable; tightens on candle-reversal signal
    t2_candle_signal: Optional[str] = None  # records which signal fired (telemetry)

    # T3 state
    t3_filled = False
    t3_entry  = 0.0
    t3_shares = 0
    t3_open   = False
    t3_outcome: Optional[str] = None
    t3_exit_price = 0.0
    t3_stop_price = entry_price   # breakeven of T1

    for i, bar in enumerate(bars):
        bar_t, bar_o, bar_h, bar_l, bar_c = (
            bar["t"], bar["o"], bar["h"], bar["l"], bar["c"]
        )

        # ── EOD: force-close all still-open tranches ─────────────────────────
        if bar_t >= eod_cutoff:
            eod_fill = bar_c * (1.0 - EQUITY_SLIPPAGE_PCT)
            if t1_open:
                t1_open, t1_outcome, t1_exit_price = False, "EOD", eod_fill
            if t2_open:
                t2_open, t2_outcome, t2_exit_price = False, "EOD", eod_fill
            if t3_open:
                t3_open, t3_outcome, t3_exit_price = False, "EOD", eod_fill
            break

        # Snapshot status BEFORE any state mutation this bar — so a T2 fill
        # on this same bar cannot enable a T3 fill on the same bar (live
        # only checks T3 on calls where T2 was already filled at start).
        t2_was_filled_before_bar = t2_filled
        t1_open_at_bar_start     = t1_open

        # ── T2 scale-in trigger (at bar.open, "9:45 / 10:00 cron-fire") ─────
        # Done BEFORE T1's stop/trail logic for this bar. Physically: at
        # 9:45:00 the scale cron sees T1 still open per Alpaca state and
        # places the T2 market buy. T1's server-side trail might fire later
        # in the same minute — but T2 was already placed at 9:45:01.
        if (
            not t2_filled
            and t1_open_at_bar_start
            and bar_t in (t2_check_1, t2_check_2)
        ):
            check_price = bar_o
            if check_price >= t2_trigger:
                t2_fill_price = check_price * (1.0 + EQUITY_SLIPPAGE_PCT)
                t2_sizing = calculate_entry(
                    t2_fill_price, flag_low, TRANCHE_2_PCT, 0.0,
                )
                if t2_sizing and t2_sizing["shares"] >= 1:
                    t2_filled = True
                    t2_open   = True
                    t2_entry  = t2_fill_price
                    t2_shares = t2_sizing["shares"]
                    t2_trail_hwm = t2_fill_price

        # ── T3 scale-in trigger (only if T2 was filled BEFORE this bar) ─────
        if (
            not t3_filled
            and t2_was_filled_before_bar
            and t2_open
            and bar_t == t3_check
        ):
            check_price = bar_o
            t3_trigger = t2_entry * (1.0 + SCALE3_TRIGGER_PCT)
            if check_price >= t3_trigger:
                t3_fill_price = check_price * (1.0 + EQUITY_SLIPPAGE_PCT)
                t3_sizing = calculate_entry(
                    t3_fill_price, t1_stop, TRANCHE_3_PCT, 0.0,
                )
                if t3_sizing and t3_sizing["shares"] >= 1:
                    t3_filled = True
                    t3_open   = True
                    t3_entry  = t3_fill_price
                    t3_shares = t3_sizing["shares"]

        # ── Candle-reversal exit signal (Ross): tighten T1 and/or T2 trails on
        # completed prior bars showing topping-tail / shooting-star / bearish-
        # engulfing. Checked BEFORE this bar's T1/T2 trail computation so the
        # tightened trail takes effect on the same bar. One-shot per trail
        # (state flag prevents repeated tightening).
        if i >= 1 and (
            (t1_open and t1_breakeven_armed and t1_candle_signal is None)
            or (t2_open and t2_candle_signal is None)
        ):
            sig = detect_candle_exit_signal(bars[:i])
            if sig is not None:
                if t1_open and t1_breakeven_armed and t1_candle_signal is None:
                    t1_candle_signal   = sig
                    t1_trail_risk_mult = T1_TRAIL_R_TIGHTENED
                if t2_open and t2_candle_signal is None:
                    t2_candle_signal = sig
                    t2_trail_pct     = TRAIL_PCT_TIGHTENED

        # ── T1 exit logic for this bar ───────────────────────────────────────
        if t1_open:
            if t1_breakeven_armed:
                t1_trail_hwm = max(t1_trail_hwm, bar_h)
                trail_stop = t1_trail_hwm - t1_risk_per_sh * t1_trail_risk_mult
                if bar_l <= trail_stop:
                    t1_open = False
                    t1_outcome = "TRAIL"
                    t1_exit_price = trail_stop * (1.0 - EQUITY_SLIPPAGE_STOP)
            else:
                # Pre-breakeven: conservative bar order — stop checked first
                if bar_l <= t1_stop:
                    t1_open = False
                    t1_outcome = "STOP"
                    t1_exit_price = t1_stop * (1.0 - EQUITY_SLIPPAGE_STOP)
                elif bar_h >= breakeven_level:
                    t1_breakeven_armed = True
                    t1_trail_hwm = bar_h
                    trail_stop = t1_trail_hwm - t1_risk_per_sh * t1_trail_risk_mult
                    if bar_l <= trail_stop:
                        t1_open = False
                        t1_outcome = "TRAIL"
                        t1_exit_price = trail_stop * (1.0 - EQUITY_SLIPPAGE_STOP)

        # ── T2 trail-stop management ─────────────────────────────────────────
        if t2_open:
            t2_trail_hwm = max(t2_trail_hwm, bar_h)
            t2_trail_stop = t2_trail_hwm * (1.0 - t2_trail_pct / 100.0)
            if bar_l <= t2_trail_stop:
                t2_open = False
                t2_outcome = "TRAIL"
                t2_exit_price = t2_trail_stop * (1.0 - EQUITY_SLIPPAGE_STOP)

        # ── T3 stop (fixed at T1 entry) ──────────────────────────────────────
        if t3_open:
            if bar_l <= t3_stop_price:
                t3_open = False
                t3_outcome = "STOP"
                t3_exit_price = t3_stop_price * (1.0 - EQUITY_SLIPPAGE_STOP)

    # If bars exhausted without crossing EOD cutoff, force-close at the last bar.
    if (t1_open or t2_open or t3_open) and bars:
        eod_fill = bars[-1]["c"] * (1.0 - EQUITY_SLIPPAGE_PCT)
        if t1_open:
            t1_open, t1_outcome, t1_exit_price = False, "EOD", eod_fill
        if t2_open:
            t2_open, t2_outcome, t2_exit_price = False, "EOD", eod_fill
        if t3_open:
            t3_open, t3_outcome, t3_exit_price = False, "EOD", eod_fill

    # If we never entered the loop (empty bars list), close T1 at entry.
    if t1_outcome is None:
        t1_outcome   = "EOD"
        t1_exit_price = entry_price

    t1_pnl = (t1_exit_price - entry_price) * t1_shares
    t2_pnl = (t2_exit_price - t2_entry) * t2_shares if t2_filled else 0.0
    t3_pnl = (t3_exit_price - t3_entry) * t3_shares if t3_filled else 0.0
    total_pnl = t1_pnl + t2_pnl + t3_pnl

    r_unit = t1_shares * t1_risk_per_sh
    blended_r = total_pnl / r_unit if r_unit > 0 else 0.0

    return {
        "t1_outcome":    t1_outcome,
        "t1_exit":       round(t1_exit_price, 4),
        "t1_pnl":        round(t1_pnl, 2),
        "t1_candle_signal": t1_candle_signal or "",
        "t2_filled":     t2_filled,
        "t2_entry":      round(t2_entry, 4) if t2_filled else 0.0,
        "t2_shares":     t2_shares,
        "t2_outcome":    t2_outcome or "",
        "t2_exit":       round(t2_exit_price, 4) if t2_filled else 0.0,
        "t2_pnl":        round(t2_pnl, 2),
        "t2_candle_signal": t2_candle_signal or "",
        "t3_filled":     t3_filled,
        "t3_entry":      round(t3_entry, 4) if t3_filled else 0.0,
        "t3_shares":     t3_shares,
        "t3_outcome":    t3_outcome or "",
        "t3_exit":       round(t3_exit_price, 4) if t3_filled else 0.0,
        "t3_pnl":        round(t3_pnl, 2),
        "total_pnl":     round(total_pnl, 2),
        "blended_r":     round(blended_r, 2),
    }


# ── Ross-style scale-out simulator (item 5b) ─────────────────────────────────
#
# Enters full T1 conviction-sized position, then harvests via a multi-tier
# limit-sell ladder. After each tier fires the stop ratchets up so the
# remaining shares lock in progressively more profit. The last tier is a
# "runner" managed by a dollar trail above a floor.
#
# Differences vs scale-IN model:
#   - SCALE-IN  adds on confirmed strength (T2 at flag×1.005, T3 at T2×1.010);
#               fatter right tail; bigger drawdowns on reversals from highs.
#   - SCALE-OUT removes on confirmed strength (limit sells at +1R/+2R/+3R);
#               smoother equity curve; smaller right tail; locks gains earlier.
#
# Within-bar order: when bar.h >= scale-out target AND bar.l <= current stop,
# we assume limit fires FIRST (high reached before low on a rally) and the
# ratcheted stop applies to the remainder. Less conservative than legacy's
# "stop-first" model but more realistic for the typical "gap up, then
# retrace" intraday pattern Ross trades.

def _scaleout_stop_after_tier(
    tier_idx_done: int, entry_price: float, risk_per_sh: float,
) -> float:
    """
    Stop level for the remaining position AFTER scale-out tier_idx fired.
      tier_idx_done = 0 (just fired tier 1 / +1R) → stop = entry (breakeven)
      tier_idx_done = 1 (just fired tier 2 / +2R) → stop = entry + 1R
      tier_idx_done = 2 (just fired tier 3 / +3R) → stop = entry + 2R (runner floor)
    """
    levels = [entry_price,
              entry_price + risk_per_sh,
              entry_price + 2.0 * risk_per_sh]
    return levels[min(tier_idx_done, len(levels) - 1)]


def _simulate_bracket_with_scaleouts(
    entry_price:     float,
    initial_stop:    float,           # flag_low
    initial_shares:  int,
    risk_per_sh:     float,
    bars:            list[dict],
    day:             date,
    ladder:          list[tuple[float, float]] = None,
) -> dict:
    """
    Returns:
      {
        'tier_fills':     list of (tier_idx, r_target, shares_sold, fill_price, pnl)
        'final_outcome':  'STOP'/'TRAIL'/'EOD'  — how the runner closed
        'final_exit':     fill price for the runner remainder
        'final_shares':   shares remaining when the last exit fired
        'total_pnl':      sum of all tier pnls + runner pnl
        'blended_r':      total_pnl / (initial_shares × risk_per_sh)
        'tiers_fired':    how many ladder rungs fired
      }
    """
    if ladder is None:
        ladder = SCALEOUT_LADDER

    day_str = day.isoformat()
    eod_cutoff = day_str + _et_utc(day, 15, 55)

    shares_remaining = initial_shares
    current_stop     = initial_stop
    tier_idx         = 0           # next ladder rung to check
    tiers_fired      = 0
    trail_armed      = False
    trail_hwm        = 0.0

    tier_fills: list[dict] = []
    final_outcome: Optional[str] = None
    final_exit_price = 0.0
    final_shares_at_exit = 0

    for bar in bars:
        bar_t, bar_h, bar_l, bar_c = bar["t"], bar["h"], bar["l"], bar["c"]

        if bar_t >= eod_cutoff and shares_remaining > 0:
            final_outcome  = "EOD"
            final_exit_price = bar_c * (1.0 - EQUITY_SLIPPAGE_PCT)
            final_shares_at_exit = shares_remaining
            shares_remaining = 0
            break

        # ── Pessimistic intrabar ordering (BT_PESSIMISTIC_FILLS=1) ──────────
        # Worst-case bound on the 1-min intrabar artifact: when a bar straddles
        # both the stop and a target, assume the DOWN-move came first and the
        # stop fills before any target this bar. Brackets the true result vs the
        # default target-first (optimistic) path. Stop level = as of bar open.
        if os.getenv("BT_PESSIMISTIC_FILLS") == "1":
            _eff_stop_pre = (max(current_stop, trail_hwm - risk_per_sh)
                             if trail_armed else current_stop)
            if bar_l <= _eff_stop_pre:
                final_outcome  = "TRAIL" if trail_armed else "STOP"
                final_exit_price = _eff_stop_pre * (1.0 - EQUITY_SLIPPAGE_STOP)
                final_shares_at_exit = shares_remaining
                shares_remaining = 0
                break

        # ── Phase 1: scale-out limit fires (high reached first on rallies) ──
        # Walk ladder forward; one bar can fire multiple rungs if it gaps.
        while tier_idx < len(ladder) and shares_remaining > 0:
            r_target, frac = ladder[tier_idx]
            target_price = entry_price + r_target * risk_per_sh
            if bar_h < target_price:
                break

            # Shares-to-sell at this rung: planned fraction of INITIAL size,
            # but capped at whatever's still open in case of int-rounding.
            planned = max(1, int(initial_shares * frac))
            shares_to_sell = min(planned, shares_remaining)
            tier_pnl = (target_price - entry_price) * shares_to_sell

            tier_fills.append({
                "tier":         tier_idx + 1,
                "r_target":     r_target,
                "shares_sold":  shares_to_sell,
                "fill_price":   round(target_price * (1.0 - EQUITY_SLIPPAGE_LIMIT), 4),
                "pnl":          round(tier_pnl, 2),
            })
            shares_remaining -= shares_to_sell
            tiers_fired      += 1
            # Ratchet stop after this tier fired
            current_stop = _scaleout_stop_after_tier(tier_idx, entry_price, risk_per_sh)
            tier_idx += 1

            if tier_idx >= len(ladder) and shares_remaining > 0:
                trail_armed = True
                trail_hwm   = bar_h

        if shares_remaining <= 0:
            # All shares sold via tiers; trade fully closed
            final_outcome  = "FULL"
            final_exit_price = 0.0  # no separate "final" exit; all via tiers
            final_shares_at_exit = 0
            break

        # ── Phase 2: stop / trail check on whatever's left ──────────────────
        if trail_armed:
            trail_hwm = max(trail_hwm, bar_h)
            effective_stop = max(current_stop, trail_hwm - risk_per_sh)
        else:
            effective_stop = current_stop

        if bar_l <= effective_stop:
            final_outcome  = "TRAIL" if trail_armed else "STOP"
            # Limit-derived stops (breakeven/+1R/+2R levels) had no slip in
            # live's mental model (placed as stop-limit at exact level), but
            # we apply the standard stop slip to be conservative for sub-$20
            # small caps where stops convert to market on trigger.
            final_exit_price = effective_stop * (1.0 - EQUITY_SLIPPAGE_STOP)
            final_shares_at_exit = shares_remaining
            shares_remaining = 0
            break

    # Bars exhausted without EOD; force-close at last bar
    if shares_remaining > 0 and bars:
        final_outcome  = "EOD"
        final_exit_price = bars[-1]["c"] * (1.0 - EQUITY_SLIPPAGE_PCT)
        final_shares_at_exit = shares_remaining
        shares_remaining = 0

    if final_outcome is None:
        final_outcome  = "EOD"
        final_exit_price = entry_price
        final_shares_at_exit = initial_shares  # never traded

    final_pnl = (final_exit_price - entry_price) * final_shares_at_exit \
                if final_shares_at_exit > 0 else 0.0
    tier_pnl_sum = sum(t["pnl"] for t in tier_fills)
    total_pnl = tier_pnl_sum + final_pnl

    r_unit = initial_shares * risk_per_sh
    blended_r = total_pnl / r_unit if r_unit > 0 else 0.0

    return {
        "tier_fills":    tier_fills,
        "tiers_fired":   tiers_fired,
        "final_outcome": final_outcome,
        "final_exit":    round(final_exit_price, 4),
        "final_shares":  final_shares_at_exit,
        "final_pnl":     round(final_pnl, 2),
        "tier_pnl":      round(tier_pnl_sum, 2),
        "total_pnl":     round(total_pnl, 2),
        "blended_r":     round(blended_r, 2),
    }


# ── Simulate one candidate on one day ────────────────────────────────────────

# ── Pullback-entry experiment (BT_PULLBACK_ENTRY=1) ──────────────────────────
# Phase 1 of the D→A+ plan. Default OFF → breakout path unchanged (parity-safe).
# Rests a limit at the flag_low retest instead of taking the next-bar-open
# breakout. Fills ONLY if price pulls back → tighter stop + larger R per fill,
# but structurally misses gap-and-go runners that never retrace. The backtest
# settles whether better-R-per-fill beats missed-runners. Stop width per
# BT_PULLBACK_STOP: tight (~0.5% below flag_low) | atr | breakout (~MAX_RISK_PCT).
import os as _os_pb
_PULLBACK_ENTRY          = _os_pb.getenv("BT_PULLBACK_ENTRY") == "1"
_PULLBACK_STOP           = (_os_pb.getenv("BT_PULLBACK_STOP") or "tight").lower()
PULLBACK_FILL_BUFFER_PCT = 0.001   # rest the limit 0.1% above flag_low
PULLBACK_TIGHT_PCT       = 0.005   # tight stop: 0.5% below flag_low
PULLBACK_ATR_MULT        = 1.0     # atr stop: flag_low − 1×ATR(1-min)

# ── Momentum / "first-push" entry bundle (Ross: trade the start of the move, on
# rising volume, on the most-obvious/highest-RVOL name). Default OFF. ──────────
#   BT_MOMENTUM_ENTRY=1     enable the bundle (uses breakout/strength entry)
#   BT_ENTRY_CUTOFF_MIN=N   no new entries after open+N minutes (default 60)
#   BT_VOL_CONFIRM=1        require trigger-bar volume >= mult × recent average
#   BT_VOL_MULT=1.5         the volume-expansion multiple
#   BT_VOL_LOOKBACK=5       bars to average for the baseline
#   BT_FIXED_STOP_PCT=0.02  fixed % stop from entry (clean 2% vs 3% test)
#   BT_RANK_RVOL=1          rank candidates by RVOL desc (the "obvious" stock)
#   BT_VWAP_FILTER=1        require trigger-bar close >= day's VWAP (above avg price)
#   BT_DYN_LEADER=1         only enter when this name is among the live top-K busiest
#                           (rolling intraday RVOL); leadership can rotate intraday.
#   BT_DYN_LEADER_K=1       how many live leaders are tradeable at each minute (1 or 3)
_MOMENTUM_ENTRY   = _os_pb.getenv("BT_MOMENTUM_ENTRY") == "1"
_ENTRY_CUTOFF_MIN = int(_os_pb.getenv("BT_ENTRY_CUTOFF_MIN") or 60)
_VOL_CONFIRM      = _os_pb.getenv("BT_VOL_CONFIRM") == "1"
_VOL_MULT         = float(_os_pb.getenv("BT_VOL_MULT") or 1.5)
_VOL_LOOKBACK     = int(_os_pb.getenv("BT_VOL_LOOKBACK") or 5)
_VWAP_FILTER      = _os_pb.getenv("BT_VWAP_FILTER") == "1"
_DYN_LEADER       = _os_pb.getenv("BT_DYN_LEADER") == "1"
_DYN_LEADER_K     = int(_os_pb.getenv("BT_DYN_LEADER_K") or 1)


def _build_leader_ranks(bars_by_sym, avgvol_by_sym, day_str):
    """Rolling intraday-leadership rank for each candidate.

    Two cross-sectional ranking metrics (BT_LEADER_METRIC):
      "level" (default) — busiest right now: cumulative session volume by t /
                          30d avg daily volume. Favors names already running.
      "accel"           — where volume is MOVING TO: recent W-min volume rate /
                          the day-so-far average per-min rate. Favors names
                          whose volume is surging right now, even if early.
    Ranks recomputed each minute, so leadership ROTATES through the day.

    Returns {symbol: {bar_ts: live_rank}} with rank 1 = top. A symbol is only
    stamped at timestamps where it actually has a bar.
    """
    import os as _osl
    metric = (_osl.getenv("BT_LEADER_METRIC") or "level").lower()
    accel_w = int(_osl.getenv("BT_ACCEL_WINDOW") or 5)

    # Per-symbol ordered (ts, cumulative-volume, day-so-far score).
    score_by_sym = {}
    all_ts = set()
    for sym, bars in bars_by_sym.items():
        tb = [b for b in bars if b["t"][:10] == day_str]
        av = avgvol_by_sym.get(sym) or 1
        cum = 0.0
        cvols, cums, tss = [], [], []
        for b in tb:
            cum += b["v"]
            cvols.append(b["v"]); cums.append(cum); tss.append(b["t"])
            all_ts.add(b["t"])
        sc = {}
        for j, ts in enumerate(tss):
            if metric == "accel":
                # recent W-min volume rate vs day-so-far average per-min rate
                recent = cums[j] - (cums[j - accel_w] if j >= accel_w else 0.0)
                rwin = min(accel_w, j + 1)
                recent_rate = recent / rwin if rwin else 0.0
                base_rate = cums[j] / (j + 1) if (j + 1) else 0.0
                sc[ts] = (recent_rate / base_rate) if base_rate > 0 else 0.0
            else:
                sc[ts] = cums[j] / av           # level
        score_by_sym[sym] = sc

    ranks = {sym: {} for sym in bars_by_sym}
    last = {sym: 0.0 for sym in bars_by_sym}
    for ts in sorted(all_ts):
        for sym, sc in score_by_sym.items():
            if ts in sc:
                last[sym] = sc[ts]
        scored = [(sym, last[sym]) for sym in bars_by_sym if last[sym] > 0]
        scored.sort(key=lambda x: -x[1])
        rank_of = {sym: idx + 1 for idx, (sym, _) in enumerate(scored)}
        for sym, sc in score_by_sym.items():
            if ts in sc:
                ranks[sym][ts] = rank_of.get(sym, 9999)
    return ranks


def _atr_1min(bars: list[dict], period: int = 14) -> float:
    """Simple ATR proxy: mean high−low range over the last `period` bars."""
    if not bars:
        return 0.0
    window = bars[-period:]
    ranges = [b["h"] - b["l"] for b in window if b["h"] >= b["l"]]
    return sum(ranges) / len(ranges) if ranges else 0.0


def simulate_candidate(
    symbol:         str,
    day:            date,
    prev_close:     float,
    bars_1min:      list[dict],
    avg_vol:        float,
    hist_df,
    gap_pct:        float,
    rvol:           float,
    float_shares:   int,
    resistance:     bool,
    float_verified: bool = True,
    has_catalyst:   bool = False,
    news_quality:   int  = 0,
    news_negative:  bool = False,
    leader_rank:    Optional[dict] = None,
) -> Optional[dict]:
    day_str      = day.isoformat()
    open_utc     = day_str + _et_utc(day, 9,  30)   # 9:30 AM ET
    # Entry window now extends to EOD-1min. Session-agnostic principle: a
    # pattern that fires at 11:15 ET is the same trade as one at 9:33 ET;
    # the prior 10:30 ET cap structurally cut off multi-leg breakouts Ross
    # explicitly trades through the morning. (Pre-2026-05-15 had close_utc
    # = 10:30 ET — removed per Ross video j5nHtWHNJPk evidence.)
    close_utc    = day_str + _et_utc(day, 15, 54)
    eod_utc      = day_str + _et_utc(day, 15, 55)   # 3:55 PM ET EOD exit
    mon_open_utc = day_str + _et_utc(day, 9,  45)   # 9:45 AM ET Monday wait

    # ── Pre-loop entry quality gates ─────────────────────────────────────────
    if GAP_ENTRY_MIN_PCT and gap_pct < GAP_ENTRY_MIN_PCT:
        return None
    if RVOL_ENTRY_MIN and rvol < RVOL_ENTRY_MIN:
        return None
    # ── Extension cap (BT_GAP_MAX / BT_RVOL_MAX) ─────────────────────────────
    # Cut the over-extended pump-and-fade setups. The 2026-06-03 practitioner
    # review found EXCEPTIONAL-tier entries (highest gap%+RVOL) had the WORST
    # win rate (38% vs 67% for STRONG) — parabolic low-float blow-offs that fade.
    # Upper bounds reject those; controlled gaps remain. Off unless env set.
    import os as _os
    _gmax = _os.getenv("BT_GAP_MAX"); _rmax = _os.getenv("BT_RVOL_MAX")
    if _gmax and gap_pct > float(_gmax):
        return None
    if _rmax and rvol > float(_rmax):
        return None
    if SKIP_RESISTANCE and resistance:
        return None

    # Compute runner status once (hist_df doesn't change per bar)
    is_runner, run_days = check_multi_day_runner(hist_df, avg_vol) \
        if hist_df is not None and not hist_df.empty else (False, 0)
    if SKIP_RUNNERS and is_runner:
        return None

    today_bars = [b for b in bars_1min if b["t"][:10] == day_str]
    if not today_bars:
        return None

    # ── Causal spike-activation gate (BT_INTRADAY_GAP=1) ─────────────────────
    # The intraday screen selects on the realized day-high, which would let a
    # name be entered BEFORE its spike actually printed (look-ahead). Fix: find
    # the first 1-min bar where price actually crossed +GAP_MIN_PCT above prev
    # close — the moment the live scanner would have flagged it — and forbid any
    # entry before that bar. If it never spiked intraday, it isn't a candidate.
    import os as _os_act
    _activation_utc = None
    if _os_act.getenv("BT_INTRADAY_GAP") == "1":
        _spike_level = prev_close * (1 + GAP_MIN_PCT / 100.0)
        for _b in today_bars:
            if _b["h"] >= _spike_level:
                _activation_utc = _b["t"]
                break
        if _activation_utc is None:
            return None

    # Earliest bar time allowed for pattern detection (so entry bar lands >= MIN_ENTRY_OFFSET_MINS)
    _min_open_et = datetime(day.year, day.month, day.day, 9, 30, tzinfo=EASTERN) \
                   + timedelta(minutes=MIN_ENTRY_OFFSET_MINS)
    min_offset_utc = day_str + _min_open_et.astimezone(timezone.utc).strftime("T%H:%M:%SZ")

    # Momentum mode: hard cutoff — no new entries after open + cutoff minutes
    # (trade the START of the move, in the high-volume early session).
    _cutoff_et = datetime(day.year, day.month, day.day, 9, 30, tzinfo=EASTERN) \
                 + timedelta(minutes=_ENTRY_CUTOFF_MIN)
    momentum_cutoff_utc = day_str + _cutoff_et.astimezone(timezone.utc).strftime("T%H:%M:%SZ")

    min_needed = POLE_BARS + FLAG_BARS_MIN + 1

    for i in range(min_needed - 1, len(today_bars)):
        bar = today_bars[i]
        bar_time = bar["t"]

        if bar_time < open_utc or bar_time > close_utc:
            continue
        if day.weekday() == 0 and bar_time < mon_open_utc:
            continue
        if bar_time < min_offset_utc:
            continue
        # Causal gate: no entry before the name actually spiked (see above).
        if _activation_utc is not None and bar_time < _activation_utc:
            continue
        # Momentum mode: stop looking once past the early-session window.
        if _MOMENTUM_ENTRY and bar_time > momentum_cutoff_utc:
            break

        bars_so_far = today_bars[:i + 1]

        pattern = _detect_bull_flag_hist(bars_so_far)
        if not pattern:
            pattern = _detect_breakout_hist(bars_so_far, prev_close)
        if not pattern:
            continue

        # Momentum mode: require expanding volume on the trigger bar — buy
        # strength, not a quiet drift (Ross: trade where the volume is).
        if _MOMENTUM_ENTRY and _VOL_CONFIRM and i >= _VOL_LOOKBACK:
            _base_vol = sum(b["v"] for b in today_bars[i - _VOL_LOOKBACK:i]) / _VOL_LOOKBACK
            if _base_vol > 0 and bar["v"] < _VOL_MULT * _base_vol:
                continue

        # VWAP filter — only buy when the stock is trading ABOVE its
        # volume-weighted average price for the day so far (a common "is it
        # really strong / are buyers in control" check). Standalone & causal:
        # VWAP computed only from bars up to and including the trigger bar.
        if _VWAP_FILTER:
            _vp = _vv = 0.0
            for _b in today_bars[:i + 1]:
                _typ = (_b["h"] + _b["l"] + _b["c"]) / 3.0
                _vp += _typ * _b["v"]
                _vv += _b["v"]
            if _vv > 0 and bar["c"] < (_vp / _vv):
                continue

        # Dynamic-leader gate — only enter when THIS name is among the live
        # top-K busiest (rolling intraday RVOL) at the trigger minute. Leadership
        # rotates intraday, so different names trade at different times of day.
        # leader_rank maps bar-timestamp -> this symbol's live rank (1 = busiest).
        if _DYN_LEADER:
            _rk = leader_rank.get(bar_time) if leader_rank else None
            if _rk is None or _rk > _DYN_LEADER_K:
                continue

        # Ross entry-quality gates (MACD / 9-EMA / VWAP).
        #   "none"       — disabled, no telemetry, no behavioral change.
        #   "score"      — compute + log gates_passed, never reject (telemetry).
        #   "conviction" — like score, plus halve conviction multiplier when
        #                  gates_passed == 0 (the shipped Ross-true behavior).
        #   "hard"       — reject unless all 3 gates pass (backtest only).
        #   "majority"   — reject unless ≥2 of 3 gates pass (backtest only).
        gates_passed = 3
        gates_reason = "disabled"
        gate_macd_ok = gate_ema_ok = gate_vwap_ok = ""
        # For conviction/score modes, gates are computed but never reject.
        check_mode = ENTRY_GATES_MODE
        if check_mode == "conviction":
            check_mode = "score"
        if check_mode != "none":
            gate_ok, gates_reason, gates_passed = check_entry_gates(
                bars_so_far,
                flag_low    = pattern["flag_low"],
                mode        = check_mode,
                ema_tol_pct = EMA9_TOL_PCT,
            )
            gate_macd_ok = _gf.LAST_GATE_BREAKDOWN["macd_ok"]
            gate_ema_ok  = _gf.LAST_GATE_BREAKDOWN["ema_ok"]
            gate_vwap_ok = _gf.LAST_GATE_BREAKDOWN["vwap_ok"]
            if not gate_ok:
                continue

        if i + 1 >= len(today_bars):
            break

        # ── Entry mechanic: breakout (default) vs pullback (BT_PULLBACK_ENTRY) ──
        # Breakout fills market at next-bar open (above flag_high), stop at
        # flag_low (wide). Pullback rests a limit at the flag_low retest →
        # tighter stop, bigger R per fill, but only fills if price pulls back.
        flag_low_ref = pattern["flag_low"]
        if _PULLBACK_ENTRY:
            entry_level = flag_low_ref * (1.0 + PULLBACK_FILL_BUFFER_PCT)
            entry_idx = None
            for _j in range(i + 1, len(today_bars)):
                if today_bars[_j]["t"] > close_utc:
                    break
                if today_bars[_j]["l"] <= entry_level:   # limit fills on the retest
                    entry_idx = _j
                    break
            if entry_idx is None:
                continue   # never pulled back → no fill (misses no-retrace runners)
            entry_bar   = today_bars[entry_idx]
            entry_price = entry_level                    # resting limit — no positive slippage
            if _PULLBACK_STOP == "atr":
                stop_ref = flag_low_ref - PULLBACK_ATR_MULT * _atr_1min(today_bars[:entry_idx + 1])
            elif _PULLBACK_STOP == "breakout":
                # baseline-width risk from the better entry; width configurable
                # via BT_PULLBACK_STOP_PCT (default MAX_RISK_PCT = 3%).
                _spct = float(_os_pb.getenv("BT_PULLBACK_STOP_PCT") or MAX_RISK_PCT)
                stop_ref = entry_level * (1.0 - _spct)
            else:  # "tight"
                stop_ref = flag_low_ref * (1.0 - PULLBACK_TIGHT_PCT)
        else:
            entry_idx   = i + 1
            entry_bar   = today_bars[entry_idx]
            # Apply buy-side slippage: market orders fill above the open.
            entry_price = entry_bar["o"] * (1.0 + EQUITY_SLIPPAGE_PCT)
            # Fixed-% stop (BT_FIXED_STOP_PCT) overrides flag_low for a clean
            # 2%-vs-3% comparison on the strength/momentum entry.
            _fsp = _os_pb.getenv("BT_FIXED_STOP_PCT")
            stop_ref = entry_price * (1.0 - float(_fsp)) if _fsp else flag_low_ref
        if entry_bar["t"] > close_utc:
            break
        # Filter on the realistic fill, not the optimistic next-bar open.
        if not (PRICE_MIN <= entry_price <= PRICE_MAX):
            break

        # Ross 50%-retrace rule (gap_filters.has_retraced_past_halfway).
        # If the stock has given back more than half its move from prev_close
        # to the day's high, skip the entry regardless of pattern.
        if has_retraced_past_halfway(prev_close, bars_so_far, entry_price):
            continue

        # ── Conviction-based sizing (gap% + RVOL scoring; catalyst N/A historically) ──
        conv_pts = 0
        if gap_pct >= OPEN_CONVICTION_GAP_STRONG:      conv_pts += 1
        if gap_pct >= OPEN_CONVICTION_GAP_EXCEPTIONAL:  conv_pts += 1
        if rvol    >= OPEN_CONVICTION_RVOL_STRONG:      conv_pts += 1
        if rvol    >= OPEN_CONVICTION_RVOL_EXCEPTIONAL:  conv_pts += 1
        # catalyst quality point omitted — historical news data unavailable
        if conv_pts >= 4:
            conv_mult, conv_tier = OPEN_CONVICTION_EXCEPTIONAL_MULT, "EXCEPTIONAL"
        elif conv_pts >= 2:
            conv_mult, conv_tier = OPEN_CONVICTION_STRONG_MULT,      "STRONG"
        else:
            conv_mult, conv_tier = OPEN_CONVICTION_STANDARD_MULT,    "STANDARD"

        # Ross-true skip-the-bad-setup adjustment: when 0 of 3 entry gates pass
        # (MACD bearish AND price below VWAP AND flag not near 9 EMA), halve
        # the conviction multiplier. Conservative pending 1-month live revisit
        # (data sample n=13–15 too thin to outright reject — see changelog).
        if ENTRY_GATES_MODE == "conviction":
            gate_size_mult = ross_gate_size_multiplier(gates_passed)
            conv_mult *= gate_size_mult
            if gate_size_mult < 1.0:
                conv_tier += f" → ROSS-HALF ({gates_passed}/3 gates)"
        conv_tranche = TRANCHE_1_PCT * conv_mult

        sizing = calculate_entry(entry_price, stop_ref, conv_tranche, 0.0)
        if not sizing:
            break

        sim_out = None  # for scaleouts; separate from `sim` (scaleins)
        if SCALEOUTS_ENABLED:
            sim_out = _simulate_bracket_with_scaleouts(
                entry_price     = entry_price,
                initial_stop    = sizing["stop_price"],
                initial_shares  = sizing["shares"],
                risk_per_sh     = sizing["risk_per_sh"],
                bars            = today_bars[entry_idx:],
                day             = day,
            )
            t1_outcome_raw = sim_out["final_outcome"]    # STOP/TRAIL/FULL/EOD
            exit_price     = sim_out["final_exit"]
            pnl            = sim_out["total_pnl"]
            r_mult         = sim_out["blended_r"]
            sim = None
            if t1_outcome_raw == "STOP" and sim_out["tiers_fired"] == 0:
                outcome = "LOSS"
            elif pnl > 0:
                outcome = "WIN"
            elif pnl < 0:
                outcome = "LOSS"
            else:
                outcome = "EOD"
        elif SCALEINS_ENABLED:
            sim = _simulate_bracket_with_scaleins(
                entry_price     = entry_price,
                t1_stop         = sizing["stop_price"],
                t1_target       = sizing["take_profit"],
                t1_shares       = sizing["shares"],
                t1_risk_per_sh  = sizing["risk_per_sh"],
                flag_low        = pattern["flag_low"],
                flag_high       = pattern["flag_high"],
                bars            = today_bars[entry_idx:],
                day             = day,
            )
            t1_outcome_raw = sim["t1_outcome"]   # STOP / TRAIL / EOD
            exit_price = sim["t1_exit"]
            pnl        = sim["total_pnl"]
            r_mult     = sim["blended_r"]
            # Map granular scale-in outcome to legacy WIN/LOSS/EOD so the
            # downstream report formatter and aggregations stay compatible.
            # In scale-ins mode T1's +3R target is cancelled at +1R, so there
            # is no "limit-fill WIN" — wins materialize as profitable trails
            # or profitable EODs (with T2/T3 contribution included).
            if t1_outcome_raw == "STOP":
                outcome = "LOSS"
            elif pnl > 0:
                outcome = "WIN"
            elif pnl < 0:
                outcome = "LOSS"
            else:
                outcome = "EOD"
        else:
            outcome, exit_price = _simulate_bracket(
                entry_price, sizing["stop_price"], sizing["take_profit"],
                today_bars[entry_idx:], eod_utc,
            )
            pnl    = round((exit_price - entry_price) * sizing["shares"], 2)
            r_mult = round((exit_price - entry_price) / sizing["risk_per_sh"], 2) \
                     if sizing["risk_per_sh"] else 0.0
            sim = None
            t1_outcome_raw = outcome

        # Entry time offset from market open (minutes)
        t = entry_bar["t"][11:16]   # "HH:MM" in UTC
        hh, mm = int(t[:2]), int(t[3:])
        entry_offset_mins = hh * 60 + mm - _market_open_mins_utc(day)

        stop_distance_pct = round(
            (entry_price - sizing["stop_price"]) / entry_price * 100, 2
        ) if entry_price else 0.0

        trade = {
            "date":               day_str,
            "symbol":             symbol,
            "pattern":            "bull_flag" if pattern["volume_contracting"] else "breakout",
            "is_runner":          is_runner,
            "run_days":           run_days,
            "gap_pct":            round(gap_pct, 2),
            "rvol":               round(rvol, 2),
            "float_shares":       int(float_shares),
            "resistance":         resistance,
            "float_verified":     float_verified,
            "entry_time":         _utc_hhmm_to_et_str(day, t),
            "entry_offset_mins":  entry_offset_mins,
            "entry":              round(entry_price, 2),
            "stop":               round(sizing["stop_price"], 2),
            "target":             round(sizing["take_profit"], 2),
            "stop_distance_pct":  stop_distance_pct,
            "exit":               round(exit_price, 2),
            "shares":             sizing["shares"],
            "outcome":            outcome,
            "pnl":                pnl,
            "r_mult":             r_mult,
            "conviction_tier":    conv_tier,
            "conviction_mult":    conv_mult,
            "conviction_pts":     conv_pts,
            # News catalyst fields (populated when --news flag is used; defaults otherwise)
            "has_catalyst":       has_catalyst,
            "news_quality":       news_quality,
            "news_negative":      news_negative,
            # Scale-in mode flag + per-tranche detail (zero/empty in T1-only mode)
            "scaleins":           SCALEINS_ENABLED,
            "scaleouts":          SCALEOUTS_ENABLED,
            "t1_outcome_raw":     t1_outcome_raw,    # STOP/TRAIL/EOD in scale-ins mode; STOP/TRAIL/FULL/EOD in scale-outs
            "t1_pnl":             sim["t1_pnl"]     if sim else pnl,
            "t1_candle_signal":   sim.get("t1_candle_signal", "") if sim else "",
            "gates_mode":         ENTRY_GATES_MODE,
            "gates_reason":       gates_reason,
            "gates_passed":       gates_passed,
            "gate_macd_ok":       gate_macd_ok,
            "gate_ema_ok":        gate_ema_ok,
            "gate_vwap_ok":       gate_vwap_ok,
            # Scale-out specifics (zero/empty in legacy and scale-ins modes)
            "tiers_fired":        sim_out["tiers_fired"]     if sim_out else 0,
            "tier_pnl_sum":       sim_out["tier_pnl"]         if sim_out else 0.0,
            "runner_outcome":     sim_out["final_outcome"]    if sim_out else "",
            "runner_exit":        sim_out["final_exit"]       if sim_out else 0.0,
            "runner_shares":      sim_out["final_shares"]     if sim_out else 0,
            "runner_pnl":         sim_out["final_pnl"]        if sim_out else 0.0,
            "t2_filled":          sim["t2_filled"]  if sim else False,
            "t2_entry":           sim["t2_entry"]   if sim else 0.0,
            "t2_shares":          sim["t2_shares"]  if sim else 0,
            "t2_outcome":         sim["t2_outcome"] if sim else "",
            "t2_exit":            sim["t2_exit"]    if sim else 0.0,
            "t2_pnl":             sim["t2_pnl"]     if sim else 0.0,
            "t2_candle_signal":   sim.get("t2_candle_signal", "") if sim else "",
            "t3_filled":          sim["t3_filled"]  if sim else False,
            "t3_entry":           sim["t3_entry"]   if sim else 0.0,
            "t3_shares":          sim["t3_shares"]  if sim else 0,
            "t3_outcome":         sim["t3_outcome"] if sim else "",
            "t3_exit":            sim["t3_exit"]    if sim else 0.0,
            "t3_pnl":             sim["t3_pnl"]     if sim else 0.0,
        }
        return trade


# ── Simulate one SHORT candidate on one day ──────────────────────────────────

def _calculate_short_entry(
    entry_price:    float,
    flag_high:      float,         # the breakdown pattern's flag_high (above entry)
    tranche_pct:    float,
    daily_loss_used: float,
) -> Optional[dict]:
    """
    Position sizing for a short. Mirrors gap_trader.calculate_entry() but
    inverted: stop is ABOVE entry, take-profit is BELOW entry.

      risk_per_share  = stop_price - entry_price   (always positive)
      stop_price      = flag_high × 1.005          (small buffer above pattern high)
      take_profit     = entry_price - RR × risk_per_share
      shares          = min(notional × MAX_RISK_PCT / risk_per_share,
                            remaining_daily_budget / risk_per_share)

    Returns None if the math doesn't work out (zero risk, exhausted budget).
    """
    if entry_price <= 0 or flag_high <= entry_price:
        return None
    stop_price     = flag_high * 1.005
    risk_per_sh    = stop_price - entry_price
    if risk_per_sh <= 0:
        return None
    take_profit    = entry_price - SHORT_RR_RATIO * risk_per_sh
    if take_profit <= 0:
        return None

    notional       = GAP_NOTIONAL * tranche_pct
    max_loss_usd   = notional * SHORT_MAX_RISK_PCT
    remaining_usd  = max(0.0, DAILY_MAX_LOSS - daily_loss_used)
    shares_by_size = int(max_loss_usd / risk_per_sh) if risk_per_sh > 0 else 0
    shares_by_day  = int(remaining_usd / risk_per_sh) if risk_per_sh > 0 else 0
    shares = min(shares_by_size, shares_by_day)
    if shares < 1:
        return None

    return {
        "shares":      shares,
        "stop_price":  round(stop_price, 4),
        "take_profit": round(take_profit, 4),
        "risk_per_sh": round(risk_per_sh, 4),
        "max_loss":    round(shares * risk_per_sh, 2),
        "rr_ratio":    SHORT_RR_RATIO,
        "notional":    round(shares * entry_price, 2),
    }


def simulate_short_candidate(
    symbol:         str,
    day:            date,
    prev_close:     float,
    bars_1min:      list[dict],
    avg_vol:        float,
    hist_df,
    gap_pct:        float,         # NEGATIVE for shorts (e.g. -18.5)
    rvol:           float,
    float_shares:   int,
    resistance:     bool,
    float_verified: bool = True,
    has_catalyst:   bool = False,
    news_quality:   int  = 0,
    news_negative:  bool = False,
) -> Optional[dict]:
    """
    Simulate one short setup. Mirrors simulate_candidate() with inverted logic.
    """
    day_str        = day.isoformat()
    open_utc       = day_str + _et_utc(day, 9,  30)
    # Entry window extended to EOD-1min on 2026-05-15 to match longs (and the
    # session-agnostic principle). Shorts had their own SHORT_TIME_STOP that
    # capped the HOLD window separately; that's unchanged below.
    close_utc      = day_str + _et_utc(day, 15, 54)
    eod_utc        = day_str + _et_utc(day, 15, 55)
    mon_open_utc   = day_str + _et_utc(day, 9,  45)
    time_stop_utc  = day_str + _et_utc(day, *SHORT_TIME_STOP_HHMM)

    # Pre-loop entry quality gates (negated for shorts)
    if SHORT_GAP_ENTRY_MIN_PCT and gap_pct > -SHORT_GAP_ENTRY_MIN_PCT:
        return None                                 # not down enough
    if SHORT_RVOL_ENTRY_MIN and rvol < SHORT_RVOL_ENTRY_MIN:
        return None
    # Float band — small floats are squeeze candidates; very large floats lack volatility
    if float_verified and not (SHORT_FLOAT_MIN <= float_shares <= SHORT_FLOAT_MAX):
        return None

    # Multi-day-runner skip: a stock that's been DOWNTRENDING for days is
    # actually GOOD for shorts (continuation), so we don't apply SKIP_RUNNERS here.
    is_runner, run_days = check_multi_day_runner(hist_df, avg_vol) \
        if hist_df is not None and not hist_df.empty else (False, 0)

    today_bars = [b for b in bars_1min if b["t"][:10] == day_str]
    if not today_bars:
        return None

    _min_open_et = datetime(day.year, day.month, day.day, 9, 30, tzinfo=EASTERN) \
                   + timedelta(minutes=MIN_ENTRY_OFFSET_MINS)
    min_offset_utc = day_str + _min_open_et.astimezone(timezone.utc).strftime("T%H:%M:%SZ")

    min_needed = POLE_BARS + FLAG_BARS_MIN + 1

    for i in range(min_needed - 1, len(today_bars)):
        bar = today_bars[i]
        bar_time = bar["t"]

        if bar_time < open_utc or bar_time > close_utc:
            continue
        if day.weekday() == 0 and bar_time < mon_open_utc:
            continue
        if bar_time < min_offset_utc:
            continue

        bars_so_far = today_bars[:i + 1]

        pattern = _detect_bear_flag_hist(bars_so_far)
        if not pattern:
            pattern = _detect_breakdown_hist(bars_so_far, prev_close)
        if not pattern:
            continue

        if i + 1 >= len(today_bars):
            break
        entry_bar = today_bars[i + 1]
        if entry_bar["t"] > close_utc:
            break

        # Sell-side slippage on a market sell-short: fills BELOW the open
        # (we wanted to sell at the bid; market move against us at the open).
        entry_price = entry_bar["o"] * (1.0 - EQUITY_SLIPPAGE_PCT)
        if not (PRICE_MIN <= entry_price <= PRICE_MAX):
            break

        sizing = _calculate_short_entry(
            entry_price, pattern["flag_high"],
            SHORT_TRANCHE_1_PCT, daily_loss_used=0.0,
        )
        if not sizing:
            break

        outcome, exit_price = _simulate_bracket_short(
            entry_price, sizing["stop_price"], sizing["take_profit"],
            today_bars[i + 1:], eod_utc, time_stop_utc=time_stop_utc,
        )

        # Short P&L: profit = entry - exit (we sold high, bought low to cover)
        pnl    = round((entry_price - exit_price) * sizing["shares"], 2)
        r_mult = round((entry_price - exit_price) / sizing["risk_per_sh"], 2) \
                 if sizing["risk_per_sh"] else 0.0

        t = entry_bar["t"][11:16]
        hh, mm = int(t[:2]), int(t[3:])
        entry_offset_mins = hh * 60 + mm - _market_open_mins_utc(day)

        stop_distance_pct = round(
            (sizing["stop_price"] - entry_price) / entry_price * 100, 2
        ) if entry_price else 0.0

        return {
            "date":               day_str,
            "symbol":             symbol,
            "direction":          "short",
            "pattern":            "bear_flag" if pattern["volume_contracting"] else "breakdown",
            "is_runner":          is_runner,
            "run_days":           run_days,
            "gap_pct":            round(gap_pct, 2),
            "rvol":               round(rvol, 2),
            "float_shares":       int(float_shares),
            "resistance":         resistance,
            "float_verified":     float_verified,
            "entry_time":         _utc_hhmm_to_et_str(day, t),
            "entry_offset_mins":  entry_offset_mins,
            "entry":              round(entry_price, 2),
            "stop":               round(sizing["stop_price"], 2),
            "target":             round(sizing["take_profit"], 2),
            "stop_distance_pct":  stop_distance_pct,
            "exit":               round(exit_price, 2),
            "shares":             sizing["shares"],
            "outcome":            outcome,
            "pnl":                pnl,
            "r_mult":             r_mult,
            "conviction_tier":    "SHORT_STD",
            "conviction_mult":    1.0,
            "conviction_pts":     0,
            "has_catalyst":       has_catalyst,
            "news_quality":       news_quality,
            "news_negative":      news_negative,
        }

    return None

    return None


# ── Pre-market spike simulation ───────────────────────────────────────────────

def simulate_premarket_candidate(
    symbol:         str,
    day:            date,
    prev_close:     float,
    bars_1min:      list[dict],   # must include pre-market bars (T10:45Z+)
    avg_vol:        float,        # 30-day avg daily volume from Alpaca IEX bars
    hist_df,
    gap_pct:        float,
    rvol:           float,
    float_shares:   int,
    resistance:     bool,
    float_verified: bool = True,
    has_catalyst:   bool = False,
    news_quality:   int  = 0,
    news_negative:  bool = False,
) -> Optional[dict]:
    """
    Scan pre-market bars (6:45–9:20 AM ET) for a news-catalyst RVOL spike.

    Strategy: press releases drop at 7:30 / 8:00 / 8:30 AM ET. When one hits,
    a single 1-min bar trades a multiple of the normal per-minute rate. We enter
    on the NEXT bar via a limit order (ask + PM_LIMIT_SLIP), place a stop at the
    pre-market session low, and carry the bracket through the regular session.

    Spike criteria (both must hold):
      1. bar_rvol_equiv ≥ PM_SPIKE_RVOL_EQUIV  (single bar ≥ 5× avg per-min rate)
      2. current price ≥ prior close × (1 + PM_GAP_AT_ENTRY_MIN/100)

    Only the FIRST qualifying spike is taken per symbol per day.
    """
    from config import PM_RVOL_MIN, PM_FLOAT_MAX

    # Hard-disable switch (2026-05-22). See PM_SPIKE_ENTRIES_ENABLED docstring.
    if not PM_SPIKE_ENTRIES_ENABLED:
        return None

    # ── Stock-level pre-market gates (match live run_premarket() criteria) ────
    # Gap threshold is enforced bar-by-bar below (current_gap >= PM_GAP_AT_ENTRY_MIN)
    if rvol < PM_RVOL_MIN:          # daily RVOL must be ≥ 5× (same as live)
        return None
    if float_shares and float_shares > PM_FLOAT_MAX:  # float ≤ 20M (live: PM_FLOAT_MAX)
        return None

    day_str     = day.isoformat()
    scan_start  = day_str + _et_utc(day, 6, 45)   # 6:45 AM ET
    entry_close = day_str + _et_utc(day, 9, 20)   # 9:20 AM ET
    eod_utc     = day_str + _et_utc(day, 15, 55)  # 3:55 PM ET

    # Pre-market bars only (6:45–9:20 AM)
    pm_bars = [b for b in bars_1min
               if scan_start <= b["t"] <= entry_close]

    # If earliest bar is at/after market open the cache has no pre-market data
    if not pm_bars or pm_bars[0]["t"] >= day_str + _et_utc(day, 9, 30):
        return None

    avg_per_min = avg_vol / MINS_IN_SESSION  # normal per-minute volume rate
    if avg_per_min <= 0:
        return None

    # B.5 "wait for pattern after spike" reverted 2026-05-15: the bull_flag
    # math is too tight for small-cap PM bars; bull_flag rarely fires, and
    # when it does it catches FAILED breakouts rather than real continuation
    # setups. Empirical: B.5b 2-yr → 5.6% WR / -$9,221 / -1.03R (vs Group A
    # baseline 19% WR / -$4,897 / -0.34R). The "first spike wins" mechanic
    # below is structurally chasing the spike top per Ross's warning, but
    # occasionally catches the 3-4 setups per 2 years that rip straight up
    # with no pullback to form a pattern. Until a better-calibrated pattern
    # exists (FCMNH, looser flag, support-bounce, etc.), retain this entry.

    for i, bar in enumerate(pm_bars):
        # ── Spike check ───────────────────────────────────────────────────────
        bar_rvol_equiv = bar["v"] / avg_per_min
        if bar_rvol_equiv < PM_SPIKE_RVOL_EQUIV:
            continue

        # ── Gap check at this moment ──────────────────────────────────────────
        if bar["c"] <= 0 or prev_close <= 0:
            continue
        current_gap = (bar["c"] - prev_close) / prev_close * 100
        if current_gap < PM_GAP_AT_ENTRY_MIN:
            continue
        # EXPERIMENT 3 (2026-05-15): spike-time window 8:15-9:25 ET.
        # Empirical hypothesis — early-PM 08:00-08:14 spikes are pump-fades
        # (NUWE 08:01 -$636, QTTB 08:01 -$626 etc.). The latest-PM winner in
        # the sample (JTAI 2/14, 09:01 ET) supports late-window inclusion.
        spike_start_utc = day_str + _et_utc(day, 8, 15)
        spike_end_utc   = day_str + _et_utc(day, 9, 25)
        if not (spike_start_utc <= bar["t"] <= spike_end_utc):
            continue

        # ── Entry at next bar via limit order ─────────────────────────────────
        if i + 1 >= len(pm_bars):
            # No next bar to enter on. Bug-fix 2026-05-15: was `break`, which
            # skipped past the for-else and continued to the post-loop sizing
            # call with `pm_session_low` undefined → UnboundLocalError under
            # some bar sequences. `return None` is the correct exit since
            # there's no entry to simulate.
            return None
        entry_bar   = pm_bars[i + 1]
        entry_price = round(entry_bar["o"] * (1 + PM_LIMIT_SLIP), 2)

        # Ross 50%-retrace rule. PM bars only at this point — kept from Group A.
        if has_retraced_past_halfway(prev_close, pm_bars[:i + 1], entry_price):
            continue

        if not (PRICE_MIN <= entry_price <= PRICE_MAX):
            # Same bug-fix as above: `break` skipped past for-else with
            # `pm_session_low` undefined. Out-of-band price → no trade.
            return None

        # ── Stop = pre-market session low to this point ───────────────────────
        pm_session_low = min(b["l"] for b in pm_bars[:i + 1])

        pattern_kind = "pm_spike"
        break
    else:
        return None
    # Unique re-entry: only the FIRST qualifying spike per session.

    # ── Pre-market conviction sizing (gap% + RVOL; catalyst N/A historically) ──
    pm_pts = 0
    if current_gap >= 40.0: pm_pts += 1
    if current_gap >= 60.0: pm_pts += 1
    if rvol >= 10.0:         pm_pts += 1
    if rvol >= 20.0:         pm_pts += 1
    # catalyst quality point omitted — historical news data unavailable
    if pm_pts >= 4:
        pm_conv_mult, pm_conv_tier = PM_CONVICTION_EXCEPTIONAL_MULT, "EXCEPTIONAL"
    elif pm_pts >= 2:
        pm_conv_mult, pm_conv_tier = PM_CONVICTION_STRONG_MULT,      "STRONG"
    else:
        pm_conv_mult, pm_conv_tier = PM_CONVICTION_STANDARD_MULT,    "STANDARD"
    pm_conv_tranche = TRANCHE_1_PCT * pm_conv_mult

    sizing = calculate_entry(entry_price, pm_session_low, pm_conv_tranche, 0.0)
    if not sizing:
        return None

    # ── Walk forward from entry bar through EOD ───────────────────────────
    all_forward = [b for b in bars_1min if b["t"] >= entry_bar["t"]]
    outcome, exit_price = _simulate_bracket(
        entry_price, sizing["stop_price"], sizing["take_profit"],
        all_forward, eod_utc,
    )

    pnl    = round((exit_price - entry_price) * sizing["shares"], 2)
    r_mult = round((exit_price - entry_price) / sizing["risk_per_sh"], 2) \
             if sizing["risk_per_sh"] else 0.0

    is_runner, run_days = (False, 0)
    if hist_df is not None and not hist_df.empty:
        is_runner, run_days = check_multi_day_runner(hist_df, avg_vol)

    # Entry time in ET (respects DST)
    t_utc   = entry_bar["t"][11:16]
    hh, mm  = int(t_utc[:2]), int(t_utc[3:])
    et_str  = _utc_hhmm_to_et_str(day, t_utc)
    # entry_offset_mins: negative = pre-market (minutes before 9:30 open)
    entry_offset_mins = hh * 60 + mm - _market_open_mins_utc(day)

    stop_distance_pct = round(
        (entry_price - sizing["stop_price"]) / entry_price * 100, 2
    ) if entry_price else 0.0

    # Spike time for logging
    s_utc    = bar["t"][11:16]
    spike_et = _utc_hhmm_to_et_str(day, s_utc)

    return {
        "date":               day_str,
        "symbol":             symbol,
        "session":            "premarket",
        "pattern":            pattern_kind,    # "pm_flag" or "pm_breakout"
        "is_runner":          is_runner,
        "run_days":           run_days,
        "gap_pct":            round(current_gap, 2),
        "rvol":               round(rvol, 2),
        "pm_bar_rvol_equiv":  round(bar_rvol_equiv, 1),
        "spike_time":         spike_et,
        "float_shares":       int(float_shares),
        "float_verified":     float_verified,
        "resistance":         resistance,
        "entry_time":         et_str,
        "entry_offset_mins":  entry_offset_mins,
        "entry":              round(entry_price, 2),
        "stop":               round(sizing["stop_price"], 2),
        "target":             round(sizing["take_profit"], 2),
        "stop_distance_pct":  stop_distance_pct,
        "exit":               round(exit_price, 2),
        "shares":             sizing["shares"],
        "outcome":            outcome,
        "pnl":                pnl,
        "r_mult":             r_mult,
        "conviction_tier":    pm_conv_tier,
        "conviction_mult":    pm_conv_mult,
        "conviction_pts":     pm_pts,
        # News catalyst fields
        "has_catalyst":       has_catalyst,
        "news_quality":       news_quality,
        "news_negative":      news_negative,
    }


# ── Alpaca bars → pandas DataFrame (for runner detection) ────────────────────

def _bars_to_df(bars: list[dict], before_date: str) -> pd.DataFrame:
    """
    Convert Alpaca daily bar dicts to a pandas DataFrame compatible with
    check_multi_day_runner (expects High, Low, Close, Volume columns).
    Only includes bars strictly before before_date so the runner check sees
    historical context, not the gap day itself.
    """
    prior = [b for b in bars if b["t"][:10] < before_date]
    if not prior:
        return pd.DataFrame()
    return pd.DataFrame({
        "High":   [b["h"] for b in prior],
        "Low":    [b["l"] for b in prior],
        "Close":  [b["c"] for b in prior],
        "Volume": [b["v"] for b in prior],
    })


# ── Float shares — the only thing we still need yfinance for ─────────────────

def _get_float_shares(symbol: str, cache_dir: Path, refresh_yf: bool) -> Optional[int]:
    """
    Fetch float shares from yfinance. Cached per symbol with a 7-day TTL.
    This is the only yfinance call in the enrichment path — RVOL, resistance,
    and runner detection all now use the Alpaca daily bars already cached.
    """
    yf_path   = _cache_path(cache_dir, "yf", symbol)
    if not refresh_yf and not _cache_stale(yf_path, YF_CACHE_TTL_DAYS):
        cached = _load_cache(yf_path)
        if cached is not None:
            return cached.get("float_shares")

    try:
        info         = yf.Ticker(symbol).info
        float_shares = info.get("floatShares") or info.get("sharesOutstanding")
        if float_shares:
            _save_cache(yf_path, {"float_shares": int(float_shares)})
            return int(float_shares)
    except Exception:
        pass
    return None


# ── Enrich one candidate using cached Alpaca bars + yfinance float ────────────

def enrich_candidate(
    c: dict, day: date, hist_bars: list[dict], cache_dir: Path, refresh_yf: bool,
    day_news: Optional[dict] = None,   # {symbol: [headline,...]} — pre-fetched for the day
    direction: str = "long",           # "long" applies FLOAT_MAX; "short" applies SHORT band
) -> Optional[dict]:
    """
    Apply float, RVOL, and resistance filters.

    Architecture change: RVOL and resistance now use the Alpaca daily bars
    that are already fully cached, so this function is no longer bottlenecked
    by yfinance rate limits or the 60-day history window. yfinance is called
    only for float shares (a single .info lookup, not a full history fetch).

    RVOL uses IEX-feed volume consistently in both numerator and denominator,
    so the ratio is accurate regardless of the absolute capture rate.
    """
    symbol  = c["symbol"]
    day_str = day.isoformat()

    # ── RVOL from Alpaca bars (IEX, but ratio is consistent) ─────────────────
    prior_bars = [b for b in hist_bars if b["t"][:10] < day_str]
    today_bars = [b for b in hist_bars if b["t"][:10] == day_str]

    if not prior_bars or not today_bars:
        return None

    prior_vols = [b["v"] for b in prior_bars[-30:]]
    if len(prior_vols) < 5:
        return None

    avg_vol   = sum(prior_vols) / len(prior_vols)
    today_vol = today_bars[0]["v"]

    if avg_vol <= 0:
        return None

    if today_vol * c["price"] < MIN_DOLLAR_VOLUME:
        return None

    rvol = today_vol / avg_vol
    if rvol < RVOL_MIN:
        return None

    # ── Resistance from Alpaca bars ───────────────────────────────────────────
    recent_highs = [b["h"] for b in prior_bars[-RESISTANCE_WINDOW:]]
    resistance   = any(
        c["price"] < h <= c["price"] * (1 + RESISTANCE_ZONE)
        for h in recent_highs
    )

    # ── Float shares from yfinance (only remaining yfinance dependency) ───────
    # Fail open: if yfinance is rate-limited or unavailable, proceed without
    # the float filter rather than silently dropping the candidate. Trades with
    # unverified float are flagged in the output.
    float_shares = _get_float_shares(symbol, cache_dir, refresh_yf)
    if float_shares is not None:
        if direction == "long":
            # Longs: tight float (≤ 10M) for momentum continuation
            if float_shares > FLOAT_MAX:
                return None
        else:
            # Shorts: float band (5M-50M) — avoid squeeze candidates AND lethargic large-caps
            if not (SHORT_FLOAT_MIN <= float_shares <= SHORT_FLOAT_MAX):
                return None

    # ── Build hist_df for runner detection from Alpaca bars ──────────────────
    hist_df = _bars_to_df(hist_bars, day_str)

    # News catalyst scoring (only populated when --news flag is used).
    # Uses gap_filters.score_catalyst_quality — same scorer as live.
    # Tier mapping: 0=none, 1=red flag, 3=unclassified, 6=moderate, 9=strong.
    symbol     = c["symbol"]
    headlines  = (day_news or {}).get(symbol, [])
    news_score, _reason = score_catalyst_quality(headlines)
    news_negative        = news_score == 1                         # red-flag tier
    has_catalyst         = news_score >= 3                         # at least unclassified news

    return {
        **c,
        "float_shares":    float_shares or 0,   # 0 = unverified (yfinance unavailable)
        "float_verified":  float_shares is not None,
        "avg_vol":         int(avg_vol),
        "today_vol":       today_vol,
        "rvol":            round(rvol, 2),
        "resistance":      resistance,
        "hist_df":         hist_df,
        "has_catalyst":    has_catalyst,
        "news_quality":    news_score,
        "news_negative":   news_negative,
        "news_headlines":  headlines,
    }


# ── Fetch / cache 1-min bars ──────────────────────────────────────────────────

def get_1min_bars(
    symbol: str, day: date, cache_dir: Path, refresh: bool,
    include_premarket: bool = False,
) -> list[dict]:
    """
    Fetch 1-min bars for a symbol on a given day.

    include_premarket=True fetches from 6:45 AM ET (T10:45Z) to capture
    pre-market RVOL spikes. These are cached with a '_pm' suffix so existing
    regular-session caches (fetched from T13:00Z) are not invalidated.
    """
    day_str   = day.isoformat()
    suffix    = "_pm" if include_premarket else ""
    path      = _cache_path(cache_dir, "1min", f"{symbol}_{day_str}{suffix}")

    if not refresh:
        cached = _load_cache(path)
        if cached is not None:
            return cached

    fetch_start = _et_utc(day, 6, 45) if include_premarket else _et_utc(day, 8, 30)
    fetch_end   = _et_utc(day, 17, 0)   # 5:00 PM ET — well past close, covers extended hours
    bars = alpaca.get_bars(
        symbol,
        timeframe="1Min",
        start=day_str + fetch_start,
        end=day_str + fetch_end,
    )
    _save_cache(path, bars)
    return bars


# ── Main backtest loop ────────────────────────────────────────────────────────

def run_backtest(
    start:             date,
    end:               date,
    top_n:             int  = 20,
    cache_dir:         Path = Path("state/cache"),
    refresh:           bool = False,
    refresh_yf:        bool = False,
    include_premarket: bool = True,    # PREMARKET IS PART OF THE STRATEGY — see
                                       # feedback_premarket_strategy.md. Setting
                                       # this to False silently drops the entire
                                       # PM entry leg that gap_trader.run_premarket
                                       # runs at 4:05 AM ET live. Opt OUT only.
    fetch_news:        bool = False,   # attach Alpaca news catalyst data to each trade
    require_catalyst:  bool = False,   # skip entries where has_catalyst=False (needs fetch_news)
    direction:         str  = "long",  # "long" or "short" (gap-down breakdown shorts)
) -> list[dict]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    days = trading_days_in_range(start, end)
    print(f"\nBacktest range: {start} → {end}  ({len(days)} trading day(s))")

    # ── Step 1: Universe ──────────────────────────────────────────────────────
    print("Fetching symbol universe …", end=" ", flush=True)
    symbols = [
        a["symbol"] for a in alpaca.get_assets()
        if a.get("tradable")
        and a.get("exchange") in ("NYSE", "NASDAQ", "AMEX", "ARCA", "BATS")
        and not a.get("symbol", "").endswith((".", "/", "W", "R", "P"))
    ]
    print(f"{len(symbols)} symbols")

    # ── Step 2: Daily bars (cached) ───────────────────────────────────────────
    bar_start    = (start - timedelta(days=LOOKBACK_DAYS)).isoformat()
    bar_end      = end.isoformat()
    daily_cache  = _cache_path(cache_dir, f"daily_{bar_start}_{bar_end}")

    daily_bars: dict[str, list[dict]] = {}
    if not refresh and not _cache_stale(daily_cache, ttl_days=9999):
        print("Loading daily bars from cache …", end=" ", flush=True)
        daily_bars = _load_cache(daily_cache) or {}
        if daily_bars:
            print(f"{len(daily_bars)} symbols loaded")
        else:
            print("cache miss — fetching")

    if not daily_bars:
        print(
            f"Fetching daily bars {bar_start} → {bar_end} "
            f"for {len(symbols)} symbols …",
            flush=True,
        )
        daily_bars = alpaca.get_multi_stock_daily_bars(symbols, bar_start, bar_end)
        print(f"  Got daily bars for {len(daily_bars)} symbols — saving to cache")
        _save_cache(daily_cache, daily_bars)

    all_trades: list[dict] = []

    # ── Step 3: Process each trading day ──────────────────────────────────────
    for day in days:
        day_str  = day.isoformat()
        day_name = day.strftime("%A %b %d")
        print(f"\n{'─'*60}")
        print(f"  {day_name}")
        print(f"{'─'*60}")

        # SPY regime filter
        spy_hist  = daily_bars.get("SPY", [])
        spy_today = [b for b in spy_hist if b["t"][:10] == day_str]
        spy_prev  = [b for b in spy_hist if b["t"][:10] < day_str]
        if spy_today and spy_prev:
            spy_open       = spy_today[0]["o"]
            spy_prev_close = spy_prev[-1]["c"]
            spy_chg        = (spy_open - spy_prev_close) / spy_prev_close
            if spy_chg < SPY_DOWN_THRESHOLD:
                print(f"  SPY regime filter: SPY {spy_chg:+.2%} — day SKIPPED")
                continue
            else:
                print(f"  SPY regime: {spy_chg:+.2%} — entries enabled")
        else:
            print(f"  SPY regime: no data — proceeding (fail open)")

        # Gap screening
        import os as _os
        _nogap        = _os.getenv("BT_NOGAP_ACTIVITY") == "1"
        _act_rvol_min = float(_os.getenv("BT_ACTIVITY_RVOL_MIN") or 3.0)
        candidates = []
        for symbol, bars in daily_bars.items():
            day_bars  = [b for b in bars if b["t"][:10] == day_str]
            prev_bars = [b for b in bars if b["t"][:10] < day_str]
            if not day_bars or not prev_bars:
                continue
            day_bar    = day_bars[0]
            prev_bar   = prev_bars[-1]
            open_price = day_bar["o"]
            prev_close = prev_bar["c"]
            if not prev_close or prev_close <= 0:
                continue
            # ── No-gap ACTIVITY screen (BT_NOGAP_ACTIVITY=1) ───────────────────
            # Drop the gap requirement entirely. Admit any in-range name whose
            # daily volume is unusually high vs its own 30d norm (daily RVOL ≥
            # BT_ACTIVITY_RVOL_MIN) — i.e. "volume showed up here today,"
            # gapped or not. The causal intraday acceleration signal then picks
            # WHEN/WHICH to trade. Same residual look-ahead caveat as the
            # intraday-gap screen (full-day volume used for universe selection;
            # entry timing/ranking remain causal).
            if _nogap:
                _pv = [b["v"] for b in prev_bars[-30:]]
                _avg = (sum(_pv) / len(_pv)) if _pv else 0.0
                _drvol = (day_bar["v"] / _avg) if _avg > 0 else 0.0
                _in_rng = (day_bar["l"] <= PRICE_MAX and day_bar["h"] >= PRICE_MIN)
                if not _in_rng or _drvol < _act_rvol_min:
                    continue
                candidates.append({
                    "symbol":     symbol,
                    "price":      round(open_price, 4),
                    "prev_close": round(prev_close, 4),
                    "gap_pct":    round((day_bar["h"] - prev_close) / prev_close * 100, 2),
                    "today_vol":  int(day_bar["v"]),
                    "daily_rvol": round(_drvol, 2),
                })
                continue
            # ── Intraday-aware screen (BT_INTRADAY_GAP=1) ──────────────────────
            # Parity fix: the live scanner fires on intraday/PM RVOL spikes, not the
            # daily OPEN gap. Track 1b showed the daily-open screen misses 42% of
            # live setups. When enabled, qualify on the intraday HIGH spike vs prev
            # close (LOW for shorts) and accept any name whose intraday range overlaps
            # $PRICE_MIN..$PRICE_MAX. The entry/exit simulation downstream is UNCHANGED
            # — it remains the real causal bot logic; only the candidate set widens.
            # CAVEAT: selecting on the realized day high introduces a mild residual
            # look-ahead (a name that spikes at 2pm could receive a morning entry in
            # the sim). Bounded because entries are real per-bar breakouts, but noted.
            import os as _os
            if _os.getenv("BT_INTRADAY_GAP") == "1":
                ref_price = day_bar["h"] if direction == "long" else day_bar["l"]
                in_range  = (day_bar["l"] <= PRICE_MAX and day_bar["h"] >= PRICE_MIN)
            else:
                ref_price = open_price
                in_range  = (PRICE_MIN <= open_price <= PRICE_MAX)
            if not in_range:
                continue
            gap_pct = (ref_price - prev_close) / prev_close * 100
            # Direction-aware filter: longs need positive gap, shorts need negative gap.
            if direction == "long":
                if gap_pct < GAP_MIN_PCT:
                    continue
            else:                                    # short
                if gap_pct > -GAP_MIN_PCT:
                    continue
            candidates.append({
                "symbol":     symbol,
                "price":      round(open_price, 4),
                "prev_close": round(prev_close, 4),
                "gap_pct":    round(gap_pct, 2),
                "today_vol":  int(day_bar["v"]),
            })

        # Sort: no-gap mode → most active (daily RVOL) first; else largest gap.
        if _nogap:
            candidates.sort(key=lambda x: x.get("daily_rvol", 0), reverse=True)
            print(f"  Activity screen: {len(candidates)} candidates with daily RVOL ≥ {_act_rvol_min}×")
        else:
            candidates.sort(key=lambda x: abs(x["gap_pct"]), reverse=True)
            if direction == "long":
                print(f"  Gap screen: {len(candidates)} candidates gapped ≥+{GAP_MIN_PCT}%")
            else:
                print(f"  Gap screen: {len(candidates)} candidates gapped ≤-{GAP_MIN_PCT}%")
        if not candidates:
            continue

        # Optional: fetch news for all pool candidates in one batch API call
        day_news: dict[str, list[str]] = {}
        pool_input = candidates[:top_n * 4]
        if fetch_news:
            pool_syms = [c["symbol"] for c in pool_input]
            print(
                f"  Fetching news for {len(pool_syms)} symbols …",
                end=" ", flush=True,
            )
            day_news = _fetch_day_news(pool_syms, day, cache_dir, refresh)
            hit_count = sum(1 for s in pool_syms if s in day_news)
            print(f"{hit_count}/{len(pool_syms)} have headlines")

        # Enrich via yfinance (parallel, capped at top_n × 4)
        enriched   = []
        print(
            f"  Enriching top {len(pool_input)} (float/RVOL/resistance) …",
            end=" ", flush=True,
        )
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {
                pool.submit(
                    enrich_candidate, c, day,
                    daily_bars.get(c["symbol"], []),
                    cache_dir, refresh_yf,
                    day_news if fetch_news else None,
                    direction,
                ): c["symbol"]
                for c in pool_input
            }
            for fut in as_completed(futures):
                result = fut.result()
                if result:
                    enriched.append(result)

        # Ranking: BT_RANK_RVOL=1 → highest relative volume first (the "obvious"
        # stock — most eyes, cleanest action). Otherwise [ROSS-A+ EXP 2026-06-04]
        # low-float-first, then high RVOL.
        if _os_pb.getenv("BT_RANK_RVOL") == "1":
            enriched.sort(key=lambda x: -x.get("rvol", 0))
        else:
            enriched.sort(key=lambda x: (x["float_shares"] if x.get("float_verified") else 9e18,
                                         -x.get("rvol", 0)))
        qualified = enriched[:top_n]
        print(f"{len(qualified)} qualified (taking top {top_n})")
        if not qualified:
            continue

        # Candidate table
        news_hdr  = "  News" if fetch_news else ""
        div_width = 58 if fetch_news else 52
        print(f"\n  {'Symbol':<8} {'Gap%':>6} {'Float':>9} {'RVOL':>6} "
              f"{'Resist':>7} {'Runner':>7}" + news_hdr)
        print(f"  {'─' * div_width}")
        for c in qualified:
            hist_df   = c.get("hist_df")
            is_runner, run_days = (False, 0)
            if hist_df is not None and not hist_df.empty:
                is_runner, run_days = check_multi_day_runner(hist_df, c["avg_vol"])
            runner_str = f"{run_days}d" if is_runner else "—"
            float_str  = f"{c['float_shares']/1e6:.1f}M" if c.get("float_verified") else "?M"
            cat_flag   = ("  ★" if c.get("has_catalyst") else "  ·") if fetch_news else ""
            print(f"  {c['symbol']:<8} {c['gap_pct']:>5.1f}%  "
                  f"{float_str:>8}  {c['rvol']:>5.1f}×  "
                  f"{'YES' if c['resistance'] else 'no':>7}  {runner_str:>7}" + cat_flag)

        # Fetch 1-min bars and simulate
        print(f"\n  Simulating entries …")
        day_trades   = []
        pm_entered   = set()   # symbols that already have a pre-market entry

        # ── Dynamic-leader pre-pass (BT_DYN_LEADER) ───────────────────────────
        # Fetch every candidate's bars once and build a rolling intraday-RVOL
        # rank map so entries can be gated on live leadership (which rotates).
        bars_cache   = {}
        leader_ranks = {}
        if _DYN_LEADER:
            avgvol_by_sym = {}
            for c in qualified:
                _b = get_1min_bars(c["symbol"], day, cache_dir, refresh,
                                   include_premarket=include_premarket)
                if _b:
                    bars_cache[c["symbol"]]    = _b
                    avgvol_by_sym[c["symbol"]] = c.get("avg_vol", 1)
            leader_ranks = _build_leader_ranks(bars_cache, avgvol_by_sym, day.isoformat())

        for c in qualified:
            symbol  = c["symbol"]
            hist_df = c.get("hist_df")
            avg_vol = c.get("avg_vol", 1)

            bars_1min = bars_cache.get(symbol) or get_1min_bars(
                symbol, day, cache_dir, refresh,
                include_premarket=include_premarket,
            )
            if not bars_1min:
                print(f"    {symbol}: no 1-min bars — skipping")
                time.sleep(0.1)
                continue

            # News fields (from enrich step — already scored per candidate)
            c_has_cat  = c.get("has_catalyst",  False)
            c_news_q   = c.get("news_quality",  0)
            c_news_neg = c.get("news_negative", False)

            # If --require-catalyst is set, skip symbols with no news catalyst
            if require_catalyst and not c_has_cat:
                continue

            # ── Pre-market pass (if enabled) ──────────────────────────────────
            if include_premarket:
                pm_trade = simulate_premarket_candidate(
                    symbol, day, c["prev_close"], bars_1min, avg_vol, hist_df,
                    gap_pct=c["gap_pct"], rvol=c["rvol"],
                    float_shares=c["float_shares"], resistance=c["resistance"],
                    float_verified=c.get("float_verified", False),
                    has_catalyst=c_has_cat, news_quality=c_news_q, news_negative=c_news_neg,
                )
                if pm_trade:
                    pm_entered.add(symbol)
                    outcome_str = {
                        "WIN":  f"+${pm_trade['pnl']:,.0f}  ({pm_trade['r_mult']:+.1f}R)",
                        "LOSS": f"-${abs(pm_trade['pnl']):,.0f}  ({pm_trade['r_mult']:+.1f}R)",
                        "EOD":  f"${pm_trade['pnl']:+,.0f}  ({pm_trade['r_mult']:+.1f}R)  [EOD]",
                    }[pm_trade["outcome"]]
                    print(f"    {symbol}: PM_SPIKE @ {pm_trade['spike_time']}  "
                          f"(bar RVOL equiv {pm_trade['pm_bar_rvol_equiv']:.0f}×)  "
                          f"entry=${pm_trade['entry']:.2f}  stop=${pm_trade['stop']:.2f}  "
                          f"target=${pm_trade['target']:.2f}  {outcome_str}")
                    day_trades.append(pm_trade)

            # ── Regular session pass (skip if pre-market entry taken) ─────────
            if symbol in pm_entered:
                continue   # already in position — don't double-enter at open

            sim_fn = simulate_short_candidate if direction == "short" else simulate_candidate
            _extra = {"leader_rank": leader_ranks.get(symbol)} \
                if (_DYN_LEADER and direction != "short") else {}
            trade = sim_fn(
                symbol, day, c["prev_close"], bars_1min, avg_vol, hist_df,
                gap_pct=c["gap_pct"], rvol=c["rvol"],
                float_shares=c["float_shares"], resistance=c["resistance"],
                float_verified=c.get("float_verified", False),
                has_catalyst=c_has_cat, news_quality=c_news_q, news_negative=c_news_neg,
                **_extra,
            )

            if trade:
                outcome_str = {
                    "WIN":     f"+${trade['pnl']:,.0f}  ({trade['r_mult']:+.1f}R)",
                    "LOSS":    f"-${abs(trade['pnl']):,.0f}  ({trade['r_mult']:+.1f}R)",
                    "EOD":     f"${trade['pnl']:+,.0f}  ({trade['r_mult']:+.1f}R)  [EOD]",
                    "TIME":    f"${trade['pnl']:+,.0f}  ({trade['r_mult']:+.1f}R)  [TIME-STOP]",
                    "SQUEEZE": f"-${abs(trade['pnl']):,.0f}  ({trade['r_mult']:+.1f}R)  [SQUEEZE]",
                }[trade["outcome"]]
                runner_tag = " [MULTI-DAY]" if trade["is_runner"] else ""
                print(f"    {symbol}: {trade['pattern'].upper()}{runner_tag}  "
                      f"entry=${trade['entry']:.2f}  stop=${trade['stop']:.2f}  "
                      f"target=${trade['target']:.2f}  {outcome_str}")
                day_trades.append(trade)
            else:
                if not include_premarket:
                    print(f"    {symbol}: no pattern triggered in entry window")

            time.sleep(RATE_LIMIT_SLEEP)

        if day_trades:
            day_pnl = sum(t["pnl"] for t in day_trades)
            wins    = sum(1 for t in day_trades if t["outcome"] == "WIN")
            losses  = sum(1 for t in day_trades if t["outcome"] == "LOSS")
            eods    = sum(1 for t in day_trades if t["outcome"] == "EOD")
            print(f"\n  {day_name} total: ${day_pnl:+,.2f}  "
                  f"({wins}W / {losses}L / {eods} EOD)  [{len(day_trades)} trade(s)]")
        else:
            print(f"\n  {day_name}: no entries triggered")

        all_trades.extend(day_trades)

    return all_trades


# ── CSV export ────────────────────────────────────────────────────────────────

CSV_FIELDS = [
    "date", "symbol", "session", "pattern", "outcome", "pnl", "r_mult",
    "gap_pct", "rvol", "pm_bar_rvol_equiv", "spike_time",
    "float_shares", "float_verified", "resistance",
    "entry_offset_mins", "stop_distance_pct",
    "entry", "stop", "target", "exit", "shares",
    "is_runner", "run_days", "entry_time",
    "conviction_tier", "conviction_mult", "conviction_pts",
    "has_catalyst", "news_quality", "news_negative",
    "scaleins", "scaleouts", "t1_outcome_raw", "t1_pnl", "t1_candle_signal",
    "gates_mode", "gates_reason", "gates_passed",
    "gate_macd_ok", "gate_ema_ok", "gate_vwap_ok",
    "t2_filled", "t2_entry", "t2_shares", "t2_outcome", "t2_exit", "t2_pnl",
    "t2_candle_signal",
    "t3_filled", "t3_entry", "t3_shares", "t3_outcome", "t3_exit", "t3_pnl",
    "tiers_fired", "tier_pnl_sum",
    "runner_outcome", "runner_exit", "runner_shares", "runner_pnl",
]

def export_trades_csv(trades: list[dict], path: Path) -> None:
    if not trades:
        return
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(trades)
    print(f"\n  Trade log saved → {path}")


# ── Report ────────────────────────────────────────────────────────────────────

def _max_drawdown_usd(trades: list[dict]) -> float:
    """
    Max running drawdown in USD across the trade sequence (chronological).
    Returns a negative number (deepest equity dip from a running peak),
    or 0.0 if no trade loses ground from a peak.
    """
    if not trades:
        return 0.0
    chrono = sorted(trades, key=lambda t: (t.get("date", ""), t.get("symbol", "")))
    cum   = 0.0
    peak  = 0.0
    worst = 0.0
    for t in chrono:
        cum  += t.get("pnl", 0.0)
        peak  = max(peak, cum)
        worst = min(worst, cum - peak)
    return worst


def emit_summary_json(
    trades: list[dict], start: date, end: date, path: Path,
) -> None:
    """
    Write a structured backtest summary to `path`.
    Consumed by the /gap-backtest skill (Step 4 baseline diff) and
    tests/test_strategy_targets.py (Phase 3 iteration loop).
    """
    import json as _json

    if not trades:
        summary = {
            "start":          start.isoformat(),
            "end":            end.isoformat(),
            "generated_at":   datetime.now().isoformat(),
            "trades":         0,
            "win_rate":       0.0,
            "total_return":   0.0,
            "avg_r":          0.0,
            "max_drawdown":   0.0,
            "trades_per_week": 0.0,
            "pattern_split":  {},
            "outcome_split":  {},
        }
    else:
        from config import GAP_BUDGET as _GAP_BUDGET
        wins   = [t for t in trades if t.get("pnl", 0) > 0]
        weeks  = max((end - start).days / 7.0, 1.0)
        pat    = {}
        out    = {}
        for t in trades:
            pat[t.get("pattern", "?")] = pat.get(t.get("pattern", "?"), 0) + 1
            out[t.get("outcome", "?")] = out.get(t.get("outcome", "?"), 0) + 1

        total_return = sum(t.get("pnl", 0) for t in trades)
        mdd          = _max_drawdown_usd(trades)
        # MAR = annualized %-return / max-drawdown %-of-budget.
        # See CLAUDE.md KPI bar (gap trader: MAR ≥ 0.5). Cap to ±99.0 to
        # keep zero-DD / zero-return edges out of the JSON (and out of any
        # downstream test that does numeric comparisons).
        if _GAP_BUDGET > 0 and mdd < 0 and abs(mdd) >= 1.0:
            annual_pct = (total_return / _GAP_BUDGET) * (52.0 / weeks)
            dd_pct     = abs(mdd) / _GAP_BUDGET
            mar = annual_pct / dd_pct if dd_pct > 0 else 0.0
            mar = max(-99.0, min(99.0, mar))
        else:
            mar = 0.0

        summary = {
            "start":          start.isoformat(),
            "end":            end.isoformat(),
            "generated_at":   datetime.now().isoformat(),
            "trades":         len(trades),
            "win_rate":       round(len(wins) / len(trades), 4),
            "total_return":   round(total_return, 2),
            "avg_r":          round(sum(t.get("r_mult", 0) for t in trades) / len(trades), 3),
            "max_drawdown":   round(mdd, 2),
            "mar":            round(mar, 2),
            "trades_per_week": round(len(trades) / weeks, 2),
            "pattern_split":  pat,
            "outcome_split":  out,
        }

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        _json.dump(summary, f, indent=2)


def print_report(trades: list[dict], start: date, end: date):
    print(f"\n{'='*65}")
    print(f"  BACKTEST RESULTS  {start} → {end}")
    print(f"{'='*65}")

    if not trades:
        print("  No trades were triggered during this period.")
        return

    total_pnl  = sum(t["pnl"] for t in trades)
    # Use P&L sign rather than literal "WIN"/"LOSS" tag so short outcomes
    # (TIME, SQUEEZE) get counted on the appropriate side.
    wins       = [t for t in trades if t["pnl"] > 0]
    losses     = [t for t in trades if t["pnl"] < 0]
    eods       = [t for t in trades if t["outcome"] == "EOD"]
    times      = [t for t in trades if t["outcome"] == "TIME"]
    squeezes   = [t for t in trades if t["outcome"] == "SQUEEZE"]
    win_rate   = len(wins) / len(trades) * 100
    avg_r      = sum(t["r_mult"] for t in trades) / len(trades)
    avg_win_r  = sum(t["r_mult"] for t in wins)   / len(wins)   if wins   else 0
    avg_loss_r = sum(t["r_mult"] for t in losses) / len(losses) if losses else 0
    runners    = [t for t in trades if t["is_runner"]]
    runner_wins= [t for t in runners if t["pnl"] > 0]

    print(f"\n  Trades total     : {len(trades)}")
    extra_breakdown = ""
    if times:
        extra_breakdown += f"  /  {len(times)} TIME"
    if squeezes:
        extra_breakdown += f"  /  {len(squeezes)} SQUEEZE"
    print(f"  Wins / Losses    : {len(wins)} W  /  {len(losses)} L  /  {len(eods)} EOD"
          + extra_breakdown)
    print(f"  Win rate         : {win_rate:.0f}%")
    print(f"  Avg R-multiple   : {avg_r:+.2f}R  "
          f"(wins avg {avg_win_r:+.1f}R  /  losses avg {avg_loss_r:+.1f}R)")
    print(f"  Total P&L        : ${total_pnl:+,.2f}")
    print(f"\n  Multi-day runners: {len(runners)} trade(s)  "
          f"({len(runner_wins)}/{len(runners)} wins"
          f"{f'  — {len(runner_wins)/len(runners)*100:.0f}% win rate' if runners else ''})")

    # Per-day breakdown
    print(f"\n  {'─'*60}")
    print(f"  {'Date':<14} {'Trades':>7} {'Win%':>6} {'P&L':>10}  Symbols")
    print(f"  {'─'*60}")
    for day_str in sorted({t["date"] for t in trades}):
        day_trades = [t for t in trades if t["date"] == day_str]
        day_wins   = sum(1 for t in day_trades if t["outcome"] == "WIN")
        day_pnl    = sum(t["pnl"] for t in day_trades)
        day_winpct = day_wins / len(day_trades) * 100 if day_trades else 0
        syms       = ", ".join(t["symbol"] for t in day_trades)
        day_label  = datetime.strptime(day_str, "%Y-%m-%d").strftime("%a %b %d")
        print(f"  {day_label:<14} {len(day_trades):>7} {day_winpct:>5.0f}%  "
              f"${day_pnl:>+9,.0f}  {syms}")

    # Individual trade log
    print(f"\n  {'─'*60}")
    print(f"  {'Symbol':<7} {'Date':<12} {'Pattern':<12} {'Gap%':>5} "
          f"{'RVOL':>5} {'+Mins':>6} {'Entry':>7} {'Stop':>7} "
          f"{'Target':>8} {'Exit':>7} {'Outcome':<8} {'P&L':>8}  {'R':>5}")
    print(f"  {'─'*60}")
    for t in sorted(trades, key=lambda x: (x["date"], x["symbol"])):
        runner_mark = "*" if t["is_runner"] else " "
        print(f"  {t['symbol']:<7}{runner_mark}"
              f"{t['date']:<12} {t['pattern']:<12} "
              f"{t['gap_pct']:>4.0f}%  {t['rvol']:>4.0f}×  "
              f"{t['entry_offset_mins']:>5}m  "
              f"${t['entry']:>6.2f} ${t['stop']:>6.2f} ${t['target']:>7.2f} "
              f"${t['exit']:>6.2f} {t['outcome']:<8} "
              f"${t['pnl']:>+7,.0f}  {t['r_mult']:>+5.1f}R")

    if runners:
        print(f"\n  * = multi-day runner")

    # Session breakdown (pre-market vs regular)
    pm_trades  = [t for t in trades if t.get("session") == "premarket"]
    reg_trades = [t for t in trades if t.get("session") != "premarket"]
    if pm_trades:
        pm_wins = [t for t in pm_trades if t["outcome"] == "WIN"]
        pm_pnl  = sum(t["pnl"] for t in pm_trades)
        pm_avgr = sum(t["r_mult"] for t in pm_trades) / len(pm_trades)
        print(f"\n  Session breakdown:")
        print(f"    Pre-market : {len(pm_trades):>3} trades  "
              f"{len(pm_wins)}/{len(pm_trades)} wins "
              f"({len(pm_wins)/len(pm_trades)*100:.0f}%)  "
              f"avg {pm_avgr:+.2f}R  ${pm_pnl:+,.0f}")
        if reg_trades:
            rw  = [t for t in reg_trades if t["outcome"] == "WIN"]
            rp  = sum(t["pnl"] for t in reg_trades)
            rar = sum(t["r_mult"] for t in reg_trades) / len(reg_trades)
            print(f"    Regular    : {len(reg_trades):>3} trades  "
                  f"{len(rw)}/{len(reg_trades)} wins "
                  f"({len(rw)/len(reg_trades)*100:.0f}%)  "
                  f"avg {rar:+.2f}R  ${rp:+,.0f}")

    # Pattern breakdown
    flag_trades = [t for t in trades if t["pattern"] == "bull_flag"]
    bo_trades   = [t for t in trades if t["pattern"] == "breakout"]
    pm_spike_trades = [t for t in trades if t["pattern"] == "pm_spike"]
    if flag_trades:
        flag_wins = sum(1 for t in flag_trades if t["outcome"] == "WIN")
        flag_pnl  = sum(t["pnl"] for t in flag_trades)
        print(f"\n  Bull flag  : {len(flag_trades)} trades  "
              f"{flag_wins}/{len(flag_trades)} wins  ${flag_pnl:+,.0f} total P&L")
    if bo_trades:
        bo_wins = sum(1 for t in bo_trades if t["outcome"] == "WIN")
        bo_pnl  = sum(t["pnl"] for t in bo_trades)
        print(f"  Breakout   : {len(bo_trades)} trades  "
              f"{bo_wins}/{len(bo_trades)} wins  ${bo_pnl:+,.0f} total P&L")
    if pm_spike_trades:
        pm_wins = sum(1 for t in pm_spike_trades if t["outcome"] == "WIN")
        pm_pnl  = sum(t["pnl"] for t in pm_spike_trades)
        pm_avgr = sum(t["r_mult"] for t in pm_spike_trades) / len(pm_spike_trades)
        print(f"  PM spike   : {len(pm_spike_trades)} trades  "
              f"{pm_wins}/{len(pm_spike_trades)} wins  "
              f"avg {pm_avgr:+.2f}R  ${pm_pnl:+,.0f} total P&L")
        # Spike time breakdown
        print(f"\n  Pre-market spike time breakdown:")
        windows = [
            ("06:45–07:29", "T10:45", "T11:29"),
            ("07:30–07:59", "T11:30", "T11:59"),
            ("08:00–08:29", "T12:00", "T12:29"),
            ("08:30–08:59", "T12:30", "T12:59"),
            ("09:00–09:19", "T13:00", "T13:19"),
        ]
        for label, utc_lo, utc_hi in windows:
            wt = [t for t in pm_spike_trades
                  if utc_lo <= (t.get("spike_time", "")[:5].replace(":", "T0").replace("T0", "T")
                                if t.get("spike_time") else "") <= utc_hi
                  or True]  # fallback: just group by entry_offset
        # Simpler: group by spike_time hour (ET)
        for et_hour in ["06", "07", "08", "09"]:
            wt = [t for t in pm_spike_trades
                  if (t.get("spike_time") or "").startswith(et_hour)]
            if wt:
                ww  = sum(1 for t in wt if t["outcome"] == "WIN")
                wp  = sum(t["pnl"] for t in wt)
                war = sum(t["r_mult"] for t in wt) / len(wt)
                print(f"    {et_hour}:xx ET : {len(wt):>3} trades  "
                      f"{ww}/{len(wt)} wins ({ww/len(wt)*100:.0f}%)  "
                      f"avg {war:+.2f}R  ${wp:+,.0f}")

    # Entry timing breakdown (buckets: 0–15, 16–30, 31–45, 46–60 mins)
    print(f"\n  Entry timing breakdown (minutes after 9:30 open):")
    buckets = [(0, 15), (16, 30), (31, 45), (46, 60)]
    for lo, hi in buckets:
        bt = [t for t in trades if lo <= t["entry_offset_mins"] <= hi]
        if bt:
            bw = sum(1 for t in bt if t["outcome"] == "WIN")
            bp = sum(t["pnl"] for t in bt)
            br = sum(t["r_mult"] for t in bt) / len(bt)
            print(f"    +{lo:02d}–{hi:02d}m : {len(bt):>3} trades  "
                  f"{bw}/{len(bt)} wins ({bw/len(bt)*100:.0f}%)  "
                  f"avg {br:+.2f}R  ${bp:+,.0f}")

    # RVOL breakdown
    print(f"\n  RVOL breakdown:")
    rvol_buckets = [(5, 10), (10, 20), (20, 50), (50, 9999)]
    for lo, hi in rvol_buckets:
        bt = [t for t in trades if lo <= t["rvol"] < hi]
        if bt:
            bw = sum(1 for t in bt if t["outcome"] == "WIN")
            bp = sum(t["pnl"] for t in bt)
            br = sum(t["r_mult"] for t in bt) / len(bt)
            label = f"{lo}–{hi}×" if hi < 9999 else f"{lo}×+"
            print(f"    {label:<10}: {len(bt):>3} trades  "
                  f"{bw}/{len(bt)} wins ({bw/len(bt)*100:.0f}%)  "
                  f"avg {br:+.2f}R  ${bp:+,.0f}")

    # Gap % breakdown
    print(f"\n  Gap % breakdown:")
    gap_buckets = [(10, 20), (20, 35), (35, 60), (60, 9999)]
    for lo, hi in gap_buckets:
        bt = [t for t in trades if lo <= t["gap_pct"] < hi]
        if bt:
            bw = sum(1 for t in bt if t["outcome"] == "WIN")
            bp = sum(t["pnl"] for t in bt)
            br = sum(t["r_mult"] for t in bt) / len(bt)
            label = f"{lo}–{hi}%" if hi < 9999 else f"{lo}%+"
            print(f"    {label:<10}: {len(bt):>3} trades  "
                  f"{bw}/{len(bt)} wins ({bw/len(bt)*100:.0f}%)  "
                  f"avg {br:+.2f}R  ${bp:+,.0f}")

    # Resistance filter impact
    resist_trades = [t for t in trades if t["resistance"]]
    clean_trades  = [t for t in trades if not t["resistance"]]
    if resist_trades or clean_trades:
        print(f"\n  Resistance overhead:")
        for label, group in [("With resistance", resist_trades), ("No resistance", clean_trades)]:
            if group:
                gw = sum(1 for t in group if t["outcome"] == "WIN")
                gp = sum(t["pnl"] for t in group)
                gr = sum(t["r_mult"] for t in group) / len(group)
                print(f"    {label:<18}: {len(group):>3} trades  "
                      f"{gw}/{len(group)} wins ({gw/len(group)*100:.0f}%)  "
                      f"avg {gr:+.2f}R  ${gp:+,.0f}")

    # Conviction tier breakdown
    print(f"\n  Conviction tier breakdown (gap% + RVOL scoring; catalyst quality not")
    print(f"  available for historical simulation — live results should be higher):")
    for tier in ("STANDARD", "STRONG", "EXCEPTIONAL"):
        ct = [t for t in trades if t.get("conviction_tier") == tier]
        if ct:
            cw  = sum(1 for t in ct if t["outcome"] == "WIN")
            cp  = sum(t["pnl"] for t in ct)
            cr  = sum(t["r_mult"] for t in ct) / len(ct)
            cm  = ct[0].get("conviction_mult", 1)
            print(f"    {tier:<12}: {len(ct):>3} trades  "
                  f"{cw}/{len(ct)} wins ({cw/len(ct)*100:.0f}%)  "
                  f"avg {cr:+.2f}R  ${cp:+,.0f}  (size mult {cm:.0f}×)")

    # ── News catalyst breakdown (only when --news was used) ───────────────────
    news_trades = [t for t in trades if "has_catalyst" in t and t.get("news_quality", 0) > 0]
    if news_trades:
        cat_trades   = [t for t in trades if t.get("has_catalyst")]
        nocat_trades = [t for t in trades if not t.get("has_catalyst")]
        neg_trades   = [t for t in trades if t.get("news_negative")]

        print(f"\n  {'─'*60}")
        print(f"  NEWS CATALYST BREAKDOWN  (via --news flag)")
        print(f"  {'─'*60}")

        def _group_stats(label: str, group: list) -> None:
            if not group:
                print(f"  {label:<28}: 0 trades")
                return
            gw  = sum(1 for t in group if t["outcome"] == "WIN")
            gp  = sum(t["pnl"] for t in group)
            gr  = sum(t["r_mult"] for t in group) / len(group)
            gwr = gw / len(group) * 100
            print(f"  {label:<28}: {len(group):>3} trades  "
                  f"{gw}/{len(group)} wins ({gwr:>4.0f}%)  "
                  f"avg {gr:>+5.2f}R  ${gp:>+9,.0f}")

        _group_stats("With news catalyst (★)", cat_trades)
        _group_stats("No news catalyst     (·)", nocat_trades)
        if neg_trades:
            _group_stats("Negative headline    (⚠)", neg_trades)

        # Quality score breakdown
        print(f"\n  News quality score breakdown (0=no news, 3=neutral, 5–10=positive):")
        for lo, hi, label in [
            (0,  0,  "0 — no news found"),
            (1,  2,  "1–2 — negative/dilution"),
            (3,  4,  "3–4 — news, no keyword"),
            (5,  6,  "5–6 — 1 positive keyword"),
            (7,  8,  "7–8 — 2 positive keywords"),
            (9, 10,  "9–10 — 3+ strong catalysts"),
        ]:
            bt = [t for t in trades if lo <= t.get("news_quality", 0) <= hi]
            if bt:
                bw = sum(1 for t in bt if t["outcome"] == "WIN")
                bp = sum(t["pnl"] for t in bt)
                br = sum(t["r_mult"] for t in bt) / len(bt)
                print(f"    {label:<26}: {len(bt):>3} trades  "
                      f"{bw}/{len(bt)} wins ({bw/len(bt)*100:>4.0f}%)  "
                      f"avg {br:>+5.2f}R  ${bp:>+9,.0f}")

        # Verdict — with explicit guardrails. The 2026-05-14 diagnostic
        # (changelog: "Catalyst-quality scoring is broken for small-cap gap
        # universe") found that Alpaca's news API misses 90%+ of the actual
        # news-driven small-cap gappers — every "no-catalyst" trade is likely
        # a missed-news trade, not a true no-catalyst trade. So a "catalyst
        # trades win more" finding is just selection on which tickers Alpaca
        # happened to cover, not a real edge. Refuse to recommend the filter
        # on tiny catalyst samples.
        if cat_trades and nocat_trades:
            cat_wr  = sum(1 for t in cat_trades   if t["outcome"] == "WIN") / len(cat_trades)  * 100
            nc_wr   = sum(1 for t in nocat_trades if t["outcome"] == "WIN") / len(nocat_trades) * 100
            cat_r   = sum(t["r_mult"] for t in cat_trades)   / len(cat_trades)
            nc_r    = sum(t["r_mult"] for t in nocat_trades) / len(nocat_trades)
            wr_diff = cat_wr - nc_wr
            r_diff  = cat_r  - nc_r
            print(f"\n  Catalyst vs No-Catalyst delta:")
            print(f"    Win rate : {'catalyst' if wr_diff > 0 else 'no-catalyst'} better by "
                  f"{abs(wr_diff):.0f} pp  ({cat_wr:.0f}% vs {nc_wr:.0f}%)")
            print(f"    Avg R    : {'catalyst' if r_diff > 0 else 'no-catalyst'} better by "
                  f"{abs(r_diff):.2f}R  ({cat_r:+.2f}R vs {nc_r:+.2f}R)")
            cat_frac = len(cat_trades) / (len(cat_trades) + len(nocat_trades))
            # The historical "→ RECOMMENDATION: Add --require-catalyst" branch
            # was removed 2026-05-14 — see changelog "Catalyst-quality scoring
            # is broken for small-cap gap universe" (item 7 finding). Even when
            # cat_frac ≥ 0.30 the no-catalyst bucket is polluted by trades
            # whose real catalyst Alpaca's cache missed, so the WR delta is
            # not a clean read on catalyst edge. The flag exists for opt-in
            # experimentation only; informational stats below, no auto-recco.
            print(f"    → INFORMATIONAL ONLY — do NOT auto-act on this delta.")
            print(f"      ({len(cat_trades)} of {len(cat_trades)+len(nocat_trades)} trades had news;")
            print(f"      Alpaca's news API misses most small-cap gappers, so the 'no-news'")
            print(f"      bucket is polluted by missed-catalyst trades. Catalyst-quality")
            print(f"      scoring is dictionary-based and was found to mis-classify small-cap")
            print(f"      PR patterns in the 2026-05-14 audit. See changelog for details.)")
            if cat_frac < 0.30 or len(cat_trades) < 10:
                print(f"    → Sample is sparse — coverage {cat_frac:.0%} below 30% trust floor.")

    print(f"\n  ── What the backtest CANNOT model ──────────────────────────────")
    print(f"  Catalyst quality filter  : red-flag setups (dilution, reverse splits)")
    print(f"                             would be skipped live — fewer, better trades")
    if SCALEINS_ENABLED:
        print(f"  T3 overnight holds       : intraday-EOD exit only; live's runner-")
        print(f"                             rule overnights stay an unmodeled signal")
        print(f"                             (see project_backtest_no_overnight_t3 memo).")
    else:
        print(f"  Breakeven trailing stop  : at +1R, stop moves to entry. Trades that")
        print(f"                             reach +1R and pull back are LOSS here but")
        print(f"                             breakeven live — understates true P&L.")
        print(f"  T2/T3 scaling tranches   : only T1 (first 25%) simulated here.")
        print(f"                             Full position scales to 100% on winners.")
        print(f"                             Pass --scaleins to model the full lifecycle.")
    print(f"{'='*65}\n")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Backtest the gap trading strategy")
    parser.add_argument("--start",      help="Start date YYYY-MM-DD")
    parser.add_argument("--end",        help="End date YYYY-MM-DD")
    parser.add_argument("--top",        type=int, default=20,
                        help="Max candidates per day (default 20)")
    parser.add_argument("--cache-dir",  default="state/cache",
                        help="Cache directory (default: state/cache)")
    parser.add_argument("--refresh",    action="store_true",
                        help="Force re-fetch of all data (ignore cache)")
    parser.add_argument("--refresh-yf", action="store_true",
                        help="Force re-fetch of yfinance enrichment only")
    parser.add_argument("--no-premarket", action="store_true",
                        help="DISABLE pre-market spike detection. "
                             "Pre-market IS the strategy by default — the live "
                             "bot runs run_premarket at 4:05 AM ET; backtests "
                             "must match. Use this flag only to reproduce the "
                             "pre-2026-05-14 regular-session-only baselines.")
    parser.add_argument("--no-filters", action="store_true",
                        help="Disable optimized entry filters (run raw baseline)")
    parser.add_argument("--min-offset", type=int, default=None,
                        help="Override MIN_ENTRY_OFFSET_MINS (default: 20)")
    parser.add_argument("--rvol-min",  type=float, default=None,
                        help="Override RVOL_ENTRY_MIN (default: 20.0)")
    parser.add_argument("--gap-min",   type=float, default=None,
                        help="Override GAP_ENTRY_MIN_PCT (default: 15.0)")
    parser.add_argument("--news",      action="store_true",
                        help="Fetch Alpaca news for each candidate and score catalyst quality. "
                             "Shows catalyst vs no-catalyst win rate split in report.")
    parser.add_argument("--require-catalyst", action="store_true",
                        help="Only simulate entries where a news catalyst was found "
                             "(requires --news). Tests catalyst-only strategy.")
    parser.add_argument("--shorts",   action="store_true",
                        help="Backtest gap-down breakdown SHORTS instead of longs. "
                             "Inverts pattern detection, sizing (15%% tranche, 2:1 R:R, "
                             "12:30 PM time stop, squeeze-protection).")
    parser.add_argument("--no-scaleins", action="store_true",
                        help="Disable T2/T3 scale-in simulation. Reproduces the legacy "
                             "T1-only single-bracket mode (use to compare against "
                             "pre-2026-05-14 baselines). Default is scale-ins ON.")
    parser.add_argument("--scaleouts", action="store_true",
                        help="Use Ross-style scale-OUT ladder instead of scale-INs. "
                             "Enters full T1 conviction size, sells 25%% at +1R/+2R/+3R, "
                             "runs last 25%% with $1R trail above +2R floor. Mutually "
                             "exclusive with scale-ins.")
    parser.add_argument("--entry-gates",
                        choices=["none", "score", "conviction", "hard", "majority"],
                        default="conviction",
                        help="Ross entry-quality gates (MACD bullish / 9-EMA pullback "
                             "support / above VWAP). 'none'=disabled (use to reproduce "
                             "pre-2026-05-14 backtest baselines). 'score'=compute + log "
                             "gates_passed, never reject. 'conviction'=DEFAULT, ships "
                             "Ross-true behavior: halve conviction multiplier when "
                             "gates_passed == 0. 'hard'=reject unless all 3 pass. "
                             "'majority'=reject unless ≥2 of 3 pass.")
    parser.add_argument("--ema-tol-pct", type=float, default=EMA9_TOL_PCT_DEFAULT,
                        help=f"9-EMA proximity tolerance for the pullback gate, as a "
                             f"fraction of price. Default {EMA9_TOL_PCT_DEFAULT} (0.5%%).")
    args = parser.parse_args()

    if args.start and args.end:
        start = date.fromisoformat(args.start)
        end   = date.fromisoformat(args.end)
    else:
        start, end = last_n_trading_days(5)

    cache_dir = Path(args.cache_dir)

    # Apply CLI overrides to module-level filter constants
    global MIN_ENTRY_OFFSET_MINS, SKIP_RUNNERS, SKIP_RESISTANCE, GAP_ENTRY_MIN_PCT, RVOL_ENTRY_MIN
    global SCALEINS_ENABLED, SCALEOUTS_ENABLED
    global ENTRY_GATES_MODE, EMA9_TOL_PCT
    ENTRY_GATES_MODE = args.entry_gates
    EMA9_TOL_PCT     = args.ema_tol_pct
    if args.no_filters:
        MIN_ENTRY_OFFSET_MINS = 0
        SKIP_RUNNERS          = False
        SKIP_RESISTANCE       = False
        GAP_ENTRY_MIN_PCT     = 0.0
        RVOL_ENTRY_MIN        = 0.0
    if args.min_offset is not None:
        MIN_ENTRY_OFFSET_MINS = args.min_offset
    if args.rvol_min is not None:
        RVOL_ENTRY_MIN = args.rvol_min
    if args.gap_min is not None:
        GAP_ENTRY_MIN_PCT = args.gap_min
    if args.no_scaleins:
        SCALEINS_ENABLED = False
    if args.scaleouts:
        SCALEOUTS_ENABLED = True
        SCALEINS_ENABLED  = False   # mutex
        if args.no_scaleins:
            print("Note: --no-scaleins is redundant with --scaleouts (mutex enforced).")

    # ── Honest-fills stress (BT_FILL_STRESS=1) ───────────────────────────────
    # Free proxy for SIP/paid-data fidelity. The default 30 bps stop slippage is
    # wildly optimistic for halting sub-$5 names whose stops realistically slip
    # 1.5–5%. Tight-pullback's +25R winners ride ~0.5–0.7% risk, so stop slip of
    # the same magnitude roughly doubles every loss — the decisive test of
    # whether the tail edge survives realistic execution. Tunable via env.
    global EQUITY_SLIPPAGE_STOP, EQUITY_SLIPPAGE_PCT
    if os.getenv("BT_FILL_STRESS") == "1":
        EQUITY_SLIPPAGE_STOP = float(os.getenv("BT_STOP_SLIP", "0.015"))   # 1.5%
        EQUITY_SLIPPAGE_PCT  = float(os.getenv("BT_MKT_SLIP",  "0.005"))   # 0.5%
        print(f"FILL STRESS  : stop slip {EQUITY_SLIPPAGE_STOP:.1%}, "
              f"market slip {EQUITY_SLIPPAGE_PCT:.1%} (BT_FILL_STRESS=1)")

    print(f"\nGap Strategy Backtester")
    print(f"Criteria : gap≥{GAP_MIN_PCT}%  price ${PRICE_MIN}–${PRICE_MAX}  "
          f"float<{FLOAT_MAX/1e6:.0f}M  RVOL≥{RVOL_MIN}×")
    print(f"Sizing   : {TRANCHE_1_PCT:.0%} tranche of ${GAP_NOTIONAL:,}  "
          f"→ ${GAP_NOTIONAL*TRANCHE_1_PCT:,.0f} per T1")
    print(f"R:R      : {RR_RATIO}:1  max risk/trade: {MAX_RISK_PCT:.0%} of notional")
    if SCALEOUTS_ENABLED:
        ladder_desc = ", ".join(f"{f*100:.0f}%@+{r:.0f}R" for r, f in SCALEOUT_LADDER)
        print(f"Mode     : SCALE-OUT (Ross harvest) — {ladder_desc}, runner trail $1R/sh "
              f"above +2R floor")
    elif SCALEINS_ENABLED:
        print(f"Scale-ins: ENABLED — T1 breakeven trail at +{BREAKEVEN_TRIGGER_R:.0f}R, "
              f"T2 {TRANCHE_2_PCT:.0%} @ flag×{1+SCALE2_TRIGGER_PCT:.3f} "
              f"(3% trail), T3 {TRANCHE_3_PCT:.0%} @ T2×{1+SCALE3_TRIGGER_PCT:.3f} "
              f"(BE stop, EOD exit)")
    else:
        print(f"Scale-ins: DISABLED — T1-only legacy bracket "
              f"(single stop+target, no trail, no T2/T3 adds)")
    print(f"Cache    : {cache_dir.resolve()}")
    if args.refresh:
        print(f"           --refresh: ignoring all cached data")
    if args.refresh_yf:
        print(f"           --refresh-yf: ignoring yfinance cache")

    filters_active = not args.no_filters
    if filters_active:
        print(f"Filters  : entry≥+{MIN_ENTRY_OFFSET_MINS}min  "
              f"{'skip runners  ' if SKIP_RUNNERS else ''}"
              f"{'skip resistance  ' if SKIP_RESISTANCE else ''}"
              f"gap≥{GAP_ENTRY_MIN_PCT:.0f}%  "
              f"RVOL≥{RVOL_ENTRY_MIN:.0f}×")
    else:
        print(f"Filters  : disabled (raw baseline mode)")

    if not args.no_premarket:
        print(f"Pre-market : ENABLED (default — scan 6:45–9:20 AM ET, "
              f"spike ≥{PM_SPIKE_RVOL_EQUIV}× per-min rate)")
    else:
        print(f"Pre-market : DISABLED (--no-premarket) — regular-session-only "
              f"legacy baseline mode")
    if args.news:
        print(f"News       : enabled  (Alpaca news API, cached per day)")
    if args.require_catalyst:
        if not args.news:
            print("WARNING: --require-catalyst has no effect without --news")
        else:
            print(f"           --require-catalyst: only trading setups with news catalyst")

    if args.shorts:
        print(f"Direction: SHORT (gap-down breakdown)")
        print(f"Sizing   : {SHORT_TRANCHE_1_PCT:.0%} tranche, {SHORT_RR_RATIO}:1 R:R, "
              f"{SHORT_MAX_RISK_PCT:.0%} max risk/trade, "
              f"time-stop {SHORT_TIME_STOP_HHMM[0]:02d}:{SHORT_TIME_STOP_HHMM[1]:02d} ET, "
              f"squeeze-protect {SHORT_SQUEEZE_R_MULT}R/{SHORT_SQUEEZE_BARS}bars")
        print(f"Universe : gap≤-{GAP_MIN_PCT}%, RVOL≥{SHORT_RVOL_ENTRY_MIN}×, "
              f"float {SHORT_FLOAT_MIN/1e6:.0f}M-{SHORT_FLOAT_MAX/1e6:.0f}M, "
              f"price ${PRICE_MIN}-${PRICE_MAX}")

    t0     = time.time()
    trades = run_backtest(
        start, end,
        top_n=args.top,
        cache_dir=cache_dir,
        refresh=args.refresh,
        refresh_yf=args.refresh_yf,
        include_premarket=not args.no_premarket,
        fetch_news=args.news,
        require_catalyst=args.require_catalyst,
        direction="short" if args.shorts else "long",
    )
    print_report(trades, start, end)

    # Structured JSON summary — consumed by /gap-backtest skill diff and
    # tests/test_strategy_targets.py (iteration loop).
    summary_path = Path(__file__).parent / "state" / "last_backtest.json"
    emit_summary_json(trades, start, end, summary_path)
    print(f"Summary written to {summary_path}")

    if trades:
        ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = cache_dir / f"trades_{start}_{end}_{ts}.csv"
        export_trades_csv(trades, csv_path)

    elapsed = time.time() - t0
    print(f"Backtest completed in {elapsed/60:.1f} minutes.\n")


if __name__ == "__main__":
    main()
