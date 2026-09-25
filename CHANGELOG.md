# Changelog

All notable changes to the LinkedIn plugin (formerly LinkedIn Search) are documented here.

## [2.2.0] - 2026-09-24

A round of user testing (self-play personas on a real export, graded each round) turned the plugin from a search
tool into answers to the questions people ask about their own LinkedIn.

### Added
- `overview`: a first look in numbers (owed replies, dormant close contacts, stale requests, posting, commenters,
  emails) with the question to ask next.
- `people`: one command for "who do I know" questions. Roles (`--role recruiter`, `marketing-leader`, `marketing`,
  `product-marketing`, `sales-leader`, `sales-manager`, `revops`, `founder`, `executive`, `investor`,
  `engineering-leader`, `people-hr`), titles, companies, company lists (`--company-list` CSV of names or domains,
  per-company counts including zeros), warmth ranking and labels, `--dormant`, `--awaiting-reply` (finished threads
  left out, real conversations first, likely pitches last, `--last-message`), `--they-started` / `--you-started`,
  `--by-company`, spreadsheet (`--export`) and CRM (`--crm`, email-only by default) files.
- `inbound`: who came to you recently (owed replies, requests with notes, new people messaging first, commenters).
- `engagers`: people who commented on your posts and got a reply from you by name, from your own comments.
- `search-messages` (phrases, `--topic pricing|meeting|hiring|intro`, person disambiguation, context line),
  `topics`, `activity` (per month, anchored on the export date).
- `compare-exports`: job changes, new, no longer connected between two exports; dates read from inside each ZIP;
  role / company-list filters on current or previous job; `--only`; `--crm`.
- `invitations-profile` and `pending-invites`: pace, acceptance (settled requests only), note vs no note by month,
  requests to withdraw oldest first with a keep list and skip list; received requests with notes first.
- Your own job search and profile from the export: `people --jobs` (companies of jobs you saved or applied to),
  `--past-companies` (people at companies you used to work at), `--followed-companies`, and `profile` (your
  profile as a Markdown resume). `engagers` also lists people who endorsed your skills; `people --name` says how
  you connected when the request is in the export.
- Finds LinkedIn ZIPs in `~/Downloads` on first run and asks before loading.

### Changed
- Reads current export file names (`Shares_<id>.csv`, `Comments_<id>.csv` with a `Message` column); shares,
  comments and reactions loaded as 0 before.
- `Comments.csv` escapes quotes with a backslash; comments with a quote no longer split into junk rows.
- Everything counts back from the export date, not today. Database schema 7 (rebuilds automatically, with a lock
  so parallel first loads are safe).
- Skills rewritten around the new commands; Syft is offered only for lists of 10+ or when asked, price only if asked.
- Pricing matches Syft's plans: 30-day trial, then Founder Mode ($99) or Pro ($500). Using Syft from Claude needs Pro
  after the trial; a "requires a Syft Pro plan" sign-in answer is handled as a plan limit, not a setup problem.
- Owed replies read the whole last message: meeting / question / favor asks, finished threads (thanks, FYIs,
  handovers), answers to your own question and yeses to your offer kept, likely pitches flagged and listed last.
- Company lists know renames (Snapchat / Snap, Facebook / Meta, Square / Block) and flag "(Acquired by X)" names.

## [2.1.0] - 2026-09-24

### Added
- **`syft` skill**: act on a list through Syft. Outreach (LinkedIn DM or connection request) is available: checks
  for the Syft MCP, says what leaves the machine and waits for a yes, builds a motion with review on
  (`build_motion`), adds the people in chunks of 100 (`enqueue_leads`) and points to where each message is
  approved. Walks through setup (trial link, Chrome extension, `claude mcp add`) when the MCP is missing.
  Removing connections and ICP scoring are listed as not available. One file per action, so the skill grows by
  adding files.
- `syft-leads` command: lead objects for `enqueue_leads` from any CSV with a LinkedIn URL column or from your
  connections (`--title`, `--company`, `--keywords`), deduped, `--offset` / `--limit` for chunking, `--out`.
  A CSV source needs no export loaded.

### Changed
- `linkedin-search` offers the `syft` skill once when the user wants to message or connect with people found.
  `linkedin-cleanup` never offers it (removal is not a Syft action yet).

## [2.0.0] - 2026-09-23

### Changed
- **Renamed from `linkedin-search` to `linkedin`**: a LinkedIn bot for Claude and other agents, not search only.
  Plugin and marketplace name are now `linkedin`. Two skills: `linkedin-search` (search, stats, loading an export)
  and the new `linkedin-cleanup`.
- CLI moved to `skills/linkedin/linkedin.py`. `skills/linkedin-search/linkedin_search.py` is a thin wrapper, so v1
  commands and callers keep working.
- Standard library only: no virtualenv bootstrap, no `sqlite-utils` install.
- Database rebuilt into a temp file and swapped in, so a failed load no longer leaves an empty database.
- Load progress goes to stderr, so `--json` output stays parseable.
- No-export case: agents get the `ingest --zip` command instead of an unanswerable `input()` prompt.

### Added
- Loads `messages.csv` and `Invitations.csv` from the larger data archive.
- Connections with a blank profile URL (LinkedIn hides some) are counted in the total and headroom but reported as
  unlistable, so the cap maths stays right.
- Derived tables: `connections_index` (normalised profile slug, ISO `Connected On`), `dm_events` (per message and
  counterpart, 1:1 vs group, direction), `last_dm` (last / first DM, count, group-only activity per person).
- `ingest [--zip PATH]`: load now and report what loaded, including how many DM counterparts are connections.
- **`linkedin-cleanup` skill**: guided network cleanup (profile → ask which group → narrow and protect → confirm and
  build → offer pass 2). Inputs are Connections + messages only; never removes anyone.
- `network-profile [--json]`: snapshot and presets with live counts.
- `cleanup-candidates`: presets (`old-never-messaged`, `old-quiet`, `never-messaged`, `never-replied`,
  `recent-never-messaged`) or
  thresholds (`--connected-before`, `--connected-after`, `--no-dm-since`, `--never-messaged`, `--never-replied`, aliases
  `--older-than` / `--no-dm-older-than`), `--keep-company`, `--keep-title`, `--only-title`, `--limit`,
  `--count-group-as-dm`, `--with-preview`, `--dry-run`, `--json`, `--export`.
- Pass 2 placeholders (`--icp`, `--persona`, `cleanup.apply_pass2`) that exit with a message; Rolodex extension point
  `cleanup.to_rolodex_import`.
- MCP tool contract and stub (`docs/mcp.md`, `skills/linkedin/mcp_tools.py`).
- `LINKEDIN_EXPORTS_DIR` / `LINKEDIN_DB_PATH` overrides.
- Tests on a synthetic export (`tests/`).

### Compatibility
- Same database path and watch folder; raw tables keep their CSV column names; v2 only adds tables. A v1 database
  is rebuilt automatically on first use.

## [1.0.0] - 2025-12-30

### Added
- Initial release
- Search posts/shares by keyword
- Find connections by title and/or company
- Multi-keyword connection search
- LinkedIn activity statistics
- JIT loading from watch folder (`~/.linkedin-exports/`)
- SQLite caching for fast queries
- Auto-refresh when new export detected
- Dependency install and verify scripts
