# Notebooks Across Repositories

A git submodule is a repository of its own: it is updated by runs started inside it, by runs started
in each project that consumes it, and it outlives any one of them. So every repository that declares
dependencies keeps its own notebook, and the state of an update — what is held back, and why — has to
be readable from inside the repository that holds the dependency, by a run that has never seen the
others.

## Which notebook an entry goes in

- **The repository whose manifest declares the package, or whose code breaks.** A constraint about a
  package only a submodule declares lives in the submodule, even when the run that found it started
  in the consumer.
- **Declared on both sides** → each side records what binds it. When one failure blocks both, the
  full entry goes where the cause lives and the other side gets a short entry that points at it.
- **Procedures** (how to collapse duplicate trees in this checkout, how to bump an image tag) belong
  to the repository whose checkout they describe — usually the consumer's, which builds the
  submodule from source.

A submodule's notebook is committed in the submodule, through `git-workflow` **checkpoint** like its
manifests: the notebook change rides the run's one submodule branch and PR.

## A submodule never names its consumer

A submodule is reused across projects and must not carry any of them in its history: no repository
name, file path, tracker ID or product term of a consumer. When a consumer is what holds a submodule
back, describe the consumer by the dependency that conflicts and the mechanism, so a run inside the
submodule — or inside a different consumer — understands it:

- **Bad**: "Breaks acme-app's `packages/web` story tests (ACME-412)."
- **Good**: "A consumer whose browser-mode tests assert `toHaveTextContent` with a prefix of the
  element's text fails on vitest 5, which matches the full text. Raising this range forces that
  consumer onto vitest 5."

## Blocks that cross the boundary

### A consumer blocks the submodule

The submodule's version is fine on its own, but moving it breaks a consumer.

- **Submodule** — a Known Issue with **Status** `blocked-by-consumer`, worded as above. It says what
  the submodule must not do: raise a lower bound, take a new major into a range, change an exact
  pin. Its own lockfile may still move within the range — the consumer's lockfile decides what the
  consumer installs.
- **Consumer** — the full entry: paths, the exact error, how to reproduce, the tracker issue. Its
  **Notes** start with `Recorded in <submodule-path>/docs/package_update.md → <entry heading>.`

### The submodule blocks the consumer

The consumer cannot move because the submodule breaks (a vendored type, a hard pin, its own source).

- **Submodule** — the full entry, as for any failure of its own.
- **Consumer** — a short entry, **Status** `blocked-by-<submodule-path>`, whose **Notes** point at the
  submodule's entry by path and heading. Do not copy the details; they drift.

Point at an entry by its heading text, not a Markdown anchor: an anchor breaks when the heading's
version range is edited.

## Lifting a block

- **A run inside the submodule never retries a `blocked-by-consumer` entry** — it cannot see the
  consumer, so a green submodule proves nothing. It lists the entry in the run report under **Not
  updated** as held for a consumer.
- **A run in a consumer may retry it**, under the entry's own re-check rules. Green → delete both
  entries (the submodule's through its PR). Red → record the new attempt on both sides.
- A consumer-caused entry may serve several consumers. Delete it only when no consumer the run knows
  of is still blocked; otherwise reword it to the one that remains.
