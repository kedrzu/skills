#!/usr/bin/env python3
"""Fetch unresolved PR review comments from every node of the chain, and from submodule PRs.

A task can land as a chain of stacked pull requests, and review publishes each finding on
the node whose diff holds its lines. Reading only the branch's own PR would therefore skip
every thread posted below the node you are standing on — silently, since a missing thread
looks exactly like a PR with no comments. So the whole chain is fetched, bottom node first,
which is also the order the fix loop travels.

Each entry carries the PR a fix for it has to be committed on and answered against. An
unstacked branch is a chain of one and reads exactly as it always has.

Chain discovery is imported from the review skill rather than copied: both skills have to
agree on what the nodes are, and two implementations of that would eventually disagree.
"""

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "review" / "scripts"))

from pr_stack import (  # noqa: E402
    ChainError,
    describe_chain,
    get_current_branch,
    get_pr_for_branch,
    get_repo_info,
    get_repo_root,
    run,
    run_or_raise,
)

GRAPHQL_QUERY = """
query($owner: String!, $repo: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      url
      title
      reviewThreads(first: 100, after: $cursor) {
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
          id
          isResolved
          isOutdated
          path
          line
          startLine
          comments(first: 50) {
            nodes {
              id
              databaseId
              body
              author { login }
              createdAt
              path
              line
              startLine
              diffHunk
            }
          }
        }
      }
    }
  }
}
"""


# The authorship test, defined in review/references/comment.md in this plugin: a comment
# is ours iff its body starts with one of these headers. Author login can NOT be used —
# agents post with the owner's own GitHub token, so an agent comment and a hand-written
# one share the same login. The login check below only catches third-party bots
# (CodeRabbit, Dependabot, ...) that post plain prose with no marker.
# The legacy headers stay listed so PRs reviewed before that contract still classify.
# This set must match that definition, and the copies in review/scripts/fetch_pr_comments.py
# and review/scripts/post_review_comment.py: a change to one is a change to all of them.
AGENT_HEADERS = (
    "## 🚨 BLOCKING",
    "## 💡 NIT",
    "## 🤖",            # our own reply on a thread we fixed
    # legacy
    "## 🚨 CRITICAL ISSUE",
    "## ⚠️ IMPORTANT",
    "## 💡 MINOR",
    "## 🔍 ISSUE",
    "## 👀 HEADS UP",
    "## 🧭 FLOW",
)
KNOWN_BOT_LOGINS = frozenset({
    "coderabbitai",
    "coderabbitai[bot]",
    "dependabot",
    "dependabot[bot]",
    "github-actions",
    "github-actions[bot]",
    "renovate",
    "renovate[bot]",
})
BOT_LOGIN_PATTERN = re.compile(r"(?:^|[-_])bot(?:$|[-_])|\[bot\]$", re.IGNORECASE)


def is_bot_login(login):
    normalized = (login or "").strip().casefold()
    return normalized in KNOWN_BOT_LOGINS or bool(BOT_LOGIN_PATTERN.search(normalized))


def has_marker_header(body):
    """True when a comment carries one of our own headers."""
    stripped = (body or "").lstrip()
    return any(stripped.startswith(h) for h in AGENT_HEADERS)


def is_agent_authored(body, author_login):
    """True when a comment was written by an agent (marker header) or a known bot."""
    return has_marker_header(body) or is_bot_login(author_login)




