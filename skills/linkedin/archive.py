"""Load a LinkedIn data export ZIP into SQLite.

Standard library only. The raw tables keep the CSV's own column names (`connections`, `shares`, `comments`,
`reactions`, plus `messages` and `invitations` from v2), so anything already querying the v1 database keeps working.
v2 adds derived tables for joining people across files:

    connections_index  one row per 1st-degree connection, keyed by normalised profile slug, ISO `connected_on`
    dm_events          one row per (message, counterpart), 1:1 vs group flagged, direction in/out
    last_dm            one row per counterpart: last / first DM, count, last direction, group-only activity

Connections.csv  = people you are connected to (accepted 1st-degree), with a day-level "Connected On".
Invitations.csv  = connection requests sent and received (pending history). Loaded for the bot; not a cleanup input.
messages.csv     = DMs, full UTC timestamps, participants by profile URL.
"""
import collections
import csv
import glob
import os
import re
import sqlite3
import sys
import tempfile
import urllib.parse
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "7"

# The raw tables, in load order. `messages` and `invitations` are new in v2; `Reactions.csv` stays optional.
RAW_FILES = {
    "shares": "Shares.csv",
    "connections": "Connections.csv",
    "comments": "Comments.csv",
    "reactions": "Reactions.csv",
    "messages": "messages.csv",
    "invitations": "Invitations.csv",
    # Your own profile and job search (small files; missing ones are skipped quietly)
    "profile": "Profile.csv",
    "positions": "Positions.csv",
    "education": "Education.csv",
    "skills": "Skills.csv",
    "certifications": "Certifications.csv",
    "saved_jobs": "Saved Jobs.csv",
    "job_applications": "Job Applications.csv",
    "job_preferences": "Job Seeker Preferences.csv",
    "company_follows": "Company Follows.csv",
    "endorsements": "Endorsement_Received_Info.csv",
    "email_addresses": "Email Addresses.csv",
}


def watch_folder():
    return Path(os.environ.get("LINKEDIN_EXPORTS_DIR", Path.home() / ".linkedin-exports")).expanduser()


def db_path():
    # Same default as v1 so existing databases and forks keep their path.
    return Path(os.environ.get("LINKEDIN_DB_PATH", Path.home() / ".linkedin-search" / "data.db")).expanduser()


class NoExportError(RuntimeError):
    pass


# ---------------------------------------------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------------------------------------------

_SLUG_RE = re.compile(r"linkedin\.com/in/([^/?#\s,]+)", re.I)


def slugs_in(text):
    """Every /in/<slug> in a string, lowercased and URL-decoded. A recipient cell can hold several URLs."""
    if not text:
        return []
    return [urllib.parse.unquote(m).lower().rstrip("/") for m in _SLUG_RE.findall(text)]


def slug_from_url(url):
    found = slugs_in(url)
    return found[0] if found else ""


_CONNECTED_FORMATS = ("%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d-%b-%y")


def parse_connected_on(value):
    """'05 Mar 2021' (LinkedIn's usual format) and a few older variants -> ISO date, or '' if unparseable."""
    value = (value or "").strip()
    for fmt in _CONNECTED_FORMATS:
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


_MESSAGE_FORMATS = ("%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%d %H:%M:%S %Z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ",
                    "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y, %I:%M %p", "%m/%d/%y, %I:%M %p")


def parse_message_date(value):
    """'2024-03-05 17:22:10 UTC' -> '2024-03-05T17:22:10Z', or '' if unparseable."""
    value = (value or "").strip()
    for fmt in _MESSAGE_FORMATS:
        try:
            dt = datetime.strptime(value, fmt)
            return dt.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
    return ""


def _col(row, *names):
    """Case- and space-insensitive column lookup, because LinkedIn renames headers between export versions."""
    wanted = {re.sub(r"[^a-z]", "", n.lower()) for n in names}
    for k, v in row.items():
        if k is not None and re.sub(r"[^a-z]", "", k.lower()) in wanted:
            return v or ""
    return ""


# ---------------------------------------------------------------------------------------------------------------
# Reading the export
# ---------------------------------------------------------------------------------------------------------------

