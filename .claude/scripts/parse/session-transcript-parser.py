#!/usr/bin/env python3
"""
Session Transcript Parser — extract structured data from Claude Code JSONL transcripts.

Handles both top-level session transcripts and nested agent_progress subagent messages.

Usage:
  python3 scripts/parse/session-transcript-parser.py SESSION_ID summary
  python3 scripts/parse/session-transcript-parser.py SESSION_ID tools
  python3 scripts/parse/session-transcript-parser.py SESSION_ID commands
  python3 scripts/parse/session-transcript-parser.py SESSION_ID results
  python3 scripts/parse/session-transcript-parser.py SESSION_ID text
  python3 scripts/parse/session-transcript-parser.py SESSION_ID dump --lines 58-67
  python3 scripts/parse/session-transcript-parser.py /path/to/file.jsonl commands
  python3 scripts/parse/session-transcript-parser.py SESSION_ID commands --json
"""

import argparse
import glob
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

PROJECTS_DIR = os.environ.get(
    "CLAUDE_PROJECTS_DIR",
    os.path.expanduser("~/.claude/projects"),
)


# --- Data structures ---

@dataclass
class ToolCall:
    line: int
    name: str
    tool_id: str
    input: dict
    caller: str  # "direct" or "agent"

@dataclass
class ToolResult:
    line: int
    tool_use_id: str
    content: str
    is_error: bool

@dataclass
class TextBlock:
    line: int
    role: str  # "user" or "assistant"
    text: str
    model: str = ""
    timestamp: str = ""

@dataclass
class SessionMeta:
    session_id: str = ""
    parent_uuid: str = ""
    agent_id: str = ""
    cwd: str = ""
    branch: str = ""
    version: str = ""
    model: str = ""
    start_time: str = ""
    end_time: str = ""
    error: str = ""
    is_subagent: bool = False


# --- File resolution ---

def resolve_jsonl(target: str) -> str:
    """Resolve a session ID or path to a JSONL file path."""
    if os.path.isfile(target):
        return target

    # Search projects dir for session ID
    for root, dirs, files in os.walk(PROJECTS_DIR):
        for f in files:
            if f == f"{target}.jsonl":
                return os.path.join(root, f)
        # Also check subagents/
        sub = os.path.join(root, target, "subagents")
        if os.path.isdir(sub):
            for sf in os.listdir(sub):
                if sf.endswith(".jsonl"):
                    return os.path.join(sub, sf)

    # Try glob pattern
    matches = glob.glob(os.path.join(PROJECTS_DIR, "**", f"{target}.jsonl"), recursive=True)
    if matches:
        return matches[0]

    print(f"Could not find transcript for: {target}", file=sys.stderr)
    sys.exit(1)


def find_subagent_files(session_id: str) -> list[str]:
    """Find all subagent JSONL files for a session."""
    results = []
    for root, dirs, files in os.walk(PROJECTS_DIR):
        sub_dir = os.path.join(root, session_id, "subagents")
        if os.path.isdir(sub_dir):
            for f in sorted(os.listdir(sub_dir)):
                if f.endswith(".jsonl"):
                    results.append(os.path.join(sub_dir, f))
    return results


# --- Parsing ---

def extract_from_content(content: list, line_num: int) -> tuple[list[ToolCall], list[TextBlock]]:
    """Extract tool calls and text blocks from a content array."""
    tools = []
    texts = []
    if not isinstance(content, list):
        return tools, texts

    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_use":
            tools.append(ToolCall(
                line=line_num,
                name=block.get("name", ""),
                tool_id=block.get("id", ""),
                input=block.get("input", {}),
                caller=block.get("caller", {}).get("type", "unknown"),
            ))
        elif block.get("type") == "text" and block.get("text", "").strip():
            texts.append(TextBlock(
                line=line_num,
                role="assistant",
                text=block["text"].strip(),
            ))
        elif block.get("type") == "tool_result":
            pass  # handled separately
    return tools, texts


def _handle_assistant_msg(msg: dict, line_num: int, meta: "SessionMeta") -> tuple[list, list]:
    """Extract tool calls and text blocks from an assistant message."""
    model = msg.get("model", "")
    if model and not meta.model:
        meta.model = model
    tc, tb = extract_from_content(msg.get("content", []), line_num)
    for t in tb:
        t.model = model
    return tc, tb


