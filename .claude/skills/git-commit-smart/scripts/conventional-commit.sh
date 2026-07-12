#!/usr/bin/env bash
set -euo pipefail

# conventional-commit.sh
# Analyzes staged/unstaged changes, classifies files into groups, and creates
# one Conventional Commit per group in order: source → config → docs.
#
# Usage:
#   ./conventional-commit.sh
#   ./conventional-commit.sh --all       # git add -A before analysis
#   ./conventional-commit.sh --dry-run   # print commit messages only, no commits
#
# This script is fully non-interactive: it never prompts for confirmation and
# commits each group automatically. Use --dry-run to preview without committing.

ADD_ALL=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --all)     ADD_ALL=true;  shift ;;
    --dry-run) DRY_RUN=true;  shift ;;
    --yes)     shift ;;  # no-op: kept for backward compatibility (always non-interactive)
    -h|--help) sed -n '1,20p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------
require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 1; }
}
require_cmd git
require_cmd mktemp

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Not inside a git repository." >&2
  exit 1
fi

GIT_ROOT="$(git rev-parse --show-toplevel)"
cd "$GIT_ROOT"

if $ADD_ALL; then
  git add -A
fi

# ---------------------------------------------------------------------------
# Collect all changed files (staged + unstaged + untracked)
# ---------------------------------------------------------------------------
ALL_FILES=()

_add_file() {
  local f="$1"
  [[ -z "$f" ]] && return
  # Skip files matched by .gitignore (belt-and-suspenders: git status already
  # respects .gitignore, but submodule boundaries and nested .gitignore files
  # can cause edge cases where ignored paths leak through)
  if git check-ignore -q -- "$f" 2>/dev/null; then
    return
  fi
  # Dedup without associative arrays for bash 3.2 compat: check array membership
  local existing
  for existing in "${ALL_FILES[@]+"${ALL_FILES[@]}"}"; do
    [[ "$existing" == "$f" ]] && return
  done
  ALL_FILES+=("$f")
}

while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  local_file="${line:3}"
  _add_file "$local_file"
done < <(git status --short)

