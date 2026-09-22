# Failure sweep

An independent attempt to break the model, run by an agent that cannot see why the model is the way it
is. Run it when a model has taken shape and there is something to falsify.

## Blind the generator

Give the subagent the model as it stands, the invariants, the lifecycle and authority rules if you have
them, and the concrete scenarios — **restated in your own words. Never paste the reasoning**: not the
decisions, not the justifications, not thread text, not the note explaining why an entity isn't just a
field on something else.

This is the whole mechanism. An agent generating cases from a model it just justified produces cases the
justification already covers — a self-graded exam that restates the design and buys confidence it didn't
earn. An agent that cannot see the justification cannot pre-answer.

Dispatch per your model-selection rules if the project has them; otherwise a cheap fast model is
enough. Read-only, so it can run alongside other read-only work.

```text
You are testing a design you did not write and whose rationale you cannot see.

<the model, invariants, lifecycle/authority rules, and concrete scenarios — nothing that explains why>

Generate the awkward cases this design will meet in reality. Work through these
transformations and keep the ones credible for this domain:

  duplicate · delay · reorder · retry · concurrent action · correction ·
  consent withdrawal · stale authorisation · partial failure · emptiness ·
  retroactive change · time boundaries

For each, state in four lines: initial state · the event · the invariant that
should hold · who is responsible for recovery.

Do not judge whether the design handles them and do not propose fixes. Don't pad —
one case a practitioner would recognise beats ten generic ones.
```

## What you do with what comes back

You classify; the generator doesn't. For each credible case, either point at the relation, invariant or
rule that already resolves it, or say plainly that nothing does.

**No scores, no counts, no exit gate.** A count reads as a measurement when it is really a restatement,
and "all cases resolved" as a condition for finishing turns an independent challenge into an unbounded
gate — which grows the design through a long series of small mandatory fixes into exactly the overbuilt
thing this is meant to prevent.

Present the credible failures and **let the user pick the disposition**: fix it now, defer it as beyond
the current horizon, or accept the risk. Record the ones that changed something in `DECISIONS.md`, and
record a deferral or an acceptance there too — otherwise the next sweep rediscovers it. The story only
mentions a case that changed what we are building.

Watch the *pattern*, not the tally: if resolving these keeps requiring another special rule, the model is
wrong and the answer is to re-model, not to add the eleventh rule.

## Where a failure points

Usually at the conceptual model, a lifecycle, an authority rule, or an invariant. Approval expiry,
consent withdrawal, stale authorisation and reconciliation order are lifecycle and authority problems,
and they are the common case.

Resist "this means we need a new entity". Adding one often makes the problem disappear from view without
resolving it — which rewards over-modelling, the opposite of what this is for. Add a concept when it
makes an invariant locally enforceable.

## Reporting

Short. Expand only the failures; a case the model already handles is one line naming what handles it.

```markdown
Holds for duplicates, reordering and empty uploads — the page-to-document assignment
invariant covers all three.

Two credible failures:

**Consent withdrawn after extraction, before the doctor reads it.** Nothing says what
happens to already-extracted observations. That's an authority question, not a modelling
one — it needs a rule about what a withdrawn consent invalidates retroactively.

**Two clinicians correct the same document date concurrently.** Revisions give us history
but no conflict rule; last-write-wins would silently discard a correction.

The first is inside the horizon. The second only bites with a real care team — defer?
```

Then let them decide. Don't decide for them, and don't start re-modelling because a sweep came back with
something.
