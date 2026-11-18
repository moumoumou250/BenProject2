"""Parsing helpers used by both commands and agents (keeps layers acyclic)."""
from __future__ import annotations

import re


def parse_from(raw: str) -> list[str]:
    ids = [s.strip() for s in re.split(r"[,\s]+", raw) if s.strip()]
    seen, out = set(), []
    for x in ids:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out
