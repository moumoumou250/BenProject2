"""Where runtime output goes — one answer, so nothing lands at the repo root.

A ben session writes files that are *not* source: worker registries, PTY
socket directories, log tails, HTML snapshots, per-challenge graphs. If every
call site decides this for itself, the base directory slowly fills with
`runs/`, `logs/`, `console/`, `workers.json`, `ben-graph.html` — which is
exactly what happened here (a 3.9 MB target-archive plus two duplicate
front-end bundles ended up tracked in git).

The rule this module enforces:

    every path ben writes at runtime is  <base>/<runtime>/...

`base` is the directory the user is working in (the project, or the match
root for a fleet). The default `<runtime>` is ``runs``; ``BEN_RUNTIME_DIR``
overrides it (declared in :mod:`ben.config`) for CI temp dirs.

Two things are deliberately *not* runtime output and stay where they are:

* ``.ben/`` — the fact graph. It is project data, the thing `ben` exists to
  produce, and it travels with the project; moving it under ``runs/`` would
  make a graph unreachable by `ben status` in its own directory.
* ``lab/`` — archived assessment material. Nothing writes here; it is a
  human-managed archive and is gitignored (see `docs/ARCH.md`).

Readers must not create directories (a read-only observer such as the
dashboard polls repeatedly); only :func:`ensure_output_dir` and
:func:`console_root` mkdir.
"""
from __future__ import annotations

import os
from pathlib import Path

#: Fallback name when BEN_RUNTIME_DIR is unset. Kept here — and nowhere else —
#: so `scripts/ci/arch_check.py` can ban the literal in every other module.
#: `ben.config.ENV_SPECS` imports this constant for the key's documented
#: default, which keeps the value single-sourced.
DEFAULT_RUNTIME_DIR = "runs"


def runtime_name() -> str:
    """Directory name for runtime output, relative to a base dir.

    Reads the environment on every call (like the rest of :mod:`ben.config`)
    so tests can patch it and a fleet can point two workers at different
    roots without re-importing.
    """
    raw = (os.environ.get("BEN_RUNTIME_DIR") or "").strip().strip("/")
    if not raw or "/" in raw or raw in (".", ".."):
        return DEFAULT_RUNTIME_DIR
    return raw


def is_runtime_path(path: Path | str) -> bool:
    """True when ``path`` is already at or below a runtime directory.

    Used to avoid the ``runs/runs/`` mistake when a caller hands us a path
    that a previous step already placed correctly (the common case: a store
    at ``runs/<name>/.ben``).
    """
    return runtime_name() in Path(path).parts


def runtime_root(base: Path | str) -> Path:
    """``<base>/<runtime>`` — the single writable root for generated files.

    Pure computation: no mkdir, no existence check.
    """
    return Path(base) / runtime_name()


def output_dir(base: Path | str) -> Path:
    """Directory a one-off generated file belongs in.

    ``base`` itself when it is already inside the runtime tree, otherwise the
    runtime root. This is why `ben view` on ``runs/juice/.ben`` writes next to
    the graph instead of nesting another ``runs/``.
    """
    base = Path(base)
    return base if is_runtime_path(base) else runtime_root(base)


def ensure_output_dir(base: Path | str) -> Path:
    """`output_dir` for writers: created if missing."""
    out = output_dir(base)
    out.mkdir(parents=True, exist_ok=True)
    return out


def logs_dir(base: Path | str, *, create: bool = False) -> Path:
    """Worker / console logs: ``<base>/<runtime>/logs``."""
    out = output_dir(base) / "logs"
    if create:
        out.mkdir(parents=True, exist_ok=True)
    return out


def registry_root(base: Path | str) -> Path:
    """Fleet registry dir (``workers.json`` + ``logs/``): the runtime root."""
    return output_dir(base)


def snapshot_file(base: Path | str, stem: str = "ben-graph") -> Path:
    """Default target for a rendered HTML snapshot."""
    return output_dir(base) / f"{stem}.html"
