# ben 代码优化方案

> ⚠️ **本文件已被 `plans/OPTIMIZATION-PLAN-v4.md` 取代**（2026-11-18）。v1 保留作对照：v2 修正了 6 处写法与 4 项数据勘误，见 v2 的 §0 与附录 B。落地请以 v2 为准。

> 基线：2026-11-18，`/home/kali/Desktop/AI/BenProject`（commit ff73143）
> 方法：先取证，再开方。每条结论都附可复现命令；每个改动都附一条**机器能判的验收**。

---

## 0. 一页结论

代码质量本身高于同类项目平均线：写入是 flock + `os.replace` 事务化的，PID 复用用 `/proc/<pid>/stat` 的 starttime 做过防伪，schema 校验和 prompt-injection 防护都到位。**问题不在"写得对不对"，而在"同一个意图有两份实现""每写一条都全量扫盘""没有任何自动护栏"**——也就是内循环正在缓慢产出熵，而唯一的质量闸门是人眼。

| # | 问题 | 证据 | 一句话改法 | 预期 |
|---|---|---|---|---|
| P0-1 | 一次 dispatch 有两份实现 | `agents/factory.py:51-169`（print 版）↔ `commands/auto.py:224-292`（return 版） | 抽 `agents/dispatch.py` 只留一份，命令层只负责打印 | 少 ~150 行，改协议只需改 1 处 |
| P0-2 | 写 intent 是 O(n²) | 200 facts 写 100 intents = **10.1 s** | `_validate_from` 别 `list_facts()`，只按 id 查存在性 | 10.1 s → < 0.5 s |
| P0-3 | 靶场残留进了 git | `fz.py` 硬编码 `http://117.72.199.2:3000`；`h.txt` 是 5 个答案 MD5；`recon/` 含 `.kdbx`、750 KB `package-lock.bak` | `.gitignore` + `git rm --cached` + 一条 grep 门禁 | 仓库 -3.5 MB，且不再泄漏靶标 |
| P1-1 | 每条命令都付 370 ms 启动税 | `import ben.core.store` = 384 ms（≈ `import ben`） | `ben/__init__.py` 停止全量 re-export | hook 379 ms → < 120 ms |
| P1-2 | `build_parser()` 单函数 473 行 | `ben/cli.py:30` | 拆成按命令组注册 | 每命令 < 20 行 |
| P1-3 | dispatch 系列 7–8 个位置参数 | 4 个函数 7×，2 个函数 8× | `DispatchContext` dataclass | 参数降到 2 |
| P1-4 | 执行器系统提示词内嵌 Python | `factory.py:21-50` 60 行字符串 | 搬到 `agents/prompts/executor_system.md` | 与其余提示词同源 |

---

## 1. 体检基线（可复现）

```bash
python -m pytest -q                    # → 78 passed, 3 skipped in 51.32 s
find ben -name "*.py" | xargs wc -l    # → 44 文件 8,214 行；tests 1,491 行
```

| 指标 | 实测值 | 复现方式 |
|---|---|---|
| 启动：`import ben` | 370 ms | `python -X importtime -c "import ben"` |
| 启动：`import ben.core.store` | 384 ms | 同上（**和全量 import 一样慢 → 被包初始化拖累**） |
| `ben status` 端到端 | 398 ms | 计时子进程 |
| Claude Code hook 每轮 | **379 ms** | `scripts/hooks/ben-hook.py userpromptsubmit` |
| `list_facts()` @ 200 facts | 83.6 ms/次 | 造临时图计时 |
| `frontier()` @ 200 facts | 133.4 ms | 同上 |
| 写 25 / 50 / 100 个 intent @ 50/100/200 facts | 0.7 / 2.9 / **10.1 s** | 同上（**每翻倍 ~3.5×**） |
| 全图读取调用点 | 21 处 | AST 扫描 `list_facts/list_intents/build_graph_view/frontier` |
| 模型调用汇聚点 | 9 处，全部经 `run_claude()` | `grep -rn "run_claude(" ben` |

