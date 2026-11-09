"""SessionStart hook: warn when a session starts below the root of its git repository.

Started in a subdirectory, Claude Code still finds the project's own skills, but plugins linked
under `.claude/skills/` do not load, and a skill that inlines a file with `` !`cat docs/…` ``
resolves the path from the session's directory and fails to load. Nothing in the session says so.
Claude Code cannot be stopped from here, so this tells the user and the agent at once.

It only runs where the plugin loads regardless of the directory: installed at user scope, not linked
into a project.

Silent at the top level of a repository (a worktree's or a submodule's own top level included),
outside any repository, and on any error: a hook that crashes must never get in the way.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys


def top_level(cwd: str) -> str | None:
    proc = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True, timeout=5)
    return proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else None


def main() -> int:
    try:
        data = json.load(sys.stdin)
        cwd = data.get("cwd") if isinstance(data, dict) else None
        if not isinstance(cwd, str) or not cwd:
            return 0
        root = top_level(cwd)
        if root is None or os.path.realpath(root) == os.path.realpath(cwd):
            return 0
    except Exception:
        return 0
    message = (f"This session started in {cwd}, below the repository root {root}. Plugins linked in the "
               f"project's .claude/skills do not load from here, and skills that inline files by a "
               f"relative path fail to load. Restart Claude Code from {root}.")
    print(json.dumps({
        "systemMessage": message,
        "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": message},
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