def read_csv(path, header_prefix=None):
    """Return (fieldnames, rows). With header_prefix, skip preamble lines (Connections.csv starts with 'Notes:')."""
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
        text = f.read()
    if header_prefix:
        lines = text.splitlines(keepends=True)
        for i, line in enumerate(lines):
            if line.lstrip().startswith(header_prefix):
                text = "".join(lines[i:])
                break
    # Comments.csv escapes quotes with a backslash (\"), the other files double them (""): without escapechar a
    # comment with a quote in it splits into junk rows (1,210 rows parsed from 1,196 real comments).
    reader = csv.DictReader(text.splitlines(keepends=True), **({"escapechar": "\\"} if '\\"' in text else {}))
    fields = [f for f in (reader.fieldnames or []) if f is not None]
    rows = [{k: (v if v is not None else "") for k, v in r.items() if k is not None} for r in reader]
    return fields, rows


def find_export_file(root, basename):
    """Find an export file anywhere in the extracted tree (exports nest a dated folder), case-insensitive.

    LinkedIn now suffixes some files with a member id (`Shares_7789716.csv`, `Comments_7789716.csv`), so
    `Shares.csv` also matches `Shares_<digits>.csv`. The stem must match exactly: `guide_messages.csv` is not
    `messages.csv`."""
    stem, _, ext = basename.lower().rpartition(".")
    pattern = re.compile(rf"^{re.escape(stem)}(_\d+)?\.{re.escape(ext)}$")
    found = sorted(p for p in Path(root).rglob("*") if p.is_file() and pattern.match(p.name.lower()))
    return found[0] if found else None


def _create_raw_table(con, table, fields, rows):
    cols, seen = [], set()
    for i, f in enumerate(fields):
        name = f.strip() or f"column_{i}"
        while name in seen:
            name += "_"
        seen.add(name)
        cols.append(name)
    con.execute(f'CREATE TABLE "{table}" ({", ".join(chr(34) + c + chr(34) + " TEXT" for c in cols)})')
    placeholders = ", ".join("?" for _ in cols)
    con.executemany(f'INSERT INTO "{table}" VALUES ({placeholders})',
                    [[r.get(f, "") for f in fields] for r in rows])


def _build_connections_index(con, rows):
    con.execute("""CREATE TABLE connections_index (
        slug TEXT PRIMARY KEY, first_name TEXT, last_name TEXT, url TEXT, email TEXT,
        company TEXT, position TEXT, connected_on TEXT, connected_on_raw TEXT)""")
    seen = set()
    for r in rows:
        url = _col(r, "URL", "Profile URL")
        s = slug_from_url(url)
        if not s or s in seen:
            continue
        seen.add(s)
        raw = _col(r, "Connected On")
        con.execute("INSERT INTO connections_index VALUES (?,?,?,?,?,?,?,?,?)", (
            s, _col(r, "First Name").strip(), _col(r, "Last Name").strip(), url, _col(r, "Email Address", "Email").strip(),
            _col(r, "Company").strip(), _col(r, "Position").strip(), parse_connected_on(raw), raw))
    con.execute("CREATE INDEX idx_connections_index_connected_on ON connections_index(connected_on)")


def detect_owner(rows):
    """The export owner is the profile that appears in the most messages (every conversation includes them)."""
    counts = collections.Counter()
    for r in rows:
        participants = set(slugs_in(_col(r, "SENDER PROFILE URL"))) | set(slugs_in(_col(r, "RECIPIENT PROFILE URLS")))
        counts.update(participants)
    return counts.most_common(1)[0][0] if counts else ""