if [[ ${#ALL_FILES[@]} -eq 0 ]]; then
  echo "No changes detected." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Guardrail: block sensitive files (Step 2)
# ---------------------------------------------------------------------------
SENSITIVE_PATTERNS=(
  '.env' '.env.*' 'credentials.*' '*.pem' '*.key' 'id_rsa' 'id_rsa*'
  '*.p12' 'token.json' '*secret*' 'service-account*.json'
)

# Paths (relative to repo root) that match a sensitive pattern by name but are
# verified not to contain secrets — e.g. loader scripts, docs about secrets.
SENSITIVE_ALLOWLIST=(
  'shell/doppler-secrets.sh'
  'shell/zsh/doppler-secrets.zsh'
)

is_sensitive() {
  local path="$1"
  for allowed in "${SENSITIVE_ALLOWLIST[@]}"; do
    [[ "$path" == "$allowed" ]] && return 1
  done
  local base_lower
  base_lower="$(echo "${path##*/}" | tr '[:upper:]' '[:lower:]')"
  for pat in "${SENSITIVE_PATTERNS[@]}"; do
    # [[ == ]] does glob matching on the RHS
    [[ "$base_lower" == $pat ]] && return 0
  done
  return 1
}

BLOCKED=()
for f in "${ALL_FILES[@]}"; do
  is_sensitive "$f" && BLOCKED+=("$f")
done

if [[ ${#BLOCKED[@]} -gt 0 ]]; then
  echo "ERROR: Sensitive files detected — refusing to stage:" >&2
  printf '  %s\n' "${BLOCKED[@]}" >&2
  echo "Remove them from the working tree or add to .gitignore before committing." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Classify each file into: source | config | docs
# (tests → source; deleted files → inferred from extension)
# ---------------------------------------------------------------------------
classify_file() {
  local f="$1"
  local lower base base_lower
  lower="$(echo "$f" | tr '[:upper:]' '[:lower:]')"
  base="${f##*/}"
  base_lower="$(echo "$base" | tr '[:upper:]' '[:lower:]')"

  # Docs
  if [[ "$lower" =~ \.(md|rst|txt)$ ]] \
     || [[ "$f" =~ ^(docs?|doc)/ ]] \
     || [[ "$base_lower" =~ ^(changelog|backlog|readme|refactoring|license|contributing) ]]; then
    echo "docs"; return
  fi

  # Config
  if [[ "$lower" =~ \.(toml|yaml|yml|lock|cfg|ini)$ ]] \
     || [[ "$lower" =~ requirements[^/]*\.txt$ ]] \
     || [[ "$base_lower" =~ ^package(-lock)?\.json$ ]] \
     || [[ "$f" =~ ^(config|configs|\.config)/ ]]; then
    echo "config"; return
  fi

  # Submodule pointer changes (directory with no extension)
  if [[ ! "$base" =~ \. ]] && [[ -d "$f" ]] \
     && git config --file .gitmodules "submodule.${f}.path" >/dev/null 2>&1; then
    echo "config"; return
  fi

  # Tests → source (commit together with source files they test)
  if [[ "$f" =~ ^(tests?|spec|__tests__)/ ]] \
     || [[ "$lower" =~ (_test\.|\.test\.|\.spec\.|_spec\.) ]] \
     || [[ "$base_lower" =~ ^test_ ]]; then
    echo "source"; return
  fi

  # Source
  if [[ "$lower" =~ \.(ts|tsx|js|jsx|py|go|rs|rb|java|c|cpp|cs|swift|kt|sh|bash)$ ]] \
     || [[ "$f" =~ ^(src|scripts|lib|app|pkg|cmd|internal)/ ]]; then
    echo "source"; return
  fi

  # .json not already matched → config
  [[ "$lower" =~ \.json$ ]] && { echo "config"; return; }

  # Default fallback
  echo "source"
}

declare -a GROUP_SOURCE GROUP_CONFIG GROUP_DOCS
GROUP_SOURCE=()
GROUP_CONFIG=()
GROUP_DOCS=()

for f in "${ALL_FILES[@]}"; do
  group="$(classify_file "$f")"
  case "$group" in
    source) GROUP_SOURCE+=("$f") ;;
    config) GROUP_CONFIG+=("$f") ;;
    docs)   GROUP_DOCS+=("$f")   ;;
  esac
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Derive scope: most frequent top-level directory among a list of files
derive_scope() {
  local -a files=("$@")
  local segs=()
  for f in "${files[@]}"; do
    local seg="${f%%/*}"
    [[ "$seg" != "$f" ]] && segs+=("$seg")
  done
  if [[ ${#segs[@]} -eq 0 ]]; then echo ""; return; fi
  local scope
  scope="$(printf '%s\n' "${segs[@]}" | sort | uniq -c | sort -rn | awk 'NR==1{print $2}')"
  # Suppress generic top-level names
  case "$scope" in src|lib|app|pkg|config|.) scope="" ;; esac
  echo "$scope"
}

# Determine type for the source group by scanning the diff
source_type() {
  local -a files=("$@")
  local diff_context=""
  for f in "${files[@]}"; do
    diff_context+="$(git diff --cached -- "$f" 2>/dev/null || git diff -- "$f" 2>/dev/null || true)"
  done

  # Explicit fix signals in added lines
  if printf '%s\n' "$diff_context" | grep -qiE '^\+.*(fix|bug|patch|correct|repair|resolve)'; then
    echo "fix"; return
  fi

  local added removed
  added=$(printf '%s\n' "$diff_context" | grep -c '^+[^+]' 2>/dev/null || true)
  added=${added%%[!0-9]*}; added=${added:-0}
  removed=$(printf '%s\n' "$diff_context" | grep -c '^-[^-]' 2>/dev/null || true)
  removed=${removed%%[!0-9]*}; removed=${removed:-0}

  if [[ $added -gt $removed ]]; then echo "feat"
  elif [[ $removed -gt $added ]]; then echo "refactor"
  else echo "refactor"
  fi
}

# Generate a short description (<72 chars remaining after header prefix)
make_description() {
  local verb="$1"
  shift
  local -a files=("$@")
  local count=${#files[@]}
  local desc

  if [[ $count -eq 1 ]]; then
    local base="${files[0]##*/}"
    desc="${verb} ${base%.*}"
  elif [[ $count -le 3 ]]; then
    local names=()
    for f in "${files[@]}"; do
      local b="${f##*/}"
      b="${b%/}"                       # strip trailing slash (directories)
      [[ -z "$b" ]] && b="${f%/}" && b="${b##*/}"  # fallback to parent segment
      [[ -z "$b" ]] && continue
      names+=("${b%.*}")
    done
    local joined=""
    for n in "${names[@]}"; do
      [[ -n "$joined" ]] && joined+=", "
      joined+="$n"
    done
    desc="${verb} ${joined}"
  else
    local scope
    scope="$(derive_scope "${files[@]}")"
    if [[ -n "$scope" ]]; then
      desc="${verb} ${count} files in ${scope}"
    else
      desc="${verb} ${count} files"
    fi
  fi

  # Lowercase, strip trailing period
  desc="$(echo "$desc" | tr '[:upper:]' '[:lower:]')"
  desc="${desc%.}"
  echo "$desc"
}

# Build and optionally execute a commit for one group
commit_group() {
  local group_name="$1"
  local commit_type="$2"
  local verb="$3"
  shift 3
  local -a files=("$@")

  local scope description header commit_msg

  scope="$(derive_scope "${files[@]}")"
  description="$(make_description "$verb" "${files[@]}")"

  header="${commit_type}"
  [[ -n "$scope" ]] && header+="(${scope})"
  header+=": ${description}"

  # Enforce <72 char header
  if [[ ${#header} -gt 72 ]]; then
    description="${description:0:$((72 - ${#commit_type} - ${#scope} - 4))}"
    header="${commit_type}"
    [[ -n "$scope" ]] && header+="(${scope})"
    header+=": ${description}"
  fi

  commit_msg="${header}"$'\n\n'"Co-Authored-By: Claude ${CLAUDE_MODEL:-Sonnet 4.6} <noreply@anthropic.com>"

  echo
  echo "=== ${group_name} commit ==="
  echo "$header"
  echo "Files (${#files[@]}):"
  printf '  %s\n' "${files[@]}"

  if $DRY_RUN; then
    echo "[dry-run] skipped."
    return
  fi

  # Stage files
  git add -- "${files[@]}"

  local tmp
  tmp="$(mktemp)"
  trap 'rm -f "$tmp"' RETURN
  printf '%s\n' "$commit_msg" > "$tmp"

  if ! git commit -F "$tmp"; then
    echo "ERROR: commit failed for group '${group_name}'" >&2
    return 1
  fi
  echo "Created: $(git rev-parse --short HEAD) ${header}"
}

# ---------------------------------------------------------------------------
# Execute commits in order: source → config → docs (Step 3)
# ---------------------------------------------------------------------------
COMMITS_CREATED=0
COMMIT_FAILED=0

if [[ ${#GROUP_SOURCE[@]} -gt 0 ]]; then
  TYPE="$(source_type "${GROUP_SOURCE[@]}")"
  case "$TYPE" in
    feat)     VERB="add" ;;
    fix)      VERB="fix" ;;
    refactor) VERB="refactor" ;;
    *)        VERB="update" ;;
  esac
  if commit_group "source" "$TYPE" "$VERB" "${GROUP_SOURCE[@]}"; then
    $DRY_RUN || (( COMMITS_CREATED++ )) || true
  else
    COMMIT_FAILED=1
  fi
fi

if [[ ${#GROUP_CONFIG[@]} -gt 0 ]]; then
  if commit_group "config" "chore" "update" "${GROUP_CONFIG[@]}"; then
    $DRY_RUN || (( COMMITS_CREATED++ )) || true
  else
    COMMIT_FAILED=1
  fi
fi

if [[ ${#GROUP_DOCS[@]} -gt 0 ]]; then
  if commit_group "docs" "docs" "update" "${GROUP_DOCS[@]}"; then
    $DRY_RUN || (( COMMITS_CREATED++ )) || true
  else
    COMMIT_FAILED=1
  fi
fi

echo
if $DRY_RUN; then
  echo "[dry-run] No commits created."
else
  echo "Done. ${COMMITS_CREATED} commit(s) created."
fi

if [[ $COMMIT_FAILED -eq 1 ]]; then
  exit 1
fi
