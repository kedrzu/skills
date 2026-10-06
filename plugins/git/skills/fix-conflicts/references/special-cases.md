# Conflicted paths that are not resolved by editing markers

Consumed by: `fix-conflicts` (Phase 3, Phase 6).

## Submodule pin conflicts

A submodule pin conflict is two different commit hashes for a submodule — `git status --porcelain`
shows `UU <path>` for the submodule directory and the merge output says `CONFLICT (submodule)`. There
is no text to merge; you choose one commit. `git config --file .gitmodules --get-regexp path` lists
which paths are submodules.

```bash
git ls-files -u -- <path>        # the two candidates: stage 2 = ours, stage 3 = theirs (swapped during rebase)
git -C <path> fetch
git -C <path> log --oneline <stage2-hash>..<stage3-hash>   # read BOTH candidate commit messages
git -C <path> log --oneline <stage3-hash>..<stage2-hash>
```

Default to the **newer** commit — the one that contains the other (one of the two logs above is
empty). BUT first read both messages: a message describing an **intentional rollback/revert** means
newer is wrong and the older pin is deliberate. When neither commit contains the other, the two
sides moved the submodule along diverging histories — escalate rather than dropping one side's
submodule work.

Record the chosen pin by checking the submodule out to it, THEN staging — the staged pointer follows
the submodule's working-tree HEAD, so the checkout is required, not optional:

```bash
git -C <path> checkout <chosen-hash>
git add <path>
```

**Pushing afterwards.** A resolution that only moved the pin has nothing of its own to publish in the
submodule. A resolution that edited files inside the submodule is a commit in the submodule's own
repository: commit and push it there first, then commit and push the new pointer in the parent
repository. Pushing only the parent leaves a pointer to a commit nobody else can fetch. Follow the
project's own submodule flow when it documents one.

## Generated files (lockfiles, codegen output)

Never hand-merge a file a tool generates — a lockfile (`package-lock.json`, `yarn.lock`,
`pnpm-lock.yaml`, `Cargo.lock`, `poetry.lock`, `go.sum`, …) or checked-in codegen output.
Clear the conflict with EITHER side (the pick is irrelevant because you regenerate; don't agonize over
ours-vs-theirs here, especially mid-rebase where they're swapped):

```bash
git checkout --theirs <file>   # or --ours; either works, the generator rewrites it next
git add <file>
```

After the whole operation completes (Phase 4), regenerate it from its merged sources with the
project's own command (the package manager's install, the codegen script), then confirm the merge
kept every change from both sides:

```bash
git diff --name-only           # the generated file should be the only churn; source diffs must be intentional
```

If something added on one side is missing after regeneration, the merge of the **source** dropped it
(for a lockfile: a manifest such as `package.json` or `Cargo.toml`) — go back and merge that source
conflict correctly, then regenerate again. The generated file is derived; its source is the truth.
