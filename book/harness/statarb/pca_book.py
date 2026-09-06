"""PCA factor-residual reversion book (Avellaneda-Lee style) — the capacity engine.

Idea: the return not explained by common factors is idiosyncratic; it mean-reverts.
Because the residual is factor-neutral BY CONSTRUCTION, a book weighted by residual
s-scores is ~market/sector-neutral without bolting on a hedge.

Per rebalance (all causal, trailing windows only):
  1. Standardize trailing returns; PCA the correlation matrix; keep top-k eigenportfolios.
  2. Factor returns F = returns @ (eigvec / sigma). Regress each name on F over the OU
     window -> idiosyncratic residual.
  3. Cumulative residual -> AR(1)/OU fit -> s-score (how far a name has drifted from its
     factor-implied path) + reversion half-life. Trade only names whose half-life is in a
     tradeable band and whose |s| clears the entry band.
  4. Weights: w_i = -s_i for tradeable names (reversion), demeaned (dollar-neutral) and
     gross-normalized. Hold to next rebalance; charge per-name one-way cost on turnover.

DATA CAVEAT: run here on a CURRENT liquid universe (yfinance) => SURVIVORSHIP-BIASED =>
results are an OPTIMISTIC UPPER BOUND. A pass earns the survivorship-safe data spend to
confirm; a fail here is a real fail (clean data can only be worse).
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd

from .costs import CostModel

# ~95 liquid large-caps across sectors (current members => survivorship-biased, flagged).
UNIVERSE = [
    "AAPL","MSFT","NVDA","GOOGL","META","AMZN","AVGO","ORCL","CRM","ADBE","CSCO","ACN",
    "AMD","INTC","QCOM","TXN","IBM","NOW","INTU","MU","NFLX","DIS","CMCSA","T","VZ","TMUS",
    "HD","LOW","NKE","MCD","SBUX","TGT","BKNG","TJX","GM","F","PG","KO","PEP","WMT","COST",
    "CL","MDLZ","MO","PM","UNH","JNJ","LLY","PFE","MRK","ABBV","TMO","ABT","DHR","BMY",
    "AMGN","CVS","MDT","JPM","BAC","WFC","C","GS","MS","BLK","SPGI","AXP","SCHW","USB","PNC",
    "CAT","DE","BA","HON","UPS","RTX","GE","LMT","MMM","UNP","FDX","XOM","CVX","COP","SLB",
    "EOG","LIN","APD","SHW","FCX","NEM","NEE","DUK","SO","AMT","PLD",
]


@dataclass
class BookResult:
    ret: pd.Series
    turnover: pd.Series
    metrics: dict
    segments: dict
    contrib: pd.Series | None = None        # per-name gross P&L contribution over holdout
    contrib_train: pd.Series | None = None  # ... and over train


def _s_scores(win_ret: pd.DataFrame, k: int, w_ou: int) -> tuple[pd.Series, pd.Series]:
    """s-score and reversion half-life (days) per name from a trailing return window."""
    cols = win_ret.columns
    R = win_ret.values                                  # (L, N)
    mu, sd = R.mean(0), R.std(0)
    sd = np.where(sd > 0, sd, 1.0)
    Y = (R - mu) / sd                                   # standardized
    C = np.corrcoef(Y, rowvar=False)
    C = np.nan_to_num(C)
    vals, vecs = np.linalg.eigh(C)                      # ascending
    top = vecs[:, -k:] / sd[:, None]                    # eigenportfolio weights (N, k)
    F = R @ top                                         # factor returns (L, k)

    Rou, Fou = R[-w_ou:], F[-w_ou:]                     # OU/regression window
    X = np.column_stack([np.ones(w_ou), Fou])          # (w_ou, k+1)
    betas, *_ = np.linalg.lstsq(X, Rou, rcond=None)     # (k+1, N)
    resid = Rou - X @ betas                             # (w_ou, N)
    cum = np.cumsum(resid, axis=0)                      # drift process (w_ou, N)

    # AR(1) per name: cum_t = a + b cum_{t-1}
    xp, yp = cum[:-1], cum[1:]
    xbar, ybar = xp.mean(0), yp.mean(0)
    xc, yc = xp - xbar, yp - ybar
    denom = (xc * xc).sum(0)
    denom = np.where(denom > 0, denom, np.nan)
    b = (xc * yc).sum(0) / denom
    a = ybar - b * xbar
    xi = yp - (a + b * xp)
    var_xi = xi.var(0)
    with np.errstate(invalid="ignore", divide="ignore"):
        m = a / (1.0 - b)
        sigma_eq = np.sqrt(var_xi / (1.0 - b * b))
        s = (cum[-1] - m) / sigma_eq
        half_life = -np.log(2.0) / np.log(b)           # days (b in (0,1) => finite)
    s = np.where((b > 0) & (b < 1) & np.isfinite(s), s, np.nan)
    half_life = np.where((b > 0) & (b < 1), half_life, np.inf)
    return pd.Series(s, index=cols), pd.Series(half_life, index=cols)


def _metrics(ret: pd.Series) -> dict:
    r = ret.dropna()
    if len(r) < 20 or r.std() == 0:
        return {k: 0.0 for k in ("ann_ret","ann_vol","sharpe","sortino","max_dd","mar","avg_turnover")}
    ann_ret = float(r.mean() * 252)
    ann_vol = float(r.std() * math.sqrt(252))
    dn = r[r < 0]
    dstd = float(dn.std() * math.sqrt(252)) if len(dn) > 1 else 0.0
    eq = 1.0 + r.cumsum()
    mdd = float(-(eq - eq.cummax()).min())
    return {"ann_ret": ann_ret, "ann_vol": ann_vol,
            "sharpe": ann_ret / ann_vol if ann_vol else 0.0,
            "sortino": ann_ret / dstd if dstd else 0.0,
            "max_dd": mdd, "mar": ann_ret / mdd if mdd else 0.0}


def _oneway_cost(cost_model, spread_ser, stats, names, notional) -> pd.Series:
    """Per-name one-way cost (fraction) for a given per-name spread Series."""
    ow = {}
    for nm in names:
        sp = float(spread_ser.get(nm, spread_ser.median()))
        adv = float(stats.loc[nm, "dollar_adv"]); sig = float(stats.loc[nm, "sigma_daily_bps"])
        bps = (cost_model.effective_half_spread_bps(sp)
               + cost_model.impact_bps(notional, adv, sig)
               + cost_model.slippage_buffer_bps) * cost_model.stress_multiplier
        ow[nm] = bps / 10_000.0
    return pd.Series(ow)


def backtest_pca_book(
    close: pd.DataFrame,
    stats: pd.DataFrame,
    cost_model: CostModel,
    k: int = 15,
    w_pca: int = 252,
    w_ou: int = 60,
    s_entry: float = 1.25,
    half_life_band: tuple[float, float] = (1.0, 30.0),
    rebal: int = 5,
    target_gross: float = 1.0,
    holdout_frac: float = 0.30,
    notional_per_name: float = 25_000.0,
    spread_by_year: dict[int, pd.Series] | None = None,
    trade_only: set | None = None,
) -> BookResult:
    rets = close.pct_change()
    names = list(close.columns)
    # per-name one-way cost. Static from stats, or TIME-VARYING via spread_by_year
    # (each date uses its year's measured spreads — attacks the "today's spreads on
    # old history" optimism).
    if spread_by_year:
        ow_by_year = {yr: _oneway_cost(cost_model, sp, stats, names, notional_per_name)
                      for yr, sp in spread_by_year.items()}
        years_avail = sorted(ow_by_year)
        ow = ow_by_year[years_avail[-1]]  # default/fallback
    else:
        ow = _oneway_cost(cost_model, stats["spread_bps"], stats, names, notional_per_name)
        ow_by_year = None

    n = len(close)
    warmup = w_pca
    w_prev = pd.Series(0.0, index=names)
    daily_ret, daily_to = [], []
    idx = close.index
    contrib = pd.Series(0.0, index=names)               # per-name gross P&L over holdout
    contrib_train = pd.Series(0.0, index=names)         # ... and over train (for persistence tests)
    ho_start = warmup + int((n - warmup) * (1 - holdout_frac))

    for t in range(warmup, n):
        # rebalance on schedule using data through t-1 (causal); trade returns over t
        if (t - warmup) % rebal == 0:
            if ow_by_year is not None:                        # time-varying spreads
                yr = idx[t].year
                ow = ow_by_year.get(yr) if yr in ow_by_year else ow_by_year[
                    min(ow_by_year, key=lambda y: abs(y - yr))]
            win = rets.iloc[t - w_pca:t].dropna(axis=1)       # names with full window
            if win.shape[1] >= k + 5:
                s, hl = _s_scores(win, k, w_ou)
                tradeable = s.index[(s.abs() > s_entry)
                                    & (hl >= half_life_band[0]) & (hl <= half_life_band[1])
                                    & s.notna()]
                if trade_only is not None:               # restrict to an allowed subset
                    tradeable = tradeable[tradeable.isin(trade_only)]
                w = pd.Series(0.0, index=names)
                if len(tradeable) >= 2:
                    raw = -s.loc[tradeable]
                    raw = raw - raw.mean()                     # dollar-neutral
                    gross = raw.abs().sum()
                    if gross > 0:
                        w.loc[tradeable] = (raw / gross) * target_gross
                turnover = float((w - w_prev).abs().sum())
                cost = float(((w - w_prev).abs() * ow.reindex(w.index).fillna(ow.mean())).sum())
                w_prev = w
            else:
                turnover, cost = 0.0, 0.0
        else:
            turnover, cost = 0.0, 0.0
        # realized return over day t from weights set at prior rebalance
        rt_vec = w_prev * rets.iloc[t].reindex(w_prev.index).fillna(0.0)
        r_t = float(rt_vec.sum()) - cost
        daily_ret.append(r_t); daily_to.append(turnover)
        if t >= ho_start:
            contrib = contrib.add(rt_vec, fill_value=0.0)
        else:
            contrib_train = contrib_train.add(rt_vec, fill_value=0.0)

    ret = pd.Series(daily_ret, index=idx[warmup:], name="pca_book")
    to = pd.Series(daily_to, index=idx[warmup:], name="turnover")
    split = int(len(ret) * (1 - holdout_frac))
    full_m = _metrics(ret); full_m["avg_turnover"] = float(to[to > 0].mean())
    return BookResult(
        ret=ret, turnover=to, metrics=full_m,
        segments={"train": _metrics(ret.iloc[:split]), "holdout": _metrics(ret.iloc[split:])},
        contrib=contrib, contrib_train=contrib_train,
    )


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    from .data import load_panel
    from .costs import stressed

    panel = load_panel(UNIVERSE, lookback_days=8 * 365, min_obs=1000, max_missing_frac=0.05)
    close, stats = panel.close, panel.stats
    print(f"SURVIVORSHIP-BIASED (current members). universe={close.shape[1]} names, "
          f"{close.shape[0]} sessions, {close.index[0].date()} -> {close.index[-1].date()}\n")

    def line(name, m):
        return (f"  {name:16s} annRet={m['ann_ret']*100:6.1f}% Sharpe={m['sharpe']:5.2f} "
                f"Sortino={m['sortino']:5.2f} MAR={m['mar']:5.2f} MaxDD={m['max_dd']*100:5.1f}%")

    print("=== PCA residual book (1x cost) ===")
    res = backtest_pca_book(close, stats, CostModel())
    print(line("full", res.metrics), f" avg turnover={res.metrics['avg_turnover']:.2f}/rebal")
    print(line("train", res.segments["train"]))
    print(line("holdout", res.segments["holdout"]))

    print("\n=== COST STRESS — holdout at 1x / 2x / 4x (THE BAR is 2x) ===")
    for mult in (1.0, 2.0, 4.0):
        r = backtest_pca_book(close, stats, stressed(CostModel(), mult))
        m = r.segments["holdout"]
        verdict = "PASS" if (m["mar"] >= 0.5 and m["sortino"] >= 1.0) else "FAIL"
        print(f"  {mult:.0f}x  MAR={m['mar']:5.2f}  Sortino={m['sortino']:5.2f}  "
              f"annRet={m['ann_ret']*100:6.1f}%  MaxDD={m['max_dd']*100:5.1f}%  -> {verdict}")
    print("\n  bar = MAR>=0.5 AND Sortino>=1.0, net of 2x cost, on holdout. Survivorship-optimistic.")
