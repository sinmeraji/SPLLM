from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List
import os
import json
import httpx


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


def propose_trades(context: Dict[str, Any]) -> List[Proposal]:
    """
    LLM stub: if OPENAI_API_KEY is present, this will later call the model.
    For now, returns an empty list to avoid trades without keys.
    """
    if not os.getenv("OPENAI_API_KEY"):
        return []
    # Minimal OpenAI call scaffold (JSON mode) — replace model as needed
    api_key = os.environ["OPENAI_API_KEY"]
    system_prompt = (Path("backend/app/prompts/system.txt").read_text(encoding="utf-8")
                     if Path("backend/app/prompts/system.txt").exists() else "You are a cautious trading assistant.")
    decision_prompt = (Path("backend/app/prompts/decision.txt").read_text(encoding="utf-8")
                       if Path("backend/app/prompts/decision.txt").exists() else "Propose trades as JSON with proposals[].")
    user_content = json.dumps({"context": context}, separators=(",", ":"))

    payload = {
        "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": decision_prompt + "\n\n" + user_content},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
    }
    try:
        with httpx.Client(timeout=30) as client:
            r = client.post("https://api.openai.com/v1/chat/completions",
                            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                            json=payload)
            r.raise_for_status()
            data = r.json()
            content = data["choices"][0]["message"]["content"]
            obj = json.loads(content)
            proposals_raw = (obj.get("proposals") or [])
            out: List[Proposal] = []
            for p in proposals_raw:
                try:
                    out.append(Proposal(
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
                    ))
                except Exception:
                    continue
            return out
    except Exception:
        return []
