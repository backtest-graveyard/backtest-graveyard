"""killtests.py — the tests that did the killing in The Backtest Graveyard.

Every function here takes plain data (a list/array of per-contributor P&L, or a
returns series) and answers one question. Nothing depends on a particular
backtester, broker, or data vendor. Copy this file into your own project.

The order below is the order to run them, cheapest first. Stop at the first
failure; there is no point costing a strategy whose universe is corrupt.

    from killtests import (
        mar, sortino, drop_top_n, cost_curve, matched_exposure,
        random_subset_control, breadth,
    )
"""
from __future__ import annotations
import math
import random
from typing import Iterable, Sequence

__all__ = ["mar", "sortino", "max_drawdown", "profit_factor", "drop_top_n",
           "cost_curve", "matched_exposure", "random_subset_control", "breadth",
           "summary"]

BAR_MAR, BAR_SORTINO = 0.5, 1.0     # the standard applied throughout the book


# --------------------------------------------------------------------- metrics
def max_drawdown(equity: Sequence[float]) -> float:
    """Worst peak-to-trough decline, as a positive fraction (0.35 == -35%)."""
    peak, worst = -math.inf, 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            worst = max(worst, (peak - v) / peak)
    return worst


def mar(cagr: float, max_dd: float) -> float:
    """Return per unit of pain. CAGR / maxDD. The book's primary ranking metric.

    A MAR of 1.0 means you earn back your worst drawdown once a year. Below ~0.5
    a human being will not stay in the seat long enough to collect."""
    return float("inf") if max_dd == 0 else cagr / max_dd


def sortino(returns: Sequence[float], rf: float = 0.0, periods: int = 252) -> float:
    """Return per unit of DOWNSIDE deviation. Upside volatility is not risk."""
    if not len(returns):
        return 0.0
    excess = [r - rf / periods for r in returns]
    downside = [min(0.0, e) for e in excess]
    dd = math.sqrt(sum(d * d for d in downside) / len(downside))
    if dd == 0:
        return float("inf")
    return (sum(excess) / len(excess)) / dd * math.sqrt(periods)


def profit_factor(pnl: Sequence[float]) -> float:
    """Gross wins / gross losses. Below 1.0 you lost money. A fast lie detector."""
    wins = sum(p for p in pnl if p > 0)
    losses = -sum(p for p in pnl if p < 0)
    return float("inf") if losses == 0 else wins / losses


# ------------------------------------------------------------- the lottery test
def drop_top_n(pnl: Sequence[float], n: int = 5) -> dict:
    """THE kill test. Remove the n largest positive contributors and re-total.

    `pnl` is per-contributor profit in whatever unit your strategy operates in —
    per trade, per name, or per month. Use the unit the strategy actually makes
    decisions in; a per-trade view of a monthly-rebalanced book is misleading.

    Read the SHAPE of the result, not just the number:
      sign flip      -> no edge. Losers were always losing; winners masked it.
      collapse to ~0 -> the pattern may be real, the business is not.
      degrades, survives -> a real edge, possibly too concentrated to trade.

    In the book this killed six of fourteen strategies AFTER conventional metrics
    had cleared them."""
    pnl = list(pnl)
    total = sum(pnl)
    kept = sorted(pnl, reverse=True)[n:]
    stripped = sum(kept)
    gross_pos = sum(p for p in pnl if p > 0) or 1.0
    top_share = sum(sorted(pnl, reverse=True)[:n]) / gross_pos
    if total == 0:
        shape = "undefined"
    elif stripped < 0 < total:
        shape = "SIGN FLIP — no edge"
    elif abs(stripped) < abs(total) * 0.15:
        shape = "COLLAPSE — pattern without a business"
    else:
        shape = "degrades, survives"
    return {"total": total, "stripped_total": stripped,
            "top_n_share_of_gross_positive": top_share,
            "retained_fraction": stripped / total if total else 0.0,
            "shape": shape, "n_removed": n, "n_contributors": len(pnl)}


# ---------------------------------------------------------------- cost sensitivity
def cost_curve(run, bps: Iterable[float] = (2, 4, 6)) -> list[dict]:
    """Run the strategy at several cost levels and report the SHAPE.

    `run(bps_per_side) -> dict` must return at least {"mar": float}.

    A single cost number gives you a result; the curve gives you a diagnosis. If
    the sign flips between 2 and 4 bps, the edge is smaller than the spread and
    no execution improvement will close that gap."""
    out = []
    for b in bps:
        res = dict(run(b)); res["bps_per_side"] = b
        out.append(res)
    signs = {1 if r["mar"] > 0 else -1 for r in out}
    for r in out:
        r["sign_flips_in_range"] = len(signs) > 1
    return out


