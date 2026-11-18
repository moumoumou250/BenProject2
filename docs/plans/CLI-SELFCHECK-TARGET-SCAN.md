# CLI 改造方案：自检（doctor）+ 目标站点测试（target / scan）

状态：**待确认**（2026-11-19）
基线：`ben 1.0.0`，工作树含 KB 闭环 S0–S5 成果；`.ben` 当前 15 facts / 0 open intents
范围：`ben/cli.py`、新增 `ben/doctor/`、新增 `ben/targets/`、`ben/core/recheck.py`、`ben/commands/{doctor,target,scan}_cmds.py`
关系：本方案是 `docs/plans/POSITIONING-PLAN-v1.md` **P1（目标抽象）的最小可落地子集**——只做 `url` 型目标与确定性基线，不做 repo/openapi、不接 LLM 编排（AI 入口仍归 `ben auto`）

---

## 0. 一句话

把「这台机器能不能跑」和「这个网站现在暴露了什么」变成两个**可机器判定**的命令：

```
ben doctor [--json] [--strict] [--offline] [--deep] [--target <id|url>] [--fix]
ben target add|list|show|rm|check ...
ben scan [target|--url URL] [--mode quick|deep] [--budget S] [--fail-on LEVEL]
         [--json] [--record] [--report PATH] [--self-test]
```

三条硬约束：**不新增第三方依赖**、**不改 `ben probe` / `ben verify` 的对外语义**、**每个能力都带 fixture 自测（无网络也能验收）**。

---

## 1. 现状核查（可复现）

| 项 | 事实 | 证据 |
|---|---|---|
| 版本 / 配置 | CLI 可跑，配置自检已存在但只管类型与必填 | `./bin/ben --version` → `ben 1.0.0`；`./bin/ben config --check` → `config ok` |
| 图与运行时 | 图自洽，运行时目录已生成 | `./bin/ben validate` → `graph valid: .ben`；`runs/` 下已有 `probe/ testrange/ logs/ …` |
| **无统一自检** | 健康检查散落在 4 处，没有一条命令回答「现在能不能开跑」 | `config --check`（配置类型）、`validate`（图结构）、`verify --run`（仅 3 个 `--help` 冒烟）、`tests/TestRange/rangectl.py doctor`（docker/python/profile 路径） |
| **任意 URL 无法测** | `ben probe` 只接受 profile id，裸 URL 直接 exit 2 | `ben/commands/probe_cmds.py:cmd_probe`：`profile_id not in profiles` → `ben: unknown profile` |
| 目标无载体 | 无 `target` 概念，目标只存在于 `--goal` 自由文本 | `.ben/project.json` 的 goal 是 `assess … http://117.72.199.2:3000/ (authorized lab)`；`grep add_parser("target"` 为空 |
| 缺 finding 类型 | `FACT_KINDS` 无 `finding`，`data` 是自由 key=value | `ben/consts.py:30` `("host","service","cred","vuln","loot","flag","note")`；`ben/core/schema.py:120` 仅校验 kind 枚举 |
| 授权判定可复用 | 已有 `host_allowed()`（私网/回环免授权，公网需 `authorized`） | `ben/commands/probe_cmds.py:host_allowed` |
| 新包有机器门槛 | `ben/` 下新目录不登记 `docs/ARCH.md` 直接失败 | `scripts/ci/arch_check.py:check_packages`（174–204 行） |
| 进度条缺口 | pyproject 禁用 `subprocess` 并提示改用 `ben.runtime.exec`，但该函数不存在 | `grep -rn "def exec" ben/` → 空；`ben/core/evidence.py` 仍直接 `import subprocess` |

**结论**：自检不是「没有」，而是「没有入口、没有结论码、不测真实链路」；目标测试不是「不好用」，而是「没有入口」。

---

## 2. 设计约束（继承仓库现有纪律）

