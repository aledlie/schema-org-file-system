#!/bin/zsh
# E2E test: verify traces and metrics reach ingest.integritystudio.ai
# Run: zsh scripts/otel/test-otlp-e2e.test.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PASS=0
FAIL=0
ERRORS=()

pass() { ((PASS++)); printf "  \033[32mPASS\033[0m %s\n" "$1"; }
fail() { ((FAIL++)); ERRORS+=("$1: $2"); printf "  \033[31mFAIL\033[0m %s — %s\n" "$1" "$2"; }

ENDPOINT="https://ingest.integritystudio.ai"
AUTH_HEADER=$(jq -r '.env.OTEL_EXPORTER_OTLP_HEADERS' "$REPO_ROOT/settings.json")
# Extract "Bearer <key>" from "Authorization=Bearer <key>"
BEARER_TOKEN="${AUTH_HEADER#Authorization=}"

echo "endpoint connectivity"

# T1: health endpoint responds 200
HEALTH_BODY=$(curl -s --max-time 10 "$ENDPOINT/health" 2>/dev/null || echo "")
HEALTH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$ENDPOINT/health" 2>/dev/null || echo "000")
[[ "$HEALTH_STATUS" == "200" ]] && pass "GET /health returns 200" \
  || fail "GET /health returns 200" "got HTTP $HEALTH_STATUS"

# T2: health response has status field = "ok"
HEALTH_ST=$(echo "$HEALTH_BODY" | jq -r '.status' 2>/dev/null)
[[ "$HEALTH_ST" == "ok" ]] && pass "GET /health status is ok" \
  || fail "GET /health status is ok" "got: $HEALTH_ST"

# T3: health response includes dependency checks
HEALTH_DEPS=$(echo "$HEALTH_BODY" | jq -r '.dependencies | keys[]' 2>/dev/null | sort | tr '\n' ',')
[[ "$HEALTH_DEPS" == *"auth"* && "$HEALTH_DEPS" == *"dedup"* && "$HEALTH_DEPS" == *"r2"* ]] \
  && pass "GET /health reports r2, auth, dedup dependencies" \
  || fail "GET /health reports r2, auth, dedup dependencies" "got: $HEALTH_DEPS"

# T4: all dependencies are healthy
UNHEALTHY=$(echo "$HEALTH_BODY" | jq -r '.dependencies | to_entries[] | select(.value != "healthy") | .key' 2>/dev/null)
[[ -z "$UNHEALTHY" ]] && pass "GET /health all dependencies healthy" \
  || fail "GET /health all dependencies healthy" "unhealthy: $UNHEALTHY"

# T5: health does not require auth
HEALTH_NOAUTH=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$ENDPOINT/health" 2>/dev/null || echo "000")
[[ "$HEALTH_NOAUTH" != "401" && "$HEALTH_NOAUTH" != "403" ]] \
  && pass "GET /health does not require auth" \
  || fail "GET /health does not require auth" "got HTTP $HEALTH_NOAUTH"

# T6: unauthenticated POST returns 401
UNAUTH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
  -X POST "$ENDPOINT/v1/traces" \
  -H "Content-Type: application/x-protobuf" \
  -d "" 2>/dev/null || echo "000")
[[ "$UNAUTH_STATUS" == "401" ]] && pass "POST /v1/traces without auth returns 401" \
  || fail "POST /v1/traces without auth returns 401" "got HTTP $UNAUTH_STATUS"

# T3: authenticated POST is accepted (non-401, non-000)
AUTH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
  -X POST "$ENDPOINT/v1/traces" \
  -H "Content-Type: application/x-protobuf" \
  -H "Authorization: $BEARER_TOKEN" \
  -d "" 2>/dev/null || echo "000")
# Accept 200 or 400 (empty body is invalid protobuf but auth passed)
if [[ "$AUTH_STATUS" == "200" || "$AUTH_STATUS" == "400" ]]; then
  pass "POST /v1/traces with auth passes authentication (HTTP $AUTH_STATUS)"
else
  fail "POST /v1/traces with auth passes authentication" "got HTTP $AUTH_STATUS (expected 200 or 400)"
fi

echo ""
echo "test-otlp.mjs end-to-end"

