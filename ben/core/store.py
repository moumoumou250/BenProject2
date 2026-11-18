"""The Store: locked, one-JSON-per-node fact graph storage."""
from __future__ import annotations

import fcntl
import json
from contextlib import contextmanager
from pathlib import Path

from ben.consts import GOAL_ID, LOCK_NAME, _UNSET
from ben.core.errors import FGError
from ben.core.io import _read_node_files, atomic_write_json, now_iso, read_json
from ben.core.schema import _check_conclusion_permission, _read_node, _validate_lookup_id, normalize_fact_data, normalize_fact_kind


class Store:
    """Filesystem-backed fact graph. One file per node, fcntl-locked."""

    def __init__(self, root: Path):
        self.root = root
        self.facts_dir = root / "facts"
        self.intents_dir = root / "intents"
        self.hints_dir = root / "hints"
        self.project_file = root / "project.json"
        self.lock_file = root / LOCK_NAME

    # -- existence --
    def exists(self) -> bool:
        return self.project_file.exists()

    def require(self) -> None:
        if not self.exists():
            raise FGError(
                f"no fact graph here ({self.root}). run `ben init` first, or "
                f"use --store <path>."
            )

    # -- init --
    def init(self, origin: str, goal: str) -> None:
        goal = goal.strip()
        if not goal:
            raise FGError("goal cannot be empty")
        # Serialize initialization too.  Without this lock two simultaneous
        # `ben init` processes can both pass the existence check and overwrite
        # each other's project metadata and goal fact.
        with self.locked():
            if self.exists():
                raise FGError(f"fact graph already exists at {self.root}")
            leftovers = [p.name for p in self.root.iterdir() if p.name != LOCK_NAME]
            if leftovers:
                raise FGError(
                    f"cannot initialize graph in non-empty directory {self.root}; "
                    f"found: {', '.join(sorted(leftovers)[:5])}"
                )
            for d in (self.root, self.facts_dir, self.intents_dir, self.hints_dir):
                d.mkdir(parents=True, exist_ok=True)
            project = {
                "id": "proj",
                "origin": origin.strip(),
                "goal": goal,
                "status": "active",
                "created_at": now_iso(),
                "counters": {"fact": 0, "intent": 0, "hint": 0, "run": 0},
            }
            atomic_write_json(self.project_file, project)
            # the goal terminal fact
            goal_fact = {
                "id": GOAL_ID,
                "description": goal,
                "created_at": now_iso(),
                "creator": "system",
                "source_intent": None,
            }
            atomic_write_json(self.facts_dir / f"{GOAL_ID}.json", goal_fact)

    # -- locking --
    @contextmanager
    def locked(self):
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.lock_file, "a+")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            fh.close()

    # -- project --
    def load_project(self) -> dict:
        try:
            project = read_json(self.project_file)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError, TypeError, ValueError) as exc:
            raise FGError(f"cannot read project metadata {self.project_file}: {exc}") from exc
        if not isinstance(project, dict):
            raise FGError("invalid project.json: expected a JSON object")
        for key in ("id", "origin", "goal", "status"):
            if not isinstance(project.get(key), str):
                raise FGError(f"invalid project.json: '{key}' must be a string")
        if not project["goal"].strip():
            raise FGError("invalid project.json: 'goal' cannot be empty")
        counters = project.get("counters")
        if counters is None:
            counters = {}
            project["counters"] = counters
        if not isinstance(counters, dict):
            raise FGError("invalid project.json: 'counters' must be an object")
        for kind in ("fact", "intent", "hint", "run"):
            value = counters.get(kind, 0)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise FGError(f"invalid project.json: counter {kind!r} must be a non-negative integer")
            counters.setdefault(kind, value)
        return project

    def save_project(self, project: dict) -> None:
        atomic_write_json(self.project_file, project)

    # -- id generation (must be called inside locked) --
    def _next_id(self, kind: str, prefix: str) -> str:
        project = self.load_project()
        n = project["counters"].get(kind, 0) + 1
        directory = {
            "fact": self.facts_dir,
            "intent": self.intents_dir,
            "hint": self.hints_dir,
        }.get(kind)
        # Counters are metadata, not the source of truth.  If a user restores
        # or hand-edits a graph with a stale counter, skip occupied ids instead
        # of silently replacing an existing node.
        while directory is not None and (directory / f"{prefix}{n:03d}.json").exists():
            n += 1
        project["counters"][kind] = n
        self.save_project(project)
        return f"{prefix}{n:03d}"

    # -- facts --
    def list_facts(self) -> list[dict]:
        return _read_node_files(self.facts_dir, "fact")

    def get_fact(self, fid: str) -> dict:
        _validate_lookup_id(fid, "fact")
        p = self.facts_dir / f"{fid}.json"
        if not p.exists():
            raise FGError(f"fact {fid} not found")
        return _read_node(p, "fact")

    def add_fact(self, description: str, creator: str, source_intent: str | None = None,
                 title: str | None = None, doc: str | None = None,
                 kind: str | None = None, data: dict | None = None) -> dict:
        if not isinstance(description, str) or not description.strip():
            raise FGError("fact description cannot be empty")
        if not isinstance(creator, str) or not creator.strip():
            raise FGError("fact creator cannot be empty")
        if source_intent is not None:
            _validate_lookup_id(source_intent, "intent")
        kind = normalize_fact_kind(kind)
        data = normalize_fact_data(data)
        with self.locked():
            source = None
            if source_intent is not None:
                source = self.get_intent(source_intent)
                if source["to"] is not None:
                    raise FGError(f"intent {source_intent} already concluded")
                _check_conclusion_permission(source, creator, allow_unconfirmed=False)
            fid = self._next_id("fact", "f")
            fact = {
                "id": fid,
                "title": (title.strip() if title and title.strip() else None),
                "description": description.strip(),
                "doc": (doc.strip() if doc and doc.strip() else None),
                "kind": kind,
                "data": data,
                "created_at": now_iso(),
                "creator": creator,
                "source_intent": source_intent,
            }
            atomic_write_json(self.facts_dir / f"{fid}.json", fact)
            if source is not None:
                source["to"] = fid
                source["status"] = "done"
                source["concluded_at"] = now_iso()
                source["worker"] = creator or source.get("worker")
                self.save_intent(source)
            return fact

    # -- intents --
    def list_intents(self) -> list[dict]:
        return _read_node_files(self.intents_dir, "intent")

    def get_intent(self, iid: str) -> dict:
        _validate_lookup_id(iid, "intent")
        p = self.intents_dir / f"{iid}.json"
        if not p.exists():
            raise FGError(f"intent {iid} not found")
        return _read_node(p, "intent")

    def _validate_from(self, fact_ids: list[str]) -> None:
        if not isinstance(fact_ids, list) or not fact_ids:
            raise FGError("intent must have at least one `from` fact")
        if any(not isinstance(fid, str) for fid in fact_ids):
            raise FGError("intent `from` ids must be strings")
        # Per-id lookup (R-07): avoid list_facts() O(n) scan under the graph lock.
        for fid in fact_ids:
            if fid == GOAL_ID:
                raise FGError("`goal` cannot be used in `from`")
            _validate_lookup_id(fid, "fact")
            try:
                self.get_fact(fid)
            except FGError as exc:
                if "not found" in str(exc):
                    raise FGError(f"from fact {fid} does not exist") from exc
                raise

    def add_intent(
        self,
        from_ids: list[str],
        description: str,
        creator: str,
        requires_confirmation: bool = False,
        title: str | None = None,
        doc: str | None = None,
    ) -> dict:
        if not isinstance(description, str) or not description.strip():
            raise FGError("intent description cannot be empty")
        if not isinstance(creator, str) or not creator.strip():
            raise FGError("intent creator cannot be empty")
        if not isinstance(from_ids, list) or any(not isinstance(fid, str) for fid in from_ids):
            raise FGError("intent `from` ids must be a list of strings")
        # A hyper-edge only needs each dependency once; de-duplicate model or
        # API input before validation and persistence.
        from_ids = list(dict.fromkeys(from_ids))
        with self.locked():
            self._validate_from(from_ids)
            iid = self._next_id("intent", "i")
            intent = {
                "id": iid,
                "title": (title.strip() if title and title.strip() else None),
                "from": from_ids,
                "to": None,
                "description": description.strip(),
                "doc": (doc.strip() if doc and doc.strip() else None),
                "creator": creator,
                "status": "open",
                "worker": None,
                "requires_confirmation": requires_confirmation,
                "confirmed_at": None,
                "created_at": now_iso(),
                "concluded_at": None,
            }
            atomic_write_json(self.intents_dir / f"{iid}.json", intent)
            return intent

    def save_intent(self, intent: dict) -> None:
        _validate_lookup_id(intent.get("id"), "intent")
        atomic_write_json(self.intents_dir / f"{intent['id']}.json", intent)

    def update_doc(self, node_id: str, doc: str | None, *, expected_doc=_UNSET) -> dict:
        """Update a fact/intent document under the graph lock."""
        _validate_lookup_id(node_id, "node")
        with self.locked():
            candidates = []
            if node_id == GOAL_ID:
                candidates.append(("fact", self.facts_dir / f"{node_id}.json"))
            else:
                candidates.extend([
                    ("fact", self.facts_dir / f"{node_id}.json"),
                    ("intent", self.intents_dir / f"{node_id}.json"),
                ])
            for kind, path in candidates:
                if path.exists():
                    node = _read_node(path, kind)
                    if expected_doc is not _UNSET and node.get("doc") != expected_doc:
                        raise FGError(
                            f"{node_id} changed while the editor was open; "
                            "re-read it and try again"
                        )
                    node["doc"] = doc.strip() if isinstance(doc, str) and doc.strip() else None
                    atomic_write_json(path, node)
                    return node
        raise FGError(f"no fact or intent named {node_id}")

    def conclude_intent(
        self,
        iid: str,
        to_fact_id: str,
        worker: str | None,
        *,
        allow_unconfirmed: bool = False,
    ) -> dict:
        """Link an intent to a produced fact (or 'goal').

        Confirmation and ownership are enforced here as the final write-side
        guard.  Callers cannot bypass a human approval gate merely by invoking
        `ben done` or a lower-level method.  `allow_unconfirmed` is reserved
        for internal abandonment bookkeeping (for example brainstorm siblings)
        and is never exposed as a CLI flag.
        """
        with self.locked():
            intent = self.get_intent(iid)
            if intent["to"] is not None:
                raise FGError(
                    f"intent {iid} already concluded (to={intent['to']})"
                )
            _check_conclusion_permission(intent, worker, allow_unconfirmed)
            if to_fact_id != GOAL_ID:
                _validate_lookup_id(to_fact_id, "fact")
            else:
                project = self.load_project()
                if project.get("status") == "completed":
                    raise FGError("project is already completed")
                if project.get("status") != "active":
                    raise FGError(f"project status {project.get('status')!r} cannot be completed")
                if any(
                    other.get("id") != iid and other.get("to") == GOAL_ID
                    for other in self.list_intents()
                ):
                    raise FGError("project already has a completion edge")
            if to_fact_id != GOAL_ID:
                # fact must exist
                target_fact = self.get_fact(to_fact_id)
                source_intent = target_fact.get("source_intent")
                if source_intent not in (None, iid):
                    raise FGError(
                        f"fact {to_fact_id} already belongs to intent {source_intent}"
                    )
                if source_intent is None:
                    target_fact["source_intent"] = iid
                    atomic_write_json(self.facts_dir / f"{to_fact_id}.json", target_fact)
            intent["to"] = to_fact_id
            intent["status"] = "complete" if to_fact_id == GOAL_ID else "done"
            intent["concluded_at"] = now_iso()
            intent["worker"] = worker or intent.get("worker")
            self.save_intent(intent)
            if to_fact_id == GOAL_ID:
                project = self.load_project()
                project["status"] = "completed"
                project["completed_at"] = now_iso()
                self.save_project(project)
            return intent

    def complete_project(self, from_ids: list[str], note: str, worker: str) -> dict:
        """Create the terminal goal edge atomically with the project status."""
        if not isinstance(note, str) or not note.strip():
            raise FGError("completion note cannot be empty")
        if not isinstance(worker, str) or not worker.strip():
            raise FGError("completion worker cannot be empty")
        with self.locked():
            project = self.load_project()
            if project.get("status") == "completed":
                raise FGError("project is already completed")
            if project.get("status") != "active":
                raise FGError(f"project status {project.get('status')!r} cannot be completed")
            existing_goal_edge = any(
                i.get("to") == GOAL_ID for i in self.list_intents()
            )
            if existing_goal_edge:
                raise FGError("project already has a completion edge")
            self._validate_from(from_ids)
            iid = self._next_id("intent", "i")
            intent = {
                "id": iid,
                "title": None,
                "from": list(dict.fromkeys(from_ids)),
                "to": GOAL_ID,
                "description": note.strip(),
                "doc": None,
                "creator": worker,
                "status": "complete",
                "worker": worker,
                "requires_confirmation": False,
                "confirmed_at": None,
                "created_at": now_iso(),
                "concluded_at": now_iso(),
            }
            atomic_write_json(self.intents_dir / f"{iid}.json", intent)
            project["status"] = "completed"
            project["completed_at"] = now_iso()
            self.save_project(project)
            return intent

    def conclude_with_new_fact(
        self, iid: str, description: str, worker: str, title: str | None = None,
        doc: str | None = None, kind: str | None = None, data: dict | None = None,
        *,
        allow_unconfirmed: bool = False,
        evidence: str | Path | None = None,
        force: bool = False,
    ) -> tuple[dict, dict]:
        """Atomically: re-check the intent is still open under lock, allocate a new
        fact id, write the fact, and link the intent to it — all in ONE locked
        transaction. Prevents orphan facts (H1) and the duplicate-worker race (C1):
        if the intent was already concluded by a concurrent executor, this raises
        *before* any fact file is written, so nothing is orphaned.

        Evidence gate (R-03): require a ``ben verify`` report path matching this
        intent + HEAD sha, or ``force=True`` (writes ``data.forced=true``).
        Validation of the report file happens *outside* the lock (no nested lock).
        """
        from ben.core.evidence import (
            git_head_sha,
            load_evidence,
            merge_evidence_into_data,
            validate_evidence_for_intent,
        )
        from ben.core.roles import check_role_paths, load_roles

        kind = normalize_fact_kind(kind)
        data = normalize_fact_data(data)
        # Gate before lock — I/O must not hold LOCK_EX.
        if force:
            data = merge_evidence_into_data(data, {}, forced=True)
        elif evidence:
            ev = load_evidence(evidence)
            validate_evidence_for_intent(ev, intent_id=iid, expected_sha=git_head_sha())
            check_role_paths(
                role=worker.split("-", 1)[0] if worker else "agent",
                evidence_sha=str(ev.get("sha") or ""),
                roles=load_roles(self.root),
                force=False,
            )
            data = merge_evidence_into_data(data, ev, forced=False)
        else:
            raise FGError(
                "conclude requires evidence from `ben verify --intent ...` "
                "(pass evidence= path) or force=True / --force"
            )
        with self.locked():
            intent = self.get_intent(iid)
            if intent["to"] is not None:
                raise FGError(
                    f"intent {iid} already concluded (to={intent['to']}); "
                    f"dropping duplicate executor result"
                )
            _check_conclusion_permission(intent, worker, allow_unconfirmed=allow_unconfirmed)
            if not isinstance(description, str) or not description.strip():
                raise FGError("fact description cannot be empty")
            fid = self._next_id("fact", "f")
            fact = {
                "id": fid,
                "title": (title.strip() if title and title.strip() else None),
                "description": description.strip(),
                "doc": (doc.strip() if doc and doc.strip() else None),
                "kind": kind,
                "data": data,
                "created_at": now_iso(),
                "creator": worker,
                "source_intent": iid,
            }
            atomic_write_json(self.facts_dir / f"{fid}.json", fact)
            intent["to"] = fid
            intent["status"] = "done"
            intent["concluded_at"] = now_iso()
            intent["worker"] = worker or intent.get("worker")
            self.save_intent(intent)
            return fact, intent

    def claim_intent(self, iid: str, worker: str) -> dict:
        with self.locked():
            intent = self.get_intent(iid)
            if intent["to"] is not None:
                raise FGError(f"intent {iid} already concluded")
            if intent.get("requires_confirmation") and not intent.get("confirmed_at"):
                raise FGError(f"intent {iid} requires confirmation before it can be claimed")
            owner = intent.get("worker")
            if owner and owner != worker:
                raise FGError(f"intent {iid} claimed by {owner}")
            intent["worker"] = worker
            intent["status"] = "claimed"
            self.save_intent(intent)
            return intent

    def release_intent(self, iid: str, worker: str) -> dict:
        with self.locked():
            intent = self.get_intent(iid)
            if intent["to"] is not None:
                raise FGError(f"intent {iid} already concluded")
            if intent.get("worker") and intent["worker"] != worker:
                raise FGError(f"intent {iid} claimed by {intent['worker']}")
            intent["worker"] = None
            intent["status"] = "open"
            self.save_intent(intent)
            return intent

    def confirm_intent(self, iid: str) -> dict:
        with self.locked():
            intent = self.get_intent(iid)
            if intent["to"] is not None:
                raise FGError(f"intent {iid} already concluded")
            if not intent["requires_confirmation"]:
                raise FGError(f"intent {iid} does not require confirmation")
            if intent["confirmed_at"]:
                raise FGError(f"intent {iid} already confirmed")
            intent["confirmed_at"] = now_iso()
            self.save_intent(intent)
            return intent

    # -- hints --
    def list_hints(self) -> list[dict]:
        return _read_node_files(self.hints_dir, "hint")

    def add_hint(self, content: str, creator: str, to: str | None = None) -> dict:
        if not isinstance(content, str) or not content.strip():
            raise FGError("hint content cannot be empty")
        if not isinstance(creator, str) or not creator.strip():
            raise FGError("hint creator cannot be empty")
        if to is not None and (not isinstance(to, str) or not to.strip()):
            raise FGError("hint to must be a non-empty string when set")
        with self.locked():
            hid = self._next_id("hint", "h")
            hint = {
                "id": hid,
                "content": content.strip(),
                "creator": creator,
                "created_at": now_iso(),
            }
            if to:
                hint["to"] = to.strip()
            atomic_write_json(self.hints_dir / f"{hid}.json", hint)
            return hint

    def update_flag_fact(self, fid: str, status: str, result_note: str | None) -> dict:
        """Lifecycle update for a flag fact: recorded -> submitted/rejected.

        Facts are immutable by convention; flags are the one exception because
        their submission status changes after the fact is written (crash-safe:
        the capture is recorded first, the platform reply second)."""
        with self.locked():
            fact = self.get_fact(fid)
            if fact.get("kind") != "flag":
                raise FGError(f"fact {fid} is not a flag fact")
            if status not in ("recorded", "submitted", "rejected", "duplicate"):
                raise FGError(f"invalid flag status {status!r}")
            data = dict(fact.get("data") or {})
            data["status"] = status
            if result_note:
                data["result"] = result_note
            fact["data"] = normalize_fact_data(data)
            atomic_write_json(self.facts_dir / f"{fid}.json", fact)
            return fact
