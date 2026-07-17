#!/usr/bin/env bash
set -euo pipefail

N=20
COMMITS=200
OUT="docs/repomix/gitlog-top${N}.txt"

mkdir -p "$(dirname "$OUT")"

# Paths excluded from the top-file ranking, sourced from the shared repomix
# config's `.diffSummary.ignore` (kept separate from `.ignore.customPatterns`,
# which the docs-only/lossless bundles rely on). Interpreted as case globs.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/repomix.config.json"
IGNORE_PATTERNS=()
if [[ -f "$CONFIG_FILE" ]]; then
  while IFS= read -r pattern; do
    [[ -n "$pattern" ]] && IGNORE_PATTERNS+=("$pattern")
  done < <(jq -r '.diffSummary.ignore // [] | .[]' "$CONFIG_FILE" 2>/dev/null || true)
fi

is_ignored() {
  local rel_path="$1" pattern
  for pattern in "${IGNORE_PATTERNS[@]}"; do
    # shellcheck disable=SC2254
    case "$rel_path" in
      $pattern) return 0 ;;
    esac
  done
  return 1
}

# Get Top-N tracked files by blob size (bytes) without xargs (macOS-safe)
TOP_FILES=()
while IFS= read -r f; do
  [[ -n "$f" ]] && TOP_FILES+=("$f")
done < <(
  git ls-files -z \
  | while IFS= read -r -d '' f; do
      is_ignored "$f" && continue
      sz="$(git cat-file -s ":$f" 2>/dev/null || echo 0)"
      printf '%s\t%s\n' "$sz" "$f"
    done \
  | sort -nr \
  | head -n "$N" \
  | cut -f2-
)

# Log: commit header + filenames (no statuses), only for those Top-N files
git log -n "$COMMITS" \
  --date=short \
  --pretty='format:%h %ad %s' \
  --name-only \
  -- "${TOP_FILES[@]}" \
| awk '
    NF==0 { print ""; next }
    /^[0-9a-f]{7,40} / { print; next }
    { print "  " $0 }
  ' > "$OUT"

echo "Wrote: $OUT"