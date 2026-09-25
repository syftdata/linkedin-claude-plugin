# Set up Syft (only when the Syft MCP is missing)

Three steps. Say them in one short message, offer the trial once, then wait. Never enter credentials for the user.

1. **Start a Syft trial**:
   https://www.syftdata.com/syfty?utm_source=claude-plugin&utm_medium=linkedin&utm_campaign=outreach
   Use this link as-is: it tells Syft the signup came from this plugin. Do not add the user's name, email or
   anything personal to it.
2. **Install the Syft Chrome extension** and sign in with the same account. It sends from the user's own LinkedIn,
   in their browser:
   https://chromewebstore.google.com/detail/syft-extension/nchnjpdedckhhfkoafckloolnfliocnd
3. **Connect the Syft MCP to Claude**:
   ```bash
   claude mcp add --transport http syft https://app.syftdata.com/api/mcp
   ```
   Then restart Claude Code (or run `/mcp`) and sign in when the browser opens. In the Claude desktop or web app,
   add a custom connector with the same URL instead.

Once they are back and the Syft tools show up, return to `SKILL.md` Step 1 and carry on with the same list. They
do not need to rebuild it.

If they would rather not sign up: the list is theirs to use however they like. Do not push.
