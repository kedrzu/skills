---
name: review
description: >-
    Reviews the branch's diff and posts what it finds as inline PR comments: five finder axes in
    parallel, one pass that tries to refute everything they found, and only the survivors get
    published. ON-REQUEST ONLY. Use when the user says "review my changes", "check my code",
    "review this PR", "/dev:review", or any variation of wanting code reviewed — any of these
    phrases in any language counts. NEVER runs automatically inside the dev pipeline (/dev:fix,
    /dev:task, /dev:feature, /dev:build) — a pipeline reviews only when the user asks for it in so
    many words. Do NOT use for verification (types, lint, tests, builds) — that is the project's
    verify skill, and the finders assume it is already green. Do NOT use for acting on comments
    already on a PR — that is /dev:fix-pr-comments.
disable-model-invocation: true
---

# Review

Catches what the mechanical checks cannot: a logic bug, a requirement the code does not meet, a
privacy or authorization gap, a rule the change breaks with no neighbour to imitate. Types, lint,
tests and builds belong to the project's `verify` skill and are assumed green — never re-run them,
never report what they catch.

The shape is fixed: the same agents, in the same order, every run. No modes, no skips, no cap that
reroutes control flow. The judgement inside each step belongs to the agent running it.

The output is inline PR comments and nothing else — no report, no verdict, no reading guide. **An
unresolved thread is something waiting on him** — a finding he has not judged, or a fix he has not
accepted — so nothing unresolved means nothing is waiting, rendered natively by GitHub's count of
them. Publishing a comment effectively decides the code will change — his only cheap answer is to
resolve the thread — so nothing is published that has not survived step 3's attempt to refute it.

**Prerequisites.** The project is on GitHub and `gh` is installed and authenticated: the scripts
read the PR, its threads and its chain through the GitHub API, including the Stacks API, which
returns `[]` for an ordinary PR on any repository. Pushing and checking out go through the
project's `git-workflow` skill — what it must provide, and that a missing one stops the run, is
`${CLAUDE_PLUGIN_ROOT}/skills/pipeline/references/contracts.md`.

**The owner's language** is the language the project's `CLAUDE.md` names for human-facing text, or,
without such a rule, the language the owner writes to you in. Everything below written for him —
the comments' human layer, the refuted list, the closing lists in chat — is in it.

## 1. Context

Push first, through `git-workflow` → **checkpoint**, pushing only — review never commits; comments
must land on the reviewed commits. Then:

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

Pick up the spec too, if one is on disk. They are named `.context/specs/<YYYY-MM-DD>-<topic>.md` —
**no issue id in the filename**, so list the directory and pick the one whose topic matches this
branch. Pass it whole; summarising it loses the acceptance criteria the spec axis checks against. If
nothing matches, say so rather than passing the nearest file — the spec axis behaves differently
when it knows there is no spec.

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
security & compliance, consistency & reuse, and the narrow testing axis. Each gets that file's path
(expanded — a subagent cannot resolve `${CLAUDE_PLUGIN_ROOT}`) and its own section of it, the diff
files it is reading, the PR description and the spec. Nothing else: finders open the skills they
need themselves.

On a chain the spec axis gets **every** node's description together — `fetch_pr_description.py`
returns them in `nodes`.

The axes split by whether their standard is local or global:

|Axis|Runs|Reads|
|-|-|-|
|Correctness|per node|that node's `diffs/nodes/<k>/`|
|Consistency & reuse|per node|"|
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
`${CLAUDE_PLUGIN_ROOT}/skills/review/references/verify.md` (pass the expanded path), and tell it the
owner's language. It attacks each one against the code as it stands, and what it cannot prove does
not exist. Survivors come back with the thing the finder usually did not write down — what
concretely goes wrong, for whom and when — plus whether the fix adds or removes code, and whether it
is blocking or a nit.

One verifier over the whole chain, whatever the node count: splitting it loses the duplicates between
nodes and the ability to kill a finding a higher node already repaired.

