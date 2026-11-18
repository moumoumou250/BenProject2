# 根目录归类方案

> **状态（2026-11-18）**：R1 与 R5 已落地，`arch_check` 升为八项检查、0 violation。
> 剩余：R2（`lab/` 出索引，待确认）、R3（`docs/` 分层）、R4（`docs_links` 检查）、
> R6（`.ben/` 处置）。

对象：`/home/kali/Desktop/AI/BenProject` 根下 22 个条目（含隐藏）。
目标：根只留「源码 / 契约文件 / 工具入口」，其余各有归属，且**归类结果由检查器保证不再长回来**。

---

## 1. 现状：22 个根条目，实际只有 4 类

| 类 | 条目 | 体积 | 被跟踪 | 判定 |
|---|---|---|---|---|
| **产品源码** | `ben/` `tests/` | 1.7M | 110 | 留在根 |
| **工具入口** | `bin/ben` `scripts/` `skills/` `examples/` | 136K | 11 | 留在根 |
| **文档** | `docs/`（13 个文件平铺） | 252K | 5 | **需分层** |
| **数据归档** | `lab/` | 3.9M | **29** | **需出索引** |
| **生成物残留** | `console/` `.cursor/` `.screenshots/` `.verify-runtime-bo1p4_zv/` `.Trash-0/` `.pytest_cache/` | 468K | 0 | **全空/垃圾，删** |
| **本地环境** | `.venv/` `.workbuddy/` `.ben/` `.claude/` `.git/` | 104M | 1 | 隐藏，留存但需清理 |

实测依据：

```
console/                     0 个条目    ← 旧版 console_root 的残留（已改到 runs/console）
.cursor/                     0 个条目
.screenshots/                0 个条目（仅一个空 .tmp）
.verify-runtime-bo1p4_zv/    0 个条目    ← 上一轮验证脚本没清干净的临时目录
.Trash-0/                    412K，全是 .trashinfo
.workbuddy/tmp/              3.8M，截图 + main.js 副本 + 模拟脚本
```

---

## 2. 真正的问题不是「不好看」，是三条

**① 四个空目录说明「删掉的路径没人收尾」。**
`console/` 是 `runtime/console.py` 改路径前的产物，`.verify-runtime-*` 是验证脚本的 `mkdtemp(dir=".")`。它们不占体积，但会让人以为还在用。

**② `docs/` 13 个文件平铺，其中 3 个是同一件事的三个版本。**
`OPTIMIZATION-PLAN.md` / `-v2` / `-v3` 合计 69K，v1 和 v2 已被取代，但和现行文档并排躺着。新读者无法从目录判断该读哪个。

**③ 根目录没有「允许清单」，所以每次都会长出新东西。**
这是根因。上一轮已经为运行时输出立了单一根（`paths.py` + `runtime_paths` 检查），但**仓库根本身**还没有等价物。

**附带发现（归类审计时撞见的）**：全库 42 条相对链接里 **18 条失效（43%）**，全部集中在两个 README——6 张 `docs/assets/*.jpg` 和 `docs/tmux-removal-plan-v3.md` 都不存在。这类问题现在没有任何机器在拦。

---

## 3. 目标结构

```
BenProject/
├── README.md                  # 门面（英文）
├── AGENTS.md                  # 必须留根：hook 与工具按此路径读
├── .gitignore  .env.example
├── ben/                       # 唯一的包
├── tests/
├── bin/ben                    # 启动器，install.sh 与 README 都指向此路径
├── scripts/
│   ├── install.sh
│   ├── ci/{arch_check.py, preflight.sh}
│   └── hooks/{ben-hook.py, _settings_patch.py}
├── skills/ben-setup/          # 可分发的 agent skill，install.sh 软链到 ~/.claude/skills
├── examples/grok/
├── docs/
│   ├── INDEX.md               # 新增：唯一入口，按「要做什么」分组
│   ├── ARCH.md  SKILL.md  CHANGELOG.md  DISCLAIMER.md  README.zh-CN.md
│   ├── adr/                   # 决策记录
│   ├── reviews/               # 评审编号存档
│   ├── plans/                 # 重构/优化方案
│   │   ├── OPTIMIZATION-PLAN-v3.md      ← 现行
│   │   └── archive/{OPTIMIZATION-PLAN.md, OPTIMIZATION-PLAN-v2.md}
│   ├── research/              # 对比与学习笔记
│   │   ├── compare-sapper-vs-ben.md
│   │   └── LEARN-FROM-SAPPER.md
│   └── reports/               # 事后复盘
│       └── BATTLE-REPORT.md
├── lab/juice-shop-20261117/   # 归档靶场数据，不跟踪、不写
└── .ben/ .claude/ .venv/ .workbuddy/ .pytest_cache/ .git/   # 隐藏，保留
```

根从 22 条降到 **12 条可见 + 5 条隐藏**，且每条都能一句话说清归属。

---

## 4. 五项动作，按风险排

### R1 清理零散残留（零风险，5 分钟）

```bash
rmdir console .cursor .screenshots/.tmp .screenshots .verify-runtime-bo1p4_zv
rm -rf .Trash-0 .workbuddy/tmp/*
```

`.gitignore` 补四条，防再生成：

```gitignore
.verify-*/
.screenshots/
.pytest_cache/
/console/
```

> `.Trash-0/` 是桌面环境回收站，删掉不影响任何东西；`.workbuddy/tmp/` 是截图与 JS 副本，3.8M。

