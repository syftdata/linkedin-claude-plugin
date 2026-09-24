"""MCP tool contract (stub). Not wired to a transport yet: see docs/mcp.md.

Each tool is a plain function over the same loader and queries the CLI uses, returning JSON-serialisable data.
A future MCP server (stdio or HTTP) registers TOOLS and dispatches to these functions. HTTP upload of the ZIP is a
later step; a local path or the watch folder works today.
"""
from datetime import date

import archive
import cleanup
import search

TOOLS = [
    {"name": "ingest_linkedin_export",
     "description": "Load a LinkedIn data export ZIP (the larger data archive) into the local database.",
     "inputSchema": {"type": "object", "properties": {
         "zip_path": {"type": "string", "description": "Local path to the ZIP. Omit to load the newest ZIP in the watch folder."}}}},
    {"name": "search_shares",
     "description": "Search the user's own LinkedIn posts by keyword.",
     "inputSchema": {"type": "object", "required": ["query"], "properties": {
         "query": {"type": "string"}, "limit": {"type": "integer"}}}},
    {"name": "find_connections",
     "description": "Find 1st-degree connections by title and/or company substring.",
     "inputSchema": {"type": "object", "properties": {"title": {"type": "string"}, "company": {"type": "string"}}}},
    {"name": "network_profile",
     "description": "Cleanup step 1: network snapshot and every cleanup preset with its live count.",
     "inputSchema": {"type": "object", "properties": {"as_of": {"type": "string", "format": "date"}}}},
    {"name": "cleanup_candidates",
     "description": "Build a ranked cleanup candidate list from Connections + messages. Never removes anyone. "
                    "Requires a preset or explicit thresholds chosen by the user.",
     "inputSchema": {"type": "object", "properties": {
         "preset": {"type": "string", "enum": list(cleanup.PRESETS)},
         "connected_before": {"type": "string", "description": "e.g. 5y, 18m"},
         "connected_after": {"type": "string"},
         "no_dm_since": {"type": "string"},
         "never_messaged": {"type": "boolean"},
         "count_group_as_dm": {"type": "boolean"},
         "keep_company": {"type": "array", "items": {"type": "string"}},
         "keep_title": {"type": "array", "items": {"type": "string"}},
         "only_title": {"type": "array", "items": {"type": "string"}},
         "limit": {"type": "integer"},
         "as_of": {"type": "string", "format": "date"}}}},
]


def ingest_linkedin_export(zip_path=None):
    stats = archive.ensure_db_current(zip_path=zip_path, force=True, log=lambda m: None)
    return stats or archive.read_metadata()


def search_shares(query, limit=None):
    archive.ensure_db_current(log=lambda m: None)
    return search.search_shares(query, limit)


def find_connections(title="", company=""):
    archive.ensure_db_current(log=lambda m: None)
    return search.find_connections(title, company)


def network_profile(as_of=None):
    archive.ensure_db_current(log=lambda m: None)
    return cleanup.network_profile(date.fromisoformat(as_of) if as_of else None)


def cleanup_candidates(preset=None, connected_before=None, connected_after=None, no_dm_since=None,
                       never_messaged=False, count_group_as_dm=False, keep_company=None, keep_title=None,
                       only_title=None, limit=None, as_of=None):
    archive.ensure_db_current(log=lambda m: None)
    over = dict(connected_before_days=cleanup.parse_duration(connected_before),
                connected_after_days=cleanup.parse_duration(connected_after),
                no_dm_since_days=cleanup.parse_duration(no_dm_since), never_messaged=never_messaged,
                count_group_as_dm=count_group_as_dm, keep_company=keep_company or [], keep_title=keep_title or [],
                only_title=only_title or [], limit=limit)
    crit = cleanup.Criteria.from_preset(preset, **over) if preset else cleanup.Criteria(**over)
    if crit.is_empty():
        raise ValueError("Pick a preset or thresholds first; call network_profile to see the options.")
    rows, summary = cleanup.candidates(crit, date.fromisoformat(as_of) if as_of else None)
    return {"summary": summary, "rows": rows, "next": cleanup.PASS2_MESSAGE}
