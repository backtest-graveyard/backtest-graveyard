#!/usr/bin/env python3
"""
Buffett Bot — backtest harness.

Simulates the screener historically using POINT-IN-TIME fundamentals: at every
rebalance date it rebuilds each company's financials from only those EDGAR
filings dated on or before that day, so the strategy sees exactly what the
market saw. Restated figures never leak backwards.

=========================== HONEST LIMITATIONS ===========================
1. SURVIVORSHIP BIAS — NOT FIXED. The universe is TODAY's S&P 500 membership
   (universe.py scrapes the current list). Every name in it survived and stayed
   in the index; companies that blew up or were removed are absent. This makes
   results an OPTIMISTIC UPPER BOUND, not a fair estimate. Removing it needs
   historical index membership + delisted names (Sharadar/Norgate, ~$50-70/mo).
   Treat a pass here as "not yet disproven", never as validation.
2. LOW STATISTICAL POWER. Multi-year holds give few independent observations,
   so both good and bad results are weak evidence.
3. Fundamentals-only. No intra-period exits; the sell discipline in monitor.py
   is not simulated (positions are held to the next rebalance).
==========================================================================

Split correctness (subtle but decisive):
  * VALUATION ratios use the RAW (unadjusted) close, because EDGAR share counts
    are as-reported-then. Mixing a split-adjusted price with a pre-split share
    count is exactly the bug that made Booking look like a P/E of 1.
  * RETURNS use the ADJUSTED close (splits + dividends), since Buffett-style
    names pay meaningful dividends.

Usage:
    python -m buffett_bot.backtest --start 2015-01-01 --end 2026-01-01
    python -m buffett_bot.backtest --limit 60 --rebalance A    # quick test
    python -m buffett_bot.backtest --top-n 20 --rebalance Q
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from . import config, edgar_source as E
from .providers import finalize_valuation
from .screener import score
from .universe import get_universe

log = logging.getLogger("buffett_bot.backtest")

_CACHE_DIR = Path("buffett_bot/output/edgar_cache")
TRADING_DAYS = 252

# Round-trip transaction cost charged on turnover at each rebalance. Low-
# turnover strategy, but cost-first is the house rule.
COST_BPS = 10.0


# --------------------------------------------------------------------------- #
# data loading                                                                 #
# --------------------------------------------------------------------------- #
def load_facts(tickers: list[str], refresh: bool = False) -> dict[str, dict]:
    """Fetch companyfacts once per ticker, cached to disk. One request each."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out: dict[str, dict] = {}
    for i, t in enumerate(tickers, 1):
        cache = _CACHE_DIR / f"{t}.json"
        if cache.exists() and not refresh:
            try:
                data = json.loads(cache.read_text())
                # Backfill SIC into caches written before business-model
                # classification existed. Without it every company would
                # classify as "cashflow" and the backtest would silently
                # disagree with the live screen on gates and valuation.
                if "sic" not in data:
                    cik = E.ticker_to_cik(t)
                    if cik:
                        sic, desc = E.company_sic(cik)
                        data["sic"], data["sicDescription"] = sic, desc
                        cache.write_text(json.dumps(data))
                        log.info("(%d/%d) backfilled SIC for %s (%s)",
                                 i, len(tickers), t, sic)
                out[t] = data
                continue
            except Exception:  # noqa: BLE001 — corrupt cache, refetch
                pass
        log.info("(%d/%d) fetching EDGAR facts %s", i, len(tickers), t)
        data = E.fetch_facts(t)
        if data:
            cache.write_text(json.dumps(data))
            out[t] = data
    log.info("EDGAR facts available for %d/%d tickers", len(out), len(tickers))
    return out


