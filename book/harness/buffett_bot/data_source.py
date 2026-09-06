"""
Data collection layer for the Buffett Bot.

Primary source: yfinance (free, no API key) for quotes, key statistics, and the
three financial statements. This layer is responsible for:
  * polite rate-limiting + retries with backoff (yfinance is scraping Yahoo)
  * turning noisy/partial vendor data into a clean, typed Fundamentals record
  * degrading gracefully — a missing field becomes None, never a crash

Swap-in note: to upgrade to a paid feed (e.g. FMP, which this project already
has credentials for), implement `fetch_one()` against that API and keep the
Fundamentals dataclass identical — nothing downstream changes.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

import pandas as pd
import yfinance as yf

log = logging.getLogger("buffett_bot.data")

# Be gentle with Yahoo: small delay between symbols + bounded retries.
_REQUEST_DELAY_S = 0.4
_MAX_RETRIES = 3
_BACKOFF_BASE_S = 1.5


@dataclass
class Fundamentals:
    """Normalized, source-agnostic snapshot of one company."""
    ticker: str
    name: Optional[str] = None
    sector: Optional[str] = None
    sic: Optional[int] = None            # SEC Standard Industrial Classification
    business_model: str = "other"        # "financial" | "software" | "other" (gates)
    valuation_model: str = "cashflow"    # "book_value" | "cashflow" (intrinsic value)
    price: Optional[float] = None
    market_cap: Optional[float] = None
    shares_out: Optional[float] = None

    # Valuation
    pe: Optional[float] = None
    pb: Optional[float] = None
    peg: Optional[float] = None
    ev_ebit: Optional[float] = None
    fcf_yield: Optional[float] = None

    # Profitability / returns
    roe: Optional[float] = None
    roic: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None

    # Health
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    interest_coverage: Optional[float] = None

    # Growth / consistency
    earnings_growth: Optional[float] = None   # multi-year net-income CAGR
    revenue_growth: Optional[float] = None
    earnings_stability: Optional[float] = None  # 0..1, fraction of up-years

    # Cash / balance-sheet raw (for DCF + price-derived ratios)
    free_cash_flow: Optional[float] = None
    total_debt: Optional[float] = None
    total_cash: Optional[float] = None
    total_equity: Optional[float] = None   # book value (for P/B)
    ebit: Optional[float] = None           # operating income (for EV/EBIT)
    net_income: Optional[float] = None
    pretax_income: Optional[float] = None  # same FY as net_income (gate context)
    impairment: Optional[float] = None     # same-FY writedown, if any (context)
    roe_normalized: Optional[float] = None # multi-year mean ROE (financials model)
    roe_years: int = 0                     # how many years fed roe_normalized
    free_cash_flow_avg: Optional[float] = None  # through-cycle mean FCF
    fcf_years: int = 0                     # how many years fed free_cash_flow_avg
    fcf_normalized: bool = False           # True = DCF used the mean, not the
                                           # latest year (cyclical guard tripped)
    dividend_yield: Optional[float] = None
    payout_ratio: Optional[float] = None

    # Provenance
    price_source: str = "yfinance"    # overridden to "alpaca_sip" when available
    shares_source: Optional[str] = None  # "edgar" | "yfinance" (multi-class fallback)

    # Diagnostics
    missing: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# small helpers                                                               #
# --------------------------------------------------------------------------- #
def _num(x) -> Optional[float]:
    """Coerce to float or None (handles NaN, None, weird strings)."""
    try:
        if x is None:
            return None
        f = float(x)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


def _row(df: Optional[pd.DataFrame], *names) -> Optional[pd.Series]:
    """Return the first matching row (by label) from a statement DataFrame."""
    if df is None or df.empty:
        return None
    for n in names:
        if n in df.index:
            return df.loc[n]
    return None


def _latest(series: Optional[pd.Series]) -> Optional[float]:
    if series is None or series.empty:
        return None
    return _num(series.iloc[0])


def _cagr(series: Optional[pd.Series]) -> Optional[float]:
    """CAGR from oldest->newest of a statement row (columns are years, newest
    first in yfinance). Returns None if signs make CAGR meaningless."""
    if series is None or series.dropna().empty:
        return None
    vals = [_num(v) for v in series.tolist()]
    vals = [v for v in vals if v is not None]
    if len(vals) < 2:
        return None
    newest, oldest = vals[0], vals[-1]
    n = len(vals) - 1
    if oldest is None or oldest <= 0 or newest <= 0:
        return None
    return (newest / oldest) ** (1.0 / n) - 1.0


def _stability(series: Optional[pd.Series]) -> Optional[float]:
    """Fraction of year-over-year periods that did not decline (0..1)."""
    if series is None or series.dropna().empty:
        return None
    vals = [_num(v) for v in series.tolist() if _num(v) is not None]
    if len(vals) < 2:
        return None
    vals = list(reversed(vals))  # oldest -> newest
    ups = sum(1 for a, b in zip(vals, vals[1:]) if b >= a)
    return ups / (len(vals) - 1)


# --------------------------------------------------------------------------- #
# main fetch                                                                  #
# --------------------------------------------------------------------------- #
def fetch_one(ticker: str) -> Optional[Fundamentals]:
    """Fetch and normalize one company. Returns None only on total failure."""
    last_err = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return _fetch_one_impl(ticker)
        except Exception as e:  # noqa: BLE001
            last_err = e
            wait = _BACKOFF_BASE_S * attempt
            log.warning("[%s] fetch attempt %d/%d failed: %s (retrying in %.1fs)",
                        ticker, attempt, _MAX_RETRIES, e, wait)
            time.sleep(wait)
    log.error("[%s] giving up after %d attempts: %s", ticker, _MAX_RETRIES, last_err)
    return None


def _fetch_one_impl(ticker: str) -> Fundamentals:
    tk = yf.Ticker(ticker)
    info = tk.info or {}
    f = Fundamentals(ticker=ticker)

    f.name = info.get("longName") or info.get("shortName")
    f.sector = info.get("sector")
    f.price = _num(info.get("currentPrice") or info.get("regularMarketPrice"))
    f.market_cap = _num(info.get("marketCap"))
    f.shares_out = _num(info.get("sharesOutstanding"))

    # ---- valuation from key stats ----
    f.pe = _num(info.get("trailingPE"))
    f.pb = _num(info.get("priceToBook"))
    f.peg = _num(info.get("trailingPegRatio") or info.get("pegRatio"))
    f.dividend_yield = _num(info.get("dividendYield"))
    f.payout_ratio = _num(info.get("payoutRatio"))

    # ---- profitability from key stats ----
    f.roe = _num(info.get("returnOnEquity"))
    f.gross_margin = _num(info.get("grossMargins"))
    f.operating_margin = _num(info.get("operatingMargins"))
    f.net_margin = _num(info.get("profitMargins"))
    f.revenue_growth = _num(info.get("revenueGrowth"))
    f.earnings_growth = _num(info.get("earningsGrowth"))

    # ---- health from key stats ----
    d2e = _num(info.get("debtToEquity"))
    f.debt_to_equity = d2e / 100.0 if d2e and d2e > 5 else d2e  # yf reports %
    f.current_ratio = _num(info.get("currentRatio"))
    f.total_debt = _num(info.get("totalDebt"))
    f.total_cash = _num(info.get("totalCash"))
    f.free_cash_flow = _num(info.get("freeCashflow"))

    # ---- statements (for things key-stats doesn't give reliably) ----
    fin = _safe_stmt(tk, "financials")        # income statement, annual
    bs = _safe_stmt(tk, "balance_sheet")
    cf = _safe_stmt(tk, "cashflow")

    ni_row = _row(fin, "Net Income", "NetIncome", "Net Income Common Stockholders")
    rev_row = _row(fin, "Total Revenue", "TotalRevenue", "Operating Revenue")
    ebit_row = _row(fin, "EBIT", "Operating Income", "OperatingIncome")
    interest_row = _row(fin, "Interest Expense", "InterestExpense")

    f.net_income = _latest(ni_row)

    # multi-year growth + stability (override key-stat 1y figure if we have depth)
    ni_cagr = _cagr(ni_row)
    if ni_cagr is not None:
        f.earnings_growth = ni_cagr
    rev_cagr = _cagr(rev_row)
    if rev_cagr is not None:
        f.revenue_growth = rev_cagr
    f.earnings_stability = _stability(ni_row)

    # interest coverage = EBIT / |interest expense|
    ebit = _latest(ebit_row)
    interest = _latest(interest_row)
    if ebit is not None and interest not in (None, 0):
        f.interest_coverage = ebit / abs(interest)

    # EV / EBIT
    ev = _num(info.get("enterpriseValue"))
    if ev is None and f.market_cap is not None:
        ev = f.market_cap + (f.total_debt or 0) - (f.total_cash or 0)
    if ev is not None and ebit not in (None, 0) and ebit > 0:
        f.ev_ebit = ev / ebit

    # FCF yield
    if f.free_cash_flow is None:
        ocf = _latest(_row(cf, "Operating Cash Flow", "Total Cash From Operating Activities"))
        capex = _latest(_row(cf, "Capital Expenditure", "Capital Expenditures"))
        if ocf is not None and capex is not None:
            f.free_cash_flow = ocf + capex  # capex is negative in yf
    if f.free_cash_flow is not None and f.market_cap:
        f.fcf_yield = f.free_cash_flow / f.market_cap

    # ROIC = NOPAT / invested capital  (approximate, conservative)
    f.roic = _compute_roic(ebit, fin, bs)

    f.missing = [k for k, v in f.as_dict().items()
                 if v is None and k not in ("missing",)]
    time.sleep(_REQUEST_DELAY_S)
    return f


def _compute_roic(ebit, fin, bs) -> Optional[float]:
    """NOPAT / (total debt + equity - cash). Uses a 21% flat tax if the
    effective rate can't be derived. Returns None if inputs are missing."""
    if ebit is None or ebit <= 0:
        return None
    pretax = _latest(_row(fin, "Pretax Income", "PretaxIncome",
                           "Income Before Tax"))
    tax = _latest(_row(fin, "Tax Provision", "Income Tax Expense",
                       "TaxProvision"))
    tax_rate = 0.21
    if pretax and pretax > 0 and tax is not None:
        tr = tax / pretax
        if 0 <= tr <= 0.6:
            tax_rate = tr
    nopat = ebit * (1 - tax_rate)

    debt = _latest(_row(bs, "Total Debt", "TotalDebt"))
    equity = _latest(_row(bs, "Stockholders Equity", "Total Stockholder Equity",
                          "StockholdersEquity", "Common Stock Equity"))
    cash = _latest(_row(bs, "Cash And Cash Equivalents",
                        "CashAndCashEquivalents", "Cash"))
    if equity is None:
        return None
    invested = (debt or 0) + equity - (cash or 0)
    if invested <= 0:
        return None
    return nopat / invested


def _safe_stmt(tk: "yf.Ticker", attr: str) -> Optional[pd.DataFrame]:
    try:
        df = getattr(tk, attr)
        if isinstance(df, pd.DataFrame) and not df.empty:
            return df
    except Exception as e:  # noqa: BLE001
        log.debug("statement %s unavailable: %s", attr, e)
    return None
