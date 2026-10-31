"""Tests for block_submodule_install.py against real throwaway git repos. Nothing here installs anything."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).parent / "block_submodule_install.py"
GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
}


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "protocol.file.allow=always", "-c", "init.defaultBranch=main", *args],
                   cwd=cwd, env=GIT_ENV, check=True, capture_output=True)


def make_repo(path: Path, files: dict[str, str]) -> Path:
    path.mkdir(parents=True)
    for name, text in files.items():
        (path / name).write_text(text)
    git(path, "init")
    git(path, "add", ".")
    git(path, "commit", "-m", "init")
    return path


def run(command, cwd: str | None, raw: str | None = None) -> tuple[int, str, str]:
    payload = raw if raw is not None else json.dumps({"cwd": cwd, "tool_input": {"command": command}})
    proc = subprocess.run([sys.executable, "-I", str(HOOK)], input=payload, capture_output=True, text=True,
                          timeout=15)
    return proc.returncode, proc.stdout, proc.stderr


class SubmoduleInstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(os.path.realpath(tempfile.mkdtemp()))
        lib = make_repo(cls.tmp / "lib-src", {"package.json": "{}"})
        other = make_repo(cls.tmp / "other-src", {"package.json": "{}"})
        cls.root = make_repo(cls.tmp / "super", {"package.json": json.dumps({"workspaces": ["./packages/*", "./lib/packages/*"]})})
        git(cls.root, "submodule", "add", str(lib), "lib")
        git(cls.root, "submodule", "add", str(other), "other")
        git(cls.root, "commit", "-m", "submodules")
        cls.lib = cls.root / "lib"
        (cls.lib / "packages" / "a").mkdir(parents=True)
        cls.other = cls.root / "other"
        cls.plain = make_repo(cls.tmp / "plain", {"package.json": "{}"})

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def assertBlocked(self, command: str, cwd: Path) -> None:
        code, _, err = run(command, str(cwd))
        self.assertEqual(code, 2, command)
        self.assertIn("Blocked by the guardrails plugin", err)
        self.assertIn("`lib`", err)
        self.assertIn(f"cd {self.root} && {command.split()[0] if command.split()[0] in ('bun', 'npm', 'pnpm', 'yarn') else 'bun'} install", err)

    def assertAllowed(self, command: str, cwd: Path) -> None:
        code, out, err = run(command, str(cwd))
        self.assertEqual((code, out), (0, ""), err)

    def test_blocks_inside_the_submodule(self):
        self.assertBlocked("bun install", self.lib)
        self.assertBlocked("bun add zod", self.lib / "packages")
        self.assertBlocked("bun i", self.lib / "packages" / "a")
        self.assertBlocked("FOO=1 timeout 60 bun install", self.lib)

    def test_blocks_other_package_managers(self):
        for command in ["npm install", "npm ci", "bun ci", "pnpm add x", "yarn", "yarn add x"]:
            with self.subTest(command=command):
                self.assertBlocked(command, self.lib)

    def test_blocks_when_the_directory_is_changed_into_the_submodule(self):
        self.assertBlocked("cd lib && bun install", self.root)
        self.assertBlocked(f"cd {self.lib} && bun install", self.plain)
        self.assertBlocked("pushd lib && bun install", self.root)
        self.assertBlocked("cd lib/packages && cd a && bun install", self.root)
        self.assertBlocked("bun --cwd lib install", self.root)
        self.assertBlocked("bun install --cwd lib", self.root)
        self.assertBlocked("npm --prefix lib install", self.root)
        self.assertBlocked("npm install -C lib", self.root)
        self.assertBlocked("env -C lib bun install", self.root)
        self.assertBlocked("bash -c 'cd lib && bun i'", self.root)
        self.assertBlocked("cd lib && bash -c 'bun i'", self.root)
        self.assertBlocked("echo hi; cd lib; bun install", self.root)

    def test_blocks_an_install_a_nested_command_runs(self):
        self.assertBlocked('cd lib && echo "bun install" | bash', self.root)
        self.assertBlocked('cd lib && env -S "bun install"', self.root)
        self.assertBlocked('cd lib && bunx -c "bun install"', self.root)

    def test_blocks_a_directory_that_does_not_exist_yet(self):
        self.assertBlocked("cd lib/packages/new && bun install", self.root)

    def test_allows_the_superproject_and_directories_leaving_the_submodule(self):
        self.assertAllowed("bun install", self.root)
        self.assertAllowed("cd lib && cd .. && bun install", self.root)
        self.assertAllowed("cd lib && bun --cwd .. install", self.root)
        self.assertAllowed("bun install", self.root / "packages")
        self.assertAllowed("bun --cwd .. install", self.lib)

    def test_a_cd_in_a_subshell_or_substitution_ends_with_it(self):
        self.assertAllowed("(cd lib && bun run lint); bun install", self.root)
        self.assertAllowed("X=$(cd lib && pwd); bun install", self.root)
        self.assertAllowed("echo $(cd lib) ; bun install", self.root)
        self.assertAllowed("echo `cd lib`; (X=$(cd lib); cd ..); bun install", self.root)
        self.assertBlocked("(cd lib && bun install)", self.root)
        self.assertBlocked("cd lib && (cd packages; X=$(cd ..)) && bun install", self.root)

    def test_allows_a_submodule_that_is_not_a_workspace(self):
        self.assertAllowed("bun install", self.other)
        self.assertAllowed("cd other && npm install", self.root)

    def test_allows_a_plain_repo(self):
        self.assertAllowed("bun install", self.plain)
        self.assertAllowed("bun install", self.tmp)

    def test_allows_commands_that_do_not_install(self):
        for command in ["bun run build", "bun test", "bun upgrade", "bunx foo", "bun x foo", "git status", "bun",
                        "npm run build", "npm test", "pnpm run x", "yarn workspace a run b", "echo bun install",
                        "grep 'bun install' f"]:
            with self.subTest(command=command):
                self.assertAllowed(command, self.lib)

    def test_unknown_directories_are_allowed(self):
        for command in ["cd - && bun install", "cd $X && bun install", "cd `pwd` && bun install",
                        "popd; bun install", "bun --cwd $D install"]:
            with self.subTest(command=command):
                self.assertAllowed(command, self.lib)

    def test_without_a_package_json_the_submodule_is_allowed(self):
        root = make_repo(self.tmp / "bare", {"README": "x"})
        git(root, "submodule", "add", str(self.tmp / "lib-src"), "lib")
        self.assertAllowed("bun install", root / "lib")

    def test_object_form_and_negated_workspaces(self):
        root = make_repo(self.tmp / "obj", {"package.json": json.dumps({"workspaces": {"packages": ["lib/*", "!lib/x"]}})})
        git(root, "submodule", "add", str(self.tmp / "lib-src"), "lib")
        code, _, _ = run("bun install", str(root / "lib"))
        self.assertEqual(code, 2)

    def test_unparseable_command_fails_open_with_a_warning(self):
        code, out, _ = run("bun install 'unterminated", str(self.lib))
        self.assertEqual(code, 0)
        self.assertIn("could not check", json.loads(out)["systemMessage"])

    def test_odd_payloads_are_allowed_silently(self):
        for raw in ["", "not json", "[]", "null", '{"tool_input": null}', '{"tool_input": {"command": 5}}']:
            with self.subTest(raw=raw):
                self.assertEqual(run(None, None, raw=raw)[:2], (0, ""))

    def test_falls_back_to_the_process_cwd_without_a_cwd_field(self):
        proc = subprocess.run([sys.executable, "-I", str(HOOK)], input=json.dumps({"tool_input": {"command": "bun install"}}),
                              capture_output=True, text=True, cwd=self.lib, timeout=15)
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
