#!/bin/bash

# Script to copy all HTML files from results/ to _site/

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Create _site directory if it doesn't exist
mkdir -p "$PROJECT_ROOT/_site"

# Copy all HTML files
echo "Copying HTML files to _site directory..."

cp "$PROJECT_ROOT/results/organization_report.html" "$PROJECT_ROOT/_site/" 2>/dev/null && echo "✓ Copied organization_report.html" || echo "⚠ organization_report.html not found"

cp "$PROJECT_ROOT/results/metadata_viewer.html" "$PROJECT_ROOT/_site/" 2>/dev/null && echo "✓ Copied metadata_viewer.html" || echo "⚠ metadata_viewer.html not found"

cp "$PROJECT_ROOT/results/correction_interface.html" "$PROJECT_ROOT/_site/" 2>/dev/null && echo "✓ Copied correction_interface.html" || echo "⚠ correction_interface.html not found"

cp "$PROJECT_ROOT/results/ml_data_explorer.html" "$PROJECT_ROOT/_site/" 2>/dev/null && echo "✓ Copied ml_data_explorer.html" || echo "⚠ ml_data_explorer.html not found"

cp "$PROJECT_ROOT/results/index.html" "$PROJECT_ROOT/_site/" 2>/dev/null && echo "✓ Copied index.html" || echo "⚠ index.html not found"

# Copy cost report for dynamic data loading
if [ -f "$PROJECT_ROOT/results/cost_report.json" ]; then
    cp "$PROJECT_ROOT/results/cost_report.json" "$PROJECT_ROOT/_site/"
    echo "✓ Copied cost_report.json"
fi

echo ""
echo "All files copied successfully to _site directory!"
echo ""
echo "Files in _site:"
ls -lh "$PROJECT_ROOT/_site/"
