# 定位调整方案 v1 —— 从「比赛战报」到「能被陌生人使用的多智能体渗透引擎」

> 基线：HEAD `ff73143`（ben 重构完成）。`ben/` 58 个模块、10,085 行；`tests/` 9 个文件、158 个用例。
> 对照物：`/home/kali/Desktop/AI/strix-main`（strix-agent 1.7.0，Apache-2.0）。
> 本文只谈**定位与分阶段重构**，不重复 [OPTIMIZATION-PLAN-v4.md](OPTIMIZATION-PLAN-v4.md) 里的代码质量问题（R-01～R-14）。
> 承接 2026-11-18 17:2x 的定位盘点（「夺旗竞赛 → 靶场渗透评估」）结论，并把那次盘点扩展成一条**产品化路径**：不仅换判据，还要换目标、换产物、换边界、换分发。

---

## 0. 结论先行

1. **strix 卖的是「一条命令 + 沙箱 + 报告」**，ben 现在卖的是「一个文明寓言 + 一次比赛成绩」。前者陌生人 5 分钟能用，后者只有作者能用。
2. ben 不该做 strix 的平替（单 agent + Docker + SARIF 这条赛道它已经跑满），而应把**已经领先的那一半**产品化：**多智能体编排 + 带 provenance 的事实图**。
3. 重构顺序必须是 **叙事 → 目标 → 产物 → 边界 → 分发 → 可复现**。跳过任何一步，后面的工作都会被「这是比赛玩具」的叙事拖回去。

**新定位一句话：**

> ben 是一个多智能体渗透编排引擎：把一次渗透拆成可并行、可审计、可复现的任务图，交给一队模型分工执行，产出带证据链的 findings 报告。

---

## 1. 两个项目现在的定位（实测对照）

| 维度 | strix | ben（当前） |
|---|---|---|
| 首屏一句话 | "Autonomous AI hackers that find and fix your app's vulnerabilities" | "The Autonomous Pentest Legion" + 女娲测试 / 文明隐喻 |
| 目标是谁 | 开发者、安全团队、CI 流水线 | 作者自己、比赛评委 |
| 跑什么 | `strix --target ./app` | `ben setup --goal "assess http://target"` → `ben status` |
| 对什么跑 | 目录 / GitHub 仓库 / URL / OpenAPI / Postman | **只有比赛平台的 challenge code** |
| 装什么 | `curl … \| bash` 或 pipx/uv | `bash scripts/install.sh`（软链 `bin/ben`，无 `[project.scripts]`） |
| 依赖门槛 | Docker + 任意 LLM key | Python 3.11+ + 模型 key + **`BENCHMARK_BASE_URL`** |
| 产物 | findings + SARIF/MD 报告 + `strix_runs/` + `strix view` 面板 | 事实图（给 agent 读）+ `runs/logs/` + `ben view` 面板 |
| 无人值守 | `-n` headless，发现漏洞 exit≠0 | 无 `-n`、无退出码语义、无 `--resume` |
| 分发面 | GitHub Action、MCP、`npx skills add`、Cloud CLI、Enterprise | 无 |
| 规模化 | Graph of Agents（单机多 agent，17 个工具目录） | commander / general / scout / soldier / signalman + 进程 fleet（**更强**） |

**关键不对称**：ben 在「编排」上领先（角色分化、hint 信箱、密钥轮换、`/proc` starttime 防 PID 复用、证据闸门、8 项架构检查、158 个测试），在「产品契约」上几乎为零。

---

## 2. 定位诊断：三处硬伤（都带证据）

### 2.1 没有「目标」这个东西

```bash
grep -rn "add_parser(\"scan\"\|add_parser(\"target\"" ben/   # 空
wc -l ben/arena.py                                          # 214 行
```

「目标」在整个仓库里只有两种形态：`--goal` 的一段自由文本，或 `benchmark.py` 里的 `challenge/flag` 原语（`list_challenges` / `start_challenge` / `submit_flag`）。
结果：**陌生人拿到代码，不知道能对自己的应用做什么**。README 自己写了这句免责：「running off the competition platform means providing or stubbing that platform interface yourself」。

### 2.2 没有「产物」

