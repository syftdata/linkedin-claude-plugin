"""Network cleanup, pass 1: who to consider removing, from Connections.csv joined to messages.csv.

Inputs are the two files only. Connections.csv is the list you are actually connected to (the list you'd thin);
messages.csv gives the last DM per person. Invitations.csv is never read here.

Nothing is removed. The output is a ranked candidate list the user reviews.

Pass 2 (ICP / persona) is not in this file on purpose: it needs Syft / Rolodex definitions and is a stub
(`apply_pass2`). Nothing here guesses who fits an ICP.
"""
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from archive import connect, table_names

LINKEDIN_CONNECTION_CAP = 30000

# Presets the guided skill offers, each shown with its live count and hidden when the count is 0.
PRESETS = {
    "old-never-messaged": {
        "label": "Connected 5+ years ago and never messaged",
        "connected_before_days": 5 * 365, "never_messaged": True},
    "old-quiet": {
        "label": "Connected 2+ years ago and no DM in the last 3 years",
        "connected_before_days": 2 * 365, "no_dm_since_days": 3 * 365},
    "never-messaged": {
        "label": "Never messaged at all, any age",
        "never_messaged": True},
    "never-replied": {
        "label": "They messaged you and you never replied (usually a pitch)",
        "never_replied": True},
    "recent-never-messaged": {
        "label": "Connected in the last 12 months and never messaged (accepted but never followed up)",
        "connected_after_days": 365, "never_messaged": True},
}

_DUR = re.compile(r"^\s*(\d+)\s*([dwmy])\s*$", re.I)


def parse_duration(text):
    """'18m' -> 548 days, '5y' -> 1825, '2w' -> 14, '90d' -> 90. A month is 365/12 days, a year 365."""
    if text in (None, ""):
        return None
    m = _DUR.match(str(text))
    if not m:
        raise ValueError(f"Bad duration {text!r}: use a number and d / w / m / y, e.g. 18m or 5y")
    n, unit = int(m.group(1)), m.group(2).lower()
    if unit == "m":
        return round(n * 365 / 12)      # 12m = 365 days, not 360
    return n * {"d": 1, "w": 7, "y": 365}[unit]


@dataclass
class Criteria:
    connected_before_days: int = None    # connected at least this many days ago
    connected_after_days: int = None     # connected at most this many days ago
    no_dm_since_days: int = None         # never messaged, or last 1:1 DM at least this many days ago
    never_messaged: bool = False         # no 1:1 DM ever
    never_replied: bool = False          # they wrote 1:1, you never wrote back
    count_group_as_dm: bool = False      # treat group-chat messages as a DM
    keep_company: list = field(default_factory=list)   # never list anyone whose Company contains one of these
    keep_title: list = field(default_factory=list)     # never list anyone whose Position contains one of these
    only_title: list = field(default_factory=list)     # only list people whose Position contains one of these
    keep_company_list: list = field(default_factory=list)  # [(label, words)] companies never to list (customers)
    limit: int = None
    preset: str = None

    def is_empty(self):
        return not any([self.connected_before_days, self.connected_after_days, self.no_dm_since_days,
                        self.never_messaged, self.never_replied, self.only_title])

    @classmethod
    def from_preset(cls, name, **overrides):
        if name not in PRESETS:
            raise ValueError(f"Unknown preset {name!r}. Options: {', '.join(PRESETS)}")
        spec = {k: v for k, v in PRESETS[name].items() if k != "label"}
        spec.update({k: v for k, v in overrides.items() if v not in (None, [], False)})
        return cls(preset=name, **spec)


def _anchor():
    """Default "as of" day: the day the export was made (ages are about the snapshot), else today."""
    try:
        from invites import export_date
        return export_date() or date.today()
    except Exception:
        return date.today()


def _days_between(iso, as_of):
    if not iso:
        return None
    d = datetime.fromisoformat(iso.replace("Z", "+00:00")).date() if "T" in iso else date.fromisoformat(iso)
    return (as_of - d).days


