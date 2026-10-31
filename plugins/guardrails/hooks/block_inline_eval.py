#!/usr/bin/env python3
"""PreToolUse guard for Bash: refuse `node` / `bun` with an inline-eval flag.

Blocked (exit 2, the reason goes back to the agent): `-e`, `--eval`, `-p`, `--print`, `--eval=...`
and short-flag clusters holding `e` or `p` (`-pe`), given to `node`, `nodejs` or `bun` before any
script file. The call is found behind env-var prefixes, wrappers (`env`, `timeout`, `nice`, `time`,
`command`, `exec`, `caffeinate`, `xargs`, `sudo`, ...), absolute paths, `npx` / `bunx` / `bun x`,
`;` `&&` `||` `|` chains, subshells, `$(...)` and backticks, `bash -c` / `sh -c` / `zsh -c`
strings, nested, and the script a shell reads on stdin from a heredoc, a here-string or a pipe from
`echo`, `printf` or `cat <<EOF`. What a file, `curl` or a variable pipes into a shell is not seen.

Why: under `-e` the parent's `process.execArgv` is `["-e", "<the whole script>"]`, and any library
that forks workers with it (jest-worker under terser, for one) makes every child re-run the script
and fork again: a fork bomb that no timeout catches.

Anything it cannot parse is allowed with a warning: the guard catches the common shapes, it does
not sandbox, and it must never block every command because of one odd string.
"""

from __future__ import annotations

import os
import re
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guard import run_guard  # noqa: E402
from shellparse import BUN_VALUE_OPTIONS, program, skip_options, walk  # noqa: E402

NODES = {"node", "nodejs"}
NODE_VALUE_OPTIONS = {"-r", "--require", "--import", "--loader", "--experimental-loader", "-C", "--conditions",
                      "--env-file", "--env-file-if-exists", "--input-type", "--inspect-port", "--title",
                      "--redirect-warnings", "--report-dir", "--report-directory", "--report-filename",
                      "--diagnostic-dir", "--icu-data-dir", "--openssl-config", "--disable-warning",
                      "--experimental-config-file", "--watch-path", "--test-reporter",
                      "--test-reporter-destination", "--stack-trace-limit", "--max-old-space-size"}
EVAL_LONG = {"--eval", "--print"}

FIX = (
    "Write the code to a file and run the file instead, so `execArgv` stays empty — under the project's "
    "scratch dir (somewhere gitignored) or `$TMPDIR`:\n"
    "    cat > \"$TMPDIR/snippet.mjs\" <<'EOF'\n"
    "    <the code>\n"
    "    EOF\n"
    "    node \"$TMPDIR/snippet.mjs\"    # or: bun \"$TMPDIR/snippet.ts\"\n"
    "A heredoc to a file like this is fine even for a one-liner."
)


def eval_flag(arg: str) -> bool:
    if arg in EVAL_LONG or arg.split("=", 1)[0] in EVAL_LONG:
        return True
    return bool(re.fullmatch(r"-[A-Za-z]+", arg)) and bool(set(arg[1:]) & {"e", "p"})


def find_eval(words: list[str], value_options: set[str]) -> int | None:
    """Index of the eval flag among a runtime's leading options; None once a script or `--` comes."""
    i = 1
    while i < len(words):
        arg = words[i]
        if arg == "--" or not arg.startswith("-") or arg == "-":
            return None
        if eval_flag(arg):
            return i
        i += 2 if arg in value_options else 1
    return None


def snippet(words: list[str], flag: int) -> str:
    shown = words[:flag + 2]
    if len(shown) > flag + 1 and len(shown[-1]) > 60:
        shown = [*shown[:-1], shown[-1][:57].split("\n", 1)[0] + "…"]
    return shlex.join(shown).replace("\n", " ")


def inline_eval(words: list[str], _cwd: object) -> str | None:
    """The visitor: the `node` / `bun` call with its eval flag, as a snippet, or None."""
    name = program(words[0])
    if name not in NODES and name != "bun":
        return None
    flag = find_eval(words, NODE_VALUE_OPTIONS if name in NODES else BUN_VALUE_OPTIONS)
    if flag is not None:
        return snippet(words, flag)
    if name == "bun":
        rest = skip_options(words[1:], BUN_VALUE_OPTIONS)
        if rest[:1] == ["run"]:
            flag = find_eval(rest, BUN_VALUE_OPTIONS)
            if flag is not None:
                return snippet([words[0], *rest], flag + 1)
    return None


def reason(found: str) -> str:
    return (
        f"Blocked by the guardrails plugin: `{found}` runs JavaScript inline. Under an eval flag "
        "`process.execArgv` holds the whole script, so any library that forks workers with it (jest-worker "
        "under terser, many build tools) re-runs the script in every child, which forks again — a fork bomb "
        "that has frozen this machine before. " + FIX
    )


def check(command: str, _cwd: object) -> str | None:
    found = walk(command, inline_eval)
    return reason(found) if found else None


def main() -> int:
    return run_guard(check, 3, "inline node/bun eval")


if __name__ == "__main__":
    sys.exit(main())
