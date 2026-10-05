# Approval Gate — canonical whitelist and loop

Single source of truth for classifying a user's reply to a presented artifact (spec, plan, findings) as approval or feedback, and for running the approval loop.

Consumed by: pipeline, task, feature, build, and any skill that reuses the protocol.

## Why this gate is strict

Models under pressure rationalize approval: after a few revision rounds, "ok sure" starts to feel like a green light — because proceeding is what the model wants to do. A closed verbatim list removes the judgment call entirely: there is nothing to weigh, only a string to match. Do not soften it; softer versions of this gate got talked past in practice.

## Approval whitelist (closed list — ONLY these count)

The user's message counts as approval only when its entire intent is one of these phrases:

- "looks good"
- "lgtm"
- "let's go"
- "approved"
- "proceed"
- "ship it"
- "go ahead"
- "yes, proceed"
- "ready to implement"
- "start implementing"
- "yes" (standalone — not as part of a longer sentence with feedback)
- "start" (standalone)
- "ready" (standalone)
- "go" (standalone)

Matching rules — the ONLY allowed flexibility:

- Case and punctuation don't matter ("LGTM!", "Looks good." match).
- The phrase must be the whole intent of the message. If the message also carries a question, suggestion, or qualification, it is feedback — "looks good but rename X" is feedback, not approval.
- No other "close variations". If you catch yourself reasoning about whether something is "basically approval", it is not on the list → it is feedback.

**Action on match:** the artifact is approved — move to the next phase.

## Everything else is feedback — no exceptions

The default classification for ANY user message is feedback. There is no "unclear" category: not on the whitelist → feedback. Period. Examples that are ALL feedback:

- Suggestions: "I think we should also...", "can we add...", "what about..."
- Questions: "how will this handle Y?", "why not Z?"
- Concerns: "hmm", "I'm not sure about...", "but what about..."
- Qualified approval: "ok but...", "sure, but one thing...", "looks good but..."
- Commentary / mild positives: "ok", "sure", "nice", "makes sense", "interesting"
- Lukewarm agreement: "ok sure", "sounds good I guess"
- Enthusiastic paraphrase — restating the artifact approvingly is not saying "proceed"
- Single-word acknowledgments without explicit proceed language

**Action on feedback:** revise the artifact, re-present it in FULL, re-ask for approval (loop below). Do NOT proceed.

## Answering ambiguity questions is NOT approval

This is the documented failure mode: you ask Socratic/ambiguity questions, the user answers them, every open question is resolved — and it FEELS like the artifact is approved. It is not. Answering questions fills specific gaps in the artifact; approval is the user reviewing the COMPLETE artifact and replying with a whitelist phrase. These are separate steps. After the last ambiguity is resolved, you still present the full artifact and run the loop below.

## The approval loop

1. **Present the FULL artifact** — the complete spec/plan/findings, not a summary. On revisions, additionally note what changed since the last round.
2. **Ask for explicit approval** — e.g. "Is this [artifact] complete and ready to proceed? If you have feedback, I'll revise and re-present." This is a hard stop — word it as one, so the user can tell at a glance that the run is waiting on them rather than still working.
3. **Classify the response** using the whitelist above:
   - Whitelist match → approved. Exit the loop; move to the next phase.
   - Anything else → feedback. Continue to step 4.
4. **Revise** the artifact based on the feedback. If the consuming skill has a reviewer/finder subagent step and the feedback changes scope or structure, re-run it.
5. **Go back to step 1** — re-present the FULL revised artifact (not a diff) and re-ask. The user may have new feedback after seeing the revision.

## Critical rules

- **Default is feedback.** When unsure whether a message is approval or feedback, it is feedback. Always.
- **Feedback is never implicit approval.** Even a tiny fix request ("just change X") means: revise → re-present in full → re-ask. Never combine a revision with proceeding to the next phase.
- **Multiple rounds are normal.** The user is refining the artifact — let them. Do not show impatience or rush toward approval.
- **The loop exits only on a whitelist match.** No exceptions, no shortcuts, no inferring intent.
