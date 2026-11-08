"""Thin Anthropic client wrapper with on-disk caching and token accounting.

* Reads ANTHROPIC_API_KEY from the environment (never from files in the repo).
* Every response is cached under code/cache/llm/ keyed by a hash of the request,
  so re-runs are free and deterministic.
* Usage (calls, input/output tokens) is tracked per model for usage_report.md.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import time

from .util import CACHE_DIR

MODEL_TEXT = os.environ.get("AUDIT_TEXT_MODEL", "claude-haiku-4-5")
MODEL_VISION = os.environ.get("AUDIT_VISION_MODEL", "claude-sonnet-4-5")

# USD per million tokens (input, output) - used only for the cost estimate
PRICES = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-opus-4-5": (5.00, 25.00),
}

USAGE: dict[str, dict] = {}
_DISABLED = {"reason": ""}   # set after a permanent error (bad key / no access) -> fall back for the rest of the run


def _record(model: str, inp: int, out: int, cached: bool):
    u = USAGE.setdefault(model, {"calls": 0, "cached_calls": 0, "input_tokens": 0, "output_tokens": 0})
    if cached:
        u["cached_calls"] += 1
    else:
        u["calls"] += 1
    u["input_tokens"] += inp
    u["output_tokens"] += out


def available() -> bool:
    if os.environ.get("AUDIT_DISABLE_LLM") or _DISABLED["reason"]:
        return False
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def _cache_path(key: str) -> str:
    d = os.path.join(CACHE_DIR, "llm")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, key + ".json")


def call(model: str, system: str, content: list, max_tokens: int = 1024) -> str | None:
    """Call Claude (or return cached answer). Returns text or None if unavailable."""
    raw = json.dumps({"m": model, "s": system, "c": content, "t": max_tokens}, sort_keys=True)
    key = hashlib.sha256(raw.encode()).hexdigest()[:32]
    cp = _cache_path(key)
    if os.path.exists(cp):
        d = json.load(open(cp, encoding="utf-8"))
        _record(model, d.get("input_tokens", 0), d.get("output_tokens", 0), cached=True)
        return d["text"]
    if not available():
        return None
    import anthropic
    client = anthropic.Anthropic()
    for attempt in range(4):
        try:
            resp = client.messages.create(model=model, max_tokens=max_tokens, system=system,
                                          temperature=0,
                                          messages=[{"role": "user", "content": content}])
            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            inp, out = resp.usage.input_tokens, resp.usage.output_tokens
            _record(model, inp, out, cached=False)
            json.dump({"text": text, "input_tokens": inp, "output_tokens": out, "model": model},
                      open(cp, "w", encoding="utf-8"))
            return text
        except Exception as exc:  # rate limits / transient errors
            status = getattr(exc, "status_code", None)
            if status in (400, 401, 403, 404):   # permanent: bad key, no access, unknown model
                _DISABLED["reason"] = f"{type(exc).__name__} ({status})"
                print(f"[llm] {type(exc).__name__} ({status}): model calls disabled, using deterministic fallback")
                return None
            wait = 2 ** attempt
            print(f"[llm] {type(exc).__name__}: {exc}; retry in {wait}s")
            time.sleep(wait)
    return None


def image_block(path: str) -> dict:
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    media_type = "image/png" if ext == "png" else "image/jpeg"
    data = base64.standard_b64encode(open(path, "rb").read()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}


def usage_summary() -> dict:
    total = {"calls": 0, "cached_calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    per = {}
    for m, u in USAGE.items():
        pin, pout = PRICES.get(m, (3.0, 15.0))
        cost = u["input_tokens"] / 1e6 * pin + u["output_tokens"] / 1e6 * pout
        per[m] = dict(u, cost_usd=round(cost, 4))
        for k in ("calls", "cached_calls", "input_tokens", "output_tokens"):
            total[k] += u[k]
        total["cost_usd"] += cost
    total["cost_usd"] = round(total["cost_usd"], 4)
    return {"per_model": per, "total": total}
