"""Text normalisation shared by recall (graph search) and kb (knowledge base).

Both used to carry their own copy of this function with their own copy of the
token regex — same algorithm, two definitions, drifting independently. One
definition lives here now; anything that needs tokens imports it.

CJK runs are split into single characters on purpose: `空指针定位` becomes four
content-bearing tokens, so a query for `指针` still matches.
"""
from __future__ import annotations

import re

TOKEN_RE = re.compile(r"[\w一-鿿]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Lowercase, then split into word / CJK-character tokens."""
    if not text:
        return []
    out: list[str] = []
    for tok in TOKEN_RE.findall(text.lower()):
        if any("一" <= ch <= "鿿" for ch in tok):
            out.extend(tok)
        else:
            out.append(tok)
    return [t for t in out if t]
