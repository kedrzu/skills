#!/usr/bin/env python3
"""Prove a change to this marketplace works — the steps CI runs, and the `verify` skill's two modes.

  verify.py --scoped     the plugins the change touched (working tree included)
  verify.py --full       every plugin
  --base <ref>           what the change is measured against; default: the open PR's base, else
                         origin/main. An empty value skips the version guard (CI with no base).

Exits non-zero when any check fails. Inside GitHub Actions the output is grouped and failures
are annotated on the file.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGINS = ROOT / "plugins"
GITHUB = os.environ.get("GITHUB_ACTIONS") == "true"
# A change here can break any plugin's checks, so it widens a scoped run to all of them.
GLOBAL_PATHS = (".claude-plugin/", ".github/", "plugins/verify/")

failures: list[str] = []


@contextmanager
def group(title: str):
    print(f"::group::{title}" if GITHUB else f"\n== {title}", flush=True)
    try:
        yield
    finally:
        if GITHUB:
            print("::endgroup::", flush=True)


def fail(message: str, file: Path | None = None, line: int | None = None) -> None:
    where = ""
    if file is not None:
        where = str(file.relative_to(ROOT)) + (f":{line}" if line else "")
    if GITHUB:
        loc = f" file={file.relative_to(ROOT)}" + (f",line={line}" if line else "") if file else ""
        print(f"::error{loc}::{message}", flush=True)
    else:
        print(f"✘ {where + ': ' if where else ''}{message}", flush=True)
    failures.append(f"{where + ': ' if where else ''}{message}")


def run(cmd: list[str], cwd: Path = ROOT) -> bool:
    print("$ " + " ".join(cmd), flush=True)
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    ok = subprocess.run(cmd, cwd=cwd, env=env).returncode == 0
    if not ok:
        fail(f"`{' '.join(cmd)}` failed (in {cwd.relative_to(ROOT) or '.'})")
    return ok


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def resolve_base(arg: str | None) -> str | None:
    """The merge-base of HEAD with the ref the change is measured against, or None."""
    if arg == "":
        return None
    ref = arg
    if ref is None:
        pr = subprocess.run(["gh", "pr", "view", "--json", "baseRefName", "--jq", ".baseRefName"],
                            cwd=ROOT, capture_output=True, text=True)
        ref = f"origin/{pr.stdout.strip()}" if pr.returncode == 0 and pr.stdout.strip() else "origin/main"
    try:
        return git("merge-base", ref, "HEAD").strip()
    except subprocess.CalledProcessError:
        print(f"⚠ no merge-base with {ref}: the version guard is skipped", flush=True)
        return None


def changed_paths(base: str) -> set[str]:
    paths = set(git("diff", "--name-only", base).split())
    paths |= set(git("ls-files", "--others", "--exclude-standard").split())
    return paths


def all_plugins() -> list[str]:
    return sorted(p.parent.parent.name for p in PLUGINS.glob("*/.claude-plugin/plugin.json"))


def manifest(name: str) -> dict:
    return json.loads((PLUGINS / name / ".claude-plugin" / "plugin.json").read_text())


def check_version(name: str, base: str) -> None:
    path = f"plugins/{name}/.claude-plugin/plugin.json"
    new = manifest(name).get("version")
    try:
        old = json.loads(git("show", f"{base}:{path}")).get("version")
    except subprocess.CalledProcessError:
        print(f"{name}: new plugin, no previous version to compare", flush=True)
        return
    if old == new:
        fail(f"{name} changed but its version is still {old} — bump it here and in "
             ".claude-plugin/marketplace.json", ROOT / path)
    else:
        print(f"{name}: {old} -> {new}", flush=True)


def check_server(name: str) -> None:
    server = PLUGINS / name / "server"
    package = json.loads((server / "package.json").read_text())
    if package.get("version") != manifest(name).get("version"):
        fail(f"version {package.get('version')} differs from plugin.json {manifest(name).get('version')}",
             server / "package.json")
    if not shutil.which("bun"):
        fail("bun is not installed, so the server was not checked — that is not a pass", server)
        return
    for cmd in (["bun", "install", "--frozen-lockfile"], ["bunx", "tsc", "--noEmit"], ["bun", "test"]):
        if not run(cmd, server):
            return


def check_python_tests(name: str) -> None:
    dirs = sorted({t.parent for t in (PLUGINS / name).rglob("test_*.py") if "node_modules" not in t.parts})
    for d in dirs:
        run([sys.executable, "-m", "unittest", "discover", "-s", str(d), "-p", "test_*.py"])


PLUGIN_ROOT_REF = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([A-Za-z0-9_./-]+)")
MD_LINK = re.compile(r"\]\(([^)\s]+)\)")
MCP_REF = re.compile(r"mcp__plugin_([a-z0-9-]+)_")
# `plugin:skill` reached by the model. A slash command (`/plugin:skill`) is excluded: pointing the
# user at another plugin's command is allowed without depending on it.
SKILL_REF = re.compile(r"(?<![\w/.:-])([a-z0-9-]+):([a-z0-9-]+)\b")


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def outside_code(text: str) -> str:
    """The text with fenced blocks and inline code blanked out, line numbers kept — an example link
    written as code is not a link."""
    out, fenced = [], False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            out.append("")
        else:
            out.append("" if fenced else line)
    return re.sub(r"`[^`]*`", lambda m: re.sub(r"[^\n]", " ", m.group()), "\n".join(out))


def check_references(name: str, plugins: list[str], skills: dict[str, set[str]]) -> None:
    root = PLUGINS / name
    deps = {d if isinstance(d, str) else d.get("name") for d in manifest(name).get("dependencies", [])}
    home = str(Path.home()) + "/"
    files = [f for f in root.rglob("*")
             if f.suffix in (".md", ".json") and f.is_file() and "node_modules" not in f.parts]
    for f in sorted(files):
        text = f.read_text(encoding="utf-8")

        if home in text:
            fail(f"absolute path from this machine ({home}…) — use ${{CLAUDE_PLUGIN_ROOT}}", f,
                 line_of(text, text.index(home)))

        for m in PLUGIN_ROOT_REF.finditer(text):
            rel = m.group(1).rstrip(".").rstrip("/")
            if rel and not (root / rel).exists():
                fail(f"${{CLAUDE_PLUGIN_ROOT}}/{rel} does not exist", f, line_of(text, m.start()))

        if f.suffix == ".md":
            prose = outside_code(text)
            for m in MD_LINK.finditer(prose):
                target = m.group(1).split("#")[0]
                if not target or "://" in target or target.startswith(("mailto:", "$", "/", "<")):
                    continue
                if not (f.parent / target).exists():
                    fail(f"link target {target} does not exist", f, line_of(prose, m.start()))

        if f.name == "README.md":
            continue  # a README talks about other plugins to a human; it reaches none of them
        for m in MCP_REF.finditer(text):
            other = m.group(1)
            if other != name and other in plugins and other not in deps:
                fail(f"uses the {other} plugin's MCP tools without declaring \"{other}\" in dependencies",
                     f, line_of(text, m.start()))
        for m in SKILL_REF.finditer(text):
            other, skill = m.groups()
            if other != name and skill in skills.get(other, ()) and other not in deps:
                fail(f"reaches {other}:{skill} without declaring \"{other}\" in dependencies",
                     f, line_of(text, m.start()))

    for skill_md in sorted(root.glob("skills/*/SKILL.md")):
        front = re.match(r"---\n(.*?)\n---", skill_md.read_text(encoding="utf-8"), re.S)
        found = front and re.search(r"^name:\s*['\"]?([^'\"\n]+?)['\"]?\s*$", front.group(1), re.M)
        if not found:
            fail("no `name` in the frontmatter", skill_md)
        elif found.group(1) != skill_md.parent.name:
            fail(f"frontmatter name `{found.group(1)}` differs from the directory `{skill_md.parent.name}`",
                 skill_md)


def check_evals(name: str) -> None:
    if not (PLUGINS / name / "evals").is_dir():
        return
    if os.environ.get("CI"):
        print(f"{name}: evals skipped in CI (no API key)", flush=True)
        return
    run(["claude", "plugin", "eval", name])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--scoped", action="store_true")
    mode.add_argument("--full", action="store_true")
    parser.add_argument("--base")
    args = parser.parse_args()

    plugins = all_plugins()
    skills = {p: {s.parent.name for s in (PLUGINS / p).glob("skills/*/SKILL.md")} for p in plugins}
    base = resolve_base(args.base)
    changed = changed_paths(base) if base else set()
    touched = {p for p in plugins if any(c.startswith(f"plugins/{p}/") for c in changed)}

    full = args.full or any(c.startswith(GLOBAL_PATHS) for c in changed)
    if args.scoped and full:
        print("A marketplace-wide file changed (marketplace.json, CI or this script): checking every plugin",
              flush=True)
    scope = plugins if full else sorted(touched)

    if not shutil.which("claude"):
        fail("the claude CLI is not installed, so nothing was validated — that is not a pass")
        return 1

    with group("marketplace"):
        run(["claude", "plugin", "validate", ".", "--strict"])
    if base:
        with group("version guard"):
            for name in sorted(touched):
                check_version(name, base)
    for name in scope:
        with group(name):
            run(["claude", "plugin", "validate", f"./plugins/{name}", "--strict"])
            check_references(name, plugins, skills)
            if (PLUGINS / name / "server" / "package.json").exists():
                check_server(name)
            check_python_tests(name)
            if full:
                check_evals(name)

    label = "full" if full else f"scoped ({', '.join(scope) or 'no plugin changed'})"
    if failures:
        print(f"\n✘ verify {label}: {len(failures)} failure(s)", flush=True)
        for f in failures:
            print(f"  - {f}", flush=True)
        return 1
    print(f"\n✔ verify {label}: green", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
