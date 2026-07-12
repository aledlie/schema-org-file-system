#!/bin/zsh
# Tests for OTEL environment and script configuration
# Run: zsh scripts/otel/otel-config.test.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PASS=0
FAIL=0
ERRORS=()

pass() { ((PASS++)); printf "  \033[32mPASS\033[0m %s\n" "$1"; }
fail() { ((FAIL++)); ERRORS+=("$1: $2"); printf "  \033[31mFAIL\033[0m %s — %s\n" "$1" "$2"; }

# --- sync-obtool-key.sh ---
echo "sync-obtool-key.sh"

# T1: shebang is zsh (not bash — macOS bash 3.2 lacks declare -gA)
SHEBANG=$(head -1 "$SCRIPT_DIR/sync-obtool-key.sh")
[[ "$SHEBANG" == "#!/bin/zsh" ]] && pass "shebang is #!/bin/zsh" \
  || fail "shebang is #!/bin/zsh" "got: $SHEBANG"

# T2: jq transform produces correct header format
TMPFILE=$(mktemp)
cat > "$TMPFILE" <<'JSON'
{"env":{"OTEL_EXPORTER_OTLP_HEADERS":"old-value"}}
JSON
RESULT=$(jq --arg header "Authorization=Bearer test-key-123" \
  '.env.OTEL_EXPORTER_OTLP_HEADERS = $header' "$TMPFILE")
EXPECTED_HEADER=$(echo "$RESULT" | jq -r '.env.OTEL_EXPORTER_OTLP_HEADERS')
[[ "$EXPECTED_HEADER" == "Authorization=Bearer test-key-123" ]] && pass "jq transform sets Authorization=Bearer header" \
  || fail "jq transform sets Authorization=Bearer header" "got: $EXPECTED_HEADER"
rm -f "$TMPFILE"

# T3: jq transform preserves other keys
TMPFILE=$(mktemp)
cat > "$TMPFILE" <<'JSON'
{"env":{"OTEL_SERVICE_NAME":"claude-code-hooks","OTEL_EXPORTER_OTLP_HEADERS":"old"}}
JSON
RESULT=$(jq --arg header "Authorization=Bearer new" \
  '.env.OTEL_EXPORTER_OTLP_HEADERS = $header' "$TMPFILE")
SERVICE_NAME=$(echo "$RESULT" | jq -r '.env.OTEL_SERVICE_NAME')
[[ "$SERVICE_NAME" == "claude-code-hooks" ]] && pass "jq transform preserves other env keys" \
  || fail "jq transform preserves other env keys" "got: $SERVICE_NAME"
rm -f "$TMPFILE"

# T4: script sources functions.sh from DOTFILES_DIR
grep -q 'source.*DOTFILES_DIR.*shell/functions.sh' "$SCRIPT_DIR/sync-obtool-key.sh" \
  && pass "sources functions.sh from DOTFILES_DIR" \
  || fail "sources functions.sh from DOTFILES_DIR" "pattern not found"

# T5: script exits on missing key
grep -q 'exit 1' "$SCRIPT_DIR/sync-obtool-key.sh" \
  && pass "exits 1 on error conditions" \
  || fail "exits 1 on error conditions" "no exit 1 found"

# --- test-otlp.mjs ---
echo ""
echo "test-otlp.mjs"

# T6: default endpoint is integritystudio.ai (not localhost or obtool.cloud)
DEFAULT_EP=$(grep -o "|| '[^']*'" "$SCRIPT_DIR/test-otlp.mjs" | head -1 | tr -d "||' ")
[[ "$DEFAULT_EP" == "https://ingest.integritystudio.ai" ]] && pass "default endpoint is ingest.integritystudio.ai" \
  || fail "default endpoint is ingest.integritystudio.ai" "got: $DEFAULT_EP"

# T7: uses OTEL_EXPORTER_OTLP_ENDPOINT env var
grep -q 'OTEL_EXPORTER_OTLP_ENDPOINT' "$SCRIPT_DIR/test-otlp.mjs" \
  && pass "reads OTEL_EXPORTER_OTLP_ENDPOINT env var" \
  || fail "reads OTEL_EXPORTER_OTLP_ENDPOINT env var" "env var not referenced"

# T8: uses Bearer auth header format
grep -q 'Bearer.*apiKey' "$SCRIPT_DIR/test-otlp.mjs" \
  && pass "uses Bearer token auth" \
  || fail "uses Bearer token auth" "Bearer pattern not found"

# --- .zshrc ---
echo ""
echo ".zshrc"

ZSHRC="$HOME/.zshrc"

