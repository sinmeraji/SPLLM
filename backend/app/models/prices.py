from __future__ import annotations

from datetime import datetime, date
from sqlalchemy import String, Float, Integer, DateTime, Date, Index
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class PriceBar(Base):
    __tablename__ = "price_bars"

    # timeframe: 'min' or 'day'
    ticker: Mapped[str] = mapped_column(String(16), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=False), primary_key=True, index=True)
    timeframe: Mapped[str] = mapped_column(String(8), primary_key=True)  # min|day

    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float, default=0.0)

    __table_args__ = (
        Index("ix_price_bars_ticker_ts", "ticker", "ts"),
    )


class PriceIndicator(Base):
    __tablename__ = "price_indicators"

    date: Mapped[date] = mapped_column(Date, primary_key=True, index=True)
    ticker: Mapped[str] = mapped_column(String(16), primary_key=True)

    r1d: Mapped[float] = mapped_column(Float, default=0.0)
    r5d: Mapped[float] = mapped_column(Float, default=0.0)
    r20d: Mapped[float] = mapped_column(Float, default=0.0)
    mom_60d: Mapped[float] = mapped_column(Float, default=0.0)
    vol_20d: Mapped[float] = mapped_column(Float, default=0.0)
    rsi_14: Mapped[float] = mapped_column(Float, default=0.0)
    macd: Mapped[float] = mapped_column(Float, default=0.0)
    v_zscore_20d: Mapped[float] = mapped_column(Float, default=0.0)


class PriceIndicatorExt(Base):
    __tablename__ = "price_indicators_ext"

    date: Mapped[date] = mapped_column(Date, primary_key=True, index=True)
    ticker: Mapped[str] = mapped_column(String(16), primary_key=True)

    sma20: Mapped[float] = mapped_column(Float, default=0.0)
    sma50: Mapped[float] = mapped_column(Float, default=0.0)
    sma200: Mapped[float] = mapped_column(Float, default=0.0)
    ema20: Mapped[float] = mapped_column(Float, default=0.0)
    ema50: Mapped[float] = mapped_column(Float, default=0.0)
    bb_upper20: Mapped[float] = mapped_column(Float, default=0.0)
    bb_lower20: Mapped[float] = mapped_column(Float, default=0.0)
    atr14: Mapped[float] = mapped_column(Float, default=0.0)
    macd_signal: Mapped[float] = mapped_column(Float, default=0.0)
    macd_hist: Mapped[float] = mapped_column(Float, default=0.0)
    stoch_k: Mapped[float] = mapped_column(Float, default=0.0)
    stoch_d: Mapped[float] = mapped_column(Float, default=0.0)
    obv: Mapped[float] = mapped_column(Float, default=0.0)


class PriceIndicatorIntraday(Base):
    __tablename__ = "price_indicators_intraday"

    ticker: Mapped[str] = mapped_column(String(16), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=False), primary_key=True, index=True)

    rsi_14: Mapped[float] = mapped_column(Float, default=0.0)
    ema20: Mapped[float] = mapped_column(Float, default=0.0)
    ema50: Mapped[float] = mapped_column(Float, default=0.0)
    macd_line: Mapped[float] = mapped_column(Float, default=0.0)
    macd_signal: Mapped[float] = mapped_column(Float, default=0.0)
    macd_hist: Mapped[float] = mapped_column(Float, default=0.0)


