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


def build_zip(path):
    with zipfile.ZipFile(path, "w") as z:
        base = "Complete_LinkedInDataExport_09-23-2026/"
        buf = io.StringIO()
        buf.write("Notes:\n")
        buf.write('"When exporting your connection data, you may notice that some of the email addresses are missing."\n')
        buf.write("\n")
        w = csv.writer(buf)
        w.writerow(["First Name", "Last Name", "URL", "Email Address", "Company", "Position", "Connected On"])
        for f, l, s, c, p, d in CONNECTIONS:
            w.writerow([f, l, url(s) if s else "", "", c, p, d])
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
        z.writestr(base + "Invitations.csv", buf.getvalue())

        z.writestr(base + "Shares.csv", "Date,ShareLink,ShareCommentary,SharedUrl,MediaUrl,Visibility\n"
                                        "2026-05-01 10:00:00,https://lnkd.in/p1,Thoughts on AI in GTM,,,MEMBER_NETWORK\n")
        z.writestr(base + "Comments.csv", "Date,Link,Message,Comment\n2026-05-02 10:00:00,https://lnkd.in/c1,,Great AI post\n")


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
        meta = json.loads(self.run_cli("ingest").stdout)
        self.assertEqual(meta["schema_version"], "2")
        self.assertEqual(meta["connections"], "11")
        self.assertEqual(meta["messages"], "6")          # guide_messages.csv was not mistaken for it
        self.assertEqual(meta["invitations"], "1")
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
        everyone = self.syft_leads("--keywords", "a")["total"]
        first = self.syft_leads("--keywords", "a", "--limit", "2")
        rest = self.syft_leads("--keywords", "a", "--offset", "2")
        self.assertEqual((first["count"], first["total"]), (2, everyone))
        self.assertEqual(first["count"] + rest["count"], everyone)
        self.assertFalse({x["linkedin"] for x in first["leads"]} & {x["linkedin"] for x in rest["leads"]})
        p = self.run_cli("syft-leads", check=False)
        self.assertEqual(p.returncode, 2)
        self.assertIn("--csv", p.stderr)

    def test_skill_names_match_folders(self):
        for skill in (ROOT / "skills").glob("*/SKILL.md"):
            front = skill.read_text().split("---")[1]
            name = next(line.split(":", 1)[1].strip() for line in front.splitlines() if line.startswith("name:"))
            self.assertEqual(name, skill.parent.name)
        for f in ("outreach.md", "setup.md"):                  # files the syft router points to
            self.assertTrue((ROOT / "skills" / "syft" / f).is_file(), f)


if __name__ == "__main__":
    unittest.main()