1. **能写成检查的不写进文档**：每个新能力配 `tests/` + `--self-test`，不往 `AGENTS.md` 加规则。
2. **复用不重写**：授权判定、证据目录、三态判定（`CONFIRMED/UNVERIFIED/NOT_CONFIRMED`）、阴性对照全部复用；`probe_cmds._http` 与 `_probe_file_write` 的观测逻辑抽到 `ben/targets/fetch.py` 与 `ben/core/recheck.py`，`ben probe` 改为调用方（否则 `arch_check duplicates` 会抓重复实现）。
3. **结论必须带退出码**：`0 正向 / 1 否定 / 2 调用方错 / 3 无法下结论`，与 `ben probe` 对齐（见 `docs/plans/KB-FEEDBACK-LOOP.md` §5.3 的有意例外）。
4. **写盘只有一处根**：证据落 `runs/scan/<target>/<ts>/`，经 `core/paths.ensure_output_dir()`，不自己拼路径。
5. **事实图不可污染**：`scan` 默认**不写图**，`--record` 才投影；扫描是探索，图是永久记忆。
6. **零第三方依赖**：HTTP/TLS 全部 `http.client` / `ssl` / `socket`；`arch_check third_party` 只在 `ben/llm/sdk.py` 放行。

---

## 3. 命令面

### 3.1 `ben doctor` —— 这台机器现在能不能跑

```
ben doctor [--json] [--strict] [--offline] [--deep] [--target <id|url>] [--fix]
```

| check id | 判据 | 网络 | 失败示例 |
|---|---|---|---|
| `env.python` | `sys.version_info >= (3,11)` 且 `tomllib` 可导入 | 否 | py3.10 |
| `env.import` | `import ben.cli` 成功（抓半安装/循环依赖） | 否 | 缺模块 |
| `repo.layout` | `bin/ben` 可执行、`docs/ARCH.md`、templates 目录、`kb/` 可读 | 否 | 从 pip 装但缺 kb |
| `config.values` | `config.config_problems()` 为空 | 否 | `BEN_TIMEOUT=abc` |
| `model.engine` | `sdk`：`sdk_ready()`；`cli`：`BEN_BIN` 可解析 | 否 | 找不到 `claude` |
| `model.live` | 仅 `--deep`：一次 ≤32 token 的 completion | 是 | 网关 401 |
| `graph.store` | `.ben` 存在 → `Store.require()` + schema 校验 + 计数 | 否 | 图损坏 |
| `graph.templates` | `_resolve_templates_dir()` 下 7 个 `*.md` 齐全 | 否 | 模板缺失 |
| `runtime.writable` | 建/删 `runs/.doctor-<pid>` | 否 | 只读挂载 |
| `kb.root` | 条目可加载、`taxonomy.json` 可解析 | 否 | KB_ROOT 指错 |
| `arena.config` | 配了 URL 但缺 token（或反之）→ WARN | 否 | 半配置 |
| `target.http` | 仅 `--target`：DNS→TCP→TLS→HTTP | 是 | 端口不通 |
| `scan.selftest` | 仅 `--deep`：跑 §6 的 fixture，要求 recall=1.0、FP=0 | 否（回环） | 规则回归 |

输出（人读）：

```
ben doctor   ben 1.0.0 · py 3.13.12 · linux
PASS  env.python        3.13.12
PASS  config.values     no problems
WARN  arena.config      BENCHMARK_BASE_URL unset (only needed for `ben bench`)
FAIL  target.http       http://117.72.199.2:3000/  connect timeout (5s)
      fix: 确认目标存活/端口，或改用 --offline 只做本地检查
summary: 9 pass · 2 warn · 1 fail · exit 1
```

- `--offline`：禁止一切出站（`model.live`/`target.http`/`scan.selftest` 跳过并标 SKIP）。CI 默认用它。
- `--strict`：WARN 也判 1。
- `--fix`：**只做无副作用修复**——建 `runs/` 子目录、卸掉损坏的 `.doctor-*` 临时文件；配置类问题只打印命令，不改文件。
- `--target` 等价于 `ben target check <id>` 的单次调用，避免两套连通性代码。

### 3.2 `ben target` —— 测哪个、有没有授权

