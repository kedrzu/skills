# The refutation pass

You get every finding from all six axes, and where the PR is one of a chain, from every node of it.
You decide what happens to each: refuted, fixed without the owner, or brought to him. Everything
brought to him lands on him, and publishing a comment is effectively deciding the code will change —
his only cheap answer is to resolve the thread. So the bar is yours to hold, before publication
rather than after it.

Read the area instructions first: the `CLAUDE.md` and `REVIEW.md` files that `axes.md` sends the
finders to, on the paths of the findings. What they say is blocking there, what not to report and
what a claim needs as evidence outrank your own sense of each, in every question below and in the label.

Take the findings one at a time, in this order.

**1. Can you refute it against the code as it stands?** Open the files. Default to refuted — an
unproven claim is not a finding, and "plausible" is not proven. The finder may have read a stale
line, guessed at a call site it never opened, or reasoned about a path nothing can reach.

"As it stands" is the tip of the chain. A finding on a lower node that a higher one already repaired
is refuted — a finder reading one layer cannot see that, and you can.

Where the finding rests on a rule rather than on the code, you need the rule's source to check it at
all — if the finder did not name one, you cannot confirm the claim, so it is refuted.

**2. Was it settled already?** When you were given the branch's memory, it lists what earlier runs
refuted and fixed, and what the owner decided in chat, each with the commit it was settled on. A
finding that matches an entry is dropped as already settled — unless the code it rests on changed
since that commit, or you can say why that verdict was wrong. A verdict is not final because it was
given once, and it is not reopened because a fresh finder phrased it differently. When you let one
through, say which of the two reasons applies. For an over-building finding the design's
`DECISIONS.md` and the plan's Claims count as settled record too: a mechanism he kept there with the
simpler version in front of him (it stands as that decision's Rejected line, or as a confirmed Claim)
is dropped, unless its premise has changed.

**3. Can it be fixed without him?** Yes when it breaks a written rule, duplicates code that already
exists, or is a plain code smell — and its fix is obvious and carries no risk he would want to see:
it leaves what the code does unchanged and touches nothing that matters in infrastructure, however
large it is. Collapsing three classes into one with the same tested behaviour takes this exit;
changing one infrastructure parameter may not. Code that guards security, authorization, audit or sensitive data carries risk by default. A bug fix never takes it, however small: a change in
behaviour is his to know about. An over-building finding never takes it either. He would never argue with the rest, so no consequence needs arguing:
their cost is that every later reviewer trips over them again. Write down the mechanism and every place it occurs — for a duplicate,
every copy in the repository — because that is the fixer's whole brief.

**4. Otherwise: what concretely goes wrong, for whom, and when, if this is left alone?** Name an
actor and a moment. *"The next person adding a currency greps for the formatter and finds two"* is a
consequence. *"Maintainability suffers"* is the no-op version and fails, as does any answer that
only restates the rule the finding rests on — and a finding that fails is dropped. Write your answer
down — it becomes the comment's human layer, because it is exactly what lets him judge in one read.
Estimate whether the fix adds or removes code, and by how many lines; the comment carries it.
A *fixed here* finding whose fixer handed it back — the fix needed a choice or carried risk after
all — comes back to you for this question; one that fails is dropped as refuted.

An over-building finding has its consequence already: the complexity, which is what produces bugs
later. Check two things instead. Is the simpler version real, and would it still do what the change
is for? Does it name everything it gives up, including requirements he stated himself, which are
questioned like any other? Drop one that fails either check.

Then label each one for him. **Blocking** — a consequence you would not ship. Wrong or lost data, a
security, privacy or authorization hole, and a requirement the change was meant to meet and does
not are the usual cases, but the list is illustrative and the judgement is yours. **Should fix** —
real, with a named consequence, but nothing breaks if it lands. **Recommendation** — every
over-building finding that survives: the simpler version he may choose, which never blocks.

Hand back each survivor with:

- its **exit** — *fixed here*, or *to him* labelled **blocking**, **should fix** or **recommendation**
- its **mechanism**: why it happens and every place it occurs
- its **provenance** — the axis, and where it rests on a rule, that rule's source
  (`Security · <the project's rule source> → audit at business boundary`). The comment's second line is
  built from this, and without it the owner cannot check a conformance claim in seconds
- for *to him*: the **consequence** from question 4, in the owner's language, and the **delta**
- the **node** it came from, carried through unchanged

And hand back **every finding you refuted as one line in the owner's language** (the orchestrator
tells you which): the claim as he would read it, plus the one thing that disproved it. The run
closes by listing those for him — it is how he judges whether the bar is set right. Findings dropped
as already settled are only counted.

Do not rewrite a finding into a different one to save it: if what survives is a different claim than
what was reported, it needs the same questions asked of it from the start.
