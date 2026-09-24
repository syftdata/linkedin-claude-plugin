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

SCHEMA_VERSION = "2"

# The raw tables, in load order. `messages` and `invitations` are new in v2; `Reactions.csv` stays optional.
RAW_FILES = {
    "shares": "Shares.csv",
    "connections": "Connections.csv",
    "comments": "Comments.csv",
    "reactions": "Reactions.csv",
    "messages": "messages.csv",
    "invitations": "Invitations.csv",
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
    reader = csv.DictReader(text.splitlines(keepends=True))
    fields = [f for f in (reader.fieldnames or []) if f is not None]
    rows = [{k: (v if v is not None else "") for k, v in r.items() if k is not None} for r in reader]
    return fields, rows


def find_export_file(root, basename):
    """Exact basename match, case-insensitive, anywhere in the extracted tree (exports nest a dated folder)."""
    target = basename.lower()
    for p in sorted(Path(root).rglob("*")):
        if p.is_file() and p.name.lower() == target:
            return p
    return None


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
            s, _col(r, "First Name"), _col(r, "Last Name"), url, _col(r, "Email Address", "Email"),
            _col(r, "Company"), _col(r, "Position"), parse_connected_on(raw), raw))
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
        preview = re.sub(r"\s+", " ", content or "").strip()[:140]
        for p in people:
            events.append((cid, sent_at, sender, p, is_group, direction, preview))
    con.executemany("INSERT INTO dm_events VALUES (?,?,?,?,?,?,?)", events)
    con.execute("CREATE INDEX idx_dm_events_counterpart ON dm_events(counterpart_slug, sent_at)")

    con.execute("""CREATE TABLE last_dm (
        counterpart_slug TEXT PRIMARY KEY, dm_count INTEGER, first_dm_at TEXT, last_dm_at TEXT,
        last_dm_direction TEXT, last_dm_preview TEXT, group_count INTEGER, last_group_at TEXT,
        out_count INTEGER, in_count INTEGER)""")
    per = {}
    for cid, sent_at, sender, p, is_group, direction, preview in sorted(events, key=lambda e: e[1]):
        d = per.setdefault(p, {"dm_count": 0, "first": "", "last": "", "dir": "", "preview": "", "group_count": 0,
                               "last_group": "", "out": 0, "in": 0})
        if is_group:
            d["group_count"] += 1
            d["last_group"] = sent_at
        else:
            d["dm_count"] += 1
            d["out" if direction == "out" else "in"] += 1
            d["first"] = d["first"] or sent_at
            d["last"], d["dir"], d["preview"] = sent_at, direction, preview
    con.executemany("INSERT INTO last_dm VALUES (?,?,?,?,?,?,?,?,?,?)", [
        (p, d["dm_count"], d["first"] or None, d["last"] or None, d["dir"] or None, d["preview"] or None,
         d["group_count"], d["last_group"] or None, d["out"], d["in"]) for p, d in per.items()])
    return events


def load_export(zip_path, target_db=None, log=print):
    """Extract the ZIP and (re)build the database. Builds into a temp file, then swaps it in."""
    zip_path = Path(zip_path)
    target_db = Path(target_db or db_path())
    target_db.parent.mkdir(parents=True, exist_ok=True)
    tmp_db = target_db.with_suffix(".building")
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
                    elif table != "reactions":
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
                                ("comments", ("Comment", "Date"))):
                if table in tables:
                    for c in cols:
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


def prompt_for_export():
    """Interactive first run only. Agents can't answer input(), so they get the ingest command instead."""
    msg = ("📂 No LinkedIn exports found in {folder}\n\n"
           "Download the larger data archive (LinkedIn Settings → Data privacy → Get a copy of your data), then:\n"
           "  python3 skills/linkedin/linkedin.py ingest --zip /path/to/Complete_LinkedInDataExport.zip")
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
    meta = read_metadata()
    stale = (
        force or zip_path is not None or not db_path().exists()
        or meta.get("schema_version") != SCHEMA_VERSION
        or os.path.getmtime(latest) > float(meta.get("last_loaded_timestamp") or 0)
        or meta.get("last_loaded_zip") not in (None, latest)
    )
    if stale:
        log(f"🔄 Loading {Path(latest).name}...")
        stats = load_export(latest, log=log)
        log("✓ Database ready!\n")
        return stats
    return None


def connect():
    con = sqlite3.connect(db_path())
    con.row_factory = sqlite3.Row
    return con


def table_names(con):
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
