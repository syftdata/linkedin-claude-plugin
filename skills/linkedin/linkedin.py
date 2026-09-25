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
import compare  # noqa: E402
import jobs  # noqa: E402
import engagers  # noqa: E402
import invites  # noqa: E402
import overview  # noqa: E402
import people  # noqa: E402
import search  # noqa: E402
import syft_leads  # noqa: E402


def argparse_suppress():
    import argparse
    return argparse.SUPPRESS


def _print_connections(rows, suffix=""):
    print(f"\nFound {len(rows)} connection(s){suffix}:\n")
    for i, r in enumerate(rows, 1):
        print(f"{i}. {r['first_name']} {r['last_name']}")
        print(f"   {r['position']} at {r['company']}")
        print(f"   {r['url']}\n")


def _need_query(a, what):
    if not [q for q in (a.query or []) if q.strip()]:
        raise ValueError(f"Give --query with a word or phrase to find in your {what}. To see what you post about, "
                         f"use `topics`; for everything since a date, `search-shares --query ... --since 6m`.")


def cmd_search_shares(a):
    _need_query(a, "posts")
    rows = search.search_shares(a.query, since_days=cleanup.parse_duration(a.since))
    q = " or ".join(f"'{x}'" for x in a.query)
    if not rows:
        print(f"No posts mention {q}" + (f" in the last {a.since}" if a.since else "") +
              ". Try a related word, `topics` to see what you do post about, or search-comments.")
        return
    shown = rows[:a.limit] if a.limit else rows
    print(f"\n{len(rows)} post(s) mention {q}" + (f" in the last {a.since}" if a.since else "") +
          (f", newest {len(shown)}:" if len(shown) < len(rows) else ":") + "\n")
    for i, r in enumerate(shown, 1):
        print(f"{i}. [{r['date']}] ({r['matched']}) {r['text']}")
        print(f"   {r['link']}\n")


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
    _need_query(a, "comments")
    rows = search.search_comments(a.query, since_days=cleanup.parse_duration(a.since))
    q = " or ".join(f"'{x}'" for x in a.query)
    if not rows:
        print(f"No comments mention {q}. Try a related word, or search-shares.")
        return
    shown = rows[:a.limit] if a.limit else rows
    print(f"\n{len(rows)} comment(s) mention {q}" + (f", newest {len(shown)}:" if len(shown) < len(rows) else ":") + "\n")
    for i, r in enumerate(shown, 1):
        print(f"{i}. [{r['date']}] ({r['matched']}) {r['snippet']}")
        if r.get("link"):
            print(f"   on: {r['link']}")
        print()


def cmd_stats(a):
    s = search.stats()
    print("\n=== LinkedIn Statistics ===\n")
    print(f"Posts/Shares: {s['shares']}")
    print(f"Connections: {s['connections']}")
    print(f"Comments: {s['comments']}")
    print(f"Reactions: {s['reactions']}")
    print(f"Messages: {s['messages']}")
    if s["invitations"]:
        p = invites.profile()
        print(f"Connection requests (last ~12 months): {p['sent']} sent ({p['sent_accepted']} accepted, "
              f"{p['sent_not_accepted']} not accepted), {p['received']} received")
    print()


def cmd_overview(a):
    o = overview.overview()
    if a.json:
        print(json.dumps(o, indent=2))
        return
    print(f"\nYour LinkedIn, {_export_note(o)}:")
    for line in o["lines"]:
        print(f"  - {line['text']}" + (f'  → ask: "{line["ask"]}"' if line.get("ask") else ""))
    print("\nAlso: " + "; ".join(o["more"]) + ".\n")


def cmd_inbound(a):
    days = cleanup.parse_duration(a.since) or 30
    r = overview.inbound(days)
    if a.json:
        print(json.dumps(r, indent=2))
        return
    from datetime import timedelta
    start = (date.fromisoformat(r["export_date"]) - timedelta(days=days)).isoformat() if r["export_date"] else "?"
    print(f"\nWho came to you from {start} to {r['export_date']} ({a.since or '30d'}), {_export_note(r)}:")
    print(f"  {len(r['owed_replies']):,} people you've talked with wrote last and are waiting on you "
          f"(finished-looking threads left out)")
    for p in r["owed_replies"][:5]:
        who = f"{p['title']} @ {p['company']}" if p["connection"] == "yes" else "not a connection"
        print(f"    - {p['name']} | {who} | since {p['last_dm_at']}" + (f", asks: {p['asks']}" if p["asks"] else "")
              + (", likely a pitch" if p["likely_pitch"] else ""))
    print(f"  {len(r['requests']):,} asked to connect and you haven't accepted ({r['requests_with_note']} with a note)")
    for q in r["requests"][:3]:
        print(f"    - {q['name']} | {q['sent_at']}" + (" | with a note" if q["note"] else ""))
    print(f"  {len(r['first_messages']):,} new people messaged you first ({r['first_messages_unanswered']} you haven't answered)")
    for f in r["first_messages"][:3]:
        who = f"{f['title']} @ {f['company']}" if f["title"] else "not a connection"
        print(f"    - {f['name']} | {who} | {f['first_message']}" + ("" if f["replied"] else " | not answered"))
    if r["commenters_total"]:
        never = [c for c in r["commenters"] if not c["dms"] and not c.get("group_messages")]
        print(f"  {r['commenters_total']:,} commented on your posts and got a reply from you"
              + (f" ({len(never)} never messaged)" if never else "")
              + (f"; you also replied to {len(r['non_connections'])} who aren't connections: "
                 + "; ".join(r["non_connections"][:5]) if r.get("non_connections") else ""))
        for c in (never + [c for c in r["commenters"] if c not in never])[:3]:
            dm = f"{c['dms']} DMs" if c["dms"] else ("group chats only" if c.get("group_messages") else "never DMed")
            print(f"    - {c['name']} | {c['title']} @ {c['company']} | {c['posts']} post(s), last {c['last_reply']} | {dm}")
    print("\nNot in the export: people who only reacted, commenters you didn't reply to, profile views.\n")


