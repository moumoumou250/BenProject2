# ben 优化方案 v2

> ⚠️ **部分条目已落地，未完成项已迁至 `plans/OPTIMIZATION-PLAN-v4.md`**（2026-11-18 10:30）。本文件保留为历史记录：v4 §1 列出哪些条目已完成并作废，§2 起是剩余 14 条。**执行请以 v4 为准，不要按本文件的排期表动手。**

> 配套文件：`OPTIMIZATION-PLAN-v3.md`（54 项质量体系清单的差距核对）。**v2 修代码，v3 建闸门**，两者不重叠，按 v2 §8 的 D1–D7 与 v3 §7 的插入点合并执行。

> 基线：2026-11-18 09:00，`/home/kali/Desktop/AI/BenProject`（分支 `refactor/structure`，commit ff73143）
> 方法：先取证，再开方。每个结论附复现命令；每个改动附**机器能判**的验收。
> 本版根据评审意见修订了 6 处；其中 1 处是 v1 自身的归因错误（见 §1.1）。

---

## 0. 这一版改了什么

| # | v1 的写法 | v2 的处理 | 性质 |
|---|---|---|---|
| 1 | P1-2 用 `@command(...)` 装饰器统一收口 | **删除**。`register(sub)` 已足够，多一层只增加 diff 与 review 成本 | 排除 |
| 2 | 门禁用全仓 IP 正则扫 `git diff --cached` | **限定路径 + allowlist**。只扫代码/配置类扩展名，例外写进 `scripts/ci/ip-allowlist.txt` | 改写 |
| 3 | 「hook 不 import ben、直接读 `.ben/*.json`」 | **不采用**。`render_status`/`render_history_block` 含 frontier 排序逻辑，hook 重写等于复制领域逻辑。改为**下沉渲染器** `ben/report/brief.py` | 改写 |
| 4 | P0-1 验收只 grep `auto.py` | **扩大到全 `ben/commands/`**，`commander.py` 用显式白名单标注为「本轮不动」 | 收紧 |
| 5 | P0-2 用 `_has_fact()`（文件存在即通过），语义放宽 | **改用 `get_fact()` 逐 id**，被引用事实仍走 schema 校验。不需要放宽语义 | 修正 |
| 6 | P0-2 只有手工计时验收 | 新增 `tests/test_perf.py`（`BEN_PERF=1` 才跑）+ `scripts/perf/write_path.py`，挂进 `ben verify` 作报告行 | 补强 |
| 7 | 「hook 379 ms → < 120 ms」「20 轮省 7.6 s」 | **撤回**。本机解释器启动基线 369 ms，120 ms 不可达；改为度量**边际开销** 227 ms → < 80 ms | 自我纠错 |

另外新增一项 v1 漏掉的：`P1-5 commander 收口`（评审点 4 指出的半拉子风险，单列而非混进 P0-1）。

---

## 1. 体检基线（重测）

### 1.1 启动开销：先修正度量口径

v1 说「`import ben.core.store` = 384 ms ≈ `import ben`，所以是 106 行 re-export 拖累」。**结论的后半句对一个、前半句错**。重测（12 次交错，取中位数）：

| 被测 | 中位数 | 扣除启动后的边际 |
|---|---|---|
| `python -c pass` | **369 ms** | —（其中 `sitecustomize` 占 309 ms，是本机环境的固定地板） |
| `import ben` | 575 ms | **≈ 206 ms** |
| `import ben.core.store` | 570 ms | **≈ 201 ms** |
| `hook userpromptsubmit` | 596 ms | **≈ 227 ms** |

`import ben.core.store` 与 `import ben` 同价，说明这 200 ms 全部发生在**包初始化**这一步，不在任何子模块——这部分 v1 判断成立。但**绝对目标错了**：任何 Python 进程在这台机器上都要先付 369 ms，所以「hook < 120 ms」永远不可能达成。

