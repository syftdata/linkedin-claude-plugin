# LinkedIn bot for Claude and agents

Turn your LinkedIn data export into something an agent can work with: search your posts and connections, see who
you actually talk to, and build a guided cleanup list of connections to consider removing. Everything runs locally
on your export (SQLite, standard-library Python). Nothing scrapes LinkedIn, logs in, or acts on your account.
When you want to act on a list (DM or connect), the `syft` skill hands it to [Syft](https://www.syftdata.com/syfty?utm_source=claude-plugin&utm_medium=linkedin&utm_campaign=outreach), opt-in, with your approval on every message.

The plugin was `linkedin-search`; the search skill keeps that name and works exactly as before; see [Upgrading from linkedin-search](#upgrading-from-linkedin-search).

## Skills

| Skill | Use it for |
|---|---|
| `linkedin-search` | Search posts and comments, find connections by title or company, stats, loading a new export |
| `linkedin-cleanup` | Guided network cleanup: profiles your network, offers groups with real counts, asks which to remove and who to keep, writes a ranked CSV. Never removes anyone |
| `syft` | Act on a list through Syft: LinkedIn DM or connection request to people you found, approval on every message. Needs a Syft account + the Syft MCP; walks you through setup |

## Setup

### 1. Download the larger data archive

1. [LinkedIn Settings → Data Privacy → Get a copy of your data](https://www.linkedin.com/mypreferences/d/download-my-data)
2. Choose **Download larger data archive**. The smaller archive has no `messages.csv`, and cleanup needs it.
3. Wait for LinkedIn's email (often 10 to 15 minutes, up to 24 hours) and download the ZIP.

### 2. Install the plugin

```bash
/plugin marketplace add syftdata/linkedin-claude-plugin
/plugin install linkedin@linkedin
```

### 3. Load your export

Ask Claude anything about your LinkedIn, or load it yourself:

```bash
python3 skills/linkedin/linkedin.py ingest --zip ~/Downloads/Complete_LinkedInDataExport_09-23-2026.zip
```

The ZIP is copied into `~/.linkedin-exports/`. Drop a newer export there any time; the next command reloads it.

## What is in the export, and what each file means

| File | What it is | Used for |
|---|---|---|
| `Connections.csv` | People you are **connected to** (accepted 1st-degree), with `Connected On` at day precision | search, cleanup |
| `messages.csv` | Your **DMs**, full UTC timestamps, participants by profile URL | last DM per person, cleanup |
| `Invitations.csv` | Connection **requests** sent and received (pending history). Not your connections | search / stats only, never cleanup |
| `Shares.csv`, `Comments.csv`, `Reactions.csv` | Your posts, comments and reactions | search |

Connections are joined to messages on the normalised profile URL (`/in/<slug>`). `ingest` prints how many people
you have messaged and how many of them are connections, so a poor join is visible.

## Search

```bash
L=skills/linkedin/linkedin.py
python3 $L search-shares --query "inverted funnel"
python3 $L find-connections --title "product" --company "microsoft"
python3 $L search-connections-keywords --keywords founder gtm
python3 $L search-comments --query "pricing"
python3 $L stats
```

## Network cleanup

Ask Claude to "clean up my LinkedIn network" or "who haven't I talked to in years". The `linkedin-cleanup` skill:

1. **Profiles** your network: connections by age, never messaged, last DM over 1 / 3 years, headroom under
   LinkedIn's 30,000 cap.
2. **Asks which group** to consider, with live counts. Options only appear when they have people in them:
   - Connected 5+ years ago and never messaged
   - Connected 2+ years ago and no DM in the last 3 years
   - Never messaged at all
   - They messaged you and you never replied (usually a pitch)
   - Connected in the last 12 months and never messaged
   - Custom thresholds
3. **Asks how many** you want to free up and **who to always keep** (company names, title words).
4. **Confirms** the definition and count, then writes a ranked CSV (default `~/.linkedin-exports/cleanup/`).
5. **Offers pass 2** (ICP / persona), which is not run in pass 1.

The same thing from the CLI:

```bash
python3 $L network-profile
python3 $L cleanup-candidates --preset old-never-messaged --keep-company "Acme" --limit 1500 --dry-run
python3 $L cleanup-candidates --connected-before 5y --no-dm-since 3y --export ~/Desktop/cleanup.csv
```

CSV columns: `name, company, title, profile_url, connected_on, last_dm_at, last_dm_preview, days_since_connect,
days_since_dm, cleanup_score, reasons`. `last_dm_preview` is only filled with `--with-preview`.
Group chats don't count as talking unless you pass `--count-group-as-dm`. LinkedIn leaves the profile URL blank for
some connections; those are counted in your total but can't be matched to messages or listed.

**Nothing is removed.** Removing a connection is manual on LinkedIn and can't be undone without a new request they
accept.

### Pass 2: ICP and persona (not built yet)

Pass 1 only knows dates and messages. Pass 2 will filter the candidates by ICP and persona using Syft or Rolodex
definitions. The `--icp` / `--persona` flags and `cleanup.apply_pass2()` are placeholders that say so and exit; nothing
guesses who fits an ICP.

## Act on a list with Syft

The `syft` skill is the one place this plugin sends anything anywhere, and only when you ask it to act
("message these founders", "connect with them"). It says what goes to your Syft workspace and waits for a yes.

```bash
L=skills/linkedin/linkedin.py
python3 $L syft-leads --keywords founder gtm --limit 5     # preview leads from your connections
python3 $L syft-leads --csv list.csv --offset 0 --limit 100 # any CSV with a LinkedIn URL column
```

`syft-leads` prints lead objects for the Syft MCP `enqueue_leads` tool (LinkedIn URL, name, title, company),
deduped, people without a readable profile URL skipped. It sends nothing. The skill then builds a motion with
`build_motion` (review on), adds the people in chunks of 100, and points you to where you approve each message.

| Action | Status |
|---|---|
| DM or connection request to a list | Available |
| Remove connections | Not available yet |
| Score a list against your ICP / personas | Not available yet |

Setup, if you don't have Syft: start a trial at the link above, install the
[Syft Chrome extension](https://chromewebstore.google.com/detail/syft-extension/nchnjpdedckhhfkoafckloolnfliocnd),
then `claude mcp add --transport http syft https://app.syftdata.com/api/mcp` and sign in.

## Rolodex

Cleanup candidate lists are a natural Rolodex import: the people you don't talk to, ranked, next to the people who
engage with you. Extension point: `cleanup.to_rolodex_import(rows)` (not built).

## MCP

The same tools are specified for an MCP server (`ingest_linkedin_export`, `search_shares`, `find_connections`,
`network_profile`, `cleanup_candidates`). Contract and stub: [docs/mcp.md](docs/mcp.md),
`skills/linkedin/mcp_tools.py`. A local ZIP path and the watch folder work today; HTTP upload comes later.

## Upgrading from linkedin-search

- `skills/linkedin-search/linkedin_search.py` still works and forwards every v1 command to `skills/linkedin/linkedin.py`.
- The database stays at `~/.linkedin-search/data.db`, the watch folder at `~/.linkedin-exports/`. Raw tables keep
  the CSV column names. v2 only adds tables (`messages`, `invitations`, `connections_index`, `dm_events`, `last_dm`).
- A v1 database is rebuilt automatically on first use.
- No more virtualenv or `sqlite-utils` install: standard library only.
- Paths can be overridden with `LINKEDIN_EXPORTS_DIR` and `LINKEDIN_DB_PATH`.

## Development

```bash
python3 -m unittest discover -s tests -v
```

Tests build a synthetic export in LinkedIn's file format; no real data needed.

## License

MIT
