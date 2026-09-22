#!/usr/bin/env python3
"""TQQQ 'just buy 3x and hold' kill-test — The Backtest Graveyard.

Question tested (the viral retail belief): "Just buy TQQQ (3x leveraged QQQ) and hold forever —
leverage means more money." We compare buy-and-hold TQQQ against the honest baseline (buy-and-hold
QQQ), a 200-day regime filter ('smart leverage'), and a 50/50 TQQQ/cash monthly rebalance, over the
full available daily history. Ranking is by MAR (CAGR / MaxDD%) — the channel's standard — NOT raw
return, because a strategy that makes more money while risking ruin has not made you richer in any
usable sense.

Data (daily total-return-adjusted closes):
  Primary : Yahoo Finance chart API (adjusted close, splits+dividends), TQQQ inception 2010-02-11
            -> today. Cached to yf_TQQQ.csv / yf_QQQ.csv on first run.
  Fallback: Alpaca SIP daily bars (adjustment=all) via ~/.alpaca/credentials — only reaches
            2016-01-04, so the pre-2016 bull run is lost; the script prints which source/window
            it actually used.

All strategies are long-only, decided on the daily close, with a realistic 'cash earns ~0%' floor
(a small T-bill drift is optional and OFF by default so results are conservative for the leverage
myth). No live-bot references, no secrets in the file, no PII.

Kill-tests included:
  1. Drawdown reality      — TQQQ max DD, time-underwater, and the +recovery% a -DD% requires.
  2. Volatility decay      — 3x daily-compounded QQQ (a self-built synthetic) vs actual TQQQ, and
                             TQQQ's ACTUAL multiple of QQQ's total return (it is NOT 3x).
  3. Entry/sequence risk   — same buy-and-hold TQQQ from several start dates; huge dispersion.
  4. Cost sensitivity      — synthetic 3xQQQ minus ~0.95%/yr (expense+financing) vs actual TQQQ.
"""
import csv, json, math, os, sys, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
TRADING_DAYS = 252


# --------------------------------------------------------------------------------------
# Data loading
# --------------------------------------------------------------------------------------
def _yahoo_csv_path(sym):
    return os.path.join(HERE, f"yf_{sym}.csv")


def _fetch_yahoo(sym):
    """Fetch daily adjusted history from Yahoo's public chart API; cache to CSV. Returns True/False."""
    import time, urllib.request
    UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           "?period1=1262304000&period2=1790000000&interval=1d"
           "&events=div%2Csplit&includeAdjustedClose=true")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    for attempt in range(6):
        try:
            raw = urllib.request.urlopen(req, timeout=30).read().decode()
            if raw.strip().startswith("{"):
                d = json.loads(raw)
                r = d["chart"]["result"][0]
                ts = r["timestamp"]; q = r["indicators"]["quote"][0]
                adj = r["indicators"].get("adjclose", [{}])[0].get("adjclose")
                out = ["Date,Open,High,Low,Close,AdjClose,Volume"]
                for i, t in enumerate(ts):
                    c = q["close"][i]
                    if c is None:
                        continue
                    date = dt.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")
                    a = adj[i] if adj and adj[i] is not None else c
                    out.append(f"{date},{q['open'][i]},{q['high'][i]},{q['low'][i]},{c},{a},{q['volume'][i]}")
                with open(_yahoo_csv_path(sym), "w") as f:
                    f.write("\n".join(out) + "\n")
                return True
        except Exception:
            pass
        time.sleep(8 * (attempt + 1))
    return False


