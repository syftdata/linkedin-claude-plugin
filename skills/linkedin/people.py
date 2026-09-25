"""Pick people from your connections the same way everywhere: by role, title, company or name, by how much you
talk, sorted the way the question needs. Used by the `people` command, `syft-leads` and `compare-exports`.

Matching rules, from real exports:
- titles / companies: ANY of the values, case-insensitive, word-aware (see `has`).
- keywords: ALL must appear (title + company, or title only).
- company lists (CSV of target accounts or customers): a listed name matches a company that starts with the same
  words ("GrowthX" matches "GrowthX AI", "Amazon" matches "Amazon Web Services", "Meta" does not match "Metabase").
- dates and windows ("12m") count back from the day the export was made, not from today.
"""
import collections
import csv
import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from archive import connect, parse_connected_on, slug_from_url, table_names
from cleanup import load_people

SORTS = ("warm", "recent", "talked", "last-dm", "name")

# Common title wordings per role. A starting point, not a classifier: always glance at the titles it returns.
ROLES = {
    "recruiter": {"any": ["recruit", "talent acquisition", "talent partner", "head of talent", "vp talent",
                          "director talent", "chief talent", "talent advisor", "partner talent", "talent lead",
                          "portfolio talent", "talent", "sourcer", "headhunter", "executive search", "search partner",
                          "technical search", "executive talent", "leadership hiring"],
                  "not": ["talent development", "talent management", "talent relations"]},
    "marketing-leader": {"any": ["cmo", "chief marketing officer", "vp marketing", "vice president marketing",
                                 "svp marketing", "evp marketing", "head of marketing", "marketing director",
                                 "director marketing", "head of growth", "vp growth", "head of demand", "vp demand",
                                 "director demand", "demand generation director", "marketing lead",
                                 "founding marketing", "growth lead", "head of content", "vp content", "marketing head",
                                 "chief growth officer", "cgo", "vice president growth", "director growth",
                                 "growth director", "demand generation lead", "avp marketing", "brand director",
                                 "director content", "head of brand", "head of communications", "chief brand officer",
                                 "vp brand", "vp communications", "director communications", "head of comms",
                                 "chief communications officer", "communications lead", "director brand", "brand lead",
                                 "lead brand", "content lead", "lead marketing", "head of pr", "pr director",
                                 "director pr", "vp pr", "head of public relations", "director public relations"],
                         # "lead" and "growth" wordings only with nothing between the words: "Marketing Lead" is in,
                         # "Marketing Analytics & CDP Lead" and "VP Product & Growth" are not
                         "strict": ["marketing lead", "growth lead", "demand generation lead", "vp growth",
                                    "vice president growth", "director growth", "growth director", "brand lead",
                                    "content lead", "communications lead"],
                         "not": ["product marketing", "business development", "marketing operations",
                                 "revenue operations", "product manager", "head of product", "fractional", "advisor",
                                 "consultant", "growth engineer", "growth engineering", "marketing automation", "cto",
                                 "marketing cloud", "marketing solutions", "engineer", "engineering", "talent relations",
                                 "lead generation", "analytics", "client growth", "product growth", "product and growth",
                                 "product & growth"]},
    "marketing": {"any": ["marketing", "marketer", "cmo", "chief marketing", "content", "brand", "pr", "public relations", "communications", "comms", "launch", "pmm", "growth",
                          "demand gen", "demand generation", "social media", "seo"],
                  # broad words (growth, content, brand), so these rule a title out wherever they are, except
                  # engineer / engineering when the title also says marketing ("Growth Marketer & GTM Engineering Lead")
                  "anywhere": True, "keep_if": ["marketing", "marketer"],
                  "soft": ["engineer", "engineering", "head of product", "product growth"],
                  "not": ["marketing cloud", "marketing solutions", "advertising solutions", "engineer", "engineering",
                          "product manager", "product owner", "account executive", "scientist", "data science",
                          "machine learning", "business analyst", "talent relations", "product growth",
                          "head of product", "client growth"]},
    "product-marketing": {"any": ["product marketing", "pmm"]},
    "sales-leader": {"any": ["cro", "chief revenue officer", "chief sales officer", "chief commercial officer",
                             "head of commercial", "director gtm", "vp sales", "svp sales", "evp sales",
                             "avp sales", "svp revenue", "vice president sales", "head of sales",
                             "sales director", "director sales", "head of revenue", "vp revenue", "head of gtm",
                             "vp gtm", "head of go to market", "vp go to market"],
                     # "head of gtm" / "vp gtm" only side by side: "Partner, Head of Platform & GTM" at a VC is out
                     "strict": ["head of gtm", "vp gtm"], "not": ["talent"]},
    "sales-manager": {"any": ["sales manager", "sdr manager", "bdr manager", "sales team lead", "sales lead"]},
    "revops": {"any": ["revops", "rev ops", "revenue operations", "sales operations", "gtm operations",
                       "marketing operations", "business operations"]},
    "revops-leader": {"any": ["head of revenue operations", "vp revenue operations", "vice president revenue operations",
                              "director revenue operations", "chief revenue operations", "head of revops", "vp revops",
                              "director revops", "revops lead", "head of rev ops", "vp rev ops", "head of sales operations",
                              "vp sales operations", "director sales operations", "head of gtm operations",
                              "vp gtm operations", "director gtm operations", "head of business operations",
                              "vp business operations", "svp revenue operations", "revenue operations lead",
                              "sales operations lead", "vice president sales operations", "vice president gtm operations",
                              "vp gtm ops", "vp revenue ops", "director gtm systems", "head of gtm systems",
                              "director revenue systems", "head of revenue systems", "director gtm data"],
                      "strict": ["vp business operations", "head of business operations"]},
    "founder": {"any": ["founder"]},
    "executive": {"any": ["ceo", "coo", "cto", "cfo", "cmo", "cro", "chief", "president"]},
    "investor": {"any": ["investor", "venture capital", "vc", "angel", "general partner"]},
    "engineering-leader": {"any": ["cto", "vp engineering", "head of engineering", "engineering director",
                                   "director engineering", "engineering manager"]},
    "people-hr": {"any": ["chro", "head of people", "vp people", "people partner", "hr director", "human resources"]},
}
_STOP = {"of", "the", "and", "for", "at", "in", "&", "a", "an", "to"}
_SUFFIX_WORDS = {"inc", "llc", "ltd", "limited", "corp", "corporation", "co", "company", "gmbh", "plc", "sa", "ag",
                 "bv", "pty", "the", "group", "holdings"}
