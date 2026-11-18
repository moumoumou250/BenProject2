# 定位重构方案 v2 —— 从「一个仓库三个身份」到「一条命令一次评估」

> 基线：HEAD `39222cd`，2026-11-18 18:00 实测（`arch_check` 9 项、`pytest` 161 passed/1 failed）
> 前身：[POSITIONING-PLAN-v1.md](POSITIONING-PLAN-v1.md)。本文继承其产品脊柱（叙事→目标→产物→边界→分发），
> **修正 5 处已过时断言、新增 2 个阶段（P-1 基线归零、P1 run 身份）、并把 KB 闭环列为首个差异化兑现点**。
> 差异清单见 §8，不要两份对着读。
>
> **已定约束（2026-11-18，用户决定）：零赛事叙事。** 对外不出现任何赛事成绩、名次、获奖、参赛规模、平台名，
> 承载它的文件一并删除；背书改由「可复现的误报率 + 零 token 回放」提供。见 §2 反目标 0。

---

## 0. 一句话结论

ben 的问题不是「叙事太哲学」，而是**同一个仓库挂着三个身份，且没有任何一个被写成产品契约**。所以重构的第一步不是加功能，是**选定一个身份并把它的契约补齐**——而补齐契约需要的五个面里，ben 有四个半是空的。

身份已选定：**ben 引擎旗舰实现**（D1=A），且**赛事身份退出对外叙事**（D0，已定）。于是「三个身份」里剩下的那个，恰好是契约最不完整的那一个——这就是本方案要补的全部内容。

---

## 1. 差距：三层，逐层带证据

### 1.1 第一层：没有单一身份（这是根因，不是修辞问题）

| 身份 | 证据 | 对谁说话 |
|---|---|---|
| **A. nvwabase 的示范应用** | `README.md` 里 `nvwabase` 出现 **14 次**，把本项目定义为「比赛 fork，通用基座在 nvwabase」 | 想复用的开发者 |
| **B. 赛事战队**（**已决定删除**，见 §2 反目标 0） | 首屏 1–12 行是赛事成绩／获奖叙事 + 公众号长文链接 + 文明寓言句 | 评委、读者 |
| **C. ben CLI 引擎** | 42 个子命令、10,085 行、9 项架构检查、161 个测试；`pyproject.toml` 的 description 写的是 `Engagement fact-graph CLI for agentic work` | 想用它的人 |

三者互相拆台的地方是具体的：

- `README.md:24` 标题写 **"What this is (and isn't)"**，正文第一句是 *"This project is designed for competition scenarios"*——**README 自己声明了这个项目不可用于非比赛场景**，而 `pyproject.toml` 说它是通用 CLI。
- `README.md:32` 教用户跑 `nuwa spawn --agent <cmd>`，但 `ben/cli.py` 的 42 个子命令里**没有 `nuwa`**（`grep add_parser(\"nuwa\"` 为空）——重命名 nuwa→ben 只改了代码，没改文档。
- 首屏要滚到第 237 行（共 448 行）才看到 Quick Start，前面 236 行是文明论、版本史与赛事段。

**判断**：定位漂移不是「文案要改」，是**三个产品共用一个 README**。任何功能层面的重构，只要这个状态不变，加完仍会被读成「赛事项目」。

### 1.2 第二层：产品契约五个面，缺四个半

以 strix-agent 1.7.0（`/home/kali/Desktop/AI/strix-main`，45,171 行）为尺子：

