from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.portfolio import Position


def position_count(db: Session) -> int:
    return db.query(Position).filter(Position.quantity > 0).count()


def tickers_with_positions(db: Session) -> list[str]:
    return [t for (t,) in db.query(Position.ticker).filter(Position.quantity > 0).all()]
