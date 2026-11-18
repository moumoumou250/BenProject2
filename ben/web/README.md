# ben view — 进度面板使用与状态排查手册

`ben view` 是 ben 的可视化视图：上半部分是实时进度仪表盘，下半部分是事实图谱。
本文重点回答一个问题——**看一眼面板，如何判断系统现在是正常推进、还是卡住了**。

## 1. 用途与适用场景

- **启动方式**

  ```bash
  ben view --store runs/<name>/.ben            # 静态快照（离线，单次导出）
  ben view --store runs/<name>/.ben --serve    # 实时面板（2 秒轮询，自动开启）
  ```

- **适用场景**
  - 长时间无人值守作战（比赛 / 自动化评估）：人不在 tmux 前盯屏，用面板总览全局
  - 多 worker 并行推进时，快速定位"谁在干活、谁在摸鱼、谁死了"
  - 事后复盘：静态快照即运行某一时刻的完整存档，可直接归档
  - 纯 stdlib HTTP 服务 + 随机 token 防护，可安全地在 127.0.0.1 上长期挂着

### 零 token 消耗

**面板的战术显示与实时日志均为纯本地读取，不产生任何 token 消耗。**

数据链路全部是磁盘文件：

| 面板内容 | 数据来源 |
|---|---|
| 任务 / 战术（intent、doc 简报） | `runs/<name>/.ben/intents/*.json` |
| 战果流（fact、data 键值） | `runs/<name>/.ben/facts/*.json` |
| 实时日志尾巴 | `runs/logs/w-*.log`（tail 读文件） |
| worker 状态 / timebox / idle | `runs/workers.json` + 日志文件 mtime |

`ben view --serve` 只是从这些文件聚合 JSON 供浏览器轮询——不调用任何模型、
不触发 `run_claude` / SDK 推理、不消耗网关配额。哪怕挂一整场比赛，
面板自身的开销也只有本地磁盘 IO 与每 2 秒一次的 HTTP 轮询。
worker id 中的模型名（如 `glm-5.3-8412`）只是从文件里解析出的历史字符串，不是调用。

唯一消耗 token 的是 worker 本身的推理与工具执行——面板只是把这些已发生的行为
**展示出来**，不新增任何推理。

## 2. 关键指标与字段含义

### 概览条（最上方一排）

| 指标 | 含义 | 关注点 |
|---|---|---|
| `host / service / cred / vuln / loot / flag` 彩色徽章 | 按 kind 分类的事实（战果）计数 | **数字长期不动 = 全军停滞** |
| `任务 x/y done · z claimed · w open` | 意图完成 / 认领中 / 待认领 | claimed 持续偏高而 done 不涨 = 执行层有问题 |
| `⏱ elapsed` | 项目已运行时长 | 对照 timebox 判断整体节奏 |
| `👷 n/m alive` | 存活 / 总注册 worker 数 | n < m 即有 worker 死亡 |

### 任务表（tasks 面板）

- 排序即优先级：**claimed 在最上 → open → done 沉底**
- 状态徽章：`claimed`（执行中）/ `open`（待认领）/ `done`（已完成）/ `confirm`（等人确认）
- 每行右侧灰色 meta：认领人 + 创建距今时长（`5m`、`1h`）
- 点击行 → 右侧弹出完整任务简报（description + doc，含 timebox 说明）

### 舰队卡片（fleet 面板）——**判断卡顿的核心区**

| 字段 | 含义 |
|---|---|
| 圆点 ● | 绿 = 进程存活；红 = 已死（registry 判定，含 PID 复用防护） |
| `up Xm` | 进程已存活时长（可对照任务 meta 推算 timebox） |
| `idle Xs` | **心跳**：该 worker 日志文件距上次写入的秒数。`<60s` 绿、`60–300s` 黄、`>300s` 红 |
| timebox 进度条 | 雇佣时定的 `--minutes` 时间盒剩余比例。`>30%` 绿、`10–30%` 黄、`<10%` 红 |
| `⚠ 任务超龄` | 当前任务 age > 2×timebox 时出现——疑似假死（见 §3） |
| `▸ i00x · 标题` | 该 worker 通过 PID 反查到的当前认领任务（认领人格式 `模型-pid`，与注册表进程对应） |
| `▸ last line` | 该 worker 日志的最后一行，直接暴露当前行为（在跑 nmap？在等模型返回？） |

### 战果流（loot 面板）

最新事实按时间倒序，徽章 = kind，正文 = 标题/描述，第二行 = `data` 键值（凭据、host 等）。
点击 → 联动图谱高亮该节点。**这就是"系统确实在产出"的直接证据**。

### 日志流（logs 面板）

