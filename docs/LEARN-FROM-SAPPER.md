# Ben 从 sapper 学什么

> **制度迁移方案** · 基线 2026-11-18 · commit `ff73143`
> 方法：先取证，再开方。每条判断附可复现命令，每个改动附一条机器能判的验收。

本文只回答一个问题：**sapper 里有哪些经过实战校准的东西，ben 应该拿走；以及拿走时必须改成什么形状。**

三份文档的分工：

| 文档 | 回答什么 |
|---|---|
| `compare-sapper-vs-ben.md` | 两边**是什么**（架构、启动、请求、渲染、部署的差异） |
| `OPTIMIZATION-PLAN.md` | ben **自己的代码**哪里糟（O(n²) 写盘、启动税、无 CI） |
| **本文** | sapper 的**制度资产**怎么装进 ben（这是唯一一项买不到、只能迁移的东西） |

---

## 0. 一页结论

sapper 的代码不值得搬——单文件 4,726 行、tmux 屏读、bash watchdog，ben 已经用进程化和 SDK 引擎取代了它们，退回去是倒退。但 sapper 有一件东西 ben 完全没有：**426 行军规**。它不是文档，是把"怎么当指挥官"从隐性经验固化成显性条款的产物，并且被一次 33+ flag 的实战校准过。

| # | sapper 有的 | ben 现状 | 迁移方式 | 收益 |
|---|---|---|---|---|
| S0 | 426 行军规（`SKILL.md`） | `AGENTS.md` 只有 50 行事实图协议 | **三路分流**，不整搬 | 制度进入决策回路 |
| S1 | §4.6 升级决策表 | `command.md:52-72` 九条散文 | 换成**图指纹刻度**表 | 升级从"感觉"变"判定" |
| S2 | "The table IS the ladder" | 无冲突仲裁规则 | 写进 `AGENTS.md` 一条 | 规则打架时有唯一出口 |
| S3 | 僵局时派 fresh eyes | 图不变就 `break`（`auto.py:151,215`），有 `blindspot` 却从不调用 | 把**终止判据**改成**换挡判据** | 僵局不再等于放弃 |
| S4 | 工具手册 | 名词替换版，语义仍是 sapper | 重写（非替换） | 少烧无效 step |

**一个必须先接受的约束**：这五条不能一起上。注入位置不解决，内容再对也会被挤掉（见 §1）。

---

## 1. 前提：为什么不能照搬

这不是风格问题，是**注入结构**问题。

**sapper 的路径**——军规在启动时一次性读入指挥官的上下文，之后靠 Claude Code 自己的存活与压缩机制维持：

```bash
wc -l docker/commander/SKILL.md   # 426
```

付一次，426 行可以"背下来"。所以它敢在 §0 写 `FIXED FACTS — memorize, never re-derive`。

**ben 的路径**——每次模型调用都重新拼一份 system prompt：

```python
# ben/llm/prompts.py:21
def build_system_prompt(append_system, cwd):
    parts = [SYSTEM_BASE.strip()]          # 17 行
    parts.append("# Project AGENTS.md\n" + agents.read_text())   # 50 行
    parts.append(append_system.strip())    # 角色模板 48~142 行
```

```bash
wc -l ben/agents/prompts/*.md   # 59 62 77 142 117 48
```

**结论**：把 426 行塞进这条路径，等于每一轮都多付 426 行，并且会撞上 ben 自己的两道闸——`sdk` 引擎的 16KB 输出截断，以及按字符阈值触发的上下文压缩。军规会把事实图挤出预算。**制度不能比它所治理的对象更占地方。**

所以正确动作是分流：按"这条规则需要什么时候在场"决定它落在哪。

---

## 2. 三路分流

```
sapper SKILL.md 426 行
        │
        ├──→ §0 固定事实 + §8 禁令 ────→ AGENTS.md（常驻，+30 行）
        ├──→ §4 条令 + §7 战略技艺 ────→ kb entries（检索命中才注入）
        └──→ §3 工具手册 ─────────────→ prompts/*.md（重写为 ben 语义）
```

判断标准只有一条：**这条规则如果必须检索才能拿到，它是不是就等于不存在？** 是 → 常驻；否 → 检索。

### 2.1 第一路：常驻锚 → `AGENTS.md`

现在 50 行，全是事实图协议（`ben status` / `ben fact` / `ben done`）。缺的是**不许推导的前提**和**不许越过的边界**。目标 +30 行，分三类。

**A 类 · 固定前提**（防止每轮重新推导，对应 sapper §0）

