#!/usr/bin/env python3
"""
Delete all rows from a specific table (DANGER).
Usage:
  python scripts/truncate_table.py <table_name>

Notes:
- Uses SQLAlchemy text('DELETE FROM {table}') for speed; no cascade checks.
- Ensure table name is valid; this does not do schema validation.
"""
from __future__ import annotations

import sys
from sqlalchemy import text
from backend.app.core.db import engine


def main() -> None:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print("Usage: python scripts/truncate_table.py <table_name>")
        raise SystemExit(2)
    table = sys.argv[1].strip()
    sql = text(f"DELETE FROM {table}")
    with engine.begin() as conn:
        conn.execute(sql)
    print(f"Truncated table: {table}")


if __name__ == "__main__":
    main()


