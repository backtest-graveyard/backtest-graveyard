"""
SEC EDGAR fundamentals engine for the Buffett Bot.

Pulls a company's full XBRL financial history from EDGAR's free `companyfacts`
API (one request per company — no key, just a polite User-Agent) and maps it
into the same `Fundamentals` record yfinance produces. This is the *source of
truth*: yfinance/FMP/Yahoo all ultimately derive from these filings.

Design:
  * one `companyfacts` GET per ticker returns every reported line item
  * GAAP tags vary by filer, so each concept has an alias list; first hit wins
  * flows (income, revenue, cash flow) use annual (10-K, ~365-day) facts;
    instants (balance sheet, shares) use the most recent reported value
  * every metric is best-effort — a missing tag becomes None, never a crash
  * price-derived ratios (P/E, P/B, EV/EBIT, FCF yield) are NOT set here (no
    price at fetch time); providers.finalize_valuation fills them once the
    Alpaca SIP price is attached.

Point-in-time note: `companyfacts` carries every historical filing with its
`filed` date, so a future backtest can reconstruct true point-in-time inputs.
For the *current* live screen we take the latest reported (restated) value.
"""
import os
from __future__ import annotations

import datetime as dt
import logging
import time
from typing import Optional

import requests

from . import config
from .data_source import Fundamentals  # shared record contract

log = logging.getLogger("buffett_bot.edgar")

# SEC requires a descriptive User-Agent with contact info; 10 req/s max.
# SEC requires a real contact address in the User-Agent. Set EDGAR_UA before use;
# the default below will be rejected by SEC if you leave it as-is.
_UA = os.environ.get(
    "EDGAR_UA",
    "Backtest Graveyard research bot (set EDGAR_UA to 'your-name your-email')",
)
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": _UA, "Accept-Encoding": "gzip, deflate"})
_POLITE_DELAY_S = 0.12

_MAX_RETRIES = 3
_TICKER_MAP: Optional[dict[str, str]] = None