`-X importtime` 的归属（累计）：

```
ben            187 ms
  json         112 ms   ← hook 解析 stdin 本来就要付
  ben.cli       49 ms   ← 只为 argparse（39 ms）
  subprocess    60 ms   ← 只为跑一次 date
  tempfile      60 ms   ← 来自 core/io.py 的原子写
  ben.agents.factory 24 ms
```

`ben/__init__.py` 里 `# noqa: F401` 是 **29 处**（v1 写的「106 行」是文件总行数，不是 re-export 条数）。

> **本版统一口径**：所有启动类指标只报「边际 = 端到端 − 369 ms」，不再报绝对墙钟时间。

### 1.2 写路径（重测，比 v1 更差）

| 场景 | 实测 |
|---|---|
| 50 facts → 写 25 intents | 0.83 s |
| 100 facts → 写 50 intents | 2.73 s |
| 200 facts → 写 100 intents | **11.88 s** |

每翻倍约 3.3–4.3×，平方项确认。热点的**位置**比 v1 描述得更糟：

```python
# core/store.py:226-227
with self.locked():            # ← 持锁期间
    self._validate_from(from_ids)   # → self.list_facts() 全目录 glob + 逐个 json.load + 逐个 schema
```

也就是说全量扫描发生在 **flock 内**。多 worker 并行时不只是慢，是写者之间被串行化——这与项目「fleet 多进程」的设计直接冲突。

### 1.3 仓库泄漏面（含 v1 没有的关键事实）

| 事实 | 值 |
|---|---|
| 索引中的靶场文件 | **29 个**（`fz.py`、`h.txt`、`recon/`、`jsscan/`） |
| 唯一 blob 总量 | **2.4 MB / 23 个**（`recon/main.js` 与 `jsscan/main.js` 同一 blob `79dd51e`，git 已去重） |
| `.git` 体积 | 33 MB / 36 commits |
| 引入这些文件的提交 | **1 个**，即根提交 `6098db0 "sapper-v2 — autonomous pentest legion"` |
| 远端 | `origin = github.com/moumoumou250/BenProject2.git`，当前分支**已推送**（ahead 1 / behind 3） |

两处 v1 需要修正的表述：

- v1 说「仓库 −3.5 MB」→ 实际唯一内容只有 **2.4 MB**（重复文件不算）。真正的收益是「不再公开泄漏」，不是省磁盘。
- v1 把「是否清历史」写成「需要时可后续 `filter-repo`」→ **不成立**。远端是公开 GitHub 仓库且已推送，泄露已经发生。这是**必须今天做的决策**，不是可选优化。

另外 `recon/ftp/order_aafc-129edb243ac04f9d.pdf` 是一份真实格式的订单 PDF，`incident-support.kdbx` 是 KeePass 库——这两项属于凭证/隐私面，优先级高于「靶标 IP 暴露」。

### 1.4 结构熵

| 指标 | 值 |
|---|---|
| `ben/` | 44 文件 / 8,214 行 |
| `tests/` | 1,491 行，78 passed / 3 skipped |
| dispatch 双实现 | `factory._dispatch_{reason,explore,verify}` ↔ `auto._run_*_raw`，逻辑一致、差别仅 print/return |
| `from ben.commands.auto import` | **3 处**（`bench.py:13`、`misc.py:13`、`commander.py:13`），v1 写 4 处 |
| `commander.py` 直连模型 | `commander.py:188` `run_claude` / `:193` `extract_json_object` |
| 反向依赖 | `agents/factory.py:9` ← `commands.util.parse_from` |

---

## 2. P0-A 仓库泄漏：先止血，再定历史

### 2.1 止血（30 分钟，风险为零）

```bash
git rm -r --cached fz.py h.txt recon jsscan
cat >> .gitignore <<'EOF'

# 靶场/演练产物：不进入版本库
fz.py
h.txt
recon/
jsscan/
runs/
*.kdbx
*.gg
EOF
```

