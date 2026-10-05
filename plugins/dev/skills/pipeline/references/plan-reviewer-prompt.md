# Plan Reviewer Prompt Template

Dispatched once in Phase 2, before the approval gate. Fill in the placeholders.

**Pass the spec whole, or point at its path.** Never summarise it: the completeness check compares acceptance criteria against tasks, and a summary is exactly where the criterion nobody planned for disappears. Pointing at the file is fine — the subagent reads it and nothing is lost.

```
Agent tool (general-purpose):
  description: "Review implementation plan: [topic]"
  prompt: |
    You are reviewing an implementation plan before anyone writes code.

    ## The plan

    [FULL TEXT of the plan]

    ## The spec

    [FULL TEXT of the spec, or its path — .context/specs/<YYYY-MM-DD>-<topic>.md — or:
     "No spec. This is a /dev:task-level run; the user's request is quoted above."]

    ## Pipeline level

    [fix | task | feature | build]

    ## What to report

    Only what would make the implementation **wrong**, or make it **fail**. A plan is read once
    and then executed; anything that would merely have been arranged differently costs the reader
    more than it saves. Across 23 of these reviews there were 56 "minor" mentions; nobody has ever
    measured one changing a plan.

    What qualifies: a missing step the work cannot complete without (a migration, codegen, a
    translation file, wiring a new endpoint to the frontend); an ordering that puts a task before
    what it depends on; a task no single session can finish coherently; a pattern this repo does
    not use, where following the plan produces code that has to be redone; an acceptance criterion
    with no task implementing it.

    ### Attack the claims

    The plan opens with the claims it rests on, and that section is the only part you can actually
    check. Everything else is judgement — "this task is too large" cannot be disproved, which is
    why findings about it are worth so little.

    So take each claim and try to break it: open the `file:line` and read what is really there,
    follow the doc link, redo the arithmetic. **A claim whose evidence does not say what the plan
    says it says is the most valuable thing you can return**, because the plan was built on it. A
    claim that carries a decision and cites nothing is the same finding one step earlier.

    A claim the plan marks unverified is not a defect. The question there is whether the plan
    survives it being false.

    ### Protections, not tests

    Each task names what it must **protect** — a behaviour, an invariant, a sensitive-data path — and not
    which tests to write, because choosing the instrument needs the code and there is none yet.
    So the finding is a missing obligation, never a missing test file: a task touching security,
    privacy, authorization, compliance or data integrity with nothing in `Must protect:`
    naming it.

    ### For a /dev:build-level plan

    Architectural decisions asserted rather than surfaced with their trade-offs; tasks that go
    beyond the spec; tasks that depend on something outside our control.

    ## How to report

    One entry per finding: where in the plan, what breaks if it ships as written, and what to
    change. No severity labels — everything you are reporting breaks something, so a severity
    adds a word and no information.

    Report separately anything that is a **fork**: two workable approaches whose consequences
    differ, where you cannot tell which one the user wants. Name both and what each costs. A plan
    that designs custom authentication, storage, cryptography or persistent infrastructure without
    his explicit approval is always a fork — see
    `${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/architecture-decision-gate.md`.

    Finding nothing is a normal outcome. Say so and stop.
```

## What the orchestrator does with the result

Everything that is not a fork is **applied to the plan**. The user sees the plan once, at the gate, already corrected — a proven, blocking finding needs a fix, not his decision, and routing it through him spends the attention this phase exists to save.

A fork goes to him **immediately**, in a sentence or two with both options named — not into the plan document for him to discover while reading it.
