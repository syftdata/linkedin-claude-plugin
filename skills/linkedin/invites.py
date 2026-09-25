"""Connection requests, from Invitations.csv: what you sent, what got accepted, and what is still hanging.

What the file is (checked on real exports): every request sent and received in roughly the last 12 months,
accepted ones included. It has no status column. So "accepted" means the other person now appears in
Connections.csv, and "not accepted" means they don't: still pending, ignored, withdrawn, or accepted and later
removed. The export cannot tell those apart, and it is a snapshot from the day it was made.

Nothing here withdraws or sends anything. Withdrawing is manual on LinkedIn (My Network → Manage → Sent).
"""
import collections
from datetime import date, datetime, timedelta

from archive import connect, slug_from_url, table_names

SETTLE_DAYS = 30

_FORMATS = ("%m/%d/%y, %I:%M %p", "%m/%d/%Y, %I:%M %p", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%d")


def parse_sent_at(text):
    """'9/6/26, 12:38 AM' (the export's format) → datetime, or None."""
    text = (text or "").strip()
    for fmt in _FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def load(con=None):
    """One dict per invitation: direction, name, profile_url, slug, sent_at (datetime or None), note, connected."""
    con = con or connect()
    names = table_names(con)
    if "invitations" not in names:
        return []
    connected = set()
    if "connections_index" in names:
        connected = {r[0] for r in con.execute("SELECT slug FROM connections_index")}
    out = []
    for frm, to, sent, note, direction, inviter, invitee in con.execute(
            'SELECT "From", "To", "Sent At", "Message", "Direction", inviterProfileUrl, inviteeProfileUrl '
            "FROM invitations"):
        outgoing = (direction or "").upper() == "OUTGOING"
        other_url = invitee if outgoing else inviter
        slug = slug_from_url(other_url or "")
        out.append({"direction": "sent" if outgoing else "received", "name": (to if outgoing else frm) or "",
                    "profile_url": f"https://www.linkedin.com/in/{slug}" if slug else "", "slug": slug,
                    "sent_at": parse_sent_at(sent), "note": (note or "").strip(), "connected": slug in connected})
    return out


def export_date(con=None):
    """The day the export was made, as best the data shows: the latest message, request or connection date.
    Ages and weekly pace are measured from here, not from today (the export is a snapshot)."""
    con = con or connect()
    names = table_names(con)
    dates = []
    if "metadata" in names:
        row = con.execute("SELECT value FROM metadata WHERE key='latest_message_at'").fetchone()
        if row and row[0]:
            dates.append(row[0][:10])
    if "connections_index" in names:
        row = con.execute("SELECT MAX(connected_on) FROM connections_index").fetchone()
        if row and row[0]:
            dates.append(row[0][:10])
    dates += [r["sent_at"].date().isoformat() for r in load(con) if r["sent_at"]]
    return date.fromisoformat(max(dates)) if dates else None


def load_keep_list(path):
    """People never to list: a CSV with LinkedIn URLs (best: a HubSpot / Salesforce contacts export) or names.
    Returns (slugs, names). Requests carry no company in the export, so company or domain lists can't match."""
    import csv as _csv
    from pathlib import Path
    path = Path(path).expanduser()
    if not path.is_file():
        raise ValueError(f"No such file: {path}")
    rows = list(_csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines()))
    slugs, names = set(), set()
    for r in rows:
        r = {(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
        for v in r.values():
            s = slug_from_url(v)
            if s:
                slugs.add(s)
        full = r.get("name") or r.get("full name") or " ".join(
            x for x in (r.get("first name") or r.get("firstname") or "", r.get("last name") or r.get("lastname") or "") if x)
        if full:
            names.add(" ".join(full.lower().split()))
    if not slugs and not names:
        raise ValueError(f"{path.name}: no LinkedIn URLs or names found. Export contacts with a LinkedIn URL or "
                         "First / Last Name column.")
    return slugs, names


def coverage_start(con=None, rows=None):
    """The first month the request history is really there. LinkedIn's file can hold a few stray old requests and
    then nothing for months, so the earliest date is misleading. Coverage starts at the first month where at least
    half of the new connections made that month have a request record (sent or received)."""
    con = con or connect()
    rows = rows if rows is not None else load(con)
    if not rows or "connections_index" not in table_names(con):
        return None
    with_request = {r["slug"] for r in rows if r["slug"]}
    months = collections.defaultdict(lambda: [0, 0])
    for slug, on in con.execute("SELECT slug, connected_on FROM connections_index WHERE connected_on != ''"):
        m = months[on[:7]]
        m[0] += 1
        m[1] += slug in with_request
    for month in sorted(months):
        total, covered = months[month]
        if total >= 5 and covered / total >= 0.5:
            return month
    return None


def _messaged_slugs(con):
    if "last_dm" not in table_names(con):
        return set()
    return {r[0] for r in con.execute("SELECT counterpart_slug FROM last_dm WHERE dm_count > 0")}


def _rate(part, whole):
    return round(100 * part / whole) if whole else None


def profile(as_of=None, con=None):
    """Snapshot for the skill: counts, acceptance rate with and without a note, age of what was never
    accepted, and sending pace per week."""
    con = con or connect()
    rows = load(con)
    exported = export_date(con)
    as_of = as_of or exported or date.today()
    sent = [r for r in rows if r["direction"] == "sent"]
    received = [r for r in rows if r["direction"] == "received"]
    not_acc = [r for r in sent if not r["connected"]]
    dated = [r["sent_at"] for r in rows if r["sent_at"]]

    def age(r):
        return (as_of - r["sent_at"].date()).days if r["sent_at"] else None

    buckets = collections.OrderedDict((k, 0) for k in ("under 30 days", "30-90 days", "90-180 days",
                                                        "over 180 days", "undated"))
    for r in not_acc:
        d = age(r)
        key = ("undated" if d is None else "under 30 days" if d < 30 else "30-90 days" if d < 90
               else "90-180 days" if d < 180 else "over 180 days")
        buckets[key] += 1

    weeks = collections.Counter()
    for r in sent:
        if r["sent_at"]:
            d = r["sent_at"].date()
            weeks[d - timedelta(days=d.weekday())] += 1
    busiest = max(weeks.items(), key=lambda kv: kv[1]) if weeks else None
    recent = [weeks.get(as_of - timedelta(days=as_of.weekday() + 7 * i), 0) for i in range(1, 9)]

    # Acceptance rates only count requests at least 30 days old at export time: newer ones have not had a fair
    # chance yet, and counting them makes whichever group was sent most recently look worse.
    settled = [r for r in sent if r["sent_at"] and (as_of - r["sent_at"].date()).days >= SETTLE_DAYS]
    noted = [r for r in settled if r["note"]]
    plain = [r for r in settled if not r["note"]]
    by_month = collections.defaultdict(lambda: {"with_note": [0, 0], "without_note": [0, 0]})
    for r in settled:
        g = by_month[r["sent_at"].strftime("%Y-%m")]["with_note" if r["note"] else "without_note"]
        g[0] += 1
        g[1] += r["connected"]
    messaged = _messaged_slugs(con)
    covered_from = coverage_start(con, rows)
    before = sum(1 for d in dated if covered_from and d.strftime("%Y-%m") < covered_from)
    return {
        "as_of": as_of.isoformat(),
        "loaded": "invitations" in table_names(con),
        "window": {"first": min(dated).date().isoformat() if dated else None,
                   "last": max(dated).date().isoformat() if dated else None,
                   "covered_from": covered_from, "stray_before": before},
        "sent": len(sent),
        "sent_accepted": len(sent) - len(not_acc),
        "sent_not_accepted": len(not_acc),
        "export_date": exported.isoformat() if exported else None,
        "settled_sent": len(settled),
        "acceptance_rate_pct": _rate(sum(r["connected"] for r in settled), len(settled)),
        "with_note": {"sent": len(noted), "accepted_pct": _rate(sum(r["connected"] for r in noted), len(noted))},
        "without_note": {"sent": len(plain), "accepted_pct": _rate(sum(r["connected"] for r in plain), len(plain))},
        "note_vs_no_note_by_month": [
            {"month": m, "with_note_sent": v["with_note"][0], "with_note_pct": _rate(v["with_note"][1], v["with_note"][0]),
             "without_note_sent": v["without_note"][0],
             "without_note_pct": _rate(v["without_note"][1], v["without_note"][0])}
            for m, v in sorted(by_month.items()) if v["with_note"][0] >= 10 and v["without_note"][0] >= 10],
        "not_accepted_by_age": buckets,
        "not_accepted_but_messaged": sum(1 for r in not_acc if r["slug"] in messaged),
        "sent_per_week": {"busiest_week": busiest[0].isoformat() if busiest else None,
                          "busiest_week_count": busiest[1] if busiest else 0,
                          "average_last_8_weeks": round(sum(recent) / 8, 1)},
        "received": len(received),
        "received_not_connected": sum(1 for r in received if not r["connected"]),
        "caveats": [
            (f"Request history is only complete from {covered_from} on" + (f" ({before} stray older ones)" if before else "")
             + "; accepted ones are included and there is no status column.") if covered_from else
            "The export's request history covers a limited recent window; accepted ones are included, no status column.",
            f"Acceptance rates leave out requests under {SETTLE_DAYS} days old at export time (too new to judge).",
            "'Not accepted' means the person is not in your connections: still pending, ignored, withdrawn, "
            "or accepted and later removed. The export can't tell these apart.",
            "Counts and ages are as of the export date, not today.",
        ],
    }


def pending(older_than_days=None, direction="sent", exclude_messaged=False, limit=None, as_of=None, con=None,
            keep_slugs=frozenset(), keep_names=frozenset()):
    """Requests with no matching connection, oldest first. direction: sent (yours, to withdraw) or received
    (theirs, still waiting on you). People you have DMed (with exclude_messaged) or on a keep list are not
    listed; they come back as `skip` so the user can withdraw "everything older than X except these"."""
    con = con or connect()
    exported = export_date(con)
    as_of = as_of or exported or date.today()
    messaged = _messaged_slugs(con) if exclude_messaged else set()
    out, skip, skipped_messaged, skipped_kept = [], [], 0, 0
    for r in load(con):
        if r["direction"] != direction or r["connected"]:
            continue
        days = (as_of - r["sent_at"].date()).days if r["sent_at"] else None
        if older_than_days is not None and (days is None or days < older_than_days):
            continue
        why = ("you've DMed them" if r["slug"] in messaged else
               "on your keep list" if (r["slug"] in keep_slugs or " ".join(r["name"].lower().split()) in keep_names)
               else "")
        if why:
            skipped_messaged += why.startswith("you")
            skipped_kept += why.startswith("on")
            skip.append({"name": r["name"], "profile_url": r["profile_url"],
                         "sent_at": r["sent_at"].date().isoformat() if r["sent_at"] else "", "why": why})
            continue
        out.append({"name": r["name"], "profile_url": r["profile_url"],
                    "sent_at": r["sent_at"].date().isoformat() if r["sent_at"] else "",
                    "days_waiting": days if days is not None else "", "had_note": "yes" if r["note"] else "no",
                    "note": r["note"][:160] if direction == "received" else ""})
    if direction == "received":
        # People waiting on the user: the ones who wrote a note first (they asked for something), newest first.
        out.sort(key=lambda x: (x["had_note"] != "yes", x["sent_at"] == "", "" if not x["sent_at"] else
                                "".join(chr(255 - ord(c)) for c in x["sent_at"])))
    else:
        out.sort(key=lambda x: (x["sent_at"] == "", x["sent_at"]))
    matched = len(out)
    if limit:
        out = out[:limit]
    return out, {"matched": matched, "count": len(out), "skipped_messaged": skipped_messaged,
                 "skipped_keep_list": skipped_kept, "skip": sorted(skip, key=lambda x: x["sent_at"]),
                 "direction": direction, "older_than_days": older_than_days, "as_of": as_of.isoformat(),
                 "export_date": exported.isoformat() if exported else None,
                 "over_180_days": sum(1 for r in out if isinstance(r["days_waiting"], int) and r["days_waiting"] >= 180)}
