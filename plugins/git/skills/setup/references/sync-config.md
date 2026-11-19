# The `sync` key of `.claude/git.json`

Read by the git plugin's background sync hook (`hooks/sync.py`). Every key is optional; a missing or
mistyped value means its default. With no `sync` key at all the hook only refreshes the branch from its
base (merge, conflict-free only) and never pushes.

## When it runs

- **Session start** and **before each prompt**: refresh, at most once per `interval` minutes per worktree
  (one session at a time; another session holding the lock means skip).
- **Stop** (end of a turn): `commitReminder`, and a push of unpushed commits when `push` is on.
- **Session end**: `autosave`, then a push when `push` is on.
- Never while a merge, rebase or cherry-pick is open, in a detached HEAD, or in a repository without an
  `origin` remote. Any error exits 0: the hook never fails a session.

## Keys

| Key | Type | Default | What it does |
| --- | --- | --- | --- |
| `refresh` | boolean | `true` | Refresh the branch from its base. `false` turns it off. |
| `base` | string | none | Branch to refresh from, e.g. `"main"`. Overrides detection. |
| `strategy` | `"merge"` \| `"rebase"` | `"merge"` | How the base is integrated. `rebase` runs `git rebase --autostash` (rewrites local commits; do not use on branches others share). |
| `interval` | number >= 0 | `5` | Minutes between refreshes. `0` refreshes on every prompt. |
| `afterUpdate` | array | none | Commands run after a refresh that brought in changes (below). |
| `push` | `false` \| `"branch"` \| `"base"` | `false` | `"branch"` pushes HEAD to the branch's own upstream on `origin`; `"base"` pushes HEAD to the base branch (the base is refreshed first). Never forced, never to a branch in `protectedBranches`. A rejected push integrates the target and retries once. |
| `commitReminder` | number >= 0 | off | At Stop, if files have uncommitted changes older than this many minutes, block once and ask the agent to commit them. Also reports leftovers at session start. |
| `autosave` | object | off | At session end, commit files left uncommitted for `idle` minutes (only those files). `{}` turns it on with defaults. |
| `autosave.idle` | number >= 0 | `5` | Minutes a file must be untouched before autosave takes it. |
| `autosave.message` | string | `"Autosave at session end: {files}"` | Commit message; `{files}` becomes the first five paths. |
| `askIdentity` | boolean | `false` | At session start, if git has no `user.name` / `user.email`, tell the agent to ask the user for them and set them globally. |

`afterUpdate` items: `{ "run": "<shell command>", "when": ["<glob>", …], "timeout": <seconds> }`.

- `run` (required) goes through `/bin/sh -c` in the repository root, no stdin.
- `when` (optional): run only if a changed file matches a glob. A pattern without `/` also matches the file name at any depth (`package.json`).
- `timeout` (optional): seconds, default 300, capped at 480.
- Commands run in order; the first failure or timeout stops the rest. Output goes to a log file whose path the agent is given.
- A refresh made by a push retry at Stop or session end does not run them (those hooks have 120 s and 60 s); the agent is told which commands to run itself.

## How the base is found

First match wins:

1. `sync.base`.
2. The base of the branch's open PR (`gh pr view`; merged or closed PRs are ignored). In a stack of PRs each node's PR base is the node below, so a node refreshes from the node below it, not from `main`.
3. The base Paseo recorded for the worktree (`paseo/worktree.json` in the git directory).
4. Nothing: no refresh, no base push.

If the base equals the current branch (a direct-to-main checkout), a refresh is a fast-forward only; local commits that diverge are left to the agent.

## What the agent is told

- Refreshed: the git command run, incoming commits (author and subject), changed files, submodules moved, each `afterUpdate` command with its exit code (or skipped / not run / timed out), and a reminder to re-read files read earlier.
- A failed `afterUpdate` command: the log path, and an instruction to fix the cause and re-run it and the ones after it.
- Conflict, or uncommitted files that the base also changes: the attempt is rolled back (HEAD and working tree unchanged) and the agent is told which files and which command to run, following `git-workflow` and `fix-conflicts`.
- Staged changes or missing git identity block a merge commit: the agent is told what to do.
- Push refused (protected target), rejected, or failed: the agent is told; commits stay safe locally and the next sync retries.
- Messages from Stop and session end are held and delivered at the next event that can carry them.

## Example: PR-only repository with `afterUpdate`

`main` is protected, so no `base` is needed (the PR's base is detected) and nothing is pushed by the hook.

```json
{
  "protectedBranches": ["main"],
  "sync": {
    "afterUpdate": [
      { "run": "pnpm install", "when": ["pnpm-lock.yaml", "package.json"] },
      { "run": "pnpm build", "timeout": 420 }
    ]
  }
}
```

After a refresh that changes the lockfile or `package.json`, it installs, then builds; after any other refresh only the build runs. If the install fails, the build is reported as not run.

## Example: direct-to-main repository

```json
{
  "sync": {
    "base": "main",
    "strategy": "rebase",
    "push": "base",
    "commitReminder": 10,
    "autosave": { "idle": 5 },
    "askIdentity": true
  }
}
```

The branch is always `main`'s own checkout kept current; at the end of a turn, unpushed commits go to `origin/main`. Files left uncommitted for 10 minutes make Stop ask the agent to commit; at session end, files idle for 5 minutes are committed automatically and pushed. A new user is asked for their name and email once. Note that `base` equals the branch here, so with `strategy: "rebase"` local commits are replayed onto `origin/main`.
