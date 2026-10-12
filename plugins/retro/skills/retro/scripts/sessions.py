#!/usr/bin/env python3
"""List and render agent session transcripts (Claude Code and Codex) for one project.

A raw transcript is hundreds of KB of JSONL, most of it tool output and injected context. This
turns it into what a retrospective reads: the user's own turns, the assistant's prose, one line per
tool call (with the error when it failed), and the points where a turn was interrupted.

    sessions.py list   --project DIR [--since 14d] [--agent claude|codex] [--subagents]
    sessions.py render FILE [--user-only] [--max-error-chars N]

`list` matches sessions by working directory: the project, every live worktree of it, the folders
those worktrees live in, and every Paseo workspace of the repo, archived ones included (so an
archived Paseo or Conductor worktree of the same repo still counts). Stdlib only; run with
`python3 -I`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

CLAUDE_ROOT = Path.home() / ".claude" / "projects"
CODEX_ROOTS = [Path.home() / ".codex" / "sessions", Path.home() / ".codex" / "archived_sessions"]
PASEO_WORKSPACES = Path.home() / ".paseo" / "projects" / "workspaces.json"

# Tool results that carry the human's words: answers to questions, a rejected plan or tool call.
USER_VOICE = ("Your questions have been answered", "The user answered", "The user doesn't want to proceed")

# User-role messages that the harness injected rather than the human typed.
INJECTED = ("<task-notification", "<paseo-system>", "<system-reminder>", "<local-command-", "Caveat: ", "<chat-history-summary")


def read_jsonl(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                yield event


def text_of(value: object) -> str:
    """Flatten the nested content shapes both agents use into plain text."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(t for t in (text_of(item) for item in value) if t)
    if isinstance(value, dict):
        for key in ("text", "content", "output", "message"):
            if key in value:
                return text_of(value[key])
    return ""


def clip(value: str, limit: int) -> str:
    """Keep the head and the tail; the tail is where errors and test summaries sit."""
    value = value.strip()
    if len(value) <= limit:
        return value
    head = limit * 2 // 3
    return f"{value[:head]} …[{len(value) - limit} chars]… {value[-(limit - head):]}"


def one_line(value: str, limit: int) -> str:
    return clip(re.sub(r"\s+", " ", value), limit)


# --- what the human typed -------------------------------------------------------------------

def classify_user_text(text: str) -> tuple[str, str] | None:
    """Return ("user"|"command"|"interrupt", text), or None for injected context."""
    # Conductor prepends its instructions to the prompt in the same text, so cut them out rather than drop it.
    stripped = re.sub(r"<system_instruction>.*?</system_instruction>", "", text, flags=re.S).strip()
    if not stripped:
        return None
    if stripped.startswith("[Request interrupted"):
        return "interrupt", stripped
    command = re.search(r"<command-name>(/?[^<]+)</command-name>", stripped)
    if command:
        args = re.search(r"<command-args>(.*?)</command-args>", stripped, re.S)
        name = command.group(1)
        return "command", f"{name if name.startswith('/') else '/' + name} {args.group(1).strip() if args else ''}".strip()
    if stripped.startswith(INJECTED) or stripped.startswith("<command-message>"):
        return None
    return "user", stripped


# --- Claude Code ----------------------------------------------------------------------------

def claude_meta(path: Path) -> dict:
    meta: dict = {"agent": "claude", "path": str(path)}
    for event in read_jsonl(path):
        if "cwd" in meta and "first" in meta:
            break
        if event.get("cwd") and "cwd" not in meta:
            meta["cwd"] = event["cwd"]
            meta["start"] = event.get("timestamp")
            meta["branch"] = event.get("gitBranch")
        if event.get("type") == "user" and "first" not in meta and not event.get("isMeta") and not event.get("isSidechain"):
            for kind, text in claude_user_turns(event):
                if kind in ("user", "command"):
                    meta["first"] = text
                    break
    return meta


