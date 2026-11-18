"""Host-port bookkeeping — make "start it now" survive a busy port.

A range that cannot bind its declared port is the single most common reason a
quick start fails, and the failure (``ports are not available`` from docker or a
compose error) does not say which port or who holds it. These helpers answer
that: find a free port, and move a profile onto it *without* editing the file.
"""
from __future__ import annotations

import copy
import re
from dataclasses import replace

from .netprobe import port_in_use
from .profiles import Profile


class PortUnavailable(RuntimeError):
    """No free port could be found in the scanned window."""


def is_free(port: int, host: str = "0.0.0.0") -> bool:
    return not port_in_use(port, host)


def host_port(mapping: str) -> int | None:
    """'8080:80' -> 8080 ; '8080' -> 8080 ; '127.0.0.1:8080:80' -> 8080."""
    parts = str(mapping).split("/", 1)[0].split(":")
    if len(parts) == 1:
        return int(parts[0]) if parts[0].isdigit() else None
    return int(parts[-2]) if parts[-2].isdigit() else None


def pick_free(preferred: int, *, span: int = 200, host: str = "0.0.0.0") -> int:
    """First free port at or after `preferred` (bounded so a typo cannot spin)."""
    for candidate in range(max(1, preferred), min(65535, preferred + span) + 1):
        if is_free(candidate, host):
            return candidate
    raise PortUnavailable(f"no free port in {preferred}..{preferred + span}")


def _swap_port(text: str, old: int, new: int) -> str:
    # the negative lookahead keeps ':80' from matching inside ':8080'
    return re.sub(rf":{old}(?!\d)", f":{new}", str(text), count=1)


def relocate(profile: Profile, old: int, new: int) -> Profile:
    """Copy `profile` with host port `old` moved to `new` (ports + target + tcp).

    The on-disk profile is never touched: a quick start should not silently
    rewrite a file a human curated.
    """
    clone = copy.deepcopy(profile)
    mappings: list[str] = []
    for mapping in profile.ports:
        if host_port(mapping) == old:
            container_side = str(mapping).split("/", 1)[0].split(":")[-1]
            mappings.append(f"{new}:{container_side}")
        else:
            mappings.append(str(mapping))
    clone.deploy["ports"] = mappings
    clone.target["url"] = _swap_port(clone.target.get("url") or "", old, new)
    tcp = clone.target.get("tcp") or []
    clone.target["tcp"] = [_swap_port(item, old, new) for item in tcp]
    if clone.health.get("path") and str(clone.health["path"]).startswith("http"):
        clone.health["path"] = _swap_port(clone.health["path"], old, new)
    return clone


def conflicts(profile: Profile, *, ours: set[int] | None = None) -> list[int]:
    """Host ports declared by the profile that are taken by someone else."""
    ours = ours or set()
    busy = []
    for mapping in profile.ports:
        port = host_port(mapping)
        if port is None or port in ours:
            continue
        if port_in_use(port):
            busy.append(port)
    return busy
