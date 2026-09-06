"""Cointegration signal engine + the beachhead kill-test.

For a candidate spread we compute, in order:
  1. Engle-Granger hedge ratio + residual, and the ADF stationarity p-value (Gate 0/1).
  2. Ornstein-Uhlenbeck half-life of mean reversion -> sets the holding period, hence
     turnover and cost. Only spreads with a tradeable half-life (2-30d) survive.
  3. A blunt NET-OF-COST edge proxy: does a typical divergence exceed the round-trip
     cost? This is the kill-test. gross ~= z_entry * sigma_resid (in bps); compare to the
     pair round-trip cost from `costs.CostModel`.

The point is to REJECT cheaply. A spread that is beautifully cointegrated but whose
divergences are smaller than transaction costs (the fate of near-redundant index ETFs)
must fail here, loudly.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller
from statsmodels.tsa.vector_ar.vecm import coint_johansen

from .costs import CostModel


def _ols(y: np.ndarray, X: np.ndarray) -> np.ndarray:
    """OLS coefficients for y ~ X (X already includes an intercept column)."""
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    return beta


def ou_half_life(spread: pd.Series) -> float:
    """Half-life of mean reversion (in observations) via the AR(1) form:
    Δs_t = a + b·s_{t-1} + e.  half_life = -ln2 / ln(1+b) when -1 < b < 0, else +inf
    (no reversion)."""
    s = spread.dropna()
    lag = s.shift(1).dropna()
    delta = (s - s.shift(1)).dropna()
    idx = lag.index.intersection(delta.index)
    if len(idx) < 30:
        return math.inf
    X = np.column_stack([np.ones(len(idx)), lag.loc[idx].values])
    b = _ols(delta.loc[idx].values, X)[1]
    phi = 1.0 + b
    if phi <= 0.0 or phi >= 1.0:
        return math.inf
    return -math.log(2.0) / math.log(phi)


@dataclass
class SpreadDiagnostics:
    y: str
    x: str
    beta: float              # hedge ratio: spread = log(y) - beta*log(x) - const
    adf_pvalue: float        # stationarity of the residual (lower = more cointegrated)
    half_life_days: float
    sigma_resid_bps: float   # std of the residual, in bps (the divergence amplitude)
    current_z: float         # latest standardized residual
    frac_beyond_2z: float    # fraction of history with |z| > 2 (opportunity frequency)

    # cost / edge (filled by analyze_spread when a cost model is supplied)
    gross_edge_bps: float = math.nan   # z_entry * sigma_resid, in bps
    cost_bps: float = math.nan         # pair round-trip cost
    net_edge_bps: float = math.nan
    tradeable: bool = False            # gross >= cushion * cost AND half-life in band


def engle_granger(log_y: pd.Series, log_x: pd.Series) -> tuple[float, pd.Series, float]:
    """Regress log_y on log_x (+const); return (beta, residual_series, adf_pvalue)."""
    idx = log_y.index.intersection(log_x.index)
    ly, lx = log_y.loc[idx].values, log_x.loc[idx].values
    X = np.column_stack([np.ones(len(lx)), lx])
    coef = _ols(ly, X)
    resid = ly - X @ coef
    adf_p = adfuller(resid, maxlag=1, regression="c", autolag=None)[1]
    return float(coef[1]), pd.Series(resid, index=idx), float(adf_p)


def analyze_spread(
    y: str,
    x: str,
    close: pd.DataFrame,
    cost_model: CostModel | None = None,
    stats: pd.DataFrame | None = None,
    notional_per_leg: float = 50_000.0,
    z_entry: float = 2.0,
    half_life_band: tuple[float, float] = (2.0, 30.0),
    cushion: float = 2.0,
    adf_max: float = 0.05,
) -> SpreadDiagnostics:
    """Full diagnostics for the y~x spread, picking the more-stationary regression
    direction. If `cost_model` + `stats` are given, also computes the net-of-cost
    edge and the tradeable verdict (the kill-test)."""
    log_y, log_x = np.log(close[y]), np.log(close[x])

    # Try both directions; keep the one with the lower ADF p-value (more stationary).
    b1, r1, p1 = engle_granger(log_y, log_x)
    b2, r2, p2 = engle_granger(log_x, log_y)
    if p1 <= p2:
        beta, resid, adf_p, yy, xx = b1, r1, p1, y, x
    else:
        beta, resid, adf_p, yy, xx = b2, r2, p2, x, y

    hl = ou_half_life(resid)
    sigma = float(resid.std())
    z = (resid - resid.mean()) / (resid.std() or 1.0)
    diag = SpreadDiagnostics(
        y=yy, x=xx, beta=beta, adf_pvalue=adf_p, half_life_days=hl,
        sigma_resid_bps=sigma * 10_000.0, current_z=float(z.iloc[-1]),
        frac_beyond_2z=float((z.abs() > 2.0).mean()),
    )

    if cost_model is not None and stats is not None:
        # gross capture of a z_entry divergence reverting to the mean, in bps of notional
        diag.gross_edge_bps = z_entry * diag.sigma_resid_bps
        hold = float(min(max(hl, 1.0), half_life_band[1])) if math.isfinite(hl) else half_life_band[1]
        diag.cost_bps = cost_model.pair_roundtrip_bps(
            long_notional=notional_per_leg, short_notional=notional_per_leg,
            long_adv=float(stats.loc[yy, "dollar_adv"]), short_adv=float(stats.loc[xx, "dollar_adv"]),
            long_spread_bps=float(stats.loc[yy, "spread_bps"]), short_spread_bps=float(stats.loc[xx, "spread_bps"]),
            long_sigma_daily_bps=float(stats.loc[yy, "sigma_daily_bps"]),
            short_sigma_daily_bps=float(stats.loc[xx, "sigma_daily_bps"]),
            holding_days=hold,
        )
        diag.net_edge_bps = diag.gross_edge_bps - diag.cost_bps
        in_band = half_life_band[0] <= hl <= half_life_band[1]
        cointegrated = diag.adf_pvalue <= adf_max
        diag.tradeable = bool(
            cointegrated and in_band and diag.gross_edge_bps >= cushion * diag.cost_bps
        )
    return diag


def johansen_rank(close: pd.DataFrame, symbols: list[str], det_order: int = 0, k_ar_diff: int = 1) -> dict:
    """Johansen test on a basket (>=2 names). Returns the number of cointegrating
    relations at the 95% level via the trace statistic."""
    data = np.log(close[symbols].dropna().values)
    res = coint_johansen(data, det_order, k_ar_diff)
    trace, cv95 = res.lr1, res.cvt[:, 1]
    rank = int((trace > cv95).sum())
    return {"n_relations_95": rank, "trace": trace.tolist(), "cv95": cv95.tolist()}


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    from .data import load_panel

    cm = CostModel()

    # Two baskets: the gold complex (expect tradeable) and the index triplet (expect NOT).
    gold = ["GLD", "GDX", "GDXJ"]
    index = ["SPY", "IVV", "VOO"]
    panel = load_panel(gold + index, lookback_days=3 * 365)
    close, stats = panel.close, panel.stats

    def show(pairs, title):
        print(f"\n=== {title} ===")
        print(f"{'spread':13s} {'beta':>6s} {'adf_p':>7s} {'half-life':>10s} "
              f"{'sigmaσ_bps':>10s} {'|z|>2':>6s} {'gross':>7s} {'cost':>6s} {'net':>7s}  verdict")
        for a, b in pairs:
            d = analyze_spread(a, b, close, cost_model=cm, stats=stats)
            hl = f"{d.half_life_days:.1f}d" if math.isfinite(d.half_life_days) else "  inf"
            print(f"{d.y+'~'+d.x:13s} {d.beta:6.2f} {d.adf_pvalue:7.3f} {hl:>10s} "
                  f"{d.sigma_resid_bps:10.0f} {d.frac_beyond_2z*100:5.1f}% "
                  f"{d.gross_edge_bps:7.0f} {d.cost_bps:6.1f} {d.net_edge_bps:7.0f}  "
                  f"{'TRADEABLE' if d.tradeable else 'reject'}")

    show([("GLD", "GDX"), ("GLD", "GDXJ"), ("GDX", "GDXJ")], "Gold complex")
    show([("SPY", "IVV"), ("SPY", "VOO"), ("IVV", "VOO")], "Index triplet (redundant)")

    print("\n=== Johansen basket rank (95%) ===")
    print(f"  gold  {gold}: {johansen_rank(close, gold)['n_relations_95']} cointegrating relation(s)")
    print(f"  index {index}: {johansen_rank(close, index)['n_relations_95']} cointegrating relation(s)")
    print("\n(gross = z=2 divergence capture in bps; cost = pair round-trip; net = gross - cost)")