_WORD = re.compile(r"[a-z0-9]+")


def has(text, word, phrase=False, plural_ok=False):
    """Does `text` mention `word`? Case-insensitive and word-aware.

    Titles (default):
    - 3 letters or fewer: whole words only ("ai" is not in "Entertainment").
    - one longer word: a word starting with it, also after "co" ("recruit" → "Recruiter", "founder" → "Co-Founder",
      "Cofounder"), but not its plural ("founder" is not in "coaching to founders").
    - several words: all of them, any order, ignoring "of" / "the" ("vp marketing" → "VP of Marketing").
    Free text (phrase=True, used for posts, comments and messages): the words in that order, as words, and
    plural_ok also accepts a trailing s / es ("signal" finds "signals")."""
    text, w = (text or "").lower(), (word or "").lower().strip()
    if not w:
        return False
    if phrase:
        words = _WORD.findall(w)
        if not words:
            return w in text
        body = r"\W+".join(re.escape(x) for x in words)
        tail = r"(?:s|es)?" if plural_ok else ""
        return re.search(rf"(?<![a-z0-9]){body}{tail}(?![a-z0-9])", text) is not None
    if len(w) <= 3:
        return re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", text) is not None
    if not _WORD.fullmatch(w):
        parts = [x for x in _WORD.findall(w) if x not in _STOP]
        return bool(parts) and all(has(text, x) for x in parts)
    for token in _WORD.findall(text):
        for stem in (token, token[2:] if token.startswith("co") else None):
            if stem and stem.startswith(w) and stem[len(w):] not in ("s", "es"):
                return True
    return False


def _spans(text, phrase, ordered=True):
    """Character spans where a role wording (ordered=True) or a phrase as written (ordered=False) sits in text."""
    t = (text or "").lower()
    words = [x for x in _WORD.findall((phrase or "").lower()) if x not in _STOP] if ordered else \
        _WORD.findall((phrase or "").lower())
    if not words:
        return []
    if ordered and len(words) > 1:
        gap = r"(?:\W+(?:of|the|and|&|for)\b)*(?:\W+[a-z0-9]+){0,2}?(?:\W+(?:of|the|and|&|for)\b)*\W+"
        body = gap.join(re.escape(x) for x in words)
    elif ordered and len(words[0]) > 3:
        body = rf"(?:co)?\W?{re.escape(words[0])}[a-z]*"
    else:
        body = r"\W+".join(re.escape(x) for x in words)
    return [m.span() for m in re.finditer(rf"(?<![a-z0-9]){body}(?![a-z0-9])", t)]


def has_ordered(text, phrase, fillers=2):
    """Role wordings: the words in this order, with at most "of / the / and / &" between them. "vp marketing"
    finds "VP of Marketing" and "VP, Marketing"; "director marketing" does not match "Director, Business
    Development, LinkedIn Marketing Solutions"."""
    words = [x for x in _WORD.findall((phrase or "").lower()) if x not in _STOP]
    if len(words) <= 1:
        return has(text, phrase)
    # Between the words: "of / the / and", or up to two other words ("Head of Global Marketing", "Director of
    # Growth Marketing", "VP of Enterprise Sales"). Never more, so far-apart words don't pair up.
    gap = rf"(?:\W+(?:of|the|and|&|for)\b)*(?:\W+[a-z0-9]+){{0,{fillers}}}?(?:\W+(?:of|the|and|&|for)\b)*\W+"
    body = gap.join(re.escape(x) for x in words)
    return re.search(rf"(?<![a-z0-9]){body}(?![a-z0-9])", (text or "").lower()) is not None


def company_words(name):
    """Words that identify a company: lowercase, no emoji or punctuation, no Inc / LLC / The, a domain reduced to
    its name ('HubSpot, Inc.' / 'hubspot.com' → ['hubspot']; 'Spekit 🐙' → ['spekit'])."""
    s = (name or "").strip().lower()
    if "." in s and " " not in s:                       # a domain: keep the name before the TLD
        s = s.split("//")[-1].split("/")[0]
        s = s[4:] if s.startswith("www.") else s
        parts = s.split(".")
        s = parts[-3] if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "ac", "gov") else parts[-2] \
            if len(parts) >= 2 else parts[0]
    return [x for x in _WORD.findall(s) if x not in _SUFFIX_WORDS]


def normalize_company(name):
    return "".join(company_words(name))


# Companies that renamed or sit under a parent people put on their profile instead ("Snapchat" → "Snap Inc.").
COMPANY_ALIASES = {("snapchat",): [["snap"]], ("facebook",): [["meta"]], ("square",): [["block"]],
                   ("snap",): [["snapchat"]], ("meta",): [["facebook"]]}


def company_matches(company, target):
    """target: words from a list. Matches when the company starts with those words, or glues them together
    ("Growth X" / "GrowthX"), or is a known other name for it ("Snapchat" / "Snap Inc.")."""
    words, t = company_words(company), list(target or ())
    if not t or not words:
        return False
    if any(_company_match(words, alias) for alias in COMPANY_ALIASES.get(tuple(t), ())):
        return True
    return _company_match(words, t)


def _company_match(words, t):
    if words[:len(t)] == t:
        return True
    joined, acc = "".join(t), ""
    for w in words:
        acc += w
        if acc == joined:
            return True
        if len(acc) >= len(joined):
            return False
    return False


def load_company_list(path):
    """[(label, words)] from a CSV of company names or domains (target accounts, customers). Uses the first
    column whose header looks like company / account / domain / website / name; no header = one value per line."""
    path = Path(path).expanduser()
    if not path.is_file():
        raise ValueError(f"No such file: {path}")
    rows = list(csv.reader(path.read_text(encoding="utf-8-sig").splitlines()))
    if not rows:
        return []
    header = [h.strip().lower() for h in rows[0]]
    wanted = ("company", "company name", "account", "account name", "organization", "domain", "company domain",
              "website", "name")
    col = next((header.index(w) for w in wanted if w in header), None)
    body = rows[1:] if col is not None else rows
    col = col or 0
    out, seen = [], set()
    for r in body:
        if len(r) > col and r[col].strip():
            words = tuple(company_words(r[col]))
            if words and words not in seen:
                seen.add(words)
                out.append((r[col].strip(), words))
    return out


