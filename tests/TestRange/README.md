# TestRange — 启动靶场 + 连接自检

一条命令把靶场拉起来，并证明"**从这台机器、此刻，真的连得上**"；连上之后它不做别的事，
只交出 `connect.env` 和下一步命令，剩下的交给主流程。

```bash
cd /path/to/BenProject
R="python3 tests/TestRange/rangectl.py"

$R start spring-cve-2022-22947     # 启动 → 健康 → 连接自检 → 交钥匙
$R connect spring-cve-2022-22947   # 靶场已在跑，只做自检
$R down spring-cve-2022-22947      # 收尾
```

退出码 `0` 表示"已启动且连接自检通过"，可以直接进主流程；非 0 就说明还不到那一步。

---

## 1. 目录结构

```
tests/TestRange/
├── rangectl.py          # 命令入口：start / connect / down / list / show / doctor
├── trange/
│   ├── profiles.py      #   profile 模型与解析（只含启动/自检所需字段）
│   ├── ports.py         #   端口冲突检测、迁移
│   ├── dockerops.py     #   docker / compose 薄封装
│   ├── netprobe.py      #   TCP / HTTP 探测 + 退避重试
│   ├── connect.py       #   连接自检判定 + connect.env
│   └── runner.py        #   三阶段编排：deploy → health → connect
├── profiles/            # 每个靶场一份（唯一的输入数据）
└── README.md
```

共 11 个文件（8 个 `.py` + 2 个 profile + 本文），约 1300 行，纯标准库。**没有**漏洞插件、
报告渲染、ben 集成、自测套件——这些按约定交给主流程。

---

## 2. 命令

| 命令 | 做什么 |
|---|---|
| `start <id>` | 启动 → 健康 → 连接自检 → 打印 handoff |
| `connect <id>` | 只做连接自检 + 写 `connect.env`，不启动 |
| `down <id> [--remove]` | 停止（可选 `docker rm -f`） |
| `list [--json]` | 所有 profile + 容器实时状态 |
| `show <id>` | 打印解析后的 profile |
| `doctor` | docker / python / ben / profile 路径自检 |

`start` 的参数：

| 参数 | 默认 | 说明 |
|---|---|---|
| `id` | 必填 | profile id；也可以直接给 `.toml` / `.json` 路径 |
| `--port N` | 用 profile 的 | 强制宿主端口（被占则报错，不静默改） |
| `--no-deploy` | false | 靶场由别处管理，只做健康 + 自检 |
| `--out DIR` | `runs/testrange/<id>-<ts>` | 产物目录 |
| `--json` | false | 机器可读结果 |

`--profiles DIR` 写在子命令**之前**，用于把 profile 放到别处。

---

## 3. profile 字段

除 `id` 与 `[target].url` 外全部可选。

```toml
id    = "spring-cve-2022-22947"
title = "Spring Cloud Gateway Actuator SpEL RCE"
cve   = "CVE-2022-22947"
tags  = ["java", "spring"]

[deploy]                                  # 怎么把靶场弄起来
container = "cve-2022-22947-spring-1"     # 容器名；留空 = 外部托管，只测不启
image     = "vulhub/spring-cloud-gateway:3.1.0"   # 容器不存在时 docker run
ports     = ["8080:8080", "5005:5005"]    # host:container
# compose_dir = "/path/to/vulhub/spring/CVE-2022-22947"   # 有则走 compose up
restart   = "unless-stopped"
create_if_missing = true

[target]                                  # 打哪里
url = "http://127.0.0.1:8080"             # 必填

[health]                                  # 怎么算"起来了"
path          = "/actuator"
expect_status = 200                       # 0 = 接受任意状态码
expect_body   = '"_links"'                 # 正则，防止错误页也算 200
timeout       = 120                       # 冷启动总预算（秒）
interval      = 3                         # 轮询上限间隔（内部 1.0 → 1.5× 退避）
```

接一个新靶场 = 复制一份 toml 改三处（`container`/`ports`/`url`），零代码。

---

## 4. 输出

### 4.1 成功（冷启动，真实输出）

```
$ R start tomcat-cve-2017-12615
[trange] target tomcat-cve-2017-12615 -> http://127.0.0.1:8081
[trange] container cve-2017-12615-tomcat-8081: exists=True running=False
[trange] health after 2.0s: http://127.0.0.1:8081/ -> HTTP 200 in 951ms

ok: CONNECTED http://127.0.0.1:8081 — tcp open, HTTP 200 in 4ms | Apache Tomcat/8.5.19

  [PASS] deploy   started: status=running ports=['0.0.0.0:8081->8080/tcp']
  [PASS] health   http://127.0.0.1:8081/ -> HTTP 200 in 951ms (waited 2.0s, budget 120s)
  [PASS] connect  CONNECTED http://127.0.0.1:8081 — tcp open, HTTP 200 in 4ms | Apache Tomcat/8.5.19

env:  runs/testrange/tomcat-cve-2017-12615-…/connect.env

handoff (nothing below is run by rangectl):
  source runs/testrange/tomcat-cve-2017-12615-…/connect.env
  ben setup --goal "assess and exploit CVE-2017-12615 at http://127.0.0.1:8081 (authorized local lab)" --agents
  ben command            # or: ben auto
```

