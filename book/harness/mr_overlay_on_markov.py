import os
"""
mr_overlay_on_markov.py — does the DBMR dip-buy sleeve diversify the Markov book?
=================================================================================
Markov sits ~87% in idle cash (live) and gets whipsawed on short-term pullbacks
(NVDA: flipped Bull->Sideways selling into a dip). DBMR BUYS those dips. Thesis:
they are negatively correlated on that failure mode, so blending them lifts the
COMBINED book's MAR/Sortino. Test it honestly.

Two framings reported:
  A) RISK-SPLIT (w_m + w_d = 1): split one risk budget between Markov and DBMR.
     Answers "does DBMR diversify Markov's risk?" (strategy-quality question).
  B) ADDITIVE (Markov 100% + DBMR funded from idle cash): the live account is only
     ~13% deployed, so DBMR on the idle 87% is ~free capital. Answers the practical
     "does it help the under-deployed live account?" question.

Both books are per-dollar-of-strategy daily returns on ONE common window. Metrics via
trend_analytics (same grader). DBMR credits its idle cash at 4% (T-bill).
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
import warnings; warnings.filterwarnings("ignore")

MB = Path(os.environ.get("MARKOV_ROOT", "./markov"))
sys.path.insert(0, str(MB)); sys.path.insert(0, str(MB / "scripts"))

import trend_analytics as ta
import trend_core as tc
import mr_dipbuy_backtest as mr

# ---- Markov book (live EQUAL-9), reuse the validated return path -----------------
import json
from voladaptive_prototype import strat_returns
from markov_bot import fetch_history

fleet = json.loads((MB / "fleet.json").read_text())["slots"]
enabled = [s for s in fleet if s.get("enabled", True)]
print(f"Markov slots (EQUAL-9 live): {[s['name'] for s in enabled]}")
mkv = {s["name"]: strat_returns(fetch_history(s["yfinance_ticker"], years=5), s["asset_class"], 0.5)
       for s in enabled}
Pm = pd.concat(mkv, axis=1).sort_index().dropna()
markov_ret = pd.Series(Pm.mean(axis=1), index=Pm.index)   # equal-weight book

# ---- DBMR book (14 ETFs, 4% cash carry) ------------------------------------------
dbmr_data = {lbl: tc.load(sym, mr.START, mr.END, auto_adjust=True) for lbl, sym in mr.UNIVERSE.items()}
rep_d = mr.run(dbmr_data, rf_annual=0.04)
dbmr_ret = rep_d["_port_ret"]

# ---- align to common window ------------------------------------------------------
df = pd.concat({"markov": markov_ret, "dbmr": dbmr_ret}, axis=1).dropna()
mk, db = df["markov"], df["dbmr"]
print(f"Common window: {df.index.min().date()} → {df.index.max().date()}  ({len(df)} days)")
print(f"Correlation(markov, dbmr) = {mk.corr(db):+.3f}")

def m(series):
    eq = (1 + series).cumprod()
    return ta.perf_metrics(eq, series)

def row(label, series):
    x = m(series)
    return f"{label:<34s} | MAR {x['mar']:>5.2f} | Sortino {x['sortino']:>5.2f} | Sharpe {x['sharpe']:>5.2f} | CAGR {x['cagr']*100:>5.1f}% | MaxDD {x['max_dd']*100:>6.1f}%"

print("\n" + "=" * 104)
print("BASELINES")
print("=" * 104)
print(row("Markov book (EQUAL-9)", mk))
print(row("DBMR book (4% carry)", db))

print("\n" + "=" * 104)
print("A) RISK-SPLIT  (w_markov + w_dbmr = 1) — does DBMR diversify Markov's risk budget?")
print("=" * 104)
best = ("Markov-only", m(mk)["mar"], m(mk)["sortino"])
for wd in [0.0, 0.10, 0.20, 0.30, 0.40, 0.50]:
    blend = (1 - wd) * mk + wd * db
    x = m(blend)
    tag = "  <-- Markov-only" if wd == 0 else ""
    print(row(f"  {int((1-wd)*100)}% Markov / {int(wd*100)}% DBMR", blend) + tag)
    if x["mar"] > best[1]:
        best = (f"{int((1-wd)*100)}/{int(wd*100)}", x["mar"], x["sortino"])

# risk-parity (inverse-vol) blend
vm, vd = mk.std(), db.std()
wrp = (1 / vd) / (1 / vm + 1 / vd)
rp = (1 - wrp) * mk + wrp * db
print(row(f"  risk-parity ({int((1-wrp)*100)}/{int(wrp*100)})", rp))

print("\n" + "=" * 104)
print("B) ADDITIVE  (Markov 100% + DBMR on idle cash) — helps the ~13%-deployed live account?")
print("=" * 104)
for xd in [0.0, 0.25, 0.50, 1.0]:
    blend = mk + xd * db
    print(row(f"  Markov + {xd:.2f}x DBMR overlay", blend))

print("\n" + "=" * 104)
mk_x = m(mk)
print(f"VERDICT INPUTS: corr={mk.corr(db):+.3f} | Markov-only MAR {mk_x['mar']:.2f}/Sortino {mk_x['sortino']:.2f}")
print(f"Best risk-split by MAR: {best[0]} (MAR {best[1]:.2f}/Sortino {best[2]:.2f})")
print("If no blend beats Markov-only on BOTH MAR and Sortino, the overlay does not add risk-adjusted value.")
