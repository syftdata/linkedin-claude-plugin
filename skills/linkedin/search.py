"""Search queries over the loaded export. Return plain data; the CLI and the MCP stub format it.

Free text (posts, comments, messages) is matched as a phrase, word by word, plural allowed: "product marketing"
finds "product marketing" and "product-marketing", never a post that says "product" and "marketing" apart;
"signal" also finds "signals". Date windows count back from the day the export was made.
"""
import collections
import re
from datetime import timedelta

from archive import connect, slug_from_url, table_names


def _terms(query):
    return [q.strip() for q in (query if isinstance(query, (list, tuple)) else [query]) if q and q.strip()]


def _clean(text):
    """LinkedIn's CSV leaves doubled quotes and line breaks in post text; show it the way it reads."""
    t = " ".join((text or "").split())
    t = re.sub(r'"\s*""\s*"', " ", t)       # LinkedIn wraps each paragraph in quotes: " " " between them
    t = re.sub(r'"(?:\s+")+', " ", t)        # ...or " " " with plain quotes between line breaks
    t = t.replace('""', '"').strip()
    return t[1:-1].strip() if len(t) > 1 and t[0] == t[-1] == '"' else t


def _locate(text, term):
    words = re.findall(r"[a-z0-9]+", term.lower())
    if not words:
        return -1
    body = r"\W+".join(re.escape(x) for x in words)
    m = re.search(rf"(?<![a-z0-9]){body}(?:s|es)?(?![a-z0-9])", text.lower())
    return m.start() if m else -1


TOPICS = {
    # Words for a subject plus patterns, so "what did they say about pricing" also finds "$450/mo".
    "pricing": {"words": ["pricing", "price", "cost", "budget", "quote", "discount", "contract", "per seat", "seats",
                          "per month", "annual", "invoice", "proposal", "renewal", "paid", "plan", "subscription",
                          "arr", "rate", "rates", "fee", "fees", "hourly", "per hour", "a month", "an hour", "retainer"],
                "patterns": [r"\$\s?\d[\d,.]*\s?[km]?", r"\b\d[\d,.]*\s?(usd|eur|gbp)\b", r"/\s?(mo|month|yr|year|seat)\b",
                             r"\b\d+(\s?-\s?\d+)?\s?k\b", r"\b\d+\s?(an|a|per)\s?(hour|month|seat|year)\b"]},
    "meeting": {"words": ["call", "meeting", "calendly", "zoom", "demo", "book a time", "schedule", "coffee"],
                "patterns": [r"calendly\.com", r"cal\.com", r"meet\.google"]},
    "hiring": {"words": ["we're hiring", "we are hiring", "hiring for", "open role", "open position", "job opening",
                         "looking to hire", "looking for a", "your resume", "your cv", "recruiting for", "headcount"],
               "patterns": []},
    "intro": {"words": ["intro", "introduce", "introduction", "connect you", "loop in"], "patterns": []},
}


def _match(text, terms, patterns=()):
    """First term (or pattern) found in text (phrase, word boundaries, plural ok) and where, or (None, -1)."""
    for t in terms:
        i = _locate(text, t)
        if i >= 0:
            return t, i
    for pat in patterns:
        m = re.search(pat, (text or "").lower())
        if m:
            return m.group(0), m.start()
    return None, -1


def _snippet(text, at=-1, width=60):
    text = _clean(text)
    if at < 0:
        return text[:width * 2] + ("..." if len(text) > width * 2 else "")
    start, end = max(0, at - width), min(len(text), at + width * 2)
    return ("..." if start else "") + text[start:end] + ("..." if end < len(text) else "")


def _cutoff(since_days):
    """'YYYY-MM-DD' since_days before the export date (or None)."""
    if not since_days:
        return None
    from invites import export_date
    from datetime import date
    anchor = export_date() or date.today()
    return (anchor - timedelta(days=since_days)).isoformat()


