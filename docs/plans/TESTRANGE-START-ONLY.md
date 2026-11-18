# TestRange 收缩方案：只做「启动 + 自检」，然后交钥匙

状态：已执行（2026-11-18 11:56），执行结果与差异见 §11
日期：2026-11-18
范围：`tests/TestRange/`

---

## 0. 我对需求的理解

TestRange 的职责只保留两件事：

1. **启动**：把指定靶场拉起来（镜像 / 容器 / compose 场景，端口冲突自己处理）；
2. **自检**：证明"从智能体所在主机，此刻真的能连上它"（TCP 可建连 + HTTP 有应答）。

连上之后**不做事**：不写漏洞 PoC、不出测试报告、不驱动 ben。直接交出连接信息，
后续由**主流程**接手：

```
rangectl start <靶场>   →   CONNECTED + connect.env   →   ben setup / ben auto（主流程）
```

也就是说，交付物从"靶场测试框架"变成"**靶场启动器 + 联通性探针**"，
代码量从当前 3396 行降到约 800 行。

> 需要你确认的唯一前提：这里的"主流程"我理解为 ben 的主链路
> （`ben setup --goal … --agents` → `ben command` / `ben auto`）。
> 如果是别的入口，只需要改方案 §5 的三行 handoff，其余不受影响。

---

## 1. 目标 / 非目标

| | 内容 |
|---|---|
| 目标 | 一条命令从"什么都没有"到"可打的靶场 + 可复用的连接环境"；失败时明确指出断在容器层还是网络层 |
| 非目标（本次删除） | 漏洞证明（`[[verify]]` 与 5 个插件）、测试报告、ben 端到端集成、插件注册表 |

---

## 2. 保留 / 删除清单（逐文件）

### 保留（7 个模块，约 780 行）

| 文件 | 精简后的职责 | 改动 |
|---|---|---|
| `rangectl.py` | 命令入口 | 删 `verify` / `kinds` / `test` / `new`；`quickstart` 改名 `start` 并去掉 `--verify/--ben*` |
| `trange/profiles.py` | profile 模型与解析 | 删 `[[verify]]`、`[ben]` 的解析与校验；`ben_goal()` → `handoff_goal()` |
| `trange/adopt.py` | 目录 / 容器 / URL → profile | 不变 |
| `trange/ports.py` | 端口冲突检测与迁移 | 不变 |
| `trange/dockerops.py` | docker / compose 封装 | 不变 |
| `trange/netprobe.py` | TCP / HTTP 探测 | 不变 |
| `trange/connect.py` | 自检判定 + `connect.env` | 不变（这是本工具的核心产物） |
| `trange/runner.py` | 3 阶段编排 | 删 `stage_verify` / `stage_ben` / `_finish` 的报告逻辑，只留 deploy → health → connect |

### 删除（全部 `extras/` 与相关耦合）

| 删除对象 | 现在的作用 | 为什么删 |
|---|---|---|
| `extras/verify.py` | 验证插件注册表 | 漏洞证明不属于"启动 + 自检" |
| `extras/verifiers/*.py`（5 个） | http / tcp / argv / 两个 CVE 的 PoC | 同上，交给主流程的 agent 做 |
| `extras/report.py` | `report.md` + `report.json` | 不再出报告；结论直接打在 stdout |
| `extras/test_rangectl.py` | 38 条自测 | 随被测代码一起删（见 §7 待定项 1） |
| `extras/README.md` | 插件/报告文档 | 随目录删除 |
| `runner.stage_network` | 与 `connect` 重叠的第二次探测 | 自检已覆盖，避免两套"通不通"的说法 |
| `profiles/*.toml` 的 `[[verify]]`、`[ben]` 段 | 漏洞与 ben 参数 | 字段收缩到 deploy/target/health |

---

## 3. 精简后的目录结构

