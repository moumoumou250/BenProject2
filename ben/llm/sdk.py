"""Native OpenAI-compatible tool loop (BEN_ENGINE=sdk)."""
from __future__ import annotations

import time
from pathlib import Path

from ben import config
from ben.core.errors import FGError
from ben.llm.context import compact_if_needed
from ben.llm.jsonx import extract_json_object
from ben.llm.llm import call_model
from ben.llm.prompts import build_system_prompt, json_repair_nudge, wrap_up_nudge
from ben.tools.builtin import TOOL_SPECS, dispatch_tool, repair_tool_calls


def _assistant_message(msg) -> dict:
    out: dict = {"role": "assistant", "content": msg.content or ""}
    if getattr(msg, "tool_calls", None):
        tool_calls = []
        for tc in msg.tool_calls:
            tool_calls.append({
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments or "{}",
                },
            })
        out["tool_calls"] = tool_calls
    return out


def _usage_dict(resp) -> dict:
    usage = getattr(resp, "usage", None)
    if usage is None:
        return {}
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }


def _looks_like_json_answer(text: str) -> bool:
    """True when the reply already contains a parseable JSON object."""
    try:
        extract_json_object(text)
        return True
    except FGError:
        return False


def run_sdk(
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
    """Run a native chat loop. When ``tools`` is False, no tool specs are sent
    (planner/JSON-only steps). When True, shell/read_file/write_file are available.
    ``skip_permissions`` is accepted for signature parity; sdk always allows tools
    when ``tools=True``.
    """
    del skip_permissions  # parity only — sdk has no Claude Code permission gate
    max_turns = max(1, config.get_int("BEN_MAX_TURNS"))
    system = build_system_prompt(append_system, cwd)
    messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    deadline = time.time() + max(1, timeout)
    tool_specs = TOOL_SPECS if tools else None
    per_call_cap = min(120, max(30, timeout // 2)) if timeout else 120
    json_repairs = 0

    for turn in range(1, max_turns + 1):
        remaining = deadline - time.time()
        if remaining <= 0:
            raise FGError(f"sdk dispatch timed out after {timeout}s")
        if tools and turn >= max_turns - 1:
            messages.extend(wrap_up_nudge())
        elif not tools and turn >= max_turns - 1:
            messages.append(json_repair_nudge())
        resp = call_model(
            messages,
            tool_specs,
            timeout=min(remaining, per_call_cap),
            model=model,
            tier=tier,
        )
        choice = resp.choices[0]
        msg = choice.message
        if not getattr(msg, "tool_calls", None):
            content = msg.content or ""
            # Planner steps (tools=False) must end in JSON. Grok often narrates
            # first; nudge instead of bubbling "no JSON object" to auto.
            if not tools and not _looks_like_json_answer(content):
                json_repairs += 1
                if json_repairs <= 3 and turn < max_turns:
                    messages.append(_assistant_message(msg))
                    messages.append(json_repair_nudge())
                    continue
            return {
                "result": content,
                "engine": "sdk",
                "usage": _usage_dict(resp),
                "turns": turn,
            }
        if not tools:
            # Model tried to call tools when none were offered — ask for JSON.
            messages.append(_assistant_message(msg))
            messages.append(json_repair_nudge())
            continue
        messages.append(_assistant_message(msg))
        for call in repair_tool_calls(msg.tool_calls):
            cid = call["id"] if isinstance(call, dict) else call.id
            messages.append({
                "role": "tool",
                "tool_call_id": cid,
                "content": dispatch_tool(call, cwd),
            })
        messages = compact_if_needed(messages)

    raise FGError("sdk dispatch exceeded max turns without a final answer")
