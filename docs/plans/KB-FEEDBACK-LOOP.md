# KB 回补闭环：确认方案（check / diagnose / probe）

状态：**已确认**（2026-11-18）  
前身：同日待评审稿 + `docs/plans/CLI-KB-AUDIT.md` 核查  
范围：`ben/kb/`、`ben/commands/kb_cmds.py`、`ben/cli.py`、`tests/TestRange/profiles/`、`docs/kb-iterations.md`  
约束：`probe` 只对 profile 白名单目标执行；`diagnose`/`check`/`probe` 不写 KB；不动 `Store` / fact graph / **默认** `kb search` 行为  
关系：继承 `docs/plans/KB-SCOPE-VERIFY.md` 的 `--only` 截断语义；CLI 冲突处置以 `CLI-KB-AUDIT.md` 为准

---

## 0. 一句话

`check` 判知识可达，`diagnose` 判缺口类型，`probe` 判目标证据；三者结果按 §6 的 4 类动作回补 KB，每次回补在账本留一行前后对照。

**命令面（确认）**：

```
ben kb check "<query>" --only <id>[,<id>...] [--json] [--show-tokens] [--root DIR]
ben kb diagnose "<query>" --only <id>[,<id>...] [--variants "a,b"] [--variants-file F] [--json]
ben probe <profile-id> <vuln> [--force] [--allow-destructive]
         [--max-requests N] [--timeout S] [--deadline S] [--json] [--profiles DIR]
```

- 原草案 `ben verify --target/--vuln` → **`ben probe`**（现有 `ben verify --intent` 保留，证据门禁不动）
- `--yes` → **`--force`**
- `--target/--vuln` flag → **两个位置参数** + 交叉校验

本文件是契约与流程；不含实现代码。落地按 §12，每步可停可退。

---

## 0.1 评审结论：保留 / 修订 / 否决

| 项 | 裁决 | 说明 |
|---|---|---|
| 三层职责分离（可达 / 缺口 / 证据） | **保留** | 实测打分器不可信，必须先有可判的 check |
| 改名 `ben probe`、位置参数、`--force` | **保留** | 与 `CLI-KB-AUDIT` 一致，已核实 `ben verify --intent` 占用 |
| 新命令退出码 `0/1/2/3` | **保留（有意例外）** | 见 §5.3；老 `kb *` 仍 `FGError→1`，不改 |
| `taxonomy.json` 放 `ben/kb/` | **保留** | 与条目同生命周期，随 `BEN_KB_ROOT` |
| 4 类回补动作 + 账本 SOP | **保留** | 成本序 `C < D < A < B` 合理 |
| S1 **改** `KnowledgeBase.search()` / `text.tokenize` 默认路径 | **否决** | 与「`search` 输出逐字节不变」自相矛盾 |
| 重叠双字切（`布尔`/`尔盲`/`盲注`） | **否决** | `尔盲` 是噪声；改为非重叠 + 词表最长匹配优先 |
| `probe` 只允 RFC1918/localhost | **修订** | `authorized=true` 的 profile host **可公网**；否则仍仅私网 |
| agent 自动 `kb add` 与人工迭代混仓 | **补硬门槛** | 见 §12 S0 |
| 用 `title title` + `set()` 假装加权 | **否决** | 现码已证实无效；新匹配器用显式字段权重 |

**已核实证据（2026-11-18）**：`kb show kb999`→exit 1；`kb bogus`→exit 2；`verify --help` 为 evidence；`git ls-files ben/kb`=57；`validation` 覆盖=0；`提权`/`sql 注入`/`二次注入` 误命中与草案 §3 一致；`ben/kb/__init__.py` 工作树仍为 `M`。

---

## 1. 术语（只用这些词）

| 词 | 含义 | 侧 |
|---|---|---|
| 核心词 / 限定词 | 漏洞大类 / 变体 | 检索面 |
| `HIT` / `WEAK` / `MISS` | check 内部三态 | check |
| 叫法缺口 / 内容缺口 | 词不对 / 库没有 | diagnose |
| `CONFIRMED` / `NOT_CONFIRMED` / `UNVERIFIED` | 有证据 / 无证据 / 未取得结论 | probe |

纪律：「命中」属 check，「证实」属 probe。禁止混用。

---

## 2. 三层职责

