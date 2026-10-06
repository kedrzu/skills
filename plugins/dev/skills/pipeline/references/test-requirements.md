# Test Requirements (pipeline policy)

What a change must protect, and what is allowed to discharge it. **HOW** to write a high-signal test — harnesses, file patterns, runners, quality examples — is the project's: its testing skill (`testing` by convention) if it has one, otherwise its `CLAUDE.md`. Whether a test that already exists still earns its maintenance is decided by the **prune** skill (this plugin), using the criteria at the bottom of this file.

Consumed by: `pipeline` (`**Must protect:**` entries and the Phase 3.5 audit), `feature`, `build`, `fix`, the implementer prompt, and `prune`.

## The plan owns the obligation; the code owns the instrument

The plan says **what must still hold** after the change — this behaviour, this invariant, this sensitive-data path. What discharges it is chosen by whoever can see the code: a test at the boundary that owns the invariant, existing higher-level coverage that already catches the failure, or the type system.

That split exists because the older shape did not work. A list of test files written at plan time is a guess made at the moment of least information, and it then binds — so an implementer who found the planned test worthless was penalised for saying so. Naming the obligation makes *"no new test: the type makes this state unrepresentable, here it is"* a correct answer rather than a deviation, and it keeps the thing that actually matters — that the invariant is protected — in the plan where the user reads it.

Whatever the implementer names, it reports **per protection**, and Phase 3.5 opens that thing and checks it holds.

## Mandatory protections — the instrument is not free

**Security, privacy, authorization, compliance and data integrity** — and anything the project's `CLAUDE.md` names as non-negotiable. These carry a regulatory or data-loss consequence rather than a maintenance one, so they admit only a **durable test at the boundary that owns the invariant**, or existing boundary coverage that directly catches the proposed failure. Which boundary and what shape is the implementer's call; whether is not. A type is not an answer here.

Prefer one test at the owning boundary over per-call-site duplicates — including one captured-log assertion per caller. The invariant lives in one place; protect it there.

## Choosing the instrument, with the code in front of you

Match the changed code against the rows. A change may match several and then needs each one that carries an obligation.

|Code|Test|
|-|-|
|Pure logic (no IO, no dependencies)|Unit|
|Code with IO or dependencies (services, commands, endpoints)|Integration, against real infrastructure where the project's harness provides it|
|User-visible features, multi-step flows|End-to-end|
|Interactive UI components|Component test|
|Pure UI/template changes (no logic — see boundary below)|None required|
|Translations, codegen config|None required|

The project's testing skill maps each row onto its harness, file pattern and runner.

A new command, service or endpoint that carries an obligation gets its integration test at the behaviour-owning boundary; a new user flow that carries one gets an e2e test; interactive component behaviour that carries one gets a Storybook component test.

## The "no logic" boundary (when a UI change needs no test)

- **No test required:** the component has no logic of its own — only imports, declarations of its inputs and outputs, and pass-through of props and slots.
- **Component-test candidate:** conditional rendering driven by component state, a derived value, a watcher, a click/type/keyboard handler, focus management, or an emitted payload built inside the component.

## Defect classification

Classify the defect using `defect-classification.md`. Review discovery does not change the category. Only a production regression automatically carries the `regression` label.

## Red-first for production regressions

A production regression is reproduced **before** the fix: write the test, confirm it FAILS for the diagnosed reason, fix the code, confirm it PASSES. Red-first is an execution order, and it is the only way to know the test tests anything — a test born green proves nothing about the bug.

If the fix already exists, revert or stash it, confirm the test fails against the unfixed code, then restore the fix.

Test type matches the layer where the bug lives: a pure helper → unit; a command/service/endpoint → integration; a user-visible bug → e2e, plus a lower-level test only when it protects a distinct root-cause invariant.

Current-PR defects, greenfield capability gaps and historical defects in unshipped code use the normal policy above.

## What makes a test worth keeping

Read at **phase 3** (`prune`), which is the first point at which the test exists and can be read. These criteria are sound and were ineffective anyway, across two prior tasks and three retro findings, because they were applied at plan time: there you know what the code should do, not what it looks like or what already covers it.

For each test the change added:

1. What **realistic** production change would it catch? "Far-fetched but possible" is not an answer — a test that covers every conceivable case signals nothing about whether the code is correct.
2. Does another test already catch that?
3. Would types, or an already-tested central invariant, catch it instead?

A test that only locks down a literal description or label, a declaration, type-enforced structure, or an incidental implementation detail answers none of them and goes. So do duplicate and per-call-site negative tests when one test at the invariant-owning boundary protects the behaviour.

The mandatory protections above are the exception: their test at the owning boundary stays, whatever it looks like.

## References

- `defect-classification.md` — canonical defect categories and their regression-label and red-first consequences.
