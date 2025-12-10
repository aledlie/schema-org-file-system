#!/bin/bash
# Launch Timeline Visualization
# Quick script to generate data and open timeline interface

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo -e "${BLUE}╔════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   Timeline Visualization Launcher             ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════╝${NC}"
echo ""

# Check if database exists
if [ ! -f "results/file_organization.db" ]; then
    echo -e "${RED}❌ Error: Database not found${NC}"
    echo ""
    echo "Please run the file organizer first:"
    echo "  python3 scripts/file_organizer_content_based.py --dry-run --limit 10"
    echo ""
    exit 1
fi

# Check Python availability
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Error: python3 not found${NC}"
    exit 1
fi

# Step 1: Generate timeline data
echo -e "${BLUE}[1/3]${NC} Generating timeline data..."
python3 src/api/timeline_api.py --db-path results/file_organization.db --output _site/timeline_data.json

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Timeline data generated successfully${NC}"
else
    echo -e "${RED}❌ Failed to generate timeline data${NC}"
    exit 1
fi

echo ""

# Step 2: Check if timeline.html exists
if [ ! -f "_site/timeline.html" ]; then
    echo -e "${RED}❌ Error: timeline.html not found in _site/${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Timeline interface ready${NC}"
echo ""

# Step 3: Launch server or open file
echo -e "${BLUE}[2/3]${NC} Choose launch method:"
echo ""
echo "  1) Launch local server (recommended)"
echo "  2) Open file directly in browser"
echo "  3) Just generate data (no launch)"
echo ""
read -p "Enter choice [1-3]: " choice

case $choice in
    1)
        echo ""
        echo -e "${BLUE}[3/3]${NC} Starting local server..."
        echo ""
        echo -e "${GREEN}🚀 Server starting on http://localhost:8000${NC}"
        echo -e "${GREEN}📊 Timeline URL: http://localhost:8000/timeline.html${NC}"
        echo ""
        echo -e "${YELLOW}Press Ctrl+C to stop the server${NC}"
        echo ""

        # Try to open browser automatically
        sleep 1
        if command -v open &> /dev/null; then
            open "http://localhost:8000/timeline.html"
        elif command -v xdg-open &> /dev/null; then
            xdg-open "http://localhost:8000/timeline.html"
        fi

        cd _site
        python3 -m http.server 8000
        ;;
    2)
        echo ""
        echo -e "${BLUE}[3/3]${NC} Opening timeline in browser..."

        if command -v open &> /dev/null; then
            open "$PROJECT_ROOT/_site/timeline.html"
            echo -e "${GREEN}✅ Timeline opened in default browser${NC}"
        elif command -v xdg-open &> /dev/null; then
            xdg-open "$PROJECT_ROOT/_site/timeline.html"
            echo -e "${GREEN}✅ Timeline opened in default browser${NC}"
        else
            echo -e "${YELLOW}⚠️  Could not open browser automatically${NC}"
            echo ""
            echo "Please open this file manually:"
            echo "  $PROJECT_ROOT/_site/timeline.html"
        fi
        ;;
    3)
        echo ""
        echo -e "${GREEN}✅ Data generated successfully${NC}"
        echo ""
        echo "To view the timeline later:"
        echo "  cd _site && python3 -m http.server 8000"
        echo "  open http://localhost:8000/timeline.html"
        ;;
    *)
        echo -e "${RED}Invalid choice. Exiting.${NC}"
        exit 1
        ;;
esac

echo ""
echo -e "${BLUE}════════════════════════════════════════════════${NC}"
echo ""
