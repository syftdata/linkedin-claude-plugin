---
name: linkedin
description: Your LinkedIn data export as a queryable database. Search your posts and comments, find connections by title or company, see who you message, and get stats. Use for any question about the user's own LinkedIn activity or network. For pruning connections, use the linkedin-cleanup skill.
allowed-tools: Read, Bash(python3:*)
---

# LinkedIn

Works on the user's LinkedIn data export (the **larger data archive** ZIP), loaded into a local SQLite database.
No scraping, no LinkedIn login, standard-library Python only.

## Setup

1. LinkedIn → Settings → Data privacy → Get a copy of your data → **Download larger data archive**. The smaller
   archive has no `messages.csv`, so anything about who you talk to won't work.
2. Load it:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/skills/linkedin/linkedin.py ingest --zip ~/Downloads/Complete_LinkedInDataExport_*.zip
   ```
   Or drop the ZIP in `~/.linkedin-exports/`. The newest ZIP there is loaded automatically on the next command.

## What is in the export

| File | What it is | Table |
|---|---|---|
| `Connections.csv` | People you are connected to (accepted 1st-degree), with a day-level `Connected On` | `connections`, `connections_index` |
| `messages.csv` | DMs, full UTC timestamps, participants by profile URL | `messages`, `dm_events`, `last_dm` |
| `Invitations.csv` | Connection requests sent and received (pending history). Not your connections | `invitations` |
| `Shares.csv`, `Comments.csv`, `Reactions.csv` | Your posts, comments, reactions | `shares`, `comments`, `reactions` |

## Commands

```bash
L=${CLAUDE_PLUGIN_ROOT}/skills/linkedin/linkedin.py
python3 $L search-shares --query "AI"                          # your posts
python3 $L find-connections --title "founder" --company "microsoft"
python3 $L search-connections-keywords --keywords founder gtm   # every keyword in title + company
python3 $L search-comments --query "pricing"
python3 $L stats
python3 $L ingest [--zip PATH]                                  # reload now, prints what loaded
```

For "who haven't I talked to", "clean up my network", "I'm near the 30,000 cap": use the **linkedin-cleanup** skill.

## Examples

"Did I write about AI?" → `search-shares --query "AI"`
"Find GTM agency founders" → `search-connections-keywords --keywords founder gtm`
"How many connections do I have?" → `stats`

`skills/linkedin-search/linkedin_search.py` still works and forwards to this CLI.
