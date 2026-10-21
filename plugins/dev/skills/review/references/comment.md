# The comment contract

Read by `/dev:review`, which writes these comments, and by `/dev:fix-pr-comments`, which reads them.

## Everything the owner reads is inline

Anchored to a line of code, on the PR. Top-level PR comments do not appear in the Files-changed
view, which is where he works, so nothing he must act on goes there. The top-level comments are the
runs' summaries — `## 🤖 Review summary` after a review, `## 🤖 Fix summary` after a fix run: the
history of what each round found and fixed, which he skims later without opening the code. There is
no verdict comment, no guide comment.

## Two layers

The top layer is his, the collapsed block is the fixing agent's, and he should be able to act on the
comment — fix it, or resolve it and move on — without ever opening the block.

**The human layer is in the owner's language (as `review/SKILL.md` defines it); the `<details>`
block is English.** The top layer exists only for him to read, and that is its whole function; the
block is read by an agent, so it stays English. Technical terms stay English in both.

```markdown
## 🚨 BLOCKING — data-integrity
_Correctness · fix adds ~6 lines_

**Two tabs submitting the consent form create two consent rows.**

The existence check and the insert are not in one transaction and nothing ties the pair together,
so a patient who clicks Save twice ends up with two consent records. A later read takes whichever
comes back first.

<details><summary>🤖 Details for the fixing agent</summary>

Check this still holds before changing anything — if the code has moved, say so instead of fixing.

`src/consent/ConsentCreateCommand.ts:42` reads, `:51` inserts, with no enclosing
`db.transaction`. No unique index on `(patientId, consentType)` in `src/schema/consent.ts:18`.

Fix: add the unique constraint and handle the conflict, or put check and insert in one transaction.
</details>
```

|Part|Carries|
|-|-|
|Line 1|`🚨 BLOCKING` or `💡 SHOULD FIX`, then the category — the scan line|
|Line 2|provenance and cost: which axis found it, and where a finding rests on a rule, which rule (`Security · <the project's rule source> → audit at business boundary`, `Spec · spec §3`); then whether the fix adds or removes roughly how many lines|
|Bold line|the claim, in plain words — no file paths, no type names|
|Paragraph|what goes wrong, for whom and when|
|`<details>`|the staleness check, the citations, the proposed fix — he never has to open it|

**The forcing function:** if the paragraph cannot be written without a file path or a step-by-step
trace, the finding is not understood well enough to post. That makes readability a property of the
finding rather than of the formatting, which is what stops the shape degrading into a template
filled with the same unreadable prose.

## Posting

`review/scripts/post_review_comment.py` builds this shape and prepends the staleness sentence
itself. Its invocation and input are in the review skill's step 5 and in the script's `--help`. A
path inside a submodule is relative to that submodule's root and goes on that submodule's PR.
Every finding one run posts goes out as one GitHub review per PR (`review/scripts/pr_review.py`), so
he gets one entry per run rather than one per comment; the summary follows as a top-level comment on
every PR the run reviewed.

## Who wrote a comment

A comment is ours if its body starts with `## 🚨 BLOCKING` or `## 💡 SHOULD FIX` for a finding, `## 🤖`
for an answer to one or a run's summary — or, on an older PR, with a legacy `## 💡 NIT` / `## 🚨 CRITICAL ISSUE` /
`## ⚠️ IMPORTANT` / `## 💡 MINOR` / `## 🔍 ISSUE` / `## 👀 HEADS UP` / `## 🧭 FLOW` header. Everything
else on the PR is the owner's. Agents post with his GitHub token, so `author.login` proves nothing:
the header is the authorship test. It holds only among comments from authors with write access to
the repository (and from GitHub Apps installed on it), because anyone can type a header: the fetch
scripts drop every other comment before reading it, so a stranger's comment is never an ask and
never settles one. This file is its canonical definition. In this plugin, `review/scripts/pr_stack.py`
holds the header list both fetch scripts read; `review/scripts/post_review_comment.py` writes the
finding headers, `fix-pr-comments/scripts/reply_and_resolve.py` writes and looks up `## 🤖`, and
`review/scripts/pr_review.py` reads the list to tell a leftover pending review of ours from his own
draft. A change here is a change in all four.

## How a comment gets answered

A fix answers with a `## 🤖` reply on the thread itself, and the thread is resolved at once.
`fix-pr-comments/scripts/reply_and_resolve.py` does that for a whole run in one call, published as
one review per PR. He signs off in chat, where the run lists every fix, so nothing is left on GitHub
for him to clear; that the fix may outdate the thread and hide it from Files changed no longer
matters, because nothing there is waiting on him.

|Thread state|Means|
|-|-|
|unresolved, no reply|**consent** — the comment stands and gets fixed|
|unresolved, with a reply from him|**settled by what he wrote** — not consent, and not a fresh claim to assess|
|resolved, with our `## 🤖` reply|fixed or answered; never re-raise what the reply reports|
|resolved, with no reply of ours|his **veto**: he read it and said no. It does not come back|
|our `## 🤖` answer as a comment of its own, from an older run|its fix is done; with a reply of his under it, his reply is the ask|

A reply from him is an instruction, not a claim to be assessed: a comment naming a change is the
ask; a comment asking whether something holds wants an answer rather than an edit.
