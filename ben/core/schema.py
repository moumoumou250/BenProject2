"""Fact/intent schema validation and node reading."""
from __future__ import annotations

import json
from pathlib import Path

from ben.consts import DATA_KEY_RE, FACT_KINDS, GOAL_ID, _VALID_NODE_ID_RE
from ben.core.errors import FGError
from ben.core.io import read_json


def normalize_fact_kind(kind: str | None) -> str | None:
    """Validate + canonicalize a fact kind. None/empty -> None (untyped)."""
    if kind is None:
        return None
    k = kind.strip().lower()
    if not k:
        return None
    if k not in FACT_KINDS:
        raise FGError(
            f"unknown fact kind {kind!r}; expected one of: {', '.join(FACT_KINDS)}"
        )
    return k


def normalize_fact_data(data: dict | None) -> dict[str, str] | None:
    """Validate fact `data`: flat object, scalar values, safe keys."""
    if data is None:
        return None
    if not isinstance(data, dict):
        raise FGError("fact data must be an object of key=value scalars")
    out: dict[str, str] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not DATA_KEY_RE.match(key):
            raise FGError(f"fact data key {key!r} must match [A-Za-z0-9_.-]+")
        if value is None:
            continue
        if isinstance(value, bool):
            value = "true" if value else "false"
        if not isinstance(value, (str, int, float)):
            raise FGError(f"fact data value for {key!r} must be a scalar")
        out[key] = str(value)
    return out or None


def parse_kv_pairs(pairs: list[str] | None) -> dict[str, str]:
    """Parse CLI `--data key=value` repeatable args into a dict."""
    out: dict[str, str] = {}
    for item in pairs or []:
        if "=" not in item:
            raise FGError(f"--data expects key=value, got {item!r}")
        key, _, value = item.partition("=")
        key = key.strip()
        if not key:
            raise FGError(f"--data key cannot be empty: {item!r}")
        out[key] = value
    return out


def _validate_lookup_id(node_id: str, kind: str) -> None:
    """Reject path-like ids before they are interpolated into a filename.

    Graph ids are generated internally, but `show`, `doc`, and dispatch accept
    ids from the command line.  Validating at that boundary prevents `../` or
    absolute-path lookups from escaping the selected graph directory.
    """
    if not isinstance(node_id, str):
        raise FGError(f"invalid {kind} id")
    if node_id == GOAL_ID and kind in ("fact", "node"):
        return
    if not _VALID_NODE_ID_RE.fullmatch(node_id):
        raise FGError(f"invalid {kind} id {node_id!r}")


