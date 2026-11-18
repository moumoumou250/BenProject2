# ADR 0008 — Concluding an intent requires machine evidence

- Status: accepted
- Date: 2026-11-18
- Enforced-by: `ben/core/store.py:conclude_with_new_fact`, `tests/test_evidence.py`

## Context

`ben done` previously called `conclude_with_new_fact` with no proof that
checks passed. Agents could mark work complete by assertion alone.

## Decision

1. `Store.conclude_with_new_fact` requires either:
   - a `ben verify --intent <id>` report (`evidence=` path) whose
     `intent` / `sha` / `exit` / check exits all match, or
   - `force=True` / `--force`, which sets `data.forced=true` and leaves a hint.
2. Explore/auto paths that conclude without a report use `force=True` and
   write a forced-conclude hint (trail, not silent bypass).
3. Naming:
   - `ben verify` — machine evidence (arch_check, pytest, optional smoke)
   - `ben dispatch verify` — LLM post-hoc review of an already-concluded fact
   - `ben validate` — graph integrity only

## Consequences

Tests and bookkeeping concludes pass `force=True`. CI and humans use
`ben verify` then `ben done --evidence`.