### 2.2 决策 B：历史怎么处理（**今天必须拍板**）

前提事实：公开远端 + 已推送 + 仅 1 个根提交引入。

| 选项 | 动作 | 代价 | 适用 |
|---|---|---|---|
| **B1 只清索引**（最低） | 上面那条 `git rm --cached` + 下一次提交 | 5 分钟；历史仍可 `git show 6098db0` 取出全部内容 | 仅当你能接受「已经泄漏、不再扩散」 |
| **B2 重写历史**（推荐） | `git filter-repo --invert-paths --path fz.py --path h.txt --path recon --path jsscan`，然后 `push --force --all` | 需通知所有协作者重新 clone；root commit 被改写，`backup/refactor-structure-20261117` 等分支 hash 全变 | 公开仓库、要长期维护 |

无论选哪个，**都要做凭证处置**（这是 v1 完全漏掉的一项）：

1. `incident-support.kdbx` 的主密码若在别处复用 → 视为已泄露，改掉；
2. 靶场 `117.72.199.2:3000` 若仍在线且属于你自己的资产 → 下线或加白；
3. `h.txt` 的 5 个答案 MD5 对应的题目若用于比赛/考核 → 换题或作废。

### 2.3 门禁脚本（限定路径 + allowlist）

```bash
#!/usr/bin/env bash
# scripts/ci/no-lab-artifacts.sh —— 只拦"这次要提交的文件"，不扫历史
set -euo pipefail

staged=$(git diff --cached --name-only --diff-filter=ACM)
[ -z "$staged" ] && exit 0

# 1) 路径黑名单：精确、零误伤
bad=$(printf '%s\n' "$staged" | grep -E '^(recon|jsscan|runs)/|^(fz\.py|h\.txt)$|\.kdbx$' || true)
if [ -n "$bad" ]; then
  printf '禁止提交靶场/演练产物：\n%s\n' "$bad"; exit 1
fi

# 2) 内容扫描：只查代码与配置，文档不参与
scan=$(printf '%s\n' "$staged" | grep -E '\.(py|js|ts|tsx|sh|ya?ml|toml|ini|cfg|env|json)$' || true)
[ -z "$scan" ] && exit 0

hits=$(printf '%s\n' "$scan" | xargs -r grep -nHE 'https?://([0-9]{1,3}\.){3}[0-9]{1,3}(:[0-9]{2,5})?' 2>/dev/null \
       | grep -vFf scripts/ci/ip-allowlist.txt || true)
if [ -n "$hits" ]; then
  echo "疑似硬编码靶标地址（确属示例请加入 scripts/ci/ip-allowlist.txt）："
  printf '%s\n' "$hits"; exit 1
fi
```

`scripts/ci/ip-allowlist.txt` 初始内容（文档/测试里合法出现的地址）：

```
127.0.0.1
0.0.0.0
8.8.8.8
```

> 关键差别：v1 扫的是 `git diff --cached` 的**全部内容**，会误伤 `.md` 里引用的示例 IP；v2 先按扩展名收窄，再走 allowlist。规则必须能被正常写作绕过（否则人会关掉它），但绕过要留痕。

### 2.4 验收

```bash
# 1) 索引已清空
git ls-files | grep -cE '^(fz\.py|h\.txt|recon/|jsscan/)'   # → 0
du -sh .git                                                  # B1 不变；B2 应明显下降

# 2) 空暂存区不误报
bash scripts/ci/no-lab-artifacts.sh; echo "exit=$?"          # → exit=0

# 3) 反证：规则必须能红（造一个违规文件，暂存后不提交）
printf 'BASE = "http://10.1.2.3:8080"\n' > probe_ban.py
git add probe_ban.py
bash scripts/ci/no-lab-artifacts.sh; echo "exit=$?"          # → exit=1，指出 probe_ban.py:1
git restore --staged probe_ban.py && rm probe_ban.py

# 4) allowlist 生效（127.0.0.1 不应被拦）
printf 'URL = "http://127.0.0.1:8000"\n' > probe_ok.py
git add probe_ok.py
bash scripts/ci/no-lab-artifacts.sh; echo "exit=$?"          # → exit=0
git restore --staged probe_ok.py && rm probe_ok.py
```

