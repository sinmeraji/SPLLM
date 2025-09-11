from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Tuple

import math
from sqlalchemy.orm import Session

from ..models.prices import PriceBar, PriceIndicator


def _to_datespan(center: date, back_days: int) -> Tuple[datetime, datetime]:
    start = datetime.combine(center - timedelta(days=back_days), datetime.min.time())
    end = datetime.combine(center, datetime.max.time())
    return start, end


def _load_daily_series(db: Session, ticker: str, center: date, back_days: int = 400) -> List[Tuple[date, float, float]]:
    """Return list of (day, close, volume_sum) for up to back_days history up to center day inclusive.
    Aggregates minute bars by taking the last close per day and summing volumes.
    """
    start_dt, end_dt = _to_datespan(center, back_days)
    bars: List[PriceBar] = (
        db.query(PriceBar)
        .filter(
            PriceBar.ticker == ticker.upper(),
            PriceBar.timeframe == 'min',
            PriceBar.ts >= start_dt,
            PriceBar.ts <= end_dt,
        )
        .order_by(PriceBar.ts.asc())
        .all()
    )
    per_day: Dict[date, Tuple[datetime, float, float]] = {}
    for b in bars:
        d = b.ts.date()
        if d not in per_day:
            per_day[d] = (b.ts, b.close, b.volume)
        else:
            last_ts, last_close, vol_sum = per_day[d]
            if b.ts >= last_ts:
                last_ts, last_close = b.ts, b.close
            per_day[d] = (last_ts, last_close, vol_sum + (b.volume or 0.0))
    series = [(d, c, v) for d, (_, c, v) in per_day.items()]
    series.sort(key=lambda x: x[0])
    return series


def _pct(a: float, b: float) -> float:
    if b == 0:
        return 0.0
    return (a - b) / b


def _sma(vals: List[float], n: int) -> float:
    if len(vals) < n or n <= 0:
        return 0.0
    return sum(vals[-n:]) / n


def _std(vals: List[float], n: int) -> float:
    if len(vals) < n or n <= 1:
        return 0.0
    window = vals[-n:]
    m = sum(window) / n
    var = sum((x - m) ** 2 for x in window) / (n - 1)
    return math.sqrt(var)


def _ema(vals: List[float], n: int) -> float:
    if not vals or n <= 0:
        return 0.0
    k = 2 / (n + 1)
    ema = vals[0]
    for v in vals[1:]:
        ema = v * k + ema * (1 - k)
    return ema


def _rsi(prices: List[float], n: int = 14) -> float:
    if len(prices) < n + 1:
        return 0.0
    gains: List[float] = []
    losses: List[float] = []
    for i in range(1, len(prices)):
        ch = prices[i] - prices[i - 1]
        gains.append(max(0.0, ch))
        losses.append(max(0.0, -ch))
    avg_gain = _sma(gains, n)
    avg_loss = _sma(losses, n)
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1 + rs))


def recompute_indicators_for_date(db: Session, *, ticker: str, d: date) -> bool:
    series = _load_daily_series(db, ticker, d, back_days=400)
    if not series:
        return False
    days = [di for (di, _, _) in series]
    closes = [c for (_, c, _) in series]
    vols = [v for (_, _, v) in series]
    # compute on the last day (d)
    try:
        idx = days.index(d)
    except ValueError:
        return False
    # returns
    r1d = _pct(closes[idx], closes[idx - 1]) if idx >= 1 else 0.0
    r5d = _pct(closes[idx], closes[idx - 5]) if idx >= 5 else 0.0
    r20d = _pct(closes[idx], closes[idx - 20]) if idx >= 20 else 0.0
    mom_60d = _pct(closes[idx], closes[idx - 60]) if idx >= 60 else 0.0
    # vol of daily returns over 20d
    daily_rets: List[float] = []
    for i in range(1, idx + 1):
        if closes[i - 1] != 0:
            daily_rets.append((closes[i] - closes[i - 1]) / closes[i - 1])
        else:
            daily_rets.append(0.0)
    vol_20d = _std(daily_rets, 20)
    # RSI 14
    rsi_14 = _rsi(closes[: idx + 1], 14)
    # MACD (12,26,9) using closes up to idx
    ema12 = _ema(closes[: idx + 1][-26:], 12)
    ema26 = _ema(closes[: idx + 1][-26:], 26)
    macd = ema12 - ema26
    # Volume z-score 20d
    v_zscore_20d = 0.0
    if idx >= 20:
        vwin = vols[idx - 19 : idx + 1]
        m = sum(vwin) / 20.0
        sd = math.sqrt(sum((x - m) ** 2 for x in vwin) / 19.0) if 19 > 0 else 0.0
        if sd > 0:
            v_zscore_20d = (vols[idx] - m) / sd

    # upsert into price_indicators
    row = db.query(PriceIndicator).filter(
        PriceIndicator.date == d,
        PriceIndicator.ticker == ticker.upper(),
    ).one_or_none()
    if not row:
        row = PriceIndicator(date=d, ticker=ticker.upper())
        db.add(row)
    row.r1d = r1d
    row.r5d = r5d
    row.r20d = r20d
    row.mom_60d = mom_60d
    row.vol_20d = vol_20d
    row.rsi_14 = rsi_14
    row.macd = macd
    row.v_zscore_20d = v_zscore_20d
    db.commit()
    return True


