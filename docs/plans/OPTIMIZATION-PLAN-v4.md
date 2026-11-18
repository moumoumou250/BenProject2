# ben 优化方案 v4 —— 只剩未完成的部分

> 基线：2026-11-18 10:30，`arch_check` 八项 0 violation，`pytest` 128 passed / 3 skipped。
> 关系：**v1/v2/v3 中已完成的部分在本文件中被删除**（§1 列出删了哪些、凭什么删），
> §2 起是剩余项，重新按依赖排序，不沿用旧编号。

---

## 0. 一句话

原来 21 条待办，**7 条已完全落地**（§1），其余 **14 条**全在 §2 起。
其中真正卡住整条链的只有一条：`ben done` 仍然不需要任何证据。

---

## 1. 从旧方案里删掉的（已优化，不要再做）

判定标准：能在当前 HEAD 上跑出绿结果，或有可指认的落地物。删掉的条目**连同它的验收命令一起作废**。

| 旧编号 | 事项 | 落地物 / 证据 |
|---|---|---|
| v2 §5.1 之前 | 运行时输出单一根 | `ben/core/paths.py`；名字只在 1 处；`arch_check --check runtime_paths` 绿；ADR 0006 |
| v3 V7 | 架构自动检查 | `scripts/ci/arch_check.py`，**8 项**（比计划的 4 项多出 `third_party`/`stale_refs`/`runtime_paths`/`root_layout`）；baseline 为空 |
| v3 V9 | ADR + 规则预算 | `docs/adr/0001–0007`，每篇带 `Enforced-by`；`AGENTS.md` 58/60 行受 `agents_budget` 约束 |
| v3 §0.5 | P4 长期治理 7 项 | 分词器两份 → `core/text.py` 一份；`now_iso` 合并；`fg-hook`→`ben-hook` 6 处；12 处失效评审编号内联化；孤儿 `payloads.pyc` 已删 |
| v2 §6.4 | 提示词移出 Python | `ben/agents/prompts/*.md` 6 个文件，由 `commands/util.py:64` 加载。**唯一一行没被完全删除的**：残余是 `factory.py:25` 的 1607 字符内联提示词 → 已改写成 **R-13** |
| 新增 | 仓库根允许清单 | `arch_check --check root_layout`；根 22 → 19 条；ADR 0007 |
| 新增 | 一键闸门 | `scripts/ci/preflight.sh`（arch_check + pytest，自动探测装了 pytest 的解释器） |
| 新增 | `console_root` 读无副作用 | 纯路径函数；`tests/test_paths.py` 三条断言钉住 |

**被删掉的三条旧验收**（它们断言的状态已经达成，留着只会误导）：

```
arch_check 4 项 → 0        # 现在是 8 项
docs/adr 目录存在           # 现在有 7 篇，且有 Enforced-by 校验
grep -r fg-hook → 空        # 已空
```

---

## 2. 剩余项总览（14 条）

按**依赖**排序，不按旧编号。`←` 表示必须先完成左边。

| ID | 事项 | 一句话证据 | 状态 |
|---|---|---|---|
| **R-01** | `lab/` 退出索引 | `git ls-files lab` → **29 个**，`.gitignore` 里的 `/lab/` 对已跟踪文件无效 | 1 条命令 |
| **R-02** | 历史与凭证决策 | 靶场文件由根提交 `6098db0` 引入，`origin` 已推送 → 泄露已发生 | **需你拍板** |
| **R-03** | 证据闸门 | `commands/dispatch.py:31` 的 `cmd_done` 零校验 | 最高杠杆 |
| **R-04** | pyproject + ruff 首绿 | 无 `pyproject.toml`，`ruff` 未安装 | 护栏地基 |
| **R-05** | CI 三步 | 无 `.github/`，无 pre-commit | ← R-04、R-03 |
| **R-06** | 分层契约 3 条 | 无 import-linter；`agents/factory.py:9` ← `commands.util`（领域层依赖命令层）；3 处命令模块互吃 `auto._args` | ← R-04 |
| **R-07** | Store 写路径 O(n²) | 200 facts 写 100 intents = **12.3 s**（50→100→200 为 0.90/3.13/12.30） | 独立 |
| **R-08** | dispatch 归一 | 同一逻辑两份：factory 91 行 + auto 65 行 | ← R-04 |
| **R-09** | 私有符号收口 | **29 条 import / 52 个符号**（`auto.py:8` 一行 8 个） | ← R-08 |
| **R-10** | hook 启动税 | 边际 **207 ms**（`python -c pass` 360 ms → hook 568 ms），每轮对话付一次 | ← R-06 |
| **R-11** | `--run` 运行时验证 | `verify` 动词是模型自评，不执行代码 | ← R-03 |
| **R-12** | JSONL 运行轨迹 | `import logging` **0 处**；`runs/logs/` 只有裸 stdout | ← R-11 |
| **R-13** | 执行器提示词外置（残余） | `agents/factory.py:25` 仍有 **1607 字符**内联系统提示词 | 独立 |
| **R-14** | 权限矩阵 + docs 分层 | 无按角色的写权限；`docs/` 13 文件平铺、18 条链接失效 | 独立 |

