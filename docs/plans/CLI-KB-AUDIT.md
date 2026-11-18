# 三命令 CLI 结构核查 + KB 写入与回滚评估

状态：**已并入确认方案**（`docs/plans/KB-FEEDBACK-LOOP.md`，2026-11-18）
日期：2026-11-18
核查对象：`ben kb check`、`ben kb diagnose`、`ben verify --target/--vuln`（方案中的三个命令）
核查基准：`ben/cli.py`（593 行）、`ben/commands/kb_cmds.py`、`ben/kb/__init__.py`、`ben/core/errors.py`、`bin/ben`、`ben/agents/prompts/explore.md`
性质：本文只做核查与结论，不含实现代码；终版命令面与实施序以确认方案为准

---

## 0. 结论摘要（两句）

1. **`ben verify` 这个名字已经被占用**，与现有「为 intent 生成 evidence report」的命令冲突，方案必须改名（建议 `ben probe`）。
2. **退出码 `2 = 用法/配置错误` 与项目现状相反**：项目里语义错误走 `FGError` → `1`，只有 argparse 层错误才是 `2`。若不明确例外，`check` 与 `kb show` 会对同一类错误给出不同码。

其余参数、输出、命名空间等 7 项基本一致，详见 §2。

---

## 1. 核查依据（可复现）

| 项 | 命令 / 位置 | 实测结果 |
|---|---|---|
| 语义错误退出码 | `./bin/ben kb show kb999` | `exit=1`（`KBError → FGError`，`cli.py:588-590`） |
| argparse 错误退出码 | `./bin/ben kb bogus` | `exit=2`（choices 校验失败，argparse 自带） |
| 缺参退出码 | `./bin/ben kb show` | `exit=1`（`target=None` 落到 `kb.get(None)` → `KBError`） |
| 已有 verify | `./bin/ben verify --help` | `usage: ben verify [-h] --intent INTENT [--run]` |
| KB 是否入 git | `git ls-files ben/kb \| wc -l` | `57`（56 条目 + `__init__.py`），全部跟踪 |
| KB 有无测试 | `grep -n kb tests/test_ben.py` | 无输出，**零覆盖** |
| 工作树状态 | `git status --short ben/kb` | `M ben/kb/__init__.py`（有未提交改动） |
| agent 是否写 KB | `ben/agents/prompts/explore.md:46` | 明确指示 `ben kb add "..." -t <tag> --detail "..."` |

---

## 2. 逐项比对：命令组织 / 参数定义 / 调用方式

### 2.1 命令组织

| 维度 | 项目现有惯例 | 方案写法 | 判定 |
|---|---|---|---|
| 一层命令（单动作） | `ben recall`、`ben validate`、`ben view`、`ben config`、`ben sweep` | `ben probe`（建议） | ✅ 若改名 |
| 一层命令（已被占用） | `ben verify --intent` 生成 evidence report（`cli.py:289-299`） | `ben verify --target/--vuln` | ❌ **P0 冲突** |
| 带动作组的命令 | `ben kb <action> <target>`、`ben arena <action>`、`ben fleet <action>`、`ben console <sub>` | `ben kb check "<query>"` | ✅ 契合 `action + target` 模式 |
| 动作枚举 | `action` 用 `choices=[...]` 硬枚举（`cli.py:403-407`） | 在 choices 里加 `check`/`diagnose` | ✅ |
| 嵌套子命令 | 仅 `ben console` 用二层 subparser | 方案不用嵌套 | ✅ 不引入新层级 |

**冲突说明**：现有 `ben verify` 被 `ben done --evidence` 消费（`cli.py:277-287` 的 `--evidence` 指向 `ben verify --intent` 产出的 `report.json`）。若把 `verify` 改造成 `--target/--vuln`，会直接打断这条 CI 证据链，且两套参数互斥无法共存。

**改名建议（择一）**：

