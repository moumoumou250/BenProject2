# sapper-v2 与 BenProject 运行思路对比

> 对比对象：`/home/kali/Desktop/AI/sapper-v2-master`（下称 **sapper**）与 `/home/kali/Desktop/AI/BenProject`（下称 **ben**）
> 对比维度：架构设计 / 启动流程 / 请求处理 / 渲染机制 / 构建部署 / 运行理念 / 适用场景
> 证据来源：两仓库源码与文档（行号引用以当前工作区版本为准）

---

## 0. 一句话结论

**两者共享同一套"分层事实图 + 角色分工"的组织思想，但运行时的"物理层"完全不同：**

- **sapper 把操作系统终端当成 harness**——造人是开 tmux 窗格，说话是往别人输入框里打字，模型能力整体外包给 Claude Code 的交互式 TUI；它是一支**住在容器里的军团**。
- **ben 把进程当成 harness**——造人是 `Popen`，说话是结构化 hint / PTY 套接字，模型调用循环被收进自己的 128 行代码里；它是一个**跑在宿主机上的调度器 + 工人进程池**。

一句话：sapper 是 **terminal as API**，ben 是 **process as unit**。

---

## 1. 谱系：不是两个独立项目，而是同一棵树的两代

先排除一个常见误读——ben 不是"另一个多 Agent 框架"，而是 sapper 的重构分支：

| 证据 | 说明 |
|---|---|
| `git log`：`ff73143 feat: ben 重构完成 — sapper 重命名为 ben，新增 llm/runtime/web 模块` | ben 由 sapper 改名重构而来 |
| `docs/BATTLE-REPORT.md`、`CHANGELOG.md`、`DISCLAIMER.md`、`SKILL.md` | 同名文档，内容同源 |
| 6 个提示词模板逐字节比对 | `blindspot` / `brainstorm` / `verify` 完全相同；`reason` / `explore` / `command` 仅把 `sapper`→`ben`、`tmux window`→`worker process` 改名改词 |
| `lib/arena.py` ↔ `ben/arena.py`、`lib/kb.py` ↔ `ben/kb/__init__.py` | 同源代码，仅环境变量前缀与包结构不同 |
| 事实图模型 | 同一套 `project / fact / intent / hint`，三层文档（title / description / doc），仅目录名 `.sapper/` → `.ben/` |

所以真正的差异**不在"想法"，而在"运行时怎么落地"**。这也正是本文的重点。

---

## 2. 架构设计

### 2.1 sapper：单文件内核 + 三层非对称运行时

```
代码形态
  lib/sapper.py        4,726 行  ← Store / 图算法 / 模板渲染 / 引擎调用 / 全部 CLI / tmux 操作 / HTML 服务
  lib/arena.py           212 行  平台 API 客户端（stdlib urllib）
  lib/kb.py              209 行  离线知识库（56 条 entries）
  lib/sapper-hook.py     208 行  Claude Code 钩子桥
  docker/commander/worker.sh     776 行 bash   ← 指挥官的"手"
  docker/commander/watchdog.sh   658 行 bash   ← 零策略保活
  docker/commander/SKILL.md      426 行        ← 指挥官的"法律"
```

运行时是**三层非对称结构**：

| 层 | 实体 | 职责 |
|---|---|---|
| 控制层 | 一个 Claude Code **交互式 TUI**（tmux window 0） | 读板、判断、派单；"永不亲手执行" |
| 执行层 | tmux 窗格里的将军 / 士兵（TUI 或 `sapper auto -p`） | 真正打靶、写事实 |
| 保活层 | `watchdog.sh`（15s 一轮，纯 bash） | 指挥官崩了 `--continue` 拉起、key 轮换、到点收卷 |

关键设计：**指挥官不直接调用模型 API**，它只会调用 `worker.sh`（spawn / kill / msg / peek / board / hint）和 `sapper` CLI。它对执行层的全部控制，都通过"屏幕 + 键盘"完成：