两个数字值得单独说：

- **hook 379 ms × 一次对话 20 轮 ≈ 7.6 秒纯等待**，而 hook 本身只做一件事：读 `.ben/*.json` 拼一段文本。
- **写路径的 3.5 倍增长曲线**说明 `add_intent` 在做平方级工作。看代码确认：`Store.add_intent` → `_validate_from` → `self.list_facts()`（`core/store.py:200`），而 `list_facts` 会 glob 整个目录、逐个 `json.load`、逐个跑 `_node_schema_errors`。`_apply_reason` 一次提 3 个 intent，就是 4 次全量扫描。

---

## 2. P0（本周内做完，收益最大）

### P0-1 一次动作，两份实现

**证据**

| 能力 | 命令版（打印） | 循环版（返回） |
|---|---|---|
| reason | `factory._dispatch_reason` L51 | `auto._run_reason_raw` L224 |
| explore | `factory._dispatch_explore` L76 | `auto._run_explore_raw` L239 |
| verify | `factory._dispatch_verify` L125 | `auto._run_verify_raw` L279 |

两份逻辑一致：取模板 → 渲染 → `run_claude()` → `extract_json_object()` → 解析 → 写图。差别只有"打印还是返回"。代价是真实存在的：`verify` 的 `issues` 必须为空这条规则（`_parse_verify_payload` L469-472）只写在一个地方，另一个地方靠复用它；而 explore 的 `claim/release` 补偿逻辑只存在于 `_run_explore_raw`。

**改法**

新建 `ben/agents/dispatch.py`，只有 return，没有 print：

```python
@dataclass(frozen=True)
class DispatchContext:
    store: Store
    templates: Path
    model: str
    timeout: int
    skip: bool
    cwd: Path
    time_budget: str = ""

def run_reason(ctx, *, dry_run=False) -> tuple[str, str]: ...
def run_explore(ctx, intent, *, claim=False) -> dict: ...
def run_verify(ctx, intent) -> tuple[bool, str]: ...
```

`commands/dispatch.py` 和 `commands/auto.py` 都只做：构造 ctx → 调 `run_*` → 打印。**"打印什么"是表现层，"写什么图"是领域层，两者不该各存一份。**

**顺手拆掉一个反向依赖**：`agents/factory.py:9` 从 `commands.util` 导入 `parse_from`——领域层依赖命令层。把 `parse_from` / `_resolve_templates_dir` 移到 `ben/core/parse.py`，这是后面分层契约能立起来的前提。

**验收**
```bash
# 两份实现必须归一：auto.py 里不再出现 run_claude / extract_json_object
grep -c "run_claude\|extract_json_object" ben/commands/auto.py   # 期望 0
python -m pytest -q                                              # 78 passed 不变
```

---

### P0-2 Store 的写路径不再全量扫盘

**证据**：见第 1 节曲线。热点在 `core/store.py:195-206`：

```python
existing = {f["id"] for f in self.list_facts()}   # ← 读+解析+校验全部事实
for fid in fact_ids:
    if fid not in existing: raise FGError(...)
```

**改法**（三处，都只碰 `Store`，不动调用方）

1. `_validate_from` 不做集合预取，逐 id 走 `get_fact(fid)`——只解析 from 里出现的那几个（通常 1–3 个）；
2. 需要"是否存在"时用文件名，不解析内容：
   ```python
   def _has_fact(self, fid: str) -> bool:
       return (self.facts_dir / f"{fid}.json").is_file()
   ```
3. `_read_node_files` 加一层进程内缓存，键 `(path, st_mtime_ns, st_size)`。`auto` 一步内会读 10+ 次同一批文件，缓存命中率接近 100%，且天然避免读到半写文件。

**验收**
```bash
# 200 facts 写 100 intents 必须 < 0.5 s（当前 10.1 s）
python -m pytest -q          # 图完整性相关 23 个测试全绿
```