### R2 `lab/` 退出索引（需你确认，10 分钟）

目前 29 个文件（2.7M）**仍被跟踪**，`.gitignore` 里的 `/lab/` 对已跟踪文件无效：

```bash
git rm -r --cached lab/juice-shop-20261117   # 保住本地文件，只退出索引
```

更彻底的做法是移出仓库（仓库 −3.9M）：

```bash
mv lab ~/ben-lab-archive
```

> 历史（对象库）里那份仍在。要不要 `filter-repo` 是 `docs/plans/OPTIMIZATION-PLAN-v2.md` §P0-A 单独待决的事，不在本次范围。

### R3 `docs/` 分层（中等，16 处链接要改）

| 移动 | 引用点 |
|---|---|
| `BATTLE-REPORT.md` → `reports/` | 4 处（README、README.zh-CN、v3、compare） |
| `compare-sapper-vs-ben.md`、`LEARN-FROM-SAPPER.md` → `research/` | 1 处（后者被前者引用） |
| `OPTIMIZATION-PLAN.md`、`-v2` → `plans/archive/`，`-v3` → `plans/` | 6 处（含 preflight.sh 与 ADR 0004） |
| `ARCH.md/SKILL.md/CHANGELOG.md/DISCLAIMER.md/README.zh-CN.md` | 不动 |

16 处全是机械替换，可用一条命令改完后由 R4 的链接检查验证。

### R4 补一个 `docs_links` 检查（防回归，这才是重点）

`arch_check.py` 加第八项：所有 md 的相对链接必须解析得到文件。

```bash
python scripts/ci/arch_check.py --check docs_links
# 现在会红 18 条 —— 说明规则有效
```

**顺序很重要**：先落检查，它会立刻红；再修 README 的 6 张图和 1 篇缺失文档（删引用或补图），红转绿。这样「链接不能烂」从今天起有人管，而不是靠下次审计。

### R5 根目录白名单（防长回来）

第九项 `root_layout`：根下只允许固定集合，其余报红并提示该放哪。

```python
ALLOWED_ROOT = {
  # files
  "README.md", "AGENTS.md", ".gitignore", ".env.example",
  # dirs
  "ben", "tests", "bin", "scripts", "skills", "examples", "docs", "lab",
}
HIDDEN_ALLOWED = {".git", ".ben", ".claude", ".venv", ".workbuddy", ".pytest_cache"}
```

报错文案给出去处，而不是只说不许：

```
✗ root_layout  ./tmp/  is not a declared root entry
  → generated files belong under runs/ (ben/core/paths.py);
     sample data belongs under examples/; archived target material under lab/
```

### R6 待你决策：`.ben/` 里装的是别人的图

根 `.ben/project.json` 的 goal 是：

```
assess and exploit OWASP Juice Shop at http://117.72.199.2:3000/
```

也就是说，**每轮改 ben 源码的对话，注入的是那次靶场评估的图谱**。三个选项：

| 选项 | 命令 | 结果 |
|---|---|---|
| A 清空重建 | `ben teardown --purge && ben init` | 得到本仓库自己的图（重构进度、ADR 待办） |
| B 保留但隔离 | 把 `.ben/` 移到 `lab/juice-shop-20261117/.ben/` | 根干净，但本仓库失去 working memory |
| C 不动 | — | 继续用靶场图谱讨论源码改动 |

我倾向 **A**：这个仓库正在做结构性重构，正是最需要一张真实图谱的时候；而 Juice Shop 那份已经在 `lab/` 里有一份完整副本（`lab/.../runs/juice/.ben/`）。

---

## 5. 执行顺序

```
今天      R1 清理      →  re-run arch_check（应仍 0 violation）
今天      R5 白名单    →  先红（列出当前违规）→ 按报错归位 → 绿
这周      R4 链接检查  →  先红 18 条 → 修 README → 绿
这周      R3 docs 分层 →  移动 + 16 处链接替换 → R4 验证绿
你决定后  R2 lab 出索引
你决定后  R6 .ben 处置
```

R5 放在 R3 之前是刻意的：先让「根只能有什么」变成可执行规则，R3 才有验收标准；否则移动完没人知道是否到位。

---

## 6. 不做清单

- **不把 `ben/` 移到 `src/`**：会同时改 `pyproject`/`bin/ben`/`install.sh`/107 处 import，收益为零。
- **不把 `bin/` 合进 `scripts/`**：`install.sh`、README、用户 `~/.local/bin/ben` 三处依赖 `bin/ben` 这个路径。
- **不拆 `tests/test_ben.py`**（1485 行 / 86 个测试）：pytest 收集成本不高，拆开要重做共享 fixture，现在没有收益。等出现真实冲突再拆。
- **不建 `docs/assets/` 放占位图**：缺的 6 张图应该删引用，不是造占位图掩盖。README 里那套 tmux 时代的叙事是否还成立，是另一个问题（`docs/tmux-removal-plan-v3.md` 整个文件都不在了）。
- **不为 `skills/` 改名**：`install.sh:87` 直接软链 `skills/ben-setup`，改名要同步改安装脚本与 `~/.claude/skills` 兼容路径。

---

## 7. 验收

```bash
python scripts/ci/arch_check.py                 # 9 checks, 0 violation
ls -A | wc -l                                   # 17（12 可见 + 5 隐藏）
git ls-files lab | wc -l                        # 0
ruff check . 2>/dev/null || true                # 不影响本案
python -m pytest -q                             # 120 passed / 3 skipped
```
