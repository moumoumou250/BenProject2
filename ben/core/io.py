"""Atomic JSON storage primitives."""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def read_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _read_node_files(directory: Path, kind: str) -> list[dict]:
    """List all node JSON files in `directory`, skipping any that are malformed
    or schema-broken with a stderr warning (a corrupt .ben/*.json
    must NOT crash status/graph/view — degrade and keep going)."""
    # Imported lazily to keep io -> schema from becoming an import cycle.
    from ben.core.schema import _node_schema_errors

    out: list[dict] = []
    seen: set[str] = set()
    for p in sorted(directory.glob("*.json")):
        try:
            data = read_json(p)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError, ValueError) as exc:
            sys.stderr.write(
                f"ben: warning: skipping malformed {kind} file {p.name}: {exc}\n"
            )
            continue
        errors = _node_schema_errors(data, kind)
        if errors:
            sys.stderr.write(
                f"ben: warning: skipping invalid {kind} file {p.name}: "
                f"{'; '.join(errors)}\n"
            )
            continue
        nid = data["id"]
        if p.stem != nid:
            sys.stderr.write(
                f"ben: warning: skipping {kind} file {p.name}: filename does not match id {nid!r}\n"
            )
            continue
        if nid in seen:
            sys.stderr.write(
                f"ben: warning: skipping duplicate {kind} id {nid!r} from {p.name}\n"
            )
            continue
        seen.add(nid)
        out.append(data)
    return out


def atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # A PID-only temporary name collides when two threads in one process write
    # the same node.  Create the temporary file in the destination directory so
    # `os.replace` stays atomic on the same filesystem, and clean it up if
    # serialization or replacement fails.
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]+")


def _scrub_inline(text: str) -> str:
    """Strip control characters (newlines, tabs, etc.) so a single node's
    title/description always occupies one line in rendered output. This prevents
    a hostile node from spoofing extra rows in the history/recall/graph view."""
    return _CONTROL_CHAR_RE.sub(" ", text) if text else ""


def _prompt_inline(text: str) -> str:
    """Make graph text safe to place inside markdown prompt fences."""
    return _scrub_inline(text).replace("`", "'")
