#!/usr/bin/env python3
"""HedgeFundie's Excellent Adventure (HFEA) kill-test — The Backtest Graveyard (Ep17).

Belief under test (the famous Reddit/Bogleheads strategy): hold 55% UPRO (3x-leveraged S&P 500) +
45% TMF (3x-leveraged 20+yr Treasuries), rebalanced quarterly. The pitch: stocks and long bonds are
negatively correlated, so 3x-leveraging BOTH and rebalancing gives equity-crushing returns while the
Treasury leg cushions the stock crashes. This script tests BOTH what is real (the risk-parity /
uncorrelated-assets idea) and what is myth (the 3x leverage, and the assumption the hedge always holds).

TWO DATA REGIMES (both run, both reported, clearly labelled):

  (A) REAL ETFs — the actual HFEA record.
      UPRO / TMF / SPY / AGG / TLT daily TOTAL-RETURN closes (adjustment=all) from Alpaca SIP.
      Alpaca SIP only reaches 2016-01-04, so this window is 2016+ — which OMITS HFEA's 2009-2015
      glory years (a conservative-UNFAVORABLE cut: we drop its best era) but CONTAINS the two
      decisive events: the 2020 COVID crash (hedge WORKED — bonds rallied) and the 2022 detonation
      (hedge FAILED — stocks AND long bonds crashed together as rates spiked). stooq.com (full 2009+)
      is behind a JavaScript proof-of-work bot wall and Yahoo's chart API hard-rate-limited this IP
      (429); we do not bypass bot-detection, so Alpaca-SIP-2016+ is the honest available window and is
      printed as the source actually used.

  (B) SIMULATED 3x — the blind spot: back through the rising-rate era.
      The whole HFEA critique is that it was implicitly fit to the 1982-2021 forty-year bond BULL.
      We simulate the strategy far earlier by BUILDING each 3x leg from underlying total returns:
        equity leg  : Fama-French daily total-return US market (CRSP; S&P 500 total-return proxy,
                      daily corr ~0.99), 1926-07+.  (ff_daily_factors.csv, no bot wall.)
        Treasury leg: a synthetic long-Treasury TOTAL-RETURN index built from FRED DGS10 daily
                      10-year constant-maturity yields (1962-01+), by fully repricing a rolling
                      10yr par bond each day (captures convexity) and adding daily coupon accrual.
      3x legs are modelled honestly as   L*index - (L-1)*RF - expense   (L=3): i.e. the fund borrows
      2x notional and pays the SHORT RATE on it. This matters enormously here — in the 1970s-early-80s
      the short rate was 5-15%, so financing ALONE drags 10-30%/yr on a leveraged leg, exactly when a
      leveraged long bond is already bleeding from rising yields. RF = Fama-French daily 1-mo T-bill.
      Common window after aligning FF + DGS10: ~1962 -> 2026, which CONTAINS the 1962-1981 bond bear
      (10yr yield 4% -> 15.8%) — the sustained version of 2022.
      CAVEAT (disclosed): DGS10 is a 10-year yield (duration ~8). TMF's real underlying is 20+yr
      (duration ~17), so this proxy UNDERSTATES the leveraged-bond damage in the rising-rate era —
      a deliberately conservative choice. Pre-1962 daily long-Treasury data is not available bot-wall
      free, so the simulation starts 1962 (still covers the entire destructive rate rise).

Strategies compared (ranked by MAR = CAGR / MaxDD%, channel bar = MAR >= 0.5 AND Sortino >= 1.0):
  1. HFEA 55/45 UPRO/TMF, quarterly rebalance   (the strategy)
  2. 100% S&P 500 total-return buy & hold
  3. Classic 60/40 (60% S&P / 40% bonds), quarterly rebalance
  4. UPRO-alone (3x S&P) — reference

Kill-test battery: the 2022 detonation (both legs down, correlation flip), regime dependence / the
1962-1982 rising-rate simulation, drawdown reality, leverage/volatility decay, rebalance sensitivity,
and the GREEN transferable keeper. No secrets in the file, no PII, no live-bot references. Re-runnable;
caches raw data (alpaca_*.csv, fred_DGS10.csv, ff_daily_factors.csv) on first run.
"""
import csv, json, math, os, sys, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
TRADING_DAYS = 252
FF_URL = ("https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
          "F-F_Research_Data_Factors_daily_CSV.zip")

# leveraged-fund cost assumptions (sim legs only; real ETFs embed their own)
LEV = 3.0
UPRO_EXPENSE = 0.0092      # UPRO gross expense ~0.91-0.92%/yr
TMF_EXPENSE = 0.0106       # TMF gross expense ~1.06%/yr
SIM_MATURITY = 10          # DGS10 -> price a rolling 10yr par bond (conservative vs TMF's 20+yr)


# ======================================================================================
# Data loading
# ======================================================================================
def _path(name):
    return os.path.join(HERE, name)


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