def cmd_engagers(a):
    keep = None
    if a.role or a.title:
        keep = lambda r: (any(people.role_match(r["title"], x) for x in (a.role or []))
                          or any(people.has(r["title"], t) for t in (a.title or [])))
    since = cleanup.parse_duration(a.since)
    rows, s = engagers.commenters(since_days=since, keep=keep)
    endorsed = engagers.endorsers(since_days=since)
    if keep:
        endorsed = [e for e in endorsed if keep(e)]
    s["endorsers"] = endorsed
    if a.export and rows:
        out = Path(a.export).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=[k for k in rows[0] if k != "slug"], extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        s["export"] = str(out)
    if a.json:
        print(json.dumps(s | {"shown": min(len(rows), a.limit or len(rows)), "commenters": rows[:a.limit or None]},
                         indent=2))
        return
    window = f" in the {a.since} before your export ({s['as_of']})" if a.since else f" (as of your {s['as_of']} export)"
    who = "people" if len(rows) != 1 else "person"
    role = " or ".join(x.replace("-", " ") for x in (a.role or [])) or " or ".join(a.title or [])
    if role:
        print(f"\n{len(rows):,} of the {s['all_commenters']:,} people who commented on your posts{window} and got a reply "
              f"from you by name match {role} ({s['replies_by_name']:,} replies on {s['posts']:,} of your "
              f"{s['posts_in_window']:,} posts).")
    else:
        print(f"\n{len(rows):,} {who} commented on your posts{window} and got a reply from you by name "
              f"({s['replies_by_name']:,} replies on {s['posts']:,} of your {s['posts_in_window']:,} posts).")

    def line(r):
        dm = f"{r['warmth']}, {r['dms']} DM{'s' if r['dms'] != 1 else ''}" if r["dms"] else \
            (f"group chats only ({r['group_messages']} messages)" if r["group_messages"] else "never messaged")
        post = (f", last on \"{r['last_post_opener']}\" (post {r['last_post_date']}, you replied {r['last_reply']})"
                if r["last_post_opener"] else f" (you replied {r['last_reply']})")
        return f"{r['name']} | {r['title']} @ {r['company']} | {r['posts']} post(s){post} | {dm}"
    never = [r for r in rows if not r["dms"] and not r["group_messages"]]
    if never:
        print(f"  never messaged ({len(never):,}), the follow-ups:")
        for r in never[:25]:
            print(f"    - {line(r)}")
        if len(never) > 25:
            print(f"    ... and {len(never) - 25} more (--export for all)")
    if s["group_chat_only"]:
        print(f"  group chats only (you've talked, not 1:1): {s['group_chat_only']:,}")
    others = [r for r in rows if r not in never]
    if others:
        print(f"  people you've messaged, most posts first:" if never else "  most posts first:")
    for i, r in enumerate(others[:a.limit or None], 1):
        print(f"  {i:>2}. {line(r)}")
    if s.get("non_connection_count") and not role:
        print(f"  you also replied by name to {s['non_connection_count']:,} people who aren't connections (send them a "
              f"request?): " + "; ".join(s["non_connections"][:8]))
    if s["top_posts"] and s["top_posts"][0]["people"] >= 2:
        print("  posts the most of them commented on: " +
              "; ".join(f"{p['date']} \"{p['opener']}\" ({p['people']})" for p in s["top_posts"][:3]))
    if endorsed:
        cold = sum(1 for e in endorsed if not e["dms"])
        print(f"  also {len(endorsed):,} endorsed your skills{' in that window' if a.since else ''} "
              f"({cold:,} never messaged), newest: " + ", ".join(e["name"] for e in endorsed[:3]))
    if s.get("export"):
        print(f"\n✓ Wrote {len(rows):,} to {s['export']}")
    print(f"\nNote: {s['caveat']}\n")


def cmd_profile(a):
    text, missing = jobs.resume()
    if a.export:
        out = Path(a.export).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
        print(f"✓ Wrote your profile as Markdown to {out}" + (f" (not in this export: {', '.join(missing)})" if missing else ""))
        return
    print(text)
    if missing:
        print(f"(not in this export: {', '.join(missing)})")


def cmd_info(a):
    meta = archive.read_metadata()
    exported = invites.export_date()
    print(json.dumps({"export_file": meta.get("last_loaded_zip"), "export_made_about": str(exported) if exported else None,
                      "loaded_at": meta.get("loaded_at"), **{k: meta.get(k) for k in (
                          "connections", "messages", "invitations", "shares", "comments", "reactions",
                          "connections_without_url", "earliest_message_at", "latest_message_at")}}, indent=2))


def cmd_ingest(a):
    # ensure_db_current already ran in main(); report what is loaded and where the copies live.
    meta = archive.read_metadata()
    if not a.json:
        ed = invites.export_date()
        n = lambda k: f"{int(meta[k]):,}" if str(meta.get(k, "")).isdigit() else "?"
        print(f"Loaded {n('connections')} connections, {n('messages')} messages, "
              f"{n('invitations')} connection requests and {n('shares')} posts from your export "
              f"(made about {ed}).\nA copy of the ZIP is in {archive.watch_folder()} and the database is "
              f"{archive.db_path()}; both stay on this machine. To remove everything, delete those two.")
        return
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
    if prof["connections_without_url"]:
        print(f"  {prof['connections_without_url']:,} have no profile URL in the export and can't be matched or listed")
    for k, v in prof["connected_on_age"].items():
        if v:
            print(f"  connected {k}: {v:,}")
    print(f"Never messaged 1:1: {prof['never_messaged_1to1']:,} (of which only in group chats: {prof['only_group_chats']:,})")
    print(f"Last DM over 1 year ago: {prof['last_dm_over_1_year']:,}  |  over 3 years: {prof['last_dm_over_3_years']:,}")
    print(f"Messaged in the last year: {prof['messaged_in_last_year']:,}  |  they wrote, you never replied: {prof['never_replied']:,}")
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
        never_messaged=a.never_messaged, never_replied=a.never_replied, count_group_as_dm=a.count_group_as_dm,
        keep_company=a.keep_company or [], keep_title=a.keep_title or [], only_title=a.only_title or [],
        keep_company_list=people.load_company_list(a.keep_company_list) if a.keep_company_list else set(),
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
    if summary["kept_by_company"] or summary["kept_by_title"] or summary["kept_by_list"]:
        print(f"  kept by your rules: {summary['kept_by_company']:,} by company, {summary['kept_by_title']:,} by title, "
              f"{summary['kept_by_list']:,} by your company list")
    for i, r in enumerate(rows[:10], 1):
        print(f"  {i:>2}. {r['name']} | {r['title']} @ {r['company']} | score {r['cleanup_score']} | {r['reasons']}")
    if a.dry_run:
        print("\n(dry run, nothing written)")
    elif out:
        print(f"\n✓ Wrote {out}")
    print(f"\nNext: {cleanup.PASS2_MESSAGE}\n")


def cmd_invitations_profile(a):
    p = invites.profile(a.as_of)
    if a.json:
        print(json.dumps(p, indent=2))
        return
    if not p["sent"] and not p["received"]:
        print("No Invitations.csv in this export. It comes with the larger data archive.")
        return
    w = p["window"]
    start = w.get("covered_from") or w["first"]
    print(f"\n=== Connection requests, {start} to {w['last']} (export made about {p['export_date']}) ===\n")
    print(f"Sent {p['sent']:,}: {p['sent_accepted']:,} accepted, {p['sent_not_accepted']:,} not accepted. "
          f"Acceptance {p['acceptance_rate_pct']}% (the {p['settled_sent']:,} at least 30 days old)")
    wn, nn = p["with_note"], p["without_note"]
    if wn["sent"] and nn["sent"]:
        print(f"  with a note: {wn['accepted_pct']}% of {wn['sent']:,}  |  without: {nn['accepted_pct']}% of {nn['sent']:,}")
        for m in p["note_vs_no_note_by_month"]:
            print(f"    {m['month']}: note {m['with_note_pct']}% of {m['with_note_sent']}, "
                  f"no note {m['without_note_pct']}% of {m['without_note_sent']}")
    print("  not accepted, by age: " + ", ".join(f"{k} {v:,}" for k, v in p["not_accepted_by_age"].items() if v))
    pw = p["sent_per_week"]
    print(f"  busiest week: {pw['busiest_week_count']} sent (week of {pw['busiest_week']}), "
          f"last 8 weeks average {pw['average_last_8_weeks']}/week")
    print(f"Received {p['received']:,}: {p['received_not_connected']:,} you haven't accepted")
    print("\n" + "\n".join("Note: " + c for c in p["caveats"]) + "\n")


