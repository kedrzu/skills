#!/usr/bin/env python3
"""Telegram notifications - a one-way channel from the agent to the user's phone.

Why a hand-rolled client instead of an off-the-shelf MCP server: every narrow
Telegram notifier on the registries is a weekend project with 0-22 stars, and
everything with traction is an MTProto userbot wanting api_id, api_hash and an
SMS-login session string - the whole account, just to send a push. This is
~250 lines of stdlib against one documented HTTPS endpoint.

Config lives OUTSIDE the plugin so it survives version bumps, and follows the
convention of the official telegram plugin so both can share a single bot:

    STATE_DIR = $TELEGRAM_STATE_DIR
             or ${CLAUDE_CONFIG_DIR:-~/.claude}/channels/telegram

    token:    $TELEGRAM_BOT_TOKEN -> STATE_DIR/.env         (file 0600, dir 0700)
    chat id:  $TELEGRAM_CHAT_ID   -> STATE_DIR/notify.json
                                  -> STATE_DIR/access.json  (allowFrom[0])

There is deliberately no way to pass a chat id in: this client can only ever
reach the configured chat. A hijacked prompt has nothing to redirect.

    telegram_core.py send --text "Deploy finished"
    telegram_core.py send --stdin --format html
    telegram_core.py check
    telegram_core.py pair
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

# Overridable so the send path can be exercised against a stub in tests.
API_BASE = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org")

# Telegram rejects messages over 4096 chars; leave room for the " (1/3)" suffix.
HARD_LIMIT = 4096
CHUNK_CHARS = 3500

REQUEST_TIMEOUT = 30
RETRIES = 3


class TelegramError(Exception):
    pass


class ParseModeError(TelegramError):
    """Telegram refused the markup. Caller retries as plain text."""


# --------------------------------------------------------------------------
# Configuration

def state_dir() -> Path:
    override = os.environ.get("TELEGRAM_STATE_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    config = os.environ.get("CLAUDE_CONFIG_DIR", "").strip() or str(Path.home() / ".claude")
    return Path(config).expanduser() / "channels" / "telegram"


def read_env_file(path: Path) -> dict[str, str]:
    """Parse a simple KEY=value file. Data, not shell - nothing is executed."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_token() -> str:
    """Real env wins over the file - same precedence as the official plugin."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if token:
        return token
    token = read_env_file(state_dir() / ".env").get("TELEGRAM_BOT_TOKEN", "").strip()
    if token:
        return token
    raise TelegramError(
        "No Telegram bot token. Create a bot with @BotFather on Telegram (/newbot), "
        f"then run /telegram:setup <token> - it writes {state_dir() / '.env'} with mode 0600."
    )


def load_chat_id() -> str:
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if chat_id:
        return chat_id

    notify_file = state_dir() / "notify.json"
    if notify_file.is_file():
        try:
            saved = json.loads(notify_file.read_text(encoding="utf-8")).get("chat_id")
        except json.JSONDecodeError:
            saved = None
        if saved:
            return str(saved)

    # Interop: if the official telegram channel plugin is already paired, its
    # allowlist holds the numeric user id, which in a DM is also the chat id.
    access_file = state_dir() / "access.json"
    if access_file.is_file():
        try:
            allowed = json.loads(access_file.read_text(encoding="utf-8")).get("allowFrom") or []
        except json.JSONDecodeError:
            allowed = []
        if allowed:
            return str(allowed[0])

    raise TelegramError(
        "No Telegram chat id. Open your bot on Telegram and send it /start "
        "(a bot cannot message you first), then run /telegram:setup to pair."
    )


def save_chat_id(chat_id: str) -> Path:
    target = state_dir()
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = target / "notify.json"
    path.write_text(json.dumps({"chat_id": str(chat_id)}, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def save_token(token: str) -> Path:
    target = state_dir()
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = target / ".env"
    values = read_env_file(path)
    values["TELEGRAM_BOT_TOKEN"] = token
    body = "".join(f"{k}={v}\n" for k, v in values.items())
    path.write_text(body, encoding="utf-8")
    path.chmod(0o600)
    return path


# --------------------------------------------------------------------------
# HTTP

def explain(code: int, description: str) -> str:
    if code == 401:
        return ("Telegram rejected the bot token (401). It was revoked or mistyped - "
                "get a fresh one from @BotFather and run /telegram:setup <token>.")
    if code == 403 and "blocked" in description.lower():
        return ("The bot is blocked (403). Unblock it in Telegram and send it /start, "
                "then try again.")
    if code == 400 and "chat not found" in description.lower():
        return ("Telegram does not know this chat id (400). Send /start to the bot "
                "and re-pair with /telegram:setup.")
    if code == 409:
        return ("Another process is already long-polling this bot (409) - most likely a "
                "session running the official telegram channel plugin. Stop it, or take "
                "the chat id from access.json instead of polling.")
    return f"Telegram returned HTTP {code}: {description or '(no description)'}"


def api(method: str, token: str, body: dict | None = None) -> dict[str, Any]:
    url = f"{API_BASE}/bot{token}/{method}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Accept": "application/json"}
    if data:
        headers["Content-Type"] = "application/json"

    delay = 1
    for attempt in range(RETRIES):
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {}
            description = str(payload.get("description", raw[:300]))

            if exc.code == 429:
                wait = int(payload.get("parameters", {}).get("retry_after", delay))
                if attempt < RETRIES - 1:
                    time.sleep(wait)
                    continue
            if exc.code == 400 and "parse entities" in description.lower():
                raise ParseModeError(description) from exc
            if exc.code >= 500 and attempt < RETRIES - 1:
                time.sleep(delay)
                delay *= 3
                continue
            raise TelegramError(explain(exc.code, description)) from exc
        except urllib.error.URLError as exc:
            if attempt < RETRIES - 1:
                time.sleep(delay)
                delay *= 3
                continue
            raise TelegramError(f"Cannot reach api.telegram.org: {exc.reason}") from exc
    raise TelegramError("Telegram kept failing after retries.")


# --------------------------------------------------------------------------
# Text

def render_html(text: str) -> str:
    """Escape everything first, then re-introduce a whitelist of markup.

    Order matters: escaping after conversion would eat our own tags.
    """
    out = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    out = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", out)
    return out


def split_chunks(text: str, limit: int = CHUNK_CHARS) -> list[str]:
    """Split long text on the nicest boundary available. Never truncates."""
    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    rest = text
    while len(rest) > limit:
        window = rest[:limit]
        cut = -1
        for sep in ("\n\n", "\n", " "):
            candidate = window.rfind(sep)
            if candidate >= limit // 2:
                cut = candidate
                break
        if cut < 0:
            cut = limit
        parts.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest:
        parts.append(rest)

    total = len(parts)
    return [f"{part} ({i}/{total})" for i, part in enumerate(parts, 1)]


# --------------------------------------------------------------------------
# Actions

def send(text: str, fmt: str = "plain", silent: bool = False,
         dry_run: bool = False) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise TelegramError("Refusing to send an empty message.")
    if fmt not in ("plain", "html"):
        raise TelegramError(f"Unknown format {fmt!r}. Use 'plain' or 'html'.")

    chunks = split_chunks(text)
    if dry_run:
        return {"ok": True, "dry_run": True, "chunks": len(chunks), "chars": len(text),
                "preview": [render_html(c) if fmt == "html" else c for c in chunks]}

    token, chat_id = load_token(), load_chat_id()
    message_ids: list[int] = []
    degraded = False

    for chunk in chunks:
        body: dict[str, Any] = {
            "chat_id": chat_id,
            "text": render_html(chunk) if fmt == "html" else chunk,
            "disable_notification": silent,
            "link_preview_options": {"is_disabled": True},
        }
        if fmt == "html":
            body["parse_mode"] = "HTML"
        try:
            result = api("sendMessage", token, body)
        except ParseModeError:
            # Markup beat the escaper. A delivered plain message beats none.
            body.pop("parse_mode", None)
            body["text"] = chunk
            result = api("sendMessage", token, body)
            degraded = True
        message_ids.append(result.get("result", {}).get("message_id"))

    return {"ok": True, "chunks": len(chunks), "chars": len(text),
            "message_ids": message_ids, "degraded_to_plain": degraded}


def check() -> dict[str, Any]:
    dirpath = state_dir()
    report: dict[str, Any] = {"state_dir": str(dirpath)}

    try:
        token = load_token()
        report["token"] = "set"
    except TelegramError as exc:
        return {"ok": False, **report, "token": "missing", "next_step": str(exc)}

    try:
        report["chat_id"] = load_chat_id()
    except TelegramError as exc:
        report["chat_id"] = None
        report["next_step"] = str(exc)

    me = api("getMe", token).get("result", {})
    report["bot"] = f"@{me.get('username')}" if me.get("username") else "unknown"
    report["ok"] = bool(report.get("chat_id"))
    return report


def pair() -> dict[str, Any]:
    """Find the chat id of whoever messaged the bot. Requires a prior /start."""
    access = state_dir() / "access.json"
    if access.is_file():
        try:
            allowed = json.loads(access.read_text(encoding="utf-8")).get("allowFrom") or []
        except json.JSONDecodeError:
            allowed = []
        if allowed:
            return {"ok": True, "chat_id": str(allowed[0]), "source": "access.json"}

    updates = api("getUpdates", load_token(), {"timeout": 0, "limit": 20}).get("result", [])
    found: list[dict[str, Any]] = []
    for update in updates:
        message = update.get("message") or update.get("my_chat_member") or {}
        chat = message.get("chat") or {}
        if chat.get("id") and not any(c["chat_id"] == str(chat["id"]) for c in found):
            found.append({"chat_id": str(chat["id"]),
                          "name": chat.get("username") or chat.get("first_name") or "?"})
    if not found:
        raise TelegramError(
            "No messages waiting. Open your bot on Telegram and send it /start, then run "
            "this again. Telegram only keeps updates for 24h, so do it now."
        )
    return {"ok": True, "chat_id": found[0]["chat_id"], "source": "getUpdates",
            "candidates": found}


# --------------------------------------------------------------------------
# CLI

def cmd_send(args: argparse.Namespace) -> int:
    text = sys.stdin.read() if args.stdin else (args.text or "")
    print(json.dumps(send(text, args.format, args.silent, args.dry_run),
                     ensure_ascii=False, indent=2))
    return 0


def cmd_check(_: argparse.Namespace) -> int:
    report = check()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # 0 usable, 1 reachable but not usable, 2 hard failure (raised below).
    return 0 if report.get("ok") else 1


def cmd_pair(args: argparse.Namespace) -> int:
    result = pair()
    if args.save:
        result["saved_to"] = str(save_chat_id(result["chat_id"]))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_set_token(args: argparse.Namespace) -> int:
    path = save_token(args.token.strip())
    me = api("getMe", args.token.strip()).get("result", {})
    print(json.dumps({"ok": True, "saved_to": str(path), "mode": "0600",
                      "bot": f"@{me.get('username')}"}, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="One-way Telegram notifications.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_send = sub.add_parser("send", help="send a message to the configured chat")
    source = p_send.add_mutually_exclusive_group(required=True)
    source.add_argument("--text")
    source.add_argument("--stdin", action="store_true", help="read the message from stdin")
    p_send.add_argument("--format", choices=["plain", "html"], default="plain")
    p_send.add_argument("--silent", action="store_true", help="deliver without a sound")
    p_send.add_argument("--dry-run", action="store_true", help="show what would be sent")
    p_send.set_defaults(func=cmd_send)

    p_check = sub.add_parser("check", help="diagnostics; sends nothing")
    p_check.set_defaults(func=cmd_check)

    p_pair = sub.add_parser("pair", help="discover the chat id after you send /start")
    p_pair.add_argument("--save", action="store_true", help="write it to notify.json")
    p_pair.set_defaults(func=cmd_pair)

    p_token = sub.add_parser("set-token", help="store the bot token (mode 0600)")
    p_token.add_argument("token")
    p_token.set_defaults(func=cmd_set_token)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except TelegramError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
