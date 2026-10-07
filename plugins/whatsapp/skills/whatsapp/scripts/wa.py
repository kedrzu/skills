#!/usr/bin/env python3
"""Read WhatsApp chats from the macOS desktop app's local database - read-only.

    wa.py chats [QUERY] [-n N]                        chats, most recent first
    wa.py messages [--chat C] [--grep T] [--since D] [--until D] [-n N]
                                                      messages, oldest first (the last N)
    wa.py media --chat C [--kind K] [--since D] [--until D] [-n N] [--copy DIR]
                                                      attachments with their file paths

C is a chat name (case- and accent-insensitive substring), a JID, or a phone number. An
ambiguous C prints the candidates and exits 2. Dates are YYYY-MM-DD[ HH:MM], local time.

The app keeps everything in ChatStorage.sqlite under its group container; attachments live
under Message/ next to it, at the path ZWAMEDIAITEM.ZMEDIALOCALPATH holds. The database is
opened with mode=ro, which still reads the WAL, so messages from the last minutes are there
while the app runs.

Exit: 0 ok · 1 database missing or unreadable · 2 bad arguments / chat not found or ambiguous

Python 3 stdlib only.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

ROOT = Path.home() / "Library/Group Containers/group.net.whatsapp.WhatsApp.shared"
DB = ROOT / "ChatStorage.sqlite"
APPLE_EPOCH = 978307200  # ZMESSAGEDATE counts seconds from 2001-01-01 UTC

KINDS = {1: "image", 2: "video", 3: "audio", 4: "contact", 5: "location", 6: "system",
         8: "document", 14: "deleted", 15: "sticker"}
SESSION_KINDS = {0: "dm", 1: "group", 2: "broadcast", 3: "status", 4: "community"}


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.casefold().replace("ł", "l"))
    return "".join(c for c in s if not unicodedata.combining(c))


def connect() -> sqlite3.Connection:
    if not DB.exists():
        sys.exit(f"No WhatsApp database at {DB} - is the WhatsApp desktop app installed and logged in?")
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        con.execute("SELECT 1 FROM ZWAMESSAGE LIMIT 1")
    except sqlite3.Error as e:
        sys.exit(f"Cannot read {DB}: {e}. If it is 'authorization denied', grant the terminal "
                 "Full Disk Access in System Settings → Privacy & Security.")
    con.row_factory = sqlite3.Row
    return con


def to_apple(text: str) -> float:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).timestamp() - APPLE_EPOCH
        except ValueError:
            pass
    raise SystemExit(2) from None


def stamp(apple: float | None) -> str:
    return datetime.fromtimestamp(apple + APPLE_EPOCH).strftime("%Y-%m-%d %H:%M") if apple else "?"


def chat_rows(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT Z_PK, ZPARTNERNAME, ZCONTACTJID, ZSESSIONTYPE, ZLASTMESSAGEDATE, "
        "(SELECT count(*) FROM ZWAMESSAGE m WHERE m.ZCHATSESSION = s.Z_PK) AS n "
        "FROM ZWACHATSESSION s WHERE ZREMOVED = 0 ORDER BY ZLASTMESSAGEDATE DESC").fetchall()


def matches(row: sqlite3.Row, query: str) -> bool:
    jid = row["ZCONTACTJID"] or ""
    digits = "".join(c for c in query if c.isdigit())
    return (fold(query) in fold(row["ZPARTNERNAME"] or "") or query == jid
            or (len(digits) >= 6 and jid.startswith(digits)))


def resolve(con: sqlite3.Connection, query: str) -> sqlite3.Row:
    rows = [r for r in chat_rows(con) if matches(r, query)]
    exact = [r for r in rows if fold(r["ZPARTNERNAME"] or "") == fold(query)]
    if len(exact) == 1 or len(rows) == 1:
        return (exact or rows)[0]
    print(f"{'No chat matches' if not rows else 'Several chats match'} {query!r}.", file=sys.stderr)
    print_chats(rows[:20], sys.stderr)
    sys.exit(2)


def print_chats(rows: list[sqlite3.Row], out=sys.stdout) -> None:
    for r in rows:
        kind = SESSION_KINDS.get(r["ZSESSIONTYPE"], "?")
        print(f"{stamp(r['ZLASTMESSAGEDATE'])}  {kind:<9} {r['n']:>6}  "
              f"{r['ZPARTNERNAME'] or '(no name)'}  <{r['ZCONTACTJID']}>", file=out)


def message_query(args, extra_where: str = "") -> tuple[str, list]:
    where, params = ["1=1"], []
    if args.chat:
        where.append("m.ZCHATSESSION = ?")
        params.append(args.chat_pk)
    if getattr(args, "grep", None):
        where.append("m.ZTEXT LIKE ?")
        params.append(f"%{args.grep}%")
    if args.since:
        where.append("m.ZMESSAGEDATE >= ?")
        params.append(to_apple(args.since))
    if args.until:
        where.append("m.ZMESSAGEDATE < ?")
        params.append(to_apple(args.until))
    sql = (
        "SELECT * FROM (SELECT m.Z_PK, m.ZMESSAGEDATE, m.ZISFROMME, m.ZMESSAGETYPE, m.ZTEXT, "
        "pn.ZPUSHNAME AS pushname, s.ZPARTNERNAME AS chat, s.ZSESSIONTYPE, gm.ZCONTACTNAME AS member, "
        "gm.ZMEMBERJID, mi.ZMEDIALOCALPATH, mi.ZFILESIZE, mi.ZTITLE, mi.ZVCARDNAME, "
        "mi.ZLATITUDE, mi.ZLONGITUDE "
        "FROM ZWAMESSAGE m JOIN ZWACHATSESSION s ON s.Z_PK = m.ZCHATSESSION "
        "LEFT JOIN ZWAGROUPMEMBER gm ON gm.Z_PK = m.ZGROUPMEMBER "
        "LEFT JOIN ZWAPROFILEPUSHNAME pn ON pn.ZJID = gm.ZMEMBERJID "
        "LEFT JOIN ZWAMEDIAITEM mi ON mi.Z_PK = m.ZMEDIAITEM "
        f"WHERE {' AND '.join(where)} {extra_where} "
        "ORDER BY m.ZMESSAGEDATE DESC LIMIT ?) ORDER BY ZMESSAGEDATE")
    return sql, params + [args.n]


def sender(r: sqlite3.Row) -> str:
    if r["ZISFROMME"]:
        return "me"
    if r["ZSESSIONTYPE"] == 0:
        return r["chat"] or "?"
    # m.ZPUSHNAME is an opaque blob, not a name; the profile table holds the real push names
    return (r["member"] or r["pushname"] or r["ZMEMBERJID"] or "?").strip()


def file_path(r: sqlite3.Row) -> Path | None:
    return ROOT / "Message" / r["ZMEDIALOCALPATH"] if r["ZMEDIALOCALPATH"] else None


def body(r: sqlite3.Row) -> str:
    kind, text = KINDS.get(r["ZMESSAGETYPE"]), r["ZTEXT"] or ""
    if kind is None and r["ZMEDIALOCALPATH"]:
        kind = "file"
    if kind is None or kind == "system":
        return text or f"[type {r['ZMESSAGETYPE']}]"
    if kind == "deleted":
        return "[deleted]"
    if kind == "location":
        return f"[location {r['ZLATITUDE']:.5f},{r['ZLONGITUDE']:.5f}] {text}".rstrip()
    if kind == "contact":
        return f"[contact {r['ZVCARDNAME'] or ''}]".replace(" ]", "]")
    path = file_path(r)
    where = str(path) if path and path.exists() else "not downloaded"
    label = text if kind == "document" else ""  # a document's ZTEXT is its file name
    caption = "" if kind == "document" else (r["ZTITLE"] or text)
    return f"[{kind} {label} {where}] {caption}".replace("  ", " ").replace("[ ", "[").rstrip()


def cmd_chats(con, args) -> None:
    rows = chat_rows(con)
    print_chats([r for r in rows if not args.query or matches(r, args.query)][: args.n])


def cmd_messages(con, args) -> None:
    sql, params = message_query(args)
    for r in con.execute(sql, params):
        where = "" if args.chat else f"[{r['chat'] or '?'}] "
        print(f"{stamp(r['ZMESSAGEDATE'])}  {where}{sender(r)}: {body(r)}".replace("\n", "\n    "))


def cmd_media(con, args) -> None:
    types = [t for t, k in KINDS.items() if k == args.kind] if args.kind else [1, 2, 3, 8, 11, 15]
    sql, params = message_query(args, f"AND (m.ZMESSAGETYPE IN ({','.join(map(str, types))})"
                                      + ("" if args.kind else " OR mi.ZMEDIALOCALPATH IS NOT NULL") + ")")
    target = Path(args.copy).expanduser() if args.copy else None
    if target:
        target.mkdir(parents=True, exist_ok=True)
    for r in con.execute(sql, params):
        path = file_path(r)
        size = f"{(r['ZFILESIZE'] or 0) / 1024:,.0f} KB"
        print(f"{stamp(r['ZMESSAGEDATE'])}  {sender(r)}: {body(r)}  ({size})")
        if target and path and path.exists():
            name = r["ZTEXT"] if r["ZMESSAGETYPE"] == 8 and r["ZTEXT"] else path.name
            if not Path(name).suffix:
                name += path.suffix
            dest = target / f"{stamp(r['ZMESSAGEDATE']).replace(':', '').replace(' ', '_')}_{Path(name).name}"
            shutil.copy2(path, dest)
            print(f"    → {dest}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("chats")
    c.add_argument("query", nargs="?")
    c.add_argument("-n", type=int, default=30)
    for name in ("messages", "media"):
        s = sub.add_parser(name)
        s.add_argument("--chat", required=name == "media")
        s.add_argument("--since")
        s.add_argument("--until")
        s.add_argument("-n", type=int, default=200 if name == "messages" else 50)
        if name == "messages":
            s.add_argument("--grep")
        else:
            s.add_argument("--kind", choices=["image", "video", "audio", "document", "sticker"])
            s.add_argument("--copy", metavar="DIR")
    args = p.parse_args()
    for d in ("since", "until"):
        if getattr(args, d, None):
            try:
                to_apple(getattr(args, d))
            except SystemExit:
                p.error(f"--{d} must be YYYY-MM-DD or 'YYYY-MM-DD HH:MM'")
    con = connect()
    if getattr(args, "chat", None):
        args.chat_pk = resolve(con, args.chat)["Z_PK"]
    {"chats": cmd_chats, "messages": cmd_messages, "media": cmd_media}[args.cmd](con, args)


if __name__ == "__main__":
    main()
