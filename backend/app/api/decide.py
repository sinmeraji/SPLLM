"""
API: decision endpoints (mock + LLM).
- /decide: mock execution with rule checks and SSE events.
- /decide/llm: builds context, calls LLM, applies accepted proposals, emits SSE.
"""
from __future__ import annotations

from datetime import datetime, time
from typing import Any, Dict, List, Optional
import json
import hashlib
import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.db import get_db
from ..services.rules import evaluate_order
from ..services.sim import apply_order, ensure_initialized, get_cash
from ..utils.events import bus
from ..services.context import build_news_context, build_decision_context
from ..engine.llm import propose_trades, Proposal
from ..models.llm import LLMCall, Decision


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
            # Emit decision event even when rejected so UI can reflect outcome
            await bus.publish({
                "type": "decision",
                "ts": ts.isoformat(),
                "ticker": t,
                "side": "BUY",
                "qty": 0.0,
                "price": ref_price,
                "accepted": False,
                "reasons": rule.reasons,
                "source": "decide",
                "reason": "decide-mock",
            })
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
            "accepted": True,
        })

    return {"results": results, "cash": cash}

@router.post('/decide/llm')
async def decide_with_llm(payload: Dict[str, Any], db: Session = Depends(get_db)) -> Dict[str, Any]:
    """LLM-driven decision using cached news context.
    payload: { tickers: [..], ts_et?: ISO, date?: YYYY-MM-DD }
    """
    ensure_initialized(db, settings.initial_cash_usd)
    tickers: List[str] = [t.upper() for t in (payload.get('tickers') or [])]
    if not tickers:
        raise HTTPException(status_code=400, detail='tickers required')
    ts_raw: Optional[str] = payload.get('ts_et')
    ts = datetime.fromisoformat(ts_raw) if ts_raw else datetime.utcnow()
    d_s: Optional[str] = payload.get('date')
    day = ts.date() if not d_s else datetime.fromisoformat(d_s).date()

    # Build full decision context
    ctx = build_decision_context(db, day, time(16, 0), tickers)
    # Call LLM to get proposals
    props: List[Proposal] = propose_trades(ctx)
    proposals_payload = [getattr(p, '__dict__', dict()) for p in props]

    # Persist LLMCall and Decision (pending; no execution here)
    req_json = json.dumps(ctx, separators=(",", ":"))
    resp_json = json.dumps({"proposals": proposals_payload}, separators=(",", ":"))
    req_hash = hashlib.sha1(req_json.encode('utf-8')).hexdigest()
    llm_call = LLMCall(
        ts=ts,
        request_hash=req_hash,
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        prompt_tokens=0,
        completion_tokens=0,
        cost_usd=0.0,
        request_json=req_json[:3900],
        response_json=resp_json[:3900],
    )
    db.add(llm_call)
    db.commit()
    db.refresh(llm_call)

    decision = Decision(
        ts=ts,
        window=ts.strftime("%H:%M"),
        tickers_json=json.dumps(tickers),
        proposals_json=json.dumps(proposals_payload),
        executed_json=json.dumps([]),
        cost_usd=0.0,
        llm_call_id=llm_call.id,
        prices_json=json.dumps(ctx.get("prices", {})),
    )
    db.add(decision)
    db.commit()
    db.refresh(decision)

    # Emit SSE recommendations event
    await bus.publish({
        "type": "decision_recommendations",
        "ts": ts.isoformat(),
        "decision_id": decision.id,
        "window": decision.window,
        "tickers": tickers,
        "count": len(proposals_payload),
    })
    return {"decision_id": decision.id, "proposals": proposals_payload}


@router.get('/decisions')
def list_decisions(limit: int = 50, db: Session = Depends(get_db)) -> Dict[str, Any]:
    q = db.query(Decision).order_by(Decision.ts.desc()).limit(max(1, min(limit, 200)))
    out = []
    for d in q.all():
        out.append({
            "id": d.id,
            "ts": d.ts.isoformat(),
            "window": d.window,
            "tickers": json.loads(d.tickers_json or "[]"),
            "proposals": json.loads(d.proposals_json or "[]"),
            "executed": json.loads(d.executed_json or "[]"),
            "cost_usd": d.cost_usd,
        })
    return {"items": out}


@router.get('/decisions/{decision_id}')
def get_decision(decision_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    d = db.query(Decision).filter(Decision.id == decision_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="decision not found")
    return {
        "id": d.id,
        "ts": d.ts.isoformat(),
        "window": d.window,
        "tickers": json.loads(d.tickers_json or "[]"),
        "proposals": json.loads(d.proposals_json or "[]"),
        "executed": json.loads(d.executed_json or "[]"),
        "cost_usd": d.cost_usd,
    }


@router.post('/decisions/{decision_id}/execute')
async def execute_decision(decision_id: int, payload: Dict[str, Any], db: Session = Depends(get_db)) -> Dict[str, Any]:
    d = db.query(Decision).filter(Decision.id == decision_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="decision not found")
    proposals = json.loads(d.proposals_json or "[]")
    selection = payload.get("selection")  # list of indices or None for all
    to_exec = proposals if not selection else [proposals[i] for i in selection if 0 <= i < len(proposals)]

    ts = datetime.utcnow()
    ensure_initialized(db, settings.initial_cash_usd)
    cash = get_cash(db)
    day_orders_count = 0
    executed: List[Dict[str, Any]] = json.loads(d.executed_json or "[]")

    for p in to_exec:
        ticker = str(p.get("ticker", "")).upper()
        side = str(p.get("action", "")).upper()
        qty = float(p.get("quantity", 0))
        ref_price = 100.0
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
            last_exit_time_by_ticker={},
        )
        if not rule.accepted:
            await bus.publish({
                "type": "decision",
                "ts": ts.isoformat(),
                "ticker": ticker,
                "side": side,
                "qty": 0.0,
                "price": ref_price,
                "accepted": False,
                "reasons": rule.reasons,
                "source": "llm",
                "reason": "llm-decision",
            })
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
            reason='llm-exec',
        )
        day_orders_count += 1
        cash = get_cash(db)
        executed.append({"ticker": ticker, "side": side, "order_id": order.id, "qty": rule.adjusted_quantity, "price": ref_price})
        await bus.publish({
            "type": "trade",
            "ts": ts.isoformat(),
            "ticker": ticker,
            "side": side,
            "qty": rule.adjusted_quantity,
            "price": ref_price,
            "order_id": order.id,
            "source": "llm",
            "reason": "llm-exec",
            "accepted": True,
        })

    d.executed_json = json.dumps(executed)
    db.commit()
    await bus.publish({"type": "decision_executed", "decision_id": d.id, "count": len(executed)})
    return {"decision_id": d.id, "executed_count": len(executed), "executed": executed}