def load_prices(tickers: list[str], start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (raw_close, adj_close) daily frames. Raw for valuation ratios,
    adjusted for returns."""
    import yfinance as yf
    raw_parts, adj_parts = [], []
    CHUNK = 100
    for i in range(0, len(tickers), CHUNK):
        batch = tickers[i:i + CHUNK]
        log.info("downloading prices %d-%d of %d", i + 1, i + len(batch), len(tickers))
        df = yf.download(batch, start=start, end=end, auto_adjust=False,
                         progress=False, group_by="column", threads=True)
        if df is None or df.empty:
            continue
        try:
            raw_parts.append(df["Close"])
            adj_parts.append(df["Adj Close"])
        except KeyError:  # single-ticker shape
            raw_parts.append(df[["Close"]].rename(columns={"Close": batch[0]}))
            adj_parts.append(df[["Adj Close"]].rename(columns={"Adj Close": batch[0]}))
    if not raw_parts:
        return pd.DataFrame(), pd.DataFrame()
    raw = pd.concat(raw_parts, axis=1)
    adj = pd.concat(adj_parts, axis=1)
    return raw.sort_index(), adj.sort_index()


def first_filed_map(facts: dict[str, dict]) -> dict[str, dt.date]:
    """Earliest filing date per company — a $0 partial proxy for index membership.

    The universe is today's S&P 500, so it contains names that were not in the
    index (or not even public) during much of the window. COIN was the #2
    contributor in the first run despite only joining the S&P 500 in 2025.
    Requiring N years of filing history as of each rebalance excludes recent
    listings. It does NOT fix membership — an established company added to the
    index in 2023 still leaks — but it removes the worst offenders for free.

    The first-filing date is knowable at any as-of date, so this adds no
    look-ahead.
    """
    out: dict[str, dt.date] = {}
    for t, data in facts.items():
        best = None
        for tax in ("us-gaap", "dei"):
            for node in (data.get("facts", {}).get(tax, {}) or {}).values():
                for unit_facts in (node.get("units", {}) or {}).values():
                    for f in unit_facts:
                        fd = f.get("filed")
                        if fd and (best is None or fd < best):
                            best = fd
        if best:
            out[t] = dt.date.fromisoformat(best)
    return out


def _asof_price(frame: pd.DataFrame, ticker: str, when: pd.Timestamp) -> Optional[float]:
    """Last close on or before `when` (no peeking forward)."""
    if ticker not in frame.columns:
        return None
    s = frame[ticker].loc[:when].dropna()
    if s.empty:
        return None
    v = float(s.iloc[-1])
    return v if v > 0 else None


# --------------------------------------------------------------------------- #
# selection                                                                    #
# --------------------------------------------------------------------------- #
def select(facts: dict[str, dict], raw: pd.DataFrame, when: pd.Timestamp,
           top_n: int, min_score: float,
           first_filed: Optional[dict] = None,
           min_history_years: float = 0.0) -> list[str]:
    """Rank the universe as of `when` and return the top-N tickers.

    Uses top-N-by-score among gate passers rather than the live BUY threshold,
    so the portfolio stays invested in periods when nothing clears 0.68.
    """
    as_of = when.date()
    rows = []
    for t, data in facts.items():
        # recent-listing filter (partial survivorship mitigation)
        if min_history_years and first_filed:
            ff = first_filed.get(t)
            if ff is None or (as_of - ff).days < min_history_years * 365.25:
                continue
        try:
            f = E.build(t, data, as_of)
        except Exception:  # noqa: BLE001
            continue
        if f is None:
            continue
        px = _asof_price(raw, t, when)          # RAW price pairs with as-reported shares
        if px is None:
            continue
        f.price = px
        finalize_valuation(f)
        s = score(f)
        if not s.passed_gates or not s.data_ok:
            continue
        if s.final_score < min_score:
            continue
        rows.append((t, s.final_score, data.get("cik")))
    rows.sort(key=lambda r: r[1], reverse=True)

    # Dual-class dedupe: GOOGL and GOOG are ONE company and would otherwise take
    # two slots, silently double-weighting it. Same CIK = same issuer; keep the
    # higher-scoring class only.
    picks, seen_ciks = [], set()
    for t, _sc, cik in rows:
        if cik is not None and cik in seen_ciks:
            log.debug("skipping %s — dual class of CIK %s already held", t, cik)
            continue
        if cik is not None:
            seen_ciks.add(cik)
        picks.append(t)
        if len(picks) >= top_n:
            break
    return picks


# --------------------------------------------------------------------------- #
# simulation                                                                   #
# --------------------------------------------------------------------------- #
def simulate(facts, raw, adj, dates, top_n, min_score,
             first_filed=None, min_history_years: float = 0.0
             ) -> tuple[pd.Series, list[dict], dict]:
    """Walk the rebalance dates, equal-weight the picks, return daily returns.

    Also attributes P&L per name (contrib) so the breadth/robustness kill-test
    can ask whether the edge is broad or carried by a handful of winners."""
    daily_parts, journal = [], []
    contrib: dict[str, float] = {}
    prev_holdings: set[str] = set()

    for i, d in enumerate(dates[:-1]):
        nxt = dates[i + 1]
        picks = select(facts, raw, d, top_n, min_score,
                       first_filed, min_history_years)
        if not picks:
            log.warning("%s: no qualifying names — holding cash this period", d.date())
            journal.append({"date": d.date().isoformat(), "n": 0, "picks": [],
                            "period_return": 0.0})
            idx = adj.loc[d:nxt].index
            daily_parts.append(pd.Series(0.0, index=idx))
            prev_holdings = set()
            continue

        window = adj.loc[d:nxt, [p for p in picks if p in adj.columns]].dropna(axis=1, how="all")
        if window.empty or window.shape[1] == 0:
            prev_holdings = set(picks)
            continue

        rets = window.pct_change().dropna(how="all")
        port_daily = rets.mean(axis=1).fillna(0.0)   # equal weight, held to next rebalance

        # per-name attribution: equal-weight share of each holding's period return
        w = 1.0 / window.shape[1]
        for tk in window.columns:
            col = window[tk].dropna()
            if len(col) >= 2 and col.iloc[0] > 0:
                contrib[tk] = contrib.get(tk, 0.0) + w * (col.iloc[-1] / col.iloc[0] - 1)

        # charge turnover cost on the first day of the period
        turnover = len(set(picks) ^ prev_holdings) / max(len(set(picks) | prev_holdings), 1)
        if len(port_daily) and turnover > 0:
            port_daily.iloc[0] -= turnover * (COST_BPS / 10_000.0)

        daily_parts.append(port_daily)
        journal.append({
            "date": d.date().isoformat(), "n": len(picks), "picks": picks,
            "period_return": float((1 + port_daily).prod() - 1),
            "turnover": round(turnover, 3),
        })
        log.info("%s: %d picks, period return %+.2f%% (turnover %.0f%%) — %s",
                 d.date(), len(picks), journal[-1]["period_return"] * 100,
                 turnover * 100, ", ".join(picks[:8]) + ("…" if len(picks) > 8 else ""))
        prev_holdings = set(picks)

    if not daily_parts:
        return pd.Series(dtype=float), journal, contrib
    return pd.concat(daily_parts).sort_index(), journal, contrib


def breadth_report(contrib: dict[str, float]) -> tuple[str, list[str]]:
    """Is the edge broad, or a few lucky winners? Returns (text, top5 tickers).

    The stat-arb post-mortem's lesson: a real edge survives losing its best
    names; a lottery doesn't. This quantifies the concentration before the
    drop-top test confirms it.
    """
    if not contrib:
        return "(no attribution)", []
    ranked = sorted(contrib.items(), key=lambda kv: kv[1], reverse=True)
    gross_pos = sum(v for _, v in ranked if v > 0) or 1e-9
    n_pos = sum(1 for _, v in ranked if v > 0)
    top5 = [t for t, _ in ranked[:5]]
    top5_share = sum(v for _, v in ranked[:5]) / gross_pos
    lines = [
        f"names held: {len(ranked)} | net-positive: {n_pos} ({n_pos/len(ranked)*100:.0f}%)",
        f"top-5 share of gross positive P&L: {top5_share*100:.0f}%",
        "top contributors: " + ", ".join(f"{t} {v*100:+.0f}%" for t, v in ranked[:8]),
        "worst contributors: " + ", ".join(f"{t} {v*100:+.0f}%" for t, v in ranked[-5:]),
    ]
    return "\n".join(lines), top5


# --------------------------------------------------------------------------- #
# metrics                                                                      #
# --------------------------------------------------------------------------- #
def metrics(daily: pd.Series) -> dict:
    """CAGR, MaxDD, MAR, Sortino — the project's standard reporting set."""
    daily = daily.dropna()
    if daily.empty:
        return {}
    equity = (1 + daily).cumprod()
    years = len(daily) / TRADING_DAYS
    cagr = equity.iloc[-1] ** (1 / years) - 1 if years > 0 else np.nan
    dd = equity / equity.cummax() - 1
    max_dd = float(dd.min())
    downside = daily[daily < 0]
    dstd = float(downside.std()) * np.sqrt(TRADING_DAYS) if len(downside) > 1 else np.nan
    sortino = (float(daily.mean()) * TRADING_DAYS) / dstd if dstd and dstd > 0 else np.nan
    vol = float(daily.std()) * np.sqrt(TRADING_DAYS)
    return {
        "total_return": float(equity.iloc[-1] - 1),
        "cagr": float(cagr),
        "max_drawdown": max_dd,
        "mar": float(cagr / abs(max_dd)) if max_dd else np.nan,
        "sortino": float(sortino),
        "vol": vol,
        "years": years,
        "days": len(daily),
    }


def _fmt(m: dict, label: str) -> str:
    if not m:
        return f"{label}: (no data)"
    return (f"{label:10s} CAGR {m['cagr']*100:6.2f}% | MaxDD {m['max_drawdown']*100:6.2f}% "
            f"| MAR {m['mar']:5.2f} | Sortino {m['sortino']:5.2f} "
            f"| vol {m['vol']*100:5.1f}% | total {m['total_return']*100:7.1f}%")


# --------------------------------------------------------------------------- #
# main                                                                         #
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Buffett Bot point-in-time backtest")
    p.add_argument("--start", default="2015-01-01")
    p.add_argument("--end", default=dt.date.today().isoformat())
    p.add_argument("--rebalance", default="A", choices=["A", "Q"],
                   help="A=annual, Q=quarterly")
    p.add_argument("--top-n", type=int, default=15)
    p.add_argument("--min-score", type=float, default=0.0)
    p.add_argument("--limit", type=int, help="cap universe size (fast test)")
    p.add_argument("--refresh", action="store_true", help="refetch EDGAR cache")
    p.add_argument("--min-history-years", type=float, default=0.0,
                   help="require N years of filing history at each rebalance "
                        "(partial survivorship mitigation; excludes recent IPOs)")
    p.add_argument("--drop-top", type=int, default=5,
                   help="kill-test: re-run excluding the N best contributors (0=off)")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    logging.getLogger("yfinance").setLevel(logging.ERROR)

    tickers = get_universe("sp500")
    if args.limit:
        tickers = tickers[:args.limit]

    log.warning("SURVIVORSHIP BIAS: universe is TODAY's S&P 500 (%d names). "
                "Results are an OPTIMISTIC UPPER BOUND, not validation.", len(tickers))

    facts = load_facts(tickers, refresh=args.refresh)
    if not facts:
        log.error("no EDGAR facts — aborting")
        return 1

    raw, adj = load_prices(list(facts) + ["SPY"], args.start, args.end)
    if adj.empty:
        log.error("no price data — aborting")
        return 1

    freq = "YS" if args.rebalance == "A" else "QS"
    dates = [d for d in pd.date_range(args.start, args.end, freq=freq) if d in adj.index
             or True]
    # snap each rebalance date to the next available trading day
    snapped = []
    for d in dates:
        idx = adj.index[adj.index >= d]
        if len(idx):
            snapped.append(idx[0])
    dates = sorted(set(snapped))
    if len(dates) < 2:
        log.error("need >=2 rebalance dates in range")
        return 1
    log.info("Rebalances: %d (%s -> %s), top-%d equal weight, %.0f bps cost",
             len(dates) - 1, dates[0].date(), dates[-1].date(), args.top_n, COST_BPS)

    first_filed = {}
    if args.min_history_years:
        log.info("computing first-filing dates for the %d-year history filter…",
                 args.min_history_years)
        first_filed = first_filed_map(facts)
        log.info("first-filing dates resolved for %d/%d tickers", len(first_filed), len(facts))

    daily, journal, contrib = simulate(facts, raw, adj, dates, args.top_n,
                                       args.min_score, first_filed,
                                       args.min_history_years)
    if daily.empty:
        log.error("no returns produced")
        return 1

    strat = metrics(daily)
    breadth_txt, top5 = breadth_report(contrib)

    # KILL-TEST: re-run without the best contributors. A real, broad edge
    # survives losing its winners; a fat-tail lottery collapses. This is the
    # test that killed the stat-arb PCA book (Sortino 1.53 -> -0.51).
    stressed = {}
    if args.drop_top and top5:
        drop = set(top5[:args.drop_top])
        log.info("KILL-TEST: re-running without top-%d contributors: %s",
                 args.drop_top, ", ".join(sorted(drop)))
        facts_less = {k: v for k, v in facts.items() if k not in drop}
        d2, _, _ = simulate(facts_less, raw, adj, dates, args.top_n,
                            args.min_score, first_filed, args.min_history_years)
        stressed = metrics(d2) if not d2.empty else {}
    spy_daily = adj["SPY"].loc[dates[0]:dates[-1]].pct_change().dropna() \
        if "SPY" in adj.columns else pd.Series(dtype=float)
    bench = metrics(spy_daily)

    bar_ok = strat.get("mar", 0) >= 0.5 and strat.get("sortino", 0) >= 1.0
    print("\n" + "=" * 78)
    print(f"BUFFETT BOT BACKTEST  {dates[0].date()} → {dates[-1].date()}  "
          f"({args.rebalance}, top-{args.top_n})")
    print("=" * 78)
    print(_fmt(strat, "STRATEGY"))
    print(_fmt(bench, "SPY"))
    if stressed:
        print(_fmt(stressed, f"DROP-TOP{args.drop_top}"))
    print("-" * 78)
    print("BREADTH:")
    print(breadth_txt)
    print("-" * 78)
    print(f"KPI bar (MAR>=0.5 AND Sortino>=1.0): {'PASS' if bar_ok else 'FAIL'}")
    if stressed:
        surv = stressed.get("mar", 0) >= 0.5 and stressed.get("sortino", 0) >= 1.0
        print(f"KILL-TEST (same bar, best {args.drop_top} names removed): "
              f"{'SURVIVES' if surv else 'COLLAPSES — edge was carried by a few names'}")
    print("SURVIVORSHIP BIAS PRESENT — optimistic upper bound, not validation.")
    print("=" * 78 + "\n")

    out = Path(config.OUTPUT["results_dir"]) / f"backtest_{dt.date.today()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "params": vars(args), "strategy": strat, "benchmark_spy": bench,
        "kpi_pass": bar_ok, "survivorship_biased": True, "journal": journal,
        "stressed_drop_top": stressed, "contributions": contrib,
    }, indent=2, default=str))
    log.info("Wrote %s", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
