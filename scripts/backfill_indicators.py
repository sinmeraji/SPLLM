#!/usr/bin/env python
from __future__ import annotations

import os
from datetime import date, timedelta

from backend.app.core.db import SessionLocal
from backend.app.services.features import (
    recompute_indicators_for_date,
    recompute_intraday_indicators_last_90d,
)


TICKERS = [t.strip().upper() for t in os.getenv("TICKERS", "AAPL,MSFT").split(",") if t.strip()]
END = date.fromisoformat(os.getenv("END_DATE", date.today().isoformat()))
START = date.fromisoformat(os.getenv("START_DATE", (date(END.year - 2, END.month, END.day)).isoformat()))


def main() -> None:
    with SessionLocal() as db:
        total_daily = 0
        cur = START
        while cur <= END:
            if cur.weekday() < 5:  # skip weekends
                for t in TICKERS:
                    ok = recompute_indicators_for_date(db, ticker=t, d=cur)
                    if ok:
                        total_daily += 1
                        print(f"daily {t} {cur.isoformat()} ok")
                    else:
                        print(f"daily {t} {cur.isoformat()} skipped")
            cur = date.fromordinal(cur.toordinal() + 1)
        print(f"DONE daily_total={total_daily}")

        # Intraday: compute last 90d up to END once per ticker
        total_intra = 0
        for t in TICKERS:
            n = recompute_intraday_indicators_last_90d(db, ticker=t, as_of=END)
            total_intra += n
            print(f"intraday {t} last90d +{n}")
        print(f"DONE intraday_total={total_intra}")


if __name__ == "__main__":
    main()


