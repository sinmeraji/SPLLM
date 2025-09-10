from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable, List, Dict

from sqlalchemy.orm import Session

from ..core.config import settings
from ..providers.prices import PriceProvider, LocalCachePriceProvider, Bar
from ..providers.news import NewsProvider, LocalCacheNewsProvider
from ..services.sim import ensure_initialized, apply_order, get_cash
from ..services.rules import evaluate_order
from ..engine.llm import propose_trades
from ..utils.logging import write_jsonl
from ..utils.events import bus
from pathlib import Path


RTH_START = time(9, 30)
RTH_END = time(16, 0)


@dataclass
class DecisionWindow:
    time_et: time


def to_decision_windows() -> List[DecisionWindow]:
    return [DecisionWindow(time.fromisoformat(t)) for t in settings.cadence.decision_windows_et]


def bar_mid(b: Bar) -> float:
    return (b.high + b.low) / 2.0


def simulate_day(
    db: Session,
    provider: PriceProvider,
    d: date,
    tickers: List[str],
):
    # Decision windows loop (LLM proposals; placeholder without API key)
    for win in to_decision_windows():
        context = {
            "as_of": datetime.combine(d, win.time_et),
            "tickers": tickers,
            "portfolio_cash": get_cash(db),
        }
        proposals = propose_trades(context)
        results = []
        cash = get_cash(db)
        day_orders_count = 0
        for p in proposals:
            ref_price = 0.0
            rule = evaluate_order(
                db,
                now_et=context["as_of"],
                ticker=p.ticker,
                side=p.action,
                quantity=p.quantity,
                reference_price=ref_price,
                cash=cash,
                day_turnover_notional=0.0,
                day_orders_count=day_orders_count,
                last_exit_time_by_ticker={},
            )
            if not rule.accepted:
                results.append({"ticker": p.ticker, "side": p.action, "accepted": False, "reasons": rule.reasons})
                continue
            order = apply_order(
                db,
                ts_et=context["as_of"],
                ticker=p.ticker,
                side=p.action,
                quantity=rule.adjusted_quantity,
                price=ref_price,
                slippage_bps=settings.execution.slippage_bps,
                commission_usd=settings.execution.commission_usd,
                reason="llm",
            )
            day_orders_count += 1
            cash = get_cash(db)
            results.append({"ticker": p.ticker, "side": p.action, "accepted": True, "order_id": order.id})

        write_jsonl(Path('logs/decisions.jsonl').resolve(), {
            "day": d.isoformat(),
            "window": win.time_et.isoformat(timespec='minutes'),
            "proposals": [getattr(p, '__dict__', dict()) for p in proposals],
            "results": results,
        })


def run_backtest(
    db: Session,
    *,
    price_provider: PriceProvider | None = None,
    news_provider: NewsProvider | None = None,
):
    ensure_initialized(db, settings.initial_cash_usd)

    price_provider = price_provider or LocalCachePriceProvider()
    news_provider = news_provider or LocalCacheNewsProvider()

    start = date.fromisoformat(settings.run_window.start_et)
    end = date.fromisoformat(settings.run_window.end_et)

    # Load universe list
    tickers = [
        t.strip() for t in (Path('configs/universe/tickers.txt').read_text().splitlines()) if t.strip()
    ]

    cur = start
    while cur <= end:
        simulate_day(db, price_provider, cur, tickers)
        cur = date.fromordinal(cur.toordinal() + 1)

    return {"status": "completed", "start": settings.run_window.start_et, "end": settings.run_window.end_et}


async def run_backtest_range(
    db: Session,
    *,
    start: date,
    end: date,
    price_provider: PriceProvider | None = None,
    news_provider: NewsProvider | None = None,
):
    ensure_initialized(db, settings.initial_cash_usd)

    price_provider = price_provider or LocalCachePriceProvider()
    news_provider = news_provider or LocalCacheNewsProvider()

    tickers = [
        t.strip() for t in (Path('configs/universe/tickers.txt').read_text().splitlines()) if t.strip()
    ]

    cur = start
    while cur <= end:
        bus_payload = {"type": "backtest_progress", "day": cur.isoformat()}
        try:
            simulate_day(db, price_provider, cur, tickers)
            bus_payload["status"] = "ok"
        except Exception as e:
            bus_payload["status"] = "error"
            bus_payload["message"] = str(e)
        finally:
            try:
                await bus.publish(bus_payload)
            except Exception:
                pass
        cur = date.fromordinal(cur.toordinal() + 1)
    return {"status": "completed", "start": start.isoformat(), "end": end.isoformat()}