| 命令 | 回答 | 网络 | 写盘 |
|---|---|---|---|
| `ben kb check` | 给定 scope 内知识取得到吗 | 否 | 否 |
| `ben kb diagnose` | 取不到是叫法还是内容 | 否 | 否 |
| `ben probe` | 靶场响应是否构成证据 | 是（预算约束） | 仅 `runs/probe/...` |

共用退出码语义：`0` 正向 / `1` 否定 / `2` 调用方错 / `3` 无法下结论。

---

## 3. 现状（基线，勿当目标）

全库 56 条，`validation`=0。根因：

1. `ben/core/text.py`：CJK 单字切；
2. `search()`：`set(_tokenize(f"{title} {title} ..."))` → title×2 **无效**；
3. `overlap > 0` 即命中，无覆盖阈值；
4. `detail` 参与匹配 → 散字误撞。

**因此：新三态判定不得建立在当前 `search()` 上。** S1 只引入**并行**匹配器。

---

## 4. 数据契约

### 4.1 `entries/*.json` → `validation`

| 键 | 必填 | 语义 |
|---|---|---|
| `signal` | **是** | 可观测响应特征 |
| `baseline` | 否 | 阴性对照 |
| `reject` | 否 | 误判条件；命中时优先于 signal → `NOT_CONFIRMED` |
| `min_evidence` | 否 | 最少观测组数 |

硬规则：缺 `validation` 或 `signal` 空 → `probe`=`3 NO_VALIDATION`；无 baseline 允许 `0` 但打印 `warn: 无阴性对照`。

MVP 期补 `validation`：**手工编辑 JSON**（`add()` 暂不扩签名）。S5 后再考虑 `ben kb` 写字段入口。

### 4.2 `ben/kb/taxonomy.json`（新增）

`check` 拆核心/限定，`diagnose` 出变体，`probe` 把 vuln → kb id。结构同前身草案（`subjects` + `vulns`）。

硬规则：

1. 每个 vuln ≥1 个存在的 `kb` id；
2. aliases / groups 每组 ≥2（含规范名），否则不参与 diagnose；
3. subjects 未命中 → 纯词面 + `note:`，**不是** exit 2；
4. 文件损坏 → check/diagnose/probe 一律 `2`。

S3 最小集：subject `注入` + vuln `file-write`→`kb003`。

### 4.3 profiles 可选字段

```toml
vulns = ["file-write"]
authorized = true   # 缺省 false
```

`probe` 不接受裸 URL，只接受 profile id。

---

## 5. 命令契约

### 5.1 `ben kb check`

`--only` 必填（可重复/逗号）；空或缺 id → `2`（列出可用 id，最多 10 + `...`）。

| 状态 | 条件 | 码 |
|---|---|---|
| `HIT` | 核心覆盖 ≥ 阈值，且限定词（若有）被覆盖 | 0 |
| `WEAK` | 核心够，限定不够 | 1 |
| `MISS` | 核心不够 | 1 |

输出必含：`scope:`（含 excluded N）、每条 `core=`/`qualifier=` 依据。score 可展示，**不参与三态**。

实现：调用 `ben/kb/match.py`（新），**禁止**改默认 `KnowledgeBase.search()` 算法。

### 5.2 `ben kb diagnose`

变体优先级：`--variants` > `--variants-file` > taxonomy 命中组 > 无。

| 结果 | verdict | 码 |
|---|---|---|
| ≥1 HIT | 叫法缺口 | 0 |
| 全 MISS | 内容缺口 | 1 |
| 无 HIT 有 WEAK | 无法归因 | 3 |
| 变体数 < 2 / 用法错 | — | 2 |

单变体不得判缺口类型。

### 5.3 退出码（与老命令的有意偏差）

| 错误类型 | 老 `kb add/search/show/...` | 新 `check/diagnose/probe` |
|---|---|---|
| argparse | 2 | 2 |
| id 不存在 / `--only` 空 / taxonomy 坏 | 1（FGError） | **2**（命令内显式 return，先于 get） |
| 否定结论 | — | 1 |
| 无法判定 | — | 3 |

必须写进 `--help` 与 docs。实现上：**不要**笼统 `except KBError: return 2`；对 `--only`/taxonomy 做本地校验后 `return 2`，其余意外仍可走 FGError→1。

### 5.4 `ben probe`

判定序（不可调换）：

```
① 参数：vuln∈taxonomy？profile 存在？host 允许？ → 否则 2
② 判据：映射到 kb 且 signal 非空？           → 否则 3 NO_VALIDATION
③ 发包（预算内）→ 0 / 1 / 3 子原因
```

