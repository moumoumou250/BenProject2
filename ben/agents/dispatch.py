"""Unified reason / explore / LLM-verify dispatch (R-08).

Print vs return is the caller's choice. ``ben dispatch verify`` here is the
*LLM* post-hoc review — machine evidence is ``ben verify`` (commands.verify_cmds).

NOTE: ``ben.commands.commander`` still has its own ``run_claude`` +
``extract_json_object`` path; that remains a known exception until a later
commander pass (R-09 tail).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ben.agents.factory import (
    _agents_system_prompt,
    _apply_reason,
    _classify_reason_payload,
    _load_template,
    _parse_explore_payload,
    _parse_verify_payload,
    _worker_id,
)
from ben.agents.prompt import _replace_placeholders, render_intent_prompt, render_prompt
from ben.core.errors import FGError
from ben.core.io import _scrub_inline
from ben.core.log import run_event
from ben.core.store import Store
from ben.llm.jsonx import extract_json_object
from ben.llm.runner import run_claude


@dataclass
class DispatchResult:
    ok: bool
    summary: str
    exit_code: int = 0
    kind: str | None = None
    fact: dict | None = None
    issues: str | None = None
    payload: Any = None


def dispatch_reason(
    store: Store,
    templates_dir: Path,
    model: str,
    timeout: int,
    skip: bool,
    cwd: Path,
    *,
    time_budget: str = "",
    dry_run: bool = False,
) -> DispatchResult:
    run_event("dispatch_start", target="reason", model=model)
    tpl = _load_template(templates_dir, "reason.md")
    prompt = render_prompt(store, tpl, time_budget=time_budget)
    if dry_run:
        return DispatchResult(ok=True, summary=prompt, payload=prompt)
    envelope = run_claude(
        prompt, model=model, timeout=timeout, skip_permissions=skip,
        append_system=None, cwd=cwd, tier="main",
    )
    payload = extract_json_object(envelope.get("result", ""))
    kind, data = _classify_reason_payload(payload)
    summary = _apply_reason(store, kind, data)
    run_event("dispatch_end", target="reason", kind=kind)
    return DispatchResult(ok=True, summary=summary, kind=kind, payload=data)


def dispatch_explore(
    store: Store,
    templates_dir: Path,
    intent: dict,
    model: str,
    timeout: int,
    skip: bool,
    cwd: Path,
    *,
    claim: bool = False,
    dry_run: bool = False,
    warn_permissions: bool = True,
) -> DispatchResult:
    run_event("dispatch_start", target="explore", intent=intent.get("id"), model=model)
    if intent["to"] is not None:
        fact = store.get_fact(intent["to"])
        summary = (
            f"{intent['id']} already concluded -> {fact['id']}: {fact['description']}"
        )
        return DispatchResult(ok=True, summary=summary, fact=fact)

    if intent.get("requires_confirmation") and not intent.get("confirmed_at"):
        raise FGError(
            f"intent {intent['id']} requires confirmation; run `ben confirm {intent['id']}` first"
        )
    if warn_permissions and not skip:
        sys.stderr.write(
            "[warn] explore without --skip-permissions will prompt for every "
            "tool use; pass --skip-permissions for autonomous runs.\n"
        )

    worker = _worker_id(model)
    tpl = _load_template(templates_dir, "explore.md")
    prompt = render_intent_prompt(store, tpl, intent)
    if dry_run:
        return DispatchResult(ok=True, summary=prompt, payload=prompt)

    claimed = False
    if claim:
        store.claim_intent(intent["id"], worker)
        claimed = True
    from ben.llm.llm import flash_configured

    tier = "flash" if flash_configured() else "main"
    try:
        envelope = run_claude(
            prompt, model=model, timeout=timeout, skip_permissions=skip,
            append_system=_agents_system_prompt(store), cwd=cwd,
            tools=True, tier=tier,
        )
        payload = extract_json_object(envelope.get("result", ""))
        title, desc, doc, kind, fdata = _parse_explore_payload(payload)
        fact, concluded = store.conclude_with_new_fact(
            intent["id"], desc, worker, title=title, doc=doc, kind=kind, data=fdata,
            force=True,
        )
        store.add_hint(
            f"forced conclude of {concluded['id']} via explore (no machine evidence)",
            worker,
        )
        run_event("dispatch_end", target="explore", intent=concluded["id"], fact=fact["id"])
        return DispatchResult(
            ok=True,
            summary=f"{concluded['id']} -> {fact['id']}: {desc}",
            fact=fact,
        )
    except Exception:
        if claimed:
            try:
                store.release_intent(intent["id"], worker)
            except FGError:
                pass
        raise


def _dispatch_reason(store, templates_dir, model, timeout, skip, cwd, args) -> int:
    result = dispatch_reason(
        store, templates_dir, model, timeout, skip, cwd,
        time_budget=getattr(args, "time_budget", "") or "",
        dry_run=bool(getattr(args, "dry_run", False)),
    )
    if getattr(args, "dry_run", False):
        print(result.summary)
        return 0
    print(f"[reason] {result.summary}")
    return result.exit_code


def _dispatch_explore(store, templates_dir, intent, model, timeout, skip, cwd, args) -> int:
    result = dispatch_explore(
        store, templates_dir, intent, model, timeout, skip, cwd,
        claim=bool(getattr(args, "claim", False)),
        dry_run=bool(getattr(args, "dry_run", False)),
        warn_permissions=True,
    )
    if getattr(args, "dry_run", False):
        print(result.summary)
        return 0
    print(f"[explore] {result.summary}")
    return result.exit_code


def _dispatch_verify(store, templates_dir, model, timeout, skip, cwd, args) -> int:
    """LLM post-hoc verify — see also machine ``ben verify`` (evidence gate)."""
    if not args.intent:
        raise FGError("verify requires --intent <id>")
    intent = store.get_intent(args.intent)
    result = dispatch_verify_llm(
        store, templates_dir, intent, model, timeout, skip, cwd,
        dry_run=bool(getattr(args, "dry_run", False)),
    )
    if getattr(args, "dry_run", False):
        print(result.summary)
        return 0
    print(f"[verify] {result.summary}")
    return result.exit_code


def dispatch_verify_llm(
    store: Store,
    templates_dir: Path,
    intent: dict,
    model: str,
    timeout: int,
    skip: bool,
    cwd: Path,
    *,
    dry_run: bool = False,
) -> DispatchResult:
    """LLM post-hoc verify (``ben dispatch verify``), not machine ``ben verify``."""
    run_event("dispatch_start", target="verify_llm", intent=intent.get("id"))
    if intent["to"] is None:
        raise FGError(f"intent {intent['id']} not concluded yet")
    fact = store.get_fact(intent["to"])
    tpl = _load_template(templates_dir, "verify.md")
    prompt = _replace_placeholders(tpl, {
        "intent_description": _scrub_inline(intent["description"]),
        "result_description": _scrub_inline(fact["description"]),
    })
    if dry_run:
        return DispatchResult(ok=True, summary=prompt, payload=prompt)
    envelope = run_claude(
        prompt, model=model, timeout=timeout, skip_permissions=skip,
        append_system=None, cwd=cwd,
    )
    payload = extract_json_object(envelope.get("result", ""))
    verified, issues = _parse_verify_payload(payload)
    tag = "VERIFIED" if verified else "FAILED"
    summary = f"{intent['id']}: {tag}" + (f" — {issues}" if issues else "")
    run_event("dispatch_end", target="verify_llm", intent=intent["id"], ok=verified)
    return DispatchResult(
        ok=verified,
        summary=summary,
        exit_code=0 if verified else 1,
        issues=issues or None,
        fact=fact,
    )
