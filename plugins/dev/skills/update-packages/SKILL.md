---
name: update-packages
description: Update every package in the repository in verified batches, and surface dependencies that were deprecated, renamed or abandoned.
disable-model-invocation: true
---

# Update Packages

Update every package in this repository, in batches, green-to-green after each batch, publishing
submodules before the main repository — and surface every dependency that was deprecated, renamed or
abandoned, which no version check will show you.

The run is unattended: it fires from a schedule, works for hours or days, and leaves behind two
artefacts a human reads — the PR and the tracker issue. Decide without asking; whatever needs the
owner goes into the run report.

Announce when you start: "Updating packages — verifying baseline first, then batching by ecosystem."

## What the project provides

- **`verify`** and **`git-workflow`** — the project contracts
  (`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/contracts.md`). Verification comes only from
  `verify` (scoped while iterating, full before every commit); every commit, push, submodule publish,
  PR description and tracker comment comes only from `git-workflow` (**checkpoint** per batch,
  **publish** for the report). Missing either → stop and say which, as the contracts file says.
- **The notebook** — `docs/package_update.md` (**General Rules** + **Known Issues**) and
  `docs/dependency-health.md` (the dependency-health log). Read both at the start, update them at
  the end. Missing on a first run → create them from
  `${CLAUDE_PLUGIN_ROOT}/skills/update-packages/references/notebook-template.md`.
  - **General Rules** are persistent constraints — couplings ("update only together with Y", "must
    match the version X bundles"), override reasons, and the project's special procedures: a
    container image tag versioned like a dependency, how to collapse duplicate dependency trees,
    which bumps need a rebuild before e2e. Follow them before touching a named package; never remove
    one unless its constraint is gone.
  - **Known Issues** are version-specific failures. Never retry a known-broken update; remove the
    entry only when a newer version resolves it.
- **Language** — the chat summary is in the owner's language (the project's `CLAUDE.md` /
  `CLAUDE.local.md`); everything committed, the PR and the tracker comment are English.

## When NOT to use

- Verifying or fixing the codebase with no dependency change → the project's `verify` skill.
- Committing or pushing unrelated changes → the project's `git-workflow` skill.
- A lockfile conflict during a merge or rebase → `/git:fix-conflicts` (the `git` plugin): it keeps
  the target side's locked versions and lists every version resolved fresh.

## The one rule of a monorepo

**Never run `bun update <pkg>` (a named package) from the repository root.** `bun update` saves by
default, and "save" means *the manifest in the current directory* — the **root** `package.json`,
not the workspace that uses the package. So it does not bump the dependency where it lives: it *adds
a new root dependency*, leaves the workspace copy stale, and breaks the "one version, declared in the
workspace that uses it" model. Any package manager whose targeted update writes to the
current-directory manifest has the same trap.

Two commands are safe:

- **Bare `bun update`** (no name) — moves the lockfile within the existing ranges across all
  workspaces at once. Enough for minor/patch batches that need no range change. It moves nothing
  pinned exactly, and it never touches `overrides`.
- **`bun install`** — regenerates the lockfile from what the manifests say. This is how a hand edit
  is applied.

To move a version, per package or batch:

1. Find the workspace manifests that declare it. Workspaces are exactly the globs in the root
   manifest's `workspaces` field — read them, never assume paths:

   ```bash
   jq -r '(.workspaces | if type == "object" then .packages else . end) // [] | .[]' package.json \
     | xargs sh -c 'for g do ls -d $g/package.json 2>/dev/null; done' _ \
     | xargs grep -l '"<pkg>"'
   ```

2. Edit the version in each match by hand — an exact pin in a product workspace, a range in a
   shared one (Library mode below).
3. If it also appears in the root `devDependencies` or `overrides`, edit it there too (Preflight).
4. `bun install`.
5. Verify — scoped while iterating, full before the commit.

## Library mode — product vs shared workspaces

A workspace is **shared** when it lives inside a git submodule of this repository or its manifest is
not `"private": true`; everything else is a **product** workspace and keeps exact pins. Before editing
a shared workspace's manifest, read
`${CLAUDE_PLUGIN_ROOT}/skills/update-packages/references/library-mode.md` — it holds the rules, the
reasons and a lockfile duplicate-copy gotcha.

## Preflight — the root constraints (after Phase 1, before Phase 2)

The root `package.json` holds versions the whole repository must agree on. Miss them and two copies
of a package install side by side, which shows up as "two different types with this name exist but
are unrelated" errors at every shared-type boundary.

- **`overrides`** — bare `bun update` does not touch them. Bumping an overridden package means
  editing its override by hand, or the override silently holds it back.
