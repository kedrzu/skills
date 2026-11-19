#!/usr/bin/env python3
"""Background git sync, run by Claude Code hooks between the agent's turns.

    sync.py session-start | prompt | stop | session-end

Refresh from the base: find the branch the current one will merge into (`sync.base` in
`.claude/git.json`, else the open PR's base, else the base Paseo recorded for the worktree), and when
`origin/<base>` has commits the branch lacks, integrate them — only when that is conflict-free — run
the project's after-update commands, and tell the agent what happened. Anything that needs judgment
(a conflict, an uncommitted edit in the way) goes to the agent as context; nothing is left half-done.

With no `.claude/git.json` this is the only behaviour, and it never pushes, never rebases and never
commits anything but the merge itself. Opt-in keys add the rest: `push` (to the branch's upstream or
straight to the base, never forced, never to a protected branch), `commitReminder` (Stop asks the agent
to commit old uncommitted work), `autosave` (SessionEnd commits idle files) and `askIdentity`.
Never fails a session: on any error the hook exits 0.
"""

from __future__ import annotations

import contextlib
import fnmatch
import json
import os
import signal
import subprocess
import sys
import time

REMOTE = "origin"
MAX_LISTED = 15
LOCK_STALE_AFTER = 15 * 60  # seconds; a lock this old belongs to a hook that was killed
GH_TIMEOUT = 5
AFTER_UPDATE_TIMEOUT, AFTER_UPDATE_TIMEOUT_CAP = 300, 480  # seconds; the hook itself gets 600
DEFAULTS = {
    "refresh": True, "base": None, "strategy": "merge", "interval": 5,
    "push": False, "commitReminder": None, "askIdentity": False,
}
AUTOSAVE_DEFAULTS = {"idle": 5, "message": "Autosave at session end: {files}"}
AUTOSAVE_LISTED = 5
INTEGRATED = ("current", "pulled")  # refresh outcomes after which HEAD contains its target

ENV = {**os.environ, "GIT_EDITOR": "true", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}


def git(*args: str, timeout: float = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "core.quotePath=false", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=ENV,
    )


def out(*args: str) -> str:
    return git(*args).stdout.strip()


def lines(*args: str) -> list[str]:
    return [line for line in out(*args).splitlines() if line]


def listed(items: list[str]) -> str:
    shown = [f"- {item}" for item in items[:MAX_LISTED]]
    if len(items) > MAX_LISTED:
        shown.append(f"- … and {len(items) - MAX_LISTED} more")
    return "\n".join(shown)


def first_line(text: str) -> str:
    return (text.strip().splitlines() or ["unknown error"])[0]


# --- config ---


def is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def load_config() -> dict:
    """The `sync` key of `.claude/git.json`; a missing, unreadable or mistyped value means its default."""
    try:
        with open(os.path.join(".claude", "git.json")) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    sync = data.get("sync") if isinstance(data, dict) else None
    sync = sync if isinstance(sync, dict) else {}

    def pick(key: str, valid) -> object:
        return sync[key] if key in sync and valid(sync[key]) else DEFAULTS[key]

    return {
        "refresh": pick("refresh", lambda v: isinstance(v, bool)),
        "base": pick("base", lambda v: isinstance(v, str) and v.strip() != ""),
        "strategy": pick("strategy", lambda v: v in ("merge", "rebase")),
        "interval": pick("interval", lambda v: is_number(v) and v >= 0),
        "afterUpdate": after_update_config(sync.get("afterUpdate")),
        "push": pick("push", lambda v: v in (False, "branch", "base")),
        "commitReminder": pick("commitReminder", lambda v: is_number(v) and v >= 0),
        "autosave": autosave_config(sync.get("autosave")),
        "askIdentity": pick("askIdentity", lambda v: isinstance(v, bool)),
        "protectedBranches": [b for b in data.get("protectedBranches") or [] if isinstance(b, str)]
        if isinstance(data, dict) and isinstance(data.get("protectedBranches"), list) else [],
    }


