"""`ben config` — report / validate the centralized configuration."""
from __future__ import annotations

import json
import os
import sys

from ben import config


def _mask_rows(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        shown = dict(row)
        shown["value"] = config.mask(row["key"], row["value"])
        del shown["secret"]
        out.append(shown)
    return out


def _print_table(rows: list[dict]) -> None:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["group"], []).append(row)
    width = max(len(r["key"]) for r in rows)
    dotenv = config._DOTENV_PATH
    if dotenv is not None:
        print(f"# loaded .env: {dotenv}")
    else:
        print("# no .env file found (environment variables only)")
    print(f"# precedence: real env > .env > default    "
          f"(template: .env.example)")
    for group in groups:
        print(f"\n[{group}]")
        for row in groups[group]:
            value = config.mask(row["key"], row["value"])
            default = row["default"]
            marker = "" if value == default or not default else \
                f"  (default: {default})"
            print(f"  {row['key'].ljust(width)}  =  {value!r}  "
                  f"[{row['source']}]{marker}")
            if row["desc"]:
                print(f"  {' ' * width}    # {row['desc']}")


def cmd_config(args) -> int:
    rows = config._effective_rows()
    problems = config.config_problems()

    if getattr(args, "json", False):
        payload = {
            "dotenv_path": str(config._DOTENV_PATH) if config._DOTENV_PATH else None,
            "values": _mask_rows(rows),
            "problems": problems,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if getattr(args, "check", False):
        for problem in problems:
            sys.stderr.write(f"ben config: {problem}\n")
        if problems:
            sys.stderr.write(
                f"\n{len(problems)} problem(s). Set the values in your environment "
                f"or copy .env.example to .env and edit it.\n"
            )
            return 1
        print("config ok")
        return 0

    _print_table(rows)
    if problems:
        print("\n[problems]")
        for problem in problems:
            print(f"  ! {problem}")
        print("(fix them in the environment or .env; `ben config --check` exits 1)")
    return 0