def load_people(as_of=None):
    """Every connection with its DM facts. Connections with no parseable profile URL are skipped (counted)."""
    as_of = as_of or _anchor()
    con = connect()
    names = table_names(con)
    if "connections_index" not in names:
        raise RuntimeError("Database is from v1 or empty. Run `ingest` to reload the export.")
    has_dm = "last_dm" in names
    sql = """SELECT c.slug, c.first_name, c.last_name, c.url, c.company, c.position, c.connected_on, c.connected_on_raw,
                    c.email, {dm}
             FROM connections_index c {join}""".format(
        dm="d.dm_count, d.last_dm_at, d.last_dm_direction, d.last_dm_preview, d.group_count, d.last_group_at, "
           "d.out_count, d.in_count, d.opened_by, d.opened_at, d.last_dm_text, d.opened_text" if has_dm else
           "0, NULL, NULL, NULL, 0, NULL, 0, 0, NULL, NULL, NULL, NULL",
        join="LEFT JOIN last_dm d ON d.counterpart_slug = c.slug" if has_dm else "")
    people = []
    for r in con.execute(sql).fetchall():
        people.append({
            "slug": r[0], "name": " ".join(f"{r[1] or ''} {r[2] or ''}".split()), "first_name": r[1] or "",
            "last_name": r[2] or "", "profile_url": r[3], "company": r[4] or "",
            "title": r[5] or "", "connected_on": r[6] or "", "connected_on_raw": r[7] or "",
            "email": r[8] or "",
            "dm_count": r[9] or 0, "last_dm_at": r[10] or "", "last_dm_direction": r[11] or "",
            "last_dm_preview": r[12] or "", "group_count": r[13] or 0, "last_group_at": r[14] or "",
            "days_since_connect": _days_between(r[6], as_of), "days_since_dm": _days_between(r[10], as_of),
            "days_since_group": _days_between(r[14], as_of),
            "out_count": r[15] or 0, "in_count": r[16] or 0, "opened_by": r[17] or "", "opened_at": r[18] or "",
            "last_dm_text": r[19] or "", "opened_text": r[20] or "",
        })
    return people


def _messaged(p, crit):
    if p["dm_count"]:
        return True
    return bool(crit.count_group_as_dm and p["group_count"])


def _days_since_any(p, crit):
    days = [d for d in (p["days_since_dm"], p["days_since_group"] if crit.count_group_as_dm else None) if d is not None]
    return min(days) if days else None


def _contains_any(text, words):
    text = (text or "").lower()
    return any(w.lower() in text for w in words if w)


def score(p, crit):
    """0 to 100. Older connection and no conversation rank highest. For ordering only, not a probability."""
    dsc = p["days_since_connect"]
    age = 30.0 if dsc is None else min(max(dsc, 0), 3650) / 3650 * 60
    if not _messaged(p, crit):
        talk = 30.0 if p["group_count"] else 40.0
    else:
        dsd = _days_since_any(p, crit) or 0
        talk = min(max(dsd, 0), 1825) / 1825 * 30
    return round(age + talk, 1)


def reasons(p, crit):
    out = []
    dsc = p["days_since_connect"]
    out.append(f"connected {dsc / 365:.1f} years ago ({p['connected_on']})" if dsc is not None
               else f"connected date unreadable ({p['connected_on_raw'] or 'blank'})")
    if not _messaged(p, crit):
        out.append("never messaged" if not p["group_count"] else f"never messaged 1:1, only in group chats (last {p['last_group_at'][:10]})")
    else:
        d = _days_since_any(p, crit)
        out.append(f"last DM {d / 365:.1f} years ago ({(p['last_dm_at'] or p['last_group_at'])[:10]})")
        if p["in_count"] and not p["out_count"]:
            out.append(f"they wrote {p['in_count']}x, you never replied")
    return out