| 候选 | 优点 | 缺点 |
|---|---|---|
| **`ben probe`**（推荐） | 叶子命令，与 `ben recall/validate` 同风格；动词准确（主动探测）；无冲突 | 新词，需在 help 里与 `verify` 划清边界 |
| `ben range verify` | 语义上归到靶场；未来可扩展 `range list/status` | 多一层 group，而当前只有 1 个动作，违背「单动作用叶子命令」的现有风格 |
| `ben kb verify` | 复用现有名字 | ❌ 它在 `kb` 命名空间下却会发网络请求，会让人误以为 `ben kb *` 都只读 |

### 2.2 参数定义

| 维度 | 项目现有惯例（出处） | 方案写法 | 判定 |
|---|---|---|---|
| 主对象用位置参数 | `fact <description>`（`cli.py:79`）、`send <peer> <message>`（:152）、`arena <action> <challenge_id>`（:392-396）、`kb <action> <target>`（:403-411） | `ben verify --target X --vuln Y`（全 flag） | ⚠️ **不一致**，见下 |
| 可重复参数 | `--tag/-t append`（:415）、`--data/-d append`（:84）、`--command/-c append`（:417） | `--only` append、`--variants` append | ✅ |
| 逗号列表 | `intent --from "a,b"`（:96 注释 "comma/space separated"） | `--only kb001,kb002` | ✅ 有先例 |
| 布尔门控 | `--force`（init/setup/done）、`--skip-permissions`（auto/dispatch）、`--run`（verify） | `--yes` | ❌ **不一致**，项目无此拼写 |
| 机器输出 | `--json`（fact/intent/peers/recall/config/console list） | `--json` | ✅ |
| 目录参数 | `kb --root`（KB 根，:421）、`bench --root`（store 根，:430）、`rangectl --profiles`（:287） | `--profiles` | ⚠️ 名称与 rangectl 一致，但跨包路径默认值需写死 |
| 数量上限 | `--limit/-n`（kb :423、recall :246） | 未定义 | ➕ 若加，必须用 `-n` 短选项 |
| 全局参数位置 | `--store`/`--engine` 可写在子命令后（`_hoist_global_flags`，:540-568）；`--root` **不**参与 hoist | 方案不涉及 | ✅ 无影响 |

**位置参数不一致的处置**：`--target/--vuln` 的初衷是防换位，但换位风险可以用**交叉校验**消除——`profile-id` 必在 profiles 集合内，`vuln` 必在 `taxonomy.vulns` 键内，两者交集为空，换位必然报错。既然校验能兜住，就应采用与项目一致的位置参数：

```
ben probe <profile-id> <vuln>
ben probe tomcat-cve-2017-12615 file-write
```

（与 `ben arena submit <challenge_id>` 的形态完全同构。）

### 2.3 调用方式与退出码

| 维度 | 项目现有惯例 | 方案写法 | 判定 |
|---|---|---|---|
| 成功 | `return 0` | `0` | ✅ |
| 语义错误 | 抛 `FGError` → `main()` 返回 `1`（`cli.py:586-590`） | `2` | ❌ **P0 冲突** |
| 参数错误 | argparse 自动 `2` | `2` | ✅ 仅限 argparse 层 |
| 无先例的码 | 全项目无 `return 3`（`grep -rn "return 2\|return 3" ben/` 无结果） | `3` | ⚠️ 需显式声明例外 |
| 输出约定 | `print()` 直出；错误写 `sys.stderr` + `ben: ` 前缀 | 同 | ✅ |
| 入口 | `bin/ben` → `sys.exit(main())`，`main` 返回 int | 同 | ✅ |

**冲突的严重性**：`kb show kb999` 现在返回 `1`。若 `kb check --only kb999` 返回 `2`，同一个 `ben kb` 家族对「id 不存在」给出两种码，脚本无法统一处理。

**建议契约（明确例外，且不破坏老命令）**：

| 错误类型 | 现有 `kb add/search/show/list/import` | 新增 `check/diagnose/probe` |
|---|---|---|
| 参数拼错、缺必填（argparse） | `2` | `2`（同） |
| id 不存在、`--only` 为空、taxonomy 损坏 | `1`（`FGError`） | **`2`**（新增显式返回，捕获 `KBError` 后 `return 2`） |
| 结论：未命中 / 未证实 | — | `1` |
| 结论：无法判定 | — | `3` |

