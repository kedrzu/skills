# The Updates Catalogue

`UPDATES.md` at a repository's root lists every version the package manager does not see — a
container image tag, a tool or runtime version in a config file or a CI workflow, a binary fetched
by URL, an image that installs "latest" at build time. `bun outdated` shows none of them, so without
the catalogue they rot silently. One per repository, like the notebook
(`cross-repo-notebooks.md`); the package manager's own dependencies need no entry.

## Entry format

One `###` per pinned item, the five fields in this order, each filled:

- **Pinned in** — the file, and the line or symbol holding the version, so the bump edits exactly
  one place (or names every place that must move together).
- **Latest** — a concrete command that prints exactly one value: the newest version to compare
  against. Not prose ("check the releases page"): a run must be able to execute it unattended.
- **Bump** — how to move it: the edit, plus whatever regenerates from it. For an item that installs
  "latest" at build time and pins nothing, what forces a fresh build.
- **Rollout** — what must be rebuilt, recreated or redeployed for the new version to take effect,
  and any follow-up the run must create (e.g. "open a tracker issue for the deploy, blocked by this
  run's issue"). For something only the cloud builds or runs, how it gets proven after merge.
- **Verify** — how to prove the new version works, as far as it can be proven locally: the project's
  `verify` protocol, plus any check specific to this item.

## Walking the catalogue

Every run walks every entry, in file order, after the risky packages. For each:

1. **Incomplete** — a field missing or empty, or **Latest** prose instead of a command → touch
   nothing, report `blocked — incomplete entry (<field>)`, go on to the next entry.
2. **Latest** — run the command. A failure, or output that is not exactly one value → report
   `blocked — Latest failed: <error>`. A pin that disappeared upstream (a deprecated image, a
   deleted tag) usually surfaces here or in Verify; the fix is the bump itself.
3. **Compare** against the version in **Pinned in**. Equal → report `already latest (<version>)`.
   A recorded Known Issue for that version in the notebook → report `blocked — Known Issue
   <heading>` without retrying.
4. **Bump** — follow it.
5. **Rollout** — do the local part: rebuild or recreate what runs it, so Verify tests the new
   version and not a cached old one.
6. **Verify** — follow it; it includes the full `verify` protocol before committing.
7. **Green** → commit through **checkpoint** (one commit per entry, named after it: "Update
   <name> to <version>"), then carry out the follow-ups **Rollout** prescribes — a follow-up
   tracker issue is created now and linked in the report. Report `bumped <from> → <to>`.
8. **Red** → revert the bump, undo its local rollout (recreate the old one), record a **Known
   Issue** `<name> <version>` in the notebook as for any failed update, report `blocked — <error in
   one line>`.

What only a deployment can prove stays unproven in this run: Verify covers the local part, and
**Rollout** names how the rest is proven after merge. Say so in the report line ("bumped; deploy
proof tracked in <issue>").

## Template

The skeleton, with the lead paragraph that defines the entries so a later run can follow the file
without this skill, is in `notebook-template.md` → `UPDATES.md`. Create the file from it when adding
a repository's first entry.
