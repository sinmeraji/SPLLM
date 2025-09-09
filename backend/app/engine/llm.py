from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List
import os


@dataclass
class Proposal:
    ticker: str
    action: str  # BUY or SELL
    quantity: float
    max_price: float | None = None
    min_price: float | None = None
    thesis: str | None = None
    horizon_days: int | None = None
    stop: float | None = None
    take_profit: float | None = None
    confidence: float | None = None


def propose_trades(context: Dict[str, Any]) -> List[Proposal]:
    """
    LLM stub: if OPENAI_API_KEY is present, this will later call the model.
    For now, returns an empty list to avoid trades without keys.
    """
    if not os.getenv("OPENAI_API_KEY"):
        return []
    # TODO: implement OpenAI call with prompts and schema validation
    return []
