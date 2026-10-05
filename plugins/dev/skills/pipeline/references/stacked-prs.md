# Stacked PRs — deliver a task as a chain of small dependent PRs

A task may land as an **ordered chain of 2–5 small dependent PRs** instead of one oversized diff.
Each node stays readable on its own, the human reads them one at a time, and they land as **one
commit each** on the main line. This file decides whether and where to cut; every command — add a
node, propagate an edit upward, mark ready, land — is `git-workflow` → **stack** (`contracts.md`).
**A project whose `git-workflow` does not support stacks lands everything as one PR**, and the
final confirmation says so.

Consumed by: `pipeline`, after Phase 4 — reached from `/dev:feature`, `/dev:build`, `/dev:task` and `/dev:deliver`.

## The chain is cut after the work is done, not planned before it

There is one shape, and nothing about it is decided at plan time:

> implement the whole change on one branch → `prune` → the full verification protocol, **once** →
> cut the result into nodes → push them as a stack → report the shape.

**You cannot know where the seams are until the code exists.** So the split appears in no spec, no
plan and neither approval gate; the pipeline runs exactly as it does for a single PR until Phase 4
is green.

**A change with no good seam is one PR, and that stays the common case.** Do not manufacture a split.

`/dev:deliver` cuts at the end too, but along history rather than paths: a node is a group of
commits, so a file several nodes touch is no obstacle. The recipe — squash the fixups, reorder the
commits into nodes, then reset and fast-forward node by node — lives in the `deliver` skill
§ Landing. Everything from "One tracker issue" down applies to its chain unchanged; the path recipe
below does not.

## Where to cut — by how each node is read

He reads a chain node by node, and kinds of change are read differently. A mechanical change — a
rename, a move, a deletion, a regenerated file — he does not read at all: the compiler and the tests
vouch for it, and it is often most of the line count. A refactor is read for one question, whether
behaviour stayed the same. New functionality is read for what it does and whether it is right.
Mixed in one node, the mechanical lines bury the ones that need him, and he cannot tell which is
which. So the first seam separates those kinds; within the logic, cut again where a node would
otherwise hold two things to understand. Say in each node's title whether it needs reading.

Cut in the **dependency direction** — the frontend depends on the backend, not the reverse, and a
rename comes before the code written in its new words. That ordering is also what makes every
prefix of the chain compile, without anyone aiming for it.

Cap the chain at **5 nodes**; a bigger effort splits into separate runs. Two constraints:

- **Whatever `git-workflow` → stack pins to the bottom node stays there** — typically submodule
  pointers, which cannot travel in a patch at all (below). No such path goes into a layer you lift
  off.
- **The cut is made once.** Review posts threads against specific PRs, so re-cutting orphans them.
  Later fixes go into the nodes that exist.

## Verification runs once, on the whole change

The full protocol (`verify`) runs **before** the chain exists. There is nothing to verify per node,
and the most expensive step in this pipeline is not multiplied by N.

What covers the nodes afterwards is the project's CI on each PR, which therefore builds every prefix
of the chain. Its job is to stop code that does not build from merging — it is **not** a constraint
on how you may cut. Where the two disagree, i.e. a change that cannot be cut in dependency order,
leave it as one PR rather than bending the split around CI.

**Every node must be green on its own**, not just the top: each lands as its own commit on the main
line. A fix carried in a higher node does not rescue a red node below it — move it down.

## One tracker issue, no sub-issues

The whole chain hangs off **one tracker issue**. Do not create a sub-issue per node — it buys
nothing and doubles the bookkeeping. How the tracker links the chain's PRs, and what it does to the
issue as nodes leave draft or are abandoned, is in `git-workflow` → stack.

## Cutting the chain — the recipe, and its ordering trap

The branch you implemented on and the PR already open for it **become node 1**; the first
"add a node" is what turns that PR into the bottom of a stack. The carrier is a patch, so the cut
needs nothing beyond git and that one operation.

The carrier is a path-scoped patch, so **check the cut is expressible before you make it.** Two
shapes are not, and both fail silently — the cut succeeds and produces a wrong chain:

```bash
BASE=$(git merge-base <main line> HEAD)
comm -12 <(git diff --name-only "$BASE" HEAD -- <node 1 paths> | sort) \
         <(git diff --name-only "$BASE" HEAD -- <node 2 paths> | sort)   # must be empty
git diff --diff-filter=R --name-status "$BASE" HEAD                      # renames crossing a boundary
```

