"""Who commented on your posts, as far as the export can tell.

The export has no list of reactions or comments by others. It does have YOUR comments, including your replies
under your own posts, and a reply to someone's comment starts with their name. So: people whose comment you
replied to, by name, who are your connections. That is a floor, not the full picture: people who only reacted,
commenters you didn't reply to, and replies that don't start with a name are not here.

How a comment is tied to your post: LinkedIn ids carry a timestamp (id >> 22 = milliseconds), and the post a
comment sits on has an activity / ugcPost id created within seconds of your share id for that same post.
"""
import bisect
import collections
import re
import unicodedata
import urllib.parse
from datetime import date

from archive import connect, table_names

_ID = re.compile(r"urn:li:(?:activity|ugcPost|share):(\d+)")


def _id(url):
    m = _ID.search(urllib.parse.unquote(url or ""))
    return int(m.group(1)) if m else None


def _text_col(con):
    cols = {r[1] for r in con.execute('PRAGMA table_info("comments")')}
    return "Comment" if "Comment" in cols else "Message"


def replies_on_own_posts(con=None):
    """[(comment date, comment text, post date, post link)] for your comments that sit under your own posts."""
    con = con or connect()
    names = table_names(con)
    if "shares" not in names or "comments" not in names:
        return []
    shares = sorted((i >> 22, d, link) for d, link in con.execute("SELECT Date, ShareLink FROM shares")
                    if (i := _id(link)))
    stamps = [s[0] for s in shares]
    out = []
    for d, link, text in con.execute(f'SELECT Date, Link, "{_text_col(con)}" FROM comments'):
        i = _id(link)
        if not i:
            continue
        t = i >> 22
        k = bisect.bisect_left(stamps, t)
        near = [shares[j] for j in (k - 1, k) if 0 <= j < len(shares) and abs(shares[j][0] - t) <= 5000]
        if near:
            out.append((d or "", text or "", near[0][1] or "", near[0][2] or ""))
    return out


def _key(text):
    """Letters and spaces only, lowercase: "˗ˏˋ Brendan Short ˎˊ˗" → "brendan short", "Benyamin 🚀\u200b" →
    "benyamin". Modifier letters, symbols, emoji and invisible characters go."""
    out = []
    for ch in unicodedata.normalize("NFKC", text or ""):
        cat = unicodedata.category(ch)
        if cat in ("Lu", "Ll", "Lt", "Lo") or ch.isdigit():
            out.append(ch.lower())
        elif ch.isspace() or cat.startswith("P") or cat in ("Sk", "So", "Lm", "Cf"):
            out.append(" ")
    return " ".join("".join(out).split())


def _is_reply(text, name):
    """A reply starts with their name and then says something. "Danny's experience (re)building…" is a mention,
    and a comment that is only a name is a tag."""
    if _key(text) == name:
        return False
    pattern = r"\W+".join(re.escape(w) for w in name.split())
    return not re.search(rf"{pattern}\s*['’]s\b", (text or "").lower()[:120])


_NOT_NAMES = set("""
i i'm i've we we're you you're my our your the a an it its it's this that these those here there if when what why how
who where and but or so then now also plus even just really such very super spot well love loved glad happy
appreciate appreciated amazing awesome cool nice fair makes same yep yup yeah yes sure ok okay hah haha ha lol lmao
totally agree agreed definitely absolutely indeed precisely exactly correct right true truth honestly interesting
great good thanks thank congrats congratulations hey hi hello oh wow couldn't can't would should could not no one
100% big huge solid strong fun funny wild crazy real hard easy yup ya ah hmm i'd i'll we'd you'd let's here's
full link links on in at for to of as by per via re ps fyi see check watch read listen podcast episode go get
new old more most last next first quick short long full-length video article post posts thread
""".split())


