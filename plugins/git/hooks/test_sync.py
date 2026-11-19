"""Tests for sync.py against a real bare remote and two clones, with `gh` stubbed on PATH."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sync.py")
FAKE_GH = '#!/bin/sh\n[ -n "$FAKE_GH_PR" ] || exit 1\nprintf "%s\\n" "$FAKE_GH_PR"\n'


def sh(cwd: str, *args: str) -> str:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def pr(base: str, number: int = 7, state: str = "OPEN") -> str:
    return json.dumps({"baseRefName": base, "number": number, "state": state})


OPENSPACE = {"sync": {
    "base": "main", "strategy": "rebase", "interval": 2, "push": "base", "commitReminder": 20,
    "autosave": {"idle": 5, "message": "Autozapis przy zamknięciu sesji: {files}"}, "askIdentity": True,
}}


class SyncTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.bin = os.path.join(root, "bin")
        os.mkdir(self.bin)
        with open(os.path.join(self.bin, "gh"), "w") as f:
            f.write(FAKE_GH)
        os.chmod(os.path.join(self.bin, "gh"), 0o755)
        self.remote = os.path.join(root, "remote.git")
        sh(root, "git", "init", "--quiet", "--bare", "--initial-branch=main", self.remote)
        self.me = self.clone("me", "Me")
        self.partner = self.clone("partner", "Ania")
        self.write(self.partner, "oferta.md", "# Oferta\n\nCena: 100 zł\n")
        self.commit(self.partner, "Dodano ofertę")
        sh(self.partner, "git", "push", "--quiet", "origin", "main")
        sh(self.me, "git", "pull", "--quiet", "origin", "main")

    def tearDown(self):
        self.tmp.cleanup()

    # --- helpers ---

    def clone(self, name: str, author: str) -> str:
        path = os.path.join(self.tmp.name, name)
        sh(self.tmp.name, "git", "clone", "--quiet", self.remote, path)
        sh(path, "git", "checkout", "--quiet", "-B", "main")
        sh(path, "git", "config", "user.name", author)
        sh(path, "git", "config", "user.email", f"{name}@example.com")
        return path

    def write(self, repo: str, name: str, text: str) -> None:
        path = os.path.join(repo, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def read(self, repo: str, name: str) -> str:
        with open(os.path.join(repo, name)) as f:
            return f.read()

    def exists(self, repo: str, name: str) -> bool:
        return os.path.exists(os.path.join(repo, name))

    def commit(self, repo: str, message: str) -> None:
        sh(repo, "git", "add", "-A")
        sh(repo, "git", "commit", "--quiet", "-m", message)

    def partner_pushes(self, name: str, text: str, message: str, branch: str = "main") -> None:
        sh(self.partner, "git", "fetch", "--quiet", "origin")
        known = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"origin/{branch}"], cwd=self.partner, capture_output=True).returncode == 0
        sh(self.partner, "git", "checkout", "--quiet", "-B", branch, f"origin/{branch}" if known else "origin/main")
        self.write(self.partner, name, text)
        self.commit(self.partner, message)
        sh(self.partner, "git", "push", "--quiet", "origin", branch)

    def on_feature(self, branch: str = "feature", start: str = "origin/main") -> None:
        sh(self.me, "git", "checkout", "--quiet", "-b", branch, start)
        self.write(self.me, f"{branch}.md", "own work\n")
        self.commit(self.me, f"Own work on {branch}")

    def configure(self, sync: object) -> None:
        """Commit `.claude/git.json` on the current branch of `me`."""
        self.write(self.me, ".claude/git.json", json.dumps(sync))
        self.commit(self.me, "Configure sync")

    def git_dir(self, repo: str) -> str:
        return sh(repo, "git", "rev-parse", "--absolute-git-dir")

    def forget_last_refresh(self) -> None:
        os.remove(os.path.join(self.git_dir(self.me), "claude-git-sync-last"))

    def head(self, repo: str = "") -> str:
        return sh(repo or self.me, "git", "rev-parse", "HEAD")

    def make_stale(self, repo: str, name: str, text: str = "draft\n") -> None:
        self.write(repo, name, text)
        hour_ago = time.time() - 3600
        os.utime(os.path.join(repo, name), (hour_ago, hour_ago))

    def remote_head(self, branch: str = "main") -> str:
        return sh(self.me, "git", "ls-remote", "origin", f"refs/heads/{branch}").split("\t")[0]

    def remote_log(self, branch: str = "main") -> list[str]:
        sh(self.me, "git", "fetch", "--quiet", "origin")
        return sh(self.me, "git", "log", "--format=%s", f"origin/{branch}").splitlines()

    def start_open_rebase(self) -> None:
        """Leave a conflicted rebase open in `me`, as an agent resolving it would."""
        self.write(self.me, "oferta.md", "# Oferta\n\nCena: 90 zł\n")
        self.commit(self.me, "Cena 90")
        self.partner_pushes("oferta.md", "# Oferta\n\nCena: 120 zł\n", "Cena 120")
        sh(self.me, "git", "fetch", "--quiet", "origin")
        subprocess.run(["git", "rebase", "origin/main"], cwd=self.me, capture_output=True)
        self.assertFalse(self.nothing_open(self.me))

    def output(self, repo: str, event: str, data: dict | None = None, gh: str | None = None) -> dict | None:
        """Run a Stop or SessionEnd hook; return its JSON output, or None when it printed nothing."""
        result = self.run_hook(repo, event, gh, data=data)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        return json.loads(result.stdout) if result.stdout.strip() else None

    def run_hook(self, repo: str, event: str, gh: str | None, project_dir: str | None = None,
                 data: dict | None = None):
        env = {
            **os.environ,
            "CLAUDE_PROJECT_DIR": project_dir or repo,
            "PATH": self.bin + os.pathsep + os.environ["PATH"],
            "HOME": self.tmp.name,
            "XDG_CONFIG_HOME": os.path.join(self.tmp.name, "xdg"),
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        env.pop("FAKE_GH_PR", None)
        if gh:
            env["FAKE_GH_PR"] = gh
        return subprocess.run(
            [sys.executable, "-I", SCRIPT, event],
            input=json.dumps({"cwd": repo, **(data or {})}),
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )

    def hook(self, repo: str, event: str = "session-start", gh: str | None = None) -> str:
        """Run the hook; return the agent's context ('' when the hook said nothing)."""
        result = self.run_hook(repo, event, gh)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        if not result.stdout.strip():
            return ""
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], {"session-start": "SessionStart", "prompt": "UserPromptSubmit"}[event])
        return output["additionalContext"]

    def nothing_open(self, repo: str) -> bool:
        d = self.git_dir(repo)
        return not any(os.path.exists(os.path.join(d, n)) for n in ("MERGE_HEAD", "rebase-merge", "rebase-apply"))