def cmd_pending_invites(a):
    if a.keep_company_list:
        raise ValueError("Requests have no company in the export, so a company or domain list can't match them. "
                         "Use --keep-list with a contacts export that has LinkedIn URLs or first / last names "
                         "(e.g. HubSpot → Contacts → Export).")
    keep_slugs, keep_names = invites.load_keep_list(a.keep_list) if a.keep_list else (set(), set())
    rows, summary = invites.pending(cleanup.parse_duration(a.older_than), a.direction, a.exclude_messaged,
                                    a.limit, a.as_of, keep_slugs=keep_slugs, keep_names=keep_names)
    out = None
    if a.export and rows:
        out = Path(a.export).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    summary["export"] = str(out) if out else None
    summary["top"] = rows[:10]
    if a.json:
        print(json.dumps(summary, indent=2))
        return
    what = "requests you sent that were never accepted" if a.direction == "sent" else \
        "requests you received and haven't accepted"
    print(f"\n{summary['matched']:,} {what}" + (f", {a.older_than}+ old" if a.older_than else "") +
          f" (as of the export, {summary['export_date']})" +
          (f", cut to the oldest {summary['count']:,}" if summary["count"] != summary["matched"] else ""))
    if summary["over_180_days"]:
        print(f"  {summary['over_180_days']:,} of them are 180+ days old")
    if a.direction == "received" and rows:
        noted = sum(1 for r in rows if r["had_note"] == "yes")
        print(f"  {noted:,} came with a note" + (" (listed first, newest first)" if noted else ""))
    show = rows if a.limit == 0 else rows[:a.limit or 10]
    if len(show) < len(rows):
        print(f"  showing {len(show)} of {len(rows):,} (--limit 0 for all, --export for a file)")
    for i, r in enumerate(show, 1):
        note = f" | note: \"{r['note'][:90]}\"" if a.direction == "received" and r["note"] and a.with_note else \
            f" | note: {r['had_note']}"
        print(f"  {i:>2}. {r['name']} | sent {r['sent_at']} | {r['days_waiting']} days{note}")
    if a.direction == "received" and rows:
        print("\nThe export has no title or company for people who sent you a request; open their profile to check. "
              "'Not accepted' also includes requests you declined.")
    if summary["skip"]:
        n = len(summary["skip"])
        print(f"\nSkip {'this person' if n == 1 else f'these {n}'} (not listed above):")
        for r in summary["skip"][:20]:
            print(f"  - {r['name']} | sent {r['sent_at']} | {r['why']} | {r['profile_url']}")
    if out:
        print(f"\n✓ Wrote {out}")
    if a.direction == "sent":
        print("\nWithdraw on LinkedIn: My Network → Manage → Sent (oldest at the bottom). Nothing here withdraws.\n")


def _company_list(a):
    """--company-list CSV plus the export's own lists: --jobs (saved / applied / dream companies),
    --followed-companies, --past-companies (where you worked). Remembers why each company is on the list."""
    out = people.load_company_list(a.company_list) if getattr(a, "company_list", None) else []
    why, sources = {}, []
    picks = [("jobs", lambda: jobs.job_companies(since=_since_iso(getattr(a, "jobs_since", None))),
              "companies from jobs you saved or applied to"),
             ("followed_companies", lambda: [e for e in jobs.job_companies(include_followed=True)
                                             if e["why"] == "you follow them"], "companies you follow"),
             ("past_companies", jobs.past_companies, "companies you used to work at")]
    for flag, get, what in picks:
        if getattr(a, flag, False):
            entries = get()
            dated = sorted(e["when"] for e in entries if e["when"])
            span = ""
            if dated and flag != "past_companies":
                span = f" ({_month(dated[0])} – {_month(dated[-1])}" + (
                    ", all over 6 months old: probably not your current search" if _months_old(dated[-1]) > 6 else "") + ")"
            if flag == "jobs" and not entries and getattr(a, "jobs_since", None):
                every = jobs.job_companies()
                newest = max((e["when"] for e in every if e["when"]), default="")
                raise ValueError(f"No jobs saved or applied to in the {a.jobs_since} before your export"
                                 + (f"; the newest is from {_month(newest)}." if newest else ".")
                                 + " Drop --jobs-since to use them all, or pass your current targets with --company-list.")
            sources.append(f"{len(entries):,} {what}{span}")
            lst, w = jobs.as_company_list(entries)
            out += lst
            why.update(w)
    a._list_why, a._list_sources = why, sources
    if sources and not out:
        raise ValueError("Your export has none of those (" + "; ".join(sources) + "). Pass your own list with "
                         "--company-list companies.csv.")
    return out


def _month(iso):
    try:
        return date.fromisoformat(iso[:10]).strftime("%b %Y")
    except ValueError:
        return iso


def _months_old(iso):
    anchor = invites.export_date() or date.today()
    try:
        return (anchor - date.fromisoformat(iso[:10])).days / 30.4
    except ValueError:
        return 0


def _since_iso(text):
    days = cleanup.parse_duration(text) if text else None
    if not days:
        return None
    from datetime import timedelta
    anchor = invites.export_date() or date.today()
    return (anchor - timedelta(days=days)).isoformat()


def _filters(a):
    labels = {k: v for k, v in (("dm_within_days", a.dm_since), ("quiet_days", a.quiet_since),
                                 ("connected_within_days", a.connected_since),
                                 ("connected_before_days", a.connected_before)) if v}
    return people.Filters(
        roles=a.role or [], labels=labels,
        titles=a.title or [], companies=a.company or [], keywords=a.keywords or [], title_only=a.title_only,
        not_titles=a.not_title or [], not_companies=a.not_company or [],
        company_list=_company_list(a),
        not_company_list=people.load_company_list(a.exclude_company_list) if a.exclude_company_list else [],
        names=a.name or [],
        messaged=True if a.messaged else (False if a.never_messaged else None), two_way=a.two_way,
        only_they_wrote=a.only_they_wrote, awaiting_reply=a.awaiting_reply, include_closed=a.include_closed,
        has_email=a.has_email,
        dm_within_days=cleanup.parse_duration(a.dm_since), quiet_days=cleanup.parse_duration(a.quiet_since),
        dormant=a.dormant,
        started_by="you" if a.you_started else ("them" if a.they_started else None),
        connected_within_days=cleanup.parse_duration(a.connected_since),
        connected_before_days=cleanup.parse_duration(a.connected_before), sort=a.sort)


