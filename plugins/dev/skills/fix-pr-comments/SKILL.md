---
name: fix-pr-comments
description: Act on the unresolved review threads on this task's PRs, stacked chains and submodules included: fix what is clear, ask in chat about what needs a choice, verify, reply and resolve.
disable-model-invocation: true
---

# Fix PR comments

An unresolved thread is the owner's consent: he has read it and left it standing, so it gets fixed.
A resolved thread is his "no" — it is done, and it does not come back. That is the whole triage, and
it is why this skill has no plan gate and no critic: judging the findings already happened, once,
where he was already reading. It acts.

The shape is fixed: the same steps in the same order every run. There is no re-triage loop — if he
wants another pass, he runs `/dev:review` again, or `/dev:review-and-fix` to loop both until review
calls the branch finished.

What a thread state means, and who wrote a comment, are defined in
`${CLAUDE_PLUGIN_ROOT}/skills/review/references/comment.md`. Read it before step 2; it is the
contract this skill consumes and it is not restated here.

**Prerequisites.** The project is on GitHub and `gh` is installed and authenticated: the scripts
read and answer the threads through the GitHub API. Verifying, committing, pushing and moving along
a chain go through the project's `verify` and `git-workflow` skills — what each must provide, and
that a missing one stops the run, is `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/contracts.md`.

**His language** is the owner's language as `/dev:review` defines it: the language named for
human-facing text in his personal `CLAUDE.local.md` at the project root, else in the project's
`CLAUDE.md` — or, without such a rule, the language he writes to you in. Name it in every brief whose output he
reads.

## 1. Fetch the threads

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/fix-pr-comments/scripts/fetch_comments.py
```

Unresolved threads for every node of this task's chain, bottom first, and separately for each
submodule's PR — the script finds the submodules itself. Per thread: `threadId`, `path` and
`line` — **the anchor is the location for his own comments**, where "rename this" means nothing
without it — `pathPrefix` (`""` for the main repo, `<submodule path>/` for a submodule's PR, whose
thread `path` is relative to that submodule's root), `diffHunk` on the first comment, full bodies
including our `<details>` blocks, and `askOrigin` plus `askCommentIndex` pointing at the **operative comment**:
the latest one he wrote, or the first when he wrote none. Everything before it is background.
Comments from anyone without write access to the repository never reach you — the script drops them,
and a thread left with none of his or ours is not returned.

No PR for the branch: the script says so and there is nothing to act on. Say it and stop. It also
exits non-zero rather than returning a partial chain — a branch that is not one of the stack's open
nodes, a closed node between two open ones, an API it could not read. Report what it said; acting on
a chain missing a node means skipping every thread on it, invisibly.

Every thread it returns is unresolved **on GitHub**, which is the only authority on that. A comment
saying "done" or "fixed" is not resolution — someone may have changed the code and never resolved
the thread; the fixer will find that out and answer accordingly. **Nothing of his is dropped here**,
whatever kind of comment it is: unresolved and unanswered is consent, uniformly. The one thing the
fetch skips is a lone `## 🤖` answer of ours with nothing under it, which older runs posted as a
comment of its own: our output, not his input — unless he replies under it, which makes his reply
the ask.

## 2. Group them

Group by what the threads ask for — one group is one coherent change, one agent, one commit. The
same rename across four files is one group; a naming nit and a logic bug in one file are two asks
but **not** two groups, because of the one hard rule:

**Threads on the same file always share a group.** Two agents editing one file overwrite each
other's work, and no amount of grouping cleverness elsewhere is worth that. On a chain a second one
binds: **a group never spans nodes**, because its edit has to be committed on one branch.

Nothing else constrains grouping — no package waves, no thread cap. Parallel agents in different
files is the cheap case; the single verification in step 4 is what catches anything they did to each
other.

## 3. Fixers, in parallel

One agent per group, all launched in a single Agent tool call.

**On a chain, one node at a time, bottom-up** — `git-workflow` → **stack** checks node `k` out, and
its groups are fixed, pruned and committed before you move up. Fixers stay parallel *within* a node.
Fixing a lower node cascades upward anyway, so git imposes the order rather than the process.

Give each one its threads with the full comment bodies, plus each thread's `path`, `line` and
`diffHunk`, and the expanded path of `${CLAUDE_PLUGIN_ROOT}/skills/review/references/comment.md`
(a subagent cannot resolve `${CLAUDE_PLUGIN_ROOT}`). The `<details>` block carries the citations for
an agent's finding, but for his own comment **the anchor is the location**, and "rename this" is
unactionable without it. Then the brief:

- **What the ask is depends on who made it.** An agent's finding is a claim: check it still holds
  against the code as it stands before changing anything, because it was written earlier and the
  code may have moved. If it no longer holds, do not fix it — say so, and that is the answer the
  thread gets. His own comment naming a change is the ask itself; carry it out. His comment asking
  whether something holds wants an answer, not an edit. And a thread where he replied to talk a
  finding down is **settled** — not consent and not a claim to re-litigate: answer it, change
  nothing. `askCommentIndex` points at whichever of these is operative. When an agent's finding
  holds, search for every instance of the mechanism it names before editing, not only the places it
  lists, and fix each, and the cause when that sits somewhere other than the line the comment is on
  — say so in your report. Outside this change apply only a removal of a duplicate of something that
  already has a helper, and that across the whole repo.
- **Edit, and nothing else.** No test suite, no commit, no push, no `git add`. Running the single
  test you wrote is fine; anything wider is the orchestrator's job and would collide with the other
  fixers.
- **Other agents are editing other parts of this repo while you work.** A failure in code you did
  not touch is theirs, not yours: note it in your report, finish your own work, and do not
  investigate. The authoritative check runs after everyone is done. This prior matters — without it
  an agent hunts a bug that belongs to someone else and burns the run doing it.
- **Stop only if the comment is genuinely unclear, if it implies he has misread the code, or if the
  fix needs a choice between workable ways that the comment does not make, or reaches code outside
  this change for more than that removal** — whether it becomes a separate task is his call. His
  preference is authoritative; his claim about the code is a claim like any other and you may
  contradict it with evidence. If you do stop, first revert your own edits — `git checkout` over the
  files you touched — and come back with the question and a clean tree. A half-applied change in a
  shared tree costs more than redoing the work, and his answer may invalidate it anyway.
- **Report per thread** what you did and how, or why you did not — it becomes the reply on that
  thread and his line in chat — plus the full list of files you changed, which is what the commit
  stages.

## 4. One verification over all the fixes

Run the project's `verify` skill → **scoped**. Once, after every fixer is done — not per fix. The
affected sets overlap, so verifying them together costs a fraction of verifying them one at a time,
and by now nothing is being edited concurrently, so a failure is attributable.

**On a chain this step waits for the whole chain.** Fix, prune and commit each node bottom-up,
propagate them upward (step 6), check out the chain's tip (`git-workflow` → **stack**), then one
scoped `verify` there: it stands in for the runs on the nodes below, whose own prefixes their PRs'
checks already cover. A red there is yours to diagnose from the tip and to fix on the node that owns
the code.

Fix what is red yourself. You are the only party that can see every change at once, which is exactly
what diagnosing a collision needs.

## 5. Prune

Run the `dev:prune` skill — the pipeline's phase 3 — over the fixes, before anything is published.
Hand it **the files the fixers changed** (step 3 collected them) and tell it **this is a fix run**;
it scopes itself to what you name, and its behaviour on tests depends on being told. Submodule fixes
count: name those files too, or the submodule's fixes are never pruned. It removes what the fixes
duplicated and inlines what they over-built, and he should read the reduced diff rather than the raw
one. Then scoped `verify` again: it was green before this step, so
anything red after it belongs to this step.

A red on the scoped check after it is **yours to fix**, the same as in step 4 — and since `prune`
may not add anything, the remedy is usually to put its deletion back.

Two things this phase does differently here: it leaves **tests alone** (after a fix run, every
test that exists was written in answer to a thread he left standing — that is consent, not clutter),
and it has to hand back **the list of what it removed, with the file and what each deletion was**,
because step 6's replies report it. Ask for that list in the invocation; without it step 6 cannot
tell him the truth about the code that is now on the PR.

## 6. Commit, push, answer, resolve

One commit per group, staged selectively so the groups stay separate. **Stage `prune`'s files
too** — it repoints call sites, which need not sit in any fixer's list, and a file it touched but
nobody staged is left dirty in the tree after the push, so step 8 then verifies something that is
not what the PR holds. Add its list to the group whose fix it shrank; anything it touched outside
every group goes on the last commit.

Commit through `git-workflow` → **checkpoint**: each group's files on their own, nothing else
staged, then push what is committed.

**Fixes inside a submodule go first.** Commit and push them in the submodule — in its own commit
convention, on the branch its PR is already open on, as the project's checkpoint operation says —
before committing in the main repo, which then carries only the moved pointer.

If the push fails, fix the push before anything else — an answer claiming a fix nobody can see is
worse than none.

**On a chain:** a new commit on a lower node does not update the nodes above it — GitHub only
cascades on merge — so once every node is committed and pushed, propagate them upward once, through
`git-workflow` → **stack**. It has to do that without force-pushing, so the review comments on the
upper nodes keep their anchors. Skipping it leaves those nodes reviewing — and later squashing
against — a base they never saw.