---

### P0-3 靶场残留：从仓库里清出去，并且让下次进不来

**证据**（全部在 git 索引里）

| 路径 | 内容 | 问题 |
|---|---|---|
| `fz.py` | 硬编码 `base="http://117.72.199.2:3000"` | 靶标地址进开源仓库 |
| `h.txt` | 5 行 32 位十六进制 | Juice Shop 题目答案的 MD5 |
| `recon/` | `incident-support.kdbx`、`announcement_encrypted.md`(369 KB)、`ftp2/package-lock.json.bak`(750 KB)、`main.js`(1.2 MB) | 渗透过程产物，且与 `jsscan/main.js` 完全重复 |
| `jsscan/` | 同一份 1.2 MB `main.js` + 65 KB `challenges.json` | 同上 |

**改法**

```bash
git rm -r --cached fz.py h.txt recon jsscan
printf '\n# 靶场/演练产物：不进入版本库\nfz.py\nh.txt\nrecon/\njsscan/\nruns/\n*.kdbx\n' >> .gitignore
```

再加一条**提交门禁**（这是"把纠正变成检查"的最小可用形态）：

```bash
# scripts/ci/no-lab-artifacts.sh
git diff --cached --name-only | grep -E '^(recon|jsscan|runs)/|^(fz\.py|h\.txt)$' && exit 1
git diff --cached | grep -nE '([0-9]{1,3}\.){3}[0-9]{1,3}:[0-9]{2,5}|flag\{' && exit 1
```

**验收**：`git ls-files | wc -l` 减少 ~20；仓库体积 `du -sh .git` 明显下降（历史仍保留，需要时可后续 `filter-repo`）。

---

## 3. P1（两周内，结构性收益）

### P1-1 干掉 370 ms 的启动税

`ben/__init__.py` 有 106 行 `# noqa: F401` 的 re-export，把 cli、web、所有 commands 都拉起来。所以 `from ben.core.store import Store` 也会顺带加载 argparse、http.server、整个命令树。

而 `scripts/hooks/ben-hook.py:40` 只 `import ben` 就要付这笔钱，**每轮对话一次**。

**改法**

```python
# ben/__init__.py —— 只留版本号
__version__ = "0.9.0"

def __getattr__(name):          # PEP 562：老调用方仍可 ben.Store
    from ben import _lazy
    return _lazy.resolve(name)
```

`_lazy` 里放一张 `{name: "module:attr"}` 表，按需 `importlib.import_module`。旧的 `ben.Store`、`ben.render_status` 继续能用，但只有真用到时才加载。同时把包内所有 `from ben.core.store import ...` 保持写全路径（已经是这样，不用改）。

**验收**
```bash
python -c "import ben.core.store"          # 目标 < 60 ms（当前 384 ms）
python scripts/hooks/ben-hook.py userpromptsubmit < event.json   # 目标 < 120 ms（当前 379 ms）
```

### P1-2 `build_parser()` 473 行 → 按命令组注册

现状：`cli.py:30-502` 一个函数里塞了 26 个子命令。加一个 flag 要滚 500 行，review diff 大，agent 改这里最容易踩空。

**改法**：`ben/cli/` 包，`fact/graph/dispatch/fleet/arena/kb/config` 各一个 `register(sub)`，用 4 行装饰器统一收口：

```python
@command("fact", help="add a confirmed fact")
def _fact(p):
    p.add_argument("description")
    p.add_argument("--title", "-t")
    ...
```

**验收**：`ben --help` 输出逐字不变（现有 3 个 CLI 契约测试兜底）；`wc -l ben/cli/*.py` 最大单文件 < 120 行。

### P1-3 7–8 个位置参数 → 一个上下文对象

`_dispatch_explore(store, templates_dir, intent, model, timeout, skip, cwd, args)` 这种签名，`args` 和具名参数混用，改一个字段要动 6 个调用点。用 P0-1 引入的 `DispatchContext` 一次性解决。

