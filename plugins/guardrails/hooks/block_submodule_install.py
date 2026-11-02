#!/usr/bin/env python3
"""PreToolUse guard for Bash: refuse a package install inside a git submodule whose packages are
workspaces of the superproject.

In such a repo (`"workspaces": ["./packages/*", "./nzyme/packages/*"]`, `nzyme/` being a submodule) the
superproject's install is the only correct one. Installing from inside the submodule creates a second
dependency store there (`<submodule>/node_modules`) and re-links the submodule packages to it, shadowing
the superproject's: two copies of the same package, phantom type errors, lint that works by accident.

Blocked (exit 2, the reason goes back to the agent): `bun install|i|ci|add|a|remove|rm|update`,
`npm install|i|in|ci|add|uninstall|un|remove|rm|r|update|up|link`, `pnpm install|i|add|remove|rm|uninstall|
un|update|up` and `yarn` (bare) or `yarn install|add|remove|up|upgrade`, when the directory they run in
is inside a submodule that a workspace pattern of the superproject's package.json points into. The
directory starts at the hook input's `cwd`, then follows `cd` / `pushd` earlier in the command line,
`env -C`, and the manager's own option (`bun --cwd`, `npm --prefix` / `-C`, `pnpm -C` / `--dir`,
`yarn --cwd`). The call is found wherever `shellparse.walk` reaches, the same walk as the inline-eval
guard: behind env-var prefixes, wrappers, `npx` / `bunx` / `bun x`, `npm exec`, `env -S`, `eval`,
`bash -c` strings and a script a shell reads on stdin from a heredoc or a pipe from `echo`. A
directory it cannot work out (`cd -`, `cd $X`) means allow.

Anything it cannot parse is allowed with a warning: the guard catches the common shapes, it does not
sandbox, and it must never block every command because of one odd string.
"""

from __future__ import annotations

import fnmatch
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guard import run_guard  # noqa: E402
from shellparse import (  # noqa: E402
    BUN_VALUE_OPTIONS, PACKAGE_RUNNERS, option_value, program, resolve, skip_options, walk,
)

INSTALL_COMMANDS: dict[str, set[str]] = {
    "bun": {"install", "i", "ci", "add", "a", "remove", "rm", "update"},
    "npm": {"install", "i", "in", "ci", "add", "uninstall", "un", "remove", "rm", "r", "update", "up", "link"},
    "pnpm": {"install", "i", "add", "remove", "rm", "uninstall", "un", "update", "up"},
    "yarn": {"install", "add", "remove", "up", "upgrade"},
}
DIR_OPTIONS = {"bun": {"--cwd"}, "npm": {"--prefix", "-C"}, "pnpm": {"-C", "--dir"}, "yarn": {"--cwd"}}
VALUE_OPTIONS = {
    "bun": BUN_VALUE_OPTIONS,
    "npm": PACKAGE_RUNNERS["npm"][1],
    "pnpm": PACKAGE_RUNNERS["pnpm"][1],
    "yarn": PACKAGE_RUNNERS["yarn"][1],
}
GIT_TIMEOUT = 2


@dataclass
class Found:
    snippet: str
    manager: str
    directory: str


def check_install(manager: str, words: list[str], cwd: str | None) -> Found | None:
    args = words[1:]
    rest = skip_options(args, VALUE_OPTIONS[manager])
    sub = rest[0] if rest else None
    if sub is None and manager != "yarn":
        return None
    if sub is not None and sub not in INSTALL_COMMANDS[manager]:
        return None
    chdir = option_value(args, DIR_OPTIONS[manager])
    directory = resolve(cwd, chdir) if chdir is not None else cwd
    if directory is None:
        return None
    shown = words[:words.index(sub, 1) + 1] if sub is not None else words[:1]
    return Found(shlex.join(shown), manager, directory)


def git(directory: str, *args: str) -> str | None:
    try:
        proc = subprocess.run(["git", "-C", directory, *args], capture_output=True, text=True,
                              timeout=GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def workspace_patterns(superproject: str) -> list[str]:
    try:
        with open(os.path.join(superproject, "package.json"), encoding="utf-8") as file:
            workspaces = json.load(file).get("workspaces")
    except (OSError, ValueError, AttributeError):
        return []
    if isinstance(workspaces, dict):
        workspaces = workspaces.get("packages")
    if not isinstance(workspaces, list):
        return []
    patterns = []
    for item in workspaces:
        if isinstance(item, str) and not item.startswith("!"):
            patterns.append(item.removeprefix("./").rstrip("/"))
    return patterns


def points_into(pattern: str, submodule: str) -> bool:
    """Whether a workspace glob names the submodule itself or a path under it."""
    if fnmatch.fnmatchcase(submodule, pattern):
        return True
    pattern_parts, parts = pattern.split("/"), submodule.split("/")
    return len(pattern_parts) >= len(parts) and all(
        fnmatch.fnmatchcase(part, glob) for part, glob in zip(parts, pattern_parts)
    )


def workspace_submodule(directory: str) -> tuple[str, str] | None:
    """(submodule path relative to the superproject, superproject root) when `directory` is inside a
    submodule whose packages are workspaces of the superproject."""
    while not os.path.isdir(directory) and os.path.dirname(directory) != directory:
        directory = os.path.dirname(directory)
    superproject = git(directory, "rev-parse", "--show-superproject-working-tree")
    if not superproject:
        return None
    toplevel = git(directory, "rev-parse", "--show-toplevel")
    if not toplevel:
        return None
    relative = os.path.relpath(os.path.realpath(toplevel), os.path.realpath(superproject))
    relative = relative.replace(os.sep, "/")
    if any(points_into(pattern, relative) for pattern in workspace_patterns(superproject)):
        return relative, os.path.realpath(superproject)
    return None


def reason(found: Found, submodule: str, superproject: str) -> str:
    return (
        f"Blocked by the guardrails plugin: `{found.snippet}` would install packages inside the git submodule "
        f"`{submodule}`, whose packages are workspaces of `{superproject}`. A second dependency store inside "
        "the submodule shadows the superproject's: duplicate copies of the same package, phantom type "
        "errors, lint that works by accident. Run the install from the superproject root instead:\n"
        f"    cd {shlex.quote(superproject)} && {found.manager} install\n"
        f"If a stray store was already created, delete `{submodule}/node_modules` (and the "
        f"`node_modules` of the packages under `{submodule}`) and reinstall from the superproject."
    )


def submodule_install(words: list[str], cwd: str | None) -> str | None:
    """The visitor: the reason to refuse `words` when it installs inside a workspace submodule, or None."""
    manager = program(words[0])
    found = check_install(manager, words, cwd) if manager in INSTALL_COMMANDS else None
    hit = workspace_submodule(found.directory) if found else None
    return reason(found, *hit) if found and hit else None


def check(command: str, cwd: object) -> str | None:
    start = cwd if isinstance(cwd, str) and cwd else os.getcwd()
    return walk(command, submodule_install, os.path.normpath(start))


def main() -> int:
    return run_guard(check, 6, "a submodule install")


if __name__ == "__main__":
    sys.exit(main())
