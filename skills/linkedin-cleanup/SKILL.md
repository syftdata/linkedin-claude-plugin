---
name: linkedin-cleanup
description: Guided LinkedIn network cleanup. Profiles the user's connections from their LinkedIn export, offers cleanup groups with real counts (e.g. connected 5+ years ago and never messaged), asks which group, how many to free and who to always keep, then writes a ranked CSV of candidates to remove. Never removes anyone. Use when the user wants to prune connections, clean up their network, find people they never talk to, or make room under LinkedIn's 30,000 connection cap.
allowed-tools: Read, Bash(python3:*)
---

# LinkedIn network cleanup (pass 1)

Builds a **candidate list** of connections the user might remove, from their LinkedIn export. **Never removes
anyone.** Removal is manual on LinkedIn, and cannot be undone without a new request they accept.

**Inputs: `Connections.csv` joined to `messages.csv` only.** Connections.csv is who they are connected to (the list
being thinned); messages.csv gives the last DM per person. `Invitations.csv` is requests history and is never a
cleanup input.

**Do not pick the group for the user.** Always profile first, offer options with their counts, and ask.

```bash
L=${CLAUDE_PLUGIN_ROOT}/skills/linkedin/linkedin.py
```

## Step 0, load the export

If there is no export yet: `python3 $L ingest --zip /path/to/export.zip`. It must be the **larger data archive**.
If `network-profile` reports `messages.loaded: false`, stop and tell the user: without `messages.csv` every
connection looks "never messaged".

## Step 1, profile

```bash
python3 $L network-profile --json
```

Tell the user, in three or four lines: total connections and headroom under 30,000, how many were connected 5+
years ago, how many they have never messaged, and the date range of the messages loaded. If
`connections_without_url` is above 0, say that many connections have no profile URL in the export and can't be
listed (LinkedIn blanks it for some members).

## Step 2, ask which group

Offer the `presets` from the profile, **each with its count**, plus a custom option. Only presets with people in
them appear. Use AskUserQuestion when available: it takes at most 4 options, so show the 4 most useful presets for
this user and say in the question that the others and custom thresholds can be typed under "Other". Otherwise use
numbered options.

| Preset | Means |
|---|---|
| `old-never-messaged` | Connected 5+ years ago and never messaged 1:1 |
| `old-quiet` | Connected 2+ years ago and no DM in the last 3 years (or never) |
| `never-messaged` | Never messaged 1:1, any connection age |
| `never-replied` | They messaged you 1:1 and you never wrote back, usually a pitch |
| `recent-never-messaged` | Connected in the last 12 months and never messaged (accepted, never followed up) |
| custom | Their own thresholds: `--connected-before 5y`, `--connected-after 12m`, `--no-dm-since 3y`, `--never-messaged` |

Group chats do not count as talking by default. If the user says they do, add `--count-group-as-dm`.

## Step 3, narrow and protect

Ask both, each skippable:
- **"How many do you want to free up?"** A number becomes `--limit N` (the highest-scoring, oldest and quietest, first).
  If they are near the cap, suggest the number that gets them back under it with some room.
- **"Anyone to always keep?"** Company names → `--keep-company "Acme"` (repeatable); title words →
  `--keep-title founder --keep-title investor`. To focus on a kind of person instead: `--only-title recruiter`.
  These match the `Company` / `Position` text in Connections.csv. They are keyword filters, not ICP matching.

## Step 4, confirm and build

Dry run first and read the `definition` and `count` back in one line, e.g.
"1,240 people: connected 5+ years ago, never messaged 1:1, keeping companies containing 'acme'. Build it?"

```bash
python3 $L cleanup-candidates --preset old-never-messaged --keep-company "Acme" --limit 1500 --dry-run --json
```

On yes, the same command without `--dry-run` (optionally `--export /path/out.csv`, default
`~/.linkedin-exports/cleanup/<date>-<preset>.csv`). Show the top 10 rows and the file path. The count must match
the dry run. Add `--with-preview` only if the user wants the last message text in the file.

Columns: `name, company, title, profile_url, connected_on, last_dm_at, last_dm_preview, days_since_connect,
days_since_dm, cleanup_score, reasons`. `cleanup_score` (0 to 100) is for ordering only.

## Step 5, offer pass 2

Say: "Pass 2 uses ICP / persona (Syft / Rolodex) and is not run in pass 1." Offer it as the next step. Do not
guess ICP or persona matches yourself, and do not pass `--icp` / `--persona` expecting results: they are
placeholders and exit with a message.

## Rules

- Never remove, message or act on anyone. The deliverable is the CSV.
- Syft cannot remove connections yet, so do not offer the syft skill for this list. Removal stays manual on LinkedIn.
- Never invent a group the data does not support; if a preset has 0 people it is not offered.
- Say what the data cannot see: connections with an unreadable `Connected On` are left out of age-based groups;
  "never messaged" only covers the messages in this export.
