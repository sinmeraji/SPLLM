"""
FastAPI application entrypoint.
- Assembles routers (prices, news, features, decide, etc.) and mounts the static UI.
- Configures CORS and SSE events; intended to run via uvicorn.
Usage: uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .api.simulate import sim_router
from .api.prices import router as prices_router
from .api.events import router as events_router
from .api.equity import router as equity_router
from .api.backtest import router as backtest_router
from .api.news_api import router as news_router
from .api.news_db_api import router as newsdb_router
from .api.decide import router as decide_router
from .api.features import router as features_router
from sqlalchemy.orm import Session
from .core.db import get_db
from .services.rules import evaluate_order
from .services.sim import apply_order, ensure_initialized, get_cash, set_cash
from .core.config import settings
from .utils.events import bus


app = FastAPI(title="Spllm Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


# For `uvicorn backend.app.main:app --reload`

app.include_router(sim_router)

app.include_router(prices_router)
app.include_router(equity_router)
app.include_router(backtest_router)
app.include_router(news_router)
app.include_router(newsdb_router)
app.include_router(decide_router)
app.include_router(features_router)

app.mount('/app', StaticFiles(directory='backend/app/static', html=True), name='static')

app.include_router(events_router)

from .services.auto_trader import auto_trader_loop
from .services.scheduler import start_scheduler, stop_scheduler
import asyncio, os

@app.on_event('startup')
async def start_auto_trader():
    # Optionally reset starting balance from env on startup
    try:
        if os.getenv('RESET_BALANCE_ON_START', '0') == '1':
            from .core.db import SessionLocal
            with SessionLocal() as db:
                # If ORIGINAL_BALANCE_USD is set, use it; otherwise keep current
                orig = os.getenv('ORIGINAL_BALANCE_USD')
                if orig:
                    try:
                        set_cash(db, float(orig))
                    except Exception:
                        pass
    except Exception:
        pass
    # Disable auto-trader by default
    if os.getenv('ENABLE_SCHEDULER', '1') == '1':
        start_scheduler()
    return


@app.post("/decide")
async def decide_entry(payload: dict, db: Session = Depends(get_db)):
    ensure_initialized(db, settings.initial_cash_usd)
    tickers = [t.upper() for t in (payload.get('tickers') or [])]
    if not tickers:
        return {"results": [], "cash": get_cash(db)}
    from datetime import datetime
    ts_raw = payload.get('ts_et')
    ts = datetime.fromisoformat(ts_raw) if ts_raw else datetime.utcnow()
    results = []
    cash = get_cash(db)
    day_orders_count = 0
    for t in tickers[:1]:
        ref_price = 100.0
        rule = evaluate_order(
            db,
            now_et=ts,
            ticker=t,
            side='BUY',
            quantity=10.0,
            reference_price=ref_price,
            cash=cash,
            day_turnover_notional=0.0,
            day_orders_count=day_orders_count,
            last_exit_time_by_ticker={},
        )
        if not rule.accepted:
            results.append({"ticker": t, "side": "BUY", "accepted": False, "reasons": rule.reasons})
            continue
        order = apply_order(
            db,
            ts_et=ts,
            ticker=t,
            side='BUY',
            quantity=rule.adjusted_quantity,
            price=ref_price,
            slippage_bps=settings.execution.slippage_bps,
            commission_usd=settings.execution.commission_usd,
            reason='decide-mock',
        )
        day_orders_count += 1
        cash = get_cash(db)
        results.append({"ticker": t, "side": "BUY", "accepted": True, "order_id": order.id})
        await bus.publish({
            "type": "trade",
            "ts": ts.isoformat(),
            "ticker": t,
            "side": "BUY",
            "qty": rule.adjusted_quantity,
            "price": ref_price,
            "order_id": order.id,
            "source": "decide",
            "reason": "decide-mock",
        })
    return {"results": results, "cash": cash}
