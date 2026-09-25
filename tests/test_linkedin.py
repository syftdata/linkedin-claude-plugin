"""End-to-end tests on a synthetic export in LinkedIn's file format. Standard library only:

    python3 -m unittest discover -s tests -v
"""
import csv
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "skills" / "linkedin" / "linkedin.py"
LEGACY = ROOT / "skills" / "linkedin-search" / "linkedin_search.py"
sys.path.insert(0, str(CLI.parent))   # so tests can import the modules directly
AS_OF = "2026-09-23"
ME = "https://www.linkedin.com/in/me-owner"


def url(slug):
    return f"https://www.linkedin.com/in/{slug}"


CONNECTIONS = [
    # first, last, slug, company, position, connected on
    ("Alice", "Able", "alice-able", "Northwind", "VP Marketing", "10 Jan 2015"),
    ("Bob", "Baker", "bob-baker-1a2b", "Contoso", "Engineer", "03 Feb 2016"),
    ("Carol", "Cole", "carol-cole", "Fabrikam", "Designer", "12 Mar 2017"),
    ("Dave", "Dunn", "dave-dunn", "Initech", "Analyst", "20 Apr 2024"),
    ("Erin", "East", "erin-east", "Globex", "Consultant", "01 Jun 2018"),
    ("Frank", "Ford", "frank-ford", "Umbrella", "Sales Rep", "15 Jun 2026"),
    ("Gina", "Gale", "gina-gale", "Acme Corp", "Product Manager", "07 Jul 2019"),
    ("Hank", "Hill", "hank-hill", "Stark", "Technical Recruiter", "02 Feb 2014"),
    ("Ivy", "Ives", "ivy-ives", "Wayne", "Student", "sometime"),
    ("Pete", "Pitch", "pete-pitch", "Vendorly", "Sales Rep", "01 Jan 2020"),
    ("Nora", "Null", "", "Hidden", "Member", "01 Jan 2016"),   # LinkedIn blanks some URLs
]

MESSAGES = [
    # conversation, sender slug, recipient slugs, date, content
    ("c1", "me-owner", ["alice-able"], "2026-07-30 10:00:00 UTC", "Hi Alice"),
    ("c1", "alice-able", ["me-owner"], "2026-08-01 09:00:00 UTC", "Hey! good to hear from you"),
    ("c2", "bob-baker-1a2b", ["me-owner"], "2021-05-01 12:00:00 UTC", "Congrats on the launch"),
    ("c3", "me-owner", ["carol-cole", "dave-dunn"], "2025-02-01 15:30:00 UTC", "Group hello"),
    ("c4", "zoe-zed", ["me-owner"], "2026-01-01 08:00:00 UTC", "Not a connection"),
    ("c5", "pete-pitch", ["me-owner"], "2024-01-01 08:00:00 UTC", "Quick question about your stack"),
]