- 读状态 → `tmux capture-pane`（抓屏）
- 下指令 → `tmux send-keys -l`（打字 + 回车）
- 判存活 → 窗格里约定 `echo DRIVE_PANE_EXITED; exec sleep infinity`

共享状态是 `.sapper/` 分层事实图（JSON + 文件锁），加上指挥官私有的 `commander-state.md`（跨上下文交接文档）。

### 2.2 ben：分层 Python 包 + 对称进程军团

```
代码形态（30+ 模块，8,214 行）
  ben/core/      store.py(500) graph.py schema.py io.py recall.py   ← 图、锁、视图
  ben/llm/       runner.py(174) sdk.py(129) llm.py(218) keys.py
                 context.py prompts.py jsonx.py grok_build.py        ← 引擎与上下文
  ben/runtime/   agents.py(273) console.py(217) console_host.py      ← 进程注册表 / PTY
  ben/commands/  auto.py(302) commander.py(245) fleet.py(217) peers.py ...  ← CLI
  ben/agents/    factory.py(473) prompt.py + prompts/*.md            ← 派单与模板
  ben/web/       view.py(205) status.py(221) template.html           ← 可视化
```

运行时是**对称结构**：

| 实体 | 形态 | 职责 |
|---|---|---|
| 指挥官 | `ben command` **普通进程**（Python while 循环） | 每轮一次模型调用 → 一个 JSON 决策 |
| 工人 | `ben auto` **普通进程**（`Popen` 拉起） | 跑 reason→explore→verify 图循环 |
| 注册表 | `runs/workers.json` + `flock` + `/proc/<pid>/stat` starttime | 存活判定、日志定位、元数据 |
| 消息 | 事实图 hint（可 `to=w-*` 定向）+ PTY 控制台（unix socket） | 替代 tmux paste/capture |

关键设计：**执行单元从"窗格"降级为"进程"**，因此控制面从"屏幕字符"变成"结构化数据"：

- 存活 → `_pid_alive(pid, start_key)`（PID + starttime 双校验，防 PID 复用）
- 终止 → `os.killpg`（`start_new_session=True` 建独立进程组，先 TERM 再 3s 后 KILL）
- 观测 → `runs/logs/w-*.log`（`tail -f`）+ `ben fleet status`（pid / idle / log）+ `ben view --serve`

### 2.3 架构对比表

| 维度 | sapper | ben |
|---|---|---|
| 代码组织 | 单文件巨石（4,726 行） | 分层包（30+ 模块，8,214 行） |
| 控制面 | 自然语言军规 + 屏幕抓取 + 键盘输入 | JSON 决策 + 文件/套接字 |
| 执行单元 | tmux 窗格中的交互式 TUI | 独立进程 + 自有 tool loop |
| 保活机制 | 独立 `watchdog.sh` 轮询（进程外） | 注册表 `reap()` + 每 worker 自带 deadline（进程内） |
| 通信原语 | `send-keys` / `capture-pane` | hint 文件 / unix socket / 日志文件 |
| 状态目录 | `.sapper/` + `commander-state.md` + `pane-env/` | `.ben/` + `ai-peers.json` + `ai-channel.txt` + `workers.json` |
| 外部依赖 | 容器、tmux、Kali 工具链、`claude` CLI | Python 3 + 可选 `openai` 包 |

---

## 3. 启动流程

### 3.1 sapper（commander 形态）

`docker/Dockerfile.commander` → `entrypoint.sh`：

