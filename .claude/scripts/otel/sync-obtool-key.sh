#!/bin/zsh
# Sync OBTOOL_API_KEY from Doppler to settings.json
# Run this after rotating keys or on shell startup

set -e

SETTINGS_FILE="$HOME/.claude/settings.json"

# Requires common.sh to be sourced first (provides doppler_get via load_doppler_cache)
if ! declare -f doppler_get >/dev/null 2>&1; then
  source "${SHELL_DIR:-$HOME/}functions.sh"
  load_doppler_cache
fi

KEY=$(doppler_get OBTOOL_API_KEY)

if [ -z "$KEY" ]; then
  echo "Error: Could not fetch OBTOOL_API_KEY from Doppler" >&2
  exit 1
fi

# Update settings.json using jq
if [ -f "$SETTINGS_FILE" ]; then
  HEADER_VALUE="Authorization=Bearer $KEY"

  # Use jq to update the value
  jq --arg header "$HEADER_VALUE" '.env.OTEL_EXPORTER_OTLP_HEADERS = $header' "$SETTINGS_FILE" > "${SETTINGS_FILE}.tmp" && \
    mv "${SETTINGS_FILE}.tmp" "$SETTINGS_FILE"

  echo "Updated OTEL_EXPORTER_OTLP_HEADERS in settings.json"
else
  echo "Error: $SETTINGS_FILE not found" >&2
  exit 1
fi
