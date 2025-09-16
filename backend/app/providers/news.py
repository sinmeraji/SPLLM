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
import email.utils as eutils
import json
import logging
import time as time_module


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
    _COMPANY_MAP: Dict[str, str] | None = None

    def _load_company_map(self) -> Dict[str, str]:
        if GdeltProvider._COMPANY_MAP is not None:
            return GdeltProvider._COMPANY_MAP
        cache_fp = Path("data/cache/sec_company_tickers.json")
        m: Dict[str, str] = {}
        try:
            if cache_fp.exists():
                data = __import__("json").loads(cache_fp.read_text(encoding="utf-8"))
            else:
                with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
                    r = client.get("https://www.sec.gov/files/company_tickers.json")
                    r.raise_for_status()
                    data = r.json()
                    cache_fp.parent.mkdir(parents=True, exist_ok=True)
                    cache_fp.write_text(__import__("json").dumps(data), encoding="utf-8")
            for v in data.values():
                t = str(v.get("ticker") or "").upper()
                nm = str(v.get("title") or "").strip()
                if t and nm:
                    m[t] = nm
        except Exception:
            m = {}
        GdeltProvider._COMPANY_MAP = m
        return m
    def get_time_gated(self, d: date, window_end: time, tickers: List[str]) -> List[NewsItem]:
        out: List[NewsItem] = []
        start = datetime(d.year, d.month, d.day, 0, 0, 0)
        end = datetime(d.year, d.month, d.day, window_end.hour, window_end.minute, window_end.second or 0)
        start_s = start.strftime("%Y%m%d%H%M%S")
        end_s = end.strftime("%Y%m%d%H%M%S")
        base = "https://api.gdeltproject.org/api/v2/doc/doc"
        headers = {
            "User-Agent": os.getenv("GDELT_USER_AGENT", "spllm/0.1 (gdelt)"),
            "Accept": "application/json",
        }
        timeout = httpx.Timeout(10.0)
        name_map = self._load_company_map()
        # Finance keywords to broaden results
        fin_kw = (
            "(stock OR shares OR earnings OR revenue OR eps OR guidance OR forecast OR "
            "upgrade OR downgrade OR rating OR buyback OR dividend OR split OR merger OR acquisition OR m&a OR lawsuit OR investigation OR antitrust OR "
            "sec OR filing OR 8-k OR 10-k OR 10-q OR results OR outlook)"
        )
        debug = str(os.getenv("GDELT_DEBUG", "0")).lower() in ("1", "true", "yes")
        batch_or = str(os.getenv("GDELT_BATCH_OR", "0")).lower() in ("1", "true", "yes")
        throttle_secs = int(os.getenv("GDELT_THROTTLE_SECS", "5") or "5")
        max_attempts = int(os.getenv("GDELT_MAX_ATTEMPTS", "3") or "3")
        backoff_mult = float(os.getenv("GDELT_BACKOFF_MULT", "2.0") or "2.0")
        with httpx.Client(timeout=timeout, headers=headers) as client:
            # Optional combined OR query to reduce rate-limited calls
            if batch_or and tickers:
                name_map = self._load_company_map()
                or_terms: List[str] = []
                for t in tickers:
                    nm = name_map.get(t.upper())
                    if nm:
                        or_terms.append(f'"{nm}"')
                    or_terms.append(t.upper())
                base_q = " OR ".join(or_terms[:40])  # cap to avoid URL length explosions
                q = f"(({base_q})) AND (sourcelang:english) AND {fin_kw}"
                params = {
                    "query": q,
                    "mode": "ArtList",
                    "format": "json",
                    "maxrecords": "250",
                    "sort": "DateDesc",
                    "startdatetime": start_s,
                    "enddatetime": end_s,
                }
                attempt = 0
                delay = max(throttle_secs, 5)
                while attempt < max_attempts:
                    attempt += 1
                    try:
                        r = client.get(base, params=params)
                        if debug:
                            logging.getLogger(__name__).debug(
                                "GDELT batch req url=%s status=%s attempt=%s", str(r.request.url), r.status_code, attempt
                            )
                        if r.status_code == 429:
                            if attempt < max_attempts:
                                if debug:
                                    logging.getLogger(__name__).warning(
                                        "GDELT batch 429 backing off %ss (attempt %s/%s)", delay, attempt, max_attempts
                                    )
                                time_module.sleep(delay)
                                delay = int(delay * backoff_mult)
                                continue
                        r.raise_for_status()
                        data = r.json()
                        arts = data.get("articles") or data.get("artList") or []
                        # Assign to tickers heuristically
                        for a in arts:
                            sd = a.get("seendate") or ""
                            try:
                                ts = datetime.strptime(sd, "%Y%m%d%H%M%S") if len(sd) == 14 else end
                            except Exception:
                                ts = end
                            title = (a.get("title") or "").strip()
                            url = a.get("url") or ""
                            source = a.get("sourceCommonName") or a.get("source") or "gdelt"
                            if ts.time() > window_end:
                                continue
                            title_l = title.lower()
                            for t in tickers:
                                nm = (name_map.get(t.upper()) or "").lower()
                                if (t.upper() in title) or (nm and nm in title_l):
                                    out.append(NewsItem(ts=ts, ticker=t.upper(), title=title, url=url, source=source))
                        break
                    except Exception:
                        if attempt < max_attempts:
                            time_module.sleep(delay)
                            delay = int(delay * backoff_mult)
                            continue
                        break
                # If batch mode used, return results now
                if out:
                    return out
                # fall through to per-ticker mode if batch returned nothing
            for t in tickers:
                nm = name_map.get(t.upper())
                base_q = f'"{nm}" OR {t}' if nm else t
                # Drop domain filter; require English and add finance keywords
                q = f"({base_q}) AND (sourcelang:english) AND {fin_kw}"
                params = {
                    "query": q,
                    "mode": "ArtList",
                    "format": "json",
                    # allow more results per ticker/day
                    "maxrecords": "250",
                    "sort": "DateDesc",
                    "startdatetime": start_s,
                    "enddatetime": end_s,
                }
                attempt = 0
                delay = max(throttle_secs, 5)
                while attempt < max_attempts:
                    attempt += 1
                    try:
                        r = client.get(base, params=params)
                        if debug:
                            try:
                                logging.getLogger(__name__).debug(
                                    "GDELT req ticker=%s url=%s status=%s attempt=%s",
                                    t,
                                    str(r.request.url),
                                    r.status_code,
                                    attempt,
                                )
                            except Exception:
                                pass
                        if r.status_code == 429:
                            if attempt < max_attempts:
                                if debug:
                                    logging.getLogger(__name__).warning(
                                        "GDELT 429 ticker=%s backing off %ss (attempt %s/%s)",
                                        t,
                                        delay,
                                        attempt,
                                        max_attempts,
                                    )
                                time_module.sleep(delay)
                                delay = int(delay * backoff_mult)
                                continue
                        r.raise_for_status()
                        data = r.json()
                        arts = data.get("articles") or data.get("artList") or []
                        if debug:
                            logging.getLogger(__name__).debug(
                                "GDELT resp ticker=%s count=%s keys=%s", t, len(arts), list(data.keys())
                            )
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
                        break  # success
                    except Exception:
                        if debug:
                            try:
                                snippet = r.text[:500] if 'r' in locals() else ''
                                logging.getLogger(__name__).warning(
                                    "GDELT error ticker=%s attempt=%s/%s status=%s bodySnippet=%s",
                                    t,
                                    attempt,
                                    max_attempts,
                                    getattr(r, 'status_code', 'NA'),
                                    snippet,
                                )
                            except Exception:
                                pass
                        if attempt < max_attempts:
                            time_module.sleep(delay)
                            delay = int(delay * backoff_mult)
                            continue
                        # give up on this ticker/day
                        break
                # space out calls across tickers to respect server guidance
                if throttle_secs > 0:
                    time_module.sleep(throttle_secs)
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
        # Cache submissions JSON per ticker to avoid repeated network calls during backfills
        self._submissions_cache: Dict[str, dict] = {}
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
                    # Use cached JSON if available for this process run
                    cache_key = t.upper()
                    if cache_key in self._submissions_cache:
                        data = self._submissions_cache[cache_key]
                    else:
                        url = base.format(cik=cik)
                        r = client.get(url)
                        r.raise_for_status()
                        data = r.json()
                        self._submissions_cache[cache_key] = data
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


