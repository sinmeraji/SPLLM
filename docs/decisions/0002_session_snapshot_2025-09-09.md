## Session snapshot — 2025-09-09

- Window (historical backtest): 2025-01-02 → 2025-02-03 ET, RTH only
- Universe: NASDAQ-100 incl. tech-adjacent + ETFs QQQ, SPY, XLK
- Risk: long-only; ≤15 positions; ≤10% per ticker; ≥5% cash
- Stops/targets: −8% stop, +12% take‑profit; continuous intraday (1m, 5m fallback)
- Cadence: decision windows at 10:00 & 15:30 ET; up to 1 event window/day; no‑trade allowed
- Costs: 2 bps slippage; $10 commission/order; fractional shares; min order $1,000 (not for forced exits)
- LLM: OpenAI; expected‑return gate ≥5% for new buys; budget cap $10/day, $300/month; event runs ≤3/day (≤5 tickers); top‑k 10 per window
- Data: Prices—Alpaca 1m (5m fallback), Yahoo daily; News—GDELT + EDGAR; time‑gated, EN only
- Fill rule: minute bar midpoint, then apply slippage and commission
- Limits: ≤30% turnover/day; ≤10 orders/day; 1h cooldown after exits
- Initial cash: $100,000

Implementation status
- Backend skeleton (FastAPI), DB models, rules, simulate endpoint: DONE
- Prompts (system, decision, summarize): DONE
- Providers: local‑cache prices/news; placeholders for Alpaca/Yahoo/GDELT/EDGAR: DONE (stubs)
- LLM engine: stub (returns no trades without key): DONE (stub)
- Backtest runner scaffold with decision windows + logging: DONE (needs data/price refs)
- Scripts: run backend and backtest: DONE

Pending (next)
- Wire real price ingestion (Alpaca 1m/5m, Yahoo daily) with caching
- Wire news/filings ingestion (GDELT + EDGAR) with time‑gating
- Implement LLM call w/ schema validation; integrate prompts
- Compute reference prices at decision windows; implement continuous stops/targets on intraday bars
- Metrics logging (equity curve, drawdown) and minimal UI (Tauri)

Keys needed
- OPENAI_API_KEY, ALPACA_KEY_ID/ALPACA_SECRET_KEY, SEC_CONTACT_EMAIL

Resume tips
- Start API: ./scripts/run_backend.sh
- Run backtest scaffold: ./scripts/run_backtest.sh
