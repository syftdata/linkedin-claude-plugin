# LinkedIn for Claude: ask your own LinkedIn data anything

Download your LinkedIn data export, install this plugin, and ask Claude in plain English:

- **"Who do I know at these 20 companies, and who should I ask for an intro?"** Warm paths, ranked by how recently
  and how much you actually talk.
- **"What's in my LinkedIn?"** A first look: replies you owe, close contacts you lost touch with, stale requests.
- **"Who did I forget to reply to?"** People waiting on you, the ones asking for something first; finished threads
  (a thanks, an emoji) left out.
- **"Who should I reconnect with?"** People you talked with a lot who went quiet over a year ago.
- **"Who came to me this month?"** Requests you haven't accepted (with their notes), new people who messaged first.
- **"Who engages with my posts?"** People who commented and got a reply from you, the ones you've never DMed first.
- **"LinkedIn keeps blocking my connection requests."** Your sending pace, acceptance rate, and an oldest-first list
  of requests nobody accepted, to withdraw.
- **"Recruiters and marketing leaders in my network, warmest first, as a spreadsheet."**
- **"Who do I know at the companies I applied to? Who's still at my old companies?"** From your own saved jobs,
  applications and past positions in the export. Plus your profile as a Markdown resume.
- **"Who changed jobs since my last export? Who removed me?"**
- **"What did I say about pricing, and to whom?"** Search your own DMs, posts and comments.
- **"Get my network into HubSpot."** A CRM-ready CSV (emails only for people who chose to share theirs, often few).
- **"I'm near the 30,000 cap. Who can I let go?"** Guided, with real counts, protecting people you talk to and your
  customers.

It runs on your machine: your export goes into a local SQLite file, nothing is uploaded to any server and nothing
logs in to LinkedIn. Claude sees the rows it reads to answer you, as with any file you open with it. Nothing is ever
sent, withdrawn or removed on LinkedIn by this plugin.

## Skills

