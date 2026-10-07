#!/usr/bin/env python3
"""Repo, branch and chain lookup — the one implementation of "what are the nodes?".

A task can land as a chain of stacked pull requests, and a comment only anchors
inside its own PR's diff — so every script here works on the chain rather than on
one branch. GitHub's Stacks API answers it in one call:
`GET /repos/{owner}/{repo}/stacks?pull_request=<n>` returns the chain a PR belongs
to, ordered bottom first, and an empty list for an ordinary PR. An unstacked
branch therefore comes back as a chain of one and needs no other path.

`[]` is the answer for "not stacked" on every repo and every owner — the route
itself is not feature-gated (verified against unstacked PRs in two unrelated
repositories). A 404 is therefore the API failing, not a repo without stacks,
and it stops the run like any other failure.

**Discovery fails loud.** Anything this cannot answer confidently — the API
erroring, a payload it does not recognise, open nodes that are not contiguous, a
branch that is not one of them — raises `ChainError` and stops the caller.
Degrading to "this is an ordinary PR" is not a neutral fallback: review would then
post the whole chain's findings onto the tip PR and the fix loop would skip every
thread below it, with an exit code of zero and nothing in the log.

Run directly, it prints the chain as JSON; imported, `describe_chain()` returns the
same dict — that is how `generate_diffs.py` and the fetch scripts get the nodes,
and why nothing re-derives them.

It also owns the other things both fetch scripts must agree on: whose comments are
read at all (`is_trusted_author`) and which of those are ours (`has_our_header`).
"""

import functools
import json
import re
import subprocess
import sys


class ChainError(Exception):
    """Discovery could not answer confidently. The caller stops."""


def run(cmd, cwd=None):
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def run_or_raise(cmd, cwd=None, *, what):
    """Like `run`, but a non-zero exit raises `ChainError` naming `what` instead of
    returning None.

    `run()`'s falsy-on-failure contract is right for callers where "the command
    failed" and "there is nothing to report" are the same outcome (no remote, no
    current branch). It is wrong inside a pagination loop: there, a failed page and
    a genuinely last page must not collapse into the same `break` — that is what
    let a 502 or a secondary rate limit masquerade as "no more comments".
    """
    stdout, stderr, ok = _gh(cmd, cwd=cwd)
    if not ok:
        raise ChainError(f"{what}: {stderr or 'gh failed'}")
    return stdout


def _gh(args, cwd=None):
    """A `gh` call that must succeed. Returns (stdout, stderr, ok)."""
    try:
        result = subprocess.run(args, capture_output=True, text=True, cwd=cwd)
    except FileNotFoundError:
        raise ChainError("`gh` is not installed, so the PR chain cannot be determined.")
    return result.stdout.strip(), result.stderr.strip(), result.returncode == 0


def get_repo_root():
    return run(["git", "rev-parse", "--show-toplevel"])


def get_repo_info(cwd=None):
    remote = run(["git", "remote", "get-url", "origin"], cwd=cwd)
    if not remote:
        return None, None
    # Anchored: `acme/acme.github.io.git` must not lose the `.git` inside its own name.
    remote = re.sub(r"\.git$", "", remote.rstrip("/"))
    if remote.startswith("git@"):
        path = remote.split(":", 1)[1]
    elif "github.com" in remote:
        path = remote.split("github.com/")[-1]
    else:
        return None, None
    parts = path.split("/")
    if len(parts) >= 2:
        return parts[0], parts[1]
    return None, None


def get_current_branch(cwd=None):
    return run(["git", "branch", "--show-current"], cwd=cwd)


# gh's wording when a branch simply has no pull request. Anything else from the
# same call is an error, not an answer.
_NO_PR = re.compile(
    r"no pull requests found|could not resolve to a pullrequest|no open pull requests",
    re.IGNORECASE,
)


def get_pr_for_branch(owner, repo, branch):
    """The branch's PR number, or None when it genuinely has none."""
    stdout, stderr, ok = _gh([
        "gh", "pr", "view", branch,
        "--repo", f"{owner}/{repo}",
        "--json", "number",
        "-q", ".number",
    ])
    if not ok:
        if _NO_PR.search(stderr):
            return None
        raise ChainError(f"could not look up the PR for '{branch}': {stderr or 'gh failed'}")
    try:
        return int(stdout)
    except ValueError:
        raise ChainError(f"unrecognised PR number for '{branch}': {stdout!r}")


# Who may instruct the agents. An unresolved comment is executed, pushed and closed by
# the fix loop, so only people who could push that change themselves are read: anyone
# else — on a public repo, any logged-in stranger — would be handed the very write
# access they lack. The repo permission is checked rather than GraphQL's
# `authorAssociation`: MEMBER only says the author belongs to the owning org, not that
# they can touch this repo, and COLLABORATOR includes read-only collaborators.
# `maintain` is reported as `write` by this endpoint, so the two below cover it.
_WRITE_PERMISSIONS = {"admin", "write"}

# gh's wording when the login is no user at all. It is a fact about the author (an
# untrusted one), unlike every other failure of the same call.
_NOT_A_USER = re.compile(r"is not a user", re.IGNORECASE)