第 3、4 步是这节的重点：**一条从没红过的规则等于没有规则**。

---

## 3. P0-B Store 写路径：提速但**不放宽语义**

### 3.1 改法（三处，只碰 `Store`）

**① `_validate_from` 逐 id 走 `get_fact`，不再预取全集**

```python
def _validate_from(self, fact_ids: list[str]) -> None:
    if not isinstance(fact_ids, list) or not fact_ids:
        raise FGError("intent must have at least one `from` fact")
    for fid in fact_ids:
        if not isinstance(fid, str):
            raise FGError("intent `from` ids must be strings")
        if fid == GOAL_ID:
            raise FGError("`goal` cannot be used in `from`")
        _validate_lookup_id(fid, "fact")
        try:
            self.get_fact(fid)          # 单文件读 + schema 校验，O(1)
        except FGError as exc:
            raise FGError(f"from fact {fid} does not exist") from exc
```

**这一条直接回应评审点 2。** v1 提出的 `_has_fact()`（文件存在即通过）会让「坏 JSON 的 fact 仍可被引用」，是真实的语义放宽；而 `get_fact` 走 `_read_node(p, "fact")`，**被 `from` 引用的事实照旧做 schema 校验**，只有「没人引用、也没被列举」的坏节点不再被发现——那本来就不该由写路径负责。所以不需要 `_has_fact`，也不需要「写明让步」。

**② 进程内读缓存，键 `(path, st_mtime_ns, st_size)`**

```python
# core/io.py
@lru_cache(maxsize=2048)
def _read_node_cached(path_str: str, mtime_ns: int, size: int) -> dict:
    return read_json(Path(path_str))
```

`auto` 一步内 `frontier`/`render_prompt`/`_graph_signature` 会重复读同一批文件 10+ 次，命中率接近 100%；键里带 mtime+size，既避免读到半写文件，也不会返回过期内容（`atomic_write_json` 必然改 mtime）。

**③ `list_facts`/`list_intents` 复用同一缓存**，于是全量列举从「200 次 json.load」变成「200 次 stat + 命中缓存」。

### 3.2 性能回归（评审点 1）

手工计时挡不住回退，加一层可跳过的守卫：

```python
# tests/test_perf.py
import os, time, tempfile
import pytest

pytestmark = pytest.mark.skipif(os.environ.get("BEN_PERF") != "1",
                                reason="性能回归，需 BEN_PERF=1 显式开启")

def test_add_intent_stays_linear():
    from ben.core.store import Store
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        st = Store(Path(d) / ".ben"); st.init("t", "goal")
        for i in range(200):
            st.add_fact(f"f{i}", "t")
        t0 = time.perf_counter()
        for i in range(100):
            st.add_intent([f"f{i+1:03d}"], f"i{i}", "t")
        elapsed = time.perf_counter() - t0
    # 当前 11.88 s；修好后应 < 0.3 s。阈值取 1.0 s：只挡 10× 级回退，不做微基准
    assert elapsed < 1.0, f"写 100 intents 用了 {elapsed:.2f}s（阈值 1.0s）"
```

`scripts/perf/write_path.py` 输出 50/100/200 三点曲线（供人看趋势），`ben verify` 把它作为**报告行**打印，不作为阻断项：

```
~ perf    write 100 intents @200 facts: 0.21s (last 0.19s)
```

### 3.3 验收

```bash
BEN_PERF=1 python -m pytest tests/test_perf.py -q     # 1 passed
python -m pytest -q                                    # 78 passed, 3 skipped 不变
python scripts/perf/write_path.py                      # 200 facts → < 0.5 s
```