```
ben target add <locator> [--id NAME] [--scope host,host] [--authorized] [--note TEXT]
ben target list [--json]
ben target show <id> [--json]
ben target rm <id>
ben target check <id> [--json] [--timeout S]
```

- `--type` 只开放 `url`（`repo|openapi` 留给 P1；argparse 不放未实现选项）。
- **授权门（硬）**：
  - 私网 / 回环（`ipaddress.is_private|is_loopback`）→ 可无 `--authorized`；
  - 公网 → 必须 `--authorized`，并记录 `authorized_at` / `authorized_by`（`$USER`）；
  - `scan` 每次启动重新校验，**只看 registry，不接受临时 `--force`**（与 `probe --force` 的例外明确区分：那里是本地靶场，这里是真实站点）。
- `scope` 缺省 = locator 的 host；`scan` 的重定向、爬取、请求域名都必须落在 scope 内。

存储 `.ben/targets.json`（`core/io.atomic_write_json`，与图同目录但不进图）：

```json
{
  "version": 1,
  "targets": {
    "juice-shop": {
      "type": "url",
      "locator": "http://117.72.199.2:3000/",
      "scope": ["117.72.199.2"],
      "authorized": true,
      "authorized_at": "2026-11-19T02:10:00Z",
      "authorized_by": "kali",
      "note": "authorized lab",
      "added_at": "2026-11-19T02:10:00Z"
    }
  }
}
```

### 3.3 `ben scan` —— 目标现在暴露了什么

```
ben scan [target] [--url URL] [--mode quick|deep]
         [--budget 60] [--max-requests 60] [--rate 5] [--timeout 5]
         [--fail-on critical|high|medium|low|info|none]
         [--json] [--record] [--report PATH] [--self-test]
```

- 不给 target 且只注册了一个 → 用它；多个 → 报错并列出（不做「猜一个」）。
- `--mode quick`（默认）：单页 + 固定 12 条路径，≤20 请求，≤30s。
- `--mode deep`：同源有界爬取（≤20 页）+ 同一套规则；**仍然只发 GET/HEAD/OPTIONS**。
- `--self-test`：起本地 fixture 跑完整流水线并断言（见 §6），不碰网络、不写图。

### 3.4 与现有命令的边界

| 命令 | 回答 | 网络 | 写盘 | 写图 |
|---|---|---|---|---|
| `ben doctor` | 这台机器能不能跑 | 仅 `--target/--deep` | `--fix` 只建 runtime 目录 | 否 |
| `ben target` | 测哪个、授权没 | 仅 `check` | `.ben/targets.json` | 否 |
| `ben scan` | 目标当前暴露面 | 是（预算内） | `runs/scan/...` | 仅 `--record` |
| `ben probe` | 某个漏洞能否复现 | 是 | `runs/probe/...` | 否 |
| `ben verify` | 代码/图能否交付 | 否 | `runs/verify/...` | 否 |
| `ben validate` | 图结构是否自洽 | 否 | 否 | 否 |

### 3.5 命名裁决

| 候选 | 裁决 | 理由 |
|---|---|---|
| `ben doctor` | ✅ | 常见动词，与 `rangectl doctor` 同名，含义一致 |
| `ben target` | ✅ | P1 已定名；本方案只实现 `url` 子集 |
| `ben scan` | ✅（限定为确定性基线） | P1 把 `scan` 当产品入口；本方案先让它**不花 token 也有用**，P1 落地时再加 `--ai` 转发给 `auto` |
| `ben probe <url>` | ❌ | 会破坏已确认的 `probe <profile-id> <vuln>` 契约 |
| `ben test` | ❌ | 与 pytest 语义混淆 |
| `ben audit` | ❌ | 与「审计轨迹」一词冲突（事实图本身就叫审计轨迹） |

---

## 4. 自检的两层（这是本方案的核心）

**第一层：`ben doctor`** —— 回答「装好了吗、配好了吗、图活着吗」。除 `--deep/--target` 外全程零网络、零写盘，可在 CI 与 docker build 里跑。

**第二层：`ben scan --self-test`** —— 回答「你的检测器还准吗」。它不测目标，测**自己**：

