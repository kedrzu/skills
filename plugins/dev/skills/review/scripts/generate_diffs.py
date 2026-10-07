#!/usr/bin/env python3
"""Per-file diffs for code review, one set per node of the branch's PR chain.

Usage: generate_diffs.py [base-branch]

Requires git >= 2.40 (`git check-attr --source`).

Output: .context/reviews/<branch-slug>/diffs/ — per-file `.diff` files,
`manifest.txt` (source path → diff file), `full.diff`, `submodules.json` and
`nodes.json`.

When the branch's pull request belongs to a GitHub stack, every node of the chain
additionally gets its own diff set under `diffs/nodes/<k>/`, generated
`base...node` — exactly what GitHub computes for that pull request — while
`diffs/` itself carries the whole chain. An unstacked branch is the same thing
with one node: `nodes.json` holds a single entry whose `diffs` is `"."`.

The nodes come from `pr_stack.py`, which is also what the review and fix scripts
use; nothing here re-derives them. Discovery failing stops the run: quietly
deciding "this is an ordinary PR" would put the whole chain's findings on the tip
PR.

Only `diffs/` is cleared each run — the rest of the branch workspace is left
alone — and only once the chain is known and every node's commit is in hand, so
an aborted run leaves the previous diffs in place.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pr_stack

def fail(*lines):
    for line in lines:
        print(line, file=sys.stderr)
    sys.exit(1)


def git(*args, cwd=None):
    """Run git and return the CompletedProcess. Bytes survive as surrogates."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        encoding="utf-8",
        errors="surrogateescape",
    )


def git_out(*args, cwd=None):
    """git's stdout with trailing whitespace stripped, or None if it failed."""
    result = git(*args, cwd=cwd)
    return None if result.returncode else result.stdout.strip()


def write(path, text):
    path.write_text(text, encoding="utf-8", errors="surrogateescape")


class DiffSet:
    """One node's (or the chain's) diff set: the files, the manifest, full.diff.

    The sequence number spans the main repo and the submodules together: `a/b.ts`
    and `a__b.ts` both sanitize to `a__b.ts`, and without it the second file would
    overwrite the first while both manifest rows point at the survivor.
    """

    def __init__(self, out_dir):
        self.dir = out_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.manifest = []
        self.full = []

    def add(self, path, content, label=None):
        name = f"{len(self.manifest) + 1}-{path.replace('/', '__')}.diff"
        content = content.rstrip("\n") + "\n"
        write(self.dir / name, content)
        self.manifest.append(f"{path}\t{name}")
        self.full.append(f"=== FILE: {label or path} ===\n{content}\n")

    def flush(self, submodules):
        write(self.dir / "manifest.txt", "".join(f"{row}\n" for row in self.manifest))
        write(self.dir / "full.diff", "".join(self.full))
        write(
            self.dir / "submodules.json",
            json.dumps(submodules, separators=(",", ":"), ensure_ascii=False) + "\n",
        )
        return len(self.manifest)


def changed_files(*args, cwd=None, what):
    """`--name-only -z` as a list. -z is also what keeps non-ASCII paths intact:
    with core.quotePath on (the default) git C-quotes them, and feeding that back
    as a pathspec matches nothing — the file would leave the review with no error
    anywhere."""
    result = git("diff", "-z", "--name-only", *args, cwd=cwd)
    if result.returncode:
        fail(f"ERROR: could not list the files changed {what}.", result.stderr.rstrip())
    return [name for name in result.stdout.split("\0") if name]


def file_diff(rev_range, path, cwd=None):
    """One file's patch. quotePath off so the `+++ b/…` header inside the patch
    reads as the same path the manifest carries — that path is what a finding is
    posted against."""
    result = git("-c", "core.quotePath=false", "diff", rev_range, "--", path, cwd=cwd)
    if result.returncode:
        fail(f"ERROR: could not diff {path} over {rev_range}.", result.stderr.rstrip())
    return result.stdout


