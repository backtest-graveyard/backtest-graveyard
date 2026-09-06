"""Phase 0 feasibility: measure REAL intraday spreads across the PCA universe from SIP.

Answers two things at once, for free (data already subscribed):
  1. Passive thesis gate: is there enough spread to *collect* by providing liquidity?
     (If median spread < ~1.5 bps, there's no toll worth collecting -> shelve passive idea.)
  2. Taker re-check: our backtest used a conservative 2 bps spread FLOOR; measured spreads
     let us see whether the taker cost model was too pessimistic.
"""

from __future__ import annotations
import time
import numpy as np
import pandas as pd
import requests

from .data import _load_credentials
from .pca_book import UNIVERSE

QUOTES_URL = "https://data.alpaca.markets/v2/stocks/quotes"
# three ~5s windows across a known regular-hours trading day (2026-07-17, EDT=UTC-4)
WINDOWS = [("2026-07-17T14:00:00Z", "2026-07-17T14:00:05Z"),   # 10:00 ET
           ("2026-07-17T16:30:00Z", "2026-07-17T16:30:05Z"),   # 12:30 ET
           ("2026-07-17T19:00:00Z", "2026-07-17T19:00:05Z")]   # 15:00 ET


def fetch_spreads() -> pd.DataFrame:
    k, s = _load_credentials("VTI_KEY", "VTI_SECRET")   # subscribed account
    h = {"APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": s}
    per_sym: dict[str, list[float]] = {s: [] for s in UNIVERSE}
    for start, end in WINDOWS:
        token = None
        for _ in range(4):
            params = {"symbols": ",".join(UNIVERSE), "start": start, "end": end,
                      "feed": "sip", "limit": 10000}
            if token:
                params["page_token"] = token
            r = requests.get(QUOTES_URL, headers=h, params=params, timeout=60)
            r.raise_for_status()
            j = r.json()
            for sym, qs in (j.get("quotes") or {}).items():
                for q in qs:
                    bp, ap = q.get("bp"), q.get("ap")
                    if bp and ap and ap > bp > 0:
                        per_sym[sym].append((ap - bp) / ((ap + bp) / 2) * 1e4)
            token = j.get("next_page_token")
            if not token:
                break
        time.sleep(0.2)
    rows = [{"symbol": s, "spread_bps": float(np.median(v)), "n": len(v)}
            for s, v in per_sym.items() if v]
    return pd.DataFrame(rows).set_index("symbol").sort_values("spread_bps")


if __name__ == "__main__":
    df = fetch_spreads()
    sp = df["spread_bps"]
    print(f"measured SIP spreads for {len(df)}/{len(UNIVERSE)} names "
          f"(3 intraday samples, 2026-07-17)\n")
    print("distribution (bps):")
    for q in (0.10, 0.25, 0.50, 0.75, 0.90):
        print(f"  {int(q*100):>2d}th pct: {sp.quantile(q):5.2f}")
    print(f"  median : {sp.median():5.2f}   mean: {sp.mean():5.2f}   max: {sp.max():5.2f}")
    print(f"\ntightest 5: {sp.head(5).round(2).to_dict()}")
    print(f"widest  5: {sp.tail(5).round(2).to_dict()}")
    print(f"\nnames with spread < 1.5 bps (nothing to collect passively): "
          f"{(sp < 1.5).sum()}/{len(sp)}")
    print(f"names with spread >= 3 bps (real toll to collect):          "
          f"{(sp >= 3).sum()}/{len(sp)}")
    print(f"\nvs the 2.0 bps FLOOR used in the backtest: measured median is "
          f"{'BELOW' if sp.median() < 2 else 'ABOVE'} it "
          f"({sp.median():.2f} vs 2.00).")
