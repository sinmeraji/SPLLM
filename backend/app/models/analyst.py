"""
Model: analyst events and metrics.
- AnalystEvent: atomic records of upgrades/downgrades, price-target changes, estimate changes.
- AnalystMetric: rollups per ticker/date/window with counts and average deltas.
Usage: populated by services/analyst.py and read by context assembly for LLM.
"""
from __future__ import annotations

from datetime import datetime
from sqlalchemy import String, Integer, Float, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from .base import Base


class AnalystEvent(Base):
    __tablename__ = "analyst_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=False), index=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    # type: upgrade|downgrade|pt_raise|pt_cut|est_raise|est_cut
    type: Mapped[str] = mapped_column(String(32), index=True)
    firm: Mapped[str] = mapped_column(String(128), default="")
    from_rating: Mapped[str] = mapped_column(String(64), default="")
    to_rating: Mapped[str] = mapped_column(String(64), default="")
    old_pt: Mapped[float] = mapped_column(Float, default=0.0)
    new_pt: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(64), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now(), onupdate=func.now(), nullable=False)


class AnalystMetric(Base):
    __tablename__ = "analyst_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=False), index=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    window: Mapped[str] = mapped_column(String(8), index=True)  # 1d|7d|30d
    up_count: Mapped[int] = mapped_column(Integer, default=0)
    down_count: Mapped[int] = mapped_column(Integer, default=0)
    pt_delta_avg_pct: Mapped[float] = mapped_column(Float, default=0.0)
    est_delta_avg_pct: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now(), onupdate=func.now(), nullable=False)