| 面 | strix | ben 现状（实测） | 缺口 |
|---|---|---|---|
| **target** | `-t/--target`、`--target-list`，支持目录/仓库/URL/OpenAPI | 无 target 概念；只有 `setup --goal "<自由文本>"` + arena 的 challenge/flag；`ben/targets/` 不存在，`ben/arena.py` 214 行挂在顶层 | 陌生人不知道能对自己的应用做什么 |
| **run** | `run_dir_for()`、`runs.py`、`-r/--resume`、`--max-budget-usd` | 有 `runs/<id>/` 和 `workers.json`，但**没有 run 对象**：无 id 契约、无 resume、无预算/成本账 | 产物无归属，中断即重来，成本不可见 |
| **产物** | `report/` **4,236 行**：`state.py`/`sarif.py`/`dedupe.py`/`coverage.py`/`pricing.py`/`usage.py` | `ben/report/` **111 行**（brief/history/status），只读终端渲染；`FACT_KINDS = (host,service,cred,vuln,loot,flag,note)`（`ben/consts.py:30`）**无 finding、无 severity** | 输出是给下一个 agent 读的中间表示，不是给用户读的结论 |
| **边界** | `runtime/` 9 个文件：`docker_client`/`session_manager`/`backends`/`caido_*` | `ben/tools/builtin.py` 一个文件，3 个工具（shell/read/write）+ 路径白名单；无容器、无出口策略、无调用审计 | 凭什么让一个能 shell 的 AI 军团跑在自己机器上 |
| **分发** | `[project.scripts] strix = ...`、`-n`、`--fail-on {critical..info}`、`--scan-mode`、`--diff-base`、MCP、GitHub Action | **无 `[project.scripts]`**（装不上）；42 个子命令里没有一个能进 CI；无 `-n`、无 `--fail-on`、无 `--resume` | 陌生人装不了，CI 接不进 |

补充一条 v1 没发现的耦合：`BENCHMARK_BASE_URL` / `BENCHMARK_TOKEN` 不只在 `ben/arena.py`，还在 **`ben/config.py:101-103`** 的全局配置注册表里——所以「arena 降为 adapter」不是搬一个文件，要连配置注册表一起拆，否则启动期仍会硬校验。

### 1.3 第三层：最该产品化的资产，恰恰没接到产品上

这是本文与 v1 分歧最大的一点。v1 说护城河是「编排」，我认为**今天真正稀缺的是「判断力已被写成可执行判据」这件事**：

```python
# ben/commands/probe_cmds.py:207 — 阴性对照，不是模型自评
baseline_url = f"{base_url.rstrip('/')}/{name}-miss.jsp"   # 取不到才判 CONFIRMED
```

这套 `CONFIRMED / UNVERIFIED / NOT_CONFIRMED` + baseline + reject 理由，配上今天的 KB 闭环（`ben kb check/diagnose/probe`、`taxonomy.json`、`docs/kb-iterations.md` 账本），是全仓库**唯一把「怎么算确认」写成机器可判**的东西。strix 的 `severity` 是 agent 写的字符串，ben 的 `CONFIRMED` 是一次对照实验的结果——这是真差异。

但它现在的产出只喂给 KB 校验，**没有变成 finding 的 confirmed 状态**。同时 `.ben/` 里 15 条事实（Juice Shop 的 HOST/HTTP/FTP/vuln）证明 ben 已经在被自己 dogfood——**只是入口是手工在本地靶场里跑，不是一条命令**。

**判断**：通向产品化最近的路，不是新写 `ben scan`，而是**把已经跑通的那条手工作业线固化成命令**，并把已有的复核逻辑接到报告上（不新写第二套）。

### 1.4 基座：自己的闸门是红的

实测（这是任何重构的前置，v1 写作时是 0 violation）：

```
arch_check  9 checks, 1 violation(s)
  ✗ duplicates  ben/commands/probe_cmds.py::_repo_root ≈ ben/commands/setup.py::_skill_root (100%)
pytest -q:  161 passed, 1 failed, 1 skipped   （test_this_repository_is_clean 红）
```

红基线开工的后果：分不清「我弄坏的」和「本来就坏的」，后面每阶段的 gate 全部失效。

---

## 2. 目标定位

**一句话**：

> ben 是一条命令对任意 target 起一队 agent，产出**带证据链与成本账**的渗透评估报告的编排引擎；赛事平台只是其中一个 target 适配器，且不出现在对外叙事里。

**三条不可让的差异**（每阶段用这三条筛改动，不满足就砍）：

| 支柱 | 现状资产 | 必须补到能对外说 |
|---|---|---|
| **编排可见** | 角色分化、fleet、hint 信箱、PTY console、密钥池、看门狗 | 谁做了什么、花了多少、为什么换人（run trace + 按角色成本） |
| **证据可判** | 阴性对照、证据闸门、`source_intent` 溯源、KB 判据 | finding 的 confirmed 来自对照实验，报告中可重放 |
| **轨迹即审计** | 三层事实图（title/gist/doc） | 报告每个结论能 `ben doc` 打开证据链 |

**反目标**（写进 README 与 `docs/POSITIONING.md`，防漂移）：

