# Changelog

All notable changes to the LinkedIn plugin (formerly LinkedIn Search) are documented here.

## [2.0.0] - 2026-09-23

### Changed
- **Renamed from `linkedin-search` to `linkedin`**: a LinkedIn bot for Claude and other agents, not search only.
  Plugin and marketplace name are now `linkedin`.
- CLI moved to `skills/linkedin/linkedin.py`. `skills/linkedin-search/linkedin_search.py` is a thin wrapper, so v1
  commands and callers keep working.
- Standard library only: no virtualenv bootstrap, no `sqlite-utils` install.
- Database rebuilt into a temp file and swapped in, so a failed load no longer leaves an empty database.
- Load progress goes to stderr, so `--json` output stays parseable.
- No-export case: agents get the `ingest --zip` command instead of an unanswerable `input()` prompt.

### Added
- Loads `messages.csv` and `Invitations.csv` from the larger data archive.
- Derived tables: `connections_index` (normalised profile slug, ISO `Connected On`), `dm_events` (per message and
  counterpart, 1:1 vs group, direction), `last_dm` (last / first DM, count, group-only activity per person).
- `ingest [--zip PATH]`: load now and report what loaded, including how many DM counterparts are connections.
- **`linkedin-cleanup` skill**: guided network cleanup (profile → ask which group → narrow and protect → confirm and
  build → offer pass 2). Inputs are Connections + messages only; never removes anyone.
- `network-profile [--json]`: snapshot and presets with live counts.
- `cleanup-candidates`: presets (`old-never-messaged`, `old-quiet`, `never-messaged`, `recent-never-messaged`) or
  thresholds (`--connected-before`, `--connected-after`, `--no-dm-since`, `--never-messaged`, aliases
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
