# skills

Personal [Claude Code](https://code.claude.com) plugin marketplace with skills shared
across projects. Each plugin lives in `plugins/` and ships one or more skills; plugins
may depend on each other, and dependencies are installed automatically.

## Install

```bash
claude plugin marketplace add kedrzu/skills
claude plugin install <plugin-name>@kedrzu-skills
```

Browse what is available with `/plugin` → **Discover**, or look in `plugins/`.

### Choose a scope

`claude plugin install` writes to **user** scope unless you pass `--scope`:

| Scope | Where it applies | Where it is stored |
| :-- | :-- | :-- |
| `user` (default) | every project on this machine | `~/.claude/settings.json` |
| `project` | this repository, shared with collaborators | `.claude/settings.json` |
| `local` | this repository, only you | `.claude/settings.local.json` |

A user-scope install is usually what you want: the plugin cache is shared, so one
install and one update cover every workspace on the machine.

To pin a plugin to a single repository and have the marketplace register itself for
anyone who trusts the folder, add this to that repository's `.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "kedrzu-skills": {
      "source": { "source": "github", "repo": "kedrzu/skills" },
      "autoUpdate": true
    }
  },
  "enabledPlugins": {
    "<plugin-name>@kedrzu-skills": true
  }
}
```

Collaborators still run `claude plugin install <plugin-name>@kedrzu-skills` once —
Claude Code does not auto-install plugins that come from an external source.

## Install as a git submodule

Use this instead of the marketplace when you want to edit the skills from inside the
repository that uses them: the plugins load straight from the submodule's files, so a
change shows up in the next session (or after `/reload-plugins`) with no push, version
bump or marketplace refresh in between.

It relies on Claude Code loading a plugin directory placed under a project's
`.claude/skills/` in place, as `<plugin-name>@skills-dir` — skills, `.mcp.json`, hooks and
dependencies on other plugins included, with `${CLAUDE_PLUGIN_ROOT}` pointing at that
directory.

1. Add the submodule, tracking `main`:

    ```bash
    git submodule add -b main https://github.com/kedrzu/skills.git skills
    ```

2. Enable each plugin you want by committing a relative symlink to its directory — the
   link's name is the plugin's name:

    ```bash
    ln -s ../../skills/plugins/<plugin-name> .claude/skills/<plugin-name>
    ```

    Link the plugins it depends on as well (`dependencies` in its `plugin.json`). The set
    of links is the project's selection. Making `.claude/skills` itself a link to
    `plugins/`, as this repository does for its own development, enables every plugin and
    leaves no room for the project's own skills.

3. Make sure the workspace is trusted. Claude Code ignores a plugin under `.claude/skills/`
   until you accept the workspace trust dialog for that folder, and `claude -p`, SDK
   sessions and tools that launch Claude Code non-interactively never show the dialog. In
   that case, set the trust by hand. Use the repository root path, and do this once per
   checkout and per git worktree:

    ```jsonc
    // ~/.claude.json, or $CLAUDE_CONFIG_DIR/.claude.json
    { "projects": { "/absolute/path/to/repo": { "hasTrustDialogAccepted": true } } }
    ```

    Edit that file with a script that rewrites only this key. It also holds your sign-in.

To turn a plugin off for everyone, delete its symlink. To turn it off only for yourself,
set `"<plugin-name>@skills-dir": false` under `enabledPlugins` in
`.claude/settings.local.json`. You switch whole plugins only: `skillOverrides` does not
apply to plugin skills, so split a plugin here if a project needs only part of it.

Things to know:

- **Same plugin from the marketplace.** An enabled marketplace install of the same plugin
  wins over the `@skills-dir` copy. Disable or uninstall it, and drop `kedrzu-skills` from
  the project's `extraKnownMarketplaces` and `enabledPlugins`.
- **MCP servers and monitors.** The plugin's MCP servers go through the same per-server
  approval as the project's `.mcp.json`. Background monitors do not load for a plugin
  that comes from the repository.
- **Clones and worktrees.** Run `git submodule update --init` in every new clone or
  worktree. Until you do, the symlinks dangle and the plugins silently do not load.
- **Publishing a change.** Branch inside the submodule, commit there, push, and open a PR
  against `main` of this repository. Bump the plugin's `version` as you would for a
  marketplace release. CI requires it, even though the in-place copy ignores versions.
  Then commit the moved submodule pointer in the parent repository.

## Turn on auto-update

Auto-update is **off by default** for third-party marketplaces like this one, so a new
version does not arrive on its own until you enable it. Declare it once in
`~/.claude/settings.json` to cover every project on the machine:

```json
{
  "extraKnownMarketplaces": {
    "kedrzu-skills": {
      "source": { "source": "github", "repo": "kedrzu/skills" },
      "autoUpdate": true
    }
  }
}
```

The same entry works in a repository's `.claude/settings.json` or in managed settings.
A declared value wins over the interactive toggle: `/plugin` then reports that
auto-update is set by that settings source and refuses to change it there. If you would
rather toggle it per machine, leave `autoUpdate` out and use
`/plugin` → **Marketplaces** → `kedrzu-skills` → **Enable auto-update**.

With auto-update on, Claude Code checks in the background shortly after a session
starts (random delay of up to ten minutes) and then shows
`Plugins changed. Run /reload-plugins to activate.` The session you are in keeps the
version it launched with until you reload.

Without auto-update, refresh on demand:

```bash
claude plugin marketplace update kedrzu-skills   # refresh the catalog
claude plugin update <plugin-name>               # then update a plugin
```

`claude plugin install <plugin-name>@kedrzu-skills` always refreshes the marketplace
first, even when auto-update is off.

## Apply changes in a running session

```
/reload-plugins
```

Use `/reload-plugins --force` if the reload warns that it would invalidate the prompt
cache. Each plugin version is cached separately and the previous one is kept for about
two weeks, so sessions already running on the old version keep working.

## Versioning

A plugin's `version` is the cache key: you only receive a change once the plugin's
version has been bumped. CI in this repository fails any change to a plugin that does
not bump its version, and tags each released version as `<plugin-name>--v<version>`,
which is what dependency version ranges resolve against.

## Repository layout

```
.claude-plugin/marketplace.json   # marketplace catalog
plugins/<plugin-name>/            # one installable plugin per directory
  .claude-plugin/plugin.json
  skills/<skill-name>/SKILL.md
```

See [CLAUDE.md](CLAUDE.md) for the conventions used when adding plugins and skills.
