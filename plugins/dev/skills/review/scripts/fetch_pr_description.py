#!/usr/bin/env python3
"""Fetch the PR title + description for this branch's PR, and for every node of its chain.

Used by the review orchestrator to inject author framing into reviewer prompts.
The top-level fields describe the branch's own PR; `nodes` describes the whole
stack, bottom first, and holds a single entry for an unstacked branch.
"""

import json
import sys

from pr_stack import ChainError, describe_chain, run_or_raise


def get_pr_description(repo, pr_number):
    result = run_or_raise([
        "gh", "pr", "view", str(pr_number),
        "--repo", repo,
        "--json", "title,body,url",
    ], what=f"fetching PR #{pr_number} description")
    if not result:
        raise ChainError(f"fetching PR #{pr_number} description returned no output")
    try:
        return json.loads(result)
    except json.JSONDecodeError:
        raise ChainError(f"PR #{pr_number} description was not valid JSON: {result[:200]!r}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Fetch PR title and body for the current branch.")
    parser.add_argument("--cwd", default=None, help="Working directory (defaults to repo root)")
    args = parser.parse_args()

    try:
        chain = describe_chain(cwd=args.cwd)
    except ChainError as error:
        print(json.dumps({"error": str(error)}))
        sys.exit(1)

    repo, branch, nodes = chain["repo"], chain["branch"], chain["nodes"]
    if nodes[0]["prNumber"] is None:
        # No PR yet — return an empty description rather than erroring,
        # so the orchestrator can still run /dev:review on un-PR'd branches.
        print(json.dumps({
            "repo": repo,
            "branch": branch,
            "prNumber": None,
            "title": "",
            "body": "",
            "url": "",
            "stacked": False,
            "stackNumber": None,
            "nodes": [],
        }, indent=2))
        return

    current = None
    for node in nodes:
        try:
            data = get_pr_description(repo, node["prNumber"])
        except ChainError as error:
            print(json.dumps({
                "error": f"node {node['index']}/{len(nodes)} (PR #{node['prNumber']}): {error}"
            }))
            sys.exit(1)
        node["title"] = data.get("title", "") or ""
        node["body"] = data.get("body", "") or ""
        node["url"] = data.get("url", "") or ""
        if node["isCurrent"]:
            current = node

    print(json.dumps({
        "repo": repo,
        "branch": branch,
        "prNumber": current["prNumber"],
        "title": current["title"],
        "body": current["body"],
        "url": current["url"],
        "stacked": chain["stacked"],
        "stackNumber": chain["stackNumber"],
        "nodes": nodes,
    }, indent=2))


if __name__ == "__main__":
    main()