- **0. 零赛事叙事**（2026-11-18 用户决定）：`README.md`、`README.zh-CN.md`、`pyproject.toml` 的 description、`docs/` 对外文档、发布文案中，**不出现任何赛事成绩、名次、获奖、参赛规模、赛事平台名，也不得把文明寓言当作背书**。理由：赛事背书只在赛事语境里成立，对「想评估自己应用的人」是噪音，且会持续把项目拉回「赛事项目」的读法。**这不是把成绩压缩成一行，是整段删除——包括删除承载它的文件（见 P0）。**
- 1. 不追工具数量 —— strix 20 个工具目录是它的战场，ben 的战场是「谁来决定用哪个工具、什么时候换人」。
- 2. 不做 TUI。
- 3. 不引 LiteLLM / `openai-agents`，不重写 stdlib 内核。
- 4. 不为赛事改通用性 —— 赛事降为 adapter，不是身份。
- 5. 不做 Cloud / SaaS。

**背书从哪来（删掉赛事叙事后的替代物）**：

| 旧凭据 | 新凭据 | 何时成立 |
|---|---|---|
| 赛事名次 / 获奖 | **可复现的误报率**：本地靶场上 precision / recall 的实测数字 + 复现命令 | P3（profiles 加 `[expect]`） |
| 公众号长文 | `docs/POSITIONING.md` + `ARCH.md` + ADR 的机器约束（9 项检查是公开可验证的） | P-1、P0 |
| 赛事成绩 | **零 token 回放的哈希一致**：同一 run 重放产出同构 findings | P6 |

**原则：不写任何未经复现的数字。** 在 P3 的评测跑通之前，README 的 Evidence 一节只写方法、命令与「待填」，不写结论——这比保留旧背书更重要。

---

## 3. 阶段总览

| 阶段 | 目标 | 涉及模块 | 优先级 | 机器可判验收 | 依赖 |
|---|---|---|---|---|---|
| **P-1** | 基线归零 | `ben/commands/*`、`ben/core/paths.py`、`docs/ARCH.md` | **P0 阻塞全部** | `arch_check` 0 violation + `pytest` 全绿 | — |
| **P0** | 身份归一（含删除赛事叙事） | `README.md`、`README.zh-CN.md`、`docs/BATTLE-REPORT.md`（删）、`docs/{POSITIONING,PHILOSOPHY}.md`、`scripts/ci/readme_contract.py` | **P0** | `readme_contract` 5 条断言绿（含禁用词表） | P-1 |
| **P1** | run 身份（一次评估） | `ben/core/paths.py`、`ben/commands/auto.py`、`ben/fleet.py`、`ben/config.py` + 新 ADR | P1 | 中断后 `--resume` 续跑且不重做已完成意图；`manifest.json` 齐 | P-1 |
| **P2** | target 抽象，arena 降 adapter | 新增 `ben/targets/`、`ben/arena.py`、`ben/config.py:101` | P1 | 无 `BENCHMARK_*` 下对本地靶场起队成功 | P1（汇合于 scan 入口） |
| **P3** | findings + 报告 + 成本账 | `ben/consts.py`、`ben/core/schema.py`、`ben/core/recheck.py`（新）、`ben/report/`、`ben/commands/findings_cmds.py`（新） | **P1 杠杆最高** | SARIF 必填字段断言 + 同 target 两次 run 结论一致 | P1、P2 |
| **P4** | 边界：沙箱 + 调用审计 | `ben/tools/`、`ben/runtime/`、`ben/config.py` | P1（公开分发前必须） | 逃逸用例全拦 + `trace.jsonl` 行数=tool 调用数 | P1（trace 挂 run）、P2（scope 来自 target） |
| **P5** | 分发：可安装可集成 | `pyproject.toml`、`.github/workflows/`、`skills/ben/SKILL.md` | P2 | 干净 venv `pip install . && ben --version`；Action 在 fixture 上正确置退出码 | P3（退出码）、P4（沙箱） |
| **P6** | 可复现（护城河兑现） | `ben/replay.py`（新）、`ben/web/` | P3（最后） | 零 token 回放产出同构 findings（哈希比对） | P1+P4 |

---

## 4. 各阶段详述

### P-1 基线归零（优先级 P0，一天内可完成）

