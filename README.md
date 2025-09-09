# Spllm

A cross-platform desktop simulator for LLM-guided trading in tech-heavy stocks (NASDAQ-100 + tech-adjacent) with two daily decision windows and continuous intraday risk controls.

## Status
Scaffolded project structure and frozen configuration; implementation to follow.

## Structure
- `backend/` - Python services (data ingestion, simulator, APIs)
- `ui/tauri/` - Tauri + React desktop UI
- `configs/` - Simulation config (`sim_config.yaml`), schemas, env templates
- `docs/decisions/` - Frozen brainstorm context and decisions
- `data/` - Local cache (prices, news, filings)
- `logs/` - Orders, portfolio snapshots, metrics
- `scripts/` - Helpers for setup and runs

## Keys & Config
1. Copy `.env.example` to `.env` and fill:
   - `OPENAI_API_KEY`
   - `ALPACA_KEY_ID`, `ALPACA_SECRET_KEY`
   - `SEC_CONTACT_EMAIL`
2. The simulation uses `configs/sim_config.yaml`. Adjust only if we agree to change.

## Agreed Simulation Window
- 2025-01-02 → 2025-02-03 ET (RTH only)

## Notes
- Intraday stops/targets trigger continuously using 1-minute bars (5-minute fallback).
- Fills: minute bar midpoint with 2 bps slippage and $10 commission; fractional shares allowed; min order $1,000 (not for forced exits).

