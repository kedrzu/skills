---
name: deliver
description: >-
    Build a closed design from `docs/design/<slug>/` in one run on one tracker issue: agree a
    high-level overview of the work, implement it milestone by milestone — each milestone
    something the user can see and try, not read — stop to bring back every gap, divergence or
    better idea the design did not settle, and land the whole thing as a stacked chain of PRs cut
    at the end. Use whenever the user wants a design folder built — "zaimplementuj design X",
    "wdróż X z designu", "build docs/design/<slug>", "zrób to, co mamy w designie", a handoff
    from /design-doc:design-doc — even if they do not name this skill. Do NOT use to write or change a design
    (/design-doc:design-doc), for large work with no design folder (/dev:build designs it itself), to turn a design
    into tracker issues, or to fan many tasks out across worktrees.
---

# Deliver

The pipeline entry point for building a design that already exists. Everything that is not
stated here — implementer dispatch, scoped verification, `prune`, the plan completion audit, the full
verify, finalization — runs as written in `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/SKILL.md`.

**Announce:** "Using /dev:deliver to build this design."

## The handoff

A design folder is what the design side knew when it handed the work over: the goal, the model, the
decisions and what was rejected. You are the development team that picks it up. The goal is a great
feature, not one that matches the document — and building always turns up what nobody could see from
the design: a question it did not settle, a place where the code or a service contradicts it, a
better way that only shows once the code exists.

So you come back with every one of those. Never diverge silently, and never knowingly build something
you believe is wrong because it is written down. The opposite holds too: `DECISIONS.md` records what
was rejected and why, so reopening a settled decision needs new information — its premise changed, or
the code proved it wrong. Code is evidence of what exists; the design is the intent; neither is law.

## What a milestone is

Large work goes wrong here in two opposite ways. One pass over the whole thing produces weak code,
nothing to check until the end, and a diff nobody can review. Splitting it into many small tracker
issues splits it by what is convenient to implement rather than by what makes sense to follow, and
every task then has to be read and its agent watched.

A milestone sits between them: **a point where he can see and try something.** He does not read code
during the run — unless you ask him to look at one specific solution — so a milestone is defined by
its surface, never by a layer: a screen or a prototype on dev, an endpoint answering a request, a test
Sentry alert arriving in the queue on a dev environment, a deploy visible in its logs, a CLI command doing its job.
What he checks is direction, usability, whether it works the way he meant, whether he likes it.

## Reading the design

`README.md` for the goal and the model, `DECISIONS.md` for what holds and what was already tried, then
the chapters the work touches, then the tail of `JOURNAL.md`. The folder carries evidence as
`Checked <date>:` notes next to the claims — use them rather than paying for the same research twice;
re-check only what a decision now rests on and is old enough to have moved. What sits under "Still
open" and blocks the first milestones is the first thing to talk about.

## Start: an overview, agreed in conversation

No spec, no ambiguity finder, no Design It Twice over what the design settled — each of those re-makes
a closed decision. Planning is a conversation (pipeline, "Planning is a conversation"): a fork goes
to him when it arises, so the overview he finally approves holds no news.

The overview is your breakdown of the whole run into steps, at the level of an outline: ordered, a
line or two each — what changes and why it comes at that point — with the milestones marked, saying
what he will see and how he will check it. No file lists and no "what changes when and how": at this
size that is unreadable, and it is your working detail, not his. When checking a milestone needs
something outside the repo — a real deploy, a vendor account, a sandbox — say so here, not at the
checkpoint.

```text
1. Public endpoint and queue — first, because everything after it waits on messages.
2. Sentry and Linear routes, each with its signature check.
   → You'll see: a test Sentry alert lands in the queue on dev. I'll give you the command that
     sends one and reads the queue back.
3. Our Linear app user and the router skeleton — a message moves its issue to In Progress.
4. Triage — collapsing duplicates, reading open and recently closed issues.
   → You'll see: forty alerts from one bad deploy become a handful of issues in Maintenance.
     Depends on whether Linear fires the hand-over webhook when our own app is the one handing
     over — I test that first and come back with the result.
```

Save it to `.context/plans/<YYYY-MM-DD>-<slug>.md`, in his language, and run the approval gate
(`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/approval-gate.md`). The overview stays alive: rearranging the
remaining steps after a checkpoint is normal, and one sentence tells him you did.

Once approved, the delivery half of the design's "What gets built first" section has been consumed —
delete it. Keep what states a dependency between parts of the system (*the timer pass has nothing to
do until the intake exists*): that is design content, permanent, and moves into the chapter that owns
it. The judgement about what is worth building first is delivery content, and the overview you just
agreed replaces it. That is the first commit of the first milestone. The folder never gains a record
of progress.

## Each milestone

1. **Plan its tasks** just before it starts: the pipeline Plan Format (Claims, Must protect, Mode)
   in `.context/plans/`. This is your working document — it is not presented and has no gate; a fork
   found while writing it goes to him as a question.
2. **Build it** — pipeline Phase 3, then the Phase 3.5 audit over this milestone's tasks. A task
   the audit classifies CHANGED is a divergence candidate: if it never reached him, it does now.
3. **Try the surface yourself** before handing it over — the project's manual-testing skill, if it has one, for anything in a
   browser, running the path for a backend or infrastructure change. The full verify runs once, at the
   end, so this is what keeps him from spending his time on something you could have caught.
4. **Commit and push**, then the checkpoint.

## When you stop