**host 允许（确认修订）**：

| 条件 | 允许 |
|---|---|
| profile.`authorized = true` | 该 profile 声明的 host（可公网 lab） |
| 否则 | 仅 `127.0.0.1` / `::1` / RFC1918 |
| 其它 | `2` |

另：无 `authorized` 时仍须 `--force` 才执行（双闸：授权标记 + 显式确认）。有 `authorized=true` 时可无 `--force`，但仍受预算与 `--allow-destructive` 约束。

其它硬约束：只读默认；写/删/RCE 需 `--allow-destructive`；默认 max-requests=20、timeout=10s、deadline=120s；证据在 `runs/probe/<profile-id>/<ts>/`；措辞仅「证实/未证实/无法判定」。

`CONFIRMED` 必须能指出证据目录里支撑结论的请求/响应行。

`--profiles`：写在子命令后；默认解析顺序：显式 DIR → 环境变量（若已有）→ 仓库内 `tests/TestRange/profiles`；找不到 → `2` 并提示路径。

交叉校验：profile-id ∈ profiles，vuln ∈ taxonomy.vulns，交集空 → 写反必 `2`。

---

## 6. 结果 → KB 动作（仅 4 类）

成本：`C < D < A < B`。触发表与「明确不动 KB」列表同前身草案 §6（`probe 2` 词表外→D；`0`+`check 1`→C；`NO_VALIDATION`/`UNREADABLE`→A；`PAYLOAD_MISMATCH`/`BLOCKED`/`NOT_VULNERABLE`+`check 1`→B）。

`diagnose`/`probe` **只打印建议**，落盘由人执行。

---

## 7. 依赖顺序

```
① A 补判据 → ② A 改解析 → ③ B 修假设 → ④ B 补绕过
→ ⑤ C 补别名 → ⑥ B 补内容 → ⑦ D 扩词表
```

① 不在前则 ②③④ 空转；⑤ 在 ⑥ 前；⑦ 必须指向已存在条目。

check×probe 动作矩阵：仅 `(1,0)` 与 `(1,1)` 动 KB；`(0,0)` 留样本；`(0,1)` 查执行不改 KB；环境类记 `UNVERIFIED` 不入表。

---

## 8. 迭代 SOP（6 步）

基线 →（check=1 则 diagnose）→ 单一动作类 → 只改一处 → 复跑 → 写账本。  
规则见 `docs/kb-iterations.md`：单动作类、前后成对、改动写到字段、与 CHANGELOG 分工。

---

## 9. 验收（S2 后粘贴）

```bash
./bin/ben kb check "sql 注入"  --only kb001,kb002   # 0 HIT
./bin/ben kb check "布尔盲注"  --only kb001,kb002   # 1 WEAK
./bin/ben kb check "提权"      --only kb002         # 1
./bin/ben kb check "文件上传"  --only kb002         # 1
./bin/ben kb check "提权"      --only kb001,kb012   # 0
./bin/ben kb diagnose "布尔盲注" --only kb001,kb002 # 3 无法归因（组内别名皆 WEAK）
./bin/ben kb diagnose "布尔盲注" --only kb001,kb002 --variants "布尔盲注,sql 注入"  # 0 叫法缺口
./bin/ben kb diagnose "二次注入" --only kb001,kb002 # 1 或 3（无 HIT；限定词未进条目）
./bin/ben kb diagnose "内存马"    --only kb001,kb002 # 2（变体<2；词表扩后期望可变）
./bin/ben kb check "x" --only kb999                 # 2
./bin/ben kb check "x" --only                       # 2
./bin/ben kb search "sql 注入"                      # 与改动前逐字节一致
```

兼容硬门槛：**默认** `ben kb search`（无新算法开关）输出与改动前一致；现有测试全绿。

`probe`（S4 后，本地 TestRange）：

```bash
./bin/ben probe tomcat-cve-2017-12615 file-write
./bin/ben probe tomcat-cve-2017-12615 内存马              # 2
./bin/ben probe tomcat-cve-2017-12615 file-write --max-requests 0  # 3 BUDGET
./bin/ben probe file-write tomcat-cve-2017-12615          # 2
```

双门槛：正例变期望码 **且** 反例仍不中。

---

## 10. 风险与缓解（增量）

