# ben 优化方案 v3 —— AI 无关的代码质量体系：差距清单

> ⚠️ **部分条目已落地，未完成项已迁至 `plans/OPTIMIZATION-PLAN-v4.md`**（2026-11-18 10:30）。本文件保留为历史记录：v4 §1 列出哪些条目已完成并作废，§2 起是剩余 14 条。**执行请以 v4 为准，不要按本文件的排期表动手。**

> 基线：2026-11-18 09:10，`/home/kali/Desktop/AI/BenProject`（`refactor/structure` @ ff73143）
> 关系：**v2 修「代码本身」，v3 建「约束代码的闸门」**。v2 仍有效，v3 只补 v2 没覆盖的部分，不重复。
> 方法：清单里每一条都先在代码里找证据，再判 ✅/⚠️/❌。判定带路径行号，可复核。

---

## 0. 一句话结论

按你这份 54 项清单逐条核对：**满足 3 项（6%）、部分满足 21 项（39%）、缺失 30 项（56%）**。

但缺的不是「30 个零散功能」，是**一条链断了**：

```
Agent 说"我做完了" → ben done 落一个 fact      ← 这里没有任何校验
                     ↑
        本应是：verify 产出证据 → 校验证据 → 才允许落 fact
```

`ben/commands/dispatch.py:31-40` 的 `cmd_done` 直接调 `conclude_with_new_fact()`，**不检查测试、不检查 diff、不检查证据**。所以清单 P0 的最后两条（"检查失败不能标记完成"、"不允许 Agent 自宣测试通过而无证据"）不是缺失，是**被架构性地允许了**。

v3 的第一优先级因此不是「加 CI」（CI 管人），而是**把证据变成 `ben done` 的前置条件**（闸门管 Agent）。这一条做完，P0-3、P2-1、P2-2、P3-2 会连带成立——因为它们都只是同一条链的不同说法。

---

## 0.5 P4 落地状态（2026-11-18）

P4「长期治理」7 项已全部落地，验证方式如下（全部可复跑）：

| P4 项 | 落地物 | 验证 | 状态 |
|---|---|---|---|
| 定期清理废弃代码 | 删 `payloads.cpython-314.pyc`；扫描 124 个模块级私有函数，0 个无引用 | `arch_check --check orphans` | ✅ |
| 删除重复实现 | 分词器合并为 `ben/core/text.py`（原本 `recall` 与 `kb` 各一份）；`kb._now_iso` 合并到 `core.io.now_iso` | `arch_check --check duplicates` | ✅（dispatch 双实现仍待 v2 §4 处理） |
| 统一历史遗留接口 | `fg-hook` → `ben-hook`（6 处，含 stderr 文案） | `grep -r fg-hook scripts ben` | ✅ |
| 清理过时注释 | 12 处外部评审编号内联化，理由写回注释；编号存档于 `docs/reviews/INDEX.md` | `arch_check --check stale_refs` | ✅ |
| 记录架构决策 | `docs/adr/0001–0005`，每篇带 `Enforced-by` 指向一条真实检查 | `ls docs/adr` | ✅ |
| 重复错误→自动化规则 | `scripts/ci/arch_check.py` 八项检查 + `scripts/ci/preflight.sh` | `bash scripts/ci/preflight.sh` | ✅ |
| AGENTS.md 不膨胀 | `_AGENTS_SPEC` 增加 rule budget 段（生成物同步），上限 60 行并受检查约束 | `arch_check --check agents_budget` | ✅ |

### 追加：运行时输出收敛到单一根目录（2026-11-18）

「生成物写哪儿」原本没有规定，于是仓库根同时长出 `runs/`、`logs/`、`console/`、
`workers.json`、`ben-graph.html`，最终一次靶场评估的 3.9 MB 产物里 2.7 MB 进了
git 索引。现在：

