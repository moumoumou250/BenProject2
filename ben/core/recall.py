"""Token-based recall scoring over graph nodes."""
from __future__ import annotations

import difflib

from ben.consts import GOAL_ID
from ben.core.store import Store
from ben.core.text import tokenize

# Historical name kept for the package-level re-export in ben/__init__.py.
_recall_tokenize = tokenize


def _recall_score(query: str, node: dict) -> float:
    """Score a node against a free-text query. Combines:
      - token overlap on title (weighted x2) and description
      - difflib ratio against the joined haystack
    Returns 0.0 if nothing useful matches."""
    title = (node.get("title") or "").lower()
    desc = (node.get("description") or "").lower()
    haystack = f"{title} {title} {desc}".strip()  # title weighted x2
    if not haystack:
        return 0.0
    q_tokens = set(_recall_tokenize(query))
    if not q_tokens:
        return 0.0
    h_tokens = set(_recall_tokenize(haystack))
    if not h_tokens:
        return 0.0
    overlap = len(q_tokens & h_tokens)
    if overlap == 0:
        # cheap difflib fallback for fuzzy matches (typo, partial English word)
        ratio = difflib.SequenceMatcher(None, query.lower(), haystack).ratio()
        return ratio if ratio >= 0.45 else 0.0
    overlap_score = overlap / max(1, len(q_tokens))
    # add a small ratio bonus so longer aligned chunks edge out shorter ones
    ratio_bonus = 0.2 * difflib.SequenceMatcher(None, query.lower(), haystack).ratio()
    return overlap_score + ratio_bonus


def recall(store: Store, query: str, limit: int = 5,
           kinds: tuple[str, ...] = ("fact", "intent")) -> list[dict]:
    """Return top-N nodes by similarity to `query`. Each returned dict has:
        id, kind, title, description, has_doc, score
    Ordered by score desc, then by id (stable).
    """
    if not query or not query.strip():
        return []
    candidates: list[dict] = []
    if "fact" in kinds:
        for f in store.list_facts():
            if f.get("id") == GOAL_ID:
                continue  # skip the terminal goal node
            s = _recall_score(query, f)
            if s > 0:
                candidates.append({
                    "id": f["id"],
                    "kind": "fact",
                    "title": f.get("title"),
                    "description": f.get("description", ""),
                    "has_doc": bool(f.get("doc")),
                    "score": s,
                })
    if "intent" in kinds:
        for i in store.list_intents():
            s = _recall_score(query, i)
            if s > 0:
                candidates.append({
                    "id": i["id"],
                    "kind": "intent",
                    "title": i.get("title"),
                    "description": i.get("description", ""),
                    "has_doc": bool(i.get("doc")),
                    "score": s,
                })
    candidates.sort(key=lambda c: (-c["score"], c["id"]))
    return candidates[:limit]