不需要写路径清单——ben 的路径能从 `ben status` 读到。要写的是**哪些量不允许估**：

- 剩余预算是 `deadline` 算出来的，不许假设任务长度；
- 已提交事实以图为准，不许复述记忆中的结论；
- 工具只有 `shell` / `read_file` / `write_file` 三个，不在列表里的动作不要尝试。

**B 类 · 禁令**（对应 sapper §8，可直接粘贴）

sapper §8 有 7 条，其中 3 条绑死在 tmux/pane 上，不迁移。剩下 3 条可以逐字拿，加 1 条 ben 特有的：

```markdown
## NEVER
- NEVER 由 reason 或 command 亲自执行探测命令——它们只产出 intent，执行是 explore 的事。
- NEVER 触碰靶场/计分基础设施。
- NEVER 在 ready 队列非空时开新链——先清便宜仗。
- NEVER 静默空转：无事可做时用一行说明为什么，然后停，不要重复同一决策。
```

第 4 条尤其重要。ben 的 `noop_streak` 现在只在连续两次 noop 时"停"，中间那一轮是静默的——模型会以为自己在工作。

**C 类 · 冲突仲裁**（对应 sapper §4.6 的元规则）

这是整套军规里最容易被忽略、也最关键的一句：

> *The table IS the ladder — no other section overrides it, no skipping upward without paying the row's cost.*

规则一多必然打架（"便宜优先" vs "深挖已有线索"）。sapper 的做法是先声明**哪份文件是唯一定级依据**。ben 必须在 `AGENTS.md` 里写下同一句的本地版：

```markdown
## 冲突时
`prompts/command.md` 的升级表是唯一定级依据。其他任何段落与之冲突时，以表为准；
不允许跳过表中的行直接升级。
```

---

### 2.2 第二路：检索层 → kb entries

ben 在这件事上有 sapper 没有的结构优势：`ben/kb/` 有 56 条 entries 和一个带 tokenize 的 `KnowledgeBase` 类，还提供 `import_markdown()` 批量导入。sapper 的军规只有"全读"和"不读"两种状态，ben 可以做到**命中才注入**。

**该迁的章节**（都是判断规则，不含运行时专名）：

| sapper 章节 | 内容 | 迁移后形态 |
|---|---|---|
| §4.1 Easy-first sweep | 先扫便宜仗 | kb 条目：定价策略 |
| §4.3 Same-challenge multi-angle | 同题多角度，而非换题 | kb 条目：僵局处理 |
| §4.5 Intel transfer | 一个挑战的结论如何变成另一个的弹药 | kb 条目：凭证复用 |
| §4.9 Model tiering | 什么时候值得花贵模型 | kb 条目：成本纪律 |
| §7.0 Meta-habits | 33+ flag 实战校准出的元习惯 | kb 条目（**最值钱的一节**） |
| §7.4 Re-enumerate on every foothold | 每拿到一个新立足点就重新枚举 | kb 条目 |
| §7.5 Parked discipline | 关掉的战场不轻易重开 | kb 条目 |
| §7.6 Fresh eyes beat repetition | 重试不如换视角 | kb 条目 |

**不该迁的**：任何提到 `worker.sh`、`tmux`、`pane`、`spawn`、flag 提交计分的段落。这些在 ben 里没有对应物，迁过来只会让模型去尝试做不到的动作——而那类失败不进事实图，纯粹烧 step。

**导入方式**（`import_markdown` 支持 base_tags，正好用来分组）：

```bash
ben kb import docs/doctrine/easy-first.md --tag doctrine --tag pricing
ben kb import docs/doctrine/fresh-eyes.md  --tag doctrine --tag deadlock
```

建议先只迁两条（§7.6 和 §7.5），验证"命中才注入"确实生效，再批量。

---

### 2.3 第三路：重写 → `prompts/command.md`

这一路是**改写，不是替换名词**。证据：

```bash
wc -l sapper-v2-master/templates/*.md          # 59 62 77 142 117 48
wc -l ben/agents/prompts/*.md                  # 59 62 77 142 117 48   ← 完全一致
grep -rc "tmux\|worker\.sh\|pane\|sapper" ben/agents/prompts/*.md   # 全 0
```

零残留、行数全等 —— 说明已做过一轮 `sapper`→`ben` 的名词替换，**结构一行没动**。ben 现在拿着 sapper 的剧本在自己的舞台上演出。

重写的第一优先级是 `command.md` 第 52-72 行那九条散文规则。它们和 sapper §4.6 是同一批语义，但没有刻度：

