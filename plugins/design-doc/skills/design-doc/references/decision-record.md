# The decision record

`DECISIONS.md` is what holds now; `history/` is everything that held once. The split exists for two
readers at once: an agent arriving cold has to see the current design without wading through how it
got there, and an agent about to reopen an area has to be able to read — without git — that its idea
was already built, dropped and replaced. A stub pointing at git history serves neither: nobody
follows it, and the agent then calls a decision pointless without knowing what it replaced.

## `DECISIONS.md`

It opens with a short header — what the file is, and the one rule an agent must follow before acting
on it:

```markdown
# Decisions

The decisions in force: grepped and re-entered, never read front to back. A heading is the
decision's ID alone, so `DECISIONS.md#d3` keeps resolving after the wording is sharpened. Retired
decisions, the journal and notes from reviews live in [history/](history/).

**Before proposing a change in an area, read the Rejected lines of its decisions and the history
they link to.** Reopening a rejected option is right when its premise changed; repeating it without
knowing it was rejected is not.
```

Each entry carries the claim, why it holds, and what was turned down — and never how it changed:

```markdown
## D12

**The router branches on the kind of message, not on the system that sent it.** (2026-08-04, owner)

**Why.** A branch per sender grows with every integration, while the set of things a message can
ask for is small and stable. Every source the 2026-08-04 sweep threw at it mapped onto an existing
kind.

> **Checked 2026-08-04:** Sentry, GitHub and Linear webhooks all carry a type field the router can
> read without the sender's SDK — `src/ingress/parse.ts:40`.

**Rejected.**
- One branch per integration — every new source would add router code
  ([history](history/DECISIONS.md#d5)).
- A rules table configured per deployment — no case needed it, and it hides routing from review.
```

- **The first line** is the claim, with the date and where it came from: the owner, or a proposal of
  the design agent he has not confirmed yet.
- **Why** holds the reasons and the `Checked` evidence that *still* support the claim. Evidence that
  only supported an earlier form leaves with that form.
- **Rejected** lists every alternative that was considered, or built and later dropped — one sentence
  each with the reason, and a link when the alternative was once a decision of its own. This is
  where "what was already tried" lives; a reader who only reads this file must still learn it.
- **No narration.** "Supersedes the renewal half of D49", "the review found…", "originally this
  said…" all belong in `history/`.

## `history/`

```text
history/
  DECISIONS.md          retired decisions, full text, under their original IDs
  JOURNAL.md            append-only, one line per turn that settled something
  <YYYY-MM-DD>-<topic>.md   narrative: a review, a redesign, the "how we got here" lifted out of the story
```

`history/DECISIONS.md` has one `## DN` heading per ID it holds, so `history/DECISIONS.md#d49`
resolves. Under it, each retired form is appended whole, oldest first, each opening with one line:
when it was retired and what replaced it, linked (`Retired 2026-10-09, replaced by
[D47](../DECISIONS.md#d47).`). Nothing here is ever edited after it is written, apart from adding
the next retired form.

## Changing a decision

**IDs are never reused.** A new decision takes the next number above every ID in both files.

- **Sharpening the wording** without changing what it decides: edit the entry in place.
- **Replacing it**: write the replacement under a new ID, move the old entry's full text to
  `history/DECISIONS.md` under its own ID, and add the old answer to the new entry's **Rejected**
  with its reason and a link. Nothing stays behind in `DECISIONS.md`.
- **Replacing part of it**: rewrite the entry, under the same ID, to what still holds; move the
  prior form whole to `history/DECISIONS.md` under that ID; add the dropped part to **Rejected**
  with a link.

Then repoint every link to what moved, in the same change.

## Repointing links

A link points at whatever it is actually about. One that supports a current claim — almost every
link from README, a chapter or code — goes to the decision that holds now. Only a link that is
about the history itself goes into `history/`. After a partial replacement, links that cited the
dropped part go to history; the rest keep pointing at the rewritten entry.

Find them by the file's path, not only by anchor. Code tends to cite in prose — "(D20 in
`docs/design/bmo/DECISIONS.md`)" — often with the ID and the path on adjacent comment lines, so
`#d20` alone misses it. Search the whole repository: the folder itself, other design folders,
`docs/`, code and skill files. Afterwards, every `DECISIONS.md#dN` and `history/DECISIONS.md#dN`
link must land on a heading that exists.
