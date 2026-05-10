"""Webhook delivery: POST intents to a configurable endpoint. Pure stdlib."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


def post(url: str, payload: dict[str, Any], timeout: int = 5) -> bool:
    """POST payload as JSON to url. Returns True on 2xx, False otherwise. Never raises."""
    if not url:
        return False
    try:
        data = json.dumps(payload, default=str).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False