```
- Cut losses: a challenge with repeated failed attempts and no new leads ...
```

"repeated" 是多少次？模型每轮自己定义一次，于是每轮定义都不同——这就是漂移。

#### sapper 的表用时钟，ben 的表应该用图指纹

sapper §4.6 的刻度是墙体时间（0-10 min 发令 / 10-20 min 换角度 / 20-30 min 上重模型 / 30-45 min 放弃）。它只能用时间，因为**它看不见结构化进展**——屏幕上的文字不是计量单位。

ben 有事实图，能算出比时间更准的东西：

```python
# ben/commands/auto.py:104
before = _graph_signature(store)
```

图指纹变了 = 真的有新知识落地；没变 = 只是在动，不在前进。**用"几轮没有新事实"当刻度，比用"过了几分钟"更接近真实。**

而且 ben 早就把这个信号算出来了——它只是把结论用在了别的地方（见 §2.4）。

#### 建议替换的表

| 信号（ben 可判定） | 动作 | 迁移自 |
|---|---|---|
| ready 队列非空 | 只做 cheapest ready intent，禁止开新链 | §4.1 |
| intent 首次进入 explore | 直接探索，不做 scout | —（ben 的 reason 已行使 review 职责） |
| 图指纹连续 1 轮未变 | **换模板**：explore → `blindspot`（换角度，不换目标） | §7.6 fresh eyes |
| 图指纹连续 2 轮未变 | 该 intent 转 blocked 并写明原因成 fact；让 reason **换目标** | §7.5 park 纪律 |
| 同一 fact 被 ≥2 个 blocked intent 依赖 | 该前提可疑 → `brainstorm` 列替代路径 | §4.3 multi-angle |
| deadline 剩余 < 20% | 只做 ready 里最便宜的，禁止开新链、禁止上新模型 | §6 |
| ready 队列为空 **且** 图指纹未变 | 才允许终止整个 run | §6 |
| reason 连续 2 次失败 | 停并保留图 | 已实现，勿改 |

注意倒数第二行的限定词：**终止的判据是"没有可做的" + "没有新知识"，不是"这一轮没进展"**。一个挑战卡住不该让整场战役结束。

配套元规则（写在表头，对应 §2.1 的 C 类）：

> 本表是唯一定级依据。任何其他规则与此冲突时以本表为准，不允许跳行升级。

**为什么这张表比 sapper 的原表更强**：sapper 的行是"预算驱动的经验值"，ben 的行是"可观测信号驱动的判定"。前者换个靶场就要重标定，后者不会。

---

### 2.4 最要紧的一条：ben 把僵局当死亡，sapper 当换挡

上面表里"图指纹连续 2 轮未变 → 换 blindspot"这一行，ben 现在做不到——而且原因比"少个分支"更根本。

ben 早就在算图指纹了，但两处用法都是**终止**：

```python
# ben/commands/auto.py:151
if _graph_signature(store) == before:
    print("[auto] no graph change and no ready work — stopping")
    break

# ben/commands/auto.py:215
if _graph_signature(store) == before:
    print(f"[auto] step {step}: no graph change after work — stopping")
    break
```

**一轮没进展就停。** 这是保守的预算保护，但它意味着僵局等于放弃。

sapper 在同一个信号上做的却是换挡——§4.6 的三级阶梯：先发战术令（免费），再派新 worker 换角度，再上重模型，三档都试过才 park。*"fresh eyes beat a second opinion."*

更讽刺的是 ben **备好了换角度的工具却不用**：

```bash
grep -c "blindspot\|brainstorm" ben/commands/auto.py   # 0
grep -c "verify"               ben/commands/auto.py   # 15
```

`auto` 的循环只有 `reason → explore → verify` 三步。`blindspot` 和 `brainstorm` 是手动命令，自动循环从不调用。所以僵局来临时，ben 的动作是"再 reason 一次、再 explore 一次"，然后撞上 `break`。

**改法**：把这两处 `break` 拆成三档，对应 §2.3 的表：

1. 图第一次不变 → 调一次 `_dispatch_blindspot`，产出落成 hint，让 reason 下一轮看到；
2. 图第二次仍不变 → 把该 intent 转 blocked、原因写成 fact，**让 reason 换目标**，不退出；
3. ready 队列空 且 图不变 → 这才允许终止整个 run。

改动约 15 行，但它把 ben 的策略空间从"一条路走到黑"变成"一条路走不通就换路"。第二档尤其关键：sapper 的 `park` 纪律说的是"把这个挑战关掉、去做别的"，**不是"整场战役结束"**——ben 现在两处 `break` 都做成了后者。