```
ben/report/            → brief.py  history.py  status.py      （只读渲染，给终端看）
strix/report/          → sarif.py(1185) state.py(1240) coverage.py dedupe.py usage.py pricing.py writer.py  = 5,769 行
```

ben 的输出是**事实图**——它是给下一个 agent 读的中间表示，不是给用户读的结论。缺的是：findings（严重度 / CVSS / OWASP 分类 / PoC 证据）、报告导出、CI 可消费的 SARIF。

更深一层缺口在数据模型（已核实）：

- `ben/consts.py:30` `FACT_KINDS = ("host","service","cred","vuln","loot","flag","note")` —— **没有 `finding`，也没有 severity 枚举**；
- `ben/core/schema.py` 的 `data` 是自由 key=value，不做枚举校验 → 严重度/OWASP 无法被机器约束；
- 事实按约定不可变，唯一的状态机是 `store.py:519 update_flag_fact`（recorded → submitted/rejected/duplicate）—— finding 的生命周期只能复用这个模式，需要一条新 ADR；
- `ben/commands/probe_cmds.py`（423 行）已经有 `CONFIRMED / UNVERIFIED / NOT_CONFIRMED` 判定、证据目录和**阴性对照**（`<name>-miss.jsp` baseline 取不到才判 CONFIRMED），但只服务 KB 校验 → 应抽成 `core/recheck.py` 复用，**不要另写一套复核逻辑**。


### 2.3 没有「边界」

```python
# ben/tools/builtin.py —— 全部工具就 3 个
shell / read_file / write_file          # 路径白名单 = cwd 及其子目录
```

- 无容器、无网络出口策略、无命令审计（v4 的 R-12：`import logging` 0 处，`runs/logs/` 只有裸 stdout）。
- strix 的默认姿势是 Docker 沙箱，这是**安全工具的产品门槛**：陌生人凭什么叫一个会 `shell` 的 AI 军团在自己机器上跑？

### 2.4 分发面缺失（附带问题）

`pyproject.toml` 只有 `[project]` + `[project.optional-dependencies]`，**没有 `[project.scripts]`** → 装不上、跑不了 `ben`；没有 `-n`/退出码/`--resume` → 进不了 CI；没有 MCP/skills → 接不进 coding agent 生态。

### 2.5 叙事还在自我拆台

README 448 行里，Quick Start 在第 237 行，前面 236 行是文明论、三能力、18 个版本、涌现故事；§8 标题写 `Runtime (v3, implemented)`，正文第一行写 `proposal, not implemented`。**首屏没有回答「这是什么、给谁用、一条命令、得到什么」。**

### 2.6 判据没有 ground truth

`tests/TestRange/`（1,702 行）只做启动与连通自检，`profiles/*.toml` 仅有 `[deploy][target][health]`，**没有 expect / 严重度**；更关键的是 `git ls-files tests/TestRange` = **0** —— 这套靶场定义未纳入版本控制，判据的 ground truth 随时会丢。

定位从「夺旗」转向「渗透评估」时，这一点是硬约束：**没有 ground truth，就没有误报率；没有误报率，findings 只是另一种 flag。**


---

## 3. 新定位

### 3.1 一句话与三条支柱

> **ben = 多智能体渗透编排引擎。** 目标是一条命令对任意 target 起一队 agent，产出一份带证据链的报告；比赛只是其中一个 target 来源。

| 支柱 | 现在的资产 | 要补的 |
|---|---|---|
| **编排**（护城河） | 角色分化、fleet、hint 信箱、PTY console、密钥池、看门狗 | 运行轨迹、replay、按角色预算/成本 |
| **证据**（可信度） | 三层事实图（title / gist / doc）、证据闸门、`source_intent` 溯源 | findings 投影、报告导出、SARIF |
| **边界**（可用前提） | 路径白名单、`start_new_session` + `killpg` | 沙箱后端、网络策略、命令审计 |

### 3.2 与 strix 的分工：不做平替

| | strix | ben |
|---|---|---|
| 单位 | 一个 agent，工具多（17 个工具目录） | 一队 agent，工具少（3 个）+ 编排强 |
| 优势场景 | 单应用快速全量扫描、CI 卡点 | 长时程、多目标、需要并行与交接的评估 |
| 交付物 | 漏洞 + 修复补丁 | 漏洞 + **为什么这么判断**（事实图即审计轨迹） |
| 借什么 | 产品契约（目标/沙箱/报告/退出码/分发） | — |

