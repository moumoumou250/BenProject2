# 0003 出处标记必须可解析

- Status: accepted
- Date: 2026-11-18

## Context

代码里有 12 处 `(review H3)`、`(review codex#8)` 这类标记，指向一轮从未进入仓库
的外部评审。对今天的读者，它们的价值是负的：看起来像有据可查，实际点不开，还
让人误以为某个决定已经被审过。更糟的是它们**替代了**真正的解释——`(review C1)`
旁边的「为什么」往往写在评审里，而不在代码里。

## Decision

代码中的出处标记只有两种合法形式：

1. 指向 `docs/reviews/INDEX.md` 里登记过的编号（且该记录必须可读）；
2. `[adr:NNNN]`，指向 `docs/adr/NNNN-*.md`。

其余一律不写。**首选做法是不写标记**，直接把「为什么」写进注释——那才是下一个
人真正需要的东西。

## Consequences

- 代价：历史编号需要一次性内联化（本仓库已在 2026-11-18 完成），diff 会碰到
  十余个文件（只改注释，不动逻辑）。
- 收益：读完代码就知道理由，不必去找一份不存在的文档；新加的 `[adr:NNNN]`
  一旦指向空号会立刻被 CI 拦住。
- 附带收益：ADR 的引用关系变成活的——被删的决策会连带暴露失效引用。

## Enforced-by

`scripts/ci/arch_check.py --check stale_refs`

判据：扫描 `ben/ scripts/ tests/` 下的 `.py` 与 `.html`：`review <编号>` 与
`codex#<n>` 必须出现在 `docs/reviews/INDEX.md` 文本中；`[adr:NNNN]` 必须有对应
`docs/adr/NNNN-*.md`。
