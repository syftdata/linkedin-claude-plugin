#!/usr/bin/env python3
"""Deprecated entry point, kept so existing callers keep working.

The LinkedIn search plugin became the LinkedIn bot in 2.0.0 and the CLI moved to skills/linkedin/linkedin.py.
Every v1 command (search-shares, find-connections, search-comments, search-connections-keywords, stats) is
forwarded unchanged. The database path (~/.linkedin-search/data.db) and watch folder (~/.linkedin-exports/)
did not move.
"""
import os
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parent.parent / "linkedin" / "linkedin.py"

if __name__ == "__main__":
    os.execv(sys.executable, [sys.executable, str(TARGET)] + sys.argv[1:])
