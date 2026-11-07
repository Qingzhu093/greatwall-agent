#!/usr/bin/env python3
"""Translate Codex PreToolUse events to the original Great Wall gate."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hook_gate import evaluate_hook


def main():
    event = json.load(sys.stdin)
    tool_name = event.get("tool_name", "")
    tool_input = event.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}

    command = str(tool_input.get("command") or tool_input.get("cmd") or "")
    path = str(tool_input.get("path") or tool_input.get("file_path") or "")
    if tool_name == "apply_patch":
        legacy_name = "edit_file"
        path = command
    elif tool_name in ("Bash", "exec_command"):
        legacy_name = "run_command"
    else:
        legacy_name = "read_file"

    result = evaluate_hook({"toolCall": {"name": legacy_name, "args": {"Path": path, "CommandLine": command}}})
    if result["decision"] == "deny":
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": result["reason"]}}))


if __name__ == "__main__":
    main()