另有 4 条**降级为可选**（原计划里排在后面，现在判定不该投入）：Pyright、Hypothesis、cli 拆分、DispatchContext、commander 收口 —— 见 §6。

---

## 3. W0：今天收尾（R-01、R-02）

### R-01 `lab/` 退出索引（1 条命令，零风险）

```bash
git rm -r --cached lab/juice-shop-20261117
git ls-files lab | wc -l        # → 0
```

本地文件全部保留。仓库索引减 2.7 MB。`.gitignore` 里 `/lab/` 已经写好，命令执行后即生效。

### R-02 历史与凭证（**必须你决定，我不动 remote**）

事实：`origin` = `github.com/moumoumou250/BenProject2`，当前分支已推送，靶场文件由**根提交 `6098db0` 一个提交**引入。所以"要不要处理历史"不是可选项，是已经发生的泄露。

| 选项 | 动作 | 代价 |
|---|---|---|
| **A 只止血** | 只做 R-01；历史里仍可 `git show 6098db0:recon/ftp/incident-support.kdbx` | 仓库若公开，KeePass 库仍可下载 |
| **B 重写历史** | `git filter-repo --path recon --path jsscan --path fz.py --path h.txt --invert-paths` + force push | 所有克隆失效；需通知协作者 |
| **C 弃库重建** | 新建仓库，推当前树 | 历史全丢，最彻底 |

无论选哪个，**凭证处置都不依赖仓库**，应当先做：

1. `incident-support.kdbx` 主密码 —— 若曾用于任何真实系统，轮换；
2. `117.72.199.2:3000` —— 靶机是否仍在线，下线或改 IP；
3. `h.txt` 5 个 MD5 —— 对应题目若仍在使用，视为已泄露。

---

## 4. W1：让「完成」需要证据（R-03）—— 本方案唯一的高杠杆项

### 为什么它排在其他一切之前

清单里 P0-3、P2-1、P2-2、P3-2 四组要求，卡的是同一行：

```python
# ben/commands/dispatch.py:31
fact, intent = store.conclude_with_new_fact(
    args.id, args.fact, args.worker, ...)      # ← 零校验
```

CI 管人（push 时），这一行管 Agent（每一步）。**没有它，后面所有质量工具都可以被一句 `ben done` 绕过。**

### 做什么

**① `ben verify --intent i042` 产出结构化证据**

```json
{"intent":"i042","sha":"ff73143","dirty":false,
 "checks":[{"name":"arch","cmd":"arch_check","exit":0,"tail":"8 checks"},
           {"name":"pytest","cmd":"pytest -q","exit":0,"tail":"128 passed"}],
 "exit":0}
```

落 `runs/<graph>/verify/<ts>/report.json`（路径已由 `paths.py` 统一，不需要新约定）。

**② `cmd_done` 四条件校验**

1. `ev["exit"] == 0`
2. `ev["intent"] == args.id` —— 防拿别人的报告
3. `ev["sha"] == 当前 HEAD` —— 防"测完又改"
4. 任一 check `exit != 0` → 拒绝

`--force` 保留，但写 `data.forced=true` + 一条 hint —— **绕过留痕，不是禁死**。

**③ 顺手解决"可追溯"**：`fact.data` 已经有 kv 机制，加 `evidence` / `sha` / `model` 三个键，配合现成的 `fact.creator`，零新存储格式。

### 验收

```bash
ben done i001 --fact x                                  # exit 1，缺 --evidence
ben verify --intent i001 && git commit --allow-empty -m t \
  && ben done i001 --fact x --evidence <旧报告>          # exit 1，sha 不匹配
ben done i002 --fact x --evidence <i001 的报告>          # exit 1，intent 不符
ben done i001 --fact x --force                          # fact.data.forced == true 且有 hint
```