* 唯一根：`<base>/runs/`，名字只在 `ben/core/paths.py` 出现一次，`BEN_RUNTIME_DIR` 可覆盖；
* 12 个调用点改为走 `paths.*`（`cli` / `fleet` / `commander` / `peers` / `web` / `runtime.console`）；
* 检查：`arch_check --check runtime_paths`（字面量 + `.gitignore` 两半），ADR `0006`。

这条同时是 P0-A（仓库止血）的**结构性前提**——没有单一根目录，`.gitignore` 就只能
一条条追着目录名写。

关键性质：**落地后 baseline 为空**（`arch_baseline.json` 不存在），即没有冻结任何存量问题。
每条检查都做过「先红一次」的反证——例如在 `ben/kb/` 追加一份分词器，`duplicates` 立刻报 100% 相同。

---

## 1. 对照总表

### P0 基础代码质量控制（12 项：✅1 / ⚠️3 / ❌8）

| 清单项 | 判定 | 证据 | 归属 |
|---|---|---|---|
| Ruff 统一格式与 lint | ❌ | 无 `pyproject.toml` / `ruff.toml` / `.ruff.toml`；`ruff` 未安装 | v2 §5.1 |
| Pyright 类型检查 | ❌ | 无任何类型检查配置。标注率：307 函数中参数全标注 182（59%），有返回标注 285（93%） | **V3** |
| 统一异常处理 | ⚠️ | `FGError` 体系完整；但 `bench.py` 4 处、`web/view.py` 4 处 `except Exception` 无理由标注 | v2 §7 |
| 统一日志 | ❌ | `import logging` **0 处**；`print(` **201 处**。运行时轨迹只有 worker 的 `.log` 裸 stdout | **V5** |
| 统一命名 | ⚠️ | 主体一致（snake_case、按域分包）；残留 `fg-hook`/`fg` 前缀（sapper 时代）、`DEFAULT_STORE` 语义漂移 | **V9** |
| 减少重复实现 | ❌ | dispatch 三动词双实现（`factory._dispatch_*` ↔ `auto._run_*_raw`） | v2 §4 |
| 使用 pytest | ✅ | 78 passed / 3 skipped，1,491 行 | — |
| 核心模块单元测试 | ⚠️ | `core/` 覆盖好；`llm/runner`、`runtime/agents` 薄；单文件 1,402 行 19 类难定位 | v2 §7 |
| 调度/认领/释放必须有测试 | ⚠️ | 有 `test_pick_claim_skips_another_workers_lease` 等 9 个相关用例；**缺**租约过期、并发双认领、release 幂等 | **V6** |
| 测试失败禁止提交 | ❌ | 无 `.github/`、无 pre-commit、无 Makefile | v2 §5.4 |
| 所有 Agent 修改过质量检查 | ❌ | 无闸门。Agent 可直接 `ben done` | **V1** |
| 检查失败不能标记完成 | ❌ | `cmd_done` 无任何前置校验（`commands/dispatch.py:31`） | **V1** |
| 保存检查结果与失败原因 | ❌ | 无 `runs/verify/` 机制，`runs/logs/` 为空 | **V1/V4** |
| 不允许自宣通过而无证据 | ❌ | fact 的 `doc`/`data` 字段本来能存证据，但 `done` 不要求 | **V1** |

### P1 架构约束（13 项：✅1 / ⚠️5 / ❌7）

