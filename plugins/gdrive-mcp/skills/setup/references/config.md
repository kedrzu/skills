# gdrive-mcp config reference

The server reads two files from the project directory (the one Claude Code was started in):

1. `.claude/gdrive-mcp.json` is committed and shared.
2. `.claude/gdrive-mcp.local.json` is personal and gitignored. It is layered on top:
   - `clients` merge by name;
   - `accounts` and `files.roots` are appended;
   - `files.downloadsDir` replaces;
   - `permissions` override one switch at a time.

Paths are relative to the project directory, and `~` means the home directory. Neither file may hold a secret. Edits take effect on the next tool call, with no restart; the tool list itself is refreshed too. If neither file exists, the server runs with no accounts and every tool explains how to set it up.

```jsonc
{
  "clients": { "<name>": <source>, ... },        // required, at least one
  "accounts": [ <rule>, ... ],                    // optional
  "permissions": { "upload": true, ... },         // optional, see below for defaults
  "files": { "roots": [...], "downloadsDir": "..." }  // optional
}
```

## permissions

Five switches. Each one covers a set of tools:

| Permission | Default | Tools | Allows |
|---|---|---|---|
| `browse` | on | `search_files`, `list_folder`, `get_file_info`, `list_shared_drives` | Searching, listing folders and shared drives, reading metadata |
| `download` | on | `read_file`, `download_file` | Reading contents as text, saving files to the local disk |
| `upload` | **off** | `upload_file`, `create_folder` | Creating files and folders |
| `edit` | **off** | `update_file`, `update_file_metadata` | Replacing contents, renaming, moving, descriptions, stars |
| `delete` | **off** | `trash_file`, `restore_file` | Moving to the trash and back |

A tool whose permission is off is left out of the tool list, so the agent does not see it. It is also refused if called anyway, for example by a client that still holds an older list. `list_accounts` is always available and reports which permissions are on.

Some actions are not possible with any setting: deleting permanently, emptying the trash, sharing a file, or changing who has access to it.

Permissions apply to the whole project, for every account it uses. The Google sign-in always grants the full `drive` scope, because one token serves every project on the machine. What an agent may actually do is therefore decided here, not on Google's consent screen.

`browse` and `download` are independent. A project that turns `browse` off can still read a file whose id or URL the user hands over.

## clients

Give each client a name of your choice and say where its id and secret come from. Use exactly one of these keys:

| Key | Reads | Notes |
|---|---|---|
| `file` | The JSON downloaded from the Cloud console (`installed` or `web`) | Can live anywhere, e.g. committed under `.claude/` |
| `envFile` | Any `KEY=value` file (`export`, quotes and `#` comments are understood) | `clientIdKey` / `clientSecretKey` name the keys. Defaults: `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` |
| `store` | `~/.claude/gdrive-mcp/clients/<name>.json`, put there by `client import <name> <file>` | Never in the repo |

A gmail-mcp client works here too: point `file` or `envFile` at the same source.

Sources are read on every account scan, so an env file decrypted after the session started works without a restart. When a source cannot be read, `check` and `list_accounts` report it, and the other clients keep working.

## accounts

This section limits which signed-in Google accounts the project may use. A token is usable when its client is configured here **and** a rule matches:

```json
"accounts": [
  { "match": "*@acme.com", "client": "acme" },
  { "match": "me@gmail.com" }
]
```

`match` is an address or a `*` glob, case-insensitive. `client` limits the rule to one configured client.

Without an `accounts` key, every account signed in under the configured clients is allowed. Signed-in accounts that match no rule are listed as `notAllowedHere`: the agent can see them but cannot use them.

## files

- `roots` lists directories outside the project that the server may upload from and download into, e.g. a notes vault. The project directory is always allowed.
- `downloadsDir` is where `download_file` writes when it gets no `path`. The default is `$TMPDIR/gdrive-mcp/downloads`. This directory is always allowed.

The following are never uploaded or overwritten, even inside an allowed root: `.env*`, `*-credentials.json`, `*-tokens.json`, the token store and every client source. Paths are checked after symlinks are resolved. A download never replaces an existing file unless the call passes `overwrite: true`.

## Examples

A personal assistant that may organise the user's Drive, with the client kept out of the repo:

```json
{
  "clients": { "personal": { "store": "personal" } },
  "permissions": { "upload": true, "edit": true, "delete": true },
  "files": { "roots": ["~/Notes"], "downloadsDir": ".context/drive" }
}
```

A company repo that only reads the shared drives, with secrets encrypted by sops/age:

```json
{
  "clients": {
    "acme": { "envFile": "secrets/google.env", "clientIdKey": "GOOGLE_OAUTH_CLIENT_ID", "clientSecretKey": "GOOGLE_OAUTH_CLIENT_SECRET" }
  },
  "accounts": [{ "match": "*@acme.com", "client": "acme" }]
}
```

An agent that publishes reports and nothing else. It cannot even look around:

```json
{
  "clients": { "acme": { "file": ".claude/google-oauth-client.json" } },
  "permissions": { "browse": false, "download": false, "upload": true }
}
```

## The store

The store lives in `${GDRIVE_MCP_HOME:-${CLAUDE_CONFIG_DIR:-~/.claude}/gdrive-mcp}`, with directories at mode 0700 and files at 0600:

- `clients/<name>.json` holds imported clients.
- `tokens/<client_id>/<email>.json` holds one refresh token per account and client. Tokens are keyed by client id, so every project using a client shares its sign-ins.

This store is separate from gmail-mcp's, so an account signs in to each plugin on its own.

## CLI

Run commands as `bun --install=force ${CLAUDE_PLUGIN_ROOT}/server/src/main.ts <command> --project <dir>`:

| Command | Does |
|---|---|
| `check` | Validates the config, reads every client, refreshes every token, prints the effective permissions; exits with 1 on any problem |
| `auth [--client N] [--login-hint EMAIL] [--port P] [--no-open]` | Signs in through the browser and stores the token |
| `accounts` | Lists accounts usable here, accounts not allowed here, and problems |
| `remove EMAIL [--client N]` | Revokes the token at Google and deletes it |
| `client import NAME FILE` | Copies a downloaded client into the store |
| `serve` | Runs the MCP server (what `.mcp.json` runs) |
