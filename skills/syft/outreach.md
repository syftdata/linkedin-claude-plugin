# Outreach: DM or connect with a list of LinkedIn people

```bash
L=${CLAUDE_PLUGIN_ROOT}/skills/linkedin/linkedin.py
```

## 1. Get the list

`syft-leads` turns people into the lead objects `enqueue_leads` takes. It sends nothing.

```bash
python3 $L syft-leads --role founder --max 30 --limit 5                     # your connections by role / title / company
python3 $L syft-leads --role founder --two-way --dm-since 12m --max 30 --limit 5   # warm: talked both ways this year
python3 $L syft-leads --csv ~/path/list.csv --max 30 --limit 5              # any CSV with a LinkedIn URL column
```

- Same filters as the `people` command (see the linkedin-search skill): `--role`, `--title` / `--company`
  (repeatable, ANY), `--two-way`, `--messaged` (you wrote to them), `--dm-since 12m`,
  `--exclude-company-list customers.csv`. Always pass `--max N` with the number the user wants, from the start.
- **"People who'd actually care"**: the warmest proxy the data has is people who have **written back**:
  `--two-way`, plus `--dm-since 12m` for "this year". `--messaged` alone includes people who never replied.
  Offer the warm option; don't guess interest from titles.
- **Order:** with a message filter the list is warmest first (recent two-way conversations); otherwise most
  recently connected first; a CSV keeps its own order. Say which.
- Read `total` (≤ N), `matched`, `skipped_no_url`, `duplicates_removed` and `odd_first_names` (covers the whole
  list, not only the 5 shown). Show the count and 5 names with title and company.
- **Before the first yes, check the titles of all N** (`--out /tmp/list.json`, or `people ... --export`) and name
  any that don't fit ("#12 is a coach 'to founders', drop them?"). Offer the full list as a file in one line so
  the user can see everyone they are approving.
- Let the user narrow it. Narrowing is a search the data supports (title, company, a keyword) or an edited CSV,
  never your guess about who fits (you cannot tell a software company from an agency by its name).

A cleanup CSV lists people the user is thinking of removing. Do not suggest messaging them; only if they ask.

## 2. Pick the action

- **DM**: LinkedIn only lets you message 1st-degree connections. A list from the user's own connections → DM.
- **Connection request**: for people they are not connected to (a Sales Navigator or other CSV). A note is
  optional; a blank request is fine.

If the list mixes both, ask. Do not assume.

## 3. The message

Ask for the copy, or the goal and tone so you can draft it. Syft's LinkedIn agent writes each message from the
motion's instructions, so:
- **Word for word**: put the copy in quotes in the motion prompt and say "send this exactly as written, only
  replacing {first} with the lead's first name". There is no template syntax; say it in words like that.
- **First names**: if `odd_first_names` is not empty, show those (e.g. "🚀 Neal" → "Neal") and ask whether to use
  the suggested names; on yes, add `--clean-names` to every later `syft-leads` call.
- Syft's agent avoids some words in generated messages (e.g. "agent"); if a word must survive, name it in the
  prompt, and check the first drafts at approval.
- If the copy claims something about each person ("you post regularly"), say you cannot check that from the
  export, once, and let the user decide.
- **Placeholders**: if the copy has a token that looks unfinished ("X", "[name]", "TBD", "<product>"), ask once
  before building ("'launched X': is X your product's name?").

## 4. First yes: what leaves the machine

Check the connection and workspace first (`SKILL.md`, "Order"). Settle odd first names now (step 3), not later.
Then:

"This sends the names, titles, companies and LinkedIn URLs of N people to your Syft workspace <name>, and creates
a motion there. Messages only go out after you approve each one. OK? (I'll ask once more before the motion is
saved.)" Wait for yes.

## 5. Build the motion (`build_motion`)

Arguments: `prompt` (the request, in words), `sessionId` (from the first reply, on every later call),
`userInput` (answers to its pending questions, keyed by question id), `motionId` (only when editing).

First call, a prompt like:

> Create a motion triggered by uploaded leads that sends a LinkedIn DM [or: connection request] from my LinkedIn
> account. Send this message exactly as written, only replacing {first} with the lead's first name: "...".
> Human review on: every message waits for my approval. Name it "<Audience> -> DM" [or "-> Connect"].

Name it the way Syft users do: `<Audience> -> <Action>`, e.g. `Founders in my network -> DM`.

Then follow the session:
- `needs_input` → ask the user the pending questions (usually which LinkedIn sender), pass their answers.
- `needs_integration` → tell them what to connect (usually the Chrome extension, see `setup.md`), then continue.
- `motion_ready` → **second yes**: show the trigger, action, message and review setting. On yes, `save it`.
- `saved` → note `savedMotionId` and `motionUrl`.

Never ask it to skip review or turn on auto-approve.

## 6. Check it is on

`enqueue_leads` needs a live motion. Call `get_org_setup` and find the motion by id. If it is a draft or
disabled, send the user the `motionUrl` to review and switch it on, and wait for them.

## 7. Add the people (`enqueue_leads`)

Use the exact flags from step 1 plus `--max N`, where N is the number the user said yes to, so the list can never
grow past it. Page through it in chunks of 100:

```bash
python3 $L syft-leads --title founder --max 30 --offset 0 --limit 100
python3 $L syft-leads --title founder --max 30 --offset 100 --limit 100   # only if total > 100
```

`total` must equal N (or less, if fewer matched). Pass each chunk's `leads` array as-is with the `motionId`, add up
`leadsEnqueued` and `duplicatesSkipped`, and report them against N. If a call errors, stop and show the error; do
not retry blindly.

## 8. Where to approve

Tell them: Syft prepares a message per person; nothing is sent until they approve it on the motion page
(`motionUrl`) or on the approval cards in Slack if the motion posts there. Check the first few drafts: name,
wording, links. Syft paces sends through their Chrome extension, so a big list goes out over days. To check
progress later: `get_motion_runs` with the motion id (waiting for approval, sent, replied).
