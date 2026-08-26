#!/usr/bin/env python3
"""Point-in-time attention universe for the earnings-night overnight backtest.

Extends overnight_earnings_backtest.py: instead of a hand-picked 14-name universe,
membership is decided EX-ANTE by trailing dollar volume:

  - Base list: ~150 liquid US names across eras (megacaps, meme/retail favorites,
    fallen angels). ADRs excluded by rule (foreign issuers file 6-Ks, not Item-2.02
    8-Ks, so earnings nights can't be detected for them).
  - Attention proxy: mean(close x volume) over trailing 252 trading days (>=120 req).
  - Rebalance quarterly (Jan/Apr/Jul/Oct 1). Top-N names = tradeable that quarter.
  - Trade an earnings night only if the name is in the top-N on the gap morning.
  - Pooled book: 25% of equity per event, same-night cap 100%, 5 bps RT cost.

KNOWN BIASES (disclosed): base list is written today -> delisted/renamed names
(BBBY, FIT, TWTR, SIVB, EXPR...) have no Alpaca bars and silently drop out =
survivorship bias IN FAVOR of the strategy. Alpaca SIP starts 2016 -> first usable
rebalance is 2016-07 (>=120d lookback). A FAIL here is decisive; a PASS is still
generous.
"""

import json
import math
import os
import time
import urllib.request

# SEC EDGAR requires a descriptive User-Agent with contact info. Use your own.
UA = {"User-Agent": "YOUR NAME your-email@example.com (personal research)"}
COST = 0.0005          # 5 bps round trip
EVENT_WEIGHT = 0.25
TOP_NS = [10, 20, 30]  # 20 = primary, declared before running
BARS_START = "2016-01-01"

BASE_LIST = """
AAPL MSFT AMZN GOOGL META NFLX NVDA TSLA AMD MU INTC CSCO ORCL CRM ADBE QCOM AVGO
TXN AMAT LRCX KLAC MRVL ARM PANW SNOW CRWD ZS DDOG NET PLTR U RBLX ABNB UBER LYFT
DASH SHOP XYZ PYPL COIN HOOD SOFI AFRM UPST GME AMC BB NOK SNDL TLRY CGC ACB SPCE
DKNG PENN FUBO WISH CLOV NKLA RIVN LCID PTON ZM DOCU ROKU TDOC TWLO OKTA PINS SNAP
GPRO MRNA BNTX NVAX INO OCGN SAVA JPM BAC WFC C GS MS SCHW XOM CVX OXY BA GE F GM
T VZ DIS PFE JNJ MRK LLY UNH ABBV BMY GILD AMGN BIIB WMT COST TGT HD LOW SBUX MCD
NKE LULU CMG KO PEP PG SMCI MSTR ON MPWR SWKS QRVO WDC STX TER ENPH SEDG FSLR RUN
PLUG FCEL BLNK CHPT KOSS EXPR VXRT RIDE FSR SQ TWTR FIT BBBY SIVB
""".split()


def get_json(url):
    req = urllib.request.Request(url, headers=UA)
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


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
               f"?timeframe=1Day&start={BARS_START}T00:00:00Z&limit=10000"
               f"&adjustment=all&feed=sip")
        if token:
            url += f"&page_token={token}"
        req = urllib.request.Request(
            url, headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec})
        try:
            d = json.loads(urllib.request.urlopen(req, timeout=60).read())
        except Exception:
            return []
        bars += d.get("bars") or []
        token = d.get("next_page_token")
        if not token:
            break
    return bars


def earnings_events(cik):
    sub = get_json(f"https://data.sec.gov/submissions/CIK{cik}.json")
    batches = [sub["filings"]["recent"]]
    for f in sub["filings"].get("files", []):
        batches.append(get_json(f"https://data.sec.gov/submissions/{f['name']}"))
        time.sleep(0.12)
    events = set()
    for b in batches:
        for form, items, acc in zip(b["form"], b["items"], b["acceptanceDateTime"]):
            if form == "8-K" and "2.02" in (items or ""):
                events.add((acc[:10], int(acc[11:13])))
    return sorted(e for e in events if e[0] >= BARS_START)


def build_gaps(events, bars):
    by_date = {b["t"][:10]: b for b in bars}
    days = [b["t"][:10] for b in bars]
    idx = {d: i for i, d in enumerate(days)}
    gaps = []
    for date, hour in events:
        if hour >= 16:
            if date in idx and idx[date] + 1 < len(days):
                d1 = days[idx[date] + 1]
                gaps.append((d1, by_date[d1]["o"] / by_date[date]["c"]))
        elif hour < 9:
            if date in idx and idx[date] > 0:
                d0 = days[idx[date] - 1]
                gaps.append((date, by_date[date]["o"] / by_date[d0]["c"]))
    return gaps


def rebalance_dates():
    out = []
    for y in range(2016, 2027):
        for m in ("01", "04", "07", "10"):
            d = f"{y}-{m}-01"
            if "2016-07-01" <= d <= "2026-07-01":
                out.append(d)
    return out


