# 0004 模块必须先登记再落地

- Status: accepted
- Date: 2026-11-18

## Context

`ben/` 下的分层是靠人记的：`core` 不许依赖 `agents`，`report` 只读，`commands`
不许被反向依赖。这些约定写在文档里没人读，写进代码又会绕。结果就是
`agents/factory.py` 从 `commands/util.py` 导入 `parse_from` 这类反向依赖能活很久。

新模块的问题更直接：加一个 `ben/xxx/` 目录零成本，于是「临时放一下」的代码会
变成永久的第 10 个包。

## Decision

`ben/` 下每个目录必须在 `docs/ARCH.md` 的登记表里有一行，写清**职责**、
**允许依赖**、**禁止**。不登记的目录视为架构违规；测试文件不得留在包内。

## Consequences

- 代价：加目录要改文档，多一步。
- 收益：分层从「口头约定」变成可 diff 的声明；review 时争的是表格而不是记忆；
  包数量增长有摩擦（这正是想要的）。
- 已知不足：登记表只约束**目录级**方向，不约束具体 import（那需要
  `import-linter`，见 `docs/OPTIMIZATION-PLAN-v2.md` §5.2）。本 ADR 是它的前置。

## Enforced-by

`scripts/ci/arch_check.py --check packages`

判据：`ben/*/`（含 `.py` 的目录）必须在 `docs/ARCH.md` 表格首列出现；
包内出现 `test_*.py` 即违规（应放 `tests/`）。