_PERSONAL = re.compile(r"@(gmail|googlemail|yahoo|ymail|hotmail|outlook|live|msn|icloud|me|mac|aol|proton|protonmail|"
                       r"gmx|yandex|mail|zoho|fastmail|hey)\.", re.I)
_CREDENTIAL = re.compile(r"\s*,\s*(mba|phd|ph\.d\.|cpa|pmp|md|jd|cfa|msc|ms|ma|bsc|pe|esq|shrm-cp|csm)\.?\b.*$", re.I)


def email_type(email):
    if not email:
        return ""
    return "personal" if _PERSONAL.search(email) else "work"


def clean_person_name(name):
    """For a CRM: no emoji or symbols, no ", MBA" / ", PhD", single spaces, and ALL CAPS in title case."""
    s = _CREDENTIAL.sub("", name or "")
    s = re.sub(r"[^\w\s.'-]", " ", s, flags=re.UNICODE)
    s = " ".join(s.split())
    return s.title() if s.isupper() and len(s) > 3 else s


def recent_dm_counts(as_of, days=90):
    """slug → 1:1 messages in the `days` before as_of (recent volume counts toward warmth)."""
    from datetime import timedelta
    con = connect()
    if "dm_events" not in table_names(con):
        return {}
    cutoff = (as_of - timedelta(days=days)).isoformat()
    return dict(con.execute("SELECT counterpart_slug, COUNT(*) FROM dm_events WHERE is_group = 0 AND sent_at >= ? "
                            "GROUP BY counterpart_slug", (cutoff,)).fetchall())


def first_messages():
    """counterpart slug → "you" / "them": who sent the first 1:1 message. Someone who started the conversation
    with you is more likely selling; someone you reached out to first, more likely a prospect or a friend."""
    con = connect()
    if "dm_events" not in table_names(con):
        return {}
    out = {}
    for slug, direction in con.execute("SELECT counterpart_slug, direction FROM dm_events WHERE is_group = 0 "
                                       "ORDER BY sent_at"):
        if slug not in out:
            out[slug] = "you" if direction == "out" else "them"
    return out


def message_only_people(as_of):
    """People you have 1:1 messages with who are not connections (InMail, message requests, people who removed
    you). They have no title or company in the export."""
    con = connect()
    names = table_names(con)
    if "last_dm" not in names or "connections_index" not in names:
        return []
    connected = {r[0] for r in con.execute("SELECT slug FROM connections_index")}
    who = {}
    if "messages" in names:
        for frm, url in con.execute('SELECT "FROM", "SENDER PROFILE URL" FROM messages'):
            slug = slug_from_url(url or "")
            if slug and slug not in who and frm:
                who[slug] = " ".join(frm.split())
    out = []
    for slug, n, last, direction, preview, out_c, in_c, opened, text, opened_text, groups, last_group in con.execute(
            "SELECT counterpart_slug, dm_count, last_dm_at, last_dm_direction, last_dm_preview, out_count, in_count, "
            "opened_by, last_dm_text, opened_text, group_count, last_group_at FROM last_dm WHERE dm_count > 0"):
        if slug in connected:
            continue
        d = date.fromisoformat(last[:10]) if last else None
        out.append({"slug": slug, "name": who.get(slug, slug), "first_name": who.get(slug, "").split(" ")[0],
                    "last_name": " ".join(who.get(slug, "").split(" ")[1:]), "profile_url":
                    f"https://www.linkedin.com/in/{slug}", "company": "", "title": "", "email": "",
                    "connected_on": "", "dm_count": n, "last_dm_at": last or "", "last_dm_direction": direction or "",
                    "last_dm_preview": preview or "", "days_since_dm": (as_of - d).days if d else None,
                    "days_since_connect": None, "in_count": in_c or 0, "out_count": out_c or 0, "connection": False,
                    "opened_by": opened or "", "last_dm_text": text or "", "opened_text": opened_text or "",
                    "group_count": groups or 0, "last_group_at": last_group or ""})
    return out


def export_date():
    try:
        from invites import export_date as _ed
        return _ed()
    except Exception:          # no database yet
        return None


_CLOSER = re.compile(r"^(thanks?|thank you|thx|ty|cheers|sounds good|great|awesome|perfect|will do|see you|"
                     r"talk soon|booked|done|ok|okay|cool|nice|got it|noted|you too|likewise|appreciate it|"
                     r"no worries|np|congrats|congratulations|happy birthday|welcome|sure|love it|love this|"
                     r"same|haha|lol|glad|happy to connect|great to connect|nice to connect|good to connect|"
                     r"stay connected|keep (it up|at it)|amazing|yes|yep|absolutely|definitely|will check)\b", re.I)
_OFFER = re.compile(r"\b(happy to|want me to|i can|we can|i could|shall i|should i|walk you through|show you|"
                    r"set (it|you) up|better if we|let me know if you('d| would) like)\b", re.I)
_YES = re.compile(r"^(y+e+s+|yeah|yep|yup|sure|absolutely|definitely|please|that would be great|would love)", re.I)
_NEED = re.compile(r"\b(still need|need (help|some help)|waiting (on|for)|haven'?t (been able|figured))\b", re.I)


def _real_question(text):
    """A question worth an answer: a sentence ending in "?" with 5+ words, not a joke ("lol?", "right?? 😂")."""
    raw = (text or "").strip()
    if raw and unicodedata.category(raw[-1]) in ("So", "Sk"):
        return False                                  # ends on an emoji: banter, not a question
    t = re.sub(r"[^\w\s?'.!,-]", " ", _plain(text or ""))
    for q in re.findall(r"[^.!?]*\?", t):
        words = q.replace("?", " ").split()
        if len(words) >= 5 and not re.search(r"\b(haha|lol|lmao|jk)\b", q, re.I):
            return True
    return False


# After you asked something, "yes" / "sure" are answers, not endings; only a thanks or an OK closes the thread.
_THANKS = re.compile(r"^(thanks?|thank you|thx|ty|cheers|appreciate it|no worries|np|will do|sounds good|great|"
                     r"awesome|perfect|cool|ok|okay|got it|noted|haha|lol)\b[\s!.🙏😊👍]*$", re.I)