@functools.lru_cache(maxsize=None)
def _has_write_access(repo, login):
    stdout, stderr, ok = _gh([
        "gh", "api", f"repos/{repo}/collaborators/{login}/permission", "-q", ".permission",
    ])
    if not ok:
        if _NOT_A_USER.search(stderr):
            return False
        # Neither trusting nor dropping is safe on a failed lookup: one obeys a stranger,
        # the other silently loses an instruction of the owner's. So the run stops.
        raise ChainError(
            f"could not read {login}'s permission on {repo}: {stderr or 'gh failed'}"
        )
    if not stdout:
        raise ChainError(f"reading {login}'s permission on {repo} returned no output")
    return stdout in _WRITE_PERMISSIONS


def is_trusted_author(repo, author):
    """True when a review comment's GraphQL `author` (`{__typename, login}`) may instruct
    the agents on `repo`. Everything else is dropped by the fetch scripts before anything
    reads it — including before the marker-header authorship test, which anyone can type.

    A GitHub App (`Bot`) is trusted: it can comment only where someone with admin rights
    installed it. A login that merely looks like a bot (`evil-bot`) is a `User` and goes
    through the permission check like anyone else. No author (a deleted account) and any
    other actor type fail closed.
    """
    if not author:
        return False
    kind = author.get("__typename")
    if kind == "Bot":
        return True
    if kind != "User" or not author.get("login"):
        return False
    return _has_write_access(repo, author["login"])


# The authorship test, defined in review/references/comment.md § Who wrote a comment: a
# comment is ours iff its body starts with one of these headers. Author login can NOT be
# used — agents post with the owner's own GitHub token. It only holds among trusted
# authors (`is_trusted_author`): anyone can type a header, so strangers are dropped first.
# The legacy headers stay listed so PRs reviewed before that contract still classify.
OUR_HEADERS = (
    "## 🚨 BLOCKING",
    "## 💡 NIT",
    "## 🤖",            # an answer to a finding, written by fix-pr-comments
    # legacy
    "## 🚨 CRITICAL ISSUE",
    "## ⚠️ IMPORTANT",
    "## 💡 MINOR",
    "## 🔍 ISSUE",
    "## 👀 HEADS UP",
    "## 🧭 FLOW",
)


def has_our_header(body):
    """True when a comment carries one of our own headers."""
    stripped = (body or "").lstrip()
    return any(stripped.startswith(h) for h in OUR_HEADERS)


def get_pr_head_and_base(repo, pr_number):
    """The PR's head SHA and the branch it targets, from one call.

    The base is what an unstacked PR's diff is measured from — the same branch
    GitHub diffs it against — so nothing has to assume the repository's main line
    is called `main`.
    """
    stdout, stderr, ok = _gh([
        "gh", "api", f"repos/{repo}/pulls/{pr_number}",
        "-q", "[.head.sha, .base.ref] | @tsv",
    ])
    sha, _, base = stdout.partition("\t")
    if not ok or not sha or not base:
        raise ChainError(
            f"could not read the head SHA and base branch of PR #{pr_number}: {stderr or stdout or 'empty'}"
        )
    return sha, base


def get_default_branch(repo):
    """The repository's default branch — the base for a branch with no PR yet."""
    stdout, stderr, ok = _gh([
        "gh", "repo", "view", repo, "--json", "defaultBranchRef", "-q", ".defaultBranchRef.name",
    ])
    if not ok or not stdout:
        raise ChainError(f"could not read the default branch of {repo}: {stderr or 'empty'}")
    return stdout


def _node_fields(pr, position):
    number, head = pr.get("number"), pr.get("head") or {}
    ref, sha = head.get("ref"), head.get("sha")
    if not (isinstance(number, int) and ref and sha):
        raise ChainError(
            f"the stack payload's pull request at position {position} is missing "
            "number, head.ref or head.sha"
        )
    return number, ref, sha


# Every state a node can be in. A value outside this set is a payload we cannot
# read: it decides whether a node is part of the review, and a wrong answer either
# drops a node's files or hands them to the node above.
_PR_STATES = {"open", "closed", "merged"}


