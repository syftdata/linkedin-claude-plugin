---
name: linkedin-cleanup
description: Guided LinkedIn cleanup from the user's export. Two problems it solves - hitting LinkedIn's invitation limit (lists the connection requests you sent that were never accepted, oldest first, to withdraw) and pruning connections (groups with real counts, e.g. connected 5+ years ago and never messaged, near the 30,000 cap). Asks before building anything, protects people you talk to and customer lists, writes a CSV. Never removes or withdraws anyone. Use when the user wants to clean up their network, withdraw pending invitations, fix "you've reached the invitation limit", find people they never talk to, or make room under the connection cap.
allowed-tools: Read, Bash(python3:*)
---

# LinkedIn cleanup

Builds **lists** the user works through on LinkedIn: requests to withdraw, connections to consider removing.
**Never removes or withdraws anyone**, and nothing here (nor Syft) can: it is manual on LinkedIn.

```bash
L=${CLAUDE_PLUGIN_ROOT}/skills/linkedin/linkedin.py
```

No export loaded yet: any command lists LinkedIn ZIPs found in `~/Downloads`; ask "Use <file>?" and run
`python3 $L ingest --zip <path>`. It must be the **larger data archive** (`Complete_...`); the small one has no
messages or requests, so every connection would look "never messaged".

## Step 1, find the actual problem (one command each, then 3 lines to the user)

```bash
python3 $L network-profile --json        # connections, headroom under 30,000, who you never talk to
python3 $L invitations-profile --json    # requests sent / accepted / never accepted, pace per week
```

- **"Invitation limit" / requests blocked / pending invites** → it's about **requests**, not connections. If the
  last-8-weeks average is under ~100 a week, pace isn't the likely cause: lead with the pile (`sent_not_accepted`,
  how many are 90+ and 180+ days old) and mention the busiest week in passing. If it's higher, lead with pace. As
  of `export_date`. Go to **Pending requests** below.
- **Near the cap** (headroom under ~3,000) or they ask to prune → go to **Prune connections**.
- **Far from the cap and no request problem**: say so plainly ("you're at 4,700 of 30,000; the cap isn't your
  problem") and ask whether they still want to prune. Don't push a menu.

State the export's limits once, in a line, where they matter: request history is only complete from the month
`invitations-profile` names (`window.covered_from`); "not accepted" can also mean withdrawn or accepted then removed;
counts and ages are as of the export date (say it: "as of your Sep 7 export"), not today.

## Pending requests (withdraw)

**What fixes an invitation limit, in order** (sources: LinkedIn Help a551012, a568295, a550555):
1. **Pace.** LinkedIn limits requests per week and doesn't publish the number (third parties cite roughly 100 to
   200); a restriction usually lifts in about a week. Compare with their own busiest week and 8-week average.
2. **Withdraw old ones.** Many ignored or pending requests can also trigger restrictions. Withdrawing doesn't
   notify the person, but you **can't re-invite them for up to 3 weeks**: so withdraw the oldest, not recent ones.
3. **Notes** don't change the limit. Free accounts can only add a note to 5 requests a month.

```bash
python3 $L pending-invites --older-than 90d --exclude-messaged               # count + oldest 10, writes nothing
python3 $L pending-invites --older-than 180d --exclude-messaged --export ~/Desktop/withdraw-first.csv
```

- Size the job to the pile: the whole 90+ day group, oldest first, is the task (say "about N clicks"; the oldest
  are at the bottom of LinkedIn → My Network → Manage → **Sent**, so the user works up from the bottom and **skips
  only the people listed under "Skip these"**). If N is large, the first sitting is the 180+ day group (say its
  count), the rest another day; the CSV is optional.
- **Protect people**: `--exclude-messaged` (anyone they've DMed) and `--keep-list contacts.csv` for customers or
  deals. Requests carry **no company** in the export, so the keep list must be a **contacts** export with LinkedIn
  URLs or first / last names (HubSpot → Contacts → Export), not a list of companies or domains. Ask for that file
  directly.
- `--direction received --with-note`: requests **they** sent that the user never accepted, the ones with a note
  first (people who asked for something), newest first. The export has no title or company for them.
- "Do notes help?": read `with_note` / `without_note` **and** `note_vs_no_note_by_month` (same months side by side);
  rates only count requests 30+ days old. Say what their own data shows, with the sample sizes.
- Going forward (if they ask how to avoid it, or say they "keep" hitting it): fewer requests, to people more likely
  to accept (people who engaged with their posts, people at their target companies). If they'd rather not pace it
  by hand: the **syft** skill sends requests from their own LinkedIn under a daily cap they set, to people they
  pick, and they approve each one. Offer once.

## Prune connections

**Do not pick the group for the user.** Offer the `presets` from `network-profile`, each with its count (only
presets with people appear), plus custom. AskUserQuestion takes at most 4 options: show the 4 most useful and say
the rest can be typed under "Other".

| Preset | Means |
|---|---|
| `old-never-messaged` | Connected 5+ years ago and never messaged 1:1 |
| `old-quiet` | Connected 2+ years ago and no DM in the last 3 years (or never) |
| `never-messaged` | Never messaged 1:1, any connection age |
| `never-replied` | They messaged you 1:1 and you never wrote back, usually a pitch |
| `recent-never-messaged` | Connected in the last 12 months and never messaged (accepted, never followed up) |
| custom | `--connected-before 5y`, `--connected-after 12m`, `--no-dm-since 3y`, `--never-messaged` |

Group chats do not count as talking unless the user says so (`--count-group-as-dm`).

Then ask, each skippable:
- **How many to free up?** → `--limit N` (oldest and quietest first). Near the cap, suggest the number that gets
  them back under it with room.
- **Who to always keep?** Company names → `--keep-company "Acme"`; title words → `--keep-title founder`;
  **customers or partners from a CRM export** → `--keep-company-list customers.csv` (company names or domains).
  To focus on one kind of person instead: `--only-title recruiter`.

Dry run, read the `definition` and `count` back in one line, then build on yes:

```bash
python3 $L cleanup-candidates --preset old-never-messaged --keep-company-list customers.csv --limit 1500 --dry-run --json
python3 $L cleanup-candidates --preset old-never-messaged --keep-company-list customers.csv --limit 1500 --export ~/Desktop/prune.csv
```

Show the top 5 and the file path; the count must match the dry run. Columns: `name, company, title, profile_url,
connected_on, last_dm_at, last_dm_preview, days_since_connect, days_since_dm, cleanup_score, reasons`.
`--with-preview` adds the last message text only if the user asks.

## Rules

- Never remove, withdraw, message or act on anyone. The deliverable is a CSV.
- Syft can't remove connections or withdraw requests either; never offer it for that. The one exception is
  above: pacing new, targeted requests, if the user asks.
- Never invent a group the data does not support; if a preset has 0 people it is not offered.
- Say what the data cannot see: who is a customer (unless they give a list), anything after the export date,
  connections with an unreadable `Connected On` (left out of age-based groups).
