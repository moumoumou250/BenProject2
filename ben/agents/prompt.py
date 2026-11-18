"""Prompt / history / graph-text rendering."""
from __future__ import annotations

import json
import re

from ben import config
from ben.consts import GOAL_ID
from ben.core.graph import build_graph_view, is_open
from ben.core.io import _prompt_inline, _scrub_inline
from ben.core.recall import recall
from ben.core.store import Store


def _visible_hints(hints: list[dict]) -> list[dict]:
    """Broadcast hints (no ``to``) plus hints addressed to this worker."""
    worker = config.get("BEN_WORKER")
    out = []
    for h in hints:
        dest = h.get("to")
        if dest is None or dest == "":
            out.append(h)
        elif worker and dest == worker:
            out.append(h)
    return out


def render_recall(matches: list[dict], query: str) -> str:
    """Human-readable recall output. First line is a usage hint so the
    caller (model or human) knows the next step is `ben doc <id>`."""
    if not matches:
        return f"(no similar prior work for {query!r})"
    lines = [
        f"# recall for: {query}",
        "# use `ben doc <id>` to read the detailed document",
        "",
    ]
    for m in matches:
        title = f"[{_scrub_inline(m['title'])}]  " if m["title"] else ""
        doc = "  📄" if m["has_doc"] else ""
        desc = _scrub_inline(m["description"])[:90]
        lines.append(
            f"  {m['id']} ({m['kind']}, score={m['score']:.2f})  "
            f"{title}{desc}{doc}"
        )
    return "\n".join(lines)


from ben.report.history import render_history_block  # noqa: E402,F401 — re-export




def render_graph_text(store: Store) -> str:
    g = build_graph_view(store)
    lines = [f"# graph  ({_scrub_inline(g['project']['status'])})"]
    lines.append("")
    lines.append("## facts")
    for f in g["facts"]:
        src = f"  <- {_scrub_inline(f['source_intent'])}" if f.get("source_intent") else ""
        t = f"[{_scrub_inline(f['title'])}]  " if f.get("title") else ""
        k = f"<{f['kind']}>" if f.get("kind") else ""
        data = ""
        if f.get("data"):
            pairs = " ".join(f"{key}={_scrub_inline(str(val))}" for key, val in f["data"].items())
            data = f"  ({pairs})"
        doc = "  📄" if f.get("doc") else ""
        lines.append(f"  {f['id']}: {k}{t}{_scrub_inline(f['description'])}{data}{src}{doc}")
    lines.append("")
    lines.append("## intents")
    for i in g["intents"]:
        to = i["to"] or "·"
        flag = ""
        if i["requires_confirmation"] and not i["confirmed_at"]:
            flag = "  !confirm"
        elif i["status"] == "claimed":
            flag = f"  ~{i['worker']}"
        t = f"[{_scrub_inline(i['title'])}]  " if i.get("title") else ""
        doc = "  📄" if i.get("doc") else ""
        lines.append(f"  {i['id']}: {i['from']} -> {to}  {t}{_scrub_inline(i['description'])[:70]}{flag}{doc}")
    hints = _visible_hints(g["hints"])
    if hints:
        lines.append("")
        lines.append("## hints")
        for h in hints:
            lines.append(f"  {h['id']} ({_scrub_inline(h['creator'])}): {_scrub_inline(h['content'])}")
    return "\n".join(lines)


def render_prompt(store: Store, template_text: str, time_budget: str = "") -> str:
    """Render a prompt template with the current graph. Simple {key} substitution."""
    g = build_graph_view(store)
    p = g["project"]
    hints = _visible_hints(g["hints"])
    replacements = {
        "origin": _prompt_inline(p["origin"]),
        "goal": _prompt_inline(p["goal"]),
        "graph_yaml": _to_yaml_like(g),
        "fact_ids": json.dumps(g["fact_ids"], ensure_ascii=False, indent=2),
        "open_intents": json.dumps(
            [_intent_brief(i) for i in g["open_intents"]],
            ensure_ascii=False, indent=2,
        ),
        "hints": json.dumps(
            [_hint_brief(h) for h in hints], ensure_ascii=False, indent=2
        ),
        "max_intents": "3",
        "time_budget": _prompt_inline(time_budget),
    }
    return _replace_placeholders(template_text, replacements)