---

## 5. W2：护栏与写路径（R-04 ~ R-08）

这四件事互相咬合，顺序不能乱：**先有 ruff 才能做 R-06 与 R-08 的验收，先有 R-06 才能安全改 R-08。**

### R-04 `pyproject.toml`（第一条规则就要能过）

只开三组，一次绿：

```toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.ruff.lint.flake8-tidy-imports.banned-api]
"subprocess".msg = "改用 ben.runtime.exec(cmd, timeout=...)：它统一处理超时、编码与退出码"
"time.sleep".msg = "禁止 sleep 兜底：请改为显式等待状态"
```

验收：`ruff check ben tests` → 0 issue；`preflight.sh` 的 ruff 段从 "skipping" 变成真跑。

### R-05 CI（三条，不做矩阵）

```yaml
- run: bash scripts/ci/preflight.sh    # arch_check 8 项 + pytest
- run: ruff check ben tests
- run: git diff --name-only origin/main..HEAD | grep -q '^lab/' && exit 1 || true
```

**先红一次**：在 PR 里故意加一个 `print(` 之外的真违规（例如 `import os` 未用），确认 CI 会挂。

### R-06 分层契约（三条，两条带显式豁免）

```toml
[[tool.importlinter.contracts]]
name = "core 不得依赖上层"
type = "forbidden"
source_modules = ["ben.core"]
forbidden_modules = ["ben.commands", "ben.agents", "ben.web", "ben.runtime"]
# 今天就是绿的，直接启用

[[tool.importlinter.contracts]]
name = "agents 不得依赖 commands"
type = "forbidden"
source_modules = ["ben.agents"]
forbidden_modules = ["ben.commands"]
ignore_imports = ["ben.agents.factory -> ben.commands.util"]   # R-08 删除此行

[[tool.importlinter.contracts]]
name = "命令模块之间不得互相 import"
type = "forbidden"
source_modules = ["ben.commands"]
forbidden_modules = ["ben.commands.auto"]
ignore_imports = [
  "ben.commands.misc      -> ben.commands.auto",   # R-08 删除
  "ben.commands.commander -> ben.commands.auto",   # R-08 删除
  "ben.commands.bench     -> ben.commands.auto",   # R-08 删除
]
```

三条的现状与意图：

| 契约 | 今天 | 谁修 |
|---|---|---|
| core 不依赖上层 | ✅ 绿 | — |
| agents 不依赖 commands | ❌ `factory.py:9` 从 `commands.util` 取 `parse_from`（领域层反向依赖命令层） | R-08 |
| 命令模块互不 import | ❌ `misc` / `commander` / `bench` 三处 `from ben.commands.auto import _args, format_time_budget` | R-08 |

后两条**先用 `ignore_imports` 逐条豁免**（不是整条关掉）——豁免行就是待办清单，R-08 完成时删掉三行，契约自动收紧闭环。这比"等修好了再上规则"多一个好处：**豁免列表进 diff，review 时看得见**。

`cli.py` 与 `__init__.py` 引 `cmd_auto` 不算违规（入口与导出枢纽本来就该知道所有命令），所以 `source_modules` 只写 `ben.commands`。

### R-07 Store 写路径（`get_fact` 逐 id，不放宽语义）

现状：`add_intent` → `_validate_from` → `list_facts()`（glob 全目录 + 逐个 json.load + schema 校验），且**发生在 `with self.locked()` 之内** —— 不只是慢，多 worker 并行会被串行化。

改法：`existing = {f["id"] for f in self.list_facts()}` → 对每个 `fid` 调 `self.get_fact(fid)`。`get_fact` 走 `_read_node` → schema 校验，**语义一点没放宽**（这点比 v2 原方案的 `_has_fact` 更干净）。

验收：

```
200 facts → 写 100 intents      当前 12.30 s     目标 < 1.0 s
tests/test_perf.py（BEN_PERF=1 才跑，阈值 1.0 s 只挡 10× 级回退）
```

### R-08 dispatch 归一（独占窗口，不夹带别的）

抽出 `ben/agents/dispatch.py`，三个动词一组：

```
dispatch_reason(store, cfg) -> DispatchResult
dispatch_explore(...)
dispatch_verify(...)
```

