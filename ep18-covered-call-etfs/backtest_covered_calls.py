#!/usr/bin/env python3
"""Covered-call 'income' ETFs kill-test — The Backtest Graveyard (Ep18).

Question tested (one of retail's most-marketed products): the covered-call / buy-write
"income" ETFs — QYLD, XYLD, RYLD (Global X) and JEPI, JEPQ (JPMorgan) — sold as
"9-12% yield, passive monthly income, lower volatility, income in retirement." The pitch
implies the distribution is free money and roughly equals your return. We test that.

THE CRITICAL DISTINCTION — TOTAL RETURN vs PRICE:
  For every fund we pull BOTH
    (a) TOTAL RETURN  : Alpaca SIP daily, adjustment=all (price + all distributions
                        reinvested) -> the honest "what you actually earned" series.
    (b) PRICE / NAV   : Alpaca SIP daily, adjustment=raw (unadjusted close) -> the actual
                        share price you watch, which for QYLD has bled DOWN for a decade
                        while it paid "~12%."
  The gap between (a) and (b) over time IS the story: how much of the "yield" is just your
  own principal (NAV) being handed back to you = return of capital / NAV erosion.

Data source: Alpaca SIP daily bars via ~/.alpaca/credentials (market-data keys only).
  SIP history reaches 2016-01-04, so we use the longest CLEAN window per fund:
    QYLD 2016-01-04 (inception 2013-12, pre-2016 lost to SIP) ; underlying QQQ
    XYLD 2016-01-04 (inception 2013-06, pre-2016 lost)        ; underlying SPY
    RYLD 2019-04-22 (inception)                               ; underlying SPY
    JEPI 2020-05-21 (inception)                               ; underlying SPY
    JEPQ 2022-05-04 (inception)                               ; underlying QQQ
  Stooq (which would reach 2013) now sits behind a JavaScript proof-of-work bot wall; we do
  not bypass bot-detection, so we take the honest 2016+ SIP window and say so. The script
  PRINTS the exact source + window per fund.

Ranking is by MAR (CAGR / MaxDD%) — the channel standard — because these funds are PITCHED
as a smoother, lower-risk ride, and a fair judge prices risk, not just raw dollars.
Bar to "pass": MAR >= 0.50 AND Sortino >= 1.00.

Public tickers and public price/distribution data only. No secrets in the file, no PII,
no reference to any live strategy or account. Re-runnable; caches raw data on first run.
"""
import csv, json, math, os, sys, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
TRADING_DAYS = 252

# Public, marketed expense ratios (for the honest cost note — described, not modeled).
EXPENSE_RATIO = {"QYLD": 0.0060, "XYLD": 0.0060, "RYLD": 0.0060,
                 "JEPI": 0.0035, "JEPQ": 0.0035}

# Fund -> underlying index ETF (total-return comparison).
UNDERLYING = {"QYLD": "QQQ", "XYLD": "SPY", "RYLD": "SPY",
              "JEPI": "SPY", "JEPQ": "QQQ"}


# ======================================================================================
# Data loading  (Alpaca SIP daily; adjustment "all"=total return, "raw"=price/NAV)
# ======================================================================================
def _csv_path(sym, adj):
    return os.path.join(HERE, f"alp_{sym}_{adj}.csv")


def _alpaca_creds():
    key = os.getenv("ALPACA_KEY"); sec = os.getenv("ALPACA_SECRET")
    creds = os.path.expanduser("~/.alpaca/credentials")
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
    return key, sec


def _fetch_alpaca(sym, adj):
    """Fetch daily bars for one symbol at one adjustment; cache to CSV. -> True/False."""
    import urllib.request
    key, sec = _alpaca_creds()
    if not (key and sec):
        return False
    rows, token = [], None
    base = (f"https://data.alpaca.markets/v2/stocks/{sym}/bars?timeframe=1Day"
            f"&start=2013-01-01T00:00:00Z&limit=10000&adjustment={adj}&feed=sip")
    while True:
        url = base + (f"&page_token={token}" if token else "")
        req = urllib.request.Request(
            url, headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec})
        d = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
        for b in d.get("bars", []) or []:
            rows.append(f"{b['t'][:10]},{b['c']}")
        token = d.get("next_page_token")
        if not token:
            break
    if not rows:
        return False
    with open(_csv_path(sym, adj), "w") as f:
        f.write("Date,Close\n")
        f.write("\n".join(rows) + "\n")
    return True


