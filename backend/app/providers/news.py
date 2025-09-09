from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date, time
from pathlib import Path
from typing import List, Optional
import csv


@dataclass
class NewsItem:
    ts: datetime  # naive ET
    ticker: str
    title: str
    url: str
    source: str
    sentiment: Optional[float] = None


class NewsProvider:
    def get_time_gated(self, d: date, window_end: time, tickers: List[str]) -> List[NewsItem]:
        raise NotImplementedError


class LocalCacheNewsProvider(NewsProvider):
    """Reads from data/news/YYYY-MM-DD.csv with columns: ts,ticker,title,url,source,sentiment
    Filters by tickers and ts <= window_end of that day.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or Path("data/news").resolve())

    def get_time_gated(self, d: date, window_end: time, tickers: List[str]) -> List[NewsItem]:
        path = self.root / f"{d.isoformat()}.csv"
        items: List[NewsItem] = []
        if not path.exists():
            return items
        with path.open("r", newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                if row["ticker"].upper() not in set(t.upper() for t in tickers):
                    continue
                ts = datetime.fromisoformat(row["ts"])
                if ts.time() <= window_end:
                    items.append(
                        NewsItem(
                            ts=ts,
                            ticker=row["ticker"].upper(),
                            title=row.get("title", ""),
                            url=row.get("url", ""),
                            source=row.get("source", ""),
                            sentiment=float(row.get("sentiment")) if row.get("sentiment") else None,
                        )
                    )
        return items


# Placeholders for future remote providers (GDELT/EDGAR)
class GdeltProvider(NewsProvider):
    def get_time_gated(self, d: date, window_end: time, tickers: List[str]) -> List[NewsItem]:
        return []


class EdgarProvider(NewsProvider):
    def get_time_gated(self, d: date, window_end: time, tickers: List[str]) -> List[NewsItem]:
        return []
