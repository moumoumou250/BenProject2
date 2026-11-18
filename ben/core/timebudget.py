"""Slot-clock helpers shared by auto / sweep / commander / bench."""
from __future__ import annotations

import time
from datetime import datetime

from ben.core.errors import FGError


def deadline_from_args(args) -> float | None:
    """Resolve --deadline <ISO8601> / --minutes <n> into an epoch float."""
    deadline = getattr(args, "deadline", None)
    minutes = getattr(args, "minutes", None)
    if deadline and minutes:
        raise FGError("pass either --deadline or --minutes, not both")
    if deadline:
        text = deadline.strip()
        try:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise FGError(
                f"--deadline must be ISO 8601 (e.g. 2026-10-17T13:00:00+08:00): {exc}"
            ) from exc
        if dt.tzinfo is None:
            dt = dt.astimezone()
        return dt.timestamp()
    if minutes:
        if minutes <= 0:
            raise FGError("--minutes must be positive")
        return time.time() + minutes * 60
    return None


def format_time_budget(deadline: float | None) -> str:
    """Human-readable remaining time for prompt injection."""
    if deadline is None:
        return ""
    remaining = deadline - time.time()
    if remaining <= 0:
        return "TIME IS UP — no time remains; only record/submit what you already have"
    local_end = datetime.fromtimestamp(deadline).strftime("%H:%M")
    if remaining >= 3600:
        text = f"{int(remaining // 3600)}h{int((remaining % 3600) // 60):02d}m"
    else:
        text = f"{int(remaining // 60)} minutes"
    return f"{text} remaining until the {local_end} deadline (local time)"