def matches(p, crit):
    dsc = p["days_since_connect"]
    if crit.connected_before_days is not None and (dsc is None or dsc < crit.connected_before_days):
        return False
    if crit.connected_after_days is not None and (dsc is None or dsc > crit.connected_after_days):
        return False
    messaged = _messaged(p, crit)
    if crit.never_messaged and messaged:
        return False
    if crit.never_replied and not (p["in_count"] and not p["out_count"]):
        return False
    if crit.no_dm_since_days is not None and messaged:
        d = _days_since_any(p, crit)
        if d is not None and d < crit.no_dm_since_days:
            return False
    if crit.only_title and not _contains_any(p["title"], crit.only_title):
        return False
    return True


def candidates(crit, as_of=None, people=None, with_preview=False):
    """Returns (rows, summary). rows are ranked; summary explains every exclusion so counts reconcile."""
    as_of = as_of or _anchor()
    people = people if people is not None else load_people(as_of)
    matched, kept = [], {"company": 0, "title": 0, "list": 0}
    if crit.keep_company_list:
        from people import company_matches
    for p in people:
        if not matches(p, crit):
            continue
        if crit.keep_company_list and any(company_matches(p["company"], w) for _, w in crit.keep_company_list):
            kept["list"] += 1
            continue
        if crit.keep_company and _contains_any(p["company"], crit.keep_company):
            kept["company"] += 1
            continue
        if crit.keep_title and _contains_any(p["title"], crit.keep_title):
            kept["title"] += 1
            continue
        matched.append(p)
    matched.sort(key=lambda p: (-score(p, crit), -(p["days_since_connect"] or 0), p["name"].lower()))
    total_matched = len(matched)
    if crit.limit:
        matched = matched[:crit.limit]
    rows = [{
        "name": p["name"], "company": p["company"], "title": p["title"], "profile_url": p["profile_url"],
        "connected_on": p["connected_on"], "last_dm_at": p["last_dm_at"],
        "last_dm_preview": p["last_dm_preview"] if with_preview else "",
        "days_since_connect": "" if p["days_since_connect"] is None else p["days_since_connect"],
        "days_since_dm": "" if p["days_since_dm"] is None else p["days_since_dm"],
        "cleanup_score": score(p, crit), "reasons": "; ".join(reasons(p, crit)),
    } for p in matched]
    summary = {
        "definition": describe(crit, as_of), "count": len(rows), "matched_before_limit": total_matched,
        "kept_by_company": kept["company"], "kept_by_title": kept["title"], "kept_by_list": kept["list"],
        "connections_total": len(people),
        "as_of": as_of.isoformat(),
    }
    return rows, summary


def _ago(days, as_of):
    from datetime import timedelta
    return (as_of - timedelta(days=days)).isoformat()


def _years(days):
    y = days / 365
    return f"{round(y)}" if abs(y - round(y)) < 0.05 else f"{y:.1f}"


def describe(crit, as_of=None):
    """One line the agent reads back for confirmation."""
    as_of = as_of or _anchor()
    parts = []
    if crit.preset:
        parts.append(f"preset {crit.preset}")
    if crit.connected_before_days is not None:
        parts.append(f"connected {_years(crit.connected_before_days)}+ years ago (on or before {_ago(crit.connected_before_days, as_of)})")
    if crit.connected_after_days is not None:
        parts.append(f"connected within the last {crit.connected_after_days} days (since {_ago(crit.connected_after_days, as_of)})")
    if crit.never_messaged:
        parts.append("never messaged" + (" (group chats count)" if crit.count_group_as_dm else " 1:1"))
    if crit.never_replied:
        parts.append("they messaged you and you never replied")
    if crit.no_dm_since_days is not None:
        parts.append(f"no DM in the last {_years(crit.no_dm_since_days)} years (since {_ago(crit.no_dm_since_days, as_of)})")
    if crit.only_title:
        parts.append("title contains " + " / ".join(repr(w) for w in crit.only_title))
    if crit.keep_company:
        parts.append("keeping companies containing " + " / ".join(repr(w) for w in crit.keep_company))
    if crit.keep_title:
        parts.append("keeping titles containing " + " / ".join(repr(w) for w in crit.keep_title))
    if crit.limit:
        parts.append(f"top {crit.limit:,} by score")
    return ", ".join(parts)


