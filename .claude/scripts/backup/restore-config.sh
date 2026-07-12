#!/bin/bash

# Configuration Restore Script
# Restores Claude Code configuration from a backup

set -e  # Exit on error

# Shared lib
source "$(dirname "$0")/../lib/colors.sh"

# Configuration
BACKUP_BASE_DIR="$CLAUDE_DIR/backups"

# Banner
echo -e "${BLUE}═══════════════════════════════════════${NC}"
echo -e "${BLUE}  Claude Code Configuration Restore${NC}"
echo -e "${BLUE}═══════════════════════════════════════${NC}"
echo ""

# Check if backups exist
if [ ! -d "$BACKUP_BASE_DIR" ]; then
    log_error "No backups found at $BACKUP_BASE_DIR"
    exit 1
fi

# List available backups
log_info "Available backups:"
echo ""

backups=($(ls -1dt "$BACKUP_BASE_DIR"/*/ 2>/dev/null | head -10))

if [ ${#backups[@]} -eq 0 ]; then
    log_error "No backups found"
    exit 1
fi

# Display backups with numbers
counter=1
for backup in "${backups[@]}"; do
    backup_name=$(basename "$backup")

    # Get backup size
    size=$(du -sh "$backup" | cut -f1)

    echo "  $counter) $(format_backup_timestamp "$backup_name") ($size)"
    ((counter++))
done

echo ""

# Get user selection
if [ -n "$1" ]; then
    selection=$1
else
    read -p "Select backup to restore (1-${#backups[@]}, or 'q' to quit): " selection
fi

if [ "$selection" = "q" ]; then
    log_info "Restore cancelled"
    exit 0
fi

# Validate selection
if ! [[ "$selection" =~ ^[0-9]+$ ]] || [ "$selection" -lt 1 ] || [ "$selection" -gt ${#backups[@]} ]; then
    log_error "Invalid selection"
    exit 1
fi

# Get selected backup
selected_backup="${backups[$((selection-1))]}"
backup_name=$(basename "$selected_backup")

log_info "Selected backup: $backup_name"

# Show what will be restored
log_info "Files in this backup:"
if [ -f "$selected_backup/MANIFEST.txt" ]; then
    cat "$selected_backup/MANIFEST.txt" | grep "^  - "
else
    find "$selected_backup" -type f | while read -r file; do
        rel_path=${file#$selected_backup/}
        echo "  - $rel_path"
    done
fi

echo ""
log_warn "This will overwrite your current configuration!"

# Confirm
read -p "Continue with restore? (y/N): " -n 1 -r
echo

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    log_info "Restore cancelled"
    exit 0
fi

# Create backup of current config before restoring
log_info "Creating backup of current configuration..."
current_backup="$BACKUP_BASE_DIR/pre-restore-$(date +%Y%m%d_%H%M%S)"
mkdir -p "$current_backup"

for file in "${BACKUP_FILES[@]}"; do
    if [ -f "$CLAUDE_DIR/$file" ]; then
        backup_file="$current_backup/$file"
        mkdir -p "$(dirname "$backup_file")"
        cp "$CLAUDE_DIR/$file" "$backup_file"
    fi
done

log_success "Current config backed up to: $current_backup"

# Restore files
log_info "Restoring configuration files..."
restored=0

# Restore main config files
for file in "${BACKUP_FILES[@]}"; do
    source_file="$selected_backup/$file"

    if [ -f "$source_file" ]; then
        dest_file="$CLAUDE_DIR/$file"
        mkdir -p "$(dirname "$dest_file")"

        cp "$source_file" "$dest_file"
        echo "  ✓ Restored: $file"
        ((restored++))
    fi
done

# Restore hooks if they exist in backup
if [ -d "$selected_backup/hooks" ]; then
    log_info "Restoring hooks..."
    hooks_restored=0

    for hook in "$selected_backup/hooks"/*.sh; do
        if [ -f "$hook" ]; then
            hook_name=$(basename "$hook")
            cp "$hook" "$CLAUDE_DIR/hooks/"
            chmod +x "$CLAUDE_DIR/hooks/$hook_name"
            ((hooks_restored++))
        fi
    done

    if [ $hooks_restored -gt 0 ]; then
        log_success "Restored $hooks_restored hook scripts"
    fi
fi

# Validate restored configuration
log_info "Validating restored configuration..."

validation_passed=true

# Check JSON files
for json_file in settings.json skills/skill-rules.json; do
    if [ -f "$CLAUDE_DIR/$json_file" ]; then
        if ! validate_json -q "$CLAUDE_DIR/$json_file" "$json_file"; then
            validation_passed=false
        fi
    fi
done

# Summary
echo ""
if [ "$validation_passed" = true ]; then
    echo -e "${GREEN}═══════════════════════════════════════${NC}"
    echo -e "${GREEN}  Restore Complete!${NC}"
    echo -e "${GREEN}═══════════════════════════════════════${NC}"
else
    echo -e "${YELLOW}═══════════════════════════════════════${NC}"
    echo -e "${YELLOW}  Restore Complete (with warnings)${NC}"
    echo -e "${YELLOW}═══════════════════════════════════════${NC}"
fi
echo ""

echo "  Restored from: $backup_name"
echo "  Files restored: $restored"
echo "  Previous config backed up to: $(basename "$current_backup")"
echo ""

log_info "Next steps:"
echo "  1. Verify configuration: npm run validate"
echo "  2. Check settings: cat $CLAUDE_DIR/settings.json"
echo ""

if [ "$validation_passed" = false ]; then
    log_warn "Some files failed validation. Check manually."
    log_info "To rollback: $0 (and select $(basename "$current_backup"))"
fi

log_success "Configuration restored successfully!"
