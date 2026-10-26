---
name: review-and-fix
description: Run /dev:review and /dev:fix-pr-comments in rounds until review calls the branch finished — each run in a subagent, with you relaying only what the owner has to decide.
disable-model-invocation: true
---

# Review and fix

Without this he runs `/dev:review`, reads the threads, runs `/dev:fix-pr-comments` and starts over,
until a review brings nothing that matters. This skill runs that loop. What a round does belongs to
those two skills and is not restated here; this one carries the loop and the traffic between him and
the agents doing the work.

**Your context is what the loop runs on.** Findings, diffs and fixer reports would fill it within two
rounds, and the loop is only worth having if its fifth round sees as clearly as its first. So every
review and every fix runs in a subagent, and what reaches you is what he reads anyway: review's
closing lists with their links and its verdict, fix's line per thread, and questions. The rest lives
on the PR and in the review memory.

**The owner's language** is the one `/dev:review` defines. Everything you write to him is in it.

## A skill in a subagent

Both skills are user-invoked: in a subagent a `/dev:review` prompt arrives as plain text, and the
Skill tool answers `Unknown skill`. So the subagent reads the file and carries it out. Its brief, for
a `general-purpose` agent:

- **The skill.** The expanded path of `${CLAUDE_PLUGIN_ROOT}/skills/review/SKILL.md` or
  `${CLAUDE_PLUGIN_ROOT}/skills/fix-pr-comments/SKILL.md`, and the value of `${CLAUDE_PLUGIN_ROOT}`,
  which the raw file carries literally. The file is its task, to be carried out step by step — not
  reference material.
- **Its own agents in the foreground** — finders, verifier, fixers, parallel in one message — and its
  turn ends only with its report. An agent that ends its turn while its background agents still run
  never receives their results; they surface in your context instead, which is what this skill
  exists to prevent.
- **It cannot reach him.** Its only channel is its final report. Where the skill says to ask him, it
  finishes everything that does not depend on the answer, then returns the question whole: the
  problem, the options, what each costs.
- **What to return** — the round's step below says — and nothing more.

Relay a question to him as it came. Send his answer to the same agent with `SendMessage`: it resumes
with its context intact, and you wait for its next report as before.

## A round

1. **Review.** A subagent carries out `review/SKILL.md` whole. It returns step 5's three lists with
   their links, whatever it could only say in chat, and its verdict on whether review is finished.
2. **His triage.** Show him what was posted — each claim with its link — and what came only to chat,
   then wait. He resolves on GitHub what he rejects, or talks it through with you; what he settles
   here goes into the fix brief as direction, as he would have written it after
   `/dev:fix-pr-comments`. A `🤔 RECOMMENDATION` is the exception to silence: it is fixed only on his
   explicit yes, and a yes given here counts as his reply on its thread. A no given here closes it:
   the fix run answers and resolves it. Unanswered, it stays open. When review brought him nothing, there is nothing to triage or fix: go to 4.
3. **Fix.** A subagent carries out steps 1 to 7 of `fix-pr-comments/SKILL.md`; step 8 belongs to the
   end of the loop. It returns the lines step 8 would print — per thread, what changed or why nothing
   did, with the commit.
4. **Again, or done.** Review's verdict decides — finished when two consecutive runs brought him
   nothing blocking. Otherwise start the next round. He can stop the loop whenever he likes.

## The end

One subagent carries out step 8 of `fix-pr-comments/SKILL.md` once, over everything the loop changed:
`verify` at the level that change calls for, and on each PR one `## 🤖 Fix summary` holding every
round's lines, which you hand it, with the verification result. A full verify per round would repeat
the hour of e2e that a single run at the end covers.

Then tell him, per round, its `review run <n>` line; what is still open; and the verification result.