def get_unresolved_threads(owner, repo, pr_number):
    all_threads = []
    pr_url = ""
    pr_title = ""
    cursor = None

    while True:
        cmd = [
            "gh", "api", "graphql",
            "-F", f"owner={owner}",
            "-F", f"repo={repo}",
            "-F", f"number={pr_number}",
            "-f", f"query={GRAPHQL_QUERY}",
        ]
        if cursor:
            cmd += ["-F", f"cursor={cursor}"]

        result = run_or_raise(
            cmd, what=f"fetching review threads for {owner}/{repo}#{pr_number} failed"
        )
        if not result:
            # `gh` succeeded but said nothing. Ending the loop here would truncate the
            # thread list silently, which is the failure this call was made loud to avoid.
            raise ChainError(
                f"fetching review threads for {owner}/{repo}#{pr_number} returned no output"
            )

        data = json.loads(result)
        pr_data = data["data"]["repository"]["pullRequest"]
        review_threads = pr_data["reviewThreads"]
        threads = review_threads["nodes"]
        pr_url = pr_data.get("url", "")
        pr_title = pr_data.get("title", "")

        all_threads.extend(threads)

        page_info = review_threads["pageInfo"]
        if page_info["hasNextPage"]:
            cursor = page_info["endCursor"]
        else:
            break

    unresolved = []
    for thread in all_threads:
        if thread["isResolved"]:
            continue
        comments = thread["comments"]["nodes"]
        if not comments:
            continue

        first_body = comments[0].get("body", "")
        first_stripped = first_body.lstrip()
        # Legacy headers — review no longer posts either, but in-flight PRs still
        # carry them. Without a human reply they are FYI-only; with a reply, the
        # reply is the ask, and from there they are ordinary threads.
        is_heads_up = (first_stripped.startswith("## 👀 HEADS UP")
                       or first_stripped.startswith("## 🧭 FLOW"))

        origins = [
            "agent" if is_agent_authored(
                c.get("body", ""),
                c["author"]["login"] if c.get("author") else None,
            ) else "human"
            for c in comments
        ]

        has_human_reply = "human" in origins[1:]

        # The operative comment — "the ask" — is the LATEST human comment in the
        # thread; with no human comment at all it is the first one. A human reply
        # supersedes the agent finding it answers, and a later human reply
        # supersedes an earlier one.
        human_indexes = [i for i, o in enumerate(origins) if o == "human"]
        ask_index = human_indexes[-1] if human_indexes else 0

        # Our own answer to an earlier fix, left unresolved for him to sign off. That
        # is the steady state now, not an exception — it is our output, and it becomes
        # his input only when he replies under it, which makes the thread longer than
        # one comment and sends it down the normal path above.
        if len(comments) == 1 and origins[0] == "agent" and first_stripped.startswith("## 🤖"):
            continue

        # Skip heads-up threads that the human hasn't engaged with — a
        # heads-up only becomes actionable when the human replies with an
        # instruction. Without a reply it's just "FYI, look at this".
        thread_comments = []
        for i, c in enumerate(comments):
            entry = {
                "author": c["author"]["login"] if c.get("author") else "unknown",
                "origin": origins[i],
                "body": c["body"],
            }
            # Keep diffHunk only on first comment (useful context)
            if i == 0 and c.get("diffHunk"):
                entry["diffHunk"] = c["diffHunk"]
            thread_comments.append(entry)

        thread_out = {
            "threadId": thread["id"],
            "path": thread.get("path") or (comments[0].get("path") if comments else None),
            "line": thread.get("line"),
            "startLine": thread.get("startLine"),
            "isOutdated": thread.get("isOutdated", False),
            "firstCommentDatabaseId": comments[0].get("databaseId"),
            "firstCommentOrigin": origins[0],
            "hasHumanReply": has_human_reply,
            "askOrigin": origins[ask_index],
            "askCommentIndex": ask_index,
            "comments": thread_comments,
        }
        unresolved.append(thread_out)

    return unresolved, pr_url, pr_title


def get_submodules(cwd=None):
    result = run(["git", "submodule", "status"], cwd=cwd)
    if not result:
        return []
    submodules = []
    for line in result.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.strip().split()
        if len(parts) >= 2:
            submodules.append(parts[1])
    return submodules


def main():
    repo_root = get_repo_root()
    if not repo_root:
        print(json.dumps({"error": "Not in a git repository"}))
        sys.exit(1)

    try:
        chain = describe_chain(cwd=repo_root)
    except ChainError as error:
        print(json.dumps({"error": str(error)}))
        sys.exit(1)

    owner, repo = chain["repo"].split("/", 1)
    branch = chain["branch"]
    results = []

    # Every node of the chain, bottom first — one entry per PR, the same shape an
    # unstacked branch has always produced.
    nodes = chain["nodes"]
    if nodes[0]["prNumber"] is not None:
        for node in nodes:
            try:
                threads, pr_url, pr_title = get_unresolved_threads(owner, repo, node["prNumber"])
            except ChainError as error:
                print(json.dumps({
                    "error": f"node {node['index']}/{len(nodes)} (PR #{node['prNumber']}): {error}"
                }))
                sys.exit(1)
            results.append({
                "repo": f"{owner}/{repo}",
                "prNumber": node["prNumber"],
                "prUrl": pr_url,
                "prTitle": pr_title,
                "branch": node["branch"],
                "node": node["index"],
                "nodeCount": len(nodes),
                "isCurrent": node["isCurrent"],
                "pathPrefix": "",
                "threads": threads
            })
    else:
        print(json.dumps({"error": f"No PR found for branch '{branch}' in {owner}/{repo}"}), file=sys.stderr)

    # Submodule PRs
    submodules = get_submodules(cwd=repo_root)
    for sub_path in submodules:
        sub_full = os.path.join(repo_root, sub_path)
        if not os.path.isdir(sub_full):
            continue
        sub_owner, sub_repo = get_repo_info(cwd=sub_full)
        sub_branch = get_current_branch(cwd=sub_full)

        if not all([sub_owner, sub_repo, sub_branch]):
            continue

        try:
            sub_pr = get_pr_for_branch(sub_owner, sub_repo, sub_branch)
        except ChainError as error:
            print(json.dumps({"error": f"submodule {sub_path}: {error}"}))
            sys.exit(1)
        if sub_pr:
            try:
                threads, pr_url, pr_title = get_unresolved_threads(sub_owner, sub_repo, sub_pr)
            except ChainError as error:
                print(json.dumps({"error": f"submodule {sub_path} (PR #{sub_pr}): {error}"}))
                sys.exit(1)
            results.append({
                "repo": f"{sub_owner}/{sub_repo}",
                "prNumber": sub_pr,
                "prUrl": pr_url,
                "prTitle": pr_title,
                "branch": sub_branch,
                # A submodule PR is never a node of the main repo's chain: it is a
                # separate PR in a separate repository, read as a chain of one.
                "node": 1,
                "nodeCount": 1,
                "isCurrent": True,
                "pathPrefix": sub_path + "/",
                "threads": threads
            })

    if not results:
        print(json.dumps({"error": "No PRs found for current branch in any repo"}))
        sys.exit(1)

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
