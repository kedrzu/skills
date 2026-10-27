# Compressing a design folder into current record and history

For a folder written before `DECISIONS.md` held only what is in force: superseded entries and stubs
sit among the live ones, live entries narrate how they changed, the journal is at the top level.
The target shape is in `decision-record.md`; this is how to get there.

**Reorganise only.** No decision changes meaning, nothing is added or dropped, and nothing
substantive rides along in the same change — the diff is how the owner reviews it, and a
reorganisation mixed with a real change hides the real change. Whatever you notice on the way (a
contradiction, a stale `Checked` note) goes into the report, not into the files.

1. **Classify every entry.** Read each `## DN` and decide: *in force*, *retired* (replaced whole,
   including stubs that only point elsewhere), or *partly replaced* (some of it still holds). The
   wording varies — "Superseded by", "That in turn superseded the first form", "Scope superseded",
   a stub whose body is a link — so judge from the content, not a keyword. Where you cannot tell
   what still holds, ask; a guess here changes the design.

2. **Restore what was cut.** Stubs and shortened entries lost their text to git. Find the last
   version that had it and copy it out whole:

   ```bash
   git log --format='%h %ad %s' --date=short -S '<a phrase from the lost text or the stub>' -- <folder>/DECISIONS.md
   git show <rev>^:<folder>/DECISIONS.md   # the file just before the cut
   ```

   When a decision was cut down in several steps, each earlier form is a separate retired form.

3. **Write `history/DECISIONS.md`.** Every retired form, whole, under its original ID, oldest first,
   each with its "Retired <date>, replaced by …" line — the date from the supersession note or the
   commit that made it.

4. **Rewrite the in-force entries** in the shape `decision-record.md` gives: claim with date and
   source, **Why** with the evidence that still supports it, **Rejected** built from the narration —
   each "this replaced …" becomes a Rejected line with the reason and a link into history. Partly
   replaced entries keep their ID and say only what holds; the earlier form goes to history. Evidence
   that only supported a retired form moves with it.

5. **Move the rest.** `git mv <folder>/JOURNAL.md <folder>/history/JOURNAL.md` so its history
   follows it. Replace the old `DECISIONS.md` preamble with the header from `decision-record.md`;
   session notes and other narrative in it, and "how we got here" passages in README and chapters,
   go to dated notes in `history/`, linked from README where a reader benefits.

6. **Repoint links**, by the rule in `decision-record.md`: a link supporting a current claim goes to
   the decision that holds now, a link about the past goes into history. Search the whole
   repository, by path as well as anchor, because code cites decisions in prose with the ID often on
   the line above the path:

   ```bash
   git grep -n '<folder>/DECISIONS.md'          # citations from anywhere, code included
   git grep -n -E 'DECISIONS\.md#d[0-9]+' -- <folder> docs   # anchors, relative links included
   git grep -n 'JOURNAL.md'                      # the journal moved too
   ```

   For each hit outside the folder, read the line before it for the ID.

7. **Check.** Every ID the old file had is in `DECISIONS.md`, `history/DECISIONS.md` or both (both
   only when partly replaced); no ID was renumbered; every `DECISIONS.md#dN` and
   `history/DECISIONS.md#dN` link in the repository lands on a heading that exists.

8. **Commit it alone**, and list in the description which IDs moved to history, which were partly
   replaced, and which outside files were repointed — the classification is the judgement call, so
   it is what the reviewer most needs to see.
