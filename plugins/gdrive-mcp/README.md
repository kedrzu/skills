# Google Drive MCP

Google Drive for agents, with several accounts at once. It can:
- search and browse My Drive, files shared with you, and shared drives;
- read Google Docs as Markdown, Sheets as CSV and text files as they are;
- download files, exporting Google files to Office formats or PDF;
- upload files, with optional conversion to Google formats;
- replace contents, rename and move files;
- move files to the trash.

It never deletes anything permanently and never shares files.

Every capability sits behind a **permission that each project switches on or off**: `browse`, `download`, `upload`, `edit` and `delete`. Reading is on by default and writing is opt-in. A switched-off tool is not even listed to the agent.

Each project also decides which Google Cloud app it signs in through and which accounts it may use. A personal assistant and a company repo can therefore use different apps, and a colleague who clones the company repo only has to sign in.

The server runs on [bun](https://bun.sh) straight from source. On first start, bun fetches the dependencies in the versions pinned by `server/bun.lock`. There is no Docker, no port to open and no environment variable to set.

## Setup

Run `/gdrive-mcp:setup` in the project. It walks through three steps:

1. **An OAuth client.** This is a *Desktop app* client in a Google Cloud project that has the Drive API enabled; see `skills/setup/references/gcp-app.md`. A client created for gmail-mcp works too.
2. **`.claude/gdrive-mcp.json`.** This file names the client and where it is read from: a file in the repo, any `.env` file, or a private store outside the repo. It also lists which accounts are allowed and which permissions the project grants. Personal additions go in the gitignored `.claude/gdrive-mcp.local.json`. Reference: `skills/setup/references/config.md`.
3. **Sign-in.** A browser tab opens for each account. The refresh token goes to `~/.claude/gdrive-mcp/tokens/` (mode 0600), never into the repo.

## Tools

| Permission | Tool | Purpose |
|---|---|---|
| — | `list_accounts` | Accounts usable in this project, the permissions in force, and any setup problem |
| `browse` | `search_files` | Plain words (full text) or Drive query syntax; optional folder and type filters |
| `browse` | `list_folder` | A folder's children, folders first; a shared drive id lists that drive's root |
| `browse` | `get_file_info` | Metadata, path, owners, capabilities, export formats |
| `browse` | `list_shared_drives` | Shared drives of the account |
| `download` | `read_file` | Contents as text: Doc → Markdown, Sheet → CSV, Slides → text, text files as is |
| `download` | `download_file` | Saves to disk; Google files are exported (docx, xlsx, pptx, pdf, md, …) |
| `upload` | `upload_file` | From a local file or from text, optionally converted to a Doc / Sheet / Slides |
| `upload` | `create_folder` | New folder |
| `edit` | `update_file` | Replaces contents and keeps the id, link, sharing and history (a Doc accepts Markdown) |
| `edit` | `update_file_metadata` | Renames, moves, describes, stars |
| `delete` | `trash_file`, `restore_file` | Moves to the trash and back; nothing is deleted permanently |

Every tool accepts a file id or a `drive.google.com` / `docs.google.com` URL.

Local paths are limited to the project directory, plus the directories the config allows. Uploading secrets such as `.env*` files, OAuth clients and tokens is refused.

## Development

```bash
cd plugins/gdrive-mcp/server
bun install
bun test
bunx tsc --noEmit
```

The plugin will move to an npm package (`@kedrzu/gdrive-mcp`, run with `bunx`) once the interface settles. Until then, `.mcp.json` runs `server/src/main.ts` directly.