```
起两个进程内 fixture（http.server，127.0.0.1:0）
  bad  : 缺 HSTS/CSP/XCTO；Cookie 无 flags；/.git/HEAD 泄露；
         /.env 200；/admin/ 目录列表；/boom 500 traceback；OPTIONS 允许 PUT/DELETE/TRACE
  clean: 安全头齐全、Cookie 全 flags、随机路径 404
断言
  bad   规则集合 == 期望集合（recall 1.0，多一条也失败）
  clean findings == []（FP 0）
  实际方法 ⊆ {GET, HEAD, OPTIONS}
  除 runs/ 外无写盘
```

`ben doctor --deep` 会调用它，并把 `recall / fp` 打进 JSON。**这才是「CLI 可以自检」的完整含义**：既检查环境，也检查检测逻辑本身。

---

## 5. 扫描流水线与规则

```
gate  →  registry 授权 + scope + 预算初始化（超 scope 直接 2）
  ↓
conn  →  DNS / TCP / TLS（版本、证书主体、SAN、有效期、自签）/ GET / 重定向链（≤5，跨 scope 记 finding 并停止）
  ↓
finger→  Server / X-Powered-By / 框架指纹 / Set-Cookie / 安全头 / title / robots / sitemap
  ↓
base  →  随机路径阴性对照（软 404 判定：状态 200 或与首页相似度 > 0.9）
  ↓
probe →  固定路径表（GET；.git/HEAD、.env、备份扩展名需**内容签名**命中，不看状态码）
  ↓
rules →  纯函数：Observation → Finding（无 I/O，可单测）
  ↓
emit  →  runs/scan/<id>/<ts>/{summary,findings,report.md,exchange/*} [--record → 事实图]
```

| rule | 判据 | 默认严重度 | 关键防误报 |
|---|---|---|---|
| `TLS-CERT-EXPIRED` | `notAfter < now` | high | 解析失败 → WARN 不报 |
| `TLS-CERT-HOST` | SAN/CN 不匹配 locator host | high | 只在 hostname 校验异常时报 |
| `TLS-VERSION` | 协商 < TLS1.2 | medium | — |
| `HDR-HSTS` | https 且无 `Strict-Transport-Security` | low | http 目标不报 |
| `HDR-CSP` | 无 `Content-Security-Policy` | low | 有 `frame-ancestors` 时单独规则 |
| `HDR-XCTO` | 无 `X-Content-Type-Options: nosniff` | low | — |
| `HDR-XFO` | 既无 `X-Frame-Options` 也无 CSP `frame-ancestors` | low | — |
| `COOKIE-FLAGS` | https 下 Set-Cookie 缺 Secure/HttpOnly/SameSite | medium | 只报缺失项组合 |
| `CORS-WILDCARD` | `ACAO: *` 且 `ACAC: true` | medium | 只发 `Origin`，不发预检 |
| `METHODS` | `Allow` 含 PUT/DELETE/TRACE | low | 仅 OPTIONS，不实际调用 |
| `PATH-EXPOSED` | `.git/HEAD` 含 `ref:`；`.env` 含 `KEY=`；备份含 ZIP/PK 魔数 | high | 内容签名 + 软 404 双重门槛 |
| `DIR-LISTING` | `<title>Index of /` | medium | 需与阴性对照正文不同 |
| `ERROR-LEAK` | 500 正文含 `Traceback (most recent call last)` 等栈特征 | low | 只取一条 |

严重度映射固定、可枚举（`critical|high|medium|low|info`），进 `schema.py` 校验；**不引入 CVSS 打分**（P2 的事）。

### 输出契约

人读：

```
target: juice-shop  http://117.72.199.2:3000/   mode=quick  budget=28.4s/60s  req=14/60
  HIGH    PATH-EXPOSED   /.git/HEAD                evidence/07.json
  MEDIUM  COOKIE-FLAGS   sid 缺 HttpOnly/SameSite  evidence/02.json
  LOW     HDR-CSP        /                        evidence/01.json
findings: 3 (1 high · 1 medium · 1 low)   exit 1 (--fail-on high)
evidence: runs/scan/juice-shop/20261119T021500Z/
```

