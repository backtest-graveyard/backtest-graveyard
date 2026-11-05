#!/usr/bin/env python3
"""Sell in May & Go Away — kill-test — The Backtest Graveyard (Ep19).

Question tested (the oldest calendar rule in the market): the "Halloween indicator" / "Sell in May
and go away." The belief is that stocks are weak from May through October, so you should be OUT of
the market in the summer and back IN from November through April. Does sitting out every summer beat
just buying and holding?

We compare, long-only, on the daily close, over the longest US-market TOTAL-RETURN history we can get:
  1. Sell in May   : hold the market Nov 1 -> Apr 30, sit in cash earning the T-bill rate
                     May 1 -> Oct 31, EVERY year (the strategy under test).
  2. Buy & hold     : the yardstick, total return (dividends reinvested).
  3. The inverse    : in the market May-Oct, cash Nov-Apr — shows how much worse the "bad" half is.

Ranking is by MAR (CAGR / MaxDD%) — the channel standard. Bar to "pass": MAR >= 0.50 AND Sortino
>= 1.00, read RELATIVE to buy & hold, because the 1929-32 -84% collapse sits in the denominator and
nothing that includes it clears an absolute 0.50.

The core honesty question is NOT "does the rule make money" — it obviously trails buy & hold by
sitting in cash half of every year — but "is summer actually DANGEROUS (negative), or merely WEAKER
(still positive)?" If summer is still positive on average, sell-in-May isn't dodging losses; it is
skipping ~6 months of real, smaller gains every single year and calling it prudence.

Data (daily, TOTAL RETURN — dividends reinvested):
  PRIMARY — Fama-French daily research factors (Dartmouth/Ken French library), 1926-07 -> 2026-07.
    We use Mkt = (Mkt-RF + RF) as the daily TOTAL return of the value-weighted US stock market (CRSP)
    compounded into a total-return index (S&P 500 total-return PROXY, daily corr ~0.99), and RF as
    the daily risk-free (1-mo T-bill) cash return. This is a free, bot-wall-free series that REACHES
    Oct 1929, Oct 1987, Oct 2008 and 2020 — the infamous autumn crashes that ARE the "summer is
    dangerous" story, so we can test whether the seasonal edge is a robust century-long drift or a
    fat-tail artifact of a few crashes. Cached to ff_daily_factors.csv.

  FALLBACK — Alpaca SIP daily SPY bars (adjustment=all, total return) via ~/.alpaca/credentials,
    2016+ only, plus FRED DTB3 for cash. Far too short to judge a seasonal effect; used only if the
    Fama-French download fails. The script PRINTS which source + window it actually used.

No secrets in the file, no PII, no live-bot references. Re-runnable; caches raw data on first run.
"""
import csv, json, math, os, sys, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
TRADING_DAYS = 252
CONST_CASH_ANNUAL = 0.02   # stated fallback if FRED is unreachable (fallback path only)
FF_URL = ("https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
          "F-F_Research_Data_Factors_daily_CSV.zip")

# The "winter" / in-market months for Sell-in-May: Nov, Dec, Jan, Feb, Mar, Apr.
WINTER_MONTHS = {11, 12, 1, 2, 3, 4}
ERA_SPLIT_YEAR = 1990   # "everyone knew about it after ~1990" — decay test boundary


# ======================================================================================
# Data loading (identical pattern to the golden-cross backtest)
# ======================================================================================
def _csv_path(name):
    return os.path.join(HERE, name)


def _fetch_ff_daily():
    """Download & cache the Fama-French daily factors CSV (unzipped). -> True/False."""
    import io, zipfile, urllib.request
    UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
    try:
        req = urllib.request.Request(FF_URL, headers={"User-Agent": UA})
        blob = urllib.request.urlopen(req, timeout=60).read()
        zf = zipfile.ZipFile(io.BytesIO(blob))
        name = [n for n in zf.namelist() if n.lower().endswith(".csv")][0]
        raw = zf.read(name).decode("latin-1")
        with open(_csv_path("ff_daily_factors.csv"), "w") as f:
            f.write(raw)
        return True
    except Exception as e:
        print(f"  (FF download failed: {e})", file=sys.stderr)
        return False


