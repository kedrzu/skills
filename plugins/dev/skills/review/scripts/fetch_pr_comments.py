#!/usr/bin/env python3
"""Fetch ALL PR review comments (including resolved) so the poster can judge what is new.

A resolved thread is the owner's "no" and it stands, so resolved ones matter as much as
open ones. Each thread carries its human reply texts too — a reply is a decision the
review has to read, not just dedup state.

Dedup is chain-wide even though publishing is per node: the same finding raised on a
lower node's PR is not new because it also shows up in a higher node's diff. So every
node of the stack is fetched, each with the head SHA a comment on it must be posted
against. An unstacked branch is one node and reads exactly as it always has.
"""

import json
import sys

from pr_stack import ChainError, describe_chain, has_our_header, is_trusted_author, run_or_raise

GRAPHQL_QUERY = """
query($owner: String!, $repo: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
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
              body
              author { __typename login }
            }
          }
        }
      }
    }
  }
}
"""


def fetch_all_threads(owner, repo, pr_number):
    """Fetch ALL review threads including resolved ones."""
    all_threads = []
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
        all_threads.extend(review_threads["nodes"])

        page_info = review_threads["pageInfo"]
        if page_info["hasNextPage"]:
            cursor = page_info["endCursor"]
        else:
            break

    repo_full = f"{owner}/{repo}"
    comments = []
    for thread in all_threads:
        # Comments from authors without write access are dropped first: a stranger's
        # reply must not settle a finding, and a stranger's thread must not stand in
        # for one of his and suppress a new finding as a duplicate.
        thread_comments = [
            c for c in thread["comments"]["nodes"]
            if is_trusted_author(repo_full, c.get("author"))
        ]
        if not thread_comments:
            continue

        first_body = thread_comments[0].get("body", "")
        is_bot = has_our_header(first_body)

        # Collect the human replies, not just the fact that one exists: a reply IS the
        # owner's decision ("leave it, because …" vs "no, do it differently"), and the
        # poster has to read what he wrote to know whether a finding was already settled.
        human_replies = [
            c.get("body", "")
            for c in thread_comments[1:]
            if not c.get("body", "").lstrip().startswith("## 🤖")
        ]
        has_human_reply = bool(human_replies)

        comments.append({
            "path": thread.get("path"),
            "line": thread.get("line"),
            "body": first_body,
            "isResolved": thread.get("isResolved", False),
            "hasHumanReply": has_human_reply,
            "humanReplies": human_replies,
            "isBot": is_bot,
            "kind": "review" if is_bot else "human",
        })

    return comments


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Fetch PR review comments for deduplication.")
    parser.add_argument("--cwd", default=None, help="Working directory (for submodule support)")
    args = parser.parse_args()

    try:
        chain = describe_chain(cwd=args.cwd)
    except ChainError as error:
        print(json.dumps({"error": str(error)}))
        sys.exit(1)

    repo, branch, nodes = chain["repo"], chain["branch"], chain["nodes"]
    owner, repo_name = repo.split("/", 1)
    if nodes[0]["prNumber"] is None:
        print(json.dumps({"error": f"No PR found for branch '{branch}' in {repo}"}))
        sys.exit(1)

    current = None
    for node in nodes:
        try:
            node["comments"] = fetch_all_threads(owner, repo_name, node["prNumber"])
        except ChainError as error:
            print(json.dumps({
                "error": f"node {node['index']}/{len(nodes)} (PR #{node['prNumber']}): {error}"
            }))
            sys.exit(1)
        if node["isCurrent"]:
            current = node

    print(json.dumps({
        "repo": repo,
        "prNumber": current["prNumber"],
        "headSha": current["headSha"],
        "comments": current["comments"],
        "stacked": chain["stacked"],
        "stackNumber": chain["stackNumber"],
        "nodes": nodes,
    }, indent=2))


if __name__ == "__main__":
    main()
