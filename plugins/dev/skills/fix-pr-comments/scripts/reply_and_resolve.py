#!/usr/bin/env python3
"""Answer a run's PR review threads: reply on each thread, then resolve it.

The answer is a reply on the thread itself, and the thread is resolved at once:
he signs off on fixes in the chat where the run reported them, so nothing is left
on GitHub for him to clear. A thread the fix outdated hides in Files changed —
which no longer matters, because nothing there is waiting on him.

Everything one call posts goes out as **one review per PR** (`review/scripts/pr_review.py`
says why and how), so the whole run's answers come in one call, after the last push:

1. clear a leftover pending review of ours
2. per thread, add a `## 🤖` reply — unless one of ours is already there
3. submit, then resolve every thread

Idempotent, not atomic. A thread already carrying our reply is not replied to again,
which is what makes a retry safe. Resolving comes last and fails open: a failure
there leaves the thread visible and safe to re-run, where resolving first could
close a finding whose answer never landed.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "review" / "scripts"))

from pr_review import (  # noqa: E402
    ReviewError, add_reply, clear_stale, discard_all, open_pending, submit,
)
from pr_stack import ChainError, has_our_header, is_trusted_author  # noqa: E402


def run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return None, result.stderr.strip()
    return result.stdout.strip(), None


FETCH_THREAD_QUERY = """
query($threadId: ID!) {
  node(id: $threadId) {
    ... on PullRequestReviewThread {
      comments(first: 50) {
        nodes {
          body
          author { __typename login }
        }
      }
    }
  }
}
"""

RESOLVE_MUTATION = """
mutation($threadId: ID!) {
  resolveReviewThread(input: {threadId: $threadId}) {
    thread {
      id
      isResolved
    }
  }
}
"""


def fetch_thread_comments(thread_id):
    result, err = run([
        "gh", "api", "graphql",
        "-F", f"threadId={thread_id}",
        "-f", f"query={FETCH_THREAD_QUERY}"
    ])
    if result is None:
        print(f"Failed to fetch thread: {err}", file=sys.stderr)
        return None
    node = json.loads(result).get("data", {}).get("node")
    if not node:
        print("Thread not found", file=sys.stderr)
        return None
    return node["comments"]["nodes"]


def already_replied(repo, comments):
    """True when a trusted author already left one of our replies under the source
    comment. Only trusted authors count, as in the fetch scripts: anyone can type the
    `## 🤖` header, and a stranger's comment must not get a thread resolved with no
    answer of ours on it. Exits on a failed lookup — falling through would post a
    second reply on exactly the retry this check exists to protect."""
    for comment in comments[1:]:
        if not has_our_header(comment.get("body")):
            continue
        try:
            if is_trusted_author(repo, comment.get("author") or {}):
                return True
        except ChainError as error:
            print(f"Failed to check a reply's author: {error}", file=sys.stderr)
            sys.exit(1)
    return False


def resolve_thread(thread_id):
    result, err = run([
        "gh", "api", "graphql",
        "-F", f"threadId={thread_id}",
        "-f", f"query={RESOLVE_MUTATION}"
    ])
    if result is None:
        print(f"Failed to resolve thread: {err}", file=sys.stderr)
        return False

    resolved = (
        json.loads(result)
        .get("data", {})
        .get("resolveReviewThread", {})
        .get("thread", {})
        .get("isResolved", False)
    )
    if resolved:
        print("Thread resolved.")
    else:
        print("Warning: thread may not have been resolved.", file=sys.stderr)
    return resolved


def main():
    parser = argparse.ArgumentParser(
        description="Reply on the source threads and resolve them — one GitHub review per PR."
    )
    parser.add_argument(
        "--answers", required=True,
        help="JSON file: a list of {repo, pr, threadId, header, message}. header: Fixed (the "
             "code changed) or Acknowledged (it did not, and the message says why).",
    )
    args = parser.parse_args()

    with open(args.answers) as f:
        answers = json.load(f)
    for answer in answers:
        if answer.get("header") not in ("Fixed", "Acknowledged"):
            print(f"Thread {answer.get('threadId')}: header must be Fixed or Acknowledged",
                  file=sys.stderr)
            sys.exit(1)
        answer["pr"] = int(answer["pr"])

    reviews = {}
    try:
        # A leftover pending reply is invisible to him, so it must be gone before
        # anything below decides a thread was already answered.
        for key in {(a["repo"], a["pr"]) for a in answers}:
            clear_stale(*key)

        for answer in answers:
            repo, pr = answer["repo"], answer["pr"]
            comments = fetch_thread_comments(answer["threadId"])
            if not comments:
                print(f"{answer['threadId']}: could not read the thread; nothing posted",
                      file=sys.stderr)
                sys.exit(1)
            if already_replied(repo, comments):
                print(f"Already answered, not replying again: {answer['threadId']}")
                continue
            if (repo, pr) not in reviews:
                reviews[(repo, pr)] = open_pending(repo, pr)
            reply = f"## 🤖 {answer['header']}\n\n{answer['message']}"
            add_reply(reviews[(repo, pr)], answer["threadId"], reply)

        for key in list(reviews):
            print(f"Review submitted on {key[0]}#{key[1]}: {submit(reviews[key])}")
            del reviews[key]
    except ReviewError as error:
        print(f"Failed: {error}", file=sys.stderr)
        sys.exit(1)
    finally:
        # Any exit halfway leaves reviews open under his account, where his next
        # browser comment would join them. A review already submitted is published
        # and left out; the rest go.
        discard_all(reviews.values())

    unresolved = [a["threadId"] for a in answers if not resolve_thread(a["threadId"])]
    if unresolved:
        print(f"Replies posted, but these threads are still open: {', '.join(unresolved)}",
              file=sys.stderr)
        sys.exit(1)
    print(f"Answered and resolved {len(answers)} thread(s).")


if __name__ == "__main__":
    main()