def _leading_name(text):
    """The name a reply starts with, for people who aren't connections: "Daren Ng, CFA thanks!" → "Daren Ng",
    "Ashmer A. Even the new ones?" → "Ashmer A.", "Maria (Smith) Lopez great point" → "Maria (Smith) Lopez",
    "Brendan, agreed" → "Brendan". Stops at an initial; a one-word name needs a comma, punctuation or a lowercase
    word after it; sentence starters ("Interesting take") are not names."""
    toks = (text or "").strip().split()
    if not toks:
        return ""
    name, i = [], 0

    def word(t):
        return re.fullmatch(r"[A-Z][A-Za-z'’-]+[,:!?.]?", t) and t.rstrip(",:!?.").lower() not in _NOT_NAMES

    if not word(toks[0]):
        return ""
    name.append(toks[0]); i = 1
    if toks[0][-1] in ",:!?.":
        return toks[0].rstrip(",:!?.")                  # "Brendan, agreed"
    if i < len(toks) and toks[i].startswith("("):     # a maiden name in brackets
        j = i
        while j < len(toks) and not toks[j].rstrip(",:!?.").endswith(")") and j - i < 4:
            j += 1
        if j < len(toks) and toks[j].rstrip(",:!?.").endswith(")"):
            name += toks[i:j + 1]; i = j + 1
    while i < len(toks) and len(name) < 3:
        t = toks[i]
        if re.fullmatch(r"[A-Z]\.?[,:!?]?", t):         # an initial ends the name
            name.append(t.rstrip(",:!?"))
            return " ".join(name)
        if word(t):
            name.append(t); i += 1
            if t[-1] in ",:!?.":
                break
            continue
        break
    nxt = toks[i] if i < len(toks) else ""
    ends_clean = name[-1][-1] in ",:!?." or not nxt or nxt[0].islower() or nxt[0] in "!?.,:"
    if len(name) == 1 and not ends_clean:
        return ""
    return " ".join(name).rstrip(",:!?.") if ends_clean or len(name) > 1 else ""


def _post_openers(con):
    """post link → (date, first 45 characters of the post), for "which post was it"."""
    if "shares" not in table_names(con):
        return {}
    out = {}
    for d, link, text in con.execute("SELECT Date, ShareLink, ShareCommentary FROM shares"):
        body = " ".join((text or "").replace('""', '"').split())
        if len(body) > 1 and body[0] == body[-1] == '"':
            body = body[1:-1]                            # quotes around the whole post, not a quote inside it
        out[link or ""] = ((d or "")[:10], body[:45] + ("…" if len(body) > 45 else ""))
    return out


