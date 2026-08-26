#!/usr/bin/env python3
"""Chart pack for Episode 1 (overnight effect). Reuses data functions from
overnight_earnings_backtest.py; renders 1920x1080 dark-theme PNGs into charts/.

Numbers for chart3 are the recorded results from
OVERNIGHT_EFFECT_EARNINGS_NIGHT_RESULTS_2026_08_23.md (not recomputed here).
"""

import math
import os
import sys
from datetime import date

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

REPO = os.path.dirname(os.path.abspath(__file__))  # harness lives alongside
sys.path.insert(0, REPO)
from overnight_earnings_backtest import (  # noqa: E402
    UNIVERSE, earnings_events, fetch_bars, load_alpaca_creds, build_gaps)

OUT = os.path.join(REPO, "charts")
os.makedirs(OUT, exist_ok=True)

# dataviz reference palette, dark mode (first three categorical slots)
SURFACE = "#1a1a19"
INK = "#ffffff"
INK2 = "#c3c2b7"
MUTED = "#898781"
GRID = "#2c2c2a"
BASE = "#383835"
BLUE, ORANGE, AQUA = "#3987e5", "#d95926", "#199e70"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "text.color": INK, "axes.labelcolor": INK2,
    "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.edgecolor": BASE, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.grid": True, "axes.axisbelow": True,
    "axes.spines.top": False, "axes.spines.right": False,
    "font.family": "sans-serif", "font.size": 16,
    "axes.titlesize": 24, "axes.titleweight": "bold", "axes.titlepad": 18,
    "legend.frameon": False,
})
FIG = dict(figsize=(16, 9), dpi=120)


def d(s):
    return date.fromisoformat(s)


def save(fig, name):
    fig.savefig(os.path.join(OUT, name), bbox_inches=None)
    plt.close(fig)
    print("wrote", name)


def series_from_bars(bars):
    days = [d(b["t"][:10]) for b in bars]
    o = [b["o"] for b in bars]
    c = [b["c"] for b in bars]
    night, intra, hold = [1.0], [c[0] / o[0]], [1.0]
    for i in range(1, len(bars)):
        night.append(night[-1] * o[i] / c[i - 1])
        intra.append(intra[-1] * c[i] / o[i])
        hold.append(hold[-1] * c[i] / c[i - 1])
    return days, night, intra, hold