def autosave_config(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    idle, message = value.get("idle"), value.get("message")
    return {
        "idle": idle if is_number(idle) and idle >= 0 else AUTOSAVE_DEFAULTS["idle"],
        "message": message if isinstance(message, str) and message.strip() else AUTOSAVE_DEFAULTS["message"],
    }


def opted_in(config: dict) -> bool:
    """Any feature beyond the refresh is on: the hook then also speaks up about open integrations."""
    return bool(config["push"]) or config["commitReminder"] is not None or config["autosave"] is not None


def after_update_config(value: object) -> list[dict]:
    commands = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("run"), str) or not item["run"].strip():
            continue
        when = item.get("when")
        timeout = item.get("timeout")
        commands.append({
            "run": item["run"],
            "when": [p for p in when if isinstance(p, str)] if isinstance(when, list) else None,
            "timeout": min(timeout, AFTER_UPDATE_TIMEOUT_CAP)
            if is_number(timeout) and timeout > 0 else AFTER_UPDATE_TIMEOUT,
        })
    return commands


# --- repo state ---


def git_dir() -> str:
    return out("rev-parse", "--absolute-git-dir")


def state_path(name: str) -> str:
    return os.path.join(git_dir(), f"claude-git-sync-{name}")


def in_progress() -> bool:
    """A rebase, merge or cherry-pick is open: the agent is resolving it (maybe asking the user)."""
    d = git_dir()
    return any(
        os.path.exists(os.path.join(d, name))
        for name in ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD")
    )


def dirty_files() -> list[str]:
    """Uncommitted and untracked files; submodules never count (they follow the pinned commit)."""
    entries = git(
        "status", "--porcelain", "-z", "-uall", "--no-renames", "--ignore-submodules=all"
    ).stdout.split("\0")
    return [entry[3:] for entry in entries if len(entry) > 3]


def stale_files(age: float) -> list[str]:
    """Uncommitted files last modified more than `age` seconds ago (a deletion counts as fresh)."""
    now = time.time()
    stale = []
    for path in dirty_files():
        try:
            if now - os.path.getmtime(path) > age:
                stale.append(path)
        except OSError:
            pass
    return stale


def current_branch() -> str:
    return out("symbolic-ref", "--quiet", "--short", "HEAD")


def ahead(target: str) -> int:
    """Commits on HEAD that `origin/<target>` lacks (0 when that ref is unknown)."""
    ref = f"refs/remotes/{REMOTE}/{target}"
    if git("rev-parse", "--verify", "--quiet", ref).returncode:
        return 0
    return int(out("rev-list", "--count", f"{ref}..HEAD") or 0)


def has_identity() -> bool:
    return bool(out("config", "user.name")) and bool(out("config", "user.email"))


# --- base detection ---


def detect_base(config: dict) -> tuple[str | None, str | None]:
    """The branch the current one merges into, and where that answer came from."""
    if config["base"]:
        return config["base"], "set in .claude/git.json"
    try:
        result = subprocess.run(
            ["gh", "pr", "view", "--json", "baseRefName,number,state"],
            capture_output=True,
            text=True,
            timeout=GH_TIMEOUT,
            env={**ENV, "GH_PROMPT_DISABLED": "1"},
        )
        pr = json.loads(result.stdout) if result.returncode == 0 else None
        # A merged or closed PR's base says nothing about where the branch goes now.
        if isinstance(pr, dict) and pr.get("state") == "OPEN" and isinstance(pr.get("baseRefName"), str) \
                and pr["baseRefName"]:
            return pr["baseRefName"], f"the base of PR #{pr.get('number')}"
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    try:
        with open(os.path.join(git_dir(), "paseo", "worktree.json")) as f:
            base = json.load(f).get("baseRefName")
        if isinstance(base, str) and base:
            return base, "the base Paseo recorded for this worktree"
    except (OSError, ValueError, AttributeError):
        pass
    return None, None


# --- throttle and lock ---


def due(interval: float) -> bool:
    try:
        with open(state_path("last")) as f:
            return time.time() - float(f.read()) >= interval * 60
    except (OSError, ValueError):
        return True


def stamp() -> None:
    with open(state_path("last"), "w") as f:
        f.write(str(time.time()))


def acquire(path: str) -> bool:
    for _ in range(2):
        try:
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return True
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(path) < LOCK_STALE_AFTER:
                    return False
                os.remove(path)
            except OSError:
                pass  # released between the two calls: try again
    return False


@contextlib.contextmanager
def locked():
    """Yields whether this hook holds the worktree's sync lock; another session holding it means skip."""
    path = state_path("lock")
    held = acquire(path)
    try:
        yield held
    finally:
        if held:
            with contextlib.suppress(OSError):
                os.remove(path)


