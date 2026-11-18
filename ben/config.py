"""Centralized configuration for ben: .env file + environment variable registry.

Every ben configuration item is an environment variable. This module is the
single place that knows:

* **which variables ben reads** — the ``ENV_SPECS`` registry below declares
  each key with its default value, type, group, description, and whether the
  value is a secret (masked in ``ben config`` output);
* **how to load a ``.env`` file** — a pure-stdlib parser (no python-dotenv,
  the kernel stays dependency-free). ``load_dotenv()`` runs once at CLI
  startup (``ben/cli.py:main``) and feeds values into ``os.environ``;
* **how to read them** — ``get`` / ``get_int`` / ``get_float`` read
  ``os.environ`` *dynamically* (so tests can still use ``mock.patch.dict``),
  applying the registry default when unset, and raising a friendly
  ``FGError`` when a value has the wrong type;
* **how to validate them** — ``config_problems()`` returns human-readable
  errors (bad types, invalid choices, missing required keys per context);
  surfaced by ``ben config --check``.

Precedence (highest first):

1. real environment variables (``export BEN_MODEL=...``);
2. values from the ``.env`` file (search order: ``$BEN_ENV_FILE``,
   ``./.env`` in the current directory, then the repo-root ``.env``);
3. the registry default declared here.

``.env`` is a convenience, not a requirement: anything it sets can equally
be exported in the shell. See ``.env.example`` at the repo root for a
documented template.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from ben.core import paths
from ben.core.errors import FGError

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# keys whose current value came from the .env file (for `ben config` source column)
_LOADED_FROM_FILE: set[str] = set()
_DOTENV_VALUES: dict[str, str] = {}
_DOTENV_PATH: Path | None = None


def _spec(default, group: str, desc: str, *, kind: str = "str",
          secret: bool = False, choices: list[str] | None = None) -> dict:
    return {
        "default": default, "kind": kind, "group": group, "desc": desc,
        "secret": secret, "choices": choices,
    }


# --- the registry: every environment variable ben reads ---------------------
ENV_SPECS: dict[str, dict] = {
    # model engine
    "BEN_ENGINE": _spec("auto", "engine", "model engine: auto | sdk | cli",
                        choices=["auto", "sdk", "cli"]),
    "BEN_MODEL": _spec("sonnet", "engine", "model id: grok / grok/<slug> (Grok Build "
                                         "subscription), OpenAI-compatible id for sdk, "
                                         "or cli label like 'sonnet'"),
    "BEN_BIN": _spec("claude", "engine", "agent CLI to invoke in cli mode (BEN_BIN "
                                        "may be a full command with args)"),
    "BEN_TIMEOUT": _spec(600, "engine", "per model-call timeout (seconds)", kind="int"),
    "BEN_RETRY_MODEL": _spec(0, "engine", "extra retries per model call beyond "
                                          "quota-key rotation", kind="int"),
    "BEN_MAX_TURNS": _spec(40, "engine", "max tool-loop turns in one sdk run", kind="int"),
    "BEN_CONTEXT_CHARS": _spec(400000, "engine", "context compaction threshold for "
                                               "sdk tool loops (chars)", kind="int"),

    # sdk gateway (OpenAI-compatible)
    "BEN_API_KEY": _spec("", "sdk gateway", "API key for the sdk engine "
                                            "(alternative: OPENAI_API_KEY)", secret=True),
    "BEN_API_BASE": _spec("", "sdk gateway", "base URL of the OpenAI-compatible "
                                             "gateway (alternative: OPENAI_BASE_URL)"),
    "OPENAI_API_KEY": _spec("", "sdk gateway", "OPENAI-style key alias honored by the "
                                              "sdk engine", secret=True),
    "OPENAI_BASE_URL": _spec("", "sdk gateway", "OPENAI-style base URL alias honored "
                                               "by the sdk engine"),
    "BEN_KEY_POOL": _spec("", "sdk gateway", "JSON array of key entries; entry #0 "
                                            "is the primary, the rest are rotation "
                                            "backups, see .env.example",
                          secret=True),

    # flash tier (workers / sub-agents); empty = share BEN_MODEL
    "BEN_FLASH_MODEL": _spec("", "flash", "sub-model id for workers when set "
                                          "(OpenAI-compatible, e.g. kimi-k2.5)"),
    "BEN_FLASH_API_KEY": _spec("", "flash", "API key for BEN_FLASH_MODEL", secret=True),
    "BEN_FLASH_API_BASE": _spec("", "flash", "base URL for BEN_FLASH_MODEL "
                                             "(e.g. https://api.moonshot.cn/v1)"),

    # cli gateway (Claude Code and compatible CLIs)
    "ANTHROPIC_BASE_URL": _spec("", "cli gateway", "gateway base URL for the cli engine"),
    "ANTHROPIC_AUTH_TOKEN": _spec("", "cli gateway", "auth token for the cli engine",
                                  secret=True),

    # competition platform (arena)
    "BENCHMARK_BASE_URL": _spec("", "arena", "TSecBench-style platform base URL "
                                             "(platform injects this in hosted mode)"),
    "BENCHMARK_TOKEN": _spec("", "arena", "platform auth token (BENCHMARK_TOKEN header)",
                             secret=True),

    # worker / messaging
    "BEN_WORKER": _spec("", "worker", "worker identity; injected by `ben fleet`, "
                                      "not normally set by hand"),
    "FGC_SENDER": _spec("ben-agent", "worker", "default sender label for `ben send`"),
    "AI_SEND_INITIAL_DELAY": _spec(0.1, "worker", "console send: pause before first "
                                                  "LF (seconds)", kind="float"),
    "AI_SEND_SUBMIT_DELAY": _spec(0.5, "worker", "console send: pause before the "
                                                 "submit LF (seconds)", kind="float"),

    # storage / tooling
    "BEN_RUNTIME_DIR": _spec(paths.DEFAULT_RUNTIME_DIR, "storage",
                             "dir for runtime output (worker registry, logs, PTY "
                             "sockets, HTML snapshots) relative to the project; "
                             "see ben/core/paths.py"),
    "BEN_KB_ROOT": _spec("", "storage", "knowledge-base root dir (default: the "
                                        "shipped ben/kb/)"),
    "BEN_TOOL_TIMEOUT": _spec(180, "storage", "default shell tool timeout (seconds)",
                              kind="int"),
    "BEN_FS_ROOTS": _spec("cwd:/tmp", "storage", "colon-separated roots the sdk shell "
                                                 "tool may touch ('cwd' = worker cwd)"),
    "BEN_PYTHON": _spec("python3", "storage", "interpreter used to spawn console hosts"),

    # generic conventions ben honors
    "EDITOR": _spec(None, "generic", "editor opened by `ben doc --edit` (falls back "
                                    "to VISUAL then vi)"),
    "VISUAL": _spec(None, "generic", "editor opened by `ben doc --edit`"),

    # this file itself
    "BEN_ENV_FILE": _spec(None, "env file", "explicit .env path; default search: "
                                            "./.env then repo root .env"),
}


# --- .env parsing (stdlib-only) ----------------------------------------------

def _bracket_depth(text: str) -> int:
    """Unclosed ``[``/``{`` depth outside JSON strings (>=0)."""
    depth = 0
    in_string = False
    escape = False
    for ch in text:
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "[{":
            depth += 1
        elif ch in "]}":
            depth = max(0, depth - 1)
    return depth


def parse_env_text(text: str) -> list[tuple[int, str, str]]:
    """Parse dotenv text into (line_number, key, value) triples.

    Accepted syntax (deliberately the common subset):
    ``KEY=value``, ``KEY="value"``, ``KEY='value'``, optional ``export `` prefix,
    ``#`` comments and blank lines are skipped. A value that starts with ``[``
    or ``{`` may span multiple lines (the natural way to write the
    ``BEN_KEY_POOL`` JSON array). Parse failures are collected by the caller
    (``load_dotenv``) and reported, never fatal.
    """
    out: list[tuple[int, str, str]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        lineno = i + 1
        line = lines[i].strip()
        i += 1
        if not line or line.startswith("#"):
            continue
        if line.startswith("export ") or line.startswith("export\t"):
            line = line[len("export "):].strip()
        if "=" not in line:
            out.append((lineno, "", ""))
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        # multi-line JSON value: keep consuming lines until brackets balance
        if value and value[0] in "[{" and _bracket_depth(value) > 0:
            parts = [value]
            while _bracket_depth("\n".join(parts)) > 0 and i < len(lines):
                parts.append(lines[i].strip())
                i += 1
            value = "\n".join(parts)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if not _KEY_RE.match(key):
            out.append((lineno, "", ""))
            continue
        out.append((lineno, key, value))
    return out


def dotenv_candidates() -> list[Path]:
    """Search order for the .env file."""
    cands: list[Path] = []
    explicit = os.environ.get("BEN_ENV_FILE", "").strip()
    if explicit:
        cands.append(Path(explicit).expanduser())
    cands.append(Path.cwd() / ".env")
    cands.append(Path(__file__).resolve().parents[1] / ".env")
    seen: set[Path] = set()
    out = []
    for c in cands:
        c = c.resolve()
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def load_dotenv(path: Path | None = None, *, warn: bool = True) -> Path | None:
    """Load a .env file into ``os.environ`` (real env vars always win).

    Returns the path actually loaded, or None when no file was found. A
    malformed line is reported to stderr and skipped — a broken .env must
    never take the whole CLI down.
    """
    global _DOTENV_PATH
    candidates = [Path(path)] if path is not None else dotenv_candidates()
    for cand in candidates:
        if not cand.is_file():
            continue
        try:
            text = cand.read_text(encoding="utf-8-sig")
        except OSError as exc:
            if warn:
                sys.stderr.write(f"[ben] cannot read .env at {cand}: {exc}\n")
            return None
        for lineno, key, value in parse_env_text(text):
            if not key:
                if warn:
                    sys.stderr.write(
                        f"[ben] .env {cand}: line {lineno} is not KEY=VALUE — skipped\n"
                    )
                continue
            # real environment takes precedence over .env (setdefault semantics)
            if key not in os.environ:
                os.environ[key] = value
                _LOADED_FROM_FILE.add(key)
                _DOTENV_VALUES[key] = value
        _DOTENV_PATH = cand
        return cand
    return None


# --- typed accessors (read os.environ live; mock-friendly) -------------------

def get(key: str) -> str | None:
    """Current value of a registered key, or its default when unset.

    Raises KeyError for keys not in the registry — ben config keys are
    declared, not invented at call sites.
    """
    spec = ENV_SPECS.get(key)
    if spec is None:
        raise KeyError(f"unknown config key {key!r} (not in ENV_SPECS)")
    value = os.environ.get(key)
    if value is not None:
        return value
    return spec["default"]


def _typed(key: str, kind: str) -> object:
    spec = ENV_SPECS[key]
    raw = get(key)
    # empty string falls back to the declared default (friendlier than int(""))
    if raw is None or (raw == "" and spec["default"] not in (None, "")):
        raw = spec["default"]
    if raw is None:
        raise FGError(f"config {key} is required but not set "
                      f"(set it in the environment or .env)")
    try:
        if kind == "int":
            return int(raw)
        if kind == "float":
            return float(raw)
        return raw
    except ValueError:
        raise FGError(
            f"config {key} must be a valid {kind}, got {raw!r} "
            f"(check your environment or .env file)"
        ) from None


def get_int(key: str) -> int:
    return int(_typed(key, "int"))


def get_float(key: str) -> float:
    return float(_typed(key, "float"))


def source(key: str) -> str:
    """Where the effective value comes from: 'env' | '.env' | 'default'."""
    if key not in os.environ:
        return "default"
    if key in _LOADED_FROM_FILE and os.environ[key] == _DOTENV_VALUES.get(key):
        return ".env"
    return "env"


def mask(key: str, value: str | None) -> str:
    """Mask secret values for display (keep the last 4 characters)."""
    if value is None:
        return ""
    if not ENV_SPECS[key]["secret"]:
        return value
    if len(value) <= 4:
        return "****"
    return f"****{value[-4:]}"


def _effective_rows() -> list[dict]:
    rows = []
    for key, spec in ENV_SPECS.items():
        value = get(key)
        rows.append({
            "key": key,
            "value": "" if value is None else str(value),
            "source": source(key),
            "default": "" if spec["default"] is None else str(spec["default"]),
            "group": spec["group"],
            "desc": spec["desc"],
            "secret": spec["secret"],
        })
    return rows


def model_key_configured() -> bool:
    """True when some model credential is present (sdk, pool, or Grok Build)."""
    from ben.llm import grok_build

    model = get("BEN_MODEL")
    if grok_build.subscription_model(model):
        return grok_build.is_authenticated()
    return bool(
        get("BEN_API_KEY") or get("OPENAI_API_KEY") or get("BEN_KEY_POOL")
    )


def config_problems() -> list[str]:
    """Human-readable configuration errors for `ben config --check`.

    Checks: type validity of every set numeric key; BEN_ENGINE choice;
    whether any model credential exists (none at all is almost certainly a
    misconfiguration — cli/sdk calls would all fail).
    """
    from ben.llm import grok_build

    problems: list[str] = []
    for key, spec in ENV_SPECS.items():
        if spec["kind"] in ("int", "float") and key in os.environ:
            raw = os.environ[key]
            try:
                int(raw) if spec["kind"] == "int" else float(raw)
            except ValueError:
                problems.append(
                    f"{key}={raw!r} is not a valid {spec['kind']} "
                    f"(default {spec['default']})"
                )
        if spec["choices"] and key in os.environ:
            raw = os.environ[key].strip().lower()
            if raw not in spec["choices"]:
                problems.append(
                    f"{key}={raw!r} is invalid; expected one of "
                    f"{', '.join(spec['choices'])}"
                )
    model = get("BEN_MODEL")
    if grok_build.subscription_model(model):
        if not grok_build.is_authenticated():
            problems.append("Grok Build login: run grok login")
    elif not model_key_configured() and not (
        get("ANTHROPIC_AUTH_TOKEN") or get("ANTHROPIC_BASE_URL")
    ):
        problems.append(
            "no model credential found: set BEN_MODEL=grok (after `grok login`), "
            "or BEN_API_KEY / OPENAI_API_KEY / BEN_KEY_POOL (sdk), "
            "or ANTHROPIC_AUTH_TOKEN (cli)"
        )
    flash_model = (get("BEN_FLASH_MODEL") or "").strip()
    if flash_model:
        if not (get("BEN_FLASH_API_KEY") or "").strip():
            problems.append(
                "BEN_FLASH_MODEL is set but BEN_FLASH_API_KEY is empty"
            )
        if not (get("BEN_FLASH_API_BASE") or "").strip():
            problems.append(
                "BEN_FLASH_MODEL is set but BEN_FLASH_API_BASE is empty"
            )
    return problems
