#!/usr/bin/env python3
"""Publish a run's comments as ONE review per PR — the pending-review helpers.

Every comment posted on its own (`POST /pulls/{n}/comments`) is wrapped by GitHub
in a review of its own: a run with eight findings, or eight answered threads,
arrives as eight reviews and eight notifications, which the GitHub mobile app shows
as a wall of separate entries. So both posting scripts build a pending review,
add every new thread and every reply to it, and submit it once.

A user has at most one pending review per PR, and the agents post with the owner's
own token — his unfinished draft in the browser IS the pending review this would
use. `open_pending` therefore deletes a pending review only when everything in it
carries one of our headers (a run that died before submitting), and refuses when
anything in it is his: submitting it would publish his draft.

Nothing is visible until `submit`, so a caller that hits a problem halfway calls
`discard` and leaves the PR exactly as it found it.
"""

import json
import subprocess
import sys

from pr_stack import has_our_header


class ReviewError(Exception):
    """A pending review could not be opened, filled or submitted. The caller stops."""


class PendingReview:
    def __init__(self, repo, pr, review_id):
        self.repo = repo
        self.pr = pr
        self.id = review_id


def _graphql(query, **variables):
    """Run a GraphQL call; return `data`, or raise `ReviewError` with GitHub's message.

    The request goes in as a JSON body so bodies with any characters and integer
    variables arrive as they are, with no `-f`/`-F` typing to get wrong.
    """
    payload = json.dumps({"query": query, "variables": variables})
    result = subprocess.run(
        ["gh", "api", "graphql", "--input", "-"],
        input=payload, capture_output=True, text=True,
    )
    try:
        response = json.loads(result.stdout) if result.stdout.strip() else {}
    except json.JSONDecodeError:
        response = {}
    errors = response.get("errors")
    if result.returncode != 0 or errors or "data" not in response:
        detail = "; ".join(e.get("message", "") for e in errors or []) or result.stderr.strip()
        raise ReviewError(detail or "gh api graphql failed")
    return response["data"]


PENDING_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      id
      headRefOid
      reviews(states: PENDING, first: 10) {
        nodes {
          id
          body
          viewerDidAuthor
          comments(first: 100) { nodes { body } }
        }
      }
    }
  }
}
"""


def clear_stale(repo, pr):
    """Delete our own leftover pending review on `pr`; refuse to touch his draft.

    Returns the PR's GraphQL id and head SHA, which opening a review needs anyway.
    Called before anything checks whether a thread was already answered: a leftover
    pending answer is invisible to him and must not count as answered.
    """
    owner, name = repo.split("/", 1)
    data = _graphql(PENDING_QUERY, owner=owner, name=name, number=pr)
    pull = (data.get("repository") or {}).get("pullRequest")
    if not pull:
        raise ReviewError(f"{repo}#{pr} not found")

    for review in pull["reviews"]["nodes"]:
        if not review.get("viewerDidAuthor"):
            continue
        bodies = [c["body"] for c in review["comments"]["nodes"]]
        if review.get("body", "").strip():
            bodies.append(review["body"])
        if not all(has_our_header(body) for body in bodies):
            raise ReviewError(
                f"{repo}#{pr} has a pending review of yours with your own draft comments in it. "
                "Submit or discard it on GitHub, then re-run — publishing it from here would "
                "publish your draft."
            )
        discard(PendingReview(repo, pr, review["id"]))
    return pull["id"], pull["headRefOid"]


def open_pending(repo, pr):
    pull_id, head = clear_stale(repo, pr)
    data = _graphql(
        """
        mutation($pr: ID!, $head: GitObjectID!) {
          addPullRequestReview(input: {pullRequestId: $pr, commitOID: $head}) {
            pullRequestReview { id }
          }
        }
        """,
        pr=pull_id, head=head,
    )
    return PendingReview(repo, pr, data["addPullRequestReview"]["pullRequestReview"]["id"])


def add_thread(review, path, line, body):
    """Add a new thread at `path:line` (file level when `line` is falsy).

    Returns the new comment's `databaseId`, or None with the reason printed by the
    caller when GitHub rejects the anchor — a line outside this PR's diff, a file
    the PR did not touch.
    """
    anchor = {"line": line, "side": "RIGHT", "subjectType": "LINE"} if line else {"subjectType": "FILE"}
    try:
        data = _graphql(
            """
            mutation($input: AddPullRequestReviewThreadInput!) {
              addPullRequestReviewThread(input: $input) {
                thread { comments(first: 1) { nodes { databaseId } } }
              }
            }
            """,
            input={"pullRequestReviewId": review.id, "path": path, "body": body, **anchor},
        )
    except ReviewError:
        return None
    thread = (data.get("addPullRequestReviewThread") or {}).get("thread")
    if not thread or not thread["comments"]["nodes"]:
        return None
    return thread["comments"]["nodes"][0]["databaseId"]


def add_reply(review, thread_id, body):
    """Add a reply on an existing thread of the same PR to the pending review."""
    _graphql(
        """
        mutation($review: ID!, $thread: ID!, $body: String!) {
          addPullRequestReviewThreadReply(input: {
            pullRequestReviewId: $review, pullRequestReviewThreadId: $thread, body: $body
          }) { comment { id } }
        }
        """,
        review=review.id, thread=thread_id, body=body,
    )


def submit(review):
    """Publish it as a plain comment review, with no summary body: everything he
    reads is inline (review/references/comment.md). Returns the review's URL."""
    data = _graphql(
        """
        mutation($review: ID!) {
          submitPullRequestReview(input: {pullRequestReviewId: $review, event: COMMENT}) {
            pullRequestReview { url }
          }
        }
        """,
        review=review.id,
    )
    return data["submitPullRequestReview"]["pullRequestReview"]["url"]


def discard(review):
    _graphql(
        """
        mutation($review: ID!) {
          deletePullRequestReview(input: {pullRequestReviewId: $review}) { clientMutationId }
        }
        """,
        review=review.id,
    )


def discard_all(reviews):
    """Best effort: a review that fails to delete is reported, not raised, so the
    caller's real error is the one that surfaces. `clear_stale` removes it next run."""
    for review in reviews:
        try:
            discard(review)
        except ReviewError as error:
            print(
                f"Could not discard the pending review on {review.repo}#{review.pr}: {error}",
                file=sys.stderr,
            )


def permalink(repo, pr, comment_db_id):
    return f"https://github.com/{repo}/pull/{pr}#discussion_r{comment_db_id}"