def main():
    key, sec = load_alpaca_creds()
    print("Fetching bars: MU NVDA SPY ...")
    bars = {s: fetch_bars(s, key, sec) for s in ("MU", "NVDA", "SPY")}
    print("Fetching EDGAR events: MU NVDA ...")
    gaps = {}
    for sym in ("MU", "NVDA"):
        ev = earnings_events(UNIVERSE[sym])
        gaps[sym], _ = build_gaps(ev, bars[sym])

    # ---- chart 1: MU overnight vs intraday vs buy & hold -------------------
    days, night, intra, hold = series_from_bars(bars["MU"])
    fig, ax = plt.subplots(**FIG)
    ax.set_yscale("log")
    ax.plot(days, hold, color=AQUA, lw=2, label="Buy & hold")
    ax.plot(days, night, color=BLUE, lw=2, label="Overnight only (close→open)")
    ax.plot(days, intra, color=ORANGE, lw=2, label="Intraday only (open→close)")
    # end labels, dodged in log space so converging endpoints don't collide
    ends = sorted([(night[-1], BLUE, f"overnight  {night[-1]:,.0f}x"),
                   (hold[-1], AQUA, f"buy & hold  {hold[-1]:,.0f}x"),
                   (intra[-1], ORANGE, f"intraday  {intra[-1]:.2f}x")])
    ys = [math.log10(v) for v, _, _ in ends]
    min_gap = 0.16  # decades of separation between label centers
    for i in range(1, len(ys)):
        ys[i] = max(ys[i], ys[i - 1] + min_gap)
    for (val, col, txt), y in zip(ends, ys):
        ax.annotate(txt, (days[-1], 10 ** y), xytext=(12, 0),
                    textcoords="offset points", color=col, fontsize=17,
                    fontweight="bold", va="center")
    ax.set_title("Micron since 2016: the entire return happened overnight")
    ax.set_ylabel("Growth of $1 (log scale)")
    ax.legend(loc="upper left")
    ax.margins(x=0.14)
    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    fig.text(0.5, 0.018,
             "documented in:  Cooper, Cliff & Gulen (2008)   ·   Lou, Polk & "
             "Skouras, Journal of Financial Economics (2019)   ·   Knuteson (2016–22)",
             ha="center", color=MUTED, fontsize=15)
    save(fig, "chart1_split_MU.png")

    # ---- chart 2: earnings-night-only equity, full vs drop-top-5 -----------
    fig, axes = plt.subplots(1, 2, **FIG)
    for ax, sym in zip(axes, ("MU", "NVDA")):
        g = gaps[sym]
        dts = [d(x) for x, _ in g]
        eq, eqk = [1.0], [1.0]
        top5 = set(sorted(range(len(g)), key=lambda i: g[i][1])[-5:])
        for i, (_, mult) in enumerate(g):
            eq.append(eq[-1] * mult)
            eqk.append(eqk[-1] * (1.0 if i in top5 else mult))
        xs = [dts[0]] + dts
        ax.plot(xs, eq, color=BLUE, lw=2, drawstyle="steps-post",
                label="All earnings nights")
        ax.plot(xs, eqk, color=BLUE, lw=2, ls="--", alpha=0.75,
                drawstyle="steps-post", label="Minus 5 best nights")
        ax.annotate(f"{eq[-1]:.2f}x", (xs[-1], eq[-1]), xytext=(8, 4),
                    textcoords="offset points", color=BLUE,
                    fontsize=16, fontweight="bold")
        ax.annotate(f"{eqk[-1]:.2f}x", (xs[-1], eqk[-1]), xytext=(8, -14),
                    textcoords="offset points", color=INK2, fontsize=16)
        # print reconciliation stats for the script
        years = (dts[-1] - dts[0]).days / 365.25
        peak, maxdd = 1.0, 0.0
        for v in eq:
            peak = max(peak, v)
            maxdd = max(maxdd, 1 - v / peak)
        cagr = eq[-1] ** (1 / years) - 1
        cagr_k = eqk[-1] ** (1 / years) - 1
        rets = [m - 1 for _, m in g]
        wr = sum(1 for r in rets if r > 0) / len(rets)
        print(f"STATS {sym}: n={len(g)} cum={eq[-1]:.2f}x CAGR={cagr*100:+.1f}% "
              f"MaxDD={maxdd*100:.1f}% MAR={cagr/maxdd:.2f} WR={wr*100:.0f}% "
              f"avg={sum(rets)/len(rets)*100:+.1f}% "
              f"drop5={eqk[-1]:.2f}x ({cagr_k*100:+.1f}%/yr)")
        ax.set_title(f"{sym} — {len(g)} earnings nights")
        ax.legend(loc="upper left")
        ax.margins(x=0.10)
        ax.xaxis.set_major_locator(mdates.YearLocator(3))
    axes[0].set_ylabel("Growth of $1")
    fig.suptitle("Hold only over earnings nights: 5 nights ARE the strategy",
                 fontsize=24, fontweight="bold")
    save(fig, "chart2_earnings_nights.png")

    # ---- chart 4: distribution of earnings-night returns -------------------
    rets = [(m - 1) * 100 for sym in ("MU", "NVDA") for _, m in gaps[sym]]
    top5 = sorted(rets)[-5:]
    rest = sorted(rets)[:-5]
    bins = [x - 20 for x in range(0, 49, 2)]
    fig, ax = plt.subplots(**FIG)
    ax.hist(rest, bins=bins, color=BLUE, edgecolor=SURFACE, lw=2,
            label="All other nights")
    ax.hist(top5, bins=bins, color=ORANGE, edgecolor=SURFACE, lw=2,
            label="The 5 best nights — the whole strategy")
    ax.axvline(0, color=BASE, lw=1.5)
    ax.set_title("86 earnings-night returns (MU + NVDA): a coin flip with fat tails")
    ax.set_xlabel("Overnight return across the announcement (%)")
    ax.set_ylabel("Nights")
    ax.set_ylim(0, 16)
    ax.legend(loc="upper left")
    med = sorted(rets)[len(rets) // 2]
    ax.annotate(f"median {med:+.1f}%   ·   worst {min(rets):+.1f}%   ·   best {max(rets):+.1f}%",
                (0.02, 0.79), xycoords="axes fraction", color=INK2, fontsize=17)
    save(fig, "chart4_night_histogram.png")

    # ---- chart 5: the cost wall --------------------------------------------
    n = 2674
    bps = [x / 2 for x in range(0, 31)]
    mult = [math.exp(-n * b / 10000) for b in bps]
    fig, ax = plt.subplots(**FIG)
    ax.set_yscale("log")
    ax.plot(bps, mult, color=BLUE, lw=2.5)
    for b, lbl in ((5, "5 bps: keep 26%"), (10, "10 bps: keep 7%")):
        m = math.exp(-n * b / 10000)
        ax.plot([b], [m], "o", color=ORANGE, ms=10)
        ax.annotate(lbl, (b, m), xytext=(12, 8), textcoords="offset points",
                    color=ORANGE, fontsize=18, fontweight="bold")
    ax.axhline(1.0, color=BASE, lw=1.5)
    ax.set_title("2,674 nightly round trips: what trading costs do to your equity")
    ax.set_xlabel("Round-trip cost (basis points)")
    ax.set_ylabel("Fraction of equity kept after 10.6 years (log)")
    save(fig, "chart5_cost_wall.png")

    # ---- chart 3: kill ladder (recorded results, not recomputed) -----------
    rows = [  # (label, MAR)
        ("Hand-picked 14 names (hindsight)", 0.80),
        ("Ex-ante 10 names — full window", 0.62),
        ("Ex-ante 10 names — 2021→2026", 0.31),
        ("Point-in-time top-10 by $ volume", 0.48),
        ("Point-in-time top-20 (primary)", 0.07),
        ("Point-in-time top-20 — last 3 yrs", -0.19),
        ("Point-in-time top-30", -0.03),
    ]
    labels = [r[0] for r in rows][::-1]
    vals = [r[1] for r in rows][::-1]
    fig, ax = plt.subplots(**FIG)
    ax.barh(labels, vals, color=BLUE, height=0.62)
    ax.axvline(0.5, color=ORANGE, lw=2, ls="--")
    ax.annotate("ship bar: MAR ≥ 0.5", (0.5, len(rows) - 0.35),
                color=ORANGE, fontsize=18, fontweight="bold",
                xytext=(8, 0), textcoords="offset points")
    ax.axvline(0, color=BASE, lw=1.5)
    for i, v in enumerate(vals):
        ax.annotate(f"{v:+.2f}", (v, i),
                    xytext=(8 if v >= 0 else -8, 0), textcoords="offset points",
                    color=INK, fontsize=17, fontweight="bold",
                    va="center", ha="left" if v >= 0 else "right")
    ax.set_title("The more honestly you pick the stocks, the worse it gets")
    ax.set_xlabel("MAR (CAGR ÷ max drawdown), pooled earnings-night book, 5 bps")
    ax.set_xlim(-0.35, 1.0)
    ax.grid(axis="y", visible=False)
    fig.subplots_adjust(left=0.30)
    save(fig, "chart3_kill_ladder.png")


if __name__ == "__main__":
    main()