所有 worker 日志尾巴（各取 6 行）合并展示，`[all] [w-xxx]` 按钮可过滤单 worker。

## 3. 正常 vs 异常的判定标准

### 正常推进的特征（全部满足）

1. 所有存活 worker 的 `idle` 徽章为 **绿色**（< 60 秒内有日志输出）
2. timebox 进度条 **绿色**（剩余 > 30%）
3. 战果流持续有新条目，概览条计数缓慢上涨
4. 任务表中 claimed 行随时间变成 done

### 异常判定速查表

| 状态 | 面板表现 | 判定阈值 |
|---|---|---|
| **卡顿**（变慢） | idle 徽章变 **黄**；last line 长期不变 | 日志 60–300 秒无写入 |
| **停滞**（卡住） | idle 徽章变 **红**；战果流计数冻结；claimed→done 停止转化 | 日志 > 300 秒无写入，且持续多个刷新周期 |
| **超时风险** | timebox 进度条 **黄**（<30%）→ **红**（<10%） | 对照雇佣时的 `--minutes` |
| **假死**（进程在但无产出） | 圆点绿、idle 绿（日志在动），但任务长期 claimed、无新事实；卡片上直接标出 `⚠ 任务超龄 X > 2× timebox —— 疑似假死` | 任务 age > 2×timebox |
| **worker 崩溃** | 卡片整体泛红、圆点红、显示 `✕ dead` | registry 已确认进程死亡 |
| **认领孤儿** | 任务 `claimed`，但认领的 worker 已不在舰队列表（或已 dead） | worker 崩溃时未释放认领 |
| **全员无响应** | 所有卡片 idle 红 / 全部 dead，任务全 open 无人认领 | 指挥官或模型网关故障 |

## 4. 常见异常示例与原因分析

### 示例 A：单兵卡顿 → 停滞

```
w-c01  ● 绿   idle 4m(红)   up 22m
        ▸ i003 · SQL dump
        ▸ last: "curl http://target/api/users --max-time 300"
```
- **表现**：进程活着，但日志 4 分钟没动。
- **原因分析**：last line 显示挂了一条带 `--max-time 300` 的 curl → 大概率在等一个慢速/无响应的目标端口；也可能卡在模型调用（网关限流排队）。看 last line 是**工具输出**还是**模型请求**即可区分：工具日志长时间停在同一条命令 = 目标侧阻塞；日志停在 `run_claude`/模型往返 = 模型侧阻塞。

### 示例 B：worker 崩溃，任务变孤儿

```
w-c02  ✕ 红   dead   pid 8390
任务表:  i005 [claimed]  mymodel-8390 · 1h
```
- **表现**：卡片泛红，但任务表里 i005 仍显示 claimed，认领人 `mymodel-8390` 的 pid 正是死掉的 8390。
- **原因分析**：worker 进程异常退出（配额耗尽 / OOM / 网关 401 自动轮换失败），未走到释放认领的代码路径。任务会一直"看起来有人在干"，实际无人执行。

### 示例 C：指挥官挂了，全军瘫痪

```
概览条: 任务 2/9 done · 7 open · 0 claimed     👷 0/0 alive（或 worker 全绿但任务全部 open）
日志流: 长时间无任何新行
```
- **表现**：worker 可能还活着（idle 绿），但没有任何任务被认领、没有新事实。
- **原因分析**：负责调度/派单的指挥官进程死亡或不再产出 dispatch，worker 空转等待；也可能是模型网关密钥全灭，所有模型调用失败。

### 示例 D：timebox 临近，成果不足

```
w-c03  ● 绿   idle 20s   up 28m
        timebox ▓▓░░░░ 剩 2:10 / 30:00（红）
        ▸ i008 · hard assault · last: 反复重试同一 payload
```
- **表现**：worker 很勤奋（idle 绿），但时间盒只剩 7%，任务仍未 conclude。
- **原因分析**：陷入低效循环（重复尝试同一思路）。按 doctrine 这属于止损纪律范畴。

## 5. 处理措施建议（按状态对照执行）