# T4: test-otlp.mjs sends a trace successfully
OUTPUT=$(node "$SCRIPT_DIR/test-otlp.mjs" 2>&1)
EXIT_CODE=$?
if [[ $EXIT_CODE -eq 0 ]] && echo "$OUTPUT" | grep -q "Trace sent successfully"; then
  pass "test-otlp.mjs completes without error"
else
  fail "test-otlp.mjs completes without error" "exit=$EXIT_CODE output=$(echo "$OUTPUT" | tail -3)"
fi

# T5: test-otlp.mjs picks up auth from OTEL_EXPORTER_OTLP_HEADERS
echo "$OUTPUT" | grep -q "Auth:" \
  && pass "test-otlp.mjs uses auth credentials" \
  || fail "test-otlp.mjs uses auth credentials" "no Auth: line in output"

# T6: test-otlp.mjs targets correct endpoint
echo "$OUTPUT" | grep -q "ingest.integritystudio.ai" \
  && pass "test-otlp.mjs targets ingest.integritystudio.ai" \
  || fail "test-otlp.mjs targets ingest.integritystudio.ai" "endpoint not in output"

echo ""
echo "metrics endpoint"

# T10: unauthenticated POST to /v1/metrics returns 401
METRICS_UNAUTH=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
  -X POST "$ENDPOINT/v1/metrics" \
  -H "Content-Type: application/x-protobuf" \
  -d "" 2>/dev/null || echo "000")
[[ "$METRICS_UNAUTH" == "401" ]] && pass "POST /v1/metrics without auth returns 401" \
  || fail "POST /v1/metrics without auth returns 401" "got HTTP $METRICS_UNAUTH"

# T11: authenticated POST to /v1/metrics is accepted
METRICS_AUTH=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
  -X POST "$ENDPOINT/v1/metrics" \
  -H "Content-Type: application/x-protobuf" \
  -H "Authorization: $BEARER_TOKEN" \
  -d "" 2>/dev/null || echo "000")
if [[ "$METRICS_AUTH" == "200" || "$METRICS_AUTH" == "400" ]]; then
  pass "POST /v1/metrics with auth passes authentication (HTTP $METRICS_AUTH)"
else
  fail "POST /v1/metrics with auth passes authentication" "got HTTP $METRICS_AUTH (expected 200 or 400)"
fi

# T12: test-metrics.mjs sends a metric successfully
METRICS_OUTPUT=$(node "$SCRIPT_DIR/test-metrics.mjs" 2>&1)
METRICS_EXIT=$?
if [[ $METRICS_EXIT -eq 0 ]] && echo "$METRICS_OUTPUT" | grep -q "Metric sent successfully"; then
  pass "test-metrics.mjs completes without error"
else
  fail "test-metrics.mjs completes without error" "exit=$METRICS_EXIT output=$(echo "$METRICS_OUTPUT" | tail -3)"
fi

# T13: test-metrics.mjs picks up auth
echo "$METRICS_OUTPUT" | grep -q "Auth:" \
  && pass "test-metrics.mjs uses auth credentials" \
  || fail "test-metrics.mjs uses auth credentials" "no Auth: line in output"

# T14: test-metrics.mjs targets correct endpoint
echo "$METRICS_OUTPUT" | grep -q "ingest.integritystudio.ai" \
  && pass "test-metrics.mjs targets ingest.integritystudio.ai" \
  || fail "test-metrics.mjs targets ingest.integritystudio.ai" "endpoint not in output"

echo ""
echo "logs endpoint"

# T15: unauthenticated POST to /v1/logs returns 401
LOGS_UNAUTH=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
  -X POST "$ENDPOINT/v1/logs" \
  -H "Content-Type: application/x-protobuf" \
  -d "" 2>/dev/null || echo "000")
[[ "$LOGS_UNAUTH" == "401" ]] && pass "POST /v1/logs without auth returns 401" \
  || fail "POST /v1/logs without auth returns 401" "got HTTP $LOGS_UNAUTH"

# T16: authenticated POST to /v1/logs is accepted
LOGS_AUTH=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
  -X POST "$ENDPOINT/v1/logs" \
  -H "Content-Type: application/x-protobuf" \
  -H "Authorization: $BEARER_TOKEN" \
  -d "" 2>/dev/null || echo "000")