```
tests/TestRange/
├── README.md              # 20 行：怎么启动、怎么读输出、怎么交给主流程
├── rangectl.py            # start | connect | down | list | show | doctor
├── trange/
│   ├── __init__.py
│   ├── profiles.py        # 字段：id/title/cve + [deploy] [target] [health]
│   ├── adopt.py           # 目录 / 容器 / URL → profile
│   ├── ports.py
│   ├── dockerops.py
│   ├── netprobe.py
│   ├── connect.py         # 自检 + connect.env
│   └── runner.py          # deploy → health → connect（短路）
└── profiles/
    ├── spring-cve-2022-22947.toml
    └── tomcat-cve-2017-12615.toml
```

`extras/` 整个消失；不再有"连接之后"的代码路径。

---

## 4. 命令面（6 个命令）

```bash
R="python3 tests/TestRange/rangectl.py"

$R start spring-cve-2022-22947                  # 接管→启动→健康→自检→交钥匙
$R start /path/vulhub/tomcat/CVE-2017-12615     # 场景目录
$R start cve-2022-22947-spring-1                # 容器名
$R start http://10.0.0.7:8080                   # 只有地址（不启容器，只连）

$R connect spring-cve-2022-22947                # 只自检，不启动
$R down    spring-cve-2022-22947 [--remove]     # 收尾
$R list / show / doctor                         # 查状态、看配置、查环境
```

`start` 的参数收缩为：`--id` `--host` `--port` `--force` `--no-deploy` `--out` `--json`。

**输出形态不变**（这部分已经是"启动 + 自检"该有的样子）：

```
ok: CONNECTED http://127.0.0.1:8081 — tcp open, HTTP 200 in 3ms | Apache Tomcat/8.5.19
  [PASS] deploy   already running (running)
  [PASS] health   http://127.0.0.1:8081/ -> HTTP 200 in 19ms (waited 0.0s, budget 120s)
  [PASS] connect  CONNECTED … | Apache Tomcat/8.5.19
```

退出码：`0` = 可以进主流程；`1` = 某层失败（deploy / health / connect）；`2` = 用法或配置问题。

---

## 5. 与主流程的衔接（本方案的关键契约）

`start` 的最后一步不是"出报告"，而是**打出可以直接复制的三行**：

```
handoff:
  source runs/testrange/tomcat-cve-2017-12615-20261118-115500/connect.env
  ben setup --goal "assess and exploit CVE-2017-12615 at $TARGET_URL (authorized local lab)" --agents
  ben command
```

- `connect.env` 是唯一跨模块接口：`TARGET_URL` / `TARGET_HOST` / `TARGET_PORT` /
  `TARGET_CONTAINER` / `TARGET_CONTAINER_IP`（另有一行注释给出容器侧端口）。
- goal 由 profile 的 `cve` + `title` 拼出，占位 `{target}` 在打印时替换成实际 URL。
- TestRange **不执行**这三行，只打印——进退由主流程决定。

---

## 6. 删除的影响面（要动的地方）

| 位置 | 改动 |
|---|---|
| `rangectl.py` | 删 `cmd_verify` / `cmd_kinds` / `cmd_test` / `cmd_new`；`cmd_quickstart` → `cmd_start` 并去掉 `--verify/--ben*` |
| `trange/runner.py` | 删 `stage_verify`、`stage_ben`、`_seed_fact`、`_find_ben`、`stage_network`；`_finish` 改为"打印结论 + 写 env + 打 handoff" |
| `trange/profiles.py` | 删 `verify` / `ben` 字段与校验；`ben_goal()` → `handoff_goal()` |
| `profiles/*.toml` | 两份都删掉 `[[verify]]` 与 `[ben]` 段 |
| `extras/` | 整目录删除 |
| `scripts/ci/arch_check.py` | 不用改（只扫 `ben/`） |
| 全量 `pytest` | 若删 `test_rangectl.py`，用例数从 169 降到 ~131（ben 本体不受影响） |
| 文档 | 顶层 `README.md` 重写为"启动器手册"；本方案留档在 `docs/plans/` |

---

## 7. 需要你拍板的三件事

1. **自测留不留？**
   - 全删（严格按"其他都不需要留"）：最干净，但失去唯一不依赖 docker 的回归网，以后改 `adopt`/`ports` 只能靠手工试。
   - 留 10 条（约 80 行，只测 profile 解析、端口迁移、连接判定）：推荐，成本极低。