四段含义：

| 输出 | 含义 |
|---|---|
| `[trange] …` | 过程日志：端口迁移、容器状态、健康轮询耗时 |
| `ok: CONNECTED …` | 结论行：`CONNECTED <url> — tcp open, HTTP <码> in <毫秒> \| <对端自述>`。`\|` 后面优先取页面 `<title>`（`Apache Tomcat/8.5.19`），JSON 应答显示 `json keys: _links`，否则正文前 70 字 |
| `[PASS]/[FAIL] <阶段>` | 分阶段结果，阶段名固定 `deploy` / `health` / `connect` |
| `env:` / `handoff:` | 可直接 `source` 的环境文件 + 下一步给主流程的三行命令 |

### 4.2 自检判定

| 检查 | 含义 | 影响结论 |
|---|---|---|
| TCP 可建连 | 目标端口能三次握手（冷启动重试 3 次） | **必须** |
| HTTP 有应答 | 收到任何状态码（200/404/401/500 都算活） | **必须** |
| 端口映射 / 容器 IP | 记录下来供容器间访问 | 只告警 |

"连得上"不等于"打得穿"——后者由主流程判断。两者分开，才不会把"应用返回 500"当成
"网络不通"，也不会把"能连上"当成"有漏洞"。

自检成功后写 `connect.env`：

```bash
source runs/testrange/<id>-<ts>/connect.env
# TARGET_URL / TARGET_HOST / TARGET_PORT / TARGET_CONTAINER / TARGET_CONTAINER_IP
```

`connect` 还会多打一行 `# from another container: http://<容器IP>:<容器侧端口>`。

### 4.3 失败（真实输出）

```
FAIL: health failed — http://127.0.0.1:9/ -> HTTP 502 (want 200) (waited 5.0s, budget 5s)

  [PASS] deploy   skipped (--no-deploy): assuming the range is managed elsewhere
  [FAIL] health   http://127.0.0.1:9/ -> HTTP 502 (want 200) (waited 5.0s, budget 5s)
```

| 提示 | 含义 / 处置 |
|---|---|
| `FAIL: health failed — … (want 200)` | 预算内没等到期望状态 → 加大 `[health].timeout`，或放宽 `expect_body`/用 `expect_status = 0` |
| `FAIL: NOT CONNECTED … — tcp … refused/timeout` | 端口没人监听 → `docker ps` 看 PORTS、`ss -ltnp` 看占用 |
| `[FAIL] deploy  …` | 容器起不来 / 镜像缺失 / 无权限 → `$R doctor` |
| `profile error: no profile for 'x'` | id 不存在 → `$R list`（错误里会列出可用 id） |
| `port error: requested port N is already in use` | `--port` 指定的口被占 → 去掉 `--port` 让工具自己挪 |

退出码：`0` 已连接；`1` 某阶段失败；`2` 用法/配置问题（profile 不存在、端口冲突、docker 缺失）。

---

## 5. 端口被占

同一台机器并存多个靶场时 `8080` 只有一个，`start` 按代价排序处理：

1. **迁端口**：目标口被占 → 从 `+1` 找空闲口，只改本次运行的内存对象，不动磁盘 profile；
2. **停容器重建**：容器存在但已停止，其端口绑定改不了 → 用原镜像另起 `<原名>-<新端口>`；
3. **compose 场景不动**：端口由 compose 文件决定，工具只提示，不假装改成功。

动作都会打印成 `[trange] host port 8080 busy -> moved to 8082`。

---

## 6. 边界

`start` 到 `connect` 为止。它**不**做：漏洞验证、报告生成、ben 调度、计分。
需要这些能力时，从 handoff 的三行往下接，或把插件写在主流程里。

已验证（2026-11-18）：

| 场景 | 结果 |
|---|---|
| Spring CVE-2022-22947 @8080，容器已在跑 | 3 阶段全 PASS，0.1s |
| Tomcat CVE-2017-12615 @8081，容器停止 | 冷启动 2.0s → CONNECTED |
| 目标端口关闭（`http://127.0.0.1:9`） | 退出码 1，明确报 `502 (want 200)` |
