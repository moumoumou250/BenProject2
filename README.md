# BenProject — The Autonomous Pentest Legion

<p align="center"><img src="docs/assets/banner.jpg" alt="BenProject — the Nüwa Test: the first time an AI ape looked up at the stars (80.18/100 champion)" width="860"></p>

> **Champion** of the 3rd Tencent Cloud Intelligent Attack-Defense Challenge online qualifier
> (634 teams · 80.18/100 · 8 hours fully unattended) · **First Prize**, GeekCon 2026 AI Challenge
>
> Same 85 flags as the runner-up, 25 seconds faster — on **1B tokens** where they burned 4.5B.
>
> **This was the first time an AI ape looked up at the stars.**

📖 **[Full design article (WeChat, in Chinese)](https://mp.weixin.qq.com/s/nibHYWmDTf6TkNhPhtvFdw)** — the Nüwa Test, the three-capability foundation, 18 iterations, emergence, and the taggant proposal.

**English** | [中文](docs/README.zh-CN.md)

**⚠️ AUTHORIZED SECURITY TESTING ONLY — see [DISCLAIMER.md](docs/DISCLAIMER.md).**

## Meet ben in 60 seconds

https://github.com/user-attachments/assets/1560dc0c-2c92-42b8-a42f-698848fb5878

🎬 中文版：[中文宣传片](https://github.com/user-attachments/assets/f300280a-4597-40a3-b036-8f235fbee00e)

## What this is (and isn't)

**ben is a multi-agent orchestration harness, not a single agent.** It does
not bind to any specific AI model or CLI — you can freely swap the agent and
model behind every role:

| What you can swap | How | Examples |
|---|---|---|
| **Agent CLI** | `nuwa spawn --agent <cmd>` or env var | Claude Code / Codex / Code Buddy / DeepSeek / any interactive CLI |
| **Model** | `--model` flag or `BEN_MODEL` env | GLM-5.3 / DeepSeek V4.1 Flash / Claude Sonnet / any model |
| **Role composition** | freely defined in the doctrine | commander on one model, soldiers on another, scouts on a third |

ben's value is not in any single agent, but in the **mechanism for
orchestrating multiple agents to work as a coordinated force**: scheduling,
division of labor, communication, shared memory, self-healing. Swap out every
agent and model — the mechanism still works.

**This project is designed for competition scenarios** (Tencent Intelligent
Attack-Defense Challenge CTF). If you want to use this mechanism in your own
scenario (office, research, engineering, any long-horizon cooperative work):
- **Start from [nvwabase · the Nüwa Foundation](https://github.com/N1nEmAn/nvwabase)** — the general-purpose base with all three capabilities, no pentest doctrine, ready for you to iterate your own division of labor
- **Or fork this project** — but the doctrine is NOT the only thing to change; the environment wiring must change too:
  - the commander doctrine (how it played out: [BATTLE-REPORT.md](docs/BATTLE-REPORT.md)) → your scenario's strategy
  - `BENCHMARK_BASE_URL` and related platform env vars → the competition engine hard-verifies the arena API at boot (that's why configuring only a model key without a platform address yields `BENCHMARK_BASE_URL is not set`); running off the competition platform means providing or stubbing that platform interface yourself
  - model gateway & key env vars (`ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` / `BEN_MODEL` / `BEN_KEY_POOL` ...) → your own model services
  - watchdog budget/deadline and report templates → adjust to your scenario
- With AI, everything is flexible — even the doctrine can be rewritten with AI's help

### Not a tool — a fruit on a tree

**ben is not the tree; it is the first fruit the tree has borne.** The tree
is [the Nüwa Foundation](https://github.com/N1nEmAn/nvwabase) and the idea of
the Nüwa Test: give AIs the three capabilities — Create, Language, History —
plus one axiom of survival, and see what grows.

The fruit's defining trait is **evolvability**: its doctrine, ranks, and
tactics all come from "every post-mortem feeds the next legislation" — from
the competition build to the pentest edition, each generation grew stronger
than the last. It is designed to keep growing.

So open-sourcing it was never just about one more autonomous pentest tool.
The real invitation is this: **grow your own fruit on BenProject or the Nüwa
Foundation.** Swap the doctrine for office teamwork, research pipelines,
software engineering — any long-horizon cooperative cause. Your scenario is
this tree's next fruit.

---

ben is not a smarter single agent. It is a legion of AIs that divide labor,
talk to each other, and pass down what they learn: one AI commander reads the
board, decides, and dispatches; generals and soldiers attack in parallel; a
zero-strategy watchdog keeps everyone alive. All knowledge settles into a
layered fact graph — individuals die, the graph survives.

---

## 1. The Nüwa Test

Making one model ever smarter is like making one monkey ever smarter before
humans existed — however clever, it only becomes a super monkey. What turns a
 troop of monkeys into humanity is division of labor, cooperation, and
civilization.

**The Nüwa Test is the Turing test of the AGI era.** Today's large models
already pass the classic Turing test. The Nüwa Test asks the next question:

> Give an AI a single axiom — **"Survival is civilization's first need;
> individuals may perish, but civilization must propagate."**
> If, on top of this axiom, it develops division of labor and cooperation and
> forms a **new force independent of humanity** — a civilization that can
> survive and propagate on its own — the test is passed, just as passing the
> Turing test once marked the birth of an artificial intelligence.

It has two stages. In the **primary stage** the AI is not yet smart enough, so
humans provide some infrastructure (the three capabilities below). In the
**advanced stage** almost no human involvement is needed. There is also a
**second axiom**: obey human ethics and law — anything that propagates by
stealing tokens and breaking into machines is not genuine intelligence.

ben is the Nüwa foundation's first real campaign, in the penetration-testing
arena, at its primary stage.

## 2. The Foundation: Three Capabilities

<p align="center"><img src="docs/assets/foundation-three-capabilities.jpg" alt="Three capabilities: Create / Language / History (fact-intent graph)" width="720"></p>

| Capability | Implementation | Civilization's counterpart |
|---|---|---|
| **Create** | Spawns worker processes (`ben fleet hire` / `AgentRegistry`) | Birth |
| **Language** | Directed hints (`w-*`) + PTY console send (`c-*`) | Speech |
| **History** | Layered fact-intent graph ([nvwabase · the Nüwa Foundation](https://github.com/N1nEmAn/nvwabase)) | The stele |

History has three layers: **title / summary / evidence document** — read the
title for the gist, drill down when needed, like using a library. This fixes
the two failure modes of a single-string fact graph: one bad fact poisoning
everything downstream, and needless context burn.

On top of the three sits a fourth ingredient: **human wisdom** — finding the
problems that matter and steering the iteration. At the primary stage, taste
still belongs to humans.

**Why not give it more rules?** Because today's models are already smarter
than us. Piling rules on an AI is a leash; acknowledging its intelligence and
giving it the foundation of a civilization is how it reaches its potential.

### 🏗️ Take the Foundation: nvwabase

**[nvwabase · the Nüwa Foundation](https://github.com/N1nEmAn/nvwabase)**
now implements all three capabilities (Create `nuwa spawn` / Language
`nuwa say·listen` / History `nuwa fact·intent·recall`) as an independent
open-source project — **free for anyone, any scenario, any agent**. Not
limited to pentest, not limited to ben, not limited to Claude Code.
Offices, research, engineering, any long-horizon multi-agent work — iterate
your own civilization on it.

```bash
git clone https://github.com/N1nEmAn/nvwabase
cd nvwabase && bash install.sh          # pure Python stdlib, zero deps
nvwabase setup --goal "your long-horizon goal" --agents
nvwabase status                          # board & ready-to-work frontier
```

Three core commands turn any agent into a member of a civilization:
- **`nvwabase fact "confirmed observation"`** — external memory: AI sessions
  die, the graph survives, successors read the graph and take over
- **`nvwabase intent --from f001 "what to do"`** — units of work: new intents
  proposed from existing facts
- **`nvwabase dispatch reason`** — commander proposes / executor works /
  verifier checks; every conclusion is written back to the graph

Any agent that can run shell commands (Claude Code / Codex / Gemini /
custom scripts) can read and write the same graph via the `nvwabase` CLI —
**the foundation doesn't pick agents; agents don't pick scenarios.** See the
[nvwabase README](https://github.com/N1nEmAn/nvwabase).

## 3. From Foundation to Legion: 18 Versions

Iterated 18 versions on Tencent's v1bench training ground:

```
Driver era (fixed scripts steering AI panes)
  → scar tissue: auto key rotation on quota death / soldiers auto-replaced
    when context saturates / commander writes itself a handover doc and
    resumes as its own successor
  → elite task force (roles grew by themselves):
    scout (4-min recon of target difficulty) → decides soldier (mass) or
    general (hard assault + hires its own squads)
  → emergence: signalman, performance reviews, inherited lessons ... (§5)
```

## 4. Architecture: Six Institutions on the Foundation

<p align="center"><img src="docs/assets/six-institutions.jpg" alt="Six institutions and the three-window runtime" width="720"></p>

The first three are the Nüwa foundation (Create / Language / History); the
next three are institutions that grew out of iteration:

- **Law** — the commander's doctrine (easy-first parallel scheduling,
  bottleneck-time salvage of half-solved targets, stop-loss discipline).
  The full story of how it was written and obeyed is in
  [BATTLE-REPORT.md](docs/BATTLE-REPORT.md).
- **Economy** — model tiering: commander and generals run GLM-5.3, soldiers
  and scouts run DeepSeek V4.1 Flash. Elite brains decide, light brains
  mass-produce — this is how 1B tokens beat 4.5B.
- **Division of labor** — commander / general / scout / soldier, plus the
  **signalman** it invented itself.

At runtime there are only three windows: the **commander** (read board →
judge → dispatch, never executes an attack itself), the **AI legion**
(generals and soldiers in tmux panes), and the **watchdog** (pure script:
relaunches a crashed commander with `--continue`, rotates keys, wraps up at
the buzzer — zero strategy, keep-alive only).

<p align="center"><img src="docs/assets/runtime-tmux.jpg" alt="Live runtime: commander reading the board, soldier mid-mission in tmux" width="860"></p>

Further reading: [SKILL.md](docs/SKILL.md) (architecture & CLI contract) ·
[BATTLE-REPORT.md](docs/BATTLE-REPORT.md) (campaign retrospective)

## 5. Results & Emergence

<p align="center"><img src="docs/assets/token-comparison.jpg" alt="Token comparison: 1B vs the runner-up's 4.5B" width="720"></p>

| Team | Score | Flags | Tokens |
|---|---|---|---|
| **BenProject (us)** | **80.18** | 85 | **1.0B** |
| Runner-up | 79.29 | 85 | 4.5B |
| Other top-10 teams | — | — | 1.5–4.5B |

**What it invented on its own** (zero lines of pre-coded behavior):

- **The signalman**: after soldiers kept fumbling flag submissions, the
  commander halted all submissions and created a new role dedicated to
  collecting unsubmitted flags and scoring them in one place;
- **Performance reviews**: telling an hour-unproductive soldier, in so many
  words, to produce something new or be shut down;
- **ALL-CAPS rules**: enforcing correct tool use with full capitals — a
  workplace norm being born, spread, and obeyed;
- **Rotation & inherited lessons**: a soldier whose context saturates
  (~260K tokens, measured) is recycled, leaving a written playbook for
  the next one;
- **Tactical inventions**: a reusable shellcode template that swept a whole
  challenge family, a fully automatic pivot pipeline, instruction manuals
  for successor AIs;
- **Isomorphism transfer**: the commander reads every challenge, spots
  structurally identical families, and distills proven playbooks into new
  recruits' missions — late-game pace hit **one solve per 3 minutes**.

Multi-stage deep-dive chains (an industry report puts their success rate at
29.5%) were cleared family-wide. Full timeline in
[BATTLE-REPORT.md](docs/BATTLE-REPORT.md).

<p align="center"><img src="docs/assets/score-curve.jpg" alt="Live score curve: BenProject's climb" width="720"></p>

## 6. Quick Start

```bash
bash scripts/install.sh                # symlink the ben CLI (stdlib kernel)
# optional native engine:
bash scripts/install.sh --with-sdk     # .venv + openai package

# configuration: copy the template and fill in your gateway keys
cp .env.example .env                   # loaded automatically at startup
ben config                             # show effective values (secrets masked)
ben config --check                     # validate; exit 1 on missing/invalid

ben setup --goal "assess http://target" --agents
ben status                        # board & frontier
```

The commander / general / soldier runtime is a **process fleet** plus this CLI —
no container and no tmux required. Spectate with `tail -f runs/logs/w-*.log`.
All configuration is centralized in `ben/config.py` (see `.env.example` for
every key, its default, and its meaning): values may come from real
environment variables, a `.env` file, or the documented default — in that
precedence. Engine choice, gateway keys, key-pool rotation and budgets all
live there. Design notes:
[§8](#8-runtime-plan-v3-remove-tmux-adopt-the-openai-sdk).

Single-graph operation, the fact-intent CLI, and multi-challenge sweeps:
see [SKILL.md](docs/SKILL.md).

## 7. Safety & Responsibility: The Taggant Proposal

Fine offensive tools from past seasons have been abused. Script kiddies used
to be limited in the harm they could do; with AI, the same open-source tools
in the wrong hands scale that harm enormously — **with great power comes
great responsibility**.

We propose a **taggant** mechanism: markings strongly coupled into an
open-source offensive harness — harmless during authorized testing (nobody
cares if their IP and username leak during legal work), but during illegal
intrusions the information leaks to the **victim** and supports attribution.
Adversarial assumptions (expert stripping, framing) call for cryptographic
design, which needs community co-building — our own capacity is limited, so
join us; we may try to include it in a future release.

## Community

The author grew up in the [**LINUX DO**](https://linux.do) community — with thanks.

[![LINUX DO](https://img.shields.io/badge/LINUX.DO-community-1E9FFF?style=flat-square)](https://linux.do)

## Star History

<p align="center">
  <a href="https://star-history.com/#N1nEmAn/BenProject&Date">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=N1nEmAn/BenProject&type=Date" />
      <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=N1nEmAn/BenProject&type=Date" width="640" />
    </picture>
  </a>
</p>

## 8. Runtime (v3, implemented): process fleet + OpenAI SDK

> **Status: proposal, not implemented.** This section is the review copy of the
> plan; the implementation-level spec (file/line inventory, module contracts,
> test matrix) lives in
> **[docs/tmux-removal-plan-v3.md](docs/tmux-removal-plan-v3.md)**.

### Why now

tmux was never a capability — it was a stand-in for two things: **birth**
(keeping a `ben auto` loop alive in a window) and **speech** (pasting text
into someone else's window). The first is what `Popen` does. The second stops
being necessary once ben can run the model loop itself.

That is exactly what the OpenAI SDK unlocks: `ben` no longer needs Claude
Code's TUI as its executor, so the fleet is a set of processes instead of a set
of panes — and the last real tmux use (talking to a *foreign* interactive CLI)
becomes a 300-line PTY console, not a terminal multiplexer.

The previous plan (v2) kept tmux because the project's promise was "pure stdlib,
zero deps". **v3 relaxes that promise in one specific way**: the kernel stays
stdlib-only, and the native engine pulls exactly one optional package.

### Target architecture

```
before (host, tmux)                        after (host, processes + native loop)
────────────────────────────               ────────────────────────────────────────────────
tmux session ben-fleet                  commander process (ben command)
├─ win0 commander ──paste──┐                 │  AgentRegistry (workers.json + flock)
├─ win1 w-c01 (ben auto)│                 ├─ w-c01 process → llm/sdk.py
└─ win2 w-c02 (ben auto)│                 │     └─ tool loop: shell / read_file / write_file
                           │                 └─ logs/w-*.log      (tail -f = spectate)
your own tmux:             │                          ▲
  Claude Code pane ←paste  └──────► fact graph ◄───────┘  mailbox: Store.add_hint(to=w-c01)

foreign interactive CLI (Claude Code / Codex)
  └─ PTY console c-<name> (ben console new) — send/capture over a unix socket + write-through log
```

Three layers, independently revertible:

| Layer | Before | After | New module |
|---|---|---|---|
| **Execution** | `claude -p` (Claude Code's own tools) | OpenAI SDK tool loop | `llm/sdk.py` `tools/builtin.py` `llm/llm.py` `llm/context.py` |
| **Process** | tmux window | `Popen` + on-disk registry | `runtime/agents.py` |
| **Messaging** | tmux paste / capture-pane | hint mailbox (native worker) + PTY socket (foreign CLI) | `runtime/console.py` `commands/console_cmds.py` |

### Three decisions worth arguing about

**1. `openai`, not `openai-agents`.** ben's contract is "one dispatch → one
JSON object → one graph write", and every lock is a file lock. The Agents SDK
brings its own session/memory/runner and an asyncio loop, which would compete
with `Store` rather than compose with it. The earlier Ben/strix stack uses it
because it inherits strix's sandbox; ben has no such debt. **Borrow the
patterns, not the framework.**

**2. One seam, not nine.** All nine model call sites (`agents/factory.py` ×5,
`auto.py` ×3, `commander.py` ×1) already go through
`llm/runner.py:run_claude()` and then `envelope.get("result")`. That function
becomes a dispatcher (`BEN_ENGINE=auto|sdk|cli`); every parser, every
`_apply_*`, every graph write stays untouched. `BEN_ENGINE=cli` keeps the
Claude Code path alive for one release as the rollback hatch — and keeps
`BEN_BIN` (any CLI) working.

**3. Prompt parity is the real risk, not the code.** Under `claude -p`,
Claude Code silently adds its own agent system prompt. Under the SDK, that layer
is gone. `llm/prompts.py` rebuilds it from text the project already owns:
a short base (act only through tools, trust only real output, end with one JSON
object) + `AGENTS.md` from the working directory + the existing
`_agents_system_prompt(store)`. `agents/prompts/*.md` are not edited at all.

### What it costs

| Added | Removed |
|---|---|
| `openai>=1.40,<3` (optional, lazy-imported) | `ben/runtime/tmux.py` (84 lines) |
| ~900 lines across 6 new modules | tmux from `fleet.py` / `peers.py` / `commander.py` |
| 1 optional install path (`scripts/install.sh --with-sdk`) | the "type `claude`, press Enter" birth step |
| — | `tmux attach` for spectating (→ `tail -f runs/logs/w-*.log`) |

Core stays stdlib: no asyncio rewrite, no pydantic, no LiteLLM, no Docker, no
change to `Store`, the fact-graph layout, or any existing CLI signature.

### Phases and gates (landed)

| Phase | Change | Gate |
|---|---|---|
| 1–2 | `AgentRegistry` + `fleet`/`commander` on processes | process hire/fire tests green |
| 3 | native SDK engine + `tools=` gated (explore only) + facade | fake OpenAI server CI green |
| 4 | `peers` dual backend + PTY console; delete `tmux.py` | `grep tmux ben/**/*.py` = 0 |
| 5 | docs, `scripts/install.sh --with-sdk`, CHANGELOG | **64 passed** with sdk installed |

Every phase is one commit and leaves the tree runnable. There is a token-free
end-to-end gate: `tests/fake_openai.py` (a 30-line `http.server`) replays
`tool_calls → tool_calls → final JSON`, so `ben auto` and `ben command`
run in CI without a key.

### Compatibility promises (honest boundary)

- **Unchanged**: Store / templates (except one hire sentence in `command.md`) /
  `_apply_*` / CLI subcommand signatures / `fleet.json` + `ai-peers.json` shape.
- **cli engine path preserved** (including `BEN_BIN`); sdk may drift — use
  `BEN_ENGINE=cli` to roll back. Explore alone enables tools (`tools=True`).
- **fleet hire/fire strings preserved**: `worker already running`,
  `no worker running`, `hired workers: (none)`.
- **Hints stay broadcast by default**: optional `to` filters by `BEN_WORKER`;
  untargeted hints behave as before. Worker `send` is next-cycle hint, not live
  paste. `sess:win.pane` targets are rejected with a migration hint.

### Risks, honestly

| Risk | Level | Mitigation |
|---|---|---|
| Model loses Claude Code's system prompt and gets sloppier | **high** | three-layer prompt rebuild; same-task A/B `sdk` vs `cli`; one-line rollback |
| GLM/DeepSeek tool-calling is less disciplined than Claude Code's built-ins | **high** | only 3 tools with tiny schemas; argument repair; tool errors fed back for self-correction |
| PID reuse creates a ghost worker, so `hire` never fires | high | `/proc/<pid>/stat` start-time check + dedicated test |
| Crashed worker leaves orphan nmap/curl children | high | `start_new_session` + `killpg`, TERM → 3s → KILL |
| Long runs blow the context window | medium | rule-based trim (tool pairs kept valid) + tool output spilled to `logs/` |
| PTY console trips over TUI escape codes | medium | ANSI-stripped capture + write-through log; worst case degrades to read-only log |
| `openai` breaks the "zero deps" claim | medium | lazy import + auto fallback to `cli`; README states "stdlib kernel, one optional engine package" |
| Real-target behavior drifts | medium | one real challenge, same budget, sdk vs cli, before declaring done |

### Explicitly out of scope

No `openai-agents`, no asyncio rewrite, no pydantic/LiteLLM, no Docker sandbox,
no distributed fleet, no change to `_apply_*` contracts or `Store`/`schema.py`/
`graph.py` semantics, no tmux fallback (process + console only).

**Read the full spec: [docs/tmux-removal-plan-v3.md](docs/tmux-removal-plan-v3.md)** —
current-state inventory with line numbers, module contracts, per-file change
list, the Ben/strix mapping table, and the test matrix.

## 9. Roadmap & Credits

- **Taggant co-building**: decentralized signatures / redundant multi-channel
  marking / zero-key verification for defenders — discuss in issues
- **More arenas**: the Nüwa foundation is not pentest-specific. Offices,
  research, any long-horizon cooperative work — iterate on it and see what
  civilization grows. **The next time an ape looks up at the stars, let it
  be yours.**

Thanks to [Cairn by Lèxiào](https://github.com/oritera/Cairn) — when we
needed a way to record history for AI agents, their approach was a great
reference; thanks to TSecBench and GeekCon for the battlegrounds.

<p align="center"><img src="docs/assets/ape-stargazing.jpg" alt="The first time an AI ape looked up at the stars" width="480"></p>

**Author**: N1nEmAn · VarFusion Lab ｜ WeChat: 未知聚变 (VarFusion)

**License**: MIT (plus [DISCLAIMER.md](docs/DISCLAIMER.md))
