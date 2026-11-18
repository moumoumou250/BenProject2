"""setup/teardown + AGENTS.md spec."""
from __future__ import annotations

import json
from pathlib import Path

from ben.commands.util import _assert_safe_store_root
from ben.core.errors import FGError
from ben.core.store import Store


def _skill_root() -> Path:
    """The repository root that ships this package (parent of ben/)."""
    return Path(__file__).resolve().parents[2]


def _hook_script_path() -> Path:
    return _skill_root() / "scripts" / "hooks" / "ben-hook.py"


def _load_settings_patch():
    """Load the settings patcher without importing it as a package."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_fg_settings_patch", _skill_root() / "scripts" / "hooks" / "_settings_patch.py"
        )
        assert spec and spec.loader
        patch = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(patch)
        return patch
    except Exception as exc:
        raise FGError(f"could not load settings patcher: {exc}") from exc


def cmd_setup(args) -> int:
    """`ben setup` — turn THIS project into a fact-graph project.

    Does three things, idempotently, scoped to the current project only:
      1. creates the local graph (.ben/) if --goal is given (else requires one
         to already exist, or asks you to pass --goal)
      2. registers the two hooks in <project>/.claude/settings.json so this
         project auto-injects the graph into every turn
      3. writes AGENTS.md so dispatched sub-agents know the protocol

    Nothing is written under ~. Other projects are untouched.
    """
    project_dir = Path.cwd()
    store = Store(Path(args.store))
    # Validate an existing settings file before creating a new graph.  A
    # malformed Claude config should not leave setup half-completed with a
    # graph that has no working hooks.
    patch = _load_settings_patch()
    target = patch.project_settings_path(project_dir)
    if target.exists():
        try:
            patch.validate(target)
        except (OSError, ValueError) as exc:
            raise FGError(f"could not read {target}: {exc}") from exc
    made_graph = False
    if not store.exists():
        if not args.goal:
            raise FGError(
                "no .ben/ here. Pass --goal \"<one-line goal>\" to create one, "
                "or run from a directory that already has a graph."
            )
        store.init(origin=args.origin or "", goal=args.goal)
        made_graph = True
        print(f"created graph at {store.root} (goal: {args.goal})")
    else:
        print(f"graph already present at {store.root}")

    # register hooks into project-level settings
    try:
        changed, msgs = patch.add(target, str(_hook_script_path()))
    except (OSError, ValueError) as exc:
        raise FGError(f"could not update {target}: {exc}") from exc
    for m in msgs:
        print(m)

    # AGENTS.md
    if args.agents:
        ap = project_dir / "AGENTS.md"
        if ap.exists() and not args.force:
            print(f"AGENTS.md exists — leaving it (--force to overwrite)")
        else:
            spec_txt = _AGENTS_SPEC.format(
                store=str(store.root.resolve()), marker=_AGENTS_MARKER
            )
            ap.write_text(spec_txt, encoding="utf-8")
            print(f"wrote {ap}")

    print(
        "\nsetup done. This project now auto-reads/maintains its fact graph.\n"
        "  ben status          # see current state\n"
        "  ben dispatch reason # propose next work\n"
        "  ben peers --discover # optional: list workers/consoles, then ask user who to authorize\n"
        "  ben auto --skip-permissions  # drive to completion\n"
        "To undo:  ben teardown   (removes ben hooks + its AGENTS.md; keeps .ben/)"
    )
    return 0


def cmd_teardown(args) -> int:
    """`ben teardown` — remove the hooks and ben-owned AGENTS.md from THIS project.

    Never touches the graph data (.ben/) unless --purge is given.
    """
    project_dir = Path.cwd()
    patch = _load_settings_patch()
    target = patch.project_settings_path(project_dir)
    removed_any = False
    if target.exists():
        try:
            _, msgs = patch.remove(target, str(_hook_script_path()))
        except (OSError, ValueError) as exc:
            raise FGError(f"could not update {target}: {exc}") from exc
        for m in msgs:
            print(m)
            if m.startswith("  -"):
                removed_any = True
        # if the project settings.json is now empty, drop it (and its dir)
        try:
            leftover = json.loads(target.read_text(encoding="utf-8") or "{}")
        except Exception:
            leftover = {}
        if not leftover:
            target.unlink(missing_ok=True)
            print(f"removed empty {target}")
            if target.parent.exists() and not any(target.parent.iterdir()):
                target.parent.rmdir()
                print(f"removed empty {target.parent}")

    ap = project_dir / "AGENTS.md"
    if ap.exists():
        try:
            agents_text = ap.read_text(encoding="utf-8")
        except OSError:
            agents_text = ""
        generated = (
            agents_text.startswith(_AGENTS_MARKER)
            or agents_text == _AGENTS_SPEC.format(
                store=str(Path(args.store).resolve()), marker=_AGENTS_MARKER
            )
        )
        if generated:
            ap.unlink()
            print(f"removed {ap}")
        else:
            print(f"kept existing {ap} (not generated by ben)")

    if args.purge:
        import shutil
        store_root = Path(args.store)
        if store_root.exists():
            _assert_safe_store_root(store_root, "purge")
            shutil.rmtree(store_root)
            print(f"purged graph data {store_root}")
    else:
        sr = Path(args.store)
        if sr.exists():
            print(f"(kept graph data at {sr}; pass --purge to delete it too)")
    return 0


_AGENTS_MARKER = "<!-- generated by ben; edit or remove this marker to keep this file -->"


_AGENTS_SPEC = """\
{marker}
# AGENTS.md — fact-graph protocol