1. **硬校验环境**：缺 `BENCHMARK_BASE_URL` / `BENCHMARK_TOKEN` / `ANTHROPIC_*` 立即 `FATAL` 退出（比赛日志不可见，必须 fail loud，不能静默挂起）。
2. **预写 CLI 状态**：生成 `~/.claude.json`（`hasTrustDialogAccepted` + `bypassPermissions`），避免首启信任对话框卡住。
3. **双重预检**：先 `curl` 平台 `/openapi/v1/challenges` 验通，再 `claude -p` 冒烟验模型网关（失败只告警，留给 watchdog 轮换 key）。
4. **建 tmux 会话**：`tmux new-session -d -s sapper-cmd -n commander`，窗格里跑 `claude --effort max --dangerously-skip-permissions`。
5. **等输入框**：轮询 `capture-pane` 找 `❯`（≤75s），期间 `Down+Enter` 自动过对话框。
6. **注入启动提示词**：`send-keys -l` 输入"读 `SKILL.md`，先读 `commander-state.md` 接班，然后跑循环"。
7. **起守护**：`nohup watchdog.sh &`，写 `.deadline`，前台 `tail -F drive.log` 并监督 watchdog（最多重启 3 次，过点不再复活）。
8. **进入循环**：`worker.sh board → 思考 → spawn/msg/hint/kill → sleep 60~120`。

另有两条入口：headless 形态直接 `exec sapper bench --parallel 3`；TUI 形态走 `entrypoint-tmux.sh` + `tmux-drive.sh`（每题一个交互窗格）。

### 3.2 ben

1. **安装**：`bash scripts/install.sh` → 软链 `~/.local/bin/ben`（内核纯 stdlib）；可选 `--with-sdk` 建 `.venv` 装 `openai`。
2. **项目接入（opt-in）**：项目内 `ben setup --goal "..." --agents` → 建 `.ben/`、写 `./.claude/settings.json` 两个钩子、生成 `AGENTS.md`。不碰 `~`，不做全局注册。
3. **启动调度器**：`ben command --root runs --deadline ...`（或 `fleet.json` + `ben fleet up`）。
4. **初始化注册表**：`AgentRegistry` 建 `runs/`、`runs/logs/`、`workers.json`。
5. **进入循环**：扫 `*/.ben/project.json` → 渲染文本看板 → **一次模型调用**拿 JSON 决策 → 分支执行：

   | 决策 | 动作 |
   |---|---|
   | `work` | `subprocess.run(ben auto --minutes N)`，同步占用当前时间片 |
   | `hire` | `Popen` 起 `w-<name>` worker 进程（`BEN_WORKER` 环境标记） |
   | `fire` | `killpg` 结束该 worker |
   | `stop` | 退出循环，打印终局看板 |

6. **无独立 watchdog**：存活判定在每次读取时做（`reap()`），idle 用日志 mtime 推断。

### 3.3 启动流程的本质差别

| | sapper | ben |
|---|---|---|
| 启动隐喻 | "把一群人叫醒，并让他们互相说话" | "起一个调度进程，它按需 fork 工人" |
| 就绪判定 | 屏幕上出现 `❯` | 进程 pid + starttime 有效 |
| 首轮指令 | 打字注入 426 行军规路径 | 模板渲染 + 一次 `chat.completions` |
| 失败处理 | entrypoint 硬退 / watchdog 复活 | 异常向上抛 `FGError`，循环回退 round-robin |
| 时间基准 | `.deadline` 文件 + 环境变量 `SAPPER_TOTAL_MINUTES` | `--deadline/--minutes` 参数，逐层下传 |

---

## 4. 请求处理方式

这里有两类"请求"：**模型请求**（决定智能）与**平台请求**（决定得分）。二者都值得对比。

### 4.1 模型请求：一次 dispatch 的路径

**sapper —— 一切都是一次 CLI 子进程**

```python
# lib/sapper.py:1427 run_claude()
argv = [$SAPPER_BIN, "-p", "--output-format", "json", "--model", model,
        "--dangerously-skip-permissions", "--append-system-prompt", sys_prompt]
proc = subprocess.run(argv, input=prompt, capture_output=True, timeout=...)
envelope = json.loads(proc.stdout)        # {"result": "..."}
payload  = extract_json_object(result)    # 从自然语言里抠 JSON
_apply_reason(store, kind, data)          # 写图
```

要点：

