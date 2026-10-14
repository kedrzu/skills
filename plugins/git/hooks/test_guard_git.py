"""Tests for guard_git.py: commands in, block or allow out."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).parent / "guard_git.py"


def run(command: str, cwd: str | None = None) -> tuple[int, str]:
    proc = subprocess.run([sys.executable, "-I", str(HOOK)], input=json.dumps({"tool_input": {"command": command}, "cwd": cwd}),
                          capture_output=True, text=True)
    return proc.returncode, proc.stderr


def git(cwd: str, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


class StashTests(unittest.TestCase):
    def test_blocked(self):
        for command in ["git stash", "git stash -u", "git stash push", "git stash push -u -- src",
                        "git stash pop", "git stash apply --index", "git stash drop", "git stash clear",
                        "cd sub && git stash pop", "git -C ../other stash pop", "echo x; git stash",
                        "make test\ngit stash pop", "FOO=1 git stash"]:
            code, err = run(command)
            self.assertEqual(code, 2, command)
            self.assertIn("Blocked by the git plugin's guard", err)

    def test_allowed(self):
        for command in ['git stash push -m "agent/fix/123-456"', "git stash push -u --message=x", "git stash -m x",
                        'git stash save "named"', "git stash list --format='%H %gs'", "git stash show -p stash@{1}",
                        "git stash apply 3f2a9c1", "git stash pop stash@{2}", "git stash drop abc123",
                        "git status", "echo 'git stash pop'", "grep -n 'git stash' README.md",
                        "cat > notes.md <<'EOF'\ngit stash pop\nEOF"]:
            self.assertEqual(run(command)[0], 0, command)


class PushTests(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "--allow-empty", "-m", "init")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        self.protect('{"protectedBranches": ["main", "master"]}')

    def protect(self, config: str | None) -> None:
        path = Path(self.repo) / ".claude" / "git.json"
        if config is None:
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(exist_ok=True)
            path.write_text(config)

    def test_force_blocked_lease_allowed(self):
        for command in ["git push --force", "git push -f origin feat", "git push -uf origin feat",
                        "git push origin +feat", "git push --mirror"]:
            self.assertEqual(run(command, self.repo)[0], 2, command)
        git(self.repo, "checkout", "-q", "-b", "feat")
        for command in ["git push --force-with-lease", "git push --force-with-lease origin feat",
                        "git push -u origin feat", "git push", "git push origin HEAD", "git push -o ci.skip origin feat"]:
            self.assertEqual(run(command, self.repo)[0], 0, command)

    def test_main_blocked(self):
        for command in ["git push", "git push origin", "git push origin HEAD", "git push origin main",
                        "git push origin feat:main", "git push origin :main", "git push --all origin",
                        "git push origin refs/heads/main"]:
            self.assertEqual(run(command, self.repo)[0], 2, command)

    def test_main_allowed_unless_the_project_protects_it(self):
        for config in [None, "{}", '{"protectedBranches": []}', "not json", '["main"]']:
            self.protect(config)
            for command in ["git push", "git push origin main", "git push --all origin"]:
                self.assertEqual(run(command, self.repo)[0], 0, f"{config}: {command}")
            self.assertEqual(run("git push --force origin main", self.repo)[0], 2, config)

    def test_first_push_of_a_new_repo_allowed(self):
        git(self.repo, "update-ref", "-d", "refs/remotes/origin/main")
        self.assertEqual(run("git push -u origin main", self.repo)[0], 0)


class InputTests(unittest.TestCase):
    def test_garbage_is_allowed(self):
        proc = subprocess.run([sys.executable, "-I", str(HOOK)], input="not json", capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(run("echo 'unbalanced")[0], 0)


if __name__ == "__main__":
    unittest.main()