**验收**：`ruff` 规则 + 人工确认无 `>=6` 位置参数的函数（当前 15 个）。

### P1-4 执行器提示词移出 Python

`factory.py:21-50` 的 `_agents_system_prompt` 是 60 行中文/英文混排字符串，和 `agents/prompts/*.md` 分居两处——改一句规则要翻代码。搬到 `agents/prompts/executor_system.md`，`_agents_system_prompt` 退化为读文件 + 注入 store 路径。

**验收**：`grep -c '"""' ben/agents/factory.py` 不再包含长文本块；提示词 diff 可读。

---

## 4. P2（按需，先记着）

| 项 | 现状 | 建议 |
|---|---|---|
| 一步内重复读全图 | `auto` 一步里 `render_prompt`/`frontier`/`_graph_signature` 各读全图，约 10–15 次 | 一步开头取一次 `build_graph_view`，作为参数往下传（P0-2 的缓存已能吃掉大部分） |
| 硬编码等待 | `auto.py:125` `sleep(15)`、`L172` `sleep(1.5)` | 提为 `BEN_RETRY_BACKOFF` / `BEN_STEP_PAUSE`，注册进 `config.ENV_SPECS` |
| 宽泛 except | `bench.py` 4 处、`web/view.py` 4 处 `except Exception` | 收敛到 `FGError/OSError/ValueError`；保留的加 `# noqa: BLE001` 并写明理由（现在 `builtin.py` 已经这么做了，是正确示范） |
| 测试单文件 | `tests/test_ben.py` 1,402 行 / 19 个类 | 按域拆 `test_core / test_llm / test_runtime / test_commands / test_web`，`conftest.py` 放公共 fixture |
| 孤儿字节码 | `ben/commands/payloads.pyc`（源码已删） | `find . -name "*.pyc" -delete`，`.gitignore` 已有 `__pycache__/` |

---

## 5. 护栏：把"下次别再犯"写成检查

这是本方案的核心。**P0/P1 修的是今天的问题；这一节防的是明天的问题。** 优先投入顺序：能写成检查的，绝不写进文档。

### 5.1 `pyproject.toml`（当前完全缺失）

```toml
[project]
name = "ben"
version = "0.9.0"                 # 与 ben/consts.py __version__ 单一来源
requires-python = ">=3.11"
dependencies = []                 # 内核保持零依赖

[project.optional-dependencies]
sdk = ["openai>=1.40,<3"]
dev = ["pytest>=8", "ruff>=0.6", "import-linter>=2.0"]

[project.scripts]
ben = "ben.cli:main"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B", "SIM", "BLE", "T20", "TID", "RUF"]
ignore = ["RUF001", "RUF002"]      # 中文全角标点

[tool.ruff.lint.flake8-tidy-imports.banned-api]
"time.sleep".msg = "禁止 sleep 兜底：长等待用 config 的 *BACKOFF，状态同步用显式轮询"
"requests".msg = "内核零依赖：用 urllib.request（见 llm/grok_build.py 的写法）"

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["T20", "BLE001"]
"ben/tools/builtin.py" = ["TID251"]      # 工具层确实要 sleep/subprocess
"ben/runtime/*" = ["TID251"]
"ben/llm/runner.py" = ["TID251"]
```

> 报错文案本身要带"改成什么"——这是最省钱的一条经验。Agent 读到 lint message 就够了，不需要人再解释一遍。

### 5.2 分层契约（`import-linter`）

先立两条今天就能过的，再逐步收紧（**新规则必须先在旧代码上红一次**，否则证明不了它有效）：

```toml
[tool.importlinter]
root_packages = ["ben"]

[[tool.importlinter.contracts]]
name = "core 不得依赖任何上层"
type = "forbidden"
source_modules = ["ben.core"]
forbidden_modules = ["ben.cli", "ben.commands", "ben.agents", "ben.llm", "ben.web", "ben.runtime"]

[[tool.importlinter.contracts]]
name = "auto 是命令，不是库"
type = "forbidden"
source_modules = ["ben.commands.bench", "ben.commands.commander", "ben.commands.misc"]
forbidden_modules = ["ben.commands.auto"]
```