2. **`adopt`（自动接管）留不留？**
   - 留：才能做到"任意靶场一条命令"（场景目录 / 容器 / URL 直接开）。
   - 删：命令只能吃手写 profile，`start <目录>` 这类用法就没了。
3. **删除前是否打备份？**
   `tests/TestRange/` 目前**整个目录未纳入 git**（`git status` 显示 `?? tests/TestRange/`），
   删掉无法恢复。**强烈建议**先 `tar czf runs/archive/testrange-$(date +%m%d-%H%M).tar.gz -C tests TestRange`。

---

## 8. 实施步骤（每步都可停、可回退）

| 步 | 动作 | 验证 |
|---|---|---|
| S1 | 备份整个目录到 `runs/archive/` | `tar tzf` 能列出 22 个文件 |
| S2 | 删 `extras/`，`runner` 去掉 verify/ben/network，`rangectl` 去掉对应命令 | `start` 两个靶场仍 CONNECTED |
| S3 | 收紧 profile 字段 + 重写 README | `grep -rn "verify\|ben\|report"` 目录内为空（README 的 handoff 段除外） |
| S4 | 验收（§9） | 全部通过后，把本文件状态改为"已执行" |

---

## 9. 验收标准

- 容器停止状态下 `rangectl start spring-cve-2022-22947`，从 `Exited` 到 `CONNECTED` 一次成功；
- `rangectl start /path/vulhub/tomcat/CVE-2017-12615` 在 8080 被占时自动迁移端口并 `CONNECTED`；
- 失败路径 `rangectl start http://127.0.0.1:9 --no-deploy`：退出码 `1`，输出明确写 `tcp … refused/timeout`；
- 目录内代码量 ≤ 900 行（`wc -l`），不再出现 `[[verify]]` / `report` / `ben auto` 字样；
- `python3 tests/TestRange/rangectl.py list` 仍能显示两个靶场的实时状态。

---

## 10. 取舍说明（为什么可以放心删）

- **删掉漏洞证明不会丢能力**：靶场"能不能打穿"本来就该由主流程的 agent 判断，
  工具提前做一遍只会重复劳动，还会让"连上了"和"打得穿"两个结论纠缠在一起。
- **删掉报告不会丢证据**：结论行 + 退出码 + `connect.env` 已经是机器可读的凭证；
  需要留痕的场景，主流程自己的 `ben fact` / 报告机制会记。
- **留下的部分都是"不可省略"的**：接管（目标形态太杂）、端口编排（同机多靶场必然冲突）、
  探测（判定的唯一依据）、`connect.env`（唯一接口）。

---

## 11. 执行结果（2026-11-18 11:56）

按你的三个决定执行：**先备份 → 自测全删 → adopt 也删**。

| 项 | 结果 |
|---|---|
| 备份 | `runs/archive/testrange-1118-1152.tar.gz`（49K，22 文件，删前状态） |
| 删除 | `extras/`（verify + 5 插件 + report + 38 自测 + 其 README）、`trange/adopt.py` |
| 裁剪 | `runner.py` 只剩 deploy/health/connect；`profiles.py` 去掉 `[[verify]]`/`[ben]`；`rangectl.py` 去掉 verify/kinds/test/new/adopt/up/check |
| 改名 | `quickstart` → `start`；结尾打印 handoff 三行 |
| 规模 | 22 文件 / 3396 行 → **11 文件 / 1309 行**（方案估的 900 偏低，docstring 与命令分发占大头） |
| 验证 | 两靶场 `start` 全 PASS（含容器停止后冷启动 2.0s）；端口关闭场景退出码 1；`arch_check` 0 violation |

**与方案的差异（因 adopt 被删）**：`start` 只接受 profile id 或 `.toml` 路径，不再接受
"场景目录 / 容器名 / URL"。随之删掉了 `prepare_compose`（场景克隆）与 `resolve_target`；
`compose_dir` 仍保留为启动方式，但端口由 compose 文件决定，工具只提示不迁移。

