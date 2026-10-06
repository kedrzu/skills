---
name: setup
description: >-
  Set up or repair Gmail access for this project through the gmail-mcp plugin - pick or create
  the Google Cloud OAuth client, write .claude/gmail-mcp.json, sign mailboxes in through the
  browser, verify. Invoked explicitly by the user as `/gmail-mcp:setup`; when a gmail tool
  reports a setup problem, tell the user to run it instead of fixing the configuration yourself.
disable-model-invocation: true
user-invocable: true
allowed-tools:
  - Read
  - Edit
  - Write
  - Bash(bun *)
  - Bash(git *)
---

# /gmail-mcp:setup — Gmail for this project

Arguments passed: `$ARGUMENTS`

The `gmail` MCP server of this plugin starts with every session. A project opts in, and
says which mailboxes it may touch, in two files:

- `.claude/gmail-mcp.json` — committed, shared by the team: OAuth clients (Google Cloud
  apps) and which accounts are allowed.
- `.claude/gmail-mcp.local.json` — personal, gitignored, layered on top (e.g. your own
  address in a shared repo).

Refresh tokens never go in the repository. They live in the user's store
(`~/.claude/gmail-mcp/tokens/<client_id>/<email>.json`, mode 0600), keyed by client, so
projects using the same client share a sign-in and a project only sees the accounts its
config allows. Full config reference: `${CLAUDE_PLUGIN_ROOT}/skills/setup/references/config.md`.

All work goes through the bundled CLI (it prints JSON and never prints a secret):

```bash
GMAIL="bun --install=force ${CLAUDE_PLUGIN_ROOT}/server/src/main.ts"
$GMAIL check --project "${CLAUDE_PROJECT_DIR}"
```

## 1. Status

Run `check` and report it in plain language: config found or not, each client readable or
why not, each account signed in and refreshable. Act on the first thing that is wrong;
when everything is ok and the user wanted nothing else, stop here.

## 2. The OAuth client

Ask which Google Cloud app this project should use, unless the config already names one:
a personal app for private mail, or the company's *Internal* app for Workspace accounts.
If none exists yet, walk the user through
`${CLAUDE_PLUGIN_ROOT}/skills/setup/references/gcp-app.md` (create the project, enable the
Gmail API, choose Internal or External, create a **Desktop app** client).

Then pick where the client is read from — the user's call, explain the trade-off:

| Source | Config entry | When |
|---|---|---|
| File in the repo | `{"file": ".claude/gmail-oauth-client.json"}` | Private company repo: a colleague clones and signs in, nothing else. A Desktop client's secret is not confidential by Google's own design, but GitHub secret scanning flags `GOCSPX-…` |
| Any `.env` file | `{"envFile": "secrets/google.env", "clientIdKey": "…", "clientSecretKey": "…"}` | The repo keeps secrets encrypted (sops/age, git-crypt) and decrypts them to files. Keys default to `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` |
| The user's store | `{"store": "personal"}` after `$GMAIL client import personal ~/Downloads/client_secret_….json` | The file must not enter the repo, or one client serves several projects |

Never `cat`, `grep` or otherwise print a client file or an env file: the secret would
land in this transcript. Pass paths only; `check` reports the client id, which is safe.

## 3. The config

Write `.claude/gmail-mcp.json` (create `.claude/` if needed). Minimal:

```json
{ "clients": { "work": { "file": ".claude/gmail-oauth-client.json" } }, "accounts": [{ "match": "*@company.com" }] }
```

- `accounts` narrows which signed-in mailboxes the project sees (exact address or a `*`
  glob, optionally `"client": "<name>"`). Omit it to allow every mailbox signed in under
  the configured clients. In a shared repo prefer a domain glob; personal addresses go in
  the `.local.json` file.
- `files.roots` lists directories outside the project that drafts may attach from;
  `files.attachmentsDir` is where `save_attachment` writes (default: a temp directory).
- `labels` is optional: exclusive label groups, required groups, archive markers and named
  search views. Add it only when the user describes such a workflow — see `config.md`.

Add `.claude/gmail-mcp.local.json` to `.gitignore` (and the client file too, if the user
chose not to commit it). Run `check` again: it validates the file and lists every problem.

## 4. Sign in

Tell the user a browser tab is about to open and that they choose the account there.
Then run, once per mailbox:

```bash
$GMAIL auth --project "${CLAUDE_PROJECT_DIR}" [--client NAME] [--login-hint user@company.com]
```

It waits up to 5 minutes for the sign-in, so give the command a 6-minute timeout. If no
browser can open (ssh, a cloud session), it prints the URL — pass it on; the redirect
goes to `127.0.0.1` on the machine running the command, so the sign-in must happen there.

- `usableInThisProject: false` → the address does not match `accounts`; fix the rule or
  the local file.
- "not all permissions were granted" → sign in again and tick every checkbox.
- `access_denied` / "app not verified" / "org_internal" → see the troubleshooting list in
  `gcp-app.md`.

## 5. Verify

Call the `list_accounts` tool of the `gmail` server (the plugin's tools are named
`mcp__plugin_gmail-mcp_gmail__*`). New accounts appear without restarting the session.
A config change that touches `labels` is picked up on the next tool call. Finish with a
real read: `search_threads` with `query: "in:inbox"`, `maxResults: 3`.

## Removing a mailbox

`$GMAIL remove user@company.com --project "${CLAUDE_PROJECT_DIR}" [--client NAME]` revokes
the token at Google and deletes it from the store. It is gone for every project that
shared it.

## When the server is missing

If the `gmail` tools are absent, the plugin is disabled or `bun` is not installed
(`bun --version`; install from bun.sh). The CLI above still works for setup.
