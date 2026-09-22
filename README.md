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
