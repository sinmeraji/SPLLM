from __future__ import annotations

from datetime import datetime, date
from sqlalchemy import String, Float, Integer, DateTime, Date, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class NewsRaw(Base):
    __tablename__ = "news_raw"
    __table_args__ = (
        UniqueConstraint("ticker", "ts", "url", name="uq_news_raw"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=False), index=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    type: Mapped[str] = mapped_column(String(16))  # breaking|analyst|macro|social|filings|other
    title: Mapped[str] = mapped_column(String(512))
    url: Mapped[str] = mapped_column(String(512))
    source: Mapped[str] = mapped_column(String(64))
    sentiment: Mapped[float] = mapped_column(Float, default=0.0)


class NewsMetric(Base):
    __tablename__ = "news_metrics"

    date: Mapped[date] = mapped_column(Date, primary_key=True, index=True)
    ticker: Mapped[str] = mapped_column(String(16), primary_key=True)
    type: Mapped[str] = mapped_column(String(16), primary_key=True)
    window: Mapped[str] = mapped_column(String(8), primary_key=True)  # 1d|7d|30d|90d

    count: Mapped[int] = mapped_column(Integer, default=0)
    novelty: Mapped[float] = mapped_column(Float, default=0.0)
    reliability: Mapped[float] = mapped_column(Float, default=0.0)
    sentiment_avg: Mapped[float] = mapped_column(Float, default=0.0)


