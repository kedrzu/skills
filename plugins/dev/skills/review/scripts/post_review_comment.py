#!/usr/bin/env python3
"""Post one review finding as an inline PR comment.

The shape it builds, and the rules behind it, live in this skill's
`references/comment.md`.
"""

import argparse
import json
import subprocess
import sys


# Severity → (emoji, label) for line 1. These two markers are also the authorship
# test: a comment is ours iff its body starts with one of them.
SEVERITY_STYLE = {
    "blocking": ("🚨", "BLOCKING"),
    "nit": ("💡", "NIT"),
}

# Constant, so no caller has to remember it: a finding is written against the code
# at review time and acted on later, by which point the code may have moved.
STALENESS_NOTE = (
    "Check this still holds before changing anything — if the code has moved, "
    "say so instead of fixing."
)


def run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return None, result.stderr.strip()
    return result.stdout.strip(), None


def build_body(severity, category, provenance, delta, claim, consequence, details):
    emoji, label = SEVERITY_STYLE[severity]

    parts = [
        f"## {emoji} {label} — {category}",
        f"_{provenance} · fix {delta}_",
        "",
        f"**{claim}**",
        "",
        consequence,
    ]

    # Always emitted, even with no citations: the staleness instruction is what
    # replaced the separate critic phase, so a finding must never reach the fixer
    # without it.
    parts += [
        "",
        "<details><summary>🤖 Details for the fixing agent</summary>",
        "",
        STALENESS_NOTE,
    ]
    if details:
        parts += ["", details]
    parts.append("</details>")

    return "\n".join(parts)


def create_review_comment(repo, pr_number, sha, body, path, line):
    """Create a review comment on the diff."""
    cmd = [
        "gh", "api", f"repos/{repo}/pulls/{pr_number}/comments",
        "-f", f"body={body}",
        "-f", f"commit_id={sha}",
        "-f", f"path={path}",
    ]

    if line is not None and line > 0:
        cmd += ["-F", f"line={line}", "-f", "side=RIGHT"]
    else:
        cmd += ["-f", "subject_type=file"]

    result, err = run(cmd)
    if result is None:
        print(f"Review comment failed: {err}", file=sys.stderr)
        return False

    data = json.loads(result)
    where = f"at {path}:{line}" if line else f"on {path}, file-level"
    print(f"Comment posted {where}: {data.get('html_url', 'ok')}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Post a review finding as an inline PR comment.")
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--pr", required=True, type=int, help="PR number")
    parser.add_argument("--sha", required=True, help="PR head commit SHA")
    parser.add_argument("--file", required=True, help="File path, relative to the PR's repo root")
    parser.add_argument("--line", required=True, type=int, help="Line number (0 for file-level)")
    parser.add_argument("--severity", required=True, choices=sorted(SEVERITY_STYLE))
    parser.add_argument("--category", required=True, help="Short category, e.g. data-integrity")
    parser.add_argument(
        "--provenance", required=True,
        help="Axis, plus the rule's source where the finding rests on a rule "
             "(e.g. 'Security · <the project's rule source> → audit at business boundary')",
    )
    parser.add_argument("--delta", required=True, help="e.g. 'adds ~6 lines' / 'removes ~12 lines'")
    parser.add_argument("--claim", required=True, help="The claim in plain words (the owner's language, one line)")
    parser.add_argument(
        "--consequence", required=True,
        help="What goes wrong, for whom, when (the owner's language, the paragraph he judges on)",
    )
    parser.add_argument("--details", default="", help="Collapsed agent layer (English)")
    args = parser.parse_args()

    body = build_body(
        args.severity, args.category, args.provenance, args.delta,
        args.claim, args.consequence, args.details,
    )

    line = args.line if args.line > 0 else None

    # Try posting at file+line, fall back to file-level. The fallback is reported
    # loudly on stdout: GitHub marks a file-level comment outdated on every push,
    # and a rejected line usually means the finding was routed to the wrong node.
    posted = create_review_comment(args.repo, args.pr, args.sha, body, args.file, line)
    if not posted and line is not None:
        print(
            f"WARNING: PR #{args.pr} would not take a comment at {args.file}:{line} — "
            "the line is not in its diff. Check the finding is on the right node; "
            "falling back to a file-level comment, which any push marks outdated."
        )
        posted = create_review_comment(args.repo, args.pr, args.sha, body, args.file, None)
    if not posted:
        print("Failed to post comment.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