| 观察到的状态 | 建议动作 |
|---|---|
| idle 黄（60–300s） | 先观察 1–2 个刷新周期；点开日志流看 last line 判断是在等工具还是等模型，**不要急着杀**——nmap/大字典爆破本来就慢 |
| idle 红 + last line 是慢工具 | 查目标可达性（`curl -m 5` 手测）；确认目标死了就 `ben fleet fire --target <name>` 释放，换下一个任务 |
| idle 红 + 日志停在模型调用 | 查 `ben config --check` 与网关状态；密钥问题等轮换，网关死了重启 worker：fire 后重新 `ben fleet hire --target <name>` |
| worker 崩溃（卡片 dead） | 面板确认对应任务的认领是否释放；若成孤儿，人工 `ben release` / 让指挥官回收后重新 hire |
| 全员无响应、任务全 open | 检查指挥官进程；比赛场景依赖 watchdog 自动 `--continue` 复活，否则手动拉起指挥官 |
| timebox < 10% 且无产出 | 按 doctrine 止损：fire 该 worker，把精力/预算让给更有希望的 intent |
| `confirm` 徽章常驻 | 这是**等人类操作**，不是故障：去 `ben show intent <id>` 看待确认内容，`ben confirm` 放行或否决 |
| 面板本身不刷新 | 看右上角 live 指示：`paused` → 点 auto 按钮重新开启；`error` → serve 进程可能已退出，重跑 `--serve` |

## 6. 排查速记（三步法）

1. **看概览条**：`👷 n/m alive` + 任务 done 是否在涨 → 10 秒内定位"死没死、动没动"
2. **看舰队卡片**：哪个 worker 的 idle 徽章不是绿的就是嫌疑人 → 用日志过滤按钮只看它
3. **看 last line**：卡在工具（目标问题）还是卡在模型（网关问题）→ 决定是 fire 重雇还是等网关恢复

> 静态快照模式下数据不更新，`elapsed`、`idle` 等字段为快照生成时刻的值；
> 需要实时判定请使用 `--serve` 模式。

## 7. Agent 运行上下文的实时观测（全部零 token）

Agent 运行时的状态与上下文信息可以通过以下渠道实时查看，**所有渠道均为本地磁盘
读取，不产生任何模型调用**。按观测深度从粗到细排列：

| 观测渠道 | 看到什么 | 实时方式 |
|---|---|---|
| `runs/logs/w-*.log` | worker 进程 stdout 全量：`[auto] step N.1 reason`、每步结论摘要、失败原因 | `tail -f runs/logs/w-*.log`；面板日志流即此文件 |
| `logs/tool-<digest>.log` | 超过阈值的大体积工具输出**全文**（nmap 全量、大字典爆破等；上下文中只保留首尾，全文落盘于此） | 直接查看 worker 工作目录下 `logs/` |
| `.ben/` 事实图 | 每一步沉淀的结论与战果（fact 的 description/doc/data、intent 状态、hint 通道） | 面板 / `ben graph` / `ben status` / `ben show <id>` |
| `ben dispatch --dry-run` / `ben auto --dry-run` | **逐字预览**即将发给模型的完整渲染提示词（系统提示 + 图 YAML + 任务模板），不调用模型 | 命令输出即结果，离线可用 |
| PTY 控制台（外国交互式 CLI） | 外部 agent CLI（Claude Code 等）的**完整终端会话内容**——`ben console new <name> -- <cmd>` 起 PTY，写穿日志记录全量字节流 | `ben console attach c-<name>` 实时看屏；`ben capture c-<name>` 读日志尾巴；日志路径在建时打印 |
| `ben capture <peer>` | 已授权 peer（worker 或控制台）的近期输出 | 命令输出，读的是 hint/log 文件 |
| `.ben/ai-channel.txt` | peer 间通信的共享记录（`ben send` 双方追加） | 直接查看 |

### 各渠道的适用对象

- **原生 worker（`ben auto`，SDK 引擎）**：主体观测靠 `w-*.log`（stdout 就是推进流水），
  深挖工具细节看 `logs/tool-*.log`，沉淀结论看事实图。运行中的模型对话上下文
  （messages 列表）只存在于 worker 进程内存中、**不逐字落盘**——这是设计取舍
  （避免把上下文两份化）；需要看"模型收到的确切输入"时用 `--dry-run` 离线逐字预览。
- **外国交互式 CLI（Claude Code / Codex 等）**：`ben console` 是观测主力——
  attach 等价于 tmux 的 `capture-pane`/attach（实时看 TUI），写穿日志保留全部
  会话字节流供事后审计。这取代了旧 tmux 方案中"看窗格"的能力。

### 判断"Agent 当前在干什么"

1. `w-*.log` 最后一行：正在第几步、在 reason 还是 explore、结论摘要是什么
2. `logs/tool-*.log` 最新文件（按 mtime）：当前工具的真实输出（能看到正在扫哪个端口、爆破哪个路径）
3. 面板舰队卡片：当前认领的 intent + idle 心跳 + timebox——"任务 × 状态 × 进度"三位一体
4. 需要精确复现模型视角时：`--dry-run` 打印的提示词与实际发送逐字节一致（同一 `render_prompt`）

> 以上全部为本地文件读取与进程信号检查，观测本身不消耗 token；
> token 只被 worker 执行的推理消耗，观测行为不改变这一点。
