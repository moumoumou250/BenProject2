"""ben probe — confirm KB validation signals against a TestRange profile.

Only profile ids are accepted (no bare URLs). Evidence lands under
``runs/probe/<profile-id>/<ts>/``. Does not write the KB.
"""
from __future__ import annotations

import ipaddress
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ben.core import paths
from ben.kb import KnowledgeBase
from ben.kb import match as kbmatch

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]


@dataclass
class ProbeProfile:
    id: str
    path: Path
    url: str
    host: str
    authorized: bool
    vulns: list[str]
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class HttpObs:
    method: str
    url: str
    status: int
    body: str
    ok_transport: bool
    error: str = ""
    elapsed_ms: int = 0


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_profiles_dir() -> Path:
    return _repo_root() / "tests" / "TestRange" / "profiles"


def _load_toml(path: Path) -> dict[str, Any]:
    if tomllib is None:
        raise RuntimeError("tomllib required (Python 3.11+) to load profiles")
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"profile root must be object: {path}")
    return data


def discover_profiles(directory: Path) -> dict[str, ProbeProfile]:
    out: dict[str, ProbeProfile] = {}
    if not directory.is_dir():
        return out
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() not in (".toml", ".json") or path.name.startswith("_"):
            continue
        if path.suffix.lower() == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            data = _load_toml(path)
        rid = str(data.get("id") or path.stem)
        target = dict(data.get("target") or {})
        url = str(target.get("url") or "").rstrip("/")
        if not url.startswith(("http://", "https://")):
            continue
        host = str(target.get("host") or urlparse(url).hostname or "")
        vulns = [str(v) for v in (data.get("vulns") or []) if v]
        out[rid] = ProbeProfile(
            id=rid,
            path=path,
            url=url,
            host=host,
            authorized=bool(data.get("authorized")),
            vulns=vulns,
            raw=data,
        )
    return out


