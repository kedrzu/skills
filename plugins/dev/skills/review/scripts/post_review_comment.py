#!/usr/bin/env python3
"""Post a run's review findings as inline PR comments — one GitHub review per PR.

The shape it builds, and the rules behind it, live in this skill's
`references/comment.md`. Why one review rather than a comment each, and how a
pending review is opened and submitted, is `pr_review.py`.
"""

import argparse
import json
import sys

from pr_review import ReviewError, add_thread, discard_all, open_pending, permalink, submit


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


def main():
    parser = argparse.ArgumentParser(
        description="Post a run's review findings as inline comments, one GitHub review per PR."
    )
    parser.add_argument(
        "--findings", required=True,
        help="JSON file: a list of {repo, pr, file, line, severity, category, provenance, delta, "
             "claim, consequence, details}. `line` 0 posts at file level; `file` is relative to "
             "that PR's repo root; `details` is optional.",
    )
    args = parser.parse_args()

    with open(args.findings) as f:
        findings = json.load(f)
    for finding in findings:
        if finding.get("severity") not in SEVERITY_STYLE:
            print(f"Unknown severity {finding.get('severity')!r}: one of {sorted(SEVERITY_STYLE)}",
                  file=sys.stderr)
            sys.exit(1)

    reviews = {}
    posted = []
    failed = []
    try:
        for finding in findings:
            key = (finding["repo"], int(finding["pr"]))
            if key not in reviews:
                reviews[key] = open_pending(*key)
            review = reviews[key]

            body = build_body(
                finding["severity"], finding["category"], finding["provenance"],
                finding["delta"], finding["claim"], finding["consequence"],
                finding.get("details", ""),
            )
            path, line = finding["file"], int(finding.get("line") or 0)
            where = f"{path}:{line}" if line else f"{path}, file-level"

            comment_id = add_thread(review, path, line, body)
            # A rejected line falls back to file level, loudly: GitHub marks a
            # file-level comment outdated on every push, and a rejected line usually
            # means the finding was routed to the wrong node.
            if comment_id is None and line:
                print(
                    f"WARNING: PR #{key[1]} would not take a comment at {where} — the line is "
                    "not in its diff. Check the finding is on the right node; falling back to a "
                    "file-level comment, which any push marks outdated."
                )
                where = f"{path}, file-level"
                comment_id = add_thread(review, path, 0, body)
            if comment_id is None:
                failed.append(f"PR #{key[1]} {where}: not in this PR's diff")
                continue
            posted.append((key, where, permalink(key[0], key[1], comment_id)))

        if failed:
            # Nothing is published yet: discarding keeps the run one review once
            # the poster has fixed the routing and re-runs it.
            discard_all(reviews.values())
            print("Nothing posted. These findings could not be anchored:", file=sys.stderr)
            for line in failed:
                print(f"  {line}", file=sys.stderr)
            sys.exit(1)

        for key in list(reviews):
            print(f"Review submitted on {key[0]}#{key[1]}: {submit(reviews[key])}")
            del reviews[key]
        for key, where, url in posted:
            print(f"Comment posted at {where} on #{key[1]}: {url}")
    except ReviewError as error:
        # A review already submitted is published and left out; the rest are discarded.
        discard_all(reviews.values())
        print(f"Failed: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