def _build_dm_tables(con, rows, owner):
    # Participants per conversation, across all its messages, decide 1:1 vs group.
    conv_people = collections.defaultdict(set)
    parsed = []
    for r in rows:
        sender = slug_from_url(_col(r, "SENDER PROFILE URL"))
        recipients = slugs_in(_col(r, "RECIPIENT PROFILE URLS"))
        cid = _col(r, "CONVERSATION ID") or f"{sender}|{'|'.join(sorted(recipients))}"
        sent_at = parse_message_date(_col(r, "DATE"))
        people = ({sender} | set(recipients)) - {owner, ""}
        conv_people[cid] |= people
        parsed.append((cid, sent_at, sender, people, _col(r, "CONTENT")))

    con.execute("""CREATE TABLE dm_events (
        conversation_id TEXT, sent_at TEXT, sender_slug TEXT, counterpart_slug TEXT,
        is_group INTEGER, direction TEXT, preview TEXT)""")
    events = []
    for cid, sent_at, sender, people, content in parsed:
        if not sent_at:
            continue
        is_group = 1 if len(conv_people[cid]) > 1 else 0
        direction = "out" if sender == owner else "in"
        preview = re.sub(r"\s+", " ", content or "").strip()[:600]
        for p in people:
            events.append((cid, sent_at, sender, p, is_group, direction, preview))
    con.executemany("INSERT INTO dm_events VALUES (?,?,?,?,?,?,?)", events)
    con.execute("CREATE INDEX idx_dm_events_counterpart ON dm_events(counterpart_slug, sent_at)")

    # last_dm_direction / last_dm_preview come from the last message with text: an empty one is a reaction or an
    # attachment, and "they reacted to my 'will do'" is not a message waiting for a reply.
    # opened_by: who wrote first in the latest conversation (after a 60+ day silence), a better "who reached out"
    # than who wrote first years ago.
    con.execute("""CREATE TABLE last_dm (
        counterpart_slug TEXT PRIMARY KEY, dm_count INTEGER, first_dm_at TEXT, last_dm_at TEXT,
        last_dm_direction TEXT, last_dm_preview TEXT, group_count INTEGER, last_group_at TEXT,
        out_count INTEGER, in_count INTEGER, opened_by TEXT, opened_at TEXT, last_dm_text TEXT, opened_text TEXT)""")
    per = {}
    for cid, sent_at, sender, p, is_group, direction, preview in sorted(events, key=lambda e: e[1]):
        d = per.setdefault(p, {"dm_count": 0, "first": "", "last": "", "dir": "", "preview": "", "group_count": 0,
                               "last_group": "", "out": 0, "in": 0, "opened_by": "", "opened_at": ""})
        if is_group:
            d["group_count"] += 1
            d["last_group"] = sent_at
        else:
            prev = d["last"]
            if not prev or (_days(prev, sent_at) or 0) >= 60:
                d["opened_by"], d["opened_at"] = ("you" if direction == "out" else "them"), sent_at
                d["opened_text"] = preview or ""
            elif not d.get("opened_text") and preview and (direction == "out") == (d["opened_by"] == "you"):
                d["opened_text"] = preview                      # the opener's first message with text
            d["dm_count"] += 1
            d["out" if direction == "out" else "in"] += 1
            d["first"] = d["first"] or sent_at
            d["last"] = sent_at
            if (preview or "").strip():
                d["dir"], d["preview"], d["text"] = direction, preview[:140], preview
            elif not d["dir"]:
                d["dir"] = direction
    con.executemany("INSERT INTO last_dm VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        (p, d["dm_count"], d["first"] or None, d["last"] or None, d["dir"] or None, d["preview"] or None,
         d["group_count"], d["last_group"] or None, d["out"], d["in"], d["opened_by"] or None, d["opened_at"] or None,
         d.get("text") or None, (d.get("opened_text") or "")[:300] or None)
        for p, d in per.items()])
    return events


def _days(a, b):
    """Days between two ISO timestamps (b later), or None."""
    try:
        fa = datetime.fromisoformat(a.replace("Z", "+00:00"))
        fb = datetime.fromisoformat(b.replace("Z", "+00:00"))
        return (fb - fa).days
    except (ValueError, AttributeError):
        return None


