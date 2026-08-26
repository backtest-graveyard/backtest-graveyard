#!/usr/bin/env python3
"""Earnings-night overnight-hold backtest (research harness, 2026-08-23).

Strategy: hold a stock only across its earnings announcement night.
  - AMC filing (acceptance >= 16:00 ET): buy close of filing day, sell next open.
  - BMO filing (acceptance < 09:00 ET): buy prior close, sell open of filing day.
  - Filings accepted 09:00-16:00 ET are skipped (reaction is intraday, no clean gap).

Data:
  - Prices: Alpaca SIP daily bars, adjustment=all, from 2016-01-04.
  - Earnings dates/times: SEC EDGAR 8-K filings with Item 2.02 (acceptanceDateTime is ET).

Universe: high-attention retail names per the overnight-effect literature (Lou/Polk/
Skouras 2019; Knuteson) and the 2026-08-22 viral post. NOTE: chosen with hindsight of
today's attention -> selection bias runs IN FAVOR of the strategy; a fail is robust.

Books reported:
  - POOLED: every event, 25% of equity per event (same-night events share, cap 100%).
  - POOLED-100: full equity into each event (concurrent events split equally).
  - Per-name full-capital books for reference.
Cost scenarios: 0 / 5 / 10 bps round-trip (MOC+MOO auction fills; 5 bps realistic).

Kill tests: drop-top-5 events; drop best name. Bars: MAR >= 0.5 AND Sortino >= 1.0.
"""

import json
import math
import os
import time
import urllib.request

# SEC EDGAR requires a descriptive User-Agent with contact info. Use your own.
UA = {"User-Agent": "YOUR NAME your-email@example.com (personal research)"}

UNIVERSE = {
    "MU":   "0000723125",
    "NVDA": "0001045810",
    "TSLA": "0001318605",
    "AMD":  "0000002488",
    "MSTR": "0001050446",
    "AAPL": "0000320193",
    "AMZN": "0001018724",
    "META": "0001326801",
    "GOOGL": "0001652044",
    "MSFT": "0000789019",
    "NFLX": "0001065280",
    "COIN": "0001679788",
    "PLTR": "0001321655",
    "SMCI": "0001375365",
}

START = "2016-01-01"
COSTS_BPS = [0, 5, 10]
EVENT_WEIGHT = 0.25  # POOLED book: fraction of equity per event


def get_json(url):
    req = urllib.request.Request(url, headers=UA)
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


def earnings_events(cik):
    """Sorted unique (date, acceptance_hour_ET) for 8-Ks with Item 2.02."""
    sub = get_json(f"https://data.sec.gov/submissions/CIK{cik}.json")
    batches = [sub["filings"]["recent"]]
    for f in sub["filings"].get("files", []):
        batches.append(get_json(f"https://data.sec.gov/submissions/{f['name']}"))
        time.sleep(0.15)
    events = set()
    for b in batches:
        for form, items, acc in zip(b["form"], b["items"], b["acceptanceDateTime"]):
            if form == "8-K" and "2.02" in (items or ""):
                events.add((acc[:10], int(acc[11:13])))
    return sorted(e for e in events if e[0] >= START)


def load_alpaca_creds():
    creds = {}
    with open(os.path.expanduser("~/.alpaca/credentials")) as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                creds[k.strip()] = v.strip()
    return (creds.get("ALPACA_KEY") or creds.get("APCA_API_KEY_ID"),
            creds.get("ALPACA_SECRET") or creds.get("APCA_API_SECRET_KEY"))


def fetch_bars(symbol, key, sec):
    bars, token = [], None
    while True:
        url = (f"https://data.alpaca.markets/v2/stocks/{symbol}/bars"
               f"?timeframe=1Day&start={START}T00:00:00Z&limit=10000"
               f"&adjustment=all&feed=sip")
        if token:
            url += f"&page_token={token}"
        req = urllib.request.Request(
            url, headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec})
        d = json.loads(urllib.request.urlopen(req, timeout=60).read())
        bars += d.get("bars") or []
        token = d.get("next_page_token")
        if not token:
            break
    return bars


def build_gaps(events, bars):
    """[(gap_morning_date, gross_gap_multiple)] plus skipped-midday count."""
    by_date = {b["t"][:10]: b for b in bars}
    days = [b["t"][:10] for b in bars]
    idx = {d: i for i, d in enumerate(days)}
    gaps, skipped = [], 0
    for date, hour in events:
        if hour >= 16:
            if date in idx and idx[date] + 1 < len(days):
                d1 = days[idx[date] + 1]
                gaps.append((d1, by_date[d1]["o"] / by_date[date]["c"]))
        elif hour < 9:
            if date in idx and idx[date] > 0:
                d0 = days[idx[date] - 1]
                gaps.append((date, by_date[date]["o"] / by_date[d0]["c"]))
        else:
            skipped += 1
    return gaps, skipped


