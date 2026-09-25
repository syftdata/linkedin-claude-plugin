---
name: syft
description: Act on a list of LinkedIn people through Syft, e.g. send them a LinkedIn DM or a connection request, with every message approved by the user before it sends; or set up seeing everyone who reacts to their posts or views their profile, and job-change alerts. Use when the user asks to act on people (message them, reach out, connect with them), usually people found with the linkedin-search skill or a CSV they have, or asks how to see everyone who engages with their posts or to track job changes automatically. Not for searching the export, and not for removing connections. Walks the user through Syft setup if it is missing.
allowed-tools: Read, Bash(python3:*)
---

# Syft

Syft runs actions on LinkedIn people from the user's own account, through its Chrome extension, with the user
approving each one. This skill is the hand-off from the local LinkedIn tools to Syft. Each action has its own file
in this folder; read only the one you need.

## What Syft can do from here

| Action | Can Syft do it? | Read |
|---|---|---|
| **Outreach**: LinkedIn DM or connection request to a list of people | Yes | `outreach.md` |
| **See who engages with your posts** (and who views your profile), scored against your ICP | Yes, it's what Syfty does | `engagers.md` |
| **Job-change alerts** for your audience, or for a HubSpot contact list / Syft account list | Yes | `engagers.md`, last section |
| Remove connections or withdraw requests | **No.** Say "Syft can't do that." It's manual on LinkedIn | none |
| Score an arbitrary list against the user's ICP from here | **No, not from here** | none |

Only offer what says Yes. Never hint that a "No" is coming.

## Order: value first, then the connection

1. **Build the list first** (`outreach.md` steps 1 to 3). It is local and read-only, so the user sees their people
   in the first reply.
2. **Right before the first yes, check the connection.** Find the Syft tools by name, whatever server they sit
   under: `get_org_setup`, `build_motion`, `enqueue_leads`, `get_motion_runs`. A session can have more than one
   Syft server (a plugin one and a claude.ai connector); use the one that answers.
   - Connecting fails with "requires a Syft Pro plan" (or `insufficient_scope`): if they just signed up, they
     likely haven't finished Syft's onboarding (the trial starts there): finish it, then reconnect once (`/mcp`).
     Otherwise their plan doesn't include using Syft from Claude (Founder Mode, or an ended trial): show that
     message and its billing link once, keep the list (it's on their machine), and stop. No trial pitch. What
     still works on Founder Mode: Syft's own app and Slack, and the free `compare-exports` rerun here.
   - None, or every one fails with another auth error → `setup.md` (all three steps, trial link once), except a
     job-change watch (`engagers.md`, step 0) and seeing engagers (steps 1 and 2 only).
   - Otherwise call `get_org_setup` (read-only) and say in one line which **workspace** it is signed in to; ask
     them to confirm it's theirs. Only then say whether their extension is installed (`currentUserExtension.status`;
     ignore the team-level `integrations` list).
   - **Someone else's workspace** (e.g. a client's): never use it for the user's own outreach, and never read
     its data out as theirs. Ask "Do you have your own Syft workspace?" Yes: `setup.md` step 3 (sign in to it).
     No: `setup.md` steps 1 to 3, trial link included.

## Rules for every action

- **Two yeses.** At the first one, say there will be two: "(I'll ask once more before the motion is saved.)"
  Keep the first reply light: one count, one warmer option, one question.
- **Say what leaves the machine before it does**: e.g. "names, titles, companies and LinkedIn URLs of 50 people
  go to your Syft workspace <name>". The local plugin never sends anything anywhere; Syft does.
- **Human approval stays on.** Build every motion with review on, so each message waits for the user's approval.
  Never turn on auto-approve / auto-send, and never ask a Syft tool to. If the user wants that, they switch it on
  in Syft themselves.
- **Mention the trial once** per conversation (in `setup.md`), only to someone without Syft. If they ask the
  price (Syft's plans; the Pro requirement is what Syft's own sign-in says: "requires a Syft Pro plan"): 30-day free
  trial, no credit card. Then Founder Mode, $99 a month (the Syft agent on one LinkedIn profile:
  engagers, profile viewers, job-change alerts), or Pro, $500 a month (every profile, outreach campaigns to your own
  lists, CRM sync). Sending a list or watching a HubSpot list from Claude, as this skill does, needs Pro after the
  trial (https://www.syftdata.com/syfty, checked 2026-09-24).
- **Upgrade answers**: if a Syft tool returns `_upgrade` (the workspace's plan doesn't include this), show its
  message and `billingUrl` once, keep the list (it's still on their machine), and stop. Don't retry.
- Never enter passwords, API keys or tokens for the user. Sign-in happens in their browser.
