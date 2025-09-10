from __future__ import annotations

from datetime import date
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
import asyncio

from ..core.db import SessionLocal
from ..sim.runner import run_backtest_range


router = APIRouter()


async def _backtest_task(start: date, end: date) -> None:
    # Use a fresh DB session inside the task
    with SessionLocal() as db:
        await run_backtest_range(db, start=start, end=end)


@router.post('/backtest')
async def start_backtest(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Kick off a backtest over a date range. Returns immediately with started=true."""
    try:
        start_s = payload.get('start')
        end_s = payload.get('end')
        if not start_s or not end_s:
            raise ValueError('Missing start or end')
        start_d = date.fromisoformat(start_s)
        end_d = date.fromisoformat(end_s)
    except Exception:
        raise HTTPException(status_code=400, detail='Invalid start/end')

    if end_d < start_d:
        start_d, end_d = end_d, start_d

    # Fire background task
    asyncio.create_task(_backtest_task(start_d, end_d))
    return {'started': True, 'start': start_d.isoformat(), 'end': end_d.isoformat()}


