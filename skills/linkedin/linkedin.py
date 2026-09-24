#!/usr/bin/env python3
"""LinkedIn bot CLI: ingest your LinkedIn data export, search it, and build network cleanup lists.

Standard library only. Data: ~/.linkedin-exports/*.zip (watch folder) -> ~/.linkedin-search/data.db (SQLite).
Override with LINKEDIN_EXPORTS_DIR / LINKEDIN_DB_PATH.
"""
import csv
import json
import os
import sys
from argparse import ArgumentParser
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import archive  # noqa: E402
import cleanup  # noqa: E402
import search  # noqa: E402


def _print_connections(rows, suffix=""):
    print(f"\nFound {len(rows)} connection(s){suffix}:\n")
    for i, r in enumerate(rows, 1):
        print(f"{i}. {r['first_name']} {r['last_name']}")
        print(f"   {r['position']} at {r['company']}")
        print(f"   {r['url']}\n")


def cmd_search_shares(a):
    rows = search.search_shares(a.query)
    if not rows:
        print(f"No posts found matching '{a.query}'")
        return
    print(f"\nFound {len(rows)} post(s) matching '{a.query}':\n")
    for i, r in enumerate(rows, 1):
        c = r["commentary"]
        print(f"{i}. [{r['date']}]")
        print(f"   {c[:150]}{'...' if len(c) > 150 else ''}")
        print(f"   Link: {r['link']}\n")


def cmd_find_connections(a):
    rows = search.find_connections(a.title, a.company)
    crit = " and ".join(x for x in (f"title '{a.title}'" if a.title else "", f"company '{a.company}'" if a.company else "") if x)
    if not rows:
        print(f"No connections found matching {crit}")
        return
    _print_connections(rows)


def cmd_search_connections_keywords(a):
    rows = search.search_connections_keywords(a.keywords)
    if not rows:
        print(f"No connections found with keywords: {', '.join(a.keywords)}")
        return
    _print_connections(rows, f" matching keywords {a.keywords}")


def cmd_search_comments(a):
    rows = search.search_comments(a.query)
    if not rows:
        print(f"No comments found matching '{a.query}'")
        return
    print(f"\nFound {len(rows)} comment(s) matching '{a.query}':\n")
    for i, r in enumerate(rows, 1):
        c = r["comment"]
        print(f"{i}. [{r['date']}]")
        print(f"   {c[:150]}{'...' if len(c) > 150 else ''}\n")


def cmd_stats(a):
    s = search.stats()
    print("\n=== LinkedIn Statistics ===\n")
    print(f"Posts/Shares: {s['shares']}")
    print(f"Connections: {s['connections']}")
    print(f"Comments: {s['comments']}")
    print(f"Reactions: {s['reactions']}")
    print(f"Messages: {s['messages']}")
    print(f"Invitations: {s['invitations']}\n")


def cmd_ingest(a):
    # ensure_db_current already ran in main(); report what is loaded.
    meta = archive.read_metadata()
    print(json.dumps({k: meta.get(k) for k in (
        "last_loaded_zip", "schema_version", "connections", "messages", "invitations", "shares", "comments",
        "reactions", "connections_indexed", "connections_with_date", "dm_counterparts", "dm_counterparts_connected",
        "earliest_message_at", "latest_message_at")}, indent=2))


def cmd_network_profile(a):
    prof = cleanup.network_profile(a.as_of)
    if a.json:
        print(json.dumps(prof, indent=2))
        return
    m = prof["messages"]
    print(f"\n=== Your network (as of {prof['as_of']}) ===\n")
    print(f"Connections: {prof['connections_total']:,} ({prof['headroom']:,} left before LinkedIn's {prof['cap']:,} cap)")
    for k, v in prof["connected_on_age"].items():
        if v:
            print(f"  connected {k}: {v:,}")
    print(f"Never messaged 1:1: {prof['never_messaged_1to1']:,} (of which only in group chats: {prof['only_group_chats']:,})")
    print(f"Last DM over 1 year ago: {prof['last_dm_over_1_year']:,}  |  over 3 years: {prof['last_dm_over_3_years']:,}")
    print(f"Messaged in the last year: {prof['messaged_in_last_year']:,}")
    if m["loaded"]:
        print(f"Messages loaded: {m['total']:,} ({m['earliest'][:10]} to {m['latest'][:10]})")
    else:
        print("Messages: not in this export. Download the larger data archive, or 'never messaged' means nothing.")
    print("\nCleanup options:")
    for i, p in enumerate(prof["presets"], 1):
        print(f"  {i}. {p['label']}: {p['count']:,}  (--preset {p['preset']})")
    print(f"  {len(prof['presets']) + 1}. Custom: --connected-before 5y --no-dm-since 3y ...\n")


def _criteria(a):
    over = dict(
        connected_before_days=cleanup.parse_duration(a.connected_before or a.older_than),
        connected_after_days=cleanup.parse_duration(a.connected_after),
        no_dm_since_days=cleanup.parse_duration(a.no_dm_since or a.no_dm_older_than),
        never_messaged=a.never_messaged, count_group_as_dm=a.count_group_as_dm,
        keep_company=a.keep_company or [], keep_title=a.keep_title or [], only_title=a.only_title or [],
        limit=a.limit)
    if a.preset:
        return cleanup.Criteria.from_preset(a.preset, **over)
    return cleanup.Criteria(**over)


