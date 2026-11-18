"""Dispatch workers: reason/explore/verify/blindspot/brainstorm payload handling."""
from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

from ben.core.parse import parse_from
from ben.consts import GOAL_ID
from ben.core.errors import FGError
from ben.core.io import _scrub_inline, now_iso
from ben.core.schema import normalize_fact_kind
from ben.core.store import Store
from ben.llm.jsonx import extract_json_object
from ben.llm.runner import run_claude
from ben.agents.prompt import _replace_placeholders, render_intent_prompt, render_prompt



def _agents_system_prompt(store: Store) -> str:
    """Load executor system prompt; only ``store.root`` is interpolated."""
    tpl_path = Path(__file__).resolve().parent / "prompts" / "executor.md"
    tpl = tpl_path.read_text(encoding="utf-8")
    return tpl.replace("{store_root}", str(store.root))


def _worker_id(model: str) -> str:
    """Per-process worker identity so two concurrent executors don't look
    identical to the claim check."""
    return f"{model}-{os.getpid()}"


# Print-facing reason/explore/verify live in ben.agents.dispatch (R-08).
# Re-export names kept for `import ben` / tests via ben/__init__.py.


def _run_blindspot(store, templates_dir, model, timeout, skip, cwd, args) -> int:
    tpl = _load_template(templates_dir, "blindspot.md")
    prompt = render_prompt(store, tpl)
    if args.dry_run:
        print(prompt)
        return 0
    envelope = run_claude(
        prompt,
        model=model, timeout=timeout, skip_permissions=skip,
        append_system=None, cwd=cwd,
    )
    text = envelope.get("result", "")
    payload = extract_json_object(text)
    summary = _apply_blindspot(store, payload)
    print(f"[blindspot] {summary}")
    return 0


def _apply_blindspot(store: Store, payload: dict) -> str:
    """Parse blindspot output and record each as a hint."""
    if not isinstance(payload, dict):
        raise FGError("blindspot payload must be a JSON object")
    if payload.get("accepted") is False:
        return "blindspot analysis rejected"
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        raise FGError(f"invalid blindspot payload: {payload}")
    spots = data.get("blindspots", [])
    if not isinstance(spots, list):
        raise FGError("blindspots must be a list")
    if not spots:
        return "no blindspots identified"
    recorded = []
    for spot in spots[:7]:
        if not isinstance(spot, dict):
            continue
        area = str(spot.get("area", "unknown")).strip() or "unknown"
        risk = str(spot.get("risk", "medium")).strip().lower() or "medium"
        if risk not in {"high", "medium", "low"}:
            risk = "medium"
        question = str(spot.get("question", "")).strip()
        suggestion = str(spot.get("suggestion", "")).strip()
        if not question:
            continue
        content = f"[blindspot/{risk}] {area}: {question}"
        if suggestion:
            content += f" — suggestion: {suggestion}"
        store.add_hint(content=content, creator="blindspot")
        recorded.append(area)
    return f"identified {len(recorded)} blindspot(s): {', '.join(recorded)}"


def _run_brainstorm(store, templates_dir, model, timeout, skip, cwd, args) -> int:
    if args.max_options < 1 or args.max_options > 20:
        raise FGError("--max-options must be between 1 and 20")
    tpl = _load_template(templates_dir, "brainstorm.md")
    max_options = str(getattr(args, "max_options", 4))
    # Fill this template-only token before graph content is inserted.  A
    # second pass over an already-rendered prompt would rewrite a fact that
    # legitimately contains the literal text `{max_options}`.
    tpl = tpl.replace("{max_options}", max_options)
    prompt = render_prompt(store, tpl)
    if args.dry_run:
        print(prompt)
        return 0
    envelope = run_claude(
        prompt,
        model=model, timeout=timeout, skip_permissions=skip,
        append_system=None, cwd=cwd,
    )
    text = envelope.get("result", "")
    payload = extract_json_object(text)
    summary = _apply_brainstorm(store, payload, max_options=args.max_options)
    print(f"[brainstorm] {summary}")
    return 0


