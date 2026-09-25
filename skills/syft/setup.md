# Set up Syft (only when the Syft MCP is missing or signed in to the wrong workspace)

**No Syft yet** (including someone signed in to another company's workspace who has none of their own): all three
steps in one short message, trial link once, then wait. **Has their own workspace but signed in to another**: step
3 only. Never enter credentials for the user.

1. **Start a Syft trial**:
   https://app.syftdata.com/auth/syft-signup?product=rolodex&source=linkedin-rolodex&utm_source=claude-plugin&utm_medium=linkedin&utm_campaign=outreach
   Use this link as-is: it goes straight to Syft's sign-up and tells Syft the signup came from this plugin (the
   buttons on syftdata.com/syfty replace that tag with their own). Do not add the user's name, email or anything
   personal to it. What Syft is and costs: https://www.syftdata.com/syfty. **Finish Syft's onboarding before step
   3**: the free trial, and with it access from Claude, starts when onboarding is done.
2. **Install the Syft Chrome extension** and sign in with the same account. It sends from the user's own LinkedIn,
   in their browser:
   https://chromewebstore.google.com/detail/syft-extension/nchnjpdedckhhfkoafckloolnfliocnd
3. **Connect the Syft MCP to Claude**:
   ```bash
   claude mcp add --transport http syft https://app.syftdata.com/api/mcp
   ```
   Then restart Claude Code (or run `/mcp`) and sign in when the browser opens. In the Claude desktop or web app,
   add a custom connector with the same URL instead. Signed in to the wrong workspace: sign out of that
   connection in `/mcp` (or the connector settings) and sign in again with the right account.

Once they are back and the Syft tools show up, return to `SKILL.md` Step 1 and carry on with the same list. They
do not need to rebuild it.

If they would rather not sign up: the list is theirs to use however they like. Do not push.

## Someone else on the team (a cofounder, a rep)

- **Their own list.** DMs only reach their own 1st-degree connections, so they need their own LinkedIn export
  (Settings → Data privacy → Get a copy of your data → larger data archive) and this plugin.
- **Same Syft workspace.** They do not need their own trial: invite them to the user's Syft workspace, and they
  install the Chrome extension signed in as themselves. Syft then offers them as a separate LinkedIn sender, and
  each sender gets their own motion (`<Audience> -> DM - <Name>`).
