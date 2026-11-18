"""Graph views: readiness, validation, frontier."""
from __future__ import annotations

import json

from ben.consts import GOAL_ID
from ben.core.errors import FGError
from ben.core.io import read_json
from ben.core.schema import _node_schema_errors
from ben.core.store import Store


def is_open(intent: dict) -> bool:
    return intent["to"] is None


def is_ready(intent: dict, fact_ids: set[str] | None = None) -> bool:
    """Whether an intent can be worked safely.

    ``fact_ids`` is optional for callers that only need the state/confirmation
    check.  The frontier passes the current set so a manually deleted or
    corrupted dependency cannot remain actionable.
    """
    if not is_open(intent):
        return False
    if fact_ids is not None and not set(intent.get("from", ())).issubset(fact_ids):
        return False
    if intent.get("requires_confirmation") and not intent.get("confirmed_at"):
        return False
    return True


def build_graph_view(store: Store) -> dict:
    """Materialize the whole graph for prompt rendering / display."""
    facts = store.list_facts()
    intents = store.list_intents()
    hints = store.list_hints()
    fact_ids = {f["id"] for f in facts}
    open_intents = [i for i in intents if is_open(i)]
    done_intents = [i for i in intents if not is_open(i)]
    return {
        "project": store.load_project(),
        "facts": facts,
        "intents": intents,
        "open_intents": open_intents,
        "done_intents": done_intents,
        "hints": hints,
        "fact_ids": sorted(fact_ids),
    }


def validate_graph(store: Store) -> list[str]:
    """Return integrity errors without mutating the graph.

    Normal read commands deliberately skip malformed node files so a damaged
    graph remains inspectable.  This explicit audit command gives operators a
    complete, actionable report before they dispatch agents or commit `.ben/`.
    """
    errors: list[str] = []
    try:
        project = store.load_project()
    except FGError as exc:
        return [str(exc)]
    if project.get("status") not in {"active", "completed"}:
        errors.append(f"project status must be 'active' or 'completed', got {project.get('status')!r}")
    counters = project.get("counters", {})
    for kind in ("fact", "intent", "hint", "run"):
        if kind not in counters:
            errors.append(f"project counters missing {kind!r}")

    by_kind: dict[str, dict[str, dict]] = {"fact": {}, "intent": {}, "hint": {}}
    dirs = {"fact": store.facts_dir, "intent": store.intents_dir, "hint": store.hints_dir}
    for kind, directory in dirs.items():
        for path in sorted(directory.glob("*.json")):
            try:
                data = read_json(path)
            except (json.JSONDecodeError, UnicodeDecodeError, OSError, TypeError, ValueError) as exc:
                errors.append(f"{kind} {path.name}: unreadable JSON ({exc})")
                continue
            schema = _node_schema_errors(data, kind)
            if schema:
                errors.append(f"{kind} {path.name}: {'; '.join(schema)}")
                continue
            node_id = data["id"]
            if path.stem != node_id:
                errors.append(f"{kind} {path.name}: filename does not match id {node_id!r}")
            if node_id in by_kind[kind]:
                errors.append(f"duplicate {kind} id {node_id!r}")
            by_kind[kind][node_id] = data

    facts = by_kind["fact"]
    intents = by_kind["intent"]
    if GOAL_ID not in facts:
        errors.append("missing terminal goal fact")
    elif facts[GOAL_ID].get("description") != project.get("goal"):
        errors.append("goal fact description does not match project goal")
    for iid, intent in intents.items():
        for fid in intent["from"]:
            if fid not in facts:
                errors.append(f"intent {iid}: missing dependency fact {fid}")
            elif fid == GOAL_ID:
                errors.append(f"intent {iid}: goal cannot be a dependency")
        target = intent["to"]
        if target is not None and target != GOAL_ID and target not in facts:
            errors.append(f"intent {iid}: target fact {target} does not exist")
        elif target is not None and target != GOAL_ID and facts[target].get("source_intent") != iid:
            errors.append(f"intent {iid}: target fact {target} does not name it as source intent")
    for fid, fact in facts.items():
        source = fact.get("source_intent")
        if source is not None and source not in intents:
            errors.append(f"fact {fid}: source intent {source} does not exist")
        elif source is not None and intents[source].get("to") != fid:
            errors.append(f"fact {fid}: source intent {source} does not point to this fact")
    goal_intents = [i for i in intents.values() if i["to"] == GOAL_ID]
    if project.get("status") == "completed" and not goal_intents:
        errors.append("project is completed but no intent targets the goal")
    if project.get("status") == "active" and goal_intents:
        errors.append("project is active although an intent already targets the goal")
    return errors


def frontier(store: Store) -> list[dict]:
    intents = store.list_intents()
    fact_ids = {f["id"] for f in store.list_facts()}
    ready = [i for i in intents if is_ready(i, fact_ids)]
    # claimed intents first (someone's already on them but they're still in-flight),
    # then by creation order.
    ready.sort(key=lambda i: (i["status"] != "claimed", i["created_at"]))
    return ready
