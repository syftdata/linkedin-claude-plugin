# LinkedIn Search Plugin for Claude Code

Search your LinkedIn data export to find posts by topic, connections by title/company, and get statistics. Features auto-loading from a watch folder with JIT SQLite indexing.

## Features

- **Search posts/shares** by keyword (e.g., "AI", "growth marketing")
- **Find connections** by title and/or company (e.g., "founders at GTM agencies")
- **Multi-keyword search** for connections (e.g., find people with "founder" AND "GTM")
- **Statistics** on your LinkedIn activity
- **JIT loading** - automatically detects and loads new exports
- **SQLite caching** - fast queries after initial load

## Installation

### Prerequisites
- Claude Code v1.0.33 or later
- Python 3.8+

### Install the Plugin

```bash
# Add the plugin marketplace
/plugin marketplace add https://github.com/yourusername/linkedin-search-plugin

# Install the plugin
/plugin install linkedin-search
```

### Install Dependencies

```bash
# Run the install script
./scripts/install-deps.sh
```

Or manually:
```bash
pip install sqlite-utils
mkdir -p ~/.linkedin-exports
```

### Add Your LinkedIn Data

1. Go to LinkedIn Settings → Data Privacy → Get a copy of your data
2. Request your data export (may take up to 24 hours)
3. Download the ZIP file when ready
4. Copy to the watch folder:
   ```bash
   cp ~/Downloads/Complete_LinkedInDataExport_*.zip ~/.linkedin-exports/
   ```

## Usage

Just ask Claude! The skill will automatically be invoked when you ask about your LinkedIn data.

**Examples:**

```
"Did I write about AI?"
"Am I connected to anyone in product management at Microsoft?"
"Find GTM agency founders I know"
"How many posts have I made?"
"Search my posts for mentions of growth marketing"
```

**Direct commands:**

```bash
# Search posts
python skills/linkedin-search/linkedin_search.py search-shares --query "AI"

# Find connections
python skills/linkedin-search/linkedin_search.py find-connections --title "founder" --company "microsoft"

# Multi-keyword search
python skills/linkedin-search/linkedin_search.py search-connections-keywords --keywords founder gtm agency

# Get stats
python skills/linkedin-search/linkedin_search.py stats
```

## How It Works

1. **Watch folder:** Place LinkedIn export ZIPs in `~/.linkedin-exports/`
2. **Auto-detection:** On first query, the skill finds the newest export (by file modification time)
3. **JIT loading:** Extracts the ZIP, parses CSVs, loads into SQLite with indexes
4. **Caching:** Subsequent queries use the cached SQLite database (much faster)
5. **Auto-refresh:** When a newer export is detected, it automatically reloads

**Data locations:**
- Watch folder: `~/.linkedin-exports/`
- SQLite database: `~/.linkedin-search/data.db`

## Updating Your Data

Just copy a new LinkedIn export to the watch folder:

```bash
cp ~/Downloads/New_LinkedIn_Export_*.zip ~/.linkedin-exports/
```

The next query will automatically detect and load the new data.

## Troubleshooting

### Verify Installation

```bash
./scripts/verify-deps.sh
```

### Common Issues

**"No LinkedIn exports found"**
- Make sure you've copied your export ZIP to `~/.linkedin-exports/`
- Check that the file ends with `.zip`

**"sqlite-utils not found"**
- Run: `pip install sqlite-utils`

**Slow first query**
- Normal! The first query extracts and indexes your data. Subsequent queries are instant.

## File Structure

```
linkedin-search-plugin/
├── .claude-plugin/
│   └── plugin.json              # Plugin manifest
├── skills/
│   └── linkedin-search/
│       ├── SKILL.md             # Skill definition
│       └── linkedin_search.py   # Python implementation
├── scripts/
│   ├── install-deps.sh          # Dependency installer
│   └── verify-deps.sh           # Verification script
├── requirements.txt             # Python dependencies
├── README.md                    # This file
├── CHANGELOG.md                 # Version history
└── LICENSE                      # MIT license
```

## Development

Test the plugin locally:

```bash
claude --plugin-dir /path/to/linkedin-search-plugin
```

## License

MIT

## Contributing

Issues and PRs welcome at https://github.com/yourusername/linkedin-search-plugin
