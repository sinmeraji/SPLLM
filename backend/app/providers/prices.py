from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
from typing import Iterable, List, Optional

import csv
import os
import httpx


@dataclass
class Bar:
    ts: datetime  # naive ET assumed
    open: float
    high: float
    low: float
    close: float
    volume: float


class PriceProvider:
    def get_minute_bars(self, ticker: str, d: date) -> List[Bar]:
        raise NotImplementedError

    def get_five_minute_bars(self, ticker: str, d: date) -> List[Bar]:
        raise NotImplementedError

    def get_daily_bars(self, ticker: str, start: date, end: date) -> List[Bar]:
        raise NotImplementedError


class LocalCachePriceProvider(PriceProvider):
    """Reads CSVs from data/prices/<ticker>/(minute|5min|daily)/YYYY-MM-DD.csv
    Columns: ts,open,high,low,close,volume (ts in ISO without tz, ET)
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or Path("data/prices").resolve())

    def _read_bars_file(self, path: Path) -> List[Bar]:
        bars: List[Bar] = []
        if not path.exists():
            return bars
        with path.open("r", newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                bars.append(
                    Bar(
                        ts=datetime.fromisoformat(row["ts"]),
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row.get("volume", 0.0) or 0.0),
                    )
                )
        return bars

    def get_minute_bars(self, ticker: str, d: date) -> List[Bar]:
        path = self.root / ticker.upper() / "minute" / f"{d.isoformat()}.csv"
        return self._read_bars_file(path)

    def get_five_minute_bars(self, ticker: str, d: date) -> List[Bar]:
        path = self.root / ticker.upper() / "5min" / f"{d.isoformat()}.csv"
        return self._read_bars_file(path)

    def get_daily_bars(self, ticker: str, start: date, end: date) -> List[Bar]:
        # optional: implement daily cache as multiple files or a single CSV per ticker
        daily_dir = self.root / ticker.upper() / "daily"
        bars: List[Bar] = []
        cur = start
        while cur <= end:
            p = daily_dir / f"{cur.isoformat()}.csv"
            bars.extend(self._read_bars_file(p))
            cur = date.fromordinal(cur.toordinal() + 1)
        return bars


# Placeholders for future remote providers
class AlpacaPriceProvider(PriceProvider):
    def get_minute_bars(self, ticker: str, d: date) -> List[Bar]:
        # TODO: implement using Alpaca Market Data
        return []

    def get_five_minute_bars(self, ticker: str, d: date) -> List[Bar]:
        return []

    def get_daily_bars(self, ticker: str, start: date, end: date) -> List[Bar]:
        return []


class YahooDailyPriceProvider(PriceProvider):
    def get_minute_bars(self, ticker: str, d: date) -> List[Bar]:
        return []


def get_latest_trade_price_alpaca(ticker: str) -> Optional[float]:
    """
    Return latest trade price from Alpaca Market Data v2 for the ticker.
    Requires env ALPACA_KEY_ID and ALPACA_SECRET_KEY. Returns None on error.
    """
    key = os.getenv("ALPACA_KEY_ID")
    secret = os.getenv("ALPACA_SECRET_KEY")
    if not key or not secret:
        return None
    url = f"https://data.alpaca.markets/v2/stocks/{ticker.upper()}/trades/latest"
    feed = os.getenv("ALPACA_FEED", "iex")
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    params = {"feed": feed}
    try:
        with httpx.Client(timeout=5) as client:
            r = client.get(url, params=params, headers=headers)
            r.raise_for_status()
            data = r.json()
            trade = data.get("trade") or {}
            p = trade.get("p")
            return float(p) if p is not None else None
    except Exception:
        return None

    def get_five_minute_bars(self, ticker: str, d: date) -> List[Bar]:
        return []

    def get_daily_bars(self, ticker: str, start: date, end: date) -> List[Bar]:
        # TODO: implement daily via yfinance
        return []
