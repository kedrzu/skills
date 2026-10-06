---
name: feature
description: >-
    Use for a medium feature that spans multiple files or layers and benefits from
    a spec and plan before implementation. Examples: adding a new domain flow end-to-end,
    building a multi-step UI wizard, integrating a third-party service, or any work
    where requirements need to be clarified before coding starts.
    Do NOT use for bug fixes (/dev:fix), simple tasks (/dev:task), or large architecture changes (/dev:build).
---

# Feature

Full pipeline (Spec → Plan → Execute → Verify) for a medium feature. This skill is a thin entry point over the pipeline orchestrator: it selects the phases and adds the two `/dev:feature`-specific rules (acceptance-criteria form, final spec compliance check). The mechanics of every phase — approval gate, Socratic questioning, subagent dispatch, test policy, verification, finalization — live in the `pipeline` skill and its references, pointed to below. You run inside that orchestration; its Red Flags apply to you.

**Announce:** "Using /dev:feature to build this."

## When NOT to use

Pick the entry point by the smallest one whose trigger you actually hit — check top to bottom, first match wins:

|Situation|Use instead|
|-|-|
|Fixing one specific bug, tweak, lint/compile error|`/dev:fix`|
|Well-scoped, well-understood work; you could write the task list now without asking anything|`/dev:task`|
|**Requirements need clarifying, spans multiple files/layers, needs a spec before coding**|**`/dev:feature` (this skill)**|
|New subsystem / architectural change / new cross-cutting pattern / 8+ files with design trade-offs|`/dev:build`|
|Just run checks and make the repo green, no feature work|the project's `verify` skill|
|A researched, sourced answer with no implementation|a research skill, if the project has one|

Escalate mid-run when a runtime discovery moves you across a boundary — surface it per `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/escalation-protocol.md` (problem + options + recommendation): spec turns out trivial → offer `/dev:task`; spec covers multiple independent subsystems or introduces new architectural patterns → offer `/dev:build` (or split into separate `/dev:feature` runs). This is only for genuinely new problems the approved plan didn't settle — in-boundary work runs autonomously.

## Process

`/dev:feature` runs Phase 1 (Spec) → Phase 2 (Plan) → Phase 3 (Execute) → Phase 3.5 (Plan Completion Audit) → Phase 4 (Verify) → Final Spec Compliance Check → Post-Pipeline. Run them in order; Phase 1 and Phase 2 each end in an approval gate that must exit before the next phase starts.

Run each phase exactly as written in `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/SKILL.md` (it is the single source for phase mechanics — Phase Matrix, Spec/Plan formats, dispatch, audit). This skill only states the `/dev:feature` deltas.

### Phase 1: Spec

Follow pipeline **Phase 1: Spec** (explore → write spec → ambiguity finder → resolve → triage → approval gate). Two things are specific to `/dev:feature`:

1. **Ambiguity finder** — dispatch it using `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/ambiguity-finder-prompt.md`. Codebase-answerable questions → resolve autonomously and record the code reference in the spec; genuine ambiguities → batch into one upfront round per `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/socratic-protocol.md` (codebase-first, 4-part question, all genuine questions asked together).

2. **Acceptance criteria form** — 3-7 bullets, and each must be checkable by an automated verification, not a human eyeballing it:

   - Behavioral criterion (user-visible flow, request/response, state change) → phrase it so an **e2e OR integration test** can assert it. If neither kind of test could check it, the criterion is too vague — make it concrete.
   - Architectural criterion (a boundary that holds, a contract that stays intact, "X never imports Y") → it does not need a runtime test; instead name the **verification step** that proves it (e.g. "verified by the project's import-boundary check", "verified by a fresh-context read of the module graph in the Final Spec Compliance Check"). A named check is auditable; "should be clean" is not.

   Why the widening from "e2e-checkable": forcing every criterion through Playwright pushed backend-only and structural work into contrived UI assertions. The real rule is *auditable by a named, repeatable check* — e2e, integration, or a specific command — not *reachable through the browser*.

**Approval gate:** present the FULL spec, ask for explicit approval, and classify the reply exactly as written in `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/approval-gate.md`. The default classification for any reply is feedback → revise → re-present → re-ask; only a whitelist phrase moves to Phase 2. Answering the ambiguity finder's questions is NOT approval — that resolves gaps, the gate is a separate step on the complete artifact.

### Phase 2: Plan

Follow pipeline **Phase 2: Plan** (read spec → check memory → surface durable decisions → write plan → classify HITL/AFK → plan reviewer → resolve → apply findings → approval gate → task list → ADRs). `/dev:feature` specifics:

1. **Design It Twice** — for a key decision where multiple approaches are genuinely viable, propose two meaningfully different designs with trade-offs and a recommendation before writing the tasks that depend on it. This is the lightweight form; the full multi-agent divergent-constraint version (2-3 parallel subagents each given a different constraint) is defined in `${CLAUDE_PLUGIN_ROOT}/skills/build/SKILL.md` under "Design It Twice" — use that when the decision is architectural. Skip entirely when the codebase already dictates the pattern.

2. **Architecture Decision Gate** — run `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/architecture-decision-gate.md` whenever it triggers, before writing dependent tasks or starting custom design.

3. **Plan reviewer** — dispatch using `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/plan-reviewer-prompt.md`.

4. **What each task must protect** — one line per obligation in its `**Must protect:**` field: the behaviour, invariant or sensitive-data path that must still hold. The implementer chooses what discharges it, with the code in view; the mandatory categories admit only a test at the owning boundary or existing coverage (`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/test-requirements.md`).

**Approval gate:** identical gate to Phase 1 — present the FULL plan, classify per `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/approval-gate.md`, loop on anything that is not a whitelist phrase. Create ADRs for genuine architectural decisions → `docs/decisions/<title-slug>.md`.

