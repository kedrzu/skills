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
  "latest" at build time and pins nothing, what forces a fresh build. For a move the run must not
  make itself — a major that is a migration (a database engine, a runtime) — that it needs the
  owner's decision (below).
- **Rollout** — what must be rebuilt, recreated or redeployed for the new version to take effect,
  and any follow-up the run must create (e.g. "open a tracker issue for the deploy, blocked by this
  run's issue"). For something only the cloud builds or runs, how it gets proven after merge.
- **Verify** — how to prove the new version works, as far as it can be proven locally: the checks
  specific to this item. The project's full `verify` protocol is not repeated per entry — it runs
  once over every entry a run bumped (below).

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
4. **Bump** — follow it. One that says the move needs the owner's decision → touch nothing, follow
   "A move that needs the owner" below, go on to the next entry.
5. **Rollout** — do the local part: rebuild or recreate what runs it, so Verify tests the new
   version and not a cached old one.
6. **Verify** — the entry's own checks (an image build, a template validate, a version printed),
   not yet the full `verify` protocol: that runs once for the whole batch (below), and an entry
   whose **Verify** names it is covered by that batch run.
7. **Green** → commit through **checkpoint** (one commit per entry, named after it: "Update
   <name> to <version>"). **Red** → revert the bump, undo its local rollout (recreate the old one),
   record a **Known Issue** `<name> <version>` in the notebook as for any failed update, report
   `blocked — <error in one line>`.

When the walk is done, the entries it bumped are verified **as one batch**: one full `verify`
protocol over all their commits — several entries rebuild the same image, and a full verify per
entry would repeat e2e for each. Red → bisect as for a package batch (Phase 3): revert half the
entry commits, re-verify, narrow down to the entry that turned it red, then revert that entry and
handle it as a red entry above. Only once the batch is green, carry out the follow-ups **Rollout**
prescribes for every entry still bumped — a follow-up tracker issue is created now and linked in
the report — and report each `bumped <from> → <to>`.

What only a deployment can prove stays unproven in this run: Verify covers the local part, and
**Rollout** names how the rest is proven after merge. Say so in the report line ("bumped; deploy
proof tracked in <issue>").

## A move that needs the owner

A report line is easy to skim past week after week, so a move that needs the owner's decision,
procedure or testing gets a tracker issue, created through the project's tracker skill: one open
issue per entry, always for the newest such version, titled `Upgrade <entry name> to <version>`.
Search the open issues for that title prefix first:

- **One for this version is open** → create nothing.
- **One for an older version is open** → cancel it with a comment naming the newer version and the
  new issue, so it stays visible which version was skipped, then create the new one.
- **None** → create it.

Its description: what moves (`from → to`), the **Pinned in** location, the evidence the entry asks
for (e.g. the current version's end-of-support date) and the procedure the entry names. Report
`blocked — needs your decision: <from> → <to>, <issue>`, and list it under **Needs your decision**.

## Template

The skeleton, with the lead paragraph that defines the entries so a later run can follow the file
without this skill, is in `notebook-template.md` → `UPDATES.md`. Create the file from it when adding
a repository's first entry.