# --- GAAP concept aliases (first present wins) -----------------------------
_FLOWS = {
    "net_income":       ["NetIncomeLoss"],
    "revenue":          ["RevenueFromContractWithCustomerExcludingAssessedTax",
                         "Revenues", "SalesRevenueNet"],
    "gross_profit":     ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "interest_expense": ["InterestExpense", "InterestExpenseNonoperating"],
    "pretax":           ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
                         "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"],
    "tax":              ["IncomeTaxExpenseBenefit"],
    "ocf":              ["NetCashProvidedByUsedInOperatingActivities",
                         "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    # Capex, most-comprehensive tag first (first-match-wins). Oil & gas
    # producers report drilling capex under the E&P-specific tags, NOT
    # PropertyPlantAndEquipment — without them, an E&P's FCF was just operating
    # cash flow with no capex subtracted (EOG read $10B vs a true ~$4B, so it
    # looked cheap). "...OilAndGasProperty" WITHOUT "AndEquipment" is only a
    # small sub-line, so it must come LAST, never ahead of the full figure.
    "capex":            ["PaymentsToAcquirePropertyPlantAndEquipment",
                         "PaymentsToAcquireOilAndGasPropertyAndEquipment",
                         "PaymentsToAcquireProductiveAssets",
                         "PaymentsForCapitalImprovements",
                         "PaymentsToAcquireOilAndGasProperty"],
    # Non-cash writedowns. Ordered most-comprehensive first and resolved
    # first-match-wins (never summed) — the combined tag already contains the
    # goodwill/intangible components, so adding them would double-count.
    "impairment":       ["GoodwillAndIntangibleAssetImpairment",
                         "GoodwillImpairmentLoss",
                         "ImpairmentOfIntangibleAssetsExcludingGoodwill",
                         "AssetImpairmentCharges",
                         "TangibleAssetImpairmentCharges"],
}
_INSTANTS = {
    "equity":        ["StockholdersEquity",
                      "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "assets_current":["AssetsCurrent"],
    "liab_current":  ["LiabilitiesCurrent"],
    "cash":          ["CashAndCashEquivalentsAtCarryingValue",
                      "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "lt_debt":       ["LongTermDebtNoncurrent", "LongTermDebt"],
    "lt_debt_cur":   ["LongTermDebtCurrent"],
    "short_debt":    ["ShortTermBorrowings", "DebtCurrent"],
}


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def _get(url: str) -> Optional[dict]:
    last = None
    for i in range(_MAX_RETRIES):
        try:
            r = _SESSION.get(url, timeout=20)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None                       # no such CIK/concept
            last = f"HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001
            last = str(e)
        time.sleep(0.5 * (i + 1))
    log.warning("EDGAR GET failed %s: %s", url, last)
    return None


def _ticker_map() -> dict[str, str]:
    global _TICKER_MAP
    if _TICKER_MAP is None:
        data = _get("https://www.sec.gov/files/company_tickers.json") or {}
        _TICKER_MAP = {
            row["ticker"].upper().replace(".", "-"): str(row["cik_str"]).zfill(10)
            for row in data.values()
        }
        time.sleep(_POLITE_DELAY_S)
        log.info("EDGAR ticker→CIK map: %d symbols", len(_TICKER_MAP))
    return _TICKER_MAP


def ticker_to_cik(ticker: str) -> Optional[str]:
    return _ticker_map().get(ticker.upper())


_SIC_CACHE: dict[str, tuple[Optional[int], Optional[str]]] = {}


def company_sic(cik: str) -> tuple[Optional[int], Optional[str]]:
    """(SIC code, description) from the SEC submissions endpoint, cached.

    SIC is not in companyfacts, so this is one extra (cached) request per
    company. It drives business-model-aware gates: a bank/insurer has no
    working-capital cycle, and a SaaS company runs current-ratio < 1 by design
    (deferred revenue), so the generic current-ratio/interest-coverage gates
    must not fire for them.
    """
    if cik in _SIC_CACHE:
        return _SIC_CACHE[cik]
    result: tuple[Optional[int], Optional[str]] = (None, None)
    data = _get(f"https://data.sec.gov/submissions/CIK{cik}.json")
    time.sleep(_POLITE_DELAY_S)
    if data:
        raw = data.get("sic")
        try:
            code = int(raw) if raw not in (None, "") else None
        except (TypeError, ValueError):
            code = None
        result = (code, data.get("sicDescription"))
    _SIC_CACHE[cik] = result
    return result


def classify_valuation_model(sic: Optional[int]) -> str:
    """Which intrinsic-value model fits this company's economics.

    "book_value" — BALANCE-SHEET financials only: banks, thrifts, and insurance
        underwriters. Their equity base *is* the productive asset, so justified
        price-to-book is the right lens.
    "cashflow" — everyone else, including the rest of SIC 6000-6799. This split
        matters: a REIT carries property at depreciated cost (American Tower
        trades at ~22x book, so P/B is meaningless for it) and an exchange or
        asset manager is an asset-light fee business (CBOE ~5x book). Lumping
        those in with banks produced absurd valuations. They keep the financial
        *gate* exemptions but get valued on cash flow.
    """
    if sic is None:
        return "cashflow"
    if 6020 <= sic <= 6120:      # national/state banks, thrifts, credit institutions
        return "book_value"
    if 6310 <= sic <= 6399:      # insurance underwriters (life, health, P&C, surety)
        return "book_value"
    return "cashflow"            # 6199 finance svcs, 6200s brokers/exchanges,
                                 # 6411 agents, 6500s real estate, 6798 REITs


def classify_business_model(sic: Optional[int]) -> str:
    """Map a SIC code to a coarse business model for gate selection.

      financial  6000-6799  banks, insurers, REITs, holding/investment cos
      software   7370-7379  prepackaged software / IT services (deferred rev)
      other      everything else
    """
    if sic is None:
        return "other"
    if 6000 <= sic <= 6799:
        return "financial"
    if 7370 <= sic <= 7379:
        return "software"
    return "other"


# --- concept extraction ----------------------------------------------------
def _units(facts: dict, concept: str) -> Optional[list[dict]]:
    """Return the flattened unit-fact list for a us-gaap/dei concept."""
    for taxonomy in ("us-gaap", "dei"):
        node = facts.get(taxonomy, {}).get(concept)
        if node and node.get("units"):
            # take the first (usually only) unit key: USD, shares, etc.
            first = next(iter(node["units"].values()))
            return first
    return None


def _first_present(facts: dict, aliases: list[str]) -> Optional[list[dict]]:
    for a in aliases:
        u = _units(facts, a)
        if u:
            return u
    return None


# Annual reports carry the authoritative, full-scale figure. A value can ALSO
# surface in later filings (proxies, 8-Ks, S-4s) pre-scaled to thousands or
# millions — and "latest filed wins" would then grab the mis-scaled copy,
# reading Schwab's $8.85B net income as $8.85M and inflating its P/E ~1000x.
# Restricting flows to the annual report keeps the value at true USD scale.
_ANNUAL_FORMS = ("10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A")


def _visible(fact: dict, as_of: Optional[dt.date]) -> bool:
    """POINT-IN-TIME GATE. True if this fact was already filed on `as_of`.

    Every backtest date must see only what the market could see then. Without
    this, a 2019 screen would use figures restated in 2023 — look-ahead bias
    that makes a backtest look good for entirely fake reasons. as_of=None means
    live mode (everything visible).
    """
    if as_of is None:
        return True
    filed = fact.get("filed")
    return bool(filed) and filed <= as_of.isoformat()


def _annual_flow_pairs(facts: dict, aliases: list[str],
                       as_of: Optional[dt.date] = None) -> list[tuple[dt.date, float]]:
    """Annual (fiscal_year_end, value) pairs, newest first, taken only from the
    annual report (10-K/20-F/40-F). Latest filing per fiscal-year-end wins, so a
    10-K/A restatement supersedes the original — but only among filings visible
    as of `as_of`."""
    u = _first_present(facts, aliases)
    if not u:
        return []
    rows: dict[dt.date, tuple[float, str]] = {}
    for f in u:
        start, end = f.get("start"), f.get("end")
        if not start or not end:
            continue
        if f.get("form") not in _ANNUAL_FORMS:
            continue
        if not _visible(f, as_of):
            continue
        if not (330 <= (_date(end) - _date(start)).days <= 400):
            continue
        e, filed = _date(end), f.get("filed", "")
        prev = rows.get(e)
        if prev is None or filed > prev[1]:
            rows[e] = (float(f["val"]), filed)
    return [(e, rows[e][0]) for e in sorted(rows, reverse=True)]


def _annual_flow_series(facts: dict, aliases: list[str],
                        as_of: Optional[dt.date] = None) -> list[float]:
    return [v for _, v in _annual_flow_pairs(facts, aliases, as_of)]


def _annual_instant_pairs(facts: dict, aliases: list[str],
                          as_of: Optional[dt.date] = None
                          ) -> list[tuple[dt.date, float]]:
    """Balance-sheet (instant) values as reported in ANNUAL reports, newest
    first — one per fiscal-year end.

    Needed to normalize ROE across years: a single year's ROE is badly distorted
    for insurers (a catastrophe year) and banks (a provision cycle), so the
    valuation model averages net income / equity over several years. Restricted
    to annual forms for the same full-scale reason as _annual_flow_pairs.
    """
    rows: dict[dt.date, tuple[float, str]] = {}
    for alias in aliases:
        u = _units(facts, alias)
        if not u:
            continue
        for f in u:
            if "start" in f:                      # duration fact, not an instant
                continue
            end = f.get("end")
            if not end or f.get("form") not in _ANNUAL_FORMS:
                continue
            if not _visible(f, as_of):
                continue
            e, filed = _date(end), f.get("filed", "")
            prev = rows.get(e)
            if prev is None or filed > prev[1]:
                rows[e] = (float(f["val"]), filed)
        if rows:
            break                                  # first alias that has data wins
    return [(e, rows[e][0]) for e in sorted(rows, reverse=True)]


# Discard any instant fact older than this. EDGAR's companyfacts API omits
# *dimensioned* facts, so once a filer starts tagging a concept per share-class
# or segment, the undimensioned total silently stops updating — leaving a value
# that can be a decade stale (e.g. Visa's cover-page share count froze in 2010).
# Without this guard those ghosts flow straight into the ratios.
_MAX_INSTANT_AGE_DAYS = 800


def _latest_instant(facts: dict, aliases: list[str],
                    max_age_days: int = _MAX_INSTANT_AGE_DAYS,
                    label: str = "",
                    as_of: Optional[dt.date] = None) -> Optional[float]:
    """Most recently reported balance-sheet / shares value (any form) visible as
    of `as_of`, or None if the newest available fact is staler than
    `max_age_days` *relative to that date* (not to today)."""
    # Try EVERY alias and keep the freshest fact. Checking only the first alias
    # that exists would discard a concept whose primary tag went stale (common
    # when a filer switches tags or starts tagging dimensionally) even though a
    # perfectly current synonym is sitting right there.
    best_val, best_end, best_tag = None, None, None
    for alias in aliases:
        u = _units(facts, alias)
        if not u:
            continue
        for f in u:
            if "start" in f:             # duration fact -> not an instant
                continue
            end = f.get("end")
            if not end:
                continue
            if not _visible(f, as_of):
                continue
            e = _date(end)
            if best_end is None or e > best_end:
                best_end, best_val, best_tag = e, float(f["val"]), alias
    if best_end is None:
        return None
    age = ((as_of or dt.date.today()) - best_end).days
    if age > max_age_days:
        log.debug("stale instant %s (%s): newest fact %s is %d days old — discarded",
                  label or aliases[0], best_tag, best_end, age)
        return None
    return best_val


def _shares_outstanding(facts: dict, as_of: Optional[dt.date] = None) -> Optional[float]:
    """Diluted share count, most-reliable source first.

    Multi-class filers (V, BRK, GOOG) tag share counts *per class*, and
    dimensioned facts are absent from companyfacts — so the obvious tags are
    either missing or frozen years ago. Deriving shares from
    `net income / diluted EPS` sidesteps that entirely: both are undimensioned
    consolidated totals that every filer reports.

    Backtest note: this returns the count *as reported then*, which pairs with a
    RAW (unadjusted) historical price. Never mix it with a split-adjusted price.
    """
    # 1) diluted weighted-average shares (the EPS denominator) when present
    waso = _annual_flow_series(
        facts, ["WeightedAverageNumberOfDilutedSharesOutstanding",
                "WeightedAverageNumberOfDilutedSharesOutstandingIncludingParticipatingSecurities",
                "WeightedAverageNumberOfShareOutstandingBasicAndDiluted"], as_of)
    if waso and waso[0] > 0:
        return waso[0]

    # 2) derive from net income / diluted EPS on the SAME fiscal year
    ni = dict(_annual_flow_pairs(facts, _FLOWS["net_income"], as_of))
    eps = dict(_annual_flow_pairs(facts, ["EarningsPerShareDiluted",
                                          "EarningsPerShareBasicAndDiluted"], as_of))
    for end in sorted(set(ni) & set(eps), reverse=True):
        if ni[end] and eps[end] and eps[end] != 0:
            derived = ni[end] / eps[end]
            if derived > 0:
                log.debug("shares derived from NI/EPS at %s: %.0f", end, derived)
                return derived

    # 3) cover-page / balance-sheet counts, only if not stale
    for concept in ("EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding"):
        v = _latest_instant(facts, [concept], label=concept, as_of=as_of)
        if v:
            return v
    return None


# --- public API ------------------------------------------------------------
def fetch_facts(ticker: str) -> Optional[dict]:
    """Raw companyfacts JSON for one company (full filing history, one request).

    Split out from build() so a backtest can fetch each company ONCE and then
    reconstruct a point-in-time snapshot for every rebalance date offline —
    the payload already contains every historical filing with its filed date.
    """
    cik = ticker_to_cik(ticker)
    if cik is None:
        log.info("[%s] not in EDGAR ticker map (foreign/ETF?) — skip", ticker)
        return None
    data = _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
    time.sleep(_POLITE_DELAY_S)
    if not data or "facts" not in data:
        log.warning("[%s] no companyfacts", ticker)
        return None
    # Inject SIC so build() can classify the business model offline (the
    # backtest reconstructs many snapshots from cached facts without network).
    sic, sic_desc = company_sic(cik)
    data["sic"] = sic
    data["sicDescription"] = sic_desc
    return data


def fetch_one(ticker: str, as_of: Optional[dt.date] = None) -> Optional[Fundamentals]:
    """Fetch + normalize one company from EDGAR. None only on total failure."""
    data = fetch_facts(ticker)
    if data is None:
        return None
    return build(ticker, data, as_of)


def build(ticker: str, data: dict,
          as_of: Optional[dt.date] = None) -> Optional[Fundamentals]:
    """Normalize a companyfacts payload into Fundamentals as visible on `as_of`.

    as_of=None -> live mode (everything). Otherwise only filings dated on or
    before as_of are used, so a backtest sees exactly what the market saw then.
    """
    facts = data.get("facts")
    if not facts:
        return None

    f = Fundamentals(ticker=ticker, price_source="pending")
    f.name = data.get("entityName")
    f.sic = data.get("sic")
    f.sector = data.get("sicDescription")
    f.business_model = classify_business_model(f.sic)
    f.valuation_model = classify_valuation_model(f.sic)

    # ---- flows (annual) ----
    ni_pairs = _annual_flow_pairs(facts, _FLOWS["net_income"], as_of)
    ni = [v for _, v in ni_pairs]
    rev = _annual_flow_series(facts, _FLOWS["revenue"], as_of)
    gp = _annual_flow_series(facts, _FLOWS["gross_profit"], as_of)
    oi = _annual_flow_series(facts, _FLOWS["operating_income"], as_of)
    interest = _annual_flow_series(facts, _FLOWS["interest_expense"], as_of)
    pretax = _annual_flow_series(facts, _FLOWS["pretax"], as_of)
    tax = _annual_flow_series(facts, _FLOWS["tax"], as_of)
    ocf = _annual_flow_series(facts, _FLOWS["ocf"], as_of)
    capex = _annual_flow_series(facts, _FLOWS["capex"], as_of)

    f.net_income = ni[0] if ni else None
    latest_rev = rev[0] if rev else None
    f.ebit = oi[0] if oi else None

    # Gate context (see screener._charge_context). Attribute a writedown ONLY
    # when it is tagged to the SAME fiscal year as the latest net income —
    # otherwise an old impairment gets blamed for a current loss.
    latest_fy = ni_pairs[0][0] if ni_pairs else None
    if latest_fy is not None:
        f.impairment = dict(
            _annual_flow_pairs(facts, _FLOWS["impairment"], as_of)).get(latest_fy)
        f.pretax_income = dict(
            _annual_flow_pairs(facts, _FLOWS["pretax"], as_of)).get(latest_fy)

    # ---- instants (latest reported as of the date) ----
    f.total_equity = _latest_instant(facts, _INSTANTS["equity"], label="equity", as_of=as_of)
    ac = _latest_instant(facts, _INSTANTS["assets_current"], label="assets_current", as_of=as_of)
    lc = _latest_instant(facts, _INSTANTS["liab_current"], label="liab_current", as_of=as_of)
    f.total_cash = _latest_instant(facts, _INSTANTS["cash"], label="cash", as_of=as_of)
    ltd = _latest_instant(facts, _INSTANTS["lt_debt"], label="lt_debt", as_of=as_of)
    ltdc = _latest_instant(facts, _INSTANTS["lt_debt_cur"], label="lt_debt_cur", as_of=as_of)
    sd = _latest_instant(facts, _INSTANTS["short_debt"], label="short_debt", as_of=as_of)
    f.shares_out = _shares_outstanding(facts, as_of)
    if f.shares_out:
        f.shares_source = "edgar"

    debt_parts = [x for x in (ltd, ltdc, sd) if x is not None]
    f.total_debt = sum(debt_parts) if debt_parts else None

    # ---- margins ----
    if latest_rev and latest_rev > 0:
        if gp:
            f.gross_margin = gp[0] / latest_rev
        if f.ebit is not None:
            f.operating_margin = f.ebit / latest_rev
        if f.net_income is not None:
            f.net_margin = f.net_income / latest_rev

    # ---- returns ----
    if f.total_equity and f.total_equity > 0 and f.net_income is not None:
        f.roe = f.net_income / f.total_equity

    # Normalized ROE: mean of same-year net_income/equity across annual reports.
    # One year of ROE is noise for a financial (catastrophe years, provision
    # cycles); the justified-P/B model needs a through-cycle figure.
    eq_by_fy = dict(_annual_instant_pairs(facts, _INSTANTS["equity"], as_of))
    ni_by_fy = dict(ni_pairs)
    yearly = [ni_by_fy[e] / eq_by_fy[e]
              for e in sorted(set(ni_by_fy) & set(eq_by_fy), reverse=True)
              if eq_by_fy[e] and eq_by_fy[e] > 0][:config.FINANCIALS["roe_years"]]
    if yearly:
        f.roe_normalized = sum(yearly) / len(yearly)
        f.roe_years = len(yearly)
    f.roic = _roic(f.ebit, pretax[0] if pretax else None,
                   tax[0] if tax else None, f.total_equity, f.total_debt, f.total_cash)

    # ---- health ----
    if ac is not None and lc not in (None, 0):
        f.current_ratio = ac / lc
    if f.total_equity and f.total_equity > 0 and f.total_debt is not None:
        f.debt_to_equity = f.total_debt / f.total_equity
    if f.ebit is not None and interest and interest[0]:
        f.interest_coverage = f.ebit / abs(interest[0])

    # ---- cash / FCF ----
    # Build the FCF series with operating cash flow and capex matched BY FISCAL
    # YEAR (the two tag series can have different year coverage, so index-0 vs
    # index-0 could silently subtract capex from the wrong year).
    ocf_by_fy = dict(_annual_flow_pairs(facts, _FLOWS["ocf"], as_of))
    capex_by_fy = dict(_annual_flow_pairs(facts, _FLOWS["capex"], as_of))
    fcf_series = [ocf_by_fy[e] - abs(capex_by_fy[e])
                  for e in sorted(set(ocf_by_fy) & set(capex_by_fy), reverse=True)]
    if fcf_series:
        f.free_cash_flow = fcf_series[0]
    elif ocf:
        f.free_cash_flow = ocf[0]

    # Through-cycle FCF, for the cyclical-earnings guard (see screener). A
    # commodity producer at peak shows trailing FCF far above this mean.
    #
    # Two conditions must hold for the mean to be a valid normalization baseline,
    # each ruling out a distinct kind of false positive:
    #   (1) every year positive — a mature cyclical stays cash-generative through
    #       the cycle; a growth-inflection name (UBER, ABNB) was FCF-negative
    #       earlier, so its mean is dragged by loss years, not a real baseline.
    #   (2) the series OSCILLATES (had a year-over-year decline) — a real cycle
    #       comes back down; monotonically-rising FCF (PLTR, APP) is GROWTH, and
    #       its current level being 2x the level five years ago is exactly what
    #       growth looks like, not a peak to revert from.
    window = fcf_series[:config.CYCLICAL["fcf_years"]]  # newest-first
    has_decline = any(window[i] < window[i + 1] for i in range(len(window) - 1))
    if len(window) >= config.CYCLICAL["min_years"] and min(window) > 0 and has_decline:
        f.free_cash_flow_avg = sum(window) / len(window)
        f.fcf_years = len(window)

    # ---- growth & consistency (multi-year) ----
    f.earnings_growth = _cagr_list(ni)
    f.revenue_growth = _cagr_list(rev)
    f.earnings_stability = _stability_list(ni)

    f.missing = [k for k, v in f.as_dict().items() if v is None and k != "missing"]
    return f


def _roic(ebit, pretax, tax, equity, debt, cash) -> Optional[float]:
    if ebit is None or ebit <= 0 or equity is None:
        return None
    tax_rate = 0.21
    if pretax and pretax > 0 and tax is not None:
        tr = tax / pretax
        if 0 <= tr <= 0.6:
            tax_rate = tr
    invested = (debt or 0) + equity - (cash or 0)
    if invested <= 0:
        return None
    return (ebit * (1 - tax_rate)) / invested


def _cagr_list(series: list[float]) -> Optional[float]:
    """CAGR over an annual series (newest first). Guards sign issues."""
    vals = [v for v in series if v is not None]
    if len(vals) < 2:
        return None
    newest, oldest, n = vals[0], vals[-1], len(vals) - 1
    if oldest <= 0 or newest <= 0:
        return None
    return (newest / oldest) ** (1.0 / n) - 1.0


def _stability_list(series: list[float]) -> Optional[float]:
    """Fraction of year-over-year periods that did not decline (0..1)."""
    vals = [v for v in series if v is not None]
    if len(vals) < 2:
        return None
    vals = list(reversed(vals))  # oldest -> newest
    ups = sum(1 for a, b in zip(vals, vals[1:]) if b >= a)
    return ups / (len(vals) - 1)
