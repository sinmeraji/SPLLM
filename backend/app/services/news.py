"""
Service: news cache and incremental ingestion helpers.
- CSV append with dedupe (hash keys), provider state under data/news/.state.
- Utilities to read/write provider state for incremental pulls.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Iterable, List, Dict, Set
import csv
import hashlib
import json

from ..providers.news import NewsItem


STATE_DIR = Path("data/news/.state").resolve()


def _ensure_dirs() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    Path("data/news").mkdir(parents=True, exist_ok=True)


def _news_csv_path(d: date) -> Path:
    return Path("data/news") / f"{d.isoformat()}.csv"


def _state_path(provider: str, d: date) -> Path:
    return STATE_DIR / f"{provider}_{d.isoformat()}.json"


def compute_item_key(item: NewsItem) -> str:
    base = f"{item.ts.isoformat()}|{item.ticker}|{item.title}|{item.url}|{item.source}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def read_existing_keys(d: date) -> Set[str]:
    path = _news_csv_path(d)
    keys: Set[str] = set()
    if not path.exists():
        return keys
    with path.open("r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            try:
                ts = datetime.fromisoformat(row["ts"]) if row.get("ts") else None
                item = NewsItem(
                    ts=ts or datetime.combine(d, time(0, 0)),
                    ticker=(row.get("ticker") or "").upper(),
                    title=row.get("title") or "",
                    url=row.get("url") or "",
                    source=row.get("source") or "",
                    sentiment=float(row.get("sentiment")) if row.get("sentiment") else None,
                )
                keys.add(compute_item_key(item))
            except Exception:
                continue
    return keys


def append_news_items(d: date, items: Iterable[NewsItem]) -> Dict[str, int]:
    _ensure_dirs()
    path = _news_csv_path(d)
    header = ["ts", "ticker", "title", "url", "source", "sentiment"]
    write_header = not path.exists()

    existing = read_existing_keys(d)
    written = 0
    skipped = 0

    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        if write_header:
            w.writeheader()
        for it in items:
            key = compute_item_key(it)
            if key in existing:
                skipped += 1
                continue
            w.writerow({
                "ts": it.ts.isoformat(),
                "ticker": it.ticker,
                "title": it.title,
                "url": it.url,
                "source": it.source,
                "sentiment": "" if it.sentiment is None else f"{it.sentiment}",
            })
            existing.add(key)
            written += 1

    return {"written": written, "skipped": skipped}


def read_provider_state(provider: str, d: date) -> Dict:
    _ensure_dirs()
    sp = _state_path(provider, d)
    if not sp.exists():
        return {}
    try:
        return json.loads(sp.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_provider_state(provider: str, d: date, state: Dict) -> None:
    _ensure_dirs()
    sp = _state_path(provider, d)
    sp.write_text(json.dumps(state, separators=(",", ":")), encoding="utf-8")


