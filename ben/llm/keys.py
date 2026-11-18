"""API key pool loading and quota-death rotation (cli + sdk)."""
from __future__ import annotations

import json
import os
import sys

from ben import config
from ben.llm.jsonx import _QUOTA_ERROR_RE


def _normalize_pool_entry(item: dict) -> dict | None:
    """Accept both legacy Anthropic fields and OpenAI-compatible fields."""
    if not isinstance(item, dict):
        return None
    api_key = (
        item.get("api_key")
        or item.get("token")
        or item.get("key")
        or ""
    )
    if not isinstance(api_key, str) or not api_key.strip():
        return None
    api_base = (
        item.get("api_base")
        or item.get("base_url")
        or config.get("BEN_API_BASE")
        or config.get("OPENAI_BASE_URL")
        or config.get("ANTHROPIC_BASE_URL")
        or ""
    )
    model = (
        item.get("model")
        or config.get("BEN_MODEL")
        or "sonnet"
    )
    return {
        "api_key": api_key.strip(),
        "api_base": (api_base or "").strip(),
        "token": api_key.strip(),          # legacy alias for cli tests
        "base_url": (api_base or "").strip(),
        "model": model,
    }


def _load_key_pool() -> list[dict]:
    raw = config.get("BEN_KEY_POOL").strip()
    if not raw:
        return []
    try:
        pool = json.loads(raw)
    except json.JSONDecodeError:
        sys.stderr.write("[ben] BEN_KEY_POOL is not valid JSON — ignoring\n")
        return []
    out = []
    for item in pool if isinstance(pool, list) else []:
        entry = _normalize_pool_entry(item)
        if entry:
            out.append(entry)
    return out


def _is_quota_error(message: str) -> bool:
    return bool(_QUOTA_ERROR_RE.search(message or ""))


def _seed_key_from_pool() -> bool:
    """Adopt pool entry #0 as the active sdk key when none is set.

    Makes ``BEN_KEY_POOL`` self-sufficient: the first entry is the primary
    (key + gateway + model); quota rotation then advances from it ring-wise.
    Explicit env vars always win — the seed only fills what is missing.
    Returns True when a seed was applied.
    """
    if os.environ.get("BEN_API_KEY") or os.environ.get("OPENAI_API_KEY"):
        return False
    pool = _load_key_pool()
    if not pool:
        return False
    first = pool[0]
    os.environ["BEN_API_KEY"] = first["api_key"]
    if first["api_base"] and not os.environ.get("BEN_API_BASE"):
        os.environ["BEN_API_BASE"] = first["api_base"]
    if first["model"] and first["model"] != "sonnet" \
            and not os.environ.get("BEN_MODEL"):
        os.environ["BEN_MODEL"] = first["model"]
    return True


def _rotate_key(*, backend: str = "cli") -> bool:
    """Advance to the next pool entry. Returns False if pool is empty.

    ``backend`` is ``cli`` (writes ANTHROPIC_*) or ``sdk`` (writes BEN_API_*).
    """
    pool = _load_key_pool()
    if not pool:
        return False
    if backend == "sdk":
        current = config.get("BEN_API_KEY") or config.get("OPENAI_API_KEY")
    else:
        current = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
    start = -1
    for i, entry in enumerate(pool):
        if entry["api_key"] == current or entry["token"] == current:
            start = i
            break
    nxt = pool[(start + 1) % len(pool)]
    if start >= 0 and nxt["api_key"] == current:
        return True  # single-entry pool: keep the key, caller retries
    if backend == "sdk":
        os.environ["BEN_API_KEY"] = nxt["api_key"]
        if nxt["api_base"]:
            os.environ["BEN_API_BASE"] = nxt["api_base"]
        os.environ["BEN_MODEL"] = nxt["model"]
    else:
        os.environ["ANTHROPIC_BASE_URL"] = nxt["base_url"]
        os.environ["ANTHROPIC_AUTH_TOKEN"] = nxt["token"]
        os.environ["BEN_MODEL"] = nxt["model"]
    sys.stderr.write(
        f"[ben] key rotated -> {nxt['api_base'] or nxt['base_url']} "
        f"model={nxt['model']} (token …{nxt['api_key'][-6:]})\n"
    )
    return True
