---
name: setup
description: >-
  Set up or repair Google Drive access for this project through the gdrive-mcp plugin:
  pick or create the Google Cloud OAuth client, write .claude/gdrive-mcp.json with the
  permissions the project grants (browse, download, upload, edit, delete), sign accounts
  in through the browser, and verify. The user invokes it explicitly as `/gdrive-mcp:setup`.
  When a gdrive tool reports a setup problem or a missing permission, tell the user to run
  it; do not change the configuration yourself.
disable-model-invocation: true
user-invocable: true
allowed-tools:
  - Read
  - Edit
  - Write
  - Bash(bun *)
  - Bash(git *)
---

# /gdrive-mcp:setup — Google Drive for this project

Arguments passed: `$ARGUMENTS`

The `gdrive` MCP server of this plugin starts with every session. A project opts in, and says which accounts it may use and what the agent may do in Drive, in two files:

- `.claude/gdrive-mcp.json` is committed and shared by the team. It holds the OAuth clients (Google Cloud apps), the allowed accounts and the permissions.
- `.claude/gdrive-mcp.local.json` is personal and gitignored, and is layered on top. Use it, for example, for your own address in a shared repo.

Refresh tokens never go in the repository. They live in the user's store, at `~/.claude/gdrive-mcp/tokens/<client_id>/<email>.json` with mode 0600. The full config reference is in `${CLAUDE_PLUGIN_ROOT}/skills/setup/references/config.md`.

Do all the work through the bundled CLI. It prints JSON and never prints a secret:

```bash
GDRIVE="bun --install=force ${CLAUDE_PLUGIN_ROOT}/server/src/main.ts"
$GDRIVE check --project "${CLAUDE_PROJECT_DIR}"
```

## 1. Status

Run `check` and report the result in plain language:
- whether the config was found;
- for each client, whether it is readable, and why not;
- for each account, whether it is signed in and its token refreshes;
- the effective permissions.

Act on the first thing that is wrong. When everything is ok and the user wanted nothing else, stop here.

## 2. The OAuth client

Unless the config already names one, ask which Google Cloud app this project should use: a personal app for a private Drive, or the company's *Internal* app for Workspace accounts.

**If the project already uses gmail-mcp**, its client works here as well. The Google Drive API only has to be enabled in the same Cloud project.

If no app exists yet, walk the user through `${CLAUDE_PLUGIN_ROOT}/skills/setup/references/gcp-app.md`: create the project, enable the Drive API, choose Internal or External, and create a **Desktop app** client.

Then let the user pick where the client is read from. Explain the trade-off:

| Source | Config entry | When |
|---|---|---|
| File in the repo | `{"file": ".claude/google-oauth-client.json"}` | A private company repo, where a colleague clones and only has to sign in. Google itself does not treat a Desktop client's secret as confidential, but GitHub secret scanning flags `GOCSPX-…` |
| Any `.env` file | `{"envFile": "secrets/google.env", "clientIdKey": "…", "clientSecretKey": "…"}` | The repo keeps secrets encrypted (sops/age, git-crypt) and decrypts them to files. The keys default to `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` |
| The user's store | `{"store": "personal"}` after `$GDRIVE client import personal ~/Downloads/client_secret_….json` | The file must not enter the repo, or one client serves several projects |

Never `cat`, `grep` or otherwise print a client file or an env file: the secret would land in this transcript. Pass paths only. `check` reports the client id, which is safe to show.

## 3. Permissions

Ask the user what the agent may do in Drive in this project. Show the five switches with their defaults:

| Permission | Default | Allows |
|---|---|---|
| `browse` | on | search, list folders and shared drives, read metadata |
| `download` | on | read contents as text, save files locally |
| `upload` | off | create files and folders |
| `edit` | off | replace contents, rename, move, change descriptions and stars |
| `delete` | off | move to the trash and restore (never permanent deletion) |

Write into the config only the switches that differ from the default. In a shared repo, permissions that only one person wants belong in the `.local.json` file.

## 4. The config

Write `.claude/gdrive-mcp.json`, creating `.claude/` if needed. A minimal example:

```json
{
  "clients": { "work": { "file": ".claude/google-oauth-client.json" } },
  "accounts": [{ "match": "*@company.com" }],
  "permissions": { "upload": true }
}
```

- `accounts` narrows which signed-in accounts the project sees. Each rule is an exact address or a `*` glob, optionally with `"client": "<name>"`. Omit `accounts` to allow every account signed in under the configured clients.
- `files.roots` lists directories outside the project that the agent may upload from and download into.
- `files.downloadsDir` is where `download_file` writes by default. Without it, a temp directory is used.

Add `.claude/gdrive-mcp.local.json` to `.gitignore`, and the client file too if the user chose not to commit it. Run `check` again: it validates the file and lists every problem.

## 5. Sign in

Tell the user a browser tab is about to open and that they choose the account there. Then run, once per account:

```bash
$GDRIVE auth --project "${CLAUDE_PROJECT_DIR}" [--client NAME] [--login-hint user@company.com]
```

The command waits up to 5 minutes for the sign-in, so give it a 6-minute timeout. If no browser can open (ssh, a cloud session), the command prints the URL; pass it on. The redirect goes to `127.0.0.1` on the machine running the command, so the sign-in must happen on that machine.

- `usableInThisProject: false`: the address does not match `accounts`. Fix the rule or the local file.
- "not all permissions were granted": sign in again and tick the Drive checkbox.
- `access_denied`, "app not verified" or "org_internal": see the troubleshooting list in `gcp-app.md`.

## 6. Verify

Call the `list_accounts` tool of the `gdrive` server. The plugin's tools are named `mcp__plugin_gdrive-mcp_gdrive__*`. New accounts appear without restarting the session, and a change to `permissions` updates the tool list after the next tool call.

Finish with a real read, if `browse` is on: call `list_folder` with no `folderId`, which lists the root of My Drive.

## Removing an account

`$GDRIVE remove user@company.com --project "${CLAUDE_PROJECT_DIR}" [--client NAME]` revokes the token at Google and deletes it from the store. The account is then gone for every project that shared that token.

## When the server is missing

If the `gdrive` tools are absent, either the plugin is disabled or `bun` is not installed. Check with `bun --version`, and install bun from bun.sh if needed. The CLI above still works for setup.
