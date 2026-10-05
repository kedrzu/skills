---
name: telegram
description: Send a message to the user's phone over Telegram - the only way to reach them when they are not at the terminal. Use when the user says "napisz mi na telegramie", "daj znać jak skończysz", "wyślij mi to na telefon", "powiadom mnie", "ping me when it's done", "text me", or when a long task they left running in the background has finished and they are no longer watching. NOT for sending email (that is a Gmail draft), NOT for publishing a document to get a shareable link (that is /publish), NOT for parking something for later (that is a task tracker or an inbox note). Read this before the first notification of a session - a badly written one gets the channel muted.
---

# Telegram — reaching the user's phone

The channel is one tool, `mcp__telegram-notify__send_message`. This file is about
judgement: when a notification is warranted, and what a good one looks like.
Mechanics, config resolution and failure modes live in the plugin README.

## When you may send

| Situation | Send? | Why |
|---|---|---|
| The user asked you to ("daj znać jak skończysz") | **Yes** | Explicit request. Honour it even if the result is boring. |
| A scheduled/unattended routine produced something they must see | **Yes** | Nobody is watching the terminal. That is the whole point of the channel. |
| A long task they left running finished | **Yes** | They walked away expecting to be called back. |
| You finished a task while they are clearly at the keyboard | **No** | They are already reading your answer. A phone buzz is noise. |
| Progress updates, "starting now", "still working" | **No** | Interruption without information. |
| Something you think is interesting | **No** | Not your call. Put it in the report. |

A notification is an interruption, not a reporting channel. The budget is
social, not technical: a channel that buzzes for nothing gets muted, and then
it is gone for the things that mattered.

## What a good message looks like

- **The first line must stand on its own.** A lock screen shows about two
  lines and no markup. `Rutyna 8:00: 4 spotkania, 7 zadań (2 zaległe), 18 maili, 3 do decyzji`
  works; `Here is your summary:` does not.
- **Aim for under ~1500 characters.** Detail belongs in the document, the
  dashboard or the report. Longer text is split into several messages
  automatically, which is a fallback, not a plan.
- **Default to `plain`.** Use `format: "html"` only when emphasis genuinely
  helps; it renders `**bold**` and `` `code` `` and escapes everything else.
- **Put a link last, bare.** Telegram linkifies a naked URL. A path inside a
  vault or a repo is *not* a link - if they are meant to click something,
  publish it first and send the URL.
- **Never ask a question.** Nobody can answer. If a decision is needed, say
  where it is waiting.

## Flow

```bash
# The tool is the normal path. Drop to the CLI only to debug.
python3 "${CLAUDE_PLUGIN_ROOT}/skills/telegram/scripts/telegram_core.py" check
```

If `send_message` fails, call `check` before retrying: it separates "no token"
from "not paired" from "Telegram is down", and each has a different fix.

## When it does not work

| Symptom | Cause |
|---|---|
| `No Telegram bot token` | Never configured on this machine → `/telegram:setup <token>` |
| `No Telegram chat id` | Token set, but you never sent `/start` to the bot → `/telegram:setup` |
| 401 | Token revoked or mistyped → new token from @BotFather |
| 403, "blocked" | The user blocked the bot → they unblock it and send `/start` |
| 409 during pairing | Another process is long-polling the same bot (the official telegram channel plugin) → stop it, or pair from `access.json` |

## What we do not do here

- **We do not receive.** No polling, no webhook, no replies. If you need an
  answer, ask in the session.
- **We do not message anyone else.** The chat is pinned in config and is not a
  parameter of the tool — by design, so a hijacked prompt has nothing to redirect.
- **We do not send sensitive material.** No patient data, identity documents,
  financial records, or third-party personal data. A phone notification is not
  a secure channel.