def load_export(zip_path, target_db=None, log=print):
    """Extract the ZIP and (re)build the database. Builds into a temp file, then swaps it in."""
    zip_path = Path(zip_path)
    target_db = Path(target_db or db_path())
    target_db.parent.mkdir(parents=True, exist_ok=True)
    tmp_db = target_db.with_suffix(f".building.{os.getpid()}")
    if tmp_db.exists():
        tmp_db.unlink()
    stats = {}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(tmp)
            con = sqlite3.connect(tmp_db)
            conn_rows, msg_rows = [], []
            for table, fname in RAW_FILES.items():
                path = find_export_file(tmp, fname)
                if not path:
                    if table in ("messages", "invitations"):
                        log(f"  ⚠️  {fname} not in this export (request the larger data archive for it)")
                    elif table in ("shares", "connections", "comments"):
                        log(f"  ⚠️  {fname} not found, skipping...")
                    continue
                fields, rows = read_csv(path, header_prefix="First Name" if table == "connections" else None)
                if not fields:
                    continue
                _create_raw_table(con, table, fields, rows)
                stats[table] = len(rows)
                log(f"  ✓ {table}: {len(rows):,}")
                if table == "connections":
                    conn_rows = rows
                elif table == "messages":
                    msg_rows = rows

            # v1 indexes, same columns
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table, cols in (("shares", ("ShareCommentary", "Date")), ("connections", ("Position", "Company")),
                                ("comments", ("Comment", "Message", "Date"))):
                if table in tables:
                    present = {r[1] for r in con.execute(f'PRAGMA table_info("{table}")')}
                    for c in (c for c in cols if c in present):
                        con.execute(f'CREATE INDEX IF NOT EXISTS "idx_{table}_{c}" ON "{table}"("{c}")')

            _build_connections_index(con, conn_rows)
            owner = detect_owner(msg_rows)
            events = _build_dm_tables(con, msg_rows, owner)

            connected = {r[0] for r in con.execute("SELECT slug FROM connections_index")}
            counterparts = {r[0] for r in con.execute("SELECT counterpart_slug FROM last_dm")}
            dated = [e[1] for e in events]
            stats.update({
                "owner_slug": owner,
                "connections_indexed": len(connected),
                # LinkedIn blanks the URL for some members; they can't be joined to messages or listed for cleanup.
                "connections_without_url": sum(1 for r in conn_rows if not slug_from_url(_col(r, "URL", "Profile URL"))),
                "connections_with_date": con.execute("SELECT COUNT(*) FROM connections_index WHERE connected_on != ''").fetchone()[0],
                "dm_counterparts": len(counterparts),
                "dm_counterparts_connected": len(counterparts & connected),
                "connections_with_any_message": len(counterparts & connected),
                "earliest_message_at": min(dated) if dated else "",
                "latest_message_at": max(dated) if dated else "",
            })
            con.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
            meta = {"last_loaded_zip": str(zip_path), "last_loaded_timestamp": str(os.path.getmtime(zip_path)),
                    "schema_version": SCHEMA_VERSION, "loaded_at": datetime.now(timezone.utc).isoformat()}
            meta.update({k: str(v) for k, v in stats.items()})
            con.executemany("INSERT OR REPLACE INTO metadata VALUES (?, ?)", meta.items())
            con.commit()
            con.close()
        os.replace(tmp_db, target_db)
    except zipfile.BadZipFile:
        if tmp_db.exists():
            tmp_db.unlink()
        raise NoExportError(f"{zip_path} is not a valid ZIP file")
    return stats


# ---------------------------------------------------------------------------------------------------------------
# Keeping the database current
# ---------------------------------------------------------------------------------------------------------------

def find_latest_export():
    exports = glob.glob(str(watch_folder() / "*.zip"))
    return max(exports, key=os.path.getmtime) if exports else None


def read_metadata(path=None):
    path = Path(path or db_path())
    if not path.exists():
        return {}
    try:
        con = sqlite3.connect(path)
        rows = con.execute("SELECT key, value FROM metadata").fetchall()
        con.close()
        return dict(rows)
    except sqlite3.Error:
        return {}


def add_to_watch_folder(zip_path):
    import shutil
    src = Path(os.path.expanduser(str(zip_path).strip().strip('"').strip("'")))
    if not src.exists():
        raise NoExportError(f"File not found: {src}")
    if src.suffix.lower() != ".zip":
        raise NoExportError("File must be a ZIP archive")
    folder = watch_folder()
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / src.name
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    return dest


