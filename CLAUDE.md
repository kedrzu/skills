# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this repository is

A personal **Claude Code plugin marketplace** (`kedrzu-skills`) holding reusable skills
that are shared across projects. It is not an application: there is no build, no
runtime, no tests. The deliverable is the manifests and the Markdown inside them.

Other projects consume it with:

```bash
claude plugin marketplace add kedrzu/skills
claude plugin install <plugin-name>@kedrzu-skills
```

## Layout

```
.claude-plugin/marketplace.json   # marketplace catalog (required, repo root)
plugins/<plugin-name>/            # one installable plugin per directory
  .claude-plugin/plugin.json      # plugin manifest
  skills/<skill-name>/SKILL.md    # one skill per subdirectory
  skills/<skill-name>/...         # optional scripts/, references/, assets/
```

`metadata.pluginRoot` is `./plugins`, so a marketplace entry may use the bare
directory name as its `source`.

## Conventions

- **Everything committed here is in English** — manifests, skill bodies, comments,
  README, commit messages. Conversations with the user happen in the user's language.
- Plugin and skill directory names are **kebab-case** and match the `name` field in
  their manifest/frontmatter.
- **Split skills into small, focused plugins** so a project installs only what it
  needs. Cross-plugin reuse is handled by the `dependencies` array (see below), so
  splitting costs nothing — prefer a new plugin over stuffing an unrelated skill into
  an existing one.
- Bump the plugin's `version` (semver) in `plugin.json` whenever its skills change;
  keep it in sync with the `version` in the marketplace entry if one is set.
- Keep `SKILL.md` bodies short and imperative; move long material into sibling files
  (`references/`, `scripts/`) and link to them from `SKILL.md`.
- Reference bundled files from a skill with `${CLAUDE_PLUGIN_ROOT}`, never with an
  absolute path from this machine.

## Adding a skill to an existing plugin

1. Create `plugins/<plugin-name>/skills/<skill-name>/SKILL.md` with frontmatter:

   ```markdown
   ---
   name: <skill-name>
   description: <what it does and when Claude should use it — this is what triggers it>
   ---
   ```

2. Bump `version` in `plugins/<plugin-name>/.claude-plugin/plugin.json`.
3. Run the validation command below.

The `description` is the only thing Claude sees before loading the skill, so write it
as a trigger: what the skill does *and* the situations that should invoke it.

## Adding a new plugin

1. `mkdir -p plugins/<plugin-name>/.claude-plugin plugins/<plugin-name>/skills`
2. Write `plugins/<plugin-name>/.claude-plugin/plugin.json`:

   ```json
   {
     "name": "<plugin-name>",
     "description": "...",
     "version": "0.1.0",
     "author": { "name": "Michał Kędrzyński" }
   }
   ```

3. Append an entry to `plugins` in `.claude-plugin/marketplace.json`:

   ```json
   { "name": "<plugin-name>", "source": "./plugins/<plugin-name>", "description": "..." }
   ```

4. Add at least one skill and validate.

## Dependencies between plugins

Dependencies exist at **plugin** level, not skill level. When a skill needs another
skill that lives in a different plugin, declare that plugin in the `dependencies`
array of the consuming plugin's `plugin.json`. Claude Code installs and enables
dependencies transitively.

```json
{
  "name": "deploy-kit",
  "version": "1.2.0",
  "dependencies": [
    "core-lib",
    { "name": "secrets-vault", "version": "~2.1.0" }
  ]
}
```

- A **bare string** tracks whatever version the marketplace currently provides. This
  is the default for plugins inside this repository: no git tags needed, the
  dependency is installed from the marketplace's current copy.
- The **object form** adds a semver range (`~2.1.0`, `^2.0`, `>=1.4`, `=2.1.0`).
  Constraints resolve against git tags named `<plugin-name>--v<version>` on this
  repository, so a constrained dependency only works once its releases are tagged
  (see Releases). Add constraints only when a real breaking change makes pinning
  worth the tagging overhead.
- `name` resolves within this marketplace. Depending on a plugin from another
  marketplace requires `marketplace` in the dependency entry *and* that marketplace's
  name listed in `allowCrossMarketplaceDependenciesOn` in `marketplace.json`.
- When several installed plugins constrain the same dependency, the ranges are
  intersected; incompatible ranges fail the install with `range-conflict`.