A file both layers touch cannot be split by path: assign it up and the bottom node loses its own
change to it, assign it down and the bottom node ships a line referring to code that arrives later.
A rename that crosses the boundary is worse — the upper patch becomes a bare `new file`, so the
bottom node deletes the original with nothing replacing it. **Either one means this is one PR**, or
a different seam. Nothing downstream catches the first; only CI catches the second.

Commit the whole verified change first (`post-pipeline.md` Step 1's commit), then, **from the repo
root** (the patches carry `-p1` paths):

```bash
BASE=$(git merge-base <main line> HEAD)

# 1. Carry every upper layer out as its own patch, by path.
git diff "$BASE" HEAD -- <node 2 paths> > /tmp/<task>-node2.patch
git diff "$BASE" HEAD -- <node 3 paths> > /tmp/<task>-node3.patch

# 2. Take them OUT of the bottom node FIRST — the same patches, reversed. This also deletes the
#    files a layer created, which `git checkout "$BASE" -- …` cannot do.
git apply -R /tmp/<task>-node3.patch /tmp/<task>-node2.patch

# 3. Stage EVERYTHING, then commit and push the bottom node (`git-workflow` → checkpoint).
#    `git add -A` — not `commit -am`: a file an upper layer deleted comes back UNTRACKED here,
#    and `-am` would ship a bottom node that still deletes it.

# 4. ONLY NOW fork upward, one node at a time, each re-applying its own layer:
#    `git-workflow` → stack "add a node", then `git apply /tmp/<task>-node2.patch`, commit, push;
#    the same again for node 3.
```

**The ordering in steps 2–4 is the whole trick, and reversing it fails silently** — measured, not
reasoned. Fork the upper node while its layer is still in the bottom one and it forks with a copy of
that layer, so it owns no commits and its PR diff is **empty from that moment**; the first upward
propagation then fast-forwards the removal into it and deletes the files from the branch too.
Exit 0, no conflict, nothing to see. **Remove first, fork second.**

A gitlink cannot travel in a patch at all: `git apply -R` on a submodule-only patch exits 0 and
changes nothing. That keeps submodule moves in the bottom node for free, and equally means one can
never be carried upward by this recipe.

Keep the patches outside the repo (`/tmp`), or they land in a commit as files of their own.

Each node forks from a complete, pushed parent. Once the whole chain is up, mark it ready for
review **once** (`post-pipeline.md` Step 1b), because a node left in draft reads as unfinished
work. The PR-changeset step of `post-pipeline.md` runs **per node**, since each has its own PR, and
the tracker comment is written **once for the whole chain**.

## Report the shape

There is no gate on the split: you cut at your own discretion and **report the result** — how many
nodes, what is in each and whether it needs reading, in bottom-up reading order, with each PR
number. He reads the outcome; he does not arbitrate the cut. If the cuts come out reading wrong that
is the signal to revisit the rule, and this report is the only channel that carries it.

Hand-off line: "chain of N PRs, one tracker issue, here is the bottom-up reading order — these M
decisions need you." Landing it is `git-workflow` → land, on his request.

## Downstack edits and conflicts

A lower branch gaining a commit does **not** update the nodes above it — the hosting platform only
cascades on merge. So after editing a lower node, commit and push it, then propagate it upward
(`git-workflow` → stack). Merge the main line into the **bottom** node only and carry it up from
there: a PR's diff is measured against the node below it, so merging the main line straight into an
upper node would make its commits read as that node's own work. Merge rather than rebase, so review
comments keep their anchors. Re-verify once at the tip afterwards — not per node.

A conflict surfaces on a specific node, and two rules follow:

- **Fix it on the node where it surfaced.** Carrying the fix to a node above buries the incoming
  changes inside someone else's layer. If the project has a conflict-resolution skill, use it.
- **Re-run the propagation after committing the resolution**, so the nodes above pick it up.

Keep chains **forward-only** — a lower node changing under reviewers who are already reading the
nodes above it costs everyone a re-read.

## Land the chain

Merging is irreversible and outward-facing: **the human asks for it**, and it goes through
`git-workflow` → land, which knows whether the platform lands a chain atomically and what to avoid
(merging a mid-stack PR by hand, for one, typically lands every node below it and strands the rest).
