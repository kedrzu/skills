---
name: pipeline
description: >-
    The engine behind the dev pipeline entry points (/dev:fix, /dev:task, /dev:feature,
    /dev:build, /dev:deliver): phases, approval gate, implementer dispatch, plan completion
    audit, finalization, and the project contracts (`verify`, `git-workflow`) it relies on.
    Load it when an entry point tells you to, or when another skill reuses one of its
    protocols — the approval gate, the Socratic protocol, the escalation protocol, the test
    requirements, stacked PRs. Not an entry point: with work to do and no entry point chosen,
    ask which one. Do NOT use for standalone verification (the project's verify skill) or
    code review (`/dev:review`, on explicit user request only, never a pipeline step).
user-invocable: false
---

# Dev Pipeline Orchestrator

## Purpose

The engine behind `/dev:fix`, `/dev:task`, `/dev:feature`, `/dev:build`, `/dev:deliver`. Manages phases (spec → plan → execute → prune → audit → verify), enforces approval gates, dispatches implementer subagents, audits plan completion, and finalizes with commit → push → ready-for-review → changeset → tracker comment.

**Not an entry point.** Loaded with no entry point chosen, ask which one the user intended. Entry skills do their own announcing — this skill adds none.

## When NOT to use

- Code review → NEVER a pipeline step. `/dev:review` is on-request only: run it when the user explicitly asks for a review, and at no other time.
- Standalone "verify / make it green" work → the project's `verify` skill.
- Researched answers without implementation → a research skill, if the project has one.

## Project contracts

Everything this pipeline knows is project-independent. Two things it takes from the project, through
skills with fixed names in the project's `.claude/skills/`: **`verify`** (how a change is proven to
work — a scoped check and the full protocol) and **`git-workflow`** (how a change moves — commit,
push, ready for review, PR description, tracker comment, stacks, landing). What each must provide,
and what to do when one is missing, is `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/contracts.md`
— read it before the first use of either. A missing contract stops the run; `/dev:setup` writes it.

Project rules the pipeline defers to live in the project's `CLAUDE.md`: what counts as shared code,
which obligations (privacy, compliance, …) are non-negotiable, where ADRs go, how prose is written.

## Phase Matrix

|Entry point|Spec|Plan|Execute|Verify|
|-|-|-|-|-|
|`/dev:fix`|-|-|yes|yes|
|`/dev:task`|-|yes|yes|yes|
|`/dev:feature`|yes|yes|yes|yes|
|`/dev:build`|yes|yes (deep)|yes|yes|
|`/dev:deliver`|- (the design is the spec)|overview + per-milestone plans|per milestone|scoped per milestone, full once|

Phases run in order for the entry point's level. Spec and Plan each end in an approval gate that loops (present FULL artifact → classify reply → revise → re-present) until the user's reply matches the approval whitelist. Feedback is never approval — run the gate exactly as written in `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/approval-gate.md`.

## Planning is a conversation, not a document handover

The artifact must never be the medium through which the user learns what was decided. By the time you present it, it should hold no news, and the gate is then a minute's skim rather than a 400-line read hunting for the decisions taken without him.

So a decision surfaces **when it arises**, not when the document is finished: one or two sentences, the fork named, an option recommended — the register of an ordinary conversation. The split that matters is **correction versus fork**, not severity:

- A **correction** — a missing step, the wrong pattern, a claim that does not hold — is applied silently. Reporting it costs attention and changes nothing.
- A **fork** — two workable approaches whose consequences differ — is asked immediately, and never batched into a document read afterwards.

What this conserves is not the number of questions. Questions during planning are cheap and welcome; discovering a decision buried in a finished plan is what is expensive. The quantity to keep down is **surprise density** — decisions per page the user is seeing for the first time. A long plan he agreed to piece by piece is cheap to skim; a short one hiding one unseen decision is worse.

---

## Phase 1: Spec (`/dev:feature`, `/dev:build`)

**Purpose:** surface ambiguities and define scope before any code is written.

