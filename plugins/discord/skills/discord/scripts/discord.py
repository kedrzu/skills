#!/usr/bin/env python3
"""Read Discord conversations through the desktop app the user is logged into — no bot, no token.

Discord's desktop client is Chromium, and its HTTP cache keeps the message pages it loads
(`/api/v9/channels/<id>/messages`, gzip JSON). `harvest` copies them into a local store; `sync`
makes the client load more by opening a channel and scrolling it up (Accessibility API + key
presses); `status`, `search` and `read` work on the store alone, offline.

Store: $DISCORD_STORE, default ~/.context/discord/
  messages/<channel_id>.jsonl   one message per line, oldest first
  channels.json                 channel_id -> name, server, kind, sync history
  harvest.json                  cache files already read (name -> mtime)
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
STORE = Path(os.environ.get("DISCORD_STORE", Path.home() / ".context" / "discord"))
SUPPORT = Path.home() / "Library" / "Application Support"
CACHE_DIRS = [SUPPORT / d / "Cache" / "Cache_Data" for d in ("discord", "discordptb", "discordcanary")]
SIMPLE_CACHE_MAGIC = 0xFCFB6D1BA7725C30
KEY_URL = re.compile(rb"https://discord\.com/api/v\d+/channels/(\d+)/messages(?:\?[^\s\x00]*)?")
DISCORD_EPOCH_MS = 1420070400000


# ---------------------------------------------------------------- store


def load_json(path, default):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True))
    tmp.replace(path)


def channels_meta():
    return load_json(STORE / "channels.json", {})


def channel_file(cid):
    return STORE / "messages" / f"{cid}.jsonl"


def load_channel(cid):
    path = channel_file(cid)
    if not path.exists():
        return {}
    return {m["id"]: m for m in map(json.loads, path.read_text().splitlines()) if m}


def save_channel(cid, msgs):
    path = channel_file(cid)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as f:
        for m in sorted(msgs.values(), key=lambda m: int(m["id"])):
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    tmp.replace(path)


def slim(m):
    """Keeps what a reader needs; the raw API object is several times larger."""
    a = m.get("author") or {}
    out = {
        "id": m["id"],
        "ts": m["timestamp"][:19],
        "author": a.get("global_name") or a.get("username") or "?",
        "username": a.get("username"),
        "content": m.get("content") or "",
    }
    if m.get("edited_timestamp"):
        out["edited"] = m["edited_timestamp"][:19]
    if (ref := m.get("message_reference")) and ref.get("message_id"):
        out["reply_to"] = ref["message_id"]
    if m.get("attachments"):
        out["attachments"] = [{"name": x.get("filename"), "url": x.get("url")} for x in m["attachments"]]
    embeds = [
        {k: e[k] for k in ("title", "description", "url") if e.get(k)} for e in m.get("embeds") or []
    ]
    if any(embeds):
        out["embeds"] = [e for e in embeds if e]
    if m.get("thread"):
        out["thread"] = {"id": m["thread"]["id"], "name": m["thread"].get("name")}
    if m.get("type") not in (0, 19, None):  # 0 default, 19 reply; others are joins, pins, boosts…
        out["type"] = m["type"]
    if m.get("reactions"):
        out["reactions"] = sum(r.get("count", 0) for r in m["reactions"])
    return out


# ---------------------------------------------------------------- cache


def read_cache_entry(path):
    """Chromium simple-cache entry: header (24 B), key, then the body (stream 1). Returns
    (channel_id, messages) for a channel-messages response, else None."""
    with path.open("rb") as f:
        head = f.read(24)
        if len(head) < 24 or struct.unpack_from("<Q", head)[0] != SIMPLE_CACHE_MAGIC:
            return None
        key_len = struct.unpack_from("<I", head, 12)[0]
        key = f.read(key_len)
        m = KEY_URL.search(key)
        if not m:
            return None
        body = f.read()
    if body[:2] == b"\x1f\x8b":
        body = zlib.decompressobj(wbits=31).decompress(body)  # stops at the gzip stream's end
    try:
        # An uncompressed body is followed by the entry's end record: parse the leading JSON only.
        data, _ = json.JSONDecoder().raw_decode(body.decode("utf-8", errors="replace"))
    except ValueError:
        return None  # truncated/evicted body, or an encoding we do not read
    if not isinstance(data, list):
        return None
    return m.group(1).decode(), data


def harvest(full=False, quiet=False):
    """Copies new message pages from the cache into the store. Returns ({channel_id: added},
    {channel_id: oldest timestamp among the pages read now}) — the second is what a running sync
    watches, since it shows what Discord loaded just now, whether or not it was stored before."""
    seen = {} if full else load_json(STORE / "harvest.json", {})
    by_channel = {}
    for cache in CACHE_DIRS:
        if not cache.is_dir():
            continue
        for path in cache.glob("*_0"):
            try:
                mtime = path.stat().st_mtime
            except FileNotFoundError:
                continue  # evicted while we were listing
            tag = f"{cache.parent.parent.name}/{path.name}"
            if seen.get(tag) == mtime:
                continue
            seen[tag] = mtime
            try:
                entry = read_cache_entry(path)
            except (OSError, zlib.error):
                continue
            if entry:
                by_channel.setdefault(entry[0], []).extend(entry[1])
    added, oldest_seen = {}, {}
    for cid, raw in by_channel.items():
        msgs = load_channel(cid)
        before = len(msgs)
        for m in raw:
            if isinstance(m, dict) and "id" in m and "timestamp" in m:
                new = slim(m)
                oldest_seen[cid] = min(oldest_seen.get(cid, "9999"), new["ts"])
                old = msgs.get(new["id"])
                if old is None or new.get("edited", "") >= old.get("edited", ""):
                    msgs[new["id"]] = new
        save_channel(cid, msgs)
        if len(msgs) > before:
            added[cid] = len(msgs) - before
    save_json(STORE / "harvest.json", seen)
    if not quiet:
        meta = channels_meta()
        total = sum(added.values())
        print(f"harvest: +{total} messages" + "".join(f"\n  {name_of(c, meta)}: +{n}" for c, n in added.items()))
    return added, oldest_seen


# ---------------------------------------------------------------- helpers


def snowflake_time(sid):
    return dt.datetime.fromtimestamp(((int(sid) >> 22) + DISCORD_EPOCH_MS) / 1000, dt.timezone.utc)


def parse_when(s):
    """'2026-11-01', '2026-11-01T10:00', or relative: '7d', '12h', '3w'. Returned as UTC ISO."""
    if not s:
        return None
    if m := re.fullmatch(r"(\d+)([hdw])", s):
        hours = int(m[1]) * {"h": 1, "d": 24, "w": 168}[m[2]]
        return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
    return s


def name_of(cid, meta):
    c = meta.get(cid)
    return f"#{c['name']} ({c.get('server', '?')})" if c and c.get("name") else f"#<{cid}>"


def resolve_channels(spec, meta, server=None):
    """A channel name, a fragment of one, or an id. Several matches across servers → all of them,
    narrowed by --server when given."""
    if spec is None:
        cids = set(meta) | {p.stem for p in (STORE / "messages").glob("*.jsonl")}
    elif spec.isdigit():
        cids = {spec}
    else:
        s = spec.lstrip("#").lower()
        exact = {c for c, v in meta.items() if (v.get("name") or "").lower() == s}
        cids = exact or {c for c, v in meta.items() if s in (v.get("name") or "").lower()}
        if not cids:
            sys.exit(f"No known channel matches '{spec}'. `channels` lists the open server's channels.")
    if server:
        s = server.lower()
        cids = {c for c in cids if s in (meta.get(c, {}).get("server") or "").lower()}
    return sorted(cids)


def message_link(m, cid, meta):
    gid = meta.get(cid, {}).get("guild_id", "@me")
    return f"https://discord.com/channels/{gid}/{cid}/{m['id']}"


def fmt(m, cid, meta, width, show_channel):
    ch = f"{name_of(cid, meta)}  " if show_channel else ""
    text = m["content"]
    for a in m.get("attachments", []):
        text += f" [file: {a['name']}]"
    for e in m.get("embeds", []):
        text += " [embed: " + " — ".join(e.get(k, "") for k in ("title", "description") if e.get(k))[:200] + "]"
    if m.get("thread"):
        text += f" [thread: {m['thread']['name']}]"
    if m.get("reply_to"):
        text = f"↪{m['reply_to'][-6:]} " + text
    text = text.replace("\n", " ⏎ ") if width else text
    if width and len(text) > width:
        text = text[: width - 1] + "…"
    return f"{m['ts'].replace('T', ' ')[:16]}  {ch}{m['author']}: {text}  ·{m['id'][-6:]}"


# ---------------------------------------------------------------- app control


def ax(*args):
    """Runs ax.swift, compiled once per source version into ~/.cache (a cold `swift` run costs
    seconds; the binary answers in under one)."""
    src = HERE / "ax.swift"
    digest = hashlib.sha1(src.read_bytes()).hexdigest()[:12]
    binary = Path.home() / ".cache" / "discord-skill" / f"ax-{digest}"
    if not binary.exists():
        binary.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["swiftc", "-O", str(src), "-o", str(binary)], capture_output=True, text=True)
        if r.returncode:
            sys.exit(f"Compiling ax.swift failed (needs Xcode Command Line Tools: xcode-select --install):\n{r.stderr}")
    r = subprocess.run([str(binary), *args], capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr.strip() or f"ax {' '.join(args)} failed")
    return json.loads(r.stdout)


def remember_channels(state):
    """Stores the names the sidebar shows; the cache has ids only."""
    meta = channels_meta()
    server = next((s["name"] for s in state.get("servers", []) if state.get("title", "").endswith(f"| {s['name']} - Discord")), None)
    if not server and " | " in state.get("title", ""):
        server = state["title"].rsplit(" | ", 1)[1].removesuffix(" - Discord")
    for c in state.get("channels", []):
        if not c.get("name"):
            continue
        entry = meta.setdefault(c["channel_id"], {})
        entry.update(name=c["name"], kind=c.get("kind"), guild_id=c["guild_id"])
        if server and c["guild_id"] == state.get("guild_id"):
            entry["server"] = server
    save_json(STORE / "channels.json", meta)
    return meta, server


def osa(script):
    return subprocess.run(["osascript", "-e", script], capture_output=True, text=True).stdout.strip()


def frontmost():
    return osa('tell application "System Events" to get name of first process whose frontmost is true')


def page_up(n, pause):
    osa(
        'tell application "System Events"\n'
        f"repeat {n} times\nkey code 116\ndelay {pause}\nend repeat\nend tell"
    )


# ---------------------------------------------------------------- commands


def cmd_harvest(a):
    harvest(full=a.full)


def cmd_status(a):
    meta = channels_meta()
    rows = []
    for cid in resolve_channels(a.channel, meta, a.server):
        msgs = load_channel(cid)
        c = meta.get(cid, {})
        if not msgs and not a.all:
            continue
        ts = sorted(m["ts"] for m in msgs.values())
        cov = c.get("covered")
        rows.append(
            (
                name_of(cid, meta),
                len(msgs),
                ts[0][:10] if ts else "-",
                ts[-1][:16].replace("T", " ") if ts else "-",
                (("start" if cov.get("top") else cov["from"]["ts"][:10]) + " → " + cov["to"][:16].replace("T", " "))
                if cov else "-",
            )
        )
    if not rows:
        print("Store is empty. `harvest` copies what Discord has cached; `sync` fetches a channel.")
        return
    w = max(len(r[0]) for r in rows)
    print(f"{'channel':<{w}}  {'msgs':>6}  {'oldest':<10}  {'newest':<16}  gap-free (last sync)")
    for r in sorted(rows, key=lambda r: r[3], reverse=True):
        print(f"{r[0]:<{w}}  {r[1]:>6}  {r[2]:<10}  {r[3]:<16}  {r[4]}")
    print("\nOutside the gap-free range the store holds only what Discord happened to cache: expect gaps.")


def iter_messages(a, meta):
    since, until = parse_when(a.since), parse_when(a.until)
    for cid in resolve_channels(a.channel, meta, a.server):
        for m in load_channel(cid).values():
            if since and m["ts"] < since:
                continue
            if until and m["ts"] > until:
                continue
            if a.author and a.author.lower() not in f"{m['author']} {m.get('username') or ''}".lower():
                continue
            yield cid, m


def cmd_search(a):
    meta = channels_meta()
    if a.regex:
        pat = re.compile(a.query, re.I)
        match = lambda t: pat.search(t)
    else:
        terms = a.query.lower().split()
        match = lambda t: all(term in t.lower() for term in terms)
    hits = []
    for cid, m in iter_messages(a, meta):
        hay = m["content"] + " " + " ".join(
            f"{e.get('title', '')} {e.get('description', '')}" for e in m.get("embeds", [])
        ) + " " + " ".join(x["name"] or "" for x in m.get("attachments", []))
        if match(hay):
            hits.append((cid, m))
    hits.sort(key=lambda h: h[1]["ts"])
    shown = hits[-a.n :]
    for cid, m in shown:
        print(fmt(m, cid, meta, a.width, True))
    print(f"\n{len(hits)} hits" + (f", showing the last {len(shown)}" if len(hits) > len(shown) else ""))


def cmd_read(a):
    meta = channels_meta()
    rows = sorted(iter_messages(a, meta), key=lambda h: h[1]["ts"])
    many = len({c for c, _ in rows}) > 1
    if a.around:
        idx = next((i for i, (_, m) in enumerate(rows) if m["id"].endswith(a.around)), None)
        if idx is None:
            sys.exit(f"No message ending in {a.around} in that selection.")
        rows = rows[max(0, idx - a.n // 2) : idx + a.n // 2 + 1]
    elif len(rows) > a.n:
        print(f"[{len(rows) - a.n} earlier messages not shown; narrow with --since or raise -n]")
        rows = rows[-a.n :]
    for cid, m in rows:
        print(fmt(m, cid, meta, 0 if a.full else a.width, many))
        if a.links:
            print("   " + message_link(m, cid, meta))


def cmd_channels(a):
    if a.server:
        state = ax("open-server", a.server)
    else:
        state = ax("state")
    meta, server = remember_channels(state)
    print(f"Open: {state.get('title')}\nServers: " + ", ".join(
        s["name"] + (f" ({s['status']})" if s.get("status") else "") for s in state.get("servers", [])
    ))
    print(f"\nChannels of {server}:")
    for c in state.get("channels", []):
        cid = c["channel_id"]
        n = len(load_channel(cid))
        flag = f"  [{c['status']}]" if c.get("status") else ""
        print(f"  #{c.get('name', '?'):<34} {c.get('kind', ''):<20} stored {n:>6}{flag}")


def cmd_sync(a):
    since = parse_when(a.since)
    state = ax("state")
    if a.server:
        state = ax("open-server", a.server)
    meta, server = remember_channels(state)
    targets = sorted({c for spec in a.channel or [] for c in resolve_channels(spec, meta)})
    # A name like #general exists on many servers: prefer the open server's.
    targets = [c for c in targets if meta.get(c, {}).get("guild_id") == state.get("guild_id")] or targets
    if not targets:
        sys.exit("Name a channel (--channel); `channels` lists them.")
    previous = frontmost()
    try:
        for cid in targets:
            sync_channel(cid, since, a, meta)
    finally:
        if previous and previous != "Discord":
            osa(f'tell application "{previous}" to activate')
    harvest(quiet=True)


def sync_channel(cid, since, a, meta):
    """Keeps one gap-free range per channel, `covered` = [from, to], and widens it:
    1. jump to the present and scroll up until the pages meet `covered.to` — the range now
       reaches the present;
    2. jump to `covered.from` with a message link and scroll up from there to --since or the
       channel's first message.
    A sync cut short (--max-minutes) still leaves a valid range, so the next one resumes."""
    label = name_of(cid, meta)
    entry = meta.setdefault(cid, {})
    if "forum" in (entry.get("kind") or "").lower():
        print(f"{label}: a forum — its posts are threads with their own ids; open a post and sync that.")
        return
    covered = entry.get("covered")
    deadline = time.time() + a.max_minutes * 60
    now_ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    if not entry.get("guild_id"):
        print(f"{label}: unknown server; run `channels` on its server first.")
        return
    harvest(quiet=True)  # flush older cache pages so they do not count as "loaded now"
    # Discord reopens a channel where it was last scrolled, not at the newest message. A link to a
    # message id made from the current time makes it load the messages around now instead.
    open_url(cid, entry, str((int(time.time() * 1000) - DISCORD_EPOCH_MS) << 22))
    if covered:
        print(f"{label}: catching up to {covered['to'][:16]}", flush=True)
        reached, why = scroll_until(cid, lambda t: t <= covered["to"], a, deadline)
        if why != "reached":
            print(f"{label}: {why} before meeting the stored range; it stays as it was.")
            return
        covered["to"] = now_ts
    else:
        covered = None
    want = lambda t: bool(since) and t <= since
    if covered and (covered.get("top") or want(covered["from"]["ts"])):
        pass  # already as far back as asked
    else:
        if covered:
            print(f"{label}: jumping back to {covered['from']['ts'][:16]}", flush=True)
            open_url(cid, entry, covered["from"]["id"])
        else:
            print(f"{label}: scrolling up to {since or 'the start'}", flush=True)
        reached, why = scroll_until(cid, want, a, deadline)
        first = next((m for m in load_channel(cid).values() if m["ts"] == reached), None)
        if first:
            covered = covered or {"to": now_ts}
            if not covered.get("from") or first["ts"] < covered["from"]["ts"]:
                covered["from"] = {"id": first["id"], "ts": first["ts"]}
            covered["top"] = why == "top"
        if why == "timeout":
            print(f"{label}: stopped after {a.max_minutes} min (--max-minutes); the next sync resumes here.")
    if covered:
        covered["at"] = now_ts
        entry["covered"] = covered
        save_json(STORE / "channels.json", {**channels_meta(), cid: entry})
        print(f"{label}: gap-free from {covered['from']['ts'][:16]}{' (start of channel)' if covered.get('top') else ''}"
              f" to now, {len(load_channel(cid))} stored.")


def open_url(cid, entry, message_id=""):
    url = f"discord://discord.com/channels/{entry.get('guild_id', '@me')}/{cid}" + (f"/{message_id}" if message_id else "")
    subprocess.run(["open", url], check=True)
    time.sleep(2.5)


def scroll_until(cid, stop, a, deadline):
    """Presses Page Up in Discord until stop(oldest timestamp loaded during this call) holds.
    Returns (that timestamp, 'reached' | 'top' | 'timeout')."""
    reached, stalled = "9999", 0
    while True:
        if time.time() > deadline:
            return reached, "timeout"
        if frontmost() != "Discord":
            osa('tell application "Discord" to activate')
            time.sleep(0.6)
            if frontmost() != "Discord":
                sys.exit("Discord would not stay in front (the user switched away?); stopped.")
        if stalled in (0, a.patience // 2):
            ax("focus-messages")  # keys go to the focused element; make it the message list
        page_up(a.pages, a.pause)
        time.sleep(1.0)  # let the page request finish and land in the cache
        _, seen = harvest(quiet=True)
        t = seen.get(cid, "9999")
        if t < reached:
            reached, stalled = t, 0
            print(f"  back to {reached[:16]}  ({len(load_channel(cid))} stored)", flush=True)
            if stop(reached):
                return reached, "reached"
        else:
            stalled += 1
            if stalled >= a.patience:
                return reached, "top"  # nothing older loads: the channel's first message


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def scope(sp):
        sp.add_argument("--channel", "-c", help="name, fragment or id; all channels when omitted")
        sp.add_argument("--server", "-s", help="server name fragment")

    def window(sp):
        sp.add_argument("--since", help="2026-11-01, 2026-11-01T10:00, or 7d / 12h / 3w")
        sp.add_argument("--until")
        sp.add_argument("--author", "-a", help="display or user name fragment")

    sp = sub.add_parser("harvest", help="copy message pages from Discord's cache into the store")
    sp.add_argument("--full", action="store_true", help="re-read every cache file")
    sp.set_defaults(fn=cmd_harvest)

    sp = sub.add_parser("status", help="what the store holds per channel")
    scope(sp)
    sp.add_argument("--all", action="store_true", help="include known channels with no messages")
    sp.set_defaults(fn=cmd_status)

    sp = sub.add_parser("search", help="find messages in the store")
    sp.add_argument("query", help="words that must all appear (case-insensitive), or a regex with --regex")
    sp.add_argument("--regex", "-E", action="store_true")
    sp.add_argument("-n", type=int, default=100, help="show at most N (the latest)")
    sp.add_argument("--width", type=int, default=300, help="truncate each line (0 = full)")
    scope(sp)
    window(sp)
    sp.set_defaults(fn=cmd_search)

    sp = sub.add_parser("read", help="messages in order, from the store")
    scope(sp)
    window(sp)
    sp.add_argument("-n", type=int, default=300, help="at most N (the latest in the range)")
    sp.add_argument("--around", help="a message id (or its last digits): N messages around it")
    sp.add_argument("--width", type=int, default=600)
    sp.add_argument("--full", action="store_true", help="no truncation, keep newlines")
    sp.add_argument("--links", action="store_true", help="print a jump link under each message")
    sp.set_defaults(fn=cmd_read)

    sp = sub.add_parser("channels", help="servers and the open server's channels (from the app)")
    sp.add_argument("--server", "-s", help="switch to this server first")
    sp.set_defaults(fn=cmd_channels)

    sp = sub.add_parser("sync", help="open a channel in the app and scroll back, storing what loads")
    sp.add_argument("--channel", "-c", action="append", help="repeatable")
    sp.add_argument("--server", "-s", help="switch to this server first")
    sp.add_argument("--since", help="how far back; the channel's start when omitted")
    sp.add_argument("--max-minutes", type=float, default=10)
    sp.add_argument("--pages", type=int, default=3, help="Page Up presses per round")
    sp.add_argument("--pause", type=float, default=0.4, help="seconds between presses")
    sp.add_argument("--patience", type=int, default=4, help="rounds with nothing older before calling it the start")
    sp.set_defaults(fn=cmd_sync)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
