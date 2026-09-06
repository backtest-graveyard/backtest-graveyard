"""Market-wide (but CURATED) amplitude screen.

Sweeps economically-tethered candidate spreads across market themes and runs the
amplitude/cointegration screen from `cointegration.analyze_spread`. This is Gate 0/1
discovery ONLY: a "pass" means "enough amplitude + real cointegration + tradeable
half-life to be worth a proper walk-forward/holdout backtest" — NOT "profitable".

Discipline notes baked in:
* No brute-force all-pairs (that is the multiple-testing catastrophe). Every candidate
  has an economic prior, listed with it.
* Redundant controls (near-identical instruments) are included ON PURPOSE — they should
  FAIL on amplitude, the same way the SPY/IVV/VOO triplet did. If they pass, the screen
  is broken.
* Single-name pairs are flagged PCA-phase: they carry idiosyncratic blow-up risk (M&A,
  guidance) and are not ETF-beachhead-eligible.
* Trials are counted. This number feeds the deflated-Sharpe correction later.
"""

from __future__ import annotations

import math
import warnings

import pandas as pd

from .cointegration import analyze_spread
from .costs import CostModel
from .data import load_panel

# (y, x, theme, kind)  kind: "etf" = beachhead-eligible, "control" = should fail,
#                              "single" = single-name (PCA-phase, higher risk)
CANDIDATES: list[tuple[str, str, str, str]] = [
    # ── commodity complex: ETF vs producers / senior vs junior (leverage divergence) ──
    ("GLD", "GDX",  "gold: metal vs miners",        "etf"),
    ("GLD", "GDXJ", "gold: metal vs junior miners", "etf"),
    ("GDX", "GDXJ", "gold: senior vs junior miners","etf"),
    ("SLV", "SIL",  "silver: metal vs miners",      "etf"),
    ("SLV", "SILJ", "silver: metal vs junior",      "etf"),
    ("SIL", "SILJ", "silver: senior vs junior",     "etf"),
    ("GLD", "SLV",  "gold/silver ratio (macro)",    "etf"),
    ("XLE", "XOP",  "energy: integrated vs E&P",    "etf"),
    ("XLE", "OIH",  "energy: sector vs services",   "etf"),
    ("XOP", "OIH",  "energy: E&P vs services",      "etf"),
    ("USO", "XLE",  "oil future vs energy equity",  "etf"),
    ("COPX","CPER", "copper: miners vs metal",      "etf"),
    ("URA", "URNM", "uranium: two miner baskets",   "etf"),
    ("SLX", "XME",  "steel vs metals&mining",       "etf"),
    ("DBA", "MOO",  "ag commodity vs agribusiness", "etf"),
    # ── sector vs sub-sector (shared driver, different beta) ──
    ("SMH", "XLK",  "semis vs broad tech",          "etf"),
    ("SOXX","XLK",  "semis vs broad tech (alt)",    "etf"),
    ("XLF", "KRE",  "financials vs regional banks", "etf"),
    ("KRE", "KBE",  "regional vs broad banks",      "etf"),
    ("XBI", "IBB",  "biotech equal- vs cap-weight", "etf"),
    ("IBB", "XLV",  "biotech vs healthcare",        "etf"),
    ("XHB", "ITB",  "homebuilders two baskets",     "etf"),
    ("IYT", "XLI",  "transports vs industrials",    "etf"),
    ("XRT", "XLY",  "retail vs consumer disc.",     "etf"),
    # ── country / region (same economy, different wrapper) ──
    ("EWA", "EWC",  "Australia vs Canada (comdty)", "etf"),
    ("EWJ", "DXJ",  "Japan unhedged vs hedged",     "etf"),
    ("FXI", "MCHI", "China large-cap two wrappers", "etf"),
    ("EWG", "EWQ",  "Germany vs France",            "etf"),
    # ── rates / credit ──
    ("TLT", "IEF",  "long vs intermediate Tsy",     "etf"),
    ("LQD", "IEF",  "IG credit vs Tsy",             "etf"),
    ("HYG", "LQD",  "high-yield vs IG credit",      "etf"),
    ("TIP", "IEF",  "TIPS vs nominal Tsy",          "etf"),
    # ── crypto-equity proxies (same underlying BTC) ──
    ("BITO","GBTC", "BTC futures ETF vs trust",     "etf"),
    ("IBIT","GBTC", "BTC spot ETF vs trust",        "etf"),
    # ── REDUNDANT CONTROLS: should FAIL on amplitude (like SPY/IVV/VOO) ──
    ("QQQ", "QQQM", "Nasdaq-100 twins (control)",   "control"),
    ("IWM", "VTWO", "Russell-2000 twins (control)", "control"),
    ("VTI", "ITOT", "total-market twins (control)", "control"),
    ("EEM", "IEMG", "EM twins (control)",           "control"),
    ("EFA", "IEFA", "developed-mkt twins (control)","control"),
    ("HYG", "JNK",  "high-yield twins (control)",   "control"),
    # ── single-name pairs (PCA-phase; idiosyncratic blow-up risk) ──
    ("KO",  "PEP",  "beverages duopoly",            "single"),
    ("V",   "MA",   "card networks duopoly",        "single"),
    ("HD",  "LOW",  "home-improvement duopoly",     "single"),
    ("GM",  "F",    "legacy US autos",              "single"),
    ("XOM", "CVX",  "oil supermajors",              "single"),
    ("UPS", "FDX",  "parcel logistics",             "single"),
    ("WMT", "TGT",  "big-box retail",               "single"),
    ("JPM", "BAC",  "money-center banks",            "single"),
]


