from __future__ import annotations

from datetime import datetime
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.db import get_db, engine
from ..models.base import Base
from ..models.portfolio import Position, KV
from ..schemas.portfolio import PortfolioOut, PositionOut, PortfolioSummaryOut, PositionDetailOut
from ..services.sim import ensure_initialized, get_cash, apply_order
from ..providers.prices import get_latest_trade_price_alpaca
from .decide import decide_and_execute as decide_fn
import asyncio
from ..utils.events import bus


router = APIRouter()
log = logging.getLogger(__name__)


@router.get("/health")
def health() -> dict:
    log.debug("/health ok")
    return {"status": "ok"}


@router.get("/config")
def get_config() -> dict:
    return settings.model_dump()


@router.on_event("startup")
def startup_event():
    Base.metadata.create_all(bind=engine)


@router.get("/portfolio", response_model=PortfolioOut)
def get_portfolio(db: Session = Depends(get_db)):
    ensure_initialized(db, settings.initial_cash_usd)
    positions = db.query(Position).all()
    cash = get_cash(db)
    return PortfolioOut(
        cash=cash,
        positions=[PositionOut(ticker=p.ticker, quantity=p.quantity, avg_cost=p.avg_cost) for p in positions],
    )


@router.get("/portfolio/summary", response_model=PortfolioSummaryOut)
def get_portfolio_summary(db: Session = Depends(get_db)):
    ensure_initialized(db, settings.initial_cash_usd)
    positions = db.query(Position).all()
    cash = get_cash(db)
    details: list[PositionDetailOut] = []
    equity = cash
    # Compute details with latest price if available
    for p in positions:
        latest = get_latest_trade_price_alpaca(p.ticker)
        price = float(latest) if latest is not None else None
        use_price = price if price is not None else p.avg_cost
        value = float(p.quantity) * float(use_price)
        pnl = (use_price - float(p.avg_cost)) * float(p.quantity)
        pnl_pct = 0.0 if p.avg_cost == 0 else (use_price / float(p.avg_cost) - 1.0)
        equity += value
        details.append(PositionDetailOut(
            ticker=p.ticker,
            quantity=p.quantity,
            avg_cost=p.avg_cost,
            price=price,
            value=round(value, 2),
            weight_pct=0.0,  # fill after equity known
            pnl=round(pnl, 2),
            pnl_pct=round(pnl_pct * 100.0, 2),
        ))
    # Fill weights
    for i in range(len(details)):
        if equity > 0:
            details[i].weight_pct = round((details[i].value / equity) * 100.0, 2)
    return PortfolioSummaryOut(
        cash=round(cash, 2),
        equity=round(equity, 2),
        positions_count=len(details),
        positions=details,
    )


@router.post("/orders/market")
async def place_market_order(
    payload: dict,
    db: Session = Depends(get_db),
):
    # Simple market order ingestion for later extension
    ts_raw = payload.get("ts_et")
    if ts_raw:
        ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
    else:
        ts = datetime.utcnow()
    ticker = payload["ticker"].upper()
    side = payload["side"].upper()
    quantity = float(payload["quantity"])    # assume post-slippage sizing later
    price = float(payload["price"])          # reference price (mid)
    order = apply_order(
        db,
        ts_et=ts,
        ticker=ticker,
        side=side,
        quantity=quantity,
        price=price,
        slippage_bps=settings.execution.slippage_bps,
        commission_usd=settings.execution.commission_usd,
        reason=payload.get("reason", "manual"),
    )
    # Emit SSE synchronously to ensure delivery
    await bus.publish({
        "type": "trade",
        "ts": ts.isoformat(),
        "ticker": ticker,
        "side": side,
        "qty": quantity,
        "price": price,
        "order_id": order.id,
        "source": payload.get("source", "manual"),
        "reason": payload.get("reason", "manual"),
        "accepted": True,
    })
    log.info("/orders/market order_id=%s ticker=%s side=%s qty=%s", order.id, ticker, side, quantity)
    return {"order_id": order.id}


@router.post("/decide")
async def decide_passthrough(payload: dict, db: Session = Depends(get_db)):
    return await decide_fn(payload, db)


@router.get("/decide-test")
def decide_test() -> dict:
    return {"status": "decide route container loaded"}
