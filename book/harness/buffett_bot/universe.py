"""
Stock universe for the Buffett Bot.

Default universe is the S&P 500 (large, established, financially-disclosed
companies — the pond Buffett actually fishes in). Pulled live from Wikipedia
with pandas; falls back to a small embedded blue-chip list if that request
fails (offline / rate-limited), so the bot always has something to run.
"""
from __future__ import annotations

import logging
from io import StringIO

import pandas as pd
import requests

log = logging.getLogger("buffett_bot.universe")

_WIKI_SP500 = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

# Fallback: a curated set of durable large-caps so the bot is never empty.
_FALLBACK = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "BRK-B", "JNJ", "PG", "KO", "PEP",
    "WMT", "COST", "HD", "MCD", "V", "MA", "UNH", "JPM", "AXP", "MMM",
    "CAT", "HON", "TXN", "ADP", "LMT", "NKE", "SBUX", "LOW", "TGT", "CL",
    "KMB", "GIS", "MDT", "ABT", "MRK", "PFE", "CVX", "XOM", "ORCL", "CSCO",
]


def get_universe(source: str = "sp500") -> list[str]:
    """Return a list of tickers to screen.

    source="sp500" pulls the live S&P 500 constituents; anything else (or a
    fetch failure) returns the embedded fallback list.
    """
    if source != "sp500":
        return list(_FALLBACK)
    try:
        # Fetch via requests (which bundles certifi) rather than letting
        # read_html call urlopen — the stdlib path has no CA bundle on macOS
        # Python.framework installs and dies with CERTIFICATE_VERIFY_FAILED.
        resp = requests.get(_WIKI_SP500, timeout=30,
                            headers={"User-Agent": "Mozilla/5.0 (buffett_bot)"})
        resp.raise_for_status()
        tables = pd.read_html(StringIO(resp.text))
        df = tables[0]
        tickers = (
            df["Symbol"].astype(str).str.replace(".", "-", regex=False).tolist()
        )
        tickers = [t.strip().upper() for t in tickers if t and t != "nan"]
        if len(tickers) < 100:  # sanity check — page layout may have changed
            raise ValueError(f"only parsed {len(tickers)} tickers")
        log.info("Loaded %d S&P 500 tickers", len(tickers))
        return tickers
    except Exception as e:  # noqa: BLE001 — degrade gracefully, never crash
        log.warning("S&P 500 fetch failed (%s); using %d-name fallback",
                    e, len(_FALLBACK))
        return list(_FALLBACK)