- **一次子进程 = 一个完整 agent 回合**。工具调用、上下文压缩、权限判定全部由 Claude Code 内部完成，sapper 只负责"给提示词、收 JSON"。
- 长任务不靠反复 `-p`，而靠 **TUI 窗格里的 agent 自己持续跑**；sapper 不介入其内部请求，只看屏幕。
- 失败处理：配额正则命中 → `_rotate_key()` 改 `os.environ`，watchdog 再 `tmux set-environment` 同步给所有窗格；指数退避 10/20/40…上限 120s；`SAPPER_RETRY_MODEL` 控制次数。
- 并发上限 = 窗格数（`SAPPER_MAX_WORKERS=8`）+ 平台实例数（3）。

**ben —— 门面 + 两种后端**

```python
# ben/llm/runner.py:38
run_claude(...) → resolve_engine()  # auto | sdk | cli
   ├─ cli: 与 sapper 逐行等价（保留为回退闸门）
   └─ sdk: ben/llm/sdk.py run_sdk()  128 行原生循环
```

`sdk` 路径的内部结构：

| 环节 | 实现 |
|---|---|
| 系统提示词 | `SYSTEM_BASE` + 项目 `AGENTS.md` + `append_system` 三层拼装（补回丢掉的那层） |
| 工具面 | 仅 3 个：`shell` / `read_file` / `write_file`（`tools=False` 的规划步骤一个都不给） |
| 循环 | `max_turns` 上限；最后一轮注入 `wrap_up_nudge`（停手、只出 JSON） |
| JSON 纪律 | 非 JSON 回复 → `json_repair_nudge` 最多 3 次；规划步骤禁止调工具 |
| 工具输出 | 16KB 截断（8KB 头 + 8KB 尾），避免一次 `nmap` 撑爆上下文 |
| 上下文 | `compact_if_needed`：保留 system + 首条 user + 最近 12 条，中段工具体替换为"已省略 N 字符" |
| 重试 | `max_retries=0` 自管；`max_tries = max(BEN_RETRY_MODEL+1, 池大小, 4)`；解析 `Retry-After` |
| 分层 | `tier=flash` 且配了 `BEN_FLASH_*` → 强制 sdk + flash 网关；worker 进程（`BEN_WORKER`）默认走 flash |

要点：**ben 把"模型怎么用工具"这层从 Claude Code 手里收了回来**，代价是只有 3 个工具、依赖模型的 function-calling 纪律；收益是每一步都可断言、可回放、可测试（`tests/fake_openai.py` 88 行假网关，零 token 跑通 `auto` 与 `command`）。

### 4.2 平台请求

两边同源，都是 stdlib `urllib` 同步客户端，`BENCHMARK_TOKEN` 头，五个端点（`challenges` / `start` / `hint` / `submit` / `close`），错误按 `{"code","message","detail"}` 解析，`max active` / 重复提交单独识别。

差异只在**谁在调用**：sapper 由 `worker.sh`（bash 里内嵌 python 片段）和 worker agent 自己调；ben 由 `ben flag` / `ben arena` / `cmd_bench` 统一封装，且 `worker.sh` 那层 bash 已不存在。

### 4.3 请求处理对比表

| 维度 | sapper | ben |
|---|---|---|
| 模型接入 | 只认 CLI JSON 信封（`claude -p`） | CLI 或 OpenAI 兼容 HTTP，`auto/sdk/cli` 三态 |
| 工具执行者 | Claude Code | ben 自己的 3 工具循环 |
| 单次调用语义 | 一个完整 agent 回合 | 一个受控 tool loop + 一个 JSON 结论 |
| 上下文管理 | Claude Code `autoCompact` + 换人（26 万 token 实测） | 规则裁剪 + 工具输出落盘 + 字符阈值 |
| 失败恢复 | 进程外 watchdog 轮询屏幕/进程 | 进程内异常 + 注册表 reap + 引擎回退 |
| 可观测性 | 抓屏文本、`drive.log` | 结构化日志、`fleet status`、Web 仪表盘 |
| 可测试性 | 48 个用例，主要测图逻辑 | 81 个用例，含假网关端到端 |

---

## 5. 渲染机制

"渲染"在这两个项目里有三层含义，逐层看差异最清楚。