def network_profile(as_of=None):
    """Step 1 of the guided flow: the snapshot, plus every preset with its live count."""
    as_of = as_of or _anchor()
    con = connect()
    meta = dict(con.execute("SELECT key, value FROM metadata").fetchall()) if "metadata" in table_names(con) else {}
    people = load_people(as_of)
    total = len(people)
    buckets = {"under 1 year": 0, "1 to 2 years": 0, "2 to 5 years": 0, "5+ years": 0, "date unreadable": 0}
    for p in people:
        d = p["days_since_connect"]
        key = ("date unreadable" if d is None else "under 1 year" if d < 365 else "1 to 2 years" if d < 730
               else "2 to 5 years" if d < 1825 else "5+ years")
        buckets[key] += 1
    never = [p for p in people if not p["dm_count"]]
    presets = []
    for name, spec in PRESETS.items():
        n = len(candidates(Criteria.from_preset(name), as_of, people)[0])
        if n:
            presets.append({"preset": name, "label": spec["label"], "count": n})
    return {
        "as_of": as_of.isoformat(),
        "connections_total": total + int(meta.get("connections_without_url", 0) or 0),
        "connections_listable": total,
        "connections_without_url": int(meta.get("connections_without_url", 0) or 0),
        "connected_on_age": buckets,
        "never_messaged_1to1": len(never),
        "only_group_chats": sum(1 for p in never if p["group_count"]),
        "last_dm_over_1_year": sum(1 for p in people if p["days_since_dm"] is not None and p["days_since_dm"] >= 365),
        "last_dm_over_3_years": sum(1 for p in people if p["days_since_dm"] is not None and p["days_since_dm"] >= 3 * 365),
        "messaged_in_last_year": sum(1 for p in people if p["days_since_dm"] is not None and p["days_since_dm"] < 365),
        "cap": LINKEDIN_CONNECTION_CAP,
        "headroom": LINKEDIN_CONNECTION_CAP - total - int(meta.get("connections_without_url", 0) or 0),
        "never_replied": sum(1 for p in people if p["in_count"] and not p["out_count"]),
        "messages": {
            "total": int(meta.get("messages", 0) or 0),
            "earliest": meta.get("earliest_message_at", ""), "latest": meta.get("latest_message_at", ""),
            "people_messaged": int(meta.get("dm_counterparts", 0) or 0),
            "people_messaged_who_are_connections": int(meta.get("dm_counterparts_connected", 0) or 0),
            "loaded": "messages" in table_names(con),
        },
        "presets": presets,
        "next": "Ask the user which preset (or custom thresholds), how many to free up, and who to always keep.",
    }


# ---------------------------------------------------------------------------------------------------------------
# Extension points. Deliberately unimplemented: do not fake these.
# ---------------------------------------------------------------------------------------------------------------

PASS2_MESSAGE = ("Pass 2 uses ICP / persona definitions from Syft or Rolodex and is not run in pass 1. "
                 "Nothing in this file matches people to an ICP. See README, 'Pass 2'.")


def apply_pass2(rows, icp=None, persona=None):
    """Pass 2 hook: filter / annotate pass-1 rows by ICP and persona via the Syft MCP or Rolodex. TODO."""
    raise NotImplementedError(PASS2_MESSAGE)


def to_rolodex_import(rows):
    """Rolodex hook: shape a candidate list for a Rolodex import. TODO, named extension point only."""
    raise NotImplementedError("Rolodex import is not built yet. See README, 'Rolodex'.")
