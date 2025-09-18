"""
Provider: Analyst events via FMP (Financial Modeling Prep).
- Fetches recent upgrades/downgrades and price target changes per ticker.
- Requires env FMP_API_KEY.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from typing import List
import httpx


@dataclass
class AnalystItem:
    ts: datetime
    ticker: str
    type: str  # upgrade|downgrade|pt_raise|pt_cut
    firm: str
    from_rating: str
    to_rating: str
    old_pt: float
    new_pt: float
    source: str = "fmp"


def _fmp_get(path: str, params: dict) -> list:
    key = os.getenv("FMP_API_KEY", "")
    if not key:
        return []
    params = dict(params or {})
    params["apikey"] = key
    url = f"https://financialmodelingprep.com/api{path}"
    with httpx.Client(timeout=20) as client:
        r = client.get(url, params=params)
        r.raise_for_status()
        try:
            data = r.json()
        except Exception:
            return []
        return data if isinstance(data, list) else []


def get_recent_for_ticker(ticker: str, limit: int = 50) -> List[AnalystItem]:
    ticker = ticker.upper()
    out: List[AnalystItem] = []
    # 1) Upgrades/Downgrades
    try:
        ud = _fmp_get(f"/v3/upgrade-downgrade/{ticker}", {"limit": limit})
        for row in ud or []:
            try:
                dt = datetime.fromisoformat(str(row.get("publishedDate")).replace("Z", "+00:00")).replace(tzinfo=None)
                action = (row.get("action") or "").lower()
                ttype = "upgrade" if "up" in action else ("downgrade" if "down" in action else "rating_change")
                out.append(
                    AnalystItem(
                        ts=dt,
                        ticker=ticker,
                        type=ttype,
                        firm=row.get("analystCompany", ""),
                        from_rating=row.get("fromGrade", ""),
                        to_rating=row.get("toGrade", ""),
                        old_pt=0.0,
                        new_pt=0.0,
                    )
                )
            except Exception:
                continue
    except Exception:
        pass
    # 2) Price Target changes
    try:
        pt = _fmp_get(f"/v4/price-target-consensus", {"symbol": ticker})
        for row in pt or []:
            try:
                # FMP consensus has history; if available use 'publishedDate' and old/new
                dt_s = row.get("date") or row.get("publishedDate") or ""
                dt = datetime.fromisoformat(str(dt_s).replace("Z", "+00:00")).replace(tzinfo=None) if dt_s else datetime.utcnow()
                old_pt = float(row.get("priceTargetOld", 0) or 0)
                new_pt = float(row.get("priceTarget", 0) or 0)
                if new_pt and old_pt:
                    ttype = "pt_raise" if new_pt > old_pt else ("pt_cut" if new_pt < old_pt else "pt_flat")
                else:
                    ttype = "pt_update"
                out.append(
                    AnalystItem(
                        ts=dt,
                        ticker=ticker,
                        type=ttype,
                        firm=str(row.get("analystCompany") or ""),
                        from_rating="",
                        to_rating="",
                        old_pt=old_pt,
                        new_pt=new_pt,
                    )
                )
            except Exception:
                continue
    except Exception:
        pass
    return out


