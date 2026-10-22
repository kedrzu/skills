"""A small, forgiving shell lexer shared by the Bash guards of this plugin.

`parse(text)` splits a command line into the simple commands it would run, the way a guard needs
them: each `Command` holds its words with quotes removed, plus what it gets on stdin from a heredoc
or a here-string. Commands inside `$(...)`, backticks and `<(...)` are returned as commands of their
own, next to the command that contains them. Heredoc bodies are never parsed as commands; a guard
that cares (a shell reading its script from stdin) looks at `Command.stdin`.

It is not a full shell grammar: keywords, `case` patterns and expansions stay plain words. Input a
shell would reject (an unterminated quote or substitution) raises `ParseError`, which a guard turns
into "allow, with a warning". The scan is linear, so it never hangs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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


def parse(text: str) -> list[Command]:
    commands, _ = _Parser(text, 0, nested=False).run()
    return commands


class _Parser:
    def __init__(self, text: str, start: int, nested: bool) -> None:
        self.s, self.i, self.nested = text, start, nested
        self.commands: list[Command] = []
        self.current = Command()
        self.word: list[str] | None = None
        self.redirect: str | None = None
        self.heredocs: list[tuple[str, bool, list[str]]] = []

    def run(self) -> tuple[list[Command], int]:
        s, depth = self.s, 0
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
                self.end_command()
                self.i += next(len(op) for op in SEPARATORS if s.startswith(op, self.i))
            elif c == "(":
                self.end_command()
                depth += 1
                self.i += 1
            elif c == ")":
                self.end_command()
                self.i += 1
                if self.nested and depth == 0:
                    return self.commands, self.i
                depth = max(0, depth - 1)
            else:
                self.add(c)
                self.i += 1
        if self.nested:
            raise ParseError("unterminated $(...)")
        self.end_command()
        return self.commands, self.i

    def add(self, text: str) -> None:
        if self.word is None:
            self.word = []
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
            self.heredocs.append((word, op == "<<-", self.current.stdin))
        elif op == "<<<":
            self.current.stdin.append(word)

    def end_command(self) -> None:
        self.end_word()
        self.redirect = None
        if self.current.words or self.current.stdin:
            self.commands.append(self.current)
        self.current = Command()

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
        for delimiter, strip_tabs, stdin in self.heredocs:
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
        commands, end = _Parser(self.s, start, nested=True).run()
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
        self.commands.extend(parse("".join(inner)))
        self.add(s[self.i:i + 1])
        self.i = i + 1

    def parameter(self) -> None:
        s, i, depth = self.s, self.i + 2, 1
        while i < len(s) and depth:
            depth += {"{": 1, "}": -1}.get(s[i], 0)
            i += 1
        if depth:
            raise ParseError("unterminated ${...}")
        self.add(s[self.i:i])
        self.i = i