def _handle_user_msg(msg: dict, line_num: int) -> tuple[list[ToolResult], list[TextBlock]]:
    """Extract tool results and text blocks from a user message."""
    tool_results: list[ToolResult] = []
    text_blocks: list[TextBlock] = []
    content = msg.get("content", "")
    if isinstance(content, str) and content.strip():
        text_blocks.append(TextBlock(line=line_num, role="user", text=content.strip()))
    elif isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result":
                tool_results.append(ToolResult(
                    line=line_num,
                    tool_use_id=block.get("tool_use_id", ""),
                    content=str(block.get("content", "")),
                    is_error=block.get("is_error", False),
                ))
            elif block.get("type") == "text" and block.get("text", "").strip():
                text_blocks.append(TextBlock(line=line_num, role="user", text=block["text"].strip()))
    return tool_results, text_blocks


def _handle_progress_msg(obj: dict, line_num: int, meta: "SessionMeta") -> tuple[list, list[ToolResult], list]:
    """Extract tool calls, tool results, and text blocks from an agent_progress message."""
    tool_calls: list = []
    tool_results: list[ToolResult] = []
    text_blocks: list = []
    data = obj.get("data", {})
    if data.get("type") != "agent_progress":
        return tool_calls, tool_results, text_blocks
    inner_msg = data.get("message", {})
    inner_inner = inner_msg.get("message", {})
    model = inner_inner.get("model", "")
    if model and not meta.model:
        meta.model = model
    tc, tb = extract_from_content(inner_inner.get("content", []), line_num)
    for t in tb:
        t.model = model
    tool_calls.extend(tc)
    text_blocks.extend(tb)
    # Also extract tool results from user messages inside agent_progress
    if inner_msg.get("type") == "user":
        ucontent = inner_inner.get("content", inner_msg.get("message", {}).get("content", []))
        if isinstance(ucontent, list):
            for block in ucontent:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tool_results.append(ToolResult(
                        line=line_num,
                        tool_use_id=block.get("tool_use_id", ""),
                        content=str(block.get("content", "")),
                        is_error=block.get("is_error", False),
                    ))
    return tool_calls, tool_results, text_blocks


def parse_transcript(path: str) -> dict:
    """Parse a session JSONL file into structured data."""
    meta = SessionMeta()
    tool_calls: list[ToolCall] = []
    tool_results: list[ToolResult] = []
    text_blocks: list[TextBlock] = []
    raw_lines: list[tuple[int, dict]] = []

    with open(path) as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            raw_lines.append((i, obj))
            msg_type = obj.get("type", "")

            # Extract metadata from first relevant entry
            if not meta.session_id:
                meta.session_id = obj.get("sessionId", "")
                meta.cwd = obj.get("cwd", "")
                meta.branch = obj.get("gitBranch", "")
                meta.version = obj.get("version", "")
                meta.parent_uuid = obj.get("parentUuid", "")
                meta.agent_id = obj.get("agentId", "")
                if meta.agent_id:
                    meta.is_subagent = True

            # Track timestamps
            ts = obj.get("timestamp", "")
            if ts:
                if not meta.start_time:
                    meta.start_time = ts
                meta.end_time = ts

            if obj.get("error"):
                meta.error = obj["error"]
            if obj.get("isApiErrorMessage"):
                meta.error = obj.get("error", meta.error)

            msg = obj.get("message", {})

            # --- Direct assistant messages (top-level sessions) ---
            if msg_type == "assistant":
                tc, tb = _handle_assistant_msg(msg, i, meta)
                tool_calls.extend(tc)
                text_blocks.extend(tb)

            # --- Direct user messages ---
            elif msg_type == "user" and not obj.get("isMeta"):
                tr, tb = _handle_user_msg(msg, i)
                tool_results.extend(tr)
                text_blocks.extend(tb)

            # --- Nested agent_progress messages (subagent transcripts in parent) ---
            elif msg_type == "progress":
                tc, tr, tb = _handle_progress_msg(obj, i, meta)
                tool_calls.extend(tc)
                tool_results.extend(tr)
                text_blocks.extend(tb)

    return {
        "meta": meta,
        "tool_calls": tool_calls,
        "tool_results": tool_results,
        "text_blocks": text_blocks,
        "raw_lines": raw_lines,
    }


