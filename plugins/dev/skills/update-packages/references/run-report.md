# Run Report Format

One report, every destination `git-workflow` **publish** names (the PR description and the tracker
comment), plus a short chat summary in the owner's language — see SKILL.md, Phase 6. Sections in the
order below. Omit a section that is genuinely empty; never write "None".

## Where it goes

Nobody watches the run, so whatever the report omits is gone; a reader must not have to reconstruct it
from 13 commits and a `bun outdated`.

- **PR description** — **replace** the body, which may still hold the pre-run `bun outdated -r`
  inventory copied in when the work started; the report supersedes it. Keep whatever heading line
  `git-workflow` requires (e.g. the tracker-issue link and title).
- **Tracker comment** — the same report, English, posted the way **publish** says.
- **Chat** — short, the owner's language: the headline, every dependency waiting for his decision,
  anything needing manual action, links to the PR and the tracker issue.

## Sources — derive it from git, not memory

```bash
git diff <base>...HEAD -- '**/package.json' <files holding pinned image/tool versions>   # every from→to that landed
git -C <submodule> diff <base>...HEAD -- '**/package.json'   # the same per submodule the run touched
git diff <base>...HEAD -- docs/package_update.md docs/dependency-health.md   # the notebook delta
bun outdated -r                                               # what is STILL outdated = the skipped list
```

`<base>` is the branch the PR targets. Every line of the final `bun outdated -r` must appear in the
report with a reason. A package you never attempted is a skip too — name it and say why, rather than
leaving it unmentioned.

## Opening line

State the verification standard once: which protocol ran and that nothing was committed on red. That
sentence is what lets a reviewer trust a 13-commit dependency PR without replaying it.

## Needs your decision

Every `pending` finding in `docs/dependency-health.md`, new or carried over — the only part of the
report that asks the owner for something, hence first. One entry each: the package, where it is used,
the evidence quoted or linked, the successor, and your recommendation with its reason.

- **`node-sass`** (`web`, `admin`) — npm: "Node Sass is no longer supported. Please use `sass` or
  `sass-embedded` instead." Successor `sass` (Dart Sass); its stricter parser and the deprecation
  of `@import` mean stylesheets change, not just a dependency name. Recommend a separate migration
  task — two apps compile with it, so it is not a rename.

## Updated

One line per version move, **always** with `from → to`:

- A family that moved to a single version collapses to one line, named with its size —
  `@aws-sdk/client-* (16 packages) 3.1103.0 → 3.1131.0`. Anything on its own version gets its own
  line.
- Group the lines by the batch they were committed in, so the list maps onto the commit history.
- Image or tool versions pinned outside the package manager (a container image tag) belong here too —
  they are version moves the `package.json` diff will not show.
- In a shared workspace, say whether the range moved or only the lockfile did.

**Any bump that forced a source change gets its own named entry**, with the package, the file, and
what the new API required. A dependency PR that also edits source is a different review from a
lockfile-only one, and the reviewer has to learn that from the description, not from the diff.

## Not updated

|Package|Attempted|Why|
|-|-|-|
|`zod`|4.6.5|Tried and reverted — schema type inference regressed in two packages (`TS2589` on a deeply nested object), same as the recorded Known Issue|
|`nuxt`, `vite`, `@nuxt/image`|4.5.2 / 8.3.0 / 2.1.0|Not attempted — the recorded blocker still holds: `@nuxt/image@2.1.0` pins a beta dependency that breaks the server build. nuxt hard-pins the builder, so vite cannot move alone|

Distinguish the two cases explicitly: **tried and reverted** (with the error) versus **not attempted**
(the recorded blocker still holds). They mean different things to whoever picks this up next week.
Cluster packages blocked by one cause into a single row rather than repeating the reason.

`bun outdated -r` prints one row **per workspace**, so the same package appears many times — dedupe
by package name before counting, or the skipped list triples.

## Runbook changes

What this run changed in `docs/package_update.md`, one line per entry — added, removed, or rewritten.
The entry headings are the whole delta, so read them straight off the diff:

```bash
git diff <base>...HEAD -- docs/package_update.md | grep -E '^[-+]###'
```

- **Added** Known Issue `svgo 4.x` — vite-svg-loader 5.1.3 requires `^3.3.5`, a 4.x pin installs a
  second copy.
- **Removed** Known Issue `@storybook/addon-mcp 0.7.0` — 10.6.0 joins the unified line and the
  version skew is gone.

Removals carry as much signal as additions: a Known Issue that finally stopped applying is the
clearest sign the blocked update is worth retrying.

## Manual action needed

Only what a human must do by hand — e.g. restart a separate dev server after a Vite bump, because the
test runner and the browser will otherwise serve pre-bump code. Omit the section when there is none.
