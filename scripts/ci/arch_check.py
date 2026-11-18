#!/usr/bin/env python3
"""arch_check — architecture and repository hygiene checks (stdlib only).

Why this exists
---------------
A rule that no machine enforces decays into prose. This file is the machine:
seven checks, each mapping to a failure mode this repo has actually produced.

  packages       a directory under ben/ that is not registered in docs/ARCH.md
                 (a new module appears without a stated responsibility), or a
                 test file left inside the package instead of tests/
  duplicates     two functions in different files that are near-identical
                 either in text or in the sequence of calls they make
                 (the same idea implemented twice, then drifting)
  third_party    an import of a non-stdlib module outside ben/llm/sdk.py
                 (the zero-dependency kernel quietly acquiring a dependency)
  orphans        .pyc left behind after its .py was deleted
  stale_refs     provenance markers that point at a review note nobody can
                 open, or [adr:NNNN] pointing at a decision record that does
                 not exist — the reason behind the code becomes lost
  runtime_paths  a module spelling the runtime directory name itself, or a
                 repository that does not ignore it (generated material —
                 logs, registries, captured target data — becoming source)
  root_layout    an entry at the repository root that nobody declared (the
                 root is the first thing a reader sees; leftovers accumulate
                 there until archived data ends up in the index)
  agents_budget  AGENTS.md growing past its line budget (rule files only grow)

Exit code 0 = clean (baselined violations allowed while unexpired), 1 otherwise.

Baselines
---------
scripts/ci/arch_baseline.json freezes known violations so the check can be
switched on today instead of after a big cleanup:

    {"<check>::<key>": {"reason": "...", "expires": "YYYY-MM-DD"}}

Past its expires date an entry STOPS being excused. Baselines rot on purpose:
an immortal baseline is a disabled check.
"""
from __future__ import annotations

import argparse
import ast
import difflib
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BASELINE = REPO / "scripts" / "ci" / "arch_baseline.json"

RULE_BUDGET = 60          # lines in a generated AGENTS.md
DUP_TEXT_RATIO = 0.86     # near-identical source
DUP_CALL_RATIO = 0.92     # same pipeline of calls, different formatting
DUP_MIN_LINES = 12        # ignore trivial getters/setters
DUP_MIN_CALLS = 8         # call-sequence signal needs enough calls to mean anything

SCAN_ROOTS = ("ben", "scripts", "tests")
SKIP_DIRS = {"__pycache__", ".git", ".venv", "node_modules", ".workbuddy", "runs", "dist"}
CODE_SUFFIXES = {".py", ".html"}

REVIEW_ID = re.compile(r"review\s+([A-Z]\d+)")
CODEX_ID = re.compile(r"codex#(\d+)")
ADR_REF = re.compile(r"\[adr:(\d{4})\]")
PYC_SUFFIX = re.compile(r"\.cpython-\d+\.pyc$")

# Third-party imports allowed at a specific path (guarded, optional dependency).
THIRD_PARTY_ALLOWLIST = {
    "ben/llm/sdk.py": {"openai", "httpx"},
}

# The runtime directory's name lives in one file; see check_runtime_paths.
RUNTIME_LITERAL = "runs"          # must equal ben/core/paths.py:DEFAULT_RUNTIME_DIR
RUNTIME_ALLOWLIST = {"ben/core/paths.py"}

