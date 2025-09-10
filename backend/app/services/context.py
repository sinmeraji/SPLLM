from __future__ import annotations

from datetime import date, time
from typing import Any, Dict, List

from ..providers.news import LocalCacheNewsProvider, NewsItem


def build_news_context(d: date, window_end: time, tickers: List[str]) -> Dict[str, Any]:
    provider = LocalCacheNewsProvider()
    items = provider.get_time_gated(d, window_end, tickers)

    # Group by ticker and take latest few for prompt compactness
    per_ticker: Dict[str, List[Dict[str, Any]]] = {}
    for it in sorted(items, key=lambda x: x.ts):
        per_ticker.setdefault(it.ticker, []).append({
            "ts": it.ts.isoformat(),
            "title": it.title,
            "url": it.url,
            "source": it.source,
            "sentiment": it.sentiment,
        })

    # Limit to last 5 items per ticker to keep prompt bounded
    limited = {t: arr[-5:] for t, arr in per_ticker.items()}
    return {"news": limited, "counts": {t: len(arr) for t, arr in per_ticker.items()}}