def generated_paths(paths, rev, cwd=None):
    """The subset of `paths` marked `linguist-generated` — output nobody reviews.

    The attribute is read from `.gitattributes` as of `rev`, the revision being
    diffed, so a node is filtered exactly as GitHub filters that PR's diff rather
    than by whatever the working tree says. `set` and `true` skip a file; `unset`,
    `false` and `unspecified` keep it. A deleted file is matched by pattern like any
    other, since attributes are looked up by path.

    One process for the whole list: -z with --stdin keeps odd paths intact and the
    output unambiguous (path, attribute, value triples).
    """
    result = subprocess.run(
        ["git", "check-attr", "-z", "--stdin", f"--source={rev}", "linguist-generated"],
        cwd=cwd,
        input="".join(f"{path}\0" for path in paths),
        capture_output=True,
        encoding="utf-8",
        errors="surrogateescape",
    )
    if result.returncode:
        fail(
            f"ERROR: could not read the linguist-generated attribute at {rev}"
            + (f" in {cwd}" if cwd else "") + ".",
            result.stderr.rstrip(),
            "       `git check-attr --source` needs git >= 2.40.",
        )
    fields = result.stdout.split("\0")
    return {
        fields[i]
        for i in range(0, len(fields) - 2, 3)
        if fields[i + 2] in ("set", "true")
    }


def ensure_commit(sha, ref):
    if git_out("rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}") is not None:
        return True
    git("fetch", "--quiet", "origin", f"+refs/heads/{ref}:refs/remotes/origin/{ref}")
    return git_out("rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}") is not None


def ensure_submodule_commit(sm_path, sha):
    """A submodule commit we do not hold locally is the same failure as a missing
    superproject commit, and it is the likeliest one here: a submodule's work lives
    in the bottom node while review stands at the tip. Silently dropping the diff would
    hide the whole submodule's work."""
    for attempt in range(2):
        if git_out("rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}", cwd=sm_path) is not None:
            return
        if attempt == 0:
            git("fetch", "--quiet", "origin", cwd=sm_path)
    fail(
        f"ERROR: submodule {sm_path} does not have commit {sha} locally and it could not be fetched.",
        f"       Run 'git -C {sm_path} fetch origin' and re-run.",
    )


def add_submodule_diffs(diff_set, sm_path, merge_base, head_rev, empty_tree):
    """The submodule's own files for one gitlink move, and its manifest entry."""
    old = (git_out("ls-tree", merge_base, "--", sm_path) or "").split()
    new = (git_out("ls-tree", head_rev, "--", sm_path) or "").split()
    sm_old = old[2] if len(old) > 2 else ""
    sm_new = new[2] if len(new) > 2 else ""

    added = not sm_old
    if added:
        sm_old = empty_tree
    if not sm_new or sm_old == sm_new:
        return None

    if not added:
        ensure_submodule_commit(sm_path, sm_old)
    ensure_submodule_commit(sm_path, sm_new)

    remote = git_out("remote", "get-url", "origin", cwd=sm_path) or ""
    repo = re.sub(r".*github\.com[:/]", "", re.sub(r"\.git$", "", remote)) if remote else ""
    rev_range = f"{sm_old}..{sm_new}"

    sm_files = changed_files(rev_range, cwd=sm_path, what=f"in submodule {sm_path} over {rev_range}")
    skipped = generated_paths(sm_files, sm_new, cwd=sm_path)
    for sm_file in sm_files:
        if sm_file in skipped:
            continue
        content = file_diff(rev_range, sm_file, cwd=sm_path)
        if content:
            diff_set.add(f"{sm_path}/{sm_file}", content, label=f"{sm_path}/{sm_file} (submodule: {sm_path})")

    return {
        "path": sm_path,
        "remote": repo,
        "branch": git_out("branch", "--show-current", cwd=sm_path) or "",
        "oldCommit": sm_old,
        "newCommit": sm_new,
    }


