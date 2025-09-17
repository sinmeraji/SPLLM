#!/usr/bin/env python
"""
Script: End-of-day updater for prices, indicators, and news metrics.
Purpose:
- For the last N business days (default N=1 for just today, ET), ensure completeness by:
  1) Ingesting ALL minute bars (market hours) and daily bars for each day (batching where possible)
  2) Recomputing daily indicators for that day
  3) Recomputing intraday indicators as-of that day (rolling last 90 days window)
  4) Fetching EOD news for that day and computing news metrics
  5) Applying retention after all days complete

Usage examples:
- DATE=YYYY-MM-DD TICKERS=AAPL,MSFT python scripts/eod_update.py
- EOD_UPDATE_LAST_N_DAYS=3 python scripts/eod_update.py
- NEWS_PROVIDERS=gdelt,edgar_submissions MINUTE_RETENTION_DAYS=60 DAILY_RETENTION_DAYS=730 python scripts/eod_update.py

Env vars:
- EOD_UPDATE_LAST_N_DAYS: integer window cap at 30 (default 1 = just today ET business day)
- DATE: ISO date (YYYY-MM-DD) anchor end date; defaults to today (ET)
- TICKERS: comma-separated tickers; else read from configs/universe/tickers.txt (defaults AAPL,MSFT,NVDA,QQQ)
- NEWS_PROVIDERS: gdelt,edgar,edgar_submissions (default: gdelt,edgar_submissions)
- MINUTE_RETENTION_DAYS: default 60
- DAILY_RETENTION_DAYS: default 730
"""
from __future__ import annotations

import os
from pathlib import Path
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
import logging

from dotenv import load_dotenv

# Ensure project imports resolve regardless of CWD
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.db import SessionLocal
from backend.app.utils.logging import setup_logging
from backend.app.services.prices_ingest import (
    ingest_provider_bars,
    ingest_provider_bars_multi,
    enforce_retention,
    synthesize_day_from_minutes,
    day_has_bars,
)
from backend.app.services.features import (
    recompute_indicators_for_date,
    recompute_intraday_indicators_last_30d_5m,
)
from backend.app.providers.news import GdeltProvider, EdgarProvider, EdgarSubmissionsProvider
from backend.app.services.news_db import upsert_news_items_to_db, compute_metrics_for_date


ET = ZoneInfo("America/New_York")


def _load_env() -> None:
    # Load explicit env file if present
    env_path = ROOT / "configs" / "env" / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=str(env_path), override=False)


def _load_tickers() -> list[str]:
    raw = os.getenv("TICKERS")
    if raw:
        return [t.strip().upper() for t in raw.split(",") if t.strip()]
    fp = ROOT / "configs" / "universe" / "tickers.txt"
    defaults = ["AAPL", "MSFT", "NVDA", "QQQ"]
    if fp.exists():
        vals = [t.strip().upper() for t in fp.read_text().splitlines() if t.strip()]
        return vals or defaults
    return defaults


def _load_date() -> date:
    raw = os.getenv("DATE")
    if raw:
        return date.fromisoformat(raw)
    return datetime.now(tz=ET).date()


def _load_window_n_days() -> int:
    try:
        n = int(os.getenv("EOD_UPDATE_LAST_N_DAYS", "1"))
    except Exception:
        n = 1
    if n < 1:
        n = 1
    if n > 30:
        n = 30
    return n


def _business_days_ending(end_d: date, n: int) -> list[date]:
    out: list[date] = []
    cur = end_d
    while len(out) < n:
        if cur.weekday() < 5:
            out.append(cur)
        cur = date.fromordinal(cur.toordinal() - 1)
    return list(reversed(out))


def _load_news_providers():
    names = [x.strip().lower() for x in os.getenv("NEWS_PROVIDERS", "gdelt,edgar_submissions").split(",") if x.strip()]
    out: list[tuple[object, str | None]] = []
    for name in names:
        if name == "gdelt":
            out.append((GdeltProvider(), None))
        elif name == "edgar":
            out.append((EdgarProvider(), "filings"))
        elif name in ("edgar_submissions", "edgar_json"):
            out.append((EdgarSubmissionsProvider(), "filings"))
    return out