def cmd_cleanup_candidates(a):
    if a.icp or a.persona:
        print(cleanup.PASS2_MESSAGE, file=sys.stderr)
        sys.exit(2)
    crit = _criteria(a)
    if crit.is_empty():
        print("Pick a group first: --preset <name> or thresholds (--connected-before 5y, --no-dm-since 3y, "
              "--never-messaged). Run `network-profile` to see the options with counts.", file=sys.stderr)
        sys.exit(2)
    rows, summary = cleanup.candidates(crit, a.as_of, with_preview=a.with_preview)
    out = None
    if not a.dry_run and rows:
        out = Path(a.export).expanduser() if a.export else (
            archive.watch_folder() / "cleanup" / f"{summary['as_of']}-{crit.preset or 'custom'}.csv")
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    summary["export"] = str(out) if out else None
    summary["top"] = rows[:10]
    summary["next"] = cleanup.PASS2_MESSAGE + " Offer it to the user as the next step."
    if a.json:
        print(json.dumps(summary, indent=2))
        return
    print(f"\n{summary['count']:,} cleanup candidates: {summary['definition']}")
    if summary["matched_before_limit"] != summary["count"]:
        print(f"  ({summary['matched_before_limit']:,} matched, cut to the top {summary['count']:,})")
    if summary["kept_by_company"] or summary["kept_by_title"]:
        print(f"  kept by your rules: {summary['kept_by_company']:,} by company, {summary['kept_by_title']:,} by title")
    for i, r in enumerate(rows[:10], 1):
        print(f"  {i:>2}. {r['name']} | {r['title']} @ {r['company']} | score {r['cleanup_score']} | {r['reasons']}")
    if a.dry_run:
        print("\n(dry run, nothing written)")
    elif out:
        print(f"\n✓ Wrote {out}")
    print(f"\nNext: {cleanup.PASS2_MESSAGE}\n")


def build_parser():
    p = ArgumentParser(description="LinkedIn bot: ingest, search and clean up your LinkedIn data export.")
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("search-shares", help="search your posts")
    s.add_argument("--query", required=True)
    s = sub.add_parser("find-connections", help="connections by title and/or company")
    s.add_argument("--title", default="")
    s.add_argument("--company", default="")
    s = sub.add_parser("search-comments", help="search your comments")
    s.add_argument("--query", required=True)
    s = sub.add_parser("search-connections-keywords", help="connections matching every keyword")
    s.add_argument("--keywords", nargs="+", required=True)
    sub.add_parser("stats", help="counts per table")

    s = sub.add_parser("ingest", help="load an export ZIP (or the newest in the watch folder) now")
    s.add_argument("--zip", help="path to a LinkedIn export ZIP; copied into the watch folder")

    s = sub.add_parser("network-profile", help="cleanup step 1: snapshot and presets with counts")
    s.add_argument("--json", action="store_true")
    s.add_argument("--as-of", type=date.fromisoformat, default=None, help="YYYY-MM-DD, default today")

    s = sub.add_parser("cleanup-candidates", help="build a cleanup candidate CSV (never removes anyone)")
    s.add_argument("--preset", choices=list(cleanup.PRESETS))
    s.add_argument("--connected-before", help="connected at least this long ago, e.g. 5y, 18m")
    s.add_argument("--older-than", help="alias of --connected-before")
    s.add_argument("--connected-after", help="connected within this window, e.g. 12m")
    s.add_argument("--no-dm-since", help="never messaged, or last DM at least this long ago, e.g. 3y")
    s.add_argument("--no-dm-older-than", help="alias of --no-dm-since")
    s.add_argument("--never-messaged", action="store_true", help="no 1:1 DM ever")
    s.add_argument("--count-group-as-dm", action="store_true", help="a group-chat message counts as talking")
    s.add_argument("--keep-company", action="append", help="never list companies containing this (repeatable)")
    s.add_argument("--keep-title", action="append", help="never list titles containing this (repeatable)")
    s.add_argument("--only-title", action="append", help="only list titles containing this (repeatable)")
    s.add_argument("--limit", type=int, help="keep the top N by score")
    s.add_argument("--with-preview", action="store_true", help="include the last DM's first 140 characters")
    s.add_argument("--export", help="CSV path; default ~/.linkedin-exports/cleanup/<date>-<preset>.csv")
    s.add_argument("--dry-run", action="store_true", help="count and describe, write nothing")
    s.add_argument("--json", action="store_true")
    s.add_argument("--as-of", type=date.fromisoformat, default=None, help="YYYY-MM-DD, default today")
    s.add_argument("--icp", help="pass 2, not implemented (Syft / Rolodex)")
    s.add_argument("--persona", help="pass 2, not implemented (Syft / Rolodex)")
    return p


COMMANDS = {
    "search-shares": cmd_search_shares, "find-connections": cmd_find_connections,
    "search-comments": cmd_search_comments, "search-connections-keywords": cmd_search_connections_keywords,
    "stats": cmd_stats, "ingest": cmd_ingest, "network-profile": cmd_network_profile,
    "cleanup-candidates": cmd_cleanup_candidates,
}


def main(argv=None):
    parser = build_parser()
    a = parser.parse_args(argv)
    if a.command not in COMMANDS:
        parser.print_help()
        return
    if a.command == "cleanup-candidates" and (a.icp or a.persona):
        print(cleanup.PASS2_MESSAGE, file=sys.stderr)
        sys.exit(2)
    try:
        # Progress goes to stderr so --json output stays parseable.
        archive.ensure_db_current(zip_path=getattr(a, "zip", None), force=a.command == "ingest",
                                  log=lambda m: print(m, file=sys.stderr))
    except archive.NoExportError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)
    try:
        COMMANDS[a.command](a)
    except ValueError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
