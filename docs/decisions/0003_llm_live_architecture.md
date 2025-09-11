# Decision 0003: Live LLM Decision Architecture (Cost-Aware)

Date: 2025-09-11

## Context
We are moving from backtesting/simulation to a live, cost-aware LLM-driven decision system. The goal is to minimize token usage by computing and storing signals locally and sending compact snapshots to the LLM a few times per day.

## Decisions
- Data will be cached locally and updated incrementally throughout the day.
- Compute price indicators and news metrics locally; only aggregate, compact context is sent to the LLM.
- Maintain strict token and cost budgets per window/day with graceful degradation.
- Use scheduler for periodic updates and decision windows.

## Architecture
- Data stores
  - Prices: minute/daily OHLCV cached locally; rolling 2-year history per ticker
  - News: CSV cache with sources (breaking, analyst, macro, social) and sentiment (optional)
  - Derived: price indicators (returns, vol, momentum, RSI, etc.), news metrics (count, novelty, reliability, sentiment)
- DB
  - Start with SQLite; plan to migrate to Postgres/TimescaleDB for production time-series scale
- LLM
  - JSON-mode with schema validation (`configs/schemas/decision.schema.json`)
  - Request hashing and dedupe; log all calls and costs
- Scheduling
  - Live loop every X minutes for ingestion + metrics updates
  - Decision windows (e.g., 10:00, 15:30 ET) build compact context and call LLM

## Endpoints (current and planned)
- Current
  - `POST /decide/llm` — builds context and calls LLM (scaffold)
  - `POST /news/ingest/{date}` — ingest news (local/gdelt/edgar) with dedupe
  - `GET /news/{date}` — time-gated news
  - `GET /events` — SSE stream (trade/decision/news)
- Planned
  - `GET /features/{ticker}/{date}` — price indicators (debug)
  - `GET /context/{date}` — compact context preview
  - `GET /decisions/{date}` — decisions and costs

## Cost Controls
- Rank tickers by salience (momentum + news novelty/sentiment); send top-N
- Enforce token caps; reduce per-ticker detail or N as needed
- Cache per-ticker summaries; send deltas after first daily call

## Risks
- API limits for news providers; mitigate with caching and user-agents
- Token drift from LLM; mitigate with estimator and tight response schema
- State drift in SQLite; mitigate by moving to Postgres/TimescaleDB

## Next Steps
1) Add DB tables for prices/news/indicators/metrics/decisions/llm_calls
2) Implement incremental price/news ingestion into DB
3) Compute indicators and news metrics on schedule
4) Extend compact context builder to read from DB with token budget
5) Add decision scheduler with daily/monthly cost caps
