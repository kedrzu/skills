#!/usr/bin/env python3
"""Collect a secret from the user and hand it to programs - without the agent ever seeing it.

The agent runs this through its own shell. The value is read INSIDE this process (a native
masked dialog, or a no-echo terminal read) and leaves it only as a verdict line: which file was
written and how many characters arrived. It is never printed, never passed on a command line,
and never exported to the agent's shell, so it appears in no transcript and in no `ps` output.

The agent must not call `osascript ... with hidden answer` (or zenity, or Get-Credential) itself:
those return the typed value on stdout, which is exactly the leak this script exists to prevent.

    secret.py set KEY [--file PATH] [--hint TEXT]   ask the user, write KEY=value
    secret.py has KEY [--file PATH]                 is it set, and where - never the value
    secret.py run KEY[,KEY...] [--file PATH] -- cmd args...
                                                    run cmd with the keys in its environment

Storage is a KEY=value file, mode 0600 in a 0700 directory. Default:
${CLAUDE_CONFIG_DIR:-~/.claude}/secrets/.env. A consumer whose own code reads a specific file
passes it with --file. On Windows chmod is a no-op; the user-profile ACL protects the file.

Exit: 0 ok · 1 write failed / key missing · 2 bad arguments
      3 no way to prompt from here - the printed command has to be run by a human
      4 nothing was entered (cancelled or timed out)

Python 3 stdlib only. The macOS path is tested; the Windows and Linux prompts are not.
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROMPT_TIMEOUT = 300
KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

APPLESCRIPT = """
on run argv
    try
        set answer to display dialog (item 2 of argv) with title (item 1 of argv) default answer "" with hidden answer with icon note giving up after 300
    on error number -128
        return ""
    end try
    if gave up of answer then return ""
    return text returned of answer
end run
"""

# Windows PowerShell 5.1 shows Get-Credential as a GUI dialog; pwsh 7 asks in the console,
# which a non-interactive shell cannot answer, so only powershell.exe is tried.
POWERSHELL = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
try {
    $c = Get-Credential -UserName $env:SECRET_PROMPT_KEY -Message $env:SECRET_PROMPT_HINT
} catch { exit 5 }
if ($null -eq $c) { exit 4 }
[Console]::Out.Write($c.GetNetworkCredential().Password)
"""


def default_file() -> Path:
    config = os.environ.get("CLAUDE_CONFIG_DIR", "").strip() or str(Path.home() / ".claude")
    return Path(config).expanduser() / "secrets" / ".env"


def result_file(key: str) -> Path:
    return Path(tempfile.gettempdir()) / f"secret-{key}.result"


def verdict(key: str, line: str) -> None:
    """Same line on stdout and in the result file - the file is what the agent reads when the
    prompt had to happen in a terminal it cannot see."""
    print(line)
    try:
        result_file(key).write_text(line + "\n", encoding="utf-8")
    except OSError:
        pass


def read_env_file(path: Path) -> dict[str, str]:
    """Parse a simple KEY=value file. Data, not shell - nothing is executed."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


# --------------------------------------------------------------------------
# Asking the user. Each prompt returns the value, "" when the user cancelled,
# or None when it cannot run here and the next one should be tried.

def prompt_macos(key: str, hint: str) -> str | None:
    if sys.platform != "darwin" or not shutil.which("osascript"):
        return None
    message = f"{key}\n\n{hint}\n\nNothing you type here is visible to the agent.".strip()
    try:
        proc = subprocess.run(["osascript", "-", f"{key} - Claude Code", message],
                              input=APPLESCRIPT, capture_output=True, text=True,
                              timeout=PROMPT_TIMEOUT + 30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    # A non-zero exit that is not a cancel means no GUI session (ssh, a locked-down daemon).
    return proc.stdout.rstrip("\n") if proc.returncode == 0 else None


def prompt_windows(key: str, hint: str) -> str | None:
    if os.name != "nt" or not shutil.which("powershell.exe"):
        return None
    env = {**os.environ, "SECRET_PROMPT_KEY": key,
           "SECRET_PROMPT_HINT": f"{hint}\nNothing you type here is visible to the agent.".strip()}
    try:
        proc = subprocess.run(["powershell.exe", "-NoProfile", "-Command", POWERSHELL],
                              env=env, capture_output=True, text=True, encoding="utf-8",
                              timeout=PROMPT_TIMEOUT + 30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode == 4:
        return ""
    return proc.stdout if proc.returncode == 0 else None


def prompt_linux(key: str, hint: str) -> str | None:
    if not sys.platform.startswith("linux"):
        return None
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return None
    text = f"{key}: {hint}".strip(": ")
    if shutil.which("zenity"):
        cmd = ["zenity", "--password", "--title", f"{key} - Claude Code",
               "--timeout", str(PROMPT_TIMEOUT)]
    elif shutil.which("kdialog"):
        cmd = ["kdialog", "--title", f"{key} - Claude Code", "--password", text]
    else:
        return None
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=PROMPT_TIMEOUT + 30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    # 1 is a cancel for both, 5 a zenity timeout; anything else means the dialog could not open.
    if proc.returncode in (1, 5):
        return ""
    return proc.stdout.rstrip("\n") if proc.returncode == 0 else None


def prompt_tty(key: str, hint: str) -> str | None:
    if not sys.stdin.isatty():
        return None
    print(f"{key}\n{hint}".strip(), file=sys.stderr)
    try:
        return getpass.getpass("Paste the value (it will not be shown): ")
    except (EOFError, KeyboardInterrupt):
        return ""


def ask(key: str, hint: str) -> str | None:
    for prompt in (prompt_macos, prompt_windows, prompt_linux, prompt_tty):
        value = prompt(key, hint)
        if value is not None:
            return value
    return None


# --------------------------------------------------------------------------
# Writing

def upsert(path: Path, key: str, value: str) -> None:
    """Replace KEY's line, keep every other line, create the file 0600 - atomically."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    out: list[str] = []
    found = False
    for line in lines:
        bare = line.strip()
        if bare.startswith("export "):
            bare = bare[len("export "):].lstrip()
        if bare.split("=", 1)[0].strip() == key and "=" in bare:
            if not found:
                out.append(f"{key}={value}")
                found = True
            continue
        out.append(line)
    if not found:
        out.append(f"{key}={value}")

    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(out) + "\n")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    path.chmod(0o600)