def _fetch_alpaca(sym):
    """Alpaca SIP daily bars, split/div adjusted (total return). Reaches ~2016-01-04. Cache CSV."""
    import urllib.request
    key, sec = _alpaca_creds()
    if not (key and sec):
        return False
    rows, token = [], None
    base = (f"https://data.alpaca.markets/v2/stocks/{sym}/bars?timeframe=1Day"
            "&start=2009-01-01T00:00:00Z&limit=10000&adjustment=all&feed=sip")
    while True:
        url = base + (f"&page_token={token}" if token else "")
        req = urllib.request.Request(
            url, headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec})
        try:
            d = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
        except Exception as e:
            print(f"  (Alpaca {sym} failed: {e})", file=sys.stderr)
            return False
        for b in d.get("bars", []) or []:
            rows.append(f"{b['t'][:10]},{b['c']}")
        token = d.get("next_page_token")
        if not token:
            break
    if not rows:
        return False
    with open(_path(f"alpaca_{sym}.csv"), "w") as f:
        f.write("Date,AdjClose\n" + "\n".join(rows) + "\n")
    return True


def load_etf(sym):
    """Return (dates, adjclose) for a real ETF from Alpaca SIP (cached)."""
    p = _path(f"alpaca_{sym}.csv")
    if not os.path.exists(p):
        if not _fetch_alpaca(sym):
            sys.exit(f"FATAL: could not obtain Alpaca SIP data for {sym}.")
    dates, px = [], []
    with open(p) as f:
        for row in csv.DictReader(f):
            try:
                px.append(float(row["AdjClose"]))
            except (ValueError, KeyError):
                continue
            dates.append(row["Date"])
    return dates, px


def _fetch_fred(series):
    import urllib.request
    try:
        raw = urllib.request.urlopen(
            f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}", timeout=40).read().decode()
        with open(_path(f"fred_{series}.csv"), "w") as f:
            f.write(raw)
        return True
    except Exception as e:
        print(f"  (FRED {series} failed: {e})", file=sys.stderr)
        return False


def load_fred(series):
    """Return dict {date_iso: value} for a FRED series (missing '.' skipped)."""
    p = _path(f"fred_{series}.csv")
    if not os.path.exists(p):
        if not _fetch_fred(series):
            sys.exit(f"FATAL: could not obtain FRED {series}.")
    obs = {}
    with open(p) as f:
        for row in csv.reader(f):
            if len(row) < 2 or not row[0][:4].isdigit():
                continue
            try:
                obs[row[0]] = float(row[1])
            except ValueError:
                continue
    return obs


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
        with open(_path("ff_daily_factors.csv"), "w") as f:
            f.write(raw)
        return True
    except Exception as e:
        print(f"  (FF download failed: {e})", file=sys.stderr)
        return False


def load_ff():
    """Fama-French daily: (dates_iso, mkt_total_ret_daily, rf_daily). Percent -> fraction."""
    p = _path("ff_daily_factors.csv")
    if not os.path.exists(p) and not _fetch_ff_daily():
        sys.exit("FATAL: could not download the Fama-French daily factors from " + FF_URL)
    dates, tr, rf = [], [], []
    with open(p, encoding="latin-1") as f:
        for line in f:
            q = [x.strip() for x in line.split(",")]
            if len(q) >= 5 and len(q[0]) == 8 and q[0].isdigit():
                try:
                    mktrf, r = float(q[1]), float(q[4])
                except ValueError:
                    continue
                dates.append(f"{q[0][:4]}-{q[0][4:6]}-{q[0][6:8]}")
                tr.append((mktrf + r) / 100.0)
                rf.append(r / 100.0)
    return dates, tr, rf


def align_many(series_map):
    """series_map: {name: (dates, values)}. Inner-join on common dates. Return (dates, {name: vals})."""
    names = list(series_map)
    dsets = [set(series_map[n][0]) for n in names]
    common = sorted(set.intersection(*dsets))
    out = {n: [] for n in names}
    lut = {n: dict(zip(*series_map[n])) for n in names}
    for d in common:
        for n in names:
            out[n].append(lut[n][d])
    return common, out


# ======================================================================================
# Metrics
# ======================================================================================
def daily_rets(equity):
    return [equity[i] / equity[i - 1] - 1.0 for i in range(1, len(equity))]


def cagr(equity, dates):
    yrs = (dt.date.fromisoformat(dates[-1]) - dt.date.fromisoformat(dates[0])).days / 365.25
    return (equity[-1] / equity[0]) ** (1 / yrs) - 1 if yrs > 0 else float("nan")


def max_drawdown(equity):
    peak = equity[0]; pk = 0; mdd = 0.0; mpk = 0; mtr = 0
    for i, v in enumerate(equity):
        if v > peak:
            peak = v; pk = i
        dd = v / peak - 1.0
        if dd < mdd:
            mdd = dd; mpk = pk; mtr = i
    return mdd, mpk, mtr


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
    return wy, yr[wy], yr


def pearson(a, b):
    n = len(a)
    if n < 3:
        return float("nan")
    ma = sum(a) / n; mb = sum(b) / n
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    va = sum((x - ma) ** 2 for x in a); vb = sum((x - mb) ** 2 for x in b)
    return cov / math.sqrt(va * vb) if va > 0 and vb > 0 else float("nan")


