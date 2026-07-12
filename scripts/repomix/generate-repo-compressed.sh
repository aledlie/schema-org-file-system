#!/usr/bin/env bash
# Runs repomix --compress and writes docs/repomix/repo-compressed.xml
set -euo pipefail

ROOT="${1:?Usage: $0 <root_dir> <output_file>}"
OUTPUT_FILE="${2:?Usage: $0 <root_dir> <output_file>}"

FORCE_COLOR=0 NO_COLOR=1 timeout 60 \
npx repomix "$ROOT" --compress ${REPOMIX_EXTRA_IGNORE:+--ignore "$REPOMIX_EXTRA_IGNORE"} -o "$OUTPUT_FILE" >/dev/null 2>&1