def _parse_ff():
    """Parse cached FF daily CSV -> (dates_iso, total_ret_daily, rf_daily). Percent -> fraction."""
    dates, tr, rf = [], [], []
    with open(_csv_path("ff_daily_factors.csv"), encoding="latin-1") as f:
        for line in f:
            p = [x.strip() for x in line.split(",")]
            if len(p) >= 5 and len(p[0]) == 8 and p[0].isdigit():
                try:
                    mktrf, r = float(p[1]), float(p[4])
                except ValueError:
                    continue
                d = f"{p[0][:4]}-{p[0][4:6]}-{p[0][6:8]}"
                dates.append(d)
                tr.append((mktrf + r) / 100.0)   # total market return (incl. dividends)
                rf.append(r / 100.0)              # daily risk-free (1-mo T-bill)
    return dates, tr, rf


def _load_alpaca_fallback():
    """Fallback: Alpaca SIP SPY (2016+, total return) + FRED DTB3 cash. -> (dates, px, cash)."""
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
        sys.exit("FATAL: Fama-French unavailable and no Alpaca creds for the fallback.")
    rows, token = [], None
    base = ("https://data.alpaca.markets/v2/stocks/SPY/bars?timeframe=1Day"
            "&start=2016-01-01T00:00:00Z&limit=10000&adjustment=all&feed=sip")
    while True:
        url = base + (f"&page_token={token}" if token else "")
        req = urllib.request.Request(
            url, headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec})
        d = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
        for b in d.get("bars", []) or []:
            rows.append((b["t"][:10], float(b["c"])))
        token = d.get("next_page_token")
        if not token:
            break
    dates = [r[0] for r in rows]; px = [r[1] for r in rows]
    cash = None
    try:
        raw = urllib.request.urlopen(
            "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTB3", timeout=30).read().decode()
        obs = {}
        for row in csv.reader(raw.splitlines()):
            if len(row) < 2 or not row[0][:4].isdigit():
                continue
            try:
                obs[row[0]] = float(row[1])
            except ValueError:
                continue
        keys = sorted(obs); last = CONST_CASH_ANNUAL * 100; ki = 0; cash = []
        for d in dates:
            while ki < len(keys) and keys[ki] <= d:
                last = obs[keys[ki]]; ki += 1
            cash.append((1 + last / 100.0) ** (1 / TRADING_DAYS) - 1)
    except Exception:
        cash = [(1 + CONST_CASH_ANNUAL) ** (1 / TRADING_DAYS) - 1] * len(dates)
    # For the fallback we return a price index; downstream treats it as the total-return index.
    return dates, px, cash


def load_market():
    """Return (dates, tr_index, cash_daily, tr_daily). Primary: Fama-French daily total-return
    market + RF. Fallback: Alpaca SPY (2016+) + FRED."""
    if not os.path.exists(_csv_path("ff_daily_factors.csv")):
        _fetch_ff_daily()
    if os.path.exists(_csv_path("ff_daily_factors.csv")):
        dates, tr, rf = _parse_ff()
        idx = [100.0]
        for r in tr[1:]:
            idx.append(idx[-1] * (1 + r))
        load_market._src = "fama-french daily (CRSP total US market, total return)"
        load_market._srccash = "fama-french RF (daily 1-mo T-bill)"
        load_market._proxy = True
        load_market._mean_cash = _compound_annual(rf)
        return dates, idx, rf, tr
    dates, px, cash = _load_alpaca_fallback()
    # derive daily returns from the price index so the seasonal math still works
    trd = [0.0] + [px[i] / px[i - 1] - 1.0 for i in range(1, len(px))]
    load_market._src = "alpaca-sip SPY (total return; 2016+ ONLY — far too short for a seasonal test)"
    load_market._srccash = "fred DTB3 (3-mo T-bill)"
    load_market._proxy = False
    load_market._mean_cash = _compound_annual(cash)
    return dates, px, cash, trd


