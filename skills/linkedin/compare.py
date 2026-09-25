"""Compare two LinkedIn exports: who changed jobs, who is new, who is gone.

Only Connections.csv is compared, matched by profile URL. "Gone" means the person was a connection in the older
export and is not in the newer one: they removed you, you removed them, or their account closed; the export can't
tell which. "New company" / "new title" is what their profile said on each export day, so a job change shows up
here with a lag (whatever they had updated by then). A company renamed with an emoji or "Inc." is not a job change.
Rows LinkedIn exported without a URL can't be matched and are counted, not guessed.
"""
import re
import tempfile
import zipfile
from pathlib import Path

from archive import connect, find_export_file, parse_connected_on, read_csv, slug_from_url, table_names

KINDS = ("new company", "new title", "new connection", "no longer connected")
_ONLY = {"moved": "new company", "retitled": "new title", "new": "new connection", "gone": "no longer connected"}


def _zip_date(path):
    """When the export was made: the timestamp LinkedIn put on Connections.csv inside the ZIP, else the date in
    the file name (Complete_LinkedInDataExport_09-15-2026.zip). Returns (iso date, how we know)."""
    try:
        with zipfile.ZipFile(path) as z:
            info = next((i for i in z.infolist() if i.filename.lower().endswith("connections.csv")), None)
            if info and info.date_time[0] >= 2003:
                y, mo, d = info.date_time[:3]
                return f"{y:04d}-{mo:02d}-{d:02d}", "file date inside the ZIP"
    except (zipfile.BadZipFile, OSError):
        pass
    m = re.search(r"(\d{2})-(\d{2})-(\d{4})", Path(path).name)
    if m:
        return f"{m.group(3)}-{m.group(1)}-{m.group(2)}", "date in the file name"
    return None, None


def _index(rows):
    out, no_url, dated = {}, 0, []
    for r in rows:
        slug = slug_from_url(r.get("URL") or r.get("Profile URL") or "")
        if not slug:
            no_url += 1
            continue
        iso = parse_connected_on(r.get("Connected On") or "")
        if iso:
            dated.append(iso)
        if slug not in out:
            out[slug] = {"name": " ".join(f"{r.get('First Name', '')} {r.get('Last Name', '')}".split()),
                         "company": " ".join((r.get("Company") or "").split()),
                         "title": " ".join((r.get("Position") or "").split()),
                         "connected_on": iso or "", "profile_url": f"https://www.linkedin.com/in/{slug}"}
    return out, no_url, (max(dated) if dated else None)


def _from_zip(zip_path):
    zip_path = Path(zip_path).expanduser()
    if not zip_path.is_file():
        raise ValueError(f"No such file: {zip_path}")
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(zip_path) as z:
            names = [n for n in z.namelist() if n.lower().endswith("connections.csv")]
            if not names:
                raise ValueError(f"{zip_path.name} has no Connections.csv")
            z.extract(names[0], tmp)
        _, rows = read_csv(find_export_file(tmp, "Connections.csv"), header_prefix="First Name")
    idx, no_url, latest = _index(rows)
    made, how = _zip_date(zip_path)
    return idx, no_url, (made, how) if made else (latest, "about: newest connection date, not certain")


def _from_db():
    con = connect()
    if "connections_index" not in table_names(con):
        raise ValueError("No export loaded yet. Pass two ZIPs, or run `ingest` first.")
    rows = [{"First Name": f, "Last Name": l, "URL": u, "Company": c, "Position": p, "Connected On": raw}
            for f, l, u, c, p, raw in con.execute(
                "SELECT first_name, last_name, url, company, position, connected_on_raw FROM connections_index")]
    no_url = 0
    if "connections" in table_names(con):
        no_url = con.execute("SELECT COUNT(*) FROM connections WHERE COALESCE(URL,'') = ''").fetchone()[0]
    idx, _, latest = _index(rows)
    from archive import read_metadata
    loaded = read_metadata().get("last_loaded_zip")
    if loaded and Path(loaded).is_file():
        made, how = _zip_date(loaded)
        if made:
            return idx, no_url, (made, how)
    from invites import export_date
    ed = export_date(con)
    return idx, no_url, (ed.isoformat(), "about: latest date in the data") if ed else (latest, "about")


def _same_text(a, b):
    norm = lambda x: " ".join((x or "").replace(" ", " ").replace("​", "").split()).casefold()
    return norm(a) == norm(b)


def _same_company(a, b):
    from people import normalize_company
    return normalize_company(a) == normalize_company(b) or _same_text(a, b)


def _dm_stats():
    """slug → message facts from the loaded export, for everyone you have messaged, connected or not (so "who
    removed me" can say you talked 12 times), plus email for current connections."""
    try:
        from people import warmth, warmth_label
        from cleanup import load_people
        from invites import export_date
        from datetime import date
        as_of = export_date() or date.today()
        out = {}
        con = connect()
        if "last_dm" in table_names(con):
            for slug, n, last, out_c, in_c in con.execute(
                    "SELECT counterpart_slug, dm_count, last_dm_at, out_count, in_count FROM last_dm WHERE dm_count > 0"):
                d = date.fromisoformat(last[:10]) if last else None
                p = {"dm_count": n, "days_since_dm": (as_of - d).days if d else None, "in_count": in_c or 0,
                     "out_count": out_c or 0}
                out[slug] = {"warmth": warmth(p), "warmth_label": warmth_label(p), "dms": n,
                             "last_dm": (last or "")[:10], "email": ""}
        for p in load_people():
            if p["slug"] and p.get("email"):
                out.setdefault(p["slug"], {"warmth": 0.0, "warmth_label": "never messaged", "dms": 0,
                                           "last_dm": "", "email": ""})["email"] = p["email"]
        return out
    except Exception:
        return {}