def stats(equity, dates, label):
    rets = daily_rets(equity)
    mdd, pk, tr = max_drawdown(equity)
    c = cagr(equity, dates)
    wy, wyr, _ = worst_cal_year(equity, dates)
    uw, span = longest_underwater(equity, dates)
    return {
        "label": label, "total_return": equity[-1] / equity[0] - 1, "cagr": c,
        "mar": c / abs(mdd) if mdd else float("nan"), "sortino": sortino(rets),
        "max_dd": mdd, "max_dd_peak": dates[pk], "max_dd_trough": dates[tr],
        "vol": ann_vol(rets), "worst_year": wy, "worst_year_ret": wyr,
        "underwater_days": uw, "underwater_span": span, "final": equity[-1],
    }


# ======================================================================================
# Building blocks: returns, rebalancing, leverage, bond total return
# ======================================================================================
def rets_from_px(px):
    """Daily return array aligned to prices; r[0]=0."""
    return [0.0] + [px[i] / px[i - 1] - 1.0 for i in range(1, len(px))]


def levered_leg(index_rets, rf, expense, lev=LEV):
    """Honest leveraged-ETF daily return: lev*index - (lev-1)*RF (financing on borrowed notional)
    - daily expense.  index_rets/rf are daily fractions aligned; expense is annual."""
    exp_d = (1 + expense) ** (1 / TRADING_DAYS) - 1.0
    return [lev * index_rets[i] - (lev - 1) * rf[i] - exp_d for i in range(len(index_rets))]


def levered_leg_flatdrag(index_rets, drag_annual, lev=LEV):
    """Alternative: lev*index minus a FLAT annual drag (no rate-sensitive financing term).
    Used to isolate how much of the sim damage is the financing mechanism vs a fixed fee."""
    d = (1 + drag_annual) ** (1 / TRADING_DAYS) - 1.0
    return [lev * index_rets[i] - d for i in range(len(index_rets))]


def bond_tr_index(dates, yields, maturity=SIM_MATURITY, f=2):
    """Total-return index (start 100) for a rolling constant-maturity par bond, from a CMT yield
    series. Each day: reprice a `maturity`-yr par bond (coupon = yesterday's yield) at today's yield
    (full repricing -> exact convexity), and add one day of coupon accrual.
    yields in DECIMAL (0.04 = 4%)."""
    idx = [100.0]
    n = int(round(maturity * f))
    day = 1.0 / TRADING_DAYS
    for i in range(1, len(dates)):
        y0 = yields[i - 1]; y1 = yields[i]
        c = (y0 / f) * 100.0                      # per-period coupon of a par bond struck at y0
        i1 = y1 / f
        if 1 + i1 <= 0:
            price = 100.0
        else:
            disc = 1.0 / (1 + i1)
            # PV of coupons (geometric) + PV of face
            if abs(i1) < 1e-12:
                pv_coupons = c * n
            else:
                pv_coupons = c * (1 - disc ** n) / i1
            price = pv_coupons + 100.0 * disc ** n
        price_ret = price / 100.0 - 1.0
        income = y0 * day
        idx.append(idx[-1] * (1 + income + price_ret))
    return idx


