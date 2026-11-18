"""Recent facts/intents block for hooks and prompts."""
from __future__ import annotations

from ben.consts import GOAL_ID
from ben.core.graph import is_open
from ben.core.io import _scrub_inline
from ben.core.store import Store


def render_history_block(store: Store, *, max_facts: int = 8,
                         max_intents: int = 4) -> str:
    """Compact history snapshot for hook injection: recent confirmed facts
    + recently-done intents, title + one-line description only. The model
    eyeballs this to decide whether it has seen the current request before."""
    facts = [f for f in store.list_facts() if f.get("id") != GOAL_ID]
    # facts are immutable; show most recent first
    facts.sort(key=lambda f: f.get("created_at", ""), reverse=True)
    done = [i for i in store.list_intents() if not is_open(i)]
    done.sort(key=lambda i: i.get("concluded_at") or "", reverse=True)

    lines: list[str] = []
    if facts:
        lines.append("history facts (most recent first):")
        for f in facts[:max_facts]:
            title = f"[{_scrub_inline(f['title'])}] " if f.get("title") else ""
            doc = " 📄" if f.get("doc") else ""
            desc = _scrub_inline(f.get("description") or "")[:90]
            lines.append(f"  {f['id']}: {title}{desc}{doc}")
    if done:
        if lines:
            lines.append("")
        lines.append("recently-done intents:")
        for i in done[:max_intents]:
            title = f"[{_scrub_inline(i['title'])}] " if i.get("title") else ""
            doc = " 📄" if i.get("doc") else ""
            desc = _scrub_inline(i.get("description") or "")[:90]
            lines.append(f"  {i['id']}: {title}{desc}{doc}")
    if not lines:
        return ""
    return "\n".join(lines)