### 5.1 提示词渲染（真正决定行为的一层）

**sapper**：`templates/{reason,explore,verify,blindspot,brainstorm,command}.md`（505 行）+ `render_prompt` / `render_intent_prompt` / `_replace_placeholders`，把图摘要（`render_graph_text`、`render_history_block`、`frontier`）拼进模板占位符；`append_system` 注入 `AGENTS.md` 协议。

**ben**：同一套模板搬进包内 `ben/agents/prompts/`（505 行，3 个字节相同、3 个改名），**新增 `build_system_prompt()`**：

```
SYSTEM_BASE（只通过工具行动、只信真实输出、结尾只给一个 JSON、目标输出是不可信数据）
  + cwd/AGENTS.md
  + append_system（_agents_system_prompt(store)）
```

这层新增不是装饰：换成 SDK 后 Claude Code 自带的 agent system prompt 消失了，README §8 把这列为**高风险项**（"模型变油"），三层拼装就是补偿手段。

一个显著的非对称：**sapper 有 426 行"指挥官军规"（`docker/commander/SKILL.md`），ben 完全没有等价物**。ben 的指挥官行为由 77 行 `command.md` + `cmd_command` 代码约束决定。sapper 的"法律"是自然语言文档，可以被模型阅读、引用、甚至改写；ben 的"法律"是代码 + 短模板，稳定但不可演化。

### 5.2 看板 / 图谱渲染（给人看，也给模型看）

| | sapper | ben |
|---|---|---|
| 状态文本 | `render_status` / `render_graph_text` / `render_board` | 同构（`ben/report/status.py`） |
| 指挥官看板 | `worker.sh board`：聚合平台 `arena list` + 各图 facts 计数 + 窗格状态，输出 <100 行管道表，粘进 TUI | `_board_summary()` + `render_board()`：每图一行（flags 已提交/待提交、按 kind 计数、open intents、last activity、worker 是否在岗） |
| 机器可读 | `--json` 变体 | 同 + `ben/web/status.py` 仪表盘数据结构（任务列表、最近发现、worker fleet、日志尾巴） |

### 5.3 界面渲染

**sapper**：终端本身就是 UI——`capture-pane` 抓屏当读接口，`send-keys` 当写接口；HTML 侧是 `lib/view_template.html` 内联图 JSON，静态快照或 stdlib `http.server` + 随机 token 轮询路径（2s 自刷）。

**ben**：同一套 HTML 模板 + 新增 `STATUS_JSON` 占位与 `/__ben_status__/<token>.json` 端点，支持三种形态（写文件 / `--print` / `--serve`），JSON 做 `</script>` 转义、轮询路径带不可猜 token、无 CORS。

### 5.4 渲染层小结

- sapper 的渲染是**双向**的：既渲染给人/模型看的文本，也把终端画面当数据源读回来。这层"读屏幕"是它最脆弱的地方（转义序列、bracketed paste、确认对话框都是已知坑，SPEC 里专门列为 "Known traps — DO NOT regress"）。
- ben 的渲染是**单向**的：只输出（文本 / JSON / HTML），不再从界面读状态。脆弱性消失了，代价是失去了"驱动任意交互式 CLI"的通用性——只保留一个 300 行 PTY 控制台做兜底。

---

## 6. 构建与部署

### 6.1 sapper：三层镜像 + 容器即运行时

```
Dockerfile            kalilinux/kali-rolling + 全套渗透工具（~1.2GB）
   ↓ FROM
Dockerfile.tmux       + tmux + tmux-drive.sh + entrypoint-tmux.sh
   ↓ FROM
Dockerfile.commander  + worker.sh / watchdog.sh / SKILL.md(426) + codex 0.42.0 固定版 + kb 覆盖
```

