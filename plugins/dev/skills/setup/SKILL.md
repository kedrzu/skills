---
name: setup
description: Configure a project for the dev pipeline: write, or check against the contract, its `verify` skill and the owner's language.
disable-model-invocation: true
---

# /dev:setup — give the pipeline what it needs from this project

Arguments passed: `$ARGUMENTS`

The definition of done is `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/contracts.md`. Read it
first: every step below is measured against it, and nothing beyond it is this skill's business —
except one setting that belongs to the person rather than the project, **the owner's language**.

The contract's other half, `git-workflow`, is written by `/git:setup` from the `git` plugin, together
with the hook configuration that has to agree with it. This skill only checks that it exists.

`/dev:review`, `/dev:fix-pr-comments` and the pipeline write PR comments, plans and chat in the
language named for human-facing text in his personal `CLAUDE.local.md` at the project root, else
in the project's `CLAUDE.md` — falling back to the language he writes in. That fallback works for you
and fails for every subagent, which sees only its brief; a named rule is what reaches them.

## 1. Take stock

Look for `.claude/skills/verify/SKILL.md` and map what it says against the contract: it needs a
scoped mode and a full one. Look for `.claude/skills/git-workflow/SKILL.md` too; missing, or missing
one of start, checkpoint, publish, stack and land → the report tells the user to run `/git:setup`.

Check the owner's language the same way: a rule in `CLAUDE.local.md` or the project's
`CLAUDE.md` naming the language for human-facing text covers it, whatever its wording.

Read the project's `CLAUDE.md` and its other skills too. The knowledge often already exists under
another name — a test-running script, a CI checklist. One owner per fact: point at it rather than
copy it.

**Everything covered → report it, one line each for `verify`, `git-workflow` and the language, and
stop without writing anything.** That is the idempotent case, and re-running this skill on a
configured project must end there.

## 2. Find the answers in the repository

For each gap in `verify`, evidence before questions: the manifests and their scripts
(`package.json`, `Makefile`, `justfile`, `pyproject.toml`, `Cargo.toml`, …), CI workflows and their
required checks, `README` / `CONTRIBUTING`, `CLAUDE.md`. Which commands type-check, lint, format,
test and build; which of them are cheap enough to run after every task; how scope follows from the
changed paths (one package in a monorepo, or the whole project).

Run a command before you write it down, where it is safe to (read-only, or the project's own test
and lint commands). A recorded command nobody has run is the kind of guess the contract exists to
prevent.

## 3. Ask what the repository cannot tell you

One round, genuine gaps only, each with the answer you would recommend: which steps the full
verification must include when CI does not say; and, with no language rule found, which language he
wants — recommend the one he is writing to you in.

## 4. Write

- `verify` as the project's own skill: its facts and commands, in its conventions, with a **Scoped**
  section and a **Full** section. The only mention of this plugin is a line saying which contract the
  skill fulfils; the description says the dev pipeline relies on it, and when else to reach for it.
- An existing skill with partial coverage gets the missing section added; what is already there
  stays.
- Never write a command you neither saw nor ran.
- The language goes into `CLAUDE.local.md` at the project root as one line, e.g.
  `- Human-facing text (PR comments, plans, specs, chat replies): Polish.` — never into the
  project's `CLAUDE.md`: it is his preference, and a teammate's may differ. Make sure git ignores
  it (`git check-ignore CLAUDE.local.md`). Being uncommitted, it is absent from every fresh
  worktree: if the project works in worktrees, its worktree setup has to copy it from the main
  checkout — say so in the report when it does not.

## 5. Report

What already existed, what you wrote, which commands you confirmed by running them, and — when
`git-workflow` is missing or incomplete — that `/git:setup` writes it. Leave the files uncommitted
for the user to read — unless they asked you to land them.
