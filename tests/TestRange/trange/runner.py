"""The runner: start a range, prove it answers, prove you can reach it.

Three stages, deliberately linear and each recorded, so a failure names the
layer that broke instead of a single opaque "failed":

    deploy    container / compose bring-up (and nothing else)
    health    poll the app until it answers (cold boot tolerated)
    connect   translate "it is up" into "we can talk to it, right now"

What happens after `connect` is not this tool's business: it hands over
`connect.env` and the operator's main flow takes it from there.
"""
from __future__ import annotations

import os
import platform
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import dockerops
from .netprobe import http_get, wait_until
from .profiles import Profile


@dataclass
class Step:
    name: str
    ok: bool
    detail: str
    seconds: float = 0.0
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail,
                "seconds": round(self.seconds, 2), "data": self.data}


@dataclass
class RangeRun:
    profile: Profile
    started: str
    out_dir: Path
    steps: list[Step] = field(default_factory=list)
    connection: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.steps) and all(s.ok for s in self.steps)

    def add(self, step: Step) -> Step:
        self.steps.append(step)
        return step


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _repo_root() -> Path:
    # tests/TestRange/trange/runner.py -> repo root
    return Path(__file__).resolve().parents[3]


def default_out_dir(profile: Profile) -> Path:
    """Runtime artifacts live under runs/ (project rule: one runtime root)."""
    root = Path(os.environ.get("BEN_RUNTIME_DIR") or (Path(_repo_root()) / "runs"))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return root / "testrange" / f"{profile.id}-{stamp}"


def _log_default(message: str) -> None:
    print(f"[trange] {message}", flush=True)


# --------------------------------------------------------------------------
# stage: deploy
# --------------------------------------------------------------------------
def stage_deploy(run: RangeRun, *, deploy: bool, log: Callable[[str], None]) -> Step:
    profile = run.profile
    started = time.time()
    if not deploy:
        return Step("deploy", True, "skipped (--no-deploy): assuming the range is managed elsewhere",
                    time.time() - started, {"mode": "external"})

    if profile.compose_dir:
        directory = Path(profile.compose_dir)
        if not directory.is_dir():
            return Step("deploy", False, f"compose_dir missing: {directory}", time.time() - started)
        # An existing container wins: `compose up` may rebuild images, which
        # turns a 2-second start into a 5-minute one.
        if profile.container and dockerops.inspect(profile.container).exists:
            log(f"container {profile.container} exists — starting it instead of compose up")
        else:
            ok, detail = dockerops.compose_up(str(directory))
            tail = " ".join(detail.split())[:160]
            return Step("deploy", ok, f"compose up in {directory.name}: {tail}",
                        time.time() - started, {"mode": "compose", "dir": str(directory)})

    if not profile.container:
        return Step("deploy", True, "no container declared — external range",
                    time.time() - started, {"mode": "external"})

    state = dockerops.inspect(profile.container)
    log(f"container {profile.container}: exists={state.exists} running={state.running}")

    if not state.exists:
        if not profile.image:
            return Step("deploy", False,
                        f"container {profile.container} absent and no image to create it",
                        time.time() - started)
        if not profile.deploy.get("create_if_missing", True):
            return Step("deploy", False, f"container {profile.container} absent "
                                         f"(create_if_missing=false)", time.time() - started)
        ok, detail = dockerops.create(profile.container, profile.image, profile.ports,
                                      str(profile.deploy.get("restart") or ""))
        return Step("deploy", ok,
                    f"docker run {profile.image} as {profile.container}: "
                    f"{' '.join(detail.split())[:120]}",
                    time.time() - started, {"mode": "create", "ports": profile.ports})

    if state.running:
        return Step("deploy", True, f"already running ({state.status})", time.time() - started,
                    {"mode": "noop", "ports": state.ports or []})

    ok, detail = dockerops.start(profile.container)
    after = dockerops.inspect(profile.container)
    return Step("deploy", ok and after.running,
                f"started: status={after.status} ports={after.ports}",
                time.time() - started, {"mode": "start", "ports": after.ports or []})


# --------------------------------------------------------------------------
# stage: health (cold-boot tolerance)
# --------------------------------------------------------------------------
def stage_health(run: RangeRun, log: Callable[[str], None]) -> Step:
    profile = run.profile
    started = time.time()
    url = profile.health_url()
    # `or 200` would swallow the documented sentinel 0 = "any status"
    raw_status = profile.health.get("expect_status")
    expect_status = 200 if raw_status is None else int(raw_status)
    expect_body = profile.health.get("expect_body")

    def check():
        res = http_get(url, timeout=5)
        if not res.ok:
            return False, f"{url} -> {res.error}"
        if expect_status and res.status != expect_status:
            return False, f"{url} -> HTTP {res.status} (want {expect_status})"
        if expect_body:
            import re
            if not re.search(str(expect_body), res.body):
                return False, f"{url} -> {res.status} but body lacks {expect_body!r}"
        return True, f"{url} -> HTTP {res.status} in {res.elapsed_ms}ms"

    ok, detail, waited = wait_until(check, timeout=profile.boot_timeout,
                                    interval=profile.health_interval, label=url)
    log(f"health after {waited:.1f}s: {detail}")
    return Step("health", ok, f"{detail} (waited {waited:.1f}s, budget {profile.boot_timeout:.0f}s)",
                time.time() - started, {"url": url, "waited": round(waited, 1)})


# --------------------------------------------------------------------------
# stage: connect (the self-check that "up" alone does not give you)
# --------------------------------------------------------------------------
def stage_connect(run: RangeRun, log: Callable[[str], None], *,
                  attempts: int = 3) -> Step:
    from .connect import check as check_connection, write_env

    started = time.time()
    conn = check_connection(run.profile, attempts=attempts, log=log)
    run.connection = conn.as_dict()
    env_path = write_env(conn, run.out_dir)
    detail = conn.summary
    if conn.notes:
        detail += " | notes: " + "; ".join(conn.notes)
    return Step("connect", conn.ok, detail, time.time() - started,
                {"env_file": str(env_path), "container_ip": conn.container_ip,
                 "container_port": conn.container_port, "published": conn.published})


# --------------------------------------------------------------------------
# orchestration
# --------------------------------------------------------------------------
def run_range(profile: Profile, *, deploy: bool = True,
              out_dir: str | Path | None = None, connect_check: bool = True,
              log: Callable[[str], None] | None = None) -> RangeRun:
    log = log or _log_default
    out = Path(out_dir) if out_dir else default_out_dir(profile)
    out.mkdir(parents=True, exist_ok=True)
    run = RangeRun(profile=profile, started=_now(), out_dir=out)

    run.add(stage_deploy(run, deploy=deploy, log=log))
    if not run.ok:
        return run

    run.add(stage_health(run, log))
    if not run.ok:
        return run

    if connect_check:
        run.add(stage_connect(run, log))

    return run


def environment_fingerprint() -> dict[str, str]:
    docker_version = ""
    try:
        docker_version = dockerops._run(["version", "--format", "{{.Server.Version}}"]).stdout.strip()
    except Exception:
        docker_version = "unavailable"
    return {
        "host": platform.node(),
        "os": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "docker": docker_version or "unavailable",
        "ben": _find_ben(),
    }


def _find_ben() -> str:
    found = shutil.which("ben")
    if found:
        return found
    # scripts/install.sh links it into ~/.local/bin, which is not always on PATH
    local = Path.home() / ".local" / "bin" / "ben"
    return str(local) if local.exists() else "not installed"
