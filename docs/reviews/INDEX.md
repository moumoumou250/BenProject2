# 外部评审记录索引

`scripts/ci/arch_check.py` 的 `stale_refs` 检查会扫描代码里的出处标记：

- `review <编号>`（如评审轮次里的 C1 / H1 / M2 这类编号）
- `codex#<数字>`
- `[adr:NNNN]`（指向 `docs/adr/` 里的决策记录）

**规则：标记必须能解析到这里，否则视为噪音。** 理由很简单——一个指向虚空的编号比没有注释更糟，它让人以为存在一份可以查的证据。

## 2026-11 评审轮

2026-11-18 的治理 pass 里，代码中 12 处外部评审编号被**内联化**：原来写成
`...(review C1)` 的地方，改成直接说清「为什么必须这样」。因为这些编号背后的
评审记录从未进仓库，读者点不开、也无法验证；保留编号只是在代码里留下考古学。

已注销编号（**不要在新代码里重新引用**）：

| 编号 | 原位置 | 该条评审在说什么（据代码上下文重建） |
|---|---|---|
| C1 | `agents/factory._worker_id` | 并发执行者不能用同一身份，否则 claim 校验会被绕过 |
| C1/H1 | `factory._dispatch_explore` | 结论必须原子：并发时不能留下孤儿 fact |
| H1 | `commands/dispatch.cmd_done` | 同上，`done` 路径 |
| H2 | `scripts/hooks/ben-hook._frontier_block` | 注入上下文必须截断，否则每轮都膨胀 |
| H3 | `llm/jsonx.extract_json_object` | 模型输出常带散文前缀，要逐个平衡括号尝试 |
| H4 | `commands/util._assert_safe_store_root` | 破坏性操作前必须确认目标是 store，不是 `/` 或 `$HOME` |
| L3 | `web/template.html` | 高亮需要记住「哪些 intent 碰到某个 fact」 |
| L5 | `commands/auto` dry-run | dry-run 不改图，跑一遍就够 |
| M1 | `web/view` | 本地端口必须带不可猜 token，防任意网页抓图 |
| M2 | `hooks/ben-hook._find_store_upward` | 严格按项目：父目录的图不能激活子目录的 hook |
| codex#4 | `web/view`（同 M1） | 同上 |
| codex#5 | `hooks/ben-hook._event_cwd` | hook 的 cwd 可能来自事件体而非进程 cwd |
| codex#6 | `hooks/_settings_patch._cmd` | 路径含空格/元字符时要 shell-quote |
| codex#8 | `core/io._read_node_files` | 坏 JSON 不能让 status/graph/view 崩 |
| codex#10 | `hooks/_settings_patch` | `remove` 可以推断脚本路径，`add` 不行 |

## 新标记怎么用

1. **优先**：把原因直接写进注释，不引入任何编号。
2. 若确实需要外部出处（例如某份安全评估），先在 `docs/reviews/` 落地一份可读记录，再引用它。
3. 架构决策不要用评审编号表达——写 `[adr:NNNN]`，指向 `docs/adr/` 里的记录。
