#!/usr/bin/env python3
"""MCP server exposing the Telegram notification channel. Transport only.

Hand-rolled JSON-RPC rather than the SDK: two tools do not pay for a dependency,
and this way the plugin needs no install step at all - no `bun install` on every
session start, no node_modules, just the python3 that macOS already ships.

The protocol surface is deliberately minimal and forgiving: we echo the client's
protocolVersion instead of pinning one, and answer anything unknown with a
proper -32601 instead of dying. All real logic lives in telegram_core, so
swapping this file for the SDK later changes nothing else.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import telegram_core as tg  # noqa: E402

SERVER_INFO = {"name": "telegram-notify", "version": "0.1.0"}
FALLBACK_PROTOCOL = "2025-06-18"

SEND_DESCRIPTION = (
    "Send a message to the user's phone over Telegram. This is the only way to reach "
    "them when they are not at the terminal.\n\n"
    "One-way channel: nobody can answer, so never ask a question here. A notification "
    "is an interruption, not a reporting channel - send one when the user asked you to, "
    "or when a long task they left running has finished. Keep it short and make the "
    "first line stand on its own; it is all they see on the lock screen."
)

TOOLS = [
    {
        "name": "send_message",
        "description": SEND_DESCRIPTION,
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Message body. First line must stand alone.",
                },
                "format": {
                    "type": "string",
                    "enum": ["plain", "html"],
                    "description": (
                        "plain (default, nothing can break) or html, which renders "
                        "**bold** and `code`. Everything else is escaped."
                    ),
                },
                "silent": {
                    "type": "boolean",
                    "description": "Deliver without a sound. Use outside working hours.",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "check",
        "description": (
            "Diagnose the Telegram channel: is a token stored, is a chat paired, does "
            "Telegram answer. Sends nothing. Use this when send_message failed."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def write(message: dict) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def respond(rid, result=None, error=None) -> None:
    message = {"jsonrpc": "2.0", "id": rid}
    message["error" if error is not None else "result"] = error if error is not None else result
    write(message)


def text_result(payload: dict, is_error: bool = False) -> dict:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}],
        "isError": is_error,
    }


def call_tool(name: str, arguments: dict) -> dict:
    # Tool errors are results, not protocol errors: the model should read them
    # and act (run /telegram:setup), not see the call blow up.
    try:
        if name == "send_message":
            return text_result(tg.send(
                text=arguments.get("text", ""),
                fmt=arguments.get("format", "plain"),
                silent=bool(arguments.get("silent", False)),
            ))
        if name == "check":
            return text_result(tg.check())
        return text_result({"error": f"Unknown tool: {name}"}, is_error=True)
    except tg.TelegramError as exc:
        return text_result({"error": str(exc)}, is_error=True)
    except Exception as exc:  # never take the session down over a notification
        return text_result({"error": f"{type(exc).__name__}: {exc}"}, is_error=True)


def handle(request: dict) -> None:
    method, rid = request.get("method"), request.get("id")
    if rid is None:
        return  # notification: the spec forbids answering

    if method == "initialize":
        params = request.get("params") or {}
        respond(rid, {
            "protocolVersion": params.get("protocolVersion", FALLBACK_PROTOCOL),
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        })
    elif method == "tools/list":
        respond(rid, {"tools": TOOLS})
    elif method == "tools/call":
        params = request.get("params") or {}
        respond(rid, call_tool(params.get("name", ""), params.get("arguments") or {}))
    elif method == "ping":
        respond(rid, {})
    else:
        respond(rid, error={"code": -32601, "message": f"Method not found: {method}"})


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            respond(None, error={"code": -32700, "message": "Parse error"})
            continue
        handle(request)
    return 0


if __name__ == "__main__":
    sys.exit(main())
