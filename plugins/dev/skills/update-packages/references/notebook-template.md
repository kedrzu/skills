# Notebook Template

The two files the skill reads at the start of a run and updates at the end. Create whichever is
missing from its skeleton below, in the project's `docs/`. Each starts with a lead paragraph that
defines its entries, so a later run can follow the format without this skill. The third input, the
`UPDATES.md` catalogue at the repository root, has its skeleton at the end.

## `docs/package_update.md`

```markdown
# Package Update Notes

Last updated: YYYY-MM-DD

## General Rules

Persistent constraints that hold whatever the version: couplings ("update only together with Y",
"must match the version X bundles"), the reason behind each root `overrides` entry, and the
project's own procedures — how to collapse duplicate dependency trees, which bumps need a rebuild or
a restart. A version pinned outside the package manager and how to bump it goes in `UPDATES.md`,
not here. One `###` per package. Remove an entry only when its constraint is gone.

### <package-name>

<the persistent constraint, and the procedure if it has one>

## Known Issues

Version-specific failures from past attempts. Never retry a listed version; delete the entry when a
newer version fixes it. One `###` per package and attempted version.

### <package-name> <attempted-version>

- **Problem**: <what breaks>
- **Error**: <brief error or symptom>
- **Status**: skip | needs-migration | regression-bug | incompatible | blocked-by-<dep> | blocked-by-<submodule-path> | blocked-by-consumer
- **Notes**: <how to reproduce / what to check; for a block across repositories, where the other side records it>
```

A constraint that persists across versions (two packages must always match) goes in **General
Rules**, not Known Issues; the procedure for a version outside the package manager goes in
`UPDATES.md`, not General Rules. Which repository's notebook an entry belongs in, and the wording of the
two cross-repository statuses: `cross-repo-notebooks.md`.

## `docs/dependency-health.md`

```markdown
# Dependency Health

Last full review: YYYY-MM-DD

Dependencies that were deprecated, renamed or abandoned, found by the registry `deprecated` check or
the monthly full review. The update run never migrates one; it raises each finding until the owner
decides. One `###` per package with the fields below. A decided finding is raised again only when
its situation changes; a `pending` one goes into every run report.

### <package-name>

- **Found**: YYYY-MM-DD — <registry deprecation | full review>
- **Used in**: <workspaces>
- **Evidence**: <the deprecation message, archived repo, README notice — quoted or linked>
- **Successor**: <package, or none>
- **Recommendation**: <what and why>
- **Decision**: pending | migrate (<tracker issue>) | keep (<reason>) | remove
```

## `UPDATES.md`

At the repository root, not in `docs/`, and created only when the first entry is added — no file
means nothing is pinned outside the package manager. Field meanings and how a run walks the file:
`updates-catalogue.md`.

```markdown
# Updates

Versions the package manager does not track — container images, tools, runtimes, binaries pinned in
config files or CI. The weekly package update walks every entry: runs **Latest**, compares it with
the pin, and if newer follows **Bump**, **Rollout** and **Verify**; a red result is reverted and
recorded in `docs/package_update.md` → Known Issues. One `###` per item, all five fields filled;
**Latest** is a command that prints exactly one version. The package manager's own dependencies do
not belong here.

### <name>

- **Pinned in**: <file> — <line or symbol>
- **Latest**: `<command printing exactly one version>`
- **Bump**: <the edit, and what regenerates; for an unpinned "latest at build" item, what forces a refresh>
- **Rollout**: <what to rebuild/recreate/redeploy; any follow-up the run must create>
- **Verify**: <how to prove it works locally; how the rest is proven after merge>
```
