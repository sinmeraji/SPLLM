<!--
Session snapshot: state as of 2025-09-12. Use to quickly resume work.
-->

## What’s in place

- Data & DB
  - Prices: DB-first ingestion (Alpaca), indicators (daily/intraday), admin scripts: reset_db.py, truncate_table.py.
  - News: providers (GDELT, EDGAR Atom, EDGAR Submissions JSON), CSV cache helpers, DB upsert with VADER sentiment; metrics (count, sentiment_avg, novelty, reliability via trust map `configs/news_sources.yaml`).
- LLM decisions
  - Prompted agent (`prompts/system.txt`, `prompts/decision.txt`).
  - `/decide/llm`: builds full context (portfolio, prices, news metrics/briefs, policy), stores `LLMCall` + `Decision` (with price snapshot), emits `decision_recommendations` SSE. No auto-exec.
  - Endpoints: list/get decisions, execute selected proposals.
- UI
  - `static/index.html`: Decide (LLM) calls `/decide/llm`, renders proposals, Execute Selected posts `/decisions/{id}/execute`.
- Scheduler
  - Interval envs: `PRICE_UPDATE_MINUTES`, `NEWS_UPDATE_MINUTES`, optional `LLM_UPDATE_MINUTES`; EOD LLM at 16:15 ET if `LLM_EOD=1`.
  - Runs minute price job (or cron via `SCHED_MINUTE_CRON`) + news job.
- Ops
  - Start/Stop: `scripts/run_backend.sh` (stop+start uvicorn + sqlite-web; prints API/UI/DB URLs), `scripts/stop_backend.sh`, `scripts/restart_backend.sh`.
  - Env controls: `RESET_BALANCE_ON_START`, `ORIGINAL_BALANCE_USD`.
  - SIM config now optional; sensible defaults from code if file absent.

## Quick test

1) Start: `./scripts/run_backend.sh` → API http://127.0.0.1:8000/ UI http://127.0.0.1:8000/app/ DB http://127.0.0.1:8081/
2) Decide: UI → Decide (LLM) → review/execute. Or API:
   - `POST /decide/llm {"tickers":["AAPL"],"date":"2025-08-15"}`
   - `GET /decisions`, `GET /decisions/{id}`
   - `POST /decisions/{id}/execute {"selection":[0,1]}`

## Next

- Add token/cost tracking to `LLMCall` from OpenAI response.
- Source trust refinements; corroboration by domain set.
- Monitoring panels (decisions, LLM costs).