def generate_diff_set(out_dir, base, head_rev, submodule_paths, empty_tree):
    """Write one diff set and return the number of files it covered.

    Both revs are commits: the review workspace is required to be clean and
    pushed, so there is no uncommitted work to fold in and the diff a finder reads
    is exactly the diff GitHub shows for that pull request.
    """
    # The PR's base is a bare branch name, and GitHub diffs against the remote's
    # copy of it — so `origin/<base>` wins whenever it resolves. A local branch of
    # that name is often stale (origin merged in, local never pulled), and its old
    # tip would pull every commit the base gained since into the range. The name
    # itself is the fallback: a clone with no remote copy, or a base that is a
    # commit, as a stacked node's is.
    def resolves(rev):
        return git_out("rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}") is not None

    remote = f"origin/{base}"
    base_rev = remote if resolves(remote) else base
    if not resolves(base_rev):
        fail(
            f"ERROR: base '{base}' resolves neither as '{remote}' nor locally, so there is no range to review.",
            f"       Fetch the base branch ('git fetch origin {base}') and re-run.",
        )
    merge_base = git_out("merge-base", base_rev, head_rev)
    if merge_base is None:
        fail(
            f"ERROR: '{base_rev}' and '{head_rev}' have no merge base, so there is no range to review.",
            f"       Fetch the base branch ('git fetch origin {base}') and re-run.",
        )

    diff_set = DiffSet(out_dir)
    rev_range = f"{merge_base}...{head_rev}"
    paths = [
        path for path in changed_files(rev_range, what=f"between {merge_base} and {head_rev}")
        if path not in submodule_paths
    ]
    skipped = generated_paths(paths, head_rev)
    for path in paths:
        if path in skipped:
            continue
        content = file_diff(rev_range, path)
        if content:
            diff_set.add(path, content)

    submodules = {}
    for sm_path in submodule_paths:
        entry = add_submodule_diffs(diff_set, sm_path, merge_base, head_rev, empty_tree)
        if entry:
            submodules[sm_path] = entry

    return diff_set.flush(submodules)