## 4. Post

Step 1 already told you whether there is a PR. With `prNumber: null` there is nowhere to post: give
the findings in chat, say the branch has no PR, and stop — the fetch below exits non-zero without
one.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/fetch_pr_comments.py    # every node's threads, resolved included, + its headSha
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
|unresolved, one of our own `## 🤖` answers|a fix from an earlier run, waiting for him to accept it. It is an answer, not a finding, and the work behind it is done — never re-raise what it reports|

Post each surviving finding in the shape
`${CLAUDE_PLUGIN_ROOT}/skills/review/references/comment.md` defines (pass the expanded path to a
poster agent), against the `prNumber` and `headSha` of **the node it belongs to**:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/post_review_comment.py \
    --repo <owner/repo> --pr <n> --sha <headSha> \
    --file src/consent/ConsentCreateCommand.ts --line 42 \
    --severity blocking --category data-integrity \
    --provenance "Correctness" --delta "adds ~6 lines" \
    --claim "<owner's language, one sentence>" \
    --consequence "<owner's language, what goes wrong, for whom, when>" \
    --details "<English, citations and the proposed fix>"
```

`--line 0` posts at file level. The script prepends the staleness sentence itself.

Which node a finding belongs to is not a judgement: **a finding belongs to the node whose diff holds
its lines** — look the file up in that node's `manifest.txt` and check the line is inside one of its
hunks. Anchored anywhere else GitHub matches nothing, and the poster degrades the comment to file
level or is rejected outright.

A finding whose fix spans several nodes goes on the **lowest node that must change**, once — fixing
a lower node cascades upward anyway, so saying it twice buys nothing but threads.

Caps are applied after that dedup, so an already-posted nit does not consume one: **at most five
nits whose fix adds code, per node.** Findings that remove code are uncapped and blocking ones are
never dropped. Past five, keep the ones you would defend.

A finding on a path inside a submodule belongs on the submodule's own PR. Every key of
`submodules.json` is a submodule whose gitlink this chain moved, and the file gives you only its
path and remote — not its PR. Resolve that PR the same way you resolved the parent's, from inside
the submodule:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/fetch_pr_description.py --cwd <path>    # → its repo, prNumber
python3 ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/fetch_pr_comments.py    --cwd <path>    # → its headSha, threads
```

Post with those values and with `--file` relative to the submodule root — the `<path>/` prefix
stripped, or GitHub matches no line in that PR's diff. It carries its own nit budget: a separate PR,
read at a separate moment. No PR for the submodule: report those findings in chat.

Finish in chat, in the owner's language, with three **lists** — not three counts. He reads this to
judge the review rather than the code, and *"5 refuted"* tells him the pass ran and nothing about
whether it ran well. One line per finding:

- **posted** — the claim as published, plus the link to the comment;
- **refuted** — the claim, and what the verifier proved against it;
- **dropped past the cap** — the claim, and nothing else; the cap is the reason.

With more than one node, say which node each posted line landed on — he reads them one PR at a time.
It always prints, whatever the numbers: no threshold, no short version, no skipping it when nothing
was refuted.

If a survivor cannot be anchored to a line — the same missing check across three handlers, a premise
the plan rested on that did not hold, a chain-level gap that belongs to no single node — say it there
in a sentence or two; chat is the only route it has. It has to be as concrete as any comment: a file,
a rule, a decision. **An objection to the approach itself does not belong here at all** — that is a
planning question, and raising it after implementation asks for a rewrite. Nothing else goes to chat.

## References

- `${CLAUDE_PLUGIN_ROOT}/skills/review/references/axes.md` — the five finder briefs. Step 2 hands each agent its own section.
- `${CLAUDE_PLUGIN_ROOT}/skills/review/references/verify.md` — the refutation brief. Step 3.
- `${CLAUDE_PLUGIN_ROOT}/skills/review/references/comment.md` — the comment contract, shared with `/dev:fix-pr-comments`. Step 4.