def build_zip(path, when=(2026, 9, 23, 9, 0, 0)):
    """A synthetic export. `when` is the timestamp on the files inside, which is how a real export says when it
    was made."""
    with zipfile.ZipFile(path, "w") as raw:
        class Stamped:                      # writestr with LinkedIn-style file dates
            def writestr(self, name, data):
                raw.writestr(zipfile.ZipInfo(name, date_time=when), data)
        z = Stamped()
        base = "Complete_LinkedInDataExport_09-23-2026/"
        buf = io.StringIO()
        buf.write("Notes:\n")
        buf.write('"When exporting your connection data, you may notice that some of the email addresses are missing."\n')
        buf.write("\n")
        w = csv.writer(buf)
        w.writerow(["First Name", "Last Name", "URL", "Email Address", "Company", "Position", "Connected On"])
        for f, l, s, c, p, d in CONNECTIONS:
            w.writerow([f, l, url(s) if s else "", "alice@northwind.com" if f == "Alice" else "", c, p, d])
        z.writestr(base + "Connections.csv", buf.getvalue())

        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["CONVERSATION ID", "CONVERSATION TITLE", "FROM", "SENDER PROFILE URL", "TO",
                    "RECIPIENT PROFILE URLS", "DATE", "SUBJECT", "CONTENT", "FOLDER"])
        for cid, sender, recips, d, content in MESSAGES:
            w.writerow([cid, "", sender, url(sender), ",".join(recips), ",".join(url(r) for r in recips), d, "",
                        content, "INBOX"])
        z.writestr(base + "messages.csv", buf.getvalue())
        # A similarly named file that must NOT be read as messages.
        z.writestr(base + "guide_messages.csv", "DATE,CONTENT\n2026-01-01,ignore me\n")

        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["From", "To", "Sent At", "Message", "Direction", "inviterProfileUrl", "inviteeProfileUrl"])
        w.writerow(["Ivan Ivanov", "Me Owner", "9/1/26, 10:00 AM", "", "INCOMING", url("ivan-ivanov"), ME])
        # Sent requests: accepted (Alice is a connection), never accepted (old, with a note), recent, and one to
        # someone you have DMed (Zoe).
        w.writerow(["Me Owner", "Alice Able", "1/5/26, 9:00 AM", "", "OUTGOING", ME, url("alice-able")])
        w.writerow(["Me Owner", "Quinn Quiet", "2/1/26, 9:00 AM", "Hi Quinn", "OUTGOING", ME, url("quinn-quiet")])
        w.writerow(["Me Owner", "Rita Recent", "9/15/26, 9:00 AM", "", "OUTGOING", ME, url("rita-recent")])
        w.writerow(["Me Owner", "Zoe Zed", "3/1/26, 9:00 AM", "", "OUTGOING", ME, url("zoe-zed")])
        z.writestr(base + "Invitations.csv", buf.getvalue())

        # Current exports suffix some files with a member id. LinkedIn ids carry a millisecond timestamp (id >> 22):
        # the post's activity id is made within seconds of the share id, which is how replies are tied to your post.
        ms = 1777626000000
        share, activity, elsewhere = (ms << 22) | 11, ((ms + 900) << 22) | 22, ((ms + 86400000) << 22) | 33
        z.writestr(base + "Shares_7789716.csv", "Date,ShareLink,ShareCommentary,SharedUrl,MediaUrl,Visibility\n"
                   f"2026-05-01 10:00:00,https://www.linkedin.com/feed/update/urn%3Ali%3Ashare%3A{share},"
                   "Thoughts on AI in GTM,,,MEMBER_NETWORK\n")
        z.writestr(base + "Comments_7789716.csv", "Date,Link,Message\n"
                   "2026-05-02 10:00:00,https://lnkd.in/c1,Great AI post\n"
                   f"2026-05-02 11:00:00,https://www.linkedin.com/feed/update/urn:li:activity:{activity},Alice Able thanks, agreed!\n"
                   f"2026-05-03 11:00:00,https://www.linkedin.com/feed/update/urn:li:activity:{activity},Carol Cole good point\n"
                   f"2026-05-04 11:00:00,https://www.linkedin.com/feed/update/urn:li:activity:{elsewhere},Bob Baker nice post\n"
                   # a decorated name, and LinkedIn's backslash-escaped quotes in Comments.csv
                   f'2026-05-05 11:00:00,https://www.linkedin.com/feed/update/urn:li:activity:{activity},'
                   '"˗ˏˋ Dave Dunn ˎˊ˗ you said \\"ship it\\", agreed"\n'
                   # a mention, not a reply to Erin
                   f"2026-05-06 11:00:00,https://www.linkedin.com/feed/update/urn:li:activity:{activity},"
                   "Erin East's take on this is the one to read\n")
        # Your own profile and job search.
        z.writestr(base + "Jobs/Saved Jobs.csv", "Saved Date,Job Url,Job Title,Company Name\n"
                   '"9/1/26, 9:00 AM",https://www.linkedin.com/jobs/view/1,Product Marketing Lead,Northwind\n'
                   '"8/1/26, 9:00 AM",https://www.linkedin.com/jobs/view/2,Designer,Fabrikam Inc.\n')
        z.writestr(base + "Jobs/Job Applications.csv", "Application Date,Contact Email,Contact Phone Number,Company Name,"
                   "Job Title,Job Url,Resume Name,Question And Answers\n"
                   '"8/15/26, 1:32 PM",me@example.com,,Globex,Analyst,https://www.linkedin.com/jobs/view/3,cv.pdf,\n')
        z.writestr(base + "Positions.csv", "Company Name,Title,Description,Location,Started On,Finished On\n"
                   "Syftly,Founder,Building things,Remote,Jan 2023,\n"
                   "Initech,Analyst,TPS reports,Austin,Jan 2019,Dec 2022\n")
        z.writestr(base + "Profile.csv", "First Name,Last Name,Maiden Name,Address,Birth Date,Headline,Summary,"
                   "Industry,Zip Code,Geo Location\nMe,Owner,,,,Founder at Syftly,I build GTM tools.,Software,,Austin\n")
        z.writestr(base + "Skills.csv", "Name\nGo-to-market\n")
        z.writestr(base + "Endorsement_Received_Info.csv", "Endorsement Date,Skill Name,Endorser First Name,"
                   "Endorser Last Name,Endorser Public Url,Endorsement Status\n"
                   "2026/08/01 10:00:00 UTC,Go-to-market,Gina,Gale,www.linkedin.com/in/gina-gale,ACCEPTED\n")


class LinkedInBotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        t = Path(cls.tmp.name)
        cls.exports = t / "exports"
        cls.exports.mkdir()
        cls.db = t / "db" / "data.db"
        build_zip(cls.exports / "Complete_LinkedInDataExport_09-23-2026.zip")
        cls.env = dict(os.environ, LINKEDIN_EXPORTS_DIR=str(cls.exports), LINKEDIN_DB_PATH=str(cls.db))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_cli(self, *args, script=CLI, check=True):
        p = subprocess.run([sys.executable, str(script), *args], env=self.env, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL)
        if check and p.returncode != 0:
            self.fail(f"{args} exited {p.returncode}\nstdout:{p.stdout}\nstderr:{p.stderr}")
        return p

    def cleanup_json(self, *args):
        return json.loads(self.run_cli("cleanup-candidates", "--json", "--dry-run", "--as-of", AS_OF, *args).stdout)

    def names(self, summary):
        return [r["name"] for r in summary["top"]]

    # --- ingest -------------------------------------------------------------------------------------------------

    def test_ingest_loads_every_file_and_keeps_v1_tables(self):
        meta = json.loads(self.run_cli("ingest", "--json").stdout)
        self.assertEqual(meta["schema_version"], "7")
        self.assertEqual(meta["connections"], "11")
        self.assertEqual(meta["messages"], "6")          # guide_messages.csv was not mistaken for it
        self.assertEqual(meta["invitations"], "5")
        self.assertEqual(meta["dm_counterparts"], "6")   # alice, bob, carol, dave, zoe, pete
        self.assertEqual(meta["dm_counterparts_connected"], "5")
        con = sqlite3.connect(self.db)
        cols = [r[1] for r in con.execute("PRAGMA table_info(connections)")]
        self.assertEqual(cols, ["First Name", "Last Name", "URL", "Email Address", "Company", "Position", "Connected On"])
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"shares", "connections", "comments", "metadata", "messages", "invitations",
                         "connections_index", "dm_events", "last_dm"} <= tables)
        owner = dict(con.execute("SELECT key, value FROM metadata").fetchall())["owner_slug"]
        self.assertEqual(owner, "me-owner")

    def test_last_dm_join(self):
        self.run_cli("stats")
        con = sqlite3.connect(self.db)
        rows = dict((r[0], r[1:]) for r in con.execute(
            "SELECT counterpart_slug, dm_count, last_dm_at, last_dm_direction, group_count FROM last_dm"))
        self.assertEqual(rows["alice-able"], (2, "2026-08-01T09:00:00Z", "in", 0))
        self.assertEqual(rows["carol-cole"], (0, None, None, 1))     # group chat only
        self.assertNotIn("ivan-ivanov", rows)                         # invitations never become DMs

    # --- search, v1 compatibility ---------------------------------------------------------------------------------

    def test_legacy_entry_point_still_works(self):
        out = self.run_cli("find-connections", "--title", "recruiter", script=LEGACY).stdout
        self.assertIn("Hank Hill", out)
        self.assertIn("Found 1 connection(s):", out)
        self.assertIn("Connections: 11", self.run_cli("stats", script=LEGACY).stdout)
        # Current exports: Comments_<id>.csv with a `Message` column (older ones called it `Comment`).
        self.assertIn("Great AI post", self.run_cli("search-comments", "--query", "ai").stdout)
        self.assertIn("Thoughts on AI", self.run_cli("search-shares", "--query", "ai", script=LEGACY).stdout)

    def test_v1_database_is_rebuilt(self):
        other_db = Path(self.tmp.name) / "v1" / "data.db"
        other_db.parent.mkdir()
        con = sqlite3.connect(other_db)
        con.execute('CREATE TABLE connections ("First Name" TEXT)')
        con.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
        zip_path = str(next(self.exports.glob("*.zip")))
        con.executemany("INSERT INTO metadata VALUES (?, ?)", [("last_loaded_zip", zip_path),
                                                                ("last_loaded_timestamp", "9999999999")])
        con.commit()
        con.close()
        env = dict(self.env, LINKEDIN_DB_PATH=str(other_db))
        subprocess.run([sys.executable, str(CLI), "stats"], env=env, check=True, capture_output=True,
                       stdin=subprocess.DEVNULL)
        tables = {r[0] for r in sqlite3.connect(other_db).execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("last_dm", tables)

    # --- cleanup ------------------------------------------------------------------------------------------------

    def test_network_profile_offers_presets_with_counts(self):
        prof = json.loads(self.run_cli("network-profile", "--json", "--as-of", AS_OF).stdout)
        self.assertEqual(prof["connections_total"], 11)
        self.assertEqual(prof["connections_without_url"], 1)
        self.assertEqual(prof["connections_listable"], 10)
        self.assertEqual(prof["headroom"], 30000 - 11)
        self.assertEqual(prof["never_replied"], 2)   # Bob (2021) and Pete (2024) wrote in, no reply
        self.assertEqual(prof["connected_on_age"]["date unreadable"], 1)
        self.assertEqual(prof["never_messaged_1to1"], 7)
        self.assertEqual(prof["only_group_chats"], 2)
        counts = {p["preset"]: p["count"] for p in prof["presets"]}
        self.assertEqual(counts, {"old-never-messaged": 4, "old-quiet": 6, "never-messaged": 7,
                                  "never-replied": 2, "recent-never-messaged": 1})

    def test_old_never_messaged_ranked(self):
        s = self.cleanup_json("--preset", "old-never-messaged")
        self.assertEqual(s["count"], 4)
        self.assertEqual(self.names(s), ["Hank Hill", "Erin East", "Carol Cole", "Gina Gale"])
        carol = next(r for r in s["top"] if r["name"] == "Carol Cole")
        self.assertIn("only in group chats", carol["reasons"])

    def test_old_quiet_uses_last_dm(self):
        names = self.names(self.cleanup_json("--preset", "old-quiet"))
        self.assertIn("Bob Baker", names)       # last DM 2021, over 3 years
        self.assertNotIn("Alice Able", names)   # messaged last month
        self.assertNotIn("Ivy Ives", names)     # unreadable date never lands in an age-based group

    def test_never_replied(self):
        s = self.cleanup_json("--preset", "never-replied")
        self.assertEqual(self.names(s), ["Bob Baker", "Pete Pitch"])
        self.assertTrue(all("you never replied" in r["reasons"] for r in s["top"]))
        self.assertNotIn("Alice Able", self.names(self.cleanup_json("--never-replied")))  # she got a reply

    def test_group_chats_can_count(self):
        s = self.cleanup_json("--preset", "old-never-messaged", "--count-group-as-dm")
        self.assertNotIn("Carol Cole", self.names(s))

    def test_keep_and_only_filters(self):
        s = self.cleanup_json("--preset", "old-never-messaged", "--keep-company", "acme")
        self.assertEqual(s["count"], 3)
        self.assertEqual(s["kept_by_company"], 1)
        s = self.cleanup_json("--never-messaged", "--only-title", "recruiter")
        self.assertEqual(self.names(s), ["Hank Hill"])

    def test_limit_and_custom_thresholds(self):
        s = self.cleanup_json("--connected-before", "5y", "--never-messaged", "--limit", "2")
        self.assertEqual(self.names(s), ["Hank Hill", "Erin East"])
        self.assertEqual(s["matched_before_limit"], 4)
        s = self.cleanup_json("--older-than", "18m", "--no-dm-older-than", "12m")
        self.assertIn("Bob Baker", self.names(s))

    def test_export_matches_dry_run(self):
        dry = self.cleanup_json("--preset", "old-quiet")
        out = Path(self.tmp.name) / "out.csv"
        self.run_cli("cleanup-candidates", "--preset", "old-quiet", "--as-of", AS_OF, "--export", str(out))
        with open(out) as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), dry["count"])
        self.assertEqual(list(rows[0].keys()), [
            "name", "company", "title", "profile_url", "connected_on", "last_dm_at", "last_dm_preview",
            "days_since_connect", "days_since_dm", "cleanup_score", "reasons"])
        self.assertEqual(rows[0]["last_dm_preview"], "")  # previews only with --with-preview

    def test_refuses_to_pick_a_group(self):
        p = self.run_cli("cleanup-candidates", "--as-of", AS_OF, check=False)
        self.assertEqual(p.returncode, 2)
        self.assertIn("network-profile", p.stderr)

    def test_small_archive_without_messages_is_flagged(self):
        small = Path(self.tmp.name) / "small"
        small.mkdir()
        with zipfile.ZipFile(small / "small.zip", "w") as z:
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["First Name", "Last Name", "URL", "Email Address", "Company", "Position", "Connected On"])
            w.writerow(["Pat", "Poe", url("pat-poe"), "", "Co", "Engineer", "01 Jan 2015"])
            z.writestr("Connections.csv", "Notes:\nx\n\n" + buf.getvalue())
        env = dict(self.env, LINKEDIN_EXPORTS_DIR=str(small), LINKEDIN_DB_PATH=str(small / "data.db"))
        p = subprocess.run([sys.executable, str(CLI), "network-profile", "--json", "--as-of", AS_OF], env=env,
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, check=True)
        prof = json.loads(p.stdout)
        self.assertFalse(prof["messages"]["loaded"])
        self.assertIn("larger data archive", p.stderr)

    def test_pass2_is_not_faked(self):
        out = Path(self.tmp.name) / "icp.csv"
        p = self.run_cli("cleanup-candidates", "--preset", "old-quiet", "--icp", "b2b-saas", "--export", str(out),
                         check=False)
        self.assertEqual(p.returncode, 2)
        self.assertIn("Pass 2", p.stderr)
        self.assertFalse(out.exists())

    # --- syft-leads (hand-off to the Syft MCP) --------------------------------------------------------------------

    def syft_leads(self, *args, env=None):
        p = subprocess.run([sys.executable, str(CLI), "syft-leads", *args], env=env or self.env, capture_output=True,
                           text=True, stdin=subprocess.DEVNULL, check=True)
        return json.loads(p.stdout)

    def test_syft_leads_from_connections(self):
        out = self.syft_leads("--title", "engineer")
        self.assertEqual(out["total"], 1)
        self.assertEqual(out["leads"], [{"linkedin": url("bob-baker-1a2b"), "name": "Bob Baker", "firstName": "Bob",
                                         "lastName": "Baker", "title": "Engineer", "company": "Contoso"}])
        hidden = self.syft_leads("--company", "hidden")     # Nora has no profile URL: counted, never guessed
        self.assertEqual((hidden["total"], hidden["skipped_no_url"]), (0, 1))

    def test_syft_leads_from_any_csv_without_an_export(self):
        t = Path(self.tmp.name)
        f = t / "salesnav.csv"
        f.write_text(
            "Notes:\n\"Exported from somewhere\"\n\n"
            "First Name,Last Name,URL,Company,Position\n"
            "Ana,Avila,https://www.linkedin.com/in/ana-avila/?miniProfile=x,Alpha,Founder\n"
            "Ana,Avila,https://linkedin.com/in/Ana-Avila,Alpha,Founder\n"      # same person, different spelling
            "Ben,Bryce,in/ben-bryce,Beta,CEO\n"                               # bare handle
            "Cy,Cole,,Gamma,CTO\n")                                           # no URL
        empty = t / "no-export"
        empty.mkdir(exist_ok=True)
        env = dict(os.environ, LINKEDIN_EXPORTS_DIR=str(empty), LINKEDIN_DB_PATH=str(empty / "data.db"))
        out = self.syft_leads("--csv", str(f), env=env)
        self.assertEqual((out["total"], out["duplicates_removed"], out["skipped_no_url"]), (2, 1, 1))
        self.assertEqual([x["linkedin"] for x in out["leads"]], [url("ana-avila"), url("ben-bryce")])
        self.assertEqual(out["leads"][1]["title"], "CEO")
        self.assertFalse((empty / "data.db").exists())      # a CSV source never loads an export

        cleanup_csv = t / "cleanup.csv"                      # the cleanup skill's own columns
        cleanup_csv.write_text("name,company,title,profile_url\nZed Zane,Omega,VP Sales,https://www.linkedin.com/in/zed\n")
        lead = self.syft_leads("--csv", str(cleanup_csv), env=env)["leads"][0]
        self.assertEqual((lead["firstName"], lead["lastName"], lead["company"]), ("Zed", "Zane", "Omega"))

    def test_syft_leads_chunks_and_needs_a_source(self):
        everyone = self.syft_leads("--connected-before", "1d")["total"]
        first = self.syft_leads("--connected-before", "1d", "--limit", "2")
        rest = self.syft_leads("--connected-before", "1d", "--offset", "2")
        self.assertEqual((first["count"], first["total"]), (2, everyone))
        self.assertEqual(first["count"] + rest["count"], everyone)
        self.assertFalse({x["linkedin"] for x in first["leads"]} & {x["linkedin"] for x in rest["leads"]})
        p = self.run_cli("syft-leads", check=False)
        self.assertEqual(p.returncode, 2)
        self.assertIn("--csv", p.stderr)

    def test_syft_leads_order_title_only_and_names(self):
        recent = self.syft_leads("--connected-before", "1d", "--sort", "recent")["leads"]   # newest connection first
        self.assertEqual(recent[0]["linkedin"], url("frank-ford"))      # connected Jun 2026, the newest
        self.assertEqual(self.syft_leads("--keywords", "acme")["total"], 1)                     # company hit
        self.assertEqual(self.syft_leads("--keywords", "acme", "--title-only")["total"], 0)     # title only
        sys.path.insert(0, str(CLI.parent))
        import syft_leads
        for raw, want in (("🚀 Neal", "Neal"), ("James J.", "James"), ("Tapajyoti (Tukan)", "Tapajyoti"),
                          ("JOHN", "John"), ("Mary-Kate", "Mary-Kate"), ("O'Neil", "O'Neil"), ("Bo", "Bo"),
                          ("brendan", "Brendan"), ("Lanny M.", "Lanny")):
            self.assertEqual(syft_leads.clean_first_name(raw), want, raw)
        t = Path(self.tmp.name) / "odd.csv"
        t.write_text("first name,last name,linkedin\n🚀 Neal,Lathia,in/nlathia\nAna,Avila,in/ana\n")
        out = self.syft_leads("--csv", str(t))
        self.assertEqual(out["odd_first_names"], [{"linkedin": url("nlathia"), "firstName": "🚀 Neal", "suggested": "Neal"}])
        self.assertEqual(out["leads"][0]["firstName"], "🚀 Neal")                       # flagged, not changed
        self.assertEqual(self.syft_leads("--csv", str(t), "--clean-names")["leads"][0]["firstName"], "Neal")

    def test_syft_leads_max_caps_the_list(self):
        capped = self.syft_leads("--connected-before", "1d", "--max", "3", "--offset", "0", "--limit", "100")
        self.assertEqual((capped["total"], capped["count"]), (3, 3))
        self.assertGreater(capped["matched"], 3)

    # --- people ---------------------------------------------------------------------------------------------------

    def people_json(self, *args):
        return json.loads(self.run_cli("people", "--json", "--as-of", AS_OF, *args).stdout)

    def test_people_ranks_by_conversation_and_filters(self):
        talked = self.people_json("--messaged")
        self.assertEqual(talked["sort"], "warm")
        self.assertEqual(talked["people"][0]["name"], "Alice Able")          # 2 DMs, both ways
        self.assertEqual((talked["group_you_wrote_to"], talked["group_two_way"], talked["group_only_they_wrote"]),
                         (1, 1, 2))            # connections only, before the message filter (Zoe isn't one)
        self.assertEqual(self.people_json("--only-they-wrote", "--limit", "0")["total"], 3)   # Bob, Pete, Zoe (not a connection)
        self.assertEqual(self.people_json("--role", "recruiter")["people"][0]["name"], "Hank Hill")
        self.assertEqual(self.people_json("--title", "marketing vp")["people"][0]["name"], "Alice Able")  # any order
        self.assertIn("5y", self.people_json("--connected-before", "5y")["definition"])
        self.assertEqual(self.people_json("--two-way")["total"], 1)           # only Alice wrote back and forth
        both = self.people_json("--title", "recruit", "--title", "vp")        # repeatable = ANY
        self.assertEqual({p["name"] for p in both["people"]}, {"Hank Hill", "Alice Able"})
        self.assertEqual(self.people_json("--title", "ai")["total"], 0)       # short words match whole words
        import people
        for text, word, hit in (("Technical Recruiter", "recruit", True), ("Co-Founder & CEO", "founder", True),
                                ("Cofounder", "founder", True), ("Coaching & Mentorship to founders", "founder", False),
                                ("Founding Partner", "founder", False), ("Head of Marketing", "head of marketing", True),
                                ("Chief AI Officer", "ai", True), ("Entertainment", "ai", False)):
            self.assertEqual(people.has(text, word), hit, (text, word))
        acme = self.people_json("--company", "acme")
        self.assertEqual(acme["companies"], [["Acme Corp", 1]])
        hidden = self.people_json("--company", "hidden")                      # no URL: counted, shown without a link
        self.assertEqual((hidden["total"], hidden["without_profile_url"]), (1, 1))

    def test_people_exclude_company_list(self):
        customers = Path(self.tmp.name) / "customers.csv"
        customers.write_text("Company Domain\nacmecorp.com\numbrella.io\n")
        names = {p["name"] for p in self.people_json("--limit", "0", "--exclude-company-list", str(customers))["people"]}
        self.assertNotIn("Frank Ford", names)                                  # Umbrella
        self.assertIn("Bob Baker", names)
        sys.path.insert(0, str(CLI.parent))
        import people
        self.assertEqual(people.normalize_company("HubSpot, Inc."), people.normalize_company("hubspot.com"))

    # --- invitations ----------------------------------------------------------------------------------------------

    def test_invitations_profile_and_pending(self):
        prof = json.loads(self.run_cli("invitations-profile", "--json", "--as-of", AS_OF).stdout)
        self.assertEqual((prof["sent"], prof["sent_accepted"], prof["sent_not_accepted"]), (4, 1, 3))
        self.assertEqual((prof["received"], prof["received_not_connected"]), (1, 1))
        self.assertEqual(prof["with_note"], {"sent": 1, "accepted_pct": 0})
        pend = json.loads(self.run_cli("pending-invites", "--older-than", "90d", "--exclude-messaged", "--json",
                                       "--as-of", AS_OF).stdout)
        self.assertEqual([r["name"] for r in pend["top"]], ["Quinn Quiet"])   # Zoe skipped (DMed), Rita too new
        self.assertEqual(pend["skipped_messaged"], 1)

    # --- messages, activity, awaiting reply, CRM export, comparing exports -------------------------------------

    def test_search_messages_and_awaiting_reply(self):
        found = json.loads(self.run_cli("search-messages", "--query", "launch", "--json").stdout)
        self.assertEqual(found["total"], 1)
        self.assertEqual(found["messages"][0]["with"], "bob-baker-1a2b")      # FROM column of the fixture
        mine = json.loads(self.run_cli("search-messages", "--person", "alice", "--json").stdout)
        self.assertEqual([m["from"] for m in mine["messages"]], ["alice-able", "you"])
        owed = self.people_json("--awaiting-reply", "--limit", "0")
        self.assertEqual({p["name"] for p in owed["people"]}, {"Pete Pitch"})  # "Quick question about your stack"
        self.assertEqual(owed["hidden_finished_threads"], 3)   # Bob "Congrats on the launch", Alice "good to hear from you", Zoe
        self.assertEqual(owed["sort"], "last-dm")
        every = self.people_json("--awaiting-reply", "--include-closed", "--limit", "0")
        self.assertEqual({p["name"] for p in every["people"]}, {"Alice Able", "Bob Baker", "Pete Pitch", "zoe-zed"})
        self.assertEqual(every["not_connections"], 1)
        self.assertEqual(self.run_cli("search-messages", check=False).returncode, 2)

    def test_activity_says_what_the_export_cannot_show(self):
        act = json.loads(self.run_cli("activity", "--json").stdout)
        self.assertEqual((act["totals"]["posts"], act["totals"]["comments"]), (1, 6))
        self.assertIn("who reacted to your posts", act["not_in_export"])

    def test_crm_export(self):
        out = Path(self.tmp.name) / "crm.csv"
        res = json.loads(self.run_cli("people", "--export", str(out), "--crm", "--json").stdout)
        with out.open() as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(list(rows[0].keys())[:7], ["First Name", "Last Name", "Email", "Email Type", "Company",
                                                    "Job Title", "LinkedIn URL"])
        self.assertEqual(rows[0]["Email Type"], "work")
        self.assertEqual([r["Email"] for r in rows], ["alice@northwind.com"])  # default: only people with an email
        self.assertEqual(res["crm"], {"with_email": 1, "without_email": 9, "work_emails": 1, "personal_emails": 0,
                                      "no_email_no_url_dropped": 1, "exported": 1})
        self.run_cli("people", "--export", str(out), "--crm", "--all")
        with out.open() as fh:
            self.assertEqual(len(list(csv.DictReader(fh))), 10)                 # everyone with an email or a URL

    def test_compare_exports(self):
        t = Path(self.tmp.name)
        old = t / "older.zip"                        # no date in the name: the date comes from inside the ZIP
        build_zip(old, when=(2026, 1, 15, 9, 0, 0))
        newer = t / "newer.zip"
        global CONNECTIONS
        saved = CONNECTIONS
        try:
            CONNECTIONS = [c for c in saved if c[0] != "Bob"]                   # Bob is gone
            CONNECTIONS = [("Gina", "Gale", "gina-gale", "Globex", "Head of Product", "07 Jul 2019") if c[0] == "Gina"
                           else ("Carol", "Cole", "carol-cole", "Fabrikam, Inc. 🎨", "Designer", "12 Mar 2017") if c[0] == "Carol"
                           else c for c in CONNECTIONS]                           # Gina moved; Carol's company renamed only
            CONNECTIONS.append(("Yara", "Young", "yara-young", "Nimbus", "Founder", "20 Sep 2026"))
            build_zip(newer, when=(2026, 9, 23, 9, 0, 0))
        finally:
            CONNECTIONS = saved
        out = json.loads(self.run_cli("compare-exports", str(old), str(newer), "--json").stdout)
        self.assertEqual((out["new_connections"], out["no_longer_connected"], out["changed_company"]), (1, 1, 1))
        moved = out["changes"]["new company"][0]
        self.assertEqual((moved["name"], moved["company"], moved["before"]), ("Gina Gale", "Globex",
                                                                            "Product Manager @ Acme Corp"))
        self.assertEqual((out["older_date"], out["newer_date"], out["warning"]), ("2026-01-15", "2026-09-23", None))
        swapped = json.loads(self.run_cli("compare-exports", str(newer), str(old), "--json").stdout)
        self.assertIn("swap", swapped["warning"])
        pm = json.loads(self.run_cli("compare-exports", str(old), str(newer), "--title", "product manager",
                                     "--json").stdout)                          # matches Gina's previous title
        self.assertEqual((pm["changed_company"], pm["new_connections"]), (1, 0))

    def test_no_export_points_to_downloads(self):
        t = Path(self.tmp.name) / "home-test"
        downloads = t / "Downloads"
        downloads.mkdir(parents=True, exist_ok=True)
        build_zip(downloads / "Complete_LinkedInDataExport_09-08-2026.zip.zip")
        (downloads / "Basic_LinkedInDataExport_09-08-2026.zip").write_bytes(b"PK")
        empty = t / "exports"
        env = dict(os.environ, HOME=str(t), LINKEDIN_EXPORTS_DIR=str(empty), LINKEDIN_DB_PATH=str(t / "db.db"))
        p = subprocess.run([sys.executable, str(CLI), "stats"], env=env, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL)
        self.assertEqual(p.returncode, 3)                                     # "nothing loaded yet", not a crash
        lines = [l for l in p.stderr.splitlines() if "LinkedInDataExport" in l and "Downloads" in l]
        self.assertIn("Complete_", lines[0])                              # larger archive first
        self.assertIn("has no messages", lines[1])

    def test_crm_name_cleaning_and_started_by(self):
        import people
        self.assertEqual(people.clean_person_name("JANE DOE, MBA 🚀"), "Jane Doe")
        self.assertEqual(people.clean_person_name("  Prakriti   Rashi "), "Prakriti Rashi")
        self.assertEqual((people.email_type("a@gmail.com"), people.email_type("a@acme.io")), ("personal", "work"))
        started = {p["name"]: p["started_by"] for p in self.people_json("--messaged", "--limit", "0")["people"]}
        self.assertEqual(started["Alice Able"], "you")
        quiet = self.people_json("--quiet-since", "12m", "--limit", "0")
        self.assertEqual({p["name"] for p in quiet["people"]}, {"Bob Baker", "Pete Pitch"})   # last DM 2021 / 2024
        self.assertEqual(self.people_json("--they-started", "--limit", "0")["total"], 3)       # Bob, Pete, Zoe

    def test_overview(self):
        o = json.loads(self.run_cli("overview", "--json").stdout)
        by = {x["what"]: x["count"] for x in o["lines"]}
        self.assertEqual((by["connections"], o["emails"]), (11, 1))
        self.assertIn("stale_requests", by)
        self.assertEqual(o["export_date"], "2026-09-15")

    def test_inbound(self):
        r = json.loads(self.run_cli("inbound", "--since", "3m", "--json").stdout)
        self.assertEqual([q["name"] for q in r["requests"]], ["Ivan Ivanov"])       # 9/1, two weeks before export
        self.assertEqual(r["since_days"], 91)

    def test_parallel_first_load_is_safe(self):
        t = Path(self.tmp.name) / "parallel"
        exports = t / "exports"
        exports.mkdir(parents=True, exist_ok=True)
        build_zip(exports / "Complete_LinkedInDataExport_09-23-2026.zip")
        env = dict(os.environ, LINKEDIN_EXPORTS_DIR=str(exports), LINKEDIN_DB_PATH=str(t / "db.db"))
        procs = [subprocess.Popen([sys.executable, str(CLI), "stats"], env=env, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, stdin=subprocess.DEVNULL) for _ in range(4)]
        outs = [p.communicate() for p in procs]
        self.assertEqual([p.returncode for p in procs], [0, 0, 0, 0], [e for _, e in outs])
        self.assertTrue(all("Connections: 11" in o for o, _ in outs))
        loads = sum(e.count("Loading") for _, e in outs)
        self.assertEqual(loads, 1)                                            # one process built it, the rest waited

    def test_engagers_from_replies_on_own_posts(self):
        r = json.loads(self.run_cli("engagers", "--json").stdout)
        # Bob commented on someone else's post; Dave's name is decorated and his comment has escaped quotes.
        self.assertEqual({c["name"] for c in r["commenters"]}, {"Alice Able", "Carol Cole", "Dave Dunn"})
        self.assertEqual((r["replies_by_name"], r["posts"]), (3, 1))
        dave = next(c for c in r["commenters"] if c["name"] == "Dave Dunn")
        self.assertEqual(dave["warmth"], "group chat only")                  # talked in a group, never 1:1
        self.assertEqual((r["never_messaged"], r["group_chat_only"]), (0, 2))  # Carol and Dave: group chat c3 only
        self.assertEqual([e["name"] for e in r["endorsers"]], ["Gina Gale"])
        self.assertIn("reacted", r["caveat"])

    def test_backslash_escaped_comments_parse(self):
        con = sqlite3.connect(self.db)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM comments").fetchone()[0], 6)
        text = con.execute("SELECT Message FROM comments WHERE Message LIKE '%Dave Dunn%'").fetchone()[0]
        self.assertIn('"ship it", agreed', text)

    def test_job_search_and_past_companies(self):
        jobs = {p["name"] for p in self.people_json("--jobs", "--limit", "0")["people"]}
        self.assertEqual(jobs, {"Alice Able", "Carol Cole", "Erin East"})   # saved x2 (Fabrikam Inc. = Fabrikam), applied
        past = {p["name"] for p in self.people_json("--past-companies", "--limit", "0")["people"]}
        self.assertEqual(past, {"Dave Dunn"})                                # left Initech; Syftly is current
        out = self.run_cli("profile").stdout
        for bit in ("# Me Owner", "Founder at Syftly", "### Analyst, Initech", "Jan 2019 – Dec 2022", "Go-to-market"):
            self.assertIn(bit, out)

    def test_role_exclusions_only_where_they_overlap(self):
        import people
        self.assertEqual(people.role_match("VP Marketing & Revenue Operations", "marketing-leader"), "vp marketing")
        self.assertIsNone(people.role_match("Head of Marketing Operations", "marketing-leader"))
        self.assertIsNone(people.role_match("Fractional CMO", "marketing-leader"))        # one word: anywhere
        self.assertIsNone(people.role_match("Growth Engineering Lead", "marketing-leader"))
        self.assertEqual(people.role_match("Talent", "recruiter"), "talent")
        self.assertIsNone(people.role_match("Talent Development Manager", "recruiter"))
        self.assertIsNone(people.role_match("Marketing Cloud Consultant", "marketing"))

    def test_owed_reply_reading(self):
        import people
        self.assertEqual(people.ask_tag("Great to meet you! Loved the post."), "")
        self.assertEqual(people.ask_tag("Here's my link https://calendar.app.google/abc"), "meeting")
        self.assertEqual(people.ask_tag("I'm in town on the 14th, free?"), "meeting")
        self.assertEqual(people.ask_tag('He said "why?" and left'), "")
        closed = lambda t: people.looks_closed({"last_dm_text": t})
        self.assertTrue(closed("Thank you so much for the intro, really appreciate it and hope we can catch up at "
                               "some point later in the year when things calm down on our side."))
        self.assertTrue(closed("Congrats on the launch. Let me know if I can help with anything at all, I'm around "
                               "most of the month and happy to make intros where it makes sense."))
        self.assertFalse(closed("Thanks! Quick one though, would you be open to a call next week about pricing?"))
        p = {"in_count": 1, "out_count": 1, "dm_count": 2, "days_since_dm": 10}
        self.assertEqual(people.warmth_label(p), "new")
        self.assertEqual(people.warmth_label(dict(p, in_count=3, out_count=3, dm_count=6)), "hot")

    def test_company_aliases_and_similar_names(self):
        import people
        self.assertTrue(people.company_matches("Snap Inc.", ["snapchat"]))
        self.assertTrue(people.company_matches("Meta", ["facebook"]))
        self.assertFalse(people.company_matches("Snapdragon Labs", ["snapchat"]))
        self.assertEqual(people._similar_companies(["snapchat"], {"Snapdragon Labs": 4, "Other": 9}), [])
        self.assertEqual(people._similar_companies(["dropboxer"], {"Dropbox, Inc.": 3, "Drop Capital": 5}),
                         [("Dropbox, Inc.", 3)])
        self.assertEqual(people._similar_companies(["datadog"], {"Culminate (Acquired by Datadog)": 2}),
                         [("Culminate (Acquired by Datadog)", 2)])

    def test_owed_reply_keeps_answers_to_your_question(self):
        import people
        self.assertFalse(people.looks_closed({"last_dm_text": "Yes, about 40 reps.", "you_asked": True}))
        self.assertTrue(people.looks_closed({"last_dm_text": "Thanks!", "you_asked": True}))
        self.assertTrue(people.looks_closed({"last_dm_text": "Yes, about 40 reps.", "you_asked": False}))

    def test_offers_questions_and_sequences(self):
        import people
        self.assertFalse(people.looks_closed({"last_dm_text": "yessss and i still need orientating", "you_offered": True}))
        self.assertTrue(people._real_question("Would you be open to a quick call next week?"))
        self.assertFalse(people._real_question("did you see the game last night? 😂"))
        self.assertFalse(people._real_question("lol?"))
        self.assertTrue(people.looks_closed({"last_dm_text": "Thanks, I'm keeping my network small for now."}))
        seq = {"opened_by": "them", "title": "Founder", "company": "Acme", "out_count": 0, "in_count": 4,
               "opened_text": "Hi", "last_dm_text": "Following up"}
        self.assertTrue(people.likely_pitch(seq))                              # 4 unanswered in a row
        self.assertEqual(people.role_match("SVP of Sales", "sales-leader"), "svp sales")
        self.assertIsNone(people.role_match("Vice President of Product & Growth", "marketing-leader"))

    def test_final_pass_regressions(self):
        import people, engagers, search
        self.assertTrue(people.role_match("Head of Product Marketing", "marketing"))      # PMM hiring managers stay
        self.assertIsNone(people.role_match("Head of Product, Self-Serve Growth", "marketing"))
        self.assertEqual(people.role_match("Chief Commercial Officer", "sales-leader"), "chief commercial officer")
        self.assertIsNone(people.role_match("Partner, Head of Platform & GTM", "sales-leader"))
        self.assertIsNone(people.role_match("VP GTM Talent", "sales-leader"))
        self.assertEqual(engagers._leading_name("Ashmer A. Even the new ones?"), "Ashmer A.")
        self.assertEqual(engagers._leading_name("Kaley (Marston) Vilmont thanks for this"), "Kaley (Marston) Vilmont")
        self.assertEqual(engagers._leading_name("Oussama fair point"), "Oussama")
        self.assertEqual(engagers._leading_name("Interesting take here"), "")
        self.assertEqual(engagers._leading_name("Full episode link: https://youtu.be/x"), "")
        spec = search.TOPICS["pricing"]
        self.assertTrue(search._match("FE devs are 5-8k a month", spec["words"], spec["patterns"])[0])

    def test_skill_names_match_folders(self):
        for skill in (ROOT / "skills").glob("*/SKILL.md"):
            front = skill.read_text().split("---")[1]
            name = next(line.split(":", 1)[1].strip() for line in front.splitlines() if line.startswith("name:"))
            self.assertEqual(name, skill.parent.name)
        for f in ("outreach.md", "setup.md", "engagers.md"):   # files the syft router points to
            self.assertTrue((ROOT / "skills" / "syft" / f).is_file(), f)


if __name__ == "__main__":
    unittest.main()
