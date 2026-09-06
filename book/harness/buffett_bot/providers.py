"""
Pluggable data providers.

Two independent seams so each layer can use the best-available source:

  PRICE        -> Alpaca SIP (full consolidated tape, already paid for) in one
                  batch call, with automatic yfinance fallback. Price feeds the
                  DCF margin-of-safety, so accuracy here is worth the round-trip.

  FUNDAMENTALS -> yfinance today; FMP is stubbed and drops in the moment
                  ~/.fmp/credentials exists AND config selects it. Both providers
                  return the identical `Fundamentals` contract, so nothing
                  downstream (screener, scoring, DCF) changes when you swap.

Design rule: a provider NEVER crashes the bot. Alpaca unreachable -> {} ->
yfinance price. FMP unavailable/unimplemented -> silently fall back to yfinance.
"""
from __future__ import annotations

import logging
import os
from typing import Optional, Protocol, runtime_checkable

from . import config
from . import edgar_source
from .data_source import Fundamentals, fetch_one as _yf_fetch

log = logging.getLogger("buffett_bot.providers")


# ==========================================================================
# PRICE
# ==========================================================================
_alpaca_mod = None  # None = not tried, False = unavailable, module = ready


def _alpaca():
    """Lazy, fault-tolerant import of the project's Alpaca client.

    Importing alpaca_client pulls in config.py, which fail-fasts if broker
    credentials are missing. A fundamentals screener must survive that, so we
    swallow any import error and mark Alpaca unavailable (prices fall back)."""
    global _alpaca_mod
    if _alpaca_mod is None:
        try:
            import alpaca_client  # noqa: PLC0415 — intentional lazy import
            _alpaca_mod = alpaca_client
            log.info("Alpaca SIP price provider ready.")
        except Exception as e:  # noqa: BLE001
            log.warning("Alpaca unavailable (%s) — prices fall back to yfinance.", e)
            _alpaca_mod = False
    return _alpaca_mod or None