| 清单项 | 判定 | 证据 | 归属 |
|---|---|---|---|
| Import Linter | ❌ | 未安装、无配置 | v2 §5.2 |
| 明确 agents/core/tools/security 依赖 | ⚠️ | 目录存在（`core/ agents/ tools/ ...`）；**无 `security/` 模块**；依赖关系只在人脑里 | v2 §5.2 |
| 禁止越权访问模块内部实现 | ❌ | **排除 `__init__` 后仍有 30 条 import 语句吃进 53 个私有符号**。最重：`commands/auto.py:8` 一行 8 个 `_` 符号、`commands/dispatch.py:7` 一行 5 个 | **V2** |
| 禁止循环依赖 | ❌ | 未检查。已知一处方向反常：`agents/factory.py:9` ← `commands.util`（领域层依赖命令层） | v2 §4.2 |
| Agent 创建统一通过 Factory | ⚠️ | 有 `agents/factory.py`，但它造的是「一次 LLM 调用」而非 Agent 对象；worker 进程由 `runtime/agents.py` 直接 `Popen` | 语义等价，见 §7 |
| 认领统一通过 TaskManager | ✅ | 无 TaskManager 类，但**单一入口已达成**：`Store.claim_intent` / `release_intent`（`core/store.py:418/433`），且有 lease 校验 | — |
| 状态修改统一接口 | ⚠️ | 主路径走 Store；但 `save_intent(intent: dict)` 接受整 dict 覆盖，可绕过状态机 | **V2** |
| 日志统一 Logger | ❌ | 同 P0 | **V5** |
| 禁止绕过核心接口改底层状态 | ⚠️ | 代码层可以管；文件层管不住——`.ben/*.json` 直接手改仍生效（这本身是特性，不该封死） | 不采纳，见 §7 |
| 检查文件放置正确 | ❌ | 无检查 | **V7** |
| 检查模块违反职责边界 | ❌ | 无检查 | v2 §5.2 |
| 检查重复定义/废弃接口 | ❌ | 无检查。已知孤儿：`ben/commands/payloads.pyc`（源码已删） | **V7** |
| 检查新模块符合架构规范 | ❌ | 无检查 | **V7** |

### P2 运行时验证（12 项：✅0 / ⚠️6 / ❌6）

| 清单项 | 判定 | 证据 | 归属 |
|---|---|---|---|
| AI 改代码后必须实际运行 | ❌ | `verify` 动词是**模型自评**（`_parse_verify_payload` 检查 issues 列表），不是执行代码 | **V4** |
| 验证功能符合预期 | ⚠️ | 同上，靠模型叙述 | **V4** |
| 验证异常处理有效 | ⚠️ | 测试覆盖部分，无故障注入 | **V6** |
| 验证并发任务正常 | ⚠️ | fleet 有单测，无并发压测/竞态用例 | **V6** |
| 验证资源正确释放 | ⚠️ | `locked()` 用 `with`，但无「锁未释放」「临时文件残留」用例 | **V6** |
| 保存 pytest 报告 | ❌ | 无 | **V1** |
| 保存运行日志 | ⚠️ | `runs/<graph>/logs/c-demo.host.err` 有，格式为裸 stdout | **V5** |
| 保存失败堆栈 | ⚠️ | 混在裸 stdout 里，不可结构化查询 | **V5** |
| 保存关键功能验证结果 | ❌ | 无 | **V4** |
| 可追溯到具体 Agent 与代码版本 | ⚠️ | Agent 有（`fact.creator`）；**代码版本没有**——worker 记录里无 git sha、无 model 名 | **V1** |
| Hypothesis 属性测试 | ❌ | 未引入 | **V6** |
| 状态转换/并发/回滚/幂等测试 | ❌ | 无 | **V6** |

### P3 Agent 协作（10 项：✅1 / ⚠️3 / ❌6）

| 清单项 | 判定 | 证据 | 归属 |
|---|---|---|---|
| 明确每个 Agent 可改模块 | ❌ | `AGENTS.md` 是通用规则，无按角色的写权限 | **V8** |
| 限制跨模块修改 | ❌ | 无 | **V8** |
| 高风险修改需人工审批 | ✅ | `requires_confirmation` 真接线了：未确认时**禁止认领**（`store.py:423`）、**禁止结论**（`store.py:450`） | — |
| 自动收集质量失败信息 | ❌ | 无质量检查，无从收集 | **V1** |
| 将错误反馈给对应 Agent | ❌ | 无 | **V1** |
| 允许 Agent 修复并重测 | ⚠️ | `auto` 有循环，但不是质检驱动 | **V1**（校验失败即 fact 未产出 → intent 仍开着 → 自然重试） |
| 限制自动修复次数 | ✅ | `max_steps` + `noop_streak>=2` 双重刹车（`auto.py:76,136`） | — |
| 检查变更范围/架构影响/安全风险 | ❌ | 无 | **V8** |
| 关键修改人工审核 | ⚠️ | 有 `confirm` 机制，但没和「改动风险」挂钩 | **V8** |

