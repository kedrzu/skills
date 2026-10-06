# Project contracts — what the pipeline expects the project to provide

The pipeline decides *what* to do: which phase runs, what a test must protect, what goes into a PR
description, where a chain of PRs is cut. Two things it cannot know, because they differ in every
repository: how this project proves a change works, and how a change travels from a branch to the
main line. Each project answers those in two skills with fixed names, in its own `.claude/skills/`.
Besides the pipeline's entry points, `/dev:review` and `/dev:fix-pr-comments` consume them too.

|Skill|Answers|
|-|-|
|`verify`|How a change is proven to work here — the scoped check and the full protocol|
|`git-workflow`|How a change moves here — branch, commit, push, review, stack, land, tracker|

**A missing contract stops the run.** At the first moment a run needs one, check that the
skill exists in the skill list. If it does not, or it lacks the operation you need and does not
say the operation is unsupported, stop and tell the user which skill or operation is missing and
that `/dev:setup` writes it. Do not improvise a substitute: a guessed test command or a guessed push
is exactly the project knowledge the contract exists to hold, and a wrong guess fails silently.

## `verify`

Two modes. A project whose whole check is cheap may say both are the same thing.

- **Scoped** — fast, covers what the current change touched. Run after each implementation task and
  again after `prune`. Green here is not a green codebase; it exists so errors are fixed where they
  were introduced instead of being misattributed later.
- **Full** — the authoritative protocol the run must pass before it may finish. It runs once, in
  Phase 4. The skill owns the step list; the pipeline never second-guesses or shortens it.

## `git-workflow`

One skill, one section per operation. A section may say the project does not support the
operation — then the pipeline skips what depends on it (no stack is cut where `stack` is
unsupported) and says so in its final confirmation.

- **start** — put the work on a branch for its task and, if the project does so, open a draft PR
  and link the tracker issue. `/dev:deliver` runs it when it begins; the other entry points expect
  the user to have started, and use the branch they are on.
- **checkpoint** — commit with a real message in the project's convention (prefix, language,
  format) and push; includes anything that must be published separately first (submodules, other
  repositories) and how to confirm the push landed. Besides committing everything, it says how to:
  - **commit only a given set of files** — selective staging, nothing else staged, so several
    groups land as one commit each (`/dev:fix-pr-comments`);
  - **push what is already committed** without making a new commit (`/dev:review`).
- **publish** — the "coding is done, please review" signal: take the PR out of draft, write the PR
  description, post the comment on the tracker issue, and how the tracker issue is identified. The
  pipeline supplies the text (`post-pipeline.md`); this section says where it goes and how.
- **stack** — turning one change into an ordered chain of dependent PRs: how to add a node on top
  of the current one, how to propagate an edit to a lower node upward without force-pushing (review
  comments on the upper nodes keep their anchors), how to check out the chain's tip and how to check
  out a given node `k`, which paths must stay in the bottom node, and how the chain is landed. The
  pipeline decides *whether* and *where* to cut (`stacked-prs.md`); this section is the commands.
- **land** — how a finished change is merged. Irreversible and outward-facing: the pipeline never
  runs it on its own. It mentions it in the hand-off so the user knows what lands the work.