**借契约，不借实现**：不复制它的 17 个工具、不引 LiteLLM/`openai-agents`、不做 TUI、不重写内核（stdlib kernel + 可选 `openai` 这条线保持）。

### 3.3 三条反目标（写进 README，防定位漂移）

1. **不追工具数量** —— 工具军备是 strix 的战场，ben 的战场是「谁来决定用哪个工具、什么时候换人」。
2. **不做纯哲学 README** —— 哲学迁到 `docs/PHILOSOPHY.md`（P0 新建），首屏只放产品契约。
3. **不为比赛牺牲通用性** —— 比赛从「身份」降级为「一个 adapter + 一份案例」。

---

## 4. 分阶段重构（6 阶段，一阶段一 commit）

| 阶段 | 主题 | 改动面 | 关键交付 | 机器可判验收 |
|---|---|---|---|---|
| **P0** | 叙事收口 | 文档 3 个文件，0 行业务代码 | README 重排、POSITIONING、PHILOSOPHY | `scripts/ci/readme_contract.py` 绿 |
| **P1** | 目标抽象 | 新增 `ben/targets/`，~600 行 | `ben target add` / `ben scan`，arena 降为 adapter | 无 `BENCHMARK_BASE_URL` 下扫描本地靶场成功 |
| **P2** | 产物：findings + 报告 | ~700 行，`report/` + 1 个新命令 | `ben findings`、`ben report --format md\|json\|sarif`、退出码 | SARIF 必填字段断言 + PoC 可复现 |
| **P3** | 边界：沙箱与审计 | ~500 行，`tools/` + `runtime/` | `BEN_SANDBOX=local\|docker`、命令审计 JSONL、网络策略 | 逃逸用例全部被拦 |
| **P4** | 分发：可安装、可集成 | ~400 行，打包 + `.github/` | `[project.scripts]`、`-n`/`--resume`、GitHub Action、MCP | 干净 venv `pip install . && ben --version` |
| **P5** | 军团可复现（护城河） | ~400 行 | run trace JSONL、`ben replay`、按角色成本 | 零 token 回放产出同构 findings |

### P0 叙事收口（先做，因为后面每步都被它拖）

**做什么**

- README 前 30 行固定四件事：定位句 / 给谁用 / 一条命令 / 输入→输出一张图。原文 §1–§5（女娲测试、三能力、18 个版本、涌现）整体移入 `docs/PHILOSOPHY.md`；§5 战果压缩成首屏三行 + 链到 [BATTLE-REPORT.md](../BATTLE-REPORT.md)。
- 修 §8 `implemented` / `proposal, not implemented` 自相矛盾；把 §8 从「方案评审稿」改写成「运行时说明」。
- 新建 `docs/POSITIONING.md`：本文的三张表（现状对照 / 与 strix 分工 / 反目标）。
- `docs/INDEX.md` 登记新文件。

**验收（写成检查，不写成规矩）**

新增 `scripts/ci/readme_contract.py`，纳入 `preflight.sh`：

1. README 前 30 行必须出现「定位句 / target / 产物」三个关键词组；
2. README 的 `quickstart` 代码块里出现的每条 `ben <sub>`，必须能在 `ben/cli.py` 的 parser 里找到同名子命令（防文档先于代码）；
3. `docs/PHILOSOPHY.md` 必须存在且被 README 链接（防哲学回流首屏）。

> 这条检查对应 ADR 0005 的规则预算：**能写成检查的，不写进 AGENTS.md。**

### P1 目标抽象（产品脊柱第一段）

**做什么**

