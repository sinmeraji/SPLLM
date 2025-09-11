from __future__ import annotations

from datetime import datetime
from sqlalchemy import String, Float, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class LLMCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=False), index=True)
    request_hash: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(String(64))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    request_json: Mapped[str] = mapped_column(String(4000))
    response_json: Mapped[str] = mapped_column(String(4000))


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=False), index=True)
    window: Mapped[str] = mapped_column(String(16))
    tickers_json: Mapped[str] = mapped_column(String(1000))
    proposals_json: Mapped[str] = mapped_column(String(4000))
    executed_json: Mapped[str] = mapped_column(String(4000))
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)


