#!/usr/bin/env python3
"""DCA vs Lump-Sum kill-test for The Backtest Graveyard (Ep11).

Question tested (the viral one): you have a lump sum in hand today. Is it better to invest it all
at once (lump-sum, LS), or spread it in equal monthly buys over N months (dollar-cost averaging,
DCA)? The honest, fair comparison lets the DCA money that hasn't been deployed yet earn the
risk-free T-bill rate (naive studies assume cash earns 0%, which unfairly inflates LS's edge).

Data: Ken French monthly US total-market return (Mkt-RF + RF) + 1-month T-bill (RF), 1926-07 to
2026-07 (ff_factors_monthly.csv). Total-return, dividends included. Nominal (not inflation-adj);
that's fine because LS and DCA face the same inflation.

Model (fair): start with $1 cash. Each month for N months, deploy a fixed nominal $1/N into the
market; the still-undeployed cash earns that month's T-bill. After N months the whole $1 of
principal is invested (plus whatever interest the waiting cash earned). The LS/DCA *relative*
result is locked in at the end of the deployment window (after that both are fully invested and
grow identically), so terminal wealth is measured at month N.
"""
import csv, os, statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
rows = []
with open(os.path.join(HERE, "ff_factors_monthly.csv")) as f:
    for line in f:
        p = line.strip().split(",")
        if len(p) == 5 and p[0].strip().isdigit() and len(p[0].strip()) == 6:
            ym = p[0].strip()
            mktrf, rf = float(p[1]), float(p[4])
            rows.append((ym, (mktrf + rf) / 100.0, rf / 100.0))   # (yyyymm, total mkt ret, rf)
rows.sort()
YM = [r[0] for r in rows]
R = [r[1] for r in rows]
RF = [r[2] for r in rows]
n = len(rows)
print(f"months: {n}  ({YM[0]} .. {YM[-1]})")


def run(start, N, cash_earns_rf=True):
    """Return (LS_terminal, DCA_terminal) for a $1 stake, measured at end of the N-month window."""
    # lump sum: $1 fully invested at month `start`
    ls = 1.0
    for k in range(N):
        ls *= (1 + R[start + k])
    # DCA: deploy $1/N nominal each month; undeployed cash earns RF (or 0 if naive)
    invested, cash = 0.0, 1.0
    c = 1.0 / N
    for k in range(N):
        invested += c
        cash -= c
        invested *= (1 + R[start + k])
        cash *= (1 + (RF[start + k] if cash_earns_rf else 0.0))
    return ls, invested + cash


def summary(N, cash_earns_rf=True):
    last = n - N
    diffs, ratios, ls_wins = [], [], 0
    per = []
    for s in range(0, last + 1):
        ls, dca = run(s, N, cash_earns_rf)
        ratios.append(ls / dca)
        diffs.append(ls - dca)
        per.append((YM[s], ls, dca, ls / dca - 1))
        if ls > dca:
            ls_wins += 1
    m = len(ratios)
    winrate = ls_wins / m
    mean_edge = st.mean(r - 1 for r in ratios)
    med_edge = st.median(r - 1 for r in ratios)
    ls_win_edges = [r - 1 for r in ratios if r > 1]
    dca_win_edges = [1 - r for r in ratios if r < 1]  # how much DCA won by
    # worst LS windows = biggest DCA outperformance
    per_sorted = sorted(per, key=lambda x: x[3])
    print(f"\n=== N={N} months  (cash earns {'T-bill' if cash_earns_rf else '0%'})  windows={m} ===")
    print(f"  Lump-sum wins: {winrate*100:.1f}% of all rolling {N}-month windows")
    print(f"  Avg lump-sum edge: {mean_edge*100:+.2f}%   median: {med_edge*100:+.2f}%")
    print(f"  When LS wins (n={len(ls_win_edges)}): avg +{st.mean(ls_win_edges)*100:.2f}%")
    print(f"  When DCA wins (n={len(dca_win_edges)}): avg +{st.mean(dca_win_edges)*100:.2f}% (DCA's margin)")
    print(f"  Worst 6 starts for lump-sum (DCA saved you most):")
    for ym, ls, dca, e in per_sorted[:6]:
        print(f"     {ym[:4]}-{ym[4:]}: LS {ls:.3f} vs DCA {dca:.3f}  -> DCA won by {-e*100:.1f}%")
    return winrate, mean_edge


print("\n########## FAIR MODEL (DCA cash earns the T-bill) ##########")
for N in (6, 12, 24):
    summary(N, cash_earns_rf=True)

print("\n########## NAIVE MODEL (DCA cash earns 0% — the inflated-LS version) ##########")
summary(12, cash_earns_rf=False)

# --- max intra-window drawdown of deployed capital: the 'sequence risk' DCA protects against ---
def max_dd_lumpsum(start, N):
    peak, mdd, v = 1.0, 0.0, 1.0
    for k in range(N):
        v *= (1 + R[start + k])
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    return mdd
N = 12
mdds = [max_dd_lumpsum(s, N) for s in range(0, n - N + 1)]
print(f"\n=== Sequence risk (N=12): worst-case drawdown DURING the deployment year ===")
print(f"  Lump-sum median max-DD in the first year: {st.median(mdds)*100:.1f}%")
print(f"  Lump-sum WORST first-year DD across history: {min(mdds)*100:.1f}%")
print(f"  (DCA caps this: at most ~1/12 of capital is exposed in month 1, ramping to full by month 12.)")

# --- export scalars for the chart pack (charts derive from data, not hardcoded) ---
def winrate(N, rf=True):
    w = m = 0; edges = []
    for s in range(0, n - N + 1):
        ls, dca = run(s, N, rf); m += 1
        if ls > dca: w += 1
        edges.append(ls / dca - 1)
    return w / m, sum(edges) / len(edges)

import json
_cd = {
    "win6": round(winrate(6)[0] * 100, 1),
    "win12": round(winrate(12)[0] * 100, 1),
    "win24": round(winrate(24)[0] * 100, 1),
    "win12_naive": round(winrate(12, False)[0] * 100, 1),
    "edge12": round(winrate(12)[1] * 100, 2),
    "ls_worst_first_year_dd": round(min(mdds) * 100, 1),
    "span": f"{YM[0][:4]}-{YM[-1][:4]}",
}
json.dump(_cd, open(os.path.join(HERE, "chart_data.json"), "w"), indent=1)
print("\nchart_data.json:", _cd)
