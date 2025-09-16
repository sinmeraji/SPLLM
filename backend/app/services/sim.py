from __future__ import annotations
"""
Service: portfolio state and simple execution simulation.
- Manages cash KV, initializes portfolio, and applies market orders with slippage/commission.
- Central place to log order application details for audit (fill, notional, pos/cash deltas).
"""

from sqlalchemy import select
from sqlalchemy.orm import Session
import logging

from ..models.portfolio import Position, Order, KV


CASH_KEY = "cash"


def get_cash(db: Session) -> float:
    row = db.get(KV, CASH_KEY)
    return float(row.value) if row else 0.0


def set_cash(db: Session, amount: float) -> None:
    row = db.get(KV, CASH_KEY)
    if not row:
        row = KV(key=CASH_KEY, value=str(amount))
        db.add(row)
    else:
        row.value = str(amount)
    db.commit()


def ensure_initialized(db: Session, initial_cash: float) -> None:
    if not db.get(KV, CASH_KEY):
        set_cash(db, initial_cash)


def apply_order(
    db: Session,
    *,
    ts_et,
    ticker: str,
    side: str,
    quantity: float,
    price: float,
    slippage_bps: float,
    commission_usd: float,
    reason: str,
):
    """Apply an execution to portfolio state and record order."""
    log = logging.getLogger(__name__)
    slip_mult = 1.0 + (slippage_bps / 10_000.0) if side == "BUY" else 1.0 - (slippage_bps / 10_000.0)
    fill_price = price * slip_mult

    pos = db.execute(select(Position).where(Position.ticker == ticker)).scalar_one_or_none()
    if not pos:
        pos = Position(ticker=ticker, quantity=0.0, avg_cost=0.0)
        db.add(pos)

    cash_before = get_cash(db)
    qty_before = float(pos.quantity)
    avg_before = float(pos.avg_cost)
    cash = cash_before

    if side == "BUY":
        notional = quantity * fill_price
        new_qty = pos.quantity + quantity
        pos.avg_cost = ((pos.avg_cost * pos.quantity) + notional) / new_qty if new_qty > 0 else 0.0
        pos.quantity = new_qty
        cash -= notional
    else:  # SELL
        sell_qty = min(quantity, pos.quantity)
        notional = sell_qty * fill_price
        pos.quantity -= sell_qty
        if pos.quantity == 0:
            pos.avg_cost = 0.0
        cash += notional

    cash -= commission_usd

    order = Order(
        ts_et=ts_et,
        ticker=ticker,
        side=side,
        quantity=quantity,
        price=fill_price,
        slippage_bps=slippage_bps,
        commission_usd=commission_usd,
        reason=reason,
    )
    db.add(order)

    set_cash(db, cash)
    db.commit()
    try:
        log.info(
            "order applied id=%s ts=%s ticker=%s side=%s qty=%.4f ref_price=%.4f fill_price=%.4f slip_bps=%.1f commission=%.2f notional=%.2f pos_qty: %.4f->%.4f avg_cost: %.4f->%.4f cash: %.2f->%.2f reason=%s",
            order.id,
            getattr(order, "ts_et", None),
            ticker,
            side,
            quantity,
            price,
            fill_price,
            slippage_bps,
            commission_usd,
            (abs(quantity) * fill_price),
            qty_before,
            float(pos.quantity),
            avg_before,
            float(pos.avg_cost),
            cash_before,
            float(cash),
            reason,
        )
    except Exception:
        pass
    return order
