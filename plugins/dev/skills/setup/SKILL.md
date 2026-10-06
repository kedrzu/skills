---
name: setup
description: >-
    Configure a project for the dev pipeline — inspect how it builds, tests and ships, ask about
    what the repository cannot tell, and write the two skills the pipeline relies on: `verify`
    (scoped and full checks) and `git-workflow` (branch, commit, push, review, stack, land,
    tracker). Idempotent: on a project that already has them it checks both against the contract
    and fills only what is missing. Run it when a /dev:* entry point stops on a missing contract,
    when adopting the pipeline in a new repository, or after the project's build or release
    process changed.
disable-model-invocation: true
---

# /dev:setup — give the pipeline what it needs from this project

Arguments passed: `$ARGUMENTS`

The definition of done is `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/contracts.md`. Read it
first: every step below is measured against it, and nothing beyond it is this skill's business.

## 1. Take stock

Look for `.claude/skills/verify/SKILL.md` and `.claude/skills/git-workflow/SKILL.md`, and map what
each says against the contract: `verify` needs a scoped mode and a full one; `git-workflow` needs
start, checkpoint, publish, stack and land — and within them the sub-operations the contract names:
checkpoint's selective commit and push-only, stack's propagate-upward-without-force-push,
check-out-the-tip and check-out-node-`k`. A
section that has the operation but misses one of those has a gap of exactly that item. A section
that says the project does not do something counts as covered — that is an answer, not a gap.

Read the project's `CLAUDE.md` and its other skills too. The knowledge often already exists under
another name — a commit-and-push skill, a test-running script, a PR checklist. One owner per fact:
point at it rather than copy it.

**Everything covered → report it, one line per contract operation, and stop without writing
anything.** That is the idempotent case, and re-running this skill on a configured project must end
there.

## 2. Find the answers in the repository

For each gap, evidence before questions:

- **verify** — the manifests and their scripts (`package.json`, `Makefile`, `justfile`,
  `pyproject.toml`, `Cargo.toml`, …), CI workflows and their required checks, `README` /
  `CONTRIBUTING`, `CLAUDE.md`. Which commands type-check, lint, format, test and build; which of
  them are cheap enough to run after every task; how scope follows from the changed paths (one
  package in a monorepo, or the whole project).
- **git-workflow** — the remote and its host (`git remote -v`; `gh` or `glab` available?), branch
  names and commit style from `git log`, PR templates, `.gitmodules`, how branches and commits name
  tracker issues, which tracker tools this session has, any CLI the project wraps git with.

Run a command before you write it down, where it is safe to (read-only, or the project's own test
and lint commands). A recorded command nobody has run is the kind of guess the contract exists to
prevent.

## 3. Ask what the repository cannot tell you

One round, genuine gaps only, each with the answer you would recommend: which tracker, and how an
issue is tied to a branch; whether PRs open as drafts; whether changes ever land as stacks; who
lands a change and how; which steps the full verification must include when CI does not say.

## 4. Write the skills

- Write them as the project's own skills: its facts and commands, in its conventions. The only
  mention of this plugin is a line saying which contract the skill fulfils.
- `verify`: a **Scoped** section and a **Full** section. `git-workflow`: one section per operation,
  in the contract's order — Start, Checkpoint, Publish, Stack, Land — with Checkpoint covering
  selective commit and push-only, and Stack covering propagate-upward-without-force-push,
  check-out-the-tip and check-out-node-`k`.
- The description says the dev pipeline relies on it, and when else to reach for it.
- An existing skill with partial coverage gets the missing sections — or the missing sub-items
  inside an existing section — added; what is already there stays.
- Never write a command you neither saw nor ran. An operation the project does not do is written as
  unsupported, with a sentence why.

## 5. Report

What already existed, what you wrote, which commands you confirmed by running them, and what is
unsupported. Leave the files uncommitted for the user to read — unless they asked you to land them.
