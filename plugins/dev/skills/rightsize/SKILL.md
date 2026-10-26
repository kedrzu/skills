---
name: rightsize
description: >-
    Checks whether a solution is bigger than its problem. For every new mechanism a design, plan or
    change brings, it asks what requirement the mechanism buys, where that requirement came from, and
    whether a pattern borrowed from elsewhere still has its reason here, and it puts the simpler
    version beside the proposed one for the user to choose. Invoked by /dev:design when a design
    closes, by the pipeline's plan phase when a plan brings a new mechanism, by /dev:review's
    over-building axis, and by a fix about to add a mechanism. Use it directly when asked "is this
    over-engineered", "czy to nie jest przekombinowane", "find over-engineering in this PR" or
    "what here is more than we need". Do NOT use to remove code with no caller (prune) or to hunt
    bugs (a review).
---

# Rightsize

A solution can work, have a caller for every piece, and still be much bigger than its problem.
Nothing else in the pipeline sees that. `prune` removes what has no caller, and an over-built
mechanism has a caller at every layer. Review finds defects, and over-building is not one until
it produces them. Warnings in the writing skills ("prefer the simpler solution", "YAGNI") were
there and let it through, because the agent that just designed four layers honestly believes each
is needed. So this is a question someone answers about each new mechanism, with the answer
written down.

## What counts as a new mechanism

Something the system did not have before and other code now relies on. A new component, layer or
service; a new infrastructure resource; a new kind of persisted record; an existing mechanism
generalised for a second use — a helper lifted out of one place so two can share it. Those are
examples, not a list.

Reusing an established pattern as it is, for the same kind of problem, is not one. A change with
no new mechanism has nothing for this skill: say so in one line and stop.

## The questions, per new mechanism

1. **What requirement does it buy?** Name the concrete case where the simpler thing breaks. A
   property — "scalability", "flexibility", "auditability", "future-proofing" — is not a case. If
   no case can be named, recommend the simpler thing.
2. **Where did that requirement come from?** The user; a law or regulation, named; a measured
   number, with where it was measured; another system's contract; or the agent's own inference.
   Report it, and never use it as a pass. A requirement the user stated is questioned like any
   other: an over-built idea of theirs is just as easy for an agent to fixate on, and nobody
   questions it later because the user said it.
3. **If it is borrowed from elsewhere in the repository** — what justified it there (volume,
   retention, an external contract, a failure that happened), and does that hold here?

Premises lean on each other. When one falls, look at what else stood on it: in practice most of an
over-built system traces back to two or three premises, and the rest is built to serve them.

Complexity is a cost in its own right — more parts, more ways to fail, more code that every later
change has to read and keep consistent. "It works and it is tested" does not answer it.

## What you return

For each new mechanism that has a real simpler alternative:

- **the mechanism**, in one sentence;
- **the premise** it rests on, and where that premise came from;
- **the simpler version**, concrete enough to build;
- **what the simpler version gives up** — every requirement it would drop, the user's own included;
- **your recommendation.**

Nothing for a mechanism whose premise holds and has no simpler version — do not pad the list to
look thorough. A simpler version that drops a stated requirement is still offered, with that
requirement named as what it gives up: the user decides whether the requirement is worth its cost.

Before raising anything, read where the work keeps its settled facts — the design's
`DECISIONS.md`, the plan's Claims, the review memory. A mechanism the user already decided to keep
is not raised again unless the premise it was kept on has changed.

## Who calls it, and what happens with the answer

|Caller|What happens|
|-|-|
|`/dev:design`, before it proposes closing|A gate. Each alternative goes to the user as the two versions; the design does not close until they pick. The pick becomes a decision and the other version its Rejected line.|
|The plan phase, when a plan brings a new mechanism|A gate before the plan reaches approval: the two versions, as the mechanism appears in planning, not batched into the finished plan. A kept mechanism goes into the plan's Claims, with the user's confirmation and its date.|
|`/dev:review`'s over-building axis|The return shape above becomes a `🤔 RECOMMENDATION` finding, which review publishes and never fixes on its own.|
|A fix about to add a new mechanism|Before building it: ask in chat — the finding needs this new mechanism, or a change to an existing one? Both versions, the user picks.|
|The user, by hand, on a PR, a branch or a design|Report in chat, in the user's language. Change nothing.|

Neither version is the default at a gate. The user wants to see both and choose, not to learn
afterwards which one was picked.

When run by hand on a change too large to hold at once, split it by area and give each area to a
fresh subagent with these questions, then merge what they return. A single pass over a large change
sees part of it, and a different part each time.

## Cases

`${CLAUDE_PLUGIN_ROOT}/skills/rightsize/references/cases.md` — five mechanisms from one real feature that passed design, plan,
implementation and three rounds of review before this question was asked, and what each turned
into once it was. Read it the first time you run in a session; the patterns repeat.
