"""Docker lifecycle helpers — thin, testable wrappers over the docker CLI.

Every function returns plain data (dicts/lists) and never raises on a missing
container: the runner decides whether that is fatal. ``DockerUnavailable`` is
the only exception raised, and only when the docker binary itself is absent.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any


class DockerUnavailable(RuntimeError):
    """docker CLI is not on PATH (or the daemon is unreachable)."""


def docker_bin() -> str:
    path = shutil.which("docker")
    if not path:
        raise DockerUnavailable("docker not found on PATH")
    return path


def _run(args: list[str], timeout: float = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [docker_bin(), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


@dataclass
class ContainerState:
    name: str
    exists: bool
    running: bool = False
    status: str = ""
    image: str = ""
    ports: list[str] | None = None
    restart: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "exists": self.exists,
            "running": self.running,
            "status": self.status,
            "image": self.image,
            "ports": self.ports or [],
            "restart": self.restart,
        }


def inspect(name: str) -> ContainerState:
    """Return the container state; `exists=False` when docker has no such name."""
    if not name:
        return ContainerState(name="", exists=False)
    proc = _run([
        "inspect", name,
        "--format",
        "{{.State.Status}}|{{.State.Running}}|{{.Config.Image}}|{{json .HostConfig.PortBindings}}|{{.HostConfig.RestartPolicy.Name}}",
    ])
    if proc.returncode != 0:
        return ContainerState(name=name, exists=False)
    parts = proc.stdout.strip().split("|", 4)
    status = parts[0] if parts else ""
    running = (parts[1].strip() == "true") if len(parts) > 1 else False
    image = parts[2] if len(parts) > 2 else ""
    ports: list[str] = []
    if len(parts) > 3 and parts[3].strip() not in ("", "null"):
        try:
            bindings = json.loads(parts[3])
            for cport, binds in (bindings or {}).items():
                for b in binds or []:
                    host_ip = b.get("HostIp") or "0.0.0.0"
                    ports.append(f"{host_ip}:{b.get('HostPort')}->{cport}")
        except json.JSONDecodeError:
            ports = [parts[3]]
    restart = parts[4].strip() if len(parts) > 4 else ""
    return ContainerState(name=name, exists=True, running=running, status=status,
                          image=image, ports=ports, restart=restart)


def start(name: str, timeout: float = 120) -> tuple[bool, str]:
    proc = _run(["start", name], timeout=timeout)
    return proc.returncode == 0, (proc.stdout or proc.stderr).strip()


def create(name: str, image: str, ports: list[str] | None = None,
           restart: str = "", timeout: float = 300) -> tuple[bool, str]:
    args = ["run", "-d", "--name", name]
    for mapping in ports or []:
        args += ["-p", mapping]
    if restart:
        args += ["--restart", restart]
    args.append(image)
    proc = _run(args, timeout=timeout)
    return proc.returncode == 0, (proc.stdout or proc.stderr).strip()


def compose_up(directory: str, timeout: float = 300) -> tuple[bool, str]:
    """`docker compose up -d` in the scenario directory (falls back to v1 CLI)."""
    for cmd in (["compose", "up", "-d"], ["-compose", "up", "-d"]):
        if cmd[0] == "-compose":
            binary = shutil.which("docker-compose")
            if not binary:
                continue
            proc = subprocess.run([binary, "up", "-d"], cwd=directory,
                                  capture_output=True, text=True, timeout=timeout, check=False)
        else:
            proc = subprocess.run([docker_bin(), *cmd], cwd=directory,
                                  capture_output=True, text=True, timeout=timeout, check=False)
        if proc.returncode == 0:
            return True, (proc.stdout or "").strip()
    return False, "docker compose up failed"


def stop(name: str, timeout: float = 90) -> tuple[bool, str]:
    proc = _run(["stop", name], timeout=timeout)
    return proc.returncode == 0, (proc.stdout or proc.stderr).strip()


def remove(name: str, timeout: float = 90) -> tuple[bool, str]:
    proc = _run(["rm", "-f", name], timeout=timeout)
    return proc.returncode == 0, (proc.stdout or proc.stderr).strip()


def logs_tail(name: str, lines: int = 40) -> str:
    proc = _run(["logs", "--tail", str(lines), name])
    return (proc.stdout or "") + (proc.stderr or "")


def list_running() -> list[dict[str, str]]:
    proc = _run(["ps", "--format", "{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}"])
    if proc.returncode != 0:
        return []
    rows = []
    for line in proc.stdout.strip().splitlines():
        parts = line.split("|")
        if len(parts) >= 4:
            rows.append({"name": parts[0], "image": parts[1],
                         "status": parts[2], "ports": parts[3]})
    return rows


def container_ip(name: str) -> str:
    """First bridge IP of the container ('' when stopped or unknown).

    Published host ports are the normal way in, but a range that is reached
    from *another container* needs this address instead.
    """
    proc = _run(["inspect", name, "--format",
                 "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}"])
    if proc.returncode != 0:
        return ""
    for token in proc.stdout.split():
        if token.count(".") == 3:
            return token
    return ""


def host_port_of(mapping: str) -> int | None:
    """'8080:8080' -> 8080 (host side)."""
    host = mapping.split(":")[0] if ":" in mapping else mapping
    return int(host) if host.isdigit() else None