# ------------------------------------------------------------- exposure matching
def matched_exposure(a_return: float, a_gross: float,
                     b_return: float, b_gross: float,
                     tol: float = 0.10) -> dict:
    """First-order check: does A still beat B once exposure is equalised?

    The single most common way a backtest lies to its author. In the book a
    challenger showed +416% against an incumbent's +196% while running average
    gross exposure of 0.80 against 0.38. Scaled to equal exposure the advantage
    is gone (1.98 vs 1.96) — the outperformance was leverage, reproducible by
    doubling every position of the incumbent, which requires no skill.

    IMPORTANT — this is a DIAGNOSTIC, not a substitute for the real thing.
    Linear scaling ignores compounding and path dependence, and it cannot tell
    you what matching exposure does to DRAWDOWN, which is usually where the
    challenger actually loses. In the book, re-running at matched exposure moved
    MAR from 2.05 to 1.42 and deepened maxDD from -6.2% to -8.5%; no amount of
    arithmetic on the headline return would have shown that. Use this to decide
    whether a re-run is warranted, then do the re-run.

    `tol` is the band inside which a scaled advantage counts as "gone" (default
    10%). Nothing in a standard performance summary reveals any of this."""
    if a_gross <= 0 or b_gross <= 0:
        raise ValueError("gross exposure must be positive")
    scale = b_gross / a_gross
    scaled = a_return * scale
    residual = (scaled - b_return) / abs(b_return) if b_return else float("inf")
    return {"a_raw": a_return, "b_raw": b_return,
            "a_scaled_to_b": scaled,
            "exposure_ratio": a_gross / b_gross,
            "residual_advantage": residual,
            "advantage_is_leverage": a_return > b_return and residual <= tol,
            "verdict": ("raw advantage disappears at matched exposure — re-run before "
                        "believing it" if a_return > b_return and residual <= tol
                        else "advantage survives scaling — re-run at matched exposure "
                             "to check drawdown")}


# ------------------------------------------------------------------- controls
def random_subset_control(pnl_by_name: dict[str, float], k: int,
                          selected: Sequence[str], trials: int = 1000,
                          seed: int | None = 0) -> dict:
    """Is your clever name-selection better than drawing k names from a hat?

    In the book a 'both-lenses' filter picked twelve names that looked good
    individually and landed at the 55th percentile of random twelve-name books.
    The identification added nothing; the return was the base rate."""
    rng = random.Random(seed)
    names = list(pnl_by_name)
    if k > len(names):
        raise ValueError("k exceeds universe size")
    draws = [sum(pnl_by_name[n] for n in rng.sample(names, k)) for _ in range(trials)]
    actual = sum(pnl_by_name[n] for n in selected)
    pct = 100.0 * sum(1 for d in draws if d < actual) / trials
    return {"actual": actual, "percentile_vs_random": pct, "trials": trials,
            "beats_hat": pct >= 95.0}


def breadth(pnl_by_name: dict[str, float], top_n: int = 5) -> dict:
    """How many contributors actually made money, and how concentrated is the win?

    Ninety-six positions of which five ARE the strategy is a concentrated bet
    with excellent camouflage. Healthy looks like ~75% net-positive with the top
    five under ~40% of gross profit."""
    vals = list(pnl_by_name.values())
    pos = [v for v in vals if v > 0]
    gross_pos = sum(pos) or 1.0
    return {"n": len(vals), "n_positive": len(pos),
            "pct_positive": 100.0 * len(pos) / len(vals) if vals else 0.0,
            "top_n_share_of_gross_positive": sum(sorted(vals, reverse=True)[:top_n]) / gross_pos}


# --------------------------------------------------------------------- reporting
def summary(cagr: float, equity: Sequence[float], returns: Sequence[float],
            pnl: Sequence[float], avg_gross_exposure: float | None = None) -> dict:
    """One call, the whole bar. Reports PASS only if every gate clears."""
    dd = max_drawdown(equity)
    m, s = mar(cagr, dd), sortino(returns)
    kill = drop_top_n(pnl, 5)
    passes = (m >= BAR_MAR and s >= BAR_SORTINO and kill["stripped_total"] > 0)
    return {"mar": m, "sortino": s, "max_drawdown": dd,
            "profit_factor": profit_factor(pnl),
            "avg_gross_exposure": avg_gross_exposure,
            "drop_top_5": kill,
            "clears_bar": passes,
            "bar": f"MAR >= {BAR_MAR} AND Sortino >= {BAR_SORTINO} AND positive after drop-top-5",
            "note": None if avg_gross_exposure is not None else
                    "avg_gross_exposure not supplied — comparisons against another "
                    "strategy are uninterpretable without it"}
