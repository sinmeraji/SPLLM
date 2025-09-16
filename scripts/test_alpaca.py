#!/usr/bin/env python
"""
Script: Test connectivity to Alpaca Market Data API.
Purpose:
- Verifies that ALPACA_KEY_ID and ALPACA_SECRET_KEY work against the v2 market data endpoint.

Usage:
- python scripts/test_alpaca.py
- Optionally set env via configs/env/.env (auto-loaded if present).

Exit codes:
- 0 on success, 1 on failure.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv


def load_env() -> None:
    # Load central env file if available
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "configs", "env", ".env")
    if os.path.exists(env_path):
        load_dotenv(dotenv_path=env_path, override=False)


def test_alpaca_connectivity() -> None:
    key = os.getenv("ALPACA_KEY_ID")
    secret = os.getenv("ALPACA_SECRET_KEY")
    if not key or not secret:
        raise SystemExit("ALPACA_KEY_ID/ALPACA_SECRET_KEY not set")

    # Request a tiny 1Day bars window for a liquid symbol
    ET = ZoneInfo("America/New_York")
    d = datetime.now(tz=ET).date()
    start_dt = datetime.combine(d - timedelta(days=5), time(9, 30), tzinfo=ET).astimezone(ZoneInfo("UTC"))
    end_dt = datetime.combine(d, time(16, 0), tzinfo=ET).astimezone(ZoneInfo("UTC"))
    feed = os.getenv("ALPACA_FEED", "iex")
    params = {
        "start": start_dt.isoformat().replace("+00:00", "Z"),
        "end": end_dt.isoformat().replace("+00:00", "Z"),
        "timeframe": "1Day",
        "limit": 1,
        "adjustment": "raw",
        "feed": feed,
    }
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    url = "https://data.alpaca.markets/v2/stocks/AAPL/bars"
    with httpx.Client(timeout=10) as client:
        r = client.get(url, params=params, headers=headers)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict) or "bars" not in data:
            raise SystemExit("Unexpected response structure from Alpaca")


if __name__ == "__main__":
    load_env()
    try:
        test_alpaca_connectivity()
    except Exception as e:
        print(f"Alpaca connectivity: FAIL ({e})")
        raise SystemExit(1)
    print("Alpaca connectivity: OK")
    raise SystemExit(0)


