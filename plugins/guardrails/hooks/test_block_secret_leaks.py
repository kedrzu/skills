"""Tests for block_secret_leaks.py: commands in, block or allow out. Nothing here runs a command."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

HOOK = Path(__file__).parent / "block_secret_leaks.py"


def run(command, raw: str | None = None) -> tuple[int, str, str]:
    payload = raw if raw is not None else json.dumps({"tool_input": {"command": command}})
    proc = subprocess.run([sys.executable, "-I", str(HOOK)], input=payload, capture_output=True, text=True,
                          timeout=10)
    return proc.returncode, proc.stdout, proc.stderr


class BlockedTests(unittest.TestCase):
    def assertBlocked(self, commands: list[str], says: str) -> None:
        for command in commands:
            with self.subTest(command=command):
                code, _, err = run(command)
                self.assertEqual(code, 2, command)
                self.assertIn("Blocked by the guardrails plugin", err)
                self.assertIn(says, err)

    def test_environment_dumps_under_secrets_run(self):
        self.assertBlocked([
            "bun nzyme secrets run -- env", "nzyme secrets run -- printenv", "bunx nzyme secrets run -- env",
            "bun x nzyme secrets run -- env", "npx nzyme secrets run -- printenv STRIPE_KEY",
            "bun app secrets run -- env", "app secrets run -- set", "bun ./cli.ts secrets run -- export -p",
            "nzyme secrets run -- export", "nzyme secrets run -- declare -p", "nzyme secrets run -- declare -x",
            "nzyme secrets run -- typeset -px", "nzyme secrets run -- env -0", "nzyme secrets run -- env -u X",
            "nzyme secrets run -- env | grep STRIPE", "nzyme secrets run -- bash -c 'env'",
            "nzyme secrets run -- sh -c 'cd x && printenv'", "nzyme secrets run -- timeout 5 env",
            "cd app && bun nzyme secrets run -- env | sort", "timeout 30 bun nzyme secrets run -- printenv",
            "bash -c 'nzyme secrets run -- env'", "nzyme secrets run env", "bws run -- env",
            "nzyme secrets run API_KEY -- env", "bun healed secrets run PIA_USER PIA_PASSWORD -- printenv",
            "bws run --project-id 1f0c -- printenv", "nzyme secrets run -- nzyme secrets run -- env",
        ], "filled with secrets")

    def test_other_processes_environment(self):
        self.assertBlocked([
            "cat /proc/1234/environ", "cat /proc/self/environ", "cat /proc/*/environ",
            "tr '\\0' '\\n' < /proc/1234/environ", "strings /proc/$(pgrep bun)/environ",
            "xxd /proc/42/task/43/environ", "nzyme secrets run -- cat /proc/self/environ", "ps eww 1234",
            "ps auxe", "ps -E -p 1234", "ps -wwE", "ps axeww | grep bun",
        ], "another process's environment")

    def test_keychain_reads(self):
        self.assertBlocked([
            "security find-generic-password -s nzyme-secrets -w",
            "security find-generic-password -s nzyme-secrets -a bw -w",
            "security find-generic-password -ws nzyme-secrets", "security find-generic-password -g -s x",
            "security find-internet-password -s github.com -w", "security -q find-generic-password -l x -w",
            "/usr/bin/security find-generic-password -s x -w", "security dump-keychain -d",
            "security dump-keychain -d login.keychain", "TOKEN=$(security find-generic-password -s x -w) app",
            "secret-tool lookup service nzyme-secrets", "secret-tool search --all service nzyme-secrets",
            "sh -c 'security find-generic-password -s x -w | pbcopy'",
        ], "OS keychain")

    def test_printing_the_store_credential(self):
        self.assertBlocked([
            "echo $BWS_ACCESS_TOKEN", 'echo "$BWS_ACCESS_TOKEN"', 'echo "${BWS_ACCESS_TOKEN}"',
            "echo ${BWS_ACCESS_TOKEN:0:8}", "printf '%s\\n' \"$BWS_ACCESS_TOKEN\"", "print -r $BWS_ACCESS_TOKEN",
            'cat <<< "$BWS_ACCESS_TOKEN"', "cat <<EOF\ntoken: $BWS_ACCESS_TOKEN\nEOF",
            "printenv BWS_ACCESS_TOKEN", "declare -p BWS_ACCESS_TOKEN", "env | grep BWS", "env | grep -i bws",
            "printenv | grep TOKEN", "set | grep ACCESS", "export -p | rg BWS_ACCESS", "bash -c 'echo $BWS_ACCESS_TOKEN'",
            "echo \"token=$BWS_ACCESS_TOKEN\" && bws project list",
        ], "BWS_ACCESS_TOKEN")

    def test_fetching_from_bitwarden(self):
        self.assertBlocked([
            "bws secret get 1f0c", "bws secret list", "bws secret list 1f0c -o env", "bws -o json secret get 1f0c",
            "bws --access-token $T secret list", "bws secret create KEY value 1f0c", "bws secret edit 1f0c",
            "bws get secret 1f0c", "bws list secrets", "bunx bws secret list",
        ], "Bitwarden")

    def test_message_says_why_and_what_instead(self):
        _, _, err = run("bun nzyme secrets run -- env")
        self.assertIn("`env`", err)
        self.assertIn("transcript", err)
        self.assertIn("rotated", err)
        self.assertIn("secrets list", err)
        self.assertIn("secrets run <KEY>... -- <the real command>", err)
        self.assertIn('secrets set NAME --prompt="<hint>"', err)


class AllowedTests(unittest.TestCase):
    def assertAllowed(self, commands: list[str]) -> None:
        for command in commands:
            with self.subTest(command=command):
                code, out, err = run(command)
                self.assertEqual(code, 0, f"{command}: {err}")
                self.assertEqual(out, "", f"{command}: {out}")

    def test_the_secrets_commands(self):
        self.assertAllowed([
            "bun nzyme secrets list", "nzyme secrets list", "bunx nzyme secrets list", "app secrets list",
            'bun nzyme secrets set STRIPE_KEY --prompt="Stripe test key: dashboard → Developers → API keys"',
            "nzyme secrets login", "nzyme secrets login bw --write", "nzyme secrets import --file .env",
            "nzyme secrets refresh", "nzyme secrets set DB_PASSWORD < password.txt",
        ])

    def test_secrets_run_with_a_real_command(self):
        self.assertAllowed([
            "bun nzyme secrets run -- bun run dev", "nzyme secrets run -- bun test", "app secrets run -- bun x.ts",
            "nzyme secrets run API_KEY DB_PASSWORD -- bun run dev",
            "nzyme secrets run -- env FOO=1 bun run dev", "nzyme secrets run -- env -u DEBUG bun run dev",
            "nzyme secrets run -- set -e", "nzyme secrets run -- bash -c 'bun run migrate && bun run dev'",
            "nzyme secrets run -- curl -H \"Authorization: Bearer $STRIPE_KEY\" https://api.stripe.com/v1/x",
            "bws run -- bun run dev", "nzyme secrets run -- export FOO=1",
        ])

    def test_environment_outside_secrets_run(self):
        self.assertAllowed([
            "env", "printenv PATH", "env | grep NODE", "env FOO=1 bun run dev", "export -p", "set -euo pipefail",
            "declare -p PATH", "FOO=1 bun x.ts",
        ])

    def test_keychain_without_reading_a_password(self):
        self.assertAllowed([
            "security find-generic-password -s nzyme-secrets", "security list-keychains",
            "security find-certificate -a -p", "security delete-generic-password -s x", "secret-tool clear a b",
            "security find-generic-password -l x -s y",
        ])

    def test_the_credential_used_not_printed(self):
        self.assertAllowed([
            "bws project list", "bws secret delete 1f0c", 'bws --access-token "$BWS_ACCESS_TOKEN" project list',
            'test -n "$BWS_ACCESS_TOKEN" && echo set', 'echo ${#BWS_ACCESS_TOKEN}', "printenv HOME",
            "env | grep PATH", "unset BWS_ACCESS_TOKEN",
        ])

    def test_processes_and_mentions(self):
        self.assertAllowed([
            "ps aux", "ps -ef", "ps -p 1234 -o pid,etime,command", "ls /proc/1234", "cat /proc/1234/status",
            "echo 'never run env under secrets run'", "git commit -m 'Block nzyme secrets run -- env'",
            "grep -rn 'find-generic-password -w' docs", "cat > notes.md <<'EOF'\nsecrets run -- env\nEOF",
            "rg BWS_ACCESS_TOKEN packages",
        ])


class RobustnessTests(unittest.TestCase):
    def test_unparseable_commands_fail_open_with_a_warning(self):
        code, out, _ = run("nzyme secrets run -- env 'open")
        self.assertEqual(code, 0)
        self.assertIn("could not check", json.loads(out)["systemMessage"])

    def test_odd_payloads_are_allowed_silently(self):
        for raw in ["", "not json", "[]", "null", '{"tool_input": null}', '{"tool_input": {"command": 5}}']:
            with self.subTest(raw=raw):
                self.assertEqual(run(None, raw=raw)[:2], (0, ""))

    def test_odd_but_valid_shapes(self):
        for command in ["", ";;", "secrets", "secrets run", "nzyme secrets run --", "bws", "bws run", "security",
                        "ps", "x secrets run -- ''"]:
            with self.subTest(command=command):
                self.assertEqual(run(command)[0], 0)


if __name__ == "__main__":
    unittest.main()
