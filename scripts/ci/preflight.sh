#!/usr/bin/env bash
# preflight — 本地一键闸门。CI 还没接上之前，这就是"测试失败禁止提交"的落点。
#
#   bash scripts/ci/preflight.sh          # 架构检查 + 全量测试
#   bash scripts/ci/preflight.sh --fast   # 只跑架构检查
#
# 退出码非 0 = 不要提交。
set -euo pipefail
cd "$(dirname "$0")/../.."

PY=${PYTHON:-}
if [ -z "$PY" ]; then
  # `python3` is not always the interpreter that has pytest (a managed/venv
  # python can shadow the system one). Pick the first that can import it.
  for cand in python3 python3.13 python3.12 python3.11 /usr/bin/python3; do
    if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import pytest' >/dev/null 2>&1; then
      PY=$cand
      break
    fi
  done
  PY=${PY:-python3}
fi

echo "== arch_check =="
"$PY" scripts/ci/arch_check.py

if [ "${1:-}" = "--fast" ]; then
  echo "(--fast: tests skipped)"
  exit 0
fi

echo
echo "== pytest =="
"$PY" -m pytest -q

echo
echo "== ruff =="
if command -v ruff >/dev/null 2>&1; then
  ruff check ben tests
elif "$PY" -c 'import ruff' >/dev/null 2>&1; then
  "$PY" -m ruff check ben tests
else
  # Local machines may lack ruff; GitHub Actions installs it (R-04/R-05).
  echo "ruff not installed — skipping locally (CI installs ruff)"
fi

echo
echo "== import-linter =="
if command -v lint-imports >/dev/null 2>&1; then
  lint-imports
elif "$PY" -c 'import importlinter' >/dev/null 2>&1; then
  "$PY" -m importlinter.cli
else
  echo "import-linter not installed — skipping locally (CI installs import-linter)"
fi

echo
echo "preflight: OK"
