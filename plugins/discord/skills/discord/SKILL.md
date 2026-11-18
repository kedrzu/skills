---
name: discord
description: Read, search and summarize the user's Discord servers and channels through the Discord desktop app they are logged into — no bot, no token. Keeps a local copy of the conversations, answers from it, and fetches only what is missing. Use when the user says "co było na kanale X", "podsumuj #general z ostatniego tygodnia", "znajdź na Discordzie / na serwerze Y…", "kto pisał o…", "what did they say on Discord about…", or otherwise asks about something said on Discord. Read-only — it cannot post.
---

# Discord — reading through the desktop app

A bot only sees servers whose admin added it, and a user token is self-botting, which Discord
bans for. Neither is needed here. The desktop app is Chromium, and its HTTP cache keeps every
page of messages it loads. `discord.py` copies those pages into a local store, and to fetch more
it makes the app load them: it opens a channel and presses Page Up.

```bash
DC="python3 -I ${CLAUDE_PLUGIN_ROOT}/skills/discord/scripts/discord.py"
$DC status [-s SERVER] [-c CHANNEL]           # what the store holds, and the gap-free range per channel
$DC search "words all present" [-s …] [-c …] [--since 7d] [-a AUTHOR] [-n 100]   # -E for a regex
$DC read -c general [--since 2026-11-01] [--until …] [-n 300] [--around ID] [--links]
$DC channels [-s SERVER]                      # servers, and that server's channels, from the app
$DC sync -c general [-c random …] [-s SERVER] --since 14d [--max-minutes 10]
$DC harvest                                   # copy whatever the app has cached, without driving it
```

`-c` takes a name, a fragment or an id. `--since`/`--until` take `2026-11-01`, `2026-11-01T10:00`,
or `12h`/`7d`/`3w`. Timestamps are UTC.

## Store first, then fetch the gap

The store is `~/.context/discord/` (`DISCORD_STORE` overrides it): `messages/<channel_id>.jsonl`,
one message per line, and `channels.json` with names, servers and each channel's `covered`
range. `status` shows that range as "gap-free". Inside it the store has every message as of the
last sync. Outside it the store holds only what Discord happened to cache when the user scrolled,
so it has gaps.

So start with `status`, and compare the gap-free range of each channel the question touches
with the period it asks about:

- The period lies inside the range, and the range ends recently enough for the question → answer
  from the store with `search`/`read`, and touch nothing in the app.
- Otherwise → `sync` exactly those channels with `--since` set to the period's start. A repeated
  sync only catches up from the newest stored message and continues back from the oldest, so it
  costs only what is missing.
- A question about a whole server → `channels -s SERVER` lists its channels; `sync` the ones the
  question plausibly touches, or all text channels if it is genuinely server-wide.

A sync is not free for the user. Discord comes to the front for its duration and the previous
app is restored after, so it takes over their screen. It loads about 8 messages a second, so a
busy channel's month can take minutes. For anything longer than a minute or two, say how many
channels and how far back, and ask before starting. A sync stops by itself when the user switches
away from Discord.

## Reading economy

Everything printed stays in the session transcript, other people's messages included. Read what
the question needs: `search` before `read`, a date range before a whole channel. `read` and
`search` print one line per message, truncated (`--width`, `--full`). `--around ID` shows the
context of a hit; the id printed after `·` is enough. To summarize thousands of messages, read
them in date slices and summarize each slice; for a whole server, give each channel to a
subagent. Link a message the user may want to open with `--links`.

## Requirements and failures

| Symptom | Cause / fix |
|---|---|
| `No Accessibility permission` | System Settings → Privacy & Security → Accessibility: allow the app running the shell (terminal, Paseo, Claude). |
| `Discord has no open window` | The app is only in the tray. Ask the user to open its window. |
| `Compiling ax.swift failed` | `xcode-select --install`. The helper compiles once into `~/.cache/discord-skill/`. |
| `unknown server; run channels` | The channel was only seen in the cache. Run `channels -s SERVER` on its server so names and server ids are known. |
| A forum channel | Its posts are threads with their own ids. Open the post in the app, then `harvest` or `sync -c <thread id>`. |
| `No server named …` | The server sits inside a collapsed sidebar folder. Ask the user to expand it. |
| A request to post or reply | Not possible here. Posting through automation of the user's account is what gets accounts banned. |

The UI labels the helper looks for are Polish and English ("Serwery"/"Servers", "Wiadomości
w"/"Messages in"). Another app language needs those added in `scripts/ax.swift`.
