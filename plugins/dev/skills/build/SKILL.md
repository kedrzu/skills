---
name: build
description: >-
    Use for large features, new subsystems, architectural changes, or cross-cutting work
    that introduces new patterns or requires significant design decisions. Examples:
    adding a new actor system, redesigning the auth layer, building a new app module
    from scratch, or any work spanning 8+ files with architectural trade-offs.
    Do NOT use for: bug fixes or one-file tweaks (/dev:fix), a well-scoped single unit of
    work with no spec needed (/dev:task), a medium multi-file feature that fits one
    spec+plan without architecture-level design (/dev:feature), or building a closed design
    from docs/design/<slug>/ (/dev:deliver). When unsure between
    /dev:feature and /dev:build, the deciding signal is architectural design work, not file count.
---

# Build

The `/dev:build` entry point of the dev pipeline: full spec → plan → execute → verify run, with **deep design work in the plan phase**. Everything except that deep design is identical to `/dev:feature` and runs through the shared orchestrator.

**Announce:** "Using /dev:build for this major feature."

## When NOT to use

`/dev:build` is the heaviest entry point. Route down when the work is smaller — carrying a small change through spec + Design-It-Twice + deep plan review wastes the user's time and yours.

|The work is…|Use|
|-|-|
|A bug, lint/type error, or a one-file tweak|`/dev:fix`|
|One clearly-scoped unit of work (endpoint, component, refactor) — no spec, no architecture decisions|`/dev:task`|
|A multi-file feature that fits ONE spec + plan, following patterns that already exist|`/dev:feature`|
|A new subsystem / new pattern / architectural trade-off / cross-cutting change|`/dev:build` (here)|
|Building a closed design from `docs/design/<slug>/` — the decisions are already made|`/dev:deliver`|

Decider between `/dev:feature` and `/dev:build`: does the plan require **choosing between viable architectures** (Design It Twice below), or does it just apply patterns the codebase already dictates? Design work → `/dev:build`. Applying known patterns → `/dev:feature`, even across many files. File count alone never decides — 8+ files is a symptom, architectural trade-offs are the cause.

Also not `/dev:build`:

- Standalone "verify / make it green" (no feature to build) → the project's `verify` skill.
- Code review → only when the user explicitly asks. Review is never a step inside `/dev:build`.

## Process

`/dev:build` IS the dev pipeline at its deepest level. Run every phase exactly as written in `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/SKILL.md` — the orchestrator owns the phase mechanics, the approval gates, per-task dispatch, the audit, and finalization. This skill only states the two things `/dev:build` does **differently** from `/dev:feature`: Design It Twice in the plan, and the enhanced plan-review delta.

Phases for `/dev:build` (per the Phase Matrix in `pipeline`): **Spec → Plan (deep) → Execute → Verify.**

1. **Phase 1 — Spec.** Run pipeline Phase 1 as written. `/dev:build` difference: explore **broadly** and map ALL affected areas before writing the spec, and expect the ambiguity finder to surface more gaps — large scope hides more edge cases. Acceptance criteria stay behavior-level and durable (no file paths), and each is verifiable by an e2e OR integration test; a criterion that is purely architectural (e.g. "notification dispatch does not import preference code") gets a named verification step in the plan instead of a test. Spec approval gate loops exactly as written in `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/approval-gate.md` — feedback and answered ambiguity questions are never approval.

2. **Phase 2 — Plan (deep).** Run pipeline Phase 2 as written, with these `/dev:build` additions:
   - **Architecture Decision Gate** — before Design It Twice or custom design, run `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/architecture-decision-gate.md` whenever it triggers. Do not write dependent tasks until any required custom-architecture approval is explicit.
   - **Design It Twice (divergent constraints)** — three parallel Plan subagents with incompatible constraints, per the "Design It Twice" section of this file. Do this for every significant architectural decision BEFORE writing the plan tasks.
   - **Protections** — the plan states obligations in each task's `**Must protect:**` field; the implementer chooses what discharges each one with the code in view, and the mandatory categories admit only a test at the owning boundary or existing coverage (`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/test-requirements.md`).
   - **Enhanced plan review** — the standard plan reviewer plus architecture validation, scope-creep, and dependency-risk checks, per the "Enhanced plan review" section of this file.
   - Surface each architectural decision in the plan with its trade-offs (carry the Design-It-Twice alternatives forward), and write an ADR per genuine decision → `docs/decisions/<title-slug>.md` or the project's ADR location (format in `pipeline`). The plan approval gate loops exactly as written in `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/approval-gate.md`.

