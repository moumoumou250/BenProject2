"""Optional path-permission matrix for conclude (R-14). Not a sandbox."""
from __future__ import annotations

import fnmatch
import json
import subprocess
from pathlib import Path
from typing import Any

from ben.core.errors import FGError


def load_roles(store_root: Path) -> dict[str, Any] | None:
    """Roles live next to the graph (``.ben/roles.json``) or repo ``.ben/roles.json``."""
    candidates = [
        store_root / "roles.json",
        Path.cwd() / ".ben" / "roles.json",
    ]
    for path in candidates:
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
    return None


def _changed_files(since_sha: str) -> list[str]:
    if not since_sha or since_sha == "nogit":
        return []
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", f"{since_sha}..HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def _match_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pat) for pat in patterns)


def check_role_paths(
    *,
    role: str,
    evidence_sha: str | None,
    roles: dict[str, Any] | None,
    force: bool = False,
) -> None:
    if force or not roles or not evidence_sha:
        return
    spec = roles.get(role) or roles.get("worker")
    if not isinstance(spec, dict):
        return
    writable = list(spec.get("writable") or [])
    forbidden = list(spec.get("forbidden") or [])
    if not writable and not forbidden:
        return
    for path in _changed_files(evidence_sha):
        if forbidden and _match_any(path, forbidden):
            raise FGError(f"role {role!r} forbids changes to {path}")
        if writable and not _match_any(path, writable):
            raise FGError(
                f"role {role!r} cannot write {path} (not in writable patterns)"
            )
