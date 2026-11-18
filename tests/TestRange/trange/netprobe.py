"""Network probes: is the range reachable *from the place the agents run*?

The harness deliberately takes the host's point of view (ben's fleet runs as
host processes), but also records the published ports so a bare `127.0.0.1`
target can be flagged when the container only listens on another interface.
"""
from __future__ import annotations

import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class HttpResult:
    ok: bool
    status: int = 0
    body: str = ""
    elapsed_ms: int = 0
    error: str = ""

    def brief(self, limit: int = 120) -> str:
        if not self.ok:
            return f"FAIL {self.error}"
        text = " ".join(self.body.split())[:limit]
        return f"HTTP {self.status} in {self.elapsed_ms}ms: {text}"


def http_get(url: str, timeout: float = 8, headers: dict[str, str] | None = None) -> HttpResult:
    started = time.time()
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "TestRange/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(4096).decode("utf-8", "replace")
            return HttpResult(True, resp.status, body, int((time.time() - started) * 1000))
    except urllib.error.HTTPError as exc:
        body = exc.read(2048).decode("utf-8", "replace") if exc.fp else ""
        return HttpResult(True, exc.code, body, int((time.time() - started) * 1000))
    except Exception as exc:  # URLError, timeout, connection refused ...
        return HttpResult(False, 0, "", int((time.time() - started) * 1000), str(exc))


def http_request(method: str, url: str, *, body: bytes | None = None,
                 headers: dict[str, str] | None = None,
                 timeout: float = 10) -> HttpResult:
    """Any method — needed by PUT-based and POST-based verifiers."""
    started = time.time()
    req = urllib.request.Request(url, data=body, method=method.upper(),
                                 headers=headers or {"User-Agent": "TestRange/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read(4096).decode("utf-8", "replace")
            return HttpResult(True, resp.status, text, int((time.time() - started) * 1000))
    except urllib.error.HTTPError as exc:
        text = exc.read(2048).decode("utf-8", "replace") if exc.fp else ""
        return HttpResult(True, exc.code, text, int((time.time() - started) * 1000))
    except Exception as exc:
        return HttpResult(False, 0, "", int((time.time() - started) * 1000), str(exc))


def tcp_open(host: str, port: int, timeout: float = 3) -> tuple[bool, int]:
    started = time.time()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        try:
            code = sock.connect_ex((host, port))
        except OSError as exc:
            return False, int((time.time() - started) * 1000)
        return code == 0, int((time.time() - started) * 1000)


def port_in_use(port: int, host: str = "0.0.0.0") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return False
        except OSError:
            return True


def wait_until(check, timeout: float, interval: float = 2.0, label: str = "healthy"):
    """Poll a predicate returning (ok, detail).

    Returns (ok, detail, waited_seconds). Exponential backoff capped at
    `interval`, so a fast-booting range is not penalised and a cold one still
    gets polled at a steady rate.
    """
    started = time.time()
    delay = min(1.0, interval)
    last = ""
    while time.time() - started < timeout:
        ok, detail = check()
        last = detail
        if ok:
            return True, detail, time.time() - started
        time.sleep(delay)
        delay = min(delay * 1.5, interval)
    return False, last, time.time() - started
