<!--
Session snapshot: current state, key changes, and next steps as of 2025-09-11.
Use these snapshots to resume work quickly and track architectural intent.
-->

## Snapshot (2025-09-11)

### What’s done
- Backend
  - FastAPI app wiring: routers mounted (prices, news, features, decide, simulate, equity, events).
  - SSE fixes: trades emitted synchronously; decide path awaits event publish.
  - Scheduler scaffold added; startup guarded by `ENABLE_SCHEDULER` (default off).
  - Price ingestion: DB-first, Alpaca-based historical ingest; idempotent upsert scripts.
  - Indicators: daily and intraday features + backfill script.
  - Models: prices/news/llm registered; DB auto-creates on startup.
- News pipeline (initial)
  - Providers scaffolded (Local cache, GDELT, EDGAR) with time-gated fetch APIs.
  - CSV cache with dedupe + provider state under `data/news/.state`.
  - API endpoints: mock, ingest per-day, get per-day, simple summaries (with SSE).
- Env & Ops
  - `.cursorrules`: headers rule + env policy (all vars in `configs/env/.env`).
  - `.env` grouped: API Keys, Provider/User-Agents, Scheduler/Live Jobs, App Config; scheduler disabled by default.
  - Multi-account git setup: SSH aliases for company/personal; repo points to personal (`sinmeraji`).
  - How-to doc: `docs/howto/multi_account_git.md`.

### Current repo state
- DB: SQLite at `backend/app/app.db`.
- Live browsing: `sqlite-web` available at 127.0.0.1:8081 when started.
- Server: `scripts/run_backend.sh` sources `.env` before uvicorn.

### Next steps (prioritized)
1) News ingestion to DB (not just CSV): persist into `NewsRaw`, compute `NewsMetric` rollups (1d/7d/30d/90d) per type.
2) Historical news backfill (2y) via GDELT/EDGAR; idempotent increments + provider state.
3) Live news ingest job (APScheduler) every X minutes; update metrics incrementally.
4) Decision context service: compact, token-budgeted context from DB (prices + indicators + news metrics + portfolio).
5) `/decide/llm`: wire LLM JSON-mode proposals, persist `LLMCall` and `Decision`, emit SSE for accepted/rejected.
6) Monitoring endpoints + UI panels: features, metrics, decisions, LLM costs.
7) README updates for new endpoints & scheduler envs; ensure `.env.example` reflects grouped layout.

### Notes
- Ensure all new jobs/services source `configs/env/.env`; no hardcoded secrets.
- Maintain idempotency in all ingestion paths (use unique constraints + upserts/try-commit/rollback).


