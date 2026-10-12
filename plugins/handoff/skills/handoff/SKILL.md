---
name: handoff
description: Hand the work to a fresh agent: summarise this session into a file and start a new agent with it.
argument-hint: "what the next session is for; say 'new worktree' for a separate task"
disable-model-invocation: true
---

# Handoff

The point is a fresh context that loses nothing that matters: the next agent starts with none of
this conversation, so the summary is everything it knows.

## Write the summary

Save it outside the repository, as `$TMPDIR/handoff-<slug>-<timestamp>.md` (`/tmp` when `$TMPDIR` is
unset). It carries:

- **The goal and where it stands**: what is done, what is in progress, the next step.
- **Decisions and the user's corrections.** A fresh agent re-litigates what it was not told was
  settled, and repeats what the user already pushed back on.
- **What was tried and did not work**, so it is not tried again.
- **The working tree**: branch, uncommitted changes, open PR.
- **Suggested skills**: which ones the next agent should load, and for what.

Point at artifacts that already exist (plans, design folders, specs, PRs, issues, commits) by path or
URL instead of copying them; a copy goes stale and crowds the prompt. Leave out secrets and personal
data: the summary becomes another agent's prompt and lands in its transcript.

When the user passed an argument, it says what the next session is for. Tailor the summary to that
and drop what it will not need.

## Start the next agent

With Paseo (`mcp__paseo__*` tools):

- **Same work, same branch** (the default): `create_agent` in this workspace.
- **A separate task** (the argument asks for a new worktree, or the next session is unrelated to
  this branch): `create_workspace` with `isolation: "worktree"`, branched off the right base, then
  `create_agent` with its `workspaceId`.

Run `list_providers` first and use the provider and model this session runs on unless the user
named another. Give it a short imperative `title`, the summary as `initialPrompt` (ending with the
summary file's path), and `notifyOnFinish: false`: the new agent reports to the user, not to this
session.

Without Paseo, start a background Claude Code session; passing the file keeps the shell from
expanding `$` or backticks in the summary:

```bash
claude --bg --name "<short title>" -- "$(cat "$TMPDIR/handoff-<slug>-<timestamp>.md")"
```

If neither is available, give the user the file path to paste into a new session.

Finish by telling the user where the new agent runs and where the summary is; this session can be
closed.