def manual_command(key: str, path: Path, hint: str) -> str:
    argv = [sys.executable or "python3", str(Path(__file__).resolve()), "set", key,
            "--file", str(path)]
    if hint:
        argv += ["--hint", hint]
    return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)


# --------------------------------------------------------------------------
# Commands

def cmd_set(args: argparse.Namespace) -> int:
    key, path, hint = args.key, args.file, args.hint or ""
    try:
        result_file(key).unlink()
    except OSError:
        pass

    value = ask(key, hint)
    if value is None:
        print(f"""No way to prompt from here: no desktop dialog is available and this shell has no
terminal. Ask the user to run this in their own terminal and say when it is done:

    {manual_command(key, path, hint)}

The verdict will then be in {result_file(key)}""", file=sys.stderr)
        return 3

    # Surrounding whitespace survives a copy-paste and silently breaks most tokens.
    value = value.strip()
    if not value or value == "...":
        verdict(key, f"EMPTY {key}  nothing was entered (cancelled, or the dialog timed out)"
                     " - nothing written")
        return 4
    if "\n" in value or "\r" in value:
        verdict(key, f"FAILED {key}  the value spans several lines - nothing written"
                     f" ({len(value)} characters were entered)")
        return 1

    try:
        upsert(path, key, value)
    except OSError as exc:
        verdict(key, f"FAILED {key}  could not write {path}: {exc.strerror or exc}")
        return 1
    verdict(key, f"OK {key}  wrote {path}  ({len(value)} characters)")
    return 0


def cmd_has(args: argparse.Namespace) -> int:
    if os.environ.get(args.key, "").strip():
        print(f"{args.key} set (environment)")
        return 0
    if read_env_file(args.file).get(args.key, "").strip():
        print(f"{args.key} set ({args.file})")
        return 0
    print(f"{args.key} missing (not in the environment, not in {args.file})")
    return 1


def cmd_run(args: argparse.Namespace) -> int:
    command = args.command
    if not command:
        print("run: nothing to run - put the command after --", file=sys.stderr)
        return 2
    stored = read_env_file(args.file)
    env = dict(os.environ)
    missing = []
    for key in filter(None, (k.strip() for k in args.keys.split(","))):
        # The real environment wins over the file, as everywhere else.
        value = env.get(key, "").strip() or stored.get(key, "").strip()
        if value:
            env[key] = value
        else:
            missing.append(key)
    if missing:
        print(f"run: not set: {', '.join(missing)} - collect with `secret.py set` first",
              file=sys.stderr)
        return 1
    try:
        return subprocess.run(command, env=env).returncode
    except OSError as exc:
        print(f"run: {command[0]}: {exc.strerror or exc}", file=sys.stderr)
        return 2


def key_arg(text: str) -> str:
    if not KEY_RE.match(text):
        raise argparse.ArgumentTypeError(f"not a valid variable name: {text!r}")
    return text


def file_arg(text: str) -> Path:
    return Path(text).expanduser()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect and use secrets without exposing them.")
    sub = parser.add_subparsers(dest="command_name", required=True)

    p_set = sub.add_parser("set", help="ask the user for KEY in a masked prompt and store it")
    p_set.add_argument("key", type=key_arg)
    p_set.add_argument("--file", type=file_arg, default=default_file())
    p_set.add_argument("--hint", help="where the value comes from - shown in the prompt")
    p_set.set_defaults(func=cmd_set)

    p_has = sub.add_parser("has", help="is KEY set - never prints the value")
    p_has.add_argument("key", type=key_arg)
    p_has.add_argument("--file", type=file_arg, default=default_file())
    p_has.set_defaults(func=cmd_has)

    p_run = sub.add_parser("run", help="run a command with KEY[,KEY...] in its environment")
    p_run.add_argument("keys")
    p_run.add_argument("--file", type=file_arg, default=default_file())
    p_run.set_defaults(func=cmd_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Everything after the first `--` is the command for `run`, untouched by argparse.
    command: list[str] = []
    if "--" in argv:
        split = argv.index("--")
        argv, command = argv[:split], argv[split + 1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    if command and args.command_name != "run":
        parser.error("only `run` takes a command after --")
    args.command = command
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
