"""Minimal tool surface for the native SDK engine: shell / read_file / write_file."""
from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path

from ben import config

TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "shell",
            "description": "Run a bash command in the working directory. stdout/stderr are merged.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout": {"type": "integer", "description": "seconds (optional)"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file by line range (1-indexed).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer"},
                    "max_lines": {"type": "integer"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write text to a file under allowed roots (cwd and /tmp by default).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
]

_OUTPUT_LIMIT = 16 * 1024
_HEAD = 8 * 1024
_TAIL = 8 * 1024


def repair_tool_arguments(raw: str) -> tuple[dict | None, str | None]:
    """Best-effort JSON repair for tool arguments. Returns (obj, error)."""
    if not isinstance(raw, str) or not raw.strip():
        return {}, None
    text = raw.strip()
    try:
        obj = json.loads(text)
        return (obj if isinstance(obj, dict) else {"_": obj}), None
    except json.JSONDecodeError:
        pass
    fixed = text
    fixed = re.sub(r",\s*}", "}", fixed)
    fixed = re.sub(r",\s*]", "]", fixed)
    fixed = fixed.replace("'", '"')
    try:
        obj = json.loads(fixed)
        return (obj if isinstance(obj, dict) else {"_": obj}), None
    except json.JSONDecodeError as exc:
        return None, f"malformed tool arguments: {exc}; raw={text[:200]!r}"


def repair_tool_calls(tool_calls, start_n: int = 1) -> list:
    """Ensure each tool call has a unique id; return a list of normalized objects."""
    seen: set[str] = set()
    out = []
    n = start_n
    for call in tool_calls or []:
        cid = getattr(call, "id", None) or (call.get("id") if isinstance(call, dict) else None)
        if not cid or cid in seen:
            while f"call_{n}" in seen:
                n += 1
            cid = f"call_{n}"
            n += 1
        seen.add(cid)
        if isinstance(call, dict):
            fixed = dict(call)
            fixed["id"] = cid
            out.append(fixed)
        else:
            # OpenAI SDK object — mutate id if possible, else wrap
            try:
                call.id = cid
            except Exception:
                pass
            out.append(call)
    return out


def _fs_roots(cwd: Path) -> list[Path]:
    raw = config.get("BEN_FS_ROOTS")
    roots: list[Path] = []
    for part in raw.split(":"):
        part = part.strip()
        if not part:
            continue
        if part == "cwd":
            roots.append(cwd.resolve())
        else:
            roots.append(Path(part).expanduser().resolve())
    return roots or [cwd.resolve(), Path("/tmp")]


def _allowed_path(path: Path, cwd: Path) -> Path:
    resolved = path if path.is_absolute() else (cwd / path)
    resolved = resolved.resolve()
    roots = _fs_roots(cwd)
    for root in roots:
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue
    raise PermissionError(
        f"path {resolved} outside allowed roots {[str(r) for r in roots]}"
    )


def _truncate_output(text: str, cwd: Path) -> str:
    if len(text.encode("utf-8", errors="replace")) <= _OUTPUT_LIMIT:
        return text
    raw = text.encode("utf-8", errors="replace")
    head = raw[:_HEAD].decode("utf-8", errors="replace")
    tail = raw[-_TAIL:].decode("utf-8", errors="replace")
    digest = hashlib.sha1(raw).hexdigest()[:12]
    log_dir = cwd / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"tool-{digest}.log"
    try:
        log_path.write_bytes(raw)
    except OSError:
        pass
    omitted = max(0, len(raw) - _HEAD - _TAIL)
    return (
        f"{head}\n\n[已省略 {omitted} 字节，全文见 {log_path}]\n\n{tail}"
    )


def _run_shell(command: str, cwd: Path, timeout: int | None) -> str:
    # Hard cap at BEN_TOOL_TIMEOUT — models must not request hour-long
    # hashcat/brute runs that look like a hung `ben auto`.
    default_to = max(1, config.get_int("BEN_TOOL_TIMEOUT"))
    requested = int(timeout) if timeout else default_to
    to = max(1, min(requested, default_to))
    try:
        proc = subprocess.Popen(
            ["bash", "-lc", command],
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
    except OSError as exc:
        return json.dumps({"exit_code": -1, "output": f"spawn failed: {exc}"}, ensure_ascii=False)
    try:
        out, _ = proc.communicate(timeout=to)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            proc.kill()
        out, _ = proc.communicate(timeout=2)
        code = -9
        out = (out or "") + f"\n[timed out after {to}s]"
    text = _truncate_output(out or "", cwd)
    return json.dumps({"exit_code": code, "output": text}, ensure_ascii=False)


def dispatch_tool(call, cwd: Path | str) -> str:
    cwd_path = Path(cwd).resolve()
    if isinstance(call, dict):
        name = (call.get("function") or {}).get("name") or call.get("name")
        raw_args = (call.get("function") or {}).get("arguments") or call.get("arguments") or "{}"
    else:
        fn = getattr(call, "function", None)
        name = getattr(fn, "name", None) if fn else getattr(call, "name", None)
        raw_args = getattr(fn, "arguments", "{}") if fn else "{}"
    args, err = repair_tool_arguments(raw_args if isinstance(raw_args, str) else json.dumps(raw_args))
    if err:
        return json.dumps({"error": err}, ensure_ascii=False)
    assert args is not None
    try:
        if name == "shell":
            return _run_shell(
                str(args.get("command", "")),
                cwd_path,
                args.get("timeout"),
            )
        if name == "read_file":
            path = _allowed_path(Path(str(args.get("path", ""))), cwd_path)
            start = max(1, int(args.get("start_line") or 1))
            max_lines = max(1, min(int(args.get("max_lines") or 400), 2000))
            text = path.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
            chunk = lines[start - 1: start - 1 + max_lines]
            numbered = "\n".join(f"{start + i}|{line}" for i, line in enumerate(chunk))
            return _truncate_output(numbered, cwd_path)
        if name == "write_file":
            path = _allowed_path(Path(str(args.get("path", ""))), cwd_path)
            content = args.get("content", "")
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return json.dumps({"ok": True, "path": str(path), "bytes": len(content.encode("utf-8"))})
        return json.dumps({"error": f"unknown tool {name!r}"}, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001 — always return to the model
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
