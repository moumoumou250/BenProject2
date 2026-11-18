#!/usr/bin/env python3
"""打印 Grok Build 登录状态；必要时刷新 access token。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ben.llm import grok_build  # noqa: E402


def main() -> int:
    print(f"auth.json : {grok_build.AUTH_PATH}")
    print(f"proxy     : {grok_build.PROXY_BASE_URL}")
    print(f"version   : {grok_build.client_version()}")
    if not grok_build.is_authenticated():
        print("status    : NOT logged in — run: grok login")
        return 1
    record = grok_build.read_record() or {}
    print(f"expires_at: {record.get('expires_at', '?')}")
    try:
        token = grok_build.get_valid_token()
    except grok_build.GrokBuildAuthError as exc:
        print(f"status    : refresh failed — {exc}")
        return 1
    print(f"status    : ok (token …{token[-8:]})")
    print(f"headers   : {grok_build.client_headers()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
