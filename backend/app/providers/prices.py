from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
from typing import Iterable, List, Optional

import csv


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

    def get_five_minute_bars(self, ticker: str, d: date) -> List[Bar]:
        return []

    def get_daily_bars(self, ticker: str, start: date, end: date) -> List[Bar]:
        # TODO: implement daily via yfinance
        return []