def years_between(d0, d1):
    from datetime import date
    a = date(*map(int, d0.split("-")))
    b = date(*map(int, d1.split("-")))
    return (b - a).days / 365.25


def book_stats(nights, label):
    if not nights:
        print(f"  {label}: no trades")
        return
    yrs = max(years_between(nights[0][0], nights[-1][0]), 0.5)
    eq, peak, maxdd = 1.0, 1.0, 0.0
    for _, r in nights:
        eq *= 1 + r
        peak = max(peak, eq)
        maxdd = max(maxdd, 1 - eq / peak)
    cagr = eq ** (1 / yrs) - 1
    rets = [r for _, r in nights]
    n = len(rets)
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r < 0]
    pf = sum(wins) / abs(sum(losses)) if losses else float("inf")
    dd = math.sqrt(sum(r * r for r in losses) / n) if losses else 0.0
    sortino = ((sum(rets) / n) / dd) * math.sqrt(n / yrs) if dd else float("inf")
    mar = cagr / maxdd if maxdd else float("inf")
    print(f"  {label:<34} nights={n:<4} cum={eq:7.3f}x CAGR={cagr*100:+6.1f}% "
          f"MaxDD={maxdd*100:5.1f}% MAR={mar:5.2f} Sortino={sortino:5.2f} "
          f"PF={pf:4.2f} WR={len(wins)/n*100:3.0f}%")


def main():
    key, sec = load_alpaca_creds()

    print("Fetching bars for base list...")
    bars = {}
    dead = []
    for sym in BASE_LIST:
        b = fetch_bars(sym, key, sec)
        if len(b) >= 120:
            bars[sym] = b
        else:
            dead.append(sym)
    print(f"  {len(bars)} names with data; {len(dead)} dropped (survivorship holes): "
          + " ".join(dead))

    # dollar-volume series per name
    dv = {s: ([bb["t"][:10] for bb in b], [bb["c"] * bb["v"] for bb in b])
          for s, b in bars.items()}

    import bisect
    universes = {}
    for rd in rebalance_dates():
        ranked = []
        for s, (ds, vs) in dv.items():
            i = bisect.bisect_left(ds, rd)
            lo = max(0, i - 252)
            if i - lo >= 120:
                ranked.append((sum(vs[lo:i]) / (i - lo), s))
        ranked.sort(reverse=True)
        universes[rd] = [s for _, s in ranked]
    rds = sorted(universes)

    for sample in ("2016-07-01", "2018-01-01", "2021-01-01", "2023-07-01", "2026-07-01"):
        print(f"  top-20 @ {sample}: {' '.join(universes[sample][:20])}")

    # earnings events only for names that ever crack the widest top-N
    candidates = sorted({s for rd in rds for s in universes[rd][:max(TOP_NS)]})
    print(f"\nFetching EDGAR events for {len(candidates)} candidate names...")
    tickmap = {v["ticker"]: str(v["cik_str"]).zfill(10)
               for v in get_json("https://www.sec.gov/files/company_tickers.json").values()}
    gaps = {}
    for s in candidates:
        cik = tickmap.get(s)
        if not cik:
            print(f"  !! no CIK for {s}, skipped")
            continue
        gaps[s] = build_gaps(earnings_events(cik), bars[s])
        time.sleep(0.12)

    def universe_at(d):
        i = bisect.bisect_right(rds, d) - 1
        return universes[rds[i]] if i >= 0 else []

    for topn in TOP_NS:
        by_night = {}
        for s, gs in gaps.items():
            for d, g in gs:
                if d >= "2016-07-01" and s in universe_at(d)[:topn]:
                    by_night.setdefault(d, []).append((s, g * (1 - COST) - 1))
        nights = []
        for d in sorted(by_night):
            evs = by_night[d]
            w = min(EVENT_WEIGHT, 1.0 / len(evs))
            nights.append((d, sum(w * r for _, r in evs)))

        print(f"\n=== TOP-{topn} point-in-time universe (5 bps) ===")
        book_stats(nights, f"full 2016-07..2026-08")
        mid = nights[len(nights) // 2][0]
        book_stats([x for x in nights if x[0] < mid], f"first half (to {mid})")
        book_stats([x for x in nights if x[0] >= mid], "second half")
        book_stats([x for x in nights if x[0] >= "2023-08-23"], "last 3y")

        if topn == 20:
            flat = sorted(((d, s, r) for d, evs in by_night.items() for s, r in evs),
                          key=lambda x: x[2])
            drop = {(d, s) for d, s, _ in flat[-5:]}
            nights_k = []
            for d in sorted(by_night):
                evs = [(s, r) for s, r in by_night[d] if (d, s) not in drop]
                w = min(EVENT_WEIGHT, 1.0 / len(by_night[d]))
                nights_k.append((d, sum(w * r for _, r in evs)))
            book_stats(nights_k, "drop-top-5 events")
            print("    dropped:", ", ".join(f"{s} {d} {r*100:+.1f}%"
                                            for d, s, r in flat[-5:]))


if __name__ == "__main__":
    main()
