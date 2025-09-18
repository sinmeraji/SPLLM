"""
Service: decision context assembly.
- Builds portfolio snapshot, price features (daily + latest intraday), and news snippets/metrics.
- Used by the LLM decision flow and APIs to provide compact, token-efficient context.
"""
from __future__ import annotations

from datetime import date, time, datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..providers.news import LocalCacheNewsProvider, NewsItem
from ..models.news import NewsMetric, NewsRaw
from ..models.prices import (
    PriceIndicator,
    PriceIndicatorExt,
    PriceIndicatorIntraday,
    PriceBar,
)
from ..models.portfolio import Position
from ..services.sim import get_cash
from ..core.config import settings
from ..providers.prices import get_latest_trade_price_alpaca


def build_news_context_file(d: date, window_end: time, tickers: List[str]) -> Dict[str, Any]:
    provider = LocalCacheNewsProvider()
    items = provider.get_time_gated(d, window_end, tickers)

    # Group by ticker and take latest few for prompt compactness
    per_ticker: Dict[str, List[Dict[str, Any]]] = {}
    for it in sorted(items, key=lambda x: x.ts):
        per_ticker.setdefault(it.ticker, []).append({
            "ts": it.ts.isoformat(),
            "title": it.title,
            "url": it.url,
            "source": it.source,
            "sentiment": it.sentiment,
        })

    # Limit to last 5 items per ticker to keep prompt bounded
    limited = {t: arr[-5:] for t, arr in per_ticker.items()}
    return {"news": limited, "counts": {t: len(arr) for t, arr in per_ticker.items()}}


def build_news_context_db(db: Session, d: date, window_end: time, tickers: List[str], per_ticker_limit: int = 5) -> Dict[str, Any]:
    start_dt = datetime.combine(d, time(0, 0))
    end_dt = datetime.combine(d, window_end)
    out: Dict[str, List[Dict[str, Any]]] = {}
    for t in tickers:
        rows = (
            db.query(NewsRaw)
            .filter(NewsRaw.ticker == t)
            .filter(NewsRaw.ts >= start_dt, NewsRaw.ts <= end_dt)
            .order_by(NewsRaw.ts.desc())
            .limit(per_ticker_limit)
            .all()
        )
        if rows:
            out[t] = [
                {
                    "ts": r.ts.isoformat(),
                    "title": r.title,
                    "url": r.url,
                    "source": r.source,
                    "sentiment": r.sentiment,
                    "type": r.type,
                }
                for r in rows
            ][::-1]  # chronological
    return {"news": out, "counts": {t: len(v) for t, v in out.items()}}



def _build_portfolio_context(db: Session) -> Dict[str, Any]:
    cash = get_cash(db)
    positions = db.query(Position).all()
    items = []
    equity = float(cash)
    for p in positions:
        latest = get_latest_trade_price_alpaca(p.ticker)
        price = float(latest) if latest is not None else float(p.avg_cost)
        value = float(p.quantity) * price
        equity += value
        items.append({"ticker": p.ticker, "quantity": p.quantity, "avg_cost": p.avg_cost, "price": (latest if latest is not None else None), "value": value})
    num_positions = len(items)
    max_position_value_usd = equity * float(settings.risk.max_position_pct)
    return {
        "cash": cash,
        "equity": round(equity, 2),
        "max_position_value_usd": round(max_position_value_usd, 2),
        "num_positions": num_positions,
        "positions": items,
    }


