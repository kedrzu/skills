---
name: review
description: Review this branch's diff — fix what nobody would argue with, post the rest that survives a refutation pass as inline PR comments.
disable-model-invocation: true
---

# Review

Catches what the mechanical checks cannot: a logic bug, a requirement the code does not meet, a
privacy or authorization gap, a rule the change breaks with no neighbour to imitate. Types, lint,
tests and builds belong to the project's `verify` skill and are assumed green — never re-run them,
never report what they catch.

The shape is fixed: the same agents, in the same order, every run. No modes, no skips, no cap that
reroutes control flow. The judgement inside each step belongs to the agent running it.

A finding that survives step 3's attempt to refute it leaves by one of two exits. **What he would
never argue with is fixed here, without him** — a written rule broken, a copy of code that already
exists, a plain code smell — when the fix removes code or adds none and changes no behaviour. The agent that wrote the code
cannot see these in its own work, and their cost is not harm but recurrence: every later reviewer
trips over the same thing again. **The rest goes to him, inline on the PR** — no report, no verdict,
no reading guide. An unresolved thread is something waiting on him, so nothing unresolved means
nothing is waiting, rendered natively by GitHub's count of them; and since his only cheap answer is
to resolve it, publishing one effectively decides the code will change.

**Prerequisites.** The project is on GitHub and `gh` is installed and authenticated: the scripts
read the PR, its threads and its chain through the GitHub API, including the Stacks API, which
returns `[]` for an ordinary PR on any repository. Pushing and checking out go through the
project's `git-workflow` skill — what it must provide, and that a missing one stops the run, is
`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/contracts.md`.

**The owner's language** is the one named for human-facing text in his uncommitted `CLAUDE.local.md`
at the project root, else in the project's `CLAUDE.md`, else the one he writes to you in. Everything
written for him is in it. Name it in the brief of every agent that writes for him — a subagent sees
only your prompt.

## 1. Context

