# 架构决策记录（ADR）

这里的每一篇都必须有 **Enforced-by** 字段，指向一条**机器检查**（`scripts/ci/arch_check.py` 的某个 check、CI 步骤或 ruff 规则）。

没有 Enforced-by 的决策不是 ADR，是备忘录。本仓库的规矩是：**锚点缺失就不合入**——因为一条没人执行的决策，三个月后就会被下一个人无声地推翻，而且没人知道自己推翻了什么。

## 索引

| 编号 | 决策 | 锚点 |
|---|---|---|
| [0001](0001-zero-dependency-kernel.md) | 内核零第三方依赖 | `arch_check third_party` |
| [0002](0002-one-implementation-per-idea.md) | 一个想法只有一份实现 | `arch_check duplicates` |
| [0003](0003-provenance-must-resolve.md) | 出处标记必须可解析 | `arch_check stale_refs` |
| [0004](0004-module-placement-is-declared.md) | 模块必须先登记再落地 | `arch_check packages` |
| [0005](0005-rule-files-have-a-budget.md) | 规则文件有行长预算 | `arch_check agents_budget` |

## 模板

```markdown
# NNNN 标题

- Status: accepted | proposed | superseded by NNNN
- Date: YYYY-MM-DD

## Context
当时面对什么问题，有哪些约束。

## Decision
决定了什么（一句话能说清，说明白到别人能据此判断对错）。

## Consequences
代价是什么。没有代价的决策通常是没想清楚。

## Enforced-by
`check` 名字 + 具体判据。检查不存在就先别写这篇。
```

写新 ADR 时用 `docs/adr/0000-template.md` 复制。
