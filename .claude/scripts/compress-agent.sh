#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "Usage: $0 <agent-dir> <output-filepath>" >&2
  echo "Example: $0 .claude/agents/ docs/repomix/agent-compressed.xml" >&2
  exit 1
fi

npx repomix "$1" --include "*.md" --no-default-patterns --compress \
  --no-file-summary --no-directory-structure -o "$2"
