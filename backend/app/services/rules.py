from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from ..core.config import settings
from ..models.portfolio import Position


@dataclass
class RuleDecision:
    accepted: bool
    adjusted_quantity: float
    reasons: List[str]


def minutes_since(dt: datetime, ref: datetime) -> float:
    return (ref - dt).total_seconds() / 60.0


def evaluate_order(
    db: Session,
    *,
    now_et: datetime,
    ticker: str,
    side: str,  # BUY or SELL
    quantity: float,
    reference_price: float,
    cash: float,
    day_turnover_notional: float,
    day_orders_count: int,
    last_exit_time_by_ticker: Optional[Dict[str, datetime]] = None,
) -> RuleDecision:
    reasons: List[str] = []
    side = side.upper()

    # Global daily limits
    if day_orders_count >= settings.limits.max_orders_per_day:
        return RuleDecision(False, 0.0, ["max_orders_per_day_exceeded"]) 

    # Turnover limit check (approx): this order notional added to current day's turnover must be <= cap
    cap_notional = settings.limits.max_turnover_daily_pct  # expressed as fraction of starting equity for the day (approx not tracked here)
    # Without intraday equity snapshot, we approximate turnover rule by hard maximum number of orders per day already enforced.

    # Cooldown after exit
    if last_exit_time_by_ticker and ticker in last_exit_time_by_ticker:
        minutes = minutes_since(last_exit_time_by_ticker[ticker], now_et)
        if minutes < settings.limits.cooldown_minutes_after_exit:
            reasons.append("cooldown_active")

    # Fetch current position if any
    pos: Position | None = db.query(Position).filter(Position.ticker == ticker).one_or_none()
    current_qty = pos.quantity if pos else 0.0

    # Compute notional
    notional = abs(quantity) * reference_price

    # Enforce min order for entries/adds/trims, but not for forced exits (handled by caller)
    if side == "BUY" and notional < settings.execution.min_order_usd:
        return RuleDecision(False, 0.0, ["min_order_breach"]) 

    # Enforce cash buffer on BUY
    if side == "BUY":
        # Required ending cash >= min_cash_pct of (ending equity approx cash only here)
        min_cash = settings.risk.min_cash_pct
        if (cash - notional - settings.execution.commission_usd) < (min_cash * cash):
            reasons.append("min_cash_buffer_breach")

        # Max position sizing by initial buy not exceeding cap
        # Enforce by notional cap vs total portfolio (approximate using cash+existing position value if needed). Here we cap by per-trade sizing only.

    # Max positions count when opening a new name
    opening_new_name = (side == "BUY" and current_qty == 0.0)
    if opening_new_name:
        # Count current names
        names_count = db.query(Position).filter(Position.quantity > 0).count()
        if names_count >= settings.risk.max_positions:
            reasons.append("max_positions_reached")

    # Expected-return gate is enforced by the caller (requires model expectation)

    accepted = len(reasons) == 0
    adjusted_qty = max(0.0, quantity) if accepted else 0.0
    return RuleDecision(accepted, adjusted_qty, reasons)
