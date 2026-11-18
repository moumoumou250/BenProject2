"""Profile loading — one TOML/JSON file describes one range.

A profile says only what is needed to **start** a range and **check the link**:

    id            = "spring-cve-2022-22947"        # unique, used by the CLI
    title         = "Spring Cloud Gateway"          # human label
    cve           = "CVE-2022-22947"                # optional metadata

    [deploy]                                        # omit for external ranges
    container     = "cve-2022-22947-spring-1"      # container to start
    image         = "vulhub/spring-cloud-gateway:3.1.0"   # created when absent
    ports         = ["8080:8080", "5005:5005"]     # host:container
    compose_dir   = "/path/to/scenario"            # preferred if present
    restart       = "unless-stopped"
    create_if_missing = true                       # docker run when absent

    [target]
    url           = "http://127.0.0.1:8080"        # what agents attack
    host          = "127.0.0.1"                    # optional, derived from url

    [health]                                        # how "started" is proven
    path          = "/actuator"
    expect_status = 200                            # 0 = any HTTP status
    expect_body   = '"_links"'                     # regex, optional
    timeout       = 120
    interval      = 3
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - 3.10 fallback, JSON only
    tomllib = None  # type: ignore[assignment]


class ProfileError(Exception):
    """Raised for an unreadable or inconsistent profile."""


@dataclass
class Profile:
    id: str
    path: Path
    title: str = ""
    cve: str = ""
    tags: list[str] = field(default_factory=list)
    deploy: dict[str, Any] = field(default_factory=dict)
    target: dict[str, Any] = field(default_factory=dict)
    health: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    # -- derived helpers ---------------------------------------------------
    @property
    def url(self) -> str:
        return str(self.target.get("url") or "").rstrip("/")

    @property
    def host(self) -> str:
        return str(self.target.get("host") or urlparse(self.url).hostname or "127.0.0.1")

    @property
    def port(self) -> int:
        parsed = urlparse(self.url)
        return int(parsed.port or (443 if parsed.scheme == "https" else 80))

    @property
    def container(self) -> str:
        return str(self.deploy.get("container") or "")

    @property
    def image(self) -> str:
        return str(self.deploy.get("image") or "")

    @property
    def compose_dir(self) -> str:
        return str(self.deploy.get("compose_dir") or "")

    @property
    def ports(self) -> list[str]:
        return [str(p) for p in (self.deploy.get("ports") or [])]

    @property
    def boot_timeout(self) -> float:
        return float(self.health.get("timeout") or self.deploy.get("boot_timeout") or 120)

    @property
    def health_interval(self) -> float:
        return float(self.health.get("interval") or 3)

    def health_url(self) -> str:
        path = str(self.health.get("path") or "/")
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.url}/{path.lstrip('/')}"

    def handoff_goal(self) -> str:
        """One-line goal for the main flow; the tool never runs it itself."""
        label = self.cve or self.title or self.id
        return f"assess and exploit {label} at {self.url} (authorized local lab)"


def _parse_text(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix in (".toml",):
        if tomllib is None:  # pragma: no cover
            raise ProfileError(f"{path.name}: TOML needs Python 3.11+ (got older); use .json")
        with path.open("rb") as fh:
            return tomllib.load(fh)
    if suffix in (".json",):
        return json.loads(path.read_text(encoding="utf-8"))
    raise ProfileError(f"{path.name}: unsupported profile type {suffix} (use .toml or .json)")


def load_profile(path: str | Path) -> Profile:
    path = Path(path)
    if not path.is_file():
        raise ProfileError(f"profile not found: {path}")
    try:
        data = _parse_text(path)
    except (json.JSONDecodeError, OSError) as exc:
        raise ProfileError(f"cannot read {path.name}: {exc}") from exc

    rid = str(data.get("id") or path.stem)
    target = dict(data.get("target") or {})
    if not target.get("url"):
        raise ProfileError(f"{path.name}: [target].url is required")
    if not str(target["url"]).startswith(("http://", "https://")):
        raise ProfileError(f"{path.name}: [target].url must start with http:// or https://")

    return Profile(
        id=rid,
        path=path,
        title=str(data.get("title") or rid),
        cve=str(data.get("cve") or ""),
        tags=[str(t) for t in (data.get("tags") or [])],
        deploy=dict(data.get("deploy") or {}),
        target=target,
        health=dict(data.get("health") or {}),
        raw=data,
    )


def discover_profiles(directory: str | Path) -> dict[str, Profile]:
    """Load every *.toml / *.json profile in a directory, keyed by id."""
    directory = Path(directory)
    found: dict[str, Profile] = {}
    if not directory.is_dir():
        return found
    for path in sorted(directory.iterdir()):
        if path.name.startswith("_") or path.suffix.lower() not in (".toml", ".json"):
            continue
        prof = load_profile(path)
        found[prof.id] = prof
    return found