1. **Explore relevant code** — read files, understand existing patterns, map the area being changed.
2. **Write spec** to `.context/specs/<YYYY-MM-DD>-<topic>.md` using the format below.
3. **Dispatch ambiguity finder subagent** using `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/ambiguity-finder-prompt.md` — it flags gaps, edge cases, and missing constraints, and classifies each as codebase-answerable or needs-user.
4. **Resolve ambiguities:**
   - Codebase-answerable → update the spec with the answer and the code reference.
   - Genuinely ambiguous → explore first, then batch the remaining genuine questions into one upfront round, following `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/socratic-protocol.md` (codebase-first gate, 4-part question format, background exploration while waiting).
5. **Triage finder output** — apply what the spec is missing. A gap is a correction: fix it silently. Only a genuine fork — two readings of what he asked for, with materially different consequences — goes to him, and it goes when it arises, not batched into the gate.
6. **Approval gate** — present the FULL spec and ask for explicit approval. Answering ambiguity questions is NOT approval, and any reply that is not a whitelist phrase is feedback (revise → re-present → re-ask). Classify and loop exactly as written in `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/approval-gate.md`. Only a whitelist match moves to Phase 2.

### Spec Format

```markdown
# [Feature Name]

## Problem

One paragraph — what's broken or missing.

## Scope

What's IN and what's explicitly OUT.

## Constraints

Tech constraints, UX requirements, integration points.

## Acceptance Criteria

3-7 bullets — how you'll know it's done.
```

### Durability Rule

Specs are durable artifacts — they must still make sense if the codebase is restructured.

- Acceptance criteria reference behaviors, not file paths.
- Use domain language ("only authenticated staff can read the unread-chats feed"), not implementation details ("`ChatUnreadListEndpointHandler.ts` calls `staffAuth()`").
- File paths belong in the plan, not the spec.

---

## Phase 2: Plan (`/dev:task`, `/dev:feature`, `/dev:build`)

**Purpose:** break work into ordered, atomic implementation tasks.

1. **Read the spec** (or the user request for `/dev:task`) + explore relevant code.
2. **Check memory** — search project memory for learnings about the affected files, patterns, or domain from past runs; fold relevant ones into planning context.
3. **Surface durable architectural decisions first** — routes, schema shapes, key models, auth approach, service boundaries. They go into the plan's "Durable Decisions" section; individual tasks reference them instead of re-deriving them (re-derivation is how two tasks silently pick two different schemas).
4. **Write plan** to `.context/plans/<YYYY-MM-DD>-<topic>.md` using the format below, tasks ordered by dependency. It opens with the claims it rests on, and each task names what it must protect — both below.
5. **Classify each task HITL vs AFK** — HITL (human-in-the-loop): user input likely mid-execution (ambiguous requirements, design choices, sensitive code). AFK: clear spec, established pattern, low risk. Mark it in the task's `**Mode:**` field so the user can kick off AFK tasks and step away.
6. **Dispatch plan reviewer subagent** using `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/plan-reviewer-prompt.md` — it reports only what would make the implementation wrong or fail, and it can attack the claims the plan declared.
7. **Resolve ambiguities** — same as Phase 1: codebase-first, then batch the remaining genuine questions into one upfront round per `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/socratic-protocol.md`.
8. **Apply the reviewer's findings to the plan** — corrections silently, so the user sees the plan once and already corrected; a finding that is a fork ("this cannot work without changing the schema") goes to him now, in a sentence or two.
9. **Approval gate** — present the FULL plan and ask for explicit approval. Ambiguity answers and feedback are NOT approval; loop exactly as written in `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/approval-gate.md`. Only a whitelist match moves on.
10. **After approval: create the task list** (TaskCreate) — one tracked task per plan task, so execution progress is visible.
11. **Create ADRs** if genuine architectural decisions were made → `docs/decisions/<title-slug>.md`, or wherever the project's `CLAUDE.md` keeps them (format below). **No number** — parallel agents in separate worktrees each take the next free one and all take the same one. The slug cannot collide.

### Plan on evidence

