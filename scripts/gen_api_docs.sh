#!/usr/bin/env bash
# Regenerate the pdoc3 API docs that live in the docs/api submodule.
#
# src/ must be on PYTHONPATH: inner modules use bare intra-package imports
# (e.g. `from cost_roi_calculator import ...`) while the repo root keeps `src`
# importable as a package.
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

PYTHONPATH="src:${PYTHONPATH:-}" pdoc --html --force --output-dir docs/api src

echo
echo "Regenerated docs/api/src. To publish:"
echo "  git -C docs/api add -A && git -C docs/api commit -m 'docs: regenerate pdoc3 API docs' && git -C docs/api push"
echo "  git add docs/api && git commit -m 'chore(docs): bump docs/api submodule'"
