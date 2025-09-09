from __future__ import annotations

from pydantic import BaseModel
from typing import List


class PositionOut(BaseModel):
    ticker: str
    quantity: float
    avg_cost: float


class PortfolioOut(BaseModel):
    cash: float
    positions: List[PositionOut]
