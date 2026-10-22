"""Tests for block_inline_eval.py: commands in, block or allow out. Nothing here runs node or bun."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import unittest
from pathlib import Path

HOOK = Path(__file__).parent / "block_inline_eval.py"


def run(command, raw: str | None = None) -> tuple[int, str, str]:
    payload = raw if raw is not None else json.dumps({"tool_input": {"command": command}})
    proc = subprocess.run([sys.executable, "-I", str(HOOK)], input=payload, capture_output=True, text=True,
                          timeout=10)
    return proc.returncode, proc.stdout, proc.stderr


class BlockedTests(unittest.TestCase):
    def assertBlocked(self, commands: list[str]) -> None:
        for command in commands:
            with self.subTest(command=command):
                code, _, err = run(command)
                self.assertEqual(code, 2, command)
                self.assertIn("Blocked by the guardrails plugin", err)

    def test_flags(self):
        self.assertBlocked([
            'node -e "console.log(1)"', "node --eval 'x'", "node --eval=x", "node -p 1+1", "node --print 1",
            "node --print=1", "node -pe 1", "node -ep 1", "bun -e 'x'", "bun --eval 'x'", "bun --eval=x",
            "bun -p 1", "bun --print 1", "nodejs -e 1", "node --inspect -e 1", "node -r ts-node/register -e 1",
            "node --require ./x.js --eval 1", "node --input-type module -e 1", "bun --smol -e 1",
            "bun --cwd sub -e 1", "bun run -e 1", "bun run --eval 'x'",
        ])

    def test_the_incident(self):
        self.assertBlocked([
            'cd x && timeout 90 bun -e "\nimport { compile } from \'./compiler\'\nawait compile()\n"',
            "cd /repo/packages/fn && timeout 90 bun -e \"const r = require('rollup'); r.rollup({})\"",
        ])

    def test_prefixes_and_wrappers(self):
        self.assertBlocked([
            "FOO=1 node -e 1", "FOO=1 BAR='a b' bun -e 1", "env node -e 1", "env -i PATH=/bin FOO=1 node -e 1",
            "env -u HOME node -e 1", "env -S 'node -e 1'", "timeout 90 bun -e 1", "timeout -k 5 -s KILL 90 node -e 1",
            "timeout --foreground 10s node -e 1", "gtimeout 5 node -e 1", "nice node -e 1", "nice -n 10 node -e 1",
            "nice -10 bun -e 1", "time node -e 1", "time -p bun -e 1", "command node -e 1", "exec node -e 1",
            "exec -a x node -e 1", "caffeinate node -e 1", "caffeinate -i -t 60 bun -e 1", "nohup node -e 1 &",
            "xargs node -e 1", "find . -name '*.js' | xargs -I {} node -e 1 {}", "xargs -0 -n 1 -P 4 bun -e 1",
            "sudo node -e 1", "sudo -u www -E FOO=1 node -e 1", "stdbuf -o L node -e 1",
            "timeout 90 nice -n 5 env FOO=1 bun -e 1", "! node -e 1", "if node -e 1; then echo; fi",
            "while true; do bun -e 1; done", "f() { node -e 1; }",
        ])

    def test_paths(self):
        self.assertBlocked([
            "/Users/x/.bun/bin/bun -e 1", "~/.nvm/versions/node/v22.1.0/bin/node -e 1", "/usr/local/bin/nodejs -p 1",
            "./node_modules/.bin/node -e 1", "'/opt/my tools/node' -e 1",
        ])

    def test_package_runners(self):
        self.assertBlocked([
            "npx node -e 1", "npx -y node@20 -e 1", "npx --package=foo node -e 1", "bunx node -e 1",
            "bunx bun -e 1", "bun x node -e 1", "npm exec -- node -e 1", "pnpm exec node -e 1",
            "yarn exec node -e 1", "npx -c 'node -e 1'",
        ])

    def test_chains_and_substitutions(self):
        self.assertBlocked([
            "echo a; node -e 1", "true && bun -e 1", "false || node -e 1", "cat x | node -e 1",
            "node -e 1 | cat", "(cd x && node -e 1)", "( node -e 1 )", "echo $(node -e 1)",
            'echo "$(node -p 1)"', "echo `node -p 1`", "x=$(bun -e 1)", "diff <(node -e 1) b",
            "echo a\nnode -e 1", "echo a &\nbun -e 1", "make build 2>&1 && node -e 1 > out.txt",
            "echo $(echo $(node -e 1))",
        ])

    def test_nested_shells(self):
        self.assertBlocked([
            "bash -c 'node -e 1'", "sh -c \"cd x && bun -e 'x'\"", "zsh -c 'node -e 1'", "bash -lc 'node -e 1'",
            "bash -euo pipefail -c 'node -e 1'", "/bin/bash -c 'timeout 5 bun -e 1'",
            "bash -c \"sh -c 'node -e 1'\"", "sudo bash -c 'node -e 1'", "eval 'node -e 1'",
            "bash <<'EOF'\nnode -e 1\nEOF", "sh <<< 'bun -e 1'", "xargs sh -c 'node -e 1'",
        ])

    def test_message_names_the_command_and_the_fix(self):
        _, _, err = run("cd x && timeout 90 bun -e 'console.log(1)'")
        self.assertIn("bun -e 'console.log(1)'", err)
        self.assertIn("execArgv", err)
        self.assertIn("$TMPDIR", err)


class AllowedTests(unittest.TestCase):
    def assertAllowed(self, commands: list[str]) -> None:
        for command in commands:
            with self.subTest(command=command):
                code, out, err = run(command)
                self.assertEqual(code, 0, f"{command}: {err}")
                self.assertEqual(out, "", f"{command}: {out}")

    def test_other_programs(self):
        self.assertAllowed([
            "grep -e foo -e bar file", "sed -e 's/a/b/' f", "perl -e 'print 1'", "python -c 'print(1)'",
            "python3 -c \"import subprocess\"", "ruby -e 'p 1'", "awk -e '{print}' f", "xargs -e foo echo",
            "git grep -e node", "nodemon -e js,ts", "node-gyp rebuild", "bun-run -e 1", "deno run x.ts",
        ])

    def test_eval_flag_after_the_script(self):
        self.assertAllowed([
            "node script.js -e", "node script.js --eval x", "bun script.ts -e", "node --inspect app.js -p 3000",
            "node -- script.js -e 1", "node - -e < x.js", "bun run dev -e", "bun ./x.ts -p 1",
        ])

    def test_bun_subcommands(self):
        self.assertAllowed([
            "bun run build", "bun test", "bun test -t name", "bun install", "bun add -d typescript",
            "bun build ./x.ts -e react --outdir dist", "bun x tsc -p tsconfig.json", "bunx tsc -p .",
            "bun --install=force src/main.ts serve", "bun run --filter pkg dev", "bun -F pkg dev",
            "npx prettier -c .", "npm exec -- tsc -p .", "npm run build -- -e", "pnpm test -e",
        ])

    def test_plain_node_and_bun(self):
        self.assertAllowed([
            "node", "node --version", "node -v", "bun --version", "node x.mjs", "bun x.ts",
            "node --check x.js", "bun \"$TMPDIR/snippet.ts\"", "node <<'EOF'\nconsole.log(1)\nEOF",
            "command -v node", "command -v bun && bun x.ts", "which node", "type node",
        ])

    def test_mentions(self):
        self.assertAllowed([
            "echo 'node -e 1'", 'echo "run bun -e to evaluate"', "printf '%s' 'node -p 1'",
            "git commit -m 'Block node -e in the guard'",
            "git commit -F - <<'EOF'\nBlock `node -e` and bun -e\n\nIt's a fork bomb (see $(node -e 1))\nEOF",
            'git commit -m "$(cat <<\'EOF\'\nBlock node -e; it\'s dangerous (really)\nEOF\n)"',
            "cat > notes.md <<'EOF'\nnode -e 1\nbun -e 2\nEOF",
            "cat > x.sh <<-EOF\n\tnode -e 1\n\tEOF\nchmod +x x.sh",
            "grep -rn 'node -e' .", "rg \"bun -e\" src", "echo hi # node -e 1", "# node -e 1",
            "bash script.sh -c 'node -e 1'", "bash x.sh <<'EOF'\nnode -e 1\nEOF", "gh pr create --body 'no node -e'",
            "echo node -e 1", "echo ${X:-node -e 1}",
        ])


class RobustnessTests(unittest.TestCase):
    def assertFailsOpen(self, command: str) -> None:
        code, out, err = run(command)
        self.assertEqual(code, 0, err)
        self.assertIn("could not check", json.loads(out)["systemMessage"])

    def test_unparseable_commands_fail_open_with_a_warning(self):
        for command in ['node -e "unterminated', "echo 'open", "echo $(node -e 1", "echo `node -e 1", "echo ${x"]:
            with self.subTest(command=command):
                self.assertFailsOpen(command)

    def test_odd_payloads_are_allowed_silently(self):
        for raw in ["", "not json", "[]", "null", '{"tool_input": null}', '{"tool_input": {"command": 5}}',
                    '{"tool_input": {}}']:
            with self.subTest(raw=raw):
                self.assertEqual(run(None, raw=raw)[:2], (0, ""))

    def test_huge_and_deep_input_never_hangs(self):
        start = time.monotonic()
        self.assertEqual(run("echo " + "a " * 200_000)[0], 0)
        self.assertEqual(run("echo " + "$(" * 5000 + ")" * 5000)[0], 0)
        self.assertEqual(run("bash -c " + "'bash -c " * 50 + "node -e 1" + "'" * 50)[0], 0)
        self.assertLess(time.monotonic() - start, 8)

    def test_odd_but_valid_shapes(self):
        for command in ["", "   ", ";;", "&&", ")", "((i++))", "case x in a) node x.js;; esac", "x=", "=", "-e",
                        "[[ -e file ]] && node x.js", "test -e f", "a=$'node -e 1'", "echo \\\nnode x.js"]:
            with self.subTest(command=command):
                self.assertEqual(run(command)[0], 0)


if __name__ == "__main__":
    unittest.main()
