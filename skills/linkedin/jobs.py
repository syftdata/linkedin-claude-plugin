"""Your own job search and profile, from the export.

- Companies from your job search: jobs you saved or applied to, dream companies from your job-seeker preferences,
  and (optionally) companies you follow. Used as a company list, so "who do I know where I applied?" is one command.
- Your profile as a Markdown resume: headline, summary, positions, education, skills, certifications.
"""
import re
from datetime import datetime

from archive import connect, table_names


def _date(s):
    """Saved Jobs '11/10/22, 11:51 PM', Company Follows 'Fri Jul 03 16:00:58 UTC 2026' → ISO date, else ''."""
    s = " ".join((s or "").split())
    for fmt in ("%m/%d/%y, %I:%M %p", "%m/%d/%Y, %I:%M %p", "%a %b %d %H:%M:%S UTC %Y", "%Y/%m/%d %H:%M:%S UTC"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def job_companies(include_followed=False, since=None):
    """[{label, words, when, why}] one per company, newest first. since: ISO date, keeps entries on or after it
    (dream companies have no date and are always kept)."""
    from people import company_words
    con = connect()
    names = table_names(con)
    seen = {}

    def add(company, when, why):
        label = " ".join((company or "").split())
        words = company_words(label)
        if not words:
            return
        key = tuple(words)
        if key not in seen or when > seen[key]["when"]:
            seen[key] = {"label": label, "words": words, "when": when, "why": why}

    if "saved_jobs" in names:
        for comp, title, d in con.execute('SELECT "Company Name", "Job Title", "Saved Date" FROM saved_jobs'):
            add(comp, _date(d), f"saved job: {' '.join((title or '').split())}")
    if "job_applications" in names:
        for comp, title, d in con.execute(
                'SELECT "Company Name", "Job Title", "Application Date" FROM job_applications'):
            add(comp, _date(d), f"applied: {' '.join((title or '').split())}")
    if "job_preferences" in names:
        cols = {r[1] for r in con.execute('PRAGMA table_info("job_preferences")')}
        if "Dream Companies" in cols:
            for (dream,) in con.execute('SELECT "Dream Companies" FROM job_preferences'):
                for c in re.split(r"[,;|]", dream or ""):
                    add(c, "", "dream company")
    if include_followed and "company_follows" in names:
        for org, d in con.execute('SELECT "Organization", "Followed On" FROM company_follows'):
            add(org, _date(d), "you follow them")
    out = [x for x in seen.values() if not since or not x["when"] or x["when"] >= since]
    return sorted(out, key=lambda x: x["when"], reverse=True)


def past_companies():
    """[{label, words, when, why}] for the companies you worked at and left (Positions.csv with an end date):
    connections there now are likely former colleagues, or know people who were."""
    from people import company_words
    con = connect()
    if "positions" not in table_names(con):
        return []
    seen = {}
    for comp, title, start, end in con.execute(
            'SELECT "Company Name", "Title", "Started On", "Finished On" FROM positions'):
        label = " ".join((comp or "").split())
        if not label or not (end or "").strip():
            continue
        words = company_words(label)
        if words and tuple(words) not in seen:
            seen[tuple(words)] = {"label": label, "words": words, "when": (end or "").strip(),
                                  "why": f"you worked there ({' '.join((start or '').split())} – {' '.join(end.split())})"}
    return list(seen.values())


def as_company_list(entries):
    """[(label, words)] for people.Filters.company_list, plus label → why."""
    return [(e["label"], e["words"]) for e in entries], {e["label"]: e["why"] for e in entries}


def counts():
    con = connect()
    names = table_names(con)
    n = lambda t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] if t in names else 0
    return {"saved_jobs": n("saved_jobs"), "applications": n("job_applications"), "followed_companies": n("company_follows")}


def resume():
    """Your profile as Markdown, from Profile / Positions / Education / Skills / Certifications. Returns (text,
    what was missing)."""
    con = connect()
    names = table_names(con)
    rows = lambda t: [dict(zip([c[0] for c in cur.description], r)) for cur in [con.execute(f'SELECT * FROM "{t}"')]
                      for r in cur.fetchall()] if t in names else []
    clean = lambda s: " ".join((s or "").split())
    out, missing = [], []
    from people import clean_person_name
    prof = rows("profile")
    emails = rows("email_addresses")
    primary = next((clean(e.get("Email Address")) for e in emails if clean(e.get("Primary")).lower() == "yes"), "")
    if prof:
        p = prof[0]
        out.append(f"# {clean_person_name(clean(p.get('First Name')) + ' ' + clean(p.get('Last Name')))}".rstrip())
        contact = " · ".join(x for x in (clean(p.get("Geo Location")), primary) if x)
        if clean(p.get("Headline")):
            out.append(f"**{clean(p['Headline'])}**")
        if contact:
            out.append(contact)
        if (p.get("Summary") or "").strip():
            out += ["", (p["Summary"] or "").strip()]
    else:
        missing.append("Profile.csv")
    pos = rows("positions")
    if pos:
        out += ["", "## Experience"]
        for r in pos:
            when = f"{clean(r.get('Started On'))} – {clean(r.get('Finished On')) or 'Present'}"
            out += ["", f"### {clean(r.get('Title'))}, {clean(r.get('Company Name'))}",
                    f"{when}" + (f" · {clean(r.get('Location'))}" if clean(r.get("Location")) else "")]
            desc = (r.get("Description") or "").strip()
            if clean(r.get("Finished On")):              # a role that ended can't say "Present" inside it
                desc = re.sub(r"\bPresent\b", clean(r.get("Finished On")), desc)
            if desc:
                # LinkedIn flattens bullet lists into " - a - b" or runs of spaces: put them back on their own lines
                month = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? \d{4}"
                desc = re.sub(rf"({month})\s*-\s*({month}|Present)", r"\1 – \2:", desc)   # keep date ranges whole
                parts = [x.strip(" -•") for x in re.split(r"\s{2,}|\s+[-•]\s+(?=[A-Z0-9])|\n+", desc) if x.strip(" -•")]
                out += [f"- {x}" for x in parts] if len(parts) > 1 else [desc]
    else:
        missing.append("Positions.csv")
    edu = rows("education")
    if edu:
        out += ["", "## Education"]
        for r in edu:
            years = "–".join(x for x in (clean(r.get("Start Date")), clean(r.get("End Date"))) if x)
            degree = clean(r.get("Degree Name"))
            out.append(f"- {clean(r.get('School Name'))}" + (f", {degree}" if degree else "") + (f" ({years})" if years else ""))
    skills = [clean(r.get("Name")) for r in rows("skills") if clean(r.get("Name"))]
    if skills:
        out += ["", "## Skills", ", ".join(skills)]
    certs = rows("certifications")
    if certs:
        out += ["", "## Certifications"]
        for r in certs:
            by = clean(r.get("Authority"))
            out.append(f"- {clean(r.get('Name'))}" + (f", {by}" if by else ""))
    return "\n".join(out).strip() + "\n", missing