class YahooRSSProvider(NewsProvider):
    """Fetch headlines from Yahoo Finance RSS for provided tickers (live only).
    Endpoint pattern: https://feeds.finance.yahoo.com/rss/2.0/headline?s={TICKER}&region=US&lang=en-US
    Note: RSS does not support historical date filters reliably; use for live ingestion.
    """

    def get_time_gated(self, d: date, window_end: time, tickers: List[str]) -> List[NewsItem]:
        out: List[NewsItem] = []
        timeout = httpx.Timeout(10.0)
        with httpx.Client(timeout=timeout, headers={"User-Agent": os.getenv("GDELT_USER_AGENT", "spllm/0.1 (yahoo) ")}) as client:
            for t in tickers:
                url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={t.upper()}&region=US&lang=en-US"
                try:
                    r = client.get(url)
                    r.raise_for_status()
                    root = ET.fromstring(r.text)
                    # Yahoo uses standard RSS 2.0
                    channel = root.find("channel")
                    if channel is None:
                        continue
                    for item in channel.findall("item"):
                        title_el = item.find("title")
                        link_el = item.find("link")
                        pub_el = item.find("pubDate")
                        title = title_el.text if title_el is not None else ""
                        link = link_el.text if link_el is not None else ""
                        ts = datetime(d.year, d.month, d.day, 12, 0, 0)
                        if pub_el is not None and pub_el.text:
                            try:
                                ts = eutils.parsedate_to_datetime(pub_el.text).astimezone(None).replace(tzinfo=None)
                            except Exception:
                                pass
                        if ts.date() == d and ts.time() <= window_end:
                            out.append(NewsItem(ts=ts, ticker=t.upper(), title=title or "", url=link or "", source="yahoo"))
                except Exception:
                    continue
        return out
