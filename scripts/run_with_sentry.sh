#!/bin/bash
# Run file organizer with Sentry error tracking via Doppler
#
# Usage:
#   ./scripts/run_with_sentry.sh --dry-run --limit 100
#   ./scripts/run_with_sentry.sh --base-path ~/Documents --sources ~/Downloads

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Get Sentry DSN from Doppler if not already set
if [ -z "$FILE_SYSTEM_SENTRY_DSN" ]; then
    FILE_SYSTEM_SENTRY_DSN="$(doppler secrets get FILE_SYSTEM_SENTRY_DSN --project integrity-studio --config prd --plain 2>/dev/null)" || true
fi

if [ -z "$FILE_SYSTEM_SENTRY_DSN" ]; then
    echo "Warning: Could not get FILE_SYSTEM_SENTRY_DSN from Doppler. Running without error tracking."
else
    export FILE_SYSTEM_SENTRY_DSN
fi

# Activate virtual environment if not already active
if [ -z "$VIRTUAL_ENV" ]; then
    source "$PROJECT_DIR/venv/bin/activate"
fi

# Run the organizer with all passed arguments
python3 "$PROJECT_DIR/scripts/file_organizer_content_based.py" "$@"