# The repository root is a closed set; see check_root_layout. Adding an entry
# here is a deliberate act, which is the whole point — a new top-level folder
# is an architectural decision, not an accident to be discovered later.
ROOT_FILES = {
    "README.md",          # front door
    "AGENTS.md",          # generated rule file; hooks read it from here
    ".gitignore",
    ".env.example",       # documented template
    ".env",               # local secrets, ignored
    ".env.local",
    "pyproject.toml",     # ruff / import-linter / pytest (R-04)
}
ROOT_DIRS = {
    "ben",                # the package (and the only source tree)
    "tests",
    "bin",                # launcher; install.sh and ~/.local/bin/ben point here
    "scripts",            # install.sh, ci/, hooks/
    "skills",             # distributable agent skill (symlinked by install.sh)
    "examples",
    "docs",
    "lab",                # archived engagement material, never written by code
    "runs",               # the ONE runtime output root (ADR-0006); gitignored
    ".github",            # CI workflows (R-05)
}
ROOT_HIDDEN = {
    ".git", ".ben", ".claude", ".venv", ".workbuddy", ".pytest_cache",
    ".cursor", ".vscode", ".idea",   # editor config: harmless, not source
    # the desktop environment's trash: `rm` moves files here instead of
    # unlinking them. It is gitignored, machine-managed, and never project
    # content — flagging it would make every local delete look like a failure.
    ".Trash-0",
}
# Where a rejected entry should have gone. The message is the fix.
ROOT_HINTS = {
    "runs": "generated output → ben.core.paths.runtime_root() (already ignored)",
    "logs": "worker / console logs → ben.core.paths.logs_dir()",
    "console": "PTY sessions → <runtime>/console (ben.runtime.console.console_root)",
    "tmp": "scratch → /tmp, or .workbuddy/tmp/ if it must survive a restart",
    "recon": "captured target material → lab/<engagement>/ (untracked)",
    "jsscan": "captured target material → lab/<engagement>/ (untracked)",
    "src": "this tree is flat on purpose: the package is ben/, not src/ben/",
    "dist": "build artifacts → scripts/install.sh --with-sdk installs into .venv/",
    "build": "build artifacts do not belong in the repo",
}
ROOT_DEFAULT_HINT = (
    "source goes in a package under ben/ (registered in docs/ARCH.md); "
    "generated files go to the runtime root; archived data goes to lab/"
)


# ---------------------------------------------------------------- infra


def _violation(check: str, key: str, detail: str) -> dict:
    return {"check": check, "key": key, "detail": detail}


_BASE: Path = REPO          # repo root the current check is running against


def _use(repo: Path) -> Path:
    """Point _rel() at this repo. Checks receive their root as an argument so
    they stay testable against a throwaway tree."""
    global _BASE
    _BASE = repo
    return repo


def _rel(p: Path) -> str:
    for base in (_BASE, REPO):
        try:
            return str(p.relative_to(base))
        except ValueError:
            continue
    return str(p)


def _code_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix not in CODE_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        out.append(p)
    return sorted(out)


def _py_files(root: Path) -> list[Path]:
    return [p for p in _code_files(root) if p.suffix == ".py"]


# ---------------------------------------------------------------- checks


def check_packages(repo: Path) -> list[dict]:
    """Every ben/<dir>/ is registered in ARCH.md and holds source, not tests."""
    repo = _use(repo)
    arch = repo / "docs" / "ARCH.md"
    if not arch.is_file():
        return [_violation("packages", "docs/ARCH.md", "docs/ARCH.md is missing")]

    registered: set[str] = set()
    for line in arch.read_text(encoding="utf-8").splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells:
            continue
        name = cells[0].strip("` ").rstrip("/")
        if name.startswith(("ben", "scripts")):
            registered.add(name)

    out: list[dict] = []
    for d in sorted(p for p in (repo / "ben").iterdir() if p.is_dir()):
        if d.name in SKIP_DIRS or not any(d.glob("*.py")):
            continue
        key = f"ben/{d.name}"
        if key not in registered:
            out.append(_violation("packages", key, f"{key} is not registered in docs/ARCH.md"))
        for stray in d.glob("test_*.py"):
            out.append(_violation(
                "packages", _rel(stray),
                f"{_rel(stray)} belongs in tests/, not inside the package",
            ))
    return out


def _functions(repo: Path) -> list[tuple[str, str, str, list[str]]]:
    """(name, file, normalised body, ordered call names) for comparable funcs."""
    out: list[tuple[str, str, str, list[str]]] = []
    for p in _py_files(repo / "ben"):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        lines = p.read_text(encoding="utf-8").splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = list(node.body)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                body = body[1:]                      # docstring carries no behaviour
            if not body:
                continue
            start = body[0].lineno
            end = max(getattr(n, "end_lineno", n.lineno) for n in body)
            raw = lines[start - 1:end]
            norm = "\n".join(re.sub(r"#.*$", "", ln).rstrip() for ln in raw if ln.strip())
            calls: list[str] = []
            for n in ast.walk(node):
                if isinstance(n, ast.Call):
                    f = n.func
                    if isinstance(f, ast.Name):
                        calls.append(f.id)
                    elif isinstance(f, ast.Attribute):
                        calls.append(f.attr)
            if norm:
                out.append((node.name, _rel(p), norm, calls))
    return out


