---
name: fix-conflicts
description: >-
    Resolve git merge, rebase, or cherry-pick conflicts by analyzing the full context — what each
    side changed, why, and how the incoming change interacts with the branch's intent — instead of
    picking a side. Classifies every hunk, synthesizes a result that keeps both sides' goals,
    escalates contradictory design decisions, then verifies and pushes. Run it when a merge, rebase
    or cherry-pick has stopped on conflicts, or when git status shows unmerged paths.
disable-model-invocation: true
---

# Fix conflicts

Resolve git conflicts by understanding the intent behind BOTH sides, not by picking one.
Naive "keep ours / keep theirs" silently drops work and breaks code. The job is to synthesize
a result that preserves both sides' goals — as if one author wrote it.

> Announce: **Resolving git conflicts with full context analysis.**

Escalate to the user instead of resolving when the conflict is a **contradictory design decision**
(defined in Phase 3 — it is a specific, narrow thing, not "this looks hard").

## The one gotcha that flips everything: ours/theirs during rebase

During a **merge**, `<<<<<<< HEAD` / `--ours` is YOUR branch and `>>>>>>>` / `--theirs` is the
incoming branch — as you'd expect.

During a **rebase**, it is **SWAPPED**: your commits are replayed on top of the upstream, so
`<<<<<<< HEAD` / `--ours` is the **upstream** branch and `>>>>>>>` / `--theirs` is **your own**
commit being replayed. Reason: rebase makes the upstream the base and treats each of your commits as
the thing being applied.
→ Never reason about a rebase conflict using the words "ours"/"theirs". Reason about it as
**upstream side vs my-branch side**, which you identified from the refs in Phase 1. Cherry-pick
behaves like rebase: `--theirs` is the commit being picked.

## Phase 1: Assess the conflict state

Identify the operation and the files. Run from the repository root:

```bash
git status                              # tells you merge / rebase / cherry-pick, and lists unmerged paths
git diff --name-only --diff-filter=U    # exact list of conflicted files (content conflicts)
git status --porcelain                  # UU=both modified, UD/DU=modify/delete, AA=both added, DD=both deleted
```

`git status` wording maps to the operation:

|Wording in `git status`|Operation|Incoming side is…|
|-|-|-|
|"You have unmerged paths" (+ `MERGE_HEAD` exists)|merge|`MERGE_HEAD`|
|"interactive rebase in progress" / "rebasing"|rebase|`REBASE_HEAD` (your replayed commit)|
|"You are currently cherry-picking commit …"|cherry-pick|`CHERRY_PICK_HEAD`|

Record: **operation type**, **conflicted file list**, **incoming ref** (from the table),
**base/target ref** (`HEAD` for merge; the upstream you're rebasing onto for rebase; the current
branch for cherry-pick).

If a tool (a stacked-PR CLI, a sync script) started the operation and stopped on the conflict,
resolve on the branch it left checked out and hand back to that tool when done — it knows what
remains to be merged; do not finish its cascade by hand.

## Phase 2: Gather context — do not skip

Intent is the whole game. A hunk you can't classify is a hunk whose intent you haven't read yet.

**This branch's intent (the base you're integrating into):**

```bash
# <base-ref> = the target branch for a merge; the upstream branch (the thing you rebased onto) for a rebase/cherry-pick
MERGE_BASE=$(git merge-base HEAD <base-ref>)
git log --oneline "$MERGE_BASE"..HEAD               # what this branch did since diverging
gh pr view --json title,body 2>/dev/null            # the "why", when a PR exists
```

**Incoming changes:**

```bash
# merge:
git log --oneline "$MERGE_BASE"..MERGE_HEAD
# rebase — the patch currently failing to apply:
git rebase --show-current-patch
# cherry-pick:
git show CHERRY_PICK_HEAD --stat
```

**Per conflicted file — what each side did to it** (this is what lets you classify each hunk):

```bash
git diff "$MERGE_BASE"..HEAD -- <file>          # base-side change to this file
git diff "$MERGE_BASE"..MERGE_HEAD -- <file>    # merge: incoming-side change
git show REBASE_HEAD -- <file>                  # rebase: incoming (your replayed commit) change
git show CHERRY_PICK_HEAD -- <file>             # cherry-pick: incoming change
```

The point is to know, for each side, whether it was **refactoring structure, adding a feature,
fixing a bug, or changing behavior** — that determines the resolution below.

## Phase 3: Resolve each conflict

For each conflicted file: read it (with the `<<<<<<< ======= >>>>>>>` markers), classify each hunk,
resolve, then `git add <file>`.

Two kinds of path are not resolved by editing markers — read
`${CLAUDE_PLUGIN_ROOT}/skills/fix-conflicts/references/special-cases.md` when one is conflicted:

- a **submodule** (`git status --porcelain` shows `UU <path>` for a directory, `CONFLICT (submodule)`);
- a **generated file** — a lockfile or any other output a tool regenerates from source.

### Classify the hunk — decision ladder (check top-to-bottom, FIRST match wins)

A hunk can look like several rows. Always take the **first** row it matches; that row is the most
specific handling. Only fall through when it genuinely doesn't match.