第二条会把 `bench/commander/misc` 里 `from ben.commands.auto import deadline_from_args`（4 处）全部打红——这正是 P0-1 要顺手搬走的 `ben/core/clock.py`。**规则写下去，改动才有方向。**

### 5.3 一条自证命令：`ben verify`

对应"没有证据不算完成"。退出码非 0 就是没做完，产物落 `runs/verify/<ts>/`：

```bash
$ ben verify
✓ ruff      ben/ 44 files, 0 issues
✓ imports   2 contracts kept
✓ pytest    78 passed, 3 skipped
✓ graph     validate: 0 errors (5 facts / 0 open intents)
evidence → runs/verify/20261118-0830/{ruff.txt,pytest.txt,imports.txt,graph.txt}
```

骨架（`ben/commands/verify_cmds.py`）：顺序跑 4 个 `subprocess.run`，`check=False` 收集，任一非 0 则整体返回 1，同时把每个命令的 stdout 写进证据目录。~60 行。

### 5.4 CI（`.github/workflows/ci.yml`，当前无 CI）

四步，全部失败即阻断合并：

```yaml
- run: ruff check ben tests
- run: lint-imports
- run: python -m pytest -q
- run: bash scripts/ci/no-lab-artifacts.sh
```

加上 `tests/fake_openai.py` 已经能在无 key 情况下跑通 sdk 路径（这是很好的设计），CI 不需要任何密钥。

---

## 6. 落地顺序与预期

| 阶段 | 内容 | 验收 |
|---|---|---|
| D1 | P0-3 仓库清理 + 门禁脚本 | `git ls-files` 少 20 项；门禁在旧提交上能红 |
| D2–D3 | P0-2 Store 索引 + 缓存 | 写 100 intent < 0.5 s；78 tests 全绿 |
| D4–D5 | P0-1 dispatch 归一 + `core/parse.py`、`core/clock.py` | `auto.py` 无 `run_claude`；行数 -150 |
| D6 | 5.1 + 5.2 护栏落地 | `ruff check` 0 issue；`lint-imports` 2 contracts kept |
| D7 | 5.3 `ben verify` + 5.4 CI | PR 上四条检查全绿 |
| W2 | P1-1 惰性导入、P1-2 cli 拆分 | `import ben.core.store` < 60 ms；hook < 120 ms |
| W3 | P1-3 / P1-4 / P2 按需 | — |

预期总量：**代码 -250 行左右，启动 -260 ms，写图快 20×，且新增一条"错误进不来"的通道。**

---

## 7. 不建议做的

- **不要为了"看起来工程化"引入 pydantic / attrs / dataclasses-json**。内核"零依赖"是这个项目真实的卖点（`nvwabase` 也是这么讲的），`Store` 的手写校验虽然啰嗦，但没有框架税。
- **不要重写 `Store` 的存储格式**。一节点一 JSON + flock 已经被 78 个测试和实战验证过；P0-2 只改"怎么查"，不改"怎么存"。
- **不要一次把 26 个命令全拆到独立包**。先拆 `cli.py` 一个文件，其余保持不动——每步都要能单独回滚。
- **不要给 `AGENTS.md` 加规则来替代上面任何一条**。这个项目自己的 `AGENTS.md` 只有 40 行，克制得恰到好处；把"禁止提交靶场文件"写成 CI 检查，比在 `AGENTS.md` 里写一句"请注意不要提交测试数据"有效 100 倍。

---

*本方案的所有数字均来自本机实测，复现命令见各节。*


> **Superseded by** [OPTIMIZATION-PLAN-v4.md](../OPTIMIZATION-PLAN-v4.md).

