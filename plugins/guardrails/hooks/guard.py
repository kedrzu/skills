"""The runner shared by the Bash guards of this plugin: hook input in, exit code out.

`run_guard(check, seconds, what)` reads the PreToolUse hook input as JSON from stdin and calls
`check(command, cwd)` under a `seconds` alarm. A returned reason is printed on stderr and the call
is refused (exit 2); `None` allows it (exit 0). Any exception allows it too, with a
`{"systemMessage": …}` warning on stdout naming `what` was being checked: a guard that crashes
must never block every command.
"""

from __future__ import annotations

import json
import signal
import sys
from typing import Callable


def _timeout(*_: object) -> None:
    raise TimeoutError("the command took too long to check")


def run_guard(check: Callable[[str, object], str | None], seconds: int, what: str) -> int:
    try:
        data = json.load(sys.stdin)
        command = (data.get("tool_input") or {}).get("command") if isinstance(data, dict) else None
        cwd = data.get("cwd") if isinstance(data, dict) else None
    except ValueError:
        return 0
    if not isinstance(command, str):
        return 0
    if hasattr(signal, "SIGALRM"):
        signal.signal(signal.SIGALRM, _timeout)
        signal.alarm(seconds)
    try:
        found = check(command, cwd)
    except Exception as error:  # fail open: one odd string must not block every command
        message = f"guardrails: could not check this command for {what} ({error}); allowed it."
        print(json.dumps({"systemMessage": message}))
        return 0
    if found:
        print(found, file=sys.stderr)
        return 2
    return 0