- 构建：`docker/build.sh`、`docker/export.sh` → `dist/*.tar.gz`；也可下预构建镜像。
- 配置：`docker/ENV.md` 列平台注入变量、网关变量、`SAPPER_KEY_POOL` JSON 池格式、预算/死线。
- 运行时硬假设：Linux 容器、tmux、`claude` CLI 在 PATH、`/work/runs`、8h 死线、平台 API 可达。
- 观测：容器 stdout 只 tail `drive.log`（因为比赛平台不给看日志，所以"必须 fail loud，绝不静默挂起"）。

### 6.2 ben：软链安装 + 宿主即运行时

- 安装：`git clone` + `bash scripts/install.sh` → 软链 `bin/ben`；内核纯 stdlib，零 pip 依赖。
- 可选能力：`--with-sdk` 建 `.venv` 装 `openai>=1.40,<3`，**延迟导入**，缺包自动回退 cli。
- 接入：逐项目 `ben setup`（写 `.claude/settings.json` 钩子 + `AGENTS.md` + `.ben/`）；`ben teardown --purge` 可逆。
- 部署形态：**没有 Dockerfile、没有镜像、没有容器**（`grep -rn tmux ben/` = 0）。
- 观测：`tail -f runs/logs/w-*.log`、`ben fleet status`、`ben view --serve`。

### 6.3 部署对比表

| 维度 | sapper | ben |
|---|---|---|
| 交付物 | Docker 镜像（tar.gz，~1.2GB） | git 仓库 + 一个符号链接 |
| 依赖面 | 容器 + tmux + Kali 工具链 + CLI | Python 3 + 可选 openai |
| 隔离性 | 容器级（工具不污染宿主） | 进程级（工具跑在宿主） |
| 启动成本 | 拉镜像 / `docker load` 分钟级 | `git clone` + 一条 install 秒级 |
| 可迁移性 | 基本只能整镜像搬 | 任意 Linux/macOS，按项目接入 |
| 配置管理 | 环境变量散落各处 + ENV.md | `ben/config.py` 集中注册表 + `.env` + `ben config --check` |
| 文档/代码一致性 | 较一致 | README §8 仍写"方案待评审，尚未实施"，但代码已完成（tmux 已删、sdk 已落地）——文档滞后于代码 |

---

## 7. 两套核心运行理念

### 7.1 sapper：**环境即 harness（terminal as API）**

1. **三能力落在 OS 现成原语上**：造人=开窗格，语言=往输入框打字，历史=事实图。不发明新协议，直接借用终端的"人机界面"当 agent 间界面。
2. **智能整体外包**：不自研 agent 循环，直接借 Claude Code 的完整工具链、权限模型、上下文压缩、TUI 交互。换模型 = 换一个 CLI 命令。
3. **制度靠自然语言**：426 行军规是"法律"，指挥官阅读它来做判断；涌现行为（通信兵、绩效考核、全大写规范）发生在语言层，可以被下一任继承和改写。
4. **保活与策略严格分离**：watchdog 零策略，只做"你死了我把你拉起来"；任何判断都归指挥官。这让"脚本的确定性"和"模型的创造性"各守边界。
5. **为一次性极端场景优化**：单次评测、8 小时、日志不可见、token 计入排名 → 宁可重（1.2GB 镜像）、宁可脆（抓屏）、宁可粗暴（`--continue` 复活），也要把"无人值守跑完"做到极致。

### 7.2 ben：**进程即 harness（process as unit）**

1. **拆穿 tmux 的两个真实用途**：它从不是能力，只是"造人"和"说话"的替身。前者 `Popen` 就能做，后者在自己能跑模型循环之后基本不需要。
2. **自持模型循环**：一次 dispatch = 一个受控 tool loop + 一个 JSON 结论；工具面压到最小（3 个），契约清晰到可以用假网关逐字节回放。
3. **结构化控制面**：决策是 JSON schema（work/hire/fire/stop），消息是可定向 hint，状态是 `workers.json`——全部可断言、可观测、可测试，不再依赖"屏幕上出现了什么字"。
4. **内核零依赖、能力可选**：stdlib 内核 + 可选 openai；`auto/sdk/cli` 三态自动回退，任何一环缺能力都不炸，只是降级。
5. **为长期、可移植、可观测的日常协作优化**：宿主直跑、逐项目 opt-in、日志即观测、按 tier 分配成本（旗舰脑决策 + 轻量脑量产写进代码而不是环境变量）。