**做什么**
1. 合并 `_repo_root`（`probe_cmds.py`）与 `_skill_root`（`setup.py`）：两者 100% 同源，落 `ben/core/paths.py`。注意 `_skill_root` 的语义是「装 skill 的目标目录」，合并前先确认它不是 repo root 的别名——若语义不同，则提取公共的「向上找 `pyproject.toml`」函数，各自保留命名。
2. 把当前绿基线写进 `docs/ARCH.md §冻结存量（baseline）`（该节已存在），作为后续阶段的回归参照。

**验收**
```bash
python scripts/ci/arch_check.py          # 9 checks, 0 violation
.venv/bin/python -m pytest -q            # 161+ passed, 0 failed
```

**风险**：合并两处路径函数可能改变 `ben setup` 的安装落点。缓解：先写一条测试固定 `_skill_root` 的当前返回值，再重构。

---

### P0 身份归一（优先级 P0，先做，因为后面每步都被它拖）

**做什么**

1. **拍板身份（D1，见 §7）**：本仓库 = ben 引擎的旗舰实现；nvwabase 从「你是它的 fork」降为「去渗透化的通用基座，见链接」一节。赛事降为**纯工程 adapter**（`ben/targets/arena.py`），保留代码能力、不留叙事。
2. **README 首屏 30 行固定四件事**：定位句 / 给谁用 / 一条命令 / 输入→输出。原 §1–§5（女娲测试、三能力、18 版本、涌现）整体迁入新建 `docs/PHILOSOPHY.md`；**赛事段整段删除，不压缩、不留链接、不留任何情怀句或寓语句充当背书**。
3. **删除承载赛事叙事的资产**（本次决策的直接后果，连带清单）：
   - `docs/BATTLE-REPORT.md`（8 KB 战役复盘）—— 它此前「不可删」的唯一理由是 README 引了 4 次；引用消失后**整文件删除**；
   - `docs/compare-sapper-vs-ben.md:27` 那行「同名文档，内容同源」的对照表项、`docs/README.zh-CN.md` 中对应的两处引用，一并清理；
   - `docs/plans/POSITIONING-PLAN-v1.md` 保留但标 `superseded by v2`（它记录了这次转向的理由，删掉会丢掉决策依据）；v1 里「战报保留为 case study」的结论**作废**。
4. **修三处具体缺陷**（v1 未列，均已实测）：
   - `README.md:32` 的 `nuwa spawn` → `ben setup` / `ben dispatch`（命令不存在）；
   - `README.md:299` 与 `:426` 指向的 `docs/tmux-removal-plan-v3.md` 是 280 字节空壳，且 §8 标题写 `implemented`、正文写 `proposal, not implemented`——删 stub、删 4 处引用（含 `README.zh-CN.md:198/311`）、§8 改写为「运行时说明」；
   - 两个 README 共 **14 处 `<img src=\"assets/*.jpg\">`** 指向已在 `39222cd` 删除的图——删引用，不造假图（`ROOT-LAYOUT.md §208` 自己就是这么定的）。
5. 新建 `docs/POSITIONING.md`（本文 §1–§2 的对照表 + 三支柱 + 反目标），`docs/INDEX.md` 登记；README 增一节 `Evidence`，**先只写方法与命令，数字留空待 P3 填**（见 §2 背书替换表）。

**验收**：新增 `scripts/ci/readme_contract.py`，纳入 `preflight.sh`，五条断言：
1. README 前 30 行出现「target / 产物 / 一条命令」三组词；
2. README 里出现的每条 `ben <sub>` **和** `nuwa <sub>` 必须在 `ben/cli.py` 有同名 parser（这条今天就会抓到 `nuwa spawn`）；
3. `docs/PHILOSOPHY.md` 存在且被 README 链接（防哲学回流首屏）；
4. README/README.zh-CN 中 `<img src>` 指向的本地文件必须存在（补 `docs_links` 只查 `[]()` 不查 `<img>` 的盲区——就是这个盲区让 14 张坏图活到今天）；
5. **禁用词表**：`README*.md`、`pyproject.toml`、`docs/**/*.md` 中不得出现赛事成绩类词（`champion` / `冠军` / `第一名` / `获奖` / 具体名次数字），词表集中在 `BANNED_TERMS` 常量里便于扩充。**把「零赛事叙事」从口头约定变成机器约束**——否则三个月后一定有人把它加回来，而且不觉得自己在推翻什么。

