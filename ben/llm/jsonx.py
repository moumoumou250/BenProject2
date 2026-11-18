"""Extract the first balanced JSON object from model output."""
from __future__ import annotations

import json
import re

from ben.core.errors import FGError


def _extract_first_balanced(text: str, start: int) -> tuple[dict | None, int]:
    """Scan from `start` (a '{') to its matching '}'. Return (parsed|None, end).
    parsed is None if the balanced object is not valid JSON — caller should try
    the next '{'. end is the index past the closing '}' (or len(text))."""
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    blob = text[start:i + 1]
                    try:
                        return json.loads(blob), i + 1
                    except json.JSONDecodeError:
                        return None, i + 1
    # ran off the end with depth>0 → unterminated
    return None, len(text)


def extract_json_object(text: str) -> dict:
    """Find the first VALID JSON object in `text`. Tolerates a prose preamble
    that contains stray braces (e.g. '{step 1}') by trying each balanced
    object in turn until one parses."""
    if not text or not text.strip():
        raise FGError("empty model output")
    pos = 0
    last_error = None
    while True:
        start = text.find("{", pos)
        if start == -1:
            break
        obj, end = _extract_first_balanced(text, start)
        if obj is not None:
            return obj
        # remember the failure for a useful error, then look past this object
        blob = text[start:min(end, len(text))]
        last_error = blob[:200]
        pos = end if end > start else start + 1
    if last_error is not None:
        raise FGError(f"model returned no valid JSON object; nearest={last_error!r}")
    raise FGError(f"no JSON object in model output: {text[:200]!r}")


_QUOTA_ERROR_RE = re.compile(
    r"insufficient|balance|quota|exceeded|arrearage|billing|payment|"
    r"401|unauthorized|invalid.{0,12}api.?key|欠费|余额",
    re.IGNORECASE,
)