A plan can only be judged on whether its premises hold, so state them. **The plan opens with the claims it rests on — only those that, if false, would change the plan.** That bar keeps the section short: a research dump fails it, and so does a fact nothing depends on. It also makes the plan refutable, which is the one thing a reviewer can do to a plan that it cannot do to an intuition.

A claim that carries a decision carries its evidence, and what evidence looks like depends on where it came from:

|Source|Evidence|
|-|-|
|Code|`file:line`, and what it actually says|
|External service, API, version|the primary documentation, the date you read it, the sentence that matters|
|Measurement|the command and its output, or the arithmetic with its inputs visible|
|History|which sessions or PRs, how many, over what window|

Evidence belongs where something was actually checked — not as a field beside every sentence. A bare claim standing without it is useful information; dressing them all up destroys that signal.

**A guess cannot be a criterion.** Guessing is fine, calling it a guess is required, and no decision may rest on one. A negative result counts equally: "checked, does not exist" saves the next reader the same hour as "checked, works".

A claim is in one of three states, and the third is a legitimate answer:

1. **Verified** — evidence attached.
2. **Checkable but unchecked** — say so. If a decision rests on it, check it before deciding: usually one documentation page, sometimes a small experiment run purely to settle the question.
3. **Genuinely unverifiable now** — say so explicitly. Then either the plan survives the claim being false, or the decision waits until it can be checked.

Effort scales with what rests on the claim: one that decides the architecture earns an experiment, one that decides a variable name earns nothing. The canonical miss is an audit architecture designed on AWS CloudTrail Lake, which had already closed to new customers — state 2 treated as state 1, one unread page, and the architecture had to be refactored back.

### What each task must protect

`**Must protect:**` states the obligation — this behaviour, this invariant, this sensitive-data path. **What discharges it is chosen by whoever can see the code**: an integration test at the owning boundary, existing higher-level coverage, or the type system. That decision needs the code in view, and at plan time there is none.

This replaced a per-task list of test files, which was a guess made at the moment of least information and then binding: an implementer who discovered the planned test was worthless got penalised for the honest answer. Naming the obligation instead makes "I did not write that test because the types catch it, here is the type" a correct answer rather than a deviation.

Security, privacy, authorization, compliance and data integrity — and anything the project's `CLAUDE.md` names as non-negotiable — are obligations wherever the change touches them — and there the instrument is not free: a durable test at the boundary that owns the invariant. Which boundary and what shape is the implementer's call; whether is not.

Phase 3.5 opens whatever the implementer named and checks it holds.

### Plan Format

```markdown
## Claims

The facts this plan rests on — only those that, if false, would change it.

- [claim] — [evidence: `file:line` / doc + date / command + output / which PRs, how many]
- [claim] — **unverified**: [why it could not be checked, and what happens if it is false]

## Durable Architectural Decisions

Decisions that apply across all tasks and are unlikely to change:

- **Routes**: [route patterns, URL structure]
- **Schema**: [database schema decisions, new tables/columns]
- **Key models**: [core types, domain objects]
- **Auth approach**: [access control patterns for this feature]
- **Service boundaries**: [which packages own what]

(Only include sections that apply. Skip sections where the codebase already dictates the answer.)

### Task N: [Name]

**Files:** create/modify file paths
**Must protect:** one line per obligation — the behaviour, invariant or sensitive-data path that must still hold after this task. Omit the field when the task genuinely carries none (a translation file, a codegen config).
**Approach:** 2-3 sentences describing implementation strategy
**Risks:** any blockers or concerns (omit this field entirely when the task has none)
**References:** durable decisions this task relies on (omit this field entirely when there are none)
**Mode:** HITL | AFK
```

**Which fields are required.** `Files`, `Approach` and `Mode` always appear, because something downstream breaks without them: Phase 2 step 5 and AFK dispatch read `Mode`, and `Files` + `Approach` *are* the task text injected into the implementer. `Must protect` appears whenever the task has an obligation, and Phase 3.5 checks each entry. `Risks` and `References` have no consumer — omit them when the task has neither, instead of emitting a header with nothing under it. **`## Claims` follows the same rule**: it holds only facts that would change the plan if false, so a plan resting on none omits the section rather than padding it — which is the research dump it exists to prevent.