def _add_filters(s):
    g = s.add_argument_group("who (connections)")
    g.add_argument("--role", action="append", choices=list(people.ROLES),
                   help="common title wordings for a role, e.g. recruiter, marketing-leader (repeatable)")
    g.add_argument("--title", action="append", help="title contains this; repeat for ANY of several")
    g.add_argument("--company", action="append", help="company contains this; repeat for ANY of several")
    g.add_argument("--keywords", nargs="+", help="ALL of these in title + company (or title only, --title-only)")
    g.add_argument("--title-only", action="store_true", help="match --keywords against the title only")
    g.add_argument("--not-title", action="append", help="leave out titles containing this")
    g.add_argument("--not-company", action="append", help="leave out companies containing this")
    g.add_argument("--company-list", help="CSV of companies or domains: only people there (e.g. target accounts)")
    g.add_argument("--exclude-company-list", help="CSV of companies or domains to leave out (e.g. customers)")
    g.add_argument("--jobs", action="store_true",
                   help="companies from your own job search in the export: jobs you saved or applied to")
    g.add_argument("--jobs-since", help="with --jobs: only jobs saved or applied to in this window, e.g. 6m")
    g.add_argument("--followed-companies", action="store_true", help="companies you follow on LinkedIn")
    g.add_argument("--past-companies", action="store_true",
                   help="companies you used to work at (from your own profile): likely former colleagues")
    g.add_argument("--messaged", action="store_true", help="only people you've written to 1:1")
    g.add_argument("--never-messaged", action="store_true", help="only people with no 1:1 messages either way")
    g.add_argument("--two-way", action="store_true", help="only people where both of you have written")
    g.add_argument("--dm-since", help="last 1:1 DM within this window, e.g. 12m")
    g.add_argument("--quiet-since", help="last 1:1 DM at least this long ago, e.g. 12m (lost touch: reconnect)")
    g.add_argument("--dormant", action="store_true",
                   help="reconnect list: close once (5+ messages each way), quiet for over a year")
    g.add_argument("--you-started", action="store_true", help="you sent the first 1:1 message")
    g.add_argument("--they-started", action="store_true", help="they sent the first 1:1 message (often selling)")
    g.add_argument("--awaiting-reply", action="store_true",
                   help="they sent the last 1:1 message (threads ending in a thanks / emoji / 'booked' are left out)")
    g.add_argument("--include-closed", action="store_true", help="with --awaiting-reply: keep threads that read as finished")
    g.add_argument("--only-they-wrote", action="store_true", help="they wrote to you and you never replied (mostly pitches)")
    g.add_argument("--name", action="append", help="person's name contains this (repeatable)")
    g.add_argument("--has-email", action="store_true", help="only people whose email is in the export")
    g.add_argument("--connected-since", help="connected within this window, e.g. 6m")
    g.add_argument("--connected-before", help="connected at least this long ago, e.g. 5y")
    g.add_argument("--sort", choices=people.SORTS,
                   help="warm (recent two-way conversations first), recent (newest connections), talked (most "
                        "DMs ever), last-dm, name; default warm (owed replies: real conversations and asks first; "
                        "--dormant / --quiet-since: talked)")


def _export_note(summary):
    ed = summary.get("export_date")
    if not ed:
        return ""
    age = (date.today() - date.fromisoformat(ed)).days
    return f"as of your export ({ed}" + (f", {age} days old: anything since isn't here)" if age > 7 else ")")