| Skill | Use it for |
|---|---|
| `linkedin-search` | Your network by role / title / company, ranked by warmth; messages you owe a reply; search your DMs, posts and comments; compare two exports; spreadsheet and CRM exports |
| `linkedin-cleanup` | Invitation limits (pace, acceptance, requests to withdraw) and pruning connections near the 30,000 cap. Builds lists; never removes anyone |
| `syft` | When you want to act on a list (DM or connect with 10+ people): hands it to [Syft](https://www.syftdata.com/syfty), opt-in, with your approval on every message |

## Setup (5 minutes, plus LinkedIn's wait)

1. **Get your export.** [LinkedIn → Settings → Data privacy → Get a copy of your data](https://www.linkedin.com/mypreferences/d/download-my-data)
   → **Download larger data archive** (the smaller one has no messages). LinkedIn emails a link, usually within 24
   hours; it expires after 72 hours.
2. **Install the plugin** in Claude Code:
   ```bash
   /plugin marketplace add syftdata/linkedin-claude-plugin
   /plugin install linkedin@linkedin
   ```
3. **Ask Claude.** On first use it finds the ZIP in `~/Downloads` and asks before loading it. Or yourself:
   ```bash
   python3 skills/linkedin/linkedin.py ingest --zip ~/Downloads/Complete_LinkedInDataExport_09-23-2026.zip
   ```

Keep each export you download: two of them let you see who changed jobs and who is no longer connected.

## What's in the export, and what isn't

| In the export | Not in the export |
|---|---|
| Your connections: name, current title and company, profile URL, date connected; email only if they allow it (most don't) | Their industry, company size, location, or past employers |
| Every DM you sent and received, with timestamps | Who reacted to **your** posts; commenters you never replied to |
| Connection requests sent and received, about the last 12 months, accepted ones included | Post impressions, profile views |
| Your own posts, comments and reactions (so: who you replied to under your posts) | People you're not connected to |

When a question needs something from the right column, the skills say so instead of guessing. (Syft covers some of
it, e.g. who engages with your posts; the plugin mentions that only when you ask.)

## The CLI (what the skills run)

```bash
L=skills/linkedin/linkedin.py
python3 $L info                                                   # what's loaded, export date
python3 $L overview                                               # a first look, with questions to ask next
python3 $L inbound --since 30d                                    # who came to you: owed replies, requests, new DMs
python3 $L engagers --since 90d                                   # who commented on your posts (and got a reply)
python3 $L people --jobs --by-company                             # who you know where you saved / applied to jobs
python3 $L people --past-companies                                # people at companies you used to work at
python3 $L profile --export ~/Desktop/resume.md                   # your profile as Markdown
python3 $L people --dormant                                       # reconnect: close once, quiet a year+
python3 $L people --role recruiter --role marketing-leader --messaged --limit 10
python3 $L people --company-list targets.csv --sort warm --export ~/Desktop/warm-paths.csv
python3 $L people --awaiting-reply --dm-since 6m --last-message   # they wrote last, real conversations first
python3 $L people --has-email --export ~/Desktop/crm.csv --crm    # CRM import columns
python3 $L search-messages --person jordan --topic pricing       # finds "$3k/year" too, with context
python3 $L topics --since 6m                                      # what your posts are about
python3 $L search-shares --query positioning --query "product marketing"
python3 $L activity                                               # posts / comments / reactions per month
python3 $L compare-exports ~/Downloads/last-year.zip              # job changes, new, no longer connected
python3 $L invitations-profile                                    # pace, acceptance, note vs no note
python3 $L pending-invites --older-than 180d --exclude-messaged --keep-list hubspot-contacts.csv
python3 $L network-profile                                        # cap headroom, who you never talk to
python3 $L cleanup-candidates --preset old-never-messaged --keep-company-list customers.csv --limit 1500 --dry-run
```

`people` filters: `--role` (recruiter, marketing-leader, marketing, product-marketing, sales-leader, sales-manager,
revops, founder, executive, investor, engineering-leader, people-hr), `--title` / `--company` (repeatable, any of them; several words match in
any order), `--keywords` (all of them), `--messaged` (you wrote), `--two-way`, `--never-messaged`, `--dm-since`,
`--awaiting-reply`, `--has-email`, `--connected-since` / `--connected-before`, `--company-list` /
`--exclude-company-list` (CSV of names or domains). Sorts: `warm` (recent two-way conversations first), `recent`,
`talked`, `last-dm`, `name`.

## Acting on a list with Syft (optional)

The `syft` skill is the only part that sends anything anywhere, and only when you ask it to act. It builds your list
locally first, tells you exactly what goes to your Syft workspace, and asks twice: before the list leaves your
machine, and before the motion is saved. Every message then waits for your approval in Syft.

| With Syft | |
|---|---|
| DM or connection request to a list, paced from your own LinkedIn | Yes |
| Remove connections or withdraw requests | No (manual on LinkedIn) |

Setup, if you don't have Syft: 30-day free trial, no credit card. Acting on lists from Claude uses outreach
campaigns, which are on Syft Pro ($500 a month) after the trial; Founder Mode ($99) is the Syft agent on one
LinkedIn profile
([sign up](https://app.syftdata.com/auth/syft-signup?product=rolodex&source=linkedin-rolodex&utm_source=claude-plugin&utm_medium=linkedin&utm_campaign=readme); plans at [syftdata.com/syfty](https://www.syftdata.com/syfty)),
the [Syft Chrome extension](https://chromewebstore.google.com/detail/syft-extension/nchnjpdedckhhfkoafckloolnfliocnd),
then `claude mcp add --transport http syft https://app.syftdata.com/api/mcp` and sign in.

## Notes and limits

- LinkedIn's rules the cleanup skill uses, with sources in its SKILL.md: 30,000 connections max; weekly request
  limits aren't published; withdrawn requests can't be re-sent for up to 3 weeks; free accounts get 5 request
  notes a month.
- Current exports name some files `Shares_<id>.csv`, `Comments_<id>.csv` (with a `Message` column); both old and new
  names load.
- Some connections come without a profile URL; they are counted but can't be linked or messaged.
- Paths: `~/.linkedin-exports/` (watch folder), `~/.linkedin-search/data.db`; override with `LINKEDIN_EXPORTS_DIR`,
  `LINKEDIN_DB_PATH`.

## Upgrading from linkedin-search (v1)

`skills/linkedin-search/linkedin_search.py` still forwards every v1 command; the database path and watch folder did
not move; the database is rebuilt automatically. Standard library only, no virtualenv.

## MCP

The same tools are specified for an MCP server: [docs/mcp.md](docs/mcp.md), `skills/linkedin/mcp_tools.py`.

## Development

```bash
python3 -m unittest discover -s tests -v
```

Tests build a synthetic export in LinkedIn's file format (including the current suffixed file names); no real data
needed.

## License

MIT
