#!/usr/bin/env python3
"""冒烟：主模型 (Grok Build) + 子模型 (BEN_FLASH_*)。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ben import config  # noqa: E402
from ben.llm.llm import call_model, client_for, flash_configured  # noqa: E402


def _ping(tier: str) -> str:
    client, model, info = client_for(tier=tier)
    print(f"[{tier}] provider={info.get('provider')} base={info.get('api_base')} model={model}")
    # kimi-k2.5 rejects temperature!=1; omit so provider default applies
    resp = call_model(
        [{"role": "user", "content": f"Reply with exactly: {tier}-ok"}],
        timeout=60,
        tier=tier,
    )
    text = (resp.choices[0].message.content or "").strip()
    print(f"[{tier}] reply: {text}")
    return text


def main() -> int:
    config.load_dotenv()
    print("problems:", config.config_problems())
    _ping("main")
    if not flash_configured():
        print("[flash] not configured — skip")
        return 0
    _ping("flash")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"smoke_tiers failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