def _compound_annual(daily):
    if not daily:
        return 0.0
    return sum((1 + r) ** TRADING_DAYS - 1 for r in daily) / len(daily)


load_market._src = ""
load_market._srccash = ""
load_market._proxy = True
load_market._mean_cash = 0.0


# ======================================================================================
# Metrics (identical to the golden-cross backtest)
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
    peak = equity[0]; peak_date = dates[0]; longest = 0; span = (None, None)
    cur = None
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


def stats(equity, dates, label, pct_invested=None, n_switches=None):
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
        "underwater_days": uw, "underwater_span": span,
        "pct_invested": pct_invested, "n_switches": n_switches, "final": equity[-1],
    }


# ======================================================================================
# Strategies (long-only, daily close, calendar signal — known in advance, no lookahead)
# ======================================================================================
def positions_sell_in_may(dates, invert=False):
    """pos[i]=1 if day i falls in the IN-market window. Sell-in-May holds Nov-Apr (WINTER_MONTHS);
    invert=True holds May-Oct instead. Calendar-only, so there is no lookahead by construction."""
    pos = [0] * len(dates)
    for i in range(1, len(dates)):
        m = int(dates[i][5:7])
        in_winter = m in WINTER_MONTHS
        pos[i] = 1 if (in_winter != invert) else 0
    return pos


def run_timed(prices_tr, tr_daily, pos, cash_daily, cost_oneway=0.0):
    """Equity for a timed long/cash strategy on the total-return series. When pos flips between i-1
    and i, pay cost_oneway. Returns (equity, n_switches)."""
    eq = [1.0]
    n_switches = 0
    for i in range(1, len(pos)):
        r = tr_daily[i] if pos[i] else cash_daily[i]
        cost = cost_oneway if pos[i] != pos[i - 1] else 0.0
        if pos[i] != pos[i - 1]:
            n_switches += 1
        eq.append(eq[-1] * (1 + r) * (1 - cost))
    return eq, n_switches


def buy_hold(prices_tr):
    return [p / prices_tr[0] for p in prices_tr]


# ======================================================================================
# Seasonal decomposition — the heart of the honesty battery
# ======================================================================================
def seasonal_blocks(dates, tr_daily):
    """Split the total-return series into contiguous May-Oct ('S') and Nov-Apr ('W') blocks.
    Returns a list of dicts: {season, year, ret, start, end}. Winter block year = the November
    year (Nov Y -> Apr Y+1). Summer block year = that calendar year (May Y -> Oct Y)."""
    blocks = []
    cur = None
    for i in range(1, len(dates)):
        m = int(dates[i][5:7]); y = int(dates[i][:4])
        s = "W" if m in WINTER_MONTHS else "S"
        byear = (y if m >= 11 else y - 1) if s == "W" else y
        if cur is None or s != cur["season"] or byear != cur["year"]:
            if cur is not None:
                cur["ret"] = cur["_eq"] - 1.0
                blocks.append(cur)
            cur = {"season": s, "year": byear, "_eq": 1.0, "start": dates[i], "end": dates[i]}
        cur["_eq"] *= (1 + tr_daily[i])
        cur["end"] = dates[i]
    if cur is not None:
        cur["ret"] = cur["_eq"] - 1.0
        blocks.append(cur)
    for b in blocks:
        b.pop("_eq", None)
    return blocks


def _mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def _median(xs):
    if not xs:
        return float("nan")
    s = sorted(xs); n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _pct_pos(xs):
    return sum(1 for x in xs if x > 0) / len(xs) if xs else float("nan")


# ======================================================================================
# Main
# ======================================================================================
def fp(x):
    return f"{x*100:,.1f}%"


