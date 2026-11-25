---
name: setup
description: Configure a project for the dev pipeline: write, or check against the contract, its `verify` skill and the languages it writes in.
disable-model-invocation: true
---

# /dev:setup — give the pipeline what it needs from this project

Arguments passed: `$ARGUMENTS`

The definition of done is `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/contracts.md`. Read it
first: every step below is measured against it, and nothing beyond it is this skill's business —
except the languages the pipeline writes in, which are a choice made per project, not a default.

The contract's other half, `git-workflow`, is written by `/git:setup` from the `git` plugin, together
with the hook configuration that has to agree with it. This skill only checks that it exists.

The pipeline writes for two audiences, and a project may want them in different languages: **the
owner's language** for the conversation with him — chat, plans, specs that stay local — and **the
repository language** for everything committed or posted — code, identifiers and names, docs, commit
messages, PR descriptions, review comments, thread replies, tracker comments — which teammates and
other agents read too. One project chooses a non-English repository language explicitly, the next
commits in English while its owner chats in Polish. `/dev:review` defines how both are read: from the
language rule in his `CLAUDE.local.md` at the project root, else in the project's `CLAUDE.md`. With
no rule the owner's language is the one he writes in, and the repository language is the one the
repository is already written in, English when that is unclear — never the one he chats in. Those
fallbacks work for you and fail for every subagent, which sees only its brief; a named rule is what
reaches them.

## 1. Take stock

Look for `.claude/skills/verify/SKILL.md` and map what it says against the contract: it needs a
scoped mode and a full one. Look for `.claude/skills/git-workflow/SKILL.md` too; missing, or missing
one of start, checkpoint, publish, stack and land → the report tells the user to run `/git:setup`.

Check the languages the same way: a rule in `CLAUDE.local.md` or the project's `CLAUDE.md` covers
them when it names the language of the conversation and of what is committed or posted, whatever
its wording.

Read the project's `CLAUDE.md` and its other skills too. The knowledge often already exists under
another name — a test-running script, a CI checklist. One owner per fact: point at it rather than
copy it.

**Everything covered → report it, one line each for `verify`, `git-workflow` and the languages, and
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
verification must include when CI does not say; and, for each of the two languages no rule names,
which one he wants for this project. Recommend the one he is writing to you in for the conversation,
and for the repository language the one the repository's code, docs and PRs are already written
in — English when that is unclear, never the chat language by default.

## 4. Write

- `verify` as the project's own skill: its facts and commands, in its conventions, with a **Scoped**
  section and a **Full** section. The only mention of this plugin is a line saying which contract the
  skill fulfils; the description says the dev pipeline relies on it, and when else to reach for it.
- An existing skill with partial coverage gets the missing section added; what is already there
  stays.
- Never write a command you neither saw nor ran.
- The languages go into `CLAUDE.local.md` at the project root as one line naming both, e.g.
  `- Chat, plans and specs: Polish. Everything committed or posted (code, docs, commits, PRs, issues, reviews): English.` —
  never into the project's `CLAUDE.md`: it is his preference, and a teammate's may differ. Make sure git ignores
  it (`git check-ignore CLAUDE.local.md`). Being uncommitted, it is absent from every fresh
  worktree: if the project works in worktrees, its worktree setup has to copy it from the main
  checkout — say so in the report when it does not.

## 5. Report

What already existed, what you wrote, which commands you confirmed by running them, and — when
`git-workflow` is missing or incomplete — that `/git:setup` writes it. Leave the files uncommitted
for the user to read — unless they asked you to land them.