This project uses a fact-graph as shared working memory. The graph lives at
`{store}` and is manipulated by the `ben` CLI.

## model
- **fact**: a confirmed observation or reproducible result. Immutable once written.
- **intent**: a unit of work. `from` = facts it depends on; `to` = the fact it
  produced (null while open). An intent with `to == "goal"` completes the project.
- **hint**: a live human message to the commander.

## commands you will use
```
ben status                     # project state + what's ready to work
ben graph                      # full graph as text (title + one-line summary + 📄 markers)
ben frontier                   # only the ready open intents
ben show intent <id>           # full node detail
ben doc <id>                   # read the DETAILED document of a fact/intent (when you need depth)
ben fact "<gist>" -t "<title>" [--doc "<detail>"]   # record a confirmed result
ben fact "<gist>" --from-intent i003              # record + close i003 atomically
ben done <intent-id> --fact "<gist>" -t "<title>"   # finish an intent, produce a fact
ben hint "<message>"           # leave a note for the commander / human
ben peers --discover           # list workers/consoles before asking the user to authorize peers
ben peers                      # list user-authorized peer targets from .ben/ai-peers.json
ben send <peer> "<message>"    # message an authorized peer (hint or console) + append .ben/ai-channel.txt
ben capture <peer>             # read recent output from an authorized peer log
```

## three documentation layers (every node)
1. **title** — short (2-10 字) human label, shown in the graph view.
2. **description** — one-sentence gist. Injected into prompts by default.
3. **doc** — detailed markdown (commands, paths, evidence). NOT in prompts by
   default; READ it with `ben doc <id>` when you need the full context.
   WRITE it with `--doc "..."` or `--doc-file <path>`.

## rules
1. Record only what you actually confirmed with a command, file, or log.
2. Never invent results. If evidence is missing, say so in the fact description.
3. Stay scoped to your assigned intent unless a blocker forces otherwise.
4. Prefer reproducible evidence: exact commands, paths, versions, error messages.
5. Conclude your intent with `ben done` so the commander can pick the next step.
6. Never send messages to a peer unless the user explicitly authorized it
   and it is listed by `ben peers` in `{store}/ai-peers.json`.
7. For authorized peer communication, prefer `ben send <peer> ...`; worker
   targets become directed hints (next reason cycle); console targets use the
   PTY socket; both append the shared log unless --no-log.
8. After sending a question, proactively check for replies with
   `ben capture <peer> --lines 120`; consoles may answer in their TUI, so
   not every reply appears in ai-channel.txt.
9. Everything ben generates at runtime lives under ONE directory: `runs/`
   (override: BEN_RUNTIME_DIR). Never write generated files, logs or captured
   material next to the source tree, and never commit that directory.

## rule budget
Keep this file under 60 lines. Add a rule only after deleting one. For every new
rule ask: can this become a machine check (lint, CI, a test) instead? If yes,
write the check — a check cannot be argued with, a rule can.
"""
