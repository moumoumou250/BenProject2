"""Model execution facade: cli (claude -p) or native OpenAI SDK tool loop."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from ben import config
from ben.core.errors import FGError
from ben.llm.keys import _is_quota_error, _rotate_key


def resolve_engine(override: str | None = None) -> str:
    """Return ``sdk`` or ``cli``.

    ``BEN_ENGINE`` / ``override``: auto | sdk | cli (default auto).
    """
    raw = (override or config.get("BEN_ENGINE") or "auto").strip().lower()
    if raw in ("sdk", "cli"):
        return raw
    if raw != "auto":
        raise FGError(f"unknown BEN_ENGINE={raw!r}; use auto|sdk|cli")
    # Lazy import to keep cli path free of openai
    from ben.llm.llm import sdk_ready
    if sdk_ready():
        model = (config.get("BEN_MODEL") or "").strip()
        from ben.llm import grok_build
        # Grok Build / any non-default model → sdk. Default "sonnet" is a
        # Claude Code label — prefer cli unless user set BEN_ENGINE=sdk.
        if grok_build.subscription_model(model) or (model and model != "sonnet"):
            return "sdk"
    return "cli"


def run_claude(
    prompt: str,
    *,
    model: str,
    timeout: int,
    skip_permissions: bool,
    append_system: str | None,
    cwd: Path,
    tools: bool = False,
    tier: str | None = None,
) -> dict:
    """Call the agent engine and return the parsed JSON result envelope.

    ``tools`` (feasibility lock-in): when True, the sdk backend exposes
    shell/read_file/write_file. Planner steps (reason/verify/blindspot/
    brainstorm/command) should leave this False; explore should pass True.
    The cli backend ignores the flag (Claude Code always has its own tools).

    ``tier``: ``main`` / ``flash`` / None (auto). Flash workers use
    ``BEN_FLASH_*`` and always go through the sdk OpenAI-compatible path.
    """
    if timeout < 1:
        raise FGError("claude timeout must be at least 1 second")
    if not isinstance(model, str) or not model.strip():
        raise FGError("claude model cannot be empty")
    from ben.llm.llm import flash_configured, resolve_model_tier

    resolved_tier = resolve_model_tier(tier)
    use_model = model
    if resolved_tier == "flash" and flash_configured():
        use_model = (config.get("BEN_FLASH_MODEL") or model).strip()
        engine = "sdk"
    else:
        engine = resolve_engine()
    if engine == "sdk":
        from ben.llm.sdk import run_sdk
        return run_sdk(
            prompt,
            model=use_model,
            timeout=timeout,
            skip_permissions=skip_permissions,
            append_system=append_system,
            cwd=cwd,
            tools=tools,
            tier=resolved_tier,
        )
    return _run_cli(
        prompt,
        model=use_model,
        timeout=timeout,
        skip_permissions=skip_permissions,
        append_system=append_system,
        cwd=cwd,
    )


def _run_cli(
    prompt: str,
    *,
    model: str,
    timeout: int,
    skip_permissions: bool,
    append_system: str | None,
    cwd: Path,
) -> dict:
    """claude -p --output-format json (or BEN_BIN wrapper). Behaviour preserved."""
    prefix = config.get("BEN_BIN").split()
    argv = prefix + [
        "-p",
        "--output-format", "json",
        "--model", model,
    ]
    if skip_permissions:
        argv.append("--dangerously-skip-permissions")
    if append_system:
        argv += ["--append-system-prompt", append_system]
    engine = prefix[0]
    attempts = 1 + max(0, config.get_int("BEN_RETRY_MODEL"))
    last_error: FGError | None = None
    for attempt in range(1, attempts + 1):
        try:
            return _run_engine_once(
                argv, prompt, timeout, cwd, engine,
            )
        except FGError as exc:
            last_error = exc
            if "CLI not found" in str(exc):
                raise  # not transient
            if _is_quota_error(str(exc)) and _rotate_key(backend="cli"):
                sys.stderr.write(
                    f"[ben] quota/auth error (attempt {attempt}/{attempts}); "
                    "key rotated — retrying immediately\n"
                )
                continue
            if attempt < attempts:
                backoff = min(120, 10 * (2 ** (attempt - 1)))
                sys.stderr.write(
                    f"[ben] engine call failed (attempt {attempt}/{attempts}): "
                    f"{exc}; retrying in {backoff}s\n"
                )
                time.sleep(backoff)
    assert last_error is not None
    raise last_error


def _run_engine_once(argv, prompt, timeout, cwd, engine) -> dict:
    try:
        proc = subprocess.run(
            argv,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd),
        )
    except FileNotFoundError:
        raise FGError(f"`{engine}` CLI not found on PATH; install it or fix BEN_BIN.")
    except subprocess.TimeoutExpired:
        raise FGError(f"{engine} dispatch timed out after {timeout}s")
    if proc.returncode != 0:
        raise FGError(
            f"{engine} exited {proc.returncode}: {proc.stderr.strip()[:500]}"
        )
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise FGError(
            f"{engine} did not return JSON. stdout[:300]={proc.stdout[:300]!r}"
        )
    if not isinstance(envelope, dict):
        raise FGError(f"{engine} returned a JSON value instead of an object envelope")
    if envelope.get("is_error"):
        result = envelope.get("result", "")
        raise FGError(f"{engine} reported error: {str(result)[:300]}")
    if not isinstance(envelope.get("result", ""), str):
        raise FGError("response envelope has a non-string result")
    return envelope
