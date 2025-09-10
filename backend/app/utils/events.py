from __future__ import annotations

import asyncio
from typing import AsyncIterator, Dict
import json
import inspect

class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[str]] = set()

    async def publish(self, event: Dict) -> None:
        # Enrich with defaults to aid debugging
        if 'source' not in event:
            event['source'] = 'unknown'
        try:
            frm = inspect.stack()[1]
            event.setdefault('origin', f"{frm.filename}:{frm.lineno}")
        except Exception:
            pass
        payload = json.dumps(event, separators=(",", ":"))
        message = f"data: {payload}\n\n"
        for q in list(self._subscribers):
            await q.put(message)

    async def subscribe(self) -> AsyncIterator[str]:
        q: asyncio.Queue[str] = asyncio.Queue()
        self._subscribers.add(q)
        try:
            while True:
                msg = await q.get()
                yield msg
        finally:
            self._subscribers.discard(q)

bus = EventBus()