这样做的代价是「同一家族两种错误码」，必须在 `--help` 与 `docs/` 明写。不这样做的代价是整个 `check` 无法当 CI 门禁用（`1` 同时表示「不可达」和「参数错」）。

### 2.4 命名空间与语义边界

| 已有命令 | 语义 | 与新命令的边界 | 风险 |
|---|---|---|---|
| `ben validate` | 图 JSON / 引用 / 状态校验 | `check` 校验知识可达性 | 名字近，需在 help 互相指路 |
| `ben verify --intent` | 生成 evidence `report.json` | `probe` 直接对靶场取证 | 改名后消失 |
| `ben kb search` | 原检索（保留） | `check` = search + 三态判定 + scope | `check` 必须复用同一打分器，不得另写一套 |

---

## 3. 不一致清单（按严重度）

| # | 级别 | 不一致 | 处置 |
|---|---|---|---|
| 1 | **P0** | `ben verify` 名字被 evidence 命令占用（`cli.py:289-299`） | 改名 `ben probe` |
| 2 | **P0** | `2 = 用法/配置错误` 与 `FGError → 1` 相反 | 仅在新增三分支显式 `return 2`，并在文档标注例外 |
| 3 | P1 | `--yes` 无先例（项目用 `--force`） | 改 `--force`，help 写明「确认已在授权范围内执行」 |
| 4 | P1 | `--target/--vuln` 全 flag，与「主对象用位置参数」不符 | 改为两个位置参数 + 交叉校验 |
| 5 | P2 | `3` 在全项目无先例 | 保留，但在 help 与 docs 声明「结论码」语义 |
| 6 | P2 | KB 零测试覆盖（`tests/` 无 kb 用例） | S2 必须新增 `tests/test_kb_check.py` |
| 7 | P2 | `kb --root` 与 `--profiles` 默认值分属不同包（`ben/` vs `tests/TestRange/`） | `probe` 的 profile 路径默认值需能跨包定位，并在找不到时给明确提示 |
| 8 | P3 | 现有 `kb` 的 `tag = args.tag[0]` 只取第一个 `--tag`（`kb_cmds.py:57`） | 新增命令不得复制该写法；老命令是否修另议 |

---

## 4. 修订后的命令面（已同步进 `KB-FEEDBACK-LOOP.md`）

```
ben kb check "<query>" --only <id>[,<id>...] [--json] [--show-tokens] [--root DIR]
ben kb diagnose "<query>" --only <id>[,<id>...] [--variants "a,b"] [--variants-file F] [--json]
ben probe <profile-id> <vuln> [--force] [--allow-destructive]
          [--max-requests N] [--timeout S] [--deadline S] [--json] [--profiles DIR]
```

调用方式与现有命令同构：`ben kb check "布尔盲注" --only kb001,kb002` ≈ `ben kb search "..." -t web`；`ben probe <id> <vuln>` ≈ `ben arena submit <challenge_id>`。

---

## 5. KB 写入路径：谁写、何时写、写什么

全库写入点只有 3 处代码入口 + 1 处人工入口。**新增的三个命令一律不写 KB**（这是设计约束，不是疏忽）。

| # | 入口 | 位置 | 触发条件 | 写入内容 |
|---|---|---|---|---|
| W1 | `ben kb add` | `kb_cmds.py:24-37` → `KnowledgeBase.add`（`kb/__init__.py:83-115`） | ① 人工执行；② **explore agent 在 dispatch 期间自动执行**（`explore.md:46` 明确指示） | 新建 `entries/kbNNN.json`：`id`（自动，= 条目数+1）、`title`、`description`、`detail`、`commands[]`、`tags[]`（强制小写且匹配 `[a-z0-9][a-z0-9_-]*`）、`source`、`created_at` |
| W2 | `ben kb import` | `kb_cmds.py:69-85` | 人工，指向 `.md` 文件或目录 | 每个 `.md` 一条：`# 标题`→`title`，首行 `>`→`description`，余下→`detail`，`--tag` 透传 |
| W3 | 手工编辑 JSON | 无代码入口 | 人工（**当前修改已有条目的唯一方式**） | 任意字段。注意：`add()` 签名**没有 `validation` 参数**，所以补 `validation` 只能走 W3，或先扩签名 |
| W4 | （S3 计划新增）`ben/kb/taxonomy.json` | 新文件 | 人工一次性建立 | `subjects`（core/qualifier 组）+ `vulns`（别名 + 指向 kb id） |

