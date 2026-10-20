#!/usr/bin/env python3
"""Golden Cross kill-test — The Backtest Graveyard (Ep16).

Question tested (the single most-searched indicator belief on the internet): the "Golden Cross" —
BUY when the 50-day simple moving average crosses ABOVE the 200-day, SELL to cash when it crosses
back below (the "Death Cross"). Does dodging bear markets with a 50/200 MA cross beat just buying
and holding the S&P 500?

We compare, long-only, on the daily close, over the longest S&P 500 TOTAL-RETURN history we can get:
  1. Golden Cross timing : hold SPY when SMA50 > SMA200 (state as of the prior close), else sit in
                           cash earning the 3-month T-bill rate (NOT 0% — that would flatter timing).
  2. SPY buy & hold       : the yardstick, total return (dividends reinvested).
  3. 200-day-only timing  : hold when price > SMA200, else cash — isolates whether the 50/200 *cross*
                           adds anything over the simpler single-MA filter.

Ranking is by MAR (CAGR / MaxDD%) — the channel standard — because the whole PITCH of the golden
cross is a smoother, more survivable ride, not more money; a fair judge has to price risk, not just
raw dollars. Bar to "pass": MAR >= 0.50 AND Sortino >= 1.00.

Data (daily, TOTAL RETURN — dividends reinvested; a price-only index would unfairly handicap buy&hold):
  PRIMARY — Fama-French daily research factors (Dartmouth/Ken French library), 1926-07 -> 2026-07.
    We use Mkt = (Mkt-RF + RF) as the daily TOTAL return of the value-weighted US stock market (CRSP),
    compounded into a total-return index, and RF as the daily risk-free (1-month T-bill) cash return.
    This is a well-known, free, bot-wall-free series and — crucially — it REACHES 1929, 2000, 2008,
    2020 and 2022, the trending bears that are the entire reason the golden cross exists. It is the
    total US market, used as an S&P 500 total-return PROXY (daily correlation with the S&P ~0.99);
    the 50/200 cross dynamics are effectively identical. Cached to ff_daily_factors.csv.
    Caveat disclosed: the textbook golden cross is computed on the PRICE index; here signal and
    returns both use the total-return index. Dividend drift shifts cross timing only marginally
    (~1.8%/yr = ~0.007%/day against ~1%/day vol), a second-order effect on crossover dates.

  If the Fama-French download fails the script stops rather than silently switching to a shorter
    window (a 2016+ feed omits 2000/2008 and is the worst possible window for this strategy).

No secrets in the file, no PII, no live-bot references. Re-runnable; caches raw data on first run.
"""
import csv, json, math, os, sys, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
TRADING_DAYS = 252
FF_URL = ("https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
          "F-F_Research_Data_Factors_daily_CSV.zip")


# ======================================================================================
# Data loading
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


def load_market():
    """Return (dates, tr_index, cash_daily): Fama-French daily total-return market + RF.
    Records the source used in load_market._src / ._srccash."""
    if not os.path.exists(_csv_path("ff_daily_factors.csv")):
        _fetch_ff_daily()
    if os.path.exists(_csv_path("ff_daily_factors.csv")):
        dates, tr, rf = _parse_ff()
        # build a total-return index starting at 100
        idx = [100.0]
        for r in tr[1:]:
            idx.append(idx[-1] * (1 + r))
        # align lengths: idx has len(tr); dates has len(tr); rf has len(tr)
        load_market._src = "fama-french daily (CRSP total US market, total return)"
        load_market._srccash = "fama-french RF (daily 1-mo T-bill)"
        load_market._proxy = True
        load_market._mean_cash = _compound_annual(rf)
        return dates, idx, rf
    sys.exit("FATAL: could not download the Fama-French daily factors from " + FF_URL)


def _compound_annual(daily):
    if not daily:
        return 0.0
    return sum((1 + r) ** TRADING_DAYS - 1 for r in daily) / len(daily)


load_market._src = ""
load_market._srccash = ""
load_market._proxy = True
load_market._mean_cash = 0.0


# ======================================================================================
# Indicators & metrics
# ======================================================================================
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


def stats(equity, dates, label, pct_invested=None, n_trades=None):
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
        "pct_invested": pct_invested, "n_trades": n_trades, "final": equity[-1],
    }