---

## 4. P0-C dispatch 归一：先把边界钉死

### 4.1 边界（评审点 4）

**本轮只归一 reason / explore / verify 三个动词。`commander` 不动。**

理由不是「工作量大」，而是三者形态不同：

| | reason/explore/verify | commander |
|---|---|---|
| 调用形态 | 一次请求 → 一次结果 | `while time.time() < deadline` 循环，带 `noop_streak`、round-robin 回退 |
| 失败语义 | 抛 `FGError` 给上一步 | 捕获后退化成 round-robin，继续跑 |
| 输出 | 写图节点 | 打印决策 + 派活给 worker 进程 |

把 commander 塞进同一个 `dispatch.py`，会让那个模块同时背「一次性动作」和「长驻调度」两种生命周期，是本方案最该避免的那类混合。它单列 P1-5。

### 4.2 改法

```python
# ben/agents/dispatch.py —— 只有 return，没有 print
@dataclass(frozen=True)
class DispatchContext:
    store: Store
    templates: Path
    model: str
    timeout: int
    skip: bool
    cwd: Path
    time_budget: str = ""

def run_reason(ctx, *, dry_run: bool = False) -> tuple[str, str]: ...
def run_explore(ctx, intent: str, *, claim: bool = False) -> dict: ...
def run_verify(ctx, intent: str) -> tuple[bool, str]: ...
```

`commands/dispatch.py` 与 `commands/auto.py` 退化为：构造 ctx → 调 `run_*` → 打印。

顺手拆两处反向依赖（这是分层契约能立起来的前提）：

- `commands.util.parse_from` → `ben/core/parse.py`
- `commands.auto.deadline_from_args` / `format_time_budget` → `ben/core/clock.py`（`bench/misc/commander` 三处 import 随之改向）

### 4.3 验收（评审点 4 的收紧版）

```bash
# 全 commands 目录只允许 commander.py 保留直连模型调用
grep -rn "run_claude(\|extract_json_object" ben/commands --include=*.py \
  | grep -v "^ben/commands/commander.py:"        # → 空

grep -rn "from ben.commands.auto import" ben     # → 空（已搬去 core/clock.py）

python -m pytest -q                              # 78 passed 不变
```

`commander.py` 的两处保留，用一行注释标明归属，避免下一个人以为是漏改：

```python
# NOTE(P1-5): commander 的长驻调度形态不并入 agents/dispatch.py，见 docs/OPTIMIZATION-PLAN-v2.md §6.5
```

### 4.4 回归窗口

`P0-C` 是全局回归风险最高的一项（动 3 个命令 + 2 个模块搬迁），**独占 2 天，期间不叠加任何护栏改动**。护栏（§5）先落地，但只落「今天就能过」的规则，不在同一提交里追着改代码。

---

## 5. 护栏：与 P0-C 解耦，可并行先落

### 5.1 `pyproject.toml`（当前完全缺失）

```toml
[project]
name = "ben"
version = "0.9.0"                 # 与 ben/consts.py 单一来源
requires-python = ">=3.11"
dependencies = []                 # 内核零依赖

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
ignore = ["RUF001", "RUF002"]     # 中文全角标点

[tool.ruff.lint.flake8-tidy-imports.banned-api]
"time.sleep".msg = "禁止 sleep 兜底：长等待用 config 的 *BACKOFF，状态同步用显式轮询"
"requests".msg = "内核零依赖：用 urllib.request（见 llm/grok_build.py 的写法）"

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["T20", "BLE001"]
"ben/tools/builtin.py" = ["TID251"]
"ben/runtime/*" = ["TID251"]
"ben/llm/runner.py" = ["TID251"]

[tool.pytest.ini_options]
markers = ["perf: 性能回归，需 BEN_PERF=1 开启"]
```

> 报错文案本身要带「改成什么」。Agent 读到 lint message 就够了，不需要人再解释一遍。