这是本文所有建议里**投入产出比最高的一条**，因为它不需要新写任何制度，只需要让已有的能力进入循环。

---

## 3. 明确不迁移的四项

| 不迁 | 理由 |
|---|---|
| **tmux 屏读** | ben 已删净（`grep -rn tmux ben/` = 0）。屏读让 sapper 能读界面状态，也让它的每个 bug 都难复现。退回去是倒退。 |
| **426 行全量常驻** | 见 §1，会挤掉事实图。 |
| **`worker.sh` 776 行能力面** | ben 用 3 个工具换确定性，这是有意取舍，不是缺陷。sapper 的能力面靠"人能做什么"定义，ben 的靠"能验证什么"定义。 |
| **8h 死线 + 极端 fail loud** | sapper 日志不可见所以必须炸给外面看。ben 有 `--deadline` / `--max-steps` / `--max-explore`，可观测性好得多，不需要那种音量。 |

---

## 4. 分阶段落地

| 阶段 | 动作 | 改动量 | 验收 |
|---|---|---|---|
| **P0** | §2.1 B 类四条禁令 + C 类仲裁句进 `AGENTS.md` | +15 行 | `python -m pytest -q` 仍全绿（当前基线 84 passed）；`wc -l AGENTS.md` < 80 |
| **P0** | §2.3 决策表替换 `command.md:52-72` | 改 1 段 | `ben auto --dry-run` 渲染出的 prompt 含表、不含 "repeated failed attempts" |
| **P1** | §2.4 两处 `break` 拆三档（blindspot → 转 blocked → 终止） | ~15 行 | 构造"图指纹不变"假场景：第 1 轮调 `blindspot`；第 2 轮 intent 转 blocked 且 run **未退出** |
| **P1** | 迁 2 条 kb（§7.5 park 纪律、§7.6 fresh eyes） | 2 个文件 | `ben kb search fresh eyes` 命中 |
| **P2** | 其余 6 条 kb | 按需 | 同上 |

**顺序不能反**：P0 的第二项（决策表）必须先于 P1（循环分支）——分支的触发条件由表定义，表不在，分支就没有判据。

---

## 5. 反向：ben 该守住的优势

迁移不是单向的。sapper 有两处结构性弱于 ben，别在学它的过程中丢掉：

1. **制度可验证**。ben 有 `tests/` 和 `fake_openai.py`，sapper 没有。决策表的每一行都能写成断言（"图指纹不变 → 必须出现 blindspot 调用"）。sapper 的军规只能靠人读，是否被遵守无法判定。**这是 ben 真正的护城河**——把军规做成可测试的，比军规本身更值钱。

2. **进展度量是结构化的**。sapper 的 §5 有一整套"85% 上下文时重写 STATE"的协议，因为它的连续性只存在一个手写文件里。ben 的连续性在事实图里，本来就不会因为上下文压缩而丢——所以 ben 不需要那套协议，只需要像 §2.3 那样把图指纹当仪表盘用。

---

## 6. 证据索引

本文所有结论的原始终端输出：

```bash
# 军规体量
wc -l sapper-v2-master/docker/commander/SKILL.md                  # 426

# 模板是替换版而非适配版
wc -l sapper-v2-master/templates/*.md                             # 59 62 77 142 117 48
wc -l ben/agents/prompts/*.md                                     # 59 62 77 142 117 48
grep -rc "tmux\|worker\.sh\|pane\|sapper" ben/agents/prompts/*.md # 全 0

# 每次调用的注入结构
sed -n '6,32p' ben/llm/prompts.py                                 # SYSTEM_BASE 17 行 + AGENTS.md + 模板

# auto 循环没有换角度分支
grep -c "blindspot\|brainstorm" ben/commands/auto.py              # 0
grep -c "verify"               ben/commands/auto.py              # 15

# 图不变被当成终止信号，而不是换挡信号
grep -n "_graph_signature(store) == before" ben/commands/auto.py  # 151, 215 —— 两处均为 break

# 可用的进展信号
grep -n "_graph_signature\|explore_count\|noop_streak\|reason_failures" ben/commands/auto.py
```

---

*本文与 `compare-sapper-vs-ben.md`（讲差异）、`OPTIMIZATION-PLAN.md`（讲代码质量）互补，不重叠。若需对外发布，可作为根 `README.md` 的 §10「Learning from the predecessor」并入，或保持独立。*
