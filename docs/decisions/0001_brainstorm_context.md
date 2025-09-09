## Brainstorm context (frozen)

- Universe: NASDAQ-100 incl. tech-adjacent + ETFs QQQ, SPY, XLK
- Risk: long-only; ≤15 positions; ≤10% per ticker; ≥5% cash; stop −8%; take-profit +12%
- Cadence: decision windows 10:00 & 15:30 ET; up to 1 extra event window/day; no-trade allowed
- Execution: continuous intraday stops/targets; fill = minute bar midpoint + 2 bps slippage; $10 commission; fractional shares; min order $1,000 (not enforced for exits)
- Limits: ≤30% daily turnover; ≤10 orders/day; 1h cooldown after exits
- LLM: OpenAI; cap $10/day, $300/month; expected-return gate ≥5% for new buys; event-triggered runs ≤3/day (≤5 tickers); window top-k 10
- Data: Prices—Alpaca (1m, fallback 5m), Yahoo (daily); News—GDELT + EDGAR; time-gated; English
- Backtest Window: 2025-01-02 → 2025-02-03 ET; RTH only
- Goal: prioritize profitability; benchmark vs QQQ with lower drawdown; 10% monthly stretch

This file mirrors `/configs/sim_config.yaml` and should be updated only through agreed changes.
