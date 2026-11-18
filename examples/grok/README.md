# Grok Build 示例

用 Cursor / Grok CLI 的订阅登录跑 ben 的 sdk 引擎，**不需要** `xai-` API key。

## 前置

```bash
grok login                          # 写入 ~/.grok/auth.json
# Cursor → Settings → Privacy → Privacy Mode (no training)
# Legacy (no storage) 会被代理拒绝
```

## 配置

```bash
cp examples/grok/env.example .env   # 或把其中几行并进已有 .env
ben config --check
```

- `BEN_MODEL=grok` → 等价 `grok/grok-4.6`
- `BEN_MODEL=grok/grok-4.6` → 指定 slug
- `xai/grok-*` **不是** Grok Build，走 `api.x.ai` + API key

## 冒烟

```bash
# 只查登录 / 刷新 token
python examples/grok/check_auth.py

# 一次 chat.completions（需 openai 包：bash scripts/install.sh --with-sdk）
python examples/grok/smoke.py
```

## 接进 ben 主流程

```bash
BEN_MODEL=grok BEN_ENGINE=auto ben dispatch reason --dry-run
```

实现位于 `ben/llm/grok_build.py`（鉴权）+ `ben/llm/llm.py`（client 路由）。