# --- Subcommands ---

def cmd_summary(data: dict, as_json: bool):
    """Print session metadata summary."""
    m = data["meta"]
    tc = data["tool_calls"]
    tr = data["tool_results"]
    tb = data["text_blocks"]

    tool_names = {}
    for t in tc:
        tool_names[t.name] = tool_names.get(t.name, 0) + 1

    errors = sum(1 for r in tr if r.is_error)

    info = {
        "session_id": m.session_id,
        "agent_id": m.agent_id,
        "is_subagent": m.is_subagent,
        "model": m.model,
        "cwd": m.cwd,
        "branch": m.branch,
        "version": m.version,
        "start_time": m.start_time,
        "end_time": m.end_time,
        "error": m.error,
        "total_lines": len(data["raw_lines"]),
        "tool_calls": len(tc),
        "tool_results": len(tr),
        "tool_errors": errors,
        "text_blocks": len(tb),
        "tool_breakdown": tool_names,
        "user_messages": [t.text[:200] for t in tb if t.role == "user"],
    }

    if as_json:
        json.dump(info, sys.stdout, indent=2)
        print()
    else:
        print(f"\nSession: {info['session_id']}")
        if info["agent_id"]:
            print(f"Agent:   {info['agent_id']} (subagent)")
        print(f"Model:   {info['model']}")
        print(f"CWD:     {info['cwd']}")
        print(f"Branch:  {info['branch']}")
        print(f"Time:    {info['start_time']} -> {info['end_time']}")
        if info["error"]:
            print(f"Error:   {info['error']}")
        print(f"Lines:   {info['total_lines']}")
        print(f"\nTool calls: {info['tool_calls']}  |  Results: {info['tool_results']}  |  Errors: {info['tool_errors']}  |  Text: {info['text_blocks']}")
        print("\nTool breakdown:")
        for name, count in sorted(info["tool_breakdown"].items(), key=lambda x: -x[1]):
            print(f"  {name}: {count}")
        if info["user_messages"]:
            print("\nUser messages:")
            for msg in info["user_messages"]:
                print(f"  {msg}")
        print()


def cmd_tools(data: dict, as_json: bool):
    """List all tool calls with descriptions."""
    tc = data["tool_calls"]
    if as_json:
        items = []
        for t in tc:
            items.append({
                "line": t.line,
                "name": t.name,
                "id": t.tool_id,
                "description": t.input.get("description", ""),
                "caller": t.caller,
            })
        json.dump(items, sys.stdout, indent=2)
        print()
    else:
        for idx, t in enumerate(tc, 1):
            desc = t.input.get("description", "")
            print(f"  [{idx}] line {t.line}  {t.name}  {f'— {desc}' if desc else ''}")


def cmd_commands(data: dict, as_json: bool):
    """Extract all Bash commands."""
    bash_calls = [t for t in data["tool_calls"] if t.name == "Bash"]
    if as_json:
        items = []
        for t in bash_calls:
            items.append({
                "line": t.line,
                "command": t.input.get("command", ""),
                "description": t.input.get("description", ""),
            })
        json.dump(items, sys.stdout, indent=2)
        print()
    else:
        for idx, t in enumerate(bash_calls, 1):
            desc = t.input.get("description", "")
            cmd = t.input.get("command", "")
            print(f"\n### Command {idx} (line {t.line}) — {desc}")
            print(cmd)


def cmd_results(data: dict, as_json: bool):
    """Extract all tool results."""
    tr = data["tool_results"]
    if as_json:
        items = []
        for r in tr:
            items.append({
                "line": r.line,
                "tool_use_id": r.tool_use_id,
                "is_error": r.is_error,
                "content": r.content[:2000],
            })
        json.dump(items, sys.stdout, indent=2)
        print()
    else:
        for idx, r in enumerate(tr, 1):
            status = "ERROR" if r.is_error else "OK"
            print(f"\n--- Result {idx} (line {r.line}) [{status}] id={r.tool_use_id}")
            # Truncate long results for display
            content = r.content
            if len(content) > 1000:
                content = content[:1000] + f"\n... ({len(r.content)} chars total)"
            print(content)