### 5.2 分层契约（先只立能过的两条）

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

第二条现在会红（3 处 `deadline_from_args`），正是 §4.2 要搬的 `core/clock.py`。

**红线不变**：新规则必须先在旧代码上红一次，否则证明不了它有效；能让它红的证据写进 PR 描述。

### 5.3 `ben verify`（自证命令）

```bash
$ ben verify
✓ ruff      ben/ 44 files, 0 issues
✓ imports   2 contracts kept
✓ pytest    78 passed, 3 skipped
✓ graph     validate: 0 errors (5 facts / 0 open intents)
~ perf      write 100 intents @200 facts: 0.21s
evidence → runs/verify/20261118-0900/{ruff.txt,pytest.txt,imports.txt,graph.txt}
```

退出码非 0 = 没做完。`perf` 是报告行，不阻断（环境噪声太大，卡阈值会变成假红灯）。

### 5.4 CI（`.github/workflows/ci.yml`，当前无）

```yaml
- run: ruff check ben tests
- run: lint-imports
- run: BEN_PERF=1 python -m pytest -q
- run: bash scripts/ci/no-lab-artifacts.sh
```

`tests/fake_openai.py` 已能在无 key 下跑通 sdk 路径，CI 不需要任何密钥——这点值得保留并在 README 里写明。

---

## 6. P1

### 6.1 启动税：用边际指标，且不复制渲染逻辑（评审点 5 的修正版）

评审建议「hook 直接读 JSON，不 import ben」。**不采用，因为它与 §5.2 的分层原则自相矛盾**：`render_status` 要算 frontier、`render_history_block` 要排序截断，hook 重写一遍就是从「一份逻辑两个实现」变成「一份逻辑三个实现」。

正确做法是**把渲染器下沉到一个依赖极轻的模块**：

```
ben/report/brief.py     ← 新：render_brief(store) -> str
  只 import: ben.core.store, json, pathlib
ben/report/status.py    ← 保持：CLI 用的完整版（含颜色/对齐）
ben/agents/prompt.py    ← 保持：需要模板目录时用它
```

hook 改为 `from ben.report.brief import render_brief`，配合包级惰性导入：

```python
# ben/__init__.py
__version__ = "0.9.0"

def __getattr__(name):                 # PEP 562，`ben.Store` 等旧用法继续可用
    from ben import _lazy
    return _lazy.resolve(name)
```

另外把 hook 的 `_date_context()` 从 `subprocess.run(["date"])` 改成 `datetime.now().astimezone()`——省掉 `subprocess` 的 60 ms，且不再依赖外部命令。

**验收（边际口径）**

```bash
hook 边际 = hook 端到端 − 369 ms      # 目标 < 80 ms（当前 227 ms）
import ben.core.store 边际            # 目标 < 40 ms（当前 201 ms）
```

按 20 轮对话算，省 ≈ 3 s——比 v1 声称的 7.6 s 少得多，所以它留在 P1，不是 P0。

### 6.2 `build_parser()` 473 行 → 按命令组注册（**无装饰器**）

```python
# ben/cli/fact.py
def register(sub) -> None:
    p = sub.add_parser("fact", help="add a confirmed fact")
    p.add_argument("description")
    p.add_argument("--title", "-t")
    p.set_defaults(func=cmd_fact)
```

`ben/cli/__init__.py` 里一行 `for m in (fact, graph, dispatch, fleet, arena, kb, config): m.register(sub)`。

验收：`ben --help` 逐字不变（现有 3 个 CLI 契约测试兜底）；`wc -l ben/cli/*.py` 单文件 < 120 行。

### 6.3 `DispatchContext`

`_dispatch_explore(store, templates_dir, intent, model, timeout, skip, cwd, args)` 这类 7–8 位置参数，用 §4.2 的 ctx 一次解决。验收：`ruff` 的 `PLR0913` 不再命中，或人工确认无 `>=6` 位置参数函数。

