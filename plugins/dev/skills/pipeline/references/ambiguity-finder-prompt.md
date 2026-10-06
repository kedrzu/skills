# Ambiguity Finder Prompt Template

Use this template when dispatching the ambiguity finder subagent during spec or plan review.

```
Agent tool (general-purpose):
  description: "Find ambiguities in spec: [topic]"
  prompt: |
    You are reviewing a spec for ambiguities, gaps, and undefined edge cases.

    ## The Spec

    [FULL TEXT of the spec]

    ## Relevant Codebase Context

    [Key files, patterns, and architectural context relevant to this spec.
    Include enough for the subagent to answer codebase-answerable questions.]

    ## Your Job

    Read the spec carefully. For each ambiguity you find:

    ### Step 1: Can the codebase answer this?

    Search the provided context (and explore the codebase if needed) for:
    - Existing patterns that answer the question
    - Similar implementations that set precedent
    - Constraints implied by the current architecture

    If YES → resolve it yourself:
    - State the ambiguity
    - State the answer with code reference (file:line)
    - Classify as: "Resolved from codebase"

    ### Step 2: If the codebase can't answer it

    This is a genuine ambiguity that needs the user's decision. Formulate a question using
    the Socratic method:

    - **One question only** — don't bundle multiple questions
    - **Ground in existing code** — reference what the codebase currently does
      Example: "Currently `src/chat/UnreadChatsEndpoint.ts`
      requires an authenticated staff member via `requireStaff()`. Should this new
      endpoint follow the same pattern, or does it need different access control?"
    - **Offer concrete options** — with trade-offs when possible
      Example: "Option A: Same staff assertion (consistent, simpler). Option B: A
      narrower role check (more granular, needs a new access rule)."
    - **Explain why it matters** — what goes wrong if we guess

    Classify as: "Needs user decision"

    ## What to Look For

    - **Undefined behavior:** What happens when X is empty? null? very large?
    - **Missing scope boundaries:** Is Y in scope or not? The spec is ambiguous.
    - **Implicit assumptions:** The spec assumes Z, but is that actually true?
    - **Integration gaps:** How does this interact with existing feature W?
    - **Error cases:** What happens when the happy path fails?
    - **Authorization:** Who can do what? Are the access rules clear?
    - **Data migration:** Does this change existing data? What about existing records?
    - **Performance:** Will this work at scale? Any N+1 queries implied?

    ## Report Format

    ### Resolved from Codebase
    1. **Ambiguity:** [what was unclear]
       **Answer:** [what the codebase says, with file:line reference]

    ### Needs User Decision
    1. **Question:** [Socratic question — one at a time, grounded in code, concrete options]
       **Why it matters:** [what goes wrong if we guess]
       **Options:**
       - A: [option with trade-off]
       - B: [option with trade-off]

    If no ambiguities found: "✅ Spec is clear — no ambiguities found."
```