def _fetch_alpaca(sym):
    """Fallback: Alpaca SIP daily bars, split/div adjusted. Reaches ~2016-01-04. Cache to CSV."""
    import urllib.request
    creds = os.path.expanduser("~/.alpaca/credentials")
    key = os.getenv("ALPACA_KEY"); sec = os.getenv("ALPACA_SECRET")
    if not (key and sec) and os.path.exists(creds):
        for line in open(creds):
            line = line.strip()
            if "=" not in line or line.startswith("#"):
                continue
            k, v = [x.strip() for x in line.split("=", 1)]
            if k == "ALPACA_KEY":
                key = key or v
            if k == "ALPACA_SECRET":
                sec = sec or v
    if not (key and sec):
        return False
    rows = []
    token = None
    base = (f"https://data.alpaca.markets/v2/stocks/{sym}/bars?timeframe=1Day"
            "&start=2010-01-01T00:00:00Z&limit=10000&adjustment=all&feed=sip")
    while True:
        url = base + (f"&page_token={token}" if token else "")
        req = urllib.request.Request(url, headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec})
        d = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
        for b in d.get("bars", []) or []:
            date = b["t"][:10]
            rows.append(f"{date},{b['o']},{b['h']},{b['l']},{b['c']},{b['c']},{b['v']}")
        token = d.get("next_page_token")
        if not token:
            break
    if not rows:
        return False
    with open(_yahoo_csv_path(sym), "w") as f:
        f.write("Date,Open,High,Low,Close,AdjClose,Volume\n")
        f.write("\n".join(rows) + "\n")
    return True


def load_series(sym):
    """Return (dates[list], adjclose[list]) using cache, else Yahoo, else Alpaca. Prints the source."""
    path = _yahoo_csv_path(sym)
    src = "cache"
    if not os.path.exists(path):
        if _fetch_yahoo(sym):
            src = "yahoo"
        elif _fetch_alpaca(sym):
            src = "alpaca-sip"
        else:
            sys.exit(f"FATAL: could not obtain data for {sym} from Yahoo or Alpaca.")
    dates, px = [], []
    with open(path) as f:
        rd = csv.DictReader(f)
        for row in rd:
            try:
                a = float(row["AdjClose"])
            except (ValueError, KeyError):
                continue
            dates.append(row["Date"])
            px.append(a)
    load_series._src[sym] = src
    return dates, px


load_series._src = {}


def align(d1, p1, d2, p2):
    """Inner-join two date-indexed series on common dates; returns (dates, a1, a2)."""
    m2 = dict(zip(d2, p2))
    D, A, B = [], [], []
    for d, a in zip(d1, p1):
        if d in m2:
            D.append(d); A.append(a); B.append(m2[d])
    return D, A, B


# --------------------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------------------
def daily_rets(equity):
    return [equity[i] / equity[i - 1] - 1.0 for i in range(1, len(equity))]


def cagr(equity, dates):
    years = (dt.date.fromisoformat(dates[-1]) - dt.date.fromisoformat(dates[0])).days / 365.25
    return (equity[-1] / equity[0]) ** (1 / years) - 1 if years > 0 else float("nan")


def max_drawdown(equity):
    """Return (maxDD as negative frac, peak_date_idx, trough_idx)."""
    peak = equity[0]; peak_i = 0; mdd = 0.0; mdd_peak = 0; mdd_trough = 0
    for i, v in enumerate(equity):
        if v > peak:
            peak = v; peak_i = i
        dd = v / peak - 1.0
        if dd < mdd:
            mdd = dd; mdd_peak = peak_i; mdd_trough = i
    return mdd, mdd_peak, mdd_trough


def longest_underwater(equity, dates):
    """Longest run (in calendar days) below a prior peak before a NEW high is made."""
    peak = equity[0]; peak_date = dates[0]; longest = 0; longest_span = (None, None)
    cur_start = None
    for i, v in enumerate(equity):
        if v >= peak:
            if cur_start is not None:
                span = (dt.date.fromisoformat(dates[i]) - dt.date.fromisoformat(peak_date)).days
                if span > longest:
                    longest = span; longest_span = (peak_date, dates[i])
                cur_start = None
            peak = v; peak_date = dates[i]
        else:
            if cur_start is None:
                cur_start = dates[i]
    # still underwater at end
    if cur_start is not None:
        span = (dt.date.fromisoformat(dates[-1]) - dt.date.fromisoformat(peak_date)).days
        if span > longest:
            longest = span; longest_span = (peak_date, dates[-1] + " (still under)")
    return longest, longest_span


