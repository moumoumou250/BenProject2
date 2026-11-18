# docs index

| Path | Role |
|------|------|
| [ARCH.md](ARCH.md) | Module placement + responsibilities |
| [DISCLAIMER.md](DISCLAIMER.md) | Legal / usage boundaries |
| [README.zh-CN.md](README.zh-CN.md) | Chinese user guide |
| [adr/](adr/) | Architecture Decision Records |
| [plans/](plans/) | Active optimization / delivery plans |
| [plans/archive/](plans/archive/) | Superseded plans (v1–v3) |
| [reviews/](reviews/) | Design / code reviews |
| [research/](research/) | Spikes and comparisons |

v1/v2/v3 optimization plans are **superseded by**
[plans/OPTIMIZATION-PLAN-v4.md](plans/OPTIMIZATION-PLAN-v4.md).

Positioning and the phased refactor that follows from it:
[plans/POSITIONING-PLAN-v1.md](plans/POSITIONING-PLAN-v1.md) — product contract
(target → findings → report → sandbox → distribution), 6 stages, one commit each.

P1's smallest shippable slice — CLI self-check + deterministic target-site
testing (`ben doctor` / `ben target` / `ben scan`, S0–S4):
[plans/CLI-SELFCHECK-TARGET-SCAN.md](plans/CLI-SELFCHECK-TARGET-SCAN.md).
