# Gmail MCP

Gmail for agents, several mailboxes at once: search, read threads as Markdown with quotes
and signatures stripped, write drafts in Markdown with attachments and inline images,
organise with labels, save attachments to disk. It never sends — drafts wait in Gmail
for a human to press Send.

Each project decides on its own which Google Cloud app it signs in through and which
mailboxes it may touch, so a personal assistant and a company repo can use different
apps, and a colleague who clones the company repo only has to sign in.

Runs on [bun](https://bun.sh) straight from source; dependencies are fetched on first start
in the versions pinned by `server/bun.lock`. No Docker, no ports, no environment variables.

## Setup

Run `/gmail-mcp:setup` in the project. It walks through:

1. **An OAuth client** — a *Desktop app* client in a Google Cloud project with the Gmail API
   enabled (`skills/setup/references/gcp-app.md`). For company accounts make the app
   *Internal* to the Workspace; for personal ones mind the 7-day token limit of External
   apps in Testing.
2. **`.claude/gmail-mcp.json`** — names the client and where to read it (a file in the
   repo, any `.env` file such as one decrypted by sops, or a private store outside the
   repo) and which accounts are allowed. Personal additions go in the gitignored
   `.claude/gmail-mcp.local.json`. Reference: `skills/setup/references/config.md`.
3. **Sign-in** — a browser tab per mailbox; the refresh token goes to
   `~/.claude/gmail-mcp/tokens/` (mode 0600), never into the repo.

## Tools

| Tool | Purpose |
|---|---|
| `list_accounts` | Mailboxes usable in this project, and any setup problem |
| `search_threads` | Gmail query syntax, de-duplicated into threads; optional named `view` |
| `get_thread`, `get_message` | Bodies as Markdown, label names, attachments |
| `create_draft`, `update_draft` | Markdown body, Gmail signature and reply quote added, attachments, inline images |
| `list_drafts`, `get_draft`, `discard_draft` | Draft round trip; discard moves to Trash |
| `update_thread` | Labels in one atomic call; enforces the project's label rules |
| `list_labels`, `create_label`, `cleanup_labels` | Label housekeeping |
| `save_attachment` | Writes the file to disk and returns its path |

Optional **label rules** (exclusive groups, required groups, archive markers, named
views) turn `update_thread` into a guarded workflow step — see `config.md`.

## Development

```bash
cd plugins/gmail-mcp/server
bun install
bun test
bunx tsc --noEmit
```

The plugin will move to an npm package (`@kedrzu/gmail-mcp`, run with `bunx`) once the
interface settles; until then `.mcp.json` runs `server/src/main.ts` directly.
