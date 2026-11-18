"""Human-readable status rendering."""
from __future__ import annotations

from ben.core.graph import build_graph_view, frontier
from ben.core.io import _scrub_inline
from ben.core.store import Store
from ben.core.text import TOKEN_RE


def render_status(store: Store) -> str:
    g = build_graph_view(store)
    p = g["project"]
    lines = []
    lines.append(
        f"project: {_scrub_inline(p.get('id') or '')}  "
        f"status: {_scrub_inline(p['status'])}"
    )
    lines.append(f"origin: {_scrub_inline(p['origin'])}")
    lines.append(f"goal:   {_scrub_inline(p['goal'])}")
    lines.append(
        f"counts: {len(g['facts'])} facts, {len(g['open_intents'])} open / "
        f"{len(g['done_intents'])} done intents, {len(g['hints'])} hints"
    )
    typed: dict[str, int] = {}
    for f in g["facts"]:
        k = f.get("kind")
        if k:
            typed[k] = typed.get(k, 0) + 1
    if typed:
        summary = ", ".join(f"{n} {k}s" if k != "flag" else f"{n} flag(s)" for k, n in typed.items())
        lines.append(f"kinds:  {summary}")
    flags = [f for f in g["facts"] if f.get("kind") == "flag"]
    for f in flags:
        d = f.get("data") or {}
        ch = f" challenge={d['challenge']}" if d.get("challenge") else ""
        lines.append(
            f"flag:   {f['id']} status={d.get('status', 'recorded')}{ch} value={_scrub_inline(str(d.get('value', '')))[:48]}"
        )
    fr = frontier(store)
    pool = []
    if fr:
        lines.append("")
        lines.append("frontier (ready to work):")
        for i in fr:
            flag = ""
            if i["requires_confirmation"] and not i["confirmed_at"]:
                flag = "  [needs confirmation]"
            elif i["status"] == "claimed":
                flag = f"  [claimed by {i['worker']}]"
            lines.append(f"  {i['id']}  from {i['from']}  {_scrub_inline(i['description'])[:80]}{flag}")
    elif g["open_intents"]:
        lines.append("")
        lines.append("(open intents exist but none ready — check confirmations)")
    else:
        lines.append("")
        lines.append("(no open intents — dispatch a reason step or complete)")
    if g["hints"]:
        lines.append("")
        lines.append(f"hints: {len(g['hints'])} (use `ben hint list`)")
    return "\n".join(lines)


_RECALL_TOKEN_RE = TOKEN_RE   # historical name, re-exported by ben/__init__.py
