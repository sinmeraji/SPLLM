# Decision 0004: News Ingestion Plan (Sources, Modes, Cadence)

Date: 2025-09-11

## Goal
Maximize coverage of market-moving news while controlling costs. Support both one-time historical backfill and live ingestion every X minutes. Classify news into types for downstream metrics and LLM context.

## Sources (free-first, paid-optional)
- Free
  - GDELT Doc API — general/breaking news
  - SEC EDGAR Atom feeds — filings
  - Yahoo Finance RSS per ticker — headlines
  - Google News RSS queries per ticker and macro topics — headlines
- Optional paid (future)
  - Polygon.io, Finnhub, Alpha Vantage — analyst notes and sentiment
  - Stocktwits/Reddit APIs — social sentiment

## Types and mapping
- breaking: GDELT, Yahoo/Google RSS, press releases
- analyst: Yahoo/Google RSS filtered for upgrades/downgrades; paid APIs when enabled
- macro: Google News queries for CPI/FOMC/jobs, curated sources
- social: Stocktwits/Reddit (optional)
- filings: EDGAR

## Ingestion modes
- A) Historical backfill
  - Endpoint: `POST /news/backfill { start, end, tickers, sources }`
  - Idempotent upserts with dedupe (url+ts+ticker)
  - Priority: EDGAR+GDELT (good history), then Yahoo/Google RSS (limited)
- B) Live ingest
  - Scheduler cadence (configurable):
    - breaking: 5m
    - analyst: 15–30m
    - filings: 15m
    - macro: 60m
    - social: 5–10m (if enabled)

## Storage
- Raw: `news_raw` table with (ts, ticker, type, title, url, source, sentiment?)
- Metrics: `news_metrics` with aggregates per type and windows (1d/7d/30d/90d)

## Risks & Mitigations
- API limits → user-agents, staggered schedules, caching
- Duplicates → hashing keys; provider-specific dedupe
- Incomplete history → multiple sources, best-effort backfill

## Next Actions
1) Add DB models for `news_raw` and `news_metrics`
2) Implement providers: GDELT, EDGAR, Yahoo/Google RSS with type tagging
3) Add `/news/backfill` and live scheduler jobs
4) Compute metrics windows and expose via API