def search_shares(query, limit=None, since_days=None):
    """Your posts mentioning ANY of the terms, newest first: [{date, text, matched, link}]."""
    con = connect()
    if "shares" not in table_names(con):
        return []
    terms, cutoff = _terms(query), _cutoff(since_days)
    out = []
    for d, text, link, shared in con.execute("SELECT Date, ShareCommentary, ShareLink, SharedUrl FROM shares "
                                             "WHERE Date IS NOT NULL ORDER BY Date DESC"):
        if cutoff and (d or "")[:10] < cutoff:
            continue
        clean = _clean(text)
        term, at = _match(f"{clean} {shared or ''}", terms)
        if term:
            out.append({"date": (d or "")[:10], "text": _snippet(clean, at if at < len(clean) else -1),
                        "matched": term, "link": link, "commentary": clean})
    return out[:int(limit)] if limit else out


def search_shares_since(days):
    """Your posts in the last `days` before the export date (the same window `topics --since` uses)."""
    con = connect()
    if "shares" not in table_names(con):
        return []
    cutoff = _cutoff(days)
    return [d for (d,) in con.execute("SELECT Date FROM shares WHERE Date IS NOT NULL") if (d or "")[:10] >= cutoff]


def _columns(con, table):
    return {r[1] for r in con.execute(f'PRAGMA table_info("{table}")')}


def search_comments(query, limit=None, since_days=None):
    """Your comments mentioning ANY of the terms, newest first, with the link to the post."""
    con = connect()
    if "comments" not in table_names(con):
        return []
    cols = _columns(con, "comments")
    # Older exports call the text column `Comment`; current ones (Comments_<id>.csv) call it `Message`.
    text_col = "Comment" if "Comment" in cols else "Message"
    link = "Link" if "Link" in cols else "NULL"
    terms, cutoff = _terms(query), _cutoff(since_days)
    out = []
    for d, text, url in con.execute(f'SELECT Date, "{text_col}", {link} FROM comments ORDER BY Date DESC'):
        if cutoff and (d or "")[:10] < cutoff:
            continue
        clean = _clean(text)
        term, at = _match(clean, terms)
        if term:
            out.append({"date": (d or "")[:10], "comment": clean, "snippet": _snippet(clean, at), "matched": term,
                        "link": url})
    return out[:int(limit)] if limit else out


def find_connections(title="", company=""):
    con = connect()
    if "connections" not in table_names(con):
        return []
    sql, params = "SELECT [First Name], [Last Name], Position, Company, URL FROM connections WHERE 1=1", []
    if title:
        sql += " AND LOWER(Position) LIKE ?"
        params.append(f"%{title.lower()}%")
    if company:
        sql += " AND LOWER(Company) LIKE ?"
        params.append(f"%{company.lower()}%")
    sql += " ORDER BY Position"
    return [{"first_name": r[0], "last_name": r[1], "position": r[2], "company": r[3], "url": r[4]}
            for r in con.execute(sql, params).fetchall()]


def search_connections_keywords(keywords):
    con = connect()
    if "connections" not in table_names(con):
        return []
    out = []
    for first, last, pos, comp, url in con.execute(
            "SELECT [First Name], [Last Name], Position, Company, URL FROM connections").fetchall():
        combined = f"{pos or ''} {comp or ''}".lower()
        if all(kw.lower() in combined for kw in keywords):
            out.append({"first_name": first, "last_name": last, "position": pos, "company": comp, "url": url})
    return out


def _owner(con):
    if "metadata" not in table_names(con):
        return ""
    row = con.execute("SELECT value FROM metadata WHERE key='owner_slug'").fetchone()
    return row[0] if row else ""


