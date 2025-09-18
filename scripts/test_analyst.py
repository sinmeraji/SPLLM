#!/usr/bin/env python
"""
Script: Probe analyst provider (no DB writes)
Purpose:
- Calls the configured analyst provider for all universe tickers
  and prints a concise summary to console.
- Useful to verify FMP_API_KEY and endpoint health.

Usage:
  python -u scripts/test_analyst.py

Env:
  Reads configs/env/.env if present
  FMP_API_KEY (required for FMP)
  ANALYST_MAX_ITEMS (default 20)
"""
from __future__ import annotations

from pathlib import Path
import os
import json

from dotenv import load_dotenv

# Ensure local imports
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.providers.analyst import get_recent_for_ticker


def load_env() -> None:
    envp = ROOT / "configs" / "env" / ".env"
    if envp.exists():
        load_dotenv(dotenv_path=str(envp), override=False)


def load_universe() -> list[str]:
    fp = ROOT / "configs" / "universe" / "tickers.txt"
    if fp.exists():
        arr = [ln.strip().upper() for ln in fp.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if arr:
            return arr
    return ["AAPL", "MSFT", "NVDA", "QQQ"]


def main() -> None:
    load_env()
    key = os.getenv("FMP_API_KEY")
    if not key:
        print("ERROR: FMP_API_KEY not set. Please add it to configs/env/.env")
        raise SystemExit(1)
    tickers = load_universe()
    max_items = int(os.getenv("ANALYST_MAX_ITEMS", "20") or 20)
    print(f"Analyst probe: provider=FMP tickers={len(tickers)} max_items={max_items}")
    total = 0
    per_ticker_counts: dict[str, int] = {}
    for t in tickers:
        items = get_recent_for_ticker(t, limit=max_items)
        per_ticker_counts[t] = len(items)
        total += len(items)
        # Print a short preview per ticker
        preview = [
            {
                "ts": it.ts.isoformat(),
                "type": it.type,
                "firm": it.firm,
                "from": it.from_rating,
                "to": it.to_rating,
                "old_pt": it.old_pt,
                "new_pt": it.new_pt,
            }
            for it in items[:3]
        ]
        print(json.dumps({"ticker": t, "count": len(items), "preview": preview}, ensure_ascii=False))
    print(json.dumps({"summary_total_items": total, "per_ticker_counts": per_ticker_counts}, ensure_ascii=False))


if __name__ == "__main__":
    main()


