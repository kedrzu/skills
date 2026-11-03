---
name: setup
description: Set up the Telegram notification channel - collect the bot token in a masked dialog, pair the chat, verify delivery. Use when the user has a bot token from @BotFather to add or replace, asks to configure or fix Telegram notifications, asks why a notification did not arrive, or wants to check whether the channel works.
user-invocable: true
allowed-tools:
  - Read
  - Bash(python3 *)
  - Bash(ls *)
  - Bash(mkdir *)
  - Bash(chmod *)
---

# /telegram:setup — configure the notification channel

Arguments passed: `$ARGUMENTS`

The token lives **outside** the plugin so it survives version bumps and works in
every project on this machine:

```bash
echo "${TELEGRAM_STATE_DIR:-${CLAUDE_CONFIG_DIR:-$HOME/.claude}/channels/telegram}"
```

This is the same location the official `telegram@claude-plugins-official`
channel plugin uses, deliberately: both can share one bot and one token.

All work goes through the bundled CLI — do not hand-write the files:

```bash
CORE="${CLAUDE_PLUGIN_ROOT}/skills/telegram/scripts/telegram_core.py"
```

## Status

Run `python3 "$CORE" check` and report it in plain language: is a token stored,
is a chat paired, does Telegram answer, which bot is it. Never print the token.
End with the single concrete next step, which the `next_step` field already
names.

## Token

The token never goes through the chat: the bundled `secret.py` asks the user in
a masked dialog you cannot read and stores the token where `$CORE` reads it. Say
the dialog is coming before you run this, because it pops up outside the terminal:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/setup/scripts/secret.py" set TELEGRAM_BOT_TOKEN \
  --file "${TELEGRAM_STATE_DIR:-${CLAUDE_CONFIG_DIR:-$HOME/.claude}/channels/telegram}/.env" \
  --hint "Bot token from @BotFather (/newbot, or /token for an existing bot), e.g. 123456789:AAH..."
```

- **Exit 0**: it prints `OK`, the file and the character count, never the value.
- **Exit 4**: nothing was entered (cancelled, or 5 minutes passed). Nothing was written.
- **Exit 3**: no way to prompt from here (ssh, a cloud session). It printed a command: give it
  to the user to run in their own terminal, then read the verdict from the result file it names.

Do not call `osascript … with hidden answer`, `zenity --password` or `Get-Credential` yourself:
they return the typed value on stdout, which is your transcript. And do not `cat` or `grep` the
`.env` file.

Then `python3 "$CORE" check` validates it against `getMe`. Report the bot's
`@username` back, because the user needs it for pairing. A 401 there means a
truncated or wrong value: run `set` again.

A token that arrived as an argument or in a message is already in the
transcript. Do not store that copy; say so, and suggest `/revoke` in @BotFather,
which issues a new token for the dialog.

## Pairing

**A bot cannot message a user first** — Telegram requires the user to open the
conversation. This is the one irreducible manual step, so say it plainly:

> Open `t.me/<username>`, press Start (or send `/start`), then tell me.

Then run `python3 "$CORE" pair --save`.

Two things to know before you run it:

- If the official channel plugin was ever paired on this machine, `pair` takes
  the id straight from its `access.json` and no `/start` is needed.
- If a session is currently running that plugin's server, Telegram answers
  **409** — two processes cannot long-poll one bot. Say which process to stop
  rather than retrying.
- Telegram only keeps pending updates for **24 hours**. If `/start` was sent
  long ago, ask for a fresh message.

## Verify

Send a real test message and confirm it arrived on the phone:

```bash
python3 "$CORE" send --text "Telegram channel is live. — assistant"
```

Delivery is the only proof that counts. If it fails, `check` separates the
causes: 401 is a bad token, 403 means the bot is blocked, "chat not found"
means the pairing is stale.

## Afterwards

Tell the user what they now have: notifications work in **every** project on
this machine, with no per-project configuration. Mention that the agent will
only message them on request or from an unattended routine — the channel is not
a running commentary.