def render_nodes_json(chain_base, current_index, rows, stack_number=None):
    """nodes.json, laid out one node per line — five finder agents and the poster
    read it, and a node is what they read it for."""
    head = {"stacked": stack_number is not None}
    if stack_number is not None:
        head["stackNumber"] = stack_number
    head.update({"base": chain_base, "currentNode": current_index, "topNode": len(rows)})

    def dump(value):
        return json.dumps(value, ensure_ascii=False)

    header = "".join(f"  {dump(key)}: {dump(value)},\n" for key, value in head.items())
    body = ",\n".join(
        "    { " + ", ".join(f"{dump(key)}: {dump(value)}" for key, value in row.items()) + " }"
        for row in rows
    )
    return "{\n" + header + '  "nodes": [\n' + body + "\n  ]\n}\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "base", nargs="?", default=None,
        help="Base branch of the chain (default: the stack's own base, else the PR's base "
             "branch, else the repository's default branch when there is no PR)",
    )
    args = parser.parse_args()

    repo_root = git_out("rev-parse", "--show-toplevel")
    if not repo_root:
        fail("ERROR: not in a git repository.")
    repo_root = Path(repo_root)
    os.chdir(repo_root)

    # One implementation, in pr_stack.py, and it stops the run rather than degrading.
    try:
        chain = pr_stack.describe_chain(cwd=str(repo_root))
    except pr_stack.ChainError as error:
        fail(
            f"ERROR: {error}",
            "ERROR: could not determine the PR chain — refusing to review a shape we cannot name.",
        )

    # Discovery already refused a tree with no branch, so the slug is always the
    # branch's own name.
    branch = chain["branch"]
    review_dir = repo_root / ".context" / "reviews" / branch.replace("/", "-")
    output_dir = review_dir / "diffs"

    submodule_paths = [
        line for line in (git_out("submodule", "--quiet", "foreach", "echo $sm_path") or "").splitlines() if line
    ]
    empty_tree = git_out("hash-object", "-t", "tree", "/dev/null")

    # An explicit argument wins, then the bottom node's base (the stack's own base,
    # else the PR's base branch), then — only with no PR at all, the one case that
    # leaves it None — the repository's default branch.
    nodes = chain["nodes"]
    chain_base = args.base or nodes[0]["base"]
    if not chain_base:
        try:
            chain_base = pr_stack.get_default_branch(chain["repo"])
        except pr_stack.ChainError as error:
            fail(f"ERROR: {error}")
    current_index = chain["currentNode"]
    local_head = git_out("rev-parse", "HEAD")

    # The rev a node is diffed from must be the commit its comments will anchor
    # to, or a finding lands on a commit that does not contain the code.
    current = nodes[current_index - 1]
    if current["headSha"] and current["headSha"] != local_head:
        fail(
            f"ERROR: this worktree is at {local_head} but PR #{current['prNumber']} has head {current['headSha']}.",
            "       Comments anchor to the PR's head, so the diff must be that commit. Push it (git-workflow → checkpoint), "
            "or bring the stack up to date (git-workflow → stack), and re-run.",
        )

    # Every node's commit has to be in hand before anything is written, so a chain
    # we cannot diff aborts with the previous run's diffs still on disk.
    for node in nodes:
        if node["headSha"] and not ensure_commit(node["headSha"], node["branch"]):
            fail(
                f"ERROR: commit {node['headSha']} of node {node['index']} ({node['branch']}) "
                "is not available locally and could not be fetched."
            )

    # Clean ONLY the diffs subfolder, and only now that the chain is known and
    # usable — never the surrounding workspace, never before a run that might abort.
    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True)

    def diff_set(out_dir, base_rev, head_rev):
        return generate_diff_set(out_dir, base_rev, head_rev, submodule_paths, empty_tree)

    # A node's diff is base...node, where the base is the node below it — the same
    # range GitHub computes for that pull request, so a line in it can be commented
    # on and a line outside it cannot. Unstacked is this with one node: its set is
    # the root, its base the chain's, and its head the commit checked out.
    stacked = chain["stacked"]
    rows = []
    for node in nodes:
        head_sha = node["headSha"] or local_head
        base_rev = chain_base if node["index"] == 1 else nodes[node["index"] - 2]["headSha"]
        out_dir = output_dir / "nodes" / str(node["index"]) if stacked else output_dir
        files = diff_set(out_dir, base_rev, head_sha)
        rows.append({
            "index": node["index"], "prNumber": node["prNumber"], "branch": node["branch"],
            "headSha": head_sha, "base": chain_base if node["index"] == 1 else node["base"],
            "diffs": f"nodes/{node['index']}" if stacked else ".",
            "files": files, "isCurrent": node["index"] == current_index,
        })

    if stacked:
        files = diff_set(output_dir, chain_base, rows[-1]["headSha"])
    write(
        output_dir / "nodes.json",
        render_nodes_json(chain_base, current_index, rows, chain["stackNumber"] if stacked else None),
    )

    print(f"Review workspace: {review_dir}")
    if stacked:
        print(f"Stack #{chain['stackNumber']}: {len(nodes)} nodes on {chain_base}")
        for row in rows:
            marker = " (checked out)" if row["isCurrent"] else ""
            print(f"  Node {row['index']} — PR #{row['prNumber']} {row['branch']}: "
                  f"{row['files']} files → nodes/{row['index']}{marker}")
    if stacked and current_index != len(nodes):
        # Flushed first: redirected to a file, python's stdout is block-buffered and
        # this unbuffered warning would otherwise jump ahead of the node list.
        sys.stdout.flush()
        print(f"WARNING: standing on node {current_index} of {len(nodes)} — "
              "the working tree is not the chain's tip.", file=sys.stderr)
    print(f"Generated diffs for {files} files in {output_dir}" if files
          else "No reviewable changed files found.")


if __name__ == "__main__":
    main()
