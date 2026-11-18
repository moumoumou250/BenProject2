"""Append-only JSONL run trail (R-12). Not a replacement for product ``print``."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ben.core.paths import logs_dir


def _default_log_path() -> Path:
    raw = (os.environ.get("BEN_RUN_LOG") or "").strip()
    if raw:
        return Path(raw)
    # Prefer CWD runtime logs so fleet/workers share one trail per session.
    return logs_dir(Path.cwd(), create=True) / "events.jsonl"


def run_event(kind: str, **fields: Any) -> None:
    """Append one JSON object: ``{"ts", "kind", ...fields}``."""
    try:
        path = _default_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            **{k: v for k, v in fields.items() if v is not None},
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except OSError:
        # Logging must never break the CLI.
        return
