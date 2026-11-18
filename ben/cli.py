"""argparse CLI: parser, templates resolution, main()."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from ben.commands.arena_cmds import cmd_arena, cmd_flag
from ben.commands.util import _resolve_templates_dir
from ben.commands.auto import cmd_auto
from ben.commands.bench import cmd_bench
from ben.commands.commander import FLEET_FILE, cmd_command
from ben.commands.config_cmds import cmd_config
from ben.commands.dispatch import cmd_claim, cmd_complete, cmd_confirm, cmd_dispatch, cmd_done, cmd_release
from ben.commands.verify_cmds import cmd_verify
from ben.commands.fleet import cmd_fleet
from ben.commands.graph_cmds import cmd_fact, cmd_frontier, cmd_graph, cmd_hint, cmd_init, cmd_intent, cmd_pick, cmd_status, cmd_validate
from ben.commands.kb_cmds import cmd_kb
from ben.commands.probe_cmds import cmd_probe
from ben.commands.misc import cmd_doc, cmd_recall, cmd_show, cmd_sweep
from ben.agents.factory import cmd_brainstorm_pick
from ben.commands.console_cmds import cmd_console
from ben.commands.peers import cmd_capture, cmd_peers, cmd_send
from ben.commands.setup import cmd_setup, cmd_teardown
from ben import config as _config
from ben.consts import DEFAULT_STORE, FACT_KINDS, __version__
from ben.core import paths
from ben.core.errors import FGError
from ben.web.view import cmd_view


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ben",
        description="fact-graph working memory for agentic work",
    )
    p.add_argument("--store", default=DEFAULT_STORE, help=f"graph dir (default: {DEFAULT_STORE})")
    p.add_argument("--version", action="version", version=f"ben {__version__}")
    p.add_argument(
        "--engine",
        choices=["auto", "sdk", "cli"],
        default=None,
        help="model backend override (default: BEN_ENGINE or auto)",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("init", help="create a fact graph in --store")
    sp.add_argument("--origin", default="", help="where this task came from")
    sp.add_argument("--goal", required=True, help="the terminal goal")
    sp.add_argument("--force", action="store_true", help="overwrite existing graph")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("status", help="project + frontier")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("graph", help="dump the graph")
    sp.add_argument("--format", choices=["text", "json"], default="text")
    sp.set_defaults(func=cmd_graph)

    sp = sub.add_parser(
        "validate",
        help="audit graph JSON, references, and project status without changing files",
    )
    sp.set_defaults(func=cmd_validate)

    sp = sub.add_parser("frontier", help="open intents ready to work")
    sp.set_defaults(func=cmd_frontier)

    sp = sub.add_parser("pick", help="pick the next intent to work (prints id)")
    sp.add_argument("--claim", action="store_true", help="claim it for this agent")
    sp.add_argument("--any", action="store_true",
                    help="also consider open intents that aren't ready (e.g. unconfirmed)")
    sp.add_argument("--worker", default=None)
    sp.set_defaults(func=cmd_pick)

    sp = sub.add_parser(
        "fact", help="add a confirmed fact (optionally typed: host/service/cred/vuln/loot/flag)"
    )
    sp.add_argument("description", help="summary (one sentence) — the gist of this node")
    sp.add_argument("--title", "-t", default=None,
                    help="short human title shown in the graph view (中文标题)")
    sp.add_argument("--kind", "-k", default=None, choices=FACT_KINDS,
                    help="typed fact kind for offensive work")
    sp.add_argument("--data", "-d", default=None, action="append", metavar="KEY=VALUE",
                    help="structured data field (repeatable), e.g. -d host=10.0.0.1 -d port=80")
    sp.add_argument("--doc", default=None,
                    help="detailed document body (markdown). For long text use --doc-file")
    sp.add_argument("--doc-file", default=None,
                    help="read the detailed document from this file path")
    sp.add_argument("--creator", default="user")
    sp.add_argument("--from-intent", default=None, help="intent that produced this fact")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_fact)

    sp = sub.add_parser("intent", help="add an intent (a unit of work)")
    sp.add_argument("--from", dest="from_", required=True, help="comma/space separated fact ids")
    sp.add_argument("description", help="summary (one sentence) — what this intent will do")
    sp.add_argument("--title", "-t", default=None,
                    help="short human title shown in the graph view (中文标题)")
    sp.add_argument("--doc", default=None,
                    help="detailed document body (markdown). For long text use --doc-file")
    sp.add_argument("--doc-file", default=None,
                    help="read the detailed document from this file path")
    sp.add_argument("--creator", default="user")
    sp.add_argument("--confirm", action="store_true", help="requires human confirmation")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_intent)

    sp = sub.add_parser("hint", help="add or list human hints")
    sp.add_argument("content", nargs="?", default=None)
    sp.add_argument("--creator", default="user")
    sp.add_argument("--to", default=None,
                    help="optional worker target (e.g. w-c01); visible only to that worker")
    sp.add_argument("--list", action="store_true")
    sp.set_defaults(func=cmd_hint)

    sp = sub.add_parser(
        "peers",
        help="discover workers/consoles and manage user-authorized AI peers",
        description=(
            "List process workers (w-*) and PTY consoles (c-*) with --discover, then "
            "authorize selected targets with --add. ben send refuses to message "
            "peers that are not stored in .ben/ai-peers.json. "
            "Worker sends land as directed hints (visible on the next reason cycle); "
            "console sends go through the PTY socket."
        ),
    )
    sp.add_argument("--discover", action="store_true",
                    help="list worker processes and console sessions")
    sp.add_argument("--add", metavar="NAME", default=None,
                    help="authorize a peer name after user approval")
    sp.add_argument("--remove", metavar="NAME", default=None, help="remove an authorized peer")
    sp.add_argument("--target", default=None,
                    help="target for --add: w-<name> (worker) or c-<name> (console)")
    sp.add_argument("--sender", default=None, help="sender label used by ben send")
    sp.add_argument("--channel", default=None,
                    help="shared append-only log path (default: .ben/ai-channel.txt)")
    sp.add_argument("--note", default=None, help="optional human note about the peer")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_peers)

    sp = sub.add_parser(
        "send",
        help="send a message to a user-authorized peer",
        description=(
            "Send to a peer configured by `ben peers --add`. "
            "w-* targets become directed hints (next reason cycle); "
            "c-* targets are written to the PTY console socket. "
            "Messages are also appended to the shared log unless --no-log is used."
        ),
    )
    sp.add_argument("peer", help="authorized peer name")
    sp.add_argument("message", nargs="*", help="message text; stdin is used if omitted")
    sp.add_argument("--sender", default=None, help="override sender label for this message")
    sp.add_argument("--channel", default=None, help="override shared log path")
    sp.add_argument("--no-log", action="store_true", help="do not append to the shared log")
    sp.add_argument("--raw", action="store_true", help="send body without timestamp/sender prefix")
    sp.set_defaults(func=cmd_send)

    sp = sub.add_parser(
        "capture",
        help="read recent output from a user-authorized peer",
        description=(
            "Capture recent log output from a peer configured by `ben peers --add`. "
            "Workers use registry logs; consoles use write-through PTY logs."
        ),
    )
    sp.add_argument("peer", help="authorized peer name")
    sp.add_argument("--lines", type=int, default=120,
                    help="recent log lines to capture (1-2000)")
    sp.add_argument("--channel", default=None,
                    help="override shared log path when --log is used")
    sp.add_argument("--log", action="store_true",
                    help="append captured output to the shared log")
    sp.set_defaults(func=cmd_capture)

    sp = sub.add_parser(
        "console",
        help="manage PTY consoles for foreign interactive CLIs",
        description=(
            "Start a PTY-backed console session for an interactive CLI "
            "(claude, codex, …). Use with peers targets c-<name>."
        ),
    )
    csub = sp.add_subparsers(dest="console_action", required=True)
    cnew = csub.add_parser("new", help="start a console session")
    cnew.add_argument("name", help="session name (becomes c-<name>)")
    cnew.add_argument("cmd", nargs=argparse.REMAINDER, help="command after --")
    cnew.set_defaults(func=cmd_console)
    clist = csub.add_parser("list", help="list console sessions")
    clist.add_argument("--json", action="store_true")
    clist.set_defaults(func=cmd_console)
    ckill = csub.add_parser("kill", help="kill a console session")
    ckill.add_argument("name")
    ckill.set_defaults(func=cmd_console)
    cattach = csub.add_parser(
        "attach",
        help="live view of a console (tail-f style) + type lines to send",
        description=(
            "Attach to a console session: prints new screen output as the TUI "
            "writes it (ANSI-stripped, polling the write-through log), and "
            "forwards lines typed on stdin to the PTY. Ctrl-D or Ctrl-C to detach."
        ),
    )
    cattach.add_argument("name", help="session name (c-<name> also accepted)")
    cattach.set_defaults(func=cmd_console)
    ccap = csub.add_parser("capture", help="tail console write-through log")
    ccap.add_argument("name")
    ccap.add_argument("--lines", type=int, default=120)
    ccap.set_defaults(func=cmd_console)

    sp = sub.add_parser("show", help="show project | fact <id> | intent <id>")
    sp.add_argument("entity", choices=["project", "fact", "intent"])
    sp.add_argument("id", nargs="?", default=None)
    sp.set_defaults(func=cmd_show)

    sp = sub.add_parser(
        "doc",
        help="read or write a node's detailed document (the third layer)",
        description=(
            "Manage the detailed 'doc' field of a fact or intent. "
            "`ben doc f001` prints it; `ben doc f001 --set '<text>'` or "
            "`--set-file <path>` writes it; `--edit` opens $EDITOR. "
            "title = human glance, description = one-line gist, doc = full detail."
        ),
    )
    sp.add_argument("id", help="fact or intent id (e.g. f001, i003)")
    sp.add_argument("--set", default=None, help="set the doc body to this text")
    sp.add_argument("--set-file", default=None, help="read the doc body from this file")
    sp.add_argument("--edit", action="store_true", help="open the doc in $EDITOR")
    sp.set_defaults(func=cmd_doc)

    sp = sub.add_parser(
        "recall",
        help="find prior facts/intents similar to <query> (read their doc to reuse)",
        description=(
            "Search title+description of every fact and intent for nodes "
            "similar to the query. The intended flow before starting any new "
            "task: `ben recall '<task gist>'` → scan top hits → "
            "`ben doc <id>` on the most relevant one to read the detailed "
            "context and reuse what was learned. Cheap Unicode/CJK-aware "
            "token overlap + difflib fuzzy fallback; no embeddings."
        ),
    )
    sp.add_argument("query", help="free-text task gist (中文 ok)")
    sp.add_argument("--limit", "-n", type=int, default=5,
                    help="max results (default: 5); must be >= 1")
    sp.add_argument("--kind", choices=["fact", "intent", "any"], default="any",
                    help="restrict to one kind (default: any)")
    sp.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    sp.set_defaults(func=cmd_recall)

    sp = sub.add_parser("claim", help="claim an open intent")
    sp.add_argument("id")
    sp.add_argument("--worker", required=True)
    sp.set_defaults(func=cmd_claim)

    sp = sub.add_parser("release", help="release a claimed intent")
    sp.add_argument("id")
    sp.add_argument("--worker", default=None)
    sp.set_defaults(func=cmd_release)

    sp = sub.add_parser("done", help="conclude an intent with a produced fact")
    sp.add_argument("id")
    sp.add_argument("--fact", required=True, help="the confirmed result text (summary)")
    sp.add_argument("--title", "-t", default=None,
                    help="short human title shown in the graph view (中文标题)")
    sp.add_argument("--kind", "-k", default=None, choices=FACT_KINDS,
                    help="typed fact kind for offensive work")
    sp.add_argument("--data", "-d", default=None, action="append", metavar="KEY=VALUE",
                    help="structured data field (repeatable), e.g. -d cve=CVE-2021-41773")
    sp.add_argument("--doc", default=None,
                    help="detailed document body (markdown). For long text use --doc-file")
    sp.add_argument("--doc-file", default=None,
                    help="read the detailed document from this file path")
    sp.add_argument("--worker", default="agent")
    sp.add_argument(
        "--evidence",
        default=None,
        help="path to report.json from `ben verify --intent` (machine evidence gate)",
    )
    sp.add_argument(
        "--force",
        action="store_true",
        help="bypass evidence gate; records data.forced=true and a hint",
    )
    sp.set_defaults(func=cmd_done)

    sp = sub.add_parser(
        "verify",
        help="run machine checks and write evidence report.json (for `ben done --evidence`)",
    )
    sp.add_argument("--intent", required=True, help="intent id the report is bound to")
    sp.add_argument(
        "--run",
        action="store_true",
        help="also run CLI smoke checks (status/graph/dispatch --help)",
    )
    sp.set_defaults(func=cmd_verify)

    sp = sub.add_parser(
        "probe",
        help="confirm a KB validation signal against a TestRange profile "
             "(not `ben verify --intent`; exit 0/1/2/3)",
    )
    sp.add_argument("profile_id", help="profile id under --profiles (not a bare URL)")
    sp.add_argument("vuln", help="taxonomy.vulns key, e.g. file-write")
    sp.add_argument(
        "--force", action="store_true",
        help="required when profile lacks authorized=true",
    )
    sp.add_argument(
        "--allow-destructive", action="store_true",
        help="permit write/delete/RCE-class actions (file-write needs this)",
    )
    sp.add_argument("--max-requests", type=int, default=20)
    sp.add_argument("--timeout", type=float, default=10.0, help="per-request seconds")
    sp.add_argument("--deadline", type=float, default=120.0, help="total seconds")
    sp.add_argument(
        "--profiles", default=None,
        help="profiles directory (default: tests/TestRange/profiles)",
    )
    sp.add_argument(
        "--root", default=None,
        help="kb root (default BEN_KB_ROOT or package kb/)",
    )
    sp.add_argument(
        "--json", action="store_true", dest="probe_json",
        help="machine-readable verdict JSON",
    )
    sp.set_defaults(func=cmd_probe)

    sp = sub.add_parser("complete", help="mark the project goal satisfied")
    sp.add_argument("--from", dest="from_", required=True, help="facts that justify completion")
    sp.add_argument("--note", default=None)
    sp.add_argument("--worker", default="reason")
    sp.set_defaults(func=cmd_complete)

    sp = sub.add_parser("confirm", help="confirm an intent that required it")
    sp.add_argument("id")
    sp.set_defaults(func=cmd_confirm)

    sp = sub.add_parser("dispatch", help="run a commander/executor step via the claude CLI")
    sp.add_argument("target", help="'reason' | 'verify' | <intent-id>")
    sp.add_argument("--model", default=_config.get("BEN_MODEL"))
    sp.add_argument("--timeout", type=int, default=_config.get_int("BEN_TIMEOUT"))
    sp.add_argument("--templates", default=None, help="templates dir (default: <store>/../templates or SKILL dir)")
    sp.add_argument("--skip-permissions", action="store_true",
                    help="pass --dangerously-skip-permissions to the executor")
    sp.add_argument("--dry-run", action="store_true", help="print the rendered prompt and exit")
    sp.add_argument("--claim", action="store_true", help="(explore) claim the intent first")
    sp.add_argument("--intent", default=None, help="(verify) intent id to verify")
    sp.add_argument("--max-options", type=int, default=4, help="(brainstorm) number of options to generate")
    sp.set_defaults(func=cmd_dispatch)

    sp = sub.add_parser(
        "brainstorm-pick",
        help="pick one brainstorm option, abandon the rest",
        description=(
            "After `ben dispatch brainstorm` proposes multiple options as "
            "requires_confirmation intents, use this to pick the winner. "
            "The picked intent is confirmed; siblings from the same batch "
            "are concluded with a rejection fact."
        ),
    )
    sp.add_argument("id", help="intent id to pick (e.g. i003)")
    sp.set_defaults(func=cmd_brainstorm_pick)

    sp = sub.add_parser(
        "setup",
        help="opt-in THIS project: create .ben/ + register hooks in ./.claude/settings.json",
        description=(
            "Turn the current project into a fact-graph project. Creates the "
            "local graph, registers the SessionStart/UserPromptSubmit hooks in "
            "this project's .claude/settings.json (NOT global), and writes "
            "AGENTS.md. Nothing under ~ is touched."
        ),
    )
    sp.add_argument("--goal", default=None, help="one-line goal (required if no .ben/ yet)")
    sp.add_argument("--origin", default="", help="where this task came from")
    sp.add_argument("--agents", action="store_true", help="also write AGENTS.md")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_setup)

    sp = sub.add_parser(
        "teardown",
        help="remove hooks + AGENTS.md from THIS project (keeps .ben/ unless --purge)",
    )
    sp.add_argument("--purge", action="store_true", help="also delete the .ben/ graph data")
    sp.set_defaults(func=cmd_teardown)

    sp = sub.add_parser(
        "view",
        help="open an interactive HTML visualization of the graph",
        description=(
            "Visualize the fact graph. By default writes a static snapshot "
            "ben-graph.html (graph inlined) and opens it — works from "
            "file:// with no server. With --serve, starts a local HTTP server "
            "that auto-refreshes every 2s as the graph changes."
        ),
    )
    sp.add_argument("--out", default=None, help="output html path (static mode)")
    sp.add_argument("--serve", action="store_true", help="serve a live auto-refreshing page")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8765)
    sp.add_argument("--print", action="store_true", help="print the static html to stdout")
    sp.set_defaults(func=cmd_view)


    sp = sub.add_parser(
        "flag", help="record a captured flag (dedupe; optionally submit via arena)"
    )
    sp.add_argument("value", help="the flag string, e.g. flag{...}")
    sp.add_argument("--challenge", "-c", default=None, help="challenge id on the platform")
    sp.add_argument("--submit", action="store_true",
                    help="also submit via the arena API (requires .ben/arena.json)")
    sp.add_argument("--title", "-t", default=None)
    sp.add_argument("--creator", default="user")
    sp.set_defaults(func=cmd_flag)

    sp = sub.add_parser(
        "arena", help="competition platform bridge (TSecBench-style API)"
    )
    sp.add_argument(
        "action", choices=["init", "challenges", "start", "stop", "submit", "hint"],
        help="init: write .ben/arena.json template; others call the platform API",
    )
    sp.add_argument("challenge_id", nargs="?", default=None, help="challenge id")
    sp.add_argument("--flag", default=None, help="flag value (for submit)")
    sp.set_defaults(func=cmd_arena)

    sp = sub.add_parser(
        "kb", help="shared offline knowledge base (techniques / CVEs / writeups)"
    )
    sp.add_argument(
        "action",
        choices=["add", "search", "show", "list", "import", "root", "check", "diagnose"],
        help="add/search/show/list/import/root; check: knowledge reachability; "
             "diagnose: naming vs content gap (exit 0/1/2/3 — see --help notes)",
    )
    sp.add_argument(
        "target", nargs="?", default=None,
        help="title (add) | kb id (show) | query (search/check/diagnose) | path (import)",
    )
    sp.add_argument("--description", "-d", default=None, help="one-line summary")
    sp.add_argument("--detail", default=None, help="markdown body")
    sp.add_argument("--detail-file", default=None, help="read markdown body from file")
    sp.add_argument("--tag", "-t", default=None, action="append",
                    help="tag (repeatable), e.g. -t web -t sqli")
    sp.add_argument("--command", "-c", default=None, action="append",
                    help="example command (repeatable)")
    sp.add_argument("--source", default=None, help="where this came from (URL/book)")
    sp.add_argument("--path", default=None, help="file or dir of .md files (for import)")
    sp.add_argument("--root", default=None,
                    help="kb root dir (default BEN_KB_ROOT or the repo's kb/)")
    sp.add_argument("--limit", "-n", type=int, default=5)
    sp.add_argument(
        "--only", action="append", default=None,
        help="limit to kb id(s); repeatable or comma-separated "
             "(required for check/diagnose; optional for search)",
    )
    sp.add_argument(
        "--variants", default=None,
        help="diagnose: comma-separated query variants (overrides taxonomy)",
    )
    sp.add_argument(
        "--variants-file", default=None,
        help="diagnose: file with one variant per line",
    )
    sp.add_argument(
        "--show-tokens", action="store_true",
        help="check: print core/qualifier token split",
    )
    sp.add_argument(
        "--json", action="store_true", dest="kb_json",
        help="check/diagnose: machine-readable JSON on stdout",
    )
    sp.set_defaults(func=cmd_kb)

    sp = sub.add_parser(
        "bench",
        help="drive TSecBench end-to-end: list->start->solve->submit->close per challenge",
    )
    sp.add_argument("--root", default=paths.runtime_name(), help="per-challenge graph root")
    sp.add_argument("--minutes", type=int, default=None, help="global budget (minutes)")
    sp.add_argument("--deadline", default=None, help="global stop time, ISO 8601 local")
    sp.add_argument("--minutes-per-challenge", type=int, default=25,
                    help="auto budget per challenge per round")
    sp.add_argument("--max-steps", type=int, default=10)
    sp.add_argument("--round-gap-seconds", type=int, default=20,
                    help="pause between rounds so a fast-failing loop cannot hammer the platform")
    sp.add_argument("--parallel", type=int, default=1,
                    help="run this many per-challenge workers concurrently (hosted night rate: high concurrency is free; platform active-container cap is honored automatically)")
    sp.add_argument("--poll-seconds", type=int, default=5,
                    help="worker reaping poll interval in parallel mode")
    sp.add_argument("--model", default=_config.get("BEN_MODEL"))
    sp.add_argument("--templates", default=None)
    sp.add_argument("--skip-permissions", action="store_true")
    sp.add_argument("--verify", action="store_true")
    sp.set_defaults(func=cmd_bench)

    sp = sub.add_parser(
        "command",
        help="field commander: LLM allocates the next work slice across challenge graphs",
    )
    sp.add_argument("--root", default=paths.runtime_name(), help="directory holding one subdir per challenge")
    sp.add_argument("--minutes", type=int, default=None,
                    help="global budget in minutes (the match slot clock)")
    sp.add_argument("--deadline", default=None,
                    help="global stop time, ISO 8601 local (e.g. 2026-10-17T13:00:00)")
    sp.add_argument("--minutes-default", type=int, default=20,
                    help="slice size when the model gives none / fallback")
    sp.add_argument("--minutes-max", type=int, default=40, help="cap on a single slice")
    sp.add_argument("--fleet-file", default=None,
                    help="fleet.json to read the session/root for hire/fire")
    sp.add_argument("--poll-seconds", type=int, default=30,
                    help="settle time after hire/fire before the next decision")
    sp.add_argument("--model", default=_config.get("BEN_MODEL"))
    sp.add_argument("--timeout", type=int, default=_config.get_int("BEN_TIMEOUT"))
    sp.add_argument("--templates", default=None)
    sp.add_argument("--skip-permissions", action="store_true")
    sp.add_argument("--verify", action="store_true")
    sp.add_argument("--max-steps", type=int, default=8)
    sp.set_defaults(func=cmd_command)

    sp = sub.add_parser(
        "fleet", help="launch/stop the whole formation as processes (match-day)"
    )
    sp.add_argument("action", choices=["init", "up", "down", "status", "hire", "fire", "workers"])
    sp.add_argument("--file", default=FLEET_FILE, help="fleet config path")
    sp.add_argument("--target", default=None, help="challenge name (for hire/fire)")
    sp.add_argument("--minutes", type=int, default=None, help="worker budget (for hire)")
    sp.add_argument("--max-steps", type=int, default=None, help="worker max steps (for hire)")
    sp.add_argument("--extra-args", default=None, help="extra args passed to the hired auto run")
    sp.set_defaults(func=cmd_fleet)

    sp = sub.add_parser(
        "sweep",
        help="round-robin `auto` across per-challenge graphs (<root>/<name>/.ben)",
    )
    sp.add_argument("--root", default=paths.runtime_name(), help="directory holding one subdir per challenge")
    sp.add_argument("--minutes", type=int, default=None,
                    help="global budget in minutes (the match slot clock)")
    sp.add_argument("--deadline", default=None,
                    help="global stop time, ISO 8601 local (e.g. 2026-10-17T13:00:00)")
    sp.add_argument("--minutes-per", type=int, default=20,
                    help="minutes of work per challenge per round")
    sp.add_argument("--model", default=_config.get("BEN_MODEL"))
    sp.add_argument("--templates", default=None)
    sp.add_argument("--skip-permissions", action="store_true")
    sp.add_argument("--verify", action="store_true")
    sp.add_argument("--max-steps", type=int, default=8)
    sp.set_defaults(func=cmd_sweep)

    sp = sub.add_parser(
        "config",
        help="show effective configuration (env + .env + defaults) or validate it",
        description=(
            "Centralized configuration report. Every ben config item is an "
            "environment variable; values may also live in a .env file "
            "(real env vars win, then .env, then the documented default). "
            "`ben config` prints the effective values (secrets masked); "
            "`ben config --check` validates and exits non-zero on problems."
        ),
    )
    sp.add_argument("--check", action="store_true",
                    help="validate types/required keys; exit 1 on problems")
    sp.add_argument("--json", action="store_true", help="machine-readable output")
    sp.set_defaults(func=cmd_config)

    sp = sub.add_parser(
        "auto", help="drive the whole graph forward: reason -> explore -> verify -> repeat"
    )
    sp.add_argument("--model", default=_config.get("BEN_MODEL"))
    sp.add_argument("--timeout", type=int, default=_config.get_int("BEN_TIMEOUT"))
    sp.add_argument("--templates", default=None)
    sp.add_argument("--skip-permissions", action="store_true")
    sp.add_argument("--dry-run", action="store_true", help="reason only, no explore")
    sp.add_argument("--verify", action="store_true", help="verify each explore result")
    sp.add_argument("--max-steps", type=int, default=8, help="max reason iterations")
    sp.add_argument("--max-explore", type=int, default=6, help="cap on explore dispatches")
    sp.add_argument("--minutes", type=int, default=None,
                    help="stop after this many minutes (match slot budget)")
    sp.add_argument("--deadline", default=None,
                    help="stop at this ISO 8601 local time (e.g. 2026-10-17T13:00:00)")
    sp.set_defaults(func=cmd_auto)

    return p


_GLOBAL_VALUE_FLAGS = ("--store", "--engine")


def _hoist_global_flags(argv: list[str]) -> list[str]:
    """Allow global options to be written after the subcommand.

    ``--store`` / ``--engine`` are defined on the top-level parser, so
    ``ben --store X view`` works but ``ben view --store X`` (the spelling the
    docs use) is rejected by argparse.  Move them in front of the subcommand
    so both orders behave the same; subcommand-specific options are untouched.
    """
    head: list[str] = []
    rest: list[str] = []
    i = 0
    while i < len(argv):
        tok = argv[i]
        matched = next(
            (f for f in _GLOBAL_VALUE_FLAGS if tok == f or tok.startswith(f + "=")),
            None,
        )
        if matched and tok == matched:
            head.append(tok)
            if i + 1 < len(argv):
                head.append(argv[i + 1])
                i += 2
                continue
        elif matched:
            head.append(tok)
        else:
            rest.append(tok)
        i += 1
    return head + rest


def main(argv: list[str] | None = None) -> int:
    # load ./.env (or BEN_ENV_FILE / repo-root .env) before anything reads the
    # environment — argparse defaults below already see .env values.
    _config.load_dotenv()
    argv = _hoist_global_flags(list(sys.argv[1:] if argv is None else argv))
    try:
        args = build_parser().parse_args(argv)
    except FGError as exc:
        sys.stderr.write(f"ben: {exc}\n")
        return 1
    if getattr(args, "engine", None):
        os.environ["BEN_ENGINE"] = args.engine
    # patch templates default post-hoc (depends on store)
    if getattr(args, "templates", None) is None and getattr(args, "func", None) in (cmd_dispatch, cmd_auto):
        args.templates = str(_resolve_templates_dir(args))
    try:
        return args.func(args)
    except FGError as exc:
        sys.stderr.write(f"ben: {exc}\n")
        return 1
    except BrokenPipeError:
        return 0