**风险**：见 §6 风险 R1（删掉背书后的真空期）。

---

### P1 run 身份（优先级 P1，与 P2 并行）

**为什么独立成阶段**：findings、报告头、CI 退出码、sandbox trace、resume——**全部挂在「一次评估」这个对象上**。v1 把它散在 P2/P4/P5 里，结果每个都要自己发明 run 概念。

**做什么**
1. `Run` 对象：`{id, target_id, started_at, ended_at, model, budget, status}` → `runs/<id>/manifest.json`。复用 `ben/core/paths.py` 的运行时唯一根（ADR-0006）。
2. `ben run start|status|resume`：`resume` 从现有 `workers.json` + 事实图恢复，**不新增状态机**。
3. 预算与成本账：现有 watchdog 有 deadline/budget，缺的是**计量与呈现**（每 worker token、按角色汇总，落 manifest）。这是「编排可见」支柱的第一块砖。
4. 写一条 ADR：`.ben/`（per-challenge 工作记忆）与 `runs/<id>/`（一次评估容器）的边界，避免两个概念长期打架。

**验收**
```bash
ben run start --target tests/TestRange/profiles/tomcat-cve-2017-12615.toml
# Ctrl-C 后
ben run resume                      # 已完成意图不重跑
cat runs/<id>/manifest.json         # 六个字段齐、成本非空
```

**风险**：`.ben` 与 run 概念重叠导致双写。缓解：run 只**引用** `.ben`（存路径+快照哈希），不复制事实。

---

### P2 target 抽象（优先级 P1）

**做什么**
1. `Target = {type: repo|url|openapi|lab, locator, auth?, scope?}` → `.ben/targets.json`；`ben target add`。
2. `ben scan [target] [--mode quick|deep] [--budget 30m] [-n]`：组合 `setup --goal` + `auto` 作为**唯一产品入口**；旧 42 个子命令保留为低层动词。
3. **arena 降级为 adapter**：`ben/arena.py` → `ben/targets/arena.py`；把 `BENCHMARK_BASE_URL`/`BENCHMARK_TOKEN` **从 `ben/config.py:101-103` 移出**（改为 adapter 私有读取），否则启动期仍硬校验。
4. `ben/targets/lab.py`：直接吃 `tests/TestRange/profiles/*.toml`（**已纳入 git 的 11 个文件**，v1 那条「先 git add TestRange」的前置已完成，不必再做）。
5. arch_check 加一条规则：`BENCHMARK_` 只允许出现在 `ben/targets/arena.py`。

**验收**
```bash
env -u BENCHMARK_BASE_URL ben scan tests/TestRange/profiles/tomcat-cve-2017-12615.toml -n
# exit 0/1，不是 "BENCHMARK_BASE_URL is not set"
grep -rn "BENCHMARK_" ben/ | grep -v "ben/targets/arena.py"   # 空
```

**风险**：`challenge/flag` 语义渗进 core。缓解：core 只认 `target_id`；flag 提交是 arena 私有动词。

---

### P3 findings + 报告 + 成本账（优先级 P1，杠杆最高）

**做什么**
1. **投影，不新建存储**：`FACT_KINDS` 增 `finding`；`data{severity, cvss, owasp, target, evidence_doc, poc}` 进 `ben/core/schema.py` 的枚举校验（当前是自由 key=value，机器约束不了严重度）。
2. **复用已有复核**：把 `probe_cmds.py` 的 `CONFIRMED/UNVERIFIED/NOT_CONFIRMED` + 阴性对照抽成 `ben/core/recheck.py`，`verify` 动词改调它。**这是本阶段唯一不可跳过的一步**——它把「证据可判」从 KB 私有变成产品能力。
3. 状态机复用 `store.py` 的 `update_flag_fact` 先例（事实不可变的唯一例外）：`open → confirmed / false_positive / accepted_risk`，补 ADR。
4. `ben findings [--severity high]`；`ben report --format md|json|sarif -o out/`；退出码：`--fail-on high` → 1，环境错 → 2，无发现 → 0。
5. 报告头固定 provenance：run id / model / 成本 / target / 时间线。
6. **ground truth**：`tests/TestRange/profiles/*.toml` 当前只有 `[deploy][target][health]`，加 `[expect]`（漏洞 id + 严重度），与扫描结果比对算 precision/recall 写进报告摘要。**没有 expect 就没有误报率；没有误报率，findings 只是另一种 flag。**

