#!/usr/bin/env python3
"""Answer one PR review thread: post at the fix, reply on the thread, resolve it.

A reply alone cannot work. The fix usually changes the very line the source comment
sits on, which makes that thread outdated and hides it in the Files-changed view —
where the owner reads. So the answer is a **new** review comment anchored to where
the fix now lives, posted after the push, and it stays unresolved: that is his
sign-off. The source thread gets a short reply pointing at it and is resolved.

Four steps per thread, in this order:

1. fetch the source thread's comments (for the quotes and their permalinks)
2. post the answer at --file/--line, quoting each source comment
3. reply on the source thread, linking to the answer
4. resolve the source thread

Idempotent, not atomic. The answer's own attribution line carries the source
comment's full permalink, so "have we already answered this thread?" is a search
for that link in a `## 🤖` comment on the PR. Checked before posting, which is what
makes a retry safe. And the order fails open — a failure at reply or resolve leaves
the source thread visible and safe to re-run, where resolving first could close a
finding whose answer never landed.

A rejected anchor falls back to the first line of that file that is in this PR's
diff, then exits non-zero **without touching the source thread**: picking a
different file is the agent's judgement, not a rung in this ladder. It never
degrades to a file-level comment — those are marked outdated by any push at all,
which is the one thing the answer exists to survive.

`--pr` is the node the **fix** landed on: the only PR whose diff the answer can
anchor inside, and its head SHA is what the comment is posted against. Pass
`--source-pr` for the rare thread that sits on a different node, so the reply and
the quoted permalinks stay on the PR he wrote on.
"""

import argparse
import base64
import json
import re
import subprocess
import sys


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
          databaseId
          body
          author { login }
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


def permalink(repo, pr_number, comment_db_id):
    return f"https://github.com/{repo}/pull/{pr_number}#discussion_r{comment_db_id}"


def build_answer_body(header, message, comments, repo, pr_number):
    """The answer: what landed first, then the source it answers.

    Quotes are not nested in a <details> — a source body carrying its own
    </details> would close the wrapper early and spill the agent layer.
    """
    parts = [f"## 🤖 {header}", "", message, ""]
    for comment in comments:
        author = comment["author"]["login"] if comment.get("author") else "unknown"
        link = permalink(repo, pr_number, comment.get("databaseId"))
        quoted = "\n".join(f"> {line}" for line in comment["body"].split("\n"))
        parts.append(f"[**@{author}**]({link}):\n{quoted}\n")
    return "\n".join(parts)


def find_existing_answer(repo, pr_number, source_pr, source_comment_db_id):
    """The idempotency check: has this thread already been answered on the PR?

    The key is the whole attribution line `build_answer_body` emits —
    `[**@author**](permalink):` — matched as that shape, anchored at both ends.
    Searching for the permalink as a *substring* is what this must not do: an
    answer to another thread that writes "same root cause as <link>" mentions the
    permalink in prose, and would mark this thread answered and resolve a finding
    nobody replied to. The anchoring also removes the need to skip quoted lines —
    a quoted attribution starts with `> ` and cannot match.

    Exits rather than returning on a failed lookup. Falling through would post a
    second answer on exactly the retry this check exists to protect.
    """
    result, err = run([
        "gh", "api", f"repos/{repo}/pulls/{pr_number}/comments", "--paginate",
        "--jq", '.[] | select(.body | startswith("## 🤖")) | (.html_url + " " + (.body | @base64))',
    ])
    if result is None:
        print(f"Failed to list PR comments: {err}", file=sys.stderr)
        sys.exit(1)

    anchor = re.compile(
        r"^\[\*\*@[^\]]+\*\*\]\("
        + re.escape(permalink(repo, source_pr, source_comment_db_id))
        + r"\):\s*$"
    )
    for line in result.split("\n"):
        url, _, encoded = line.strip().partition(" ")
        if not encoded:
            continue
        body = base64.b64decode(encoded).decode("utf-8", "replace")
        if any(anchor.match(body_line) for body_line in body.split("\n")):
            return url
    return None


def get_pr_head_sha(repo, pr_number):
    result, err = run(["gh", "api", f"repos/{repo}/pulls/{pr_number}", "-q", ".head.sha"])
    if result is None:
        print(f"Failed to get PR head SHA: {err}", file=sys.stderr)
    return result


