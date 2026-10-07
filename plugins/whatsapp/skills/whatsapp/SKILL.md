---
name: whatsapp
description: Read the user's WhatsApp chats and attachments on this Mac, straight from the WhatsApp desktop app's local database — list chats, read a conversation, search messages, find and copy the files someone sent. Use when the user says "sprawdź moją rozmowę z X na WhatsAppie", "co mi pisał X", "znajdź na WhatsAppie…", "co było na grupie Y", "wyciągnij plik / PDF / zdjęcie, które X przysłał", "check my WhatsApp chat with…", or otherwise asks about something said or sent on WhatsApp. Read-only — it cannot send messages.
---

# WhatsApp — reading local chats

WhatsApp has no API for a personal account, and none is needed: the macOS desktop app keeps
the whole history in a plain SQLite database, and `scripts/wa.py` reads it read-only.

```bash
WA="python3 -I ${CLAUDE_PLUGIN_ROOT}/skills/whatsapp/scripts/wa.py"
$WA chats [QUERY]                                    # find a chat: name, kind, message count, JID
$WA messages --chat "Anna" --since 2026-10-01       # read a conversation, oldest first
$WA messages --grep "faktura" [--chat …] [-n 50]     # search, across all chats without --chat
$WA media --chat "Anna" --kind document             # attachments with their paths on disk
$WA media --chat "Anna" --since 2026-09-01 --copy ~/Downloads/wa   # copy them out, named by date
```

`--chat` takes a name fragment (case- and accent-insensitive), a JID or a phone number. When
it matches several chats the script lists them and exits 2: pick the right one, or ask the
user if the names don't settle it. `messages` returns the **last** `-n` messages in the range
(200 by default), so narrow with `--since`/`--until` rather than raising `-n`.

Read only what the question needs. Everything printed stays in the session transcript,
including other people's messages, so prefer a date range or `--grep` over dumping a whole
chat.

## Files

A downloaded attachment is an ordinary file, and the path is printed next to the message.
Read it in place, or `--copy` it out, which restores a document's original name. `not
downloaded` means the app never fetched it on this Mac. The CDN copy is encrypted and expires,
so the fix is for the user to open the chat in WhatsApp and download the file, then rerun.

## Beyond the script

For anything the script doesn't answer (counts, who wrote most, starred messages), query the
database directly:

- Database: `~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite`.
  Open it with `sqlite3 "file:…?mode=ro"`. Never use `immutable=1`, because that skips the WAL
  and with it the latest messages.
- `ZWACHATSESSION`: chats. `ZPARTNERNAME`, `ZCONTACTJID`, and `ZSESSIONTYPE` (0 dm, 1 group,
  3 status, 4 community).
- `ZWAMESSAGE`: `ZCHATSESSION` → chat, `ZTEXT`, `ZISFROMME`, `ZMESSAGETYPE` (0 text, 1 image,
  2 video, 3 audio, 4 contact, 5 location, 6 system, 8 document — `ZTEXT` is then the file
  name, 14 deleted, 15 sticker), `ZGROUPMEMBER` → `ZWAGROUPMEMBER.ZCONTACTNAME` (the sender
  in groups), `ZMEDIAITEM` → `ZWAMEDIAITEM`, `ZSTARRED`.
- `ZMESSAGEDATE` counts seconds from 2001-01-01. Add `978307200` for Unix time.
- `ZWAMEDIAITEM.ZMEDIALOCALPATH` is relative to `Message/` next to the database. NULL means not
  downloaded.
- `ZWAMESSAGE.ZPUSHNAME` is an opaque blob, not a name. Push names are in `ZWAPROFILEPUSHNAME`.

## When it does not work

| Symptom | Cause |
|---|---|
| `No WhatsApp database` | The desktop app is not installed or never logged in on this Mac. The phone's history is not reachable from here. |
| `authorization denied` | macOS blocks the terminal from other apps' data. The user grants Full Disk Access to the terminal app in System Settings → Privacy & Security. |
| A chat or old messages missing | The desktop app only holds what it synced when it was linked. |
| A request to send or reply | Not possible here. The unofficial linked-device bridges risk a ban of the account, so tell the user rather than reaching for one. |