def cmd_people(a):
    f = _filters(a)
    rows, summary = people.select(f, a.as_of)
    if f.awaiting_reply and f.two_way:
        from dataclasses import replace
        wide_rows, wide = people.select(replace(f, two_way=False), a.as_of)
        one_way = [p for p in wide_rows if not p["out_count"]]
        summary["one_way_left_out"] = len(one_way)
        summary["one_way_pitches"] = sum(1 for p in one_way if people.likely_pitch(p))
    if getattr(a, "_list_why", None):
        for p in rows:
            p["target_why"] = a._list_why.get(p.get("target", ""), "")
    if a.crm and a.export:
        with_email = [p for p in rows if p.get("email")]
        linkable = [p for p in rows if p.get("email") or p["profile_url"]]
        summary["crm"] = {"with_email": len(with_email), "without_email": len(linkable) - len(with_email),
                          "work_emails": sum(1 for p in with_email if people.email_type(p["email"]) == "work"),
                          "personal_emails": sum(1 for p in with_email if people.email_type(p["email"]) == "personal"),
                          "no_email_no_url_dropped": len(rows) - len(linkable),
                          "exported": len(linkable) if a.all else len(with_email)}
        rows = linkable if a.all else with_email
    limit = a.limit if not (a.export and a.crm and a.limit == 20) else 5      # a CRM export needs no long list
    shown = [people.row_out(p, text=a.last_message) for p in (rows[:limit] if limit else rows)]
    if a.export and not rows:
        summary["export"] = None
        print("Nothing matched, so no file was written.", file=sys.stderr)
    if a.export and rows:
        out = Path(a.export).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        shape = people.crm_row if a.crm else \
            (lambda p: people.sheet_row(p, with_target=bool(f.company_list), with_role=f.roles if len(f.roles) > 1 else False))
        with open(out, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(shape(rows[0]).keys()))
            w.writeheader()
            w.writerows(shape(p) for p in rows)
        summary["export"] = str(out)
    groups = people.by_company(rows, a.limit, f.company_list) if a.by_company else None
    if a.json:
        print(json.dumps(summary | {"shown": len(shown), "people": shown} | ({"by_company": groups} if groups else {}),
                         indent=2))
        return
    s = summary
    noun = "person" if s["total"] == 1 else "people"
    nc = s.get("not_connections") or 0
    split = f" ({s['total'] - nc:,} connections + {nc:,} not connected)" if nc else ""
    print(f"\n{s['total']:,} {noun}{split}: {s['definition']} {_export_note(s)}")
    redundant = f.awaiting_reply and f.two_way
    if not redundant and (f.uses_messages() or f.roles or f.titles or s["group"] != s["total"]):
        of = f"of all {s['group']:,} connections" if s["group_is_everyone"] else f"of the {s['group']:,} in this group"
        print(f"  {of}: you've written to {s['group_you_wrote_to']:,}, {s['group_two_way']:,} both ways, "
              f"{s['group_only_they_wrote']:,} only wrote to you, {s['group_never_messaged']:,} never messaged")
    if f.awaiting_reply and s["total"] and not f.two_way:
        print(f"  of these {s['total']:,}: {s['total'] - s['inbound_only']:,} are conversations you're part of, "
              f"{s['inbound_only']:,} are inbound only (you never wrote; mostly pitches)"
              + (f"; {s['not_connections']:,} " + ("isn't a connection" if s["not_connections"] == 1 else
                                                     "aren't connections") if s["not_connections"] else ""))
    if s.get("by_role"):
        tops = []
        for r, n in s["by_role"].items():
            names = [p["name"] for p in rows if people.role_match(p["title"], r)][:2]
            tops.append(f"{r.replace('-', ' ')} {n:,}" + (f" (warmest: {', '.join(names)})" if names else ""))
        print("  by role: " + "; ".join(tops))
    if s.get("one_way_left_out"):
        print(f"  +{s['one_way_left_out']:,} wrote to you and you never answered (left out by --two-way; "
              f"{s['one_way_pitches']:,} of them look like pitches); drop --two-way to see them")
    if s.get("likely_pitches"):
        print(f"  {s['likely_pitches']:,} look like pitches (they opened with a pitch line, or sell for a living): listed last")
    if f.awaiting_reply and s["total"] and s.get("export_date"):
        age = (date.today() - date.fromisoformat(s["export_date"])).days
        if age > 14:
            print(f"  your export is {age} days old: some of these may be answered or scheduled since; check each "
                  f"thread on LinkedIn before replying, and treat dates they proposed as possibly passed")
    if s.get("hidden_finished_threads"):
        print(f"  left out {s['hidden_finished_threads']:,} threads that read as finished (a thanks, an emoji, a "
              f"short reply with no question; --include-closed to see them)")
    if "marketing-leader" in f.roles and "product-marketing" not in f.roles:
        pmm = sum(1 for p in people.load_people() if people.role_match(p["title"], "product-marketing"))
        if pmm:
            print(f"  ({pmm:,} product marketers are not in marketing-leader; add --role product-marketing for them)")
    if getattr(a, "_list_sources", None):
        print("  list: " + "; ".join(a._list_sources))
    if s.get("per_listed_company"):
        zero = [c["company"] for c in s["per_listed_company"] if not c["people"]]
        hits = [c for c in s["per_listed_company"] if c["people"]]
        print("  your list: " + "; ".join(f"{c['company']} {c['people']}" for c in hits[:20])
              + (f" (+{len(hits) - 20} more)" if len(hits) > 20 else ""))
        loose = [f"{c['company']} → {' / '.join(m for m in c['matched_as'] if people.normalize_company(m) != people.normalize_company(c['company']))}"
                 for c in hits if any(people.normalize_company(m) != people.normalize_company(c["company"]) for m in c["matched_as"])]
        if loose:
            print("  matched by name start (check these): " + "; ".join(loose[:10]))
        similar = [f"{c['company']} → " + " / ".join(f"{k} ({n})" for k, n in c["similar"])
                   for c in s["per_listed_company"] if c.get("similar")]
        if similar:
            print("  similar names in your network, not counted (add them to the list if they're the same company): "
                  + "; ".join(similar[:8]))
        if zero:
            there = {c["company"]: c["connections_there"] for c in s["per_listed_company"]}
            if f.roles or f.titles or f.uses_messages():
                other = [f"{c} ({there[c]})" for c in zero if there[c]]
                none = [c for c in zero if not there[c]]
                if other:
                    print(f"  no one matching at {len(other)} of them, but you have other connections there: " + "; ".join(other))
                if none:
                    print(f"  no connections at all at {len(none)} of them: " + "; ".join(none))
            else:
                print(f"  no connections at {len(zero)} of them: " + "; ".join(zero))
    elif s.get("companies"):
        print("  companies: " + "; ".join(f"{c} {n}" for c, n in s["companies"]))
    if s.get("crm"):
        c = s["crm"]
        print(f"  CRM file: {c['with_email']:,} have an email ({c['work_emails']:,} work, {c['personal_emails']:,} personal), "
              f"{c['without_email']:,} don't (LinkedIn only exports emails people chose to share); wrote {c['exported']:,}" +
              (" (including the ones without an email: HubSpot dedupes by email, so those rows can duplicate "
               "contacts you already have, and importing the file twice duplicates them all)" if a.all else
               " with an email (--all adds the rest; your CRM can't dedupe them without an email)") +
              (f"; dropped {c['no_email_no_url_dropped']} with neither" if c["no_email_no_url_dropped"] else ""))
    if not rows:
        hint = (f"no one with {' or '.join(r.replace('-', ' ') for r in f.roles)} titles here (other titles may be)" if f.roles else
                "try a role (--role recruiter), a shorter word, or drop a filter")
        print(f"  Nothing matched: {hint}.")
        return
    if groups:
        print(f"  by company (warmest contact first):")
        for g in groups:
            warm = f" | warmest: {g['warmest']} ({g['warmest_title']}, last DM {g['warmest_last_dm'][:7]})" if g["warmest"] else ""
            n = "person" if g["people"] == 1 else "people"
            print(f"  - {g['company']}: {g['people']} {n}, you've written to {g['you_wrote_to']}, "
                  f"{g['two_way']} both ways{warm}")
            if len(rows) <= 30:
                print("      " + "; ".join(g["names"]))
    else:
        pool = len(rows)
        more = (f" of the {pool:,} in the file" if s.get("crm") else
                f" of {pool:,} (--limit 0 for all, --export for a file)") if pool > len(shown) else ""
        print(f"  showing {len(shown)}{more}, {s['sorted_by']}:")
        for i, p in enumerate(shown, 1):
            dm = (f"{p['warmth']}, {p['dms']} DM{'s' if p['dms'] != 1 else ''} ({p['you_sent']} you / {p['they_sent']} them), "
                  f"last {p['last_dm_at'][:7]}"
                  if p["dms"] else ("never messaged 1:1, " + f"{p['group_messages']} group-chat messages"
                                    if p.get("group_messages") else "never messaged"))
            if p["they_wrote_last"]:
                dm += (f", they wrote last on {p['last_dm_at']}" + (f" (asks: {p['asks']})" if p["asks"] else "")
                       + (f", {'you' if p['opened'] == 'you' else 'they'} opened" if p["opened"] else "")) \
                    if f.awaiting_reply else ", they wrote last"
            elif p["you_wrote_last"] is not None and p["they_sent"]:
                dm += f", you wrote last ({p['you_wrote_last']} days ago, no reply)"
            if p["likely_pitch"] and f.awaiting_reply:
                dm += ", likely a pitch"
            if p.get("reads_finished") and f.include_closed:
                dm += " (reads finished)"
            who = f"{p['title']} @ {p['company']}" if p["connection"] == "yes" else "(not a connection)"
            link = p["profile_url"] or "(no profile URL in export)"
            print(f"  {i:>2}. {p['name']} | {who} | {dm} | {link}")
            if f.names and p["how_connected"]:
                print(f"      how you connected: {p['how_connected']}")
            if a.last_message and p["last_message"]:
                print(f"      last message ({'them' if p['they_wrote_last'] else 'you'}): {' '.join(p['last_message'].split())[:200]}")
    if s.get("export"):
        print(f"\n✓ Wrote {len(rows):,} to {s['export']}")
    print()


def cmd_search_messages(a):
    if not (a.query or a.person or a.person_url or a.topic):
        raise ValueError("Give --query (words in the message), --topic, and/or --person (part of their name).")
    urls = a.person_url or [""]
    if a.json and len(urls) > 1:
        print(json.dumps([search.search_messages(a.query or [], a.person, cleanup.parse_duration(a.since), a.limit,
                                                 a.include_groups, u, a.topic) | {"person_url": u} for u in urls],
                         indent=2))
        return
    for u in urls:
        _search_messages_one(a, u)


