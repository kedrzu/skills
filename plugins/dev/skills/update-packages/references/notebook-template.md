# Notebook Template

The two files the skill reads at the start of a run and updates at the end. Create whichever is
missing from its skeleton below, in the project's `docs/`. Each starts with a lead paragraph that
defines its entries, so a later run can follow the format without this skill.

## `docs/package_update.md`

```markdown
# Package Update Notes

Last updated: YYYY-MM-DD

## General Rules

Persistent constraints that hold whatever the version: couplings ("update only together with Y",
"must match the version X bundles"), the reason behind each root `overrides` entry, and the
project's own procedures — a container image or tool version pinned outside the package manager and
how to bump it, how to collapse duplicate dependency trees, which bumps need a rebuild or a restart.
One `###` per package. Remove an entry only when its constraint is gone.

### <package-name>

<the persistent constraint, and the procedure if it has one>

## Known Issues

Version-specific failures from past attempts. Never retry a listed version; delete the entry when a
newer version fixes it. One `###` per package and attempted version.

### <package-name> <attempted-version>

- **Problem**: <what breaks>
- **Error**: <brief error or symptom>
- **Status**: skip | needs-migration | regression-bug | incompatible | blocked-by-<dep>
- **Notes**: <how to reproduce / what to check>
```

A constraint that persists across versions (two packages must always match) goes in **General
Rules**, not Known Issues.

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
