# Post-pipeline: commit, publish, changeset, tracker comment

The flow that runs after Phase 4 passes: commit → push → ready for review → PR changeset → tracker
comment → confirm → completion options. This file owns **what** is said and in which order; every
command comes from the project's `git-workflow` skill (`contracts.md`), so read the operation named
at each step before running it.

Consumed by: `fix`, `task`, `feature`, `build`, `deliver`, `pipeline`.

## Authorization — runs automatically

**This runs automatically after Phase 4 passes — do not wait for user confirmation and do not pause to ask permission.** Invoking the pipeline skill (`/dev:fix`, `/dev:task`, `/dev:feature`, `/dev:build`, `/dev:deliver`) is the user's authorization to commit, push, update the PR description, and post the tracker comment. The standing "don't change code without asking" preference governs the implement-vs-answer decision, NOT finalizing an already-approved pipeline run.

For `/dev:fix`, the user's approval at the diagnosis gate completes this authorization — finalization still runs without pausing.

This flow contains **no code-review step** — review is on-request only, never an implicit part of the pipeline. Do not add one.

## Step 1: Commit & push all changes

Two ordered actions, both `git-workflow` → **checkpoint**:

1. **Commit** everything with a real WHAT+WHY message in the project's convention — per-entry-point
   examples below. A real message now is what keeps the PR history readable; tooling that
   auto-commits leftovers under a generated label is the thing it beats.
2. **Push**, including whatever the checkpoint section says must be published separately first.

**Cutting a stacked chain happens between these two actions.** Commit the whole verified change, then cut it into nodes and push them bottom-up as `stacked-prs.md` describes — that recipe replaces the single push here, and the rest of this flow then runs per node where it says so. A change that stays one PR just pushes.

## Step 1b: Mark the PR ready for review

`git-workflow` → **publish**: take the PR out of draft. It is the "coding done, please review"
signal — it does **not** merge.

The flip is what makes the finished work visible, to a human and to a machine. A human reads draft
state as "still being written" and skips the PR, and any automation that waits for the review
signal — an orchestrator watching its task agents' PRs, a reviewer bot — never fires on a PR left
in draft. Nothing errors; the work just stalls.

- **No PR exists yet** → skip this; the "Create PR" completion option covers it.
- **Stacked chain** → mark ready **once, after the whole chain is up** (`stacked-prs.md`). The chain has ONE tracker issue, so write **one** tracker comment covering the whole chain — listing the nodes in bottom-up reading order — not one per node.

## Step 1c: Verify the push actually landed

Do not trust "the command printed success" — a skipped or partial push is the single most common finalization failure, and it still lets you print "pushed" if you don't check. Confirm the branch is really on its remote before going further. This gate is **mandatory and self-correcting**:

```bash
git status --porcelain    # must be empty — nothing left uncommitted/unstaged
git rev-parse HEAD         # local tip
git rev-parse @{u}         # upstream tip — must equal the local tip
```

- Working tree not clean, or `HEAD` ≠ `@{u}` → the push didn't fully land. Run the checkpoint push again, then re-check.
- `@{u}` errors ("no upstream configured") → the branch was never pushed. Push, then re-check.
- **Stacked chain** → this check is per node, run as each one is pushed; a node left local is a PR the human cannot read.
- **Something published separately** (a submodule, another repository) → confirm it landed too, as the checkpoint section says.
- Still failing after one retry → **STOP and surface the git error to the user**; do not proceed to Step 6 and never report "pushed" while `HEAD` ≠ `@{u}`.

## Step 2: Gather changeset data

From the completed pipeline run, prepare:

- **Entry point used**: `/dev:fix`, `/dev:task`, `/dev:feature`, `/dev:build`, or `/dev:deliver`
- **One-line title**: imperative mood (e.g., "Add patient notification preferences")
- **PR summary**: technical context that isn't obvious from reading the diff — features added, architectural decisions, reasoning behind the approach, edge cases handled. NOT a list of modified files (the PR diff already shows that). Bullet points with bold highlights for scannability.
- **Tracker summary**: plain-language description from a user/product perspective — new capabilities, changed behaviors, things stakeholders can or should test. No header, no date, no status info (the issue status handles that), no technical jargon.

The WHY in both summaries comes from a different artifact per entry point — see the per-entry-point table below.

## Step 3: Identify the tracker issue

`git-workflow` → **publish** says how this project ties a branch to its tracker issue (a pattern in
the branch name, a commit prefix). No issue found → skip Step 5 and say so in the Step 6
confirmation. Never guess or invent an issue ID — a comment on the wrong issue misinforms
stakeholders.