def search_messages(query=(), person="", since_days=None, limit=10, include_groups=False, person_url="", topic=None):
    """Your DMs, newest first, as short snippets around the match.

    query: ANY of the terms (phrase, plural ok). person: part of the other person's name. When several different
    people match that name, returns them in `people` (with title and how much you talked) and no messages, so the
    user can pick one; pass a fuller name or person_url to choose. Group chats are left out unless include_groups."""
    con = connect()
    names = table_names(con)
    empty = {"messages": [], "total": 0, "people": [], "ambiguous": False}
    if "messages" not in names:
        return empty
    owner = _owner(con)
    groups = set()
    if "dm_events" in names:
        groups = {r[0] for r in con.execute("SELECT DISTINCT conversation_id FROM dm_events WHERE is_group = 1")}
    titles = {}
    if "connections_index" in names:
        titles = {s: (f"{f or ''} {l or ''}".strip(), p or "", c or "") for s, f, l, p, c in con.execute(
            "SELECT slug, first_name, last_name, position, company FROM connections_index")}
    terms, cutoff = _terms(query), _cutoff(since_days)
    patterns = []
    if topic:
        if topic not in TOPICS:
            raise ValueError(f"Unknown topic {topic!r}. Options: {', '.join(TOPICS)}")
        terms = terms + TOPICS[topic]["words"]
        patterns = TOPICS[topic]["patterns"]
    want_slug = slug_from_url(person_url) if person_url else ""
    from people import clean_person_name
    want_name = clean_person_name(person).lower() if person else ""
    rows, people, prev_in_conv = [], {}, {}
    for cid, d, frm, to, sender_url, recip_urls, content in con.execute(
            'SELECT "CONVERSATION ID", DATE, "FROM", "TO", "SENDER PROFILE URL", "RECIPIENT PROFILE URLS", CONTENT '
            "FROM messages ORDER BY DATE DESC"):
        if cid in groups and not include_groups:
            continue
        mine = bool(owner) and owner in (sender_url or "").lower()
        other_name = " ".join(((to if mine else frm) or "").split())
        other_slug = slug_from_url(recip_urls if mine else sender_url) or ""
        if want_slug and other_slug != want_slug:
            continue
        if person and not want_slug and want_name not in clean_person_name(other_name).lower():
            continue
        if person and not want_slug:
            e = people.setdefault(other_slug or other_name, {"name": other_name, "profile_url":
                                  f"https://www.linkedin.com/in/{other_slug}" if other_slug else "",
                                  "messages": 0, "hits": 0, "last": (d or "")[:10]})
            e["messages"] += 1
        if cutoff and (d or "")[:10] < cutoff:
            continue
        term, at = _match(content or "", terms, patterns) if (terms or patterns) else ("", -1)
        if (terms or patterns) and not term:
            continue
        if person and not want_slug:
            people[other_slug or other_name]["hits"] += 1
        rows.append({"date": (d or "")[:10], "from": "you" if mine else other_name, "with": other_name,
                     "with_key": other_slug or other_name, "conversation_id": cid, "_content": content or "",
                     # reading one person's thread (no search words): whole messages, for drafting a reply
                     "snippet": _snippet(content, at) if (terms or patterns or not (want_slug or person))
                     else _clean(content)[:600], "matched": term})
    searched = bool(terms or patterns)
    narrowed_from = 0
    if person and not want_slug and len(people) > 1 and searched:
        with_hits = [k for k, e in people.items() if e["hits"]]
        if len(with_hits) == 1:                       # only one of them ever said it: that's the answer
            narrowed_from = len(people)
            rows = [r for r in rows if r["with_key"] == with_hits[0]]
            people = {with_hits[0]: people[with_hits[0]]}
    if searched and rows:
        # Context before each hit (same conversation, within 30 days): the nearest earlier message that says
        # something (25+ characters or a question), looking back up to 3, so "$3k/year" has its "for what" even
        # when the message right before it is "They do".
        from datetime import date as _date
        shown = rows[:limit or len(rows)]
        convs = {r["conversation_id"] for r in shown}
        by_conv = {}
        for cid, d, frm, content in con.execute('SELECT "CONVERSATION ID", DATE, "FROM", CONTENT FROM messages '
                                                 "ORDER BY DATE"):
            if cid in convs:
                by_conv.setdefault(cid, []).append(((d or "")[:10], " ".join((frm or "").split()), content or ""))
        for r in shown:
            msgs = by_conv.get(r["conversation_id"], [])
            for i, (d, frm, content) in enumerate(msgs):
                if d == r["date"] and content == r["_content"]:
                    for pd, pf, pc in reversed(msgs[max(0, i - 3):i]):
                        close = pd and (_date.fromisoformat(d) - _date.fromisoformat(pd)).days <= 30
                        if not close or _match(pc, terms, patterns)[0]:
                            break
                        if len(pc.strip()) >= 25 or "?" in pc:
                            r["before"] = f"[{pd}] {pf}: {_snippet(pc, -1, 50)}"
                            break
                    break
    if person and not want_slug and len(people) > 1:
        ppl = []
        for key, e in sorted(people.items(), key=lambda kv: (kv[1]["hits"], kv[1]["last"]), reverse=True):
            t = titles.get(slug_from_url(e["profile_url"]) if e["profile_url"] else "", ("", "", ""))
            ppl.append(e | {"title": t[1], "company": t[2]})
        return {"messages": [], "total": 0, "people": ppl, "ambiguous": True, "searched": searched, "narrowed_from": 0}
    for r in rows:
        r.pop("with_key", None)
        r.pop("conversation_id", None)
        r.pop("_content", None)
    return {"messages": rows[:limit] if limit else rows, "total": len(rows),
            "people": list(people.values()), "ambiguous": False, "searched": searched, "narrowed_from": narrowed_from}