**不写 KB 的三处（明确记录）**：`check`、`diagnose`、`probe`。`probe` 只写 `runs/probe/<profile-id>/<ts>/`（请求响应与 `verdict.json`），该目录不属 KB。

**W1 的两个隐含风险**：

1. **agent 会自己写库**。`explore.md:46` 指示它在「发现 KB 没覆盖的东西」时执行 `ben kb add`。这意味着一次 `ben auto` 跑下来，KB 可能被追加多条无人复核的条目，且与人工改动混在同一工作树里。
2. **id 复用**。`_next_id()`（`kb/__init__.py:77-81`）取 `条目数+1`，删除某条后新增会**复用同一个 id**，而历史账本/证据里引用的 id 会悄悄指向新内容。

---

## 6. 触发条件汇总（什么操作会让 KB 变脏）

| 触发 | 是否需人工确认 | 影响文件数 | 典型场景 |
|---|---|---|---|
| `ben kb add`（人工） | 是（人敲的命令） | 1 | 调试时发现缺口，补一条 |
| `ben kb add`（agent，`explore.md:46`） | **否** | 0~N | `ben auto` / `ben dispatch explore` 期间自动追加 |
| `ben kb import` | 是 | N（目录下全部 `.md`） | 批量导入 writeup |
| 手工编辑（W3） | 是 | 1 | 补 `validation`、改 `tags` |
| `taxonomy.json` 编辑（S3） | 是 | 1 | 补词表/别名 |
| `check`/`diagnose`/`probe` | — | **0** | 只读 |

---

## 7. 回滚评估

### 7.1 可行性结论：**高**

三个有利事实：

1. **一条目一文件**，纯 JSON，无数据库、无二进制；
2. **全部 57 个文件都在 git 跟踪内**（`git ls-files ben/kb` = 57），回滚就是文件回滚；
3. **没有派生索引**（无 sqlite / 无缓存索引文件，`__pycache__` 除外），回滚后无需重建。

### 7.2 回滚方式（按粒度）

| 粒度 | 命令 | 适用 | 可行性 |
|---|---|---|---|
| 单字段 | `git diff ben/kb/entries/kb002.json` → `git checkout -- <file>` | 改错一个 `tags` | ✅ 最常用 |
| 单条目 | `git checkout -- ben/kb/entries/kb056.json`（新增则 `git rm`） | 补错了整条 | ✅ |
| 一批改动 | `git revert <sha>` | 一次迭代的整组改动 | ✅ 要求每次迭代单独提交 |
| 无 git 环境 | `cp -a ben/kb /tmp/kb.bak.$(date +%s)` 后再改 | `BEN_KB_ROOT` 指向仓库外时 | ⚠️ 唯一手段 |

**必备前置（当前不满足）**：`ben/kb/__init__.py` 已有未提交改动（`M`）。在开始任何 KB 迭代前必须先 `git commit` 一个干净点，否则 `git checkout` 的边界不可判定，且无法区分「我的改动」与「既有改动」。

### 7.3 影响范围

| 被回滚的对象 | 影响面 | 是否波及 |
|---|---|---|
| `entries/kbNNN.json` 的 `tags/description` | 该条目的检索命中与 `check` 结论 | 不波及 Store / graph |
| `entries/kbNNN.json` 的 `validation` | 该条目的 `probe` 判定（`0`/`1`/`3` 之间翻转） | 不影响其他条目 |
| 新增条目 | 条目总数 → `_next_id()` 的下一个 id | 删除后 id 会被复用 |
| `taxonomy.json` | `check`/`diagnose`/`probe` **三条链同时受影响** | 影响面最大 |
| 打分器代码（S1） | 全部条目的命中结果 | 与 entries 解耦，可独立回滚 |

### 7.4 风险

