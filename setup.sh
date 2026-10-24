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

# The developer's personal, gitignored instructions (e.g. the language agents write to him in).
# Being uncommitted, it is otherwise missing from every fresh worktree.
if [ -f "$REPO_ROOT/CLAUDE.local.md" ]; then
    cp "$REPO_ROOT/CLAUDE.local.md" CLAUDE.local.md
    echo "✅ CLAUDE.local.md copied from main repo"
fi

# Plugins from other marketplaces that .claude/settings.json enables. A project-scope install is
# recorded per project path, so in a fresh worktree they are enabled but not installed: they do not
# load, and every skills-dir plugin depending on one (skill-improve → skill-creator) is dropped as
# `dependency-unsatisfied`. Installing rewrites settings.json, so restore it afterwards.
if command -v claude > /dev/null; then
    for plugin in $(python3 -c 'import json; print(*json.load(open(".claude/settings.json")).get("enabledPlugins", {}))'); do
        claude plugin install "$plugin" --scope project > /dev/null \
            && echo "✅ $plugin installed" \
            || echo "⚠️  $plugin not installed — run: claude plugin install $plugin --scope project"
    done
    git checkout --quiet -- .claude/settings.json
fi

# --- Worktree: catch up with origin/main ---

# Only a branch based on `main` catches up with it. Merging `main` into anything else drags it into
# a PR that does not target `main` — a stacked node, or a branch cut from another feature branch.
# The base, most authoritative first: the open PR's, then the one Paseo recorded when it cut the
# worktree (`baseRefName` — for a checked-out PR that is the PR's base, for an existing branch the
# branch itself). No answer means no merge.
BRANCH=$(git branch --show-current)
BASE=$(gh pr view --json baseRefName --jq .baseRefName 2> /dev/null || true)
PASEO_METADATA="$(git rev-parse --git-dir)/paseo/worktree.json"
if [ -z "$BASE" ] && [ -f "$PASEO_METADATA" ]; then
    BASE=$(sed -n 's/.*"baseRefName": *"\([^"]*\)".*/\1/p' "$PASEO_METADATA")
fi

if [ "$BASE" != main ]; then
    echo ""
    echo "⏭️  Not catching up: ${BRANCH:-detached HEAD} is based on ${BASE:-an unknown branch}, not main."
    exit 0
fi

# Paseo cuts a branch from a freshly fetched `origin/main` when it can, but falls back to the cached
# ref when the fetch fails, and a re-run on an older branch is behind by definition.
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

# A fresh branch fast-forwards. A re-run on a branch carrying real work may not merge cleanly; a
# conflict under `set -e` would leave a half-merged tree, so an unclean merge is rolled back and
# reported instead.
if git merge --quiet --no-edit origin/main; then
    echo "✅ Up to date with origin/main"
else
    git merge --abort 2> /dev/null || true
    echo "⚠️  Could not merge origin/main into $BRANCH — merge it by hand."
fi
