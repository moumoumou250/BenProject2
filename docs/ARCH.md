# ben 架构登记表

> 这份表是 `scripts/ci/arch_check.py` 的输入：**任何 `ben/` 下的目录，不在这里登记就过不了检查**。
> 新增模块时先在这一行写清「它负责什么、它不准依赖谁」，再写代码。这比事后补架构文档便宜一个数量级。

## 分层

```
commands / web / cli        表现层：解析参数、打印、起 server。只做 I/O 与编排
        ↓
agents / runtime            领域层：dispatch 动词、worker 生命周期
        ↓
core                        内核：图、存储、schema、io。不得依赖任何上层
        ↓
consts / errors             叶子：零依赖
```

`llm/` 与 `tools/` 是**旁路**：core 与 agents 可以调它们，它们不准反过来读图。
`kb/` `report/` 是只读者：允许依赖 core，不允许写。

## 登记表

| 包 | 职责 | 允许依赖 | 禁止 |
|---|---|---|---|
| `ben/core` | 图模型、存储（一节点一 JSON + flock）、schema 校验、原子写、证据闸门、路径、日志、角色矩阵 | `consts` `errors` | 任何上层（`commands/agents/llm/web/runtime`） |
| `ben/agents` | dispatch 动词（`dispatch.py` 归一 reason/explore/LLM-verify）、提示词、payload 解析 | `core` `llm` | `commands` |
| `ben/commands` | CLI 子命令实现：参数 → 调领域层 → 打印 | 全部 | 被 `agents`/`core` 反向依赖 |
| `ben/llm` | 模型调用（claude / openai 兼容 / grok）、JSON 提取、密钥池 | `core/errors` | 读图、写图 |
| `ben/runtime` | worker 进程、fleet 注册表、日志与 capture | `core` `llm` | 直接改图状态（须经 Store） |
| `ben/tools` | 给模型用的工具函数（文件读写、命令执行、路径白名单） | `core` | 依赖 `commands` |
| `ben/web` | 静态图视图、本地 http server、token 防抓取 | `core` `report` | 写图 |
| `ben/report` | 只读渲染：status、graph 文本、面板 | `core` | 写图、依赖 `agents` |
| `ben/kb` | 知识库索引与检索 | `core` | 写图 |
| `scripts/ci` | 机器检查：`arch_check.py`、`no-lab-artifacts.sh`、`perf/` | stdlib only | 被 `ben/` 导入 |

## 顶层模块

`ben/cli.py` 是唯一入口（`ben = "ben.cli:main"`）；`ben/config.py` 只管环境变量；
`ben/arena.py` 是靶场客户端；`ben/consts.py` 与 `ben/errors.py` 必须保持零依赖。

## 运行时输出（唯一根目录）

**运行时写完的东西全部落在 `<base>/runs/` 之下。** 目录名只在
`ben/core/paths.py` 定义一次，可用 `BEN_RUNTIME_DIR` 覆盖；调用点不准自己拼
路径，也不准调用 `mkdir`（只读者如面板会反复轮询）。

```
runs/
├── workers.json (+ .lock)        fleet 注册表
├── logs/                          worker / console 日志
├── console/                       PTY socket 与 sessions.json
├── probe/<profile-id>/<ts>/       ben probe 证据与 verdict.json
├── <challenge>/.ben/              每个挑战一张图
└── <challenge>/ben-graph.html     ben view 的静态快照
```

| 要用什么 | 函数 |
|---|---|
| 目录名 / 是否已在 runtime 树内 | `runtime_name()` / `is_runtime_path()` |
| 根目录（只读计算） | `runtime_root(base)` / `registry_root(base)` |
| 单个生成文件该放哪 | `output_dir(base)` / `snapshot_file(base)` |
| 写之前建目录 | `ensure_output_dir(base)` / `logs_dir(base, create=True)` |

两个例外，位置**不动**：`.ben/`（项目数据，要跟着项目走）与 `lab/`（人工归档，
代码永不写入）。决策理由见 `docs/adr/0006-runtime-output-has-one-root.md`。

## 检查怎么跑

```bash
python scripts/ci/arch_check.py                 # 人读
python scripts/ci/arch_check.py --json          # CI 读
python scripts/ci/arch_check.py --check duplicates --check orphans
python scripts/ci/arch_check.py --show-baseline # 看冻结了哪些存量问题、什么时候到期
bash scripts/ci/preflight.sh                    # 一键：arch_check + pytest
```

八项检查与它们各自防的历史事故：

| 检查 | 防的是什么 | 触发过的真实例子 |
|---|---|---|
| `packages` | 新模块绕过架构直接落地 | 测试文件写进包内、目录不登记 |
| `duplicates` | 同一个想法实现两遍然后各自漂移 | `recall` 与 `kb` 各一份分词器（已合并到 `core/text.py`）；`now_iso` 两份（已合并） |
| `third_party` | 内核悄悄长出依赖 | `openai` 只允许 `ben/llm/sdk.py` 模块级导入 |
| `orphans` | 删了源码没删字节码 | `ben/commands/payloads.pyc` |
| `stale_refs` | 注释里的出处指向虚空 | 12 处外部评审编号，已内联化 |
| `runtime_paths` | 生成物写进仓库根、或被提交 | `console/`、`logs/`、`workers.json` 曾落在仓库根；3.9 MB 靶场产物进索引 |
| `root_layout` | 仓库根变成堆放场 | 22 个根条目里 4 个空目录、`docs/` 13 个文件平铺、三版方案并排 |
| `agents_budget` | 规则文件只增不减 | `AGENTS.md` 上限 60 行 |

## 冻结存量（baseline）

`scripts/ci/arch_baseline.json` 允许暂时保留已知问题，但每条必须带 `expires`：

```json
"duplicates::ben/agents/factory.py::_dispatch_verify::ben/commands/auto.py::_run_verify_raw": {
  "reason": "P0-C dispatch 归一后消失，见 docs/OPTIMIZATION-PLAN-v2.md §4",
  "expires": "2026-12-02"
}
```

**过期即视为违规。** 没有到期日的 baseline 等于关掉检查，所以 `apply_baseline` 会把过期条目标红。
