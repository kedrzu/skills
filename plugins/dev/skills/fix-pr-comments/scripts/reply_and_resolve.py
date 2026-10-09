#!/usr/bin/env python3
"""Answer a run's PR review threads: post at each fix, reply on each thread, resolve.

A reply alone cannot work. The fix usually changes the very line the source comment
sits on, which makes that thread outdated and hides it in the Files-changed view —
where the owner reads. So the answer is a **new** review comment anchored to where
the fix now lives, posted after the push, and it stays unresolved: that is his
sign-off. The source thread gets a short reply pointing at it and is resolved.

Everything one call posts goes out as **one review per PR** (`review/scripts/pr_review.py`
says why and how), so the whole run's answers come in one call, after the last push:

1. clear a leftover pending review of ours, then skip what is already on the PR
2. per thread, add the answer at its file/line, quoting each source comment
3. add a reply on the source thread, linking to the answer
4. submit, then resolve every source thread

Idempotent, not atomic. The answer's own attribution line carries the source
comment's full permalink, so "have we already answered this thread?" is a search
for that link in a `## 🤖` comment on the PR — which is what makes a retry safe.
Resolving comes last and fails open: a failure there leaves the source thread
visible and safe to re-run, where resolving first could close a finding whose
answer never landed.

A rejected anchor falls back to the first line of that file that is in the PR's
diff. Past that, nothing is published: the pending reviews are discarded and the
call exits non-zero naming the threads, so the agent picks another file and
re-runs the batch, still as one review — picking a different file is its
judgement, not a rung in this ladder. It never degrades to a file-level comment:
those are marked outdated by any push at all, which is the one thing the answer
exists to survive.

`pr` is the node the **fix** landed on: the only PR whose diff the answer can
anchor inside. `sourcePr` names the node carrying the thread, for the rare fix
that landed elsewhere, so the reply and the quoted permalinks stay on the PR he
wrote on.
"""

import argparse
import base64
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "review" / "scripts"))

from pr_review import (  # noqa: E402
    ReviewError, add_reply, add_thread, clear_stale, discard_all, open_pending, permalink, submit,
)
from pr_stack import ChainError, is_trusted_author  # noqa: E402


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

    Only comments from trusted authors count (`is_trusted_author`, as in the fetch
    scripts): anyone can type the `## 🤖` header and the attribution line, and a
    stranger's comment must not get the thread resolved with no answer of ours on it.
    The REST `user.type` is passed as the GraphQL `__typename` — both say `User` or `Bot`.

    Exits rather than returning on a failed lookup. Falling through would post a
    second answer on exactly the retry this check exists to protect.
    """
    result, err = run([
        "gh", "api", f"repos/{repo}/pulls/{pr_number}/comments", "--paginate",
        "--jq", '.[] | select(.body | startswith("## 🤖"))'
        ' | (.html_url + " " + (.user.type // "-") + " " + (.user.login // "-") + " " + (.body | @base64))',
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
        fields = line.strip().split(" ")
        if len(fields) != 4:
            continue
        url, kind, login, encoded = fields
        body = base64.b64decode(encoded).decode("utf-8", "replace")
        if not any(anchor.match(body_line) for body_line in body.split("\n")):
            continue
        try:
            trusted = is_trusted_author(repo, {"__typename": kind, "login": login})
        except ChainError as error:
            print(f"Failed to check the author of {url}: {error}", file=sys.stderr)
            sys.exit(1)
        if trusted:
            return url
    return None


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
        description="Post fix answers on live code, reply on the source threads, resolve them — "
                    "one GitHub review per PR."
    )
    parser.add_argument(
        "--answers", required=True,
        help="JSON file: a list of {repo, pr, sourcePr?, threadId, header, message, file, line}. "
             "header: Fixed (the code changed) or Acknowledged (it did not, and the message says "
             "why). file/line: where the fix lives NOW; line 0 anchors at the file's first line "
             "in the diff.",
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
        answer["sourcePr"] = int(answer.get("sourcePr") or answer["pr"])

    reviews = {}
    try:
        # A leftover pending answer is invisible to him, so it must be gone before
        # anything below decides a thread was already answered.
        for key in {(a["repo"], pr) for a in answers for pr in (a["pr"], a["sourcePr"])}:
            clear_stale(*key)

        def review_on(repo, pr):
            if (repo, pr) not in reviews:
                reviews[(repo, pr)] = open_pending(repo, pr)
            return reviews[(repo, pr)]

        failed = []
        for answer in answers:
            repo, pr, source_pr = answer["repo"], answer["pr"], answer["sourcePr"]
            comments = fetch_thread_comments(answer["threadId"])
            if not comments or not comments[0].get("databaseId"):
                failed.append(f"{answer['threadId']}: could not read the source thread")
                continue
            answer["comments"] = comments

            answer_url = find_existing_answer(repo, pr, source_pr, comments[0]["databaseId"])
            if answer_url:
                print(f"Already answered, not posting again: {answer_url}")
            else:
                body = build_answer_body(answer["header"], answer["message"], comments, repo, source_pr)
                path, line = answer["file"], int(answer.get("line") or 0)
                comment_id = add_thread(review_on(repo, pr), path, line, body) if line > 0 else None
                if comment_id is None:
                    fallback = first_diff_line(repo, pr, path)
                    if fallback is not None and fallback != line:
                        print(f"Anchoring {path} at its first diff line ({fallback})", file=sys.stderr)
                        comment_id = add_thread(review_on(repo, pr), path, fallback, body)
                if comment_id is None:
                    failed.append(f"{answer['threadId']}: could not anchor the answer in {path}")
                    continue
                answer_url = permalink(repo, pr, comment_id)

            # The reply carries the answer's URL, so that URL is what identifies it: an
            # earlier answer's reply is not this one's, and skipping on it would resolve
            # the thread with nothing on it pointing at the answer just posted.
            if not any(answer_url in c.get("body", "") for c in comments[1:]):
                reply = f"## 🤖 {answer['header']}\n\n{answer['message']}\n\n{answer_url}"
                add_reply(review_on(repo, source_pr), answer["threadId"], reply)
            answer["url"] = answer_url

        if failed:
            discard_all(reviews.values())
            print("Nothing posted, no thread touched. Name a file the PR changed and re-run:",
                  file=sys.stderr)
            for line in failed:
                print(f"  {line}", file=sys.stderr)
            sys.exit(1)

        for key in list(reviews):
            print(f"Review submitted on {key[0]}#{key[1]}: {submit(reviews[key])}")
            del reviews[key]
    except ReviewError as error:
        # A review already submitted is published and left out; the rest are discarded.
        discard_all(reviews.values())
        print(f"Failed: {error}", file=sys.stderr)
        sys.exit(1)

    unresolved = [a["threadId"] for a in answers if not resolve_thread(a["threadId"])]
    if unresolved:
        print(f"Answers posted, but these source threads are still open: {', '.join(unresolved)}",
              file=sys.stderr)
        sys.exit(1)
    for answer in answers:
        print(f"Answered {answer['threadId']}: {answer['url']}")


if __name__ == "__main__":
    main()
