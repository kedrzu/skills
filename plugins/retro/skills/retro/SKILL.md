---
name: retro
description: Retrospective on how agents worked in this project: find the root cause in session transcripts and PR reviews, and propose changes to the environment.
argument-hint: "what went wrong, and your hypotheses (default: this session)"
disable-model-invocation: true
---

# Retro

A retro finds what to change in the **environment** agents work in (steering files, skills,
checks, tools, access to information) so the next run goes better. It ends with proposals: whether
a change is made now, split into tasks, researched further or dropped is the user's call, made
after the retro. It is not a second attempt at the task itself either.

The user comes with a question: something that went wrong, often with their own hypotheses about why. That
question is the scope. Answer it with evidence, verdict by verdict, and resist widening it into a
survey of everything that could be better. With no argument, the question is the current session.

## Read the previous retro first

Reports live in `docs/retro/` in the project. Open the newest one and, for every change it
proposed, check two things: did it land (git log on the file it names), and does the friction it
targeted still show up in sessions since then? Give each a verdict: **helped**, **unchanged**,
**regressed** or **never landed**. Shipping a change is not evidence that it worked; only the
recurrence (or absence) of the friction is. An unchanged one comes back as a finding of this run,
carrying the old evidence along with the new.

This is the part of a retro loop that turned out most valuable in practice: without it, the loop
writes rules and never learns which ones did anything.

## Gather evidence

**Sessions.** The bundled script reads both Claude Code and Codex transcripts:

```bash
python3 -I ${CLAUDE_PLUGIN_ROOT}/skills/retro/scripts/sessions.py list --project . --since 14d   # this repo, its worktrees, archived ones too
python3 -I ${CLAUDE_PLUGIN_ROOT}/skills/retro/scripts/sessions.py render <file> --user-only      # the user's turns, answers, interruptions only
python3 -I ${CLAUDE_PLUGIN_ROOT}/skills/retro/scripts/sessions.py render <file>                  # + assistant prose, one line per tool call
```

Start from `--user-only`: frustration, corrections mid-run, interruptions, and anything the user had to
say twice are where the friction is. A repeat marks a rule that does not catch. Render the full
narrative only for the stretch that matters. With more than a handful of sessions, hand them to
subagents and have each return a structural account (what was attempted, where it stalled, what
the user corrected), not quotes.

Claude Code deletes transcripts after `cleanupPeriodDays` (30 by default), so older work survives
only in Codex rollouts, git history and PRs. When the question reaches further back than the
transcripts do, say so instead of concluding from what is left.

**Merged-PR review threads** show what shipped wrong even when the session felt smooth:
`gh pr list --state merged --limit 30`, then `gh api repos/{owner}/{repo}/pulls/<n>/comments` and
`gh pr view <n> --comments`.

**The environment itself**: `CLAUDE.md`/`AGENTS.md`, the skills the sessions loaded, the repo's
check command (`package.json` scripts, CI workflow, pre-commit hooks).

Line the sources up. Where sessions and reviews agree, the finding is solid. A problem reviewers keep
flagging that never made the agent hesitate is a **silent quality problem**: the agent would never
stop to read a document about it, so it needs a mechanical check, not more text.

## Lenses

- **Navigation**: time lost finding the right file; a pointer would have saved it.
- **Automated checks**: a mistake a lint rule, type check, test or hook could catch. Read the
  repo's existing check command first; a check that exists but is unwired or broken is the finding.
  A mechanical violation (a banned API, an import shape, a file-location rule) gets a check, not a
  rule in prose.
- **Review standards**: what the reviewing agent should have caught and did not. Judgement calls
  belong where the reviewer reads, not in the implementer's always-loaded context.
- **Steering files**: always-loaded text that is stale, duplicated, changes nothing (a no-op the
  model already does by default), or restates a check that already enforces it, so the two drift
  apart. Removing it is a valid fix.
- **Skills**: an instruction that lost, was wrong, or is missing.
- **Tool economy**: expensive or repeated tool calls a script or a better tool would replace.
- **Information access**: something the agent could not see (logs, a third-party service, data)
  and guessed instead.

## Name each change's home

The home follows from where the behaviour can be caught, not from where the agent learned it. A
misstep recognisable in a tool call or a diff goes to a check even when a skill or `CLAUDE.md`
taught it: a check fires every time, text only when it wins the agent's attention.

| Cause | Home |
|-|-|
| Mechanical mistake | a check: a `PreToolUse` hook in a Claude Code plugin, a lint rule, a CI job, whichever the repo makes cheapest |
| A skill behaved badly | the skill: name the instruction that should have caught this, and whether it is missing, lost or wrong |
| Judgement the reviewer missed | the review standards the project's reviewer reads |
| Navigation | a pointer in `CLAUDE.md`/`AGENTS.md`, or in the doc the agent was already reading |
| Missing information | access: a tool, a log, a read-only credential |
| Code | the code itself |

A one-off slip, or a model too small for the job, is not an environment problem. Saying so is a
finding too.

## Refute before you propose

Before anything reaches the user, have a subagent try to refute each proposed change against the repo:
does it already exist, does the evidence really show what the finding claims, would something
narrower do, could a check enforce what the change puts in text? In one real run this pass dropped 2 of 15 drafted changes as false and narrowed 8, and
every overstatement pointed the same way: towards building something that already existed.

## Present the proposals

In the conversation's language:

1. **Root cause**: one short story of why it went wrong, not a list.
2. **The user's hypotheses**: each **confirmed**, **partly**, or **not confirmed**, with the evidence.
3. **Previous retro**: the verdicts.
4. **Findings**: numbered, so the user can prune by number. Each has the evidence, the change, its home,
   and what would look different next time if it worked.

Expect scope corrections and findings of the user's own; those corrections are often the most
valuable input of the run. Revise and re-present until the user settles the list.

Then write `docs/retro/<YYYY-MM-DD>-<topic>.md` in English: the question, the evidence looked at
(counts, date range, session and PR ids), the previous-retro verdicts, the root cause, and the
findings the user kept, each with its proposed change and home. The next retro reads this file, so
the "what would look different" line is what makes it useful. The report is committed: describe
things structurally, never quote transcripts or review comments, and keep out personal data,
patient data and secrets.

That is where the retro stops. Carrying out the changes is a separate decision for the user, and
each one carries its own procedure (`skill-improve` for a skill, the project's entry points for
code); starting one from here would make that decision for them.