_STOPWORDS = set("""
a about above after again against all also am an and any are as at be because been before being below between both
but by can could did do does doing down during each few for from further had has have having he her here hers him
his how i if in into is it its itself just me more most my no nor not now of off on once only or other our ours out
over own same she should so some such than that the their them then there these they this those through to too under
until up very was we were what when where which while who whom why will with would you your yours yourself im ive
id ill dont cant wont isnt youre thats theres lets weve were wed get got go going gone make made makes one two three
new like need needs know see way really much many every thing things lot lots day days week weeks year years time
today still even back us via etc here s t re ve ll d m don didn doesn won isn aren wasn weren hasn haven hadn want
said say says take took use used using work working good great best better big small first last next let well right
real never getting think thinking always without something anything everything someone actually probably maybe
told nobody call run running build built comments comment post posts link below dm dms check ask asked asking
literally already ever keep come comes came look looking feel sure yes yeah lol ago since part hard easy yet another
done doing thats heres whats whos theyre isnt doesnt didnt wasnt youve theyve ive youll
http https www com lnkd co html utm amp
""".split())


def topics(since_days=None, top=15):
    """What your posts are about: the words and two-word phrases that appear in the most posts in the window
    (common words removed). Counts posts, not mentions."""
    con = connect()
    if "shares" not in table_names(con):
        return {"posts": 0, "words": [], "phrases": []}
    cutoff = _cutoff(since_days)
    first_names = set()
    if "connections_index" in table_names(con):
        first_names = {(r[0] or "").strip().lower() for r in con.execute("SELECT first_name FROM connections_index")}
    words, pairs, n = collections.Counter(), collections.Counter(), 0
    for d, text in con.execute("SELECT Date, ShareCommentary FROM shares WHERE Date IS NOT NULL"):
        if cutoff and (d or "")[:10] < cutoff:
            continue
        n += 1
        raw = re.sub(r"https?://\S+", " ", _clean(text))
        # "Brendan Short" (a first name you know + a capitalized word) is a person, not a topic; "Field Notes" stays.
        names_here = {f"{a.lower()} {b.lower()}" for a, b in re.findall(r"\b([A-Z][a-z]+)\s+([A-Z][a-z]+(?:-[A-Z][a-z]+)?)\b", raw)
                      if a.lower() in first_names}
        clean = raw.lower()
        tokens = [t for t in re.findall(r"[a-z0-9][a-z0-9'+-]*[a-z0-9+]|[a-z]", clean) if not t.isdigit()]
        tokens = [t.replace("'", "") for t in tokens]
        keep = [t for t in tokens if t not in _STOPWORDS and len(t) > 2]
        words.update(set(keep))
        bigrams = {f"{a} {b}" for a, b in zip(tokens, tokens[1:])
                   if a not in _STOPWORDS and b not in _STOPWORDS and len(a) > 2 and len(b) > 2} - names_here
        pairs.update(bigrams)
    return {"posts": n, "since": cutoff, "words": words.most_common(top),
            "phrases": [(p, c) for p, c in pairs.most_common(top) if c > 1]}


