#!/bin/bash
# Shared shell colors, log helpers, and path constants for scripts/

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

# Canonical paths
CLAUDE_DIR="${OTEL_CONFIG_DIR:-${CLAUDE_CONFIG_DIR:-$HOME/.claude}}"
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$HOME/dev}"
TELEMETRY_DIR="${TELEMETRY_DIR:-$HOME/.claude-history/telemetry}"

# Logging helpers
log_info() {
  echo -e "${BLUE}ℹ${NC} $1"
}

log_success() {
  echo -e "${GREEN}✓${NC} $1"
}

log_warn() {
  echo -e "${YELLOW}⚠${NC} $1"
}

log_error() {
  echo -e "${RED}✗${NC} $1"
}

# JSON validation via jq
# Usage: validate_json [-q] <file> [label]
#   -q  quiet mode: suppress output on success, still print on failure
validate_json() {
  local quiet=false
  if [ "$1" = "-q" ] || [ "$1" = "--quiet" ]; then
    quiet=true
    shift
  fi
  local file="$1"
  local label="${2:-$file}"
  if [ ! -f "$file" ]; then
    echo -e "  ${RED}✗${NC} $label (missing)"
    return 1
  fi
  if jq empty "$file" 2>/dev/null; then
    $quiet || echo -e "  ${GREEN}✓${NC} $label (valid JSON)"
    return 0
  else
    echo -e "  ${RED}✗${NC} $label (invalid JSON)"
    return 1
  fi
}

# Component counting — sets CC_* prefixed variables to avoid caller collisions
count_components() {
  CC_skills=$(find "$CLAUDE_DIR/skills" -name "*.md" 2>/dev/null | wc -l | tr -d ' ')
  CC_hooks=$(find "$CLAUDE_DIR/hooks" -name "*.sh" 2>/dev/null | wc -l | tr -d ' ')
  CC_agents=$(find "$CLAUDE_DIR/agents" -name "*.md" 2>/dev/null | wc -l | tr -d ' ')
  CC_commands=$(find "$CLAUDE_DIR/commands" -name "*.md" 2>/dev/null | wc -l | tr -d ' ')
  CC_active=$(find "$PROJECT_DIR/active" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
  CC_archive=$(find "$PROJECT_DIR/archive" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
}

# Backup file manifest
BACKUP_FILES=(
  "settings.json"
  "skills/skill-rules.json"
  ".envrc"
  "package.json"
)

# Format backup timestamp YYYYMMDD_HHMMSS -> human-readable
format_backup_timestamp() {
  local backup_name="$1"
  local backup_date="${backup_name:0:8}"
  local backup_time="${backup_name:9:6}"
  local formatted_date
  local formatted_time
  formatted_date=$(echo "$backup_date" | sed 's/\(....\)\(..\)\(..\)/\1-\2-\3/')
  formatted_time=$(echo "$backup_time" | sed 's/\(..\)\(..\)\(..\)/\1:\2:\3/')
  echo "$formatted_date $formatted_time"
}