Push first, through `git-workflow` → **checkpoint**, pushing only — comments must land on commits
the PR has. The only commits review makes are its own fixes, in step 4. Then:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/generate_diffs.py          # → .context/reviews/<branch>/diffs/
python3 ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/fetch_pr_description.py    # → {repo, branch, prNumber, title, body, url} + nodes
```

`generate_diffs.py` writes one `.diff` per changed file plus `manifest.txt` (source path → diff
file), `full.diff`, `submodules.json` and `nodes.json`; files marked `linguist-generated` are
filtered out already. If it reports no changed files, there is nothing to review — say so and stop.

Either script exiting non-zero stops the run: both refuse to guess what the nodes are, because
guessing wrong means posting the whole chain's findings on one PR. Report what it said.

If the push fails, `git status --porcelain` is non-empty, or `HEAD` ≠ `@{u}`, stop and report it: a
comment anchored to a commit that is not on the PR lands nowhere.

Pick up the spec too, if one is on disk: `.context/specs/<YYYY-MM-DD>-<topic>.md`, with no issue id
in the name, so pick the one whose topic matches this branch. Pass it whole — a summary loses the
acceptance criteria. If nothing matches, say so rather than passing the nearest file.

### The chain, and the node

`nodes.json` next to the diffs says whether this task landed as a chain of stacked PRs. **The node is
where a finding is published** — a comment only anchors inside its own PR's diff — **and the chain is
what gets read**, because a node judged on its own yields findings the node above already fixed. So
each node has its own diff set under `diffs/nodes/<k>/`, generated `base...node` exactly as GitHub
computes that PR's diff, while `diffs/` at the root carries the whole chain. An unstacked branch is
not a mode but the same thing with one node: a single entry whose `diffs` is `.`, read as the chain
and the node at once.

The files a finder opens are the working tree, so the tree has to be the chain's tip. If `nodes.json`
reports `currentNode` below `topNode`, stop and say so; `git-workflow` → **stack** checks out the
chain's tip.

## 2. The finders, in parallel

One agent per axis in `${CLAUDE_PLUGIN_ROOT}/skills/review/references/axes.md` — correctness, spec,
security & compliance, conformance & duplication, and the narrow testing axis. Each gets that file's path
(expanded — a subagent cannot resolve `${CLAUDE_PLUGIN_ROOT}`) and its own section of it, the diff
files it is reading, the PR description and the spec. Nothing else: finders open the skills they
need themselves.

On a chain the spec axis gets **every** node's description together — `fetch_pr_description.py`
returns them in `nodes`.

The axes split by whether their standard is local or global:

|Axis|Runs|Reads|
|-|-|-|
|Correctness|per node|that node's `diffs/nodes/<k>/`|
|Conformance & duplication|per node|"|
|Testing — deleted coverage|per node|"|
|Spec|once over the chain|`diffs/` at the root|
|Security & compliance|once over the chain|"|

Tell each per-node finder which node it has.

All of them run every time. A skip would change which lenses ran from one review to the next, and
the lenses barely overlap — across 617 locations flagged by four agentic review tools, 93% were
caught by exactly one of them. Keep their results separate to the end: do not rank or merge across
axes, or a pass on one masks a failure on another.

## 3. One verifier: try to refute

Hand every finding, all axes together, to a single agent running
`${CLAUDE_PLUGIN_ROOT}/skills/review/references/verify.md` (pass the expanded path), tell it the
owner's language, and give it the memory when it exists: `.context/reviews/<bottom>/memory.md`,
written by step 6 of earlier runs, `<bottom>` being the bottom node's branch from `nodes.json` with
`/` replaced by `-`, as `generate_diffs.py` names its directory. **Only the verifier gets the
memory.** A finder that saw it would steer away from ground already covered, and fresh eyes are
what find what earlier runs missed; the verifier is where a finding already settled is recognised and dropped.

It attacks each finding against the code as it stands, and what it cannot prove does not exist.
Survivors come back with what the finder usually did not write down — the mechanism and every place
in the change it occurs, and what concretely goes wrong — plus their exit: fixed here, or brought to
him as blocking or should-fix.

One verifier over the whole chain, whatever the node count: splitting it loses the duplicates between
nodes and the ability to kill a finding a higher node already repaired.

## 4. Fix what needs nobody

Fix the survivors whose exit is *fixed here* the way `/dev:fix-pr-comments` fixes threads — its
steps 2 to 5 in `${CLAUDE_PLUGIN_ROOT}/skills/fix-pr-comments/SKILL.md`: the same grouping rule, the
same fixer brief, one scoped `verify` over every fix, then `prune` as a fix run, bottom-up on a
chain. Each fixer gets its finding's mechanism and every place it occurs, and fixes all of them; a
duplicate of something that already exists is removed across the whole repository, not only in this
change. A fixer that finds the fix needs a choice, changes behaviour or adds code after all
hands it back unapplied, and it goes to him in step 5 as a should-fix finding.

Commit them through `git-workflow` → **checkpoint**, one commit per group, and push before anything
is posted. The fixes move lines under the findings left for him, so after a push re-run
`generate_diffs.py` as you ran it and re-anchor each of those findings on the code as it now stands:
step 5 posts on the pushed head and places them by the fresh `manifest.txt`.

## 5. Post

Step 1 already told you whether there is a PR. With `prNumber: null` there is nowhere to post: give
the findings in chat, say the branch has no PR, and stop — the fetch below exits non-zero without
one.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/fetch_pr_comments.py    # every node's threads, resolved included
```

Give the poster the survivors and the existing threads, and let it decide what is **genuinely new** —
new against the threads already there and against what it has already posted this run. There is no
matching rule for this. Dedup is chain-wide, over every node in `nodes`: a finding already raised
low in the chain is not new because the same lines also show up in a diff further up. Read the
threads and judge, including what he wrote under them:

|Thread|Means|
|-|-|
|resolved|his "no", and it stands. Re-deriving it from another call site or another axis, in different words, is the failure to avoid|
|unresolved, with a reply arguing it down|also settled — `humanReplies` carries what he wrote, and it is there to be read|
|unresolved, no reply|nothing was said; a genuinely new finding may go next to it|
|resolved with our `## 🤖` reply, or an older `## 🤖` answer of ours|a fix or answer from an earlier run — the work behind it is done; never re-raise what it reports|

Post the findings whose exit is *to him* in the shape
`${CLAUDE_PLUGIN_ROOT}/skills/review/references/comment.md` defines. A poster agent needs the
expanded path to that file and the owner's language. Each finding goes on the `prNumber` of **the
node it belongs to**. All of them, from every node and every submodule, go into one file and one
call:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/post_review_comment.py \
  --findings <findings.json> --summary <summary.md> --prs <owner/repo#n> [<owner/repo#n> …]