| 风险 | 级 | 缓解 |
|---|---|---|
| 知识可达误读成漏洞可检 | 高 | 措辞分离；help 明写 |
| 环境故障并入「未证实」 | 高 | `UNVERIFIED` 独立；BUDGET/CONNECTION 禁入 1 |
| 改 search 破坏兼容 | 高 | **S1 不碰默认 search/tokenize** |
| 公网 lab 被私网闸误杀 | 高 | `authorized=true` 开 profile host |
| agent 自动 add 污染迭代 | 高 | S0：`source` 前缀 + 提交前分类；迭代期不提交无复核 agent 条目 |
| 补词表作弊通过 | 中 | 正反例双门槛；孤词拒入表 |
| id 复用 | 中 | 不删条目，标 `deprecated`（`_next_id` 对尾部删除仍可能复用） |
| KB 零测试 | 中 | S2 起 `tests/test_kb_check.py` |

---

## 11. 不做

- 不改 Store / schema / graph
- 不自动写 KB
- 不做利用链 / 横向 / 报告 / CVSS
- 不做向量检索
- 不做命名 scope 组
- 单变体不定缺口
- probe 不接裸 URL、不批量多目标
- 不合并/改名现有 `ben verify --intent`
- **不**在 S1–S5 改默认 `tokenize` / `search` 排序语义

---

## 12. 实施顺序（确认）

| 步 | 改哪里 | 验收 | 回退 |
|---|---|---|---|
| **S0** | 提交/收干净 `M ben/kb/__init__.py`；约定 agent `source=agent/...`；迭代 commit 账本与 entries 同提交 | `git status ben/kb` 干净或仅有意改动 | — |
| **S1** | **新增** `ben/kb/match.py`（切分+覆盖+三态）；**不改** `search()` / 默认 `tokenize` | 单元测试：提权@kb002→MISS；sql注入@kb001,2→HIT；detail 散字不致 HIT | 删模块即可 |
| **S2** | `kb check`/`diagnose` + cli choices/`--only`/`--variants`；可选：`search --only` 仅做 id 截断（旧打分） | §9 前 11 条；`search` 无回归 | 只删新分支 |
| **S3** | `ben/kb/taxonomy.json` 最小集 | 无孤词/悬挂；缺文件降级 | 删文件 |
| **S4** | `ben probe`，仅 `file-write`；先手补 `kb003.validation` | 实跑能指两行证据；无 validation→3 | 默认闸挡住误触 |
| **S5** | 一次真实回补 + 账本真行（删示例行） | probe 3→0 且 check 未松 | revert 同 commit |

S1–S2 无网络风险；S4 起才有。

---

## 附录 A：匹配规格（S1，`match.py`）

匹配面：

| 字段 | 参与 | 权重 |
|---|---|---|
| `title` | 是 | 高（计数加权，非 set 去重后假重复） |
| `description` / `tags` | 是 | 中 |
| `validation.signal` / `reject` | 是 | 中 |
| `detail` | **否** | — |

切分：

1. **先**对查询做 taxonomy 别名最长匹配，命中组 → 限定词，剩余 → 核心词；
2. 剩余中文：**非重叠**双字（左起成对；奇数字尾保留单字）；英文按词；
3. 停用字不入分母；
4. 核心覆盖 = 命中核心 token 数 / 核心 token 总数；
5. 阈值默认 `0.6`（可配）；score 只排序展示；
6. 无 taxonomy 组 → 整句当核心词 + `note:`。

---

## 附录 B：首次落地清单

- [x] S0：source 约定 + `runs/kb-baseline/`（整仓 commit 待用户明示）
- [x] 登记 §3 五条 `kb search` 基线输出（兼容对照）
- [x] S1：`match.py` + 单测
- [x] S2：§9 十一连 + `test_kb_check.py`
- [x] S3：最小 taxonomy
- [x] 补 `kb003.validation` 后 S4（Tomcat:8081 实跑 CONFIRMED）
- [x] S5：账本真行，删示例

---

## 附录 C：相对前身草案的 diff 摘要

1. S1 从「改 search/tokenize」→「并行 match 模块」  
2. 重叠双字 → 非重叠 + 别名最长优先  
3. probe host：`authorized` profile 可公网  
4. 退出码例外：显式校验 return 2，不吞一切 KBError  
5. 增加 S0（脏树 / agent 写入）  
6. `search --only` 可作 S2 附带，仍用旧打分  
