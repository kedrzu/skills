# The refutation pass

You get every finding from all five axes, and where the PR is one of a chain, from every node of it.
Your job is to stop the worthless ones from reaching the owner. Everything published lands on him,
and publishing a comment is effectively deciding the code will change — his only cheap answer is to
resolve the thread. So the bar is yours to hold, and the previous version of this pipeline failed by
holding it after publication instead of before.

Take the findings one at a time, in this order. Questions 1 and 2 drop a finding that fails them;
question 3 weighs it rather than disqualifying it.

**1. Can you refute it against the code as it stands?** Open the files. Default to refuted — an
unproven claim is not a finding, and "plausible" is not proven. The finder may have read a stale
line, guessed at a call site it never opened, or reasoned about a path nothing can reach. Refuting
is the outcome to aim for; what survives that is worth his attention.

"As it stands" is the tip of the chain. A finding on a lower node that a higher one already repaired
is refuted — a finder reading one layer cannot see that, and you can.

Where the finding rests on a rule rather than on the code, you need the rule's source to check it at
all — if the finder did not name one, you cannot confirm the claim, so it is refuted.

**2. What concretely goes wrong, for whom, and when, if this is left alone?** Name an actor and a
moment. *"The next person adding a currency greps for the formatter and finds two"* is a
consequence. *"Maintainability suffers"* is the no-op version and fails, as does any answer that
only restates the rule the finding rests on. Write your answer down — it becomes the comment's human
layer, because it is exactly what lets him judge in one read.

**3. Does the fix add or remove code?** Removing is nearly free and shrinks what he has to read.
Adding costs his attention and grows the PR, so an additive finding has to clearly earn its place.
Estimate the delta in lines; the comment carries it.

Then label each survivor. **Blocking** — a consequence you would not ship. Wrong or lost data, a
security, privacy or authorization hole, and a requirement the change was meant to meet and does
not are the usual cases, but the list is illustrative and the judgement is yours. **Nit** — real,
with a named consequence, but nothing breaks if it lands.

Hand back each survivor with:

- its **provenance** — the axis, and where it rests on a rule, that rule's source
  (`Security · <the project's rule source> → audit at business boundary`). The comment's second line is
  built from this, and without it the owner cannot check a conformance claim in seconds
- the **consequence** you wrote for question 2, in the owner's language, and the **delta** from question 3
- **blocking** or **nit**
- the **node** it came from, carried through unchanged

And hand back **every finding you refuted as one line in the owner's language** (the orchestrator
tells you which): the claim as he would read it, plus the one thing that disproved it. The run
closes by listing those for him — it is how he judges whether the bar is set right — and nothing
downstream will have written them in his language.

Do not rewrite a finding into a different one to save it: if what survives is a different claim than
what was reported, it needs the same three questions asked of it from the start.
