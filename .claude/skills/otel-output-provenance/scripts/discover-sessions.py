#!/usr/bin/env python3
"""Discover all Claude Code sessions that contributed to creating a given output.

Usage:
  discover-sessions.py <file-path> [--commit <hash>] [--search "<term>"]
  discover-sessions.py --commit <hash>
  discover-sessions.py --search "<term>"

Output: JSON with discovered sessions, roles, time ranges, and match evidence.
"""

import argparse
import json
import glob
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta

TELEMETRY_DIR = os.path.expanduser(os.environ.get("CLAUDE_TELEMETRY_DIR", "~/.claude-history/telemetry"))
EST = timezone(timedelta(hours=-5))


def git_log_for_file(file_path):
    """Get commits that touched a file."""
    try:
        result = subprocess.run(
            ["git", "log", "--all", "--format=%H %aI %s", "--", file_path],
            capture_output=True, text=True, timeout=10
        )
        commits = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split(" ", 2)
            if len(parts) >= 3:
                commits.append({
                    "hash": parts[0],
                    "date": parts[1],
                    "message": parts[2],
                    "date_key": parts[1][:10],
                })
        return commits
    except Exception:
        return []


def git_show_files(commit_hash):
    """Get files changed in a commit."""
    try:
        result = subprocess.run(
            ["git", "show", "--stat", "--format=", commit_hash],
            capture_output=True, text=True, timeout=10
        )
        files = []
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if "|" in line:
                files.append(line.split("|")[0].strip())
        return files
    except Exception:
        return []


def extract_references(file_path):
    """Extract referenced files from markdown content."""
    refs = []
    try:
        with open(file_path) as f:
            content = f.read()
        # Markdown links to local files
        for match in re.finditer(r'\[.*?\]\((\.\.?/[^)]+\.md)\)', content):
            ref_path = os.path.normpath(os.path.join(os.path.dirname(file_path), match.group(1)))
            if os.path.exists(ref_path):
                refs.append(ref_path)
        # Source: headers
        for match in re.finditer(r'\*\*Source.*?\*\*:.*?\[.*?\]\((\.\.?/[^)]+)\)', content):
            ref_path = os.path.normpath(os.path.join(os.path.dirname(file_path), match.group(1)))
            if os.path.exists(ref_path):
                refs.append(ref_path)
    except Exception:
        pass
    return list(set(refs))


def derive_search_terms(file_path, commit_messages):
    """Derive search terms from file path and commit messages."""
    terms = set()
    # Stem from filename
    stem = os.path.splitext(os.path.basename(file_path))[0]
    terms.add(stem)
    # Split on hyphens for individual keywords
    for part in stem.split("-"):
        if len(part) > 3:
            terms.add(part)
    # Parent directory name
    parent = os.path.basename(os.path.dirname(file_path))
    if parent and parent != ".":
        terms.add(parent)
    # Key terms from commit messages
    stop_words = {"the", "and", "for", "with", "from", "this", "that", "add", "update", "fix", "docs"}
    for msg in commit_messages:
        for word in re.findall(r'[a-zA-Z]{4,}', msg):
            if word.lower() not in stop_words:
                terms.add(word.lower())
    return terms


def scan_traces_for_sessions(date_keys, search_terms, time_windows=None):
    """Scan trace JSONL files for matching sessions."""
    sessions = {}

    for date_key in date_keys:
        # Also check the next day (sessions spanning midnight)
        dates_to_check = [date_key]
        try:
            d = datetime.strptime(date_key, "%Y-%m-%d")
            dates_to_check.append((d + timedelta(days=1)).strftime("%Y-%m-%d"))
        except ValueError:
            pass

        for check_date in dates_to_check:
            trace_file = os.path.join(TELEMETRY_DIR, f"traces-{check_date}.jsonl")
            if not os.path.exists(trace_file):
                continue

            with open(trace_file) as f:
                for line in f:
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    attrs = obj.get("attributes", {})
                    sid = attrs.get("session.id", "")
                    if not sid:
                        continue

                    # Initialize session record
                    if sid not in sessions:
                        sessions[sid] = {
                            "session_id": sid,
                            "spans": 0,
                            "min_epoch": float("inf"),
                            "max_epoch": 0,
                            "tools": defaultdict(int),
                            "agent_descriptions": set(),
                            "match_evidence": [],
                            "match_score": 0,
                            "source_file": check_date,
                        }

                    s = sessions[sid]
                    s["spans"] += 1

                    # Track time range
                    start = obj.get("startTime", [0, 0])
                    epoch = start[0] if isinstance(start, list) else 0
                    if epoch > 0:
                        s["min_epoch"] = min(s["min_epoch"], epoch)
                        s["max_epoch"] = max(s["max_epoch"], epoch)

                    # Track tools
                    tool = attrs.get("builtin.tool", "")
                    if tool:
                        s["tools"][tool] += 1

                    # Track agent descriptions
                    desc = attrs.get("agent.description", "")
                    if desc:
                        s["agent_descriptions"].add(desc)

                    # Score by search term matches
                    line_lower = line.lower()
                    for term in search_terms:
                        if term.lower() in line_lower:
                            if term not in [e.get("term") for e in s["match_evidence"]]:
                                s["match_evidence"].append({
                                    "term": term,
                                    "field": "trace_content",
                                })
                                s["match_score"] += 1

                    # Score by agent description matches
                    if desc:
                        desc_lower = desc.lower()
                        for term in search_terms:
                            if term.lower() in desc_lower:
                                if f"desc:{term}" not in [e.get("term") for e in s["match_evidence"]]:
                                    s["match_evidence"].append({
                                        "term": f"desc:{term}",
                                        "field": "agent.description",
                                        "value": desc,
                                    })
                                    s["match_score"] += 3  # Higher weight for description matches

    # Apply time window correlation if provided
    if time_windows:
        for sid, s in sessions.items():
            for window in time_windows:
                w_start = window.get("epoch_start", 0)
                w_end = window.get("epoch_end", float("inf"))
                # Session overlaps with commit window (+/- 2 hours)
                if s["max_epoch"] >= (w_start - 7200) and s["min_epoch"] <= (w_end + 7200):
                    if "temporal" not in [e.get("type") for e in s["match_evidence"]]:
                        s["match_evidence"].append({
                            "type": "temporal",
                            "commit": window.get("commit", ""),
                            "message": window.get("message", ""),
                        })
                        s["match_score"] += 2

    return sessions