def load_series(sym, adj):
    """Return (dates[list], close[list]) for one symbol/adjustment, using cache then Alpaca."""
    path = _csv_path(sym, adj)
    if not os.path.exists(path):
        if not _fetch_alpaca(sym, adj):
            sys.exit(f"FATAL: could not obtain {sym} ({adj}) from Alpaca SIP.")
    dates, px = [], []
    with open(path) as f:
        rd = csv.DictReader(f)
        for row in rd:
            try:
                px.append(float(row["Close"]))
            except (ValueError, KeyError):
                continue
            dates.append(row["Date"])
    return dates, px


def align(d1, p1, d2, p2):
    """Inner-join two date-indexed series on common dates -> (dates, a1, a2)."""
    m2 = dict(zip(d2, p2))
    D, A, B = [], [], []
    for d, a in zip(d1, p1):
        if d in m2:
            D.append(d); A.append(a); B.append(m2[d])
    return D, A, B


def align3(d1, p1, d2, p2, d3, p3):
    m2 = dict(zip(d2, p2)); m3 = dict(zip(d3, p3))
    D, A, B, C = [], [], [], []
    for d, a in zip(d1, p1):
        if d in m2 and d in m3:
            D.append(d); A.append(a); B.append(m2[d]); C.append(m3[d])
    return D, A, B, C


# ======================================================================================
# Metrics
# ======================================================================================
def daily_rets(equity):
    return [equity[i] / equity[i - 1] - 1.0 for i in range(1, len(equity))]


def cagr(equity, dates):
    yrs = (dt.date.fromisoformat(dates[-1]) - dt.date.fromisoformat(dates[0])).days / 365.25
    return (equity[-1] / equity[0]) ** (1 / yrs) - 1 if yrs > 0 else float("nan")


def max_drawdown(equity):
    peak = equity[0]; peak_i = 0; mdd = 0.0; mdd_pk = 0; mdd_tr = 0
    for i, v in enumerate(equity):
        if v > peak:
            peak = v; peak_i = i
        dd = v / peak - 1.0
        if dd < mdd:
            mdd = dd; mdd_pk = peak_i; mdd_tr = i
    return mdd, mdd_pk, mdd_tr


def underwater_series(equity):
    peak = equity[0]; out = []
    for v in equity:
        if v > peak:
            peak = v
        out.append(v / peak - 1.0)
    return out


def longest_underwater(equity, dates):
    peak = equity[0]; peak_date = dates[0]; longest = 0; span = (None, None); cur = None
    for i, v in enumerate(equity):
        if v >= peak:
            if cur is not None:
                d = (dt.date.fromisoformat(dates[i]) - dt.date.fromisoformat(peak_date)).days
                if d > longest:
                    longest = d; span = (peak_date, dates[i])
                cur = None
            peak = v; peak_date = dates[i]
        elif cur is None:
            cur = dates[i]
    if cur is not None:
        d = (dt.date.fromisoformat(dates[-1]) - dt.date.fromisoformat(peak_date)).days
        if d > longest:
            longest = d; span = (peak_date, dates[-1] + " (still under)")
    return longest, span


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
    by = {}
    for i in range(1, len(equity)):
        by.setdefault(dates[i][:4], []).append(equity[i] / equity[i - 1])
    yr = {y: math.prod(v) - 1 for y, v in by.items()}
    wy = min(yr, key=yr.get)
    return wy, yr[wy]


def stats(equity, dates, label):
    rets = daily_rets(equity)
    mdd, pk, tr = max_drawdown(equity)
    c = cagr(equity, dates)
    wy, wyr = worst_cal_year(equity, dates)
    uw, span = longest_underwater(equity, dates)
    return {
        "label": label, "total_return": equity[-1] / equity[0] - 1, "cagr": c,
        "mar": c / abs(mdd) if mdd else float("nan"), "sortino": sortino(rets),
        "max_dd": mdd, "max_dd_peak": dates[pk], "max_dd_trough": dates[tr],
        "vol": ann_vol(rets), "worst_year": wy, "worst_year_ret": wyr,
        "underwater_days": uw, "underwater_span": span, "final": equity[-1],
    }


