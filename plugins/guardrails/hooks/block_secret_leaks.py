#!/usr/bin/env python3
"""PreToolUse guard for Bash: refuse a command that would print a secret value into the transcript.

Whatever a command prints stays in the session transcript for good, so a printed value is a leaked
value and has to be rotated. The `secrets` commands of `@nzyme/secrets` never print values; the leaks
come from around them. Blocked (exit 2, the reason goes back to the agent):

- an environment dump run by `secrets run -- <cmd>` or `bws run -- <cmd>`, which fill it with every
  mapped secret: `env` with no command, `printenv`, `set`, `export` / `export -p`, `declare -p` /
  `-x`, `typeset` alike;
- another process's environment, which holds the secrets of a dev server started with `secrets run`:
  `/proc/<pid>/environ` read by any command, `ps` with `e` (BSD style) or `-E` (macOS);
- a password read out of the OS keychain, for any service: `security find-generic-password` /
  `find-internet-password` with `-w` or `-g`, `security dump-keychain -d`, `secret-tool lookup` /
  `search`;
- the store credential printed: `$BWS_ACCESS_TOKEN` given to `echo` / `printf` / `print` or on the
  stdin of `cat` / `tee`, `printenv BWS_ACCESS_TOKEN`, `declare -p BWS_ACCESS_TOKEN`, an environment
  dump piped into `grep BWS` (or `TOKEN`, `ACCESS`);
- values fetched from Bitwarden: `bws secret get|list|create|edit` (and the old `bws get secret`).

`secrets` is matched as a subcommand of any CLI (`bun nzyme secrets run`, `<product-cli> secrets run`),
and every command is found wherever a shell would run it (`shellparse.walk()`). A script file that reads
the keychain (`Bun.secrets.get`) is out of reach. Anything it cannot parse is allowed with a warning.
"""

from __future__ import annotations

import os
import re
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guard import run_guard  # noqa: E402
from shellparse import Command, program, skip_options, strip_prefixes, walk  # noqa: E402

CREDENTIALS = ("BWS_ACCESS_TOKEN",)
REFERENCE = re.compile(r"\$\{?(" + "|".join(CREDENTIALS) + r")\b")
PROC_ENVIRON = re.compile(r"^/proc/[^/]+(/task/[^/]+)?/environ$")
PRINTERS = {"echo", "printf", "print"}
STDIN_PRINTERS = {"cat", "tee"}
FILTERS = {"grep", "egrep", "fgrep", "rg", "ag", "ack"}
DECLARES = {"declare", "typeset", "local"}

BWS_VALUE_OPTIONS = {"-o", "--output", "-c", "--color", "-t", "--access-token", "-f", "--config-file", "-p",
                     "--profile", "--server-url"}
BWS_RUN_VALUE_OPTIONS = {"--project-id", "--shell"}
BWS_FETCH = {"get", "list", "create", "edit"}
SECURITY_VALUE_OPTIONS = {"-a", "-c", "-C", "-d", "-D", "-G", "-j", "-l", "-p", "-P", "-r", "-s", "-t"}

WHY = (
    "Whatever a command prints stays in the session transcript for good — it is stored, synced and "
    "re-read — so a value printed there is leaked and has to be rotated where it was issued."
)
INSTEAD = (
    "Instead:\n"
    "    secrets list                          # is each secret set? (names and statuses, no values)\n"
    "    secrets run -- <the real command>     # run the app or test that uses them\n"
    "    secrets set NAME --prompt=\"<hint>\"    # ask the user for a value in a masked dialog\n"
    "(prefixed the way this repo runs its CLI: `bun nzyme secrets …` or the product's own CLI). To check a "
    "value is right, run what uses it."
)
WHAT = {
    "env": "prints the environment that `secrets run` filled with every mapped secret",
    "process": "prints another process's environment, where a dev server started with `secrets run` holds "
               "every mapped secret",
    "keychain": "prints a password from the OS keychain. `@nzyme/secrets` keeps its store tokens and cached "
                "values there (service `nzyme-secrets`), next to every other saved password, so any service "
                "is refused",
    "credential": "prints the secret-store credential `BWS_ACCESS_TOKEN`, which unlocks every secret its "
                  "machine account can read; tools that need it read it from the environment themselves",
    "store": "fetches secret values straight from Bitwarden Secrets Manager and prints them",
}


def shown(words: list[str]) -> str:
    text = shlex.join(words).replace("\n", " ")
    return text if len(text) <= 80 else text[:79] + "…"