def check_duplicates(repo: Path) -> list[dict]:
    repo = _use(repo)
    funcs = _functions(repo)
    found: list[dict] = []
    for i in range(len(funcs)):
        name_a, file_a, body_a, calls_a = funcs[i]
        for j in range(i + 1, len(funcs)):
            name_b, file_b, body_b, calls_b = funcs[j]
            # Cross-file only, on purpose: identical *shapes* inside one module
            # (get_fact/get_intent, list_facts/list_intents, three arena HTTP
            # wrappers) are deliberate symmetry, not debt. Duplication that
            # actually hurts is always "the same idea in two places".
            if file_a == file_b:
                continue

            text_ratio = 0.0
            if min(len(body_a), len(body_b)) >= DUP_MIN_LINES:
                if abs(len(body_a) - len(body_b)) <= max(len(body_a), len(body_b)) * 0.4:
                    text_ratio = difflib.SequenceMatcher(None, body_a, body_b).ratio()

            call_ratio = 0.0
            if len(calls_a) >= DUP_MIN_CALLS and len(calls_b) >= DUP_MIN_CALLS:
                call_ratio = difflib.SequenceMatcher(None, calls_a, calls_b).ratio()

            if text_ratio < DUP_TEXT_RATIO and call_ratio < DUP_CALL_RATIO:
                continue

            basis = []
            if text_ratio >= DUP_TEXT_RATIO:
                basis.append(f"{text_ratio:.0%} identical source")
            if call_ratio >= DUP_CALL_RATIO:
                basis.append(f"{call_ratio:.0%} same call sequence")
            key = "::".join(sorted([f"{file_a}::{name_a}", f"{file_b}::{name_b}"]))
            found.append(_violation(
                "duplicates", key,
                f"{file_a}::{name_a}  ≈  {file_b}::{name_b}  ({', '.join(basis)})",
            ))
    found.sort(key=lambda v: v["key"])
    return found


def check_third_party(repo: Path) -> list[dict]:
    """The kernel is stdlib-only, with one nuance that matters in practice:

    - a MODULE-LEVEL third-party import is a hard dependency → only allowed in
      ben/llm/sdk.py (and whatever THIRD_PARTY_ALLOWLIST names);
    - a FUNCTION-LEVEL import is optional and lazy (the SDK may not be
      installed at all) → allowed anywhere under ben/llm/.

    Collapsing those two would either ban the lazy SDK entirely or let a hard
    dependency slip into core.
    """
    repo = _use(repo)
    stdlib = set(getattr(sys, "stdlib_module_names", set()))
    out: list[dict] = []
    for p in _py_files(repo / "ben"):
        rel = _rel(p)
        allowed = THIRD_PARTY_ALLOWLIST.get(rel, set())
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue

        parents: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node

        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods = [node.module.split(".")[0]]

            lazy = False
            cur = parents.get(node)
            while cur is not None:
                if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    lazy = True
                    break
                cur = parents.get(cur)
            lazy_ok = lazy and rel.startswith("ben/llm/")

            for mod in mods:
                if mod in ("ben", "__future__") or mod in stdlib or mod in allowed or lazy_ok:
                    continue
                out.append(_violation(
                    "third_party", f"{rel}:{node.lineno}",
                    f"module-level import of '{mod}' — kernel is stdlib-only "
                    f"(import inside a function for an optional path)",
                ))
    return out


def check_orphans(repo: Path) -> list[dict]:
    repo = _use(repo)
    out: list[dict] = []
    for root in SCAN_ROOTS:
        base = repo / root
        if not base.is_dir():
            continue
        for pyc in base.rglob("*.pyc"):
            if not PYC_SUFFIX.search(pyc.name):
                continue
            source = pyc.parent.parent / (PYC_SUFFIX.sub(".py", pyc.name))
            if not source.is_file():
                out.append(_violation(
                    "orphans", _rel(pyc), f"{_rel(pyc)} has no source ({_rel(source)})",
                ))
    return sorted(out, key=lambda v: v["key"])


