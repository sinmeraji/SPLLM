from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class RunWindowConfig(BaseModel):
    start_et: str
    end_et: str
    rth_only: bool = True


class UniverseConfig(BaseModel):
    include_etfs: list[str] = Field(default_factory=list)
    index: str = "NASDAQ-100"
    include_tech_adjacent: bool = True


class RiskConfig(BaseModel):
    long_only: bool = True
    max_positions: int = 15
    max_position_pct: float = 0.10
    min_cash_pct: float = 0.05
    stop_loss_pct: float = 0.08
    take_profit_pct: float = 0.12


class CadenceConfig(BaseModel):
    decision_windows_et: list[str] = Field(default_factory=lambda: ["10:00", "15:30"])
    allow_event_window: bool = True
    max_event_windows_per_day: int = 1


class ExecutionConfig(BaseModel):
    continuous_triggers: bool = True
    fill_rule: str = "minute_bar_midpoint"
    slippage_bps: int = 2
    commission_usd: float = 10.0
    allow_fractional: bool = True
    min_order_usd: float = 1000.0
    enforce_min_on_exits: bool = False


class LimitsConfig(BaseModel):
    max_turnover_daily_pct: float = 0.30
    max_orders_per_day: int = 10
    cooldown_minutes_after_exit: int = 60


class LLMConfig(BaseModel):
    provider: str = "openai"
    daily_cap_usd: float = 10.0
    monthly_cap_usd: float = 300.0
    expected_return_gate_pct: float = 0.05
    event_runs_per_day_max: int = 3
    event_run_max_tickers: int = 5
    window_top_k_tickers: int = 10


class PricesConfig(BaseModel):
    primary_intraday: str = "alpaca"
    fallback_bar: str = "5min"
    primary_daily: str = "yahoo"


class NewsConfig(BaseModel):
    sources: list[str] = Field(default_factory=lambda: ["gdelt", "edgar"])
    time_gated: bool = True
    language: list[str] = Field(default_factory=lambda: ["en"])


class Settings(BaseModel):
    run_window: RunWindowConfig
    universe: UniverseConfig
    risk: RiskConfig
    cadence: CadenceConfig
    execution: ExecutionConfig
    limits: LimitsConfig
    llm: LLMConfig
    prices: PricesConfig
    news: NewsConfig
    initial_cash_usd: float = 100000.0


def load_settings() -> Settings:
    config_path = os.getenv("SIM_CONFIG", str(Path("configs/sim_config.yaml").resolve()))
    with open(config_path, "r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f)
    return Settings(**raw)


settings = load_settings()