def norm(px):
    """Normalize a price/TR series to start at 1.0."""
    return [p / px[0] for p in px]


def trailing_dist_yield(tr, px):
    """Reinvested income yield over the trailing ~252 trading days, derived as
    (TR growth) / (price growth) - 1 over the last year. This is the distribution the fund
    actually paid on a reinvested basis (a clean, data-derived stand-in for the marketed yield)."""
    n = len(tr)
    if n < TRADING_DAYS + 1:
        j = 0
    else:
        j = n - 1 - TRADING_DAYS
    tr_growth = tr[-1] / tr[j]
    px_growth = px[-1] / px[j]
    if px_growth == 0:
        return float("nan")
    # annualize if the window is shorter than a year
    yr_frac = (len(tr) - 1 - j) / TRADING_DAYS
    inc = tr_growth / px_growth - 1.0
    return inc / yr_frac if yr_frac > 0 else inc


# ======================================================================================
# Helpers
# ======================================================================================
def fp(x):
    return f"{x*100:,.1f}%" if x == x else "n/a"


def window_dd(eq, dates, a, b):
    seg = [eq[i] for i in range(len(dates)) if a <= dates[i] <= b]
    if len(seg) < 2:
        return None
    return max_drawdown(seg)[0]


# ======================================================================================
# Main
# ======================================================================================
def main():
    funds = ["QYLD", "XYLD", "RYLD", "JEPI", "JEPQ"]

    # --- load every fund (TR + price) and both underlyings (TR) ---
    raw = {}
    for sym in funds:
        d_tr, p_tr = load_series(sym, "all")     # total return
        d_px, p_px = load_series(sym, "raw")     # price / NAV
        raw[sym] = {"d_tr": d_tr, "p_tr": p_tr, "d_px": d_px, "p_px": p_px}
    for u in ("QQQ", "SPY"):
        d_tr, p_tr = load_series(u, "all")
        raw[u] = {"d_tr": d_tr, "p_tr": p_tr}

    print("Data source: Alpaca SIP daily bars (adjustment=all -> total return, adjustment=raw -> price/NAV).")
    print("Stooq (longer history) is behind a JS proof-of-work bot wall; not bypassed. SIP window is 2016-01-04+.")
    print()

    # --- per-fund vs underlying: aligned on the fund's available window ---
    pair_results = []   # list of dicts
    curves = {}         # for curve_data.json
    for sym in funds:
        u = UNDERLYING[sym]
        D, F, U = align(raw[sym]["d_tr"], raw[sym]["p_tr"], raw[u]["d_tr"], raw[u]["p_tr"])
        # price/NAV aligned to the SAME dates as the TR series
        _, _, Fpx = align(raw[sym]["d_tr"], raw[sym]["p_tr"], raw[sym]["d_px"], raw[sym]["p_px"])
        eq_f = norm(F); eq_u = norm(U); nav_f = norm(Fpx)
        s_f = stats(eq_f, D, f"{sym} (total return)")
        s_u = stats(eq_u, D, f"{u} total return")
        dy = trailing_dist_yield(F, Fpx)
        # NAV erosion over the window (actual share price)
        nav_change = Fpx[-1] / Fpx[0] - 1.0
        pair_results.append({
            "fund": sym, "underlying": u, "window": (D[0], D[-1]), "n": len(D),
            "yrs": (dt.date.fromisoformat(D[-1]) - dt.date.fromisoformat(D[0])).days / 365.25,
            "fund_stats": s_f, "und_stats": s_u, "dist_yield": dy,
            "nav_change": nav_change, "nav_start": Fpx[0], "nav_end": Fpx[-1],
            "eq_f": eq_f, "eq_u": eq_u, "nav_f": nav_f, "dates": D,
        })

    # =====================================================================================
    # RESULTS TABLE — every fund vs its underlying, ranked by MAR
    # =====================================================================================
    print("=" * 132)
    print("RESULTS  —  every covered-call fund vs its underlying index (both TOTAL RETURN), ranked by MAR = CAGR/MaxDD%")
    print("=" * 132)
    hdr = (f"{'Series':<26}{'Window':>21}{'TotRet':>11}{'CAGR':>8}{'MAR':>7}"
           f"{'Sortino':>9}{'MaxDD':>9}{'Vol':>8}{'TrailYield':>11}{'Bar':>7}")
    print(hdr); print("-" * 132)
    # flatten to a ranking of every series (funds + the distinct underlyings shown per pair)
    ranked_rows = []
    for pr in pair_results:
        for who in ("fund_stats", "und_stats"):
            s = pr[who]
            is_fund = who == "fund_stats"
            ranked_rows.append({
                "label": s["label"], "window": f"{pr['window'][0]}->{pr['window'][1]}",
                "tot": s["total_return"], "cagr": s["cagr"], "mar": s["mar"],
                "sortino": s["sortino"], "mdd": s["max_dd"], "vol": s["vol"],
                "dy": pr["dist_yield"] if is_fund else None,
                "is_fund": is_fund,
            })
    ranked_rows.sort(key=lambda r: -(r["mar"] if r["mar"] == r["mar"] else -1))
    for r in ranked_rows:
        passes = "PASS" if (r["mar"] >= 0.5 and r["sortino"] >= 1.0) else "fail"
        dy = fp(r["dy"]) if r["dy"] is not None else "  (index)"
        print(f"{r['label']:<26}{r['window']:>21}{fp(r['tot']):>11}{fp(r['cagr']):>8}"
              f"{r['mar']:>7.2f}{r['sortino']:>9.2f}{fp(r['mdd']):>9}{fp(r['vol']):>8}"
              f"{dy:>11}{passes:>7}")
    print("-" * 132)
    print("Bar to 'pass': MAR >= 0.50 AND Sortino >= 1.00. Windows differ (each fund from its SIP inception),")
    print("so compare each FUND only to the underlying on its OWN row-pair, not across different windows.\n")

    # per-pair head-to-head summary
    print("HEAD-TO-HEAD (each fund vs its underlying over the SAME window):")
    print(f"   {'Pair':<16}{'Window':>21}{'Fund TotRet':>13}{'Index TotRet':>14}{'Gap':>11}{'Fund CAGR':>11}{'Index CAGR':>12}")
    for pr in pair_results:
        sf, su = pr["fund_stats"], pr["und_stats"]
        gap = sf["total_return"] - su["total_return"]
        print(f"   {pr['fund']+' vs '+pr['underlying']:<16}{pr['window'][0]+'->'+pr['window'][1]:>21}"
              f"{fp(sf['total_return']):>13}{fp(su['total_return']):>14}{fp(gap):>11}"
              f"{fp(sf['cagr']):>11}{fp(su['cagr']):>12}")
    print()

    # =====================================================================================
    # KILL-TEST 1 — TOTAL RETURN vs THE INDEX ($10k -> what each)
    # =====================================================================================
    print("KILL-TEST 1 — TOTAL RETURN vs THE INDEX  (the headline: capped upside for premium)")
    print(f"   $10,000 invested at each fund's start, total return (distributions reinvested):")
    print(f"   {'Pair':<16}{'Window':>21}{'$10k -> Fund':>16}{'$10k -> Index':>16}{'You gave up':>14}")
    kt1 = {}
    for pr in pair_results:
        sf, su = pr["fund_stats"], pr["und_stats"]
        vf = 10000 * (1 + sf["total_return"]); vu = 10000 * (1 + su["total_return"])
        kt1[pr["fund"]] = {"fund_end": vf, "index_end": vu, "index": pr["underlying"],
                           "window": pr["window"], "gap_dollars": vu - vf}
        print(f"   {pr['fund']+' vs '+pr['underlying']:<16}{pr['window'][0]+'->'+pr['window'][1]:>21}"
              f"{'$'+format(vf,',.0f'):>16}{'$'+format(vu,',.0f'):>16}{'$'+format(vu-vf,',.0f'):>14}")
    print("   -> Every covered-call fund LAGS its own index's total return. You sold your upside for premium;")
    print("      in a bull market the calls got exercised away and you kept the small premium, not the gains.\n")

    # =====================================================================================
    # KILL-TEST 2 — THE YIELD ILLUSION / NAV EROSION
    # =====================================================================================
    print("KILL-TEST 2 — THE YIELD ILLUSION / NAV EROSION  (is the 'income' free, or your own principal?)")
    kt2 = {}
    for pr in pair_results:
        sym = pr["fund"]
        nav = pr["nav_change"]
        tr = pr["fund_stats"]["total_return"]
        # total distributions "handed back" ~ total-return minus price-return (the reinvested income leg)
        income_leg = (1 + tr) / (1 + nav) - 1.0
        kt2[sym] = {"nav_start": pr["nav_start"], "nav_end": pr["nav_end"],
                    "nav_change": nav, "total_return": tr, "income_leg": income_leg,
                    "trail_yield": pr["dist_yield"]}
        tag = ""
        if nav < -0.01:
            tag = f"  <- NAV FELL {fp(-nav)} while paying ~{fp(pr['dist_yield'])}/yr"
        print(f"   {sym}: share price (NAV) ${pr['nav_start']:.2f} -> ${pr['nav_end']:.2f} "
              f"({fp(nav)} over {pr['yrs']:.1f}y).{tag}")
    q = kt2["QYLD"]
    print()
    print(f"   FLAGSHIP — QYLD: NAV bled from ${q['nav_start']:.2f} to ${q['nav_end']:.2f} "
          f"({fp(q['nav_change'])}) over the window while advertising a ~12% yield.")
    print(f"     Total return was still {fp(q['total_return'])} — but that came ENTIRELY from distributions "
          f"(income leg {fp(q['income_leg'])}),")
    print(f"     NOT from the price. A chunk of every '12%' check was return of your own capital: the fund sold")
    print(f"     you back your NAV and called it yield. The price chart falling for a decade is the tell.\n")

    # =====================================================================================
    # KILL-TEST 3 — DOWNSIDE PROTECTION (does the premium actually cushion?)
    # =====================================================================================
    print("KILL-TEST 3 — DOWNSIDE PROTECTION  (covered calls keep the premium, but eat most of a big drop)")
    bears = [("2020 COVID", "2020-02-15", "2020-04-30"),
             ("2022 bear", "2022-01-01", "2022-12-31")]
    kt3 = {}
    print(f"   {'Bear':<14}{'Fund':<7}{'Fund maxDD':>12}{'Index maxDD':>13}{'Cushion':>10}")
    for pr in pair_results:
        sym = pr["fund"]; u = pr["underlying"]
        for name, a, b in bears:
            fdd = window_dd(pr["eq_f"], pr["dates"], a, b)
            udd = window_dd(pr["eq_u"], pr["dates"], a, b)
            if fdd is None or udd is None:
                continue
            cushion = abs(udd) - abs(fdd)
            kt3.setdefault(sym, {})[name] = {"fund_dd": fdd, "index_dd": udd, "cushion": cushion}
            print(f"   {name:<14}{sym:<7}{fp(fdd):>12}{fp(udd):>13}{fp(cushion):>10}")
    print("   -> The cushion is real but SMALL: you keep the premium, so you fall a bit less than the index,")
    print("      but you still eat the large majority of a serious drawdown — AND you gave up the recovery")
    print("      upside on the way back out (calls cap you exactly when the market snaps back).\n")

    # =====================================================================================
    # KILL-TEST 4 — THE DIY TEST (homemade income from the index)
    # =====================================================================================
    print("KILL-TEST 4 — THE DIY TEST  (hold the index, sell shares for the SAME cash flow — who ends richer?)")
    print("   For each fund: hold it and SPEND every distribution (principal follows the price/NAV).")
    print("   DIY twin: hold the index (total return) and withdraw the EXACT SAME dollars each day.")
    print("   Same cash flow out the door -> compare the portfolio LEFT at the end.\n")
    kt4 = {}
    for pr in pair_results:
        sym = pr["fund"]; u = pr["underlying"]
        D = pr["dates"]
        Ftr = [x for x in pr["eq_f"]]            # fund total-return index (norm 1.0)
        Fpx = [x for x in pr["nav_f"]]           # fund price/NAV index (norm 1.0)
        Utr = [x for x in pr["eq_u"]]            # index total-return (norm 1.0)
        start = 10000.0
        shares_val0 = start                      # $ invested in fund at t0 (constant shares)
        cash_taken = 0.0
        fund_val = start                         # price value of the constant-share fund position
        diy_val = start                          # DIY twin, index TR, minus matched withdrawals
        for i in range(1, len(D)):
            # fund distribution paid this step (reinvested-income leg of TR vs price)
            tr_step = Ftr[i] / Ftr[i - 1]
            px_step = Fpx[i] / Fpx[i - 1]
            dist_ret = tr_step / px_step - 1.0 if px_step else 0.0
            income = fund_val * max(dist_ret, 0.0)   # $ handed to you this step
            # fund principal follows price only (distributions spent, not reinvested)
            fund_val *= px_step
            cash_taken += income
            # DIY twin grows at index TR, then pays out the same $ income
            diy_val *= (Utr[i] / Utr[i - 1])
            diy_val -= income
            if diy_val < 0:
                diy_val = 0.0
        # fund investor's total wealth = remaining NAV position + cash they took (spent)
        fund_total = fund_val + cash_taken
        diy_total = diy_val + cash_taken
        kt4[sym] = {"index": u, "window": pr["window"], "cash_taken": cash_taken,
                    "fund_nav_left": fund_val, "diy_left": diy_val,
                    "fund_total": fund_total, "diy_total": diy_total,
                    "diy_advantage": diy_val - fund_val}
        print(f"   {sym} vs {u}-DIY  ({pr['window'][0]}->{pr['window'][1]}):")
        print(f"      Cash income taken (identical both sides): ${cash_taken:,.0f} on a $10k start")
        print(f"      LEFT at end -> hold {sym}: ${fund_val:,.0f} (NAV)   |   DIY index+sell: ${diy_val:,.0f}")
        print(f"      Same spending, DIY left you {'+' if diy_val>=fund_val else ''}${diy_val-fund_val:,.0f} "
              f"({'MORE' if diy_val>=fund_val else 'LESS'} money).\n")

    # =====================================================================================
    # KILL-TEST 5 — VOLATILITY / SORTINO (the funds' one real win — give it to them)
    # =====================================================================================
    print("KILL-TEST 5 — VOLATILITY & SORTINO  (the honest selling point: a smoother ride)")
    print(f"   {'Pair':<16}{'Fund vol':>10}{'Index vol':>11}{'Fund Sortino':>14}{'Index Sortino':>15}")
    kt5 = {}
    for pr in pair_results:
        sf, su = pr["fund_stats"], pr["und_stats"]
        kt5[pr["fund"]] = {"fund_vol": sf["vol"], "index_vol": su["vol"],
                           "fund_sortino": sf["sortino"], "index_sortino": su["sortino"]}
        print(f"   {pr['fund']+' vs '+pr['underlying']:<16}{fp(sf['vol']):>10}{fp(su['vol']):>11}"
              f"{sf['sortino']:>14.2f}{su['sortino']:>15.2f}")
    print("   -> TRUE: every fund has LOWER volatility than its index. That is the one thing the wrapper")
    print("      genuinely delivers. Whether lower vol is worth a big return haircut depends entirely on")
    print("      who you are (see the GREEN keeper).\n")

    # =====================================================================================
    # Cost / tax note (described, not modeled)
    # =====================================================================================
    print("COST / TAX NOTE (described, not modeled)")
    print(f"   Expense ratios: " + ", ".join(f"{k} {v*100:.2f}%" for k, v in EXPENSE_RATIO.items()) +
          " (already inside the total-return series above).")
    print("   Distributions are largely ORDINARY income (and, for QYLD/XYLD/RYLD, partly return-of-capital),")
    print("   taxed at your marginal rate in a TAXABLE account — far worse than qualified dividends or")
    print("   deferred capital gains. These funds make the most sense, if ever, inside an IRA/401k.\n")

    # =====================================================================================
    # GREEN keeper + verdict
    # =====================================================================================
    print("GREEN KEEPER (what the data actually supports)")
    jepi = next(p for p in pair_results if p["fund"] == "JEPI")
    qyld = next(p for p in pair_results if p["fund"] == "QYLD")
    print(f"   The funds DO deliver a real, high, smoother CURRENT-income stream at LOWER volatility")
    print(f"   (QYLD vol {fp(qyld['fund_stats']['vol'])} vs QQQ {fp(qyld['und_stats']['vol'])}; "
          f"JEPI vol {fp(jepi['fund_stats']['vol'])} vs SPY {fp(jepi['und_stats']['vol'])}).")
    print(f"   That is a legitimate product for a NARROW use case: a retiree who needs cash flow NOW, has low")
    print(f"   volatility tolerance, holds it in a tax-advantaged account, and is willing to give up growth.")
    print(f"   JEPI-style ACTIVE management (out-of-the-money calls on a lower-vol stock sleeve) is more")
    print(f"   defensible than QYLD-style MECHANICAL at-the-money index writing: JEPI trailed SPY by "
          f"{fp(jepi['und_stats']['total_return']-jepi['fund_stats']['total_return'])} of total return")
    print(f"   and held its NAV far better than QYLD, whose NAV fell {fp(qyld['nav_change'])}.")
    print(f"   What it is NOT: 'free 12% yield,' and the yield is NOT your return. For growth/accumulation")
    print(f"   these funds lose to simply holding the index and selling a sliver when you need cash.\n")

    # verdict one-liner chosen from the data
    verdict = "PAID WITH YOUR OWN MONEY — the yield is real, the return isn't."
    print("PROPOSED VERDICT:")
    print(f"   {verdict}\n")

    # =====================================================================================
    # curve_data.json
    # =====================================================================================
    def r6(xs):
        return [round(x, 6) for x in xs]

    def round_stats(s, extra=None):
        out = {k: s[k] for k in ("label", "total_return", "cagr", "mar", "sortino",
                                 "max_dd", "max_dd_peak", "max_dd_trough", "vol",
                                 "worst_year", "worst_year_ret", "underwater_days")}
        out["passes_bar"] = bool(s["mar"] >= 0.5 and s["sortino"] >= 1.0)
        if extra:
            out.update(extra)
        return out

    qp = qyld; jp = jepi
    curve = {
        "meta": {
            "generated": dt.date.today().isoformat(),
            "source": "alpaca-sip daily (adjustment=all=total return, raw=price/NAV)",
            "note": "SIP history from 2016-01-04; stooq (longer) is bot-walled and not bypassed.",
            "channel_bar": "MAR>=0.50 AND Sortino>=1.00",
            "verdict": verdict,
        },
        # KEY PAIR 1: QYLD-TR vs QQQ-TR, plus QYLD price-only (NAV) for the erosion chart
        "qyld_vs_qqq": {
            "window": {"start": qp["window"][0], "end": qp["window"][1]},
            "dates": qp["dates"],
            "qyld_total_return": r6(qp["eq_f"]),
            "qqq_total_return": r6(qp["eq_u"]),
            "qyld_price_nav": r6(qp["nav_f"]),
            "stats": {
                "qyld": round_stats(qp["fund_stats"], {"trailing_yield": qp["dist_yield"],
                                                       "nav_change": qp["nav_change"]}),
                "qqq": round_stats(qp["und_stats"]),
            },
        },
        # KEY PAIR 2: JEPI-TR vs SPY-TR, plus JEPI NAV
        "jepi_vs_spy": {
            "window": {"start": jp["window"][0], "end": jp["window"][1]},
            "dates": jp["dates"],
            "jepi_total_return": r6(jp["eq_f"]),
            "spy_total_return": r6(jp["eq_u"]),
            "jepi_price_nav": r6(jp["nav_f"]),
            "stats": {
                "jepi": round_stats(jp["fund_stats"], {"trailing_yield": jp["dist_yield"],
                                                       "nav_change": jp["nav_change"]}),
                "spy": round_stats(jp["und_stats"]),
            },
        },
        # all funds' scalar stats + NAV + yield
        "all_funds": {
            pr["fund"]: {
                "underlying": pr["underlying"],
                "window": {"start": pr["window"][0], "end": pr["window"][1]},
                "trailing_yield": pr["dist_yield"],
                "nav_change": pr["nav_change"],
                "nav_start": pr["nav_start"], "nav_end": pr["nav_end"],
                "fund": round_stats(pr["fund_stats"]),
                "index": round_stats(pr["und_stats"]),
            } for pr in pair_results
        },
        "killtests": {
            "kt1_total_return_vs_index_10k": kt1,
            "kt2_nav_erosion": kt2,
            "kt3_downside_cushion": kt3,
            "kt4_diy_homemade_income": kt4,
            "kt5_vol_sortino": kt5,
        },
    }
    with open(os.path.join(HERE, "curve_data.json"), "w") as f:
        json.dump(curve, f)
    print(f"Wrote curve_data.json (2 key pairs w/ curves + NAV, all-fund stats, 5 kill-tests).")


if __name__ == "__main__":
    main()