def download_candidates(folder=None):
    """LinkedIn export ZIPs sitting in ~/Downloads (or `folder`), best first: the larger archive ("Complete_...")
    before the basic one, newest first. Browsers sometimes save them as ".zip.zip"."""
    folder = Path(folder or Path.home() / "Downloads").expanduser()
    if not folder.is_dir():
        return []
    found = [p for p in list(folder.glob("*LinkedInDataExport*.zip*")) + list(folder.glob("*/*LinkedInDataExport*.zip*"))
             if p.is_file() and p.name.lower().endswith(".zip")]
    return sorted(set(found), key=lambda p: ("complete" not in p.name.lower(), -p.stat().st_mtime))


def prompt_for_export():
    """Interactive first run only. Agents can't answer input(), so they get the ingest command instead, plus any
    export ZIPs found in ~/Downloads so they can ask the user which one to load."""
    found = download_candidates()
    hint = ""
    if found:
        hint = "\nFound in your Downloads (ask the user before loading):\n" + "\n".join(
            f"  {p}" + ("   ← smaller archive, has no messages" if "basic" in p.name.lower() else "")
            for p in found[:5]) + "\n"
    cli = Path(__file__).resolve().parent / "linkedin.py"
    msg = ("No LinkedIn export loaded yet.\n" + hint + "\n"
           f"Load one with:\n  python3 {cli} ingest --zip /path/to/Complete_LinkedInDataExport.zip\n"
           "No export yet? LinkedIn → Settings → Data privacy → Get a copy of your data → larger data archive "
           "(LinkedIn emails a link, usually within a day).")
    if not sys.stdin.isatty():
        raise NoExportError(msg.format(folder=watch_folder()))
    print(f"📂 No LinkedIn exports found in {watch_folder()}\n")
    print("Please provide the path to your LinkedIn export ZIP file.")
    print("(Download from: LinkedIn Settings → Data Privacy → Get a copy of your data)\n")
    path = input("Path to LinkedIn export ZIP: ")
    if not path.strip():
        raise NoExportError("No path provided")
    dest = add_to_watch_folder(path)
    print(f"📦 Copied to {dest}")
    return str(dest)


def ensure_db_current(zip_path=None, force=False, log=print):
    """Load the newest export if it is newer than the database, the database is v1, or a ZIP was named."""
    watch_folder().mkdir(parents=True, exist_ok=True)
    latest = str(add_to_watch_folder(zip_path)) if zip_path else find_latest_export()
    if not latest:
        latest = prompt_for_export()
    def stale():
        meta = read_metadata()
        return (force or zip_path is not None or not db_path().exists()
                or meta.get("schema_version") != SCHEMA_VERSION
                or os.path.getmtime(latest) > float(meta.get("last_loaded_timestamp") or 0)
                or meta.get("last_loaded_zip") not in (None, latest))

    if not stale():
        return None
    # Claude often runs two commands at once. One loads; the other waits for it and then uses the result.
    db_path().parent.mkdir(parents=True, exist_ok=True)
    with _load_lock():
        if not force and zip_path is None and not stale():
            return None
        log(f"🔄 Loading {Path(latest).name}...")
        stats = load_export(latest, log=log)
        log("✓ Database ready!\n")
        return stats


class _load_lock:
    """An exclusive lock next to the database while it is (re)built. No-op where fcntl is missing (Windows)."""
    def __enter__(self):
        self.f = open(str(db_path()) + ".lock", "w")
        try:
            import fcntl
            fcntl.flock(self.f, fcntl.LOCK_EX)
        except ImportError:
            pass
        return self

    def __exit__(self, *exc):
        try:
            import fcntl
            fcntl.flock(self.f, fcntl.LOCK_UN)
        except ImportError:
            pass
        self.f.close()


def connect():
    con = sqlite3.connect(db_path())
    con.row_factory = sqlite3.Row
    return con


def table_names(con):
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
