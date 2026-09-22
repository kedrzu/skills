---
name: stash-safety
description: >-
    How to set work aside safely in a repository that has more than one git worktree checked out.
    Stashes are shared across every worktree of a clone, so a bare `git stash pop` can apply
    somebody else's work on top of yours and silently corrupt it — a real hazard whenever parallel
    agents or several checkouts share one clone. Holds the two always-on rules, the unique-naming
    template, the restore-by-ref recipe that fails loudly on ambiguity, and the patch-file
    alternative that avoids the shared stack entirely. Read this before ANY `git stash`,
    `git stash pop` or `git stash apply`, and whenever you need to park changes to switch branches,
    test a clean tree, or prove a failure is pre-existing.
---

# Stash safety in a multi-worktree repo

Git stashes are **shared across all worktrees** of a repo (stored in the main `.git/refs/stash`, not
per-worktree). Multiple agents may be running in parallel worktrees, so a blind `git stash pop` can
apply another agent's stash on top of your working tree and silently corrupt your work.

## The two rules

1. **Always name a stash**, with a message that is both meaningful and unique — see below.
2. **Never use bare `git stash`, `git stash pop` or `git stash apply`.** They target the top of the
   stack, which may belong to another worktree. Restore by ref, matched on your own message.

These hold even for a stash you expect to pop back two commands later: the window is exactly where
another agent lands.

## Naming a stash

Name stashes with a message that is both **meaningful** (describes purpose) and **unique** (won't
collide with another agent doing the same kind of task). Generic names like
`claude-verify-preexisting` are not enough — multiple agents may be doing exactly that at the same
moment. Include a uniquifier: current branch + short purpose + a timestamp or random suffix.

```bash
# template
git stash push -m "claude/<branch>/<purpose>/$(date +%s)-$RANDOM"
# concrete example
git stash push -m "agent/fix-flaky-upload-spec/verify-preexisting-tests/1715000000-12345"
```

## Restoring your stash

Find your exact message, then pop by ref — do not assume `stash@{0}` is yours, another agent may have
stashed in between:

Match the **whole** message and abort unless exactly one stash matches. `grep -F` matches substrings,
so a message that is a prefix of another agent's (`…/1715000000-123` inside `…/1715000000-1234`) would
match theirs too, and `head -1` would then silently pop it. Ambiguity here means applying someone
else's work on top of yours, so it must fail loudly rather than pick.

```bash
msg="<your full message>"                              # exactly what you passed to -m
git stash list                                         # eyeball it first
refs=$(git stash list --pretty='%gd %gs' \
    | awk -v m="$msg" '{ ref=$1; sub(/^[^ ]* /, ""); sub(/^On [^:]*: /, ""); if ($0 == m) print ref }')
n=$(printf '%s' "$refs" | grep -c . || true)
if [ "$n" -ne 1 ]; then
    echo "Expected exactly 1 stash matching '$msg', found $n — aborting." >&2
else
    git stash pop "$refs"
fi
```

## Preferred alternative — don't touch the shared stack at all

When the flow is linear and short-lived, a snapshot leaves nothing in the shared stash stack.

Snapshot **all three** kinds of local state, not just unstaged tracked changes: `git diff` alone omits
anything you have staged, and untracked files are in neither. Note what the naive recipe actually does
— `git checkout -- .` restores the worktree *from the index*, so it does not discard staged work and
does not remove untracked files. The failure mode is therefore not silent loss but a tree that is still
dirty when you "do the thing"; it turns into real loss the moment someone reaches for `reset --hard` or
`clean` to get the clean slate the recipe implied.

```bash
snap=/tmp/<unique-name>
mkdir -p "$snap"
git diff HEAD > "$snap/tracked.patch"                  # staged AND unstaged, unlike plain `git diff`
git ls-files --others --exclude-standard -z \
    | tar --null -czf "$snap/untracked.tgz" -T -       # untracked, which no patch would carry

git reset --hard HEAD && git clean -fd                 # DESTRUCTIVE — only after both files exist
# ... do the thing ...
git apply "$snap/tracked.patch"
tar -xzf "$snap/untracked.tgz"
```

If you would rather not run a destructive clean at all, require the index to be clean and no untracked
files up front (`git status --porcelain` empty except your unstaged edits) and stay with the plain
`git diff` + `git checkout -- .` pair — but then say so explicitly instead of assuming it.