### P4 长期治理（7 项：✅0 / ⚠️4 / ❌3）

| 清单项 | 判定 | 证据 | 归属 |
|---|---|---|---|
| 定期清理废弃代码 | ⚠️ | 孤儿 `payloads.pyc`；`--include` 类死参数未扫 | **V7** |
| 删除重复实现 | ❌ | 同 P0 | v2 §4 |
| 统一历史遗留接口 | ⚠️ | `fg-hook` 文件名与 `fg` 前缀、`DEFAULT_STORE` 术语 | **V9** |
| 清理过时注释/错误示例 | ❌ | 代码里有 `review H2`/`review L5`/`codex#5` 之类引用，指向的评审记录不在仓库里 | **V9** |
| 记录架构决策（ADR） | ❌ | `docs/` 有 CHANGELOG/BATTLE-REPORT，无 ADR | **V9** |
| 重复错误→自动化规则 | ❌ | v2 §5 只覆盖了 3 类 | v2 §5 + **V7** |
| 持续维护 AGENTS.md | ⚠️ | 40 行，克制；但无「规则预算」，会慢慢膨胀 | **V9** |

**合计：54 项 → ✅ 3 / ⚠️ 21 / ❌ 30。**

---

## 2. 已经满足的，不要重复建设

这 5 项如果照着清单再做一遍，是纯粹的税：

1. **pytest 体系**（78 passed）——不需要引入别的框架。
2. **认领/释放的单一入口**——`Store.claim_intent/release_intent` + lease 校验，比新造一个 `TaskManager` 类更可靠（见 §7）。
3. **`requires_confirmation` 人工审批**——`store.py:423` 未确认禁止认领、`450` 未确认禁止结论。这是真接线，不是摆设。清单 P3 的"高风险人工审批"已满足，缺的只是"什么算高风险"。
4. **自动循环的刹车**——`max_steps` + `noop_streak`，清单 P3"限制修复次数"已满足。
5. **fact-graph 本身就是证据系统**——`fact.doc` 存详细文档、`fact.data` 存结构化键值、`source_intent` 存溯源。**v3 的所有证据机制都应复用它，而不是新建一套**。这是本方案能零依赖落地的根本原因。

---

## 3. V1（最高优先）证据闸门：让「完成」需要凭证

### 3.1 现状：一句话就能宣布完工

```python
# ben/commands/dispatch.py:31-40
def cmd_done(args) -> int:
    store = Store(Path(args.store))
    store.require()
    fact, intent = store.conclude_with_new_fact(
        args.id, args.fact, args.worker, ...)      # ← 无任何校验
```

Agent 只要敲一行 `ben done i042 --fact "改好了"`，intent 就关闭、fact 就落库、frontier 就往下走。**清单 P0 后两条、P2-2、P3-2 全都卡在这一行。**

### 3.2 改法：`verify` 出证据 → `done` 验证据

**第一步：`ben verify` 产出结构化证据**（v2 §5.3 的加强版）

```bash
$ ben verify --intent i042
✓ ruff      ben/ 44 files, 0 issues
✓ imports   2 contracts kept
✓ pytest    78 passed, 3 skipped
✓ graph     validate: 0 errors
evidence → runs/<graph>/verify/20261118-0912/report.json
```