def book_stats(night_returns, years, label):
    """night_returns: list of (date, portfolio_return_that_night). Compounded."""
    eq, peak, maxdd = 1.0, 1.0, 0.0
    for _, r in night_returns:
        eq *= 1 + r
        peak = max(peak, eq)
        maxdd = max(maxdd, 1 - eq / peak)
    cagr = eq ** (1 / years) - 1
    rets = [r for _, r in night_returns]
    n = len(rets)
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r < 0]
    pf = sum(wins) / abs(sum(losses)) if losses else float("inf")
    dd_dev = math.sqrt(sum(r * r for r in losses) / n) if n else 0.0
    sortino = ((sum(rets) / n) / dd_dev) * math.sqrt(n / years) if dd_dev else float("inf")
    mar = cagr / maxdd if maxdd else float("inf")
    print(f"  {label:<26} nights={n:<4} cum={eq:7.3f}x CAGR={cagr*100:+6.1f}% "
          f"MaxDD={maxdd*100:5.1f}% MAR={mar:5.2f} Sortino={sortino:5.2f} "
          f"PF={pf:4.2f} WR={len(wins)/n*100:3.0f}%")
    return {"cum": eq, "cagr": cagr, "maxdd": maxdd, "mar": mar,
            "sortino": sortino, "pf": pf, "n": n}


def main():
    key, sec = load_alpaca_creds()
    per_name = {}          # sym -> list[(date, gross_gap)]
    print("Fetching EDGAR events + Alpaca bars...")
    for sym, cik in UNIVERSE.items():
        ev = earnings_events(cik)
        bars = fetch_bars(sym, key, sec)
        gaps, skipped = build_gaps(ev, bars)
        per_name[sym] = gaps
        note = f" ({skipped} midday filings skipped)" if skipped else ""
        span = f"{bars[0]['t'][:10]}..{bars[-1]['t'][:10]}" if bars else "no bars"
        print(f"  {sym:<5} {len(gaps):3d} earnings nights, bars {span}{note}")
        time.sleep(0.2)

    all_days = sorted({d for g in per_name.values() for d, _ in g})
    years = 10.64  # 2016-01-04 .. 2026-08-21

    for cost_bps in COSTS_BPS:
        c = cost_bps / 10000.0
        print(f"\n=== Round-trip cost {cost_bps} bps ===")

        # per-event net returns grouped by night
        by_night = {}
        for sym, gaps in per_name.items():
            for d, g in gaps:
                by_night.setdefault(d, []).append((sym, g * (1 - c) - 1))

        # POOLED: 25% per event, same-night events capped at 100% total
        pooled = []
        for d in all_days:
            evs = by_night[d]
            w = min(EVENT_WEIGHT, 1.0 / len(evs))
            pooled.append((d, sum(w * r for _, r in evs)))
        stats = book_stats(pooled, years, f"POOLED {int(EVENT_WEIGHT*100)}%/event")

        # POOLED-100: full equity each night, concurrent events split equally
        pooled100 = []
        for d in all_days:
            evs = by_night[d]
            w = 1.0 / len(evs)
            pooled100.append((d, sum(w * r for _, r in evs)))
        book_stats(pooled100, years, "POOLED 100%/night")

        if cost_bps == 5:
            # kill test 1: drop 5 best single-event contributions (POOLED book)
            flat = sorted(
                ((d, sym, r) for d, evs in by_night.items() for sym, r in evs),
                key=lambda x: x[2])
            drop = {(d, sym) for d, sym, _ in flat[-5:]}
            pooled_k = []
            for d in all_days:
                evs = [(s, r) for s, r in by_night[d] if (d, s) not in drop]
                if not evs and by_night[d]:
                    pooled_k.append((d, 0.0))
                    continue
                w = min(EVENT_WEIGHT, 1.0 / len(by_night[d]))
                pooled_k.append((d, sum(w * r for _, r in evs)))
            book_stats(pooled_k, years, "POOLED drop-top-5 events")
            print("    dropped:", ", ".join(f"{s} {d} {r*100:+.1f}%"
                                            for d, s, r in flat[-5:]))

            # kill test 2: drop the single best name entirely
            contrib = {}
            for sym, gaps in per_name.items():
                eqn = 1.0
                for _, g in gaps:
                    eqn *= g * (1 - c)
                contrib[sym] = eqn
            best = max(contrib, key=contrib.get)
            pooled_nb = []
            for d in all_days:
                evs = [(s, r) for s, r in by_night[d] if s != best]
                if not evs:
                    continue
                w = min(EVENT_WEIGHT, 1.0 / len(by_night[d]))
                pooled_nb.append((d, sum(w * r for _, r in evs)))
            book_stats(pooled_nb, years, f"POOLED minus {best}")

            # per-name reference books (full capital per event)
            print("  --- per-name (100% capital, 5 bps) ---")
            for sym in sorted(per_name, key=lambda s: -contrib[s]):
                book_stats([(d, g * (1 - c) - 1) for d, g in per_name[sym]],
                           years, f"  {sym}")


if __name__ == "__main__":
    main()