The project's writing rules (`CLAUDE.md`), if it has them, govern the prose inside every field — and being required never licenses length.

### ADR Format (only for genuine architectural choices)

```markdown
# [Title]

## Status

Accepted

## Context

What problem were we solving? What constraints existed?

Any fact that carries the decision — a cost, a limit, what a service can do, what the code actually
does — carries its evidence, dated:

> **Checked 2026-08-04:** CloudTrail Lake is closed to new customers — [AWS](https://docs.aws.amazon.com/…).

A negative result counts the same: "checked, does not exist" saves the next reader the same hour.
An unchecked claim says so; a guess cannot be a criterion.

## Options Considered

- **Option A:** [1-2 sentences]. Trade-off: [...]
- **Option B:** [1-2 sentences]. Trade-off: [...]

## Decision

We chose Option B because [reasons].

## Consequences

What we gained. What we accepted as downsides.
```

---

## Phase 3: Execute (all levels)

**Purpose:** implement each task from the plan.

Per-task flow — strictly sequential, ONE implementer at a time:

1. Dispatch the implementer subagent (below).
2. Handle its status (table below).
3. Run scoped verification → green.
4. Run `prune` over that task's change, then scoped verification again → green (below).
5. Mark the task complete → next task (after the last task → Phase 3.5).

Implement the whole change on this one branch. Whether it eventually lands as one PR or as a chain of stacked ones is decided after Phase 4, with the finished code in view — nothing here is per-node.

There is NO review step in this flow. Code review runs only when the user explicitly requests it — never insert one.

### Implementation Dispatch

Dispatch one implementer per task using `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/implementer-prompt.md`, filled with the full task text (never make the subagent read the plan file — file reads waste its context and can fail; injected text is reliable) and scene-setting context: where this fits, what came before, what it depends on.

**Nothing is injected.** The implementer has the `Skill` tool and can see the skill list, so it opens the skills governing the files it is about to touch, choosing them by their descriptions. A signal→skill table maintained here would be a second, worse copy of those descriptions, and it goes stale the moment a skill's scope moves. Skills the project's `CLAUDE.md` says apply to all code are named in the prompt — names, not a mechanism.

### Prune, inside each task

Once the scoped check is green, run the `prune` skill over that task's change, then run the scoped check again. Tell it **the files the implementer changed** and that this is an **implementation run** — it scopes itself to what the caller names, and it prunes signal-free tests only when it knows which kind of run this is. Told neither, it leaves the tests alone, and the one phase chartered to remove a worthless test never gets the chance.

The green→prune→green sandwich is what makes its output attributable: nothing else touched the tree, so a red on the second check is prune's, and since it may not add anything, the remedy is usually to put the deletion back. Do not run the full verify here — that runs once, in Phase 4, and doubling the expensive gate is what this placement exists to avoid.

Prune hands back what it removed, plus anything it found and may not fix (an extraction is new code, so it is not its to make). Carry both into the Phase 3.5 report — a deletion that took out something a `Must protect` entry relied on is exactly what the audit is placed after prune to catch.

### Subagent Status Handling

|Status|Action|
|-|-|
|**DONE**|Take it at face value here. Whether each `**Must protect:**` entry is really discharged is Phase 3.5's question, asked by opening the thing the report names — asking it twice, once on the report and once on the code, is the double enforcement this design removed.|
|**DONE_WITH_CONCERNS**|Read the concerns. Correctness/scope concerns → address now. Pure observations → note and proceed.|
|**NEEDS_CONTEXT**|Provide the missing information and re-dispatch the same subagent.|
|**BLOCKED**|1. Context problem → provide more context, re-dispatch. 2. Needs more reasoning → re-dispatch with a more capable model. 3. Task too large → split it. 4. Plan is wrong → escalate per `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/escalation-protocol.md` (problem + options).|