```json
{
  "intent": "i042",
  "sha": "ff73143",
  "dirty": false,
  "started_at": "2026-11-18T09:12:03+08:00",
  "checks": [
    {"name": "ruff",    "cmd": "ruff check ben tests", "exit": 0, "tail": ""},
    {"name": "imports", "cmd": "lint-imports",          "exit": 0, "tail": ""},
    {"name": "pytest",  "cmd": "pytest -q",             "exit": 0, "tail": "78 passed, 3 skipped"},
    {"name": "graph",   "cmd": "ben validate",          "exit": 0, "tail": "0 errors"}
  ],
  "exit": 0
}
```

**第二步：`ben done` 把它变成前置条件**

```python
def cmd_done(args) -> int:
    ...
    ev = _load_evidence(args.evidence)          # 读 report.json
    _check_evidence(ev, intent=args.id, head=_git_sha(), allow_dirty=False)
    # 四条硬规则：
    #  1) ev["exit"] == 0
    #  2) ev["intent"] == args.id        ← 防止拿别人的报告交差
    #  3) ev["sha"] == 当前 HEAD        ← 防止"测完又改了"
    #  4) 任一 check 的 exit != 0 → 拒绝
    fact, intent = store.conclude_with_new_fact(
        ..., data={**parse_kv_pairs(args.data), "evidence": ev["path"], "sha": ev["sha"], "model": args.model})
```

`--force` 保留（人会需要），但强制写 `data.forced=true` + 一条 hint 到图上——**绕过留痕**，而不是直接禁死。

### 3.3 为什么这比"加 CI"更关键

| | CI | 证据闸门 |
|---|---|---|
| 管谁 | 人（push 时） | Agent（每一步） |
| 失败后果 | PR 红，人看一眼 | intent 关不掉，frontier 不动 |
| 能否绕过 | `--no-verify` / 直接 push main | 只能 `--force`，且留痕 |
| 覆盖清单 | P0 部分 | P0-3 / P2-1 / P2-2 / P3-2 全部 |

而且它**顺手解决了"追溯到具体 Agent 和代码版本"**：`fact.data` 里同时有 `evidence`（路径）、`sha`（代码版本）、`model`（模型）、`fact.creator`（Agent）。零新存储格式。

### 3.4 验收

```bash
# 无证据必须被拒
ben done i042 --fact "x"                         # → exit 1: 缺少 --evidence
# 证据 sha 与工作区不一致必须被拒
ben verify --intent i042 && git commit --allow-empty -m tmp && ben done i042 --fact "x" --evidence <旧路径>
#                                                  → exit 1: sha 不匹配（ff73143 ≠ 新 HEAD）
# 证据属于别的 intent 必须被拒
ben done i043 --fact "x" --evidence runs/.../i042 → exit 1
# 强制绕过必须留痕
ben done i042 --fact "x" --force                  # → fact.data.forced == true，且多一条 hint
```

---

## 4. V2 公开面治理：53 个私有符号在跨模块乱窜

### 4.1 证据

排除 `ben/__init__.py`（导出枢纽，另算）后：

| 引用方 | 被引用模块 | 私有符号数 |
|---|---|---|
| `commands/auto.py:8` | `agents.factory` | **8** |
| `commands/dispatch.py:7` | `agents.factory` | **5** |
| `commands/commander.py:14` | `commands.fleet` | 5 |
| `llm/llm.py:11` | `llm.keys` | 4 |
| `core/store.py:12` | `core.schema` | 3 |
| 其余 25 条 | — | 28 |
| **合计** | | **30 条语句 / 53 个符号** |

清单 P1「禁止越权访问其他模块内部实现」在这里是**硬性不满足**。而 `auto.py` 那 8 个符号，正是 v2 §4 要归一的 dispatch 逻辑——**两件事是同一件事**。

### 4.2 改法：三层收口，一条规则守住

1. **每个包声明 `__all__`**（显式公开面）；
2. **跨包只能 import 公开名**，包内不受限（`core.schema` → `core.store` 属同一层，允许）；
3. **机器检查**：ruff 的 `PLC2701`（private-name-imported）+ per-file-ignores 白名单同层引用：