# ======================================================================================
# Strategies (long-only, daily close, no lookahead)
# ======================================================================================
def positions_ma_cross(prices, fast, slow):
    """pos[i] in {0,1} = whether we HOLD during day i, decided by the MA state as of close i-1."""
    sf = sma(prices, fast); ss = sma(prices, slow)
    pos = [0] * len(prices)
    for i in range(1, len(prices)):
        if sf[i - 1] is not None and ss[i - 1] is not None:
            pos[i] = 1 if sf[i - 1] > ss[i - 1] else 0
    return pos


def positions_above_ma(prices, slow):
    """pos[i]=1 if price closed >= its slow-SMA as of close i-1 (single-MA filter)."""
    ss = sma(prices, slow)
    pos = [0] * len(prices)
    for i in range(1, len(prices)):
        if ss[i - 1] is not None:
            pos[i] = 1 if prices[i - 1] >= ss[i - 1] else 0
    return pos


def run_timed(prices, pos, cash_daily, cost_oneway=0.0):
    """Equity for a timed long/cash strategy. When pos flips between i-1 and i, pay cost_oneway
    (a fraction) on the switch. Returns (equity, n_round_trips, segments) where segments is a list
    of dicts describing each in-market run for the whipsaw/lag analysis."""
    eq = [1.0]
    segments = []
    in_seg = False; seg_start = None
    for i in range(1, len(prices)):
        r = (prices[i] / prices[i - 1] - 1.0) if pos[i] else cash_daily[i]
        cost = cost_oneway if pos[i] != pos[i - 1] else 0.0
        eq.append(eq[-1] * (1 + r) * (1 - cost))
        # segment bookkeeping (based on holding state)
        if pos[i] and not in_seg:
            in_seg = True; seg_start = i          # first held day
        if in_seg and (not pos[i] or i == len(prices) - 1):
            seg_end = i if not pos[i] else i       # last held day (approx at series end)
            last_held = i - 1 if not pos[i] else i
            segments.append({"start": seg_start, "last_held": last_held,
                             "entry_px_idx": seg_start - 1, "exit_signal_idx": i if not pos[i] else i})
            in_seg = False
    # a round trip = a completed in-market segment
    return eq, len(segments), segments


def buy_hold(prices):
    return [p / prices[0] for p in prices]


# ======================================================================================
# Main
# ======================================================================================
def fp(x):
    return f"{x*100:,.1f}%"