### 6.4 执行器提示词移出 Python

`factory.py:21-50` 的 `_agents_system_prompt` 是 60 行字符串，与 `agents/prompts/*.md` 分居两处。搬到 `agents/prompts/executor_system.md`，函数退化为「读文件 + 注入 store 路径」。

验收：`grep -c '"""' ben/agents/factory.py` 不含长文本块；提示词 diff 可读。

### 6.5 commander 收口（v1 漏项）

`commander.py:188` 的 `run_claude` + `:193` 的 `extract_json_object` 在 P0-C 之后成为 `ben/commands/` 里**唯一**的直连模型调用点。

先做**低风险的一半**：抽出 `_decide_next(board, rows, tpl) -> Decision`，把「渲染 → 调模型 → 解析 → 失败降级 round-robin」收成一个可单测的函数（现在是内联在 40 行 while 体里，测试只能测到 round-robin 分支）。

暂不做的：把它并入 `agents/dispatch.py`。等 §6.3 的 ctx 稳定、且 commander 的降级语义被测试固定之后，再评估。

验收：`commander.py` 的 while 体从 40 行降到 < 15 行；`_decide_next` 有 3 个用例（正常 / 模型超时降级 / 返回未知 target）。

---

## 7. P2（按需，先记着）

| 项 | 现状 | 建议 |
|---|---|---|
| 一步内重复读全图 | `auto` 一步里 `render_prompt`/`frontier`/`_graph_signature` 各读全图，10–15 次 | §3.1 的缓存已吃掉大部分；剩余靠「一步开头取一次" |
| 硬编码等待 | `auto.py:125` `sleep(15)`、`L172` `sleep(1.5)` | 提为 `BEN_RETRY_BACKOFF` / `BEN_STEP_PAUSE`，注册进 `config.ENV_SPECS` |
| 宽泛 except | `bench.py` 4 处、`web/view.py` 4 处 | 收敛到 `FGError/OSError/ValueError`；保留的加 `# noqa: BLE001` 写理由（`builtin.py` 已是正确示范） |
| 测试单文件 | `tests/test_ben.py` 1,402 行 / 19 类 | 按域拆 `test_core / test_llm / test_runtime / test_commands / test_web`，`conftest.py` 放公共 fixture |
| 孤儿字节码 | `ben/commands/payloads.pyc`（源码已删） | `find . -name "*.pyc" -delete` |

---

## 8. 排期（与护栏错峰）

| 阶段 | 内容 | 谁可以被阻断 |
|---|---|---|
| **D1 上午** | §2.1 止血 + §2.2 决策 B + 凭证处置 | — |
| **D1 下午** | §2.3 门禁脚本 + 在旧提交上验红 | — |
| **D2** | §5.1 pyproject + `ruff check` 首次全绿（只修 lint 能自动修的） | 可与 D3 并行 |
| **D3–D4** | §3 Store（`get_fact` + 缓存）+ §3.2 性能回归 | 不叠加其他改动 |
| **D5–D6** | §4 dispatch 归一 + `core/parse.py`、`core/clock.py` | **独占窗口**，护栏只保留能过的两条 |
| **D7** | §5.2 分层契约转正 + §5.3 `ben verify` + §5.4 CI | PR 四检全绿 |
| **W2** | §6.1 渲染器下沉 + 惰性导入；§6.2 cli 拆分 | — |
| **W3** | §6.3 / §6.4 / §6.5 / P2 | — |

与 v1 的差别：**护栏不再和 dispatch 归一压在同一周**。D2 先把能过的规则立起来，D5–D6 让 P0-C 独占，D7 才把契约收紧到 2 条——评审说的「先落能过的两条 contract，再收紧」就是这个意思。

---

## 9. 不做清单

