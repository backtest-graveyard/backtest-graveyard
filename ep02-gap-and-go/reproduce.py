#!/usr/bin/env python3
"""
Reproduce the kill-test numbers and charts for Episode 2 (gap-and-go) straight
from the trade log. No credentials, no data feed — everything below is computed
from ./trades.csv (537 trades, the exact log analysed in the video).

    python3 reproduce.py            # print the verification table
    python3 reproduce.py --charts   # also regenerate the two kill-test charts

The point of the channel: you should be able to run this and get the same numbers.
If you get something different, open an issue — corrections get pinned.
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TRADES = os.path.join(HERE, "trades.csv")


def load():
    with open(TRADES, newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["pnl"] = float(r["pnl"])
        r["r_mult"] = float(r["r_mult"])
    return rows


def verify(rows):
    n = len(rows)
    dollars = sum(r["pnl"] for r in rows)
    total_R = sum(r["r_mult"] for r in rows)
    wins = sum(1 for r in rows if r["outcome"] == "WIN")
    by_R = sorted(rows, key=lambda r: r["r_mult"], reverse=True)
    dates = sorted(r["date"] for r in rows)

    def strip(k):
        return total_R - sum(r["r_mult"] for r in by_R[:k])

    print(f"\n  GAP-AND-GO — {n} trades, {dates[0]} to {dates[-1]}")
    print("  " + "-" * 58)
    print(f"  Headline P&L (~$200k deployed) : ${dollars:>10,.0f}   ({total_R:+.1f}R)")
    print(f"  Win rate                       : {wins}/{n} = {wins/n*100:.0f}%")
    print(f"  Average trade                  : ${dollars/n:>10,.2f}   ({total_R/n:+.3f}R)")
    print()
    print("  The lottery — strip the best trades (by risk-multiple):")
    print(f"    all {n} trades               : {total_R:+6.1f}R")
    print(f"    minus top 3                  : {strip(3):+6.1f}R"
          f"   (top 3 = {sum(r['r_mult'] for r in by_R[:3])/total_R*100:.0f}% of all profit)")
    print(f"    minus top 5                  : {strip(5):+6.1f}R   <-- goes negative")
    print(f"    minus top 10                 : {strip(10):+6.1f}R")
    print()
    print("  The 5 tickets that ARE the strategy (by R):")
    for r in by_R[:5]:
        print(f"    {r['date']}  {r['symbol']:<6}  {r['r_mult']:+5.1f}R   ${r['pnl']:>8,.0f}")
    print("  " + "-" * 58)
    print("  Read it however you like: without a handful of lucky mornings that")
    print("  nothing measurable predicts in advance, the edge is gone.\n")
    return by_R, total_R


def charts(rows, by_R, total_R):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    SURFACE, INK, MUTED = "#1a1a19", "#f5f5f2", "#898781"
    BLUE, ORANGE, GRID = "#3987e5", "#f2662e", "#2c2c2a"
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "text.color": INK, "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED,
        "axes.edgecolor": "#383835", "grid.color": GRID, "axes.grid": True, "axes.axisbelow": True,
        "axes.spines.top": False, "axes.spines.right": False, "font.size": 13,
    })
    out = os.path.join(HERE, "charts", "reproduced")
    os.makedirs(out, exist_ok=True)

    # strip ladder
    labels = [f"all {len(rows)}", "minus top 3", "minus top 5", "minus top 10"]
    vals = [total_R,
            total_R - sum(r["r_mult"] for r in by_R[:3]),
            total_R - sum(r["r_mult"] for r in by_R[:5]),
            total_R - sum(r["r_mult"] for r in by_R[:10])]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.barh(range(len(vals))[::-1], vals,
            color=[BLUE if v >= 0 else ORANGE for v in vals])
    ax.set_yticks(range(len(vals))[::-1]); ax.set_yticklabels(labels)
    for i, v in enumerate(vals):
        ax.text(v, (len(vals) - 1 - i), f"  {v:+.1f}R", va="center",
                ha="left" if v >= 0 else "right", color=INK)
    ax.axvline(0, color=MUTED, lw=1); ax.set_xlabel("total profit in R (risk units)")
    ax.set_title("3 trades were 92% of the profit; without 5, it's a losing strategy")
    fig.tight_layout(); fig.savefig(os.path.join(out, "strip_ladder.png"), dpi=110); plt.close(fig)

    # R histogram, top 5 highlighted
    rs = [r["r_mult"] for r in rows]
    cut = sorted(rs, reverse=True)[4]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.hist([r for r in rs if r < cut], bins=40, color=BLUE, label=f"{len(rows)-5} trades: net ~ zero")
    ax.hist([r for r in rs if r >= cut], bins=40, color=ORANGE, label="the 5 lottery tickets")
    ax.set_yscale("log"); ax.set_xlabel("trade outcome in R (multiples of risk)")
    ax.set_ylabel("trades (log)"); ax.legend()
    ax.set_title("The whole strategy is the right-hand tail")
    fig.tight_layout(); fig.savefig(os.path.join(out, "r_histogram.png"), dpi=110); plt.close(fig)
    print(f"  regenerated charts -> {out}\n")


if __name__ == "__main__":
    rows = load()
    by_R, total_R = verify(rows)
    if "--charts" in sys.argv:
        charts(rows, by_R, total_R)