def classify_role(session):
    """Classify session role based on tools and descriptions."""
    descs = " ".join(session.get("agent_descriptions", [])).lower()
    tools = session.get("tools", {})

    if any(k in descs for k in ["research", "scraping", "fetch", "explore"]):
        return "research"
    if any(k in descs for k in ["design", "plan", "architect"]):
        return "design"
    if any(k in descs for k in ["review", "audit"]):
        return "review"

    # Heuristic: Write-heavy with Bash near a commit = commit session
    write_count = tools.get("Write", 0)
    bash_count = tools.get("Bash", 0)
    edit_count = tools.get("Edit", 0)
    task_count = tools.get("TaskCreate", 0) + tools.get("TaskUpdate", 0)

    if write_count > 0 and bash_count > 5 and session["spans"] < 50:
        return "commit"
    if task_count > 10:
        return "orchestrator"
    if edit_count > 20:
        return "implementation"

    return "contributor"


def format_output(sessions, target, commits):
    """Format the final output."""
    # Filter to sessions with match_score > 0
    matched = {sid: s for sid, s in sessions.items() if s["match_score"] > 0}

    # Sort by match_score descending
    sorted_sessions = sorted(matched.values(), key=lambda s: s["match_score"], reverse=True)

    result = {
        "target": target,
        "commits": commits,
        "session_count": len(sorted_sessions),
        "sessions": [],
    }

    for s in sorted_sessions:
        min_dt = datetime.fromtimestamp(s["min_epoch"], tz=EST).strftime("%Y-%m-%d %H:%M:%S") if s["min_epoch"] < float("inf") else "?"
        max_dt = datetime.fromtimestamp(s["max_epoch"], tz=EST).strftime("%Y-%m-%d %H:%M:%S") if s["max_epoch"] > 0 else "?"
        duration_min = (s["max_epoch"] - s["min_epoch"]) / 60 if s["max_epoch"] > 0 and s["min_epoch"] < float("inf") else 0

        result["sessions"].append({
            "session_id": s["session_id"],
            "role": classify_role(s),
            "spans": s["spans"],
            "start": min_dt,
            "end": max_dt,
            "duration_minutes": round(duration_min, 1),
            "tools": dict(s["tools"]),
            "agent_descriptions": sorted(s["agent_descriptions"]),
            "match_score": s["match_score"],
            "match_evidence": s["match_evidence"],
            "source_file": s["source_file"],
        })

    return result


def main():
    parser = argparse.ArgumentParser(description="Discover sessions contributing to an output")
    parser.add_argument("file_path", nargs="?", help="Target file path")
    parser.add_argument("--commit", help="Git commit hash")
    parser.add_argument("--search", help="Search term")
    args = parser.parse_args()

    target = args.file_path or args.commit or args.search
    if not target:
        print("Error: provide a file path, --commit, or --search", file=sys.stderr)
        sys.exit(1)

    # Phase 1: Identify commits and dates
    commits = []
    all_files = []

    if args.file_path and os.path.exists(args.file_path):
        all_files.append(args.file_path)
        commits.extend(git_log_for_file(args.file_path))

        # Find referenced files
        refs = extract_references(args.file_path)
        for ref in refs:
            all_files.append(ref)
            commits.extend(git_log_for_file(ref))

    if args.commit:
        changed_files = git_show_files(args.commit)
        for f in changed_files:
            if os.path.exists(f):
                all_files.append(f)
                commits.extend(git_log_for_file(f))

    # Get unique date keys
    date_keys = sorted(set(c["date_key"] for c in commits))
    if not date_keys:
        # Fall back to today
        date_keys = [datetime.now().strftime("%Y-%m-%d")]

    # Derive search terms
    commit_messages = [c["message"] for c in commits]
    search_terms = set()
    for f in all_files:
        search_terms.update(derive_search_terms(f, commit_messages))
    if args.search:
        search_terms.add(args.search)
        for word in args.search.split():
            if len(word) > 3:
                search_terms.add(word)

    # Build time windows from commits
    time_windows = []
    for c in commits:
        try:
            dt = datetime.fromisoformat(c["date"])
            time_windows.append({
                "epoch_start": int(dt.timestamp()),
                "epoch_end": int(dt.timestamp()),
                "commit": c["hash"][:8],
                "message": c["message"],
            })
        except Exception:
            pass

    # Phase 2: Scan traces
    sessions = scan_traces_for_sessions(date_keys, search_terms, time_windows)

    # Format and output
    result = format_output(sessions, target, [
        {"hash": c["hash"][:8], "date": c["date_key"], "message": c["message"]}
        for c in commits
    ])

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
