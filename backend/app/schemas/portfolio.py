from __future__ import annotations
"""
Schemas: portfolio API responses.
- PositionOut: minimal position view
- PortfolioOut: cash + minimal positions
- PositionDetailOut/PortfolioSummaryOut: enriched view for UI (price, value, weights, PnL, equity)
"""

from pydantic import BaseModel
from typing import List, Optional


class PositionOut(BaseModel):
    ticker: str
    quantity: float
    avg_cost: float


class PortfolioOut(BaseModel):
    cash: float
    positions: List[PositionOut]


class PositionDetailOut(BaseModel):
    ticker: str
    quantity: float
    avg_cost: float
    price: Optional[float] = None
    value: float
    weight_pct: float
    pnl: float
    pnl_pct: float


class PortfolioSummaryOut(BaseModel):
    cash: float
    equity: float
    positions_count: int
    positions: List[PositionDetailOut]