def host_allowed(host: str, *, authorized: bool) -> bool:
    if not host:
        return False
    if authorized:
        return True
    if host in ("localhost", "127.0.0.1", "::1"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(ip.is_private or ip.is_loopback)


def _http(method: str, url: str, *, body: bytes | None = None,
          timeout: float = 10) -> HttpObs:
    """One-shot request with Connection: close (avoids keep-alive quirks on Tomcat)."""
    started = time.time()
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    headers = {
        "User-Agent": "ben-probe/1.0",
        "Connection": "close",
    }
    data = body
    if data is not None:
        # Match curl -d defaults; some Tomcat lab builds serve PUT bodies
        # written as octet-stream only after a delay (or not via http.client).
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        headers["Content-Length"] = str(len(data))
    try:
        import http.client
        conn_cls = (
            http.client.HTTPSConnection
            if parsed.scheme == "https"
            else http.client.HTTPConnection
        )
        conn = conn_cls(host, port, timeout=timeout)
        try:
            conn.request(method.upper(), path, body=data, headers=headers)
            resp = conn.getresponse()
            raw = resp.read(8192)
            text = raw.decode("utf-8", "replace")
            return HttpObs(
                method=method.upper(), url=url, status=int(resp.status),
                body=text, ok_transport=True,
                elapsed_ms=int((time.time() - started) * 1000),
            )
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 — surface as CONNECTION_LOST
        return HttpObs(
            method=method.upper(), url=url, status=0, body="",
            ok_transport=False, error=str(exc),
            elapsed_ms=int((time.time() - started) * 1000),
        )


def _write_evidence(outdir: Path, observations: list[HttpObs], verdict: dict) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    for i, obs in enumerate(observations, 1):
        (outdir / f"{i:02d}-{obs.method.lower()}.json").write_text(
            json.dumps({
                "method": obs.method,
                "url": obs.url,
                "status": obs.status,
                "ok_transport": obs.ok_transport,
                "error": obs.error,
                "elapsed_ms": obs.elapsed_ms,
                "body": obs.body[:4000],
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    (outdir / "verdict.json").write_text(
        json.dumps(verdict, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _probe_file_write(
    base_url: str,
    validation: dict[str, Any],
    *,
    timeout: float,
    max_requests: int,
    allow_destructive: bool,
) -> tuple[str, int, str, list[HttpObs]]:
    """Return (label, exit_code, detail, observations)."""
    if not allow_destructive:
        return (
            "NOT_CONFIRMED",
            1,
            "file-write requires --allow-destructive (PUT writes a file)",
            [],
        )

    stamp = int(time.time())
    name = f"ben-probe-{stamp}"
    # Body token is NOT the filename — Tomcat 404 pages echo the URI and
    # would otherwise false-positive a marker-in-body check.
    body_token = f"PROBEOK{stamp}X"
    put_url = f"{base_url.rstrip('/')}/{name}.jsp/"
    get_url = f"{base_url.rstrip('/')}/{name}.jsp"
    # Baseline MUST NOT touch get_url before PUT — Tomcat caches the 404 and
    # subsequent GETs keep missing even after the file appears on disk.
    baseline_url = f"{base_url.rstrip('/')}/{name}-miss.jsp"
    payload = f"{body_token}\n".encode()
    signal = str(validation.get("signal") or "")
    observations: list[HttpObs] = []

    if max_requests <= 0:
        return "UNVERIFIED", 3, "BUDGET", observations

    if max_requests >= 1:
        base = _http("GET", baseline_url, timeout=timeout)
        observations.append(base)
        if not base.ok_transport:
            retry = _http("GET", baseline_url, timeout=timeout)
            observations.append(retry)
            if not retry.ok_transport:
                return "UNVERIFIED", 3, "CONNECTION_LOST", observations

    if len(observations) >= max_requests:
        return "UNVERIFIED", 3, "BUDGET", observations

    put = _http("PUT", put_url, body=payload, timeout=timeout)
    observations.append(put)
    if not put.ok_transport:
        put2 = _http("PUT", put_url, body=payload, timeout=timeout)
        observations.append(put2)
        put = put2
        if not put.ok_transport:
            return "UNVERIFIED", 3, "CONNECTION_LOST", observations

    body_l = put.body.lower()
    if "challenge" in body_l:
        return "NOT_CONFIRMED", 1, "reject: WAF/challenge page", observations

    if put.status == 200:
        return "NOT_CONFIRMED", 1, "reject: PUT status 200 alone is not evidence", observations
    if put.status not in (201, 204):
        return "NOT_CONFIRMED", 1, f"PAYLOAD_MISMATCH: PUT status={put.status}", observations

    if len(observations) >= max_requests:
        return "UNVERIFIED", 3, "BUDGET", observations

    got = None
    for attempt in range(6):
        if len(observations) >= max_requests:
            return "UNVERIFIED", 3, "BUDGET", observations
        cand = _http("GET", get_url, timeout=timeout)
        observations.append(cand)
        if not cand.ok_transport:
            time.sleep(0.3)
            continue
        got = cand
        if cand.status in range(200, 300) and body_token in cand.body:
            break
        time.sleep(0.3 * (attempt + 1))
    if got is None or not got.ok_transport:
        return "UNVERIFIED", 3, "CONNECTION_LOST", observations
    if got.status not in range(200, 300):
        return (
            "NOT_CONFIRMED",
            1,
            f"PAYLOAD_MISMATCH: GET status={got.status} (need 2xx + body token)",
            observations,
        )
    if body_token not in got.body:
        return (
            "NOT_CONFIRMED",
            1,
            f"PAYLOAD_MISMATCH: GET status={got.status} missing body token",
            observations,
        )

    detail = (
        f"CONFIRMED by validation.signal: {signal!r}; "
        f"PUT {put.status} @ {put_url}; GET {got.status} body token ok"
    )
    return "CONFIRMED", 0, detail, observations


def cmd_probe(args) -> int:
    profile_id = (args.profile_id or "").strip()
    vuln = (args.vuln or "").strip()
    if not profile_id or not vuln:
        sys.stderr.write("ben: usage: ben probe <profile-id> <vuln>\n")
        return 2

    profiles_dir = Path(args.profiles) if args.profiles else default_profiles_dir()
    if not profiles_dir.is_dir():
        sys.stderr.write(
            f"ben: profiles dir not found: {profiles_dir}\n"
            "ben: pass --profiles DIR (default: tests/TestRange/profiles)\n"
        )
        return 2

    try:
        profiles = discover_profiles(profiles_dir)
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"ben: failed to load profiles: {exc}\n")
        return 2

    kb_root = Path(args.root) if getattr(args, "root", None) else KnowledgeBase.default_root()
    kb = KnowledgeBase(kb_root)
    tax_path = kb.root / "taxonomy.json"
    try:
        taxonomy = kbmatch.load_taxonomy(tax_path if tax_path.is_file() else None)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        sys.stderr.write(f"ben: taxonomy error at {tax_path}: {exc}\n")
        return 2

    if taxonomy is None or vuln not in (taxonomy.get("vulns") or {}):
        # cross-check: maybe they swapped args
        if profile_id in (taxonomy or {}).get("vulns", {}) and vuln in profiles:
            sys.stderr.write(
                "ben: arguments look swapped; expected: ben probe <profile-id> <vuln>\n"
            )
        else:
            sys.stderr.write(f"ben: vuln {vuln!r} not in taxonomy.vulns\n")
        return 2

    if profile_id not in profiles:
        if profile_id in (taxonomy.get("vulns") or {}) and vuln in profiles:
            sys.stderr.write(
                "ben: arguments look swapped; expected: ben probe <profile-id> <vuln>\n"
            )
        else:
            sample = ", ".join(sorted(profiles)[:10])
            sys.stderr.write(
                f"ben: unknown profile {profile_id!r}\n"
                f"ben: available: {sample}\n"
            )
        return 2

    prof = profiles[profile_id]
    if not host_allowed(prof.host, authorized=prof.authorized):
        sys.stderr.write(
            f"ben: host {prof.host!r} not allowed "
            "(need authorized=true profile or private/loopback host)\n"
        )
        return 2
    if not prof.authorized and not args.force:
        sys.stderr.write(
            "ben: profile lacks authorized=true; pass --force to confirm "
            "you are in scope\n"
        )
        return 2

    vspec = taxonomy["vulns"][vuln]
    kb_ids = [str(x) for x in (vspec.get("kb") or [])]
    if not kb_ids:
        sys.stderr.write(f"ben: taxonomy.vulns[{vuln}].kb is empty\n")
        return 2

    entries = []
    for kid in kb_ids:
        try:
            entries.append(kb.get(kid))
        except Exception as exc:  # KBError
            sys.stderr.write(f"ben: taxonomy points at missing entry {kid}: {exc}\n")
            return 2

    entry = entries[0]
    validation = entry.get("validation") if isinstance(entry.get("validation"), dict) else None
    signal = (validation or {}).get("signal") if validation else None
    signal_ok = isinstance(signal, str) and bool(signal.strip())
    observations: list[HttpObs] = []
    if not validation or not signal_ok:
        label, code, detail = "UNVERIFIED", 3, "NO_VALIDATION"
    elif vuln != "file-write":
        label, code, detail = "UNVERIFIED", 3, f"probe for vuln {vuln!r} not implemented"
    else:
        deadline = time.time() + float(args.deadline)
        if time.time() > deadline:
            label, code, detail, observations = "UNVERIFIED", 3, "BUDGET", []
        else:
            label, code, detail, observations = _probe_file_write(
                prof.url,
                validation,
                timeout=float(args.timeout),
                max_requests=int(args.max_requests),
                allow_destructive=bool(args.allow_destructive),
            )

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    outdir = paths.ensure_output_dir(_repo_root()) / "probe" / profile_id / ts
    verdict = {
        "profile_id": profile_id,
        "vuln": vuln,
        "kb_ids": kb_ids,
        "label": label,
        "exit_code": code,
        "detail": detail,
        "url": prof.url,
        "validation_snapshot": validation,
        "evidence_dir": str(outdir),
        "n_requests": len(observations),
    }
    _write_evidence(outdir, observations, verdict)

    if getattr(args, "probe_json", False):
        print(json.dumps(verdict, ensure_ascii=False, indent=2))
    else:
        print(f"profile: {profile_id}  vuln: {vuln}  kb: {','.join(kb_ids)}")
        print(f"target: {prof.url}")
        if validation and not signal_ok:
            print("warn: validation present but signal empty")
        elif validation and not validation.get("baseline"):
            print("warn: 无阴性对照")
        print(f"verdict: {label} ({detail})")
        print(f"evidence: {outdir}")
        if code == 0 and observations:
            puts = [o for o in observations if o.method == "PUT"]
            # Prefer the GET that actually carried the marker, not the baseline 404.
            gets = [o for o in observations if o.method == "GET" and o.ok_transport and o.body]
            if puts:
                print(f"evidence-put: {puts[-1].method} {puts[-1].status} {puts[-1].url}")
            if gets:
                print(f"evidence-get: {gets[-1].method} {gets[-1].status} {gets[-1].url}")
    return code