**验收**
- `tests/test_report.py`：SARIF 2.1.0 必填字段（`version`/`runs[].tool.driver`/`results[].ruleId,level,locations`）；
- 同一 target 跑两次，findings 集合一致（去重有据）；
- 每个 finding：`ben doc <id>` 能打开完整证据，报告里 PoC 可重放。

**风险**：投影与图不一致。缓解：`report/` 保持只读包（arch_check 已有约束），finding 禁止独立写入路径。

---

### P4 边界：沙箱 + 调用审计（优先级 P1，公开分发前必须）

**做什么**
1. `BEN_SANDBOX=local|docker`；docker 后端借 strix 的思路（镜像 + 挂载 target + 出口白名单），**不搬它的运行时**。
2. 调用审计：每轮 tool 调用写 `runs/<id>/trace.jsonl`（`ts/worker/tool/args_hash/exit/duration`）——顺手解决 v4 的 R-12（`import logging` 0 处）。
3. 每 worker 独立工作目录 + 网络策略默认仅 target 域；无 docker 时 `scan` 给可执行提示并 exit 2，不静默降级。

**验收**（安全工具的验收必须是攻击用例）
```
工具逃逸：../../etc/passwd / 写仓库外 / 符号链接绕过
进程：    超时子进程 / 孤儿 nmap（killpg 后 pgrep 为空）
网络：    非 scope 域被拒
审计：    trace.jsonl 行数 == tool 调用数
```

---

### P5 分发（优先级 P2）

**做什么**：`[project.scripts] ben = "ben.cli:main"`；`-n` headless + `--fail-on` + `--resume`；`.github/workflows/scan.yml`（PR 触发、diff 范围限定，同 strix 的 `--diff-base`）；MCP server 暴露 `ben.graph/frontier/fact`；`skills/ben/SKILL.md` 供 Claude Code / Cursor 调用。

**验收**：干净 venv `pip install . && ben --version`；workflow 在 fixture 上跑通并正确置退出码；MCP 能列出 `ben.status`/`ben.fact`。

**依赖硬约束**：退出码来自 P3，沙箱来自 P4——**先发 pip 包再补沙箱，等于把 shell 权限发给陌生人**。

---

### P6 可复现（优先级 P3，最后）

trace 回放（`tests/fake_openai.py` 已有零 token 回放，扩成 `ben replay`）、按角色成本报表、viewer 的分工图、同 target 两次 run 的 diff。
**验收**：回放一次 run 产出与录制一致的 findings 集合（哈希），全程零 token。

---

## 5. 依赖与顺序

```
P-1 基线
 └─► P0 身份 ──┬─► P1 run ──┬─► P3 产物 ─┬─► P5 分发 ──► P6 可复现
               └─► P2 target┘             │
                      └────► P4 边界 ──────┘
```

- **P-1 不先做**：红基线下每阶段的 gate 都是假的。
- **P0 不先做**：后面每加一个功能，读者首屏仍先看到寓言与赛事段——定位没变，功能白加。
- **P1 与 P2 可并行**：一个给「一次评估」身份，一个给「评估对象」，在 `ben scan` 入口汇合。**P2 单独做会得到「有目标没归属」的扫描**，所以两者必须在 P3 前都完成。
- **P3 是杠杆点**：它把已有的判断力资产第一次变成对外产物。
- **P4 可与 P3 并行，但必须早于 P5**（安全工具的分发前提）。
- **P6 最后**：可复现是护城河，但只有真实用户能证明它值钱。

---

## 6. 风险

