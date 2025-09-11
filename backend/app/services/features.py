"""
Service: price indicators computation.
- Builds daily indicators from DB minute bars and stores to price_indicators(+_ext).
- Computes intraday (last 90d) rolling indicators and stores to price_indicators_intraday.
Usage: call recompute_indicators_for_date(...) or recompute_intraday_indicators_last_90d(...).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Tuple

import math
from sqlalchemy.orm import Session

from ..models.prices import PriceBar, PriceIndicator, PriceIndicatorExt, PriceIndicatorIntraday


def _to_datespan(center: date, back_days: int) -> Tuple[datetime, datetime]:
    start = datetime.combine(center - timedelta(days=back_days), datetime.min.time())
    end = datetime.combine(center, datetime.max.time())
    return start, end


def _load_daily_series(db: Session, ticker: str, center: date, back_days: int = 400) -> List[Tuple[date, float, float]]:
    """Return list of (day, close, volume_sum) for up to back_days history up to center day inclusive.
    Aggregates minute bars by taking the last close per day and summing volumes.
    """
    bars: List[PriceBar] = (
        db.query(PriceBar)
        .filter(
            PriceBar.ticker == ticker.upper(),
            PriceBar.timeframe == 'min',
            PriceBar.ts >= datetime.combine(center - timedelta(days=back_days), datetime.min.time()),
            PriceBar.ts <= datetime.combine(center, datetime.max.time()),
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


def recompute_intraday_indicators_last_90d(db: Session, *, ticker: str, as_of: date) -> int:
    """Compute intraday indicators (RSI-14, EMA20/50, MACD) for last 90 calendar days of minute bars.
    Upsert into price_indicators_intraday keyed by (ticker, ts).
    """
    start_dt = datetime.combine(as_of - timedelta(days=90), datetime.min.time())
    end_dt = datetime.combine(as_of, datetime.max.time())
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
    closes: List[float] = []
    out = 0
    ema20_val = 0.0
    ema50_val = 0.0
    macd_signal = 0.0
    for b in bars:
        closes.append(b.close)
        rsi = _rsi(closes, 14)
        ema20_val = _ema(closes[-60:], 20)
        ema50_val = _ema(closes[-100:], 50)
        ema12 = _ema(closes[-40:], 12)
        ema26 = _ema(closes[-60:], 26)
        macd_line = ema12 - ema26
        macd_signal = 0.8 * macd_signal + 0.2 * macd_line
        macd_hist = macd_line - macd_signal
        row = db.query(PriceIndicatorIntraday).filter(
            PriceIndicatorIntraday.ticker == ticker.upper(),
            PriceIndicatorIntraday.ts == b.ts,
        ).one_or_none()
        if not row:
            row = PriceIndicatorIntraday(ticker=ticker.upper(), ts=b.ts)
            db.add(row)
        row.rsi_14 = rsi
        row.ema20 = ema20_val
        row.ema50 = ema50_val
        row.macd_line = macd_line
        row.macd_signal = macd_signal
        row.macd_hist = macd_hist
        out += 1
    db.commit()
    return out


def recompute_indicators_for_date(db: Session, *, ticker: str, d: date) -> bool:
    series = _load_daily_series(db, ticker, d, back_days=400)
    if not series:
        return False
    days = [di for (di, _, _) in series]
    closes = [c for (_, c, _) in series]
    vols = [v for (_, _, v) in series]
    try:
        idx = days.index(d)
    except ValueError:
        return False
    r1d = _pct(closes[idx], closes[idx - 1]) if idx >= 1 else 0.0
    r5d = _pct(closes[idx], closes[idx - 5]) if idx >= 5 else 0.0
    r20d = _pct(closes[idx], closes[idx - 20]) if idx >= 20 else 0.0
    mom_60d = _pct(closes[idx], closes[idx - 60]) if idx >= 60 else 0.0
    daily_rets: List[float] = []
    for i in range(1, idx + 1):
        if closes[i - 1] != 0:
            daily_rets.append((closes[i] - closes[i - 1]) / closes[i - 1])
        else:
            daily_rets.append(0.0)
    vol_20d = _std(daily_rets, 20)
    rsi_14 = _rsi(closes[: idx + 1], 14)
    ema12 = _ema(closes[: idx + 1][-26:], 12)
    ema26 = _ema(closes[: idx + 1][-26:], 26)
    macd = ema12 - ema26
    v_zscore_20d = 0.0
    if idx >= 20:
        vwin = vols[idx - 19 : idx + 1]
        m = sum(vwin) / 20.0
        sd = math.sqrt(sum((x - m) ** 2 for x in vwin) / 19.0) if 19 > 0 else 0.0
        if sd > 0:
            v_zscore_20d = (vols[idx] - m) / sd
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
    closes_hist = [c for (_, c, _) in series[: idx + 1]]
    sma20 = _sma(closes_hist, 20)
    sma50 = _sma(closes_hist, 50)
    sma200 = _sma(closes_hist, 200)
    ema20 = _ema(closes_hist[-60:], 20)
    ema50 = _ema(closes_hist[-100:], 50)
    bb_mid = sma20
    bb_sd = _std(closes_hist, 20)
    bb_upper20 = bb_mid + 2 * bb_sd
    bb_lower20 = bb_mid - 2 * bb_sd
    macd_line = macd
    macd_signal = _ema([macd_line], 9)
    macd_hist = macd_line - macd_signal
    if len(closes_hist) >= 14:
        win = closes_hist[-14:]
        ll, hh = min(win), max(win)
        stoch_k = 0.0 if hh == ll else (closes_hist[-1] - ll) / (hh - ll) * 100.0
    else:
        stoch_k = 0.0
    stoch_d = stoch_k
    obv = 0.0
    for i in range(1, len(closes_hist)):
        if closes_hist[i] > closes_hist[i-1]:
            obv += vols[i]
        elif closes_hist[i] < closes_hist[i-1]:
            obv -= vols[i]
    ext = db.query(PriceIndicatorExt).filter(PriceIndicatorExt.date == d, PriceIndicatorExt.ticker == ticker.upper()).one_or_none()
    if not ext:
        ext = PriceIndicatorExt(date=d, ticker=ticker.upper())
        db.add(ext)
    ext.sma20 = sma20
    ext.sma50 = sma50
    ext.sma200 = sma200
    ext.ema20 = ema20
    ext.ema50 = ema50
    ext.bb_upper20 = bb_upper20
    ext.bb_lower20 = bb_lower20
    ext.atr14 = 0.0
    ext.macd_signal = macd_signal
    ext.macd_hist = macd_hist
    ext.stoch_k = stoch_k
    ext.stoch_d = stoch_d
    ext.obv = obv
    db.commit()
    return True


