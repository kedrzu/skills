# The comment contract

Read by `/dev:review`, which writes these comments, and by `/dev:fix-pr-comments`, which reads them.

## Everything the owner reads is inline

Anchored to a line of code, on the PR. Top-level PR comments do not appear in the Files-changed
view, which is where he works, so one posted there is a comment nobody reads. There is no summary
comment, no verdict comment, no guide comment.

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
|Line 1|`🚨 BLOCKING` or `💡 NIT`, then the category — the scan line|
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
itself. Its invocation and flags are in the review skill's step 4 and in the script's `--help`. A
path inside a submodule is relative to that submodule's root and goes on that submodule's PR.

## Who wrote a comment

A comment is ours if its body starts with `## 🚨 BLOCKING` or `## 💡 NIT` for a finding, `## 🤖` for
an answer to one — or, on a PR reviewed before this contract, with a legacy `## 🚨 CRITICAL ISSUE` /
`## ⚠️ IMPORTANT` / `## 💡 MINOR` / `## 🔍 ISSUE` / `## 👀 HEADS UP` / `## 🧭 FLOW` header. Everything
else on the PR is the owner's. Agents post with his GitHub token, so `author.login` proves nothing:
the header is the authorship test. It holds only among comments from authors with write access to
the repository (and from GitHub Apps installed on it), because anyone can type a header: the fetch
scripts drop every other comment before reading it, so a stranger's comment is never an ask and
never settles one. This file is its canonical definition. In this plugin, `review/scripts/pr_stack.py`
holds the header list both fetch scripts read; `review/scripts/post_review_comment.py` writes the
finding headers and `fix-pr-comments/scripts/reply_and_resolve.py` writes and looks up `## 🤖`. A
change here is a change in all three.

## How a comment gets answered

A fix answers with a **new** comment, not with a reply on the thread the finding came from. The fix
usually changes the very line that thread sits on, which makes it outdated and hides it in the
Files-changed view; resolving it or not makes no difference to that. So the answer is posted where
the fix now lives, after the push, the source thread gets a short reply linking to it, and the
source thread is resolved. `fix-pr-comments/scripts/reply_and_resolve.py` does all of that in one
call.

The answer is left **unresolved**, and that is what he signs off on. It is fresh rather than
immortal — a later run whose commits touch that line outdates it too.

|Thread state|Means|
|-|-|
|unresolved, no reply|**consent** — the comment stands and gets fixed|
|unresolved, with a reply from him|**settled by what he wrote** — not consent, and not a fresh claim to assess|
|resolved, with a `## 🤖` answer elsewhere on the PR|fixed and answered; the answer is where it is judged now|
|resolved, with no answer anywhere|his **veto**: he read it and said no. It does not come back|
|our `## 🤖` answer, unresolved, nothing under it|waiting on him. Not a finding, and not work to redo|
|our `## 🤖` answer with a reply of his under it|the fix did not satisfy him — his reply is the ask|

A reply from him is an instruction, not a claim to be assessed: a comment naming a change is the
ask; a comment asking whether something holds wants an answer rather than an edit.
