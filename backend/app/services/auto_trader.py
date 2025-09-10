from __future__ import annotations

import asyncio
from datetime import datetime
from random import random, choice

from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.db import SessionLocal
from ..models.portfolio import Position
from ..services.sim import apply_order, get_cash, ensure_initialized
from ..utils.events import bus

TICKERS = ["AAPL", "MSFT", "NVDA", "QQQ"]

async def auto_trader_loop():
    while True:
        try:
            with SessionLocal() as db:
                ensure_initialized(db, settings.initial_cash_usd)
                t = choice(TICKERS)
                side = "BUY" if random() < 0.5 else "SELL"
                price = 100.0 + int(random()*50)
                qty = 1.0
                pos = db.query(Position).filter(Position.ticker == t).one_or_none()
                if side == "SELL" and (not pos or pos.quantity <= 0):
                    side = "BUY"
                order = apply_order(
                    db,
                    ts_et=datetime.utcnow(),
                    ticker=t,
                    side=side,
                    quantity=qty,
                    price=price,
                    slippage_bps=settings.execution.slippage_bps,
                    commission_usd=settings.execution.commission_usd,
                    reason="auto",
                )
                await bus.publish({
                    "type": "trade",
                    "ts": datetime.utcnow().isoformat(),
                    "ticker": t,
                    "side": side,
                    "qty": qty,
                    "price": price,
                    "order_id": order.id,
                    "source": "auto",
                    "reason": "auto",
                })
        except Exception as e:
            await bus.publish({"type": "error", "message": str(e)})
        await asyncio.sleep(5)