_GREETING = re.compile(r"^(hi|hey|hello|yo|dear)\b[\s,!.]*(\w+[\s,!.]+)?", re.I)
_ASK = re.compile(r"\?|\b(still need|need help|waiting (on|for)|can you|could you|would you|are you|do you|interested|chat|call|meet|time|schedule|"
                  r"available|free|demo|quick question|thoughts|feedback|intro|price|pricing|cost|budget|proposal|"
                  r"contract|send|share|looking for|hiring|role|job|calendly|cal\.com)\b", re.I)
# Closing lines that end a message politely without asking anything.
_CLOSING_TAIL = re.compile(r"(let'?s stay (connected|in touch)|let me know if (i|we) can (help|do anything)|"
                           r"(happy|glad) to help|feel free to reach out|anytime|talk soon|have a great (day|week|weekend)|"
                           r"cheers|best|thanks!?|thank you!?)[\s.!🙏😊👍]*$", re.I)


def _plain(text):
    """Message text without links or quoted text, for judging whether it asks something."""
    t = re.sub(r"https?://\S+", " ", text or "")
    return re.sub(r'"[^"]{0,80}"|“[^”]{0,80}”', " ", t)


def ask_tag(text):
    """What the last message asks for: a meeting, a favor, a question, or nothing. Used to sort owed replies."""
    raw = (text or "").lower()
    t = _plain(raw)
    t_no_greet = re.sub(r"\b(nice|great|pleased|good|lovely|was great) (to )?meet(ing)? you\b", " ", t)
    if re.search(r"calendly|cal\.com|calendar\.app\.google|calendar\.google|meet\.google|zoom\.us|hubspot\.com/meetings|"
                 r"savvycal|chilipiper", raw) or \
            re.search(r"\b(meet(ing)?s?|call|chat|coffee|time to|schedule|available|my cal|this week|next week|in town|"
                      r"\d{1,2}(st|nd|rd|th))\b", t_no_greet):
        return "meeting"
    if re.search(r"\b(can you|could you|would you|would love if|favor|help me|intro(duce)? (me|us)|"
                 r"introduction to|connect me with)\b", t):
        return "favor"
    if "?" in t:
        return "question"
    return ""


_FYI = re.compile(r"(keep(ing)? my (linkedin )?network (small|limited|tight)|"
                  r"you('ve| have) been (added|invited|approved)|is your new|will be your (new )?|i'?ll be your "
                  r"(new )?|taking over (your|the) account|\bfyi\b|heads[- ]up|no need to (reply|respond)|"
                  r"just (sharing|wanted to share|an? fyi)|for your (reference|records))", re.I)


def looks_closed(p):
    """They wrote last, but it reads like an ending: a short thanks, "sounds good", "love it", "booked", an
    emoji, a message that opens with thanks or offers help and asks nothing, or any short message with no ask.
    A greeting ("Hi Priya,") is skipped first."""
    text = (p.get("last_dm_text") or p.get("last_dm_preview") or "").strip()
    if not text:
        return False
    letters = re.sub(r"[\W_]+", "", text)
    if not letters:                                     # only emoji / punctuation
        return True
    body = _GREETING.sub("", text, count=1).strip() if len(text) <= 120 else text
    plain = _plain(text)
    if "?" not in plain and _FYI.search(text):
        return True                                   # "You've been added to ...", "X is your new CSM", "FYI"
    if len(text) <= 80 and "?" not in plain and re.search(r"\b(just )?booked\b", text, re.I):
        return True                                   # "Just booked some time for my co-founder"
    if p.get("you_offered") and (_YES.match(body) or _NEED.search(text)):
        return False                                  # "yessss and I still need onboarding" after your offer: your move
    if p.get("you_asked"):                            # they answered your question ("Yes, about 40 reps"): your move,
        if len(body) <= 60 and _THANKS.match(body):   # unless it's only a thanks / OK,
            return True
        return bool(re.match(r"(thanks|thank you|great|awesome|perfect|will do|sounds good|noted|got it)\b", body, re.I)
                    and "?" not in plain and not ask_tag(text))   # or opens with thanks and asks nothing
    if len(body) <= 60 and _CLOSER.match(body):
        return True
    if "?" not in plain and not ask_tag(text):
        if _CLOSING_TAIL.search(text) or re.match(r"\s*(thanks|thank you|thx|much appreciated|appreciate)", body, re.I) \
                or re.search(r"let me know if (i|we) can (help|do anything)|happy to help|if you ever need", text, re.I):
            return True                               # "Thank you! ... let me know if I can help" / "let's stay connected"
    return len(text) <= 80 and not _ASK.search(plain)