if [[ "$LOGS_AUTH" == "200" || "$LOGS_AUTH" == "400" ]]; then
  pass "POST /v1/logs with auth passes authentication (HTTP $LOGS_AUTH)"
else
  fail "POST /v1/logs with auth passes authentication" "got HTTP $LOGS_AUTH (expected 200 or 400)"
fi

# T17: test-logs.mjs sends a log successfully
LOGS_OUTPUT=$(node "$SCRIPT_DIR/test-logs.mjs" 2>&1)
LOGS_EXIT=$?
if [[ $LOGS_EXIT -eq 0 ]] && echo "$LOGS_OUTPUT" | grep -q "Log sent successfully"; then
  pass "test-logs.mjs completes without error"
else
  fail "test-logs.mjs completes without error" "exit=$LOGS_EXIT output=$(echo "$LOGS_OUTPUT" | tail -3)"
fi

# T18: test-logs.mjs picks up auth
echo "$LOGS_OUTPUT" | grep -q "Auth:" \
  && pass "test-logs.mjs uses auth credentials" \
  || fail "test-logs.mjs uses auth credentials" "no Auth: line in output"

# T19: test-logs.mjs targets correct endpoint
echo "$LOGS_OUTPUT" | grep -q "ingest.integritystudio.ai" \
  && pass "test-logs.mjs targets ingest.integritystudio.ai" \
  || fail "test-logs.mjs targets ingest.integritystudio.ai" "endpoint not in output"

echo ""
echo "hooks OTEL exporter config"

# T7: hooks otel.ts uses protobuf exporter matching endpoint requirements
grep -q "exporter-trace-otlp-http" "$REPO_ROOT/hooks/lib/otel.ts" \
  && pass "hooks/lib/otel.ts imports OTLP HTTP exporter" \
  || fail "hooks/lib/otel.ts imports OTLP HTTP exporter" "import not found"

# T8: OTEL_EXPORTER_OTLP_PROTOCOL is set to http/protobuf in settings
PROTO=$(jq -r '.env.OTEL_EXPORTER_OTLP_PROTOCOL' "$REPO_ROOT/settings.json")
[[ "$PROTO" == "http/protobuf" ]] && pass "settings.json protocol is http/protobuf" \
  || fail "settings.json protocol is http/protobuf" "got: $PROTO"

# T9: test-otlp.mjs uses proto exporter (not JSON http)
grep -q "exporter-trace-otlp-proto" "$SCRIPT_DIR/test-otlp.mjs" \
  && pass "test-otlp.mjs uses protobuf exporter" \
  || fail "test-otlp.mjs uses protobuf exporter" "still using JSON exporter"

# T18: hooks otel.ts configures metric exporter
grep -q "OTLPMetricExporter" "$REPO_ROOT/hooks/lib/otel.ts" \
  && pass "hooks/lib/otel.ts configures OTLPMetricExporter" \
  || fail "hooks/lib/otel.ts configures OTLPMetricExporter" "not found"

# T19: hooks otel.ts configures log exporter
grep -q "OTLPLogExporter" "$REPO_ROOT/hooks/lib/otel.ts" \
  && pass "hooks/lib/otel.ts configures OTLPLogExporter" \
  || fail "hooks/lib/otel.ts configures OTLPLogExporter" "not found"

# T20: settings.json enables metric exporter
METRICS_EXP=$(jq -r '.env.OTEL_METRICS_EXPORTER' "$REPO_ROOT/settings.json")
[[ "$METRICS_EXP" == "otlp" ]] && pass "settings.json OTEL_METRICS_EXPORTER=otlp" \
  || fail "settings.json OTEL_METRICS_EXPORTER=otlp" "got: $METRICS_EXP"

# T21: settings.json enables log exporter
LOGS_EXP=$(jq -r '.env.OTEL_LOGS_EXPORTER' "$REPO_ROOT/settings.json")
[[ "$LOGS_EXP" == "otlp" ]] && pass "settings.json OTEL_LOGS_EXPORTER=otlp" \
  || fail "settings.json OTEL_LOGS_EXPORTER=otlp" "got: $LOGS_EXP"

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
