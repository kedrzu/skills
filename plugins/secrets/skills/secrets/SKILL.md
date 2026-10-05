---
name: secrets
description: Collect an API key, token, password or any other credential from the user without it ever entering the conversation, and use it from scripts without reading it - a masked native dialog writes it to a 0600 file, and a wrapper hands it to the program that needs it. Use whenever a task or another skill needs a secret the user has to supply (bot token, API key, PAT, licence key), when the user is about to paste one into the chat or asks where to put one, and whenever a command needs a stored secret in its environment. Do NOT ask for the value in chat, and do NOT take it as a command argument.
---

# Secrets — out of the transcript

Whatever the user types into the chat, and whatever a command prints, stays in the session
transcript for good. A secret typed into the dialog below never reaches you: `secret.py` reads it
inside its own process and prints only a verdict line. That is the whole point — the value can be
used without ever becoming part of the conversation.

This protects the **transcript, not the disk**. The value sits in a plain `KEY=value` file (mode
0600 in a 0700 directory) that you could still read, so don't: `cat`, `grep`, `env`, `printenv` or
an `echo $KEY` would put it straight back into the transcript.

```bash
SECRET="${CLAUDE_PLUGIN_ROOT}/skills/secrets/scripts/secret.py"
```

## Collect

```bash
python3 "$SECRET" set KEY [--file PATH] --hint "Where the value comes from"
```

A masked dialog appears on the user's screen (macOS: `osascript`; Windows: PowerShell
`Get-Credential`; Linux: zenity/kdialog; otherwise a no-echo terminal prompt). Tell the user it is
coming before you run it, because it pops up outside the terminal. Write the hint for the person:
which site, which page, which scope.

- **Exit 0**: `OK KEY wrote PATH (N characters)`. A suspicious length is your only clue to a
  mistyped value. Confirm it with the consumer's own probe rather than by looking at the value.
- **Exit 4**: nothing was entered (cancelled, or 5 minutes passed). Nothing was written.
- **Exit 3**: no way to prompt from here (no desktop session, no terminal; ssh, a cloud session). It
  printed a command. Give it to the user to run in their own terminal, then read the verdict from
  the result file it names.

`--file` is the consumer's call: when its own code reads a specific file (Telegram reads
`~/.claude/channels/telegram/.env`), write there. Otherwise leave it at the shared default,
`${CLAUDE_CONFIG_DIR:-~/.claude}/secrets/.env`. `set` replaces only that key's line and keeps the
rest of the file.

Do not call `osascript … with hidden answer`, `zenity --password` or `Get-Credential` yourself.
They return the typed value on stdout, which is your transcript.

## Check and use

```bash
python3 "$SECRET" has KEY [--file PATH]                    # set (environment) / set (file) / missing
python3 "$SECRET" run KEY[,KEY2] [--file PATH] -- cmd args # cmd runs with the keys in its environment
```

`run` is how an ad-hoc command gets a secret it reads from the environment, e.g.
`run GITHUB_TOKEN -- gh api user`. The value never appears in the command you write, but the
command's output does reach you, so don't run anything that echoes its environment.

A variable already set in the real environment wins over the file, both in `has` and `run`.

## Already pasted

If the user pastes a secret into the chat anyway, it is in the transcript now. Do not store that
copy. Tell them so plainly, suggest revoking or rotating it where it was issued, and collect the
new value with `set`.

## Windows

The scripts are stdlib Python and use the same commands. Where `python3` is missing, `python` or
`py -3` runs them. `chmod` is a no-op there: the file's protection is the user-profile ACL. The
Windows dialog path has not been tested yet, so if it fails, the terminal fallback (exit 3) still
works.