`--json`：

```json
{"tool":"ben scan","version":"1.0.0","sha":"abc1234","target":{"id":"juice-shop","url":"...","authorized":true},
 "mode":"quick","budget":{"seconds":60,"used":28.4,"requests":14,"max_requests":60,"exhausted":false},
 "summary":{"critical":0,"high":1,"medium":1,"low":1,"info":0,"exit":1,"exit_reason":"fail_on=high"},
 "findings":[{"rule":"PATH-EXPOSED","severity":"high","confidence":"high","url":".../.git/HEAD",
              "evidence":"exchange/07.json","detail":"..."}],
 "evidence_dir":"runs/scan/juice-shop/20261119T021500Z/"}
```

`--record` 的图投影（`Store.add_fact`，一条 finding 一条 fact + 一条 summary note）：

```bash
./bin/ben fact "<gist>" -k finding -t "[scan] PATH-EXPOSED /.git/HEAD" \
  -d severity=high -d rule=PATH-EXPOSED -d target=juice-shop \
  -d url=http://.../.git/HEAD -d evidence=runs/scan/.../exchange/07.json
```

> `FACT_KINDS` 增加 `"finding"` 属 S3，需同步 `schema.py` 的 severity 枚举与 `tests/test_ben.py` 的 kind 断言；旧图不受影响（新值向后兼容）。

---

## 6. 模块落位（`docs/ARCH.md` 必须同步登记）

```
ben/doctor/              自检：检查项 + 渲染（不写盘，除 --fix 的 runtime 目录）
  checks.py              每个 check 一个函数 → CheckResult(id,status,detail,fix,hint)
  runner.py              顺序执行、超时、--json/人读渲染、退出码
ben/targets/             目标领域包：注册表、授权/scope、观测、规则、编排、自检
  registry.py            .ben/targets.json CRUD（atomic_write_json）
  scope.py               URL 规范化、host_allowed 扩展、same_scope、重定向策略
  fetch.py               HTTP/TCP/TLS 观测（http.client + ssl），限速与预算
  rules.py               纯函数规则（Observation → Finding），零 I/O
  scan.py                流水线编排、证据落盘、图投影
  selftest.py            进程内 fixture + 期望断言
ben/core/recheck.py      三态判定 + 阴性对照（从 probe_cmds 抽出，probe/scan 共用）
ben/commands/doctor_cmds.py | target_cmds.py | scan_cmds.py
```

| 包 | 职责 | 允许依赖 | 禁止 |
|---|---|---|---|
| `ben/doctor` | 环境/配置/图/模型/目标的只读体检 | `config` `core` `kb` `llm` `targets` `runtime` | `commands` `agents` `web` |
| `ben/targets` | 目标注册、授权、网络观测、规则、扫描编排 | `core` `consts` | `commands` `agents` `llm` `doctor` |

其他必须同步的机器门槛：

1. `docs/ARCH.md` 登记表 + 运行时目录树加 `runs/scan/<id>/<ts>/`（否则 `arch_check packages` 直接红）。
2. `pyproject.toml` 给 `ben/targets/fetch.py` 加 `per-file-ignores = ["TID251"]`——限速需要 `time.sleep`，这是**唯一**合法理由，注释写明；其余位置仍禁用。
3. 顺手修掉发现的不一致（二选一，建议前者）：新增 `ben/core/proc.py::run_cmd()` 并让 `doctor` 用它跑 `BEN_BIN --version`；或把 `pyproject` 里 `"subprocess".msg` 的提示从「改用 `ben.runtime.exec`」改为真实路径。当前提示指向的函数不存在，属于「规则说了、代码没有」。

---

## 7. 模块骨架（关键签名）

