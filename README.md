# Spllm

A live LLM-guided trading backend with local caching and compact, cost-aware prompts.

## Status
Live-mode scaffold implemented: SSE, mock/LLM decide endpoint, news ingest (local/GDELT/EDGAR), and context builder.

## Structure
- `backend/` - FastAPI services (prices/news ingest, indicators, decisions)
- `ui/tauri/` - Desktop UI
- `configs/` - Config (`sim_config.yaml`), schemas, env templates
- `docs/decisions/` - Decisions and design docs
- `data/` - Local cache (prices, news, filings)
- `logs/` - Events and metrics
- `scripts/` - Run helpers

## Keys & Config
1. Create `.env` with:
   - `OPENAI_API_KEY`
   - `SEC_USER_AGENT` (e.g., `me@example.com`) and optional `GDELT_USER_AGENT`
2. Runtime config: `configs/sim_config.yaml`

## Run
```
bash scripts/restart_backend.sh
open http://127.0.0.1:8000/app
```

## Important endpoints
- Health: `GET /health`
- SSE: `GET /events`
- Portfolio: `GET /portfolio`
- Orders: `POST /orders/market`
- Decide (mock): `POST /decide`
- Decide (LLM): `POST /decide/llm`
- News ingest: `POST /news/ingest/{YYYY-MM-DD}?tickers=AAPL,MSFT&provider=gdelt|edgar|local`
- News: `GET /news/{YYYY-MM-DD}`

## Live LLM architecture (high level)
- Cache prices/news locally; compute indicators and news metrics daily and intraday.
- Build compact, token-budgeted context and call OpenAI in JSON mode.
- Enforce daily/monthly cost caps; dedupe by request-hash; log costs and decisions.

See `docs/decisions/0003_llm_live_architecture.md` for details and next steps.