- 新概念 `Target`：`{type: repo|url|openapi|image, locator, auth?, scope?}`，落 `.ben/targets.json`。
- `ben target add ./app` / `ben target add https://app.example.com --scope api.example.com`。
- `ben scan [target] [--mode quick|deep] [--budget 30m] [-n]`：组合 `setup --goal` + `auto` 作为**唯一产品入口**（旧命令全部保留为低层动词）。
- `ben/arena.py` → `ben/targets/arena.py`，`BENCHMARK_BASE_URL` / `BENCHMARK_TOKEN` **只允许**在该文件里读；arch_check 增加一条禁止规则。
- `ben/targets/local.py`：本地目录 + 活体 URL，把当前「challenge code」的位置换成 target id。
- **前置（1 条命令，零风险）**：`git add tests/TestRange`，把 1,702 行靶场定义纳入版本控制 —— 否则 P2 的 ground truth 随时会丢。

**验收**

```bash
env -u BENCHMARK_BASE_URL ben scan ./lab/juice-shop --mode quick --budget 5m -n   # exit 0/1，不是报错退出
pytest -q                                                                          # arena 场景测试仍绿
grep -rn "BENCHMARK_" ben/ | grep -v "ben/targets/arena.py"                        # 空
```

**风险**：arena 的 `challenge/flag` 语义渗进 core。缓解：core 只认 `target_id`，flag 提交是 arena adapter 的私有动词。

### P2 产物：findings + 报告（杠杆最高）

**做什么**

- **不新建存储**：finding 是事实图的**投影**。`FACT_KINDS` 增加 `finding`，`data{severity, cvss, owasp, target, evidence_doc, poc}` 进 `schema.py` 的枚举校验（当前是自由 key=value），`source_intent` 天然给出来源尝试。
- **复用已有复核**：把 `probe_cmds.py` 的 `CONFIRMED / UNVERIFIED / NOT_CONFIRMED` + 阴性对照抽成 `core/recheck.py`，`verify` 动词改调它，而不是模型自评。
- **状态机复用 flag 的先例**：`store.py:519 update_flag_fact` 是「事实不可变」的唯一例外；`update_finding_state(open → confirmed / false_positive / accepted_risk)` 照同一个写法定，并补一条 ADR 说明为什么允许。
- `ben findings [--severity high]` 终端表格；`ben report --format md|json|sarif -o out/`。
- 退出码契约：`--fail-on high` → 1；环境/配置错误 → 2；无发现 → 0（CI 可用）。
- `ben view` 增加 findings 视图（复用现有模板，不加服务端）。
- 报告头部固定 provenance：run id、model、预算消耗、target、时间线——这是 ben 相对 strix 的差异点。
- **误报率是这套东西的验收指标**：`profiles/*.toml` 增加 `[expect]`（漏洞 id + 严重度），扫描结果与 expect 比对算 precision/recall，写进报告摘要。

**验收**

- `tests/test_report.py`：SARIF 2.1.0 必填字段（`version` / `runs[].tool.driver` / `results[].ruleId,level,locations`）断言通过；
- 一次真实扫描产出 ≥1 个 finding，报告中 PoC 命令可重放成功；
- 双向可追溯：`finding.id → fact.id → source_intent`，`ben doc <id>` 能取到完整证据。

**风险**：投影与图不一致。缓解：finding 只读，禁止独立写入路径（`report/` 保持只读包，arch_check 已有此约束）。

### P3 边界：沙箱与审计

**做什么**

- `BEN_SANDBOX=local|docker`；docker 后端复用 strix 的思路（镜像 + 挂载 target + 出口白名单），但不搬它的运行时。
- 命令审计：每轮 tool 调用写 `runs/<id>/trace.jsonl`（`ts / worker / tool / args_hash / exit / duration`）——顺手解决 v4 的 R-12。
- 每 worker 独立工作目录 + 网络策略（默认仅 target 域）。
- 无 docker 时 `ben scan` 给出可执行提示并 exit 2，不静默降级。

**验收**（安全工具的验收必须是攻击用例）

```
tools 逃逸：  ../../etc/passwd / 写仓库外 / 符号链接绕过
进程：       超时子进程 / 孤儿 nmap（killpg 后 pgrep 为空）
网络：       非 scope 域请求被拒
审计：       trace.jsonl 行数与 tool 调用数一致
```

### P4 分发：可安装、可集成

**做什么**