```python
# ben/targets/registry.py
@dataclass(frozen=True)
class Target:
    id: str; type: str; locator: str
    scope: tuple[str, ...]; authorized: bool
    note: str = ""; authorized_at: str | None = None; authorized_by: str | None = None

def load(store_root: Path) -> dict[str, Target]: ...
def add(store_root: Path, target: Target) -> None: ...      # 重名 → FGError
def remove(store_root: Path, tid: str) -> None: ...

# ben/targets/scope.py
def normalize(locator: str) -> tuple[str, str]: ...          # (url, host)，非法 → FGError
def requires_authorization(host: str) -> bool: ...
def in_scope(host: str, scope: Sequence[str]) -> bool: ...   # 精确 host 或子域

# ben/targets/fetch.py
@dataclass
class Observation:
    method: str; url: str; status: int; headers: dict[str, str]
    body_head: str; elapsed_ms: int; error: str = ""
    tls: dict | None = None

class Fetcher:
    def __init__(self, *, timeout: float, rate: float, budget: float, max_requests: int): ...
    def get(self, url: str, *, headers: dict | None = None) -> Observation: ...
    def head(self, url: str) -> Observation: ...
    def options(self, url: str) -> Observation: ...
    @property
    def exhausted(self) -> bool: ...

# ben/targets/rules.py
def evaluate(obs: list[Observation], *, target: Target) -> list[Finding]: ...

# ben/targets/scan.py
def run(target: Target, *, mode: str, budget: float, max_requests: int,
        rate: float, timeout: float, base: Path) -> ScanResult: ...
```

`ScanResult` 负责写 `summary.json / findings.json / report.md` 与 `exchange/NN.json`，命令层只负责参数、打印、`--record`。`rules.py` 不 import 任何 I/O，便于表驱动单测。

---

## 8. 安全与边界（写进代码，不写进文档）

| 边界 | 实现 | 违反时 |
|---|---|---|
| 未授权不扫 | `scan` 启动时只读 registry 判定 | exit 2 + 指向 `ben target add --authorized` |
| 不越 scope | 每次请求前 `in_scope()`；跨域重定向不跟随并记 FINDING | 该请求不发出 |
| 不破坏 | 方法白名单 `{GET, HEAD, OPTIONS}`，`fetch.py` 硬编码，无参数可放开 | 代码级不可能 |
| 不爆破 | 固定 12 条路径 + 预算/速率硬上限 | 超限即停，`exhausted=true` |
| 不刷站 | 默认 `--rate 5`，串行请求 | 令牌桶等待 |
| 不泄密 | 证据只存响应头 + 正文前 4KB；Authorization/Cookie 值打码 | — |
| 不留垃圾 | 全部落 `runs/`；`--fix` 也只碰 `runs/` | `arch_check runtime_paths` |

---

## 9. 分阶段实施（每阶段一个 commit，可停可退）

| 阶段 | 交付 | 改动面 | 机器验收 | 可退 |
|---|---|---|---|---|
| **S0** | `ben doctor`（含 `--offline/--strict/--json/--fix`） | +`ben/doctor/` ~380 行、`commands/doctor_cmds.py` ~80、`cli.py` +12、`ARCH.md` +2 行 | `./bin/ben doctor` 在本机 exit 0（允许 WARN）；`ben doctor --offline --json` 的 `summary.fail==0`；`tests/test_doctor.py` 用 monkeypatch 覆盖 PASS/WARN/FAIL 三态与退出码 | 纯新增，revert 无副作用 |
| **S1** | `ben target add/list/show/rm/check` | +`targets/{__init__,registry,scope}.py` ~260、`target_cmds.py` ~120、`cli.py` +20、`ARCH.md` +1 行 | 公网 locator 不带 `--authorized` → exit 2；`--authorized` 后可 `list --json` 读回；`target check` 对 127.0.0.1 fixture 通过；`arch_check` 0 violation | 只新增 `.ben/targets.json`，删即可 |
| **S2** | `ben scan` quick + `--self-test` + 规则表 | +`targets/{fetch,rules,scan,selftest}.py` ~620、`scan_cmds.py` ~140、`pyproject` 1 行 ignore | `ben scan --self-test` recall=1.0 / FP=0 / 方法白名单断言；`ben scan --url http://127.0.0.1:<fixture> --json` 退出码符合 §3.5；真实目标扫描人工复核 1 次 | 不动 schema、不写图 |
| **S3** | 落图 + `report.md` + `--fail-on` + `probe` 复用公共 client | +`core/recheck.py` ~120、`consts.py` 1 值、`schema.py` severity 枚举、`report` 渲染 ~120 | `scan --record` 后 `ben graph` 出现 `finding` 事实且 `ben doc <id>` 能读到证据；`--fail-on high` 在有 HIGH 时 exit 1；`ben probe` 回归全绿 | 需回滚 schema 时旧图仍可读（新增枚举值向后兼容） |
| **S4**（可选） | `--mode deep` 有界爬取 + profile `[expect]` 精度/召回 | ~200 行 | 对 2 个 TestRange profile 跑出 precision/recall 并写进 summary | 独立开关 |