Then, once every push has succeeded — every node, every submodule — and no question to him is still
open, answer all the threads in one call:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/fix-pr-comments/scripts/reply_and_resolve.py --answers <answers.json>
```

`answers.json` is a list with one entry per thread: `{"repo", "pr", "threadId", "header",
"message"}`, where `pr` is the PR carrying the thread. Everything it posts goes out as **one GitHub
review per PR** — a comment posted on its own is a review of its own, and the run would reach him, on
his phone too, as a wall of separate entries. That is why the call waits for the last push and the last
answer: a review is submitted once, and nothing can join it afterwards.

Per thread, the script replies on the thread and, once the review is submitted, resolves it. Nothing
is left on GitHub for him to sign off — he signs off in chat, where step 8 lists every fix. Re-running
is safe after any failure: a thread that already carries our reply is not replied to twice. If it
stops because he has a draft review of his own open on that PR, ask him to submit or discard it.
Publishing ours would publish his.

`header` is `Fixed` when the code changed and `Acknowledged` when it did not — a finding that no
longer held, a request the code already satisfied, an answer to a question he asked. Say which in
the message; an answer claiming a fix that did not happen is worse than none. Write it in his
language: he is the one who reads it.

If `prune` removed part of what a fixer added, the answer says so. If it removed something the
thread actually needed, restore that first — the answer has to be true of the code now on the PR.

A thread whose fixer stopped with a question stays out of the file and stays open. **Put that question to
him when it arrives, not at the end of the run, and keep fixing** — it is a fork, and
batching forks into a closing report is exactly what makes him discover decisions after the fact.
Ask in an ordinary message, never in a dialog that holds the run until he answers: the groups
already fixed are verified, pruned, committed and pushed meanwhile, their answers waiting for that
one call, and his reply reaches you like any other event.
One or two sentences: what the comment asks, what the code actually says, and what you need from
him. His answer starts one more fixer for that thread's group once nothing from steps 3 to 6 is in
flight — they need a tree nobody else is editing — and on a chain with that group's node checked
out; it then goes through steps 4 to 6 like the rest, the upward propagation included. **The run
does not go on to step 8 while any question is open:** final verification and the closing list
cover every thread, so they wait until the last answer's fix has been through step 6 and every thread is answered. When
everything else is done and a question is still unanswered, ask it again in full — the problem, the
options and what each costs — never as a pointer to the earlier message: the last message is the one
he answers from.

Threads on the submodule's PR go in the same file, with that PR's own `repo` and `pr` from step 1;
their messages, the submodule's commits and its step 8 lines cite only what `comment.md` →
**Posting** allows. The script resolves threads by GraphQL node id, so nothing else changes.

## 7. `RULE:` — fold it into the skill that should have caught it

A comment of his starting with `RULE:` means *fix it here **and** fold it*, not instead of fixing.
It is his signal that this instance is a general rule, and he only knows that at the moment he
writes it — which is why it is caught here rather than reconstructed later.

Folding is a diagnosis, not an append. Most of these come from a rule we already have being the
wrong shape, not from a rule being missing, and a skill that only grows dilutes every rule already
in it. So work it out before proposing anything:

1. **Which existing rule should have caught this?** There usually is one. Finding it is discovery
   work — read the skills governing the code the comment sits on. Trust the routing; a skill nobody
   reaches has a defective description, and that is fixed in the skill, not worked around here.
2. **Why did it not fire?** Wrong shape (too narrow, or so general it decides nothing), misunderstood
   (it reads differently from what it means), or not on the critical path of the work it governs —
   the third needs a catcher downstream, because no wording saves a rule nobody has to read to get
   the job done.
3. **Propose**, in this order of preference:
   - **add an example** under the existing rule — one line, and the default;
   - **reshape** that rule — edited in place, no growth;
   - **a new general rule** — last resort, said out loud as such, carrying a direction plus at least
     one example. Never a bare prohibition.
4. **Ask him**, in his language, with the options and what each costs where there is a real choice.
   This is a fork, not a correction, so it is his call — and the volume is low enough that asking is
   cheap.
5. **Apply it** with a subagent running the project's skill-authoring skill (`skill-creator`, if
   installed), and commit it in this PR so the rule and the instance that motivated it can be read
   side by side.

## 8. Final verification

Run the project's `verify` skill once, at the end, at the level its change classification gives for
everything this run changed — **full** when the fixes reach code only the full protocol checks,
less when they don't. A one-thread copy fix does not need an hour of e2e.

Then, in his language, one line per thread: what changed and how, or why nothing did, with the
commit. This is where he signs off — on GitHub there is only a reply under a resolved thread. On
each PR whose threads this run answered, post that PR's lines only, headed `## 🤖 Fix summary` with
the verification result under it, as a top-level comment (`gh pr comment <n> --repo <owner/repo>
--body-file <summary.md>`). It stays out of Files changed and sits next to the review's summary:
what he skims later to see what a round of fixes did without opening the code.
