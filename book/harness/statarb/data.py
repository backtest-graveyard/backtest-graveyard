"""Data layer for the stat-arb bot — point-in-time-safe daily price panels.

Self-contained on purpose: reads ~/.alpaca/credentials directly and hits the Alpaca
v2 data REST API with `requests`, so it does NOT import the archived gap-trader's
`config`/`live_safety` (which fail-fast at import and pull in unrelated state).

DATA-SOURCE ARCHITECTURE (revised 2026-07-18, on evidence):
* Daily prices + ADV  -> yfinance (CONSOLIDATED volume + dividend-adjusted closes).
  IEX daily volume is venue-local (~2-3% of tape) and understates true ADV by 30-150x
  with a per-name-varying ratio, so it CANNOT feed the ADV filter. Measured directly.
* Spread (the #1 cost lever) -> a conservative per-name assumption with a non-zero floor
  for research. IEX quotes are unusable (stale/crossed: SPY snapshotted at 601 bps),
  and Corwin-Schultz collapses to 0 on liquid names. Precise spreads come from SIP quotes
  sampled INTRADAY at the pre-funding calibration step (paid, one month), not here.
* The Alpaca fetcher below is retained for that later SIP/intraday work, not for the
  daily research panel.

Nothing here places orders or needs a trading account; market-data endpoints use the same
API key/secret.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import os
import time

import numpy as np
import pandas as pd
import requests

from .costs import corwin_schultz_spread_bps

ALPACA_DATA_URL = "https://data.alpaca.markets/v2/stocks/bars"
_CRED_PATH = os.path.expanduser("~/.alpaca/credentials")


# ── credentials ───────────────────────────────────────────────────────────────

def _load_credentials(key_name: str = "ALPACA_KEY", secret_name: str = "ALPACA_SECRET") -> tuple[str, str]:
    """Read KEY=VALUE lines from ~/.alpaca/credentials. Returns (key, secret).
    Raises if the file or the named entries are missing — fail fast, never guess."""
    if not os.path.exists(_CRED_PATH):
        raise FileNotFoundError(f"missing {_CRED_PATH}")
    creds: dict[str, str] = {}
    with open(_CRED_PATH) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            creds[k.strip()] = v.strip()
    try:
        return creds[key_name], creds[secret_name]
    except KeyError as e:
        raise KeyError(f"{e} not found in {_CRED_PATH}") from None


# ── raw fetchers ───────────────────────────────────────────────────────────────

def fetch_alpaca_daily(
    symbols: list[str],
    start: str,
    end: str,
    feed: str = "iex",
    adjustment: str = "all",
    key_name: str = "ALPACA_KEY",
    secret_name: str = "ALPACA_SECRET",
    page_limit: int = 10_000,
) -> dict[str, pd.DataFrame]:
    """Fetch daily OHLCV bars from Alpaca v2 for `symbols` in [start, end] (YYYY-MM-DD).

    Handles multi-symbol batching and `next_page_token` pagination. Returns
    {symbol: DataFrame[open, high, low, close, volume]} indexed by tz-naive date.
    `adjustment='all'` gives split+dividend adjusted prices (total-return proxy),
    which is what cointegration/PCA want.
    """
    key, secret = _load_credentials(key_name, secret_name)
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    out: dict[str, list[dict]] = {s: [] for s in symbols}

    page_token: str | None = None
    while True:
        params = {
            "symbols": ",".join(symbols),
            "timeframe": "1Day",
            "start": start,
            "end": end,
            "adjustment": adjustment,
            "feed": feed,
            "limit": page_limit,
        }
        if page_token:
            params["page_token"] = page_token
        # 60s timeout + retry: large multi-symbol ranges can be slow (repo note:
        # short timeouts silently return empty on big ranges).
        for attempt in range(3):
            try:
                r = requests.get(ALPACA_DATA_URL, headers=headers, params=params, timeout=60)
                r.raise_for_status()
                break
            except requests.RequestException:
                if attempt == 2:
                    raise
                time.sleep(1.5 * (attempt + 1))
        payload = r.json()
        for sym, bars in (payload.get("bars") or {}).items():
            out.setdefault(sym, []).extend(bars)
        page_token = payload.get("next_page_token")
        if not page_token:
            break

    frames: dict[str, pd.DataFrame] = {}
    for sym, bars in out.items():
        if not bars:
            continue
        df = pd.DataFrame(bars)
        df["date"] = pd.to_datetime(df["t"]).dt.tz_localize(None).dt.normalize()
        df = (
            df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
            .set_index("date")[["open", "high", "low", "close", "volume"]]
            .sort_index()
        )
        df = df[~df.index.duplicated(keep="last")]
        frames[sym] = df
    return frames


def fetch_yfinance_daily(symbols: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    """Fallback: dividend+split-adjusted daily OHLCV via yfinance. `close` is set to the
    adjusted close so it matches Alpaca `adjustment='all'` semantics."""
    import yfinance as yf

    raw = yf.download(
        symbols, start=start, end=end, auto_adjust=True, progress=False, group_by="ticker"
    )
    frames: dict[str, pd.DataFrame] = {}
    single = len(symbols) == 1
    for sym in symbols:
        try:
            sub = raw if single else raw[sym]
            df = sub[["Open", "High", "Low", "Close", "Volume"]].copy()
        except (KeyError, TypeError):
            continue
        df.columns = ["open", "high", "low", "close", "volume"]
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        df = df.dropna(how="all").sort_index()
        if not df.empty:
            frames[sym] = df
    return frames


# ── panel assembly ─────────────────────────────────────────────────────────────

@dataclass
class Panel:
    """Aligned, cleaned daily panel plus the per-name stats the cost model consumes.

    close/high/low/volume: DataFrames (index=date, columns=symbol), inner-aligned on
    dates common to all retained symbols. `stats` has one row per symbol:
    dollar_adv, sigma_daily_bps, spread_bps, n_obs.
    """

    close: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    volume: pd.DataFrame
    stats: pd.DataFrame
    source: str

    @property
    def symbols(self) -> list[str]:
        return list(self.close.columns)

    def log_returns(self) -> pd.DataFrame:
        return np.log(self.close / self.close.shift(1)).dropna(how="all")


def _per_name_stats(
    frames: dict[str, pd.DataFrame],
    adv_window: int = 21,
    vol_window: int = 63,
    spread_floor_bps: float = 2.0,
    spread_override: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Per-name cost-model inputs. Spread is deliberately conservative: measured
    Corwin-Schultz FLOORED at `spread_floor_bps` (CS collapses to ~0 on liquid names,
    which would price trades as free), or an explicit `spread_override[sym]` when we
    have a trustworthy (e.g. SIP-measured) value. Never returns spread < floor."""
    override = spread_override or {}
    rows = []
    for sym, df in frames.items():
        if df.empty:
            continue
        dollar_vol = (df["close"] * df["volume"]).tail(adv_window)
        rets = np.log(df["close"] / df["close"].shift(1)).dropna()
        sigma_bps = float(rets.tail(vol_window).std() * 10_000) if len(rets) else np.nan
        h, l = df["high"].values, df["low"].values
        cs = [corwin_schultz_spread_bps(h[i], l[i], h[i - 1], l[i - 1])
              for i in range(max(1, len(df) - adv_window), len(df))]
        cs_med = float(np.median(cs)) if cs else 0.0
        spread = override.get(sym, max(cs_med, spread_floor_bps))
        rows.append({
            "symbol": sym,
            "dollar_adv": float(dollar_vol.median()) if len(dollar_vol) else np.nan,
            "sigma_daily_bps": sigma_bps,
            "spread_bps": spread,
            "spread_measured": sym in override,  # False => conservative floor, calibrate later
            "n_obs": int(len(df)),
        })
    return pd.DataFrame(rows).set_index("symbol")