- `[project.scripts] ben = "ben.cli:main"`；`pipx install` / `uv tool install` 可用；`scripts/install.sh` 降级为「开发用软链」。
- `-n` headless + `--resume`（复用现有 `workers.json` 与图，不新增状态机）。
- `.github/workflows/scan.yml`：PR 触发，`ben scan -n --fail-on high`，diff 范围限定（strix 的 `--scan-mode quick` 同理）。
- MCP server：把 `ben graph/frontier/fact` 暴露为 MCP 工具；出 `skills/ben/SKILL.md` 供 Claude Code / Cursor 调用。

**验收**：干净 venv `pip install . && ben --version`；workflow 在 fixture 应用上跑通并正确设置退出码；MCP 工具列表可列出 `ben.status` / `ben.fact`。

### P5 军团可复现（护城河，等有真实用户再做）

**做什么**：trace 回放（`tests/fake_openai.py` 已有零 token 回放，扩成 `ben replay`）、按角色 token/成本、viewer 的 agent 分工图、同 target 两次 run 的差异对比。

**验收**：回放一次完整 run 产出与录制一致的 findings 集合（哈希比对），全程零 token。

---

## 5. 顺序理由

```
P0 叙事 ──► P1 目标 ──► P2 产物 ──► P3 边界 ──► P4 分发 ──► P5 可复现
              │            │
              └─ 产品脊柱 ─┘   缺任一段，陌生人都用不起来
```

- **P0 不先做**，后面每加一个功能，读者仍先看到「女娲测试」——定位没变，功能白加。
- **P1 → P2 是脊柱**：有目标没产物 = 玩具；有产物没目标 = 空壳。
- **P2 在 P3 前**：先让报告值钱，再谈「敢让它跑」。但 **P3 必须早于任何公开推广**（发 pip 包却不隔离 shell 权限，是把风险发给陌生人）。
- **P5 最后**：可复现是护城河，但只有真实用户能证明它值钱；提前做就是自嗨。

---

## 6. 风险表（诚实版）

| 风险 | 级别 | 缓解 |
|---|---|---|
| 漂移成 strix 平替，正面撞车且丢掉军团差异 | **高** | 反目标写进 README + POSITIONING；PR 评审只问一句「这加强了编排还是只是多了工具」 |
| P1 抽象泄漏，`challenge/flag` 渗进 core | 高 | core 只认 `target_id`；arch_check 禁止 core 出现 `BENCHMARK_` |
| P2 findings 与事实图双写不一致 | 中 | finding 只做投影，不建第二存储 |
| P3 沙箱拖慢迭代 / 本机无 docker | 中 | `local` 保底 + CI 用 fixture 应用；docker 只在 `scan` 默认路径要求 |
| 叙事迁移丢掉「比赛冠军」带来的流量 | 中 | 战报保留为 case study，首屏保留三行成绩 + 链接 |
| 阶段并行导致每条都半成品 | 中 | 一阶段一 commit，gate 不过不进入下一阶段 |

---

## 7. 需要你拍板的三件事

| # | 决策 | 选项 | 我的建议 |
|---|---|---|---|
| D1 | 定位取向 | **A 编排引擎（差异化）** / B strix 式单 agent 报告工具 / C 维持比赛资产不产品化 | **A**：唯一能把现有资产变成优势的方向 |
| D2 | 沙箱默认 | **A `local` 默认（门槛低）** / B `docker` 默认（安全，符合安全工具惯例） | **B**，但在 P4 公开发布时才切换默认；P3 阶段 `local` 仍是默认 |
| D3 | findings 建模 | **A 事实图投影（零新存储）** / B 独立 SQLite（查询强，双写风险） | **A**：provenance 是 ben 的卖点，拆开就没了 |

---

## 8. 第一个 commit 长什么样（P0.1）

```
README.md                    前 30 行重写；§1–§5 迁出；§8 状态句修正
docs/PHILOSOPHY.md           新建（承接 §1–§5 原文，加一句「这不是使用说明」）
docs/POSITIONING.md          新建（本文 §1–§3）
docs/INDEX.md                登记两个新文件
scripts/ci/readme_contract.py 新建（三条断言）
scripts/ci/preflight.sh      追加 readme_contract
```

验收：`bash scripts/ci/preflight.sh` 绿；一个没读过项目的人只看首屏 30 行，能说出「它给谁用、跑什么命令、拿到什么」。
