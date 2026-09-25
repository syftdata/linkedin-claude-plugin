"""Turn a list of LinkedIn people into lead objects for the Syft MCP `enqueue_leads` tool.

Sources: any CSV with a LinkedIn profile column (a cleanup CSV, a Connections.csv, a Sales Navigator or Rolodex
export), or the user's own connections filtered by title / company / keywords. Only people with a readable
/in/<slug> URL become leads; the rest are counted, never guessed. Nothing is sent from here: the agent passes the
JSON to `enqueue_leads` after the user says yes.
"""
import csv
import re
from pathlib import Path

from archive import slug_from_url

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


_PAREN = re.compile(r"\s*[(\[].*?[)\]]\s*")
_EDGE = re.compile(r"^[^\w]+|[^\w.'-]+$", re.UNICODE)
_INITIAL = re.compile(r"^(\w{2,})\s+\w\.?$", re.UNICODE)


def clean_first_name(first):
    """What a "Hey {first}" greeting should use: no emoji or symbols at the edges, no "(nickname)", no trailing
    middle initial, no ALL CAPS. Returns the input unchanged when it already reads fine."""
    s = _PAREN.sub(" ", first or "").strip()
    s = _EDGE.sub("", s).strip()
    m = _INITIAL.match(s)
    if m:
        s = m.group(1)
    if (s.isupper() and len(s) > 2) or s.islower():
        s = s[:1].upper() + s[1:].lower() if s.isupper() else s[:1].upper() + s[1:]
    return s


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
    LinkedIn's own Connections.csv) is skipped by looking for the header row. File order is kept."""
    path = Path(path).expanduser()
    if not path.is_file():
        raise ValueError(f"No such file: {path}")
    with open(path, newline="", encoding="utf-8-sig") as f:
        lines = f.read().splitlines()
    start = next((i for i, line in enumerate(lines)
                  if any(c.strip().lower() in URL_COLS for c in next(csv.reader([line]), []))), None)
    if start is None:
        raise ValueError(f"No LinkedIn URL column in {path.name}. Expected one of: {', '.join(URL_COLS)}")
    out = []
    for row in csv.DictReader(lines[start:]):
        row = {(k or "").strip().lower(): (v or "") for k, v in row.items()}
        out.append((_pick(row, URL_COLS), _pick(row, FIRST_COLS), _pick(row, LAST_COLS), _pick(row, NAME_COLS),
                    _pick(row, TITLE_COLS), _pick(row, COMPANY_COLS)))
    return out


def leads_from_connections(filters, as_of=None):
    """The user's own connections chosen with people.Filters (same rules as the `people` command), in the
    filters' order. Connections LinkedIn exported without a profile URL are counted, never guessed."""
    import people
    rows, summary = people.select(filters, as_of)
    raw = [(p["profile_url"], p["first_name"], p["last_name"], "", p["title"], p["company"]) for p in rows]
    return raw, summary


def build(raw, offset=0, limit=None, clean_names=False, max_people=None):
    """raw: tuples (url, first, last, name, title, company). Dedupes by profile, keeps order.
    max_people caps the list itself (so `total` is the number the user agreed to); offset / limit page it."""
    leads, seen, no_url, dupes, warnings = [], set(), 0, 0, []
    for url, first, last, name, title, company in raw:
        lead = to_lead(url, first, last, name, title, company)
        if not lead:
            no_url += 1
            continue
        if lead["linkedin"] in seen:
            dupes += 1
            continue
        seen.add(lead["linkedin"])
        original = lead.get("firstName", "")
        fixed = clean_first_name(original)
        if fixed != original:
            warnings.append({"linkedin": lead["linkedin"], "firstName": original, "suggested": fixed})
            if clean_names and fixed:
                lead["firstName"] = fixed
        leads.append(lead)
    matched = len(leads)
    if max_people:
        leads = leads[:max_people]
    total = len(leads)
    page = leads[offset:offset + limit] if limit else leads[offset:]
    in_list = {x["linkedin"] for x in leads}
    # Odd names are reported for the whole (capped) list, not just this page, so a preview of 5 still shows them.
    return {"total": total, "matched": matched, "offset": offset, "count": len(page), "skipped_no_url": no_url,
            "duplicates_removed": dupes, "chunk_size": CHUNK, "names_cleaned": clean_names,
            "odd_first_names": [w for w in warnings if w["linkedin"] in in_list], "leads": page}