建议顺序理由：S0 零风险且立刻能用（当前 `.ben` 已有 15 facts，开跑前正需要它）；S1 是所有后续的授权前提；S2 是「能测网站」的最小闭环；S3 才动 schema，把不可逆改动压到最后。

---

## 10. 测试策略

```
tests/test_doctor.py        三态渲染、--offline 跳过网络项、退出码、--fix 只建 runtime
tests/test_targets_registry.py  增删改查、重名、公网授权门、scope 子域匹配
tests/test_targets_rules.py 表驱动：每个 rule 一条正例 + 一条反例（防误报）
tests/test_scan_selftest.py 调 selftest.run()，断言 recall/FP —— CI 无网络也跑
tests/test_scan_cli.py      --json 契约字段、--fail-on 退出码、--record 事实数量
```

CI（`scripts/ci/preflight.sh`）追加两行，不引入新脚本：

```bash
python -m ben doctor --offline --json > /dev/null     # 环境自检可机器判定
python -m ben scan --self-test                        # 检测器自检
```

---

## 11. 风险表

| 风险 | 级别 | 缓解 |
|---|---|---|
| 误报毁掉信任 | **高** | 软 404 阴性对照 + 内容签名 + `--self-test` 卡 FP=0；`confidence` 字段随 finding 输出 |
| 被当成扫描器滥用 | **高** | 公网必须 registry 显式 `--authorized`；无 `--force` 旁路；请求方法白名单 |
| `scan` 与 P1 的 AI 入口撞名 | 中 | 本方案把 `scan` 定义为确定性基线；P1 落地用 `--ai` 转发 `auto`，不改语义 |
| 与 `probe` 重复实现被 arch_check 抓 | 中 | S3 强制抽 `fetch.py`/`recheck.py`，`probe` 改调用方 |
| `doctor` 变成第二套 config 校验 | 中 | `config.values` 只调 `config_problems()`，不复制规则 |
| schema 加 `finding` 破坏旧图 | 低 | 新增枚举值、`validate` 回归；旧节点无 `kind=finding` 不受影响 |
| 真实扫描把运行时间拉长 | 低 | 预算/速率硬上限；`--self-test` 不联网，CI 秒级 |

---

## 12. 不做清单（防止范围漂移）

- 不做大字典目录爆破、不做登录后扫描、不做漏洞利用（`probe` 已有边界，`scan` 只做暴露面）。
- 不引入 `requests` / `httpx` / `dnspython`（`arch_check third_party` 会拦）。
- 不导出 SARIF、不做 CVSS 打分（P2）。
- 不改 `ben verify` / `ben probe` 的参数与退出码语义（只允许内部改调用）。
- 不在 README quickstart 里提前写未实现的命令（`readme_contract` 检查会红）。

---

## 13. 下一步

确认本方案后，按 S0 → S1 → S2 顺序落地；S0 完成即可用现有 `.ben`（Juice Shop 目标）跑第一次 `ben doctor`，S2 完成即可：

```bash
./bin/ben target add http://117.72.199.2:3000/ --id juice-shop \
  --scope 117.72.199.2 --authorized --note "authorized lab"
./bin/ben scan juice-shop --mode quick --fail-on high --json
```
