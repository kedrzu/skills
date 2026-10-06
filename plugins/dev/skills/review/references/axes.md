# Finder briefs

One agent per axis, all in parallel. Each reads the shared part below and its own section.
Correctness, consistency & reuse and deleted coverage run **once per node** of the PR chain; spec
and security & compliance run **once over the whole chain**. An unstacked branch is one node.

## What they all share

**The diff you were given is your subject; the working tree is the chain's tip.** Only what it
changed is yours to judge — pre-existing code is not a finding, and a finding is yours only when
your diff contains the lines it is about. Open the surrounding files whenever proving something
needs them: they show the final state of the code, upper layers included, which is what stops you
reporting something a later node already fixed.

Verification already passed: the project's full verify — types, lint, tests, formatting, builds —
is green, and anything it would have caught is noise here.

**Open the skills that govern the files you are reading.** Pick them off the available-skills list
by their descriptions; nothing is handed to you. Read a skill as a hint about where to look, not as
a checklist to run down the diff — scanning a rulebook for violations is how *"is there one export
per file?"* became two threads that had to be reverted.

Everything you report goes to an agent whose job is to refute it, and it drops whatever it cannot
prove. So bring evidence rather than suspicion. Per finding: where it is (`file:line`), what is
wrong in one sentence, and what makes you believe it — the lines you actually read, or, when the
finding rests on a rule, which rule and where it is written (e.g. `database/SKILL.md` → the transaction
around check-then-insert). The bar for publishing is held once, by that agent; do not hold it here
as well.

**Concrete technical decisions only — files, lines, a rule this change breaks.** If your objection
is to the approach itself, it is out of scope: that belongs to planning, where it costs a paragraph,
not to review, where acting on it costs a rewrite.

Returning nothing is a normal outcome, not a failure to find something.

## Correctness

Read no repo rules; a bug is a bug, and no convention tells you whether a condition is inverted.

What the code does against what the surrounding code plainly means it to do: an inverted or missing
condition, a null/empty/error path nobody handles, an off-by-one, an ordering or concurrency
assumption that does not hold, a check and a write that can interleave, an external call that is not
idempotent or that sits inside a transaction, state that can be written twice or silently lost.

On a chain, one thing more, and it is nobody else's: this node lands on the chain's base before the ones
above it. **Does it break something already running there** — a migration dropping a column whose last
consumer only disappears in the node above? *"This node does not build on its own"* is not it: a
build gate runs on every PR, and no finder outperforms a compiler.

Style, naming and structure are not yours.

## Spec

The spec and the PR descriptions are the standard, and nothing else is.

Three shapes: a requirement with nothing implementing it; behaviour the code has that nothing asked
for; code that contradicts an acceptance criterion. Quote the line you are judging against.

On a chain you get **every node's description, together**, and they are one standard rather than
several: each node describes only its own layer, so a layer read against another node's description
looks like behaviour nobody asked for. Where a spec exists it leads.

With no spec, the descriptions are the standard and it is a weak one — a finding needs a quotable
claim, not an intention you inferred. With neither, report nothing.

## Security & compliance

The one axis where the rule *is* the standard: *"a disclosed read of regulated data needs an audit
event"* is not derivable from the code, and breaking it costs a regulatory or security consequence
rather than a maintenance one. Whenever the diff goes near sensitive data — personal, health,
financial, credentials — read the project's security and privacy rules: its `CLAUDE.md` and the
skills governing the touched files.

What breaking such a rule looks like, by example: a disclosed read of regulated data (PHI, say) or a
committed state change with no audit event where the project requires one; authorization enforced
in one layer where the project requires defense-in-depth; sensitive data reaching logs, errors or
an error tracker; an endpoint whose input or auth context is unvalidated.

## Consistency & reuse

Phase 3 (`dev:prune`) has already compared the diff against the repo and removed duplicates,
hand-written copies of existing utils, and dead code. What is left for you is the half imitation
cannot deliver: **conformance to a rule no nearby file demonstrates.** Where every neighbour does it
the wrong way, imitation spreads the wrong way and there is no correct instance to cite — those are
exactly the findings worth having, so "cite a file that does it right" is not asked of you.

Read the skills governing the touched files (the project's code index, if it has one, only as a
fallback) and **name the rule's source in every finding** — the verifier cannot adjudicate a
conformance claim without it, so a finding that omits it dies there rather than here.

## Testing — deleted coverage only

One question: did this PR remove test coverage? A deleted test file, a deleted test or assertion, a
case dropped from a table, a `test.skip` added. Say what is no longer covered.

Nothing else belongs to this axis. *"There is no test for this"* belongs to the implementer and to
the plan's `Must protect` list; *"this test carries no signal"* belongs to phase 3, which prunes
tests on purpose. You report a deletion, never an absence.