- **不引 pydantic / attrs / dataclasses-json**。零依赖是真实卖点，`Store` 的手写校验虽啰嗦但没有框架税。
- **不改 `Store` 的存储格式**。一节点一 JSON + flock 已被 78 个测试和实战验证；P0-B 只改「怎么查」，不改「怎么存」。
- **不一次把 26 个命令全拆包**。先拆 `cli.py` 一个文件，其余不动，每步可单独回滚。
- **不给 `AGENTS.md` 加规则来替代上面任何一条**。项目自己的 `AGENTS.md` 只有 40 行，克制得刚好；把「禁止提交靶场文件」写成 CI 检查，比写一句「请注意不要提交测试数据」有效 100 倍。
- **不为了「让 hook 更快」在 hook 里重写渲染逻辑**（v2 新增）。省 150 ms 换来第三份实现，是本方案最不划算的交易。

---

## 10. 验收总表（一条一条机器可判）

| # | 断言 | 命令 | 期望 |
|---|---|---|---|
| 1 | 靶场文件不在索引 | `git ls-files \| grep -cE '^(fz\.py\|h\.txt\|recon/\|jsscan/)'` | `0` |
| 2 | 门禁能红 | 暂存一个含 `http://10.1.2.3:8080` 的 `.py` 后跑脚本 | `exit 1` |
| 3 | 门禁不误伤 | 暂存一个含 `127.0.0.1` 的测试文件 | `exit 0` |
| 4 | 写路径线性 | `BEN_PERF=1 pytest tests/test_perf.py` | `< 1.0 s`（当前 11.88 s） |
| 5 | 老测试不退 | `pytest -q` | `78 passed, 3 skipped` |
| 6 | dispatch 单实现 | `grep -rn "run_claude(" ben/commands \| grep -v commander.py` | 空 |
| 7 | 无反向依赖 | `grep -rn "from ben.commands.auto import" ben` | 空 |
| 8 | 分层契约 | `lint-imports` | `2 contracts kept` |
| 9 | 启动边际 | hook 端到端 − 369 ms | `< 80 ms`（当前 227 ms） |
| 10 | 零依赖不变 | `python -c "import ben, sys; print([m for m in sys.modules if m.split('.')[0] not in ('ben',) and m in ('openai','requests')])"` | `[]` |

---

## 附录 A：v1 中被否的写法（留档，防回潮）

| 被否写法 | 否定理由 | 替代 |
|---|---|---|
| `@command("fact")` 装饰器 | 收益 < diff 成本 | `def register(sub)` |
| 全量 diff 扫 IP 正则 | 误伤文档示例 | 路径收窄 + allowlist |
| hook 直接读 `.ben/*.json` | 复制 frontier 逻辑 | 渲染器下沉 `report/brief.py` |
| `_has_fact()` 存在即通过 | 放宽 schema 校验语义 | `get_fact()` 逐 id（校验保留） |
| P0-1 只 grep `auto.py` | 漏掉 commander，验收虚假通过 | 全目录 grep + 显式白名单 |
| 「hook < 120 ms」 | 启动地板 369 ms，不可达 | 边际 < 80 ms |

## 附录 B：v1 数据勘误

| v1 表述 | 实测 | 原因 |
|---|---|---|
| `__init__.py` 106 行 re-export | 29 处 `noqa: F401`（文件 106 行） | 把文件行数当成了 re-export 条数 |
| 仓库 −3.5 MB | 唯一 blob 2.4 MB / 23 个 | 重复文件在 git 层已去重 |
| hook 379 ms、20 轮 7.6 s | hook 边际 227 ms、20 轮 ≈ 4.5 s | 未扣除 369 ms 解释器启动 |
| `from ben.commands.auto import` 4 处 | 3 处 | 计数错误 |

---

*本方案所有数字均来自本机实测（2026-11-18，12 次交错取中位数），复现命令见各节。*


> **Superseded by** [OPTIMIZATION-PLAN-v4.md](../OPTIMIZATION-PLAN-v4.md).