- **`devDependencies`** — root dev tools act as global constraints. A package listed here is bumped
  here too whenever it is bumped in a workspace.

Then re-read the notebook's General Rules for the couplings they record.

## Batch categories

- **Safe** (batches of 5–15, grouped by ecosystem): cloud SDKs, `@types/*`, test/dev tools, build
  tools, utility libraries, backend libraries, monitoring/logging, external API clients.
- **Risky** (one at a time, own commit): the UI framework and its router/state, the meta-framework,
  UI/CSS tooling, the bundler, TypeScript majors, packages that live in a git submodule of this
  repository.
- **Rule of thumb**: anything that feeds the app build pipeline, or is a major bump with breaking
  changes, is risky; everything else is safe.

Full lists and the decision tree: `${CLAUDE_PLUGIN_ROOT}/skills/update-packages/references/batch-strategy.md`.

## Process

### Phase 1 — Verify the baseline

Run the full `verify` protocol. Anything red → stop, fix it, commit the fix (**checkpoint**), and only
then start — on a red codebase you cannot tell which failure a batch introduced.

### Phase 2 — Find outdated and deprecated packages

```bash
bun outdated -r
```

Save the output (its `Workspace` column shows where each dependency lives) — this is the work list.
Categorize it against the batch categories.

`bun outdated` compares versions and nothing else. A package its authors abandoned or replaced sits on
its final version, so it is never outdated — `rollup-plugin-terser` stayed on 7.0.2 for years after
`@rollup/plugin-terser` replaced it, and its process-forking worker came along unnoticed. The registry
carries a `deprecated` message; this checks every direct dependency in seconds, skipping the
project's own workspace packages:

```bash
manifests=$(jq -r '(.workspaces | if type == "object" then .packages else . end) // [] | .[]' package.json \
  | xargs sh -c 'echo package.json; for g do ls -d $g/package.json 2>/dev/null; done' _)
own=$(echo "$manifests" | xargs jq -r '.name // empty' | sort -u)
echo "$manifests" \
  | xargs jq -r '[.dependencies,.devDependencies,.peerDependencies,.optionalDependencies][] | select(.) | keys[]' \
  | grep -vxF -f <(echo "$own") | sort -u \
  | xargs -P 16 -n 1 sh -c 'for pkg do out=$(bun info "$pkg" deprecated 2>&1); rc=$?
      msg=$(printf "%s\n" "$out" | grep -v "^\[[0-9.]*ms\] ")
      if [ $rc -eq 0 ]; then echo "$pkg: $msg"
      else case $msg in *"Property deprecated not found"*) ;; *) echo "$pkg: LOOKUP FAILED: $msg" >&2; exit 1 ;; esac; fi; done' _
```

The loops name their values (`for g do`, `for pkg do` walk the positional arguments) because a skill
invoked with arguments has every numbered positional token (a dollar sign followed by a digit) in
this file replaced by them — never write one here.

It reads the latest version, so every hit is a package that is dead or has moved — a finding for
Dependency health, not an item for the work list. A non-zero exit means some lookups failed
(registry error, rate limit), listed as `LOOKUP FAILED`: rerun those before treating the list as
complete — a failed lookup prints nothing on stdout, exactly like a healthy package.

### Dependency health — escalate, never migrate

Replacing a library is a migration with its own risk, and whether it happens now, later or never is
the owner's call. The run never swaps one package for another, however mechanical the swap looks; it
puts each one under **Needs your decision** in the run report.

`docs/dependency-health.md` holds the date of the last full review, every finding and the owner's
decision on each; its lead paragraph defines the entry format. A finding that already carries a
decision is not raised again unless its situation changed; one still `pending` goes into every report
until it gets one.

The registry flag only catches authors who bothered to set it. When the last full review is a month
old or more, review every direct dependency — fan them out to Sonnet subagents with
`${CLAUDE_PLUGIN_ROOT}/skills/update-packages/references/dependency-review.md`. Record new findings
and the review date in the log.

### Phase 3 — Safe batches

For each batch (5–15 packages, one ecosystem):

1. Edit the versions in the workspace manifests (and root `overrides`/`devDependencies`).
2. `bun install`.
3. Verify — scoped while iterating, the **full** protocol before committing; a green scoped run is
   not a green codebase.
4. **Green** → commit and push (Phase 5).
5. **Red** → bisect to the offending package, revert just that one, move it to the risky list.

### Phase 4 — Risky packages, one at a time

Edit → `bun install` → full verify → commit if green. If red, classify:

