"""
Engine: LLM trade proposal generator (OpenAI JSON-mode scaffold).
- propose_trades(context) returns typed Proposals from compact JSON response.
- Uses prompts under backend/app/prompts; respects OPENAI_API_KEY.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List
import os
import json
import httpx
from pathlib import Path
import logging


@dataclass
class Proposal:
    ticker: str
    action: str  # BUY or SELL
    quantity: float
    max_price: float | None = None
    min_price: float | None = None
    thesis: str | None = None
    horizon_days: int | None = None
    stop: float | None = None
    take_profit: float | None = None
    confidence: float | None = None


_last_usage: Dict[str, Any] = {}


def get_last_usage() -> Dict[str, Any]:
    return dict(_last_usage)


def propose_trades(context: Dict[str, Any]) -> List[Proposal]:
    """
    LLM stub: if OPENAI_API_KEY is present, this will later call the model.
    For now, returns an empty list to avoid trades without keys.
    """
    if not os.getenv("OPENAI_API_KEY"):
        return []
    # Minimal OpenAI call scaffold (JSON mode) — replace model as needed
    api_key = os.environ["OPENAI_API_KEY"]
    log = logging.getLogger(__name__)
    decision_path = Path("backend/app/prompts/decision.txt")
    decision_prompt = (
        decision_path.read_text(encoding="utf-8")
        if decision_path.exists()
        else "Propose trades as JSON with proposals[]."
    )
    try:
        log.info(
            "LLM prompts: decision=%s (system.txt disabled)",
            str(decision_path) if decision_path.exists() else "<default>",
        )
    except Exception:
        pass

    user_content = json.dumps({"context": context}, separators=(",", ":"))

    payload = {
        "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        "messages": [
            {"role": "system", "content": decision_prompt},
            {"role": "user", "content": user_content},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
    }
    try:
        # Log request preview (truncate long user content)
        preview = payload.copy()
        if isinstance(preview.get("messages"), list) and len(preview["messages"]) >= 2:
            # Append decision prompt visibly, and context JSON separately for easier inspection
            # Already included in messages as system/user, but keep a separate debug line
            pass
        log.debug("LLM decision prompt (system role) begins:\n%s\n---", decision_prompt[:4000])
        log.debug("LLM context JSON (user role) begins:\n%s\n---", user_content[:4000])
    except Exception:
        pass

    try:
        with httpx.Client(timeout=30) as client:
            r = client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
            content = data["choices"][0]["message"]["content"]
            try:
                log.debug(
                    "LLM raw content preview=%s",
                    (content[:2000] + "... [truncated]") if len(content) > 2000 else content,
                )
            except Exception:
                pass
            # capture usage for cost computation by callers
            try:
                global _last_usage
                _last_usage = data.get("usage", {}) or {}
                log.info(
                    "LLM usage prompt_tokens=%s completion_tokens=%s",
                    _last_usage.get("prompt_tokens"),
                    _last_usage.get("completion_tokens"),
                )
            except Exception:
                pass
            obj = json.loads(content)
            proposals_raw = (obj.get("proposals") or [])
            out: List[Proposal] = []
            for p in proposals_raw:
                try:
                    out.append(
                        Proposal(
                            ticker=str(p["ticker"]).upper(),
                            action=str(p["action"]).upper(),
                            quantity=float(p["quantity"]),
                            max_price=p.get("max_price"),
                            min_price=p.get("min_price"),
                            thesis=p.get("thesis"),
                            horizon_days=p.get("horizon_days"),
                            stop=p.get("stop"),
                            take_profit=p.get("take_profit"),
                            confidence=p.get("confidence"),
                        )
                    )
                except Exception:
                    continue
            try:
                log.info("LLM proposals count=%d", len(out))
            except Exception:
                pass
            return out
    except Exception as e:
        try:
            log.error("LLM call failed: %s", e)
        except Exception:
            pass
        return []