class RefreshFromBaseTest(SyncTestCase):
    # --- refresh ---

    def test_merges_the_pr_base_and_reports_it(self):
        self.on_feature()
        self.configure({"sync": {"afterUpdate": [{"run": "echo installed"}]}})
        self.partner_pushes("plan.md", "# Plan\n", "Dodano plan")
        context = self.hook(self.me, gh=pr("main"))
        self.assertEqual(self.read(self.me, "plan.md"), "# Plan\n")
        self.assertEqual(len(sh(self.me, "git", "log", "-1", "--format=%P").split()), 2)
        self.assertIn("$ git merge --no-edit origin/main", context)
        self.assertIn("PR #7", context)
        self.assertIn("Ania: Dodano plan", context)
        self.assertIn("- plan.md", context)
        self.assertIn("`echo installed` → exit 0", context)
        self.assertNotIn("claude-git-sync-log", context)
        self.assertIn("re-read them", context)

    def test_without_config_only_merges_and_never_pushes(self):
        self.on_feature()
        before = self.head()
        remote_before = sh(self.me, "git", "ls-remote", "origin")
        self.partner_pushes("plan.md", "# Plan\n", "Dodano plan")
        remote_after_partner = sh(self.me, "git", "ls-remote", "origin")
        self.assertIn("git merge --no-edit", self.hook(self.me, gh=pr("main")))
        self.assertNotEqual(remote_before, remote_after_partner)
        self.assertEqual(sh(self.me, "git", "ls-remote", "origin"), remote_after_partner)
        self.assertEqual(sh(self.me, "git", "rev-parse", "HEAD^1"), before)  # own commit kept, not rebased
        self.assertEqual(sh(self.me, "git", "rev-list", "--count", "--no-merges", "origin/main..HEAD"), "1")

    def test_stacked_node_refreshes_from_the_node_below_not_main(self):
        self.partner_pushes("lower.md", "lower\n", "Lower node", branch="lower")
        sh(self.me, "git", "fetch", "--quiet", "origin")
        self.on_feature("upper", start="origin/lower")
        self.partner_pushes("lower.md", "lower v2\n", "Lower node v2", branch="lower")
        self.partner_pushes("plan.md", "# Plan\n", "Main moved", branch="main")
        context = self.hook(self.me, gh=pr("lower"))
        self.assertIn("origin/lower", context)
        self.assertNotIn("Main moved", context)
        self.assertEqual(self.read(self.me, "lower.md"), "lower v2\n")
        self.assertFalse(self.exists(self.me, "plan.md"))

    def test_no_pr_and_no_paseo_record_leaves_the_branch_alone(self):
        self.on_feature()
        before = self.head()
        self.partner_pushes("plan.md", "# Plan\n", "Dodano plan")
        self.assertEqual(self.hook(self.me, gh=None), "")
        self.assertEqual(self.head(), before)
        self.assertEqual(self.hook(self.me, gh=pr("main", state="MERGED")), "")
        self.assertEqual(self.head(), before)

    def test_paseo_record_is_used_when_gh_fails(self):
        self.on_feature()
        paseo = os.path.join(self.git_dir(self.me), "paseo")
        os.makedirs(paseo)
        with open(os.path.join(paseo, "worktree.json"), "w") as f:
            json.dump({"baseRefName": "main"}, f)
        self.partner_pushes("plan.md", "# Plan\n", "Dodano plan")
        self.assertIn("Paseo", self.hook(self.me, gh=None))
        self.assertTrue(self.exists(self.me, "plan.md"))

    def test_conflict_is_rolled_back_and_handed_to_the_agent(self):
        sh(self.me, "git", "checkout", "--quiet", "-b", "feature")
        self.write(self.me, "oferta.md", "# Oferta\n\nCena: 90 zł\n")
        self.commit(self.me, "Cena 90")
        before = self.head()
        self.partner_pushes("oferta.md", "# Oferta\n\nCena: 120 zł\n", "Cena 120")
        context = self.hook(self.me, gh=pr("main"))
        self.assertIn("- oferta.md", context)
        self.assertIn("fix-conflicts", context)
        self.assertIn("`git merge --no-edit origin/main`", context)
        self.assertEqual(self.head(), before)
        self.assertTrue(self.nothing_open(self.me))
        self.assertEqual(sh(self.me, "git", "status", "--porcelain"), "")
        self.assertIn("90 zł", self.read(self.me, "oferta.md"))

    def test_conflict_under_rebase_leaves_no_rebase_open(self):
        sh(self.me, "git", "checkout", "--quiet", "-b", "feature")
        self.configure({"sync": {"strategy": "rebase"}})
        self.write(self.me, "oferta.md", "# Oferta\n\nCena: 90 zł\n")
        self.commit(self.me, "Cena 90")
        before = self.head()
        self.partner_pushes("oferta.md", "# Oferta\n\nCena: 120 zł\n", "Cena 120")
        context = self.hook(self.me, gh=pr("main"))
        self.assertIn("`git rebase --autostash origin/main`", context)
        self.assertEqual(self.head(), before)
        self.assertTrue(self.nothing_open(self.me))

    def test_rebase_strategy_replays_own_commits(self):
        self.on_feature()
        self.configure({"sync": {"strategy": "rebase"}})
        self.partner_pushes("plan.md", "# Plan\n", "Dodano plan")
        self.assertIn("$ git rebase --autostash origin/main", self.hook(self.me, gh=pr("main")))
        self.assertEqual(sh(self.me, "git", "merge-base", "HEAD", "origin/main"), sh(self.me, "git", "rev-parse", "origin/main"))
        self.assertEqual(sh(self.me, "git", "log", "-1", "--format=%P").count(" "), 0)

    def test_uncommitted_or_untracked_overlap_is_not_integrated(self):
        self.on_feature()
        before = self.head()
        self.partner_pushes("oferta.md", "# Oferta\n\nCena: 120 zł\n", "Cena 120")
        self.partner_pushes("plan.md", "# Plan\n", "Dodano plan")
        self.write(self.me, "oferta.md", "# Oferta\n\nCena: 90 zł\n")
        self.write(self.me, "plan.md", "my own plan\n")
        context = self.hook(self.me, gh=pr("main"))
        self.assertIn("- oferta.md\n- plan.md", context)
        self.assertIn("Checkpoint", context)
        self.assertEqual(self.head(), before)
        self.assertIn("90 zł", self.read(self.me, "oferta.md"))
        self.assertEqual(self.read(self.me, "plan.md"), "my own plan\n")

    def test_unrelated_uncommitted_edit_survives_the_merge(self):
        self.on_feature()
        self.write(self.me, "oferta.md", "# Oferta\n\nCena: 90 zł\n")
        self.partner_pushes("plan.md", "# Plan\n", "Dodano plan")
        self.assertIn("git merge", self.hook(self.me, gh=pr("main")))
        self.assertTrue(self.exists(self.me, "plan.md"))
        self.assertIn("90 zł", self.read(self.me, "oferta.md"))

    def test_staged_unrelated_file_blocks_a_merge(self):
        self.on_feature()
        before = self.head()
        self.write(self.me, "notes.md", "notes\n")
        sh(self.me, "git", "add", "notes.md")
        self.partner_pushes("plan.md", "# Plan\n", "Dodano plan")
        context = self.hook(self.me, gh=pr("main"))
        self.assertIn("staged", context)
        self.assertEqual(self.head(), before)
        self.assertEqual(sh(self.me, "git", "status", "--porcelain"), "A  notes.md")

    def test_missing_identity_blocks_a_merge(self):
        self.on_feature()
        before = self.head()
        sh(self.me, "git", "config", "--unset", "user.name")
        self.partner_pushes("plan.md", "# Plan\n", "Dodano plan")
        self.assertIn("user.name", self.hook(self.me, gh=pr("main")))
        self.assertEqual(self.head(), before)

    def test_refresh_is_throttled_across_events(self):
        self.on_feature()
        self.partner_pushes("plan.md", "# Plan\n", "Dodano plan")
        self.assertIn("Dodano plan", self.hook(self.me, gh=pr("main")))
        self.partner_pushes("notes.md", "notes\n", "Notatki")
        self.assertEqual(self.hook(self.me, "prompt", gh=pr("main")), "")
        self.assertFalse(self.exists(self.me, "notes.md"))
        self.forget_last_refresh()
        self.assertIn("Notatki", self.hook(self.me, "prompt", gh=pr("main")))

    def test_lock_held_by_another_session_skips(self):
        self.on_feature()
        before = self.head()
        open(os.path.join(self.git_dir(self.me), "claude-git-sync-lock"), "w").close()
        self.partner_pushes("plan.md", "# Plan\n", "Dodano plan")
        self.assertEqual(self.hook(self.me, gh=pr("main")), "")
        self.assertEqual(self.head(), before)

    def test_open_rebase_is_never_touched(self):
        sh(self.me, "git", "checkout", "--quiet", "-b", "feature")
        self.start_open_rebase()
        head = self.head()
        self.partner_pushes("plan.md", "# Plan\n", "Dodano plan")
        self.assertEqual(self.hook(self.me, gh=pr("main")), "")
        self.assertEqual(self.hook(self.me, "prompt", gh=pr("main")), "")  # no opt-in feature: no reminder
        self.assertEqual(self.head(), head)
        self.assertFalse(self.nothing_open(self.me))

    def test_detached_head_is_left_alone(self):
        sh(self.me, "git", "checkout", "--quiet", "--detach")
        before = self.head()
        self.partner_pushes("plan.md", "# Plan\n", "Dodano plan")
        self.assertEqual(self.hook(self.me, gh=pr("main")), "")
        self.assertEqual(self.head(), before)

    def test_own_base_fast_forwards_but_never_merges_when_diverged(self):
        self.configure({"sync": {"base": "main"}})
        sh(self.me, "git", "push", "--quiet", "origin", "main")
        self.partner_pushes("plan.md", "# Plan\n", "Dodano plan")
        self.assertIn("$ git merge --ff-only origin/main", self.hook(self.me))
        self.assertEqual(self.head(), sh(self.me, "git", "rev-parse", "origin/main"))
        self.forget_last_refresh()
        self.write(self.me, "mine.md", "mine\n")
        self.commit(self.me, "Local commit")
        before = self.head()
        self.partner_pushes("notes.md", "notes\n", "Notatki")
        self.assertEqual(self.hook(self.me), "")
        self.assertEqual(self.head(), before)

    # --- after-update commands ---

    def test_after_update_when_filters_by_changed_paths(self):
        self.on_feature()
        self.configure({"sync": {"afterUpdate": [
            {"run": "touch lock-ran", "when": ["*.lock"]},
            {"run": "touch pkg-ran", "when": ["package.json"]},
            {"run": "touch any-ran", "when": "not a list"},
        ]}})
        self.partner_pushes("apps/web/package.json", "{}\n", "Web package")
        context = self.hook(self.me, gh=pr("main"))
        self.assertIn("`touch lock-ran` → skipped (when: no matching change)", context)
        self.assertIn("`touch pkg-ran` → exit 0", context)
        self.assertIn("`touch any-ran` → exit 0", context)
        self.assertFalse(self.exists(self.me, "lock-ran"))
        self.assertTrue(self.exists(self.me, "pkg-ran"))

    def test_after_update_stops_at_the_first_failure(self):
        self.on_feature()
        self.configure({"sync": {"afterUpdate": [
            {"run": "echo boom; exit 3"},
            {"run": "touch never-ran"},
        ]}})
        self.partner_pushes("plan.md", "# Plan\n", "Dodano plan")
        context = self.hook(self.me, gh=pr("main"))
        log = os.path.join(self.git_dir(self.me), "claude-git-sync-log")
        self.assertIn("`echo boom; exit 3` → exit 3", context)
        self.assertIn("`touch never-ran` → not run (an earlier command failed)", context)
        self.assertIn(log, context)
        self.assertFalse(self.exists(self.me, "never-ran"))
        with open(log) as f:
            self.assertIn("boom", f.read())

    def test_after_update_timeout_is_reported(self):
        self.on_feature()
        self.configure({"sync": {"afterUpdate": [{"run": "sleep 30", "timeout": 1}, {"run": "true"}]}})
        self.partner_pushes("plan.md", "# Plan\n", "Dodano plan")
        context = self.hook(self.me, gh=pr("main"))
        self.assertIn("`sleep 30` → timed out after 1 s", context)
        self.assertIn("`true` → not run", context)

    # --- config and robustness ---

    def test_malformed_config_means_defaults(self):
        self.on_feature()
        for n, config in enumerate(['[]', '"x"', '{"sync": "x"}', '{not json',
                                    '{"sync": {"refresh": "no", "strategy": 5, "interval": "x", '
                                    '"base": 3, "afterUpdate": "x"}}']):
            with self.subTest(config=config):
                self.write(self.me, ".claude/git.json", config)
                self.partner_pushes(f"plan{n}.md", "# Plan\n", f"Plan {n}")
                self.assertIn("$ git merge --no-edit origin/main", self.hook(self.me, gh=pr("main")))
                self.assertTrue(self.exists(self.me, f"plan{n}.md"))
                self.forget_last_refresh()

    def test_refresh_can_be_turned_off(self):
        self.on_feature()
        self.configure({"sync": {"refresh": False}})
        before = self.head()
        self.partner_pushes("plan.md", "# Plan\n", "Dodano plan")
        self.assertEqual(self.hook(self.me, gh=pr("main")), "")
        self.assertEqual(self.head(), before)

    def test_outside_a_repo_or_on_error_exits_quietly(self):
        plain = os.path.join(self.tmp.name, "plain")
        os.mkdir(plain)
        self.assertEqual(self.hook(plain), "")
        result = self.run_hook(self.me, "prompt", None, project_dir=os.path.join(self.tmp.name, "missing"))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("git sync hook:", result.stderr)

    def test_moved_submodule_pin_is_checked_out(self):
        # Local submodule remotes need the file protocol, which git refuses by default.
        file_protocol = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "protocol.file.allow", "GIT_CONFIG_VALUE_0": "always"}
        os.environ.update(file_protocol)
        self.addCleanup(lambda: [os.environ.pop(k) for k in file_protocol])
        lib = os.path.join(self.tmp.name, "lib")
        sh(self.tmp.name, "git", "init", "--quiet", "--initial-branch=main", lib)
        for author in ("one", "two"):
            self.write(lib, "skill.md", f"{author}\n")
            sh(lib, "git", "add", "-A")
            sh(lib, "git", "-c", "user.name=x", "-c", "user.email=x@x", "commit", "--quiet", "-m", author)
        first = sh(lib, "git", "rev-parse", "HEAD~1")
        second = sh(lib, "git", "rev-parse", "HEAD")

        self.on_feature()
        sh(self.partner, "git", "submodule", "add", "--quiet", lib, "lib")
        sh(self.partner, "git", "-C", "lib", "checkout", "--quiet", first)
        self.commit(self.partner, "Submodule")
        sh(self.partner, "git", "push", "--quiet", "origin", "main")
        self.assertIn("Submodules checked out at their new pin:\n- lib", self.hook(self.me, gh=pr("main")))
        self.assertEqual(sh(self.me, "git", "-C", "lib", "rev-parse", "HEAD"), first)

        sh(self.partner, "git", "-C", "lib", "checkout", "--quiet", second)
        self.commit(self.partner, "Submodule v2")
        sh(self.partner, "git", "push", "--quiet", "origin", "main")
        self.forget_last_refresh()
        self.hook(self.me, gh=pr("main"))
        self.assertEqual(sh(self.me, "git", "-C", "lib", "rev-parse", "HEAD"), second)


