# Socratic Protocol

Canonical procedure for resolving ambiguities that surface during any pipeline phase — explore first, resolve everything the codebase answers, then batch the genuine remainder into ONE upfront round.

Consumed by: pipeline, task, feature, build, and any skill that reuses the protocol.

## Gate 1: Codebase-first (explore before asking)

Most "ambiguities" are answered by the code. If the question is about current system behavior, existing conventions, or how similar things are already done — explore and resolve it autonomously. Asking the user something the codebase answers wastes their attention and trains them to ignore your questions.

- Search for existing patterns, conventions, similar implementations in the same domain
- If found: resolve autonomously and note the code reference in the artifact (spec/plan: under "What We Already Know" or equivalent)
- Example: "How should auth work for this endpoint?" → read existing endpoints in the same domain first (e.g. `src/chat/UnreadChatsEndpoint.ts` calls `requireStaff()`)

Only questions the codebase genuinely cannot answer — user intent, product decisions, trade-offs between valid options — pass this gate.

## Gate 2: Batch the genuine remainder into ONE upfront round

After the codebase-first gate, only real gaps remain — user intent, product decisions, trade-offs between valid options. Ask them **together, once**, before work starts, rather than dripping them out one at a time across the session. The drip is its own form of babysitting: it turns one decision point into many, and each round-trip re-injects the whole accumulated context (the dominant token cost). One upfront round lets the user answer everything in a single sitting and then step away while the agent runs autonomously.

Batching only works if each question stands on its own — otherwise multiple questions get partial answers and anchor the user toward whatever you listed first. So:

- Give every question its own full 4-part treatment (below): re-ground, simplify, recommend, options. A batched question is not a terse list — it is several well-formed standalone questions presented together.
- Ask only what genuinely needs the user. If exploration can still answer it, answer it — do not pad the batch.
- Number them so the user can reply per-item ("1: B, 2: A, 3: your call").

Once answered, move on — don't re-ask or over-clarify. If an answer opens a genuinely new gap that could not have been foreseen, it is fine to ask a short follow-up round — but the goal is one round, not a running dialogue.

Ask in the user's language (the language they are writing in). Socratic dialogue is natural conversation — a question in a foreign language adds friction exactly when you need a considered answer.

## Question format (4 parts, in order)

Assume the user hasn't looked at the terminal in 20 minutes. Every question must stand alone with enough context to answer without scrolling up.

1. **Re-ground:** Remind them where you are and what you found. "I'm in Phase 2 (Plan) for [feature]. While reviewing the plan, I found an ambiguity about [topic]. Currently the code does X via `[file:line]`."
2. **Simplify:** State the question in plain terms — the user may have context-switched away.
3. **Recommend:** State your recommendation with reasoning and how the answer changes direction. "I'm 80% confident Option A is correct based on existing patterns in `[file]`."
4. **Options:** Provide lettered options (A, B, C) with trade-offs, so the user can respond with just a letter.

## While waiting: background exploration

While the user considers the question, dispatch an exploration subagent in the background to map related code areas, find similar patterns, and identify downstream impacts. When the answer arrives, you already have the context to incorporate it instead of starting cold.

## Answered questions are NOT approval

Ambiguity resolution resolves specific gaps in the spec or plan. The approval loop at the end of each phase is where the user reviews the *complete artifact* and confirms it is ready. These are separate steps — never skip the approval loop because ambiguities were resolved, and never treat an ambiguity answer ("A", "yes, use the same pattern") as approval of the artifact.

This file is deliberately separate from the approval gate: conflating "questions answered" with "artifact approved" is the exact failure mode being prevented. Feedback is never approval — run the gate exactly as written in `approval-gate.md`.