| # | 风险 | 级别 | 缓解 |
|---|---|---|---|
| R1 | **删掉赛事叙事后的真空期**：项目此前被看见的理由是那场比赛，删干净后对外没有任何「凭什么信你」的凭据，而新凭据（P3 的误报率、P6 的回放）要到后期才成立 | **高** | 三条：①P0 同一次提交里就把 README 的 `Evidence` 一节建好（写方法 + 可复现命令 + 「待填」），不留空白；②**绝不补写未经复现的数字**——编一个 precision 比保留旧背书更伤；③把「零 token 回放」这类可被陌生人一条命令验证的东西优先做完（P6 提前到 P3 之后立刻做） |
| R2 | **漂移成 strix 平替**：P1–P5 的契约面几乎逐条对应 strix | **高** | 每阶段过「差异化闸门」：本阶段改动是否强化「编排可见」或「证据可判」之一？否则砍掉 |
| R3 | 没有真实外部用户，产品化自嗨 | **高** | 每阶段末做一次陌生人 5 分钟可用性测试（不看 README 之外的任何文档） |
| R4 | 红基线未归零就开工，无法判断回归 | **高** | P-1 硬前置 |
| R5 | `challenge/flag` 语义渗进 core | 中 | core 只认 `target_id`；arch_check 禁 `BENCHMARK_` |
| R6 | run 与 `.ben` 概念重叠导致双写 | 中 | run 只引用 `.ben` + 快照哈希；写 ADR |
| R7 | findings 与事实图双写不一致 | 中 | 只做投影，`report/` 保持只读 |
| R8 | KB 判据只有一个样本（file-write/Tomcat），`recheck` 抽出来泛化不足 | 中 | 先做成「证据模板」而非 Tomcat 特例；新增 vuln 类必须能在 profiles 复现 |
| R9 | 沙箱拖慢迭代 / CI 无 docker | 中 | `local` 默认；docker 只在 CI fixture 与公开发布时要求 |
| R10 | 阶段并行导致每条半成品 | 中 | 一阶段一 commit；gate 不过不进下一阶段 |

---

## 7. 需要拍板的四件事

| # | 决策 | 选项 | 建议 |
|---|---|---|---|
| **D0** | 对外是否保留赛事叙事 | **已定（2026-11-18）**：不保留，且物理删除承载文件 | 已生效，见 §2 反目标 0 与 P0 |
| **D1** | 本仓库身份 | A **ben 引擎旗舰实现**（nvwabase 降为一节）/ B 通用基座的一个案例 / C 维持现状 | **A**：唯一能把已有 10,085 行变成产品资产的方向。（原「保留赛事身份」选项随 D0 作废） |
| **D2** | 默认沙箱 | A `local` 默认 / B `docker` 默认 | **A 起步，P5 公开发布时切 B** |
| **D3** | findings 建模 | A 事实图投影（零新存储）/ B 独立 SQLite | **A**：provenance 是卖点，拆开就没了 |
| **D4** | `ben arena` 地位 | A 降为 target adapter（保留薄壳）/ B 保持一等命令 | **A**：赛事被定位为「一个 target 来源」，不出现在文档与 README |

---

## 8. 与 v1 的差异（修正清单）

| # | v1 的写法 | 实测（HEAD 39222cd） | 本文处理 |
|---|---|---|---|
| 1 | 「arena 的 `BENCHMARK_*` 只在 `arena.py` 读」 | 还在 `ben/config.py:101-103` 全局注册表 | P2 增加「连配置注册表一起拆」 |
| 2 | 「`git ls-files tests/TestRange` = 0，前置要先 git add」 | **已纳入版本控制，11 个文件** | 前置取消，直接作为 P2 的 target 来源 |
| 3 | 「`arch_check` 八项 0 violation」 | **9 项、1 条违规**（`_repo_root` ≡ `_skill_root`） | 新增 P-1 基线归零 |
| 4 | 「158 个用例」 | 161 passed / 1 failed / 1 skipped | 同上 |
| 5 | 把 run 责任分散在 P2/P4/P5 | ben 无 run 对象（无 id/resume/成本） | 新增 P1 独立阶段 |
| 6 | 未提 README 与代码不同步 | `nuwa spawn` 不存在；14 张坏图；`§8` 自相矛盾 | 并入 P0，并给 `readme_contract` 加第 4 条断言 |
| 7 | 护城河 = 编排 | 编排强但未计量；**KB 阴性对照才是最新鲜的差异化** | P3 把 `recheck` 作为不可跳过项，P6 才谈回放 |
| 8 | 「战报保留为 case study，首屏保留三行成绩 + 链接」，风险栏主张「只改位置、不删事实」 | 用户 2026-11-18 决定：**零赛事叙事** | **全部作废**：赛事段整段删除，`BATTLE-REPORT.md` 整文件删除，并加禁用词表把这条变成机器约束（§2 反目标 0、P0 第 3/5 条、R1 重写） |