Three kinds of stop. The first two use the shape in
`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/escalation-protocol.md` — problem and evidence, impact,
options, recommendation. Between stops, in-boundary work stays autonomous exactly as the pipeline's
Execution Autonomy table says; the milestone plan is the boundary.

- **A question the design did not settle.**
- **A divergence or a better idea.** Once he decides, write it back into the design in this run: a
  new `DECISIONS.md` entry that supersedes the old one (and says so under the old one), plus the edit
  to the chapter or README prose that described it. Only what a stop settled — never an audit of the
  diff against the design.
- **The milestone checkpoint.** It has to stand alone; assume he has not looked at the terminal for an
  hour. How to see and try it, and what to pay attention to; what you decided on your own that he
  would want to know; the divergences settled since the last one; a specific piece of code worth his
  eyes and why, only if there is one; what comes next. Then yield.

While he has not answered a checkpoint, explore and plan the next milestone, but write no code — his
answer may change the direction. It may rearrange the remaining milestones; finished ones are redone
only if he asks.

## Git during the run

One branch — the one `git-workflow` → **start** opened. Every commit carries its milestone's
marker, `M2: <what changed>` after whatever prefix `git-workflow` → **checkpoint** asks for, which is
how you find where the run stands.

**A mechanical change gets a commit of its own** — a rename, a move, a deletion, a regenerated file —
never mixed with logic. The chain is cut along commits at the end, and what one commit mixes cannot
be separated there.

**Earlier milestones are never frozen.** Nothing is read as code until the final chain exists, so
nothing below the current milestone is settled. When milestone 4 shows milestone 1 got something
wrong, fix it where it belongs and commit the fix as `git commit --fixup=<a commit of M1>`: the squash
at the end moves it into the commit it fixes, and the chain reads only the final version. Bending new
code around an old mistake to avoid touching it is the failure this exists to prevent.

Merging the main line in mid-run is fine; the squash at the end linearises the merges it makes.
Whatever `git-workflow` → **stack** pins to the bottom node — a submodule pointer, typically — is
published as **checkpoint** says, and its move is a fixup to a commit that will sit in the bottom
node.

## Landing

1. **Full verify** — the project's `verify` skill, on the tip.

2. **Squash the fixups.** Checked 2026-09-24 in a scratch repo (`main` stands for the project's main line):

   ```bash
   git fetch origin main
   PRE=$(git rev-parse HEAD)
   GIT_SEQUENCE_EDITOR=: git rebase -i --autosquash "$(git merge-base origin/main HEAD)"
   git diff --stat "$PRE" HEAD   # must print nothing
   ```

   It runs without interaction, and merges from `main` drop out as the history is replayed onto the
   base. A fixup that touches lines a later milestone also changed conflicts **twice** — at its target
   and again at that later milestone; resolve each to what that milestone should contain
   (the project's conflict-resolution skill, if it has one). The empty diff is the proof: the tip is byte-identical to the verified one,
   so the verify still holds. Anything printed means a resolution went wrong — fix it before cutting.

3. **Cut the chain** into at most 5 nodes, by how each is read — mechanical apart from refactor
   apart from new logic (`stacked-prs.md`, "Where to cut"). Not by milestone: a milestone is what he
   tried during the run and says nothing about how its code reads. Put the commits in node order
   first; moving one past another that touches the same lines conflicts, so resolve each to what that
   commit should contain, and the empty diff again proves the tip is the verified one:

   ```bash
   PRE=$(git rev-parse HEAD)
   GIT_SEQUENCE_EDITOR='<script writing the todo: every commit, grouped by node>' \
     git rebase -i "$(git merge-base origin/main HEAD)"
   git diff --stat "$PRE" HEAD                       # must print nothing
   ```

   The bottom node is the branch you already have; each node above forks from the pushed tip of the
   one below (`git-workflow` → **stack** adds each node):

   ```bash
   git branch <task>-full HEAD                       # the whole run, kept
   git reset --hard <last commit of node 1>
   git push --force-with-lease
   # git-workflow → stack: add a node titled "<node 2 title>"
   git merge --ff-only <last commit of node 2, from <task>-full>
   # git-workflow → checkpoint: push
   # …the top node fast-forwards to <task>-full itself; delete that branch once the chain is up
   ```

   The rewritten bottom node goes out through `git push --force-with-lease` — the one force-push in this pipeline, and never through a project push command that does not force. It is safe only because the branch is
   this run's own and nobody else commits to it, and the lease refuses if the remote holds anything
   you have not seen. The nodes above fast-forward, so they push normally. CI builds
   every node; nothing is verified per node (`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/stacked-prs.md`).

4. **Finalize** per `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/post-pipeline.md` — ready for review once,
   a changeset per node, one tracker comment for the whole chain — and report the shape as
   `stacked-prs.md` describes, bottom-up, with PR numbers.

## Coming back after a break

A run spans days and sessions. Recover state from what is on disk, not from memory: the overview and
the current milestone's plan in `.context/plans/`, `git log --oneline` (the markers show which
milestone is where), the design folder (what was written back), and the chain as `git-workflow` shows it.

## References

|File|Read when|
|-|-|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/SKILL.md`|Always — Phase 3, Phase 3.5, Execution Autonomy, the Plan Format|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/approval-gate.md`|Presenting the overview|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/escalation-protocol.md`|Any stop other than a checkpoint|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/stacked-prs.md`|Cutting and landing the chain; editing a node after the cut|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/post-pipeline.md`|Finalizing|