def activity(months=12):
    """Your posting and what came in: posts, comments and reactions per month, plus connection requests received
    and new people who messaged you first. Counted back from the export date; the export's own month is partial.
    The export has no impressions and no record of who reacted to your posts; commenters you replied to by name
    are in `engagers`."""
    from datetime import date
    from invites import export_date, load as load_invites
    con = connect()
    names = table_names(con)
    anchor = export_date() or date.today()

    def per_month(table, col="Date"):
        if table not in names:
            return collections.Counter()
        return collections.Counter((r[0] or "")[:7] for r in con.execute(f'SELECT "{col}" FROM "{table}"') if r[0])

    posts, comments, reactions = per_month("shares"), per_month("comments"), per_month("reactions")
    from invites import coverage_start
    invs = load_invites(con)
    covered_from = coverage_start(con, invs)
    requests_in = collections.Counter(r["sent_at"].strftime("%Y-%m") for r in invs
                                      if r["direction"] == "received" and r["sent_at"])
    requests_out = collections.Counter(r["sent_at"].strftime("%Y-%m") for r in invs
                                       if r["direction"] == "sent" and r["sent_at"])
    new_conn = collections.Counter()
    if "connections" in names:             # all connections, including the ones exported without a profile URL
        from archive import parse_connected_on
        new_conn = collections.Counter((parse_connected_on(r[0]) or "")[:7] for r in con.execute(
            'SELECT "Connected On" FROM connections'))
    first_contact = collections.Counter()
    if "dm_events" in names:
        seen = set()
        for slug, sent_at, direction in con.execute(
                "SELECT counterpart_slug, sent_at, direction FROM dm_events WHERE is_group = 0 ORDER BY sent_at"):
            if slug in seen:
                continue
            seen.add(slug)
            if direction == "in":
                first_contact[(sent_at or "")[:7]] += 1
    keys, y, m = [], anchor.year, anchor.month
    for _ in range(months):
        keys.append(f"{y:04d}-{m:02d}")
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    recent = []
    if "shares" in names:
        recent = [{"date": (d or "")[:10], "text": _snippet(t, -1, 45), "link": link or ""}
                  for d, t, link in con.execute(
                      "SELECT Date, ShareCommentary, ShareLink FROM shares WHERE Date IS NOT NULL ORDER BY Date DESC LIMIT 5")]
    def req(counter, k):
        return counter.get(k, 0) if covered_from and k >= covered_from else None   # None: no data that month
    # Posting trend: the last 3 full months against the 3 before. Flat posting can't explain a change in what came in.
    full = keys[1:7]
    last3, prev3 = sum(posts.get(k, 0) for k in full[:3]), sum(posts.get(k, 0) for k in full[3:6])
    if prev3 and abs(last3 - prev3) / prev3 < 0.25:
        note = (f"Your posting was steady ({prev3} then {last3} posts in the last two 3-month blocks), so the export "
                "can't show an effect of posting on what came in; your own requests sent drive new connections too.")
    else:
        way = "up" if last3 > prev3 else "down"
        note = (f"Your posting went {way} ({prev3} then {last3} posts in the last two 3-month blocks). If requests and "
                "new people messaging you moved with it, that's a correlation, not proof; check the requests you sent "
                "in the same months (your own outreach brings people in too).")
    return {
        "export_date": anchor.isoformat(),
        "months": [{"month": k, "partial": k == anchor.strftime("%Y-%m"), "posts": posts.get(k, 0),
                    "comments": comments.get(k, 0), "reactions": reactions.get(k, 0),
                    "new_connections": new_conn.get(k, 0), "requests_sent": req(requests_out, k),
                    "requests_received": req(requests_in, k), "new_people_messaged_you": first_contact.get(k, 0)}
                   for k in reversed(keys)],
        "totals": {"posts": sum(posts.values()), "comments": sum(comments.values()),
                   "reactions_given": sum(reactions.values())},
        "requests_since": covered_from,
        "recent_posts": recent,
        "not_in_export": ["who reacted to your posts", "commenters you didn't reply to by name (the ones you did "
                          "reply to: `engagers`)", "impressions or views of your posts", "who viewed your profile"],
        "note": note,
    }


def stats():
    con = connect()
    names = table_names(con)
    return {t: (con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] if t in names else 0)
            for t in ("shares", "connections", "comments", "reactions", "messages", "invitations")}