def fetch_prices(tickers: list[str]) -> dict[str, float]:
    """Latest SIP trade price per ticker in one batch call.

    Returns {ticker: price}. Empty dict if Alpaca is unavailable — callers then
    keep the yfinance price already on the Fundamentals record. Chunked to stay
    within URL-length limits on large universes.
    """
    if config.PROVIDERS.get("price") != "alpaca":
        return {}
    ac = _alpaca()
    if not ac:
        return {}
    out: dict[str, float] = {}
    CHUNK = 200
    for i in range(0, len(tickers), CHUNK):
        batch = tickers[i:i + CHUNK]
        # Alpaca spells class shares with a dot (BRK.B); EDGAR/yfinance use a
        # dash (BRK-B). Translate on the way out and map results back.
        amap = {_to_alpaca_symbol(t): t for t in batch}
        try:
            _fetch_price_batch(ac, list(amap), amap, out)
        except Exception as e:  # noqa: BLE001
            log.warning("Alpaca batch price failed for chunk %d (%s).", i // CHUNK, e)
    log.info("Alpaca SIP prices: %d/%d tickers (rest use yfinance).",
             len(out), len(tickers))
    return out


def _to_alpaca_symbol(ticker: str) -> str:
    """BRK-B -> BRK.B (Alpaca's class-share convention)."""
    return ticker.replace("-", ".")


def _fetch_price_batch(ac, syms: list[str], amap: dict[str, str],
                       out: dict[str, float]) -> None:
    """Fetch a batch, halving on total failure to isolate bad symbols.

    Alpaca's multi-symbol endpoint returns NOTHING for the whole request if any
    one symbol is malformed — so a single bad ticker would silently wipe prices
    for the entire universe. On an empty result we split and retry, which
    isolates the offender in ~log2(n) rounds instead of losing every price.
    """
    if not syms:
        return
    got = ac.get_latest_prices_batch(syms)
    if got:
        for a, p in got.items():
            out[amap.get(a, a)] = p
        return
    if len(syms) == 1:
        log.debug("no Alpaca price for %s", syms[0])
        return
    mid = len(syms) // 2
    _fetch_price_batch(ac, syms[:mid], amap, out)
    _fetch_price_batch(ac, syms[mid:], amap, out)


# ==========================================================================
# FUNDAMENTALS
# ==========================================================================
@runtime_checkable
class FundamentalsProvider(Protocol):
    name: str
    def fetch(self, ticker: str) -> Optional[Fundamentals]: ...


class YFinanceFundamentals:
    """Free yfinance scrape (see data_source.py). Serves pre-computed ratios."""
    name = "yfinance"

    def fetch(self, ticker: str) -> Optional[Fundamentals]:
        return _yf_fetch(ticker)


class EdgarFundamentals:
    """SEC EDGAR — source-of-truth XBRL filings (see edgar_source.py).

    Most accurate for US filers and free. Returns raw statement values; the
    price-derived ratios (P/E, P/B, EV/EBIT, FCF yield) are filled later by
    finalize_valuation once the SIP price is attached. `fallback` (yfinance) is
    tried when EDGAR can't map a ticker (foreign issuers, ETFs, thin filers).
    """
    name = "edgar"

    def __init__(self, fallback: Optional["FundamentalsProvider"] = None):
        self.fallback = fallback

    def fetch(self, ticker: str) -> Optional[Fundamentals]:
        try:
            f = edgar_source.fetch_one(ticker)
        except Exception as e:  # noqa: BLE001 — never crash the run on one name
            log.warning("[%s] EDGAR fetch error (%s)", ticker, e)
            f = None
        if f is None and self.fallback is not None:
            log.info("[%s] EDGAR miss — falling back to %s", ticker, self.fallback.name)
            return self.fallback.fetch(ticker)
        if f is not None and not f.shares_out:
            _patch_shares_from_yfinance(f)
        return f


def _patch_shares_from_yfinance(f: Fundamentals) -> None:
    """Fill share count from yfinance when EDGAR structurally can't supply it.

    Multi-class filers (V, BRK, and others) tag every share/EPS concept per
    class, and companyfacts omits dimensioned facts — so EDGAR has no
    consolidated share count at any age. Without this, market cap is None and
    the min_market_cap gate silently REJECTS the company (Berkshire itself
    included). Statements still come from EDGAR; only this one field is
    borrowed, and `shares_source` records it.
    """
    sh = mc = None
    try:
        import yfinance as yf  # noqa: PLC0415 — only needed on the rare fallback
        tk = yf.Ticker(f.ticker)

        # fast_info first: it's a lighter endpoint and stays populated for names
        # whose full .info comes back empty (Visa does exactly this).
        try:
            fi = tk.fast_info
            sh, mc = fi["shares"], fi["market_cap"]
        except Exception:  # noqa: BLE001
            pass

        if not sh:
            info = tk.info or {}
            # impliedSharesOutstanding is the as-converted all-class total — a
            # better denominator for a multi-class company than one class alone.
            sh = info.get("impliedSharesOutstanding") or info.get("sharesOutstanding")
            mc = mc or info.get("marketCap")
    except Exception as e:  # noqa: BLE001
        log.warning("[%s] share-count fallback failed (%s)", f.ticker, e)
        return

    if sh:
        f.shares_out = float(sh)
        f.shares_source = "yfinance"
        log.info("[%s] shares from yfinance (multi-class; EDGAR has none): %.0f",
                 f.ticker, f.shares_out)
    if mc and f.market_cap is None:
        f.market_cap = float(mc)


class FMPFundamentals:
    """STUB — Financial Modeling Prep (Starter tier serves full statements).

    To activate: implement fetch() against FMP's /income-statement,
    /balance-sheet-statement, /cash-flow-statement, /ratios-ttm and /quote
    endpoints, mapping into the SAME Fundamentals fields yfinance fills. Keep the
    contract identical and the screener/DCF need no changes. Until then this
    raises, and the factory below will not select it unless explicitly enabled.
    """
    name = "fmp"
    BASE = "https://financialmodelingprep.com/api/v3"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def fetch(self, ticker: str) -> Optional[Fundamentals]:  # pragma: no cover
        raise NotImplementedError(
            "FMP provider not implemented yet. See the map above and "
            "buffett_bot/README.md → 'Upgrade path'.")


_FMP_CRED_PATH = os.path.expanduser("~/.fmp/credentials")


def _read_fmp_key() -> Optional[str]:
    """Read FMP_API_KEY=... from ~/.fmp/credentials (KEY=VALUE), or None."""
    try:
        with open(_FMP_CRED_PATH) as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("FMP_API_KEY") and "=" in line:
                    return line.split("=", 1)[1].strip()
    except FileNotFoundError:
        return None
    except Exception as e:  # noqa: BLE001
        log.warning("Could not read FMP creds (%s).", e)
    return None


def get_fundamentals_provider() -> FundamentalsProvider:
    """Select the fundamentals provider per config, always degrading to yfinance.

      "edgar"   -> SEC filings (default), with yfinance fallback per-ticker.
      "fmp"     -> chosen only if config asks AND creds exist AND it's
                   implemented, so the stub never half-activates.
      "yfinance"-> free scrape.
    """
    choice = config.PROVIDERS.get("fundamentals", "edgar")

    if choice == "edgar":
        log.info("Using EDGAR fundamentals provider (yfinance fallback).")
        return EdgarFundamentals(fallback=YFinanceFundamentals())

    if choice == "fmp":
        key = _read_fmp_key()
        if not key:
            log.info("FMP selected but ~/.fmp/credentials missing — using yfinance.")
        else:
            try:
                provider = FMPFundamentals(key)
                provider.fetch("AAPL")  # smoke-test; stub raises NotImplementedError
                log.info("Using FMP fundamentals provider.")
                return provider
            except NotImplementedError:
                log.info("FMP provider not implemented — using yfinance.")
            except Exception as e:  # noqa: BLE001
                log.warning("FMP provider init failed (%s) — using yfinance.", e)

    return YFinanceFundamentals()


# ==========================================================================
# PRICE-DERIVED RATIOS
# ==========================================================================
def reconcile_shares_if_implausible(f: Fundamentals) -> bool:
    """Guard against a share count that's inconsistent with the current price.

    EDGAR's share count comes from the last 10-K and lags corporate actions —
    most importantly stock splits (Booking split ~24:1; EDGAR still reports the
    pre-split 33M while the SIP price is post-split, giving a P/E of 1.08 and a
    false BUY). It also misfires on odd structures (IBKR's small public float →
    P/E 914; a bad MCD tag → P/E 0). The SIP price is always split-current, so
    the share count must be too.

    Only fires when per-share metrics already look implausible — so it costs one
    yfinance call on a handful of names, not all 500 — and only overrides when
    the split-current count differs >2x (a genuine low-P/E value stock, where the
    counts agree, is left untouched). Returns True if it changed the record.
    """
    if f.shares_source != "edgar" or not f.shares_out or not f.price:
        return False
    implausible = (
        (f.pe is not None and (f.pe < 6 or f.pe > 80))
        or (f.fcf_yield is not None and f.fcf_yield > 0.25)
    )
    if not implausible:
        return False
    try:
        import yfinance as yf  # noqa: PLC0415
        cur = yf.Ticker(f.ticker).fast_info["shares"]
    except Exception as e:  # noqa: BLE001
        log.debug("[%s] split cross-check unavailable (%s)", f.ticker, e)
        return False
    if not cur or cur <= 0:
        return False
    ratio = cur / f.shares_out
    if 0.5 <= ratio <= 2.0:
        return False   # counts agree -> metrics are real, not a split artifact
    log.warning("[%s] EDGAR shares %.0f vs split-current %.0f (%.1fx) — likely "
                "split/structure; adopting current count.",
                f.ticker, f.shares_out, cur, ratio)
    f.shares_out = float(cur)
    f.shares_source = "yfinance-split"
    f.market_cap = f.pe = f.pb = f.peg = f.ev_ebit = f.fcf_yield = None
    finalize_valuation(f)
    return True


def finalize_valuation(f: Fundamentals) -> None:
    """Fill valuation ratios that need a price, in place, after the SIP price is
    attached. Only fills fields still None — so a provider that already supplied
    a ratio (yfinance) is never clobbered, while EDGAR's price-independent record
    gets P/E, P/B, PEG, market cap, EV/EBIT and FCF yield computed here.
    """
    px, sh = f.price, f.shares_out
    if not px or px <= 0 or not sh or sh <= 0:
        return

    if f.market_cap is None:
        f.market_cap = px * sh

    if f.pe is None and f.net_income and f.net_income > 0:
        eps = f.net_income / sh
        if eps > 0:
            f.pe = px / eps

    if f.pb is None and f.total_equity and f.total_equity > 0:
        book_ps = f.total_equity / sh
        if book_ps > 0:
            f.pb = px / book_ps

    if f.peg is None and f.pe and f.pe > 0 and f.earnings_growth and f.earnings_growth > 0:
        f.peg = f.pe / (f.earnings_growth * 100.0)

    if f.ev_ebit is None and f.ebit and f.ebit > 0 and f.market_cap:
        ev = f.market_cap + (f.total_debt or 0) - (f.total_cash or 0)
        f.ev_ebit = ev / f.ebit

    if f.fcf_yield is None and f.free_cash_flow is not None and f.market_cap:
        f.fcf_yield = f.free_cash_flow / f.market_cap
