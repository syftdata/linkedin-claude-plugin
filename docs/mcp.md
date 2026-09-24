# MCP endpoint (design, stubbed)

Goal: the same LinkedIn bot as an MCP server, so any agent (Claude, GrokBot, others) can load a user's LinkedIn
export and query it. Status: **tool contract and Python functions exist (`skills/linkedin/mcp_tools.py`); no
transport is wired.** A local ZIP path and the watch folder work today; HTTP upload is a later step.

## Tools

| Tool | Input | Returns |
|---|---|---|
| `ingest_linkedin_export` | `zip_path` (optional; default: newest ZIP in the watch folder) | load stats: row counts per file, messages date range, how many DM counterparts are connections |
| `search_shares` | `query`, `limit` | the user's posts matching the keyword |
| `find_connections` | `title`, `company` | 1st-degree connections by substring |
| `network_profile` | `as_of` (optional) | snapshot + every cleanup preset with its live count |
| `cleanup_candidates` | `preset` or thresholds, `keep_company[]`, `keep_title[]`, `only_title[]`, `limit`, `as_of` | `{summary, rows, next}`; refuses with no preset or thresholds |

JSON schemas: `TOOLS` in `skills/linkedin/mcp_tools.py`. Every tool calls the same loader and queries as the CLI,
so CLI and MCP results match.

## Upload (later)

`ingest_linkedin_export` will also accept an upload (multipart or a signed URL). The server writes it into the watch
folder and runs the same loader. Until then, callers pass a local path.

## Guided cleanup over MCP

The agent drives the same five steps as `skills/linkedin-cleanup/SKILL.md`: `network_profile` → ask the user →
`cleanup_candidates` with their choices. The server never picks the group and never removes anyone.

## Extension points

- `cleanup.apply_pass2(rows, icp, persona)`: pass 2, ICP / persona via the Syft MCP or Rolodex. Raises
  `NotImplementedError`.
- `cleanup.to_rolodex_import(rows)`: shape a candidate list for a Rolodex import. Raises `NotImplementedError`.
