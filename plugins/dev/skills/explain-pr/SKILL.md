---
name: explain-pr
description: >-
    Explains the current branch's pull request in plain language — what it actually does and why,
    where the changes that matter are, what can be skimmed, and what could go wrong — so the owner
    can get his bearings before (or instead of) reading the diff. When the PR is one node of a
    stacked chain, explains the whole chain node by node, bottom up. Use when the user says "wyjaśnij
    ten PR", "o co chodzi w tych zmianach", "co właściwie robi ten PR", "przeprowadź mnie przez
    stacka", "explain this PR", "walk me through these changes", "what does this stack do", or
    otherwise wants to understand a PR rather than judge it — any language counts. Read-only: it
    posts nothing. Do NOT use to find bugs and post findings (/dev:review) or to act on PR comments
    (/dev:fix-pr-comments).
---

# Explain PR

He opens this to understand a PR fast — usually one an agent wrote, often one in a chain — before he
decides where to spend his attention. So the explanation is a map, not a summary of every file: what
the change does for whoever uses the system, the few places where that actually happens, what he can
skim, and what could break. A diff already lists everything; the value here is in the ordering and
the plain words.

Everything is in chat, in the owner's language as `/dev:review` defines it
(`${CLAUDE_PLUGIN_ROOT}/skills/review/SKILL.md`). Technical terms stay English. Nothing is posted to
GitHub and no file is written.

## Getting the chain

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/pr_stack.py
```

It prints the chain this branch belongs to, bottom first: per node `prNumber`, `branch`, `headSha`,
`base`, plus `currentNode`. An ordinary PR is a chain of one, so there is no separate path. A
non-zero exit means it could not tell what the chain is — report what it said and stop rather than
explaining a guessed shape. `prNumber: null` means the branch has no PR yet: say so, and explain the
branch against its base (`git diff <default branch>...HEAD`) instead.

Per node:

```bash
gh pr view <n> --json title,body,url,commits
gh pr diff <n>
```

`gh pr diff` is exactly what GitHub shows for that node, whatever is checked out locally. When it
refuses a very large PR, use `git diff <base>...<headSha>` after `git fetch origin <branch>`. To read
code beyond the diff — a caller, the type a field comes from — read it as the node has it
(`git show <headSha>:<path>`), since the working tree may stand on another node. Do read beyond the
diff when the change only makes sense through its surroundings; the description says what the author
meant, the code says what happens.

## A chain is explained as a chain

A node read alone often makes no sense — a new table with no reader, an interface with one
implementation — because its reason lives in the node above. So read every node first, then explain:
the chain's story in a few sentences, then node by node from the bottom, each with its role in the
story. Mark the node he is standing on. A risk that spans nodes is named once, on the lowest node it
starts in.

## What he gets

- **What it does, and why** — in terms of behaviour, not files. Who notices the change, and how.
- **Where it happens** — the handful of places that carry the change, as `path:line`, each with one
  sentence on what it decides. This is what he will open, so be selective.
- **What can be skimmed** — mechanical changes (renames, moves, regenerated files, wiring) and
  refactors meant to keep behaviour the same. Say which is which: a refactor is read for one question,
  whether behaviour stayed the same, and mechanical churn is vouched for by the compiler and tests.
- **Risks** — concrete: what breaks, for whom, when. "Existing rows get `NULL` in the new column and
  the report sums it" is a risk; "could introduce bugs" is not. If you see none worth naming, say so
  in a sentence — padding this list teaches him to skip it.
- Anything in the PR that the description does not mention, or that contradicts it.

Size follows the PR: a ten-line fix gets a paragraph, not five headings.

## Example

For a two-node chain, standing on the top node (written in the owner's language in practice):

> **The chain:** patients can now withdraw marketing consent themselves; until now only staff could,
> through support. Node 1 adds the withdrawal to the backend, node 2 puts the button in the portal.
>
> **#412 — withdrawal in the backend** (read it)
> A new command records the withdrawal and stops further campaign mailings.
> - `src/consent/WithdrawConsentCommand.ts:30` — marks the consent withdrawn rather than deleting it,
>   so the history stays for audit.
> - `src/campaigns/recipients.ts:58` — the mailing query now skips withdrawn consents.
> - Skim: `src/consent/index.ts` and the regenerated `api.gen.ts` are wiring.
> - Risk: campaigns already queued before the withdrawal still go out — the check is at queue time,
>   not at send time. A patient who withdraws an hour before a send still gets that email.
>
> **#413 — button in the portal** ← you are here (skim)
> One button and a confirmation dialog calling the command from #412
> (`src/portal/ConsentPanel.tsx:44`). No logic of its own; nothing worth naming as a risk.
