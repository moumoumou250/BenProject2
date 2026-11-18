# 0007 仓库根是一个封闭集合

- Status: accepted
- Date: 2026-11-18

## Context

ADR 0006 约束了「运行时写哪里」，但仓库根本身仍然没有规则。于是它按堆积的方式
生长，最后同时存在：

- 4 个空目录，全是改过路径的残骸（`console/` 是 `console_root` 从 `<base>/console`
  改到 `<base>/runs/console` 之前留下的；`.verify-runtime-*` 是验证脚本
  `mkdtemp(dir=".")` 没清干净；`.cursor/`、`.screenshots/` 从未被写入）；
- `docs/` 下 13 个文件平铺，其中包括同一件事的三个版本（`OPTIMIZATION-PLAN.md`
  与其 `-v2`、`-v3`，合计 69 KB），新读者无法从目录判断该读哪个；
- 一次靶场评估的 3.9 MB 产物以 `recon/`、`jsscan/`、`fz.py`、`h.txt` 的形式
  直接落在根上，其中 2.7 MB 进了 git 索引。

共同点：**没有任何一条规则说「什么不允许出现在根上」**，所以每次都是事后审计才发现。

## Decision

仓库根只有一个声明的集合，其余一律报错：

- 文件：`README.md`、`AGENTS.md`、`.gitignore`、`.env.example`、`.env`、`.env.local`
- 目录：`ben/` `tests/` `bin/` `scripts/` `skills/` `examples/` `docs/` `lab/`
- 隐藏：`.git` `.ben` `.claude` `.venv` `.workbuddy` `.pytest_cache`
  `.cursor` `.vscode` `.idea`，以及桌面环境的 `.Trash-0`（`rm` 的落点，机器管理）

新条目要进根，必须同时改 `scripts/ci/arch_check.py` 里的 `ROOT_FILES` /
`ROOT_DIRS`——**把「加一个顶层目录」从随手动作变成需要写理由的动作**，这是本决策的全部价值。

`ROOT_HINTS` 让报错本身就是修复指令：

```
✗ root_layout  recon/
    ./recon/ is not a declared root entry — captured target material
    → lab/<engagement>/ (untracked)
```

## Consequences

- 代价：`pyproject.toml`、`Makefile`、`LICENSE` 这类常规根文件也会先报错，需要
  显式登记。这是有意的摩擦——本项目零依赖、用 `bin/ben` 与 `scripts/install.sh`
  就够了，真要加构建配置时应该先想清楚。
- 代价：`.Trash-0` 被放行，因为它是桌面环境的 `rm` 行为，不由项目决定；它已在
  `.gitignore` 里，不可能被提交。
- 收益：根从 22 条降到 19 条（4 个空目录 + `.Trash-0` 已清），`lab/` 出索引后
  为 18 条；且不会再长回来。

## Enforced-by

`scripts/ci/arch_check.py --check root_layout`，判据：对 `repo.iterdir()` 的每个
条目，目录必须在 `ROOT_DIRS` ∪ `ROOT_HIDDEN`，文件必须在 `ROOT_FILES` ∪
`ROOT_HIDDEN`，否则违规并在 detail 里给出应去的目录。

`tests/test_arch_check.py` 有 6 例：未声明目录、未声明文件、已声明集合放行、
隐藏环境目录放行、已知名字给出去处、未知名字给出兜底提示。

尚未覆盖（记录在案，不假装已经解决）：`docs/` 内部的分层（`plans/`
`research/` `reports/`）不在本检查范围内；全库 18 条失效的相对链接也没有
机器在拦，需要另一条 `docs_links` 检查。