## Step 4: Update PR description

If no PR exists for the current branch yet, skip this step — the "Create PR" completion option covers it. On a chain, each node has its own PR and its own changeset, describing that node's layer. Otherwise read the current body (`git-workflow` → **publish**):

- Body contains `<!-- changeset-start -->` → insert the new entry before `<!-- changeset-end -->`
- No changeset section → append the full changeset block after the existing body content

Changeset block format (heading is `### <entry point> — <one-line title>`):

```markdown
<!-- changeset-start -->

## Changeset

### /dev:feature — Add patient notification preferences

- **New settings UI**: patients can toggle email, SMS, and push notification channels independently from a new tab in Settings
- **Preference persistence**: stored per-patient with clinic-level defaults as fallback — if a clinic disables a channel, patient toggle is ignored
- **Architecture**: notification preferences are a separate bounded context from notification dispatch to avoid coupling scheduling logic with user preferences

<!-- changeset-end -->
```

Each bullet must cover **what** changed AND **why** (WHY source per entry point — table below). Best-effort — if writing the description fails, log the error but do not block the pipeline.

## Step 5: Post the tracker comment (only if an issue was found)

Post through `git-workflow` → **publish**. The body is the plain-language tracker summary. **Lead with the WHY** (source per entry point — table below), then describe what changed and how stakeholders can test it. No header, no date, no status. Example:

```
Patients can now manage their notification preferences from the Settings page — they can toggle email, SMS, and push notifications on or off independently.

If you'd like to test: go to Settings → Notifications tab, toggle channels, save, and verify preferences persist after page reload. Also check that disabling a channel at clinic level overrides the patient setting.
```

Best-effort — if it fails, log the error but do not block the pipeline. Anything else the publish
section asks for while the issue is open (a label, a field) follows the same rule.

## Step 6: Confirm to user

One line: "Committed, pushed (verified on the remote), marked the PR ready for review, updated PR description and posted the tracker comment on <issue>." — only claim "pushed" once Step 1c confirmed `HEAD` == `@{u}`. Explicitly note anything skipped or fallen back (e.g., "no tracker issue found, skipped the comment"; "no PR yet, skipped ready"; "the project does not support stacks, landed as one PR"). Then present the completion options.

## Per-entry-point parameters

The flow is identical for every entry point; only these inputs differ. Do not average them — each entry point sources its WHY from a different artifact because that is where its user-approved context lives. Commit messages get the project's prefix or format from `git-workflow` → **checkpoint**; the examples show only the sentence.

|Entry point|Changeset heading|Commit message example|WHY source (PR bullets + tracker lead)|
|-|-|-|-|
|`/dev:fix`|`### /dev:fix — <title>`|`Fix patient login redirect loop`|The **approved diagnosis**: the bug/symptom and its root cause — not just the code that moved. The tracker comment leads with what was broken from the user's point of view, then what now works and how to verify the fix.|
|`/dev:task`|`### /dev:task — <title>`|`Implement observation list endpoint`|The **plan + the originating user request**: the problem this solves or the need it addresses. The tracker comment then describes the new capabilities and what stakeholders can test.|
|`/dev:feature`|`### /dev:feature — <title>`|`Add patient observation data layer`|The **spec's Problem/Scope section**. The tracker comment leads with the problem from the spec's Problem section, then the new capabilities and what stakeholders can test.|
|`/dev:build`|`### /dev:build — <title>`|`Build notification delivery subsystem`|Same as `/dev:feature`: the **spec's Problem/Scope section** — the spec is larger for `/dev:build`, but the WHY still comes from Problem/Scope, not from the task list.|
|`/dev:deliver`|`### /dev:deliver — <title>`|`M2: Route Sentry alerts into the queue`|The **design README's opening** — what this is, why, and what is different once it exists — plus, per node, what it holds and whether it needs reading. The tracker comment leads with that WHY, then what each milestone lets stakeholders try.|

WHY sourcing matters because reviewers and downstream agents read only the PR and tracker text — if the WHY isn't pulled from the approved artifact, that context is lost the moment the session ends.

## Completion options

Work is already committed and pushed. Present the user with exactly these options:

1. **Create PR** — if on a feature branch with no PR yet, offer to create the PR with summary
2. **Keep working** — if the user wants to iterate
3. **Discard** — if the user wants to throw away the work (confirm before acting)
