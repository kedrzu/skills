---
name: rightsize
description: >-
    Reports where a solution is bigger than its problem. For every new mechanism a design, plan or
    change brings, it asks what requirement the mechanism buys, where that requirement came from,
    and whether a pattern borrowed from elsewhere still has its reason here, and it names the
    simpler version and what that version gives up. Invoked by /dev:design before a design closes,
    by the pipeline's plan phase, by /dev:review and by a fix about to add a mechanism. Use it
    directly when asked "is this over-engineered", "czy to nie jest przekombinowane", "find
    over-engineering in this PR" or "what here is more than we need". Not for code with no caller
    (prune) or for bugs (a review).
---

# Rightsize

A solution can work, have a caller for every piece, and still be much bigger than its problem.
`prune` cannot see that, because an over-built mechanism has a caller at every layer, and the agent
that designed it honestly believes each part is needed. This skill only reports. Whoever invoked it
weighs each item against what has already been settled and decides what reaches the user. So report
every candidate. Deciding that something is justified is not your job here, and a mechanism you
leave out is one nobody will look at again.

## What to look at

A new mechanism is something the system did not have before and other code now relies on. Examples:
a component, layer or service; an infrastructure resource; a kind of persisted record; an existing
mechanism generalised for a second use. Using an established pattern as it is, for the same kind of
problem, is not one.

For each new mechanism:

1. **What does it buy?** Name the concrete case where the simpler thing breaks. A property such as
   "scalability", "auditability" or "future-proofing" is not a case.
2. **Where did that requirement come from?** The user, a named law, a measured number, another
   system's contract, or the agent's own inference. Something the agent proposed and the user only
   accepted counts as the agent's. Report the source as you found it; it does not excuse the mechanism.
3. **If it is borrowed or generalised from something already in the repository:** what justified it
   there, and does that reason hold for the new use? A second user is what a generalisation creates,
   not a reason for it.

Premises lean on each other. Most of an over-built system traces back to two or three of them, and
the rest is built to serve them, so when one falls, follow what stood on it.

## What you return

One entry per mechanism that has a simpler version:

- **the mechanism**, in one sentence;
- **the premise** it rests on, and where that premise came from;
- **the simpler version**, concrete enough to build;
- **what the simpler version gives up**: every requirement it would drop, including the user's own.

List only these entries.

## How to run it

Run three fresh subagents and merge what they return; tell each that it is one of the three, so it
answers the questions itself. Give each one the whole subject, this file and
`${CLAUDE_PLUGIN_ROOT}/skills/rightsize/references/cases.md`, both by expanded path (a subagent
cannot resolve the variable). The cases are five mechanisms from one real feature and what each
turned into once someone asked. One pass over a large change sees part of it, and a different part
each time.
