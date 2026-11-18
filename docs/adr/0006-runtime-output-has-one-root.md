# 0006 运行时输出只有一个根

- Status: accepted
- Date: 2026-11-18

## Context

`ben` 在运行时会写很多非源码文件：worker 注册表（`workers.json` + `.lock`）、
每个 worker 的日志尾巴、PTY console 的 socket 目录、`ben view` 的 HTML 快照、
以及每个挑战一份 `.ben/` 图。

问题不在「有这些文件」，在**每个调用点自己决定写哪里**。于是同一个仓库根上
先后长出了 `runs/`、`logs/`、`console/`、`workers.json`、`ben-graph.html`，
再加上一次靶场评估留下的 `recon/`、`jsscan/`、`h.txt`——最终 3.9 MB 生成物
里 2.7 MB 进了 git 索引，其中包含靶机 IP、KeePass 库、订单 PDF 与答案摘要。

三条具体成因，都能指出行号：

1. `ben/cli.py` 三个子命令的 `--root` 默认值是字面量 `"runs"`；
2. `ben/runtime/console.py:24` 把 socket 目录建在 `<base>/console`，
   `_log_path` 建在 `<base>/logs`——base 是仓库根时，两者都落在源码旁边；
3. `ben/web/view.py` 的快照写在 `.ben` 同级，store 在仓库根写出的就是
   `ben-graph.html`。

## Decision

**运行时产生的一切写入都在 `<base>/<runtime>/` 之下，默认 `<runtime> = runs`。**

- 目录名只在 `ben/core/paths.py:DEFAULT_RUNTIME_DIR` 出现一次，可用
  `BEN_RUNTIME_DIR` 覆盖（已在 `ben/config.py:ENV_SPECS` 登记）。
- 调用点不得自己拼路径，只能用 `paths.runtime_root()` /
  `paths.output_dir()` / `paths.logs_dir()` / `paths.snapshot_file()`。
- `output_dir()` 对已经在 runtime 树内的路径原样返回，避免
  `runs/<name>/runs/` 这种嵌套。
- 读取方（dashboard 轮询）不得 mkdir；只有 `ensure_output_dir()` 与
  `console_root()` 建目录。

**两件事不属于运行时输出，位置不变：**

- `.ben/` —— 事实图是「项目数据」，是这个工具存在的目的，要跟着项目走；
  塞进 `runs/` 会让 `ben status` 在自己的目录里找不到图。
- `lab/` —— 归档的评估素材，代码永不写入，人工管理。它在 `.gitignore` 里，
  但索引里已跟踪的文件必须先 `git rm -r --cached` 才生效。

## Consequences

- 代价：`fleet.json` 的 `root` 语义从「相对 base 的目录名」收紧为「必须是
  runtime 目录名或显式路径」；老配置写了绝对路径仍然工作，写 `runs/runs`
  不再被自动纠正。
- 收益：`.gitignore` 一行 `/runs/` 覆盖全部生成物；换布局只改一个常量；
  一次性脚本不会再往仓库根扔文件。
- 未覆盖：`/tmp` 里的临时文件（`probe.sh` 的 `/tmp/b.txt` 之类）不属于产物，
  不在本决策范围内。

## Enforced-by

`scripts/ci/arch_check.py --check runtime_paths`，两半：

1. `ben/` 下任何模块（除 `ben/core/paths.py`）出现字面量 `"runs"` 或以
   `"runs/"` 开头的常量 → 违规，报错信息直接给出应改用的函数；
2. `.gitignore` 里没有 `/runs/` → 违规（生成物会变成提交候选）。

`tests/test_paths.py` 另有一份等价的单向断言，跑得更快，且钉住
`BEN_RUNTIME_DIR` 的越界值（含 `/`、`..`）必须回落到默认值。