def _read_node(path: Path, kind: str) -> dict:
    """Read one node and turn corruption into a concise CLI error."""
    try:
        data = read_json(path)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError, TypeError, ValueError) as exc:
        raise FGError(f"cannot read {kind} {path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise FGError(f"invalid {kind} {path.name}: expected a JSON object")
    errors = _node_schema_errors(data, kind)
    if errors:
        raise FGError(f"invalid {kind} {path.name}: {'; '.join(errors)}")
    if path.stem != data["id"]:
        raise FGError(
            f"invalid {kind} {path.name}: filename does not match id {data['id']!r}"
        )
    return data


def _node_schema_errors(data: object, kind: str) -> list[str]:
    """Return schema errors for records used by renderers and graph logic."""
    if not isinstance(data, dict):
        return ["expected a JSON object"]
    errors: list[str] = []
    node_id = data.get("id")
    if not isinstance(node_id, str):
        errors.append("missing string 'id'")
    elif node_id == GOAL_ID and kind != "fact":
        errors.append("reserved 'id' is only valid for the goal fact")
    elif node_id != GOAL_ID and not _VALID_NODE_ID_RE.fullmatch(node_id):
        errors.append("invalid 'id'")
    if kind == "fact":
        if not isinstance(data.get("description"), str):
            errors.append("missing string 'description'")
        if not isinstance(data.get("created_at"), str):
            errors.append("missing string 'created_at'")
        if not isinstance(data.get("creator"), str):
            errors.append("missing string 'creator'")
        if "source_intent" in data and data["source_intent"] is not None and not isinstance(data["source_intent"], str):
            errors.append("'source_intent' must be a string or null")
        if "source_intent" not in data:
            errors.append("missing 'source_intent'")
        if "title" in data and data["title"] is not None and not isinstance(data["title"], str):
            errors.append("'title' must be a string or null")
        if "doc" in data and data["doc"] is not None and not isinstance(data["doc"], str):
            errors.append("'doc' must be a string or null")
        if "kind" in data and data["kind"] is not None:
            if not isinstance(data["kind"], str) or data["kind"] not in FACT_KINDS:
                errors.append(f"'kind' must be null or one of: {', '.join(FACT_KINDS)}")
        if "data" in data and data["data"] is not None:
            d = data["data"]
            if not isinstance(d, dict):
                errors.append("'data' must be an object or null")
            else:
                for key, value in d.items():
                    if not isinstance(key, str) or not DATA_KEY_RE.match(key):
                        errors.append("'data' key must match [A-Za-z0-9_.-]+")
                        break
                    if not isinstance(value, (str, int, float)):
                        errors.append("'data' values must be scalars")
                        break
    elif kind == "intent":
        if not isinstance(data.get("from"), list) or not data.get("from") or not all(
            isinstance(x, str) and x != GOAL_ID and _VALID_NODE_ID_RE.fullmatch(x)
            for x in data.get("from", [])
        ):
            errors.append("'from' must be a list of strings")
        if "to" not in data or (
            data.get("to") is not None
            and (
                not isinstance(data.get("to"), str)
                or (data.get("to") != GOAL_ID and not _VALID_NODE_ID_RE.fullmatch(data.get("to")))
            )
        ):
            errors.append("'to' must be a string or null")
        if not isinstance(data.get("description"), str):
            errors.append("missing string 'description'")
        if not isinstance(data.get("created_at"), str):
            errors.append("missing string 'created_at'")
        if not isinstance(data.get("status"), str):
            errors.append("missing string 'status'")
        elif data["status"] not in {"open", "claimed", "done", "complete"}:
            errors.append("invalid 'status'")
        if "worker" not in data or (data.get("worker") is not None and not isinstance(data.get("worker"), str)):
            errors.append("'worker' must be a string or null")
        if not isinstance(data.get("requires_confirmation"), bool):
            errors.append("missing boolean 'requires_confirmation'")
        if "confirmed_at" not in data or (data.get("confirmed_at") is not None and not isinstance(data.get("confirmed_at"), str)):
            errors.append("'confirmed_at' must be a string or null")
        status = data.get("status")
        target = data.get("to")
        if status in {"done", "complete"} and target is None:
            errors.append("completed status requires a target")
        if status in {"open", "claimed"} and target is not None:
            errors.append("open/claimed status cannot have a target")
        if status == "complete" and target != GOAL_ID:
            errors.append("complete status must target goal")
        if status == "done" and target == GOAL_ID:
            errors.append("done status cannot target goal")
        if "title" in data and data["title"] is not None and not isinstance(data["title"], str):
            errors.append("'title' must be a string or null")
        if "doc" in data and data["doc"] is not None and not isinstance(data["doc"], str):
            errors.append("'doc' must be a string or null")
    elif kind == "hint":
        if not isinstance(data.get("content"), str):
            errors.append("missing string 'content'")
        if not isinstance(data.get("creator"), str):
            errors.append("missing string 'creator'")
        if not isinstance(data.get("created_at"), str):
            errors.append("missing string 'created_at'")
    return errors


def _check_conclusion_permission(
    intent: dict, worker: str | None, allow_unconfirmed: bool,
) -> None:
    if intent.get("requires_confirmation") and not intent.get("confirmed_at") and not allow_unconfirmed:
        raise FGError(
            f"intent {intent['id']} requires confirmation; run `ben confirm {intent['id']}` first"
        )
    owner = intent.get("worker")
    if owner and owner != worker:
        raise FGError(f"intent {intent['id']} claimed by {owner}")
