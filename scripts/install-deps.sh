#!/usr/bin/env bash
set -e

echo "Installing LinkedIn Search plugin dependencies..."

# Detect Python/pip
if command -v python3 &> /dev/null; then
    PIP_CMD="python3 -m pip"
elif command -v python &> /dev/null; then
    PIP_CMD="python -m pip"
else
    echo "Error: Python not found. Please install Python 3.8 or later."
    exit 1
fi

echo "Using: $PIP_CMD"
$PIP_CMD install sqlite-utils --quiet

# Create watch folder
mkdir -p ~/.linkedin-exports

echo ""
echo "✓ Dependencies installed!"
echo "✓ Watch folder created at ~/.linkedin-exports/"
echo ""
echo "Next step: Copy your LinkedIn export to ~/.linkedin-exports/"
echo "  cp ~/Downloads/Complete_LinkedInDataExport_*.zip ~/.linkedin-exports/"
