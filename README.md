# LinkedIn Search Plugin for Claude Code

Search your LinkedIn data export to find posts, connections, and statistics.

## Setup

### 1. Download your LinkedIn data

1. Go to [LinkedIn Settings → Data Privacy](https://www.linkedin.com/mypreferences/d/download-my-data)
2. Select "Download larger data archive" (includes posts, connections, comments)
3. Click "Request archive"
4. Wait for email from LinkedIn (usually 10-15 minutes, can take up to 24 hours)
5. Download the ZIP file from the link in the email

### 2. Install plugin

```bash
/plugin marketplace add https://github.com/syftdata/linkedin-claude-plugin
/plugin install linkedin-search
```

### 3. Add your LinkedIn export

```bash
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
