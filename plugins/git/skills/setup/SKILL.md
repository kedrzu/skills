---
name: setup
description: Configure how changes move in this project — write its `git-workflow` skill and `.claude/git.json`, or check them.
disable-model-invocation: true
---

# /git:setup — write down how a change moves in this project

Arguments passed: `$ARGUMENTS`

Two files, both committed, both following from one decision — **does `main` take direct pushes, or
only pull requests?**

- `.claude/skills/git-workflow/SKILL.md` — the project's own skill with every git and PR command an
  agent needs. The `dev` pipeline (`/dev:fix` … `/dev:deliver`, `/dev:review`,
  `/dev:fix-pr-comments`) takes all of them from here and stops when it is missing.
- `.claude/git.json` — read by this plugin's hook, which blocks an agent's push to any branch listed
  in it: `{ "protectedBranches": ["main"] }`. Without the file every branch takes pushes.

The two must agree: a `git-workflow` that lands changes through PRs lists the main line in
`protectedBranches`; one that pushes to `main` directly has no entry for it (and no file, unless
another branch is protected).

## 1. Take stock

Read both files if they exist, the project's `CLAUDE.md` and its other skills. The knowledge often
already exists under another name — a commit-and-push skill, a PR checklist. One owner per fact:
point at it rather than copy it.

`git-workflow` needs one section per operation, in this order:

- **Start** — put the work on a branch for its task; open a draft PR and link the tracker issue if the
  project does so.
- **Checkpoint** — commit in the project's convention and push, including whatever must be published
  first (submodules, other repositories) and how to confirm the push landed. Also how to **commit
  only a given set of files** (nothing else staged) and how to **push what is already committed**.
- **Publish** — the "ready for review" signal: out of draft, the PR description, the tracker comment,
  and how the tracker issue is identified.
- **Stack** — a chain of dependent PRs: add a node on top, **propagate an edit to a lower node upward
  without force-pushing**, **check out the tip**, **check out node `k`**, what must stay in the bottom
  node, how the chain lands.
- **Land** — how a finished change is merged; run only on the owner's request.

A section that misses one of the bold items has a gap of exactly that item. A section that says the
project does not do something counts as covered — that is an answer, not a gap.

**Everything covered and the two files agree → report it, one line per operation plus one for
`.claude/git.json`, and stop without writing anything.** Re-running on a configured project ends here.

## 2. Find the answers in the repository

Evidence before questions: the remote and its host (`git remote -v`; `gh` or `glab` available?),
branch names and commit style from `git log`, PR templates, `.gitmodules`, how branches and commits
name tracker issues, which tracker tools this session has, any CLI the project wraps git with. Branch
protection on the host is the strongest evidence for the main-line decision
(`gh api repos/{owner}/{repo}/branches/main/protection`, read-only), and `git log --first-parent main`
shows whether `main` grows by merged PRs or by direct commits.

Run a command before you write it down, where it is safe to (read-only). A recorded command nobody
has run is a guess, and a wrong guess fails silently.

## 3. Ask what the repository cannot tell you

One round, genuine gaps only, each with the answer you would recommend: direct pushes to `main` or
PRs only; which tracker, and how an issue is tied to a branch; whether PRs open as drafts; whether
changes ever land as stacks; who lands a change and how.

## 4. Write

- `git-workflow` as the project's own skill: its facts and commands, in its conventions, sections in
  the order above. One line says it fulfils the `dev` pipeline's `git-workflow` contract; the
  description says the pipeline relies on it and when else to reach for it (any commit, push or PR).
- An existing skill with partial coverage gets the missing sections or sub-items added; what is
  already there stays.
- Never write a command you neither saw nor ran. An operation the project does not do is written as
  unsupported, with a sentence why.
- `.claude/git.json` to match: the main line in `protectedBranches` when it takes only PRs. Keep any
  other key already in the file.

## 5. Report

What already existed, what you wrote, which commands you confirmed by running them, and what is
unsupported. Leave the files uncommitted for the user to read — unless they asked you to land them.