class OpenSpaceTest(SyncTestCase):
    """OpenSpace's own scenarios: everyone on main, rebase, push HEAD:main, reminder, autosave."""

    def setUp(self):
        super().setUp()
        self.partner_pushes(".claude/git.json", json.dumps(OPENSPACE), "Configure sync")
        sh(self.me, "git", "pull", "--quiet", "origin", "main")

    def test_session_start_pulls_partner_changes_and_names_them(self):
        self.partner_pushes("plan.md", "# Plan\n", "Dodano plan")
        context = self.hook(self.me)
        self.assertIn("Ania: Dodano plan", context)
        self.assertIn("$ git rebase --autostash origin/main", context)
        self.assertEqual(self.read(self.me, "plan.md"), "# Plan\n")

    def test_prompt_is_throttled(self):
        self.hook(self.me)
        self.partner_pushes("plan.md", "# Plan\n", "Dodano plan")
        self.assertEqual(self.hook(self.me, "prompt"), "")
        self.assertFalse(self.exists(self.me, "plan.md"))

    def test_stop_pushes_commits_and_reports_pulled_changes_on_next_prompt(self):
        self.hook(self.me)
        self.partner_pushes("plan.md", "# Plan\n", "Dodano plan")
        self.write(self.me, "notatki.md", "notatki\n")
        self.commit(self.me, "Dodano notatki")
        self.assertIsNone(self.output(self.me, "stop"))  # regardless of the interval
        self.assertEqual(self.remote_log()[:2], ["Dodano notatki", "Dodano plan"])
        self.assertIn("Ania: Dodano plan", self.hook(self.me, "prompt"))  # delivered although not due
        self.assertEqual(self.hook(self.me, "prompt"), "")

    def test_stop_reports_after_update_commands_instead_of_running_them(self):
        config = {"sync": {**OPENSPACE["sync"], "afterUpdate": [{"run": "touch built.flag"}]}}
        self.partner_pushes(".claude/git.json", json.dumps(config), "Add a build")
        sh(self.me, "git", "pull", "--quiet", "--rebase", "origin", "main")
        self.partner_pushes("plan.md", "# Plan\n", "Dodano plan")
        self.write(self.me, "notatki.md", "notatki\n")
        self.commit(self.me, "Dodano notatki")
        self.assertIsNone(self.output(self.me, "stop"))
        self.assertEqual(self.remote_log()[0], "Dodano notatki")
        self.assertFalse(self.exists(self.me, "built.flag"))  # Stop's hook timeout is too short for them
        context = self.hook(self.me, "prompt")
        self.assertIn("After-update commands were NOT run", context)
        self.assertIn("- touch built.flag", context)

    def test_stop_blocks_on_conflict_once_and_leaves_no_rebase_open(self):
        self.partner_pushes("oferta.md", "# Oferta\n\nCena: 120 zł\n", "Cena 120")
        self.write(self.me, "oferta.md", "# Oferta\n\nCena: 90 zł\n")
        self.commit(self.me, "Cena 90")
        output = self.output(self.me, "stop")
        self.assertEqual(output["decision"], "block")
        self.assertIn("collides", output["reason"])
        self.assertIn("- oferta.md", output["reason"])
        self.assertTrue(self.nothing_open(self.me))
        self.assertIn("90 zł", self.read(self.me, "oferta.md"))
        self.assertIsNone(self.output(self.me, "stop", {"stop_hook_active": True}))
        self.assertIn("collides", self.hook(self.me, "prompt"))  # the second Stop deferred it

    def test_uncommitted_edit_to_a_file_partner_changed_is_not_touched(self):
        self.partner_pushes("oferta.md", "# Oferta\n\nCena: 120 zł\n", "Cena 120")
        self.write(self.me, "oferta.md", "# Oferta\n\nCena: 90 zł\n")
        context = self.hook(self.me)
        self.assertIn("uncommitted or untracked local changes", context)
        self.assertIn("left over from an earlier session:\n- oferta.md", context)
        self.assertIn("90 zł", self.read(self.me, "oferta.md"))

    def test_uncommitted_edit_elsewhere_survives_the_pull(self):
        self.partner_pushes("plan.md", "# Plan\n", "Dodano plan")
        self.write(self.me, "oferta.md", "# Oferta\n\nCena: 90 zł\n")
        self.hook(self.me)
        self.assertEqual(self.read(self.me, "plan.md"), "# Plan\n")
        self.assertIn("90 zł", self.read(self.me, "oferta.md"))

    def test_stop_asks_to_commit_only_stale_work_and_never_twice(self):
        self.write(self.me, "fresh.md", "fresh\n")
        self.assertIsNone(self.output(self.me, "stop"))
        self.make_stale(self.me, "old.md")
        output = self.output(self.me, "stop")
        self.assertEqual(output["decision"], "block")
        self.assertIn("older than 20 minutes:\n- old.md", output["reason"])
        self.assertIn("`git-workflow` skill (Checkpoint)", output["reason"])
        self.assertNotIn("fresh.md", output["reason"])
        self.assertIsNone(self.output(self.me, "stop", {"stop_hook_active": True}))

    def test_stop_never_blocks_while_an_integration_is_open(self):
        self.start_open_rebase()
        self.make_stale(self.me, "old.md")
        self.assertIsNone(self.output(self.me, "stop"))
        self.assertIsNone(self.output(self.me, "session-end"))
        self.assertFalse(self.nothing_open(self.me))
        self.assertIn("still open", self.hook(self.me, "prompt"))
        self.assertIn("still open", self.hook(self.me))

    def test_worktree_on_its_own_branch_pushes_to_main(self):
        worktree = os.path.join(self.tmp.name, "wt")
        sh(self.me, "git", "worktree", "add", "--quiet", "-b", "paseo-task", worktree)
        self.write(worktree, "z-worktree.md", "x\n")
        self.commit(worktree, "Z worktree")
        self.assertIsNone(self.output(worktree, "stop"))
        self.assertEqual(self.remote_log()[0], "Z worktree")
        self.assertEqual(sh(self.me, "git", "ls-remote", "origin", "paseo-task"), "")

    def test_session_end_autosaves_idle_files_only_and_pushes(self):
        self.make_stale(self.me, "szkic.md", "szkic\n")
        self.write(self.me, "w-toku.md", "inna sesja jeszcze nad tym pracuje\n")
        sh(self.me, "git", "add", "w-toku.md")
        self.assertIsNone(self.output(self.me, "session-end"))
        self.assertEqual(sh(self.me, "git", "status", "--porcelain"), "A  w-toku.md")
        self.assertEqual(self.remote_log()[0], "Autozapis przy zamknięciu sesji: szkic.md")
        self.assertEqual(sh(self.me, "git", "show", "--name-only", "--format=", "origin/main"), "szkic.md")

    def test_autosave_lists_five_files_and_counts_the_rest(self):
        for n in range(7):
            self.make_stale(self.me, f"s{n}.md")
        self.output(self.me, "session-end")
        self.assertEqual(self.remote_log()[0], "Autozapis przy zamknięciu sesji: s0.md, s1.md, s2.md, s3.md, s4.md and 2 more")

    def test_offline_is_reported_and_does_not_fail(self):
        sh(self.me, "git", "remote", "set-url", "origin", os.path.join(self.tmp.name, "missing.git"))
        self.assertIn("unreachable", self.hook(self.me))

    def test_missing_identity_is_asked_for(self):
        sh(self.me, "git", "config", "--unset", "user.name")
        self.assertIn("git config --global user.name", self.hook(self.me))

    def test_submodule_follows_the_pin_a_partner_moves_and_is_never_autosaved(self):
        file_protocol = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "protocol.file.allow", "GIT_CONFIG_VALUE_0": "always"}
        os.environ.update(file_protocol)
        self.addCleanup(lambda: [os.environ.pop(k) for k in file_protocol])
        lib = os.path.join(self.tmp.name, "lib")
        sh(self.tmp.name, "git", "init", "--quiet", "--initial-branch=main", lib)
        for author in ("one", "two"):
            self.write(lib, "skill.md", f"{author}\n")
            sh(lib, "git", "add", "-A")
            sh(lib, "git", "-c", "user.name=x", "-c", "user.email=x@x", "commit", "--quiet", "-m", author)
        first = sh(lib, "git", "rev-parse", "HEAD~1")
        second = sh(lib, "git", "rev-parse", "HEAD")

        sh(self.partner, "git", "submodule", "add", "--quiet", lib, "lib")
        sh(self.partner, "git", "-C", "lib", "checkout", "--quiet", first)
        self.commit(self.partner, "Podmoduł")
        sh(self.partner, "git", "push", "--quiet", "origin", "main")
        self.hook(self.me)
        self.assertEqual(sh(self.me, "git", "-C", "lib", "rev-parse", "HEAD"), first)

        sh(self.partner, "git", "-C", "lib", "checkout", "--quiet", second)
        self.commit(self.partner, "Nowa wersja podmodułu")
        sh(self.partner, "git", "push", "--quiet", "origin", "main")
        self.forget_last_refresh()
        self.hook(self.me)
        self.assertEqual(sh(self.me, "git", "-C", "lib", "rev-parse", "HEAD"), second)

        # A pin moved by hand stays out of the autosave.
        sh(self.me, "git", "-C", "lib", "checkout", "--quiet", first)
        self.make_stale(self.me, "szkic.md")
        self.output(self.me, "session-end")
        self.assertEqual(sh(self.me, "git", "ls-tree", "origin/main", "lib").split()[2], second)
        self.assertEqual(sh(self.me, "git", "show", "--name-only", "--format=", "origin/main"), "szkic.md")


