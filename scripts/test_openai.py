#!/usr/bin/env python3
"""
Quick connectivity test to OpenAI Chat Completions API.

Usage:
  set -a; . ./configs/env/.env; set +a
  python scripts/test_openai.py

Prints status, model used, latency, and a short snippet of the response.
"""
from __future__ import annotations

import os
import time
import json
import sys
import httpx


def main() -> None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY is not set in environment.")
        sys.exit(2)
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Respond with a short sentence confirming connectivity."},
        ],
        "temperature": 0.0,
        "max_tokens": 20,
    }
    t0 = time.time()
    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            latency = time.time() - t0
            r.raise_for_status()
            data = r.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            usage = data.get("usage", {})
            print(json.dumps({
                "ok": True,
                "model": model,
                "latency_s": round(latency, 3),
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "content_preview": content[:120],
            }, indent=2))
    except httpx.HTTPError as e:
        print("HTTP error:", e)
        if e.response is not None:
            try:
                print(e.response.text)
            except Exception:
                pass
        sys.exit(1)
    except Exception as e:
        print("ERROR:", e)
        sys.exit(1)


if __name__ == "__main__":
    main()




