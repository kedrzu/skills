---
name: prune
description: >-
    Phase 3 of the dev pipeline — a subtractive self-review of the change just made. Removes the
    helper that duplicates an existing one, the single-caller indirection, the abstraction with no
    producer, the code the change orphaned, and — after implementation only — the test that carries
    no signal. It may delete code and repoint call sites at code that already exists; it never adds.
    Runs after implementation and again after a fix run, between the scoped check and the full
    verify. Invoked by the pipeline and by whatever applies review fixes; use it directly when asked to "prune
    this", "shrink the diff", "usuń zbędny kod", or to strip what a change over-built. Do NOT use to
    hunt bugs (a review), to run checks (the project's verify skill), or for any cleanup whose fix is to write
    more code — an extraction, a rename or an efficiency rewrite is not this phase.
---

# Prune

Every other phase can only add. Review finds a missing guard and the fixer adds it, the implementer
adds a test, and nothing in the loop was ever chartered to take something out — so a PR could only
grow, measured at +34.1% between first review and merge across 13 PRs. This phase is the
counterweight.

It is not a gate. It asks no permission, blocks nothing and cannot say no to anyone; it makes the
diff smaller before the next phase has to read it. Two earlier attempts to bound PR growth failed
because they were bounds — they computed the growth, paused, and the run proceeded on approval. If
you find yourself writing a threshold, a budget, or a question about whether to go ahead, that is
the same failure coming back.

## What you may do

> **Remove code, and redirect to code that already exists. Introduce nothing new.**

That is the whole permission. It is a property, not a list of allowed edits: the diff does not grow
and no design decision gets made here. Repointing five call sites at an existing util is fine — the
util is not new. Inlining a helper's body at its one call site is fine, for the same reason.
Extracting a shared function is not, however obvious the duplication.

## Where you run

Once inside each implementation task, and once after a fix run. **Not a budget** — a plan with six
tasks prunes six times, and a branch fixed twice prunes twice more. If you are invoked and the tree
holds a change, that is reason enough.

Both times the tree was green on the `verify` skill's scoped check a moment before you started, and the caller
runs that same scoped check straight after you. That is what makes your output attributable —
nothing else touched the tree, so a red afterwards is yours, and since you may not add anything, the
remedy is to put the deletion back. Don't run the full verify; it runs once, later, and doubling the
expensive gate is exactly what the phase order exists to avoid.

Your subject is **the change in front of you** — the files the caller names, or when nobody named
any, the uncommitted work in the tree. Not the branch against the main line: that is a review's subject,
and on a fix run it would drag in every earlier task and re-judge what an earlier prune already
passed.

Old code is in scope when **the change made it removable** — a helper whose last caller this change
deleted has been on `main` for months and is still yours. What is out of scope is code the change
did not touch and did not orphan.

### Standing on a node of a chain, "no consumer" is judged against the chain

A node can hold an endpoint whose only caller arrives in the node above it, which reads as an
abstraction with no producer. **Look up the chain before deleting.**

## What to look for

- **A helper that duplicates something that already exists.** Delete it and repoint its call sites.
- **A single-caller helper, factory or constant.** Inline it.
- **Speculative generality** — a parameter nobody passes, a hook with no producer, an option with
  one value, an abstraction over a single case.
- **Code the change orphaned** — the branch that can no longer be reached, the field nothing reads,
  the import nothing uses.
- **A test the change added that carries no signal** — after implementation only; see below.

### The duplicate search is by capability, not by name

This is the check the writer could not perform, which is why it lands here. An agent writing
`formatMoney` greps `formatMoney`, finds nothing and writes it — the existing one is called
`formatCurrency`. `grep` is a lookup by name; a catalogue organised by what a thing *does* — if the
project keeps one, its `CLAUDE.md` says where — is what you need when you don't know its name.

You can run that lookup because by now the helper exists with a name, a signature and a body. Say
what it does in a phrase, then look for that capability — in the catalogue, or failing one by reading
the modules where such a thing would live — not for its identifier in the tree.

### Tests — after implementation, never after a fix

Tests are the last one-way valve: the implementer adds them, review adds them, nobody removes them.
The criteria for a worthwhile test are good and already written down in
`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/test-requirements.md`; they are simply applied at plan
time, to tests that are imagined. You are the first point where the test exists and can be read.

So for each test the change added: **what realistic production change would this catch, and does
another test already catch it?** Neither, and it goes. A test asserting a literal, a declaration or
type-enforced structure answers neither question — but check rather than assume, because the same
shape occasionally does own a real invariant.

The mandatory categories — security, privacy, authorization, compliance, data integrity — keep
their test at the boundary that owns the invariant, whatever it looks like. Phase 3.5 opens those
right after you and checks they still exist.

**After a fix run, leave the tests entirely alone.** By then every test in the change was written in
answer to a thread the owner left standing — either a review finding that survived refutation, or a
comment of his own, and an unresolved thread is consent. Neither is yours to remove, and you have no
way to tell which test came from which thread, so the rule is the whole behaviour rather than a
judgement call. If you cannot tell which of the two runs this is, treat it as a fix run and leave
them.

## What is not yours

Bugs, renames, efficiency, altitude, general tidying — none of it. **If the answer to what you found
is "write more code", it is not this phase's finding.**

That includes the tempting one: the same logic shape written twice inside this change. Its fix is an
extraction, and an extraction is new code *and* a design decision at once — what shape, what name,
where it lives. Making design decisions here would turn you into another author, which is the one
thing that stops this being a counterweight. Report it instead — *"the same shape is in X and Y; the
fix is an extraction, which is not mine to make"* — and leave it for review or for the owner.

## What to hand back

The list of what you removed: the file, and what each deletion was. Nothing about threads — you do
not see them and the caller maps them. This is not bookkeeping. The
caller reports it onward, and after a fix run it goes into the reply on the thread whose fix you
just
shrank — without it the owner is told something that is not true of the code now on the PR. If you
removed nothing, say that; it is equally an answer.

Then anything you found and could not fix, a sentence each. When that reaches him directly in chat
rather than through a caller, write it in his language.