@dataclass
class Filters:
    roles: list = field(default_factory=list)           # ROLES keys
    titles: list = field(default_factory=list)          # any of
    companies: list = field(default_factory=list)       # any of
    names: list = field(default_factory=list)           # person's name contains any of
    keywords: list = field(default_factory=list)        # all of
    title_only: bool = False
    not_titles: list = field(default_factory=list)
    not_companies: list = field(default_factory=list)
    company_list: list = field(default_factory=list)      # [(label, words)]: only these companies
    not_company_list: list = field(default_factory=list)  # [(label, words)]: never these (customers, say)
    messaged: bool = None                               # True: you wrote to them; False: no 1:1 messages at all
    two_way: bool = False
    only_they_wrote: bool = False                       # they wrote, you never did (pitches, mostly)
    dm_within_days: int = None
    quiet_days: int = None                              # last 1:1 DM at least this many days ago (lost touch)
    dormant: bool = False                               # was close (5+ messages each way), quiet for a year+
    started_by: str = None                              # "you" / "them": who sent the first 1:1 message
    awaiting_reply: bool = False                        # they wrote last
    include_closed: bool = False                        # with awaiting_reply: keep threads that read as finished
    has_email: bool = False
    connected_within_days: int = None
    connected_before_days: int = None
    sort: str = None
    labels: dict = field(default_factory=dict)          # durations as the user wrote them

    def all_titles(self):
        out = list(self.titles)
        for r in self.roles:
            if r not in ROLES:
                raise ValueError(f"Unknown role {r!r}. Options: {', '.join(ROLES)}")
            out += ROLES[r]["any"]
        return out

    def role_excludes(self):
        return [x for r in self.roles for x in ROLES.get(r, {}).get("not", [])]

    def _dur(self, key, days):
        return self.labels.get(key) or f"{days} days"

    def uses_messages(self):
        return bool(self.messaged is not None or self.two_way or self.only_they_wrote or self.dm_within_days
                    or self.awaiting_reply or self.quiet_days or self.started_by or self.dormant)

    def describe(self):
        bits = []
        if self.roles:
            bits.append("role " + " or ".join(self.roles))
        if self.titles:
            bits.append("title has " + " or ".join(f"'{t}'" for t in self.titles))
        if self.companies:
            bits.append("company has " + " or ".join(f"'{c}'" for c in self.companies))
        if self.names:
            bits.append("name has " + " or ".join(f"'{n}'" for n in self.names))
        if self.keywords:
            bits.append(("title" if self.title_only else "title or company") + " has " +
                        " and ".join(f"'{k}'" for k in self.keywords))
        if self.not_titles:
            bits.append("title without " + ", ".join(self.not_titles))
        if self.not_companies:
            bits.append("company without " + ", ".join(self.not_companies))
        if self.company_list:
            bits.append(f"at one of {len(self.company_list)} listed companies")
        if self.not_company_list:
            bits.append(f"not at {len(self.not_company_list)} excluded companies")
        if self.messaged is True:
            bits.append("you've written to them 1:1")
        if self.messaged is False:
            bits.append("no 1:1 messages either way")
        if self.two_way:
            bits.append("both of you have written")
        if self.only_they_wrote:
            bits.append("they wrote, you never replied")
        if self.dm_within_days:
            bits.append(f"last DM within {self._dur('dm_within_days', self.dm_within_days)}")
        if self.quiet_days:
            bits.append(f"quiet for {self._dur('quiet_days', self.quiet_days)}+")
        if self.dormant:
            bits.append("close once (5+ messages each way), quiet for a year+")
        if self.started_by:
            bits.append("you started the conversation" if self.started_by == "you" else "they started the conversation")
        if self.awaiting_reply:
            bits.append("they wrote last" + ("" if self.include_closed else ", not counting threads that read as finished"))
        if self.has_email:
            bits.append("email in the export")
        if self.connected_within_days:
            bits.append(f"connected within {self._dur('connected_within_days', self.connected_within_days)}")
        if self.connected_before_days:
            bits.append(f"connected over {self._dur('connected_before_days', self.connected_before_days)} ago")
        return ", ".join(bits) or "all connections"

    def sort_key(self):
        if self.sort:
            return self.sort
        if self.awaiting_reply:
            return "last-dm"
        if self.quiet_days or self.dormant:
            return "talked"
        return "warm"


def role_match(title, role):
    """A role's wording in the title (words in order, up to two words between), and none of its exclusions as
    written ("marketing operations" excludes "Head of Marketing Operations", not "CMO & GTM Operations"). The bare
    wording "talent" only counts when it is the whole title (people titled just "Talent" at VC firms)."""
    spec = ROLES[role]
    t = re.sub(r"\bvice[\s-]+president\b", "VP", (title or "").strip(), flags=re.I)   # "Vice President, X" = "VP X"
    for w in spec["any"]:
        if w == "talent":
            if t.lower() == "talent" and not _excluded(t, spec, [(0, len(t))]):
                return w
            continue
        if (has_ordered(t, w, fillers=0) if w in spec.get("strict", ()) else has_ordered(t, w)):
            spans = _spans(t, w) or [(0, len(t))]
            if not _excluded(t, spec, spans):
                return w
    return None


def _excluded(title, spec, hit_spans):
    """One-word exclusions ("fractional", "advisor", "cto") rule a title out wherever they are. A phrase
    ("marketing operations") only when it overlaps the wording that matched, so "Head of Marketing Operations" is
    out but "VP Marketing & Revenue Operations" is in."""
    keep = any(has(title, k, phrase=True) for k in spec.get("keep_if", ()))
    for x in spec.get("not", []):
        if keep and x in spec.get("soft", ()):
            continue
        if " " not in x.strip() or spec.get("anywhere"):
            if has(title, x, phrase=True):
                return True
            continue
        for a, b in _spans(title, x, ordered=False):
            if any(a < hb and ha < b for ha, hb in hit_spans):
                return True
    return False


def matched_title(p, f):
    for t in f.titles:
        if has(p["title"], t):
            return t
    for r in f.roles:
        hit = role_match(p["title"], r)
        if hit:
            return hit
    return ""


def _who(p, f):
    """The people filters that don't involve messages: role, title, company, name, keywords, lists, dates."""
    title, comp = p["title"], p["company"]
    if (f.titles or f.roles) and not (any(has(title, t) for t in f.titles) or
                                      any(role_match(title, r) for r in f.roles)):
        return False
    if f.companies and not any(has(comp, c) for c in f.companies):
        return False
    if f.names and not any(clean_person_name(n).lower() in clean_person_name(p["name"]).lower() for n in f.names):
        return False
    if f.keywords:
        hay = title if f.title_only else f"{title} {comp}"
        if not all(has(hay, k) for k in f.keywords):
            return False
    if any(has(title, t) for t in f.not_titles) or any(has(comp, c) for c in f.not_companies):
        return False
    if f.company_list and not any(company_matches(comp, w) for _, w in f.company_list):
        return False
    if f.not_company_list and any(company_matches(comp, w) for _, w in f.not_company_list):
        return False
    if f.has_email and not p.get("email"):
        return False
    dc = p["days_since_connect"]
    if f.connected_within_days is not None and (dc is None or dc > f.connected_within_days):
        return False
    if f.connected_before_days is not None and (dc is None or dc < f.connected_before_days):
        return False
    return True