| 风险 | 级别 | 说明与缓解 |
|---|---|---|
| 回滚条目但账本未同步 | **高** | 账本与实际不符。缓解：entries 与 `kb-iterations.md` **放在同一个 commit**，一起 revert |
| agent 自动 add 的条目混在人工改动里 | **高** | 回滚会连带删掉 agent 的有效发现。缓解：`source` 字段必填并标注来源（`agent/` 前缀），回滚前先 `git status` 分类 |
| id 复用导致历史记录指向新内容 | 中 | 账本/证据里写的 `kb056` 可能已换内容。缓解：不删条目，改为 `tags` 置 `deprecated` 并保留文件 |
| 证据与判据脱钩 | 中 | 回滚 `validation` 后，旧 `runs/probe/*/verdict.json` 引用的判据已不存在。缓解：`verdict.json` 记录当时的 `validation` 快照与文件 sha |
| `BEN_KB_ROOT` 指到仓库外 | 中 | git 完全失效，只能靠备份。缓解：迭代前打印实际 KB 根并确认它在 git 内 |
| KB 零测试 | 中 | 回滚后无法自动验证「没退化」。缓解：S2 同时补 `tests/test_kb_check.py`，把 §9 的正反例固化为断言 |
| 打分器回滚但账本保留 | 低 | 「前/后」对照失效。缓解：账本记录代码 `git sha` |

### 7.5 回滚结论

**可回滚，且成本低（单文件 `git checkout`）**，但有三个前提必须先补：

1. **提交现有脏工作树**（`M ben/kb/__init__.py`），建立干净基线；
2. **entries 与账本同 commit**，否则账本会说谎；
3. **不删条目、只标记**，规避 id 复用；同时给 `source` 定一个可区分的命名规则（人工 vs agent）。

---

## 8. 需要同步修订的方案条目（已完成）

| 原写法 | 修订为 | 影响章节 |
|---|---|---|
| `ben verify --target <id> --vuln <v>` | `ben probe <profile-id> <vuln>` | 全文 |
| `--yes` | `--force` | §5.4、§9 |
| `2 = 用法/配置错误`（含 id 不存在） | 保留 `2`，但标注为「新增三分支显式返回」的例外，老命令仍 `1` | §5、§9 |
| 无「命名冲突」说明 | 新增与 `ben verify --intent` 的边界说明 | §2、§11 |
| 回滚/写入分析缺失 | 本文 §5–§7 | 新增 |

---

## 9. 核查后仍需确认的两件事

1. **`ben probe` 是否接受用户自建 profile 路径**？现 `rangectl --profiles DIR` 写在子命令前（`rangectl.py:287`），而 `ben` 的全局参数只 hoist `--store/--engine`。若 `probe --profiles` 写成子命令后，与 rangectl 的位置习惯相反，需在 help 明写。
2. **`taxonomy.json` 放 `ben/kb/` 还是 `ben/data/`**？放 `ben/kb/` 与 entries 同目录，随 `BEN_KB_ROOT` 迁移，但会被「KB 是知识、不是配置」的直觉挑战；放 `ben/` 则不受 `BEN_KB_ROOT` 影响，但换 KB 根后词表与条目不匹配。**建议放 `ben/kb/`**，理由是词表必须与被检索的那批条目同生命周期。

---

## 10. 确认方案对审计项的最终裁决

| 审计项 | 确认裁决 |
|---|---|
| P0 `verify` 名冲突 | `ben probe` |
| P0 退出码 2 例外 | 仅新三命令；显式校验 return 2，老命令不动 |
| P1 `--yes` | `--force` |
| P1 全 flag 主对象 | 两位置参数 + 交叉校验 |
| P2 码 `3` | 保留为结论码 |
| P2 零测试 | S2 补 `tests/test_kb_check.py` |
| P2 `--profiles` 默认 | 子命令后；回退到 `tests/TestRange/profiles` |
| 额外：S1 改 `search()` | **否决**——并行 `ben/kb/match.py` |
| 额外：仅 RFC1918 | **修订**——`authorized=true` 可公网 lab |
| 额外：重叠双字 | **否决**——非重叠 + 别名最长优先 |