def sortino(rets, target=0.0):
    downs = [min(0.0, r - target) for r in rets]
    dd = math.sqrt(sum(x * x for x in downs) / len(downs))
    if dd == 0:
        return float("inf")
    mean = sum(rets) / len(rets)
    return (mean - target) / dd * math.sqrt(TRADING_DAYS)


def ann_vol(rets):
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(TRADING_DAYS)


def worst_cal_year(equity, dates):
    by_year = {}
    for i in range(1, len(equity)):
        y = dates[i][:4]
        by_year.setdefault(y, []).append(equity[i] / equity[i - 1])
    yr_ret = {y: (math.prod(v) - 1.0) for y, v in by_year.items()}
    wy = min(yr_ret, key=yr_ret.get)
    return wy, yr_ret[wy], yr_ret


def stats(equity, dates, label):
    rets = daily_rets(equity)
    tot = equity[-1] / equity[0] - 1.0
    c = cagr(equity, dates)
    mdd, pk, tr = max_drawdown(equity)
    mar = c / abs(mdd) if mdd != 0 else float("nan")
    so = sortino(rets)
    vol = ann_vol(rets)
    wy, wyr, _ = worst_cal_year(equity, dates)
    uw_days, uw_span = longest_underwater(equity, dates)
    return {
        "label": label, "total_return": tot, "cagr": c, "mar": mar, "sortino": so,
        "max_dd": mdd, "max_dd_peak": dates[pk], "max_dd_trough": dates[tr],
        "vol": vol, "worst_year": wy, "worst_year_ret": wyr,
        "underwater_days": uw_days, "underwater_span": uw_span,
        "final": equity[-1],
    }


# --------------------------------------------------------------------------------------
# Strategies (all long-only, daily close)
# --------------------------------------------------------------------------------------
def bh(prices):
    """Buy and hold: equity normalized to 1.0."""
    return [p / prices[0] for p in prices]