def cmd_text(data: dict, as_json: bool):
    """Extract all text blocks (user messages and assistant responses)."""
    tb = data["text_blocks"]
    if as_json:
        items = []
        for t in tb:
            items.append({
                "line": t.line,
                "role": t.role,
                "model": t.model,
                "text": t.text,
            })
        json.dump(items, sys.stdout, indent=2)
        print()
    else:
        for t in tb:
            role_label = "USER" if t.role == "user" else "ASSISTANT"
            print(f"\n[{role_label}] line {t.line}")
            print(t.text)


def cmd_dump(data: dict, line_range: str, as_json: bool):
    """Dump raw JSON for specific line range."""
    raw = data["raw_lines"]

    start, end = 1, len(raw)
    if line_range:
        parts = line_range.split("-")
        start = int(parts[0])
        end = int(parts[1]) if len(parts) > 1 else start

    for line_num, obj in raw:
        if start <= line_num <= end:
            if as_json:
                print(json.dumps(obj, indent=2))
            else:
                print(f"\n--- Line {line_num} (type={obj.get('type', '?')})")
                print(json.dumps(obj, indent=2)[:3000])


def cmd_paired(data: dict, as_json: bool):
    """Show tool calls paired with their results."""
    tc_by_id = {}
    for t in data["tool_calls"]:
        tc_by_id[t.tool_id] = t

    pairs = []
    for r in data["tool_results"]:
        call = tc_by_id.get(r.tool_use_id)
        pairs.append({
            "tool_use_id": r.tool_use_id,
            "call": {
                "line": call.line,
                "name": call.name,
                "description": call.input.get("description", ""),
                "command": call.input.get("command", "") if call.name == "Bash" else "",
            } if call else None,
            "result": {
                "line": r.line,
                "is_error": r.is_error,
                "content": r.content[:1000],
            },
        })

    if as_json:
        json.dump(pairs, sys.stdout, indent=2)
        print()
    else:
        for idx, p in enumerate(pairs, 1):
            call = p["call"]
            res = p["result"]
            if call:
                print(f"\n[{idx}] {call['name']} (line {call['line']}) — {call['description']}")
                if call["command"]:
                    lines = call["command"].split("\n")
                    for cl in lines[:3]:
                        print(f"  $ {cl}")
                    if len(lines) > 3:
                        print(f"  ... ({len(lines)} lines)")
            else:
                print(f"\n[{idx}] (call not found) id={p['tool_use_id']}")

            status = "ERROR" if res["is_error"] else "OK"
            content = res["content"]
            if len(content) > 500:
                content = content[:500] + "..."
            print(f"  -> [{status}] {content}")


def main():
    parser = argparse.ArgumentParser(
        description="Parse Claude Code session JSONL transcripts",
    )
    parser.add_argument("target", help="Session ID or path to .jsonl file")
    parser.add_argument(
        "command",
        choices=["summary", "tools", "commands", "results", "text", "dump", "paired"],
        help="What to extract",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--lines", help="Line range for dump (e.g. 58-67)")
    parser.add_argument("--include-subagents", action="store_true", help="Also parse subagent files")
    parser.add_argument(
        "--projects-dir",
        default=PROJECTS_DIR,
        help=f"Projects directory (default: {PROJECTS_DIR})",
    )
    args = parser.parse_args()

    path = resolve_jsonl(args.target)
    data = parse_transcript(path)

    # Optionally merge subagent data
    if args.include_subagents:
        sid = data["meta"].session_id
        for sub_path in find_subagent_files(sid):
            sub_data = parse_transcript(sub_path)
            agent_id = sub_data["meta"].agent_id or Path(sub_path).stem
            # Prefix tool calls with agent context
            for tc in sub_data["tool_calls"]:
                tc.caller = f"subagent:{agent_id}"
            data["tool_calls"].extend(sub_data["tool_calls"])
            data["tool_results"].extend(sub_data["tool_results"])
            data["text_blocks"].extend(sub_data["text_blocks"])

    dispatch = {
        "summary": lambda: cmd_summary(data, args.json),
        "tools": lambda: cmd_tools(data, args.json),
        "commands": lambda: cmd_commands(data, args.json),
        "results": lambda: cmd_results(data, args.json),
        "text": lambda: cmd_text(data, args.json),
        "dump": lambda: cmd_dump(data, args.lines, args.json),
        "paired": lambda: cmd_paired(data, args.json),
    }
    dispatch[args.command]()


if __name__ == "__main__":
    main()
