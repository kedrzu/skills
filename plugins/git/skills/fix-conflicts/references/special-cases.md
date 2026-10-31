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

Never hand-merge a file a tool generates. For checked-in codegen output, clear the conflict with
either side, `git add` it, and after the whole operation completes (Phase 4) re-run the generator.
If something added on one side is missing afterwards, the **source** merge dropped it — fix that
conflict and regenerate. The generated file is derived; its source is the truth.

### Lockfiles (`bun.lock`, `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `Cargo.lock`, `poetry.lock`, `go.sum`, …)

The pick of side is NOT irrelevant: the installer keeps every version still satisfying the manifest
from the lockfile you start from, and resolves everything else fresh to the latest in range — a
version nobody tested. Where the project pins versions, the lockfile is what guarantees nothing
moved. So start from the side whose versions are already verified, and surface what is new.

1. **Save both sides** before clearing the conflict, from the index:

   ```bash
   S=$(mktemp -d)
   git show :2:<lock> > $S/stage2.lock   # merge: current branch. rebase/cherry-pick: the branch you replay ONTO
   git show :3:<lock> > $S/stage3.lock   # merge: the incoming branch. rebase/cherry-pick: the commit being replayed
   ```

2. **Clear it with the target side** — the branch being integrated into (main / upstream), whose
   lockfile was already verified there:

   - merge into the target (you are on main): `git checkout --ours <lock>`
   - merge of the target into your branch: `git checkout --theirs <lock>`
   - rebase onto the target: `git checkout --ours <lock>` (`--ours` is the upstream mid-rebase —
     the opposite of the usual swap intuition)
   - cherry-pick onto the target: `git checkout --ours <lock>`

   Then `git add <lock>`.

3. **Manifest conflict on the same dependency's version** (`package.json`, `Cargo.toml`, …): take the
   higher version, unless a commit on either side (`git log -S'<version>' -- <manifest>`) says the
   version is deliberately held back or reverted (a known-broken release) — then escalate.

4. **During a rebase**, regenerate at each replayed commit that conflicts on the lockfile and
   `git add` it before `--continue`; otherwise every later commit re-conflicts.

5. **After the operation completes**, regenerate with the project's install command, then list every
   `name@version` in the result that appears in NEITHER saved lockfile — those were resolved fresh:

   ```bash
   # the regex depends on the lockfile format; this one matches bun.lock entries ("name@1.2.3")
   pairs() { grep -oE '"(@[^/"]+/)?[^"@/ ]+@[0-9][^" ]*"' "$1" | tr -d '"' | sort -u; }
   pairs <lock> > $S/result.txt
   sort -u <(pairs $S/stage2.lock) <(pairs $S/stage3.lock) > $S/saved.txt
   comm -23 $S/result.txt $S/saved.txt
   ```

   Report the list in the resolution summary; Phase 5 verifies it. If a fresh version belongs to a
   package one side had locked at another version, re-pin to that side's version (the manifest's
   exact version, or the project's override mechanism), regenerate, and re-run the comparison, rather
   than accepting the fresh one.
