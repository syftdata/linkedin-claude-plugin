#!/usr/bin/env bash

echo "Verifying LinkedIn Search plugin dependencies..."
echo ""

# Check Python
if command -v python3 &> /dev/null; then
    echo "✓ Python3 found: $(python3 --version)"
else
    echo "✗ Python3 not found"
    exit 1
fi

# Check sqlite-utils
if python3 -c "import sqlite_utils" 2>/dev/null; then
    echo "✓ sqlite-utils installed"
else
    echo "✗ sqlite-utils not found"
    echo "  Run: pip install sqlite-utils"
    exit 1
fi

# Check watch folder
if [ -d ~/.linkedin-exports ]; then
    EXPORT_COUNT=$(ls ~/.linkedin-exports/*.zip 2>/dev/null | wc -l | tr -d ' ')
    echo "✓ Watch folder exists: ~/.linkedin-exports/"
    echo "  Found $EXPORT_COUNT export(s)"
else
    echo "✗ Watch folder not found: ~/.linkedin-exports/"
    echo "  Run: mkdir -p ~/.linkedin-exports"
    exit 1
fi

# Check database
if [ -f ~/.linkedin-search/data.db ]; then
    echo "✓ Database exists: ~/.linkedin-search/data.db"
else
    echo "○ Database not created yet (will be created on first query)"
fi

echo ""
echo "All checks passed! Plugin is ready to use."