|Situation|Classification|Action|
|-|-|-|
|Type errors confined to **call sites** (rename, moved export, signature tweak) and the fix stays inside 1–2 packages|**Easy**|Fix inline, verify, commit with the bump|
|Needs an **API redesign**, changes **runtime/behavioural** semantics, or the failure touches **3+ packages**|**Hard**|Revert the bump, add a **Known Issues** entry, give it its **own** commit (not folded into a batch), move on|

The split keeps a routine batch from smuggling a migration: a hard update is a mini-project that
deserves isolation and a paper trail, not a line in "Update AWS SDK packages".

Cases the version list does not show:

- **Duplicate dependency trees** — when two workspaces (often one inside a submodule) declare
  drifting versions of one package, two trees install, and type errors flood code that did not
  change (TS2883 "inferred type cannot be named … not portable", "two different types with this
  name"). They are an install artefact, not source bugs: align the versions, then collapse the trees
  as the General Rules say (typically pruning `node_modules` and installing again from the kept
  lockfile), and re-verify. The same thing happens after a branch switch or merge that moved a
  submodule pointer when install ran before the submodule update.
- **Versions outside the package manager** — a container image tag or tool version pinned in a
  config file is not in `bun outdated`. Update those the General Rules list, each with its own
  procedure: edit the tag, recreate what runs it, full verify; green → commit, red → revert, recreate
  the old one, record a Known Issue.
- **Build-pipeline bumps** (framework, bundler, CSS tooling) leave the build output stale until
  rebuilt; the full `verify` protocol owns rebuilding before e2e. What it cannot do: tell the owner,
  in the report's **Manual action needed**, to restart any dev server he runs — a test runner that
  reuses a running dev server serves pre-bump code.

### Phase 5 — Commit strategy (submodule-aware)

`bun install` updates every workspace from the root, but a submodule is a separate repository: its
manifest and lockfile changes are committed and pushed there FIRST, then the main repository records
the new pointer. Both go through `git-workflow` **checkpoint**, which owns that order and its
commands.

- **One submodule branch and PR for the whole run**, gaining a commit per batch.
- Detect submodule changes with `git -C <submodule> status --porcelain` (dirty files) and
  `git status --porcelain <submodule>` (a moved pointer).
- Commit messages name the batch ("Update AWS SDK packages"), or list the packages of a single risky
  bump.

## Failure handling

|Situation|Action|
|-|-|
|A check goes red after a batch|That batch caused it. Bisect (halve and re-verify) or revert the whole batch and re-add packages one by one|
|A single risky bump is red and hard to fix|Revert it, log it under **Known Issues** with the exact error, its own commit — do not retry it this run|
|Type errors flood code that did not change|Duplicate trees — see Phase 4|
|"Cannot find module" for the project's own workspace packages after `bun install`|A missing workspace link — run `bun install` again (or a clean reinstall)|

### Phase 6 — Document and report

Update `docs/package_update.md` in the format of the template: a constraint that persists across
versions goes in **General Rules**; a version-specific failure in **Known Issues**, deleted once a
newer version fixes it.

Then write the run report — ONCE, at the end, after `git-workflow` **publish** has taken the PR out of
draft — and send the same report everywhere **publish** puts the PR description and the tracker
comment, replacing a pre-run inventory in the PR body. Send a short chat summary in the owner's
language: the headline, every dependency waiting for his decision, any manual action, links to the PR
and the tracker issue.

Derive the report from git, never from memory — the early batches of a multi-day run are long out of
context. Every line of the final `bun outdated -r` appears in it with a reason; a package never
attempted is a skip too. Commands, section order and a worked example:
`${CLAUDE_PLUGIN_ROOT}/skills/update-packages/references/run-report.md`.

## References

- `${CLAUDE_PLUGIN_ROOT}/skills/update-packages/references/batch-strategy.md` — per-ecosystem safe/risky lists and the decision tree. Read when categorizing `bun outdated`.
- `${CLAUDE_PLUGIN_ROOT}/skills/update-packages/references/library-mode.md` — ranges, peers and bounds in shared workspaces. Read before editing a submodule's or a published workspace's manifest.
- `${CLAUDE_PLUGIN_ROOT}/skills/update-packages/references/dependency-review.md` — signals of an abandoned dependency. Read for the monthly full review.
- `${CLAUDE_PLUGIN_ROOT}/skills/update-packages/references/run-report.md` — the report's sources, sections and example. Read when writing it.
- `${CLAUDE_PLUGIN_ROOT}/skills/update-packages/references/notebook-template.md` — skeletons of both notebook files. Read when either is missing or you add an entry.
- `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/contracts.md` — what `verify` and `git-workflow` provide.
