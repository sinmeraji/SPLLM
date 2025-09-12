from __future__ import annotations

from datetime import date, time, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..providers.news import LocalCacheNewsProvider, NewsItem
from ..models.news import NewsMetric
from ..models.prices import PriceIndicator, PriceIndicatorExt
from ..models.portfolio import Position
from ..services.sim import get_cash


def build_news_context(d: date, window_end: time, tickers: List[str]) -> Dict[str, Any]:
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



def _build_portfolio_context(db: Session) -> Dict[str, Any]:
    cash = get_cash(db)
    positions = db.query(Position).all()
    pos = [{"ticker": p.ticker, "quantity": p.quantity, "avg_cost": p.avg_cost} for p in positions]
    num_positions = len(pos)
    return {
        "cash": cash,
        "num_positions": num_positions,
        "positions": pos,
    }


def _build_price_features(db: Session, d: date, tickers: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for t in tickers:
        row = db.query(PriceIndicator).filter(PriceIndicator.date == d, PriceIndicator.ticker == t).first()
        ext = db.query(PriceIndicatorExt).filter(PriceIndicatorExt.date == d, PriceIndicatorExt.ticker == t).first()
        out[t] = {
            "r1d": getattr(row, "r1d", None) if row else None,
            "r5d": getattr(row, "r5d", None) if row else None,
            "r20d": getattr(row, "r20d", None) if row else None,
            "mom_60d": getattr(row, "mom_60d", None) if row else None,
            "vol_20d": getattr(row, "vol_20d", None) if row else None,
            "rsi_14": getattr(row, "rsi_14", None) if row else None,
            "macd": getattr(row, "macd", None) if row else None,
            "v_zscore_20d": getattr(row, "v_zscore_20d", None) if row else None,
            "sma_20": getattr(ext, "sma_20", None) if ext else None,
            "sma_50": getattr(ext, "sma_50", None) if ext else None,
            "sma_200": getattr(ext, "sma_200", None) if ext else None,
            "ema_20": getattr(ext, "ema_20", None) if ext else None,
            "ema_50": getattr(ext, "ema_50", None) if ext else None,
            "bb_upper": getattr(ext, "bb_upper", None) if ext else None,
            "bb_lower": getattr(ext, "bb_lower", None) if ext else None,
            "macd_signal": getattr(ext, "macd_signal", None) if ext else None,
            "macd_hist": getattr(ext, "macd_hist", None) if ext else None,
        }
    return out


def _build_news_metrics(db: Session, d: date, tickers: List[str]) -> List[Dict[str, Any]]:
    q = db.query(NewsMetric).filter(NewsMetric.date == d)
    if tickers:
        q = q.filter(NewsMetric.ticker.in_(tickers))
    rows = q.all()
    return [{
        "ticker": r.ticker,
        "type": r.type,
        "window": r.window,
        "count": r.count,
        "sentiment_avg": r.sentiment_avg,
        "novelty": r.novelty,
        "reliability": r.reliability,
    } for r in rows]


def build_decision_context(db: Session, d: date, window_end: time, tickers: List[str]) -> Dict[str, Any]:
    """Assemble full decision context for the LLM call.
    Includes portfolio, price features, news metrics, and brief headlines.
    """
    tickers_u = [t.upper() for t in tickers]
    portfolio = _build_portfolio_context(db)
    prices = _build_price_features(db, d, tickers_u)
    news_metrics = _build_news_metrics(db, d, tickers_u)
    news_briefs = build_news_context(d, window_end, tickers_u)
    policy = {
        "limits": {"max_positions": 15, "max_weight_pct": 10, "min_cash_pct": 5},
        "costs": {"commission_usd": 10, "slippage_bps": 2},
        "stops_targets": {"default_stop_frac": 0.08, "default_target_frac": 0.12},
        "min_order_usd": 1000,
    }
    return {
        "as_of": datetime.combine(d, window_end).isoformat(),
        "tickers": tickers_u,
        "policy": policy,
        "portfolio": portfolio,
        "prices": prices,
        "news_metrics": news_metrics,
        "news": news_briefs,
    }