def _build_price_features(db: Session, d: date, tickers: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for t in tickers:
        row = (
            db.query(PriceIndicator)
            .filter(PriceIndicator.date == d, PriceIndicator.ticker == t)
            .first()
        )
        ext = (
            db.query(PriceIndicatorExt)
            .filter(PriceIndicatorExt.date == d, PriceIndicatorExt.ticker == t)
            .first()
        )

        # Orientation for today
        last_close: Optional[float] = None
        change_pct_1d: Optional[float] = None
        try:
            start_dt = datetime.combine(d, time(0, 0))
            end_dt = datetime.combine(d, time(23, 59))
            mb = (
                db.query(PriceBar)
                .filter(PriceBar.ticker == t, PriceBar.timeframe == 'min')
                .filter(PriceBar.ts >= start_dt, PriceBar.ts <= end_dt)
                .order_by(PriceBar.ts.desc())
                .first()
            )
            if mb:
                last_close = float(mb.close)
            pb = (
                db.query(PriceBar)
                .filter(PriceBar.ticker == t, PriceBar.timeframe == 'day')
                .filter(PriceBar.ts < start_dt)
                .order_by(PriceBar.ts.desc())
                .first()
            )
            if pb and last_close is not None and pb.close:
                change_pct_1d = (last_close / float(pb.close)) - 1.0
        except Exception:
            pass

        # Intraday indicators (latest for today)
        intraday: Dict[str, Any] = {}
        try:
            irow = (
                db.query(PriceIndicatorIntraday)
                .filter(PriceIndicatorIntraday.ticker == t)
                .filter(PriceIndicatorIntraday.ts >= datetime.combine(d, time(0, 0)))
                .order_by(PriceIndicatorIntraday.ts.desc())
                .first()
            )
            if irow:
                intraday = {
                    "rsi_14": getattr(irow, "rsi_14", None),
                    "ema20": getattr(irow, "ema20", None),
                    "ema50": getattr(irow, "ema50", None),
                    "macd": getattr(irow, "macd_line", None),
                    "macd_signal": getattr(irow, "macd_signal", None),
                    "macd_hist": getattr(irow, "macd_hist", None),
                }
        except Exception:
            pass

        # Compact historical sequences for LLM (token-bounded)
        daily_hist: Dict[str, List[float]] = {}
        intraday_hist_5m: Dict[str, List[float]] = {}
        try:
            # Daily: last N closes and volumes up to date d (inclusive if present)
            N_DAYS = 20
            start_hist = datetime.combine(d, time(23, 59))
            drows: List[PriceBar] = (
                db.query(PriceBar)
                .filter(PriceBar.ticker == t, PriceBar.timeframe == 'day')
                .filter(PriceBar.ts <= start_hist)
                .order_by(PriceBar.ts.desc())
                .limit(N_DAYS)
                .all()
            )
            if drows:
                closes = [float(r.close) for r in reversed(drows)]
                vols = [float(r.volume or 0.0) for r in reversed(drows)]
                daily_hist = {"closes": closes, "volumes": vols}
        except Exception:
            pass
        try:
            # Intraday today: bucket minute bars into 5m, take last K closes
            K_POINTS = 12
            start_day = datetime.combine(d, time(0, 0))
            end_day = datetime.combine(d, time(23, 59))
            mrows: List[PriceBar] = (
                db.query(PriceBar)
                .filter(PriceBar.ticker == t, PriceBar.timeframe == 'min')
                .filter(PriceBar.ts >= start_day, PriceBar.ts <= end_day)
                .order_by(PriceBar.ts.asc())
                .all()
            )
            if mrows:
                bucket_to_close: Dict[int, float] = {}
                five = 5 * 60
                for r in mrows:
                    try:
                        epoch = int(r.ts.timestamp())
                    except Exception:
                        continue
                    bucket = (epoch // five) * five
                    bucket_to_close[bucket] = float(r.close)
                keys = sorted(bucket_to_close.keys())
                series = [bucket_to_close[k] for k in keys][-K_POINTS:]
                intraday_hist_5m = {"closes": series}
        except Exception:
            pass

        out[t] = {
            "last_close": last_close,
            "change_pct_1d": change_pct_1d,
            "r1d": getattr(row, "r1d", None) if row else None,
            "r5d": getattr(row, "r5d", None) if row else None,
            "r20d": getattr(row, "r20d", None) if row else None,
            "mom_60d": getattr(row, "mom_60d", None) if row else None,
            "vol_20d": getattr(row, "vol_20d", None) if row else None,
            "rsi_14": getattr(row, "rsi_14", None) if row else None,
            "macd": getattr(row, "macd", None) if row else None,
            "v_zscore_20d": getattr(row, "v_zscore_20d", None) if row else None,
            "sma20": getattr(ext, "sma20", None) if ext else None,
            "sma50": getattr(ext, "sma50", None) if ext else None,
            "sma200": getattr(ext, "sma200", None) if ext else None,
            "ema20": getattr(ext, "ema20", None) if ext else None,
            "ema50": getattr(ext, "ema50", None) if ext else None,
            "bb_upper20": getattr(ext, "bb_upper20", None) if ext else None,
            "bb_lower20": getattr(ext, "bb_lower20", None) if ext else None,
            "macd_signal": getattr(ext, "macd_signal", None) if ext else None,
            "macd_hist": getattr(ext, "macd_hist", None) if ext else None,
            "intraday": intraday,
            "daily_history": daily_hist,
            "intraday_history_5m": intraday_hist_5m,
        }
    return out


def _build_news_metrics(
    db: Session, d: date, tickers: List[str], allowed_windows: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    q = db.query(NewsMetric).filter(NewsMetric.date == d)
    if tickers:
        q = q.filter(NewsMetric.ticker.in_(tickers))
    if allowed_windows:
        q = q.filter(NewsMetric.window.in_(allowed_windows))
    rows = q.all()
    return [
        {
            "ticker": r.ticker,
            "type": r.type,
            "window": r.window,
            "count": r.count,
            "sentiment_avg": r.sentiment_avg,
            "novelty": r.novelty,
            "reliability": r.reliability,
        }
        for r in rows
    ]


def build_decision_context(db: Session, d: date, window_end: time, tickers: List[str]) -> Dict[str, Any]:
    """Assemble full decision context for the LLM call.
    Includes portfolio, price features, news metrics, and brief headlines.
    """
    tickers_u = [t.upper() for t in tickers]
    portfolio = _build_portfolio_context(db)
    # Decide intraday vs EOD windows for news metrics
    intraday = window_end < time(16, 0)
    allowed_windows = ["1d", "3d"] if intraday else ["1d", "3d", "7d"]
    prices = _build_price_features(db, d, tickers_u)
    news_metrics = _build_news_metrics(db, d, tickers_u, allowed_windows=allowed_windows)
    news_briefs = build_news_context_db(db, d, window_end, tickers_u)
    if not news_briefs["news"]:
        # fallback to file cache if DB empty
        news_briefs = build_news_context_file(d, window_end, tickers_u)
    policy = {
        "limits": {"max_positions": 15, "max_weight_pct": 10, "min_cash_pct": 5},
        "costs": {"commission_usd": 10, "slippage_bps": 2},
        "stops_targets": {"default_stop_frac": 0.08, "default_target_frac": 0.12},
        "min_order_usd": 1000,
    }
    as_of = datetime.combine(d, window_end).isoformat()

    # Optional small market context (QQQ)
    market: Dict[str, Any] = {}
    if "QQQ" not in tickers_u:
        qqq = _build_price_features(db, d, ["QQQ"]).get("QQQ")
        if qqq:
            market["QQQ"] = {k: v for k, v in qqq.items() if k in ("change_pct_1d", "rsi_14", "vol_20d", "macd")}

    ctx = {
        "as_of": as_of,
        "tickers": tickers_u,
        "policy": policy,
        "portfolio": portfolio,
        "prices": prices,
        "news_metrics": news_metrics,
        "news": news_briefs,
    }
    if market:
        ctx["market"] = market

    # prune nulls and round floats to reduce tokens
    def _round(v: Any) -> Any:
        if isinstance(v, float):
            return round(v, 4)
        return v

    def _prune(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: _prune(v) for k, v in obj.items() if v is not None and v != {}}
        if isinstance(obj, list):
            return [_prune(x) for x in obj if x is not None]
        return _round(obj)

    return _prune(ctx)

