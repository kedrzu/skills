---
name: verify
description: >-
    How a change is proven to work in this repository — manifests, version bumps, references
    inside the skills, and the server and hook tests — in a scoped mode and a full one. The dev
    pipeline, `/dev:review` and `/dev:fix-pr-comments` take every check from here. Use it directly
    before committing any change under `plugins/` or to the marketplace, and when CI fails.
---

# Verify

Fulfils the `dev` plugin's `verify` contract. This is a project skill, not a plugin: it has no
`plugin.json` and no marketplace entry, and it reaches `.claude/skills/` through the `plugins`
symlink. CI runs the same script, so a green full run here is a green `Verify` job there.

Both modes are one script, run from the repository root. It needs `claude`, `bun` and `python3`; a
missing one is reported as a failure, never as a pass.

## Scoped

```bash
python3 plugins/verify/scripts/verify.py --scoped
```

Covers the plugins the change touched since it left its base (the open PR's base, else
`origin/main`), uncommitted and untracked files included: the marketplace and each touched
plugin validated with `--strict`, the version guard, the plugin's references, its server
(`bun install --frozen-lockfile`, `bunx tsc --noEmit`, `bun test`) and every `test_*.py` under
it. A change to `.claude-plugin/`, `.github/` or this skill widens it to every plugin. Green here
says nothing about the plugins it did not look at.

## Full

```bash
python3 plugins/verify/scripts/verify.py --full
```

The same checks over every plugin, plus `claude plugin eval <name>` for a plugin with an
`evals/` directory. That is the whole protocol; nothing is added to it by hand.

## When it is red

- **Version guard** — the plugin changed and its `version` did not: bump it in
  `plugins/<name>/.claude-plugin/plugin.json`, in its `.claude-plugin/marketplace.json` entry and,
  when it has one, in `server/package.json`. In a stack, each node bumps relative to the node below
  (`git-workflow` → Stack).
- **A reference** — `${CLAUDE_PLUGIN_ROOT}/<path>` or a relative link points at nothing: fix the
  path or restore the file. Another plugin's MCP tools or `<plugin>:<skill>` reached without
  `"<plugin>"` in `dependencies`: declare it (`CLAUDE.md` → "Dependencies between plugins"), or,
  when only the user should run it, write it as the slash command `/<plugin>:<skill>`.
- **`claude plugin validate`** — its message names the field. Its warnings do not fail the run.
- **A stack** — the default base is the open PR's base, so a node is measured against the node
  below. Before its PR exists, pass `--base <branch of the node below>`.