def claude_user_turns(event: dict) -> Iterator[tuple[str, str]]:
    content = (event.get("message") or {}).get("content")
    origin = event.get("turnOrigin")
    if event.get("isCompactSummary") or isinstance(origin, dict) and origin.get("kind") == "task_notification":
        return
    blocks = [content] if isinstance(content, str) else [b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text"]
    for block in blocks:
        turn = classify_user_text(block)
        if turn:
            yield turn


def render_claude(path: Path, user_only: bool, max_error: int) -> list[str]:
    events = list(read_jsonl(path))
    results = {}
    for event in events:
        if event.get("type") == "user":
            for block in (event.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    results[block.get("tool_use_id")] = block

    first = next((e for e in events if e.get("cwd")), {})
    out = header("claude", path, first, [e.get("timestamp") for e in events])
    for event in events:
        if event.get("isSidechain") or event.get("isMeta"):
            continue
        if event.get("type") == "user":
            for kind, text in claude_user_turns(event):
                out.append(turn_line(kind, text))
        elif event.get("type") == "attachment" and (event.get("attachment") or {}).get("type") == "queued_command":
            # Typed while the agent was busy: delivered as an attachment, not as a user turn.
            turn = classify_user_text(text_of((event["attachment"]).get("prompt")))
            if turn:
                out.append(turn_line(*turn))
        elif event.get("type") == "assistant":
            for block in (event.get("message") or {}).get("content") or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and block.get("text", "").strip() and not user_only:
                    out.append(f"## ASSISTANT\n{block['text'].strip()}\n")
                elif block.get("type") == "tool_use":
                    result = results.get(block.get("id")) or {}
                    result_text = text_of(result.get("content")).strip()
                    if result_text.startswith("User has approved your plan"):
                        out.append("## USER (approved the plan)\n")
                        continue
                    if result_text.startswith(USER_VOICE):
                        out.append(f"## USER (answering {block.get('name')})\n{clip(result_text, 3000)}\n")
                        continue
                    if user_only:
                        continue
                    error = result_text if result.get("is_error") else None
                    out.append(tool_line(block.get("name", "?"), block.get("input"), error, max_error))
    return out


# --- Codex ----------------------------------------------------------------------------------

def codex_meta(path: Path) -> dict | None:
    with path.open(encoding="utf-8", errors="replace") as handle:
        try:
            first = json.loads(handle.readline())
        except json.JSONDecodeError:
            return None
    payload = first.get("payload") or {}
    if first.get("type") != "session_meta":
        return None
    meta = {
        "agent": "codex",
        "path": str(path),
        "cwd": payload.get("cwd"),
        "start": payload.get("timestamp"),
        "branch": (payload.get("git") or {}).get("branch"),
        "subagent": payload.get("thread_source") == "subagent",
    }
    for kind, text in codex_turns(path, user_only=True):
        if kind in ("user", "command"):
            meta["first"] = text
            break
    return meta


def codex_turns(path: Path, user_only: bool) -> Iterator[tuple[str, str]]:
    """Codex logs each finished item as event_msg/item_completed; older rollouts only as response_item.

    Shell calls never become items, so tool calls always come from response_item, paired with their
    output by call_id; where items exist, the calls they already render are skipped."""
    outputs: dict | None = None
    itemised = False
    has_items = False
    fallback: list[tuple[str, str]] = []
    for event in read_jsonl(path):
        payload = event.get("payload") or {}
        if event.get("type") == "event_msg" and payload.get("type") == "item_completed":
            has_items = True
            item = payload.get("item") or {}
            kind = item.get("type")
            if kind == "UserMessage":
                turn = classify_user_text(text_of(item.get("content")))
                if turn:
                    yield turn
            elif user_only:
                continue
            elif kind == "AgentMessage":
                yield "assistant", text_of(item.get("content"))
            elif kind == "McpToolCall":
                failed = item.get("status") != "completed" or bool(item.get("error"))
                yield "tool", json.dumps([f"{item.get('server')}.{item.get('tool')}", item.get("arguments"), text_of(item.get("error") or item.get("result")) if failed else None])
            elif kind == "FileChange":
                yield "tool", json.dumps(["edit", list((item.get("changes") or {}).keys()), None])
            elif kind not in ("ContextCompaction", "Reasoning"):
                yield "tool", json.dumps([kind, None, None])
        elif event.get("type") == "event_msg" and payload.get("type") == "turn_aborted":
            yield "interrupt", f"[turn aborted: {payload.get('reason')}]"
        elif event.get("type") == "response_item" and payload.get("type") in ("function_call", "custom_tool_call"):
            if outputs is None:
                # Read on the first call, so codex_meta, which stops at the first prompt, never pays for it.
                outputs, itemised = codex_outputs(path)
            output = outputs.get(payload.get("call_id"))
            if payload.get("name") == "request_user_input" and output:
                # No item covers it, and the human's answers live only in the call's output.
                turn = "answer", codex_answers(output)
            elif user_only or (itemised and codex_call_has_item(payload)):
                continue
            else:
                call = codex_call(payload, output)
                if not call:
                    continue
                turn = "tool", json.dumps(call)
            if itemised:
                yield turn
            else:
                fallback.append(turn)
        elif not has_items and event.get("type") == "response_item":
            if payload.get("type") == "message" and payload.get("role") == "user":
                turn = classify_user_text(text_of(payload.get("content")))
                if turn and not turn[1].startswith(("# AGENTS.md", "<environment_context>", "<user_instructions>", "<permissions")):
                    fallback.append(turn)
            elif payload.get("type") == "message" and payload.get("role") == "assistant" and not user_only:
                fallback.append(("assistant", text_of(payload.get("content"))))
    if not has_items:
        yield from fallback


def codex_call_has_item(payload: dict) -> bool:
    """FileChange renders apply_patch, McpToolCall the MCP tools, Plan update_plan, SubAgentActivity the agents."""
    if (payload.get("namespace") or "").startswith(("mcp__", "collaboration")):
        return True
    # An exec cell is JavaScript that calls tools; it is covered only when every tool it calls is.
    names = re.findall(r"tools\.(\w+)", payload.get("input") or "") if payload.get("name") == "exec" else [payload.get("name") or ""]
    return bool(names) and all(n in ("apply_patch", "update_plan") or n.startswith("mcp__") for n in names)


def codex_outputs(path: Path) -> tuple[dict, bool]:
    """Tool outputs by call_id, and whether the rollout logs items at all."""
    outputs, itemised = {}, False
    for event in read_jsonl(path):
        payload = event.get("payload") or {}
        itemised = itemised or payload.get("type") == "item_completed"
        if payload.get("type") in ("function_call_output", "custom_tool_call_output"):
            outputs[payload.get("call_id")] = payload.get("output")
    return outputs, itemised


def codex_answers(output: object) -> str:
    """`{"answers": {id: {"answers": [...]}}}` as one `id: answer` line per question."""
    text = text_of(output)
    try:
        answers = json.loads(text)["answers"]
        return "\n".join(f"{qid}: {'; '.join(map(str, (a or {}).get('answers') or []))}" for qid, a in answers.items())
    except (ValueError, KeyError, TypeError, AttributeError):
        return text


def codex_call(payload: dict, output: object) -> list | None:
    """[name, args, error] for one tool call; None for a poll of a running exec cell that did not fail."""
    name, args = payload.get("name"), payload.get("arguments") or payload.get("input")
    text = text_of(output)
    failed = text.startswith(("Script failed", "aborted by user")) or re.search(r"^(Process exited with code|Exit code:) [1-9]", text, re.M)
    if name == "exec" and isinstance(args, str):
        # Show the shell commands the cell ran rather than its JavaScript.
        commands = [m.group(2) for m in re.finditer(r'cmd"?\s*:\s*(["`])((?:\\.|(?!\1).)*)\1', args)]
        args = "; ".join(commands) or args
    if name == "wait" and not failed:
        return None
    return [name, args, text if failed else None]


def render_codex(path: Path, user_only: bool, max_error: int) -> list[str]:
    first = next(read_jsonl(path), {})
    payload = first.get("payload") or {}
    timestamps = [payload.get("timestamp")] + [e.get("timestamp") for e in read_jsonl(path)]
    out = header("codex", path, {"cwd": payload.get("cwd"), "gitBranch": (payload.get("git") or {}).get("branch")}, timestamps)
    if payload.get("thread_source") == "subagent":
        out.insert(1, f"subagent: {payload.get('agent_path')}")
    for kind, text in codex_turns(path, user_only):
        if kind == "assistant":
            if text.strip():
                out.append(f"## ASSISTANT\n{text.strip()}\n")
        elif kind == "tool":
            name, args, error = json.loads(text)
            out.append(tool_line(name, args, error, max_error))
        else:
            out.append(turn_line(kind, text))
    return out


# --- shared rendering -----------------------------------------------------------------------

def header(agent: str, path: Path, first: dict, timestamps: list) -> list[str]:
    stamps = sorted(t for t in timestamps if isinstance(t, str))
    lines = [f"# {agent} session {path.stem}", f"cwd: {first.get('cwd')}"]
    if first.get("gitBranch"):
        lines.append(f"branch: {first['gitBranch']}")
    if stamps:
        start, end = parse_time(stamps[0]), parse_time(stamps[-1])
        span = f" ({int((end - start).total_seconds() // 60)} min)" if start and end else ""
        lines.append(f"time: {stamps[0]} → {stamps[-1]}{span}")
    lines.append("")
    return lines


def turn_line(kind: str, text: str) -> str:
    if kind == "interrupt":
        return f"!! {text}\n"
    if kind == "answer":
        return f"## USER (answering request_user_input)\n{text}\n"
    return f"## USER\n{text}\n"


def tool_line(name: str, args: object, error: str | None, max_error: int) -> str:
    summary = summarise_args(args)
    line = f"- {name}({summary})"
    if error:
        line += f" -> ERROR: {one_line(error, max_error)}"
    return line


def summarise_args(args: object) -> str:
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return one_line(args, 140)
    if isinstance(args, dict):
        for key in ("command", "cmd", "file_path", "path", "pattern", "url", "query", "skill", "description"):
            if args.get(key):
                return one_line(str(args[key]), 140)
        return one_line(", ".join(sorted(args)), 140)
    if isinstance(args, list):
        return one_line(" ".join(map(str, args)), 140)
    return ""


def parse_time(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


# --- which sessions belong to the project ---------------------------------------------------

def project_prefixes(project: Path) -> list[str]:
    project = project.resolve()
    prefixes = {str(project)}
    try:
        listing = subprocess.run(["git", "-C", str(project), "worktree", "list", "--porcelain"],
                                 capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        listing = ""
    main = None
    for line in listing.splitlines():
        if line.startswith("worktree "):
            tree = Path(line[len("worktree "):]).resolve()
            main = main or tree
            prefixes.add(str(tree))
            # Worktree managers keep one folder per repo; an archived worktree of this repo lived there too.
            if tree != main and tree.parent != main.parent:
                prefixes.add(str(tree.parent))
    # Archiving removes a Paseo worktree from git and disk, but Paseo's workspace list keeps it.
    main = main or project
    try:
        workspaces = json.loads(PASEO_WORKSPACES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        workspaces = []
    for entry in workspaces if isinstance(workspaces, list) else []:
        if isinstance(entry, dict) and entry.get("cwd") and entry.get("mainRepoRoot") and Path(entry["mainRepoRoot"]).resolve() == main:
            prefixes.add(str(Path(entry["cwd"]).resolve()))
    return sorted(prefixes)


def under(cwd: str | None, prefixes: list[str]) -> bool:
    if not cwd:
        return False
    cwd = os.path.realpath(cwd)
    return any(cwd == p or cwd.startswith(p.rstrip("/") + "/") for p in prefixes)


def slug(path: str) -> str:
    """Claude Code's project folder name: every character but a letter or digit becomes '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def list_sessions(project: Path, since_s: float, agent: str | None, subagents: bool) -> list[dict]:
    prefixes = project_prefixes(project)
    # /private/tmp style aliases: compare against both the given and the resolved form.
    prefixes += [p for p in {str(project.absolute())} if p not in prefixes]
    cutoff = time.time() - since_s
    found = []
    if agent in (None, "claude") and CLAUDE_ROOT.is_dir():
        slugs = [slug(p) for p in prefixes]
        for folder in CLAUDE_ROOT.iterdir():
            if not any(folder.name.startswith(s) for s in slugs):
                continue
            for path in folder.glob("*.jsonl"):
                if path.stat().st_mtime < cutoff:
                    continue
                meta = claude_meta(path)
                if under(meta.get("cwd"), prefixes):
                    found.append(meta)
    if agent in (None, "codex"):
        for root in CODEX_ROOTS:
            if not root.is_dir():
                continue
            for path in root.rglob("rollout-*.jsonl"):
                if path.stat().st_mtime < cutoff:
                    continue
                meta = codex_meta(path)
                if meta and (subagents or not meta["subagent"]) and under(meta.get("cwd"), prefixes):
                    found.append(meta)
    for meta in found:
        meta["kb"] = Path(meta["path"]).stat().st_size // 1024
    return sorted(found, key=lambda m: m.get("start") or "", reverse=True)


def parse_since(value: str) -> float:
    match = re.fullmatch(r"(\d+)([hdw])", value)
    if not match:
        raise argparse.ArgumentTypeError("use e.g. 12h, 14d or 2w")
    return int(match.group(1)) * {"h": 3600, "d": 86400, "w": 604800}[match.group(2)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    ls = sub.add_parser("list", help="sessions of one project, newest first")
    ls.add_argument("--project", default=".", type=Path)
    ls.add_argument("--since", default="14d", type=parse_since)
    ls.add_argument("--agent", choices=["claude", "codex"])
    ls.add_argument("--subagents", action="store_true", help="include Codex subagent threads")
    rd = sub.add_parser("render", help="one transcript as a compact narrative")
    rd.add_argument("file", type=Path)
    rd.add_argument("--user-only", action="store_true", help="only the human's turns and interruptions")
    rd.add_argument("--max-error-chars", type=int, default=400)
    args = parser.parse_args()

    if args.command == "list":
        sessions = list_sessions(args.project, args.since, args.agent, args.subagents)
        for meta in sessions:
            when = (meta.get("start") or "?")[:16].replace("T", " ")
            print(f"{when}  {meta['agent']:<6} {meta['kb']:>6} KB  {meta['path']}")
            print(f"    {meta.get('branch') or '-'} | {one_line(meta.get('first') or '(no user prompt)', 120)}")
        print(f"{len(sessions)} sessions", file=sys.stderr)
        return 0

    path = args.file
    if not path.is_file():
        parser.error(f"no such file: {path}")
    first = next(read_jsonl(path), {})
    agent = "codex" if first.get("type") == "session_meta" else "claude"
    render = render_codex if agent == "codex" else render_claude
    sys.stdout.write("\n".join(render(path, args.user_only, args.max_error_chars)).rstrip() + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