def sma(prices, n):
    out = [None] * len(prices)
    s = 0.0
    for i, p in enumerate(prices):
        s += p
        if i >= n:
            s -= prices[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def regime_filter(tqqq_px, qqq_px, n=200, cash_daily=0.0):
    """Hold TQQQ when QQQ closed >= its n-day SMA yesterday, else cash. Decision uses only info
    available at the close we act on (yesterday's SMA state -> today's holding)."""
    qsma = sma(qqq_px, n)
    eq = [1.0]
    for i in range(1, len(tqqq_px)):
        # position for day i is decided by regime state as of close i-1
        in_mkt = qsma[i - 1] is not None and qqq_px[i - 1] >= qsma[i - 1]
        r = (tqqq_px[i] / tqqq_px[i - 1] - 1.0) if in_mkt else cash_daily
        eq.append(eq[-1] * (1 + r))
    return eq


def half_cash_monthly(tqqq_px, dates, cash_daily=0.0):
    """50/50 TQQQ/cash, rebalanced monthly to 50/50."""
    eq_t = 0.5; eq_c = 0.5
    equity = [1.0]
    for i in range(1, len(tqqq_px)):
        eq_t *= tqqq_px[i] / tqqq_px[i - 1]
        eq_c *= (1 + cash_daily)
        # rebalance on first trading day of a new month
        if dates[i][:7] != dates[i - 1][:7]:
            tot = eq_t + eq_c
            eq_t = eq_c = tot / 2.0
        equity.append(eq_t + eq_c)
    return equity


def synthetic_3x(qqq_px, drag_annual=0.0):
    """Self-built 3x DAILY-reset leverage on QQQ, minus an optional annual drag (expense+financing).
    This reproduces the daily-reset + cost mechanics that make TQQQ != 3x the index's total return."""
    daily_drag = (1 + drag_annual) ** (1 / TRADING_DAYS) - 1.0
    eq = [1.0]
    for i in range(1, len(qqq_px)):
        qr = qqq_px[i] / qqq_px[i - 1] - 1.0
        eq.append(eq[-1] * (1 + 3 * qr - daily_drag))
    return eq


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------
def fmt_pct(x):
    return f"{x*100:,.1f}%"


def main():
    dt_t, px_t = load_series("TQQQ")
    dt_q, px_q = load_series("QQQ")
    D, T, Q = align(dt_t, px_t, dt_q, px_q)
    print(f"Data source: TQQQ={load_series._src['TQQQ']}  QQQ={load_series._src['QQQ']}")
    print(f"Common window: {D[0]} -> {D[-1]}  ({len(D)} trading days, "
          f"{(dt.date.fromisoformat(D[-1])-dt.date.fromisoformat(D[0])).days/365.25:.1f} yrs)\n")

    strategies = {}
    strategies["1. TQQQ buy&hold (the myth)"] = bh(T)
    strategies["2. QQQ buy&hold (baseline)"] = bh(Q)
    strategies["3. TQQQ w/ QQQ>200d filter"] = regime_filter(T, Q, 200)
    strategies["4. 50/50 TQQQ/cash monthly"] = half_cash_monthly(T, D)

    results = {name: stats(eq, D, name) for name, eq in strategies.items()}
    ranked = sorted(results.values(), key=lambda s: (-(s["mar"] if s["mar"] == s["mar"] else -1)))

    print("=" * 108)
    print("RESULTS  (ranked by MAR = CAGR / MaxDD%,  the channel standard)")
    print("=" * 108)
    hdr = f"{'Strategy':<32}{'TotRet':>11}{'CAGR':>9}{'MAR':>7}{'Sortino':>9}{'MaxDD':>9}{'WorstYr':>13}{'UW days':>9}{'Vol':>8}"
    print(hdr)
    print("-" * 108)
    for s in ranked:
        passes = "PASS" if (s["mar"] >= 0.5 and s["sortino"] >= 1.0) else "fail"
        print(f"{s['label']:<32}{fmt_pct(s['total_return']):>11}{fmt_pct(s['cagr']):>9}"
              f"{s['mar']:>7.2f}{s['sortino']:>9.2f}{fmt_pct(s['max_dd']):>9}"
              f"{s['worst_year']+' '+fmt_pct(s['worst_year_ret']):>13}{s['underwater_days']:>9}"
              f"{fmt_pct(s['vol']):>8}  [{passes}]")
    print("-" * 108)
    print("Channel bar to 'pass': MAR >= 0.50 AND Sortino >= 1.00.  QQQ buy&hold is the yardstick.\n")

    # ---- KILL-TEST 1: drawdown reality ----
    tq = results["1. TQQQ buy&hold (the myth)"]
    qq = results["2. QQQ buy&hold (baseline)"]
    recovery_needed = 1 / (1 + tq["max_dd"]) - 1
    print("KILL-TEST 1 — THE DRAWDOWN REALITY")
    print(f"  TQQQ max drawdown: {fmt_pct(tq['max_dd'])}  "
          f"(peak {tq['max_dd_peak']} -> trough {tq['max_dd_trough']})")
    print(f"  A {fmt_pct(tq['max_dd'])} drawdown requires a +{recovery_needed*100:,.0f}% gain just to get back to even.")
    print(f"  Longest time underwater: {tq['underwater_days']} calendar days "
          f"(~{tq['underwater_days']/365.25:.1f} yrs)  span {tq['underwater_span']}")
    print(f"  (QQQ's worst DD over the same window: {fmt_pct(qq['max_dd'])}, "
          f"needs +{(1/(1+qq['max_dd'])-1)*100:,.0f}% to recover.)\n")

    # ---- KILL-TEST 2: volatility decay / path dependence ----
    years = (dt.date.fromisoformat(D[-1]) - dt.date.fromisoformat(D[0])).days / 365.25
    qqq_tot = Q[-1] / Q[0]
    tqqq_tot = T[-1] / T[0]
    actual_multiple = (tqqq_tot - 1) / (qqq_tot - 1)
    synth = synthetic_3x(Q, drag_annual=0.0)
    synth_costed = synthetic_3x(Q, drag_annual=0.0095)
    implied_drag = (tqqq_tot / synth[-1]) ** (1 / years) - 1  # actual vs costless 3x, annualized
    print("KILL-TEST 2 — VOLATILITY DECAY / PATH DEPENDENCE (3x daily != 3x the index)")
    print(f"  QQQ total return over window:  {fmt_pct(qqq_tot-1)}  (x{qqq_tot:.2f})")
    print(f"  TQQQ total return over window: {fmt_pct(tqqq_tot-1)}  (x{tqqq_tot:.2f})")
    print(f"  'Naive 3x on the RETURN' would be +{(qqq_tot-1)*3*100:,.0f}% (x{1+(qqq_tot-1)*3:.2f}).")
    print(f"  Actual TQQQ multiple of QQQ's total return: {actual_multiple:.2f}x  (NOT 3.0x) — in this")
    print(f"    bull-dominated window, sustained uptrends compounded leverage ABOVE 3x on the way up.")
    # the OTHER side of path-dependence: the 2022 collapse
    pk_i = [i for i, d in enumerate(D) if d == tq["max_dd_peak"]][0]
    tr_i = [i for i, d in enumerate(D) if d == tq["max_dd_trough"]][0]
    q_seg = Q[tr_i] / Q[pk_i] - 1
    t_seg = T[tr_i] / T[pk_i] - 1
    seg_mult = t_seg / q_seg
    print(f"  Through the 2022 collapse ({tq['max_dd_peak']}->{tq['max_dd_trough']}): "
          f"QQQ {fmt_pct(q_seg)}, TQQQ {fmt_pct(t_seg)} = {seg_mult:.2f}x the loss.")
    print(f"    Same 3x wrapper: >3x MORE money in the climb, ~{seg_mult:.1f}x MORE pain in the crash.")
    print(f"  Self-built 3x daily-reset on QQQ (NO cost):   x{synth[-1]:.2f}")
    print(f"  Self-built 3x daily-reset minus 0.95%/yr:     x{synth_costed[-1]:.2f}")
    print(f"  Actual TQQQ:                                   x{tqqq_tot:.2f}")
    print(f"  -> A COSTLESS 3x would have made x{synth[-1]:.0f}; TQQQ made x{tqqq_tot:.0f} — barely half.")
    print(f"     Implied all-in drag of the real wrapper vs a costless 3x: ~{implied_drag*100:.1f}%/yr.")
    print(f"     (0.84% sticker expense + financing on the 2x borrowed notional, which BALLOONS when")
    print(f"      rates rise — exactly when a leveraged long is already bleeding — plus my synthetic's")
    print(f"      QQQ-total-return base overstates the price-index TQQQ actually tracks by ~1.5-2%/yr.)\n")

    # ---- KILL-TEST 3: entry / sequence sensitivity ----
    print("KILL-TEST 3 — ENTRY / SEQUENCE SENSITIVITY (same 'buy & hold TQQQ', different start)")
    starts = ["2010-02-11", "2018-01-02", "2021-01-04", "2022-01-03", "2022-12-28"]
    date_to_i = {d: i for i, d in enumerate(D)}
    def nearest(dstr):
        cand = [d for d in D if d >= dstr]
        return cand[0] if cand else None
    seq_rows = []
    for s in starts:
        d0 = nearest(s)
        if not d0:
            continue
        i0 = date_to_i[d0]
        eq = [p / T[i0] for p in T[i0:]]
        sub_dates = D[i0:]
        st = stats(eq, sub_dates, f"start {d0}")
        seq_rows.append((d0, st))
        print(f"  bought {d0}: total {fmt_pct(st['total_return']):>10}  CAGR {fmt_pct(st['cagr']):>8}"
              f"  MaxDD {fmt_pct(st['max_dd']):>8}  ({sub_dates[0]}->{sub_dates[-1]})")
    print("  -> Outcome is dominated by WHEN you bought, not by any skill. Same asset, same rule,")
    print("     wildly different fate: buying the 2021 top vs the 2022 bottom is a different universe.\n")

    # ---- KILL-TEST 4: cost sensitivity ----
    print("KILL-TEST 4 — COST SENSITIVITY")
    gap = synth[-1] / synth_costed[-1] - 1
    print(f"  Even the STICKER 0.95%/yr (expense + a light financing assumption) over {years:.1f} yrs")
    print(f"  cuts the synthetic 3x terminal wealth by {fmt_pct(gap)} (x{synth[-1]:.2f} -> x{synth_costed[-1]:.2f}).")
    print(f"  But the REAL implied drag was ~{implied_drag*100:.1f}%/yr (KT2): financing on the borrowed")
    print(f"  2x notional scales with interest rates, so the cost is largest in the years leverage hurts")
    print(f"  most. Cost compounds silently every single day; it is the rent you pay for the wrapper.\n")

    # ---- GREEN keeper ----
    reg = results["3. TQQQ w/ QQQ>200d filter"]
    print("GREEN KEEPER (what the data actually supports)")
    print(f"  200-day regime filter vs naked TQQQ:  MAR {reg['mar']:.2f} vs {tq['mar']:.2f}, "
          f"MaxDD {fmt_pct(reg['max_dd'])} vs {fmt_pct(tq['max_dd'])}, "
          f"Sortino {reg['sortino']:.2f} vs {tq['sortino']:.2f}.")
    print("  Leverage multiplies your PATH, not your edge. The only defensible use of a 3x sleeve is")
    print("  small, capped, and on a bet you can stomach taking to near-zero. A trend filter cuts the")
    print("  worst of the drawdown, but it does not turn leverage into free money.\n")

    # ---- export curve_data.json ----
    def norm(eq):
        return [round(x, 6) for x in eq]
    curve = {
        "meta": {
            "generated": dt.date.today().isoformat(),
            "source_tqqq": load_series._src["TQQQ"],
            "source_qqq": load_series._src["QQQ"],
            "window_start": D[0], "window_end": D[-1],
            "trading_days": len(D),
        },
        "dates": D,
        "curves": {
            "tqqq_buyhold": norm(strategies["1. TQQQ buy&hold (the myth)"]),
            "qqq_buyhold": norm(strategies["2. QQQ buy&hold (baseline)"]),
            "tqqq_200d_filter": norm(strategies["3. TQQQ w/ QQQ>200d filter"]),
        },
        "stats": {
            r["label"]: {
                "total_return": r["total_return"], "cagr": r["cagr"], "mar": r["mar"],
                "sortino": r["sortino"], "max_dd": r["max_dd"], "vol": r["vol"],
                "worst_year": r["worst_year"], "worst_year_ret": r["worst_year_ret"],
                "underwater_days": r["underwater_days"],
                "passes_bar": bool(r["mar"] >= 0.5 and r["sortino"] >= 1.0),
            } for r in results.values()
        },
        "killtests": {
            "tqqq_max_dd": tq["max_dd"],
            "tqqq_recovery_needed": recovery_needed,
            "tqqq_underwater_days": tq["underwater_days"],
            "qqq_total_return": qqq_tot - 1,
            "tqqq_total_return": tqqq_tot - 1,
            "tqqq_actual_multiple_of_qqq": actual_multiple,
            "synth_3x_nocost_x": synth[-1],
            "synth_3x_costed_x": synth_costed[-1],
            "cost_drag_sticker_pct": gap,
            "implied_annual_drag_vs_costless_3x": implied_drag,
            "crash_2022_qqq": q_seg,
            "crash_2022_tqqq": t_seg,
            "crash_2022_amplification": seg_mult,
        },
    }
    with open(os.path.join(HERE, "curve_data.json"), "w") as f:
        json.dump(curve, f)
    print(f"Wrote curve_data.json ({len(D)} dates, 3 curves + scalar stats).")


if __name__ == "__main__":
    main()
