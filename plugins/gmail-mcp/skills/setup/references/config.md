# gmail-mcp config reference

Read from the project directory (the one Claude Code was started in):

1. `.claude/gmail-mcp.json` — committed, shared.
2. `.claude/gmail-mcp.local.json` — personal, gitignored, layered on top: `clients` merge by
   name, `accounts` and `files.roots` are appended, `files.attachmentsDir` and `labels`
   replace.

Paths are relative to the project directory; `~` is the home directory. Neither file may
contain a secret. Edits take effect on the next tool call — no restart. Without either
file the server runs with no accounts and every tool explains how to set it up.

```jsonc
{
  "clients": { "<name>": <source>, ... },     // required, at least one
  "accounts": [ <rule>, ... ],                 // optional
  "files": { "roots": [...], "attachmentsDir": "..." },  // optional
  "labels": { ... }                            // optional label rules
}
```

## clients

A name of your choice → where the OAuth client's id and secret come from. Exactly one of:

| Key | Reads | Notes |
|---|---|---|
| `file` | The JSON downloaded from the Cloud console (`installed` or `web`) | Anywhere, e.g. committed under `.claude/` |
| `envFile` | Any `KEY=value` file (`export`, quotes and `#` comments understood) | `clientIdKey` / `clientSecretKey` name the keys; default `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` |
| `store` | `~/.claude/gmail-mcp/clients/<name>.json`, put there by `client import <name> <file>` | Never in the repo |

Sources are read on every account scan, so an env file decrypted after the session started
works without a restart. A source that cannot be read is reported by `check` and
`list_accounts`; the other clients keep working.

## accounts

Which signed-in mailboxes this project may use. A token is usable when its client is
configured here **and** a rule matches:

```json
"accounts": [
  { "match": "*@acme.com", "client": "acme" },
  { "match": "me@gmail.com" }
]
```

`match` is an address or a `*` glob, case-insensitive. `client` limits the rule to one
configured client. No `accounts` key = every mailbox signed in under the configured
clients. Signed-in mailboxes that no rule matches are listed as `notAllowedHere`, so they
are visible but untouchable.

## files

- `roots` — directories outside the project that drafts may attach files from (the
  project directory is always allowed), e.g. a notes vault.
- `attachmentsDir` — where `save_attachment` writes, `<dir>/<messageId>/<file>`. Default:
  `$TMPDIR/gmail-mcp/attachments`. Always allowed as an attachment source.

`.env*`, `*-credentials.json`, `*-tokens.json`, the token store and every client source
are refused as attachments, even inside an allowed root.

## labels

Optional rules the server enforces on `update_thread` and offers on `search_threads`.
Without this section labels are free-form. Four building blocks:

```json
"labels": {
  "groups": {
    "status":   ["AI/Done", "AI/Triage"],
    "priority": ["P/0", "P/1", "P/2", "P/3"]
  },
  "require": [{ "when": "AI/Done", "group": "priority" }],
  "archiveMarkers": ["Outdated", "Junk"],
  "views": {
    "unprocessed": "-label:AI/Done -label:AI/Triage",
    "triage": "label:AI/Triage"
  }
}
```

- **groups** — mutually exclusive label sets. They are changed only through
  `update_thread.set` (`{"status": "AI/Done"}` applies it and removes `AI/Triage`;
  `{"status": null}` clears the group); passing them in `addLabels`/`removeLabels` is
  rejected. Missing group labels are created on first use. A label belongs to at most one
  group.
- **require** — a thread that carries `when` must also carry one label of `group`. Checked
  on the thread's resulting labels whenever a call sets or clears either side, before
  anything is written.
- **archiveMarkers** — the only way out of INBOX: adding a marker removes INBOX
  automatically; removing INBOX without a marker on the thread is rejected. Without
  markers, archiving (removing INBOX) is unrestricted.
- **views** — named Gmail queries; `search_threads.view` ANDs the view with `query`.
  Omitting `view` searches all mail.

Group labels and markers are also protected from `cleanup_labels`. The tool descriptions
are generated from these rules, so the agent sees exactly what the project enforces.

## Examples

Personal assistant, two own mailboxes, client kept out of the repo:

```json
{
  "clients": { "personal": { "store": "personal" } },
  "files": { "roots": ["~/Notes"], "attachmentsDir": ".context/attachments" }
}
```

Company repo, secrets encrypted with sops/age and decrypted to `secrets/google.env`:

```json
{
  "clients": {
    "acme": { "envFile": "secrets/google.env", "clientIdKey": "GMAIL_OAUTH_CLIENT_ID", "clientSecretKey": "GMAIL_OAUTH_CLIENT_SECRET" }
  },
  "accounts": [{ "match": "*@acme.com", "client": "acme" }]
}
```

Company repo with the Desktop client committed, plus a personal mailbox only on one
machine (`.claude/gmail-mcp.local.json`):

```json
{
  "clients": { "personal": { "store": "personal" } },
  "accounts": [{ "match": "me@gmail.com", "client": "personal" }]
}
```

## The store

`${GMAIL_MCP_HOME:-${CLAUDE_CONFIG_DIR:-~/.claude}/gmail-mcp}` — directories 0700, files 0600:

- `clients/<name>.json` — imported clients;
- `tokens/<client_id>/<email>.json` — one refresh token per mailbox and client. Keyed by
  client id, so the same mailbox can be signed in under two apps independently, and every
  project using a client shares its sign-ins.

## CLI

`bun --install=force ${CLAUDE_PLUGIN_ROOT}/server/src/main.ts <command> --project <dir>`:

| Command | Does |
|---|---|
| `check` | Validates the config, reads every client, refreshes every token; exit 1 on any problem |
| `auth [--client N] [--login-hint EMAIL] [--port P] [--no-open]` | Browser sign-in, stores the token |
| `accounts` | Accounts usable here, those not allowed here, problems |
| `remove EMAIL [--client N]` | Revokes at Google and deletes the token |
| `client import NAME FILE` | Copies a downloaded client into the store |
| `serve` | The MCP server (what `.mcp.json` runs) |
