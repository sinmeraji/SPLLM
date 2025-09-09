from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.db import get_db, engine
from ..models.base import Base
from ..models.portfolio import Position, KV
from ..schemas.portfolio import PortfolioOut, PositionOut
from ..services.sim import ensure_initialized, get_cash, apply_order


router = APIRouter()


@router.get("/health")
def health() -> dict:
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


@router.post("/orders/market")
def place_market_order(
    payload: dict,
    db: Session = Depends(get_db),
):
    # Simple market order ingestion for later extension
    ts = datetime.fromisoformat(payload["ts_et"]) if "ts_et" in payload else datetime.utcnow()
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
    return {"order_id": order.id}