def check_stale_refs(repo: Path) -> list[dict]:
    repo = _use(repo)
    """Provenance markers must resolve, or they are noise."""
    reviews = repo / "docs" / "reviews" / "INDEX.md"
    review_text = reviews.read_text(encoding="utf-8") if reviews.is_file() else ""
    adr_dir = repo / "docs" / "adr"
    adr_ids = {p.name.split("-", 1)[0] for p in adr_dir.glob("*.md")} if adr_dir.is_dir() else set()

    out: list[dict] = []
    for p in _code_files(repo):
        if not any(str(p).startswith(str(repo / r)) for r in SCAN_ROOTS):
            continue
        for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            for token in REVIEW_ID.findall(line):
                if token not in review_text:
                    out.append(_violation(
                        "stale_refs", f"{_rel(p)}:{lineno}",
                        f"external-review id '{token}' does not resolve in docs/reviews/INDEX.md",
                    ))
            for token in CODEX_ID.findall(line):
                if f"codex#{token}" not in review_text:
                    out.append(_violation(
                        "stale_refs", f"{_rel(p)}:{lineno}",
                        f"'codex#{token}' does not resolve in docs/reviews/INDEX.md",
                    ))
            for adr in ADR_REF.findall(line):
                if adr not in adr_ids:
                    out.append(_violation(
                        "stale_refs", f"{_rel(p)}:{lineno}",
                        f"[adr:{adr}] has no docs/adr/{adr}-*.md",
                    ))
    return out


def check_agents_budget(repo: Path) -> list[dict]:
    repo = _use(repo)
    agents = repo / "AGENTS.md"
    if not agents.is_file():
        return []
    text = agents.read_text(encoding="utf-8")
    if not text.startswith("<!-- generated by ben"):
        return []                      # hand-written rule file: not our budget
    n = len(text.splitlines())
    if n > RULE_BUDGET:
        return [_violation(
            "agents_budget", "AGENTS.md",
            f"{n} lines > budget {RULE_BUDGET}; delete a rule before adding one",
        )]
    return []


