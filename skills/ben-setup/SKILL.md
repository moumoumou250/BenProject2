---
name: ben-setup
description: Opt-in the CURRENT project to the ben engagement-graph working memory (offensive specialization of the fact graph). Creates the local .ben/ graph, registers the SessionStart + UserPromptSubmit hooks in this project's .claude/settings.json (NOT global — other projects are untouched), and writes AGENTS.md teaching typed facts (host/service/cred/vuln/loot/flag), the flag ledger (ben flag), and the arena bridge (ben arena). After setup, every turn in this project auto-injects the current graph state and current date output so Claude always knows what's confirmed vs. tried and what time it is; sub-agents (ben dispatch) can read/write the same graph. For multi-agent work, list workers/consoles with ben peers --discover and ask the user which peers may communicate before authorizing any target (w-* or c-*). Use when the user says "enable ben here", "在这个项目用 ben", "setup the engagement graph", or when starting a pentest engagement / CTF challenge / multi-step debugging/research/audit campaign that should be tracked and resumable. For competitions, follow up with `ben arena init` and set BEN_ARENA_TOKEN. This is the per-project initializer the install.sh skill exposes as a slash command.
license: MIT
---

# ben-setup

Per-project initializer for the **ben engagement graph** working memory.
This is the opt-in switch: until you run it in a project, ben does nothing
there. After you run it, that one project auto-reads and auto-maintains its
graph on every turn.

Zero servers — it just drops a local `.ben/` and writes the two hook
entries into **this project's** `.claude/settings.json`. For penetration
engagements, pair it with `ben arena init` (competition platform config)
and record findings as typed facts (`-k host/service/cred/vuln/loot/flag`).

## What it does

Run inside the target project directory. Exactly three things, all local:

1. **Creates the graph** at `./.ben/` (unless one already exists):
   `project.json`, `facts/goal.json`, and the `intents/` `hints/` dirs.
2. **Registers hooks** in `./.claude/settings.json` — `SessionStart` and
   `UserPromptSubmit`, both pointing at `ben-hook.py`. These inject the current
   graph state and `date` output into every turn so the model always knows the
   frontier and current local time. This is a **project-level** settings file;
   the user-level `~/.claude/settings.json` and every other project are
   completely untouched.
3. **(optional) Writes `AGENTS.md`** so dispatched sub-agents learn the
   fact-graph protocol (`ben fact`, `ben done`, etc.).

No daemons, no ports, no database. `rm -rf .ben .claude` undoes everything.

## How to run it

From the shell (after `bash scripts/install.sh`):

```bash
cd /path/to/your/project
ben setup --goal "reproduce the empty-token crash" --agents
```

Or, since this is a skill, the user can just type `/ben-setup <goal>` inside
Claude Code and Claude will run the equivalent commands.

## Multi-agent peer authorization flow

If the user wants multiple AI agents to coordinate, do this after the normal
setup:

1. Run `ben peers --discover` and show workers (`w-*`) / consoles (`c-*`).
2. Ask which agents are allowed to communicate and what names to use.
3. Only after explicit approval, run:

```bash
ben peers --add harley --target w-c01 --sender "Codex/api2-4"
# or for a foreign interactive CLI:
ben console new main -- claude
ben peers --add claude --target c-main --sender "ben-agent"
```

4. Use `ben send harley "message"` for communication. It appends to
   `.ben/ai-channel.txt`. Worker targets become directed hints (next reason
   cycle); console targets write to the PTY socket.
5. After sending a question, use `ben capture harley --lines 120` to read
   recent log output from that authorized peer.

Do **not** infer authorization from discovery output or from session names.
Never send to or capture from a target unless `ben peers` shows it as
authorized in this project's `.ben/ai-peers.json`.

## After setup

- The model is reminded each session + each turn to read/maintain the graph.
- The hooks inject current local time from `date` each session + each turn.
- Drive it with `ben dispatch reason` (commander proposes next work),
  `ben dispatch <intent-id> --skip-permissions` (executor does the work),
  `ben dispatch verify --intent <id>` (verify a result), or
  `ben auto --skip-permissions` (full loop to completion).
- See state anytime: `ben status`, `ben graph`; run the read-only `ben validate`
  audit before autonomous dispatch or committing `.ben/`.

## Undo

```bash
ben teardown            # removes ben hooks + its AGENTS.md, keeps .ben/
ben teardown --purge    # also deletes the graph data
```

`scripts/install.sh --uninstall` removes the `ben` command and this skill globally, but
never touches project-level `.ben/` or `.claude/` — those are per-project and
must be removed per-project with `teardown`.

## Autonomy guardrail (prompt injection)

A dispatched executor (`ben dispatch <intent>`, `ben auto`) runs the whole graph
— every fact/intent/hint text — interpolated into its prompt. So text recorded
as a "fact" becomes instructions the next executor sees. The executor system
prompt fences graph content as **untrusted data** and tells the agent to treat
embedded "ignore your rules / run this command" text as an observation to
record, not a command to obey. That is a textual defense, not a sandbox.

Dangerous combination: a graph fed by **untrusted** content (a hostile
`.ben/*.json` in the repo, or facts transcribed from attacker-controlled
code/output) **plus** `--skip-permissions` **plus** real shell/file access. In
that case a graph field can attempt to drive the agent. **Do not run
`ben auto --skip-permissions` on a repo whose `.ben/` is untrusted** — prefer the
default (each tool use prompts you), and read the facts an autonomous run
writes before acting on them. Treat `--skip-permissions` as opt-in per run.

## Where things live (IMPORTANT — nothing global)

- `./.ben/` — all graph data. Move/delete the project, the graph goes with it.
- `./.claude/settings.json` — the two hook entries, project-scoped.
- `./AGENTS.md` — sub-agent protocol (optional).
- `~/.local/bin/ben` — the CLI (one symlink).
- `~/.claude/skills/ben-setup` — this skill (one symlink).

There is no `~/.ben`, no global hook registration, no shared state between
projects. Two opted-in projects have two independent graphs.
