# Escalation Protocol — the one legal mid-work stop

Canonical procedure for the single kind of interruption allowed during execution (Phase 3): a
*novel, material* problem the approved plan did not settle. Everything else stays autonomous.

Consumed by: pipeline, fix, task, feature, build, deliver, and any skill that reuses the protocol.

## Why this exists

The pipeline runs autonomously inside the approved plan — that is the point, and it is what keeps
the user out of babysitting and keeps token cost down (every mid-work round-trip re-injects the
whole accumulated context). But two failures sit on either side of that autonomy:

- **Babysitting** — stopping to ask about work the plan already anticipated, or about trivial,
  reversible choices. This trains the user to ignore you and wastes their attention.
- **Thin-air decisions** — silently picking an answer to a consequential question the plan never
  settled (which schema, which contract shape, a user-visible behavior). The user discovers the
  guess later, when it is expensive to unwind.

This protocol is the narrow path between them: stay silent on in-boundary and trivial work; stop
*only* for a genuinely new, material decision — and when you stop, hand the user a real choice, not
a guess dressed up as a question.

## When to invoke (and when not)

Invoke ONLY for an out-of-boundary discovery, as classified in the Execution Autonomy table in
`SKILL.md`:

- A material decision the approved plan did not settle (schema/contract/pattern to adopt, a
  user-visible behavior choice).
- A newly discovered problem: the real root cause is a design flaw; the fix now spans 3+ packages;
  a public contract must change; the requirements contradict each other.
- The discovery means the whole task is at the wrong altitude (offer an entry-point change among
  the options).

Do NOT invoke for: files/behaviors the plan anticipated, or out-of-plan work that is clearly in
service of the plan and low-risk/reversible (helper rename, import fix, obvious local refactor) —
proceed and record those for the end-of-run summary.

The test is **consequence and reversibility, not whether the exact file was listed.** Would a wrong
silent choice here be expensive to unwind, change a public contract, or surprise the user? If yes,
it is material — surface it. If it is mechanical and reversible, stay autonomous.

## The format (4 parts, in order)

Assume the user has not looked at the terminal in 20 minutes. The message must stand alone.

1. **Problem + evidence:** what new problem surfaced, and the concrete evidence — the file, the
   failing assumption, the contradiction. "While implementing Task 3 I found `X` at `[file:line]`
   assumes `Y`, but the plan's approach requires `Z`." Name why the approved plan did not cover it
   (it is genuinely new information, not a re-litigation of a settled decision).
2. **Impact:** what is blocked or at risk if this is decided wrong — blast radius, reversibility,
   who is affected. This is how the user weights the options.
3. **Options:** 2–3 concrete options (A, B, C) with trade-offs, so the user can reply with a
   letter. Include an entry-point change (`/dev:task`, `/dev:feature`, `/dev:build`) when the discovery means
   the task is at the wrong altitude. Do not pad with straw options — every option must be one you
   would actually be willing to execute.
4. **Recommendation:** which option you would take and why, with your confidence. "I lean B (80%)
   — it matches the existing pattern in `[file]` and stays inside the current blast radius."

Ask in the user's language (the language they are writing in).

Post the escalation as your final message and yield. Do the same on a **hard failure** the user must
resolve (verify or merge broke unrecoverably).

## While waiting: keep making progress

Escalating does not mean going idle. Continue any in-boundary work that does not depend on the
pending decision, and dispatch a background exploration subagent to map the options' downstream
impact — so when the answer arrives you can act immediately instead of starting cold. Do not start
work that depends on the decision; that is what you are waiting on.

## After the answer

The user's chosen option becomes part of the boundary — proceed autonomously from there; do not
re-ask to confirm the same decision. If the answer materially reshapes the plan (new tasks,
changed approach), update the plan artifact so the boundary stays accurate, then continue.

## This is not the approval gate

The approval gate (`approval-gate.md`) is the *upfront* whitelist-classified sign-off on the whole
spec/plan. This protocol is a *mid-execution* stop for a single new decision. They are different
tools: a chosen option here (a letter, a "do B") is not a spec/plan approval, and an approval is
not a standing licence to guess at material decisions the plan never mentioned.
