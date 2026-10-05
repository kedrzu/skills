# Telegram

A one-way notification channel: let the agent reach your phone when you are not
at the terminal. The agent sends; nothing comes back.

For a two-way conversation with Claude Code over Telegram, use
`telegram@claude-plugins-official` instead. The two are designed to coexist —
they read the same token from the same place, so one bot serves both.

## Setup

**1. Create a bot.** Open [@BotFather](https://t.me/BotFather), send `/newbot`,
pick a name and a username ending in `bot`. You get a token like
`123456789:AAHfiqksKZ8...` — copy all of it, including the leading digits.

**2. Store it.** In Claude Code:

```
/telegram:setup 123456789:AAHfiqksKZ8...
```

**3. Pair.** A bot cannot message you first, so open `t.me/<your-bot>`, press
Start, and run `/telegram:setup` again. It captures the chat id and sends a test
message.

No per-project configuration: once this is done, the channel works in every
project on the machine.

## Tools

| Tool | Purpose |
| --- | --- |
| `send_message` | Send to the configured chat. Takes `text`, optional `format` (`plain` default, or `html` for `**bold**` and `` `code` ``) and `silent`. Text over 4096 chars is split, never truncated. |
| `check` | Is a token stored, is a chat paired, does Telegram answer. Sends nothing. |

**There is no `chat_id` parameter.** The destination is pinned in config, so a
hijacked prompt has nothing to redirect. This is the same structural guarantee
as having no `delete` subcommand: the capability simply is not there.

## Where the token lives

```
${TELEGRAM_STATE_DIR:-${CLAUDE_CONFIG_DIR:-$HOME/.claude}/channels/telegram}/
├── .env          TELEGRAM_BOT_TOKEN, mode 0600 (directory 0700)
└── notify.json   the paired chat id
```

Resolution order, token: `$TELEGRAM_BOT_TOKEN` → `.env`.
Chat id: `$TELEGRAM_CHAT_ID` → `notify.json` → `access.json` (`allowFrom[0]`,
written by the official channel plugin if you ever paired it).

The shell wins over the file, matching the official plugin's convention.
Deliberately **outside** the plugin directory: a version bump replaces the
plugin, and configuration must survive that.

Claude Code has no credential store for stdio MCP servers — keychain and OAuth
apply only to remote HTTP/SSE servers. A 0600 file is the honest maximum here,
which is why Anthropic's own Telegram plugin does exactly the same thing.

## CLI

The MCP server is a thin transport over `telegram_core.py`, which also runs
standalone — setup and debugging must not require a working MCP session:

```bash
CORE="${CLAUDE_PLUGIN_ROOT}/skills/telegram/scripts/telegram_core.py"
python3 "$CORE" check
python3 "$CORE" send --text "Deploy finished" [--format html] [--silent] [--dry-run]
python3 "$CORE" send --stdin
python3 "$CORE" pair --save
python3 "$CORE" set-token <token>
```

Exit codes: `0` fine, `1` channel not usable (see the printed report), `2` error
(JSON on stderr).

## Requirements

`python3` only — no dependencies, no install step, nothing fetched at session
start. The MCP protocol layer is ~150 lines of hand-rolled JSON-RPC, which two
tools do not outgrow.

## Failure modes

| Symptom | Cause |
| --- | --- |
| `No Telegram bot token` | Not configured on this machine → `/telegram:setup <token>` |
| `No Telegram chat id` | Never sent `/start` to the bot → `/telegram:setup` |
| 401 | Token revoked or mistyped |
| 403 "blocked" | You blocked the bot; unblock and send `/start` |
| "chat not found" | Stale pairing; re-pair |
| 409 while pairing | Another process long-polls this bot (the official channel plugin). Stop it, or let `pair` read `access.json` |
| Message arrived without formatting | `html` markup failed to parse, so it was re-sent as plain text rather than dropped |

## What this is not

No receiving, no webhook, no allowlist, no groups, no attachments. Those belong
to the official channel plugin.
