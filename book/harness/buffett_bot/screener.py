"""
Screening, valuation, moat detection, and scoring.

Pipeline per stock:
  1. hard gates    -> pass/fail (Buffett rule #1: don't lose money)
  2. DCF valuation -> intrinsic value + margin of safety
  3. moat signals  -> qualitative flags derived from durable-returns evidence
  4. scoring       -> 0..1 per category, weighted into a final 0..1 score

Everything is defensive: a missing metric contributes a neutral 0.5 to its
category rather than nuking the whole score, and the number of missing inputs
is surfaced so low-confidence rows can be flagged.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from . import config
from .data_source import Fundamentals

log = logging.getLogger("buffett_bot.screener")


@dataclass
class Score:
    ticker: str
    name: Optional[str]
    sector: Optional[str]
    price: Optional[float]
    passed_gates: bool
    gate_failures: list[str] = field(default_factory=list)
    intrinsic_value: Optional[float] = None
    margin_of_safety: Optional[float] = None
    category_scores: dict = field(default_factory=dict)
    quality_score: float = 0.0   # moat + financials + growth composite
    price_score: float = 0.0     # valuation + safety composite
    final_score: float = 0.0
    moat_flags: list[str] = field(default_factory=list)
    moat_score: float = 0.0
    confidence: float = 1.0   # 1.0 = all inputs present
    data_ok: bool = True      # False = can't value it; not a real verdict
    recommendation: str = "PASS"


# --------------------------------------------------------------------------- #
# 1. GATES                                                                     #
# --------------------------------------------------------------------------- #
def _money(v: float) -> str:
    """Compact USD for reason lines: 1.75e9 -> '$1.75B'."""
    a = abs(v)
    if a >= 1e9:
        return f"${v / 1e9:.2f}B"
    if a >= 1e6:
        return f"${v / 1e6:.0f}M"
    return f"${v:,.0f}"


def _charge_context(f: Fundamentals) -> str:
    """Explain a loss/thin-coverage caused by a non-cash writedown.

    Deliberately CONTEXT ONLY — it never changes the verdict. A gate failure
    still fails. But "negative net income" reads very differently when pretax
    income was positive and a one-time impairment (plus its non-deductible tax
    treatment) drove the line below zero, versus a business burning cash. The
    caller still has to judge which it is; this just stops the reason line from
    implying the wrong one. (General Mills FY2026 is the worked example: −$88M
    net income on +$406M pretax after a $1.75B impairment.)
    """
    if not f.impairment or f.impairment <= 0:
        return ""
    bits = [f"includes {_money(f.impairment)} non-cash impairment"]
    if f.pretax_income is not None and f.pretax_income > 0:
        bits.append(f"pretax still positive ({_money(f.pretax_income)})")
    return " — " + "; ".join(bits)


def check_gates(f: Fundamentals) -> list[str]:
    """Return list of gate failure reasons (empty = passed).

    Gates are business-model-aware: a gate that is structurally inapplicable to
    a company's model (current ratio for a bank, interest coverage for an
    insurer, the 10% ROE floor for a low-leverage holding company) is skipped
    or relaxed rather than firing a false 'thesis broken'. See config
    .GATE_EXEMPTIONS and edgar_source.classify_business_model.
    """
    g = config.GATES
    model = f.business_model or "other"
    exempt = config.GATE_EXEMPTIONS.get(model, set())
    fails: list[str] = []

    def below(val, floor, label, gate_key):
        if gate_key in exempt:
            return
        if floor is not None and val is not None and val < floor:
            fails.append(f"{label} {val:.2f} < {floor}")

    def above(val, cap, label):
        if cap is not None and val is not None and val > cap:
            fails.append(f"{label} {val:.2f} > {cap}")

    # Only judge market cap when we actually have it — a missing value is a data
    # gap, reported via `data_ok`/INSUFFICIENT DATA, not a real gate failure.
    if g["min_market_cap"] and f.market_cap is not None \
            and f.market_cap < g["min_market_cap"]:
        fails.append(f"market_cap {f.market_cap:.0f} < {g['min_market_cap']}")
    above(f.debt_to_equity, g["max_debt_to_equity"], "D/E")
    below(f.current_ratio, g["min_current_ratio"], "current_ratio", "current_ratio")
    roe_floor = g["min_roe_financial"] if model == "financial" else g["min_roe"]
    below(f.roe, roe_floor, "ROE", "roe")
    below(f.interest_coverage, g["min_interest_coverage"],
          "interest_coverage", "interest_coverage")
    if "fcf" not in exempt and g["require_positive_fcf"] \
            and f.free_cash_flow is not None and f.free_cash_flow <= 0:
        fails.append("negative free cash flow")
    if g["require_positive_earnings"] and f.net_income is not None and f.net_income <= 0:
        fails.append("negative net income" + _charge_context(f))

    # An impairment also crushes EBIT, so a thin interest-coverage reading can be
    # the same one-off rather than real balance-sheet stress. Show the ex-charge
    # figure alongside — the gate still fails either way.
    if f.impairment and f.impairment > 0 and f.ebit is not None:
        for i, msg in enumerate(fails):
            if msg.startswith("interest_coverage") and f.interest_coverage:
                ex = (f.ebit + f.impairment) / (f.ebit / f.interest_coverage)
                fails[i] = (f"{msg} (EBIT depressed by "
                            f"{_money(f.impairment)} impairment; "
                            f"ex-charge ~{ex:.1f}x)")
    return fails


# --------------------------------------------------------------------------- #
# 2. VALUATION — two-stage owner-earnings DCF                                  #
# --------------------------------------------------------------------------- #
def intrinsic_value(f: Fundamentals) -> tuple[Optional[float], Optional[float]]:
    """Return (intrinsic_value_per_share, margin_of_safety).

    Conservative two-stage DCF on free cash flow (owner-earnings proxy):
      stage 1: grow FCF at a capped growth rate for N years
      stage 2: Gordon terminal value at long-run growth
    Discounted at the required rate; net cash added / net debt subtracted;
    divided by shares outstanding. Margin of safety = (IV - price)/IV.
    """
    d = config.DCF
    # A free-cash-flow DCF does not describe a bank/insurer/REIT — their cash
    # generation runs through float, reserves, and regulatory capital, not FCF.
    # Route BALANCE-SHEET financials (banks, insurers) to justified P/B. REITs,
    # exchanges and asset managers stay on cash flow — their book value is
    # depreciated cost or near-zero, so P/B is meaningless for them.
    if (f.valuation_model or "cashflow") == "book_value":
        return intrinsic_value_financial(f)
    fcf = f.free_cash_flow
    shares = f.shares_out
    if fcf is None or fcf <= 0 or not shares or shares <= 0 or not f.price:
        return None, None

    # CYCLICAL-EARNINGS GUARD. If the latest FCF is a spike far above the
    # through-cycle mean, discount the MEAN — extrapolating a peak year is how a
    # DCF turns the top of a commodity cycle into a fake bargain. Only fires
    # with enough history and only when the mean is positive.
    c = config.CYCLICAL
    avg = f.free_cash_flow_avg
    if (avg is not None and avg > 0 and f.fcf_years >= c["min_years"]
            and fcf > c["fcf_spike_ratio"] * avg):
        fcf = avg
        f.fcf_normalized = True

    g = f.earnings_growth if f.earnings_growth is not None else 0.05
    g = max(d["growth_floor"], min(g, d["growth_cap"]))
    r = d["discount_rate"]
    gt = d["terminal_growth"]

    pv = 0.0
    cf = fcf
    for yr in range(1, d["stage1_years"] + 1):
        cf *= (1 + g)
        pv += cf / (1 + r) ** yr

    terminal_cf = cf * (1 + gt)
    terminal_val = terminal_cf / (r - gt)
    pv += terminal_val / (1 + r) ** d["stage1_years"]

    # equity bridge: add cash, subtract debt
    equity_value = pv + (f.total_cash or 0) - (f.total_debt or 0)
    iv_per_share = equity_value / shares
    if iv_per_share <= 0:
        return iv_per_share, None
    mos = (iv_per_share - f.price) / iv_per_share
    return iv_per_share, mos


def intrinsic_value_financial(f: Fundamentals) -> tuple[Optional[float], Optional[float]]:
    """Justified price-to-book (residual income) valuation for financials.

        justified P/B = (ROE_normalized - g) / (r - g)
        intrinsic value per share = justified P/B x book value per share

    The economics: a financial is worth book value plus the present value of the
    returns it earns *above* its cost of equity. ROE == r prices it at exactly
    1.0x book — the correct anchor. ROE above r earns a premium to book, below r
    a discount.

    Conservatism (this is where the margin of safety comes from):
      * ROE is normalized over several years — one year is noise for an insurer
        (catastrophes) or a bank (provision cycle).
      * ROE is capped, so a temporarily spectacular year isn't extrapolated
        forever, and the resulting multiple is capped again.
      * ROE must exceed g, else the model is undefined (returns None rather than
        a negative "value"). Our financial ROE gate (8%) is far above g (2.5%),
        so this only bites on names already rejected.

    Known limitation: reported ROE understates the economics of a conglomerate
    like Berkshire (unrealized gains, insurance float, subsidiary earning power
    not in reported earnings), so this model reads BRK as dearer than most
    analysts would. Treat financial IVs as a sanity band, not a price target.
    """
    c = config.FINANCIALS
    roe = f.roe_normalized if f.roe_normalized is not None else f.roe
    equity, shares = f.total_equity, f.shares_out
    if roe is None or not equity or equity <= 0 or not shares or shares <= 0 \
            or not f.price:
        return None, None

    r, g = c["cost_of_equity"], c["terminal_growth"]
    if r <= g:                                  # guard a mis-set config
        return None, None
    roe = min(roe, c["roe_cap"])
    if roe <= g:                                # model undefined below growth
        return None, None

    justified_pb = min((roe - g) / (r - g), c["max_pb"])
    bvps = equity / shares
    iv = justified_pb * bvps
    if iv <= 0:
        return None, None
    return iv, (iv - f.price) / iv


# --------------------------------------------------------------------------- #
# 3. MOAT DETECTION                                                            #
# --------------------------------------------------------------------------- #
def moat_signals(f: Fundamentals) -> tuple[list[str], float]:
    """Heuristic moat detection. A durable competitive advantage shows up in
    the financials as *persistently high returns and pricing power*. We can't
    read a 10-K's qualitative moat here, so we proxy it with hard evidence:

      * High, sustained ROE / ROIC   -> returns competitors can't compete away
      * Fat, stable gross margins     -> pricing power / brand / switching costs
      * Strong FCF conversion         -> asset-light, cash-generative franchise
      * Earnings that rarely fall     -> demand durability across cycles
      * Low leverage w/ high returns   -> returns aren't just financial engineering

    Returns (list_of_flags, moat_score 0..1).
    """
    flags: list[str] = []
    hits = 0
    total = 6

    if (f.roe or 0) >= 0.20:
        flags.append("high ROE ≥20% (excess returns)")
        hits += 1
    if (f.roic or 0) >= 0.15:
        flags.append("high ROIC ≥15% (capital efficiency)")
        hits += 1
    if (f.gross_margin or 0) >= 0.40:
        flags.append("fat gross margin ≥40% (pricing power)")
        hits += 1
    if (f.operating_margin or 0) >= 0.20:
        flags.append("operating margin ≥20% (cost/scale advantage)")
        hits += 1
    if (f.earnings_stability or 0) >= 0.80:
        flags.append("earnings up in ≥80% of years (demand durability)")
        hits += 1
    if (f.fcf_yield or 0) > 0 and (f.roe or 0) >= 0.15 and (f.debt_to_equity or 99) <= 1.0:
        flags.append("high returns on a clean balance sheet")
        hits += 1

    return flags, hits / total


# --------------------------------------------------------------------------- #
# 4. SCORING                                                                   #
# --------------------------------------------------------------------------- #
def _band_score(value: Optional[float], band: tuple[float, float],
                higher_is_better: bool) -> Optional[float]:
    """Linear-clamp a value into 0..1 given (poor, excellent) anchors."""
    if value is None:
        return None
    poor, excellent = band
    if higher_is_better:
        lo, hi = poor, excellent
    else:
        lo, hi = poor, excellent  # excellent < poor for 'lower is better'
    if hi == lo:
        return 0.5
    s = (value - lo) / (hi - lo)
    return max(0.0, min(1.0, s))


def _category_score(f: Fundamentals, metrics) -> tuple[float, int, int]:
    """Average band-scores for a category. Missing metrics -> neutral 0.5 but
    counted toward the 'missing' tally for the confidence figure."""
    vals = []
    missing = 0
    for metric, higher in metrics:
        raw = getattr(f, metric, None)
        band = config.BANDS[metric]
        s = _band_score(raw, band, higher)
        if s is None:
            missing += 1
            vals.append(0.5)
        else:
            vals.append(s)
    avg = sum(vals) / len(vals) if vals else 0.5
    return avg, missing, len(metrics)


def score(f: Fundamentals) -> Score:
    """Full pipeline for one stock."""
    out = Score(ticker=f.ticker, name=f.name, sector=f.sector, price=f.price,
                passed_gates=False)

    # Without a share count we cannot compute market cap, P/E, P/B or the DCF —
    # so the name is un-valuable, not un-attractive. Surface it as a data gap
    # rather than letting it look like a considered rejection.
    out.data_ok = bool(f.shares_out and f.market_cap)

    out.gate_failures = check_gates(f)
    out.passed_gates = not out.gate_failures

    iv, mos = intrinsic_value(f)
    out.intrinsic_value = iv
    out.margin_of_safety = mos
    f.__dict__["margin_of_safety"] = mos  # feed the 'safety' band

    out.moat_flags, out.moat_score = moat_signals(f)

    total_missing = 0
    total_metrics = 0
    for cat, metrics in config.CATEGORY_METRICS.items():
        cat_score, missing, n = _category_score(f, metrics)
        out.category_scores[cat] = round(cat_score, 4)
        total_missing += missing
        total_metrics += n

    q, p, final = _combine(out.category_scores)
    out.quality_score = round(q, 4)
    out.price_score = round(p, 4)
    out.final_score = round(final, 4)
    out.confidence = round(1 - total_missing / max(total_metrics, 1), 3)

    out.recommendation = _recommend(out)
    return out


def _meta_composite(cat_scores: dict, cats: list[str]) -> tuple[float, float]:
    """Weight-normalized arithmetic mean of a meta-pillar's categories.
    Returns (composite 0..1, summed raw weight of the group)."""
    w = {c: config.CATEGORY_WEIGHTS[c] for c in cats}
    tot = sum(w.values())
    comp = sum(cat_scores[c] * w[c] for c in cats) / tot if tot else 0.0
    return comp, tot


def _combine(cat_scores: dict) -> tuple[float, float, float]:
    """Return (quality_composite, price_composite, final_score).

    Geometric method (default): final = quality**Wq * price**Wp with the meta-
    pillar exponents taken from the summed category weights (0.60 / 0.40). The
    product makes the two complementary — a name has to be good AND fairly
    priced; neither pillar can carry a weak other one. Additive method is the
    legacy weighted sum, kept for comparison.
    """
    q, wq = _meta_composite(cat_scores, config.META_PILLARS["quality"])
    p, wp = _meta_composite(cat_scores, config.META_PILLARS["price"])

    if config.SCORING.get("method") == "additive":
        final = sum(cat_scores[c] * w for c, w in config.CATEGORY_WEIGHTS.items())
        return q, p, final

    total = wq + wp
    eq, ep = wq / total, wp / total
    # tiny floor so an exact 0 on one pillar still leaves a rankable score
    # rather than collapsing a whole cohort to a flat 0.
    qf, pf = max(q, 1e-6), max(p, 1e-6)
    final = (qf ** eq) * (pf ** ep)
    return q, p, final


def _recommend(s: Score) -> str:
    # Manual judgment overlay wins over everything — the model may score the name
    # a BUY, but a documented human reason (see config.MANUAL_EXCLUSIONS) keeps
    # it off the list. This does not change the score, only the verdict.
    if s.ticker in config.MANUAL_EXCLUSIONS:
        return "EXCLUDED (manual)"
    if not s.data_ok:
        return "INSUFFICIENT DATA"
    if not s.passed_gates:
        return "REJECT (failed gate)"
    thr = config.OUTPUT["buy_score_threshold"]
    if s.final_score >= thr and (s.margin_of_safety or 0) > 0:
        return "BUY CANDIDATE"
    if s.final_score >= thr:
        return "WATCH (quality, fair price)"
    if s.final_score >= thr - 0.1:
        return "WATCH"
    return "PASS"
