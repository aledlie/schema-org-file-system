#!/bin/bash

# Configuration Backup Script
# Creates timestamped backups of critical Claude Code configuration files

set -e  # Exit on error

# Shared lib
source "$(dirname "$0")/../lib/colors.sh"

# Configuration
BACKUP_BASE_DIR="$CLAUDE_DIR/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="$BACKUP_BASE_DIR/$TIMESTAMP"

# Banner
echo -e "${BLUE}═══════════════════════════════════════${NC}"
echo -e "${BLUE}  Claude Code Configuration Backup${NC}"
echo -e "${BLUE}═══════════════════════════════════════${NC}"
echo ""

# Create backup directory
log_info "Creating backup directory..."
mkdir -p "$BACKUP_DIR"
log_success "Created: $BACKUP_DIR"

# Backup each file
log_info "Backing up configuration files..."
backed_up=0
skipped=0

for file in "${BACKUP_FILES[@]}"; do
    source_file="$CLAUDE_DIR/$file"

    if [ -f "$source_file" ]; then
        # Create subdirectory structure in backup
        backup_file="$BACKUP_DIR/$file"
        backup_dir=$(dirname "$backup_file")

        mkdir -p "$backup_dir"
        cp "$source_file" "$backup_file"

        # Get file size
        size=$(ls -lh "$source_file" | awk '{print $5}')

        echo "  ✓ $file ($size)"
        ((backed_up++))
    else
        echo "  ⊘ $file (not found)"
        ((skipped++))
    fi
done

# Backup hooks directory (optional)
if [ -d "$CLAUDE_DIR/hooks" ]; then
    log_info "Backing up hooks..."
    mkdir -p "$BACKUP_DIR/hooks"

    # Copy all .sh files
    hooks_count=0
    for hook in "$CLAUDE_DIR/hooks"/*.sh; do
        if [ -f "$hook" ]; then
            cp "$hook" "$BACKUP_DIR/hooks/"
            ((hooks_count++))
        fi
    done

    if [ $hooks_count -gt 0 ]; then
        log_success "Backed up $hooks_count hook scripts"
    else
        log_warn "No hook scripts found"
    fi
fi

# Create backup manifest
log_info "Creating backup manifest..."
cat > "$BACKUP_DIR/MANIFEST.txt" << EOF
Claude Code Configuration Backup
================================

Backup Time: $(date '+%Y-%m-%d %H:%M:%S')
Backup Location: $BACKUP_DIR

Files Backed Up:
EOF

find "$BACKUP_DIR" -type f ! -name "MANIFEST.txt" | while read -r file; do
    rel_path=${file#$BACKUP_DIR/}
    size=$(ls -lh "$file" | awk '{print $5}')
    echo "  - $rel_path ($size)" >> "$BACKUP_DIR/MANIFEST.txt"
done

log_success "Created manifest"

# Calculate backup size
backup_size=$(du -sh "$BACKUP_DIR" | cut -f1)

# Summary
echo ""
echo -e "${GREEN}═══════════════════════════════════════${NC}"
echo -e "${GREEN}  Backup Complete!${NC}"
echo -e "${GREEN}═══════════════════════════════════════${NC}"
echo ""
echo "  Location: $BACKUP_DIR"
echo "  Size: $backup_size"
echo "  Files backed up: $backed_up"
if [ $skipped -gt 0 ]; then
    echo "  Files skipped: $skipped"
fi
echo ""

# List recent backups
log_info "Recent backups:"
ls -lt "$BACKUP_BASE_DIR" | grep '^d' | head -5 | while read -r line; do
    backup=$(echo "$line" | awk '{print $9}')
    echo "  • $(format_backup_timestamp "$backup")"
done

echo ""
log_info "To restore:"
echo "  cp $BACKUP_DIR/settings.json $CLAUDE_DIR/"
echo "  cp $BACKUP_DIR/skills/skill-rules.json $CLAUDE_DIR/skills/"

# Cleanup old backups (optional)
backup_count=$(ls -1d "$BACKUP_BASE_DIR"/*/ 2>/dev/null | wc -l | tr -d ' ')
if [ "$backup_count" -gt 10 ]; then
    echo ""
    log_warn "You have $backup_count backups"
    read -p "Delete backups older than 30 days? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        log_info "Cleaning up old backups..."
        find "$BACKUP_BASE_DIR" -type d -mtime +30 -exec rm -rf {} + 2>/dev/null || true
        log_success "Cleanup complete"
    fi
fi

echo ""
log_success "Backup saved to: $BACKUP_DIR"
