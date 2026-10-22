#!/usr/bin/env python3
"""PreToolUse guard for Bash: refuse `node` / `bun` with an inline-eval flag.

Blocked (exit 2, the reason goes back to the agent): `-e`, `--eval`, `-p`, `--print`, `--eval=...`
and short-flag clusters holding `e` or `p` (`-pe`), given to `node`, `nodejs` or `bun` before any
script file. The call is found behind env-var prefixes, wrappers (`env`, `timeout`, `nice`, `time`,
`command`, `exec`, `caffeinate`, `xargs`, `sudo`, ...), absolute paths, `npx` / `bunx` / `bun x`,
`;` `&&` `||` `|` chains, subshells, `$(...)` and backticks, and `bash -c` / `sh -c` / `zsh -c`
strings, nested or fed on stdin.

Why: under `-e` the parent's `process.execArgv` is `["-e", "<the whole script>"]`, and any library
that forks workers with it (jest-worker under terser, for one) makes every child re-run the script
and fork again: a fork bomb that no timeout catches.

Anything it cannot parse is allowed with a warning: the guard catches the common shapes, it does
not sandbox, and it must never block every command because of one odd string.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import signal
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shellparse import parse  # noqa: E402

MAX_DEPTH = 8
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\[[^]]*\])?\+?=")
KEYWORDS = {"!", "{", "}", "if", "then", "else", "elif", "fi", "do", "done", "while", "until", "coproc"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "mksh"}
NODES = {"node", "nodejs"}

# Wrappers that run the rest of their arguments as a command: options that take a separate value,
# and how many positional arguments come before the command (`timeout 90 cmd`).
WRAPPERS: dict[str, tuple[set[str], int]] = {
    "env": ({"-u", "--unset", "-C", "--chdir", "-P"}, 0),
    "timeout": ({"-s", "--signal", "-k", "--kill-after"}, 1),
    "gtimeout": ({"-s", "--signal", "-k", "--kill-after"}, 1),
    "nice": ({"-n", "--adjustment"}, 0),
    "time": ({"-f", "--format", "-o", "--output"}, 0),
    "command": (set(), 0),
    "builtin": (set(), 0),
    "exec": ({"-a"}, 0),
    "nohup": (set(), 0),
    "caffeinate": ({"-t", "-w"}, 0),
    "stdbuf": ({"-i", "-o", "-e", "--input", "--output", "--error"}, 0),
    "xargs": ({"-I", "-J", "-L", "-n", "-P", "-R", "-S", "-s", "-E", "-e", "-d", "-a", "--delimiter",
               "--arg-file", "--max-args", "--max-procs", "--max-lines", "--max-chars", "--eof"}, 0),
    "sudo": ({"-u", "--user", "-g", "--group", "-h", "--host", "-p", "--prompt", "-C", "--close-from",
              "-D", "--chdir", "-r", "--role", "-t", "--type", "-U", "--other-user", "-T", "--command-timeout"}, 0),
    "doas": ({"-u", "-C"}, 0),
    "npx": ({"-p", "--package"}, 0),
    "bunx": ({"-p", "--package"}, 0),
}
PACKAGE_RUNNERS = {"npm": {"exec", "x"}, "pnpm": {"exec", "dlx"}, "yarn": {"exec", "dlx"}}

NODE_VALUE_OPTIONS = {"-r", "--require", "--import", "--loader", "--experimental-loader", "-C", "--conditions",
                      "--env-file", "--env-file-if-exists", "--input-type", "--inspect-port", "--title",
                      "--redirect-warnings", "--report-dir", "--report-directory", "--report-filename",
                      "--diagnostic-dir", "--icu-data-dir", "--openssl-config", "--disable-warning",
                      "--experimental-config-file", "--watch-path", "--test-reporter",
                      "--test-reporter-destination", "--stack-trace-limit", "--max-old-space-size"}
BUN_VALUE_OPTIONS = {"-r", "--preload", "--require", "--import", "--cwd", "--env-file", "-c", "--config", "-d",
                     "--define", "-l", "--loader", "--tsconfig-override", "--conditions", "--port",
                     "--main-fields", "--extension-order", "--jsx-factory", "--jsx-fragment",
                     "--jsx-import-source", "--jsx-runtime", "--console-depth", "--install", "-F", "--filter",
                     "--unhandled-rejections", "--dns-result-order", "--fetch-preconnect",
                     "--max-http-header-size", "--title"}
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


def program(word: str) -> str:
    name = os.path.basename(word).lower()
    name = name.removesuffix(".exe")
    if "@" in name[1:]:
        name = name[0] + name[1:].split("@", 1)[0]
    return name


def skip_options(args: list[str], with_value: set[str]) -> list[str]:
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            return args[i + 1:]
        if not arg.startswith("-") or arg == "-":
            break
        i += 2 if arg in with_value else 1
    return args[i:]


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


def shell_script(args: list[str]) -> tuple[str, str | None]:
    """How a shell gets its script: ("c", text), ("file", None) or ("stdin", None)."""
    i, inline = 0, False
    while i < len(args):
        arg = args[i]
        if arg in ("--", "-"):
            i += 1
            break
        if arg.startswith("--"):
            i += 2 if arg in ("--rcfile", "--init-file") else 1
            continue
        if len(arg) > 1 and arg[0] in "-+":
            inline = inline or (arg[0] == "-" and "c" in arg[1:])
            i += 2 if arg[-1] in "oO" else 1
            continue
        break
    rest = args[i:]
    if inline:
        return "c", rest[0] if rest else None
    return ("file", None) if rest else ("stdin", None)


def snippet(words: list[str], flag: int) -> str:
    shown = words[:flag + 2]
    if len(shown) > flag + 1 and len(shown[-1]) > 60:
        shown = [*shown[:-1], shown[-1][:57].split("\n", 1)[0] + "…"]
    return shlex.join(shown).replace("\n", " ")


def check_command(words: list[str], stdin: list[str], depth: int) -> str | None:
    while True:
        while words and (words[0] in KEYWORDS or ASSIGNMENT.match(words[0])):
            words = words[1:]
        if not words:
            return None
        name, args = program(words[0]), words[1:]
        if name in NODES or name == "bun":
            flag = find_eval(words, NODE_VALUE_OPTIONS if name in NODES else BUN_VALUE_OPTIONS)
            if flag is not None:
                return snippet(words, flag)
            if name == "bun":
                rest = skip_options(args, BUN_VALUE_OPTIONS)
                if rest[:1] == ["x"]:
                    words = skip_options(rest[1:], WRAPPERS["bunx"][0])
                    continue
                if rest[:1] == ["run"]:
                    flag = find_eval(rest, BUN_VALUE_OPTIONS)
                    if flag is not None:
                        return snippet([words[0], *rest], flag + 1)
            return None
        if name == "command" and args[:1] and re.fullmatch(r"-[pvV]*[vV][pvV]*", args[0]):
            return None
        if name == "env" and any(a in ("-S", "--split-string") or a.startswith("--split-string=") for a in args):
            split = [a.removeprefix("--split-string=") for a in args if a not in ("-S", "--split-string")]
            return check_text(" ".join(["env", *split]), depth + 1)
        if name in ("npx", "bunx") and any(a in ("-c", "--call") for a in args):
            call = args[args.index("-c" if "-c" in args else "--call") + 1:][:1]
            return check_text(call[0], depth + 1) if call else None
        if name in WRAPPERS:
            with_value, positional = WRAPPERS[name]
            words = skip_options(args, with_value)[positional:]
            continue
        if name in PACKAGE_RUNNERS:
            rest = skip_options(args, set())
            if not rest or rest[0] not in PACKAGE_RUNNERS[name]:
                return None
            words = skip_options(rest[1:], {"-p", "--package", "-w", "--workspace", "--filter", "-F", "-C", "--dir"})
            continue
        if name == "eval":
            return check_text(" ".join(args), depth + 1)
        if name in SHELLS:
            how, text = shell_script(args)
            if how == "c":
                return check_text(text, depth + 1) if text is not None else None
            if how == "stdin":
                for body in stdin:
                    found = check_text(body, depth + 1)
                    if found:
                        return found
            return None
        return None


def check_text(command: str, depth: int = 0) -> str | None:
    if depth > MAX_DEPTH:
        return None
    for cmd in parse(command):
        found = check_command(cmd.words, cmd.stdin, depth)
        if found:
            return found
    return None


def reason(found: str) -> str:
    return (
        f"Blocked by the guardrails plugin: `{found}` runs JavaScript inline. Under an eval flag "
        "`process.execArgv` holds the whole script, so any library that forks workers with it (jest-worker "
        "under terser, many build tools) re-runs the script in every child, which forks again — a fork bomb "
        "that has frozen this machine before. " + FIX
    )


def _timeout(*_: object) -> None:
    raise TimeoutError("the command took too long to parse")


def main() -> int:
    try:
        data = json.load(sys.stdin)
        command = (data.get("tool_input") or {}).get("command") if isinstance(data, dict) else None
    except ValueError:
        return 0
    if not isinstance(command, str):
        return 0
    if hasattr(signal, "SIGALRM"):
        signal.signal(signal.SIGALRM, _timeout)
        signal.alarm(3)
    try:
        found = check_text(command)
    except Exception as error:  # fail open: one odd string must not block every command
        message = f"guardrails: could not check this command for inline node/bun eval ({error}); allowed it."
        print(json.dumps({"systemMessage": message}))
        return 0
    if found:
        print(reason(found), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