```

```json
[{"repo": "<owner/repo>", "pr": 12, "file": "src/consent/ConsentCreateCommand.ts", "line": 42,
  "severity": "blocking", "category": "data-integrity", "provenance": "Correctness",
  "delta": "adds ~6 lines", "claim": "<owner's language, one sentence>",
  "consequence": "<owner's language, what goes wrong, for whom, when>",
  "details": "<English, citations and the proposed fix>"}]
```

The script publishes **one GitHub review per PR** that has findings — posted one at a time they
would reach him, on his phone too, as a wall of separate entries. Then it posts the run's summary as
a top-level comment on every PR in `--prs`, findings or not: the record that the run happened, a run
that found nothing included. It shows only in the Conversation tab, not where he works.
`summary.md` holds the **fixed without him** and **refuted** lists below and one count line,
`review run <n>: <a> to owner (<b> blocking), <c> fixed, <d> refuted, <e> already settled`. Leave
the **posted** list out: the script appends it, because the links exist only once it has posted.
`line: 0` posts at file level. The script prepends the staleness sentence itself. If it stops
because he has a draft review of his own open on that PR, ask him to submit or discard it, because
publishing ours would publish his.

Which node a finding belongs to is not a judgement: **a finding belongs to the node whose diff holds
its lines** — look the file up in that node's `manifest.txt` and check the line is inside one of its
hunks. Anchored anywhere else GitHub matches nothing, and the poster degrades the comment to file
level or is rejected outright.

A finding whose fix spans several nodes goes on the **lowest node that must change**, once — fixing
a lower node cascades upward anyway, so saying it twice buys nothing but threads.

A finding on a path inside a submodule belongs on the submodule's own PR. `submodules.json` lists
each submodule whose gitlink this chain moved, by path and remote; resolve its PR from inside it:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/fetch_pr_description.py --cwd <path>    # → its repo, prNumber
python3 ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/fetch_pr_comments.py    --cwd <path>    # → its threads
```

Post with those values and with `file` relative to the submodule root — the `<path>/` prefix
stripped, or GitHub matches no line in that PR's diff. No PR for the submodule: report those
findings in chat.

Finish in chat, in the owner's language, with three **lists** — not three counts. He reads this to
judge the review rather than the code, and *"5 refuted"* tells him the pass ran and nothing about
whether it ran well. One line per finding:

- **fixed without him** — what changed and in how many places; it is where he looks when something
  later seems off, and how he tells whether the line between the two exits sits in the right place;
- **posted** — the claim as published, plus the link the script printed for it;
- **refuted** — the claim, and what the verifier proved against it. Findings dropped as already
  settled are counted, not listed: he has seen them before.

With more than one node, say which node each posted line landed on. The lists always print,
whatever the numbers.

If a survivor cannot be anchored to a line — the same missing check across three handlers, a premise
the plan rested on that did not hold, a chain-level gap that belongs to no single node — say it there
in a sentence or two; chat is the only route it has. It has to be as concrete as any comment: a file,
a rule, a decision. **An objection to the approach itself does not belong here at all** — that is a
planning question, and raising it after implementation asks for a rewrite. Nothing else goes to chat.

Then say whether review is finished. It is when this run and the one before it brought him nothing
blocking — the memory holds each run's `review run <n>` line; a `/dev:deliver` milestone pass's
`review M<k> pass <p>` line is not a run. Asking for nothing at all would never end: fresh
reviewers always find a few more things worth fixing.

## 6. Record the run

Append to the memory file of step 3, one line each, with the commit it was settled on:
every refuted finding and what refuted it, every finding fixed here, and the run's count line. What
was posted stays out — the PR's threads are its memory. Nothing else holds this file; lost, it costs
the next verifier a second refutation, nothing more.

## References

- `${CLAUDE_PLUGIN_ROOT}/skills/review/references/axes.md` — the five finder briefs. Step 2 hands each agent its own section.
- `${CLAUDE_PLUGIN_ROOT}/skills/review/references/verify.md` — the refutation brief. Step 3.
- `${CLAUDE_PLUGIN_ROOT}/skills/review/references/comment.md` — the comment contract, shared with `/dev:fix-pr-comments`. Step 5.