def run_scan(lookback_days: int = 3 * 365) -> pd.DataFrame:
    warnings.filterwarnings("ignore")
    symbols = sorted({s for a, b, _, _ in CANDIDATES for s in (a, b)})
    print(f"loading {len(symbols)} symbols, {len(CANDIDATES)} candidate spreads ...")
    panel = load_panel(symbols, lookback_days=lookback_days)
    close, stats = panel.close, panel.stats
    have = set(close.columns)
    cm = CostModel()

    rows = []
    skipped = []
    for a, b, theme, kind in CANDIDATES:
        if a not in have or b not in have:
            skipped.append((f"{a}~{b}", theme, [s for s in (a, b) if s not in have]))
            continue
        d = analyze_spread(a, b, close, cost_model=cm, stats=stats)
        rows.append({
            "spread": f"{d.y}~{d.x}", "theme": theme, "kind": kind,
            "adf_p": d.adf_pvalue, "half_life": d.half_life_days,
            "sigma_bps": d.sigma_resid_bps, "pct_gt2z": d.frac_beyond_2z * 100,
            "gross_bps": d.gross_edge_bps, "cost_bps": d.cost_bps,
            "net_bps": d.net_edge_bps, "tradeable": d.tradeable,
        })
    df = pd.DataFrame(rows)
    return df, skipped, panel


if __name__ == "__main__":
    df, skipped, panel = run_scan()
    n_trials = len(df)

    def fmt(sub: pd.DataFrame) -> str:
        lines = []
        for _, r in sub.iterrows():
            hl = f"{r.half_life:.0f}d" if math.isfinite(r.half_life) else "inf"
            flag = "TRADEABLE" if r.tradeable else "reject"
            lines.append(f"  {r.spread:12s} {r.adf_p:6.3f} {hl:>5s} {r.sigma_bps:7.0f} "
                         f"{r.pct_gt2z:5.1f}% {r.cost_bps:6.1f} {r.net_bps:8.0f}  {flag:9s} {r.theme}")
        return "\n".join(lines)

    hdr = f"  {'spread':12s} {'adf_p':>6s} {'  hl':>5s} {'σ_bps':>7s} {'|z|>2':>6s} {'cost':>6s} {'net_bps':>8s}  verdict"

    passed = df[df.tradeable].sort_values("adf_p")
    failed = df[~df.tradeable].sort_values("adf_p")

    print(f"\n{'='*100}\nAMPLITUDE SCREEN — {n_trials} spreads tested "
          f"(source={panel.source}, {panel.close.shape[0]} sessions)\n{'='*100}")
    print(f"\n### PASSED the screen ({len(passed)}) — earn a real walk-forward/holdout test ###")
    print(hdr); print(fmt(passed))
    print(f"\n### REJECTED ({len(failed)}) ###")
    print(hdr); print(fmt(failed))

    # sanity: how did the redundant controls do? (they should all reject)
    ctrl = df[df.kind == "control"]
    ctrl_pass = ctrl[ctrl.tradeable]
    print(f"\n### control check: {len(ctrl)} redundant pairs, {len(ctrl_pass)} passed "
          f"(expect 0 — a pass means the screen is broken) ###")

    if skipped:
        print(f"\n### skipped (missing data): {len(skipped)} ###")
        for sp, theme, miss in skipped:
            print(f"  {sp:12s} missing {miss}  ({theme})")

    print(f"\nTRIALS LEDGER: +{n_trials} spreads tested this scan (running total feeds "
          f"the deflated-Sharpe correction). Amplitude pass != profit.")
