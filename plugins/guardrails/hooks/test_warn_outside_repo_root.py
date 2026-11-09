"""Tests for warn_outside_repo_root.py against real throwaway git repos."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).parent / "warn_outside_repo_root.py"
GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}


def run(payload: str) -> tuple[int, str]:
    proc = subprocess.run([sys.executable, "-I", str(HOOK)], input=payload, capture_output=True, text=True,
                          timeout=15)
    return proc.returncode, proc.stdout


class WarnOutsideRepoRootTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        (self.repo / "packages" / "app").mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=self.repo, env=GIT_ENV, check=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def session(self, cwd: Path | str) -> tuple[int, str]:
        return run(json.dumps({"hook_event_name": "SessionStart", "cwd": str(cwd)}))

    def test_silent_at_the_root(self) -> None:
        self.assertEqual(self.session(self.repo), (0, ""))

    def test_warns_in_a_subdirectory(self) -> None:
        code, out = self.session(self.repo / "packages" / "app")
        self.assertEqual(code, 0)
        result = json.loads(out)
        self.assertIn("Restart Claude Code from", result["systemMessage"])
        self.assertEqual(result["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertEqual(result["hookSpecificOutput"]["additionalContext"], result["systemMessage"])

    def test_silent_outside_a_repository(self) -> None:
        outside = Path(self.tmp.name) / "plain"
        outside.mkdir()
        self.assertEqual(self.session(outside), (0, ""))

    def test_silent_on_bad_input(self) -> None:
        self.assertEqual(run("not json"), (0, ""))
        self.assertEqual(run(json.dumps({"cwd": str(Path(self.tmp.name) / "missing")})), (0, ""))


if __name__ == "__main__":
    unittest.main()