- Disabling a plugin that another enabled plugin depends on is refused, and
  uninstalling leaves orphaned dependencies behind until `claude plugin prune`.

**Bundle plugins**: a manifest may consist of just `name`, `version` and
`dependencies`. Installing it pulls in the whole curated set — a good way to offer a
one-command install of the skills a given project type needs.

A skill that depends on another skill should say so in its `SKILL.md` body (name the
skill and the plugin it comes from), because the dependency array alone does not tell
the reader why it is there.

## Validation

Always run before committing a manifest or skill change:

```bash
claude plugin validate . --strict                       # marketplace + entries
claude plugin validate ./plugins/<plugin-name> --strict  # a single plugin
```

`claude plugin eval <plugin-name>` runs a plugin's eval suite when one exists under
`plugins/<plugin-name>/evals/`.

## Testing a change locally

Load plugins straight from the working tree — no install, no marketplace update:

```bash
claude --plugin-dir ./plugins                  # loads every plugin in the folder
claude --plugin-dir ./plugins/<plugin-name>    # a single plugin
```

A local copy satisfies another local plugin's dependency entry, and version
constraints are not checked against local copies, so cross-plugin dependencies can be
developed together this way.

## Publishing

There is no push-style publish step for this marketplace: **the git repository is the
distribution channel**. Consumers add `kedrzu/skills` once, and a push to `main`
becomes available to them the next time their marketplace refreshes (an explicit
`claude plugin marketplace update kedrzu-skills`, an install that names the
marketplace, or auto-update if they enabled it — it is off by default for third-party
marketplaces).

A user only receives a changed plugin when its `version` in `plugin.json` is bumped,
because the version is the cache key. **Never change a plugin's skills without
bumping its version.**

Other distribution routes, for reference:

- **claude.ai sync** — plugins enabled on a claude.ai account load in every session as
  `<name>@synced`, including cloud sessions, with no marketplace install. Uploading is
  done on claude.ai, not from this repo. A plugin distributed that way cannot ship a
  top-level `bin/` directory.
- **Community marketplace** (`claude-community`) — submission and review via
  platform.claude.com/plugins/submit; approved plugins are pinned to a commit SHA that
  CI bumps as this repository gets new commits. Not needed for private use.
- The official `claude-plugins-official` marketplace is curated by Anthropic; there is
  no application process.

## Releases and CI

`.github/workflows/validate.yml` runs on every push and pull request:

1. **validate** — `claude plugin validate --strict` on the marketplace and on each
   plugin. Needs no API key; the CLI is installed from npm.
2. **version guard** — fails the build when files under `plugins/<name>/` changed
   without a bump to that plugin's `version`. A new plugin with no previous manifest
   is allowed through. This is the safety net for the rule above: content that ships
   without a version bump silently never reaches consumers.
3. **tag** — on `main` only, creates and pushes a `<plugin-name>--v<version>` tag for
   any plugin whose current manifest version has no tag yet.

Tags matter because dependency version constraints resolve against them. Bumping
`version` in `plugin.json` and merging to `main` is therefore the whole release
process. To tag by hand instead, run `claude plugin tag ./plugins/<plugin-name> --push`.

## How an update reaches a consumer

There is no daemon and no continuous polling. A machine picks up a new version when:

- **Session start**, for marketplaces with auto-update enabled: Claude Code checks in
  the background after startup, with a random delay of up to ten minutes, then shows
  `Plugins changed. Run /reload-plugins to activate.` The running session keeps the
  version it launched with. Auto-update is **off by default** for third-party
  marketplaces like this one. A consumer turns it on either in `/plugin` →
  **Marketplaces**, or declaratively with `"autoUpdate": true` on the
  `extraKnownMarketplaces` entry in any settings file, which then takes precedence
  over the interactive toggle. The README documents both.
- **An explicit refresh**: `claude plugin marketplace update kedrzu-skills`, or any
  `claude plugin install <name>@kedrzu-skills`, which refreshes the marketplace first
  even when auto-update is off.

Scope, not the repository, decides where a plugin is active. A user-scope install
makes it available in every project on that machine, and the cache at
`~/.claude/plugins/cache/` is shared, so one update covers every workspace at once.
Project scope writes the plugin into that repository's `.claude/settings.json`;
collaborators still run `claude plugin install` themselves for an external source.
Each version gets its own cache directory, and the previous one is swept about 14 days
later so sessions still running on it don't break.
