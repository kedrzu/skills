---
name: task
description: >-
    Use for a well-scoped implementation task: adding an endpoint, creating a component,
    refactoring a module, wiring up a new service, or any clearly-defined unit of work
    that benefits from a lightweight plan but doesn't need a full spec.
    Do NOT use for bug fixes (/dev:fix), medium features needing a spec (/dev:feature),
    or large/architectural work (/dev:build).
---

# Task

Lightweight plan → execute → verify pipeline for well-understood work with clear scope. Runs the `/dev:task` column of the pipeline Phase Matrix: Plan → Execute → Verify (NO spec phase). See `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/SKILL.md` Phase Matrix.

**Announce:** "Using /dev:task to implement this."

## When NOT to use

Route by structural signal — not by estimated hours (a model can't verify hours). Check in order, first match wins:

|Signal|Skill|
|-|-|
|A specific bug, tweak, lint/compile error to resolve|`/dev:fix`|
|Work needs a written spec first — requirements unclear, or multiple valid approaches to weigh|`/dev:feature`|
|Introduces a new pattern/subsystem, or needs an architectural trade-off decision|`/dev:build`|
|Otherwise (clear scope, existing patterns, just needs a plan)|stay here|

Mid-run, the same triggers escalate: if planning surfaces >8 tasks or a design trade-off, or a task turns out to need a new pattern, that is a novel problem the plan didn't settle — surface it per `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/escalation-protocol.md` (problem + options + recommendation, including `/dev:feature` or `/dev:build` among the options). WHY: a task that silently grows into a redesign ships unreviewed architecture — but equally, don't stop for in-boundary work the plan already covers.

## Process

### Phase 2 — Plan

1. Explore the affected code to understand existing patterns.
2. Write a lightweight plan to `.context/plans/<YYYY-MM-DD>-<topic>.md`, following the **Plan Format** in `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/SKILL.md` — the claims it rests on, then ordered tasks, each listing Files, Must protect, Approach and Mode. `Must protect:` states the obligation; what discharges it is the implementer's call with the code in view (`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/test-requirements.md`).
3. Dispatch the **plan reviewer subagent** using `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/plan-reviewer-prompt.md`. Apply what comes back to the plan; a fork goes to the user immediately.
4. Resolve ambiguities: codebase-answerable → resolve autonomously; genuine gaps → batch into one upfront round per `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/socratic-protocol.md`.
5. **Approval gate.** Present the FULL plan, ask for explicit approval, and classify the reply exactly as written in `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/approval-gate.md`. Feedback (and answered ambiguity questions) is never approval — revise → re-present in full → re-ask. Loop until a whitelist phrase; only then proceed.

### Phase 3 — Execute

Follow `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/SKILL.md` Phase 3 for per-task implementation: sequential implementer dispatch, then per task scoped verification → `prune` → scoped verification again. The implementer reports what discharges each `**Must protect:**` entry before DONE. `/dev:task` does NOT run code review — review is on-request only; never insert one.

### Phase 3.5 — Plan Completion Audit

After all tasks report done, `/dev:task` DOES run this audit — do not skip it. Follow `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/SKILL.md` Phase 3.5: re-read the plan, classify each task (DONE / PARTIAL / NOT DONE / CHANGED), and open whatever the implementer named as discharging each `**Must protect:**` entry before the expensive Phase 4. An undischarged protection → the task is PARTIAL; finish it now.

### Phase 4 — Verify

Follow `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/SKILL.md` Phase 4: invoke the project's `verify` skill and run its full protocol. Every failure is YOUR responsibility until proven otherwise.

### Post-Pipeline

A `/dev:task` is normally a **single PR**. Only when the finished change turns out to have a clean **two-part seam** (mechanical refactor → behavior change, or generated/version bump → hand-written consumers) cut it into a 2-node chain per `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/stacked-prs.md`. That call is made here, on the verified code — not in the plan.

Finalization runs automatically after Phase 4 passes — commit → push → ready-for-review → PR changeset → tracker comment → confirm → completion options, each command from the project's `git-workflow`. Do NOT pause for permission: invoking `/dev:task` is your authorization to finalize. Step 1c verifies the branch is on its remote before reporting done. Run it exactly as written in `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/post-pipeline.md` (the `/dev:task` row sources the changeset WHY from the plan + originating request).

## References

|File|Read when|
|-|-|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/SKILL.md`|Phase Matrix, Plan Format, Phase 3 / 3.5 / 4 mechanics|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/approval-gate.md`|Before classifying ANY reply at the plan approval gate|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/socratic-protocol.md`|Before asking the user any ambiguity question|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/escalation-protocol.md`|Mid-execution, when a novel problem the plan didn't settle surfaces|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/test-requirements.md`|Writing each task's `**Must protect:**` entries|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/plan-reviewer-prompt.md`|Dispatching the plan reviewer subagent|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/stacked-prs.md`|Only when the verified change has a clean two-part seam and you cut it into a 2-node chain|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/post-pipeline.md`|After Phase 4 passes — commit/push/ready-for-review/changeset/tracker finalization|
