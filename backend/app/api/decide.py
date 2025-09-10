from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.db import get_db
from ..services.rules import evaluate_order
from ..services.sim import apply_order, ensure_initialized, get_cash
from ..utils.events import bus


router = APIRouter()


@router.post('/decide')
async def decide_and_execute(payload: Dict[str, Any], db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Mock decision endpoint. Generates simple BUY/SELL proposals and executes those passing rules.

    payload: {
      "tickers": ["AAPL","MSFT"],
      "ts_et": "2025-01-02T10:00:00",
      "mode": "mock"
    }
    """
    ensure_initialized(db, settings.initial_cash_usd)

    tickers: List[str] = [t.upper() for t in (payload.get('tickers') or [])]
    if not tickers:
        raise HTTPException(status_code=400, detail='tickers required')

    ts_raw: Optional[str] = payload.get('ts_et')
    ts = datetime.fromisoformat(ts_raw) if ts_raw else datetime.utcnow()

    # Simple mock: BUY 1 share of up to first 2 tickers if rules allow
    results: List[Dict[str, Any]] = []
    cash = get_cash(db)
    day_orders_count = 0
    for t in tickers[:2]:
        ref_price = 100.0  # mock reference
        rule = evaluate_order(
            db,
            now_et=ts,
            ticker=t,
            side='BUY',
            quantity=10.0,  # $1,000 notional at $100 to satisfy min order
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
        # Emit trade event
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