def run_target(words: list[str]) -> list[str] | None:
    """The command `secrets run -- <cmd>` or `bws run -- <cmd>` starts, or None for anything else."""
    name, args = program(words[0]), words[1:]
    if name == "bws":
        rest = skip_options(args, BWS_VALUE_OPTIONS)
        return skip_options(rest[1:], BWS_RUN_VALUE_OPTIONS) if rest[:1] == ["run"] else None
    # `nzyme secrets`, `bun nzyme secrets`, `bun ./cli.ts secrets`, `bun --cwd x cli secrets`
    if "secrets" not in args[:4]:
        return None
    rest = skip_options(args[args.index("secrets") + 1:], set())
    return skip_options(rest[1:], set()) if rest[:1] == ["run"] else None


def dumps_env(words: list[str]) -> bool:
    name, args = program(words[0]), words[1:]
    if name == "printenv":
        return True
    if name == "env":
        return not strip_prefixes(skip_options(args, {"-u", "--unset", "-C", "--chdir", "-P", "-S"}))
    if name == "set":
        return not args
    if name == "export":
        return not args or "-p" in args
    if name in DECLARES:
        options = [a for a in args if a.startswith(("-", "+"))]
        return len(options) == len(args) or any(a.startswith("-") and "p" in a for a in options)
    return False


def names_credential(word: str) -> bool:
    """A grep pattern that would pick the credential out of an environment dump."""
    pattern = word.upper()
    return "BWS" in pattern or (len(pattern) >= 4 and any(pattern in c for c in CREDENTIALS))


def prints_credential(words: list[str], cmd: Command) -> bool:
    name, args = program(words[0]), words[1:]
    if name in PRINTERS:
        return any(REFERENCE.search(a) for a in args)
    if name in STDIN_PRINTERS:
        return any(REFERENCE.search(body) for body in cmd.stdin)
    if name == "printenv" or name in DECLARES:
        return any(a in CREDENTIALS for a in args)
    if name in FILTERS:
        feeder = cmd.piped_from
        words = strip_prefixes(feeder.words) if feeder else []
        return bool(words) and dumps_env(words) and any(names_credential(a) for a in args if a[:1] != "-")
    return False


def reads_keychain(words: list[str]) -> bool:
    name, args = program(words[0]), words[1:]
    if name == "secret-tool":
        return skip_options(args, set())[:1] in (["lookup"], ["search"])
    if name != "security":
        return False
    rest = skip_options(args, {"-p"})
    if not rest or rest[0] not in ("find-generic-password", "find-internet-password", "dump-keychain"):
        return False
    letters = "d" if rest[0] == "dump-keychain" else "wg"
    i, args = 0, rest[1:]
    while i < len(args):
        arg = args[i]
        if arg in SECURITY_VALUE_OPTIONS and letters != "d":
            i += 2
            continue
        if re.fullmatch(r"-[A-Za-z]+", arg) and set(arg[1:]) & set(letters):
            return True
        i += 1
    return False


def reads_process_env(words: list[str], cmd: Command) -> bool:
    if any(PROC_ENVIRON.match(w) for w in [*words, *cmd.redirects]):
        return True
    name, args = program(words[0]), words[1:]
    if name != "ps":
        return False
    bsd = bool(args) and re.fullmatch(r"[A-Za-z]+", args[0]) is not None and "e" in args[0]
    return bsd or any(re.fullmatch(r"-[A-Za-z]+", a) and "E" in a for a in args)


def fetches_from_store(words: list[str]) -> bool:
    if program(words[0]) != "bws":
        return False
    rest = skip_options(words[1:], BWS_VALUE_OPTIONS)
    if not rest:
        return False
    second = skip_options(rest[1:], BWS_VALUE_OPTIONS)[:1]
    return bool(rest[0] in ("secret", "secrets") and second and second[0] in BWS_FETCH) or (
        rest[0] in BWS_FETCH and second in (["secret"], ["secrets"]))


def leak(words: list[str], cmd: Command, under_run: bool) -> tuple[str, str] | None:
    if under_run and dumps_env(words):
        return "env", shown(words)
    if reads_process_env(words, cmd):
        return "process", shown(words)
    if reads_keychain(words):
        return "keychain", shown(words)
    if prints_credential(words, cmd):
        return "credential", shown(words)
    if fetches_from_store(words):
        return "store", shown(words)
    target = run_target(words)
    if target:
        return walk(shlex.join(target), lambda w, _cwd, c: leak(w, c, under_run=True))
    return None


def check(command: str, _cwd: object) -> str | None:
    found = walk(command, lambda words, _cwd, cmd: leak(words, cmd, under_run=False))
    return f"Blocked by the guardrails plugin: `{found[1]}` {WHAT[found[0]]}. {WHY}\n{INSTEAD}" if found else None


def main() -> int:
    return run_guard(check, 3, "secret leaks")


if __name__ == "__main__":
    sys.exit(main())