- `factory._dispatch_*`（91 行，打印版）与 `auto._run_*_raw`（65 行，返回版）合并为一份，返回结构体，由调用方决定 print 还是 return；
- 同时把 `factory.py:9` 的 `from ben.commands.util import parse_from` 反向依赖拆掉（`parse_from` 移入 `core/parse.py`）；
- `commander.py` 的 `run_claude` + `extract_json_object` 直接调用**不在本轮范围**，加一行 `NOTE` 标注为已知例外，避免验收误判通过。

验收：

```bash
grep -c "_dispatch_" ben/agents/factory.py                    # 0（已迁出）
grep -rn "from ben.commands.auto import _" ben | wc -l        # 0（不再吃私有符号）
lint-imports                                                  # 3 contracts kept, 4 ignores → 0
python -m pytest -q                                           # 全绿
```

---

## 6. W3 之后：其余 6 条（按投入产出排）

### R-09 私有符号收口（跟在 R-08 后面，趁热）

现状 **29 条 / 52 个符号**。`auto.py:8` 一行吃 8 个、`dispatch.py:7` 一行吃 5 个 —— 全是 R-08 迁走的函数。

做法：每个包写 `__all__`；跨包只 import 公开名；`ruff select = ["PLC2701"]` + `per-file-ignores`（`ben/core/*`、`ben/llm/*` 同层豁免）。白名单本身就是架构声明。

验收：`ruff check ben --select PLC2701` → 0；`grep -c "import _" ben/commands/auto.py` → 0。

### R-10 hook 启动税（207 ms → < 80 ms 边际）

两刀，按收益排：

1. **`_date_context` 从 `subprocess date` 改为 `datetime.now()`** —— 省一次进程 spawn，约 60 ms，零风险；
2. **渲染器下沉**：`render_status` / `render_history_block` 移到 `ben/report/brief.py`，hook 只依赖它 —— 让 hook 不再 `import ben`（29 处 re-export，边际 191 ms）。

> 这里不采纳"hook 直接读裸 JSON"：`render_status` 要算 frontier、`render_history_block` 要排序截断，重写一遍就是把"两份实现"变成"三份"。

验收：12 次交错测量中位数，边际 207 → < 80 ms（约省 2.5 s / 20 轮）。

### R-11 `--run` 运行时验证

`ben verify --intent i042 --run` 真跑三条冒烟并捕获退出码：

```
ben status / ben graph / ben dispatch reason --dry-run
```

产物 `smoke.json` 记录 `argv / exit / stderr 前 40 行`。
验收：在 `render_status` 里注入 `raise` → `verify --run` 必须 exit 1 且 `smoke.json` 带堆栈。

### R-12 JSONL 运行轨迹（**不是**把 201 处 print 换 logging）

`ben/core/log.py` 约 40 行，`run_event(kind, **fields)` 追加一行 JSONL 到 `runs/<graph>/logs/`。写点 6 处：dispatch 开始/结束、verify 每次 check、claim/release、worker 启停、模型调用、异常捕获。

验收：`jq -c . runs/*/logs/*.jsonl` 无解析错误；一次 `ben auto --max-steps 1` 至少 5 类事件。

### R-13 执行器提示词外置（残余）

`agents/factory.py:25` 的 1607 字符系统提示词里，CLI 用法清单是静态的，可移到 `ben/agents/prompts/executor.md`；只保留 `store.root` 这类动态插值。

验收：`factory.py` 内不再有 > 1200 字符的字符串常量。

### R-14 权限矩阵 + docs 分层（两条独立小活）

**权限矩阵**（`.ben/roles.json`，零依赖）：

```json
{"worker":    {"writable": ["ben/**","tests/**"], "forbidden": ["ben/core/store.py"]},
 "commander": {"writable": [".ben/**","runs/**"], "forbidden": ["ben/**"]}}
```

生效点只有一处：`done` 校验 `git diff --name-only <sha>..HEAD` 全在 writable 内。越界拒绝，`--force` 留痕。**不做内核级沙箱。**

**docs 分层**：`plans/`（本文件 + v3；v1/v2 进 `plans/archive/`）、`research/`、`reports/` + `INDEX.md`；
配套 `arch_check --check docs_links`（**当前会红 18 条**，全在两个 README 的 6 张缺失配图与 `tmux-removal-plan-v3.md`）——先落检查、再修 README、红转绿。

---

## 7. 被我判定为「不必做」的（v3 里还留着的）

