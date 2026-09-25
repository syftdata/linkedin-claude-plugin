"""A first look at someone's own LinkedIn, in numbers: the answer to "what can this do with my LinkedIn?".

Each line is something they can act on today, with the question to ask next. Everything is as of the export date.
"""
from datetime import date
from pathlib import Path

import people
from cleanup import LINKEDIN_CONNECTION_CAP, load_people
from invites import export_date, profile as invitations_profile


def overview():
    exported = export_date()
    as_of = exported or date.today()
    everyone = load_people(as_of) + people.no_url_people(as_of)
    lines = []

    owed_all, _ = people.select(people.Filters(awaiting_reply=True, dm_within_days=90), as_of)
    owed = [p for p in owed_all if p["in_count"] and p["out_count"]]
    cold = len(owed_all) - len(owed)
    dormant, _ = people.select(people.Filters(dormant=True), as_of)
    inv = invitations_profile(as_of)
    stale = inv["not_accepted_by_age"].get("90-180 days", 0) + inv["not_accepted_by_age"].get("over 180 days", 0)

    near_cap = len(everyone) >= 25000
    lines.append({"what": "connections", "count": len(everyone),
                  "text": f"{len(everyone):,} connections" + (f", {LINKEDIN_CONNECTION_CAP - len(everyone):,} under "
                                                              f"LinkedIn's 30,000 cap" if near_cap else ""),
                  **({"ask": "Who can I let go?"} if near_cap else {})})
    lines.append({"what": "owed_replies", "count": len(owed),
                  "text": f"{len(owed):,} people you've talked with wrote last in the past 3 months and are waiting on you"
                          + (f" (plus {cold:,} who wrote first and you never answered, mostly pitches)" if cold else ""),
                  "ask": "Who am I waiting to reply to?"})
    lines.append({"what": "dormant", "count": len(dormant),
                  "text": f"{len(dormant):,} close contacts (real back-and-forth) went quiet over a year ago",
                  "ask": "Who should I reconnect with?"})
    if inv["sent"]:
        lines.append({"what": "stale_requests", "count": stale,
                      "text": f"{stale:,} connection requests you sent 90+ days ago were never accepted "
                              f"(busiest week {inv['sent_per_week']['busiest_week_count']} sent)",
                      "ask": "Why do my connection requests get blocked?"})
    import search
    act = search.activity(3)
    recent_posts = len(search.search_shares_since(90))
    if act["totals"]["posts"]:
        lines.append({"what": "posting", "count": recent_posts,
                      "text": f"{recent_posts} posts in the last 90 days ({act['totals']['posts']:,} in all); the export "
                              f"has no reactions or impressions on them",
                      "ask": "What have I been posting about, and is it working?"})
    import engagers
    fans, fsum = engagers.commenters(as_of, 90)
    if fans:
        lines.append({"what": "engagers", "count": len(fans),
                      "text": f"{len(fans):,} people commented on your posts in the last 90 days and got a reply from "
                              f"you ({fsum['never_messaged']:,} of them you've never DMed); people who only reacted "
                              f"aren't in the export",
                      "ask": "Who engages with my posts?"})
    with_email = sum(1 for p in everyone if p.get("email"))
    import jobs
    from datetime import timedelta
    recent_jobs = jobs.job_companies(since=(as_of - timedelta(days=365)).isoformat())
    recent_jobs = [e for e in recent_jobs if e["when"]]
    job_q = [f"Who do I know at the {len(recent_jobs):,} companies I saved or applied to jobs at this year?"] \
        if recent_jobs else []
    return {"export_date": exported.isoformat() if exported else None, "lines": lines, "emails": with_email,
            "more": ["Who do I know at <company> / on this list of companies?", "Recruiters or buyers in my network, "
                     "warmest first", *job_q, *(["Who changed jobs since my last export?"] if _has_older_export() else
                       ["(I kept a copy of this export: load your next one in a month or two and I'll show who "
                        "changed jobs and who's gone)"]),
                     f"Get my network into a spreadsheet or CRM ({with_email:,} shared an email)"]}


def _has_older_export(min_days=30):
    """Another LinkedIn export made at least `min_days` before the loaded one (not the same ZIP sitting in
    ~/Downloads, and not one a day apart): only then is "who changed jobs" worth asking."""
    import compare
    from archive import read_metadata
    try:
        loaded = read_metadata().get("last_loaded_zip")
        made = compare._zip_date(loaded)[0] if loaded and Path(loaded).is_file() else None
        if not made:
            return False
        for other in compare.other_exports(exclude=loaded):
            d = compare._zip_date(other)[0]
            if d and (date.fromisoformat(made) - date.fromisoformat(d)).days >= min_days:
                return True
    except Exception:
        return False
    return False


def inbound(since_days=30):
    """Who came to you recently, from what the export does have: people you've talked with who are waiting on your
    reply, connection requests you haven't accepted (with notes first), new people who messaged you first
    (unanswered first), and people who commented on your posts and got a reply from you."""
    from invites import pending
    import search
    exported = export_date()
    as_of = exported or date.today()
    owed_all, _ = people.select(people.Filters(awaiting_reply=True, dm_within_days=since_days), as_of)
    owed = [p for p in owed_all if p["in_count"] and p["out_count"]]
    owed_slugs = {p.get("slug") for p in owed_all}
    requests, _ = pending(direction="received", as_of=as_of)
    requests = [r for r in requests if isinstance(r["days_waiting"], int) and r["days_waiting"] <= since_days]
    firsts = []
    cutoff = search._cutoff(since_days)
    con = search.connect()
    if "dm_events" in search.table_names(con):
        seen = {}
        for slug, sent_at, direction in con.execute(
                "SELECT counterpart_slug, sent_at, direction FROM dm_events WHERE is_group = 0 ORDER BY sent_at"):
            if slug not in seen:
                seen[slug] = (sent_at, direction)
        who = {p["slug"]: p for p in load_people(as_of) + people.message_only_people(as_of)}
        for slug, (sent_at, direction) in seen.items():
            if direction == "in" and (sent_at or "")[:10] >= cutoff:
                p = who.get(slug, {})
                firsts.append({"name": p.get("name", slug), "title": p.get("title", ""), "company": p.get("company", ""),
                               "first_message": (sent_at or "")[:10], "profile_url": f"https://www.linkedin.com/in/{slug}",
                               "replied": bool(p.get("out_count"))})
                firsts[-1]["waiting_on_you"] = slug in owed_slugs
        firsts.sort(key=lambda x: x["first_message"], reverse=True)
        firsts.sort(key=lambda x: x["replied"])                     # unanswered first, newest first within
    import engagers
    fans, fsum = engagers.commenters(as_of, since_days)
    return {"export_date": exported.isoformat() if exported else None, "since_days": since_days,
            "owed_replies": [people.row_out(p) for p in owed],
            "requests": requests, "requests_with_note": sum(1 for r in requests if r["had_note"] == "yes"),
            "first_messages": firsts, "first_messages_unanswered": sum(1 for f in firsts if not f["replied"]),
            "commenters": fans[:25], "commenters_total": len(fans), "commenters_caveat": fsum["caveat"],
            "non_connections": fsum.get("non_connections", [])}
