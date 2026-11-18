#!/usr/bin/env bash
# install.sh — install the `ben` CLI + the `ben-setup` project skill.
#
# This installer does NOT touch ~/.claude/settings.json and does NOT register
# any global hooks. The fact-graph is strictly per-project opt-in: you opt a
# project in by running `ben setup` (or the /ben-setup skill) inside that
# project, which writes ./.claude/settings.json + .ben/ there.
#
# Usage:
#   bash scripts/install.sh              # install CLI + project skill (recommended)
#   bash scripts/install.sh --cli-only   # just symlink ben, skip the skill
#   bash scripts/install.sh --with-sdk   # also create .venv and pip-install openai
#   bash scripts/install.sh --uninstall  # remove the symlink + the skill
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SRC="${REPO_ROOT}/bin/ben"
mode="${1:-install}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "install: python3 is required (kernel is stdlib; openai is optional via --with-sdk)." >&2
  exit 1
fi

if [[ "$mode" == "--with-sdk" ]]; then
  VENV="${REPO_ROOT}/.venv"
  if [[ ! -d "$VENV" ]]; then
    python3 -m venv "$VENV"
  fi
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
  pip install -q 'openai>=1.40,<3'
  echo "installed openai into $VENV"
  mode="install"
fi

# --- uninstall -------------------------------------------------------------
if [[ "$mode" == "--uninstall" ]]; then
  rm -f "${HOME}/.local/bin/ben"
  echo "removed ~/.local/bin/ben"
  if [[ -e "${HOME}/.claude/skills/ben-setup" || -L "${HOME}/.claude/skills/ben-setup" ]]; then
    rm -f "${HOME}/.claude/skills/ben-setup"
    echo "removed ~/.claude/skills/ben-setup"
  fi
  echo "uninstalled."
  echo "(Project-level .ben/ graphs and ./.claude/settings.json in your projects are untouched."
  echo " Remove them per-project with: cd <project> && ben teardown --purge)"
  exit 0
fi

# --- install CLI -----------------------------------------------------------
if [[ ! -f "$SRC" ]]; then
  echo "install: bin/ben launcher not found at $SRC" >&2; exit 1
fi

DEST_DIR="${HOME}/.local/bin"
mkdir -p "$DEST_DIR"
if [[ -e "$DEST_DIR/ben" || -L "$DEST_DIR/ben" ]]; then
  rm -f "$DEST_DIR/ben"
fi
ln -s "$SRC" "$DEST_DIR/ben"
chmod +x "$SRC"
echo "installed: ben -> $DEST_DIR/ben"

case ":$PATH:" in
  *":$DEST_DIR:"*) ;;
  *) echo "install: NOTE — $DEST_DIR is not on your PATH. Add:" >&2
     echo "    export PATH=\"$DEST_DIR:\$PATH\"" >&2 ;;
esac

"$DEST_DIR/ben" --version >/dev/null && echo "  (ben works)"

if [[ "$mode" == "--cli-only" ]]; then
  echo "(--cli-only: skipping the /ben-setup skill)"
  exit 0
fi

# --- install the project skill --------------------------------------------
SKILLS_DIR="${HOME}/.claude/skills"
mkdir -p "$SKILLS_DIR"
SKILL_LINK="$SKILLS_DIR/ben-setup"
if [[ -e "$SKILL_LINK" || -L "$SKILL_LINK" ]]; then
  rm -f "$SKILL_LINK"
fi
ln -s "${REPO_ROOT}/skills/ben-setup" "$SKILL_LINK"
echo "installed: /ben-setup skill -> $SKILL_LINK"

cat <<'NOTE'

Done. Nothing global was configured — the fact-graph is per-project opt-in.

To opt a project IN (run inside the project dir):
  ben setup --goal "your one-line goal" --agents
  #  ↑ creates ./.ben/  +  registers hooks in ./.claude/settings.json  +  AGENTS.md

Or just invoke the skill from inside Claude Code:
  /ben-setup <your goal>

After that, every turn in that project auto-injects the current graph state,
and you can drive it with `ben dispatch reason` / `ben auto`.

To opt a project OUT:
  cd <project> && ben teardown           # removes hooks + AGENTS.md (keeps .ben/)
  cd <project> && ben teardown --purge   # also deletes the graph data
NOTE