def _search_messages_one(a, person_url):
    res = search.search_messages(a.query or [], a.person, cleanup.parse_duration(a.since), a.limit,
                                 a.include_groups, person_url, a.topic)
    if a.json:
        print(json.dumps(res, indent=2))
        return
    if res["ambiguous"]:
        print(f"\n{len(res['people'])} different people match '{a.person}'. Which one? (pass a fuller --person or --person-url)")
        for e in res["people"][:10]:
            t = f"{e['title']} @ {e['company']}" if e.get("title") else "not a current connection"
            n = "message" if e["messages"] == 1 else "messages"
            hits = f", {e['hits']} mention it" if res.get("searched") else ""
            print(f"  - {e['name']} | {t} | {e['messages']} {n}{hits}, last {e['last']} | {e['profile_url']}")
        print()
        return
    what = " and ".join(x for x in ((f"about {a.topic}" if a.topic else "") +
                                     (" or " if a.topic and a.query else "") +
                                     (" or ".join(f"'{q}'" for q in a.query) if a.query else ""),
                                     f"with {a.person or person_url}" if (a.person or person_url) else "") if x)
    rows = res["messages"]
    if res.get("narrowed_from"):
        print(f"\n{res['narrowed_from']} people named '{a.person}' in your DMs; only {res['people'][0]['name']} matched those words (the others may use different ones).")
    print(f"\n{res['total']:,} 1:1 message(s) {what}" + (f" in the last {a.since}" if a.since else "") +
          ("" if a.include_groups else " (group chats left out)") +
          (f", newest {len(rows)}:" if res["total"] > len(rows) else ":"))
    for r in rows:
        who = f"you → {r['with']}" if r["from"] == "you" else f"{r['from']} → you"
        print(f"  [{r['date']}] {who}: {r['snippet']}")
        if r.get("before"):
            print(f"      ↳ the message before it: {r['before']}")
    if not rows and a.query:
        print("  Nothing. Try other words for the same thing, or --topic pricing / meeting / hiring / intro.")
    print()


def cmd_topics(a):
    t = search.topics(cleanup.parse_duration(a.since), a.top)
    if a.json:
        print(json.dumps(t, indent=2))
        return
    if not t["posts"]:
        print("No posts in that window.")
        return
    print(f"\nIn your {t['posts']} post(s)" + (f" since {t['since']}" if t["since"] else "") +
          ", the words and phrases in the most posts (common words removed):")
    print("  words:   " + ", ".join(f"{w} {c}" for w, c in t["words"]))
    if t["phrases"]:
        print("  phrases: " + ", ".join(f"{w} {c}" for w, c in t["phrases"]))
    print("  (counts are posts, not mentions; a post can count under several words)\n")


def cmd_activity(a):
    act = search.activity(a.months)
    if a.json:
        print(json.dumps(act, indent=2))
        return
    t = act["totals"]
    print(f"\nAll time in this export: {t['posts']:,} posts, {t['comments']:,} comments and "
          f"{t['reactions_given']:,} reactions by you (export made about {act['export_date']})\n")
    dash = lambda v: "-" if v is None else v
    print("            ------- by you -------- | --------------- connections and requests ---------------")
    print("  month     posts  comments  reactions | new conn.  req. sent  req. in  new people DMed you first")
    for m in act["months"]:
        flag = "  (partial: export date)" if m["partial"] else ""
        print(f"  {m['month']}  {m['posts']:>5}  {m['comments']:>8}  {m['reactions']:>9} | {m['new_connections']:>9}"
              f"  {dash(m['requests_sent']):>9}  {dash(m['requests_received']):>7}  {m['new_people_messaged_you']:>25}{flag}")
    if act["recent_posts"]:
        print("\nLatest posts:")
        for p in act["recent_posts"]:
            print(f"  [{p['date']}] {p['text']}  {p['link']}")
    since = f"Request history starts {act['requests_since']} ('-' = no data that month)." if act["requests_since"] \
        else "No request history in this export."
    print(f"\nNote: {act['note']} {since}")
    print("Not in the export: " + "; ".join(act["not_in_export"]) + ".\n")


