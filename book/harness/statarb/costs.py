"""Shared transaction-cost model for the market-neutral stat-arb bot.

This module is the single source of truth for what a round-trip trade costs. It is
imported by BOTH the backtester and the live execution layer so that backtest and
live can never drift on cost assumptions (a documented failure mode in this repo).

Assumptions (reviewed & set 2026-07-18)
---------------------------------------
* Alpaca is commission-free -> the entire cost is spread + impact + tiny sell-side
  regulatory fees + (short legs) borrow. No per-share commission.
* IMPACT is volatility-aware square-root:  impact_bps = impact_c * sigma_daily_bps *
  sqrt(Q / ADV).  impact_c ~ 0.5-1 in the literature; default 0.75. This is far more
  accurate at small participation than a flat coefficient (a $50k trade in a $500M/day
  name now costs ~1 bp of impact, not ~10). sigma_daily is per-name and comes from the
  data panel; a default is used only when absent.
* FILL model is MIXED, one knob: `fill_aggressiveness` in [0,1] is the fraction of legs
  assumed to cross the spread. The passive remainder does NOT get the spread for free --
  it pays `passive_cost_ratio` of the half-spread to model adverse selection (you get
  filled passively precisely when the market is moving against you). Default 0.75 / 0.5
  is deliberately conservative: only ~12.5% cheaper than always-crossing. Relax only
  once measured IEX fills justify it.
* SPREAD is pluggable: measured IEX/quote spread when available, else Corwin-Schultz
  from daily OHLC (works on yfinance), else `default_spread_bps`.

All costs are in basis points (1 bp = 0.01%) of traded notional unless a name says
`_dollars`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math

# Regulatory fees apply to SELLS only (SEC Section 31 fee + FINRA TAF). Order of a few
# tenths of a bp; kept explicit so the model is honest at scale.
DEFAULT_SELL_FEES_BPS = 0.30


def corwin_schultz_spread_bps(
    high_t: float, low_t: float, high_t1: float, low_t1: float
) -> float:
    """Estimate the proportional bid-ask spread (bps) from two consecutive daily bars.

    Corwin & Schultz (2012). Noisy and biased high on daily bars for very liquid names,
    so this is a FALLBACK only -- prefer measured IEX spreads. Floored at 0.
    """
    if min(high_t, low_t, high_t1, low_t1) <= 0:
        return 0.0

    beta = math.log(high_t / low_t) ** 2 + math.log(high_t1 / low_t1) ** 2
    high_2 = max(high_t, high_t1)
    low_2 = min(low_t, low_t1)
    gamma = math.log(high_2 / low_2) ** 2

    denom = 3.0 - 2.0 * math.sqrt(2.0)
    alpha = (math.sqrt(2.0 * beta) - math.sqrt(beta)) / denom - math.sqrt(gamma / denom)
    spread = 2.0 * (math.exp(alpha) - 1.0) / (1.0 + math.exp(alpha))
    if spread < 0.0 or math.isnan(spread):
        return 0.0
    return spread * 10_000.0


@dataclass(frozen=True)
class CostModel:
    """Round-trip transaction-cost model, in basis points of notional.

    Parameters
    ----------
    impact_c:
        Coefficient on the volatility-aware square-root impact law. ~0.5-1.0.
    default_sigma_daily_bps:
        Fallback per-name daily return volatility (bps) when the panel doesn't supply
        one. 150 bps == 1.5%/day, a typical liquid large-cap.
    fill_aggressiveness:
        Fraction of legs assumed to cross the spread (marketable). 1.0 == always cross
        (pessimistic bound); lower assumes some passive fills.
    passive_cost_ratio:
        Cost of a passively-filled leg as a fraction of the crossing half-spread, i.e.
        the adverse-selection haircut. 0.0 == passive fills capture the full spread for
        free (optimistic); 1.0 == passive is as costly as crossing. 0.5 default.
    sell_fees_bps:
        Regulatory fees, sell leg only.
    slippage_buffer_bps:
        Flat per-leg pad for quote staleness / PFOF / residual adverse selection.
    default_spread_bps:
        Used only when neither a measured spread nor OHLC is supplied.
    stress_multiplier:
        Scales the VARIABLE cost (spread + impact + slippage) for the cost-stress gate.
        Fees and borrow are real and not inflated.
    """

    impact_c: float = 0.75
    default_sigma_daily_bps: float = 150.0
    fill_aggressiveness: float = 0.75
    passive_cost_ratio: float = 0.5
    sell_fees_bps: float = DEFAULT_SELL_FEES_BPS
    slippage_buffer_bps: float = 1.0
    default_spread_bps: float = 5.0
    stress_multiplier: float = 1.0

    # ---- per-leg building blocks -------------------------------------------------

    def effective_half_spread_bps(self, spread_bps: float) -> float:
        """Blended half-spread paid per leg under the mixed fill model.

        crossing legs pay 0.5*spread; passive legs pay passive_cost_ratio * 0.5*spread.
        """
        a = self.fill_aggressiveness
        blend = a + (1.0 - a) * self.passive_cost_ratio
        return 0.5 * spread_bps * blend

    def impact_bps(
        self, notional: float, adv_dollars: float, sigma_daily_bps: float | None = None
    ) -> float:
        """Volatility-aware square-root impact for one leg.

        impact = impact_c * sigma_daily_bps * sqrt(notional / ADV_dollars).
        Missing/zero ADV returns a punitive number so the capacity check rejects it.
        """
        if adv_dollars <= 0:
            return 1_000.0  # effectively untradeable
        sigma = self.default_sigma_daily_bps if sigma_daily_bps is None else sigma_daily_bps
        participation = max(notional, 0.0) / adv_dollars
        return self.impact_c * sigma * math.sqrt(participation)

    def one_leg_bps(
        self,
        notional: float,
        adv_dollars: float,
        spread_bps: float,
        sigma_daily_bps: float | None,
        is_sell: bool,
    ) -> float:
        """Cost of executing ONE leg: effective half-spread + impact + slippage buffer
        (variable, scaled by stress) + sell fees if applicable (not scaled)."""
        variable = (
            self.effective_half_spread_bps(spread_bps)
            + self.impact_bps(notional, adv_dollars, sigma_daily_bps)
            + self.slippage_buffer_bps
        )
        variable *= self.stress_multiplier
        fees = self.sell_fees_bps if is_sell else 0.0
        return variable + fees

    def borrow_bps(self, borrow_rate_annual_pct: float, holding_days: float) -> float:
        """Short-leg borrow cost (bps) over the holding period. `borrow_rate_annual_pct`
        is the annualized fee in percent (0.3 == general collateral; HTB is far higher
        and such names should be excluded by the universe filter, not priced here)."""
        return (borrow_rate_annual_pct / 100.0) * (holding_days / 365.0) * 10_000.0

    # ---- full round trip ---------------------------------------------------------

    def roundtrip_bps(
        self,
        notional: float,
        adv_dollars: float,
        spread_bps: float | None = None,
        sigma_daily_bps: float | None = None,
        ohlc: tuple[float, float, float, float] | None = None,
        holding_days: float = 1.0,
        short_leg: bool = False,
        borrow_rate_annual_pct: float = 0.3,
    ) -> float:
        """Total round-trip cost (open + close) for ONE side, in bps of its notional.

        Spread resolution: explicit `spread_bps` -> Corwin-Schultz(`ohlc`) -> default.
        """
        if spread_bps is None:
            if ohlc is not None:
                spread_bps = corwin_schultz_spread_bps(*ohlc) or self.default_spread_bps
            else:
                spread_bps = self.default_spread_bps

        # Exactly one of the two legs is a sell (long: sell to close; short: sell to open).
        open_leg = self.one_leg_bps(notional, adv_dollars, spread_bps, sigma_daily_bps, is_sell=short_leg)
        close_leg = self.one_leg_bps(notional, adv_dollars, spread_bps, sigma_daily_bps, is_sell=not short_leg)
        cost = open_leg + close_leg
        if short_leg:
            cost += self.borrow_bps(borrow_rate_annual_pct, holding_days)
        return cost

    def pair_roundtrip_bps(
        self,
        long_notional: float,
        short_notional: float,
        long_adv: float,
        short_adv: float,
        long_spread_bps: float | None = None,
        short_spread_bps: float | None = None,
        long_sigma_daily_bps: float | None = None,
        short_sigma_daily_bps: float | None = None,
        holding_days: float = 1.0,
        short_borrow_rate_annual_pct: float = 0.3,
    ) -> float:
        """Round-trip cost of a full market-neutral pair, in bps of the AVERAGE leg
        notional (directly comparable to a per-pair edge in bps)."""
        long_cost = self.roundtrip_bps(
            long_notional, long_adv, spread_bps=long_spread_bps,
            sigma_daily_bps=long_sigma_daily_bps, holding_days=holding_days, short_leg=False,
        )
        short_cost = self.roundtrip_bps(
            short_notional, short_adv, spread_bps=short_spread_bps,
            sigma_daily_bps=short_sigma_daily_bps, holding_days=holding_days, short_leg=True,
            borrow_rate_annual_pct=short_borrow_rate_annual_pct,
        )
        avg_notional = 0.5 * (long_notional + short_notional)
        if avg_notional <= 0:
            return 0.0
        cost_dollars = long_cost / 10_000.0 * long_notional + short_cost / 10_000.0 * short_notional
        return cost_dollars / avg_notional * 10_000.0

    # ---- the no-trade band -------------------------------------------------------

    def edge_clears_cost(self, edge_bps: float, cost_bps: float, cushion: float = 2.0) -> bool:
        """Core no-trade gate: act only when edge >= cushion * cost. Default cushion 2.0
        (the ship rule: signal must clear 2x modeled cost)."""
        return edge_bps >= cushion * cost_bps


def stressed(model: CostModel, multiplier: float) -> CostModel:
    """Copy of the model with the stress multiplier applied (validation Gate 5)."""
    return replace(model, stress_multiplier=multiplier)


if __name__ == "__main__":
    # Smoke test / worked examples.  python3 statarb/costs.py
    m = CostModel()

    print("=== Fill model: effective half-spread on a 6 bps spread ===")
    for a in (1.0, 0.75, 0.5):
        mm = replace(m, fill_aggressiveness=a)
        print(f"  aggressiveness {a:.2f} -> {mm.effective_half_spread_bps(6.0):.3f} bps/leg")

    print("\n=== Vol-aware impact, $50k across the liquidity spectrum ===")
    for adv, label in ((500_000_000, "mega-cap $500M/d"),
                       (50_000_000, "mid-cap $50M/d"),
                       (2_000_000, "small-cap $2M/d")):
        print(f"  {label:18s}: {m.impact_bps(50_000, adv, sigma_daily_bps=150):6.2f} bps/leg")

    print("\n=== Full market-neutral pair, tight 3 bps spread, $50k legs, 5-day hold ===")
    pair_tight = m.pair_roundtrip_bps(
        50_000, 50_000, 500_000_000, 500_000_000,
        long_spread_bps=3.0, short_spread_bps=3.0,
        long_sigma_daily_bps=150, short_sigma_daily_bps=150, holding_days=5,
    )
    print(f"  round-trip: {pair_tight:6.2f} bps  -> need >= {2*pair_tight:.1f} bps edge to trade (2x)")

    print("\n=== Same pair but a wider 10 bps spread (spread dominates) ===")
    pair_wide = m.pair_roundtrip_bps(
        50_000, 50_000, 500_000_000, 500_000_000,
        long_spread_bps=10.0, short_spread_bps=10.0,
        long_sigma_daily_bps=150, short_sigma_daily_bps=150, holding_days=5,
    )
    print(f"  round-trip: {pair_wide:6.2f} bps  -> need >= {2*pair_wide:.1f} bps edge to trade")

    print("\n=== Cost stress (Gate 5): tight pair at 1x / 2x / 4x ===")
    for mult in (1.0, 2.0, 4.0):
        p = stressed(m, mult).pair_roundtrip_bps(
            50_000, 50_000, 500_000_000, 500_000_000,
            long_spread_bps=3.0, short_spread_bps=3.0,
            long_sigma_daily_bps=150, short_sigma_daily_bps=150, holding_days=5)
        print(f"  {mult:.0f}x -> {p:6.2f} bps")

    print("\n=== Capacity cliff: $50k into a $2M/day name (25 bps spread) ===")
    thin = m.pair_roundtrip_bps(
        50_000, 50_000, 2_000_000, 2_000_000,
        long_spread_bps=25.0, short_spread_bps=25.0,
        long_sigma_daily_bps=300, short_sigma_daily_bps=300, holding_days=5)
    print(f"  round-trip: {thin:6.2f} bps  (impact + spread blow-up -> universe filter must exclude)")