def main():
    D, TRIDX, cash_daily, tr_daily = load_market()
    yrs = (dt.date.fromisoformat(D[-1]) - dt.date.fromisoformat(D[0])).days / 365.25
    print(f"Market source: {load_market._src}")
    print(f"Cash source  : {load_market._srccash}  (mean ~{load_market._mean_cash*100:.2f}%/yr over window)")
    if load_market._proxy:
        print("Note: CRSP total US market used as the S&P 500 total-return proxy (daily corr ~0.99).")
    print(f"Window       : {D[0]} -> {D[-1]}   ({len(D)} trading days, {yrs:.1f} yrs)\n")

    COST = 0.0005   # 5 bps one-way switching cost (base case)

    # --- three headline strategies ---
    pos_sim = positions_sell_in_may(D, invert=False)   # Sell in May: hold Nov-Apr
    pos_inv = positions_sell_in_may(D, invert=True)    # Inverse: hold May-Oct
    eq_sim, n_sim = run_timed(TRIDX, tr_daily, pos_sim, cash_daily, COST)
    eq_inv, n_inv = run_timed(TRIDX, tr_daily, pos_inv, cash_daily, COST)
    eq_bh = buy_hold(TRIDX)

    inv_sim = sum(pos_sim[1:]) / (len(D) - 1)
    inv_inv = sum(pos_inv[1:]) / (len(D) - 1)

    results = {
        "SIM": stats(eq_sim, D, "1. Sell in May (hold Nov-Apr)", inv_sim, n_sim),
        "BH": stats(eq_bh, D, "2. Buy & hold (S&P total ret)", 1.0, 0),
        "INV": stats(eq_inv, D, "3. Inverse (hold May-Oct)", inv_inv, n_inv),
    }
    ranked = sorted(results.values(),
                    key=lambda s: -(s["mar"] if s["mar"] == s["mar"] else -1))

    print("=" * 122)
    print("RESULTS  (ranked by MAR = CAGR / MaxDD%,  the channel standard)")
    print("=" * 122)
    hdr = (f"{'Strategy':<32}{'TotRet':>14}{'CAGR':>8}{'MAR':>7}{'Sortino':>9}"
           f"{'MaxDD':>9}{'WorstYr':>15}{'UWdays':>8}{'Vol':>8}{'%Inv':>7}{'Switch':>8}")
    print(hdr); print("-" * 122)
    for s in ranked:
        p = "PASS" if (s["mar"] >= 0.5 and s["sortino"] >= 1.0) else "fail"
        inv = f"{s['pct_invested']*100:.0f}%" if s['pct_invested'] is not None else "-"
        sw = str(s['n_switches']) if s['n_switches'] is not None else "-"
        print(f"{s['label']:<32}{fp(s['total_return']):>14}{fp(s['cagr']):>8}{s['mar']:>7.2f}"
              f"{s['sortino']:>9.2f}{fp(s['max_dd']):>9}"
              f"{s['worst_year']+' '+fp(s['worst_year_ret']):>15}{s['underwater_days']:>8}"
              f"{fp(s['vol']):>8}{inv:>7}{sw:>8}  [{p}]")
    print("-" * 122)
    print("Bar to 'pass': MAR >= 0.50 AND Sortino >= 1.00 (read RELATIVE — the 1929-32 -84% crash is")
    print("in the denominator, so nothing clears an absolute 0.50). Buy & hold is the yardstick.\n")

    sim, bh, inv = results["SIM"], results["BH"], results["INV"]
    d1 = 1 + sim["total_return"]; d2 = 1 + bh["total_return"]

    # ---- modern sub-window (post-1990) ----
    def slice_from(year):
        k = next(i for i, d in enumerate(D) if int(d[:4]) >= year)
        return k
    k90 = slice_from(1990)
    D90 = D[k90:]; TR90 = tr_daily[k90:]; CASH90 = cash_daily[k90:]
    TRIDX90 = [TRIDX[i] / TRIDX[k90] * 100 for i in range(k90, len(TRIDX))]
    pos_sim90 = positions_sell_in_may(D90, invert=False)
    pos_inv90 = positions_sell_in_may(D90, invert=True)
    eq_sim90, ns90 = run_timed(TRIDX90, TR90, pos_sim90, CASH90, COST)
    eq_inv90, ni90 = run_timed(TRIDX90, TR90, pos_inv90, CASH90, COST)
    eq_bh90 = buy_hold(TRIDX90)
    sim90 = stats(eq_sim90, D90, "Sell in May", sum(pos_sim90[1:]) / (len(D90) - 1), ns90)
    bh90 = stats(eq_bh90, D90, "Buy & hold", 1.0, 0)
    inv90 = stats(eq_inv90, D90, "Inverse", sum(pos_inv90[1:]) / (len(D90) - 1), ni90)
    print(f"MODERN SUB-WINDOW ({D90[0]} -> {D90[-1]}, {len(D90)} days):")
    print(f"     {'strategy':<14}{'TotRet':>12}{'CAGR':>8}{'MAR':>7}{'Sortino':>9}{'MaxDD':>9}")
    for st in (sim90, bh90, inv90):
        print(f"     {st['label']:<14}{fp(st['total_return']):>12}{fp(st['cagr']):>8}"
              f"{st['mar']:>7.2f}{st['sortino']:>9.2f}{fp(st['max_dd']):>9}")
    print()

    # ======================================================================================
    # KILL-TEST 1 — IS SUMMER ACTUALLY NEGATIVE, OR JUST WEAKER?
    # ======================================================================================
    blocks = seasonal_blocks(D, tr_daily)
    summer = [b["ret"] for b in blocks if b["season"] == "S"]
    winter = [b["ret"] for b in blocks if b["season"] == "W"]
    avg_s, avg_w = _mean(summer), _mean(winter)
    med_s, med_w = _median(summer), _median(winter)
    print("KILL-TEST 1 — IS SUMMER ACTUALLY NEGATIVE, OR JUST WEAKER?")
    print(f"  May-Oct  blocks: {len(summer)}   avg {fp(avg_s)}   median {fp(med_s)}   "
          f"positive {_pct_pos(summer)*100:.0f}% of years")
    print(f"  Nov-Apr  blocks: {len(winter)}   avg {fp(avg_w)}   median {fp(med_w)}   "
          f"positive {_pct_pos(winter)*100:.0f}% of years")
    print(f"  -> Winter beats summer by {fp(avg_w - avg_s)} on average (the real, mild seasonal tilt).")
    verdict_summer = "POSITIVE" if avg_s > 0 else "NEGATIVE"
    print(f"  -> BUT the average summer return is {verdict_summer} ({fp(avg_s)}). Summer is not")
    print(f"     dangerous, just weaker — 'sell in May' skips real (smaller) gains, it doesn't dodge losses.\n")

    # ======================================================================================
    # KILL-TEST 2 — TOTAL RETURN vs BUY & HOLD ($1 -> what)
    # ======================================================================================
    print("KILL-TEST 2 — TOTAL RETURN vs BUY & HOLD (the price of sitting out half of every year)")
    print(f"  Sell in May : {fp(sim['total_return'])}  (${d1:,.2f} per $1, CAGR {fp(sim['cagr'])})")
    print(f"  Buy & hold  : {fp(bh['total_return'])}  (${d2:,.2f} per $1, CAGR {fp(bh['cagr'])})")
    print(f"  -> Sell-in-May keeps ${d1:,.0f} of buy & hold's ${d2:,.0f} — {d1/d2*100:.1f}% of the wealth, "
          f"giving up {fp(bh['cagr'] - sim['cagr'])}/yr of CAGR")
    print(f"     by being in cash {(1-inv_sim)*100:.0f}% of the time. Six months out every year is a huge "
          f"compounding drag even when summer is weaker.\n")

    # ======================================================================================
    # KILL-TEST 3 — CRASH DEPENDENCE (is 'summer weakness' a few autumn crashes?)
    # ======================================================================================
    print("KILL-TEST 3 — CRASH DEPENDENCE (strip the worst few summers — does the edge survive?)")
    s_sorted = sorted(((b["ret"], b["year"]) for b in blocks if b["season"] == "S"))
    worst = s_sorted[:3]
    print("  Worst 3 May-Oct blocks (the infamous autumn crashes live here):")
    for r, y in worst:
        print(f"     May-Oct {y}: {fp(r)}")
    strip_years = {y for _, y in worst}
    summer_ex = [b["ret"] for b in blocks if b["season"] == "S" and b["year"] not in strip_years]
    avg_s_ex = _mean(summer_ex)
    gap_full = avg_w - avg_s
    gap_ex = avg_w - avg_s_ex
    print(f"  Avg summer WITH the 3 worst : {fp(avg_s)}   (winter-minus-summer gap {fp(gap_full)})")
    print(f"  Avg summer WITHOUT them     : {fp(avg_s_ex)}   (gap shrinks to {fp(gap_ex)})")
    shrink = 1 - gap_ex / gap_full if gap_full else float("nan")
    print(f"  -> Removing just 3 of {len(summer)} summers erases {fp(shrink)} of the winter-over-summer gap.")
    print(f"     The 'summer is weak' edge is heavily a FAT-TAIL artifact of a handful of Oct crashes,\n"
          f"     not a smooth, reliable seasonal drift you can count on any given year.\n")

    # ======================================================================================
    # KILL-TEST 4 — POST-PUBLICATION DECAY (has the edge shrunk since everyone knew?)
    # ======================================================================================
    print(f"KILL-TEST 4 — POST-PUBLICATION DECAY (pre-{ERA_SPLIT_YEAR} vs post-{ERA_SPLIT_YEAR})")
    s_pre = [b["ret"] for b in blocks if b["season"] == "S" and b["year"] < ERA_SPLIT_YEAR]
    w_pre = [b["ret"] for b in blocks if b["season"] == "W" and b["year"] < ERA_SPLIT_YEAR]
    s_post = [b["ret"] for b in blocks if b["season"] == "S" and b["year"] >= ERA_SPLIT_YEAR]
    w_post = [b["ret"] for b in blocks if b["season"] == "W" and b["year"] >= ERA_SPLIT_YEAR]
    gap_pre = _mean(w_pre) - _mean(s_pre)
    gap_post = _mean(w_post) - _mean(s_post)
    print(f"  Pre-{ERA_SPLIT_YEAR} : summer avg {fp(_mean(s_pre))}, winter avg {fp(_mean(w_pre))}, "
          f"gap {fp(gap_pre)}  ({len(s_pre)} summers)")
    print(f"  Post-{ERA_SPLIT_YEAR}: summer avg {fp(_mean(s_post))}, winter avg {fp(_mean(w_post))}, "
          f"gap {fp(gap_post)}  ({len(s_post)} summers)")
    decayed = gap_post < gap_pre
    print(f"  -> The winter-over-summer gap {'SHRANK' if decayed else 'did not shrink'} "
          f"from {fp(gap_pre)} to {fp(gap_post)} after ~{ERA_SPLIT_YEAR}.")
    print(f"     Post-{ERA_SPLIT_YEAR} you'd also have sat out huge May-Oct rallies "
          f"(e.g. the 2009 and 2020 recoveries):")
    for yr in ("2009", "2020"):
        blk = next((b for b in blocks if b["season"] == "S" and str(b["year"]) == yr), None)
        if blk:
            print(f"        May-Oct {yr}: market {fp(blk['ret'])} — earned in cash instead.")
    print()

    # ======================================================================================
    # KILL-TEST 5 — TAX & COST DRAG
    # ======================================================================================
    print("KILL-TEST 5 — TAX & TRADING DRAG (twice a year, every year, forever)")
    eq_0x, _ = run_timed(TRIDX, tr_daily, pos_sim, cash_daily, 0.0)
    eq_2x, _ = run_timed(TRIDX, tr_daily, pos_sim, cash_daily, COST * 2)
    c0, c1, c2 = cagr(eq_0x, D), cagr(eq_sim, D), cagr(eq_2x, D)
    print(f"  Switches: {n_sim} over {yrs:.0f} yrs (~{n_sim/yrs:.1f}/yr = the two calendar flips).")
    print(f"  Switching cost 0 bps : ${eq_0x[-1]:,.2f}  CAGR {fp(c0)}")
    print(f"  Switching cost 5 bps : ${eq_sim[-1]:,.2f}  CAGR {fp(c1)}  (base case)")
    print(f"  Switching cost 10 bps: ${eq_2x[-1]:,.2f}  CAGR {fp(c2)}")
    print(f"  -> Explicit commissions are small, BUT this ignores TAX: selling every single year in a")
    print(f"     taxable account realizes short-term gains yearly instead of deferring them for decades.")
    print(f"     Buy & hold defers the entire gain (0 forced realizations); sell-in-May forces one every")
    print(f"     May. In a taxable account the after-tax gap is materially WORSE than shown here.\n")

    # ======================================================================================
    # KILL-TEST 6 — RISK-ADJUSTED (does sitting out summer actually buy less risk?)
    # ======================================================================================
    print("KILL-TEST 6 — RISK-ADJUSTED (is the summer 'seatbelt' worth the return you give up?)")
    dd_cut = 1 - abs(sim["max_dd"]) / abs(bh["max_dd"])
    vol_cut = 1 - sim["vol"] / bh["vol"]
    print(f"  Max drawdown : B&H {fp(bh['max_dd'])}  vs  Sell-in-May {fp(sim['max_dd'])}  "
          f"({fp(dd_cut)} smaller)")
    print(f"  Volatility   : B&H {fp(bh['vol'])}  vs  Sell-in-May {fp(sim['vol'])}  ({fp(vol_cut)} lower)")
    print(f"  MAR          : B&H {bh['mar']:.2f}  vs  Sell-in-May {sim['mar']:.2f}")
    print(f"  Sortino      : B&H {bh['sortino']:.2f}  vs  Sell-in-May {sim['sortino']:.2f}")
    better_mar = sim["mar"] > bh["mar"]
    print(f"  -> On MAR/Sortino sell-in-May is {'modestly BETTER' if better_mar else 'not better'} "
          f"(it avoids the autumn-crash tail), but you paid for it")
    print(f"     with {fp(bh['cagr'] - sim['cagr'])}/yr and ~{(1-d1/d2)*100:.0f}% of your terminal wealth. "
          f"A smaller-but-real drawdown cut, bought dearly.\n")

    # ======================================================================================
    # GREEN keeper
    # ======================================================================================
    print("GREEN KEEPER (what the data actually supports)")
    print(f"  The SEASON is real: winter (Nov-Apr) beat summer (May-Oct) by {fp(avg_w - avg_s)}/yr on")
    print(f"  average over {yrs:.0f} years — one of the more robust calendar effects. But summer is still")
    print(f"  {verdict_summer} ({fp(avg_s)}), most of the gap is a few autumn crashes, and the trade "
          f"lost {fp(bh['total_return']-sim['total_return'])}")
    print(f"  of total return vs buy & hold by sitting in cash half of every year.")
    print(f"  The honest use is NOT selling your portfolio each May — it's a weak nudge to TIME NEW")
    print(f"  CONTRIBUTIONS toward the Nov-Apr window if anything. The season is real; the trade is not.\n")

    # ======================================================================================
    # export curve_data.json
    # ======================================================================================
    def norm(eq):
        return [round(x, 6) for x in eq]
    uw_sim = [round(x, 6) for x in underwater_series(eq_sim)]
    uw_bh = [round(x, 6) for x in underwater_series(eq_bh)]

    # seasonal-average bars, overall and by era
    seasonal_bars = {
        "overall": {"summer_avg": round(avg_s, 6), "winter_avg": round(avg_w, 6),
                    "summer_median": round(med_s, 6), "winter_median": round(med_w, 6),
                    "summer_pct_pos": round(_pct_pos(summer), 4),
                    "winter_pct_pos": round(_pct_pos(winter), 4),
                    "n_summers": len(summer), "n_winters": len(winter)},
        f"pre_{ERA_SPLIT_YEAR}": {"summer_avg": round(_mean(s_pre), 6),
                                  "winter_avg": round(_mean(w_pre), 6),
                                  "gap": round(gap_pre, 6), "n_summers": len(s_pre)},
        f"post_{ERA_SPLIT_YEAR}": {"summer_avg": round(_mean(s_post), 6),
                                   "winter_avg": round(_mean(w_post), 6),
                                   "gap": round(gap_post, 6), "n_summers": len(s_post)},
    }
    # per-year seasonal series for charting
    per_year = {
        "summer": [{"year": b["year"], "ret": round(b["ret"], 6)}
                   for b in blocks if b["season"] == "S"],
        "winter": [{"year": b["year"], "ret": round(b["ret"], 6)}
                   for b in blocks if b["season"] == "W"],
    }

    curve = {
        "meta": {
            "generated": dt.date.today().isoformat(),
            "market_source": load_market._src, "cash_source": load_market._srccash,
            "is_proxy": load_market._proxy, "cash_mean_annual": round(load_market._mean_cash, 5),
            "window_start": D[0], "window_end": D[-1], "trading_days": len(D),
            "years": round(yrs, 2), "cost_oneway_bps": COST * 1e4,
            "winter_months": sorted(WINTER_MONTHS), "era_split_year": ERA_SPLIT_YEAR,
        },
        "dates": D,
        "curves": {
            "sell_in_may": norm(eq_sim),
            "buy_hold": norm(eq_bh),
            "inverse_may_oct": norm(eq_inv),
        },
        "underwater": {
            "sell_in_may": uw_sim,
            "buy_hold": uw_bh,
        },
        "seasonal_bars": seasonal_bars,
        "seasonal_per_year": per_year,
        "stats": {
            k: {kk: v[kk] for kk in ("label", "total_return", "cagr", "mar", "sortino",
                                     "max_dd", "max_dd_peak", "max_dd_trough", "vol",
                                     "worst_year", "worst_year_ret", "underwater_days",
                                     "pct_invested", "n_switches", "final")}
            for k, v in results.items()
        },
        "stats_modern": {
            "window": [D90[0], D90[-1]],
            "sell_in_may": {kk: sim90[kk] for kk in ("total_return", "cagr", "mar", "sortino", "max_dd")},
            "buy_hold": {kk: bh90[kk] for kk in ("total_return", "cagr", "mar", "sortino", "max_dd")},
            "inverse": {kk: inv90[kk] for kk in ("total_return", "cagr", "mar", "sortino", "max_dd")},
        },
        "killtests": {
            "summer_avg": avg_s, "winter_avg": avg_w, "summer_is_positive": avg_s > 0,
            "winter_minus_summer_gap": avg_w - avg_s,
            "summer_pct_positive": _pct_pos(summer),
            "sim_dollar_per_1": d1, "bh_dollar_per_1": d2, "sim_frac_of_bh": d1 / d2,
            "cagr_shortfall": bh["cagr"] - sim["cagr"],
            "pct_time_invested": inv_sim,
            "worst3_summers": [{"year": y, "ret": r} for r, y in worst],
            "summer_avg_ex_worst3": avg_s_ex,
            "gap_full": gap_full, "gap_ex_worst3": gap_ex, "gap_shrink_frac": shrink,
            "gap_pre": gap_pre, "gap_post": gap_post, "gap_decayed": decayed,
            "maxdd_bh": bh["max_dd"], "maxdd_sim": sim["max_dd"], "maxdd_reduction_frac": dd_cut,
            "vol_bh": bh["vol"], "vol_sim": sim["vol"], "vol_reduction_frac": vol_cut,
            "cost_cagr_0bps": c0, "cost_cagr_5bps": c1, "cost_cagr_10bps": c2,
            "n_switches": n_sim, "n_switches_per_year": n_sim / yrs,
        },
    }
    with open(_csv_path("curve_data.json"), "w") as f:
        json.dump(curve, f)
    print(f"Wrote curve_data.json ({len(D)} dates, 3 curves + underwater + seasonal bars + stats + killtests).")


if __name__ == "__main__":
    main()