def commenters(as_of=None, since_days=None, keep=None):
    """People who commented on your posts and got a reply from you by name, most posts first.
    keep: optional function(row) → bool (a role / title filter); totals are counted after it."""
    import people as ppl
    from cleanup import load_people
    from invites import export_date
    con = connect()
    as_of = as_of or export_date() or date.today()
    cutoff = (as_of.toordinal() - since_days) if since_days else None
    everyone = {p["slug"]: p for p in load_people(as_of) if p["slug"]}
    by_name, first_words = {}, collections.Counter()
    for p in everyone.values():
        n = _key(p["name"])
        if n:
            first_words[n.split(" ")[0]] += 1
            by_name.setdefault(n, p["slug"])
    # Full names of 5+ characters with a space; one-word names (an emoji or invisible last name) only when 6+
    # letters and no other connection's name starts with that word.
    usable = {n: s for n, s in by_name.items()
              if (" " in n and len(n) > 4) or (" " not in n and len(n) >= 6 and first_words[n] == 1)}
    ordered = sorted(usable, key=len, reverse=True)
    openers = _post_openers(con)
    stats = collections.defaultdict(lambda: {"replies": 0, "posts": set(), "first": "", "last": "", "last_post": "",
                                             "last_text": ""})
    unnamed, strangers, stranger_last = 0, collections.Counter(), {}
    for d, text, post_date, post_link in replies_on_own_posts(con):
        if cutoff and d[:10] and date.fromisoformat(d[:10]).toordinal() < cutoff:
            continue
        body = _key(" ".join((text or "").split()[:8]))
        name = next((n for n in ordered if body.startswith(n) and body[len(n):len(n) + 1] in ("", " ")), None)
        slug = usable[name] if name and _is_reply(text, name) else None
        if not slug:
            unnamed += 1
            who = _leading_name(text)
            if who and not name:
                strangers[who] += 1                      # replied by name to someone who isn't a connection
                stranger_last[who] = {"name": who, "post_opener": openers.get(post_link, ("", ""))[1],
                                      "post_date": openers.get(post_link, ("", ""))[0], "replied": d[:10],
                                      "your_reply": " ".join((text or "").split())[:300]}
            continue
        s = stats[slug]
        s["replies"] += 1
        s["posts"].add(post_link)
        s["first"] = min(s["first"] or d, d)
        if d >= s["last"]:
            s["last"], s["last_post"], s["last_text"] = d, post_link, " ".join((text or "").split())[:400]
    rows = []
    for slug, s in stats.items():
        p = everyone[slug]
        dm = p["dm_count"]
        rows.append({"name": p["name"], "title": p["title"], "company": p["company"], "profile_url": p["profile_url"],
                     "replies_from_you": s["replies"], "posts": len(s["posts"]), "last_reply": s["last"][:10],
                     "last_post": s["last_post"], "last_post_opener": openers.get(s["last_post"], ("", ""))[1],
                     "last_post_date": openers.get(s["last_post"], ("", ""))[0], "your_last_reply": s["last_text"],
                     "dms": dm, "group_messages": p.get("group_count", 0),
                     "warmth": ppl.warmth_label(p) if dm else ("group chat only" if p.get("group_count") else "never messaged"),
                     "slug": slug, "_post_links": s["posts"], "_replies": s["replies"]})
    everyone_count = len(rows)
    if keep:
        rows = [r for r in rows if keep(r)]
    rows.sort(key=lambda r: (r["posts"], r["replies_from_you"], r["last_reply"]), reverse=True)
    replies_total = sum(r["_replies"] for r in rows)
    post_links = set().union(*[r["_post_links"] for r in rows]) if rows else set()
    counts = collections.Counter()                       # people per post, among the people kept
    for r in rows:
        for link in r["_post_links"]:
            counts[link] += 1
    top_posts = [{"date": openers.get(link, ("", ""))[0], "opener": openers.get(link, ("", ""))[1], "link": link,
                  "people": n} for link, n in counts.most_common(5)]
    for r in rows:
        r.pop("_post_links"), r.pop("_replies")
    never = [r for r in rows if not r["dms"] and not r["group_messages"]]
    posts_in_window = 0
    if "shares" in table_names(con):
        cut = date.fromordinal(cutoff).isoformat() if cutoff else ""
        posts_in_window = sum(1 for (d,) in con.execute("SELECT Date FROM shares") if (d or "")[:10] >= cut)
    return rows, {"people": len(rows), "all_commenters": everyone_count, "replies_by_name": replies_total,
                  "posts": len(post_links),
                  "non_connections": [n for n, _ in strangers.most_common(15)], "non_connection_count": len(strangers),
                  "non_connection_replies": [stranger_last[n] for n, _ in strangers.most_common(15)],
                  "posts_in_window": posts_in_window, "never_messaged_names": [r["name"] for r in never],
                  "replies_without_a_known_name": unnamed, "since_days": since_days, "as_of": as_of.isoformat(),
                  "never_messaged": len(never), "group_chat_only": sum(1 for r in rows if not r["dms"] and r["group_messages"]),
                  "top_posts": top_posts,
                  "caveat": "Only people whose comment you replied to by name. People who only reacted and commenters "
                            "you didn't reply to aren't in the export; commenters who aren't connections come as a name "
                            "only (no title or profile link)."}


def endorsers(as_of=None, since_days=None):
    """People who endorsed a skill of yours, newest first: another sign someone pays attention to you."""
    import people as ppl
    from cleanup import load_people
    from invites import export_date
    from archive import slug_from_url
    con = connect()
    if "endorsements" not in table_names(con):
        return []
    as_of = as_of or export_date() or date.today()
    everyone = {p["slug"]: p for p in load_people(as_of) if p["slug"]}
    by = {}
    for d, skill, first, last, url in con.execute(
            'SELECT "Endorsement Date", "Skill Name", "Endorser First Name", "Endorser Last Name", '
            '"Endorser Public Url" FROM endorsements'):
        day = (d or "")[:10].replace("/", "-")
        if since_days and day and (as_of.toordinal() - date.fromisoformat(day).toordinal()) > since_days:
            continue
        slug = slug_from_url(url or "")
        e = by.setdefault(slug or f"{first} {last}", {"name": " ".join(f"{first or ''} {last or ''}".split()),
                                                     "skills": [], "last": "", "slug": slug})
        e["skills"].append(" ".join((skill or "").split()))
        e["last"] = max(e["last"], day)
    out = []
    for e in by.values():
        p = everyone.get(e["slug"]) or {}
        out.append({"name": e["name"], "title": p.get("title", ""), "company": p.get("company", ""),
                    "skills": ", ".join(dict.fromkeys(e["skills"])), "last_endorsed": e["last"],
                    "dms": p.get("dm_count", 0), "connection": bool(p),
                    "profile_url": f"https://www.linkedin.com/in/{e['slug']}" if e["slug"] else ""})
    return sorted(out, key=lambda x: x["last_endorsed"], reverse=True)