3. **Phase 3 — Execute.** Run pipeline Phase 3 as written: ONE implementer at a time, which opens the skills governing its own files; then per task, scoped verification (the `verify` skill's scoped mode) → `prune` → scoped verification again; then Phase 3.5 Plan Completion Audit. There is **no review step** in this flow — review runs only when the user explicitly asks for it.

4. **Phase 4 — Verify.** Invoke the project's `verify` skill and run its full protocol exactly as written there (the single authoritative step list). Then the **Final Spec Compliance Check** (pipeline Phase 4): a fresh-context subagent gets the original spec + the current diff and returns a per-acceptance-criterion pass/fail table — any FAIL is fixed and verification re-run. Every failure is YOUR responsibility until proven otherwise.

5. **Post-pipeline.** Decide first whether the verified change is cut into a stacked chain (section below, mechanics in `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/stacked-prs.md`), then finalize. Finalization runs automatically after Phase 4 passes — do not pause for permission. Invoking `/dev:build` is the user's authorization to commit, push, take the PR out of draft, update the PR changeset, and post the tracker comment, each command from the project's `git-workflow`. Step 1c verifies the branch is on its remote before reporting done. Run it exactly as written in `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/post-pipeline.md`; its per-entry-point table says `/dev:build` sources the changeset and tracker WHY from the **spec's Problem/Scope section** (not the task list). Then present the completion options (Create PR / Keep working / Discard).

## Design It Twice (divergent constraints)

`/dev:build`-specific. For each significant architectural decision, do NOT design once and refine — the first idea anchors everything after it. Instead spawn **three Plan subagents in parallel**, each locked to a different constraint so their designs genuinely diverge:

- **Agent A — minimize the interface:** fewest entry points, smallest public API surface, most hidden.
- **Agent B — maximize flexibility:** support extension and future/unknown use cases; more seams.
- **Agent C — optimize the common case:** make the default path trivial, even at the cost of edge-case ergonomics.

Each agent returns: the interface signature, one usage example, what the design hides, and its trade-offs.

WHY three constraints instead of "propose a few options": a single agent asked for alternatives produces variations on one idea (it anchors on its own first sketch); forcing three incompatible optimization targets forces three genuinely different shapes, so the comparison is real.

**Provider diversity (optional):** the three panel members are read-only design agents, so where the project can dispatch agents from another model provider (its `CLAUDE.md` or a model-selection skill says how), one panel member may be one — a genuinely different design instinct on the logic-heavy option, say. Only when it adds real divergence, not for its own sake.

**Fan-out cap:** run ONE decision's panel at a time — 3 Plan subagents in flight, never several panels concurrently. Architectural decisions usually depend on each other, so a later panel must see the earlier decision's outcome; and each panel is expensive (three full design contexts), so serializing panels also bounds the token fan-out.

**What the user sees:** a comparison summary of the three designs + your recommendation (or a hybrid), not the three full designs — offer to show any full design on request. The user chooses; you do not pick silently.

**If the three designs converge** on essentially the same shape: present the single consensus design and say so explicitly — *convergence is signal that the design is constrained by the problem, not wasted work.* Do not manufacture artificial disagreement to look thorough.

Skip Design It Twice for a decision where the codebase already dictates the pattern (there is nothing to choose) — note that you skipped it and why.

## Enhanced plan review (delta vs standard)

`/dev:build` uses the SAME plan reviewer subagent as `/dev:task` and `/dev:feature` — dispatch it exactly as written in `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/plan-reviewer-prompt.md`. The prompt itself already carries a `/dev:build`-only section; state the pipeline level as `build` so the reviewer runs it. The delta the reviewer adds on top of the standard completeness / ordering / task-size / pattern checks:

- **Architecture validation** — are the architectural decisions surfaced explicitly with trade-offs (the Design-It-Twice alternatives)?
- **Scope-creep check** — are there tasks that go beyond the spec? Anything that should be deferred to a follow-up?
- **Dependency risk** — tasks that depend on external/uncontrolled factors.

Use opus for the `/dev:build` plan reviewer (architecture validation needs the deeper read). Apply what it returns to the plan; anything that is a fork goes to the user immediately rather than into the document. Then run the approval gate.

## Splitting a large build

Some builds are too large to run as a single pipeline pass. Split when the feature contains **independently verifiable increments** — pieces that each leave the codebase green on their own (compile + tests pass without the later pieces). Split along **subsystem seams** (e.g. data layer / API / UI, or two bounded contexts), NOT by raw file count — a 20-file change to one cohesive subsystem is one increment; a 6-file change spanning schema + a new actor + a UI flow is three.

When a build meets that criterion, **ask the user with a concrete proposed split** — do not split silently:

> "This is large enough to split into N independently shippable pieces: (1) …, (2) …, (3) …. Each leaves the codebase green on its own. Run them as separate pipeline passes (`/dev:feature` or `/dev:task` each), then a final integration verification across all of them? Or keep it as one `/dev:build`?"

If the user agrees: run each piece through `/dev:feature` or `/dev:task`, in dependency order, then a final verification pass across all pieces together. If the user prefers one pass, proceed as a single `/dev:build`.

**Splitting the run is not splitting the PR.** The split above turns *independent* increments into *separate* pipeline passes, and it is a question for the user because it changes what he approves. Whether the work of **one** run lands as one PR or as a stacked chain is a different question with a different answer time: it is decided after Phase 4, on the finished code, and it is yours (`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/stacked-prs.md`). A `/dev:build` that stayed one run is the likeliest thing in this pipeline to have a real seam — look for one before finalizing.

## Failure handling

|Situation|Action|
|-|-|
|An implementer subagent returns BLOCKED / NEEDS_CONTEXT|Handle per the Subagent Status table in pipeline Phase 3 — never force an unchanged retry.|
|Blast radius the plan didn't anticipate (> 5 packages, or shared code / schema / public-contract changes not covered by the spec)|Surface it per pipeline "Execution Autonomy" + `escalation-protocol.md`. Blast radius the plan already anticipated → proceed, don't re-confirm.|
|A novel, material problem the plan didn't settle mid-run (out-of-plan decision, "while I'm here" that isn't trivial/reversible, a new-feature finding)|Surface it per pipeline "Execution Autonomy" + `escalation-protocol.md` (problem + options + recommendation) — never warn-and-continue, never guess. In-boundary work stays autonomous.|
|Feature turns out even larger than one `/dev:build` can hold|Propose a split (section above) — ask before splitting.|
|Genuinely stuck after distinct attempts|Escalate WITH evidence (what you tried, the errors, your hypothesis) — a legal exit beats an improvised shortcut.|

## Red flags — STOP

Each of these has bitten this pipeline; the WHY is why it matters:

- **Designing the architecture once and refining it.** The first sketch anchors every later decision — run Design It Twice with divergent constraints so the alternatives are real, not variations on your first idea.
- **Picking a design silently.** The user chooses the architecture; you present the comparison + recommendation. Choosing for them buries a decision they wanted to make.
- **Manufacturing fake disagreement when the three designs converge.** Convergence is evidence the design is forced — present the consensus and say so; don't invent options to look thorough.
- **Starting implementation before spec AND plan approval.** Building before agreement produces thrown-away code — both gates loop until a whitelist phrase, and answered ambiguities are not approval.
- **Splitting a large build without asking.** The user may have a different seam in mind — propose the concrete split and let them decide.
- **Running a code review as a build step.** Review is on-request only; inserting it silently is not the pipeline's job.
- **Claiming done on scoped greens.** Scoped per-task checks never rebuild downstream consumers — only the full Phase 4 protocol proves the codebase is green.

## References

|File|Read when|
|-|-|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/SKILL.md`|ALWAYS — the phase mechanics, Blast Radius, Execution Autonomy, ADR format. This skill only holds the `/dev:build` deltas.|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/approval-gate.md`|At every spec/plan approval gate — before classifying ANY user reply.|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/socratic-protocol.md`|Before asking the user any ambiguity question.|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/escalation-protocol.md`|Mid-execution, when a novel material problem the plan didn't settle surfaces.|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/architecture-decision-gate.md`|Before significant architectural choices or any custom auth, storage, cryptography, or persistent infrastructure design.|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/test-requirements.md`|Writing per-task `**Must protect:**` entries and checking the acceptance criteria are covered by them.|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/stacked-prs.md`|After Phase 4, when the verified change has a dependency seam — cut it into a stacked chain of small PRs.|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/plan-reviewer-prompt.md`|Dispatching the enhanced (`/dev:build`-level) plan reviewer.|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/post-pipeline.md`|After Phase 4 passes — automatic commit/push/ready-for-review/changeset/tracker finalization.|
|The project's `verify` skill|Phase 4 — the authoritative full verification protocol.|
