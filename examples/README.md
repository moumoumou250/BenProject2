# ben — worked examples

## Grok Build

订阅登录跑 sdk 引擎（无需 xAI API key）：见 [grok/](grok/)。

```bash
grok login
cp examples/grok/env.example .env
python examples/grok/check_auth.py
python examples/grok/smoke.py
```

## Example 1 — a debugging campaign (fgc classic)

The goal is to find why `python reproduce.py` segfaults.

```bash
# 0. set up a workspace
mkdir -p /tmp/ben-demo && cd /tmp/ben-demo
cat > reproduce.py <<'EOF'
import sys
print("loading module X")
# ... imagine this segfaults deep in a C extension
raise SystemExit("segfault would happen here in the real case")
EOF

# 1. create the graph
ben init --origin "user report: segfault" --goal "find root cause of segfault in reproduce.py"

# 2. see it
ben status
ben graph                    # full graph as text

# 3. commander proposes the first intents (DRY RUN first to see the prompt)
ben dispatch reason --dry-run

# 4. for real — sonnet reads the graph and writes intents into .ben/
ben dispatch reason

# 5. work the first proposed intent
ben pick                       # -> i001
ben dispatch i001

# 6. verify what it claimed
ben dispatch verify --intent i001

# 7. loop: reason -> explore -> verify until the commander returns {"complete":...}
ben dispatch reason

# 8. finish
ben complete --from f003 --note "C extension double-free, patched in v2.1"

ben status                     # status: completed
```

## Example 2 — an engagement / CTF challenge (ben native)

```bash
mkdir -p runs/c01 && cd runs/c01
ben init --goal "break target c01 and submit the flag"

# optional: wire the platform API (fill endpoints from the official doc)
ben arena init
export BEN_ARENA_TOKEN=...

# recon lands as typed facts
ben fact "10.0.2.15 alive, ports 22,80,3306" -t "主机存活" -k host -d ip=10.0.2.15 -d os=linux
ben fact "80/tcp nginx 1.18 + php 7.2" -k service -d host=10.0.2.15 -d port=80 -d product=nginx -d version=1.18
ben fact "admin:admin123 logs into /admin" -k cred -d username=admin -d password=admin123

# exploit, then the moment you see a flag:
ben flag "flag{s0me_pr00f}" -c c01 --submit
ben status
#   kinds:  1 hosts, 1 services, 1 creds, 1 flag(s)
#   flag:   f005 status=submitted challenge=c01 value=flag{s0me_pr00f}

# autonomous run bounded by the match clock
ben auto --skip-permissions --deadline "2026-10-17T13:00:00"

# a whole board of challenges, round-robin
cd .. && ben sweep --root runs --minutes-per 20 --deadline "2026-10-17T13:00:00" --skip-permissions
```

## resuming

The graph is on disk. Close the terminal, come back tomorrow:

```bash
cd runs/c01
ben status      # picks up exactly where you left off
ben graph       # full history of facts + intents
```