def _talk(p, f):
    """The message filters."""
    if f.messaged is True and not p["out_count"]:
        return False
    if f.messaged is False and p["dm_count"]:
        return False
    if f.two_way and not (p["in_count"] and p["out_count"]):
        return False
    if f.only_they_wrote and not (p["in_count"] and not p["out_count"]):
        return False
    if f.awaiting_reply and p.get("last_dm_direction") != "in":
        return False
    if f.dm_within_days is not None and (p["days_since_dm"] is None or p["days_since_dm"] > f.dm_within_days):
        return False
    if f.quiet_days is not None and (p["days_since_dm"] is None or p["days_since_dm"] < f.quiet_days):
        return False
    if f.started_by and p.get("started_by") != f.started_by:
        return False
    if f.dormant and not (min(p["in_count"], p["out_count"]) >= 5 and (p["days_since_dm"] or 0) > 365):
        return False
    return True


def warmth(p):
    """How warm the relationship looks from the messages alone: more messages, both sides writing, and above all
    recent. A 160-message thread from 2022 ranks below a 15-message one from last month."""
    if not p["dm_count"]:
        return 0.0
    days = p["days_since_dm"] if p["days_since_dm"] is not None else 3650
    if p["in_count"] and p["out_count"]:
        volume = 2.0 * math.log1p(p["dm_count"]) + 1.5 * math.log1p(p.get("recent_dms", 0))
    elif p["out_count"]:
        volume = math.log1p(p["out_count"])            # you wrote, they never did
    else:
        volume = 0.3 * math.log1p(p["in_count"])       # they wrote, you never did: a pitch, mostly
    return round(volume / (1 + days / 180), 4)


def warmth_label(p):
    """hot / warm only while the conversation is recent; a close thread that went quiet is "dormant", which is
    exactly who to reconnect with. One-way threads are labeled as such."""
    if not p["dm_count"]:
        return "never messaged"
    days = p["days_since_dm"] if p["days_since_dm"] is not None else 3650
    if not p["out_count"]:
        return "one-way (they wrote)"
    if not p["in_count"]:
        return "one-way (you wrote)"
    if days <= 90:
        return "hot" if min(p["in_count"], p["out_count"]) >= 3 else "new"
    if days <= 365:
        return "warm"
    if days > 365 and min(p["in_count"], p["out_count"]) >= 5:
        return "dormant (was close)"
    return "cool" if days <= 730 else "cold"


TIERS = {"hot": 0, "warm": 1, "new": 1, "dormant (was close)": 3, "cool": 4, "one-way (you wrote)": 5, "cold": 6,
         "one-way (they wrote)": 7, "never messaged": 8}

SELLER = ("business development", "bdr", "sdr", "partnerships", "partner manager", "account executive",
          "sales development", "agency", "growth consultant", "lead generation")


SELLER_COMPANY = ("agency", "consulting", "consultancy", "outsourcing", "lead generation", "lead gen", "studio")
PITCH_CUES = re.compile(r"\b(sponsor(ship|ing|s)?|podcast|demo day|quick favou?r|partnership|partner with|we help|"
                        r"we work with|we build|we built|our (agency|team helps|clients)|agency|outsourc\w*|lead gen\w*|"
                        r"book a (demo|call)|case stud(y|ies)|free (trial|audit|pilot)|white[- ]label|guest post|"
                        r"collab(oration)?|would love to show you|i noticed you|noticed you('ve| have)|"
                        r"random question|saw you follow|your exact buyers?|not a pitch|quick pitch|saw your comment|"
                        r"rooting for|curious,? how are you)\b", re.I)


def likely_pitch(p):
    """They opened the latest conversation, and either sell for a living (title, or an agency / consulting company)
    or opened with a pitch line (sponsorship, "we help", a demo, a podcast plug). One-way inbound needs only one of
    those; a real back-and-forth needs a seller who asks for a favor or nothing specific, or a pitch line."""
    if p.get("opened_by") != "them":
        return False
    seller = any(has(p["title"], w, phrase=True) for w in SELLER) or \
        any(has(p.get("company", ""), w, phrase=True) for w in SELLER_COMPANY)
    cue = bool(PITCH_CUES.search(_plain(f"{p.get('opened_text') or ''} {p.get('last_dm_text') or ''}")))
    if not p["out_count"]:
        return seller or cue or p["in_count"] >= 4    # four+ messages you never answered: a sequence
    return cue or (seller and ask_tag(p.get("last_dm_text") or p.get("last_dm_preview")) in ("favor", ""))


def _order(rows, how):
    by_connect = sorted(rows, key=lambda p: p["connected_on"], reverse=True)   # tie-breaker: newest connection
    if how == "warm":      # by label first (so a "hot" never sits under a "warm"), then the score
        return sorted(by_connect, key=lambda p: (TIERS.get(warmth_label(p), 9), -warmth(p)))
    if how == "talked":
        return sorted(by_connect, key=lambda p: (p["dm_count"], p["last_dm_at"]), reverse=True)
    if how == "last-dm":
        return sorted(by_connect, key=lambda p: p["last_dm_at"], reverse=True)
    if how == "name":
        return sorted(rows, key=lambda p: p["name"].lower())
    return by_connect


def _your_last_before(last_at):
    """slug → your last 1:1 message before their last one (to tell "they answered your question" from a closing
    line). last_at: slug → their last message time."""
    if not last_at:
        return {}
    con = connect()
    if "dm_events" not in table_names(con):
        return {}
    out = {}
    marks = ",".join("?" for _ in last_at)
    for slug, sent_at, text in con.execute(
            f"SELECT counterpart_slug, sent_at, preview FROM dm_events WHERE is_group = 0 AND direction = 'out' "
            f"AND counterpart_slug IN ({marks}) ORDER BY sent_at", list(last_at)):
        if sent_at <= (last_at.get(slug) or "") and (text or "").strip():
            out[slug] = text
    return out


def _invites_by_slug():
    """slug → the latest connection request between you and them: {direction, sent_at, note}. The export's request
    history only covers recent months, so older connections have none."""
    from invites import load
    out = {}
    for r in load():
        if r["slug"] and r["sent_at"] and (r["slug"] not in out or r["sent_at"] > out[r["slug"]]["sent_at"]):
            out[r["slug"]] = r
    return out


def how_connected(p):
    inv = p.get("invite")
    if not inv:
        return ""
    when = inv["sent_at"].date().isoformat()
    who = "you sent them a request" if inv["direction"] == "sent" else "they sent you a request"
    return f"{who} on {when}" + (" with a note" if inv["note"] else "")


SORT_TEXT = {"warm": "warmest first", "last-dm": "most recent message first", "talked": "most messages first",
             "connected": "newest connection first", "name": "name",
             "owed": "real conversations first, fresh asks (meeting, question, favor) before ones over 60 days old, "
                     "likely pitches last"}


