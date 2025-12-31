---
name: linkedin-search
description: Search your LinkedIn posts/shares by topic, find connections by title or company, and get LinkedIn statistics. Use when analyzing your LinkedIn data, finding specific connections, or reviewing past posts and shares.
allowed-tools: Read, Bash(python:*)
---

# LinkedIn Search

Search your LinkedIn data archive to find posts by topic, connections by role/company, and view statistics.

## Setup (One-time)

### 1. Install dependencies
```bash
pip install sqlite-utils
```

### 2. Create watch folder
```bash
mkdir -p ~/.linkedin-exports
```

### 3. Copy your LinkedIn export
Download your LinkedIn data export from LinkedIn Settings → Download your data, then:
```bash
cp ~/Downloads/Complete_LinkedInDataExport_*.zip ~/.linkedin-exports/
```

That's it! The skill will auto-load your data on first use.

## Usage

The skill automatically detects and loads the latest LinkedIn export from `~/.linkedin-exports/`. Just copy new exports there periodically, and the skill will auto-refresh.

**Search posts/shares by topic:**
```bash
python ${CLAUDE_PLUGIN_ROOT}/skills/linkedin-search/linkedin_search.py search-shares --query "AI adoption"
```

**Find connections by title and/or company:**
```bash
python ${CLAUDE_PLUGIN_ROOT}/skills/linkedin-search/linkedin_search.py find-connections --title "product manager" --company "Microsoft"
```

**Search connections by multiple keywords:**
```bash
python ${CLAUDE_PLUGIN_ROOT}/skills/linkedin-search/linkedin_search.py search-connections-keywords --keywords founder gtm
```

**Search comments:**
```bash
python ${CLAUDE_PLUGIN_ROOT}/skills/linkedin-search/linkedin_search.py search-comments --query "your query"
```

**Get statistics:**
```bash
python ${CLAUDE_PLUGIN_ROOT}/skills/linkedin-search/linkedin_search.py stats
```

## How it works

1. **First time:** Extracts your ZIP file, loads data into SQLite at `~/.linkedin-search/data.db`, creates indexes
2. **Subsequent queries:** Uses cached SQLite database (much faster)
3. **New export detected:** Automatically reloads when a newer export is detected in `~/.linkedin-exports/`

## Examples

User: "Did I write about AI?"
Claude runs: `search-shares --query "AI"`

User: "Am I connected to anyone in product at Microsoft?"
Claude runs: `find-connections --title "product" --company "Microsoft"`

User: "Find GTM agency founders I know"
Claude runs: `search-connections-keywords --keywords founder gtm`

User: "How many posts have I made?"
Claude runs: `stats`
