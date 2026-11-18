#!/usr/bin/env python3
"""一次 Grok Build chat.completions 冒烟（走 ben.llm 路由）。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ben import config  # noqa: E402
from ben.llm import grok_build  # noqa: E402
from ben.llm.llm import call_model, client_for  # noqa: E402


def main() -> int:
    model = os.environ.get("BEN_MODEL") or "grok"
    os.environ.setdefault("BEN_MODEL", model)
    config.load_dotenv()

    slug = grok_build.subscription_model(model)
    if not slug:
        print(f"BEN_MODEL={model!r} is not a Grok Build id (use grok or grok/<slug>)")
        return 2
    if not grok_build.is_authenticated():
        print("not signed in — run: grok login")
        return 1

    client, resolved, info = client_for(model)
    print(f"provider={info.get('provider')} base={info.get('api_base')} model={resolved}")
    resp = call_model(
        [{"role": "user", "content": "Reply with exactly: pong"}],
        timeout=60,
        model=model,
        temperature=0,
    )
    text = (resp.choices[0].message.content or "").strip()
    print(text)
    return 0 if "pong" in text.lower() else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"smoke failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