```toml
[tool.ruff.lint]
select = ["PLC2701"]

[tool.ruff.lint.per-file-ignores]
"ben/core/*" = ["PLC2701"]        # core 内部 io/schema/graph 互为实现细节
"ben/llm/*"  = ["PLC2701"]        # keys/jsonx/runner 是同一层
```

第 3 条的白名单本身就是**架构声明**：一旦有人把 `agents` 加进去，diff 里看得见。

### 4.3 验收

```bash
ruff check ben --select PLC2701                    # 白名单外 0 issue
grep -c "^from ben\..* import _" <(git show HEAD:ben/commands/auto.py)   # 归一后应为 0
```

---

## 5. V3–V9 其余新增

### V3 Pyright 渐进（P0，但排在 V1 之后）

数据决定策略：参数全标注 **59%**、返回标注 **93%**。直接开 strict 会一次喷出几百条，人只会关掉它。

```toml
# pyrightconfig.json
{
  "include": ["ben"],
  "exclude": ["ben/commands", "ben/web"],
  "typeCheckingMode": "basic",
  "reportMissingTypeStubs": "none",
  "executionEnvironments": [
    {"root": "ben/core",   "typeCheckingMode": "standard"},
    {"root": "ben/agents", "typeCheckingMode": "standard"}
  ]
}
```

顺序：先补 `core/` + `agents/` 的 118 个未标注参数（约半天）→ 开 `basic` → CI 只跑这两个目录 → 稳定后再纳入 `commands/`。

验收：`pyright` 在 `ben/core ben/agents` 上 0 error；`ben done` 的 evidence 里多一行 `pyright` check。

### V4 运行时验证（P2-1 的真实含义）

`verify` 现在验的是「模型说没问题」。V4 加 `--run`：真执行三条冒烟命令并捕获退出码/异常。

```bash
ben verify --intent i042 --run
# + smoke   ben status        exit 0
# + smoke   ben graph         exit 0 (2.1 KB)
# + smoke   ben dispatch reason --dry-run  exit 0
```

产物仍落 `runs/<graph>/verify/<ts>/`，其中 `smoke.json` 记录每条命令的 `argv / exit / stderr 前 40 行`。

验收：故意在 `render_status` 里抛异常 → `ben verify --run` 必须 `exit 1` 且 `smoke.json` 里带堆栈。

### V5 日志分层（不是"把 print 换成 logging"）

先纠正一个前提：**这个项目里 201 处 `print` 大部分不是日志，是产品输出**。`ben graph` 的 stdout 被 hook 消费、被 3 个 CLI 契约测试断言。把它们换成 `logging` 会同时破坏用户可见性和测试。

所以只补「运行时轨迹」这一层：

```python
# ben/core/log.py  ~40 行
def run_event(kind: str, **fields) -> None:
    """追加一行 JSONL 到 runs/<graph>/logs/<worker|cmd>.jsonl"""
```

写点固定在 6 处：dispatch 开始/结束、verify 每次 check、claim/release、worker 启动/退出、模型调用（model/timeout/token/耗时）、异常捕获点。

验收：`runs/<graph>/logs/*.jsonl` 每行 `json.loads` 成功，且一次 `ben auto --max-steps 1` 至少产出 5 类事件。

### V6 属性测试（Hypothesis，dev-only）

`dev` 依赖里加 `hypothesis>=6`，**不进主干**（`dependencies` 仍为空）。六条不变量：

| # | 不变量 | 反例它一定能抓到 |
|---|---|---|
| 1 | 任何 intent 的 `from` 都指向存在的 fact | 并发删/改 |
| 2 | `intent.to != null ⇒ status == "done"` | 半写状态 |
| 3 | `requires_confirmation` 未确认 ⇒ claim 必失败 | 权限绕过 |
| 4 | 同一 intent 不能同时被两个 worker 持有 | 双认领竞态 |
| 5 | `release` 重复调用幂等 | 补偿逻辑重复执行 |
| 6 | `conclude_with_new_fact` 后 `fact.source_intent == intent.id` 且 `intent.to == fact.id` | 双向不一致 |

