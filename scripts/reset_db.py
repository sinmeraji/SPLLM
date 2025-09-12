#!/usr/bin/env python3
"""
Reset database schema (DANGER): drops ALL tables and recreates them.
Usage:
  # optional: source env first
  # set -a; . ./configs/env/.env; set +a
  python scripts/reset_db.py

Notes:
- Uses SQLAlchemy Base metadata to drop/create all tables registered under backend.app.models.
- SQLite DB path: backend/app/app.db
"""
from __future__ import annotations

import sys
from backend.app.core.db import engine
from backend.app.models import Base  # noqa: F401  (ensures all models are imported)


def main() -> None:
    print("Dropping all tables...")
    Base.metadata.drop_all(bind=engine)
    print("Creating all tables...")
    Base.metadata.create_all(bind=engine)
    print("Done.")


if __name__ == "__main__":
    main()


