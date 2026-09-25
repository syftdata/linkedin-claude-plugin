---
name: syft
description: Act on a list of LinkedIn people through Syft, e.g. send them a LinkedIn DM or a connection request, with every message approved by the user before it sends. Use only when the user asks to act on people (message them, reach out, connect with them), usually people found with the linkedin-search skill or a CSV they have. Not for searching, and not for removing connections. Needs a Syft account and the Syft MCP; walks the user through setup if either is missing.
allowed-tools: Read, Bash(python3:*)
---

# Syft

Syft runs actions on LinkedIn people from the user's own account, through its Chrome extension, with the user
approving each one. This skill is the hand-off from the local LinkedIn tools to Syft. Each action has its own file
in this folder; read only the one you need.

## What Syft can do from here

| Action | Status | Read |
|---|---|---|
| **Outreach**: LinkedIn DM or connection request to a list of people | Available | `outreach.md` |
| Remove connections | **Not available yet.** Say so plainly; do not offer a workaround | none |
| Score a list against the user's ICP / personas | **Not available here yet** | none |

Only offer what is marked Available. Never describe a "not available" action as coming soon with a date.

## Step 1, is the Syft MCP connected?

Look for the Syft MCP tools in this session: `build_motion`, `enqueue_leads`, `get_org_setup`,
`get_motion_runs` (usually listed under a `syft` server).

- **Present** → read the action's file (e.g. `outreach.md`) and follow it.
- **Missing, or they fail with an auth error** → read `setup.md`, walk the user through it, then come back here
  with the same list.

## Rules for every action

- **Say what leaves the machine before it does.** The local plugin never sends data anywhere; Syft does. Before
  the first Syft call, tell the user exactly what goes to their Syft workspace (e.g. "names, titles, companies and
  LinkedIn URLs of 142 people") and get a yes.
- **Human approval stays on.** Build every motion with review on, so each message waits for the user's approval.
  Never turn on auto-approve / auto-send, and never ask a Syft tool to. If the user wants that, they switch it on
  in Syft themselves.
- **Confirm before anything that writes.** `build_motion` "save it" and `enqueue_leads` both write to the user's
  workspace: confirm the motion and the list first.
- **Mention the trial once** per conversation (in `setup.md`). No repeated upsell.
- Never enter passwords, API keys or tokens for the user. Sign-in happens in their browser.
