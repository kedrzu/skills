#!/bin/zsh
# Workspace setup for a worktree (Paseo runs it for every new worktree — see paseo.json).
# Nothing to build here: plugin servers fetch their own dependencies with `bun --install=force`.
set -e

REPO_ROOT=$(git rev-parse --path-format=absolute --git-common-dir | sed 's|/\.git\(/.*\)*$||')
CURRENT_DIR=$(pwd -P)

# In a plain clone the branch you are on is a deliberate choice, and setup has no business merging
# into it.
if [ "$CI" = "true" ] || [ "$REPO_ROOT" = "$CURRENT_DIR" ]; then
    exit 0
fi

# --- Worktree: catch up with origin/main ---

# A worktree is cut from the *local* `main` ref, which may have fallen behind origin.
echo ""
echo "🔄 Catching up with origin/main..."
echo ""

git fetch --quiet origin main

# Fast-forward the local `main` too, so the NEXT worktree is not cut from a stale base. Git refuses
# to move a branch another worktree holds, so ask that worktree — and only when clean.
MAIN_WORKTREE=$(git worktree list --porcelain \
    | awk '/^worktree /{wt=$2} /^branch refs\/heads\/main$/{print wt; exit}')

if [ -z "$MAIN_WORKTREE" ]; then
    git fetch --quiet origin main:main \
        || echo "⚠️  Local main not fast-forwarded (diverged from origin/main)."
elif [ -n "$(git -C "$MAIN_WORKTREE" status --porcelain)" ]; then
    echo "⚠️  Local main left as it is — $MAIN_WORKTREE has uncommitted changes."
else
    git -C "$MAIN_WORKTREE" merge --ff-only --quiet origin/main \
        || echo "⚠️  Local main not fast-forwarded (diverged from origin/main)."
fi

# A fresh worktree fast-forwards. A re-run on a branch carrying real work may not merge cleanly; a
# conflict under `set -e` would leave a half-merged tree, so an unclean merge is rolled back and
# reported instead.
if git merge --quiet --no-edit origin/main; then
    echo "✅ Up to date with origin/main"
else
    git merge --abort 2> /dev/null || true
    echo "⚠️  Could not merge origin/main into $(git branch --show-current) — merge it by hand."
fi