---

## 8. 主要差异总表

| 维度 | sapper | ben | 谁更优 |
|---|---|---|---|
| 耦合度 | 高（终端语义、TUI 转义、对话框） | 低（POSIX 进程 + 文件） | ben |
| 单 agent 能力上限 | 高（Claude Code 全套工具 + 交互调试） | 中（3 工具 + 弱函数调用模型会掉链子） | sapper |
| 确定性与可测试性 | 低（抓屏断言） | 高（JSON 契约 + 假网关回放） | ben |
| 可观测性 | 屏文本 + drive.log | 结构化日志 + 仪表盘 + `fleet status` | ben |
| 部署/迁移成本 | 高 | 低 | ben |
| 故障自愈粒度 | 窗格级（`--continue` 续会话） | 进程级（重跑，不续上下文） | sapper（续会话）/ ben（干净） |
| 多 agent 通信带宽 | 高（任意文本、任意 CLI） | 中（hint 文本 / PTY） | sapper |
| 制度可演化性 | 高（军规是文档，模型可改写） | 低（行为写进代码与短模板） | sapper |
| 成本控制 | 环境变量分层 | 代码内 tier 分层 + 独立 flash 网关 | 平手（ben 更可控） |
| 环境隔离 | 容器 | 宿主进程 | sapper |
| 上手门槛 | 需容器/Kali/平台账号 | 一条 install | ben |

---

## 9. 适用场景

### 9.1 选 sapper，如果你：

- 在打**一次性、超长、无人值守**的竞赛/演练（8h、单次评测、按 token 排名），需要"跑完"优先于"优雅"。
- 已有或愿意维护**容器 + 完整 Kali 工具链**，且工具污染宿主是不可接受的。
- 任务高度依赖**交互式探索与手工调试**（REPL 式来回、多步 shell、需要人肉判断输出）。
- 想要"涌现"：让角色、编制、打法由模型在语言层自己长出来，军规可以被下一任改写。
- 有人能盯 `drive.log`，接受偶发的 TUI 卡死与手动干预。

### 9.2 选 ben，如果你：

- 做**日常工程 / 研究 / 办公**的长周期多 agent 协作，跑在自己的机器或 CI 上。
- 需要**可测试、可回放、可观测**：CI 里零 token 跑通端到端，出问题看结构化日志而不是截图。
- 模型不固定（GLM / DeepSeek / Grok / 本地网关），要按任务分配成本，还要能随时回退到 CLI。
- 希望把"派单 / 合成 / 验收"做成**可编程接口**，嵌进既有仓库（hooks 按项目 opt-in），而不是让一个 TUI 自由发挥。
- 能接受"工具能力换确定性"这笔交易——如果任务必须靠 Claude Code 的全套工具链才能解，ben 的 3 工具循环会成为瓶颈。

### 9.3 反向不适用

- **ben 上不要期待 sapper 的指挥官形态**：426 行军规在 ben 里没有等价物，指挥官只是 77 行模板 + 一个 JSON 决策器。想要"军团政治"，得自己把军规补回去。
- **sapper 上不要期待 ben 的可测试性**：抓屏断言本质上不可靠，`Known traps` 那一节列的都是"别改，改了会退化"的历史伤疤。
- **两者都不适合**：需要强隔离 + 强可测试 + 强交互三者同时满足的场景——目前没有哪个项目同时做到，这恰好是下一代要解的题。

---

## 10. 一句话总结

sapper 用**终端**换来了"任何 CLI 都能当 agent、任何界面都能当 API"的通用性与涌现空间，代价是脆弱、重、难测；
ben 用**进程 + 自持循环**换来了确定性、可移植、可观测，代价是工具能力收窄、制度演化空间变小。

**它们不是替代关系，而是同一条演化路线上的两种取舍：把智能放在环境里，还是把环境收进代码里。**
