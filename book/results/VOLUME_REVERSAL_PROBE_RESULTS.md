# Red-to-Green Reversal — Step-1 PRICE-LEG Probe Results
_Generated 2026-06-26T14:24:36-04:00_
## What was tested
- **PRICE leg only.** Entry: 2+ consecutive red 1-min bars -> green close -> enter next bar open. Exit: 4.0% trailing stop OR force-flat at 16:00 ET.
- **NOT tested:** the buy-vol >= 1.5x sell-vol entry gate and the sell-vol >= 1.5x buy-vol exit. Minute bars have no buy/sell split; that needs tick classification (the expensive Step 2).
- Regular session only (09:30-16:00 ET). Flat at close. No overlapping positions.
- Universe: AAPL, MSFT, NVDA, AMD, TSLA, AMZN, META, GOOGL, SPY, QQQ, NFLX, AVGO, CRM, INTC, MU, COIN, SMH, XLF, BAC, JPM
- Window: 2024-06-26 -> 2026-06-26  (~730 calendar days)
- Data feed: sip

## Slippage stress (per side, bps)

### Slippage 2 bps/side
```
  trades=11170  trade-days=502
  total_return=+13.6%  CAGR=+6.6%
  MAR=0.48  Sortino=0.74  maxDD=13.7%
  win_rate=49.0%  profit_factor=0.93
  avg_win=+1.27%  avg_loss=-1.31%
  exits: trail=1177 eod=9993  avg_hold=341min
```

### Slippage 4 bps/side
```
  trades=11170  trade-days=502
  total_return=-7.1%  CAGR=-3.6%
  MAR=-0.18  Sortino=-0.23  maxDD=19.5%
  win_rate=47.6%  profit_factor=0.88
  avg_win=+1.27%  avg_loss=-1.31%
  exits: trail=1177 eod=9993  avg_hold=341min
```

### Slippage 6 bps/side
```
  trades=11170  trade-days=502
  total_return=-24.0%  CAGR=-12.8%
  MAR=-0.40  Sortino=-1.15  maxDD=32.2%
  win_rate=46.3%  profit_factor=0.83
  avg_win=+1.26%  avg_loss=-1.32%
  exits: trail=1177 eod=9993  avg_hold=341min
```

## Fat-tail check (base slippage, top trades stripped)
```
strip top 0:
  trades=11170  trade-days=502
  total_return=+13.6%  CAGR=+6.6%
  MAR=0.48  Sortino=0.74  maxDD=13.7%
  win_rate=49.0%  profit_factor=0.93
  avg_win=+1.27%  avg_loss=-1.31%
  exits: trail=1177 eod=9993  avg_hold=341min

strip top 1:
  trades=11169  trade-days=502
  total_return=+13.1%  CAGR=+6.4%
  MAR=0.46  Sortino=0.72  maxDD=13.7%
  win_rate=49.0%  profit_factor=0.93
  avg_win=+1.27%  avg_loss=-1.31%
  exits: trail=1177 eod=9992  avg_hold=341min

strip top 3:
  trades=11167  trade-days=502
  total_return=+11.8%  CAGR=+5.7%
  MAR=0.42  Sortino=0.66  maxDD=13.7%
  win_rate=49.0%  profit_factor=0.93
  avg_win=+1.26%  avg_loss=-1.31%
  exits: trail=1177 eod=9990  avg_hold=341min

strip top 5:
  trades=11165  trade-days=502
  total_return=+11.1%  CAGR=+5.4%
  MAR=0.39  Sortino=0.63  maxDD=13.7%
  win_rate=49.0%  profit_factor=0.92
  avg_win=+1.26%  avg_loss=-1.31%
  exits: trail=1177 eod=9988  avg_hold=341min

strip top 10:
  trades=11160  trade-days=502
  total_return=+9.5%  CAGR=+4.7%
  MAR=0.34  Sortino=0.55  maxDD=13.7%
  win_rate=49.0%  profit_factor=0.91
  avg_win=+1.25%  avg_loss=-1.31%
  exits: trail=1175 eod=9985  avg_hold=341min

```

## How to read this
- These are **price-pattern** numbers, an optimistic ceiling — the real strategy adds two volume gates that can only cut trades, plus more cost.
- **Decision rule:** if the edge already fails to clear MAR ~0.5 / Sortino ~1.0 here, or it collapses at 2x slippage, or it goes negative when the top 5 trades are stripped, **stop** — don't build the tick-classification step. The volume gate is unlikely to rescue a price pattern that's already a coin flip.
- If it shows a real, robust signal, THEN the buy/sell tick classification (Step 2 in the framework) is worth the effort.
- Reminder (repo rule): near-zero trades = broken gate, not a result.