def render_intent_prompt(store: Store, template_text: str, intent: dict) -> str:
    g = build_graph_view(store)
    # Recall: surface prior facts/intents whose title/description look similar
    # to THIS intent. Excludes the intent itself (it would otherwise score 1.0
    # against its own description). Keep small (5) — the model just needs a
    # short list of ids it can `ben doc` into.
    matches = [m for m in recall(store, intent.get("description", ""), limit=6)
               if m["id"] != intent["id"]][:5]
    recall_block = render_recall(matches, intent.get("description", "")) \
        if matches else "(no prior nodes look similar to this intent)"
    replacements = {
        "graph_yaml": _to_yaml_like(g),
        "intent_id": intent["id"],
        "intent_description": _prompt_inline(intent["description"]),
        "recall_block": recall_block,
    }
    return _replace_placeholders(template_text, replacements)


def _replace_placeholders(template_text: str, replacements: dict[str, str]) -> str:
    """Substitute template tokens in one pass.

    Repeated ``str.replace`` calls re-scan inserted graph content, so a fact
    containing text such as ``{goal}`` could accidentally rewrite a later
    placeholder.  A regex pass only touches tokens present in the template.
    """
    return re.sub(
        r"\{([A-Za-z_][A-Za-z0-9_]*)\}",
        lambda match: replacements.get(match.group(1), match.group(0)),
        template_text,
    )


def _intent_brief(i: dict) -> dict:
    return {
        "id": i["id"],
        "from": i["from"],
        "description": i["description"],
        "requires_confirmation": i["requires_confirmation"],
        "confirmed": bool(i["confirmed_at"]),
    }


def _hint_brief(h: dict) -> dict:
    brief = {"id": h["id"], "creator": h["creator"], "content": h["content"]}
    if h.get("to"):
        brief["to"] = h["to"]
    return brief


def _to_yaml_like(g: dict) -> str:
    """Compact human-readable dump of the graph for prompts.
    Shows title + description (the two summary layers) but NOT `doc` — the
    detailed layer is opt-in, read via `ben doc <id>`, so prompts stay small."""
    lines = []
    lines.append(f"project: status={_prompt_inline(g['project']['status'])}")
    lines.append(f"goal: {_prompt_inline(g['project']['goal'])}")
    lines.append("facts:")
    for f in g["facts"]:
        src = f" (from {_prompt_inline(f['source_intent'])})" if f.get("source_intent") else ""
        title = f"[{_prompt_inline(f['title'])}] " if f.get("title") else ""
        kind = f"<{f['kind']}> " if f.get("kind") else ""
        data = ""
        if f.get("data"):
            pairs = " ".join(f"{k}={_prompt_inline(str(v))}" for k, v in f["data"].items())
            data = f" {{{pairs}}}"
        has_doc = " (has doc)" if f.get("doc") else ""
        lines.append(
            f"  - {f['id']}: {kind}{title}{_prompt_inline(f['description'])}{data}{src}{has_doc}"
        )
    lines.append("intents:")
    for i in g["intents"]:
        to = i["to"] or "open"
        flag = ""
        if i["requires_confirmation"] and not i["confirmed_at"]:
            flag = " [needs_confirmation]"
        title = f"[{_prompt_inline(i['title'])}] " if i.get("title") else ""
        has_doc = " (has doc)" if i.get("doc") else ""
        lines.append(
            f"  - {i['id']}: {i['from']} -> {to}{flag} | {title}"
            f"{_prompt_inline(i['description'])}{has_doc}"
        )
    hints = _visible_hints(g["hints"])
    if hints:
        lines.append("hints:")
        for h in hints:
            lines.append(
                f"  - {h['id']} ({_prompt_inline(h['creator'])}): "
                f"{_prompt_inline(h['content'])}"
            )
    lines.append(
        "note: nodes marked (has doc) carry a detailed layer — read it with "
        "`ben doc <id>` when you need the full context."
    )
    return "\n".join(lines)