def other_exports(exclude=None):
    """LinkedIn export ZIPs in the watch folder and ~/Downloads made on a different day from `exclude` (the loaded
    one), oldest first, one per day. The same export usually sits in both places: a copy is not another export."""
    from archive import download_candidates, watch_folder
    found = {p.resolve() for p in download_candidates()}
    found |= {p.resolve() for p in Path(watch_folder()).glob("*.zip")}
    skip = Path(exclude).resolve() if exclude else None
    skip_date = _zip_date(skip)[0] if skip and skip.is_file() else None
    by_date = {}
    for p in sorted(found):
        if skip and p == skip:
            continue
        made, _ = _zip_date(p)
        if made and made == skip_date:
            continue
        by_date.setdefault(made or str(p), p)
    return [p for _, p in sorted(by_date.items())]


def compare(old_zip, new_zip=None, filters=None, only=None):
    """old_zip vs new_zip (or vs the export currently loaded). Returns (changes, summary).

    filters: people.Filters; only its role / title / company / name parts are used, against the current and the
    previous title and company, so "only RevOps and sales leaders" also catches someone who moved out of RevOps.
    only: 'moved' / 'retitled' / 'new' / 'gone'."""
    old, old_no_url, (old_date, old_how) = _from_zip(old_zip)
    new, new_no_url, (new_date, new_how) = _from_zip(new_zip) if new_zip else _from_db()
    stats = _dm_stats()
    changes = []
    for s in new.keys() - old.keys():
        changes.append(dict(new[s], change="new connection", before=""))
    for s in old.keys() - new.keys():
        changes.append(dict(old[s], change="no longer connected", before=""))
    for s in new.keys() & old.keys():
        o, n = old[s], new[s]
        if not _same_company(o["company"], n["company"]):
            changes.append(dict(n, change="new company", before=f"{o['title']} @ {o['company']}",
                                before_title=o["title"], before_company=o["company"]))
        elif not _same_text(o["title"], n["title"]):
            changes.append(dict(n, change="new title", before=o["title"], before_title=o["title"],
                                before_company=o["company"]))
    for c in changes:
        c.update(stats.get(slug_from_url(c["profile_url"]), {"warmth": 0.0, "warmth_label": "", "dms": 0,
                                                            "last_dm": "", "email": ""}))
    if filters is not None and (filters.company_list or filters.companies):
        # With companies named, say which way each mover went: left one of them, or joined one.
        from people import company_matches
        named = list(filters.company_list) + [(c, None) for c in filters.companies]
        hit = lambda company, w, label: company_matches(company, w) if w is not None else \
            label.lower() in (company or "").lower()
        for c in changes:
            if c["change"] != "new company":
                continue
            # a typed --company is a fragment ("snowflake"): name the company as it appears in the data
            left = next(((l if w is not None else c.get("before_company")) for l, w in named
                         if hit(c.get("before_company", ""), w, l)), None)
            joined = next(((l if w is not None else c["company"]) for l, w in named if hit(c["company"], w, l)), None)
            c["direction"] = f"left {left}" if left else f"joined {joined}" if joined else ""
    if filters is not None and filters.describe() != "all connections":
        from people import _who
        keep = []
        for c in changes:
            now = {"title": c["title"], "company": c["company"], "name": c["name"], "email": c.get("email", ""),
                   "days_since_connect": None}
            before = dict(now, title=c.get("before_title", ""), company=c.get("before_company", ""))
            if _who(now, filters) or (c.get("before_title") is not None and _who(before, filters)):
                keep.append(c)
        changes = keep
    counts = {k: sum(1 for c in changes if c["change"] == k) for k in KINDS}
    from people import ROLES, role_match
    movers_by_role = {r: sum(1 for c in changes if c["change"] == "new company" and
                             (role_match(c["title"], r) or role_match(c.get("before_title", ""), r)))
                      for r in ROLES}
    if only:
        changes = [c for c in changes if c["change"] == _ONLY[only]]
    order = {k: i for i, k in enumerate(KINDS)}
    changes.sort(key=lambda c: (order[c["change"]], -c["warmth"], c["name"].lower()))
    gap = None
    if old_date and new_date:
        from datetime import date as _d
        gap = (_d.fromisoformat(new_date) - _d.fromisoformat(old_date)).days
    summary = {"older": len(old), "newer": len(new), "older_date": old_date, "newer_date": new_date,
               "left_listed": sum(1 for c in changes if c.get("direction", "").startswith("left")),
               "joined_listed": sum(1 for c in changes if c.get("direction", "").startswith("joined")),
               "older_date_source": old_how, "newer_date_source": new_how, "days_between": gap,
               "movers_by_role": {r: n for r, n in movers_by_role.items() if n},
               "new_connections": counts["new connection"], "no_longer_connected": counts["no longer connected"],
               "changed_company": counts["new company"], "changed_title": counts["new title"],
               "without_url_skipped": {"older": old_no_url, "newer": new_no_url},
               "newer_source": str(new_zip) if new_zip else "the export currently loaded",
               "filtered": bool(filters is not None and filters.describe() != "all connections"),
               "warning": ("The 'older' export looks newer than the other one: swap them, or new and gone are "
                           "reversed.") if gap is not None and gap < 0 else
                          (f"The two exports are only {gap} days apart: few people change jobs that fast, so expect "
                           "little.") if gap is not None and gap < 30 else None}
    return changes, summary
