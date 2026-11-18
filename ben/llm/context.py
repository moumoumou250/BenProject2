"""Rule-based context compaction for long SDK tool loops."""
from __future__ import annotations

from ben import config


def _content_len(msg: dict) -> int:
    content = msg.get("content")
    if isinstance(content, str):
        return len(content)
    if content is None:
        return 0
    return len(str(content))


def messages_chars(messages: list[dict]) -> int:
    return sum(_content_len(m) for m in messages)


def compact_if_needed(messages: list[dict]) -> list[dict]:
    """Keep system + first user + last 6 rounds; stub middle tool bodies."""
    limit = config.get_int("BEN_CONTEXT_CHARS")
    if messages_chars(messages) <= limit:
        return messages
    if len(messages) <= 8:
        return messages

    # Find system + first user
    head: list[dict] = []
    rest_start = 0
    if messages and messages[0].get("role") == "system":
        head.append(messages[0])
        rest_start = 1
    if rest_start < len(messages) and messages[rest_start].get("role") == "user":
        head.append(messages[rest_start])
        rest_start += 1

    # Keep last ~6 turns (assistant+tool pairs ≈ 12 messages)
    keep_tail = 12
    middle = messages[rest_start: max(rest_start, len(messages) - keep_tail)]
    tail = messages[max(rest_start, len(messages) - keep_tail):]

    compacted_middle: list[dict] = []
    for m in middle:
        if m.get("role") == "tool" and not m.get("_compacted"):
            n = _content_len(m)
            compacted_middle.append({
                **m,
                "content": f"[已省略 {n} 字符，全文见 logs/tool-*.log]",
                "_compacted": True,
            })
        else:
            compacted_middle.append(m)
    return head + compacted_middle + tail
