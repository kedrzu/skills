"""Tests for sessions.py on synthetic transcripts (no real session data)."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import sessions  # noqa: E402

SCRIPT = Path(__file__).parent / "sessions.py"


def write_jsonl(path: Path, events: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    return path


def claude_events(cwd: str) -> list[dict]:
    base = {"cwd": cwd, "gitBranch": "feat", "sessionId": "s1"}
    return [
        {**base, "type": "user", "timestamp": "2026-10-01T10:00:00Z",
         "message": {"role": "user", "content": "<command-message>dev:fix</command-message>\n<command-name>/dev:fix</command-name>\n<command-args>login breaks</command-args>"}},
        {**base, "type": "user", "isMeta": True, "message": {"content": [{"type": "text", "text": "Base directory for this skill: /x"}]}},
        {**base, "type": "assistant", "timestamp": "2026-10-01T10:01:00Z", "message": {"content": [
            {"type": "thinking", "thinking": "private"},
            {"type": "text", "text": "Reproducing first."},
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "bun test login"}},
            {"type": "tool_use", "id": "t2", "name": "AskUserQuestion", "input": {"questions": []}},
        ]}},
        {**base, "type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": "FAIL login.test.ts expected 200 got 500"},
            {"type": "tool_result", "tool_use_id": "t2", "content": "Your questions have been answered: \"Which?\"=\"A\""},
        ]}},
        {**base, "type": "user", "promptSource": "sdk", "message": {"content": [{"type": "text", "text": "<paseo-system> Agent 1 finished"}]}},
        {**base, "type": "user", "turnOrigin": {"kind": "task_notification"}, "message": {"content": "<task-notification>done</task-notification>"}},
        {**base, "type": "user", "message": {"content": [{"type": "text", "text": "[Request interrupted by user]"}]}},
        {**base, "type": "attachment", "attachment": {"type": "queued_command", "prompt": [{"type": "text", "text": "nie, najpierw test"}]}},
        {**base, "type": "assistant", "isSidechain": True, "message": {"content": [{"type": "text", "text": "subagent noise"}]}},
        {**base, "type": "user", "timestamp": "2026-10-01T10:30:00Z", "message": {"content": [{"type": "text", "text": "ok, działaj"}]}},
    ]


def codex_events(cwd: str, subagent: bool = False) -> list[dict]:
    def item(it):
        return {"type": "event_msg", "payload": {"type": "item_completed", "item": it}}

    def call(kind, call_id, **fields):
        return {"type": "response_item", "payload": {"type": kind, "call_id": call_id, **fields}}

    def output(kind, call_id, value):
        return {"type": "response_item", "payload": {"type": kind, "call_id": call_id, "output": value}}
    return [
        {"type": "session_meta", "payload": {"timestamp": "2026-10-02T08:00:00Z", "cwd": cwd, "git": {"branch": "main"},
                                             "thread_source": "subagent" if subagent else "user"}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "# AGENTS.md instructions"}]}},
        item({"type": "UserMessage", "content": [{"type": "text", "text": "/retro why are e2e tests flaky"}]}),
        item({"type": "AgentMessage", "content": [{"type": "Text", "text": "Looking at sessions."}]}),
        item({"type": "McpToolCall", "server": "linear", "tool": "list_issues", "arguments": {"query": "flaky"}, "status": "failed", "error": "unauthorized"}),
        item({"type": "FileChange", "changes": {"/r/docs/a.md": {"type": "add"}}}),
        call("custom_tool_call", "c1", name="exec", input='const r = await tools.exec_command({cmd: "bun test e2e", workdir: "/r"});\ntext(r);'),
        output("custom_tool_call_output", "c1", [{"type": "input_text", "text": "Script failed"}, {"type": "input_text", "text": "Script error:\n3 tests failed"}]),
        call("function_call", "c2", name="exec_command", arguments=json.dumps({"cmd": "git status", "workdir": "/r"})),
        output("function_call_output", "c2", "Wall time 0.1 seconds\nProcess exited with code 0\nOutput:\nclean"),
        call("function_call", "c3", name="wait", arguments=json.dumps({"cell_id": "7"})),
        output("function_call_output", "c3", "Script completed"),
        # Already rendered by the FileChange and McpToolCall items above.
        call("custom_tool_call", "c4", name="apply_patch", input="*** Begin Patch"),
        call("custom_tool_call", "c5", name="exec", input="text(await tools.mcp__linear__list_issues({query: 'flaky'}));"),
        item({"type": "UserMessage", "content": [{"type": "text", "text": "<paseo-system> Agent 2 idle"}]}),
        {"type": "event_msg", "payload": {"type": "turn_aborted", "reason": "interrupted"}},
    ]


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def run_script(self, *args) -> str:
        return subprocess.run([sys.executable, "-I", str(SCRIPT), *args], capture_output=True, text=True, check=True).stdout

    def test_claude_render_keeps_the_human_and_drops_injections(self):
        path = write_jsonl(self.tmp / "c.jsonl", claude_events("/r"))
        out = self.run_script("render", str(path))
        self.assertIn("/dev:fix login breaks", out)
        self.assertIn("- Bash(bun test login) -> ERROR: FAIL login.test.ts", out)
        self.assertIn("## USER (answering AskUserQuestion)", out)
        self.assertIn("!! [Request interrupted by user]", out)
        self.assertIn("nie, najpierw test", out)
        self.assertIn("(30 min)", out)
        for noise in ("paseo-system", "task-notification", "Base directory", "subagent noise", "private"):
            self.assertNotIn(noise, out)

    def test_claude_user_only(self):
        path = write_jsonl(self.tmp / "c.jsonl", claude_events("/r"))
        out = self.run_script("render", str(path), "--user-only")
        self.assertIn("ok, działaj", out)
        self.assertNotIn("Reproducing first", out)
        self.assertNotIn("Bash(", out)

    def test_codex_render(self):
        path = write_jsonl(self.tmp / "rollout-x.jsonl", codex_events("/r"))
        out = self.run_script("render", str(path))
        self.assertIn("/retro why are e2e tests flaky", out)
        self.assertIn("## ASSISTANT\nLooking at sessions.", out)
        self.assertIn("linear.list_issues(flaky) -> ERROR: unauthorized", out)
        self.assertIn("- edit(/r/docs/a.md)", out)
        self.assertIn("- exec(bun test e2e) -> ERROR: Script failed Script error: 3 tests failed", out)
        self.assertIn("- exec_command(git status)\n", out)
        for covered in ("wait(", "apply_patch", "mcp__linear"):
            self.assertNotIn(covered, out)
        self.assertIn("!! [turn aborted: interrupted]", out)
        self.assertNotIn("AGENTS.md", out)
        self.assertNotIn("paseo-system", out)


class ListTests(unittest.TestCase):
    def test_lists_project_sessions_from_both_agents(self):
        tmp = Path(tempfile.mkdtemp()).resolve()
        project = tmp / "repo"
        project.mkdir()
        claude_root, codex_root = tmp / "claude", tmp / "codex"
        folder = claude_root / sessions.slug(str(project))
        folder.mkdir(parents=True)
        write_jsonl(folder / "a.jsonl", claude_events(str(project)))
        other = claude_root / sessions.slug(str(project) + "2")  # same slug prefix, different repo
        other.mkdir()
        write_jsonl(other / "b.jsonl", claude_events(str(project) + "2"))
        (codex_root / "2026").mkdir(parents=True)
        write_jsonl(codex_root / "2026" / "rollout-1.jsonl", codex_events(str(project / "sub")))
        write_jsonl(codex_root / "2026" / "rollout-2.jsonl", codex_events(str(project), subagent=True))
        # An archived Paseo worktree: gone from git and disk, known only to Paseo's workspace list.
        archived = tmp / "paseo" / "old_tree"
        folder = claude_root / (sessions.slug(str(tmp)) + "-paseo-old-tree")  # Claude Code's own name for it
        folder.mkdir()
        write_jsonl(folder / "c.jsonl", claude_events(str(archived)))
        workspaces = tmp / "workspaces.json"
        workspaces.write_text(json.dumps([
            {"cwd": str(archived), "mainRepoRoot": str(project), "archivedAt": "2026-10-01T12:00:00Z"},
            {"cwd": str(tmp / "paseo" / "elsewhere"), "mainRepoRoot": str(tmp / "other"), "archivedAt": None},
        ]), encoding="utf-8")

        sessions.CLAUDE_ROOT, sessions.CODEX_ROOTS, sessions.PASEO_WORKSPACES = claude_root, [codex_root], workspaces
        found = sessions.list_sessions(project, 86400, None, False)
        self.assertEqual(sorted(Path(m["path"]).name for m in found), ["a.jsonl", "c.jsonl", "rollout-1.jsonl"])
        self.assertEqual({m["first"] for m in found}, {"/dev:fix login breaks", "/retro why are e2e tests flaky"})
        with_sub = sessions.list_sessions(project, 86400, "codex", True)
        self.assertEqual(len(with_sub), 2)


if __name__ == "__main__":
    unittest.main()