def load_panel(
    symbols: list[str],
    start: str | None = None,
    end: str | None = None,
    lookback_days: int = 4 * 365,
    source: str = "yfinance",
    min_obs: int = 252,
    max_missing_frac: float = 0.02,
    spread_floor_bps: float = 2.0,
    spread_override: dict[str, float] | None = None,
) -> Panel:
    """Load a clean, aligned daily panel for `symbols`.

    source: 'yfinance' (default — consolidated volume, required for a correct ADV
    filter), 'alpaca' (IEX; prices only, NOT for ADV), or 'auto' (yfinance then Alpaca).
    Drops symbols with < `min_obs` bars or > `max_missing_frac` gaps after alignment.
    `spread_override` supplies trustworthy (SIP-measured) spreads by symbol when available.
    """
    if end is None:
        end = date.today().isoformat()
    if start is None:
        start = (date.fromisoformat(end) - timedelta(days=lookback_days)).isoformat()

    frames: dict[str, pd.DataFrame] = {}
    used = source
    if source in ("yfinance", "auto"):
        frames = fetch_yfinance_daily(symbols, start, end)
        used = "yfinance"
    if not frames and source in ("alpaca", "auto"):
        frames = fetch_alpaca_daily(symbols, start, end)  # prices only; ADV understated
        used = "alpaca-iex"
    elif source == "alpaca":
        frames = fetch_alpaca_daily(symbols, start, end)
        used = "alpaca-iex"

    # Drop thin names before alignment so one short-history name doesn't truncate all.
    frames = {s: df for s, df in frames.items() if len(df) >= min_obs}
    if not frames:
        raise RuntimeError(f"no symbols with >= {min_obs} obs from source={source}")

    def field(name: str) -> pd.DataFrame:
        return pd.DataFrame({s: df[name] for s, df in frames.items()})

    close = field("close")
    # Inner-align on the shared trading calendar, then enforce the gap tolerance.
    close = close.dropna(how="all")
    keep = [c for c in close.columns if close[c].isna().mean() <= max_missing_frac]
    close = close[keep].dropna()
    frames = {s: frames[s].reindex(close.index) for s in keep}

    stats = _per_name_stats(
        {s: frames[s].dropna() for s in keep},
        spread_floor_bps=spread_floor_bps,
        spread_override=spread_override,
    )
    return Panel(
        close=close,
        high=field("high")[keep].reindex(close.index),
        low=field("low")[keep].reindex(close.index),
        volume=field("volume")[keep].reindex(close.index),
        stats=stats,
        source=used,
    )


if __name__ == "__main__":
    # Smoke test: pull a few structurally-linked ETFs and show the panel + cost inputs.
    syms = ["SPY", "IVV", "VOO", "GLD", "GDX", "GDXJ", "XLE", "USO"]
    print(f"loading {syms} ...")
    panel = load_panel(syms, lookback_days=3 * 365)
    print(f"\nsource={panel.source}  shape={panel.close.shape}  "
          f"dates {panel.close.index[0].date()} -> {panel.close.index[-1].date()}")
    print("\nper-name stats (cost-model inputs):")
    with pd.option_context("display.float_format", lambda v: f"{v:,.2f}"):
        print(panel.stats)
    print("\nlast 3 closes:")
    print(panel.close.tail(3).round(2))