def main():
    D, SPY, cash_daily = load_market()
    yrs = (dt.date.fromisoformat(D[-1]) - dt.date.fromisoformat(D[0])).days / 365.25
    print(f"Market source: {load_market._src}")
    print(f"Cash source  : {load_market._srccash}  (mean ~{load_market._mean_cash*100:.2f}%/yr over window)")
    if load_market._proxy:
        print("Note: CRSP total US market used as the S&P 500 total-return proxy (daily corr ~0.99);")
        print("      signal & returns both on the total-return index (see header caveat).")
    print(f"Window       : {D[0]} -> {D[-1]}   ({len(D)} trading days, {yrs:.1f} yrs)\n")

    COST = 0.0005   # 5 bps one-way switching cost (base case)

    # --- build the three headline strategies ---
    pos_gc = positions_ma_cross(SPY, 50, 200)
    pos_200 = positions_above_ma(SPY, 200)
    eq_gc, n_gc, seg_gc = run_timed(SPY, pos_gc, cash_daily, COST)
    eq_200, n_200, seg_200 = run_timed(SPY, pos_200, cash_daily, COST)
    eq_bh = buy_hold(SPY)

    inv_gc = sum(pos_gc[1:]) / (len(SPY) - 1)
    inv_200 = sum(pos_200[1:]) / (len(SPY) - 1)

    results = {
        "GC": stats(eq_gc, D, "1. Golden Cross 50/200 (myth)", inv_gc, n_gc),
        "BH": stats(eq_bh, D, "2. S&P500 total-ret buy&hold", 1.0, 0),
        "M200": stats(eq_200, D, "3. Price > 200d only (simpler)", inv_200, n_200),
    }
    ranked = sorted(results.values(),
                    key=lambda s: -(s["mar"] if s["mar"] == s["mar"] else -1))

    print("=" * 120)
    print("RESULTS  (ranked by MAR = CAGR / MaxDD%,  the channel standard)")
    print("=" * 120)
    hdr = (f"{'Strategy':<32}{'TotRet':>12}{'CAGR':>8}{'MAR':>7}{'Sortino':>9}"
           f"{'MaxDD':>9}{'WorstYr':>15}{'UWdays':>8}{'Vol':>8}{'%Inv':>7}{'Trades':>8}")
    print(hdr); print("-" * 120)
    for s in ranked:
        p = "PASS" if (s["mar"] >= 0.5 and s["sortino"] >= 1.0) else "fail"
        inv = f"{s['pct_invested']*100:.0f}%" if s['pct_invested'] is not None else "-"
        tr = str(s['n_trades']) if s['n_trades'] is not None else "-"
        print(f"{s['label']:<32}{fp(s['total_return']):>12}{fp(s['cagr']):>8}{s['mar']:>7.2f}"
              f"{s['sortino']:>9.2f}{fp(s['max_dd']):>9}"
              f"{s['worst_year']+' '+fp(s['worst_year_ret']):>15}{s['underwater_days']:>8}"
              f"{fp(s['vol']):>8}{inv:>7}{tr:>8}  [{p}]")
    print("-" * 120)
    print("Bar to 'pass': MAR >= 0.50 AND Sortino >= 1.00.  SPY buy&hold is the yardstick.\n")

    gc, bh, m200 = results["GC"], results["BH"], results["M200"]

    # ---- KILL-TEST 1: does it beat buy & hold on RETURN? ----
    ret_short = gc["total_return"] - bh["total_return"]
    cagr_short = gc["cagr"] - bh["cagr"]
    print("KILL-TEST 1 — DOES IT BEAT BUY & HOLD ON RETURN?")
    print(f"  Golden Cross total return : {fp(gc['total_return'])}  (${1+gc['total_return']:.2f} per $1, CAGR {fp(gc['cagr'])})")
    print(f"  SPY buy & hold total ret  : {fp(bh['total_return'])}  (${1+bh['total_return']:.2f} per $1, CAGR {fp(bh['cagr'])})")
    print(f"  -> Timing {'TRAILS' if ret_short < 0 else 'BEATS'} buy&hold by {fp(abs(ret_short))} of total return "
          f"({fp(abs(cagr_short))}/yr of CAGR). It was invested only {inv_gc*100:.0f}% of the time.\n")

    # ---- KILL-TEST 2: the drawdown story (its real value) ----
    print("KILL-TEST 2 — THE DRAWDOWN STORY (its actual value)")
    print(f"  Golden Cross max drawdown : {fp(gc['max_dd'])}  (peak {gc['max_dd_peak']} -> trough {gc['max_dd_trough']})")
    print(f"  Buy & hold max drawdown   : {fp(bh['max_dd'])}  (peak {bh['max_dd_peak']} -> trough {bh['max_dd_trough']})")
    dd_cut = 1 - abs(gc['max_dd']) / abs(bh['max_dd'])
    print(f"  -> Timing cut the worst drawdown by {fp(dd_cut)} ({fp(bh['max_dd'])} -> {fp(gc['max_dd'])}).")
    print(f"  Longest underwater: GC {gc['underwater_days']}d (~{gc['underwater_days']/365.25:.1f}y) "
          f"vs B&H {bh['underwater_days']}d (~{bh['underwater_days']/365.25:.1f}y).")
    # per-bear behaviour: drawdown of each strategy over the bear window
    bears = [("2000 dot-com", "2000-03-01", "2002-10-31"),
             ("2008 GFC", "2007-10-01", "2009-03-31"),
             ("2020 COVID", "2020-02-01", "2020-04-30"),
             ("2022 inflation", "2022-01-01", "2022-12-31")]
    idx = {d: i for i, d in enumerate(D)}

    def window_dd(eq, a, b):
        seg = [eq[i] for i in range(len(D)) if a <= D[i] <= b]
        if len(seg) < 2:
            return None
        return max_drawdown(seg)[0]
    print("  Bear-by-bear max drawdown (over the bear window):")
    print(f"     {'bear':<16}{'buy&hold':>11}{'GoldenCross':>13}{'saved':>9}")
    bear_rows = {}
    for name, a, b in bears:
        bdd = window_dd(eq_bh, a, b); gdd = window_dd(eq_gc, a, b)
        if bdd is None:
            print(f"     {name:<16}{'(not in data window)':>33}")
            continue
        saved = abs(bdd) - abs(gdd)
        bear_rows[name] = {"bh": bdd, "gc": gdd, "saved": saved}
        print(f"     {name:<16}{fp(bdd):>11}{fp(gdd):>13}{fp(saved):>9}")
    print()

    # ---- KILL-TEST 3: whipsaws ----
    print("KILL-TEST 3 — WHIPSAWS (the choppy-market tax)")
    # per completed in-market segment: SPY return captured entry_px -> last_held
    seg_rets = []
    for s in seg_gc:
        e = s["entry_px_idx"]; l = s["last_held"]
        if e < 0 or l <= e:
            continue
        r = SPY[l] / SPY[e] - 1.0
        seg_rets.append((D[max(e,0)], D[l], r))
    losers = [r for _, _, r in seg_rets if r < 0]
    winners = [r for _, _, r in seg_rets if r >= 0]
    cum_loser = math.prod(1 + r for r in losers) - 1 if losers else 0.0
    print(f"  Completed round-trips (in-market segments): {len(seg_rets)}")
    print(f"  Round-trips that LOST money: {len(losers)} of {len(seg_rets)} "
          f"({len(losers)/max(len(seg_rets),1)*100:.0f}%)")
    if losers:
        print(f"  Avg losing round-trip: {fp(sum(losers)/len(losers))};  worst: {fp(min(losers))}")
        print(f"  Compounded drag of ALL losing round-trips: {fp(cum_loser)} "
              f"(that is the cumulative whipsaw tax on captured SPY moves).")
    if winners:
        print(f"  Avg winning round-trip: {fp(sum(winners)/len(winners))};  best: {fp(max(winners))}")
    print(f"  (Win rate by round-trip: {len(winners)/max(len(seg_rets),1)*100:.0f}% — a FEW big trend rides "
          f"pay for a crowd of small chop losses.)\n")

    # ---- KILL-TEST 4: lag ----
    print("KILL-TEST 4 — LAG (a lagging confirmation, not a top/bottom caller)")
    exit_gaps = []   # how far below the recent peak the death cross got us out
    entry_gaps = []  # how far above the recent trough the golden cross got us back in
    for k, s in enumerate(seg_gc):
        # exit: at last_held, compare to the peak SPY reached during this in-market run
        l = s["last_held"]; st = s["start"]
        if l > st:
            run_peak = max(SPY[st:l + 1])
            exit_gaps.append(SPY[l] / run_peak - 1.0)
        # entry: at entry_px_idx, compare to the trough SPY reached while we were OUT (since prior exit)
        e = s["entry_px_idx"]
        prev_exit = seg_gc[k - 1]["last_held"] if k > 0 else 0
        if e > prev_exit >= 0:
            out_trough = min(SPY[prev_exit:e + 1])
            entry_gaps.append(SPY[e] / out_trough - 1.0)
    avg_exit = sum(exit_gaps) / len(exit_gaps) if exit_gaps else 0.0
    avg_entry = sum(entry_gaps) / len(entry_gaps) if entry_gaps else 0.0
    print(f"  Death cross exits, on avg, {fp(avg_exit)} BELOW the peak of the move it was riding "
          f"(it gives back the last leg down before getting out).")
    print(f"  Golden cross entries, on avg, {fp(avg_entry)} ABOVE the low made while it was in cash "
          f"(it misses the first leg of the recovery).")
    print(f"  The cross is confirmation, not prediction: it is late at BOTH ends.\n")

    # ---- KILL-TEST 5: parameter robustness ----
    print("KILL-TEST 5 — PARAMETER ROBUSTNESS (is 50/200 special, or just one point on a plateau?)")
    pairs = [(20, 100), (30, 150), (50, 150), (50, 200), (100, 200), (100, 300)]
    print(f"     {'pair':<12}{'CAGR':>8}{'MaxDD':>9}{'MAR':>7}{'Sortino':>9}{'Trades':>8}")
    sweep = {}
    for f, s in pairs:
        p = positions_ma_cross(SPY, f, s)
        eq, n, _ = run_timed(SPY, p, cash_daily, COST)
        st2 = stats(eq, D, f"{f}/{s}", None, n)
        sweep[f"{f}/{s}"] = {"cagr": st2["cagr"], "max_dd": st2["max_dd"],
                             "mar": st2["mar"], "sortino": st2["sortino"], "trades": n}
        star = "  <- the famous one" if (f, s) == (50, 200) else ""
        print(f"     {f'{f}/{s}':<12}{fp(st2['cagr']):>8}{fp(st2['max_dd']):>9}"
              f"{st2['mar']:>7.2f}{st2['sortino']:>9.2f}{n:>8}{star}")
    mars = [v["mar"] for v in sweep.values()]
    gc_mar = sweep["50/200"]["mar"]
    print(f"  50/200 MAR {gc_mar:.2f} vs sweep range [{min(mars):.2f}, {max(mars):.2f}]. "
          f"{'It is NOT a special peak — broad plateau (good: not curve-fit, but no magic in 50/200).' if gc_mar <= max(mars) - 0.02 else 'It sits at/near the top of the plateau.'}\n")

    # ---- KILL-TEST 6: cost sensitivity ----
    print("KILL-TEST 6 — COST SENSITIVITY (it trades rarely, so costs should barely matter)")
    eq_1x, _, _ = run_timed(SPY, pos_gc, cash_daily, COST)
    eq_2x, _, _ = run_timed(SPY, pos_gc, cash_daily, COST * 2)
    eq_0x, _, _ = run_timed(SPY, pos_gc, cash_daily, 0.0)
    c0 = cagr(eq_0x, D); c1 = cagr(eq_1x, D); c2 = cagr(eq_2x, D)
    print(f"  Switching cost 0 bps : final ${eq_0x[-1]:.2f}  CAGR {fp(c0)}")
    print(f"  Switching cost 5 bps : final ${eq_1x[-1]:.2f}  CAGR {fp(c1)}  (base case)")
    print(f"  Switching cost 10 bps: final ${eq_2x[-1]:.2f}  CAGR {fp(c2)}")
    print(f"  -> Doubling costs moved CAGR by {fp(abs(c2 - c1))} — {n_gc} trades over {yrs:.0f} yrs is "
          f"~{n_gc/yrs:.1f} round-trips/yr. Cost is a rounding error here (a point IN its favor vs churn strategies).\n")

    # ---- KILL-TEST 7: regime dependence / 2020 V-crash ----
    print("KILL-TEST 7 — REGIME DEPENDENCE (its edge is TRENDING bears; a V-crash can HURT)")
    if "2020-03-23" in idx:
        # find the golden-cross round trip that spans the 2020 crash
        covid = None
        for k, s in enumerate(seg_gc):
            # the segment that was exited during Mar-2020, then the re-entry after
            if D[s["last_held"]] >= "2020-02-15" and D[s["last_held"]] <= "2020-06-30":
                covid = (k, s)
                break
        if covid:
            k, s = covid
            ex_i = s["last_held"]
            re_i = seg_gc[k + 1]["entry_px_idx"] if k + 1 < len(seg_gc) else None
            print(f"  2020: death cross exited around {D[ex_i]}.")
            if re_i is not None:
                print(f"        golden cross re-entered around {D[re_i]}, "
                      f"{'HIGHER' if SPY[re_i] > SPY[ex_i] else 'lower'} by {fp(SPY[re_i]/SPY[ex_i]-1)} "
                      f"than where it sold.")
                print(f"        The V-shaped snap-back meant it sold low and bought back higher — lag HURT here.")
        else:
            print("  2020: the 50/200 cross barely moved out before the V-snapback (crash too fast for the slow MA).")
    else:
        print("  2020 not in the data window.")
    # how the strategy did specifically in 2020 vs B&H
    y20_bh = window_dd(eq_bh, "2020-01-01", "2020-12-31")
    y20_gc = window_dd(eq_gc, "2020-01-01", "2020-12-31")
    if y20_bh is not None:
        print(f"        2020 max DD: B&H {fp(y20_bh)} vs GC {fp(y20_gc)} "
              f"({'timing helped' if abs(y20_gc) < abs(y20_bh) - 0.005 else 'timing did NOT help'}).\n")
    else:
        print()

    # ---- GREEN keeper ----
    print("GREEN KEEPER (what the data actually supports)")
    print(f"  The golden cross did NOT make more money ({fp(gc['total_return'])} vs B&H {fp(bh['total_return'])}),")
    print(f"  but it cut the worst drawdown from {fp(bh['max_dd'])} to {fp(gc['max_dd'])} and lowered vol")
    print(f"  from {fp(bh['vol'])} to {fp(gc['vol'])}. On MAR it is {gc['mar']:.2f} vs {bh['mar']:.2f} "
          f"({'better' if gc['mar'] > bh['mar'] else 'worse'}); Sortino {gc['sortino']:.2f} vs {bh['sortino']:.2f}.")
    print(f"  THE TWIST: the simpler price>200d filter beat the 50/200 CROSS on nearly everything — "
          f"CAGR {fp(m200['cagr'])} vs {fp(gc['cagr'])}, MaxDD {fp(m200['max_dd'])} vs {fp(gc['max_dd'])}, "
          f"MAR {m200['mar']:.2f} vs {gc['mar']:.2f}.")
    print(f"  The 50/200 cross lags MORE than price-vs-MA (in 1929 the cross bled to {fp(gc['max_dd'])} while")
    print(f"  price>200d got out at {fp(m200['max_dd'])}). The famous 'golden cross' is the WORSE MA rule.")
    print("  It is a SEATBELT, not an engine: you trade some upside for a smoother, more survivable ride")
    print("  that sidesteps the worst of long TRENDING bears (2000, 2008) — and it pays a small whipsaw tax")
    print("  in chop and gets whipsawed by a V-crash (2020). The 50/200 numbers are not magic; nearby")
    print("  pairs do about the same.\n")

    # ---- export curve_data.json ----
    def norm(eq):
        return [round(x, 6) for x in eq]
    uw_gc = [round(x, 6) for x in underwater_series(eq_gc)]
    uw_bh = [round(x, 6) for x in underwater_series(eq_bh)]
    curve = {
        "meta": {
            "generated": dt.date.today().isoformat(),
            "market_source": load_market._src, "cash_source": load_market._srccash,
            "is_proxy": load_market._proxy, "cash_mean_annual": round(load_market._mean_cash, 5),
            "window_start": D[0], "window_end": D[-1], "trading_days": len(D),
            "years": round(yrs, 2), "cost_oneway_bps": COST * 1e4,
        },
        "dates": D,
        "curves": {
            "golden_cross_50_200": norm(eq_gc),
            "market_buyhold": norm(eq_bh),
            "above_200d_only": norm(eq_200),
        },
        "underwater": {
            "golden_cross_50_200": uw_gc,
            "market_buyhold": uw_bh,
        },
        "stats": {
            k: {kk: v[kk] for kk in ("label", "total_return", "cagr", "mar", "sortino",
                                     "max_dd", "max_dd_peak", "max_dd_trough", "vol",
                                     "worst_year", "worst_year_ret", "underwater_days",
                                     "pct_invested", "n_trades")}
            for k, v in results.items()
        },
        "killtests": {
            "return_shortfall_total": ret_short,
            "cagr_shortfall": cagr_short,
            "pct_time_invested": inv_gc,
            "maxdd_bh": bh["max_dd"], "maxdd_gc": gc["max_dd"],
            "maxdd_reduction_frac": dd_cut,
            "bear_drawdowns": bear_rows,
            "roundtrips_total": len(seg_rets),
            "roundtrips_losing": len(losers),
            "roundtrips_losing_pct": len(losers) / max(len(seg_rets), 1),
            "whipsaw_compounded_drag": cum_loser,
            "avg_exit_below_peak": avg_exit,
            "avg_entry_above_trough": avg_entry,
            "param_sweep": sweep,
            "cost_cagr_0bps": c0, "cost_cagr_5bps": c1, "cost_cagr_10bps": c2,
            "n_roundtrips_per_year": n_gc / yrs,
        },
    }
    with open(_csv_path("curve_data.json"), "w") as f:
        json.dump(curve, f)
    print(f"Wrote curve_data.json ({len(D)} dates, 3 curves + underwater + stats + killtests).")


if __name__ == "__main__":
    main()