用例形态：

```python
@given(st.lists(st.sampled_from(["f001","f002","goal"]), min_size=1, max_size=4))
def test_from_always_resolvable(from_ids):
    ...
```

验收：6 条全绿；把 `claim_intent` 里的 lease 判断注释掉，第 4 条必须红——**规则要先能红**。

### V7 架构自动检查（已落地，见 §0.5）

四项，各自独立可跑：

| 检查 | 判据 | 当前会不会红 |
|---|---|---|
| 文件放置 | `ben/<pkg>/*.py` 只允许出现在 `docs/ARCH.md` 登记的包 | 不会（先登记现状） |
| 重复定义 | 不同文件里同名函数，函数体 AST md5 相同且 >5 行 | **会红**（dispatch 双实现） |
| 废弃接口 | 标了 `@deprecated` 或 `# DEPRECATED:` 且调用点为 0 | 不会 |
| 孤儿产物 | `*.pyc` 无对应 `.py` | **会红**（`payloads.pyc`） |

验收：脚本跑在 HEAD 上红 2 项；清理后 0 项。

### V8 权限矩阵与 review 清单（P3）

`.ben/roles.json`（零依赖，复用现有 `.ben/` 布局）：

```json
{
  "worker":    {"writable": ["ben/**", "tests/**"], "forbidden": [".github/**", "ben/core/store.py"]},
  "commander": {"writable": [".ben/**", "runs/**"], "forbidden": ["ben/**"]}
}
```

生效点只有一处：`ben done` 校验 `git diff --name-only <sha>..HEAD` 是否全在 `writable` 内、且不在 `forbidden` 内。越界则拒绝，除非 `--force`（留痕）。**不做内核级沙箱**——那是另一个量级的工程。

Review 清单（`docs/REVIEW.md`，5 条，每 PR 勾选）：变更范围 / 架构影响 / 安全面 / 重复实现 / 证据齐全。

### V9 ADR 与规则预算（已落地，见 §0.5）

`docs/adr/NNNN-<slug>.md`，四个字段：

```markdown
## Context
## Decision
## Consequences
## Enforced-by     ← 关键字段：必须指向一条检查（contract 名 / ruff 规则 / CI 步骤）
```

**没有 `Enforced-by` 的 ADR 不允许合入**——否则 ADR 会退化成文档堆积，正是本项目一直在避免的。

规则预算：`AGENTS.md` ≤ 60 行；每条规则末尾标 `[enforced: <检查名>]` 或 `[judgment]`。超过 60 行必须先删一条再加一条。

---

## 6. 不建议照做的 4 条（附理由）

| 清单项 | 为什么不做 | 替代 |
|---|---|---|
| 引入 `TaskManager` 类 | `Store.claim_intent/release_intent` 已是唯一入口且有 lease 校验。加一层壳只会让"两处都能改状态" | 保留 Store，加 V2 的 `save_intent` 收口 |
| 统一 Logger 替换 print | 201 处 print 里多数是**产品输出**（被 hook 消费、被契约测试断言）。替换会破坏用户可见性 | V5：只给运行轨迹加 JSONL |
| Pyright `strict` 全仓 | 59% 参数标注下会一次喷几百条，结果是团队关掉它 | V3：`basic` + 按目录 `standard` |
| P3 全自动「失败→反馈→重试」链路 | 回路已有（`auto` 循环 + `max_steps`），缺的是**证据**不是回路。先做 V1，回路自动成立 | V1 |

还有一条**明确不做**：不封死"手改 `.ben/*.json`"。这是本项目的调试与救急通道，封死会让故障现场无法修复。要防的是"Agent 篡改后仍算完成"，那由 V1 的 sha 校验兜住。

---

## 7. 排期（插入 v2 时间线，不破坏 P0-C 独占窗口）

