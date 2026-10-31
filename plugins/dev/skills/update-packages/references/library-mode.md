# Library Mode: Product vs Shared Workspaces

How a dependency is declared depends on who installs the workspace. Decide per workspace, then apply
the matching rules below during every batch.

## Which workspaces are shared

A workspace is **shared** when either holds:

- it lives inside a git submodule of this repository — the submodule paths are
  `git config --file .gitmodules --get-regexp path`;
- its manifest is not `"private": true` — it is published.

Everything else is a **product** workspace.

## Product workspaces — exact pins

Keep pinning exact versions. Minor releases have broken apps before, and with exact pins the
lockfile guarantees nothing moves by itself. Updating means editing the pin by hand and
`bun install` — a bare `bun update` does not move an exact pin.

## Shared workspaces — ranges and peers

- **External dependencies are ranges** (`^x.y.z`). The lower bound is the minimum version the
  library has been verified with; the consuming product's lockfile picks the exact version.
- **Framework singletons are `peerDependencies`** — a package whose instances or types are shared
  with the consumer, or the host of a plugin or preset. Repeat the same range in `devDependencies`:
  a submodule consumer installs dev dependencies too, and a different specifier there means a
  second copy.

Why: an exact pin in a library forces every consumer into lockstep, and the moment one consumer
bumps, the others get a duplicate copy — with the "two different types with this name" errors that
come with it.

## During a run

- **Do not raise a lower bound just because a newer version exists.** The lockfile update within the
  range is enough, and the report says the range stayed.
- Raise a bound only when the library's code needs the newer version, or for a security fix.
- **A range that moves to a new major is a breaking change of the library.** Follow its
  repository's convention for breaking changes (commit type, changelog, version bump) — that is how
  it reaches the other consumers.
- **When the product needs a version outside a submodule's range**, the range change is a separate
  commit and PR in the submodule, published first through `git-workflow` **checkpoint**; then the
  product moves.

## Gotcha: a new peer/dev entry can create a nested copy

Observed with bun: adding a new peer or dev entry for a package, or a new range for one, can resolve
it to the newest version and create a nested second copy even though the set of `name@version`
entries in the lockfile does not change. After such an edit, look for new nested keys
(`<pkg>/<dep>`) in the lockfile. If one appears:

1. pin the dev entry to the version already locked;
2. `bun install`;
3. restore the range;
4. `bun install` again.

The lockfile then keeps the single locked copy while the manifest carries the range.