def no_url_people(as_of):
    """Connections LinkedIn exported with a blank profile URL. They have a name, title and company, so filters
    apply to them and they are counted, but they can't be listed as a link or messaged through Syft."""
    con = connect()
    if "connections" not in table_names(con):
        return []
    out = []
    for first, last, comp, pos, raw in con.execute(
            "SELECT [First Name], [Last Name], Company, Position, [Connected On] FROM connections "
            "WHERE COALESCE(URL,'') = ''"):
        iso = parse_connected_on(raw) or ""
        days = (as_of - date.fromisoformat(iso)).days if iso else None
        out.append({"slug": "", "name": f"{first or ''} {last or ''}".strip(), "first_name": (first or "").strip(),
                    "last_name": (last or "").strip(), "profile_url": "", "company": (comp or "").strip(),
                    "title": (pos or "").strip(), "email": "", "last_dm_direction": "", "last_dm_preview": "",
                    "connected_on": iso, "dm_count": 0, "last_dm_at": "", "days_since_dm": None,
                    "days_since_connect": days, "in_count": 0, "out_count": 0})
    return out


def select(f, as_of=None, people=None):
    """(rows, summary). rows: matching connections, ordered. summary: counts for the whole group the user asked
    about (before any message filter), what was left out, and for company filters the companies behind them."""
    exported = export_date()
    as_of = as_of or exported or date.today()
    if people is None:
        people = load_people(as_of) + no_url_people(as_of)
        who_filters = f.titles or f.roles or f.companies or f.company_list or f.keywords or f.has_email or \
            f.connected_within_days or f.connected_before_days
        if f.uses_messages() and not who_filters:
            people += message_only_people(as_of)        # owed replies and conversations with non-connections
    recent = recent_dm_counts(as_of)
    for p in people:
        p["started_by"] = p.get("opened_by", "")          # who opened the latest conversation
        p["recent_dms"] = recent.get(p.get("slug"), 0)
        p.setdefault("connection", True)
    base = [p for p in people if _who(p, f)]
    rows = [p for p in base if _talk(p, f)]
    base = [p for p in base if p.get("connection", True)]     # the group summary is about connections
    closed = []
    if f.awaiting_reply:
        asked = _your_last_before({p["slug"]: p["last_dm_at"] for p in rows if p.get("last_dm_direction") == "in"})
        for p in rows:
            mine = asked.get(p.get("slug"), "")
            p["you_asked"] = _real_question(mine)
            p["you_offered"] = bool(_OFFER.search(_plain(mine)))
            theirs = p.get("last_dm_text") or ""
            body = _GREETING.sub("", theirs, count=1).strip()
            p["offer_taken"] = p["you_offered"] and bool(_YES.match(body) or _NEED.search(theirs))
    if f.awaiting_reply:
        for p in rows:
            p["reads_finished"] = looks_closed(p)
    if f.awaiting_reply and not f.include_closed:
        closed = [p for p in rows if p["reads_finished"]]
        rows = [p for p in rows if not p["reads_finished"]]
    rows = _order(rows, f.sort_key())
    if f.awaiting_reply:
        summary_pitches = sum(1 for p in rows if likely_pitch(p))
    if f.awaiting_reply and f.sort_key() == "last-dm":
        # Owed replies: real conversations before one-way ones, likely pitches last, then what they ask for
        # (meeting, question, favor), then warmth.
        rank = {"meeting": 0, "question": 1, "favor": 2, "": 3}

        def ask_rank(p):
            r = rank[ask_tag(p.get("last_dm_text") or p.get("last_dm_preview"))]
            if p.get("offer_taken"):
                return 0                              # a yes to your own offer: as good as a meeting ask
            if r == 3 and p.get("you_asked"):
                return 1                              # they answered your question: your move
            if r == 2 and warmth_label(p) not in ("hot", "warm"):
                return 3                              # a favor from someone you barely know waits
            return r
        rows = sorted(rows, key=lambda p: (likely_pitch(p), not (p["in_count"] and p["out_count"]),
                                           (p["days_since_dm"] or 0) > 60, ask_rank(p), -warmth(p)))
    summary = {
        "total": len(rows), "definition": f.describe(), "sort": f.sort_key(), "as_of": as_of.isoformat(),
        "by_role": ({r: sum(1 for p in rows if role_match(p["title"], r)) for r in f.roles}
                    if len(f.roles) > 1 else {}),
        "sorted_by": SORT_TEXT.get("owed" if f.awaiting_reply and f.sort_key() == "last-dm" else f.sort_key(), f.sort_key()),
        "likely_pitches": summary_pitches if f.awaiting_reply else 0,
        "export_date": exported.isoformat() if exported else None,
        "group": len(base), "group_is_everyone": not (f.titles or f.roles or f.companies or f.company_list or
                                                      f.keywords or f.names or f.has_email or f.not_titles or
                                                      f.not_companies or f.not_company_list or
                                                      f.connected_within_days or f.connected_before_days),
        "not_connections": sum(1 for p in rows if not p.get("connection", True)),
        "you_started": sum(1 for p in rows if p.get("started_by") == "you"),
        "they_started": sum(1 for p in rows if p.get("started_by") == "them"),
        "inbound_only": sum(1 for p in rows if p["in_count"] and not p["out_count"]),
        "group_you_wrote_to": sum(1 for p in base if p["out_count"]),
        "group_two_way": sum(1 for p in base if p["in_count"] and p["out_count"]),
        "group_only_they_wrote": sum(1 for p in base if p["in_count"] and not p["out_count"]),
        "group_never_messaged": sum(1 for p in base if not p["dm_count"]),
        "with_email": sum(1 for p in rows if p.get("email")),
        "without_profile_url": sum(1 for p in rows if not p["profile_url"]),
    }
    if closed:
        summary["hidden_finished_threads"] = len(closed)
    if f.companies or f.company_list:
        summary["companies"] = collections.Counter(p["company"] or "(none)" for p in rows).most_common(15)
    if f.company_list:
        connected = [p for p in people if p.get("connection", True)]
        all_companies = collections.Counter(p["company"] for p in connected if p["company"])
        summary["per_listed_company"] = [
            {"company": label, "people": sum(1 for p in rows if company_matches(p["company"], w)),
             "connections_there": sum(1 for p in connected if company_matches(p["company"], w)),
             "matched_as": sorted({p["company"] for p in rows if company_matches(p["company"], w)})[:5],
             "similar": _similar_companies(w, all_companies)}
            for label, w in f.company_list]
    invites_by = _invites_by_slug() if rows else {}
    for p in rows:
        p["invite"] = invites_by.get(p.get("slug"))
        p["matched_by"] = matched_title(p, f)
        p["role"] = next((r for r in f.roles if role_match(p["title"], r)), "")
        if f.company_list:
            p["target"] = next((label for label, w in f.company_list if company_matches(p["company"], w)), "")
    return rows, summary


