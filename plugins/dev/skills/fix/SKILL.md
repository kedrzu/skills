---
name: fix
description: >-
    Use when fixing a specific bug, small tweak, lint error, or compilation error.
    Also use when the user says "fix this", "fix that bug", "make it work",
    or any variation of wanting a specific issue resolved quickly.
    Do NOT use for: a full green-the-repo verification sweep (the project's verify skill);
    a well-scoped implementation task that needs a plan (task skill);
    a multi-file feature that needs a spec (feature skill);
    or a large/architectural change (build skill).
---

# Fix

Quick bug-fix pipeline: diagnose the root cause, get the diagnosis approved, then fix and verify. Skips the spec and plan phases — but keeps the diagnosis approval gate, because an unapproved fix that treats the wrong cause wastes more time than the gate costs.

**Announce:** "Using /dev:fix to resolve this issue. I'll diagnose the root cause first and get your approval before changing any code."

Verifying and landing the fix go through the project's `verify` and `git-workflow` skills
(`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/contracts.md`). If either is missing, say so
before you start — `/dev:setup` writes them — rather than diagnosing a bug you cannot then land.

## When NOT to use — route by structure, first match wins

Check these in order against the work in front of you:

|The change…|Use instead|
|-|-|
|touches **3+ packages** (excluding test files), OR changes a **public contract** (an exported signature, endpoint shape, or DB schema), OR diagnosis reveals a **design flaw** (the bug is the design, not a slip)|`/dev:task` — or `/dev:feature` if it also needs a spec (unclear requirements / multiple valid approaches)|
|is a clearly-scoped **implementation** unit (add an endpoint, create a component, refactor a module) with no bug to diagnose|`/dev:task`|
|is a new **subsystem / architectural** change spanning 8+ files with design trade-offs|`/dev:build`|
|is "make the whole repo green" / run all checks, with no single bug identified|the project's `verify` skill|

Everything else — one identified defect, small tweak, lint or compile error — stays here.

WHY this boundary is structural, not size-in-hours: a model cannot estimate "how long" reliably, but it CAN count packages, spot a changed export, and recognize when the fix is really a redesign. Escalating there keeps a fix from silently becoming an unplanned architecture change (see "Escalate mid-fix" below — this same test applies if you only discover the blast radius while diagnosing).

## Step 1: Diagnose the root cause — four ordered phases

Prove the cause; do not guess. Run these phases **strictly in order** — you cannot understand a bug you haven't isolated, and you can't isolate one you can't reproduce. Do not skip ahead to a fix.

### Phase 1 — Reproduce

- Confirm the bug exists with a concrete, repeatable case (exact input/state → observed wrong output).
- If you cannot reproduce it, you cannot fix it. Stop and report NEEDS_CONTEXT with the reproduction attempts you made and what you'd need from the user.

### Phase 2 — Isolate

Narrow to the smallest failing unit: which file, which function, which line.

- **Read the actual error message and stack trace. Then read it again.** Debug what it *literally says*, not your paraphrase of it — the paraphrase is where the wrong-direction session starts.
- **Binary-search the logic:** disable/short-circuit half the suspect path; does it still fail? Repeat on the failing half.
- **Tool — Pattern Analysis** (use here, it narrows scope): find a working example of similar functionality and diff it against the broken path — the difference is often the bug. Check `git blame` on the failing line: was it changed recently, or did a dependency bump land near it?
- **Tool — Multi-Component Debugging** (use here when the bug crosses packages/services): add diagnostic logging at each component boundary and trace the data flow — find the exact boundary where a correct value turns incorrect. That boundary's owning component is your isolate target.

### Phase 3 — Understand

- WHY does that line produce the wrong result? State the mechanism, not the symptom.
- What did the author intend (check `git blame` / the surrounding code if unclear)?
- What is the exact gap between expected and actual state at that point?

You do not leave Phase 3 until you can name the root cause in one sentence. That sentence is what the user approves in Step 2 and what the applicable test evidence supports.

### Mandatory defect classification

Before Phase 4, classify the defect using `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/defect-classification.md` and record the category for Step 2. Review discovery does not change the category.

### Phase 4 — Reproduce a production regression before fixing it (NO fix yet)

The failing test is your *proof* that Phase 3 is right — it is the last thing you do before the approval gate.

- **Production regression** → write the reproduction before the fix, run it, and confirm it FAILS for the diagnosed reason. A test born green proves nothing about the bug. **HOW** to write it is the project's testing skill (or its `CLAUDE.md`).
- **Any other category** → no red-first. Name what the fix must protect (`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/test-requirements.md`; the mandatory categories bind wherever the fix touches them) and what will discharge it, then write that after approval.
- **STOP after the test decision and any required test.** Do NOT edit any production code. The fix is written in Step 3, only after the user approves the diagnosis.

## Step 2: Diagnosis approval gate (STOP — wait for the user)

**Do not edit any production code until the user approves the diagnosis.** This gate exists because the user wants to read the root cause and sign off on the proposed fix before anything changes — a fix aimed at the wrong cause is worse than no fix.

Present all of this in **one** message, using the 4-part question format (re-ground → simplify → recommend → options) from `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/socratic-protocol.md`:

1. **Root cause** — evidence from Phases 1–3: the literal error/stack trace, the offending file/function/line, and the mechanism that makes it wrong. The proof, not a guess.
2. **Classification and what the fix must protect** — name the defect category; name any invariant the fix touches that must still hold (and, for security, privacy, authorization, compliance or data integrity, the test at the owning boundary that will hold it); when red-first applies, name the failing test.
3. **Proposed fix** — what you will change and where (files/functions), in plain terms. Describe it; do not write it.
4. **Ask for explicit approval** — e.g. "Approve this root cause and proposed fix? I'll implement only after you approve."

Classify the reply against the **canonical approval whitelist** — feedback is never approval; the default classification for ANY reply is feedback. Run the gate exactly as written in `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/approval-gate.md`.

- **Whitelist match** → go to Step 3.
- **Anything else is feedback** → revise the diagnosis and/or proposed fix, re-present the FULL diagnosis, and re-ask. Do NOT start implementing. Multiple rounds are normal; never combine a revision with proceeding to implementation.

## Step 3: Implement the fix (only after approval)

1. Fix the **root cause**, not the symptom.
2. Follow existing codebase patterns (CLAUDE.md is already in your context — don't restate it, apply it).
3. When Phase 4 required a red-first test, run it again and confirm it now PASSES; otherwise run the new or existing coverage named by the test decision.
4. Check whether the fix introduces any new issue in related code.
5. If the fix now touches 3+ packages or a public contract, or you realize the cause is a design flaw, STOP and escalate (see "Escalate mid-fix" below) — do not push through.

## Step 4: Per-task verification (scoped)

While the fix is the only outstanding work, run **scoped** checks on what you touched — not the full protocol (that wastes tens of minutes mid-fix). Run the `verify` skill's **scoped** mode — it owns the exact commands and how scope is derived from the changed paths. Fix every scoped failure.

Then run `prune` over the fix — name the files you changed and say it is an **implementation run** — and run the scoped checks again. It was green a moment ago and nothing else touched the tree, so anything red now is prune's, and the remedy is to put the deletion back. Only then go to Step 5.

## Step 5: Full verification protocol

Invoke the project's `verify` skill and run its **full** protocol exactly as written there — it is the single authoritative step list. `verify` defines the protocol; **fixing every error it surfaces is this skill's job** — do not hand failures back to the user while any remain fixable.

## Step 6: Post-pipeline (runs automatically — do not pause)

After verification passes, commit → push → ready-for-review → PR changeset → tracker comment → confirm → completion options, **without pausing to ask**, each command from the project's `git-workflow`. Step 1c verifies the branch is on its remote before reporting done — do not claim "pushed" until it is. Your Step 2 diagnosis approval is the authorization for these finalization steps; the standing "don't change code without asking" preference governs the pre-implementation gate, NOT this finalization. WHY source for the changeset and tracker text = the **approved diagnosis** (the bug and its root cause). Run it exactly as written in `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/post-pipeline.md`.

## The 3-strike rule

An **attempt** = one distinct **hypothesis** about the cause, implemented and tested. Re-editing the *same* hypothesis (tweaking the same fix that failed) is NOT a new attempt — it's the same strike.

After **3 distinct hypotheses fail**, STOP. You are treating a symptom, not the cause — a 4th variation of the same wrong idea won't help. Do this instead:

1. Re-read the stack trace from scratch (the raw trace, not your interpretation of it).
2. Re-check `git blame` for recent changes in the affected area.
3. Look one layer deeper — the bug may be upstream of where it manifests.
4. Question the core assumption: "What if the bug isn't where I think it is?"
5. **Escalate WITH evidence** — a legal exit prevents a rationalized illegal one. Report: the 3 hypotheses you tried, the exact failure of each, and your current best guess at the real cause. Ask the user how to proceed.

## Escalate mid-fix

Between the approved diagnosis and a green fix, run autonomously — the approved diagnosis is your boundary. The one thing that stops you: discovering the fix is bigger than the diagnosis assumed — it meets a trigger from the "When NOT to use" table (**3+ packages, a changed public contract, or a design-flaw root cause**). That is a novel, material problem the diagnosis didn't settle, so surface it per `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/escalation-protocol.md` (problem + evidence + options + recommendation) rather than either pushing through silently or guessing at the redesign:

> "This is bigger than the approved fix — it [touches N packages / changes the X contract / the root cause is a design issue in Y]. Options: **A)** upgrade to `/dev:task` for proper planning; **B)** [narrower fix that stays in the current blast radius, if one exists]; **C)** [other]. I lean A because …"

WHY: a fix that quietly grows into a redesign skips the planning and approval that a change that size requires. Catching it mid-fix is expected — the blast radius often only becomes visible during diagnosis.

## Red flags — STOP, then recover

Each row: the trap, why it burns you, and what to do the moment you catch yourself.

|If you catch yourself…|Why it's a trap|Recover by|
|-|-|-|
|Editing production code before the Step 2 diagnosis is approved|You may be fixing the wrong cause; the user hasn't seen your reasoning|Revert the edit, finish the diagnosis, present the Step 2 gate|
|Applying a fix before you can state the root cause in one sentence|A fix without a cause is a guess; it hides the real bug|Go back to Phase 3; do not fix until the sentence exists|
|Fixing a symptom while the real bug is elsewhere|The symptom returns via another path; you've added noise|Re-run Phase 2 (Isolate) at the boundary one layer up|
|Making the same class of change a 3rd time ("maybe THIS will work")|You're out of hypotheses on this theory — variations won't converge|Invoke the 3-strike rule: stop, reset assumptions, escalate with evidence|
|The fix now spans 3+ packages or changes a public contract|It's no longer a fix; it's unplanned architecture|Escalate to `/dev:task` (or `/dev:feature`) — see "Escalate mid-fix"|
|Thinking "this is probably fine" without running verification|"Probably" is not evidence; green is|Run scoped checks (Step 4), then the full `verify` protocol (Step 5)|

## References

- `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/defect-classification.md` — read before Phase 4: classify the defect before deciding whether red-first applies.
- `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/approval-gate.md` — read when running the Step 2 gate: the canonical whitelist and the feedback-is-default loop.
- `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/socratic-protocol.md` — read when composing the Step 2 diagnosis message: the 4-part question format.
- `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/escalation-protocol.md` — read when escalating mid-fix: the problem + options + recommendation format for a novel problem the diagnosis didn't settle.
- `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/test-requirements.md` — read at Phase 4: what must be protected, what may discharge it, and the red-first policy.
- `${CLAUDE_PLUGIN_ROOT}/skills/prune/SKILL.md` — read at Step 4: the subtractive pass over the fix, between the two scoped runs.
- The project's testing skill — read at Phase 4 / Step 3: HOW to write the reproduction and fix tests.
- The project's `verify` skill — scoped mode at Step 4, the full protocol at Step 5.
- `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/post-pipeline.md` — read at Step 6: commit → push → ready-for-review → PR changeset → tracker flow and its auto-run authorization; the commands come from the project's `git-workflow`.
