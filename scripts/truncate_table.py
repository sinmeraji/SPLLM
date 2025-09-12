#!/usr/bin/env python3
"""
Delete all rows from a specific table (DANGER).
Usage:
  TABLE=news_raw python scripts/truncate_table.py

Notes:
- Uses SQLAlchemy text('DELETE FROM {table}') for speed; no cascade checks.
- Ensure table name is valid; this does not do schema validation.
"""
from __future__ import annotations

import os
from sqlalchemy import text
from backend.app.core.db import engine


def main() -> None:
    table = os.getenv("TABLE")
    if not table:
        raise SystemExit("Set TABLE=<name>")
    sql = text(f"DELETE FROM {table}")
    with engine.begin() as conn:
        conn.execute(sql)
    print(f"Truncated table: {table}")


if __name__ == "__main__":
    main()