def check_runtime_paths(repo: Path) -> list[dict]:
    """Runtime output has exactly one home; this check keeps it that way.

    Two halves of one rule:

    1. the directory name is spelled in one place only
       (``ben/core/paths.py:DEFAULT_RUNTIME_DIR``) — a call site that writes
       ``"runs"`` itself has silently opted out of ``BEN_RUNTIME_DIR`` and will
       keep working after the layout is changed, which is how a stray
       ``logs/`` or ``console/`` reappears at a repo root;
    2. that directory is gitignored, so a session that writes 400 MB of
       target material cannot be committed by accident.
    """
    repo = _use(repo)
    out: list[dict] = []
    for p in _py_files(repo / "ben"):
        rel = _rel(p)
        if rel in RUNTIME_ALLOWLIST:
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            value = node.value
            if value != RUNTIME_LITERAL and not value.startswith(RUNTIME_LITERAL + "/"):
                continue
            out.append(_violation(
                "runtime_paths", f"{rel}:{node.lineno}",
                f"hardcodes {value!r}: runtime output must go through "
                f"ben.core.paths (runtime_root / output_dir / logs_dir / "
                f"snapshot_file) so BEN_RUNTIME_DIR still applies and nothing "
                f"is written next to the source tree",
            ))

    gitignore = repo / ".gitignore"
    text = gitignore.read_text(encoding="utf-8") if gitignore.is_file() else ""
    ignored = {
        line.strip().strip("/")
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    if RUNTIME_LITERAL not in ignored and RUNTIME_LITERAL + "/" not in ignored:
        out.append(_violation(
            "runtime_paths", ".gitignore",
            f"{RUNTIME_LITERAL!r} is not ignored: a run's logs, registries and "
            f"captured material would become commit candidates. Add "
            f"'/{RUNTIME_LITERAL}/'",
        ))
    return out


def check_root_layout(repo: Path) -> list[dict]:
    """The repository root is a closed set, not an open dumping ground.

    Every entry at the root is read by someone who has never seen this repo.
    Twenty-odd entries where a third are leftovers (an empty ``console/`` from a
    path change, a ``.verify-runtime-*`` from a test that forgot to clean up,
    three versions of the same plan document sitting side by side) is not a
    cosmetic problem: it is how a 2.9 MB assessment directory ends up in the
    index, because nothing ever says "this does not belong here".

    So the root has a declared allowlist, and anything else fails with the
    place it should have gone.
    """
    repo = _use(repo)
    out: list[dict] = []
    for p in sorted(repo.iterdir()):
        name = p.name
        if p.is_dir():
            if name in ROOT_DIRS or name in ROOT_HIDDEN:
                continue
            shown = name + "/"
        else:
            if name in ROOT_FILES or name in ROOT_HIDDEN:
                continue
            shown = name
        hint = ROOT_HINTS.get(name, ROOT_DEFAULT_HINT)
        out.append(_violation(
            "root_layout", name,
            f"./{shown} is not a declared root entry — {hint}. "
            f"If it genuinely belongs at the root, add it to ROOT_FILES / "
            f"ROOT_DIRS in scripts/ci/arch_check.py",
        ))
    return out



def check_docs_links(repo: Path) -> list[dict]:
    """Markdown links under docs/ and README.md must resolve on disk."""
    repo = repo.resolve()
    out: list[dict] = []
    roots = [repo / "README.md", repo / "docs"]
    md_files: list[Path] = []
    for root in roots:
        if root.is_file():
            md_files.append(root)
        elif root.is_dir():
            md_files.extend(sorted(root.rglob("*.md")))
    link_re = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
    for md in md_files:
        try:
            body = md.read_text(encoding="utf-8")
        except OSError:
            continue
        for match in link_re.finditer(body):
            target = match.group(2).strip()
            if not target or target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target = target.split("#", 1)[0].split("?", 1)[0]
            if not target:
                continue
            dest = (md.parent / target).resolve()
            try:
                dest.relative_to(repo)
            except ValueError:
                continue
            if not dest.exists():
                rel = md.relative_to(repo).as_posix()
                out.append(_violation(
                    "docs_links", f"{rel}:{target}",
                    f"broken link in {rel} -> {target}",
                ))
    return out


CHECKS = {
    "packages": check_packages,
    "duplicates": check_duplicates,
    "third_party": check_third_party,
    "orphans": check_orphans,
    "stale_refs": check_stale_refs,
    "runtime_paths": check_runtime_paths,
    "root_layout": check_root_layout,
    "agents_budget": check_agents_budget,
    "docs_links": check_docs_links,
}


# ---------------------------------------------------------------- baseline


def load_baseline() -> dict:
    if not BASELINE.is_file():
        return {}
    try:
        return json.loads(BASELINE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _expired(entry: dict, today: date) -> bool:
    raw = entry.get("expires")
    if not raw:
        return False
    try:
        return date.fromisoformat(raw) < today
    except ValueError:
        return True


def apply_baseline(violations: list[dict], baseline: dict, today: date) -> tuple[list[dict], list[dict]]:
    active: list[dict] = []
    excused: list[dict] = []
    for v in violations:
        entry = baseline.get(f"{v['check']}::{v['key']}")
        if entry is None:
            active.append(v)
        elif _expired(entry, today):
            v = {**v, "detail": v["detail"] + f"  [baseline expired {entry.get('expires')}]"}
            active.append(v)
        else:
            excused.append({**v, "reason": entry.get("reason", ""), "expires": entry.get("expires")})
    return active, excused


# ---------------------------------------------------------------- cli


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="architecture & repo hygiene checks")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--check", action="append", choices=sorted(CHECKS), help="run only these")
    ap.add_argument("--update-baseline", action="store_true",
                    help="freeze current violations for 14 days")
    ap.add_argument("--show-baseline", action="store_true", help="list baseline entries")
    args = ap.parse_args(argv)

    if args.show_baseline:
        base = load_baseline()
        if not base:
            print("baseline empty — every violation is active")
        for key, entry in sorted(base.items()):
            print(f"{key}\n    {entry.get('reason','')}  (expires {entry.get('expires')})")
        return 0

    names = args.check or list(CHECKS)
    violations: list[dict] = []
    for name in names:
        violations.extend(CHECKS[name](REPO))

    if args.update_baseline:
        today = date.today()
        base = load_baseline()
        for v in violations:
            base[f"{v['check']}::{v['key']}"] = {
                "reason": v["detail"],
                "expires": (today + timedelta(days=14)).isoformat(),
            }
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(base, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"baseline updated: {len(violations)} entries → {_rel(BASELINE)}")
        return 0

    active, excused = apply_baseline(violations, load_baseline(), date.today())

    if args.json:
        print(json.dumps({
            "checks": names,
            "active": active,
            "excused": excused,
            "ok": not active,
        }, indent=2, ensure_ascii=False))
        return 0 if not active else 1

    print(f"arch_check  {len(names)} checks, {len(active)} violation(s), "
          f"{len(excused)} baselined")
    for v in active:
        print(f"  ✗ {v['check']:14s} {v['key']}\n      {v['detail']}")
    for v in excused:
        print(f"  ~ {v['check']:14s} {v['key']}  (expires {v['expires']})")
    if not active:
        print("  ✓ clean")
    return 0 if not active else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
