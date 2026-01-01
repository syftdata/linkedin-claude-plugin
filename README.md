# LinkedIn Search Plugin for Claude Code

Search your LinkedIn data export to find posts, connections, and statistics.

## Setup

```bash
# 1. Install plugin
/plugin marketplace add https://github.com/yourusername/linkedin-search-plugin
/plugin install linkedin-search

# 2. Add your LinkedIn export
mkdir -p ~/.linkedin-exports
cp ~/Downloads/Complete_LinkedInDataExport_*.zip ~/.linkedin-exports/
```

That's it! Dependencies install automatically on first use.

## Usage

Just ask Claude:

- "Did I write about AI?"
- "Find GTM agency founders I know"
- "Am I connected to anyone at Microsoft?"
- "How many posts have I made?"

## Updating Data

Download a new LinkedIn export and copy to the watch folder:

```bash
cp ~/Downloads/New_Export_*.zip ~/.linkedin-exports/
```

The plugin auto-detects and reloads on next query.

## How It Works

1. **First query:** Auto-installs sqlite-utils, extracts ZIP, loads to SQLite
2. **Subsequent queries:** Uses cached database (instant)
3. **New export detected:** Auto-reloads when newer ZIP found

**Data locations:**
- Watch folder: `~/.linkedin-exports/`
- Database: `~/.linkedin-search/data.db`

## License

MIT
