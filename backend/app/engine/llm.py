"""
Engine: LLM trade proposal generator (OpenAI JSON-mode scaffold).
- propose_trades(context): calls OpenAI with JSON response format.
- Supports chat.completions; falls back to responses API on 400 errors.
- Respects OPENAI_API_KEY and OPENAI_MODEL.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
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


def _parse_json_content(text: str) -> Dict[str, Any]:
    try:
        return json.loads(text)
    except Exception:
        return {}


def _call_chat_completions(api_key: str, model: str, decision_prompt: str, user_content: str, log) -> Optional[List[Proposal]]:
    is_gpt5 = model.lower().startswith("gpt-5")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": decision_prompt},
            {"role": "user", "content": user_content},
        ],
        "response_format": {"type": "json_object"},
    }
    # Some GPT-5 variants only accept default temperature; omit if gpt-5
    if not is_gpt5:
        payload["temperature"] = float(os.getenv("OPENAI_TEMPERATURE", "0.2"))
    timeout_secs = float(os.getenv("OPENAI_TIMEOUT_SECS", "180"))
    with httpx.Client(timeout=timeout_secs) as client:
        import time
        t0 = time.perf_counter()
        r = client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        try:
            r.raise_for_status()
        except Exception:
            try:
                log.error("chat.completions error status=%s body=%s", r.status_code, r.text[:800])
            except Exception:
                pass
            return None
        data = r.json()
        try:
            proc_ms = r.headers.get("openai-processing-ms") or r.headers.get("x-openai-processing-ms")
            dt = (time.perf_counter() - t0) * 1000.0
            log.info("LLM chat.completions processing_ms=%s roundtrip_ms=%.0f", str(proc_ms), dt)
        except Exception:
            pass
        content = data["choices"][0]["message"]["content"]
        try:
            log.debug("LLM raw content (chat) first_1000=\n%s", content[:1000])
        except Exception:
            pass
        obj = _parse_json_content(content)
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
            global _last_usage
            _last_usage = data.get("usage", {}) or {}
            log.info("LLM usage prompt_tokens=%s completion_tokens=%s", _last_usage.get("prompt_tokens"), _last_usage.get("completion_tokens"))
        except Exception:
            pass
        try:
            log.debug("LLM parsed proposals n=%d sample=%s", len(out), [getattr(p, '__dict__', {}) for p in out[:3]])
        except Exception:
            pass
        return out


def _call_responses(api_key: str, model: str, decision_prompt: str, user_content: str, log) -> Optional[List[Proposal]]:
    # Responses API: send system+user as input list; request JSON via text.format
    is_gpt5 = model.lower().startswith("gpt-5")
    payload = {
        "model": model,
        "input": [
            {"role": "system", "content": decision_prompt},
            {"role": "user", "content": user_content},
        ],
        "text": {"format": "json"},
    }
    if not is_gpt5:
        payload["temperature"] = float(os.getenv("OPENAI_TEMPERATURE", "0.2"))
    timeout_secs = float(os.getenv("OPENAI_TIMEOUT_SECS", "180"))
    with httpx.Client(timeout=timeout_secs) as client:
        import time
        t0 = time.perf_counter()
        r = client.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        try:
            r.raise_for_status()
        except Exception:
            try:
                log.error("responses error status=%s body=%s", r.status_code, r.text[:800])
            except Exception:
                pass
            return None
        data = r.json()
        try:
            proc_ms = r.headers.get("openai-processing-ms") or r.headers.get("x-openai-processing-ms")
            dt = (time.perf_counter() - t0) * 1000.0
            log.info("LLM responses processing_ms=%s roundtrip_ms=%.0f", str(proc_ms), dt)
        except Exception:
            pass
        # Try multiple shapes used by responses API
        text: Optional[str] = None
        try:
            # unified helper field when available
            text = data.get("output_text")
        except Exception:
            text = None
        if not text:
            try:
                # structured content path
                outputs = data.get("output") or data.get("outputs") or []
                if outputs and isinstance(outputs, list):
                    parts = outputs[0].get("content") or []
                    if parts and isinstance(parts, list):
                        text = parts[0].get("text")
            except Exception:
                text = None
        if not text:
            # fallback: try top-level content
            try:
                text = data.get("content")
            except Exception:
                text = None
        if not text or not isinstance(text, str):
            try:
                log.error("responses parse failure; unknown schema keys=%s", list(data.keys()))
            except Exception:
                pass
            return None
        try:
            log.debug("LLM raw content (responses) first_1000=\n%s", text[:1000])
        except Exception:
            pass
        obj = _parse_json_content(text)
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
            global _last_usage
            _last_usage = data.get("usage", {}) or {}
        except Exception:
            pass
        try:
            log.debug("LLM parsed proposals n=%d sample=%s", len(out), [getattr(p, '__dict__', {}) for p in out[:3]])
        except Exception:
            pass
        return out


def propose_trades(context: Dict[str, Any]) -> List[Proposal]:
    """
    LLM stub: if OPENAI_API_KEY is present, this will later call the model.
    For now, returns an empty list to avoid trades without keys.
    """
    if not os.getenv("OPENAI_API_KEY"):
        return []
    # Minimal OpenAI call scaffold (JSON mode) — supports chat & responses
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

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    try:
        # Debug: show prompt and compact context preview
        log.debug("LLM decision prompt (system role) begins:\n%s\n---", decision_prompt[:4000])
        log.debug("LLM context JSON (user role) begins:\n%s\n---", user_content[:4000])
        news_briefs = (context or {}).get("news", {})
        news_dict = (news_briefs or {}).get("news") or {}
        news_items = sum(len(v) for v in news_dict.values()) if isinstance(news_dict, dict) else 0
        log.debug(
            "LLM context includes news tickers=%d items=%d",
            len(news_dict) if isinstance(news_dict, dict) else 0,
            news_items,
        )
        nm = (context or {}).get("news_metrics") or []
        log.debug("LLM context includes news_metrics rows=%d", len(nm) if isinstance(nm, list) else 0)
    except Exception:
        pass

    # Attempt chat.completions first
    out = _call_chat_completions(api_key, model, decision_prompt, user_content, log)
    if out is None:
        # Fallback to responses API
        out = _call_responses(api_key, model, decision_prompt, user_content, log)
    if out is None:
        # Optional final fallback to a known-good model if configured
        fallback_model = os.getenv("OPENAI_FALLBACK_MODEL", "gpt-4o-mini")
        if fallback_model and fallback_model != model:
            log.warning("LLM; primary model %s failed; trying fallback %s", model, fallback_model)
            out = _call_chat_completions(api_key, fallback_model, decision_prompt, user_content, log)
            if out is None:
                out = _call_responses(api_key, fallback_model, decision_prompt, user_content, log)
    if out is None:
        log.error("LLM; all attempts failed; using fallback mock")
        return []
    try:
        log.info("LLM proposals count=%d", len(out))
    except Exception:
        pass
    return out