def find_stack(repo, pr_number):
    """The stack this PR belongs to, or None when it is an ordinary PR.

    Merged and closed nodes are dropped — what is under review is the part of the
    chain still open — but they may only sit at the ends of it. A closed node
    *between* two open ones would make the survivors look contiguous when they are
    not, and node k+1's diff would silently absorb the files of node k.
    """
    stdout, stderr, ok = _gh(["gh", "api", f"repos/{repo}/stacks?pull_request={pr_number}"])
    if not ok:
        raise ChainError(f"the stacks API failed for PR #{pr_number}: {stderr or 'gh failed'}")
    try:
        stacks = json.loads(stdout)
    except json.JSONDecodeError:
        raise ChainError(f"the stacks API returned something that is not JSON: {stdout[:200]!r}")
    if not isinstance(stacks, list):
        raise ChainError("the stacks API returned an object where a list was expected")
    if not stacks:
        return None
    if len(stacks) > 1:
        raise ChainError(
            f"the stacks API returned {len(stacks)} stacks for PR #{pr_number}. A PR belongs "
            "to one chain; picking one of them is a guess about which chain is under review."
        )

    stack = stacks[0]
    prs = stack.get("pull_requests")
    if not isinstance(prs, list) or not prs:
        raise ChainError("the stack payload carries no pull_requests list")

    for position, pr in enumerate(prs, start=1):
        state = pr.get("state") if isinstance(pr, dict) else None
        if state not in _PR_STATES:
            raise ChainError(
                f"the stack payload's pull request at position {position} has state "
                f"{state!r}, which is not one of {'/'.join(sorted(_PR_STATES))} — this is not "
                "a shape we recognise, and guessing which nodes are open is exactly what "
                "must not happen here"
            )

    # A node repeated in the payload would become its own base, and its diff would
    # come out empty while its files stay in no node at all.
    for label, values in (
        ("pull request", [pr.get("number") for pr in prs]),
        ("head ref", [(pr.get("head") or {}).get("ref") for pr in prs]),
    ):
        seen = [value for value in values if values.count(value) > 1]
        if seen:
            raise ChainError(
                f"stack #{stack.get('number')} lists the same {label} more than once "
                f"({seen[0]!r}). A chain's nodes are distinct."
            )

    open_at = [i for i, pr in enumerate(prs) if pr.get("state") == "open"]
    if not open_at:
        return None
    if open_at != list(range(open_at[0], open_at[-1] + 1)):
        shape = ", ".join(f"#{pr.get('number')} {pr.get('state')}" for pr in prs)
        raise ChainError(
            f"stack #{stack.get('number')} has a closed or merged node between open "
            f"ones ({shape}). The open nodes are not a chain, and treating them as "
            "one would attribute a node's files to the node above it."
        )

    open_prs = [prs[i] for i in open_at]
    for position, pr in enumerate(open_prs, start=1):
        _node_fields(pr, position)

    base = (stack.get("base") or {}).get("ref")
    if not base:
        raise ChainError(f"stack #{stack.get('number')} has no base ref")

    if len(open_prs) < 2:
        # One node left open is an ordinary pull request, whatever the stack was.
        return None

    return {"number": stack.get("number"), "base": base, "pullRequests": open_prs}


def get_chain(repo, branch, pr_number):
    """The chain this branch's PR belongs to, bottom first.

    Returns `(stackNumber, base, nodes)`. `stackNumber` and `base` are None for an
    unstacked branch, whose chain is the single node the branch itself is. Every
    node carries the PR number and head SHA a comment has to be posted against, and
    the ref its diff is measured from — for an unstacked PR the branch it targets,
    and None only when the branch has no PR at all.
    """
    stack = find_stack(repo, pr_number) if pr_number else None
    if stack is None:
        head_sha, base = get_pr_head_and_base(repo, pr_number) if pr_number else (None, None)
        return None, None, [{
            "index": 1,
            "prNumber": pr_number,
            "branch": branch,
            "headSha": head_sha,
            "base": base,
            "isCurrent": True,
        }]

    nodes = []
    for index, pr in enumerate(stack["pullRequests"], start=1):
        number, ref, sha = _node_fields(pr, index)
        nodes.append({
            "index": index,
            "prNumber": number,
            "branch": ref,
            "headSha": sha,
            "base": stack["base"] if index == 1 else nodes[-1]["branch"],
            "isCurrent": ref == branch,
        })

    if not any(node["isCurrent"] for node in nodes):
        refs = ", ".join(node["branch"] for node in nodes)
        raise ChainError(
            f"'{branch}' is not one of stack #{stack['number']}'s open nodes ({refs}). "
            "Its own work would be in no node's diff. Check out one of them "
            "(git-workflow → stack) and re-run."
        )

    return stack["number"], stack["base"], nodes


def describe_chain(cwd=None):
    """The whole chain as a plain dict — what `__main__` prints and bash consumes."""
    cwd = cwd or get_repo_root()
    if not cwd:
        raise ChainError("not in a git repository")
    owner, repo_name = get_repo_info(cwd=cwd)
    branch = get_current_branch(cwd=cwd)
    if not all([owner, repo_name, branch]):
        raise ChainError("could not determine the repo's owner, name or current branch")

    repo = f"{owner}/{repo_name}"
    pr_number = get_pr_for_branch(owner, repo_name, branch)
    stack_number, base, nodes = get_chain(repo, branch, pr_number)
    current = next(node["index"] for node in nodes if node["isCurrent"])
    return {
        "repo": repo,
        "branch": branch,
        "stacked": stack_number is not None,
        "stackNumber": stack_number,
        "base": base,
        "currentNode": current,
        "topNode": len(nodes),
        "nodes": nodes,
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Print this branch's PR chain as JSON.")
    parser.add_argument("--cwd", default=None, help="Working directory (defaults to repo root)")
    args = parser.parse_args()
    try:
        print(json.dumps(describe_chain(cwd=args.cwd), indent=2))
    except ChainError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