### Phase 3: Execute + Phase 3.5: Audit

Run pipeline **Phase 3** (per-task, strictly sequential, ONE implementer at a time; dispatch implementer, handle status, scoped-verify → `prune` → scoped-verify again) and then **Phase 3.5: Plan Completion Audit** (re-read the plan, classify every task DONE/PARTIAL/NOT DONE/CHANGED, and open whatever discharges each `**Must protect:**` entry). An undischarged protection makes a task PARTIAL — finish it before Phase 4.

There is NO code-review step here. Review is on-request only — never insert one into the pipeline (pipeline Red Flags).

### Phase 4: Verify

Run pipeline **Phase 4**: invoke the project's `verify` skill and run its full protocol exactly as written there — the single authoritative step list. Do not reconstruct or abbreviate its steps here; run it in full. Every failure is YOUR responsibility; fix each one before claiming done.

### Final Spec Compliance Check (before any completion claim)

After Phase 4 passes and before you claim the feature is done, run the check as defined in pipeline Phase 4's "Final Spec Compliance Check". Concretely:

- **Dispatch a fresh-context subagent** — no session history. Fresh eyes are the whole point: it must judge the code, not your narrative of the code.
- **Input:** the original approved spec (full text) + the full diff of the branch (`git diff` against the base, or the accumulated changes of this run). Inject both as text; do not tell it to reconstruct them.
- **Output:** a per-acceptance-criterion pass/fail table — one row per criterion from the spec, PASS or FAIL, with the evidence (test name, command output, or file:line) for each.
- **Any FAIL** → fix it, then re-run Phase 4 verification and re-run this check. Do not proceed to Post-Pipeline with a FAIL on the table.

### Post-Pipeline

Run the finalization flow exactly as written in `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/post-pipeline.md` (commit → push → ready-for-review → PR changeset → tracker comment → confirm → completion options), each command from the project's `git-workflow`. Step 1c verifies the branch is on its remote before reporting done. It runs automatically — invoking `/dev:feature` is the user's authorization to commit, push, and log; the standing "don't change code without asking" preference governs the implement-vs-answer decision, NOT this finalization. Do not pause to ask.

For `/dev:feature`, the WHY in the PR changeset bullets and the tracker comment lead comes from the **spec's Problem/Scope section** (per-entry-point table in post-pipeline.md) — reviewers and downstream agents read only the PR and tracker text, so context not pulled from the approved spec is lost when the session ends.

## Failure handling

|Situation|Action|
|-|-|
|Requirements still unclear after the spec phase|Do NOT start Phase 2 — work with the user to clarify (Socratic, genuine questions batched into one round) until the spec is concrete, then re-run the approval gate.|
|Implementer returns BLOCKED / NEEDS_CONTEXT|Handle per pipeline "Subagent Status Handling" — provide context and re-dispatch, split the task, upgrade the model, or escalate per `escalation-protocol.md`. Never retry unchanged (an unchanged retry reproduces the same failure).|
|A novel, material problem the plan didn't settle (out-of-plan decision, new-feature finding, blast radius the plan didn't anticipate, entry-point boundary crossed)|Surface it per pipeline "Execution Autonomy" + `escalation-protocol.md` (problem + options + recommendation). In-boundary work stays autonomous — do not stop for it.|
|Genuinely stuck after real attempts|Stop and escalate WITH evidence — the exact error, what you tried, why it failed. A legal exit beats an improvised shortcut.|

## Red Flags

The pipeline's Red Flags apply in full (you run inside its orchestration). The ones most often violated at `/dev:feature` scope:

- Treating an answered ambiguity, feedback, or a lukewarm positive ("ok sure") as spec/plan approval — the gate exits ONLY on a whitelist match, because a model under revision pressure rationalizes "ok" into a green light. Classify every reply per `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/approval-gate.md`.
- Starting implementation before the spec OR the plan is approved — building before agreement produces thrown-away code.
- Claiming done on scoped/per-task greens without the full Phase 4 protocol — scoped builds never rebuild downstream consumers, so scoped greens do not compose into a green codebase.
- Claiming done before the Final Spec Compliance Check passes — "I implemented the tasks" is not "the spec's acceptance criteria are met".
- Inserting a code-review step because the change feels big — review is on-request only.

## References

|File|Read when|
|-|-|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/SKILL.md`|Running any phase — it owns all phase mechanics (Phase Matrix, Spec/Plan formats, dispatch, audit, Final Spec Compliance Check).|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/approval-gate.md`|At the Phase 1 and Phase 2 approval gates — before classifying ANY user reply.|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/socratic-protocol.md`|Before asking the user any ambiguity question.|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/escalation-protocol.md`|Mid-execution, when a novel material problem the plan didn't settle surfaces.|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/architecture-decision-gate.md`|Before significant architectural choices or any custom auth, storage, cryptography, or persistent infrastructure design.|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/ambiguity-finder-prompt.md`|Dispatching the Phase 1 ambiguity finder.|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/plan-reviewer-prompt.md`|Dispatching the Phase 2 plan reviewer.|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/test-requirements.md`|Writing each task's `**Must protect:**` entries (what must still hold).|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/stacked-prs.md`|After verification, when the finished feature has a natural seam and you cut it into a chain of small PRs.|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/post-pipeline.md`|After the compliance check passes — commit/push/ready-for-review/changeset/tracker finalization.|
|The project's `verify` skill|Phase 4 — the authoritative full verification protocol.|
|`${CLAUDE_PLUGIN_ROOT}/skills/build/SKILL.md`|Design It Twice, when the decision is architectural (full divergent-constraint form).|
