"""Turn a list of LinkedIn people into lead objects for the Syft MCP `enqueue_leads` tool.

Sources: any CSV with a LinkedIn profile column (a cleanup CSV, a Connections.csv, a Sales Navigator or Rolodex
export), or the user's own connections filtered by title / company / keywords. Only people with a readable
/in/<slug> URL become leads; the rest are counted, never guessed. Nothing is sent from here: the agent passes the
JSON to `enqueue_leads` after the user says yes.
"""
import csv
from pathlib import Path

from archive import slug_from_url
import search

URL_COLS = ("linkedin", "linkedin url", "linkedin_url", "linkedin profile", "profile_url", "profile url", "url")
NAME_COLS = ("name", "full name", "full_name")
FIRST_COLS = ("first name", "first_name", "firstname")
LAST_COLS = ("last name", "last_name", "lastname")
TITLE_COLS = ("title", "job title", "job_title", "position")
COMPANY_COLS = ("company", "company name", "company_name", "organization")

CHUNK = 100  # leads per enqueue_leads call the skill recommends


def _pick(row, names):
    for n in names:
        v = row.get(n)
        if v and v.strip():
            return v.strip()
    return ""


def profile_url(value):
    """Canonical https://www.linkedin.com/in/<slug>, or "" when there is no readable profile slug."""
    value = (value or "").strip()
    if value.lower().startswith("in/"):
        value = "https://www.linkedin.com/" + value
    slug = slug_from_url(value)
    return f"https://www.linkedin.com/in/{slug}" if slug else ""


def to_lead(url, first="", last="", name="", title="", company=""):
    url = profile_url(url)
    if not url:
        return None
    first, last, name = first.strip(), last.strip(), name.strip()
    if not name:
        name = " ".join(x for x in (first, last) if x)
    if name and not (first or last):
        first, _, last = name.partition(" ")
    lead = {"linkedin": url, "name": name, "firstName": first, "lastName": last.strip(), "title": title.strip(),
            "company": company.strip()}
    return {k: v for k, v in lead.items() if v}


def leads_from_csv(path):
    """Read any CSV with a LinkedIn column. Header names are matched case-insensitively; a preamble (as in
    LinkedIn's own Connections.csv) is skipped by looking for the header row."""
    path = Path(path).expanduser()
    if not path.is_file():
        raise ValueError(f"No such file: {path}")
    with open(path, newline="", encoding="utf-8-sig") as f:
        lines = f.read().splitlines()
    start = next((i for i, line in enumerate(lines)
                  if any(c.strip().lower() in URL_COLS for c in next(csv.reader([line]), []))), None)
    if start is None:
        raise ValueError(f"No LinkedIn URL column in {path.name}. Expected one of: {', '.join(URL_COLS)}")
    rows = csv.DictReader(lines[start:])
    out = []
    for row in rows:
        row = {(k or "").strip().lower(): (v or "") for k, v in row.items()}
        out.append((_pick(row, URL_COLS), _pick(row, FIRST_COLS), _pick(row, LAST_COLS), _pick(row, NAME_COLS),
                    _pick(row, TITLE_COLS), _pick(row, COMPANY_COLS)))
    return out


def leads_from_connections(title="", company="", keywords=None):
    rows = search.search_connections_keywords(keywords) if keywords else search.find_connections(title, company)
    return [(r["url"], r["first_name"] or "", r["last_name"] or "", "", r["position"] or "", r["company"] or "")
            for r in rows]


def build(raw, offset=0, limit=None):
    """raw: tuples (url, first, last, name, title, company). Dedupes by profile, keeps order."""
    leads, seen, no_url, dupes = [], set(), 0, 0
    for url, first, last, name, title, company in raw:
        lead = to_lead(url, first, last, name, title, company)
        if not lead:
            no_url += 1
            continue
        if lead["linkedin"] in seen:
            dupes += 1
            continue
        seen.add(lead["linkedin"])
        leads.append(lead)
    total = len(leads)
    page = leads[offset:offset + limit] if limit else leads[offset:]
    return {"total": total, "offset": offset, "count": len(page), "skipped_no_url": no_url,
            "duplicates_removed": dupes, "chunk_size": CHUNK, "leads": page}
