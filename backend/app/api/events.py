from __future__ import annotations

import asyncio
from datetime import datetime
from typing import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ..utils.events import bus

router = APIRouter()

async def event_stream() -> AsyncIterator[str]:
    # Emit immediate connection event so clients see activity right away
    yield "data: {\"type\":\"connected\",\"source\":\"sse\"}\n\n"
    async for msg in bus.subscribe():
        yield msg

@router.get('/events')
async def sse_events():
    return StreamingResponse(event_stream(), media_type='text/event-stream')
