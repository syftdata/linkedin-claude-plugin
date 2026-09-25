# Outreach: DM or connect with a list of LinkedIn people

```bash
L=${CLAUDE_PLUGIN_ROOT}/skills/linkedin/linkedin.py
```

## 1. Get the list

`syft-leads` turns people into the lead objects `enqueue_leads` takes. It sends nothing.

```bash
python3 $L syft-leads --keywords founder gtm --limit 5          # your connections, every keyword in title + company
python3 $L syft-leads --title "head of marketing" --limit 5      # your connections by title and/or --company
python3 $L syft-leads --csv ~/path/list.csv --limit 5            # any CSV with a LinkedIn URL column
```

Read `total`, `skipped_no_url` and `duplicates_removed`, and show the user the count plus 5 sample names with
title and company. People with no readable LinkedIn profile URL are skipped, never guessed. Let them narrow it
before going on ("only the ones at seed-stage companies" means a different search or an edited CSV, not your guess).

A cleanup CSV lists people the user is thinking of removing. Do not suggest messaging them; only do it if they ask.

## 2. Pick the action

- **DM**: LinkedIn only lets you message 1st-degree connections. A list from the user's own connections → DM.
- **Connection request**: for people they are not connected to (a Sales Navigator or other CSV). A note is
  optional; a blank request is fine.

If the list mixes both, ask. Do not assume.

## 3. The message

Ask for the copy, or the goal and tone so you can draft it for them. Syft's LinkedIn agent writes each message
from the motion's instructions, so:
- If the text must go out word for word, say so in the motion prompt: "send this message exactly as written".
- Syft's agent avoids some words in generated messages (e.g. "agent"); if a word must survive, name it in the
  prompt, and check the first drafts at approval.
- Personalisation fields: first name is always available; title and company come from the list.

## 4. Confirm what leaves the machine

One line, then wait for yes: "This sends the names, titles, companies and LinkedIn URLs of N people to your Syft
workspace, and creates a motion there. Messages only go out after you approve each one. OK?"

## 5. Build the motion (`build_motion`)

First call, a prompt like:

> Create a motion triggered by uploaded leads that sends a LinkedIn DM [or: connection request] from my LinkedIn
> account. Message: "...". Human review on: every message waits for my approval. Name it
> "<Audience> -> DM" [or "-> Connect"].

Name it the way Syft users do: `<Audience> -> <Action>`, e.g. `Founders in my network -> DM`.

Then follow the tool's session: pass `sessionId` on every call.
- `needs_input` → ask the user the pending questions (usually which LinkedIn sender), pass their answers.
- `needs_integration` → tell them what to connect (usually the Chrome extension, see `setup.md`), then continue.
- `motion_ready` → show them the trigger, action, message and review setting. On yes, call again with
  `save it`.
- `saved` → note `savedMotionId` and `motionUrl`.

Never ask it to skip review or turn on auto-approve.

## 6. Check it is on

`enqueue_leads` needs a live motion. Call `get_org_setup` and find the motion by id. If it is a draft or
disabled, send the user the `motionUrl` to review and switch it on, and wait for them.

## 7. Add the people (`enqueue_leads`)

In chunks of 100, in order:

```bash
python3 $L syft-leads --keywords founder gtm --offset 0 --limit 100
python3 $L syft-leads --keywords founder gtm --offset 100 --limit 100    # and so on, until offset >= total
```

Pass each chunk's `leads` array as-is with the `motionId`. Add up `leadsEnqueued` and `duplicatesSkipped`
and report the totals against `total`. If a call errors, stop and show the error; do not retry blindly.

## 8. Where to approve

Tell them: Syft prepares a message per person; nothing is sent until they approve it on the motion page
(`motionUrl`) or on the approval cards in Slack if the motion posts there. Syft paces sends through their Chrome
extension, so a big list goes out over days. To check progress later: `get_motion_runs` with the motion id (runs
waiting for approval, sent, replied).
