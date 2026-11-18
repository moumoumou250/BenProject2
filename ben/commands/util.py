"""Shared helpers for command handlers."""
from __future__ import annotations

from pathlib import Path

from ben.core.errors import FGError
from ben.core.parse import parse_from  # noqa: F401 — re-export for callers


def _read_doc_arg(args) -> str | None:
    """Resolve the `doc` body from CLI flags: --doc '<text>' inline, or
    --doc-file <path> read from disk. --doc-file wins if both given."""
    doc_file = getattr(args, "doc_file", None)
    if doc_file:
        p = Path(doc_file)
        if not p.exists():
            raise FGError(f"doc file not found: {p}")
        text = p.read_text(encoding="utf-8")
        return text or None
    return getattr(args, "doc", None)


def _assert_safe_store_root(root: Path, action: str) -> None:
    """Refuse to delete a path that doesn't look like a fact-graph store
    (guards a destructive path): must contain project.json, and must not be a filesystem
    root or the user's home."""
    if root == root.parent:
        raise FGError(f"refusing to {action} filesystem root: {root}")
    home = Path.home()
    try:
        if root.resolve() == home.resolve():
            raise FGError(f"refusing to {action} home directory: {root}")
    except OSError:
        pass
    marker = root / "project.json"
    if not root.exists():
        return  # nothing to delete; fine
    if not marker.exists():
        raise FGError(
            f"refusing to {action} {root}: not a fact-graph store "
            f"(no project.json). Re-check your --store path."
        )


def _resolve_templates_dir(args) -> Path:
    if args.templates:
        return Path(args.templates)
    # default: sibling `templates/` next to the store, else the repo's templates/
    store_root = Path(args.store).resolve()
    cand = store_root.parent / "templates"
    if cand.exists():
        return cand
    # fall back to the prompt templates shipped inside the package
    return Path(__file__).resolve().parents[1] / "agents" / "prompts"