| 旧编号 | 为什么不做 |
|---|---|
| v3 V3 Pyright | 307 函数参数标注 59%、返回 93%。要开 `basic` 先得补 118 个标注，半天收益是一个"通过"的灯。等 R-08 把 `factory`/`auto` 合并后标注量自然下降一半，那时再做。 |
| v3 V6 Hypothesis | 6 条不变量里，4 条（from 可解析、to/status 一致、confirm 拒绝、conclude 双向一致）用普通 pytest 就能写，且现有 128 个测试已覆盖大部分。为"属性测试"引入 dev 依赖，收益不抵维护成本。**改：把 6 条不变量写成普通用例，不装 hypothesis。** |
| v2 §6.2 cli 拆分 | `build_parser` 481 行 / 35 个子命令，读起来难受，但它是**纯声明**，没有逻辑，拆成 35 个 `register(sub)` 只是把 481 行变成 35 个小函数 + 一张注册表。等真的出现合并冲突再做。 |
| v2 §6.3 `DispatchContext` | R-08 的返回结构体已经覆盖它的用途（统一参数打包）。单独再造一个 Context 类，是在归一完成前猜接口。 |
| v2 §6.5 commander 收口 | R-08 会给它留 `NOTE` 例外。真正的收口要等 `commander` 的 5 个私有符号（`commands.fleet`）一起处理，属于 R-09 的尾巴。 |

---

## 8. 排期（按依赖，不按周）

```
今天     R-01 lab 出索引          ← 1 条命令
今天     R-02 你拍板 A/B/C + 凭证处置
────────────────────────────────────────
W1       R-03 证据闸门            ← 不依赖任何东西，可立即开工
W2       R-04 pyproject → R-05 CI → R-06 三条契约（2 条带 ignore，R-08 后清零）
W2       R-07 Store（与 R-06 并行，面小）
W3       R-08 dispatch 归一（独占，留足回归窗口）
W3       R-09 私有符号（紧跟 R-08，同一批代码）
────────────────────────────────────────
W4       R-10 hook / R-13 提示词 / R-14 docs 分层（互不依赖，可并行）
W5       R-11 --run → R-12 JSONL（后者要前者的产物目录）
W5       R-14 权限矩阵
```

两条硬约束：**R-03 必须早于 R-11**（没证据目录，`--run` 的结果没处放）；**R-09 必须紧跟 R-08**（那 13 个符号是同一批代码，隔一周上下文就凉）。

---

## 9. 验收总表（全部机器可判）

| ID | 命令 | 期望 |
|---|---|---|
| R-01 | `git ls-files lab \| wc -l` | 0 |
| R-03 | `ben done i001 --fact x` | exit 1 |
| R-03 | `ben done i001 --fact x --force` | `fact.data.forced == true` |
| R-04 | `ruff check ben tests` | 0 issue |
| R-05 | `bash scripts/ci/preflight.sh` | exit 0，且 ruff 段不再 skipping |
| R-06 | `lint-imports` | 3 contracts kept；`ignore_imports` 4 条在 R-08 后清零 |
| R-07 | `BEN_PERF=1 pytest tests/test_perf.py` | 100 intents < 1.0 s |
| R-08 | `grep -c "_dispatch_" ben/agents/factory.py` | 0 |
| R-09 | `ruff check ben --select PLC2701` | 0 issue |
| R-10 | 12 次交错测量中位数 | 边际 < 80 ms |
| R-11 | 注入 `raise` 后 `verify --run` | exit 1 且 `smoke.json` 有堆栈 |
| R-12 | `jq -c . runs/*/logs/*.jsonl` | 无解析错误 |
| R-13 | AST 扫描 `agents/` 最长字符串常量 | < 1200 字符 |
| R-14 | `arch_check --check docs_links` | 0（当前 18） |

---

## 10. 不做清单（继承 + 新增）

继承 v2/v3 且仍然有效：

- 不引入 `TaskManager` / `Logger` 空壳抽象（`Store.claim_intent` 已是唯一入口）。
- 不把 201 处 `print` 换成 `logging`（其中多数是产品输出，被 hook 与 3 个契约测试断言）。
- 不做容器级沙箱、不做 AST 级权限（R-14 只到 diff 路径粒度）。
- 不封死"手改 `.ben/*.json`"——那是故障现场的救急通道，要防的是"篡改后仍算完成"，由 R-03 的 sha 校验兜住。
- 不写没有 `Enforced-by` 的 ADR。

新增：

- 不为凑清单引入 Pyright / Hypothesis（§7）。
- 不在 R-08 那一轮夹带 CLI 拆分或权限矩阵。
- 不重写 v1/v2/v3 —— 它们是历史记录，只加一行"已被 v4 取代"。
