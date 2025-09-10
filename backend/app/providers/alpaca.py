from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List
import os
import csv
import httpx
from zoneinfo import ZoneInfo

from .prices import Bar

ALPACA_DATA_URL = "https://data.alpaca.markets/v2/stocks"


def _auth_headers() -> dict:
    key = os.getenv("ALPACA_KEY_ID")
    secret = os.getenv("ALPACA_SECRET_KEY")
    if not key or not secret:
        raise RuntimeError("ALPACA_KEY_ID/ALPACA_SECRET_KEY not set")
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


async def fetch_minute_bars(ticker: str, start_iso: str, end_iso: str, limit: int = 10000) -> List[Bar]:
    url = f"{ALPACA_DATA_URL}/{ticker.upper()}/bars"
    params = {"timeframe": "1Min", "start": start_iso, "end": end_iso, "limit": limit}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url, headers=_auth_headers(), params=params)
        r.raise_for_status()
        data = r.json()
    items = data.get("bars") or []
    bars: List[Bar] = []
    for b in items:
        # Convert UTC to naive ET approximation by dropping tz; for backtest use ET-aware later
        ts = datetime.fromisoformat(b["t"].replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York")).replace(tzinfo=None)
        bars.append(Bar(ts=ts, open=b["o"], high=b["h"], low=b["l"], close=b["c"], volume=b.get("v", 0)))
    return bars


def save_bars_csv(ticker: str, bars: List[Bar]):
    if not bars:
        return
    outdir = Path("data/prices") / ticker.upper() / "minute"
    outdir.mkdir(parents=True, exist_ok=True)
    # group by date
    grouped = {}
    for b in bars:
        d = b.ts.date().isoformat()
        grouped.setdefault(d, []).append(b)
    for d, group in grouped.items():
        path = outdir / f"{d}.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["ts", "open", "high", "low", "close", "volume"])
            for b in group:
                w.writerow([b.ts.isoformat(), b.open, b.high, b.low, b.close, b.volume])
