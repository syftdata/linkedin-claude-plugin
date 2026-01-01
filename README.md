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

### 3. Ask a question

Just ask Claude anything about your LinkedIn data. On first run, it will prompt you for the path to your export ZIP:

```
📂 No LinkedIn exports found in ~/.linkedin-exports/

Please provide the path to your LinkedIn export ZIP file.

Path to LinkedIn export ZIP: ~/Downloads/Complete_LinkedInDataExport_08-27-2025.zip

📦 Copying to ~/.linkedin-exports/...
✓ Export copied!
🔄 Loading...
✓ Database ready!
```

That's it - you're ready to search!

## Usage

Just ask Claude:

- "Find me the link to the post I wrote about inverted funnels for GTM"
- "Who are the GTM agency founders in my network?"
- "Am I connected to anyone in product management at Microsoft?"
- "What did I write about AI-powered sales tools last year?"

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