def _apply_brainstorm(store: Store, payload: dict, max_options: int | None = None) -> str:
    """Parse brainstorm output: create requires_confirmation intents for each option."""
    if not isinstance(payload, dict):
        raise FGError("brainstorm payload must be a JSON object")
    if max_options is not None and (max_options < 1 or max_options > 20):
        raise FGError("max_options must be between 1 and 20")
    if payload.get("accepted") is False:
        return "brainstorm rejected"
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        raise FGError(f"invalid brainstorm payload: {payload}")
    options = data.get("options", [])
    if not isinstance(options, list):
        raise FGError("options must be a list")
    if not options:
        return "no options generated"
    # ISO timestamps only have second precision; two brainstorm calls in one
    # second used to share a tag and picking one could abandon the other's
    # options.  Add cryptographic entropy so batches are always disjoint.
    batch_tag = f"brainstorm-{now_iso()}-{secrets.token_hex(6)}"
    existing_facts = {f["id"] for f in store.list_facts()}
    made = []
    if max_options is not None:
        options = options[:max_options]
    for opt in options:
        if not isinstance(opt, dict):
            continue
        raw_from = opt.get("from", [])
        if isinstance(raw_from, str):
            raw_from = parse_from(raw_from)
        if not isinstance(raw_from, list):
            continue
        from_ids = [str(x) for x in raw_from]
        if not from_ids:
            continue
        bad = [x for x in from_ids if x not in existing_facts or x == GOAL_ID]
        if bad:
            continue
        raw_desc = opt.get("description", "")
        desc = raw_desc.strip() if isinstance(raw_desc, str) else ""
        if not desc:
            continue
        title = opt.get("title")
        title = title.strip() if isinstance(title, str) and title.strip() else None
        effort = str(opt.get("effort", "medium")).strip().lower() or "medium"
        if effort not in {"low", "medium", "high"}:
            effort = "medium"
        raw_doc = opt.get("doc", "")
        doc_text = raw_doc.strip() if isinstance(raw_doc, str) else ""
        doc_text = f"[brainstorm batch: {batch_tag}]\n[effort: {effort}]\n\n{doc_text}".strip()
        intent = store.add_intent(
            from_ids=from_ids,
            description=desc,
            creator="brainstorm",
            requires_confirmation=True,
            title=title,
            doc=doc_text,
        )
        made.append(intent["id"])
    if not made:
        return "no valid options (check from-facts exist)"
    return f"proposed {len(made)} options (confirm one with `ben brainstorm-pick <id>`): {', '.join(made)}"


def cmd_brainstorm_pick(args) -> int:
    """Pick one brainstorm option: confirm it, abandon siblings from same batch."""
    store = Store(Path(args.store))
    store.require()
    picked_id = args.id
    picked = store.get_intent(picked_id)
    if picked["to"] is not None:
        raise FGError(f"{picked_id} already concluded")
    if not picked["requires_confirmation"]:
        raise FGError(f"{picked_id} is not a brainstorm option (no confirmation required)")
    doc = picked.get("doc") or ""
    batch_tag = None
    for line in doc.split("\n"):
        if line.startswith("[brainstorm batch: "):
            batch_tag = line.split(": ", 1)[1].rstrip("]")
            break
    if not batch_tag:
        raise FGError(f"{picked_id} has no brainstorm batch tag in its doc")
    if not picked["confirmed_at"]:
        store.confirm_intent(picked_id)
    all_intents = store.list_intents()
    abandoned = []
    for i in all_intents:
        if i["id"] == picked_id:
            continue
        if i["to"] is not None:
            continue
        i_doc = i.get("doc") or ""
        if f"[brainstorm batch: {batch_tag}]" in i_doc:
            fact, _ = store.conclude_with_new_fact(
                i["id"],
                f"option abandoned in favor of {picked_id}",
                "brainstorm-pick",
                title="已弃用",
                allow_unconfirmed=True,
                force=True,
            )
            abandoned.append(i["id"])
    print(f"confirmed {picked_id}, abandoned {len(abandoned)} sibling(s): {', '.join(abandoned) or '(none)'}")
    return 0


def _load_template(templates_dir: Path, name: str) -> str:
    p = templates_dir / name
    if not p.exists():
        raise FGError(f"template not found: {p}")
    return p.read_text(encoding="utf-8")


def _classify_reason_payload(payload: dict) -> tuple[str, dict | list | None]:
    """Mirror Star's reason contract: complete | intents | noop | rejected."""
    if not isinstance(payload, dict):
        raise FGError("reason payload must be a JSON object")
    if payload.get("accepted") is False:
        return "rejected", None
    data = payload.get("data") if isinstance(payload.get("data"), dict) else (
        payload if _looks_reason(payload) else None
    )
    if data is None:
        raise FGError(f"unrecognized reason payload: {payload}")
    if "complete" in data:
        c = data["complete"]
        if not isinstance(c, dict) or "from" not in c or "description" not in c:
            raise FGError("invalid complete payload")
        return "complete", c
    if "intents" in data:
        ints = data["intents"]
        if not isinstance(ints, list):
            raise FGError("intents must be a list")
        return "intents", ints
    return "noop", None