def cmd_compare_exports(a):
    old = a.old
    if not old:
        loaded = archive.read_metadata().get("last_loaded_zip")
        others = compare.other_exports(exclude=loaded)
        if len(others) == 1:
            old = str(others[0])
            print(f"Comparing with {others[0].name}, the other LinkedIn export found.", file=sys.stderr)
        else:
            msg = ("Found these other LinkedIn exports; which one is the older? Pass it as the first argument:\n" +
                   "\n".join(f"  {x}" for x in others)) if others else \
                "No other LinkedIn export found. Keep each export you download; pass the older ZIP's path."
            print(msg, file=sys.stderr)
            sys.exit(3)
    f = _filters(a)
    changes, summary = compare.compare(old, a.new, f, a.only)
    if a.export and not changes:
        summary["export"], summary["exported"] = None, 0
        print("Nothing matched your filter, so no file was written.", file=sys.stderr)
    if a.export and changes:
        out = Path(a.export).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        if a.crm:
            movers = [c for c in changes if c["change"] != "no longer connected"]
            with_email = [c for c in movers if c.get("email")]
            summary["crm"] = {"in_file_candidates": len(movers), "with_email": len(with_email),
                              "without_email": len(movers) - len(with_email),
                              "work_emails": sum(1 for c in with_email if people.email_type(c["email"]) == "work"),
                              "personal_emails": sum(1 for c in with_email if people.email_type(c["email"]) == "personal")}
            changes_for_crm = movers if a.all else with_email
            rows = [{"First Name": people.clean_person_name(c["name"].split(" ")[0]),
                     "Last Name": people.clean_person_name(" ".join(c["name"].split(" ")[1:])), "Email": c.get("email", ""),
                     "Company": c["company"], "Job Title": c["title"], "LinkedIn URL": c["profile_url"],
                     "Change": c.get("direction") or c["change"], "Before": c.get("before", ""),
                     "Connected On": c.get("connected_on", ""), "Last LinkedIn DM": c.get("last_dm", ""),
                     "LinkedIn DMs": c.get("dms", 0)}
                    for c in changes_for_crm]
            keys = list(rows[0].keys()) if rows else []
            if not rows:
                out = None
                print(f"None of the {len(movers):,} have an email in the export, so no file was written. --all writes "
                      f"them with their LinkedIn URL only (HubSpot can't dedupe those by email).", file=sys.stderr)
        else:
            rows, keys = changes, ["change", "name", "title", "company", "before", "warmth_label", "dms", "last_dm",
                                   "email", "profile_url", "connected_on"]
        if out:
            with open(out, "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
                w.writeheader()
                w.writerows(rows)
        summary["export"] = str(out) if out else None
        summary["exported"] = len(rows) if out else 0
    if a.json:
        per = {k: [c for c in changes if c["change"] == k] for k in compare.KINDS}
        out = {k: v[:25] for k, v in per.items() if v}
        truncated = {k: len(v) for k, v in per.items() if len(v) > 25}
        print(json.dumps(summary | {"changes": out, "truncated": truncated}, indent=2))
        return
    s = summary
    if s["warning"]:
        print(f"\n⚠️  {s['warning']}")
    skipped = s["without_url_skipped"]
    print(f"\n{s['older_date'] or '?'} → {s['newer_date'] or '?'} ({s['days_between']} days): "
          f"{s['older']:,} → {s['newer']:,} comparable connections"
          + (f" (of {s['newer'] + skipped['newer']:,}; {skipped['newer']:,} have no profile URL)" if skipped["newer"] else "") + ".")
    if "about" in (s["older_date_source"] or "") or "about" in (s["newer_date_source"] or ""):
        print(f"  dates: older = {s['older_date_source']}, newer = {s['newer_date_source']}")
    lead = "Matching your filter" if s["filtered"] else "Changes"
    counts = {"moved": f"changed company {s['changed_company']:,}", "retitled": f"changed title {s['changed_title']:,}",
              "new": f"new {s['new_connections']:,}", "gone": f"no longer connected {s['no_longer_connected']:,}"}
    print(f"  {lead}: " + (counts[a.only] + " (other kinds left out by --only)" if a.only else ", ".join(counts.values())))
    if s.get("movers_by_role") and not s["filtered"] and a.only in (None, "moved"):
        print("  who moved, by role: " + ", ".join(f"{r.replace('-', ' ')} {n}" for r, n in
                                                    sorted(s["movers_by_role"].items(), key=lambda kv: -kv[1])))
    if s.get("left_listed") or s.get("joined_listed"):
        where = "your company list" if f.company_list else "the companies you named"
        print(f"  at {where}: {s['left_listed']} left, {s['joined_listed']} joined")
    if s.get("crm"):
        c = s["crm"]
        print(f"  CRM file: {c['with_email']:,} of the {c['in_file_candidates']:,} have an email ({c['work_emails']:,} work, "
              f"{c['personal_emails']:,} personal), {c['without_email']:,} don't (LinkedIn only exports emails people "
              f"chose to share)" + ("; rows without an email can duplicate contacts you already have in HubSpot, and "
                                    "importing the file twice duplicates them all" if a.all else
                                    "; only the ones with an email were written, --all adds the rest "
                                    "(HubSpot can't dedupe rows without an email)")
              + (f"; the {s['no_longer_connected']:,} no longer connected are left out of CRM files"
                 if s["no_longer_connected"] and a.only in (None, "gone") else ""))
    labels = {"new company": "job changes, warmest first", "new title": "new titles", "new connection": "new",
              "no longer connected": "no longer connected"}
    for kind in compare.KINDS:
        every = [c for c in changes if c["change"] == kind]
        rows = every[:5 if kind != "new company" else 10]
        if not rows:
            continue
        print(f"  {labels[kind]}:")
        for r in rows:
            talk = f" | {r['warmth_label']}, {r['dms']} DMs, last {r['last_dm'][:7]}" if r.get("dms") else " | never messaged"
            what = f"{r['before']} → {r['title']} @ {r['company']}" if kind in ("new company", "new title") \
                else f"{r['title']} @ {r['company']}"
            if r.get("direction", "").startswith("left"):
                what = f"{r['direction']} → {r['title']} @ {r['company']}"
            elif r.get("direction"):
                what = f"{r['before']} → {r['title']} @ {r['company']} ({r['direction']})"
            print(f"    - {r['name']} | {what}{talk}")
        if len(every) > len(rows):
            print(f"    ... and {len(every) - len(rows):,} more" + ("" if s.get("export") else " (--export for all)"))
    if s.get("export"):
        print(f"\n✓ Wrote {s['exported']:,} to {s['export']}")
    shown_kinds = {c["change"] for c in changes}
    notes = []
    if "no longer connected" in shown_kinds:
        notes.append("'No longer connected' can mean they removed you, you removed them, or the account closed.")
    if shown_kinds & {"new company", "new title"}:
        notes.append("Job changes show once people update their profile.")
    print(("\n" + " ".join(notes) + "\n") if notes else "")


def cmd_syft_leads(a):
    f = _filters(a)
    if a.csv:
        raw = syft_leads.leads_from_csv(a.csv)
    elif f.describe() != "all connections":
        raw, _ = syft_leads.leads_from_connections(f)
    else:
        raise ValueError("Pick a source: --csv PATH, or filters on your connections (--title, --company, "
                         "--keywords, --messaged, --dm-since ...). Same filters as the `people` command.")
    out = syft_leads.build(raw, a.offset, a.limit, a.clean_names, a.max)
    if a.out:
        Path(a.out).expanduser().write_text(json.dumps(out, indent=2))
        out = {k: v for k, v in out.items() if k != "leads"} | {"written_to": str(Path(a.out).expanduser())}
    print(json.dumps(out, indent=2))


def build_parser():
    p = ArgumentParser(description="LinkedIn bot: ingest, search and clean up your LinkedIn data export.")
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("search-shares", help="search your posts (repeat --query for ANY of several)")
    s.add_argument("--query", required=True, action="append")
    s.add_argument("--since", help="only posts this recent, e.g. 6m")
    s.add_argument("--limit", type=int, default=10, help="how many to show (0 = all)")
    s = sub.add_parser("find-connections", help="connections by title and/or company")
    s.add_argument("--title", default="")
    s.add_argument("--company", default="")
    s = sub.add_parser("search-comments", help="search your comments (repeat --query for ANY of several)")
    s.add_argument("--query", required=True, action="append")
    s.add_argument("--since", help="only comments this recent, e.g. 6m")
    s.add_argument("--limit", type=int, default=10, help="how many to show (0 = all)")
    s = sub.add_parser("search-connections-keywords", help="connections matching every keyword")
    s.add_argument("--keywords", nargs="+", required=True)
    sub.add_parser("stats", help="counts per table")

    s = sub.add_parser("ingest", help="load an export ZIP (or the newest in the watch folder)")
    s.add_argument("--zip", help="path to a LinkedIn export ZIP; copied into the watch folder")
    s.add_argument("--force", action="store_true", help="rebuild even if this export is already loaded")
    s.add_argument("--json", action="store_true")
    sub.add_parser("info", help="what is loaded: which export, its date, row counts (reads only)")
    s = sub.add_parser("overview", help="a first look: owed replies, dormant contacts, stale requests, posting")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("engagers", help="who commented on your posts (the ones you replied to by name)")
    s.add_argument("--since", help="only this recent, e.g. 90d, 6m")
    s.add_argument("--role", action="append", choices=list(people.ROLES))
    s.add_argument("--title", action="append")
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--export")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("profile", help="your own profile (headline, positions, education, skills) as a Markdown resume")
    s.add_argument("--export", help="write it to this .md file")
    s = sub.add_parser("inbound", help="who came to you recently: owed replies, requests to accept, new people DMing")
    s.add_argument("--since", help="window before the export date, e.g. 30d, 3m (default 30d)")
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("network-profile", help="cleanup step 1: snapshot and presets with counts")
    s.add_argument("--json", action="store_true")
    s.add_argument("--as-of", type=date.fromisoformat, default=None, help="YYYY-MM-DD, default: the day the export was made")

    s = sub.add_parser("cleanup-candidates", help="build a cleanup candidate CSV (never removes anyone)")
    s.add_argument("--preset", choices=list(cleanup.PRESETS))
    s.add_argument("--connected-before", help="connected at least this long ago, e.g. 5y, 18m")
    s.add_argument("--older-than", help="alias of --connected-before")
    s.add_argument("--connected-after", help="connected within this window, e.g. 12m")
    s.add_argument("--no-dm-since", help="never messaged, or last DM at least this long ago, e.g. 3y")
    s.add_argument("--no-dm-older-than", help="alias of --no-dm-since")
    s.add_argument("--never-messaged", action="store_true", help="no 1:1 DM ever")
    s.add_argument("--never-replied", action="store_true", help="they messaged you 1:1 and you never replied")
    s.add_argument("--count-group-as-dm", action="store_true", help="a group-chat message counts as talking")
    s.add_argument("--keep-company", action="append", help="never list companies containing this (repeatable)")
    s.add_argument("--keep-title", action="append", help="never list titles containing this (repeatable)")
    s.add_argument("--only-title", action="append", help="only list titles containing this (repeatable)")
    s.add_argument("--keep-company-list", help="CSV of companies or domains never to list (customers, partners)")
    s.add_argument("--limit", type=int, help="keep the top N by score")
    s.add_argument("--with-preview", action="store_true", help="include the last DM's first 140 characters")
    s.add_argument("--export", help="CSV path; default ~/.linkedin-exports/cleanup/<date>-<preset>.csv")
    s.add_argument("--dry-run", action="store_true", help="count and describe, write nothing")
    s.add_argument("--json", action="store_true")
    s.add_argument("--as-of", type=date.fromisoformat, default=None, help="YYYY-MM-DD, default: the day the export was made")
    s.add_argument("--icp", help="pass 2, not implemented (Syft / Rolodex)")
    s.add_argument("--persona", help="pass 2, not implemented (Syft / Rolodex)")

    s = sub.add_parser("invitations-profile", help="connection requests: sent, accepted, never accepted, pace")
    s.add_argument("--json", action="store_true")
    s.add_argument("--as-of", type=date.fromisoformat, default=None, help="YYYY-MM-DD, default: the day the export was made")

    s = sub.add_parser("pending-invites", help="requests never accepted, oldest first (never withdraws anything)")
    s.add_argument("--direction", choices=("sent", "received"), default="sent")
    s.add_argument("--older-than", help="only requests at least this old, e.g. 90d, 3m")
    s.add_argument("--exclude-messaged", action="store_true", help="leave out anyone you have DMed")
    s.add_argument("--keep-list", help="CSV of people never to list: LinkedIn URLs or first / last names (a CRM contacts export)")
    s.add_argument("--with-note", action="store_true", help="with --direction received: show the first line of each note")
    s.add_argument("--keep-company-list", help=argparse_suppress())
    s.add_argument("--limit", type=int, help="keep the oldest N (0 = all)")
    s.add_argument("--export", help="write a CSV here")
    s.add_argument("--json", action="store_true")
    s.add_argument("--as-of", type=date.fromisoformat, default=None, help="YYYY-MM-DD, default: the day the export was made")

    s = sub.add_parser("people", help="find connections by title / company / how much you talk, ranked")
    _add_filters(s)
    s.add_argument("--limit", type=int, default=20, help="how many to show (default 20; 0 = all)")
    s.add_argument("--export", help="write every match to this CSV")
    s.add_argument("--crm", action="store_true",
                   help="export in CRM import columns (First Name, Email, Company ...); only people with an email")
    s.add_argument("--all", action="store_true", help="with --crm: also people without an email (by LinkedIn URL)")
    s.add_argument("--by-company", action="store_true", help="group by company: people, written to, warmest contact")
    s.add_argument("--last-message", action="store_true",
                   help="print each person's last message (200 chars) under the row, for Claude to check which "
                        "threads need a reply; never paste these to the user")
    s.add_argument("--json", action="store_true")
    s.add_argument("--as-of", type=date.fromisoformat, default=None, help="YYYY-MM-DD, default: the day the export was made")

    s = sub.add_parser("search-messages", help="your DMs by words and/or person, newest first (snippets only)")
    s.add_argument("--query", action="append", help="words in the message; repeat for ANY of several")
    s.add_argument("--person", default="", help="part of the other person's name")
    s.add_argument("--person-url", action="append", default=[],
                   help="their LinkedIn URL (repeat for several people: each thread is printed in turn)")
    s.add_argument("--include-groups", action="store_true", help="also search group chats")
    s.add_argument("--topic", choices=list(search.TOPICS),
                   help="a subject with its usual words and patterns (pricing also finds $ amounts and /mo)")
    s.add_argument("--since", help="only this recent, e.g. 12m")
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("topics", help="what your posts are about: most common words and phrases")
    s.add_argument("--since", help="only posts this recent, e.g. 6m")
    s.add_argument("--top", "--limit", type=int, default=15, dest="top")
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("activity", help="posts / comments / reactions per month, requests and new DMs coming in")
    s.add_argument("--months", type=int, default=12)
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("compare-exports", help="two exports: job and title changes, new connections, gone")
    s.add_argument("old", nargs="?", help="the older export ZIP (default: find the other LinkedIn export)")
    s.add_argument("new", nargs="?", help="the newer export ZIP (default: the one currently loaded)")
    s.add_argument("--only", choices=("moved", "retitled", "new", "gone"), help="one kind of change")
    _add_filters(s)
    s.add_argument("--export", help="write the changes to this CSV (with warmth, last DM and email)")
    s.add_argument("--crm", action="store_true",
                   help="with --export: CRM import columns (First Name, Email ...); only people with an email")
    s.add_argument("--all", action="store_true", help="with --crm: also people without an email")
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("syft-leads", help="lead objects for the Syft MCP enqueue_leads tool (sends nothing)")
    s.add_argument("--csv", help="any CSV with a LinkedIn profile column (cleanup CSV, Connections.csv, Sales Nav)")
    _add_filters(s)
    s.add_argument("--max", type=int, help="cap the list at N people (the number the user agreed to)")
    s.add_argument("--clean-names", action="store_true",
                   help="use the suggested first name for odd ones (emoji, nickname, initial) listed in odd_first_names")
    s.add_argument("--offset", type=int, default=0, help="skip this many leads (for sending in chunks)")
    s.add_argument("--limit", type=int, help=f"at most this many leads (the skill sends {syft_leads.CHUNK} per call)")
    s.add_argument("--out", help="write the full JSON here and print only the summary")
    return p


COMMANDS = {
    "search-shares": cmd_search_shares, "find-connections": cmd_find_connections,
    "search-comments": cmd_search_comments, "search-connections-keywords": cmd_search_connections_keywords,
    "stats": cmd_stats, "ingest": cmd_ingest, "info": cmd_info, "overview": cmd_overview, "inbound": cmd_inbound,
    "engagers": cmd_engagers, "profile": cmd_profile, "network-profile": cmd_network_profile,
    "cleanup-candidates": cmd_cleanup_candidates, "syft-leads": cmd_syft_leads,
    "invitations-profile": cmd_invitations_profile, "pending-invites": cmd_pending_invites, "people": cmd_people,
    "search-messages": cmd_search_messages, "activity": cmd_activity, "compare-exports": cmd_compare_exports,
    "topics": cmd_topics,
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
    # A CSV handed to syft-leads needs no export loaded.
    no_db_needed = (a.command == "syft-leads" and a.csv) or (a.command == "compare-exports" and a.new)
    if not no_db_needed:
        try:
            # Progress goes to stderr so --json output stays parseable.
            archive.ensure_db_current(zip_path=getattr(a, "zip", None),
                                  force=a.command == "ingest" and bool(getattr(a, "force", False)),
                                      log=lambda m: print(m, file=sys.stderr))
        except archive.NoExportError as e:
            print(str(e), file=sys.stderr)
            sys.exit(3)      # 3 = nothing loaded yet (not a crash): list the ZIPs found and ask the user
    try:
        COMMANDS[a.command](a)
    except ValueError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