class OptInTest(SyncTestCase):
    def test_without_config_stop_and_session_end_do_nothing(self):
        self.on_feature()
        sh(self.me, "git", "push", "--quiet", "-u", "origin", "feature")
        self.write(self.me, "more.md", "more\n")
        self.commit(self.me, "More")
        head, remote = self.head(), self.remote_head("feature")
        self.make_stale(self.me, "old.md")
        sh(self.me, "git", "config", "--unset", "user.name")
        self.assertIsNone(self.output(self.me, "stop"))
        self.assertIsNone(self.output(self.me, "session-end"))
        self.assertEqual(self.hook(self.me), "")  # no identity question, no leftovers, no push
        self.assertEqual(self.hook(self.me, "prompt"), "")
        self.assertEqual(self.head(), head)
        self.assertEqual(self.remote_head("feature"), remote)
        self.assertEqual(sh(self.me, "git", "status", "--porcelain"), "?? old.md")
        self.assertFalse(os.path.exists(os.path.join(self.git_dir(self.me), "claude-git-sync-pending")))

    def test_push_branch_pushes_to_its_upstream_only(self):
        self.on_feature()
        sh(self.me, "git", "push", "--quiet", "-u", "origin", "feature")
        main = self.remote_head("main")
        self.configure({"sync": {"push": "branch"}})
        self.assertIsNone(self.output(self.me, "stop", gh=pr("main")))
        self.assertEqual(self.remote_head("feature"), self.head())
        self.assertEqual(self.remote_head("main"), main)

    def test_push_branch_skips_a_branch_with_no_upstream(self):
        self.on_feature()
        self.configure({"sync": {"push": "branch"}})
        self.assertIsNone(self.output(self.me, "stop", gh=pr("main")))
        self.forget_last_refresh()
        self.assertEqual(self.hook(self.me, gh=pr("main")), "")
        self.assertEqual(sh(self.me, "git", "ls-remote", "origin", "feature"), "")

    def test_rejected_branch_push_merges_the_upstream_and_retries(self):
        self.on_feature()
        sh(self.me, "git", "push", "--quiet", "-u", "origin", "feature")
        self.partner_pushes("partner.md", "partner\n", "Partner on feature", branch="feature")
        self.configure({"sync": {"push": "branch"}})
        self.assertIsNone(self.output(self.me, "stop"))
        self.assertEqual(self.remote_head("feature"), self.head())
        self.assertTrue(self.exists(self.me, "partner.md"))
        self.assertEqual(len(sh(self.me, "git", "log", "-1", "--format=%P").split()), 2)  # merged, not rebased
        self.assertIn("refreshed from its upstream `origin/feature`", self.hook(self.me, "prompt"))

    def test_push_is_refused_to_a_protected_branch(self):
        for push in ("branch", "base"):
            with self.subTest(push=push):
                remote = self.remote_head("main")
                self.configure({"protectedBranches": ["main"], "sync": {"push": push, "base": "main"}})
                self.assertIsNone(self.output(self.me, "stop"))
                self.assertEqual(self.remote_head("main"), remote)
                self.assertIn("`protectedBranches`", self.hook(self.me, "prompt"))

    def test_open_integration_reminder_needs_an_opt_in_feature(self):
        self.configure({"sync": {"commitReminder": 30}})
        self.start_open_rebase()
        self.assertIn("still open", self.hook(self.me, "prompt"))


if __name__ == "__main__":
    unittest.main()
