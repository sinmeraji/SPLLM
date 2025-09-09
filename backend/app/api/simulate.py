from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.db import get_db
from ..services.rules import evaluate_order
from ..services.sim import apply_order, get_cash, ensure_initialized


sim_router = APIRouter()


@sim_router.post("/simulate")
def simulate_orders(payload: Dict[str, Any], db: Session = Depends(get_db)):
    """
    Accepts a proposals payload (LLM or otherwise), applies rules, and executes accepted orders.
    Payload example matches configs/schemas/decision.schema.json.
    """
    ensure_initialized(db, settings.initial_cash_usd)

    decision_time = payload.get("decision_time")
    ts = datetime.fromisoformat(decision_time) if decision_time else datetime.utcnow()
    proposals: List[Dict[str, Any]] = payload.get("proposals", [])

    results: List[Dict[str, Any]] = []
    cash = get_cash(db)
    day_orders_count = 0
    last_exit_map: Dict[str, datetime] = {}

    for p in proposals:
        ticker = p["ticker"].upper()
        side = p["action"].upper()
        qty = float(p["quantity"])
        ref_price = float(p.get("ref_price") or p.get("max_price") or p.get("min_price") or 0.0)
        reason = p.get("reason", "llm")

        rule = evaluate_order(
            db,
            now_et=ts,
            ticker=ticker,
            side=side,
            quantity=qty,
            reference_price=ref_price,
            cash=cash,
            day_turnover_notional=0.0,
            day_orders_count=day_orders_count,
            last_exit_time_by_ticker=last_exit_map,
        )
        if not rule.accepted:
            results.append({"ticker": ticker, "side": side, "accepted": False, "reasons": rule.reasons})
            continue

        order = apply_order(
            db,
            ts_et=ts,
            ticker=ticker,
            side=side,
            quantity=rule.adjusted_quantity,
            price=ref_price,
            slippage_bps=settings.execution.slippage_bps,
            commission_usd=settings.execution.commission_usd,
            reason=reason,
        )
        day_orders_count += 1
        cash = get_cash(db)
        if side == "SELL":
            last_exit_map[ticker] = ts
        results.append({"ticker": ticker, "side": side, "accepted": True, "order_id": order.id})

    return {"results": results, "cash": cash}
