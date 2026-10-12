---
name: git-workflow
description: >-
    How a change moves in this repository — the task branch, commit and push, the GitHub PR and its
    description, stacked PRs (GitHub's native stacks) and landing with a squash merge, all through
    `git` and `gh`. The dev pipeline (`/dev:fix`, `/dev:task`, `/dev:feature`, `/dev:build`,
    `/dev:deliver`), `/dev:review` and `/dev:fix-pr-comments` take every git and PR command from
    here. Use it directly whenever you commit, push or open a PR in this repository. Do NOT use to
    decide what a PR description says or where a stack is cut (the dev pipeline owns that), or to
    resolve conflicts (`fix-conflicts` from the `git` plugin).
---

# Git workflow

Fulfils the `dev` plugin's `git-workflow` contract, one section per operation. This is a project
skill, not a plugin: it has no `plugin.json` and no marketplace entry, and it reaches
`.claude/skills/` through the `plugins` symlink. The standing authorization to commit, push and
open PRs without asking, and the workspace naming rule, are in `CLAUDE.md` → "Workspace and pull
requests"; this skill holds the commands.

The remote is `origin` = `github.com/kedrzu/skills`, the main line is `main`. There is no issue
tracker: branches and commits name no issue, and no step here posts to one.

## Start

- **Paseo workspace** — Paseo cuts the worktree's branch from `origin/main`, and `setup.sh` catches
  it up with `origin/main` when the branch is based on `main` (see the script). Work on that branch;
  rename it only if its generated name (`ripe-penguin`) would mislead, with `git branch -m <name>`
  before the first push.
- **On `main`** — `git switch -c <name>`, kebab-case and descriptive (`add-explain-pr-skill`,
  `fix-google-mcp-roots-and-reauth`). In the local checkout `~/Dev/skills` other workspaces share the
  directory: ask once before switching branches there.
- No draft PR at start. The PR opens at the first push, ready for review (Publish).

## Checkpoint

**Before committing**, bump the `version` in `plugins/<name>/.claude-plugin/plugin.json` of every
plugin whose files changed (and its `server/package.json` if it has one); CI fails a PR without it.
Run the validation in `CLAUDE.md` → "Validation".

**Message**: English, imperative subject, no prefix, no issue tag; the subject says WHAT, the body
says WHY when the subject does not. Match `git log`: `Add the retro plugin: question-driven
retrospective over agent transcripts`, `Keep Codex question answers and drop injected context in
retro renders`. End it with the `Co-Authored-By` trailer the session gives you.

```bash
git add -A
git commit -F - <<'EOF'
<subject>

<why>

Co-Authored-By: ...
EOF
```

**Only a given set of files** — empty the index first, so nothing staged earlier rides along, then
stage exactly the group and commit it. Repeat per group, one commit each:

```bash
git restore --staged :/
git add -- <file> <file> ...
git diff --cached --name-only        # must list exactly the group
git commit -F - <<'EOF'
...
EOF
```

**Push** — the first push of a Paseo branch needs `-u` (Paseo creates branches with `--no-track`):

```bash
git push -u origin HEAD      # first push
git push                     # afterwards
```

**Push what is already committed** — the same `git push`, with no `git add` or `git commit` before
it.

**Confirm it landed**: `git status --porcelain` prints nothing and `git rev-parse HEAD` equals
`git rev-parse @{u}`.

**Push rejected** (the remote branch moved): `git pull --no-rebase`, then push again. A conflict →
resolve it (`fix-conflicts` skill), commit, push. Never `--force`: review comments anchor to the
pushed commits.

## Publish

PRs here are never drafts: one opens ready for review at the first push of a branch. So publish
means the PR exists and its description is current.

- **No PR for the branch** (`gh pr view` fails) → open it:

  ```bash
  gh pr create --base main --title "<subject-style title>" --body-file - <<'EOF'
  <what changed and why>

  🤖 Generated with [Claude Code](https://claude.com/claude-code)
  EOF
  ```

- **PR exists** → read the body with `gh pr view --json body --jq .body`, write the new one with
  `gh pr edit --body-file - <<'EOF' … EOF`.
- **A draft exists anyway** (opened by hand) → `gh pr ready`.
- **Tracker**: none. Skip the tracker comment and say so in the hand-off.
- End the turn with the PR URL (`gh pr view --json url --jq .url`).

## Stack

GitHub's native stacked pull requests: one change, several PRs, each based on the one below, and
one squash commit per node on `main`. Node 1 is the task branch; node `k` is `<branch>--s<k>`. The
`stacks` endpoints have no `gh` subcommand, so they go through `gh api`.

**Read the chain** (nodes bottom first):

```bash
gh api "repos/kedrzu/skills/stacks?pull_request=$(gh pr view --json number --jq .number)" \
  --jq 'if length == 0 then "not stacked" else .[0] | {stack: .number, nodes: [.pull_requests[] | {number, branch: .head.ref, state}]} end'
```

**Add a node** on top of the current node `k`, which must be committed and pushed:

```bash
git switch -c <branch>--s<k+1>
# commit the node's changes (Checkpoint), then:
git push -u origin HEAD
gh pr create --base <branch of node k> --title "..." --body-file - <<'EOF'
...
EOF
# the first time, create the stack from all its PRs, bottom first:
gh api -X POST repos/kedrzu/skills/stacks -F 'pull_requests[]=<pr 1>' -F 'pull_requests[]=<pr 2>'
# afterwards, append to the existing stack:
gh api -X POST repos/kedrzu/skills/stacks/<stack number>/add -F 'pull_requests[]=<new pr>'
```

**Check out the tip**: `git switch <branch of the last node>`. **Check out node `k`**:
`git switch <branch of node k>`. A branch that another worktree holds cannot be switched to here:
work on it in that worktree.

**Propagate an edit to a lower node** without force-pushing — commit and push it on node `k`, then
merge each node into the one above it, in order, up to the tip:

```bash
git switch <node k+1> && git merge --no-edit <node k> && git push
git switch <node k+2> && git merge --no-edit <node k+1> && git push
# ... up to the tip
```

A conflict stops the walk on that node: resolve it there, commit, push, and carry on upward.

**Catching up with `main`**: merge `origin/main` into the **bottom** node only
(`git fetch origin main && git switch <node 1> && git merge --no-edit origin/main && git push`), then
propagate upward as above. Never merge `main` into a higher node.

**What stays in the bottom node**: nothing is pinned there. But CI's version guard compares every
PR with its own base, the node below, so **each node bumps the version of every plugin it changes**,
relative to the node below. Two nodes changing `dev` bump it twice (`0.6.0` in node 1, `0.6.1` in
node 2).

**Landing**: the whole chain at once (Land). Never merge a mid-stack PR in the GitHub UI: it lands
every node below it and leaves the rest open.

## Land

On the owner's request only. It is irreversible and lands on `main`.

- **One PR**: `gh pr merge <number> --squash --match-head-commit <head sha>` — the squash commit's
  subject is the PR title with `(#<number>)`, as in `git log`. Branches are not deleted on merge
  here; leave them.
- **A stack**: merge the **top** PR asynchronously; GitHub lands every node below it first, one
  squash commit each, in order:

  ```bash
  uuid=$(gh api -X PUT repos/kedrzu/skills/pulls/<top pr>/merge-async \
    -f merge_method=squash -f sha=<top head sha> --jq .uuid)
  gh api repos/kedrzu/skills/pulls/<top pr>/merge-async/$uuid --jq .status   # poll until merged or failed
  ```

After landing, CI on `main` tags each bumped plugin as `<plugin>--v<version>` (`CLAUDE.md` →
"Releases and CI"). Nothing else to do.
