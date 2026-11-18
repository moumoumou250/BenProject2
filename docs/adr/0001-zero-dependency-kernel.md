# 0001 内核零第三方依赖

- Status: accepted
- Date: 2026-11-18

## Context

`ben` 要在三处运行：本地开发机、比赛 CVM（常常无法装包、网络受限）、以及被
hook 每轮调用一次的短生命周期进程。任何模块级第三方依赖都会把这三处同时变成
安装问题；而 hook 的启动开销直接乘以对话轮数。

同时确实需要 `openai`/`httpx` 作为**可选** SDK——但那是能力，不是地基。

## Decision

`ben/` 下除 `ben/llm/sdk.py` 外，**模块级**导入只允许标准库与 `ben.*`。
需要第三方 SDK 的路径必须在函数内部惰性导入，且只能在 `ben/llm/` 下。

## Consequences

- 代价：惰性导入会让「sdk 未安装」的错误推迟到调用时才出现，因此该路径必须
  自带清晰的报错文案（`sdk.py` 已如此）。
- 收益：`pip install ben` 只需要一个解释器；hook 与 `ben status` 不被任何
  第三方包拖慢；比赛机器上 `git clone` 即用。
- 直接后果：P1 的启动优化不必再讨论「依赖太重」，只剩「包初始化太长」。

## Enforced-by

`scripts/ci/arch_check.py --check third_party`

判据：AST 扫描 `ben/**/*.py` 的 `Import` / `ImportFrom`；模块级导入的非标准库
模块名不在 allowlist 内即违规。函数内导入在 `ben/llm/` 下豁免（惰性可选依赖），
其余位置不豁免。