def main() -> None:
    _load_env()
    setup_logging()
    log = logging.getLogger("scripts.eod_update")

    end_date = _load_date()
    n_days = _load_window_n_days()
    days = _business_days_ending(end_date, n_days)
    tickers = _load_tickers()
    providers = _load_news_providers()
    log.info(
        "EOD update start end_date=%s window=%s days=%s tickers=%s providers=%s",
        end_date.isoformat(), n_days, ",".join([d.isoformat() for d in days]), ",".join(tickers), ",".join([p.__class__.__name__ for p,_ in providers])
    )

    with SessionLocal() as db:
        # Process each business day in window
        for d_et in days:
            log.info("day begin %s", d_et.isoformat())
            # 1) Ingest MINUTE bars (market hours) for all tickers (batch)
            try:
                n_min = ingest_provider_bars_multi(db, provider="alpaca", tickers=tickers, d=d_et, timeframe="minute", skip_if_exists=False)
                log.info("minute ingest done date=%s rows=%s", d_et.isoformat(), n_min)
            except Exception as e:
                log.warning("minute ingest failed date=%s err=%s", d_et.isoformat(), e)

            # 1b) Ingest DAILY bars (batch), then synthesize missing per ticker from minutes
            try:
                n_day = ingest_provider_bars_multi(db, provider="alpaca", tickers=tickers, d=d_et, timeframe="day", skip_if_exists=False)
                miss = []
                for t in tickers:
                    if not day_has_bars(db, ticker=t, d=d_et, timeframe="day"):
                        try:
                            s = synthesize_day_from_minutes(db, ticker=t, d=d_et)
                            miss.append((t, s))
                        except Exception as ee:
                            log.warning("synthesize daily failed ticker=%s date=%s err=%s", t, d_et.isoformat(), ee)
                log.info("daily ingest done date=%s rows=%s synth_missing=%s", d_et.isoformat(), n_day, len([m for m in miss if m[1] > 0]))
            except Exception as e:
                log.warning("daily ingest failed date=%s err=%s", d_et.isoformat(), e)

            # 2) Recompute indicators for this day (daily)
            for t in tickers:
                try:
                    ok = recompute_indicators_for_date(db, ticker=t, d=d_et)
                    log.info("indicators daily ticker=%s date=%s ok=%s", t, d_et.isoformat(), bool(ok))
                except Exception as e:
                    log.warning("indicators daily failed ticker=%s date=%s err=%s", t, d_et.isoformat(), e)

            # 3) Recompute intraday indicators with 30d lookback on 5-min buckets as-of this day
            for t in tickers:
                try:
                    nrows = recompute_intraday_indicators_last_30d_5m(db, ticker=t, as_of=d_et)
                    log.info("indicators intraday(5m/30d) ticker=%s as_of=%s rows=%s", t, d_et.isoformat(), nrows)
                except Exception as e:
                    log.warning("indicators intraday failed ticker=%s as_of=%s err=%s", t, d_et.isoformat(), e)

            # 4) EOD news + metrics for the day
            for prov, explicit_type in providers:
                try:
                    items = prov.get_time_gated(d_et, time(23, 59), tickers)
                    upsert_news_items_to_db(db, items, explicit_type=explicit_type)
                    log.info("news upserted provider=%s items=%d date=%s", prov.__class__.__name__, len(items), d_et.isoformat())
                except Exception as e:
                    log.warning("news ingest failed provider=%s date=%s err=%s", prov.__class__.__name__, d_et.isoformat(), e)
            try:
                compute_metrics_for_date(db, d_et, tickers)
                log.info("news metrics computed date=%s", d_et.isoformat())
            except Exception as e:
                log.warning("news metrics compute failed date=%s err=%s", d_et.isoformat(), e)

            log.info("day done %s", d_et.isoformat())

        # 5) Enforce retention once at end
        try:
            minute_days = int(os.getenv("MINUTE_RETENTION_DAYS", "60"))
            day_days = int(os.getenv("DAILY_RETENTION_DAYS", "730"))
            stats = enforce_retention(db, minute_keep_days=minute_days, day_keep_days=day_days, tickers=tickers)
            log.info("retention applied deleted_minute=%s deleted_daily=%s", stats.get("deleted_minute"), stats.get("deleted_daily"))
        except Exception as e:
            log.warning("retention failed err=%s", e)

    log.info("EOD update done end_date=%s window=%s", end_date.isoformat(), n_days)


if __name__ == "__main__":
    main()


