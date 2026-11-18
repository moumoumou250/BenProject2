"""Connection self-check — "up" is not the same as "connected".

A container can be ``Up`` while the port is bound to a different interface, the
process inside is still booting, or the app answers 500 on the path you picked.
This module answers one question from the agents' point of view:

    can something on this host actually talk to the range, right now?

`ok` is deliberately loose about *content*: any HTTP response proves a live
socket and a live server. Whether the response means "exploitable" is the main
flow's business, not the connection check's.
"""
from __future__ import annotations

import json
import socket
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from . import dockerops
from .netprobe import http_get, tcp_open
from .profiles import Profile


@dataclass
class Connection:
    ok: bool
    url: str = ""
    host: str = ""
    ip: str = ""
    port: int = 0
    tcp_open: bool = False
    http_status: int = 0
    elapsed_ms: int = 0
    body_hint: str = ""
    container: str = ""
    container_ip: str = ""
    container_port: int = 0
    published: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if not self.ok:
            reasons = "; ".join(self.notes) or "no response"
            return f"NOT CONNECTED to {self.url or '?'} — {reasons}"
        head = (f"CONNECTED {self.url} — tcp open, HTTP {self.http_status} "
                f"in {self.elapsed_ms}ms")
        return head + (f" | {self.body_hint}" if self.body_hint else "")

    def env_lines(self) -> list[str]:
        """Shell-ready exports, so a follow-up shell/agent needs no re-derivation."""
        lines = [
            f"export TARGET_URL={_q(self.url)}",
            f"export TARGET_HOST={_q(self.host)}",
            f"export TARGET_PORT={self.port}",
        ]
        if self.container:
            lines.append(f"export TARGET_CONTAINER={_q(self.container)}")
        if self.container_ip:
            lines.append(f"export TARGET_CONTAINER_IP={_q(self.container_ip)}")
        return lines

    def as_dict(self) -> dict:
        return {
            "ok": self.ok, "summary": self.summary,
            "url": self.url, "host": self.host, "ip": self.ip,
            "port": self.port, "tcp_open": self.tcp_open,
            "http_status": self.http_status, "elapsed_ms": self.elapsed_ms,
            "container": self.container, "container_ip": self.container_ip,
            "container_port": self.container_port,
            "published": self.published, "notes": self.notes,
        }


def _q(value: str) -> str:
    return "'" + str(value).replace("'", "'\\''") + "'"


def _hint(body: str) -> str:
    """A short, human-useful gist of the response — never a wall of markup.

    Priority: a ``<title>`` (the server's own name), then the top-level keys of
    a JSON answer ("json keys: _links" beats a truncated blob), then flattened
    text. This line is what an operator reads to confirm *which* app answered.
    """
    source = body or ""

    title = re.search(r"(?is)<title[^>]*>(.*?)</title>", source)
    if title:
        text = re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", title.group(1))).strip()
        if text:
            return text[:70]

    head = source.lstrip()
    if head.startswith("{"):
        try:
            data = json.loads(source)
        except ValueError:
            pass
        else:
            if isinstance(data, dict) and data:
                return "json keys: " + ", ".join(list(data)[:6])

    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", source)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:70]


def _resolve(host: str) -> str:
    try:
        return socket.gethostbyname(host)
    except OSError:
        return ""


def check(profile: Profile, *, attempts: int = 3, timeout: float = 8.0,
          log=lambda _m: None) -> Connection:
    """One TCP attempt plus one HTTP request, retried while the socket is cold."""
    parsed = urlparse(profile.url or profile.health_url())
    host = parsed.hostname or profile.host
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    url = profile.url or profile.health_url()

    conn = Connection(ok=False, url=url, host=host, ip=_resolve(host), port=port,
                      container=profile.container)

    if profile.container:
        state = dockerops.inspect(profile.container)
        conn.published = state.ports or []
        if state.exists and not state.running:
            conn.notes.append(f"container {profile.container} is {state.status or 'stopped'}")
        conn.container_ip = dockerops.container_ip(profile.container) if state.running else ""

    opened = False
    for index in range(max(1, attempts)):
        opened, _ms = tcp_open(host, port, timeout=min(timeout, 4))
        if opened:
            break
        if index + 1 < attempts:
            time.sleep(0.6 * (index + 1))
    conn.tcp_open = opened
    if not opened:
        conn.notes.append(f"tcp {host}:{port} refused/timeout")

    started = time.time()
    # Ask for the health path, not just "/": the gist in the summary should
    # describe the range, not whatever the root route happens to proxy.
    probe_url = profile.health_url() or url
    res = http_get(probe_url, timeout=timeout)
    conn.elapsed_ms = int((time.time() - started) * 1000)
    if res.ok:
        conn.http_status = res.status
        conn.body_hint = _hint(res.body)
    else:
        conn.notes.append(f"http {probe_url} -> {res.error}")

    # a published port that does not include the target port explains most
    # "container is up but nothing answers" cases, so surface it explicitly
    if conn.published:
        published_ports = set()
        for entry in conn.published:
            host_side, _, container_side = entry.partition("->")
            left = host_side
            if ":" in left:
                published_ports.add(left.rsplit(":", 1)[1])
            # the container-internal port differs from the published one whenever
            # the mapping was relocated, so record it for container-to-container use
            if container_side.split("/")[0].isdigit() and \
                    left.rsplit(":", 1)[-1] == str(port):
                conn.container_port = int(container_side.split("/")[0])
        if str(port) not in published_ports:
            conn.notes.append(f"port {port} not published (published: "
                              f"{', '.join(sorted(published_ports)) or 'none'})")

    conn.ok = bool(opened and conn.http_status)
    if conn.ok and conn.notes:
        log("connected with warnings: " + "; ".join(conn.notes))
    return conn


def write_env(conn: Connection, out_dir: str | Path) -> Path:
    """Persist the connection as a sourceable file next to the report."""
    path = Path(out_dir) / "connect.env"
    path.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "# generated by rangectl — `source` this to point tools at the range",
        f"# {conn.summary}",
    ]
    path.write_text("\n".join(header + conn.env_lines()) + "\n", encoding="utf-8")
    return path