# --- refresh ---


def sync(config: dict, force: bool = False, after_update: bool = True) -> tuple[str, list[str]]:
    """Refresh from the base when due (or forced), then push when `push` is on.

    `after_update=False` (Stop, SessionEnd: their hook timeouts are short) reports the after-update
    commands an integration would have run instead of running them.

    Returns the worst integration outcome (`refresh`'s statuses, or "skipped") and messages for the agent."""
    if not (config["refresh"] or config["push"]) or in_progress() or not (force or due(config["interval"])):
        return "skipped", []
    with locked() as held:
        # Re-checked under the lock: another session may have synced while this one waited.
        if not held or in_progress() or not (force or due(config["interval"])):
            return "skipped", []
        try:
            base, source = detect_base(config) if config["refresh"] or config["push"] == "base" else (None, None)
            status, messages = refresh(config, base, source, after_update=after_update) if config["refresh"] else ("current", [])
        finally:
            stamp()
        # A push to the base needs the base integrated first; a push to the branch's own upstream does not.
        if (config["push"] == "base" and status in INTEGRATED) or (config["push"] == "branch" and status != "offline"):
            pushed, more = push(config, base, source, after_update)
            messages += more
            if pushed in ("conflict", "overlap"):
                status = pushed
        return status, messages


def push(config: dict, base: str | None, source: str | None, after_update: bool = True) -> tuple[str, list[str]]:
    """Push HEAD to its target when it has unpushed commits, never forced.

    A rejected push integrates the target (the base, or the branch's upstream) and retries once."""
    branch = current_branch()
    if not branch:
        return "skipped", []
    if config["push"] == "base":
        target = base
    else:
        upstream = out("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
        target = upstream[len(REMOTE) + 1:] if upstream.startswith(REMOTE + "/") else None
    if not target:
        return "skipped", []  # no base, or a branch with no upstream on origin: nothing to push to
    messages: list[str] = []
    for attempt in range(2):
        if not ahead(target):
            return "pushed", messages
        if target in config["protectedBranches"]:
            return "refused", messages + [
                f"Commits on `{branch}` were NOT pushed: their push target `{target}` is listed in "
                "`protectedBranches` of .claude/git.json, and this hook never pushes there. Change "
                "`sync.push` in .claude/git.json or move the commits to a branch of their own (the "
                "project's `git-workflow` skill)."
            ]
        result = git("push", "--quiet", REMOTE, f"HEAD:refs/heads/{target}", timeout=60)
        if result.returncode == 0:
            return "pushed", messages
        if "rejected" not in result.stderr and "fetch first" not in result.stderr:
            return "failed", messages + [
                f"Could not push the committed changes to `{REMOTE}/{target}` ({first_line(result.stderr)}). "
                "They are safe locally and the next sync retries. If it keeps failing, tell the user "
                "plainly (for example that their GitHub login may have expired)."
            ]
        if attempt:
            break
        # Someone pushed first: take their work, then retry.
        if config["push"] == "base":
            status, integrated = refresh(config, base, source, after_update=after_update)
        else:
            status, integrated = refresh(
                config, target, "the push target, which had new commits", "upstream", after_update
            )
        messages += integrated
        if status not in INTEGRATED:
            return status, messages or [
                f"The push of `{branch}` to `{REMOTE}/{target}` was rejected: the remote has commits this "
                f"branch lacks. Integrate `{REMOTE}/{target}` following the project's `git-workflow` "
                "skill; the next sync pushes."
            ]
    return "rejected", messages + [
        f"The push of `{branch}` to `{REMOTE}/{target}` was rejected twice; the next sync retries."
    ]


def refresh(
    config: dict, base: str | None, source: str | None, noun: str = "base", after_update: bool = True
) -> tuple[str, list[str]]:
    """Bring origin/<base> into the current branch when that is safe.

    Returns a status (current, pulled, conflict, overlap, blocked, failed, diverged, offline, skipped)
    and messages for the agent. `noun` "upstream" integrates the branch's own push target: a merge
    into the branch itself is then allowed."""
    branch = current_branch()
    if not branch:
        return "skipped", []  # detached HEAD: no branch to refresh
    if not base:
        return "current", []
    target = f"{REMOTE}/{base}"
    if git("fetch", "--quiet", REMOTE, f"+refs/heads/{base}:refs/remotes/{target}", timeout=20).returncode:
        return "offline", []  # offline, or the base is gone from the remote
    if git("merge-base", "--is-ancestor", target, "HEAD").returncode == 0:
        return "current", []  # up to date

    strategy = config["strategy"]
    fast_forward = git("merge-base", "--is-ancestor", "HEAD", target).returncode == 0
    if strategy == "rebase":
        command = ["rebase", "--autostash", target]
    elif base == branch and noun == "base":
        if not fast_forward:
            return "diverged", []  # local commits on the branch's own base: merging them is not this hook's call
        command = ["merge", "--ff-only", target]
    else:
        command = ["merge", "--no-edit", target]
    shown = "git " + " ".join(command)
    incoming = lines("log", "--reverse", "--format=%h %an: %s", f"HEAD..{target}")
    behind = (
        f"The branch `{branch}` is {len(incoming)} commit(s) behind its {noun} `{target}` ({source}), "
        "and was NOT refreshed automatically: "
    )

    makes_commit = strategy == "merge" and not fast_forward
    if makes_commit and git("diff", "--cached", "--quiet").returncode:
        return "blocked", [
            behind + "changes are staged, and git merge refuses to start then. Commit them (the "
            "project's `git-workflow` skill, 'Checkpoint') or unstage them; the next refresh brings "
            f"the base in, or run `{shown}` yourself."
        ]
    if makes_commit and not has_identity():
        return "blocked", [
            behind + "git does not know who the user is (user.name / user.email are not set), and the "
            "merge needs a commit. Ask the user for their full name and email, set them with "
            f"`git config --global user.name \"…\"` and `git config --global user.email \"…\"`, then run `{shown}`."
        ]
    overlap = sorted(set(dirty_files()) & set(lines("diff", "--name-only", f"HEAD...{target}")))
    if overlap:
        return "overlap", [
            behind + "these files have uncommitted or untracked local changes and also change on the "
            f"{noun}:\n{listed(overlap)}\n"
            "Commit your edits first (the project's `git-workflow` skill, 'Checkpoint'), then run "
            f"`{shown}` and resolve any conflict following the project's `git-workflow` skill and the "
            "`fix-conflicts` skill (git plugin)."
        ]

    old = out("rev-parse", "HEAD")
    try:
        result = git(*command, timeout=120)
        failed, error = result.returncode != 0, result.stderr
    except subprocess.TimeoutExpired:
        failed, error = True, f"{shown} timed out"
    if failed:
        return integration_failed(branch, target, source, shown, error, noun)

    new = out("rev-parse", "HEAD")
    changed = lines("diff", "--name-only", old, new)
    message = [
        f"Between turns, the branch `{branch}` was refreshed from its {noun} `{target}` ({source}); it is "
        "already integrated, nothing to do:",
        f"$ {shown}",
        f"Incoming commits:\n{listed(incoming)}",
        f"Changed files:\n{listed(changed)}",
    ]
    message += update_submodules(old, new)
    message += run_after_update(config["afterUpdate"], changed, after_update)
    message.append("Files you read earlier in this session may have changed: re-read them before editing.")
    return "pulled", ["\n".join(message)]


def integration_failed(
    branch: str, target: str, source: str, shown: str, error: str, noun: str
) -> tuple[str, list[str]]:
    """Roll back whatever the failed command left open, and explain it to the agent."""
    conflicted = lines("diff", "--name-only", "--diff-filter=U")
    d = git_dir()
    if os.path.exists(os.path.join(d, "MERGE_HEAD")):
        git("merge", "--abort")
    if any(os.path.exists(os.path.join(d, name)) for name in ("rebase-merge", "rebase-apply")):
        git("rebase", "--abort")
    if conflicted:
        return "conflict", [
            f"The branch `{branch}` is behind its {noun} `{target}` ({source}), and bringing it in "
            f"collides with this branch's own changes in:\n{listed(conflicted)}\n"
            "The attempt was rolled back: HEAD and the working tree are as they were. Integrate it "
            "yourself following the project's `git-workflow` skill and the `fix-conflicts` skill (git "
            f"plugin): run `{shown}` and resolve the conflicts."
        ]
    return "failed", [
        f"Refreshing the branch `{branch}` from its {noun} `{target}` ({source}) failed: `{shown}` said "
        f"\"{first_line(error)}\". Nothing was changed. Look into it, then run `{shown}` yourself."
    ]


def update_submodules(old: str, new: str) -> list[str]:
    """Check out the submodules whose pinned commit the integration moved; leave the others alone."""
    paths = []
    for line in lines("diff", "--raw", "--no-renames", old, new):
        meta, _, path = line.partition("\t")
        fields = meta.split()
        if len(fields) > 1 and fields[1] == "160000":
            paths.append(path)
    if not paths:
        return []
    result = git("submodule", "update", "--init", "--recursive", "--checkout", "--", *paths, timeout=120)
    if result.returncode:
        return [f"Submodules NOT checked out at their new pin ({first_line(result.stderr)}):\n{listed(paths)}"]
    return [f"Submodules checked out at their new pin:\n{listed(paths)}"]


def matches(pattern: str, path: str) -> bool:
    if fnmatch.fnmatchcase(path, pattern):
        return True
    return "/" not in pattern and fnmatch.fnmatchcase(path.rsplit("/", 1)[-1], pattern)


def run_after_update(commands: list[dict], changed: list[str], run_now: bool = True) -> list[str]:
    """Run the configured commands in order; the first failure or timeout stops the rest."""
    if not commands:
        return []
    if not run_now:
        due_now = [c["run"] for c in commands if c["when"] is None or any(
            matches(pattern, path) for pattern in c["when"] for path in changed
        )]
        if not due_now:
            return []
        return [
            "After-update commands were NOT run (this happened at the end of a turn, where the hook "
            f"has no time for them). Run them yourself before relying on the result:\n{listed(due_now)}"
        ]
    log = state_path("log")
    results, failed = [], False
    with open(log, "w") as f:
        for command in commands:
            run = command["run"]
            if failed:
                results.append(f"`{run}` → not run (an earlier command failed)")
                continue
            if command["when"] is not None and not any(
                matches(pattern, path) for pattern in command["when"] for path in changed
            ):
                results.append(f"`{run}` → skipped (when: no matching change)")
                continue
            f.write(f"$ {run}\n")
            f.flush()
            proc = subprocess.Popen(
                ["/bin/sh", "-c", run],
                stdin=subprocess.DEVNULL,
                stdout=f,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                code = proc.wait(timeout=command["timeout"])
            except subprocess.TimeoutExpired:
                kill_group(proc)
                results.append(f"`{run}` → timed out after {command['timeout']:g} s")
                failed = True
                continue
            results.append(f"`{run}` → exit {code}")
            failed = code != 0
    message = [f"After-update commands:\n{listed(results)}"]
    if failed:
        message.append(
            f"A command failed; its output is in {log}. Read it, fix the cause (or tell the user), then "
            "re-run the failed command and the ones after it."
        )
    return message


def kill_group(proc: subprocess.Popen) -> None:
    for sig, wait in ((signal.SIGTERM, 5), (signal.SIGKILL, None)):
        with contextlib.suppress(OSError):
            os.killpg(proc.pid, sig)
        try:
            proc.wait(timeout=wait)
            return
        except subprocess.TimeoutExpired:
            continue


# --- hook events ---


def context(event: str, messages: list[str]) -> None:
    if messages:
        payload = {"hookEventName": event, "additionalContext": "\n\n".join(messages)}
        print(json.dumps({"hookSpecificOutput": payload}))


def defer(messages: list[str]) -> None:
    """Stop and SessionEnd cannot inform without blocking: keep the news for the next event that can."""
    if messages:
        with open(state_path("pending"), "a") as f:
            f.write("\n\n".join(messages) + "\n\n")


def take_deferred() -> list[str]:
    try:
        with open(state_path("pending")) as f:
            text = f.read().strip()
        os.remove(state_path("pending"))
        return [text] if text else []
    except OSError:
        return []


OPEN_INTEGRATION = (
    "A rebase, merge or cherry-pick is still open in this worktree. If the user just answered your "
    "question about it, finish resolving it first (the project's `git-workflow` skill and the "
    "`fix-conflicts` skill, git plugin)."
)


def session_start(_data: dict, config: dict) -> None:
    messages = take_deferred()
    if config["askIdentity"] and not has_identity():
        messages.append(
            "Git does not know who this user is (user.name / user.email are not set). Ask them for their "
            "full name and the email of their GitHub account, then run `git config --global user.name \"…\"` "
            "and `git config --global user.email \"…\"`. Their commits are signed with these."
        )
    if in_progress():
        if opted_in(config):
            messages.append(OPEN_INTEGRATION)
    else:
        leftovers = dirty_files() if config["commitReminder"] is not None or config["autosave"] is not None else []
        if leftovers:
            messages.append(
                f"Uncommitted changes are left over from an earlier session:\n{listed(leftovers)}\n"
                "Look at what they are and commit them following the project's `git-workflow` skill "
                "(Checkpoint)."
            )
        status, synced = sync(config)
        messages += synced
        if status == "offline" and config["push"]:
            messages.append(
                "The remote is unreachable (offline?). Commits are kept locally and pushed once the "
                "connection is back."
            )
    context("SessionStart", messages)


def prompt(_data: dict, config: dict) -> None:
    messages = take_deferred()
    if in_progress():
        if opted_in(config):
            messages.append(OPEN_INTEGRATION)
    else:
        messages += sync(config)[1]
    context("UserPromptSubmit", messages)


def unpushed(config: dict) -> bool:
    """HEAD has commits its push target lacks (a cheap check: no fetch)."""
    if not config["push"] or not current_branch():
        return False
    if config["push"] == "base":
        target = detect_base(config)[0]
    else:
        upstream = out("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
        target = upstream[len(REMOTE) + 1:] if upstream.startswith(REMOTE + "/") else None
    return bool(target) and ahead(target) > 0


def stop(data: dict, config: dict) -> None:
    # An open integration means the agent is resolving it, possibly waiting for the user's choice.
    if in_progress():
        return
    # Second Stop in a row after a block: never block again (no loops); still push what got committed.
    may_block = not data.get("stop_hook_active")

    if config["commitReminder"] is not None and may_block:
        stale = stale_files(config["commitReminder"] * 60)
        if stale:
            print(json.dumps({
                "decision": "block",
                "reason": (
                    "Safety net: these files have uncommitted changes older than "
                    f"{config['commitReminder']:g} minutes:\n{listed(stale)}\n"
                    "Commit them now following the project's `git-workflow` skill (Checkpoint), one "
                    "commit per logical change. Then end your turn the way you were about to: if your "
                    "last message asked the user something, ask it again briefly."
                ),
            }))
            return

    if unpushed(config):
        status, messages = sync(config, force=True, after_update=False)
        if status in ("conflict", "overlap") and may_block:
            print(json.dumps({"decision": "block", "reason": "\n\n".join(messages)}))
        else:
            defer(messages)


def session_end(_data: dict, config: dict) -> None:
    """Last chance: nobody can answer now, so commit left-behind files mechanically and push them.

    Only files idle for `autosave.idle` minutes: another session in this worktree may be editing the
    fresh ones. Submodules never count (dirty_files ignores them), and only these paths are committed,
    whatever else is staged."""
    if in_progress():
        return
    autosave = config["autosave"]
    if autosave is not None:
        files = stale_files(autosave["idle"] * 60)
        if files:
            summary = ", ".join(files[:AUTOSAVE_LISTED])
            if len(files) > AUTOSAVE_LISTED:
                summary += f" and {len(files) - AUTOSAVE_LISTED} more"
            git("add", "--", *files)
            git("commit", "--quiet", "-m", autosave["message"].replace("{files}", summary), "--", *files)
    if unpushed(config):
        defer(sync(config, force=True, after_update=False)[1])


HANDLERS = {
    "session-start": session_start,
    "prompt": prompt,
    "stop": stop,
    "session-end": session_end,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in HANDLERS:
        return
    try:
        data = json.load(sys.stdin)
    except ValueError:
        data = {}
    data = data if isinstance(data, dict) else {}
    # The project dir first: the agent often `cd`s into a submodule, and following the event's `cwd`
    # there would sync the submodule instead of the project.
    os.chdir(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd())
    if out("rev-parse", "--is-inside-work-tree") != "true" or REMOTE not in lines("remote"):
        return
    os.chdir(out("rev-parse", "--show-toplevel"))  # paths from git status are relative to the cwd
    HANDLERS[sys.argv[1]](data, load_config())


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # never break the session over sync
        print(f"git sync hook: {error}", file=sys.stderr)
    sys.exit(0)