|#|Type|It looks like…|Resolution|
|-|-|-|-|
|1|**Import conflict**|Both sides added/removed `import` lines in the same block|Union all imports, drop exact duplicates, keep one sorted block|
|2|**Both-added / parallel addition**|Both sides inserted NEW code at the same spot; neither touched pre-existing lines|Keep BOTH additions, ordered logically|
|3|**Add vs modify**|One side added new code, the other edited the surrounding existing code|Place the addition INTO the edited context|
|4|**Structural refactor vs edit**|One side moved/renamed/reshaped the code (extracted a function, changed a data structure); the other edited the OLD shape|Re-apply the other side's edit **inside the new structure** (see decision tree)|
|5|**Modify / delete**|`git status` showed `UD`/`DU`; one side deleted the file/block, the other modified it|Decide via the decision tree; resolve with `git add` (keep modified) or `git rm` (accept delete), NOT by editing markers — see note below|
|6|**Divergent modification**|Both sides edited the SAME existing lines to different values|Decision tree: same intent → synthesize; contradictory design decision → escalate|

Modify/delete conflicts (row 5) do NOT contain `<<<<<<<` markers in the file — git leaves the
modified version whole in the tree. Resolve by choosing: `git add <file>` keeps it; `git rm <file>`
accepts the deletion.

### Resolution decision tree (the judgment calls, made concrete)

- **One side refactored structure + the other side changed behavior** → apply the **behavior change
  into the new structure**. The refactor is how the code is shaped now; the behavior change is what
  it must do. Example: this branch renamed `getUser` → `loadUser` and split it; incoming fixed a null
  check inside the old `getUser` → put the fixed null check inside the new `loadUser`.
- **One side deleted code the other modified** → find out if the deletion was a **move** (search the
  incoming diff for the same lines landing elsewhere: `git show REBASE_HEAD` /
  `git diff "$MERGE_BASE"..MERGE_HEAD`). Moved → re-apply the modification at the new location. Truly
  removed on purpose → drop it, but only after confirming intent in the commit/PR. Uncertain →
  escalate.
- **Both sides changed the SAME function's signature or contract in DIFFERENT ways** → **escalate.**
  This is the "contradictory design decision" — two authors made incompatible API choices and you
  cannot know which the team wants.
- **A rename is NOT a contradictory design decision.** If one side merely renamed a
  symbol/param/file and the other used the old name, apply the rename to the other side's usage and
  move on — do not escalate.

### Resolution principles

- **Never blind-pick a side.** Even the "less important" side's change exists for a reason;
  understand it before discarding.
- **The branch's own PR intent wins on code SHAPE.** If this PR reshaped a signature and the incoming
  used the old one, update the incoming usage to the new signature (that is the "apply into new
  structure" rule above).
- **Preserve every distinct piece of new functionality** from both sides.
- **Match the surrounding style** — the result must read like one author, not a stitch of two
  branches.

## Phase 4: Complete the operation

Only after every conflicted file is resolved and `git add`ed:

```bash
git merge --continue         # merge
git rebase --continue        # rebase
git cherry-pick --continue   # cherry-pick
```

A **rebase replays commits one at a time**, so new conflicts can appear on the next commit after
`--continue`. When they do, repeat Phases 1–3 for that commit (its incoming side is the new
`REBASE_HEAD`) — the ours/theirs swap still applies.

## Phase 5: Verify

The resolution is untested code until the checks pass. Run the project's full verification — its
`verify` skill when it has one, otherwise the checks its `CLAUDE.md` / `AGENTS.md` / README / CI
config prescribe (typecheck, lint, tests, build). Fix every failure before Phase 6. Regenerate any
generated file you cleared in Phase 3 before verifying.

If a failure looks caused by a wrong resolution (a symbol that should exist is missing, a behavior
that should be there is gone), **go back to Phase 3** for that file before patching the symptom — a
bad merge fixed by adding code on top hides the real mistake.

## Phase 6: Push

After verification is fully green, push the way the project pushes — its commit/push skill or
documented flow when it has one, otherwise `git push`. A resolution that touched a submodule's own
files is published in the submodule first (see the special-cases reference).

If the push is rejected, **do NOT force-push.** Report it to the user and let them decide — a
rejected push after a conflict resolution usually means the remote moved again, and force-pushing
can destroy the resolution.

## Escalate to the user when

Stop and ask instead of guessing when:

- Both sides made a **contradictory design decision** — same function's signature/contract changed
  incompatibly, or one side replaced a component the other extended. (A rename is not this.)
- The conflict is **business logic** where both outcomes are valid but different.
- A **large block was deleted on one side and heavily modified on the other** and you can't confirm
  the deletion was intentional.
- You are **genuinely uncertain of either side's intent** after reading its commit messages and diffs.

Present: (1) what each side was trying to do, **with commit references**; (2) why you can't
confidently resolve it; (3) your suggested resolution and why, or two concrete options to choose
from.

## References

- `${CLAUDE_PLUGIN_ROOT}/skills/fix-conflicts/references/special-cases.md` — read when a submodule
  or a generated file (lockfile, codegen output) is among the conflicted paths, and before pushing a
  resolution that touched a submodule's files.