def first_diff_line(repo, pr_number, path):
    """The first line of `path` that exists on the RIGHT side of this PR's diff.

    The fallback anchor, and the reason it is not simply line 1: `line` must be a
    line of the blob **in the diff**, so a file's first line is usually not
    postable. A file the PR only deleted has no right side at all — then there is
    no anchor here and the agent has to name another file.
    """
    patch, err = run([
        "gh", "api", f"repos/{repo}/pulls/{pr_number}/files", "--paginate",
        "--jq", f'.[] | select(.filename == "{path}") | .patch',
    ])
    if patch is None:
        print(f"Failed to read the PR diff: {err}", file=sys.stderr)
        return None

    right_line = None
    for raw in patch.split("\n"):
        if raw.startswith("@@"):
            match = re.search(r"\+(\d+)", raw)
            right_line = int(match.group(1)) if match else None
        elif right_line is not None and (raw.startswith("+") or raw.startswith(" ")):
            return right_line
    return None


def create_review_comment(repo, pr_number, sha, body, path, line):
    cmd = [
        "gh", "api", f"repos/{repo}/pulls/{pr_number}/comments",
        "-f", f"body={body}",
        "-f", f"commit_id={sha}",
        "-f", f"path={path}",
        "-F", f"line={line}", "-f", "side=RIGHT",
    ]
    result, err = run(cmd)
    if result is None:
        print(f"Review comment failed: {err}", file=sys.stderr)
        return None
    return json.loads(result).get("html_url", "")


def reply_to_thread(repo, pr_number, comment_db_id, body):
    result, err = run([
        "gh", "api",
        f"repos/{repo}/pulls/{pr_number}/comments/{comment_db_id}/replies",
        "-f", f"body={body}"
    ])
    if result is None:
        print(f"Reply failed: {err}", file=sys.stderr)
        return False
    print(f"Reply posted: {json.loads(result).get('html_url', 'ok')}")
    return True


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
        description="Post a fix answer on live code, reply on the source thread, resolve it."
    )
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument(
        "--pr", required=True, type=int,
        help="PR of the node the fix landed on — the answer is anchored in its diff",
    )
    parser.add_argument(
        "--source-pr", type=int, default=None,
        help="PR carrying the source thread, when the fix landed on another node (defaults to --pr)",
    )
    parser.add_argument("--thread-id", required=True, help="GraphQL node ID of the source thread")
    parser.add_argument(
        "--header", required=True, choices=["Fixed", "Acknowledged"],
        help="Fixed = the code changed; Acknowledged = it did not, and the message says why",
    )
    parser.add_argument("--message", required=True, help="What landed, in the owner's language")
    parser.add_argument("--file", required=True, help="Where the fix lives NOW, relative to repo root")
    parser.add_argument(
        "--line", required=True, type=int,
        help="Line of the fix; 0 to let the script anchor at the file's first line in the diff",
    )
    args = parser.parse_args()
    source_pr = args.source_pr if args.source_pr is not None else args.pr

    comments = fetch_thread_comments(args.thread_id)
    if not comments:
        sys.exit(1)

    source_comment_db_id = comments[0].get("databaseId")
    if not source_comment_db_id:
        print("Could not get source comment database ID", file=sys.stderr)
        sys.exit(1)

    answer_url = find_existing_answer(args.repo, args.pr, source_pr, source_comment_db_id)
    if answer_url:
        print(f"Already answered, not posting again: {answer_url}")
    else:
        sha = get_pr_head_sha(args.repo, args.pr)
        if sha is None:
            sys.exit(1)

        body = build_answer_body(args.header, args.message, comments, args.repo, source_pr)
        answer_url = None
        if args.line > 0:
            answer_url = create_review_comment(args.repo, args.pr, sha, body, args.file, args.line)
        if answer_url is None:
            fallback = first_diff_line(args.repo, args.pr, args.file)
            if fallback is not None and fallback != args.line:
                print(f"Anchoring at the first diff line of the file ({fallback})...", file=sys.stderr)
                answer_url = create_review_comment(args.repo, args.pr, sha, body, args.file, fallback)
        if answer_url is None:
            print(
                f"Could not anchor the answer in {args.file}. Source thread untouched — "
                "name a file this PR changed and re-run.",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"Answer posted: {answer_url}")

    # A retry after a failed resolve must not leave a second copy of the same reply.
    # The reply carries the answer's URL, so that URL is what identifies it: an
    # earlier answer's reply is not this one's, and skipping on it would resolve the
    # thread with nothing on it pointing at the answer just posted.
    already_replied = any(answer_url in c.get("body", "") for c in comments[1:])
    if not already_replied:
        reply = f"## 🤖 {args.header}\n\n{args.message}\n\n{answer_url}"
        if not reply_to_thread(args.repo, source_pr, source_comment_db_id, reply):
            sys.exit(1)

    if not resolve_thread(args.thread_id):
        print("Answer and reply posted, but the source thread is still open.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
