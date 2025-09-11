"""
Providers: news sources (local cache, GDELT, EDGAR).
- LocalCacheNewsProvider reads CSV cache under data/news by day.
- GdeltProvider fetches headlines from GDELT Doc API v2.
- EdgarProvider fetches recent filings via EDGAR Atom feeds.
- EdgarSubmissionsProvider fetches filings via EDGAR Submissions JSON (better for historical/backfill).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date, time
from pathlib import Path
from typing import List, Optional, Dict
import csv
import os
import httpx
from urllib.parse import urlencode
import xml.etree.ElementTree as ET


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
    """Fetches articles from GDELT Doc API v2 for provided tickers within the date/window.
    API: https://api.gdeltproject.org/api/v2/doc/doc?query=...&mode=ArtList&format=json
    """
    def get_time_gated(self, d: date, window_end: time, tickers: List[str]) -> List[NewsItem]:
        out: List[NewsItem] = []
        start = datetime(d.year, d.month, d.day, 0, 0, 0)
        end = datetime(d.year, d.month, d.day, window_end.hour, window_end.minute, window_end.second or 0)
        start_s = start.strftime("%Y%m%d%H%M%S")
        end_s = end.strftime("%Y%m%d%H%M%S")
        base = "https://api.gdeltproject.org/api/v2/doc/doc"
        headers = {"User-Agent": os.getenv("GDELT_USER_AGENT", "spllm/0.1 (gdelt)")}
        timeout = httpx.Timeout(10.0)
        with httpx.Client(timeout=timeout, headers=headers) as client:
            for t in tickers:
                q = t
                params = {
                    "query": q,
                    "mode": "ArtList",
                    "format": "json",
                    "maxrecords": "75",
                    "startdatetime": start_s,
                    "enddatetime": end_s,
                }
                try:
                    r = client.get(base, params=params)
                    r.raise_for_status()
                    data = r.json()
                    arts = data.get("articles") or data.get("artList") or []
                    for a in arts:
                        # seendate like 20250102101000
                        sd = a.get("seendate") or ""
                        try:
                            ts = datetime.strptime(sd, "%Y%m%d%H%M%S") if len(sd) == 14 else end
                        except Exception:
                            ts = end
                        title = a.get("title") or ""
                        url = a.get("url") or ""
                        source = a.get("sourceCommonName") or a.get("source") or "gdelt"
                        if ts.time() <= window_end:
                            out.append(NewsItem(ts=ts, ticker=t.upper(), title=title, url=url, source=source))
                except Exception:
                    # best-effort; continue other tickers
                    continue
        return out


class EdgarProvider(NewsProvider):
    """Fetch latest SEC filings via EDGAR Atom feeds per ticker.
    Endpoint: https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={ticker}&owner=exclude&count=40&output=atom
    """
    def get_time_gated(self, d: date, window_end: time, tickers: List[str]) -> List[NewsItem]:
        out: List[NewsItem] = []
        ua = os.getenv("SEC_USER_AGENT", "spllm/0.1 (edgar)")
        headers = {"User-Agent": ua, "Accept": "application/atom+xml"}
        timeout = httpx.Timeout(10.0)
        base = "https://www.sec.gov/cgi-bin/browse-edgar"
        with httpx.Client(timeout=timeout, headers=headers) as client:
            for t in tickers:
                params = {
                    "action": "getcompany",
                    "CIK": t,
                    "owner": "exclude",
                    "count": "40",
                    "output": "atom",
                }
                try:
                    r = client.get(base, params=params)
                    r.raise_for_status()
                    root = ET.fromstring(r.text)
                    ns = {"a": "http://www.w3.org/2005/Atom"}
                    for entry in root.findall("a:entry", ns):
                        title_el = entry.find("a:title", ns)
                        updated_el = entry.find("a:updated", ns)
                        link_el = entry.find("a:link", ns)
                        title = title_el.text if title_el is not None else ""
                        link = link_el.get("href") if link_el is not None else ""
                        ts = None
                        if updated_el is not None and updated_el.text:
                            try:
                                # updated is ISO8601 Zulu; convert naive
                                ts = datetime.fromisoformat(updated_el.text.replace("Z", "+00:00")).astimezone(None).replace(tzinfo=None)
                            except Exception:
                                ts = datetime(d.year, d.month, d.day)
                        ts = ts or datetime(d.year, d.month, d.day)
                        if ts.date() == d and ts.time() <= window_end:
                            out.append(NewsItem(ts=ts, ticker=t.upper(), title=title, url=link, source="edgar"))
                except Exception:
                    continue
        return out


class EdgarSubmissionsProvider(NewsProvider):
    """Fetch filings via EDGAR Submissions JSON per company CIK.
    Uses the SEC-provided `company_tickers.json` mapping to resolve ticker->CIK.
    Mapping is cached under data/cache/sec_company_tickers.json.
    Docs: https://www.sec.gov/edgar/sec-api-documentation
    """

    MAP_URL = "https://www.sec.gov/files/company_tickers.json"

    def __init__(self) -> None:
        self.ua = os.getenv("SEC_USER_AGENT", "spllm/0.1 (edgar-submissions)")
        self._map_cache: Dict[str, str] = {}
        self._ensure_mapping()

    def _ensure_mapping(self) -> None:
        cache_dir = Path("data/cache").resolve()
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_fp = cache_dir / "sec_company_tickers.json"
        if cache_fp.exists():
            try:
                data = json.loads(cache_fp.read_text(encoding="utf-8"))
                self._map_cache = {str(v["ticker"]).upper(): str(v["cik_str"]).zfill(10) for v in data.values()}
                return
            except Exception:
                pass
        # Fetch fresh mapping
        try:
            with httpx.Client(timeout=httpx.Timeout(15.0), headers={"User-Agent": self.ua}) as client:
                r = client.get(self.MAP_URL)
                r.raise_for_status()
                data = r.json()
                cache_fp.write_text(json.dumps(data), encoding="utf-8")
                self._map_cache = {str(v["ticker"]).upper(): str(v["cik_str"]).zfill(10) for v in data.values()}
        except Exception:
            # Leave map empty if failed; provider will no-op
            self._map_cache = {}

    def _cik_for(self, ticker: str) -> Optional[str]:
        return self._map_cache.get(ticker.upper())

    def get_time_gated(self, d: date, window_end: time, tickers: List[str]) -> List[NewsItem]:
        out: List[NewsItem] = []
        headers = {"User-Agent": self.ua, "Accept": "application/json"}
        base = "https://data.sec.gov/submissions/CIK{cik}.json"
        with httpx.Client(timeout=httpx.Timeout(15.0), headers=headers) as client:
            for t in tickers:
                cik = self._cik_for(t)
                if not cik:
                    continue
                try:
                    url = base.format(cik=cik)
                    r = client.get(url)
                    r.raise_for_status()
                    data = r.json()
                    # recent filings arrays are parallel
                    recent = (data.get("filings") or {}).get("recent") or {}
                    forms = recent.get("form") or []
                    dates = recent.get("filingDate") or []
                    accs = recent.get("accessionNumber") or []
                    prim_docs = recent.get("primaryDocument") or []
                    for form, fdate, acc, pdoc in zip(forms, dates, accs, prim_docs):
                        try:
                            ts = datetime.fromisoformat(fdate)
                        except Exception:
                            # fallback to day at noon
                            ts = datetime(d.year, d.month, d.day, 12, 0, 0)
                        if ts.date() != d or ts.time() > window_end:
                            continue
                        acc_nodashes = str(acc).replace("-", "")
                        doc_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_nodashes}/{pdoc}"
                        title = f"{t} {form} filing"
                        out.append(NewsItem(ts=ts, ticker=t.upper(), title=title, url=doc_url, source="edgar"))
                except Exception:
                    continue
        return out
