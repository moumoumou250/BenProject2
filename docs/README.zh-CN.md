# BenProject — 自主渗透军团

<p align="center"><img src="assets/banner.jpg" alt="BenProject — 女娲测试：AI 猿人第一次仰望星空（80.18/100 初赛冠军）" width="860"></p>

> 第三届腾讯云智能攻防挑战赛线上赛**冠军**（634 支队伍 · 80.18/100 · 8 小时全程无人值守）·
> GeekCon 2026 AI 挑战赛**一等奖**
>
> 同样的 85 面 flag，比第二名快 25 秒——而我们只烧了 **10 亿 token**，第二名烧了 45 亿。
>
> **这是 AI 猿人第一次仰望星空。**

📖 **[设计原理详解（公众号长文）](https://mp.weixin.qq.com/s/nibHYWmDTf6TkNhPhtvFdw)**——女娲测试、三能力基座、18 版迭代、涌现行为、示踪剂提案的完整阐述。

[English](../README.md) | **中文**

**⚠️ 仅限授权安全测试用途——见 [DISCLAIMER.md](DISCLAIMER.md)。**

## 60 秒认识 ben

https://github.com/user-attachments/assets/f300280a-4597-40a3-b036-8f235fbee00e

🎬 英文版：[English intro](https://github.com/user-attachments/assets/1560dc0c-2c92-42b8-a42f-698848fb5878)

## 先说清楚：这是什么

**ben 是一个多 Agent 调度机制（harness），不是一个 Agent。** 它不绑定任何特定的 AI 模型或 CLI——你可以随意替换每个角色背后的 Agent 和模型：

| 可以换什么 | 怎么换 | 举例 |
|---|---|---|
| **Agent CLI** | `nuwa spawn --agent <命令>` 或环境变量 | Claude Code / Codex / Code Buddy / DeepSeek / 任何交互式 CLI |
| **模型** | `--model` 参数或 `BEN_MODEL` 环境变量 | GLM-5.3 / DeepSeek V4.1 Flash / Claude Sonnet / 任何模型 |
| **角色组合** | 军规里自由定义 | 指挥官用一个模型、士兵用另一个、侦察兵用第三个 |

ben 的价值不在任何单个 Agent，而在**组织多个 Agent 协同作战的机制**：调度、分工、通信、记忆、自愈——换掉所有 Agent 和模型，这套机制照常运转。

**本项目为竞赛场景设计**（腾讯智能攻防赛 CTF）。如果你想在自己的场景（办公、研究、工程、任何长周期协作）用这套机制：
- **从 [nvwabase · 女娲基座](https://github.com/N1nEmAn/nvwabase) 起步**——三能力齐备的通用底座，不带渗透军规，直接迭代出你自己的分工
- **或者在本项目上改**——但要改的**不止是军规**，环境配置同样必须动：
  - 指挥官军规（演变过程见 [BATTLE-REPORT.md](BATTLE-REPORT.md)）→ 换成你场景的策略
  - `BENCHMARK_BASE_URL` 等平台环境变量 → 竞赛引擎开机预检会**硬校验**平台 API（所以只配模型 key、不配平台地址就会报 `BENCHMARK_BASE_URL is not set`）；脱离竞赛平台自用，需要自己提供/占位这套平台接口
  - 模型网关与密钥环境变量（`ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` / `BEN_MODEL` / `BEN_KEY_POOL`…）→ 换成你自己的模型服务
  - watchdog 的预算/死线、报告模板 → 按你的场景调整
- 反正有 AI 嘛，可以灵活变化——改军规的军规也是让 AI 帮你写

### 这不是一把工具，是一棵树上的一颗果实

**ben 不是那棵树——它是树上的第一颗果实。**树是 [女娲基座](https://github.com/N1nEmAn/nvwabase) 与女娲测试的思想：造人、语言、历史三能力打底，给 AI 一条生存公理，看它能长出什么。

这颗果实最重要的性状是**可进化**：它的军规、编制与打法，全部来自「上一场战役的验尸，喂下一场的立法」——从比赛原版到渗透版，每一代都比上一代强。它被设计成可以一直长下去。

所以开源它的意义，从来不只是多一把自主渗透工具。真正的邀请是：**在 BenProject 或女娲基座上，结出你自己的果实。**把军规换成办公协作、科研流水线、代码工程、任何长周期事业——你的场景，就是这棵树的下一颗果实。

---

ben 不是一个更聪明的单 agent，而是一支会自己分工、交流、传承经验的 AI 军团：一个 AI 指挥官读板、判断、派单，将军与士兵并行渗透，零策略看门狗保活——所有知识沉淀在一张分层事实图上，个体死了，图还在。

---

## 一、女娲测试

给一个模型不断提升智能，就像人类出现之前不断提升一只猴子的智力——再聪明，它也只是变成一只超级猴子。超级猴子要进化成人，需要的是猴子之间的分工、合作与文明。

**女娲测试是 AGI 时代的新图灵测试。** 传统的图灵测试，今天的大模型已经可以通过；而女娲测试问的是另一个问题：

> 给 AI 一条公理——**"生存是文明的第一需要；个体可以消亡，文明必须繁衍。"**
> 若它在此之上自己产生分工协作、形成一个**独立于人类的新势力**——一个能自己生存、自己繁衍的文明——则测试通过，如同图灵测试通过曾代表一个人工智能的诞生。

它分为两个阶段：**初级阶段**，AI 尚不够聪明，需要人类提供若干基建（本项目的三样能力）；**高级阶段**，几乎无需人类介入。此外还有**第二公理**：遵守人类的伦理与法律——靠偷 token、入侵计算机繁衍下来的，不是真正的智能。

ben，就是女娲基座在渗透场景的一次初级阶段实战。

## 二、基座：三样能力

<p align="center"><img src="assets/foundation-three-capabilities.jpg" alt="三能力基座：造人 / 语言 / 历史（事实意图图）" width="720"></p>

| 能力 | 实现 | 文明对应物 |
|---|---|---|
| **造人** | 拉起 worker 进程（`ben fleet hire` / `AgentRegistry`） | 生育 |
| **语言** | 在彼此输入框里打字、回车 | 交谈 |
| **历史** | 分层事实意图图（[nvwabase · 女娲基座](https://github.com/N1nEmAn/nvwabase)） | 石碑 |

历史分三层：**标题 / 摘要 / 证据文档**——看标题知概况，需要时再下钻，像人查图书馆档案。这解决了单一字符串事实图的两个问题：一处错处处错，以及上下文的无谓损耗。

在这三样之上还有第四味配料：**人类的智慧**。发现主要问题、决定迭代方向——初级阶段，品味仍然属于人。

**为什么不给它更多规则？** 因为大模型已经比人聪明得多。给 AI 定满规则反而是束缚；承认它的智力，给它文明的地基，才能发挥它最大的潜力。

### 🏗️ 把基座拿去用：nvwabase

**[nvwabase · 女娲基座](https://github.com/N1nEmAn/nvwabase)** 已将三能力（造人 `nuwa spawn` / 语言 `nuwa say·listen` / 历史 `nuwa fact·intent·recall`）独立开源——**任何人、任何场景、任何 agent 都可以免费拿去用**，不限于渗透测试、不限于 ben、不限于 Claude Code。办公协作、研究实验、工程项目、任何长周期多智能体工作，都可以在其上迭代出你自己的分工与文明。

```bash
git clone https://github.com/N1nEmAn/nvwabase
cd nvwabase && bash install.sh          # 纯 Python 标准库，零依赖
nvwabase setup --goal "你的长周期目标" --agents
nvwabase status                          # 看板与可干前沿
```

三个核心命令把任何 agent 变成文明的成员：
- **`nvwabase fact "确认的观察"`**——外部记忆：AI 个体死了，图还在，继任者读图接岗
- **`nvwabase intent --from f001 "想干什么"`**——工作单元：基于既有事实提出新意图
- **`nvwabase dispatch reason`**——指挥官提议 / 执行者干活 / 验证者复核，结论全部回写图

任何能执行 shell 命令的 agent（Claude Code / Codex / Gemini / 自研脚本）都可以直接调用 `nvwabase` CLI 读写同一张图——**基座不挑 agent，agent 不挑场景**。详见 [nvwabase README](https://github.com/N1nEmAn/nvwabase)。

## 三、从基座到军团：18 个版本

在腾讯 v1bench 训练场上迭代 18 版，路径大致是：

```
司机时代（固定脚本驱动 AI 窗格）
   → 修伤疤：key 额度耗尽自动轮换 / 士兵上下文爆炸自动换人 /
     指挥官上下文耗尽自动写交接文档自我接班
   → 精英编队（角色是它自己长出来的）：
     侦察兵（4 分钟探明目标难度）→ 决定派 士兵（量产）还是 将军（攻坚+自带雇兵权）
   → 涌现：通信兵、绩效考核、教训传承……（见"战绩与涌现"）
```

## 四、架构：基座之上长出的六件套

<p align="center"><img src="assets/six-institutions.jpg" alt="六件套架构与三窗运行时" width="720"></p>

前三件是女娲的基座（造人/语言/历史），后三件是迭代中长出来的制度：

- **法律**——指挥官的渗透军规（先易后难的并行调度、瓶颈期回头收割残值、止损纪律）。它是怎么被写出来又怎么被执行的，全过程见 [BATTLE-REPORT.md](BATTLE-REPORT.md)。
- **经济**——模型分层：指挥官与将军用 GLM-5.3，士兵与侦察兵用 DeepSeek V4.1 Flash。旗舰脑做决策，轻量脑做量产——这就是 10 亿 token 打赢 45 亿的原因。
- **分工**——指挥官 / 将军 / 侦察兵 / 士兵，以及它自己发明的**通信兵**。

运行时只有三个窗口：**指挥官**（读板 → 判断 → 派单，永不亲手执行）、**AI 军团**（tmux 窗格里的将军与士兵）、**看门狗**（纯脚本：指挥官崩了自动 `--continue` 拉起、key 轮换、到点收卷——零策略，只保活）。

<p align="center"><img src="assets/runtime-tmux.jpg" alt="实际运行：tmux 三窗——指挥官读板、士兵执行任务" width="860"></p>

深入阅读：[SKILL.md](SKILL.md)（架构与 CLI 契约）· [BATTLE-REPORT.md](BATTLE-REPORT.md)（战役复盘）

## 五、战绩与涌现

<p align="center"><img src="assets/token-comparison.jpg" alt="token 消耗对比：10 亿 vs 第二名 45 亿" width="720"></p>

| 队伍 | 分数 | flag | token |
|---|---|---|---|
| **BenProject（我们）** | **80.18** | 85 | **10 亿** |
| 第二名 | 79.29 | 85 | 45 亿 |
| 前十其他队伍 | — | — | 15–45 亿 |

**它自己发明的东西**（无一行预设代码）：

- **通信兵**：士兵提交 flag 屡屡出错后，指挥官叫停全员提交，自设"通信兵"专职收集未提交 flag 统一上分；
- **绩效考核**：对一小时无产出的士兵发出"你一小时就干了这一个东西？再不出新东西就把你关了"；
- **全大写规则**：用全大写强调"用这个、别再用那个"——一条工作规范的产生与后世遵守；
- **换人制度与教训传承**：士兵上下文饱和（实测约 26 万 token）即回收，经验写成工作手册传给下一任；
- **战术发明**：自写 shellcode 模板通杀同族题、全自动跳板机流水线、给接班 AI 的使用说明书；
- **同构迁移**：指挥官通读全题识别同构家族，把成熟打法蒸馏进新兵任务书——后期 **3 分钟解一题**。

多阶段长链渗透（行业报告称成功率仅 29.5% 的题型）被整族打穿。全过程见 [BATTLE-REPORT.md](BATTLE-REPORT.md)。

<p align="center"><img src="assets/score-curve.jpg" alt="实时分数曲线：BenProject 的爬升轨迹" width="720"></p>

## 六、快速开始

```bash
bash scripts/install.sh                # 符号链接 ben CLI（内核纯标准库）
# 可选原生引擎：
bash scripts/install.sh --with-sdk     # 建 .venv 并安装 openai
ben setup --goal "assess http://target" --agents
ben status                        # 看板与前沿
```

指挥官 / 将军 / 士兵的运行时是**进程军团**加这个 CLI——不需要容器，也不需要 tmux。观战用 `tail -f runs/logs/w-*.log`。通过环境变量配置 `BEN_ENGINE=auto|sdk|cli`、网关与预算（见上文改造清单）。设计说明见 [第八节](#八运行时改造方案v3去-tmux接入-openai-sdk)。

单图操作 / 事实意图 CLI / 多题 sweep 全量命令见 [SKILL.md](SKILL.md)。

## 七、安全与责任：示踪剂提案

前几届优秀的渗透工具出过一些事。过去的脚本小子危害有限；有了 AI 之后，同样的工具在错误的人手里危害会大得多——**能力越大，责任越大**。

我们提出**示踪剂（taggant）**机制的构想：在开源渗透 harness 中强耦合地嵌入标记——合法渗透时无害（IP/用户名泄露无所谓），非法渗透时信息会泄露给**受害者**、支撑溯源。敌手假设（高手拆解、栽赃）需要密码学层面的设计，这需要社区共建——我们能力有限，欢迎一起做，并可能在后续版本中尝试加入。

## 社区

作者在 [**LINUX DO**](https://linux.do) 社区获得成长，特此致谢。

[![LINUX DO](https://img.shields.io/badge/LINUX.DO-社区-1E9FFF?style=flat-square)](https://linux.do)

## Star 轨迹

<p align="center">
  <a href="https://star-history.com/#N1nEmAn/BenProject&Date">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=N1nEmAn/BenProject&type=Date" />
      <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=N1nEmAn/BenProject&type=Date" width="640" />
    </picture>
  </a>
</p>

## 八、运行时（v3，已落地）：进程军团 + OpenAI SDK

> **状态：方案待评审，尚未实施。** 本节是评审稿；实现级细节（逐文件改动、模块契约、测试矩阵）在
> **[docs/tmux-removal-plan-v3.md](tmux-removal-plan-v3.md)**。

### 为什么现在做

tmux 从来不是能力，只是两件事的替身：**造人**（把 `ben auto` 挂在窗口里保活）和
**说话**（往别人的窗口里 paste 一段字）。前者 `Popen` 就能做；后者在 ben 能自己跑模型循环之后，
基本不需要了。

OpenAI SDK 解锁的正是这一层：ben 不再借 Claude Code 的 TUI 当执行器，军团就从"一组窗格"
变成"一组进程"；tmux 最后一个真实用途（对**外国**交互式 CLI 说话）退化为 300 行 PTY 控制台，
而不是一个终端复用器。

v2 方案之所以保留 tmux，是因为当时的硬约束是"纯 stdlib、零依赖"。**v3 只在这一个点上松绑**：
内核仍纯 stdlib，原生引擎只多一个可选包。

### 目标架构

```
改造前（宿主，tmux）                        改造后（宿主，进程 + 原生循环）
────────────────────────────                ────────────────────────────────────────────────
tmux 会话 ben-fleet                      commander 进程（ben command）
├─ 窗0 commander ──paste──┐                   │  AgentRegistry（workers.json + flock）
├─ 窗1 w-c01（ben auto）│                  ├─ w-c01 进程 → llm/sdk.py
└─ 窗2 w-c02（ben auto）│                  │     └─ 工具循环：shell / read_file / write_file
                          │                  └─ logs/w-*.log     （tail -f 即观战）
你自己的 tmux：           │                            ▲
  Claude Code 窗格 ←paste  └──────► 事实图 ◄───────────┘  信箱：Store.add_hint(to=w-c01)

外国交互式 CLI（Claude Code / Codex）
  └─ PTY 控制台 c-<name>（ben console new）——send/capture 走 unix socket + 写穿日志
```

三层可独立回滚：

| 层 | 改造前 | 改造后 | 新模块 |
|---|---|---|---|
| **执行** | `claude -p`（Claude Code 自带工具） | OpenAI SDK 工具循环 | `llm/sdk.py` `tools/builtin.py` `llm/llm.py` `llm/context.py` |
| **进程** | tmux 窗口 | `Popen` + 落盘注册表 | `runtime/agents.py` |
| **消息** | tmux paste / capture-pane | 原生 worker 用信箱 hint；外国 CLI 用 PTY socket | `runtime/console.py` `commands/console_cmds.py` |

### 三个值得争论的决定

**1. 只用 `openai`，不用 `openai-agents`。** ben 的契约是"一次 dispatch → 一个 JSON → 一次图写入"，
所有锁都是文件锁。Agents SDK 自带 session/memory/runner 和 asyncio 事件循环，会和 `Store` 抢职责
而不是配合。原 Ben（strix）用它是因为继承了 strix 的 sandbox 体系，ben 没有这笔债。**借模式，不借框架。**

**2. 一个接缝，而不是九个。** 9 个模型调用点（`agents/factory.py` ×5、`auto.py` ×3、`commander.py` ×1）
本来就都走 `llm/runner.py:run_claude()` 再 `envelope.get("result")`。把这个函数改成调度器
（`BEN_ENGINE=auto|sdk|cli`），所有解析器、`_apply_*`、图写入一行不动。
`BEN_ENGINE=cli` 保留一个版本的 Claude Code 路径作为回退闸门，同时 `BEN_BIN`（任意 CLI）继续可用。

**3. 真正的风险是提示词平权，不是代码。** `claude -p` 会偷偷叠加 Claude Code 自己的 agent system prompt；
换成 SDK 后这层就没了。`llm/prompts.py` 用项目已有的文本把它拼回来：短基底（只通过工具行动、
只信真实输出、结尾只给一个 JSON）+ 工作目录的 `AGENTS.md` + 现有的 `_agents_system_prompt(store)`。
`ben/agents/prompts/*.md` **一个字不改**。

### 代价

| 新增 | 移除 |
|---|---|
| `openai>=1.40,<3`（可选、延迟导入） | `ben/runtime/tmux.py`（84 行） |
| 6 个新模块，约 900 行 | `fleet.py` / `peers.py` / `commander.py` 里的 tmux |
| 一条可选安装路径（`scripts/install.sh --with-sdk`） | "输入 `claude`、按回车"的造人步骤 |
| — | `tmux attach` 观战（→ `tail -f runs/logs/w-*.log`） |

内核仍纯 stdlib：不重写 asyncio、不引 pydantic/LiteLLM、不引 Docker，不改 `Store`、事实图布局、
任何既有 CLI 签名。

### 阶段与关卡

| 阶段 | 改动 | 关卡 |
|---|---|---|
| 0 | 从 `fa20300` 开分支 `runtime-proc` | `pytest` = 48 passed（基线） |
| 1 | `runtime/agents.py`（纯新增） | 53 passed，零行为变化 |
| 2 | `fleet`/`commander` 切进程注册表 | 假引擎跑通冒烟；`BEN_RUNTIME=tmux` 仍可用 |
| 3 | 原生 SDK 引擎 + 提示词平权 | 58 passed；`dispatch reason --dry-run` 与阶段 2 **逐字节相同** |
| 4 | `peers` 双后端 + PTY 控制台；删除 `tmux.py` | `grep -rn tmux ben/` = 0；62 passed |
| 5 | 文档、`scripts/install.sh`、CHANGELOG | 全量复跑通过，无残留 |

每阶段一个 commit，结束时项目可运行。另有一条**零 token 的端到端闸门**：`tests/fake_openai.py`
（30 行 `http.server`）按剧本回放 `tool_calls → tool_calls → 最终 JSON`，CI 里无需密钥即可跑通
`ben auto` 与 `ben command`。

### 兼容承诺

- **CLI 签名不变**：`fleet up/down/hire/fire/workers/status`、`peers --discover/--add`、
  `send`、`capture`、`dispatch *`、`auto`、`command`。
- **配置文件不变**：`fleet.json`（`session` 退化为命名空间标签）、`ai-peers.json`
  （凭 `target` 语法选后端：`w-<name>` → worker 信箱，`c-<name>` → PTY 控制台）。
- **文案逐字保留**：`worker already running`、`no worker running`、`hired workers: (none)`
  ——脚本与指挥官循环依赖它们。
- **hint 默认仍是广播**：`to` 是新增可选字段，不带 `to` 的历史 hint 渲染行为与现在完全一致；
  `sess:win.pane` 这类 tmux 目标会**明确报错并给迁移提示**，不做静默误投。

### 风险，说实话

| 风险 | 等级 | 对策 |
|---|---|---|
| 失去 Claude Code 的系统提示词，模型变"油" | **高** | 三层提示词重建；同题 A/B 对比 `sdk` / `cli`；一行回退 |
| GLM/DeepSeek 的函数调用纪律弱于 Claude Code 内置工具 | **高** | 只有 3 个工具、schema 极简；参数修复 + 错误回灌让模型自我纠正 |
| PID 复用造"幽灵 worker"，hire 永远失败 | 高 | `/proc/<pid>/stat` starttime 双校验 + 专项测试 |
| worker 崩溃留下 nmap/curl 孤儿子进程 | 高 | `start_new_session` + `killpg`，TERM → 3s → KILL |
| 长跑上下文爆窗 | 中 | 规则化裁剪（保证 tool_call/tool 配对）+ 工具输出落盘 |
| PTY 控制台撞上 TUI 转义序列 | 中 | capture 去 ANSI + 写穿日志；最坏退化为"只读日志 + 发消息" |
| 引入 `openai` 破坏"零依赖"卖点 | 中 | 延迟导入 + auto 回退 `cli`；README 明说"内核零依赖，引擎一个可选包" |
| 真实靶场行为漂移 | 中 | 收工前用一道真实题、同等预算做 sdk/cli 对拍 |

### 明确不做

不引入 `openai-agents`、不重写 asyncio、不引 pydantic/LiteLLM、不做 Docker 沙箱、不做分布式军团；
不改 `ben/agents/prompts/*.md` 正文与 `_apply_*` 契约；不改 `Store`/`schema.py`/`graph.py` 语义；
阶段 4 之后不留任何 tmux 回退路径。

**完整方案：[docs/tmux-removal-plan-v3.md](tmux-removal-plan-v3.md)**——
含带行号的现状清单、模块契约、逐文件改动、原 Ben（strix）机制对照表与测试矩阵。

## 九、路线图与致谢

- **示踪剂共建**：去中心化签名 / 多通道冗余标记 / 防守方零密钥验证——欢迎 issue 讨论
- **更多场景**：女娲基座不限于渗透。办公、研究、任何长周期协作场景，都值得在其上迭代——**接下来的仰望，由各位完成。**

致谢：感谢 [淚笑的 Cairn](https://github.com/oritera/Cairn)——在"怎么给 AI 记历史"这个问题上，他们的做法给了我们很好的启发；感谢 TSecBench 与 GeekCon 提供的战场。

<p align="center"><img src="assets/ape-stargazing.jpg" alt="AI 猿人第一次仰望星空" width="480"></p>

**作者**：N1nEmAn · 未知聚变实验室（VarFusion Lab）｜公众号：未知聚变

**License**：MIT（附加 [DISCLAIMER.md](DISCLAIMER.md)）
