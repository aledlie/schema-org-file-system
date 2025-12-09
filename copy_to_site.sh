#!/bin/bash

# Script to copy all HTML files from results/ to _site/

# Create _site directory if it doesn't exist
mkdir -p /Users/alyshialedlie/schema-org-file-system/_site

# Copy all HTML files
echo "Copying HTML files to _site directory..."

cp /Users/alyshialedlie/schema-org-file-system/results/organization_report.html /Users/alyshialedlie/schema-org-file-system/_site/
echo "✓ Copied organization_report.html"

cp /Users/alyshialedlie/schema-org-file-system/results/metadata_viewer.html /Users/alyshialedlie/schema-org-file-system/_site/
echo "✓ Copied metadata_viewer.html"

cp /Users/alyshialedlie/schema-org-file-system/results/correction_interface.html /Users/alyshialedlie/schema-org-file-system/_site/
echo "✓ Copied correction_interface.html"

cp /Users/alyshialedlie/schema-org-file-system/results/ml_data_explorer.html /Users/alyshialedlie/schema-org-file-system/_site/
echo "✓ Copied ml_data_explorer.html"

echo ""
echo "All files copied successfully to _site directory!"
echo ""
echo "Files in _site:"
ls -lh /Users/alyshialedlie/schema-org-file-system/_site/