def _similar_companies(target, counts, top=2):
    """Companies in your network that aren't matched but share a 4+ letter start with the listed name
    ("Snapchat" → "Snap Inc." 108): a hint to check, never counted."""
    t = list(target or ())
    if not t or len(t[0]) < 4:
        return []
    out = collections.Counter()
    for company, n in counts.items():
        w = company_words(company)
        if not w or company_matches(company, t):
            continue
        # a one-word company whose name starts the listed one ("Snap Inc." for "Snapchat"), not "Cloud Capital"
        # for "CloudBees" or "SalesPlaybook" for "Salesloft"
        prefix = len(w) == 1 and len(w[0]) >= 4 and len(w[0]) < len(t[0]) and t[0].startswith(w[0])
        acquired = re.search(rf"\(acquired by {re.escape(' '.join(t))}\b", company.lower())
        if (prefix and n >= 2) or acquired:
            out[company] += n
    return out.most_common(top)


def by_company(rows, limit=20, company_list=None):
    """Company-first view: how many people, how many you've written to, the warmest contact there. With a company
    list, people are grouped under the company as the user listed it ("Amazon" covers "Amazon Web Services")."""
    groups = collections.OrderedDict()
    for p in rows:
        key = next((label for label, w in (company_list or []) if company_matches(p["company"], w)), None)
        groups.setdefault(key or p["company"] or "(none)", []).append(p)
    out = []
    for comp, ps in groups.items():
        best = max(ps, key=warmth)
        out.append({"company": comp, "people": len(ps), "best_warmth": warmth(best),
                    "you_wrote_to": sum(1 for p in ps if p["out_count"]),
                    "two_way": sum(1 for p in ps if p["in_count"] and p["out_count"]),
                    "warmest": best["name"] if best["dm_count"] else "", "warmest_title": best["title"] if best["dm_count"] else "",
                    "warmest_last_dm": best["last_dm_at"][:10] if best["dm_count"] else "",
                    "names": [f"{p['name']} ({p['title']}, {warmth_label(p)})"
                              for p in sorted(ps, key=warmth, reverse=True)[:3]]})
    out.sort(key=lambda g: (g["best_warmth"], g["two_way"], g["you_wrote_to"], g["people"]), reverse=True)
    return out[:limit] if limit else out


def row_out(p, text=False):
    return {"name": p["name"], "title": p["title"], "company": p["company"], "profile_url": p["profile_url"],
            "email": p.get("email", ""), "connected_on": p["connected_on"], "dms": p["dm_count"],
            "you_sent": p["out_count"], "they_sent": p["in_count"], "last_dm_at": p["last_dm_at"][:10],
            "they_wrote_last": "yes" if p.get("last_dm_direction") == "in" else "",
            "started_by": p.get("started_by", ""), "connection": "yes" if p.get("connection", True) else "no",
            "asks": (ask_tag(p.get("last_dm_text") or p.get("last_dm_preview")) or
                     ("took you up on your offer" if p.get("offer_taken") else
                      "answered your question" if p.get("you_asked") else "")) if p.get("last_dm_direction") == "in" else "",
            "reads_finished": bool(p.get("reads_finished")),
            "waiting_days": p["days_since_dm"] if p.get("last_dm_direction") == "in" else None,
            "you_wrote_last": p["days_since_dm"] if p.get("last_dm_direction") == "out" and p["dm_count"] else None,
            "likely_pitch": likely_pitch(p), "opened": p.get("started_by", ""),
            "group_messages": p.get("group_count", 0), "how_connected": how_connected(p),
            **({"last_message": (p.get("last_dm_text") or "")[:200],
                "request_note": (p.get("invite") or {}).get("note", "")} if text else {}),
            "warmth": warmth_label(p), "matched_by": p.get("matched_by", ""), "target": p.get("target", "")}


def sheet_row(p, with_target=False, with_role=False):
    """A row to work through in a spreadsheet: who, why they're on the list, how warm, and empty columns for
    the user's own status and notes. Target / Role columns only when the list was built from a company list /
    roles, so no column is always empty."""
    row = {"Name": p["name"], "Title": p["title"], "Company": p["company"]}
    if with_target:
        row["Target Company"] = p.get("target", "")
        if "target_why" in p:
            row["Why Listed"] = p["target_why"]
    if with_role:
        row["Role"] = "; ".join(r for r in with_role if role_match(p["title"], r)) if isinstance(with_role, list) \
            else p.get("role", "")
    last_from = {"in": "them", "out": "you"}.get(p.get("last_dm_direction"), "") if p["dm_count"] else ""
    row.update({"Warmth": warmth_label(p), "Last DM": p["last_dm_at"][:10], "DMs": p["dm_count"],
                "You Sent": p["out_count"], "They Sent": p["in_count"], "Last From": last_from or "-",
                "Connected On": p["connected_on"], "Email": p.get("email", ""), "LinkedIn URL": p["profile_url"],
                "Status": "", "Notes": ""})
    return row


def crm_row(p):
    """Columns HubSpot / Salesforce / a Google Sheet import map without renaming."""
    return {"First Name": clean_person_name(p.get("first_name", "")), "Last Name": clean_person_name(p.get("last_name", "")),
            "Email": p.get("email", ""), "Email Type": email_type(p.get("email", "")),
            "Company": p["company"], "Job Title": p["title"], "LinkedIn URL": p["profile_url"],
            "Connected On": p["connected_on"], "Last LinkedIn DM": p["last_dm_at"][:10],
            "LinkedIn DMs": p["dm_count"]}