# T9: no duplicate CLAUDE_ exports
DUPES=$(grep -o 'export CLAUDE_[A-Z_]*=' "$ZSHRC" | sort | uniq -d)
[[ -z "$DUPES" ]] && pass "no duplicate CLAUDE_ exports" \
  || fail "no duplicate CLAUDE_ exports" "duplicates: $DUPES"

# T10: OTEL_CONFIG_DIR is set
grep -q 'export OTEL_CONFIG_DIR=' "$ZSHRC" \
  && pass "OTEL_CONFIG_DIR is exported" \
  || fail "OTEL_CONFIG_DIR is exported" "not found"

# T11: sync-obtool-key invocation exists with throttle
grep -q 'sync-obtool-key.sh' "$ZSHRC" \
  && pass "sync-obtool-key.sh invoked on shell startup" \
  || fail "sync-obtool-key.sh invoked on shell startup" "not found"

# T12: sync throttle uses stamp file
grep -q '.sync-obtool-key.stamp' "$ZSHRC" \
  && pass "sync throttled via stamp file" \
  || fail "sync throttled via stamp file" "stamp pattern not found"

# --- settings.json ---
echo ""
echo "settings.json"

SETTINGS="$REPO_ROOT/settings.json"

# T13: endpoint in settings.json matches integritystudio.ai
SETTINGS_EP=$(jq -r '.env.OTEL_EXPORTER_OTLP_ENDPOINT' "$SETTINGS")
[[ "$SETTINGS_EP" == "https://ingest.integritystudio.ai" ]] && pass "settings.json endpoint is ingest.integritystudio.ai" \
  || fail "settings.json endpoint is ingest.integritystudio.ai" "got: $SETTINGS_EP"

# T14: OTLP headers use Authorization=Bearer format
SETTINGS_HDR=$(jq -r '.env.OTEL_EXPORTER_OTLP_HEADERS' "$SETTINGS")
[[ "$SETTINGS_HDR" == Authorization=Bearer* ]] && pass "settings.json headers use Authorization=Bearer format" \
  || fail "settings.json headers use Authorization=Bearer format" "got: $SETTINGS_HDR"

# T15: protocol is http/protobuf
SETTINGS_PROTO=$(jq -r '.env.OTEL_EXPORTER_OTLP_PROTOCOL' "$SETTINGS")
[[ "$SETTINGS_PROTO" == "http/protobuf" ]] && pass "settings.json protocol is http/protobuf" \
  || fail "settings.json protocol is http/protobuf" "got: $SETTINGS_PROTO"

# --- Endpoint consistency across current-state docs ---
echo ""
echo "endpoint consistency (no stale obtool.cloud in current-state files)"

CURRENT_DOCS=(
  "$REPO_ROOT/CLAUDE.md"
  "$REPO_ROOT/README.md"
  "$REPO_ROOT/settings.json"
  "$REPO_ROOT/docs/observability-framework-current.md"
  "$REPO_ROOT/docs/context-management-current.md"
  "$REPO_ROOT/hooks/CONFIG.md"
  "$REPO_ROOT/hooks/PERFORMANCE_MONITORING.md"
  "$REPO_ROOT/hooks/lib/langtrace.ts"
  "$REPO_ROOT/scripts/otel/test-otlp.mjs"
  "$REPO_ROOT/scripts/otel/sync-obtool-key.sh"
  "$REPO_ROOT/mcp-servers/observability-toolkit/docs/integrations/integrations.md"
  "$REPO_ROOT/mcp-servers/observability-toolkit/.github/workflows/publish.yml"
)

for f in "${CURRENT_DOCS[@]}"; do
  BASENAME="${f#$REPO_ROOT/}"
  if [[ ! -f "$f" ]]; then
    fail "$BASENAME: no stale obtool.cloud" "file not found"
    continue
  fi
  if grep -q 'ingest\.us\.obtool\.cloud' "$f"; then
    fail "$BASENAME: no stale obtool.cloud" "still references ingest.us.obtool.cloud"
  else
    pass "$BASENAME: no stale obtool.cloud"
  fi
done

# --- Summary ---
echo ""
TOTAL=$((PASS + FAIL))
printf "Results: %d/%d passed" "$PASS" "$TOTAL"
if ((FAIL > 0)); then
  printf " (\033[31m%d failed\033[0m)\n" "$FAIL"
  echo ""
  echo "Failures:"
  for e in "${ERRORS[@]}"; do
    printf "  - %s\n" "$e"
  done
  exit 1
else
  printf " \033[32m(all passed)\033[0m\n"
fi
