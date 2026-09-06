import os  # noqa: E402  (added for EDGAR_UA env lookup)
"""
Buffett Bot — configuration.

All thresholds and scoring weights live here so the strategy is auditable in one
place. Numbers reflect a *conservative value* reading of Buffett/Graham criteria.
These are screening heuristics, not investment advice.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# HARD GATES — a stock must pass ALL of these to make the watchlist at all.
# Set a value to None to disable that gate. Kept intentionally lenient so the
# scoring layer (not the gate) does the ranking; the gate only removes stocks
# that clearly violate Buffett's "don't lose money" first rule.
# ---------------------------------------------------------------------------
GATES = {
    "min_market_cap": 2_000_000_000,   # $2B — avoid illiquid micro-caps
    "max_debt_to_equity": 2.0,         # reject balance-sheet-heavy names
    "min_current_ratio": 1.0,          # can cover near-term liabilities
    "min_roe": 0.10,                   # 10% return on equity floor
    "min_roe_financial": 0.08,         # banks/insurers/REITs run structurally
                                       # lower ROE (esp. low-leverage holdcos
                                       # like BRK) — a slightly lower floor
    "min_interest_coverage": 3.0,      # EBIT covers interest >=3x
    "require_positive_fcf": True,      # must generate real cash
    "require_positive_earnings": True, # no speculative loss-makers
}

# Which gates DON'T apply to which business model (see edgar_source
# .classify_business_model). A structurally-inapplicable gate must not fire —
# else the screen flags Berkshire (ROE ~9%) and every SaaS name (current
# ratio <1 by design, deferred revenue) as failures.
#   financial: no working-capital cycle → skip current_ratio; interest expense
#              is operational for banks → skip interest_coverage; FCF (OCF−capex)
#              is meaningless/volatile for banks → skip it; lower ROE bar.
#   software:  deferred revenue makes current ratio <1 normal → skip it (but
#              keep the FCF gate — a SaaS business SHOULD generate cash).
GATE_EXEMPTIONS = {
    "financial": {"current_ratio", "interest_coverage", "fcf"},
    "software":  {"current_ratio"},
    "other":     set(),
}

# ---------------------------------------------------------------------------
# MANUAL EXCLUSIONS — a JUDGMENT overlay, not a model verdict. Some real risks
# aren't in the structured data: e.g. First Solar's earnings lean on IRA
# Section 45X manufacturing tax credits (~$1B+/yr, > half of net income), which
# are booked into cost of sales and disclosed only in 10-K narrative — invisible
# to XBRL, and no principled screen rule catches them without also flagging
# healthy growth-inflection names. Excluded names are marked "EXCLUDED (manual)"
# and kept off the BUY list and watchlist; the reason travels with them.
# Keep this SHORT and documented — it's where discipline erodes if it grows.
# ---------------------------------------------------------------------------
MANUAL_EXCLUSIONS = {
    "FSLR": "earnings depend heavily on IRA §45X manufacturing tax credits "
            "(~$1B+/yr, >half of net income) — policy/subsidy risk not visible "
            "in XBRL; excluded by user judgment 2026-08-10",
}

# ---------------------------------------------------------------------------
# SCORING BANDS — each metric is scored 0..1 by where it falls between a
# "poor" and an "excellent" anchor (linear, clamped). Direction handled in
# screener.py. Anchors are (poor, excellent).
# ---------------------------------------------------------------------------
BANDS = {
    # Valuation (lower = better -> direction handled in code)
    "pe":                (35.0, 8.0),     # P/E: 35 poor, 8 excellent
    "pb":                (6.0, 1.0),      # Price/Book
    "peg":               (3.0, 0.8),      # PEG (growth-adjusted P/E)
    "fcf_yield":         (0.02, 0.10),    # FCF / market cap: higher better
    "ev_ebit":           (25.0, 8.0),     # Enterprise value / EBIT

    # Profitability & returns (higher = better)
    "roe":               (0.10, 0.30),
    "roic":              (0.08, 0.25),
    "gross_margin":      (0.20, 0.55),
    "operating_margin":  (0.08, 0.30),
    "net_margin":        (0.05, 0.25),

    # Financial health
    "debt_to_equity":    (2.0, 0.2),      # lower better
    "current_ratio":     (1.0, 3.0),      # higher better
    "interest_coverage": (3.0, 20.0),     # higher better

    # Growth & consistency (higher = better)
    "earnings_growth":   (0.0, 0.15),     # 5y-ish CAGR
    "revenue_growth":    (0.0, 0.12),
    "earnings_stability":(0.0, 1.0),      # 0..1 consistency score (see code)
    "margin_of_safety":  (0.0, 0.40),     # (intrinsic - price)/intrinsic
}

# ---------------------------------------------------------------------------
# CATEGORY WEIGHTS — how the five Buffett pillars combine into the final score.
# Must sum to ~1.0. Value + moat are weighted most heavily, matching Buffett's
# "wonderful company at a fair price" bias toward quality + margin of safety.
# ---------------------------------------------------------------------------
CATEGORY_WEIGHTS = {
    "valuation":     0.28,
    "moat":          0.24,   # profitability/returns durability = the moat proxy
    "financials":    0.18,
    "growth":        0.18,
    "safety":        0.12,   # explicit DCF margin of safety
}

# --- How the pillars combine into the final score --------------------------
# "geometric" (default): the five categories are grouped into two meta-pillars,
#   QUALITY (moat + financials + growth) and PRICE (valuation + safety), each a
#   weight-normalized average of its categories. The final score is
#       quality ** Wq  *  price ** Wp
#   where Wq/Wp are the summed category weights (0.60 / 0.40). Because it's a
#   PRODUCT, a near-zero on either meta-pillar tanks the whole score — a name
#   must be BOTH a good business AND fairly priced. Cheapness can't buy its way
#   in, and quality can't win at any price. This is the Buffett interaction.
# "additive": legacy weighted sum (kept for A/B comparison).
SCORING = {"method": "geometric"}

META_PILLARS = {
    "quality": ["moat", "financials", "growth"],   # summed weight 0.60
    "price":   ["valuation", "safety"],            # summed weight 0.40
}

# Which BANDS metrics feed each category, and whether higher raw value is better.
# (metric, higher_is_better)
CATEGORY_METRICS = {
    "valuation":  [("pe", False), ("pb", False), ("peg", False),
                   ("fcf_yield", True), ("ev_ebit", False)],
    "moat":       [("roe", True), ("roic", True), ("gross_margin", True),
                   ("operating_margin", True), ("net_margin", True)],
    "financials": [("debt_to_equity", False), ("current_ratio", True),
                   ("interest_coverage", True)],
    "growth":     [("earnings_growth", True), ("revenue_growth", True),
                   ("earnings_stability", True)],
    "safety":     [("margin_of_safety", True)],
}

# ---------------------------------------------------------------------------
# DCF assumptions (deliberately conservative — margin of safety comes from
# pessimistic inputs, per Buffett/Graham).
# ---------------------------------------------------------------------------
DCF = {
    "discount_rate": 0.09,     # required return
    "terminal_growth": 0.025,  # long-run GDP-ish
    "stage1_years": 10,
    "growth_cap": 0.10,        # never extrapolate >10% for a decade
    "growth_floor": 0.0,
}

# ---------------------------------------------------------------------------
# CYCLICAL-EARNINGS GUARD.
# A commodity producer at the top of its cycle reports trailing free cash flow
# far above its through-cycle level. A DCF that extrapolates that peak for a
# decade turns the top of a cycle into an apparent bargain — the classic way a
# value screen gets fooled (CF Industries and EOG Resources both ranked highly
# on exactly this). When the latest year is anomalously high versus its
# multi-year mean, value the company on the MEAN instead of the peak.
#
# Calibration note: a steady compounder growing FCF ~15-20%/yr sits around
# 1.2-1.5x its own 5-year mean, so the trigger has to sit above that or it would
# penalize every growth business. 2.0x separates a genuine spike from growth.
# This is a valuation ADJUSTMENT, not a rejection — the name still competes, it
# just competes on honest inputs.
# ---------------------------------------------------------------------------
CYCLICAL = {
    "fcf_spike_ratio": 2.0,   # latest FCF > this x mean => normalize to the mean
    "fcf_years": 5,           # window for the through-cycle mean
    "min_years": 3,           # need at least this much history to judge
}

# ---------------------------------------------------------------------------
# FINANCIALS valuation (banks, insurers, REITs, exchanges).
# A free-cash-flow DCF does not describe these businesses, so they use the
# standard justified price-to-book / residual-income model instead:
#
#     justified P/B = (ROE_normalized - g) / (r - g)
#     intrinsic value per share = justified P/B x book value per share
#
# It values a financial on how far its through-cycle return on equity exceeds
# the cost of that equity. ROE == r prices it at exactly book value, which is
# the correct economic anchor. ROE is normalized over several years because a
# single year is noise (catastrophe losses, provision cycles), and capped so a
# temporarily spectacular ROE isn't extrapolated forever.
# ---------------------------------------------------------------------------
FINANCIALS = {
    "cost_of_equity": 0.09,    # r — same required return as the DCF
    "terminal_growth": 0.025,  # g — must stay below r
    "roe_cap": 0.20,           # never extrapolate a >20% ROE in perpetuity
    "roe_years": 5,            # normalize ROE over up to N annual reports
    "max_pb": 3.0,             # hard ceiling on the justified multiple
}

# ---------------------------------------------------------------------------
# Data providers (see providers.py). Each layer picks its best source
# independently and always degrades to yfinance if the preferred one is absent.
#   price:        "alpaca" (SIP consolidated tape, already paid) | "yfinance"
#   fundamentals: "edgar" (SEC filings, source of truth, free; default) |
#                 "yfinance" (free scrape, pre-computed ratios) |
#                 "fmp" (stub — flip once implemented AND ~/.fmp/credentials
#                 exists; falls back to yfinance otherwise)
# EDGAR falls back to yfinance per-ticker for names it can't map (foreign/ETF).
# ---------------------------------------------------------------------------
PROVIDERS = {
    "price": "alpaca",
    "fundamentals": "edgar",
}

# ---------------------------------------------------------------------------
# Output / alerting
# ---------------------------------------------------------------------------
OUTPUT = {
    "top_n": 25,                 # size of the ranked watchlist
    "buy_score_threshold": 0.68, # score above this => "candidate BUY" alert
    "results_dir": "buffett_bot/output",
    "email_alerts": False,       # set True + fill EMAIL below to enable
}

EMAIL = {
    "to": os.environ.get("EDGAR_UA", "your-name your-email@example.com"),
    "from": os.environ.get("EDGAR_UA", "your-name your-email@example.com"),
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
    # App password read from env BUFFETT_SMTP_PASS — never hard-code secrets.
}

# ---------------------------------------------------------------------------
# SELL DISCIPLINE (monitor.py). We can't compute the "optimal" sell time —
# that needs the future. We flag when the REASON to own has changed. Three
# calculable triggers, mapped to the same pillars used to buy, plus tax timing.
# The monitor flags and explains; it never sells. You decide.
# ---------------------------------------------------------------------------
SELL = {
    "holdings_file": "buffett_bot/holdings.json",

    # 1) THESIS BROKEN — the Quality pillar deteriorated.
    #    A hard gate failure now (ROE<10%, negative earnings, debt blowout) is
    #    the strongest signal. Softer: quality score fell below a floor, or
    #    dropped materially from entry (if entry_quality recorded in holdings).
    "quality_floor": 0.45,      # abs quality score below this => review
    "quality_drop": 0.20,       # OR quality fell >=0.20 vs entry_quality

    # 2) OVERVALUED — the Price pillar inverted. Margin of safety this negative
    #    means price is well ABOVE intrinsic value (the DCF now says expensive).
    "trim_margin_of_safety": -0.25,  # MoS <= -25% => trim candidate

    # 3) TAX TIMING — long-term capital-gains threshold. If a sale is otherwise
    #    indicated on a GAIN and the lot is within `ltcg_warn_window` days of
    #    the 1-year mark, flag "wait N days for LTCG" (unless thesis is BROKEN —
    #    a broken thesis you exit regardless of tax).
    "ltcg_days": 365,
    "ltcg_warn_window": 60,

    "results_dir": "buffett_bot/output",
}
