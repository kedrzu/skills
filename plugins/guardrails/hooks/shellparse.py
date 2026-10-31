"""A small, forgiving shell lexer and command walker shared by the Bash guards of this plugin.

`parse(text)` splits a command line into the simple commands it would run, the way a guard needs
them: each `Command` holds its words with quotes removed, plus what it gets on stdin from a heredoc
or a here-string. Commands inside `$(...)`, backticks and `<(...)` are returned as commands of their
own, next to the command that contains them. A heredoc body is plain text, except that under an
unquoted delimiter (`<<EOF`, not `<<'EOF'`) bash runs its `$(...)` and backticks, so they are
returned too; a guard that cares (a shell reading its script from stdin) looks at `Command.stdin`,
and at `Command.piped_from`: the command on the left of the `|` or `|&` that feeds it.
`Command.scope` names the subshells (`( … )`) and substitutions the command runs in, outermost
first, so a guard can drop what a `cd` in one of them did once it closes.

It is not a full shell grammar: keywords, `case` patterns and expansions stay plain words. Input a
shell would reject (an unterminated quote or substitution) raises `ParseError`, which a guard turns
into "allow, with a warning". The scan is linear, so it never hangs.

`walk(text, visit, cwd)` is how a guard uses it: it calls `visit` on every command the line would
run, down through wrappers, package runners and nested shells, with the directory it runs in. A
guard is a visitor that answers what to refuse.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from itertools import count
from typing import Callable, TypeVar

SEPARATORS = ("&&", "||", ";;", "|&", ";", "|", "&")
REDIRECTS = ("<<<", "<<-", "<<", "&>>", "&>", ">>", ">&", "<&", "<>", ">|", ">", "<")
DQ_ESCAPES = '$`"\\\n'
ANSI_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", "'": "'", '"': '"', "e": "\x1b", "a": "\a"}


class ParseError(ValueError):
    pass


@dataclass
class Command:
    words: list[str] = field(default_factory=list)
    stdin: list[str] = field(default_factory=list)
    piped_from: Command | None = field(default=None, repr=False, compare=False)
    scope: tuple[int, ...] = field(default=(), compare=False)  # ids of the enclosing subshells/substitutions


def parse(text: str) -> list[Command]:
    commands, _ = _Parser(text, 0, nested=False).run()
    return commands


def _substitutions(text: str, scope: tuple[int, ...], ids: count) -> list[Command]:
    """The commands an unquoted heredoc body runs: its `$(...)` and backticks; the rest is text."""
    parser = _Parser(text, 0, nested=False, scope=scope, ids=ids)
    while parser.i < len(text):
        c, nxt = text[parser.i], text[parser.i + 1:parser.i + 2]
        if c == "\\":
            parser.i += 2
        elif c == "$" and nxt == "(":
            parser.substitution(parser.i + 2)
        elif c == "`":
            parser.backticks()
        else:
            parser.i += 1
    return parser.commands


class _Parser:
    def __init__(self, text: str, start: int, nested: bool, scope: tuple[int, ...] = (),
                 ids: count | None = None) -> None:
        self.s, self.i, self.nested = text, start, nested
        self.base, self.scope, self.ids = scope, scope, ids if ids is not None else count(1)
        self.commands: list[Command] = []
        self.current = Command()
        self.word: list[str] | None = None
        self.word_start = start
        self.redirect: str | None = None
        self.heredocs: list[tuple[str, bool, bool, list[str]]] = []

    def run(self) -> tuple[list[Command], int]:
        s = self.s
        while self.i < len(s):
            c, nxt = s[self.i], s[self.i + 1:self.i + 2]
            if c in " \t\r":
                self.end_word()
                self.i += 1
            elif c == "\n":
                self.end_command()
                self.i += 1
                self.read_heredocs()
            elif c == "#" and self.word is None:
                newline = s.find("\n", self.i)
                self.i = len(s) if newline < 0 else newline
            elif c == "\\":
                if nxt != "\n":
                    self.add(nxt or "\\")
                self.i += 2
            elif c == "'":
                end = s.find("'", self.i + 1)
                if end < 0:
                    raise ParseError("unterminated single quote")
                self.add(s[self.i + 1:end])
                self.i = end + 1
            elif c == "$" and nxt == "'":
                self.ansi_c_quote()
            elif c == '"':
                self.double_quote()
            elif c == "$" and nxt == "(":
                self.substitution(self.i + 2)
            elif c == "$" and nxt == "{":
                self.parameter()
            elif c == "`":
                self.backticks()
            elif c in "<>" and nxt == "(":
                self.substitution(self.i + 2)
            elif c in "<>" or (c == "&" and nxt == ">"):
                self.start_redirect()
            elif c in ";&|":
                op, feeder = next(op for op in SEPARATORS if s.startswith(op, self.i)), self.current
                self.end_command()
                self.current.piped_from = feeder if op in ("|", "|&") else None
                self.i += len(op)
            elif c == "(":
                self.end_command()
                self.scope += (next(self.ids),)
                self.i += 1
            elif c == ")":
                self.end_command()
                self.i += 1
                if self.nested and self.scope == self.base:
                    return self.commands, self.i
                if self.scope != self.base:
                    self.scope = self.scope[:-1]
            else:
                self.add(c)
                self.i += 1
        if self.nested:
            raise ParseError("unterminated $(...)")
        self.end_command()
        return self.commands, self.i

    def add(self, text: str) -> None:
        if self.word is None:
            self.word, self.word_start = [], self.i
        self.word.append(text)

    def end_word(self) -> None:
        if self.word is None:
            return
        word, self.word = "".join(self.word), None
        if self.redirect is None:
            self.current.words.append(word)
            return
        op, self.redirect = self.redirect, None
        if op in ("<<", "<<-"):
            # Any quote in the delimiter (`'EOF'`, `"EOF"`, `\EOF`, `E"O"F`) keeps the body plain text.
            expands = not any(q in self.s[self.word_start:self.i] for q in "'\"\\")
            self.heredocs.append((word, op == "<<-", expands, self.current.stdin))
        elif op == "<<<":
            self.current.stdin.append(word)

    def end_command(self) -> None:
        self.end_word()
        self.redirect = None
        ended, self.current = self.current, Command()
        if ended.words or ended.stdin:
            ended.scope = self.scope
            self.commands.append(ended)
        else:  # `a |` then a newline or `(`: the pipe still feeds the next command
            self.current.piped_from = ended.piped_from

    def start_redirect(self) -> None:
        # `2>&1`: digits right before the operator are a file descriptor, not a word.
        if self.word is not None and "".join(self.word).isdigit():
            self.word = None
        self.end_word()
        op = next(op for op in REDIRECTS if self.s.startswith(op, self.i))
        self.redirect = op
        self.i += len(op)

    def read_heredocs(self) -> None:
        s = self.s
        for delimiter, strip_tabs, expands, stdin in self.heredocs:
            body: list[str] = []
            while self.i < len(s):
                newline = s.find("\n", self.i)
                end = len(s) if newline < 0 else newline
                line = s[self.i:end]
                self.i = end + 1
                if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                    break
                body.append(line)
            stdin.append("\n".join(body))
            if expands:
                self.commands.extend(_substitutions(stdin[-1], self.scope, self.ids))
        self.heredocs = []

    def ansi_c_quote(self) -> None:
        s, i, out = self.s, self.i + 2, []
        while i < len(s) and s[i] != "'":
            if s[i] == "\\" and i + 1 < len(s):
                out.append(ANSI_ESCAPES.get(s[i + 1], s[i + 1]))
                i += 2
            else:
                out.append(s[i])
                i += 1
        if i >= len(s):
            raise ParseError("unterminated $'...'")
        self.add("".join(out))
        self.i = i + 1

    def double_quote(self) -> None:
        s = self.s
        self.add("")
        self.i += 1
        while self.i < len(s):
            c, nxt = s[self.i], s[self.i + 1:self.i + 2]
            if c == '"':
                self.i += 1
                return
            if c == "\\" and nxt and nxt in DQ_ESCAPES:
                if nxt != "\n":
                    self.add(nxt)
                self.i += 2
            elif c == "$" and nxt == "(":
                self.substitution(self.i + 2)
            elif c == "`":
                self.backticks()
            else:
                self.add(c)
                self.i += 1
        raise ParseError("unterminated double quote")

    def substitution(self, start: int) -> None:
        commands, end = _Parser(self.s, start, nested=True, scope=self.inner(), ids=self.ids).run()
        self.commands.extend(commands)
        self.add(self.s[self.i:end])
        self.i = end

    def backticks(self) -> None:
        s, i, inner = self.s, self.i + 1, []
        while i < len(s) and s[i] != "`":
            if s[i] == "\\" and s[i + 1:i + 2] in ("`", "\\", "$"):
                inner.append(s[i + 1])
                i += 2
            else:
                inner.append(s[i])
                i += 1
        if i >= len(s):
            raise ParseError("unterminated backticks")
        self.commands.extend(_Parser("".join(inner), 0, nested=False, scope=self.inner(), ids=self.ids).run()[0])
        self.add(s[self.i:i + 1])
        self.i = i + 1

    def inner(self) -> tuple[int, ...]:
        """The scope of a substitution opened here."""
        return self.scope + (next(self.ids),)

    def parameter(self) -> None:
        s, i, depth = self.s, self.i + 2, 1
        while i < len(s) and depth:
            depth += {"{": 1, "}": -1}.get(s[i], 0)
            i += 1
        if depth:
            raise ParseError("unterminated ${...}")
        self.add(s[self.i:i])
        self.i = i


MAX_DEPTH = 8
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\[[^]]*\])?\+?=")
KEYWORDS = {"!", "{", "}", "if", "then", "else", "elif", "fi", "do", "done", "while", "until", "coproc"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "mksh"}

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
    "npx": ({"-p", "--package", "-w", "--workspace"}, 0),
    "bunx": ({"-p", "--package"}, 0),
}
# Package managers: the subcommands that run a command, and the options that take a separate value
# (`pnpm --filter web exec`). pnpm's `-w` is `--workspace-root` and takes none.
PACKAGE_RUNNERS: dict[str, tuple[set[str], set[str]]] = {
    "npm": ({"exec", "x"}, {"-w", "--workspace", "-C", "--prefix"}),
    "pnpm": ({"exec", "dlx"}, {"-F", "--filter", "--filter-prod", "-C", "--dir"}),
    "yarn": ({"exec", "dlx"}, {"--cwd"}),
}
BUN_VALUE_OPTIONS = {"-r", "--preload", "--require", "--import", "--cwd", "--env-file", "-c", "--config", "-d",
                     "--define", "-l", "--loader", "--tsconfig-override", "--conditions", "--port",
                     "--main-fields", "--extension-order", "--jsx-factory", "--jsx-fragment",
                     "--jsx-import-source", "--jsx-runtime", "--console-depth", "--install", "-F", "--filter",
                     "--unhandled-rejections", "--dns-result-order", "--fetch-preconnect",
                     "--max-http-header-size", "--title"}

T = TypeVar("T")
Visitor = Callable[[list[str], "str | None"], "T | None"]


def walk(command: str, visit: Visitor[T], cwd: str | None = None, depth: int = 0) -> T | None:
    """Call `visit(words, cwd)` on every command `command` runs, and return the first non-None answer.

    `words` is the command with env-var prefixes and keywords stripped, offered at every layer: a
    wrapper (`timeout 90 bun i`), then what it runs (`bun i`). The walk goes on into what a wrapper,
    `npx` / `bunx` / `bun x`, `npm` / `pnpm` / `yarn exec` or `dlx`, `npx -c`, `env -S`, `eval` and a
    nested shell run — its `-c` string, or the script it reads on stdin from a heredoc, a here-string
    or a pipe from `echo`, `printf` or `cat <<EOF`. `cwd` is where the command runs: it follows `cd` /
    `pushd` / `popd` until the subshell or substitution holding them closes, and `env -C`; None once
    it is unknown (`cd $X`, `popd`).
    """
    if depth > MAX_DEPTH:
        return None
    scope: tuple[int, ...] = ()
    opened_in: list[str | None] = []  # the cwd each scope in `scope` opened in
    for cmd in parse(command):
        # A `cd` in a subshell or substitution lasts until it closes, then the cwd it opened in is back.
        shared = 0
        while shared < min(len(scope), len(cmd.scope)) and scope[shared] == cmd.scope[shared]:
            shared += 1
        if shared < len(scope):
            cwd = opened_in[shared]
            del opened_in[shared:]
        opened_in.extend(cwd for _ in cmd.scope[shared:])
        scope = cmd.scope
        found, cwd = _walk_command(cmd, visit, cwd, depth)
        if found is not None:
            return found
    return None


def _walk_command(cmd: Command, visit: Visitor[T], cwd: str | None, depth: int) -> tuple[T | None, str | None]:
    """The first answer of `visit` for `cmd` or a command it runs, and the cwd after `cmd`."""
    words, here = cmd.words, cwd
    while True:
        words = strip_prefixes(words)
        if not words:
            return None, cwd
        found = visit(words, here)
        if found is not None:
            return found, cwd
        name, args = program(words[0]), words[1:]
        if name in ("cd", "pushd", "popd"):
            return None, change_directory(name, args, cwd)
        if name == "command" and args[:1] and re.fullmatch(r"-[pvV]*[vV][pvV]*", args[0]):
            return None, cwd
        if name == "env":
            if any(a in ("-S", "--split-string") or a.startswith("--split-string=") for a in args):
                split = [a.removeprefix("--split-string=") for a in args if a not in ("-S", "--split-string")]
                return walk(" ".join(["env", *split]), visit, here, depth + 1), cwd
            chdir = option_value(args, {"-C", "--chdir"})
            if chdir is not None:
                here = resolve(here, chdir)
        if name in ("npx", "bunx") and any(a in ("-c", "--call") for a in args):
            call = args[args.index("-c" if "-c" in args else "--call") + 1:][:1]
            return (walk(call[0], visit, here, depth + 1) if call else None), cwd
        if name == "bun":
            rest = skip_options(args, BUN_VALUE_OPTIONS)
            if rest[:1] != ["x"]:
                return None, cwd
            words = skip_options(rest[1:], WRAPPERS["bunx"][0])
            continue
        if name in WRAPPERS:
            with_value, positional = WRAPPERS[name]
            words = skip_options(args, with_value)[positional:]
            continue
        if name in PACKAGE_RUNNERS:
            subcommands, with_value = PACKAGE_RUNNERS[name]
            rest = skip_options(args, with_value)
            if not rest or rest[0] not in subcommands:
                return None, cwd
            words = skip_options(rest[1:], with_value | {"-p", "--package"})
            continue
        if name == "eval":
            return walk(" ".join(args), visit, here, depth + 1), cwd
        if name in SHELLS:
            how, text = shell_script(args)
            if how == "c" and text is not None:
                return walk(text, visit, here, depth + 1), cwd
            if how == "stdin":
                for body in [*cmd.stdin, *piped_text(cmd.piped_from)]:
                    found = walk(body, visit, here, depth + 1)
                    if found is not None:
                        return found, cwd
        return None, cwd


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


def option_value(args: list[str], names: set[str]) -> str | None:
    """The value of the last of `names` among `args` (`--prefix x`, `--prefix=x`), None if absent."""
    found = None
    for i, arg in enumerate(args):
        if arg == "--":
            break
        if arg in names and i + 1 < len(args):
            found = args[i + 1]
        elif arg.startswith("--") and "=" in arg and arg.split("=", 1)[0] in names:
            found = arg.split("=", 1)[1]
    return found


def strip_prefixes(words: list[str]) -> list[str]:
    while words and (words[0] in KEYWORDS or ASSIGNMENT.match(words[0])):
        words = words[1:]
    return words


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


def unescape(text: str) -> str:
    return re.sub(r"\\(.)", lambda m: ANSI_ESCAPES.get(m.group(1), m.group(0)), text, flags=re.S)


def piped_text(feeder: Command | None) -> list[str]:
    """What the left side of a pipe writes, when it is `echo`, `printf` or `cat` fed by a heredoc.

    Backslash escapes are decoded (as `printf` and zsh's `echo` do), and `printf` prints its format and
    then each argument on a line of its own instead of filling in `%s`: enough to see a command in it.
    """
    words = strip_prefixes(feeder.words) if feeder else []
    if not words:
        return []
    name, args = program(words[0]), words[1:]
    if name == "cat":
        return feeder.stdin if all(a.startswith("-") for a in args) else []
    if name == "echo":
        while args and re.fullmatch(r"-[neE]+", args[0]):
            args = args[1:]
        return [unescape(" ".join(args))]
    if name == "printf":
        args = skip_options(args, {"-v"})
        return ["\n".join([unescape(args[0]), *args[1:]])] if args else []
    return []


def resolve(base: str | None, arg: str) -> str | None:
    """`arg` as an absolute directory from `base`; None when it depends on an expansion or `base` is unknown."""
    if "$" in arg or "`" in arg:
        return None
    arg = os.path.expanduser(arg)
    if os.path.isabs(arg):
        return os.path.normpath(arg)
    return os.path.normpath(os.path.join(base, arg)) if base is not None else None


def change_directory(name: str, args: list[str], cwd: str | None) -> str | None:
    """The cwd after `cd`, `pushd` or `popd` with `args`; None when it cannot be worked out."""
    if cwd is None or name == "popd":
        return None
    args = skip_options(args, set())
    if not args:
        return None if name == "pushd" else resolve(cwd, "~")
    if args[0] == "-" or args[0].startswith("+"):
        return None
    return resolve(cwd, args[0])