| 阶段 | v2 项 | v3 新增 |
|---|---|---|
| D1 | 仓库止血 + 决策 B + 门禁 | — |
| D2 | pyproject + ruff 首绿 | — |
| D3–D4 | P0-B Store 写路径 | **V1 证据闸门**（与 Store 无耦合，可并行） |
| D5–D6 | **P0-C dispatch 归一（独占）** | — |
| D7 | 分层契约 + `ben verify` + CI | V1 的 `report.json` 格式在此定型 |
| W2 | 渲染器下沉、cli 拆分 | **V2 公开面收口**（与 dispatch 归一同源，趁热做） |
| W2 | — | **V4 运行时验证**（`--run`） |
| W3 | — | **V3 Pyright**（补 118 个标注 + basic） |
| W3 | — | **V5 日志分层** |
| W4 | — | **V6 Hypothesis**（V7 arch_check 已于 2026-11-18 完成） |
| W5 | — | **V8 权限矩阵**（V9 ADR + 预算 已于 2026-11-18 完成） |

关键排序理由：**V1 必须早于 V4**（没有证据目录，`--run` 的结果没处放）；**V2 必须紧跟 P0-C**（那 13 个私有符号是同一批代码，隔一周就忘了上下文）；**V3/V5/V6 全部依赖 V1 的 `report.json`**——所以它们天然排在 D7 之后。

---

## 8. 验收总表（v3 新增项，全部机器可判）

| # | 断言 | 命令 | 期望 |
|---|---|---|---|
| V1-1 | 无证据不能完成 | `ben done i001 --fact x` | exit 1 |
| V1-2 | sha 不符被拒 | 改一个文件后拿旧报告跑 | exit 1，提示 sha 不匹配 |
| V1-3 | 跨 intent 借报告被拒 | `ben done i002 --evidence .../i001` | exit 1 |
| V1-4 | 强制绕过硬留痕 | `ben done ... --force` | `fact.data.forced == true` |
| V2-1 | 无私有符号越权 | `ruff check ben --select PLC2701` | 0 issue |
| V2-2 | auto 不再吃私有 API | `grep -c "import _" ben/commands/auto.py` | 0 |
| V3-1 | 类型检查通过 | `pyright ben/core ben/agents` | 0 error |
| V3-2 | 标注率 | AST 统计参数全标注比例 | ≥ 85%（当前 59%） |
| V4-1 | 冒烟能抓崩溃 | 注入 `raise` 后 `ben verify --run` | exit 1 且 `smoke.json` 有堆栈 |
| V5-1 | 轨迹可解析 | `jq -c . runs/*/logs/*.jsonl` | 无解析错误 |
| V6-1 | 不变量成立 | `pytest -m hypothesis` | 6 passed |
| V6-2 | 规则能红 | 注释掉 lease 判断 | 第 4 条红 |
| V7-1 | 架构检查收敛 | `python scripts/ci/arch_check.py` | 0 项 |
| V8-1 | 越界写被拒 | commander 改 `ben/core/store.py` 后 `done` | exit 1 |
| V9-1 | ADR 有执行锚点 | `grep -L "Enforced-by" docs/adr/*.md` | 空 |

---

## 9. v3 不做清单

- 不新建一套测试框架、不换 pytest。
- 不引入 `TaskManager` / `Logger` 这类空壳抽象（§6）。
- 不做容器级沙箱、不做 AST 级权限（V8 只到 diff 路径粒度）。
- 不把 ADR 写成设计文档——`Enforced-by` 为空的一律不合入。
- 不为凑清单去改 201 处 `print`。

---

*本文件的 54 项判定均基于 2026-11-18 09:10 的代码实测（AST 统计 + 逐文件核对）。v2 的 P0-A/B/C 仍按原优先级执行，v3 只在 D3 起插入 V 项。*


> **Superseded by** [OPTIMIZATION-PLAN-v4.md](../OPTIMIZATION-PLAN-v4.md).

