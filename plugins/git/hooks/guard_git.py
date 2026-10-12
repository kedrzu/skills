#!/usr/bin/env python3
"""PreToolUse guard for Bash: stop the git commands that silently lose someone else's work.

Blocked (exit 2, the reason goes back to the agent):
- `git stash` / `git stash push` without a message, and `git stash pop|apply|drop` without a ref:
  the stash stack is shared by every worktree of a clone, so the top entry may be another agent's.
- `git stash clear`: it deletes every worktree's stashes.
- `git push --force` / `-f` / a `+refspec` / `--mirror`: `--force-with-lease` is the safe form.
- a push to `main` or `master`, unless the remote has no such branch yet (a repository's first push).

Anything it cannot parse is allowed: the guard exists to catch the common slip, not to sandbox.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys

PROTECTED = {"main", "master"}
SEPARATORS = {";", "&&", "||", "|", "&", "(", ")"}
PREFIXES = {"sudo", "command", "time", "nohup", "exec", "env"}
GIT_OPTS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
STASH_SAFETY = "The git:stash-safety skill has the recipe."


def segments(command: str) -> list[list[str]]:
    """Split a shell command into simple commands, skipping heredoc bodies."""
    lines, kept, terminator = command.splitlines(), [], None
    for line in lines:
        if terminator is not None:
            if line.strip() == terminator:
                terminator = None
            continue
        kept.append(line)
        match = re.search(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", line)
        if match:
            terminator = match.group(1)
    result = []
    for line in kept:
        try:
            lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
            lexer.whitespace_split = True
            tokens = list(lexer)
        except ValueError:
            continue
        current: list[str] = []
        for token in tokens:
            if token in SEPARATORS:
                if current:
                    result.append(current)
                current = []
            else:
                current.append(token)
        if current:
            result.append(current)
    return result


def git_call(tokens: list[str]) -> tuple[list[str], list[str]] | None:
    """Return (global options, subcommand + args) when the simple command runs git."""
    while tokens and (tokens[0] in PREFIXES or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0])):
        tokens = tokens[1:]
    if not tokens or not (tokens[0] == "git" or tokens[0].endswith("/git")):
        return None
    rest, options = tokens[1:], []
    while rest and rest[0].startswith("-"):
        option = rest.pop(0)
        options.append(option)
        if option in GIT_OPTS_WITH_VALUE and rest:
            options.append(rest.pop(0))
    return options, rest


def check_stash(args: list[str]) -> str | None:
    sub = args[1] if len(args) > 1 and not args[1].startswith("-") else None
    rest = args[2:] if sub else args[1:]
    if sub in (None, "push", "save"):
        named = any(a in ("-m", "--message") or a.startswith("--message=") or (a.startswith("-m") and len(a) > 2)
                    for a in rest)
        if sub == "save" and any(not a.startswith("-") for a in rest):
            named = True
        if not named:
            return ("an unnamed stash is indistinguishable from the ones other worktrees of this clone push "
                    "onto the same shared stack. Name it uniquely: "
                    "`git stash push -m \"<branch>/<purpose>/$(date +%s)-$RANDOM\"`, then restore it by ref. "
                    + STASH_SAFETY)
    if sub in ("pop", "apply", "drop") and not any(not a.startswith("-") for a in rest):
        return (f"`git stash {sub}` without a ref takes the top of a stack shared by every worktree of this "
                "clone, which may be another agent's work. Find your own entry by its message "
                "(`git stash list --format='%H %gs'`) and pass it explicitly: "
                f"`git stash {sub} <sha>`. " + STASH_SAFETY)
    if sub == "clear":
        return ("`git stash clear` deletes the stashes of every worktree of this clone, not just yours. "
                "Drop your own entry by ref: `git stash drop <sha>`. " + STASH_SAFETY)
    return None


def current_branch(cwd: str | None, options: list[str]) -> str | None:
    try:
        return subprocess.run(["git", *options, "symbolic-ref", "--quiet", "--short", "HEAD"], cwd=cwd or None,
                              capture_output=True, text=True, timeout=5).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def remote_has(cwd: str | None, options: list[str], remote: str, branch: str) -> bool:
    try:
        return subprocess.run(["git", *options, "rev-parse", "--verify", "--quiet", f"refs/remotes/{remote}/{branch}"],
                              cwd=cwd or None, capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return True


def check_push(args: list[str], options: list[str], cwd: str | None) -> str | None:
    flags, positional, rest = [], [], args[1:]
    while rest:
        arg = rest.pop(0)
        if arg.startswith("-"):
            flags.append(arg)
            if arg in ("-o", "--push-option", "--repo", "--receive-pack", "--exec") and rest:
                rest.pop(0)
        else:
            positional.append(arg)
    forced = any(f in ("--force", "--mirror") or re.fullmatch(r"-[A-Za-z]*f[A-Za-z]*", f) for f in flags)
    if forced or any(p.startswith("+") for p in positional[1:]):
        return ("a plain force-push overwrites whatever is on the remote, including commits pushed from another "
                "worktree or by someone else. Use `git push --force-with-lease` (it refuses when the remote moved "
                "since you last fetched), and only on a branch that is yours.")
    remote = positional[0] if positional else "origin"
    refspecs = positional[1:]
    if "--all" in flags:
        targets = PROTECTED
    elif refspecs:
        targets = set()
        for spec in refspecs:
            src, _, dst = spec.lstrip("+").partition(":")
            dst = dst or src
            if dst == "HEAD":
                dst = current_branch(cwd, options) or dst
            targets.add(dst.removeprefix("refs/heads/"))
    else:
        branch = current_branch(cwd, options)
        targets = {branch} if branch else set()
    for target in targets & PROTECTED:
        if remote_has(cwd, options, remote, target):
            return (f"this pushes to `{target}`, which changes reach only through a pull request. Push a task branch "
                    "and open a PR; if the user really wants this push, ask them to run it themselves.")
    return None


def check(command: str, cwd: str | None) -> str | None:
    for tokens in segments(command):
        call = git_call(tokens)
        if not call or not call[1]:
            continue
        options, args = call
        if args[0] == "stash":
            reason = check_stash(args)
        elif args[0] == "push":
            reason = check_push(args, options, cwd)
        else:
            reason = None
        if reason:
            return f"Blocked by the git plugin's guard: {reason}"
    return None


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    command = (data.get("tool_input") or {}).get("command")
    if not isinstance(command, str):
        return 0
    reason = check(command, data.get("cwd"))
    if reason:
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