def _looks_reason(payload: dict) -> bool:
    keys = set(payload)
    return keys & {"complete", "intents", "intent"}


def _apply_reason(store: Store, kind: str, data) -> str:
    if kind == "rejected":
        return "commander rejected the task"
    if kind == "noop":
        return "commander returned no new work (open intents already cover it)"
    if kind == "complete":
        comp = data
        raw_from = comp.get("from")
        if not isinstance(raw_from, list):
            raise FGError("complete.from must be a list of fact ids")
        from_ids = [str(x) for x in raw_from]
        note = comp.get("description", "goal satisfied")
        if not isinstance(note, str) or not note.strip():
            raise FGError("complete.description must be a non-empty string")
        intent = store.complete_project(from_ids, note, "reason")
        return f"goal complete via {intent['id']}"
    if kind == "intents":
        # Validate each candidate before writing it. Invalid model entries are
        # ignored without allowing a malformed id to reach the filesystem.
        existing = {f["id"] for f in store.list_facts()}
        made = []
        for it in data[:3]:
            if not isinstance(it, dict):
                continue
            raw_from = it.get("from", [])
            if isinstance(raw_from, str):
                raw_from = parse_from(raw_from)
            if not isinstance(raw_from, list):
                continue
            from_ids = [str(x) for x in raw_from]
            if not from_ids:
                continue
            bad = [x for x in from_ids if x not in existing or x == GOAL_ID]
            if bad:
                # skip invalid rather than aborting the whole batch
                continue
            raw_desc = it.get("description", "")
            desc = raw_desc.strip() if isinstance(raw_desc, str) else ""
            if not desc:
                continue
            req = bool(it.get("requires_confirmation", False))
            t = it.get("title")
            t = t.strip() if isinstance(t, str) and t.strip() else None
            d = it.get("doc")
            d = d.strip() if isinstance(d, str) and d.strip() else None
            intent = store.add_intent(
                from_ids=from_ids, description=desc, creator="reason",
                requires_confirmation=req, title=t, doc=d,
            )
            made.append(intent["id"])
        return f"proposed intents: {', '.join(made) if made else '(none valid)'}"
    return "unknown"


def _parse_explore_payload(payload: dict) -> tuple[str | None, str, str | None, str | None, dict | None]:
    """Return (title, description, doc, kind, data). title/doc/kind/data may be None."""
    if payload.get("accepted") is False:
        raise FGError(f"executor rejected: {payload.get('reason','')}")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        raise FGError(f"invalid explore payload: {payload}")
    desc = data.get("description")
    if not isinstance(desc, str) or not desc.strip():
        raise FGError("explore payload missing 'description'")
    title = data.get("title")
    title = title.strip() if isinstance(title, str) and title.strip() else None
    doc = data.get("doc")
    doc = doc.strip() if isinstance(doc, str) and doc.strip() else None
    kind = normalize_fact_kind(data.get("kind") if isinstance(data.get("kind"), str) else None)
    fdata = data.get("data") if isinstance(data.get("data"), dict) else None
    deviations = data.get("deviations")
    if isinstance(deviations, list) and deviations:
        lines = ["\n\n## Deviations\n"]
        for d in deviations:
            if isinstance(d, dict):
                planned = d.get("planned", "")
                actual = d.get("actual", "")
                reason = d.get("reason", "")
                lines.append(f"- **Planned:** {planned} → **Actual:** {actual} — *Reason:* {reason}")
        if len(lines) > 1:
            doc = (doc or "") + "\n".join(lines)
    return title, desc.strip(), doc, kind, fdata


def _parse_verify_payload(payload: dict) -> tuple[bool, str]:
    if not isinstance(payload, dict):
        raise FGError("verify payload must be a JSON object")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        raise FGError(f"invalid verify payload: {payload}")
    verified = data.get("verified")
    if not isinstance(verified, bool):
        raise FGError("verify payload missing boolean 'verified'")
    issues = data.get("issues", "") or ""
    if not isinstance(issues, str):
        raise FGError("verify payload 'issues' must be a string")
    issues = issues.strip()
    if not verified and not issues:
        raise FGError("verify payload must explain a failed verification in 'issues'")
    if verified and issues:
        raise FGError("verify payload must leave 'issues' empty when verified")
    return verified, issues
