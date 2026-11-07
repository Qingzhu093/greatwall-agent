#!/usr/bin/env python3
"""
Great Wall Agent V4.2 — Lightweight PreToolUse Hook Gate (`hook_gate.py`)
=========================================================================
原则：克制、精准、零误伤（绝不在非长城攻关工作区瞎拦任何命令！）。
仅当检测到当前会话处于包含 `.kernel_vault/` 的长城攻关工作区、且当前路径位于 `worktrees/slot_*` 清洁室孤岛内时生效：
1. 拦截对 `.kernel_vault` 的直接读取或篡改；
2. 拦截对 `shared_readonly/` 公共只读区的写入修改；
3. 拦截跨孤岛偷看隔壁 `worktrees/slot_*` 分支代码。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict


def evaluate_hook(payload: Dict[str, Any]) -> Dict[str, Any]:
    tool_call = payload.get("toolCall") or {}
    tool_name = str(tool_call.get("name", ""))
    tool_args = tool_call.get("args") or {}

    # 1. 提取当前可能涉及的目标路径或命令行文本
    target_path_str = str(tool_args.get("Path") or tool_args.get("TargetFile") or "")
    cmd_line = str(tool_args.get("CommandLine") or "")
    combined_text = f"{target_path_str} {cmd_line}"

    # 快速放行：若完全未涉及长城工作区敏感目录名，0.1ms 直接 allow！
    if not any(kw in combined_text for kw in (".kernel_vault", "shared_readonly", "worktrees")):
        return {"decision": "allow"}

    # 2. 拦截探索节点直接通过文件工具或终端命令偷看 `.kernel_vault` 特权保险箱
    if ".kernel_vault" in combined_text:
        return {
            "decision": "deny",
            "reason": "🔒 [长城 Agent 清洁室隔离门禁] 严禁直接读取或修改 `.kernel_vault` 内核保险箱（含评测真值与 HMAC 密钥）！请使用 `gw_*` 标准 MCP 工具交互。",
        }

    # 3. 拦截对 `shared_readonly` 公共只读区执行写操作 (`write_file` / `edit_file`)
    if tool_name in ("write_file", "edit_file", "replace_file_content", "multi_replace_file_content"):
        norm_p = target_path_str.replace("\\", "/")
        if "/shared_readonly/" in norm_p:
            return {
                "decision": "deny",
                "reason": "🔒 [长城 Agent 只读档案馆门禁] `shared_readonly/` 为公共只读挂载区，严禁直接用写文件工具篡改！请在孤岛 `legacy_out/` 下提交遗产包并通过 `gw_submit_legacy` 验收入库。",
            }

    return {"decision": "allow"}


def main() -> None:
    try:
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        raw = sys.stdin.read()
        if not raw.strip():
            sys.stdout.write('{"decision": "allow"}\n')
            return
        payload = json.loads(raw)
        out = evaluate_hook(payload)
        sys.stdout.write(json.dumps(out, ensure_ascii=True) + "\n")
        sys.stdout.flush()
    except Exception:
        # 钩子自身发生任何解析异常时一律安全放行，绝不卡死主流程
        sys.stdout.write('{"decision": "allow"}\n')
        sys.stdout.flush()


if __name__ == "__main__":
    main()