**Never** ignore an escalation or force a retry without changing something — an unchanged retry reproduces the same failure and burns a dispatch.

### Per-Task Verification

Both scoped runs — before and after prune — are the `verify` skill's **scoped** mode. Fix every scoped failure before starting the next task; errors left behind compound and get misattributed to later changes, which is also why the first run has to be green before prune touches anything. A green scoped run is NOT evidence of a green codebase; the full protocol still runs once, in Phase 4.

### `/dev:fix` Level

No plan file, so nothing states the obligations in advance — but the mandatory categories bind wherever the fix touches them (`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/test-requirements.md`), and a production regression is reproduced red-first. Implement, run scoped verification, run `prune` as an implementation run over the changed files, run scoped verification again, then continue to Phase 4.

---

## Phase 3.5: Plan Completion Audit (`/dev:task`, `/dev:feature`, `/dev:build`)

**Purpose:** every plan task implemented, and every `**Must protect:**` entry discharged by something that exists and does the job. The gap between "implementer said DONE" and actually done is where bugs hide — do NOT skip this step.

It runs after the last task's prune and before the full verify. That placement is free and buys a safety property: if prune removed a test that was discharging a protection, this is what notices, while putting it back still costs nothing.

1. Re-read the plan from `.context/plans/`.
2. Classify each task:
   - **DONE** — fully implemented, evidence in code
   - **PARTIAL** — started but incomplete (document what's missing)
   - **NOT DONE** — not implemented at all
   - **CHANGED** — implemented differently than planned (document why)
3. **Check the claims still hold.** The implementer reports any `## Claims` entry it found untrue —
   the cited line moved, the file now does the opposite. A plan approved on Monday can rest on a fact
   two sibling merges falsified by Thursday, and the implementer is the first party to open those
   files. A falsified claim that changed nothing is worth a line; one that undoes the plan is a fork
   and goes to him now.
4. **Audit the obligations, not a list.** For each `**Must protect:**` entry the implementer named what discharges it. Open that thing — the test file, the existing coverage, the type — and check it exists and actually holds the invariant. Security, privacy, authorization, compliance and data integrity admit only a test or existing coverage; a type is not an answer there. Anything undischarged makes the task PARTIAL.
5. An unfinished task or an undischarged protection is a **correction the pipeline finishes**, not news for the user: investigate why (cut? blocked? absorbed elsewhere?), fix it, re-audit. Escalate only when finishing it needs a decision the plan did not settle — then it is a fork, and it goes out per `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/escalation-protocol.md`.
6. Present the summary:

   ```
   COMPLETION: N/M DONE, X PARTIAL, Y NOT DONE, Z CHANGED
   ```

   Then the notable **in-boundary decisions made autonomously** during execution (helper extractions, local refactors, out-of-plan-but-in-service edits) and **what prune removed**, including anything it flagged and could not fix. This is the end-of-run visibility that replaces mid-work check-ins, and the removals are the only record that the branch no longer contains what an earlier phase put there.

---

## Phase 4: Verify (all levels)

Invoke the `verify` skill and run its **full** protocol exactly as written there — it is the single authoritative step list. Fix every error before claiming completion; every error is your error until proven otherwise.

### Final Spec Compliance Check (`/dev:feature`, `/dev:build` only)

After verification passes, dispatch a **fresh-context compliance subagent**:

- Input: the original spec + the current code/diff — no session history (fresh eyes are the point: it must judge the code, not your narrative of the code).
- Output: a per-acceptance-criterion pass/fail table.
- Any FAIL → fix it and re-run verification.

---

## Blast Radius Check (before Phase 3 — every level, including `/dev:fix`)

Assess scope before executing, and fold the result into the plan boundary:

- **How many files/packages does this touch?** >5 packages → the work may need splitting.
- **Does it change shared code?** Code with many consumers — the packages the project's `CLAUDE.md` names as shared, a vendored framework — run downstream tests early.
- **Does it change database schema?** Needs a migration plan.
- **Does it change public contracts?** Exported interfaces, API schemas, anything other code is compiled or deployed against — verify all callers.

If the blast radius matches what the approved plan/spec anticipated, proceed — do not re-confirm it. If execution reveals a blast radius the plan did NOT anticipate (a schema change that wasn't in the spec, a fix that fans out across packages), that is an out-of-boundary discovery → escalate per the Execution Autonomy rules below.

## Execution Autonomy (during Phase 3)

The approved plan (for `/dev:fix`, the approved diagnosis) is the **decision boundary**. Inside it, execute to completion autonomously — do not stop to report in-boundary progress or to ask the user to bless work the plan already anticipated. This is deliberate on two fronts: it removes babysitting, and every mid-work round-trip re-injects the whole accumulated context, the single largest token cost in a run.

The **only** legal mid-work stop is a *novel, material* problem the approved plan did not settle. When you hit one, do NOT invent an answer from thin air and do NOT silently expand scope — surface it exactly as written in `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/escalation-protocol.md` (problem + evidence + 2–3 options + recommendation) and let the user choose. `/dev:deliver` adds one planned stop, the milestone checkpoint its approved overview names — a stop he agreed to in advance, not a surprise.

Classify every mid-work discovery:

|Discovery|Bucket|Action|
|-|-|-|
|Files/behaviors the plan anticipated|In-boundary|Proceed silently|
|Out-of-plan but clearly in service of the plan, low-risk and reversible (helper rename, import fix, obvious local refactor)|In-boundary|Proceed; note it for the end-of-run summary|
|A material decision the plan did not settle (which schema/contract/pattern to adopt, a user-visible behavior choice)|Out-of-boundary|STOP — escalate with options|
|A newly discovered problem (design flaw is the real root cause; fix now spans 3+ packages; a public contract must change; requirements contradict)|Out-of-boundary|STOP — escalate with options|
|A finding that is a new feature, not needed for the plan|Out-of-boundary|Record for the user; never auto-implement|

The test for "material" is **consequence and reversibility, not whether the exact file was listed**: would a wrong silent choice be expensive to unwind, change a public contract, or surprise the user? If yes → out-of-boundary, surface it. If it is mechanical and reversible → stay autonomous. This is what keeps the agent from both babysitting (stopping for trivia) and inventing consequential decisions from thin air.

When a discovered problem means the whole task is at the wrong altitude, include an entry-point change among the options you present:

|Current|Discovery|Option to offer|
|-|-|-|
|`/dev:fix`|Touches 3+ packages (excluding tests), changes a public contract, or root cause is a design flaw|Upgrade to `/dev:task` (or `/dev:feature` if it needs a spec)|
|`/dev:task`|Needs >8 tasks or surfaces architectural trade-offs|Upgrade to `/dev:feature`|
|`/dev:feature`|Spans multiple independent subsystems or introduces new patterns|Upgrade to `/dev:build`, or split into separate `/dev:feature` runs|
|`/dev:build`|Too large for a single pipeline run|Split into independent sub-features|

## Model Selection

Every subagent dispatch (implementer, plan reviewer, ambiguity finder, spec-compliance check,
explorer) picks its provider, model tier, and effort by the role: **use the least capable model that
reliably handles the role, escalate on a real signal (BLOCKED / thin output), and never drop below
sonnet-class for shared-code or public-contract work.** Where the project states its own model-selection
rules (`CLAUDE.md` or a skill), those win.

## Artifact Management

- **Ephemeral** (`.context/`, gitignored): `.context/specs/<YYYY-MM-DD>-<topic>.md` (Phase 1), `.context/plans/<YYYY-MM-DD>-<topic>.md` (Phase 2).
- **Permanent** (committed): `docs/decisions/<title-slug>.md` (or the project's ADR location) — ADRs, only when a decision chooses between viable approaches, deviates from or introduces patterns, or has trade-offs worth documenting.

---

## Post-Pipeline (after Phase 4 passes)

1. **Save learnings to memory** — before presenting results, save to project memory any non-obvious insights this run surfaced: pitfalls discovered, undocumented codebase patterns, debugging approaches that worked, domain knowledge learned from the user. Do NOT save things already in CLAUDE.md or domain skills, or anything derivable from code — memory is for what a fresh session could not rediscover.
2. **Decide whether this lands as one PR or a chain.** The verified code is in front of you, which is the only moment the seams are knowable — a layout guessed at plan time is what this replaced. A change with a natural seam is cut into an ordered chain of 2–5 dependent PRs per `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/stacked-prs.md` (commit, cut, push the nodes bottom-up, report the shape); no seam, or a project whose `git-workflow` does not support stacks → one PR, which stays the common case. `/dev:fix` is always one PR.
3. **Run the finalization flow** exactly as written in `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/post-pipeline.md` (commit → push → ready-for-review → PR changeset → tracker comment → confirm → completion options), each command from `git-workflow`. It runs automatically — invoking the pipeline was the user's authorization to commit, push, mark ready and log; do not pause to ask. It ends by presenting the completion options (Create PR / Keep working / Discard).
4. **Consider follow-ups** (one line each, only if applicable): domain skill/doc updates for new patterns; new env variables needed in deployment; migrations to run in staging/production; security review for new dependencies.

---

## Red Flags

**Never:**

- Dispatch implementation subagents in parallel — parallel implementers create merge conflicts and inconsistent patterns; sequential is slower but correct.
- Make subagents read plan files — inject the full task text; file reads waste the subagent's context and can fail, injected text is reliable.
- Skip per-task scoped verification — a regression caught in task 3 is cheap; the same regression found in Phase 4 after five more tasks is expensive to bisect.
- Claim work is done without the full Phase 4 protocol — scoped greens do not compose into a green codebase (scoped builds never rebuild downstream consumers).
- Suppress errors, skip tests, or disable lint rules — every suppression is debt someone else pays; if a rule seems wrong, escalate instead.
- Start implementation before spec/plan approval (when those phases apply) — building before agreement produces thrown-away code.
- Treat ambiguity answers, feedback, or lukewarm positives as approval — the gate exits only on a whitelist match; classify every reply exactly as written in `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/approval-gate.md`.
- Run a code review as a pipeline step — `/dev:review` is on-request only; the user asks for it explicitly or it does not happen.
- Invent an answer from thin air to a material decision the approved plan did not settle — no silent scope expansion, no guessed schema/contract/behavior. Surface it per `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/escalation-protocol.md` (problem + options). Equally: do NOT stop for in-boundary trivia — babysitting and thin-air decisions are the two failures this rule sits between.

**If stuck:** describe the issue clearly, show what you tried, ask the user for guidance. A legal exit beats an improvised shortcut.

---

## References

|File|Read when|
|-|-|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/contracts.md`|Before the first use of `verify` or `git-workflow` in a run|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/approval-gate.md`|At every spec/plan approval gate — before classifying ANY user reply|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/socratic-protocol.md`|Before asking the user any ambiguity question|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/escalation-protocol.md`|Mid-execution, when a novel material problem the plan didn't settle surfaces|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/test-requirements.md`|Writing `**Must protect:**` entries; choosing what discharges one; auditing them in Phase 3.5|
|`prune` skill (this plugin)|Phase 3, after each task's scoped check is green|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/stacked-prs.md`|After Phase 4, when the verified change has a natural seam and you cut it into a chain of small PRs|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/post-pipeline.md`|After Phase 4 passes — commit/push/ready-for-review/changeset/tracker finalization|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/ambiguity-finder-prompt.md`|Dispatching the Phase 1 ambiguity finder|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/plan-reviewer-prompt.md`|Dispatching the Phase 2 plan reviewer|
|`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/implementer-prompt.md`|Dispatching any Phase 3 implementer|
|`verify` skill (the project's)|Per-task scoped checks (Phase 3) and the full protocol (Phase 4)|
|`git-workflow` skill (the project's)|Every commit, push, PR and tracker operation|
