#!/usr/bin/env bash
# Regenerate the pdoc3 API docs that live in the docs/api submodule.
#
# PYTHONPATH must be src:scripts:. — the same value the Makefile uses:
#   - `src`     : inner modules use bare intra-package imports
#                 (e.g. `from cost_roi_calculator import ...`)
#   - `scripts` : several src/ modules do `from shared.x import y`, and
#                 shared/ lives under scripts/ (see CLAUDE.md). Without it pdoc
#                 dies on `ModuleNotFoundError: No module named 'shared'`.
#   - `.`       : keeps `src` importable as a package from the repo root.
#
# Requires pdoc3 (NOT the unrelated `pdoc` project, whose CLI takes `-o` and
# rejects `--html --force`). It is declared in the `dev` extra; a `pdoc` on
# PATH from another environment will be the wrong tool.
#
# The output tree (docs/api/src/) is a git submodule
# (integritystudio/schema-org-file-system-apidocs). After running this, commit
# and push inside docs/api, then commit the bumped gitlink in the parent.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ -f venv/bin/activate ]; then
  # shellcheck disable=SC1091
  source venv/bin/activate
fi

PYTHONPATH="src:scripts:.:${PYTHONPATH:-}" pdoc --html --force --output-dir docs/api src

echo
echo "Regenerated docs/api/src. To publish:"
echo "  git -C docs/api add -A && git -C docs/api commit -m 'docs: regenerate pdoc3 API docs' && git -C docs/api push"
echo "  git add docs/api && git commit -m 'chore(docs): bump docs/api submodule'"