def _bucket(d, freq):
    y, m = int(d[:4]), int(d[5:7])
    if freq == "Q":
        return (y, (m - 1) // 3)
    if freq == "M":
        return (y, m)
    if freq == "A":
        return (y,)
    return None  # never


def rebalanced(rets_list, weights, dates, freq="Q"):
    """Equity of a fixed-weight portfolio rebalanced at freq boundaries. rets_list: list of daily
    return arrays aligned to dates (index 0 = 0). weights sum to 1. Returns (equity, n_rebalances)."""
    vals = list(weights)          # sleeve values, total = 1.0 at t0
    equity = [1.0]
    nreb = 0
    for i in range(1, len(dates)):
        for j in range(len(vals)):
            vals[j] *= (1 + rets_list[j][i])
        tot = sum(vals)
        equity.append(tot)
        if freq != "never" and _bucket(dates[i], freq) != _bucket(dates[i - 1], freq):
            vals = [tot * w for w in weights]
            nreb += 1
    return equity, nreb


def single(rets, dates):
    eq = [1.0]
    for i in range(1, len(dates)):
        eq.append(eq[-1] * (1 + rets[i]))
    return eq


# ======================================================================================
# Reporting helpers
# ======================================================================================
def fp(x):
    return f"{x*100:,.1f}%"


def print_table(results, title, yardstick_note):
    ranked = sorted(results.values(), key=lambda s: -(s["mar"] if s["mar"] == s["mar"] else -1))
    print("=" * 118)
    print(title)
    print("=" * 118)
    hdr = (f"{'Strategy':<34}{'TotRet':>13}{'CAGR':>8}{'MAR':>7}{'Sortino':>9}"
           f"{'MaxDD':>9}{'WorstYr':>15}{'UWdays':>8}{'Vol':>8}")
    print(hdr); print("-" * 118)
    for s in ranked:
        p = "PASS" if (s["mar"] >= 0.5 and s["sortino"] >= 1.0) else "fail"
        print(f"{s['label']:<34}{fp(s['total_return']):>13}{fp(s['cagr']):>8}{s['mar']:>7.2f}"
              f"{s['sortino']:>9.2f}{fp(s['max_dd']):>9}"
              f"{s['worst_year']+' '+fp(s['worst_year_ret']):>15}{s['underwater_days']:>8}"
              f"{fp(s['vol']):>8}  [{p}]")
    print("-" * 118)
    print(yardstick_note + "\n")
    return ranked


def window_return(eq, dates, a, b):
    seg = [(dates[i], eq[i]) for i in range(len(dates)) if a <= dates[i] <= b]
    if len(seg) < 2:
        return None, None, None
    ret = seg[-1][1] / seg[0][1] - 1.0
    dd = max_drawdown([v for _, v in seg])[0]
    return ret, dd, (seg[0][0], seg[-1][0])


def year_return(rets, dates, year):
    prod = 1.0; found = False
    for i in range(1, len(dates)):
        if dates[i][:4] == str(year):
            prod *= (1 + rets[i]); found = True
    return prod - 1.0 if found else None


# ======================================================================================
# MAIN
# ======================================================================================
def main():
    out = {"meta": {"generated": dt.date.today().isoformat()}, "real": {}, "sim": {}}

    # ==================================================================================
    # REGIME A — REAL ETFs (Alpaca SIP, 2016+)
    # ==================================================================================
    print("\n" + "#" * 118)
    print("# REGIME A — REAL ETFs (the actual HFEA record)")
    print("#" * 118)
    syms = {}
    for s in ("UPRO", "TMF", "SPY", "AGG", "TLT"):
        d, p = load_etf(s)
        syms[s] = (d, p)
    D, cols = align_many(syms)
    yrsA = (dt.date.fromisoformat(D[-1]) - dt.date.fromisoformat(D[0])).days / 365.25
    print(f"Source: Alpaca SIP daily bars, adjustment=all (total return).")
    print(f"Window: {D[0]} -> {D[-1]}  ({len(D)} trading days, {yrsA:.1f} yrs)")
    print("Note: Alpaca SIP starts 2016-01-04, so HFEA's 2009-2015 glory years are OMITTED")
    print("      (a cut UNFAVORABLE to HFEA). Both decisive events are in-window: 2020 COVID")
    print("      (hedge worked) and 2022 detonation (hedge failed).\n")

    r_upro = rets_from_px(cols["UPRO"])
    r_tmf = rets_from_px(cols["TMF"])
    r_spy = rets_from_px(cols["SPY"])
    r_agg = rets_from_px(cols["AGG"])
    r_tlt = rets_from_px(cols["TLT"])

    eq_hfea, nreb_hfea = rebalanced([r_upro, r_tmf], [0.55, 0.45], D, "Q")
    eq_spy = single(r_spy, D)
    eq_6040, _ = rebalanced([r_spy, r_agg], [0.60, 0.40], D, "Q")
    eq_upro = single(r_upro, D)

    resA = {
        "HFEA": stats(eq_hfea, D, "1. HFEA 55/45 UPRO/TMF (Q-reb)"),
        "SPY": stats(eq_spy, D, "2. S&P 500 total-ret buy&hold"),
        "6040": stats(eq_6040, D, "3. 60/40 SPY/AGG (Q-reb)"),
        "UPRO": stats(eq_upro, D, "4. UPRO alone (3x S&P) ref"),
    }
    rankedA = print_table(resA, "REGIME A RESULTS (ranked by MAR = CAGR / MaxDD%)",
                          "Bar to 'pass': MAR >= 0.50 AND Sortino >= 1.00.  S&P buy&hold is the yardstick.")

    # ---- KILL-TEST A1: THE 2022 DETONATION (both legs down, correlation flip) ----
    print("KILL-TEST A1 — THE 2022 DETONATION (the hedge became a double-long-leverage bet)")
    upro_2022 = year_return(r_upro, D, 2022)
    tmf_2022 = year_return(r_tmf, D, 2022)
    hfea_2022 = year_return(rets_from_px(eq_hfea), D, 2022)
    spy_2022 = year_return(r_spy, D, 2022)
    tlt_2022 = year_return(r_tlt, D, 2022)
    hfea_dd_2022 = window_return(eq_hfea, D, "2022-01-01", "2022-12-31")[1]
    # peak-to-trough of HFEA over full window usually the 2021 top -> 2022 trough
    hf = resA["HFEA"]
    print(f"  2022 calendar-year returns:")
    print(f"     UPRO (3x S&P)   : {fp(upro_2022)}      <- stock leg CRUSHED")
    print(f"     TMF  (3x 20y TSY): {fp(tmf_2022)}      <- 'hedge' leg ALSO crushed (same year)")
    print(f"     -> BOTH legs fell together. The Treasury leg did not cushion anything; it was a")
    print(f"        second leveraged long into the same rising-rate shock.")
    print(f"     HFEA 2022        : {fp(hfea_2022)}   (SPY {fp(spy_2022)}, TLT 1x {fp(tlt_2022)})")
    print(f"  HFEA max drawdown (full window): {fp(hf['max_dd'])}  "
          f"(peak {hf['max_dd_peak']} -> trough {hf['max_dd_trough']})")
    print(f"  HFEA drawdown WITHIN 2022 alone: {fp(hfea_dd_2022)}")
    # correlation flip: SPY vs long-bond (TLT) daily returns, calm era vs 2022
    def yr_slice(arr, a, b):
        return [arr[i] for i in range(len(D)) if a <= D[i] <= b]
    corr_calm = pearson(yr_slice(r_spy, "2016-01-01", "2019-12-31"),
                        yr_slice(r_tlt, "2016-01-01", "2019-12-31"))
    corr_2020 = pearson(yr_slice(r_spy, "2020-01-01", "2020-12-31"),
                        yr_slice(r_tlt, "2020-01-01", "2020-12-31"))
    corr_2022 = pearson(yr_slice(r_spy, "2022-01-01", "2022-12-31"),
                        yr_slice(r_tlt, "2022-01-01", "2022-12-31"))
    print(f"  Stock/long-bond DAILY correlation (SPY vs TLT):")
    print(f"     2016-2019 (calm) : {corr_calm:+.2f}   2020 (COVID): {corr_2020:+.2f}   "
          f"2022 (inflation): {corr_2022:+.2f}")
    print(f"     -> The whole thesis needs NEGATIVE correlation. In 2022 it went {corr_2022:+.2f} — the")
    print(f"        hedge inverted in the exact regime (inflation/rising rates) it was needed most.\n")

    # ---- KILL-TEST A2: 2020 vs 2022 — when the hedge worked ----
    print("KILL-TEST A2 — WHEN THE HEDGE WORKED (2020) vs WHEN IT BROKE (2022)")
    covid_ret, covid_dd, cw = window_return(eq_hfea, D, "2020-02-19", "2020-03-23")
    tmf_covid, _, _ = window_return(single(r_tmf, D), D, "2020-02-19", "2020-03-23")
    upro_covid, _, _ = window_return(single(r_upro, D), D, "2020-02-19", "2020-03-23")
    print(f"  2020 COVID crash ({cw[0]} -> {cw[1]}): UPRO {fp(upro_covid)}, TMF {fp(tmf_covid)}")
    print(f"     -> The Treasury leg RALLIED while stocks fell — the hedge did its job. HFEA still")
    print(f"        drew down {fp(covid_dd)} but far less than UPRO alone. THIS is the real, working idea.")
    print(f"  2022 (see A1): both legs fell together — the identical wrapper, opposite outcome. The")
    print(f"  difference is the macro regime, not the strategy. HFEA is a BET that stock/bond stay")
    print(f"  negatively correlated; 2022 shows that bet can lose for a whole year.\n")

    # ---- KILL-TEST A3: DRAWDOWN REALITY ----
    print("KILL-TEST A3 — DRAWDOWN REALITY")
    rec = 1 / (1 + hf["max_dd"]) - 1
    sp = resA["SPY"]
    print(f"  HFEA max DD {fp(hf['max_dd'])} needs +{rec*100:,.0f}% just to break even; "
          f"longest underwater {hf['underwater_days']}d (~{hf['underwater_days']/365.25:.1f}y), still-open span {hf['underwater_span']}.")
    print(f"  S&P buy&hold over the SAME window: max DD {fp(sp['max_dd'])}, "
          f"underwater {sp['underwater_days']}d. HFEA's crash is ~{abs(hf['max_dd']/sp['max_dd']):.1f}x deeper.\n")

    # ---- KILL-TEST A4: LEVERAGE / VOLATILITY DECAY (real 3x != 3x the index) ----
    print("KILL-TEST A4 — LEVERAGE / VOLATILITY DECAY (real 3x is NOT 3x the index's total return)")
    spy_tot = eq_spy[-1] / eq_spy[0]; upro_tot = eq_upro[-1] / eq_upro[0]
    tlt_tot = single(r_tlt, D)[-1]; tmf_tot = single(r_tmf, D)[-1]
    print(f"  Equity leg: SPY x{spy_tot:.2f} (+{fp(spy_tot-1)});  UPRO x{upro_tot:.2f} (+{fp(upro_tot-1)}).")
    print(f"     Naive 3x on SPY's RETURN would be x{1+(spy_tot-1)*3:.2f}; UPRO actually did "
          f"x{upro_tot:.2f} = {(upro_tot-1)/(spy_tot-1):.2f}x the index return.")
    print(f"  Bond leg: TLT x{tlt_tot:.2f} ({fp(tlt_tot-1)});  TMF x{tmf_tot:.2f} ({fp(tmf_tot-1)}).")
    print(f"     Naive 3x on TLT's RETURN would be x{1+(tlt_tot-1)*3:.2f}; TMF actually did "
          f"x{tmf_tot:.2f} = {(tmf_tot-1)/(tlt_tot-1):.2f}x — leverage decay + financing on TWO funds.\n")

    # ---- KILL-TEST A5: REBALANCE SENSITIVITY ----
    print("KILL-TEST A5 — REBALANCE SENSITIVITY (does the result lean on quarterly timing?)")
    variants = {"Never (buy&hold 55/45)": "never", "Quarterly": "Q", "Monthly": "M", "Annual": "A"}
    reb_rows = {}
    for name, freq in variants.items():
        eqv, nv = rebalanced([r_upro, r_tmf], [0.55, 0.45], D, freq)
        st = stats(eqv, D, name)
        y22 = year_return(rets_from_px(eqv), D, 2022)
        reb_rows[name] = {"cagr": st["cagr"], "max_dd": st["max_dd"], "mar": st["mar"],
                          "sortino": st["sortino"], "ret_2022": y22, "n_reb": nv}
        print(f"     {name:<24} CAGR {fp(st['cagr']):>8}  MaxDD {fp(st['max_dd']):>8}  "
              f"MAR {st['mar']:>5.2f}  2022 {fp(y22):>8}  (rebs={nv})")
    print(f"  -> In 2022 quarterly rebalancing REBALANCED INTO the falling TMF leg (sold the less-bad")
    print(f"     asset to buy the collapsing one), so it did not save the year. Rebalancing is a")
    print(f"     risk-control/vol-harvesting tool, NOT downside protection when BOTH legs trend down.\n")

    out["real"] = {
        "meta": {"source": "alpaca-sip (adjustment=all, total return)", "window_start": D[0],
                 "window_end": D[-1], "trading_days": len(D), "years": round(yrsA, 2)},
        "dates": D,
        "curves": {"hfea_5545_qreb": [round(x, 6) for x in eq_hfea],
                   "sp500_buyhold": [round(x, 6) for x in eq_spy],
                   "sixty_forty_qreb": [round(x, 6) for x in eq_6040],
                   "upro_alone": [round(x, 6) for x in eq_upro]},
        "underwater": {"hfea_5545_qreb": [round(x, 6) for x in underwater_series(eq_hfea)],
                       "sp500_buyhold": [round(x, 6) for x in underwater_series(eq_spy)]},
        "leg_curves_2022_detail": {  # for the both-legs-down chart
            "upro": [round(x, 6) for x in single(r_upro, D)],
            "tmf": [round(x, 6) for x in single(r_tmf, D)]},
        "stats": {k: {kk: v[kk] for kk in ("label", "total_return", "cagr", "mar", "sortino",
                                           "max_dd", "max_dd_peak", "max_dd_trough", "vol",
                                           "worst_year", "worst_year_ret", "underwater_days")}
                  for k, v in resA.items()},
        "killtests": {
            "upro_2022": upro_2022, "tmf_2022": tmf_2022, "hfea_2022": hfea_2022,
            "spy_2022": spy_2022, "tlt_2022": tlt_2022,
            "hfea_max_dd": hf["max_dd"], "hfea_recovery_needed": rec,
            "hfea_dd_within_2022": hfea_dd_2022,
            "corr_spy_tlt_2016_2019": corr_calm, "corr_spy_tlt_2020": corr_2020,
            "corr_spy_tlt_2022": corr_2022,
            "covid_upro": upro_covid, "covid_tmf": tmf_covid, "covid_hfea_dd": covid_dd,
            "upro_mult_of_spy": (upro_tot - 1) / (spy_tot - 1),
            "tmf_mult_of_tlt": (tmf_tot - 1) / (tlt_tot - 1),
            "rebalance_variants": reb_rows,
        },
    }

    # ==================================================================================
    # REGIME B — SIMULATED 3x back through the rising-rate era
    # ==================================================================================
    print("\n" + "#" * 118)
    print("# REGIME B — SIMULATED 3x (back through the 1962-1981 rising-rate era)")
    print("#" * 118)
    ff_d, ff_tr, ff_rf = load_ff()
    dgs10 = load_fred("DGS10")
    # forward-fill DGS10 onto FF trading dates, starting at first FF date >= DGS10 start
    first_y = min(dgs10)
    last_yield = None
    sim_dates, sim_mkt, sim_rf, sim_y = [], [], [], []
    for d, tr, rf in zip(ff_d, ff_tr, ff_rf):
        if d < first_y:
            continue
        if d in dgs10:
            last_yield = dgs10[d]
        if last_yield is None:
            continue
        sim_dates.append(d); sim_mkt.append(tr); sim_rf.append(rf)
        sim_y.append(last_yield / 100.0)   # percent -> decimal
    yrsB = (dt.date.fromisoformat(sim_dates[-1]) - dt.date.fromisoformat(sim_dates[0])).days / 365.25
    print(f"Equity source  : Fama-French daily total-return US market (S&P 500 TR proxy, corr ~0.99).")
    print(f"Treasury source: FRED DGS10 (10yr CMT yield) -> repriced rolling {SIM_MATURITY}yr par bond TR.")
    print(f"Financing model: 3x leg = 3*index - 2*RF - expense (RF = FF 1-mo T-bill; the borrowed 2x")
    print(f"                 pays the SHORT RATE, which was 5-15% in the late 1970s).")
    print(f"Window: {sim_dates[0]} -> {sim_dates[-1]}  ({len(sim_dates)} days, {yrsB:.1f} yrs)")
    print(f"CAVEAT: 10yr proxy (dur ~8) UNDERSTATES TMF's 20+yr (dur ~17) damage — conservative.\n")

    # build unleveraged total returns
    lt_index = bond_tr_index(sim_dates, sim_y, SIM_MATURITY)
    r_lt = rets_from_px(lt_index)              # unleveraged long-Treasury TR daily
    r_eq = [0.0] + sim_mkt[1:]                 # equity TR daily (index0=0 for alignment)
    r_eq[0] = 0.0
    # note: sim_mkt[i] is that day's total return; use directly as return array
    r_eq = list(sim_mkt); r_eq[0] = 0.0

    # leveraged legs (rate-aware financing) and flat-drag variant
    r_upro_s = levered_leg(r_eq, sim_rf, UPRO_EXPENSE)
    r_tmf_s = levered_leg(r_lt, sim_rf, TMF_EXPENSE)
    r_upro_flat = levered_leg_flatdrag(r_eq, 0.01)
    r_tmf_flat = levered_leg_flatdrag(r_lt, 0.01)

    eq_hfea_s, _ = rebalanced([r_upro_s, r_tmf_s], [0.55, 0.45], sim_dates, "Q")
    eq_hfea_flat, _ = rebalanced([r_upro_flat, r_tmf_flat], [0.55, 0.45], sim_dates, "Q")
    eq_spy_s = single(r_eq, sim_dates)
    eq_6040_s, _ = rebalanced([r_eq, r_lt], [0.60, 0.40], sim_dates, "Q")
    eq_upro_s = single(r_upro_s, sim_dates)
    eq_tmf_s = single(r_tmf_s, sim_dates)

    resB = {
        "HFEA": stats(eq_hfea_s, sim_dates, "1. HFEA 55/45 sim (Q-reb)"),
        "SPY": stats(eq_spy_s, sim_dates, "2. S&P 500 TR buy&hold (sim)"),
        "6040": stats(eq_6040_s, sim_dates, "3. 60/40 sim (Q-reb)"),
        "UPRO": stats(eq_upro_s, sim_dates, "4. UPRO-sim alone (3x S&P)"),
    }
    print_table(resB, "REGIME B RESULTS (full 1962-2026 simulation, ranked by MAR)",
                "Bar to 'pass': MAR >= 0.50 AND Sortino >= 1.00.  S&P buy&hold is the yardstick.")

    # ---- KILL-TEST B1: THE RISING-RATE DECADE ----
    print("KILL-TEST B1 — THE RISING-RATE ERA (1962-1981): the sustained 2022")
    RR0, RR1 = "1962-01-01", "1981-09-30"   # 10yr yield ~4.0% -> ~15.8%
    y0 = sim_y[0] * 100;
    y_peak_i = max(range(len(sim_dates)), key=lambda i: sim_y[i] if sim_dates[i] <= RR1 else -1)
    print(f"  10yr yield: {y0:.2f}% ({sim_dates[0]}) -> {sim_y[y_peak_i]*100:.2f}% ({sim_dates[y_peak_i]}) — a 20-year bond BEAR.")
    for name, eq in (("HFEA sim", eq_hfea_s), ("S&P TR (sim)", eq_spy_s),
                     ("60/40 sim", eq_6040_s), ("UPRO-sim (3x S&P)", eq_upro_s),
                     ("TMF-sim (3x 10y TSY)", eq_tmf_s)):
        ret, dd, w = window_return(eq, sim_dates, RR0, RR1)
        print(f"     {name:<22} {RR0[:4]}-{RR1[:4]}: total {fp(ret):>10}  maxDD {fp(dd):>9}")
    lt_ret, lt_dd, _ = window_return(single(r_lt, sim_dates), sim_dates, RR0, RR1)
    print(f"     {'long-TSY 1x (sim)':<22} {RR0[:4]}-{RR1[:4]}: total {fp(lt_ret):>10}  maxDD {fp(lt_dd):>9}")
    print(f"  -> The leveraged Treasury leg bled for ~20 years. 3x-ing a multi-year bond DOWNtrend, with")
    print(f"     financing that rose WITH the very rates that were sinking the bonds, is a slow ruin.")
    print(f"  This is the era HFEA never lived through — and the whole reason its 2009-2021 record looks")
    print(f"  miraculous: it was born at the START of the biggest bond BULL in history and back-fit to it.\n")

    # ---- KILL-TEST B2: FINANCING MECHANISM (rate-aware vs flat 1% drag) ----
    print("KILL-TEST B2 — THE FINANCING MECHANISM (why rising rates are lethal to leverage)")
    rr_rate, _, _ = window_return(eq_hfea_s, sim_dates, RR0, RR1)
    rr_flat, _, _ = window_return(eq_hfea_flat, sim_dates, RR0, RR1)
    full_rate = resB["HFEA"]
    full_flat = stats(eq_hfea_flat, sim_dates, "flat")
    print(f"  HFEA-sim with rate-aware financing (3x-2*RF-exp):  full CAGR {fp(full_rate['cagr'])}, "
          f"MaxDD {fp(full_rate['max_dd'])}")
    print(f"  HFEA-sim with a FLAT 1%/yr drag (no rate term)  :  full CAGR {fp(full_flat['cagr'])}, "
          f"MaxDD {fp(full_flat['max_dd'])}")
    print(f"  Over 1962-1981 the rate-aware version returned {fp(rr_rate)} vs the flat-drag {fp(rr_flat)}.")
    print(f"  -> A flat fee massively FLATTERS leverage. The real cost of a 3x fund is 2x the short rate,")
    print(f"     which spikes precisely in the inflations when leverage is already losing. Most rosy HFEA")
    print(f"     backtests use a fixed borrow assumption and hide this.\n")

    # ---- KILL-TEST B3: CORRELATION BY DECADE ----
    print("KILL-TEST B3 — STOCK/BOND CORRELATION IS NOT A CONSTANT (it flips with the regime)")
    decades = [("1960s", "1962-01-01", "1969-12-31"), ("1970s", "1970-01-01", "1979-12-31"),
               ("1980s", "1980-01-01", "1989-12-31"), ("1990s", "1990-01-01", "1999-12-31"),
               ("2000s", "2000-01-01", "2009-12-31"), ("2010s", "2010-01-01", "2019-12-31"),
               ("2020s", "2020-01-01", "2026-12-31")]
    corr_by_decade = {}
    for name, a, b in decades:
        eqs = [r_eq[i] for i in range(len(sim_dates)) if a <= sim_dates[i] <= b]
        bnd = [r_lt[i] for i in range(len(sim_dates)) if a <= sim_dates[i] <= b]
        c = pearson(eqs, bnd)
        corr_by_decade[name] = c
        flag = "  <- POSITIVE (hedge broken)" if c > 0.05 else ("  <- negative (hedge works)" if c < -0.05 else "")
        print(f"     {name}: stock/long-bond daily corr {c:+.2f}{flag}")
    print(f"  -> The negative correlation HFEA depends on is a ~2000-2020 phenomenon. In the inflationary")
    print(f"     1970s-early-80s it was POSITIVE — stocks and bonds fell together for years, exactly what")
    print(f"     2022 previewed. The 'always-on hedge' assumption is regime-dependent, not a law.\n")

    # ---- KILL-TEST B4: LEVERAGE / VOL DECAY on the sim legs ----
    print("KILL-TEST B4 — LEVERAGE / VOLATILITY DECAY (sim legs vs 3x the index return)")
    eqt = eq_spy_s[-1]; equ = eq_upro_s[-1]
    lt_tot = single(r_lt, sim_dates)[-1]; tmf_tot_s = eq_tmf_s[-1]
    print(f"  Equity: S&P TR x{eqt:.1f}; UPRO-sim x{equ:.1f}; naive 3x-return x{1+(eqt-1)*3:.1f}.")
    print(f"  Bond:   long-TSY 1x x{lt_tot:.2f}; TMF-sim x{tmf_tot_s:.2f}; naive 3x-return x{1+(lt_tot-1)*3:.2f}.")
    print(f"  Over 60+ years the daily-reset + financing gap compounds enormously; 3x the ride is NOT")
    print(f"  3x the destination on either leg.\n")

    out["sim"] = {
        "meta": {"equity_source": "fama-french daily total-return market (S&P TR proxy)",
                 "treasury_source": f"FRED DGS10 -> rolling {SIM_MATURITY}yr par-bond total return",
                 "financing_model": "3x leg = 3*index - 2*RF - expense",
                 "upro_expense": UPRO_EXPENSE, "tmf_expense": TMF_EXPENSE,
                 "caveat": "10yr proxy understates TMF 20+yr duration (conservative)",
                 "window_start": sim_dates[0], "window_end": sim_dates[-1],
                 "trading_days": len(sim_dates), "years": round(yrsB, 2)},
        "dates": sim_dates,
        "curves": {"hfea_5545_qreb": [round(x, 6) for x in eq_hfea_s],
                   "sp500_buyhold": [round(x, 6) for x in eq_spy_s],
                   "sixty_forty_qreb": [round(x, 6) for x in eq_6040_s],
                   "upro_alone": [round(x, 6) for x in eq_upro_s],
                   "tmf_alone": [round(x, 6) for x in eq_tmf_s]},
        "underwater": {"hfea_5545_qreb": [round(x, 6) for x in underwater_series(eq_hfea_s)],
                       "sp500_buyhold": [round(x, 6) for x in underwater_series(eq_spy_s)]},
        "yield_10yr": [round(y, 5) for y in sim_y],
        "stats": {k: {kk: v[kk] for kk in ("label", "total_return", "cagr", "mar", "sortino",
                                           "max_dd", "max_dd_peak", "max_dd_trough", "vol",
                                           "worst_year", "worst_year_ret", "underwater_days")}
                  for k, v in resB.items()},
        "killtests": {
            "rising_rate_window": [RR0, RR1],
            "yield_start_pct": y0, "yield_peak_pct": sim_y[y_peak_i] * 100,
            "hfea_risingrate_total": window_return(eq_hfea_s, sim_dates, RR0, RR1)[0],
            "hfea_risingrate_maxdd": window_return(eq_hfea_s, sim_dates, RR0, RR1)[1],
            "tmf_sim_risingrate_total": window_return(eq_tmf_s, sim_dates, RR0, RR1)[0],
            "tmf_sim_risingrate_maxdd": window_return(eq_tmf_s, sim_dates, RR0, RR1)[1],
            "longtsy_1x_risingrate_total": lt_ret, "longtsy_1x_risingrate_maxdd": lt_dd,
            "hfea_full_cagr_rateaware": full_rate["cagr"], "hfea_full_maxdd_rateaware": full_rate["max_dd"],
            "hfea_full_cagr_flatdrag": full_flat["cagr"], "hfea_full_maxdd_flatdrag": full_flat["max_dd"],
            "hfea_risingrate_rateaware": rr_rate, "hfea_risingrate_flatdrag": rr_flat,
            "corr_by_decade": corr_by_decade,
        },
    }

    # ==================================================================================
    # Export curve_data.json
    # ==================================================================================
    with open(_path("curve_data.json"), "w") as f:
        json.dump(out, f)
    print("=" * 118)
    print(f"Wrote curve_data.json  (real: {len(D)} dates x4 curves; sim: {len(sim_dates)} dates x5 curves;")
    print(f"                        underwater + 2022 leg detail + decade correlations + all scalars).")
    print("=" * 118)


if __name__ == "__main__":
    main()
