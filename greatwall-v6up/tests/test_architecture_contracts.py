"""架构防腐门禁测试：
1. 跨语言单一契约源对齐（Python tool_registry.py ↔ Node prompts / sandbox / mcp_bridge）
2. control_plane/describe_contracts RPC 握手一致性
3. 7 份角色系统提示词对各自授权工具的 100% 覆盖
4. Python 分层单向依赖防循环检查（AST）
5. 后端模块行数守卫（防上帝文件回潮）
6. dsh_plugin/tools/doctor.mjs --json 一键自检可执行且全绿
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core_python.mcp_server import greatwall_core_mcp as mcp
from core_python.mcp_server import tool_registry as registry


def _load_node_contract_snapshot() -> dict:
    """直接导入 Node ESM 模块导出静态契约常量，避免手工正则解析漂移。"""
    plugin_dir = ROOT_DIR / "dsh_plugin"
    script = """
import { ALL_MCP_TOOLS, ALL_31_MCP_TOOLS, ROLE_MCP_TOOLS, TURN_CONCLUDING_TOOLS } from './lib/prompts.js'
import { READONLY_BLOCKED_MCP_TOOLS } from './lib/read_isolated_sandbox.js'
import { LONG_RUNNING_MCP_TOOLS } from './lib/mcp_bridge.js'

console.log(JSON.stringify({
  all_tools: [...ALL_MCP_TOOLS].sort(),
  all_31_alias: [...ALL_31_MCP_TOOLS].sort(),
  roles: Object.fromEntries(Object.entries(ROLE_MCP_TOOLS).map(([k, v]) => [k, [...v].sort()])),
  readonly_blocked_tools: [...READONLY_BLOCKED_MCP_TOOLS].sort(),
  long_running_tools: [...LONG_RUNNING_MCP_TOOLS].sort(),
  turn_concluding_tools: [...TURN_CONCLUDING_TOOLS].sort(),
}))
""".strip()
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=str(plugin_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"读取 Node 静态契约失败 (rc={proc.returncode}): {proc.stderr or proc.stdout}")
    return json.loads(proc.stdout)


def _collect_imported_modules(py_file: Path) -> set[str]:
    """提取单个 Python 文件中所有 import / from-import 目标模块名（含相对路径后缀）。"""
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod:
                mods.add(mod)
            for alias in node.names:
                mods.add(f"{mod}.{alias.name}" if mod else alias.name)
    return mods


class TestArchitectureContracts(unittest.TestCase):
    def test_1_python_node_tool_contracts_exact_match(self) -> None:
        py_snap = registry.export_contracts_snapshot()
        node_snap = _load_node_contract_snapshot()

        py_all = sorted(tool for tools in py_snap["role_mcp_tools"].values() for tool in tools)
        py_roles_sorted = {r: sorted(ts) for r, ts in py_snap["role_mcp_tools"].items()}

        self.assertEqual(py_snap["tool_count"], 32)
        self.assertEqual(node_snap["all_tools"], py_all)
        self.assertEqual(node_snap["all_31_alias"], py_all)
        self.assertEqual(node_snap["roles"], py_roles_sorted)
        self.assertEqual(node_snap["readonly_blocked_tools"], py_snap["readonly_blocked_mcp_tools"])
        self.assertEqual(node_snap["long_running_tools"], py_snap["long_running_mcp_tools"])
        self.assertEqual(node_snap["turn_concluding_tools"], py_snap["turn_concluding_tools"])

    def test_2_describe_contracts_rpc_matches_registry_snapshot(self) -> None:
        expected = registry.export_contracts_snapshot()
        resp = mcp.handle_jsonrpc_message(
            {
                "jsonrpc": "2.0",
                "id": 9001,
                "method": "control_plane/describe_contracts",
                "params": {},
            }
        )
        self.assertIsNotNone(resp)
        assert resp is not None
        self.assertNotIn("error", resp)
        result = resp["result"]
        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("data"), expected)

    def test_3_seven_role_prompts_cover_every_authorized_tool(self) -> None:
        agents_dir = ROOT_DIR / "core_python" / "agents"
        for role, allowed in sorted(registry.ALLOWED_TOOLS_BY_ROLE.items()):
            md_path = agents_dir / f"{role}.md"
            self.assertTrue(md_path.is_file(), f"缺少角色提示词模板: {md_path}")
            content = md_path.read_text(encoding="utf-8")
            missing = [tool for tool in sorted(allowed) if tool not in content]
            self.assertEqual(
                missing,
                [],
                f"角色提示词 {role}.md 遗漏授权工具声明: {missing}",
            )

    def test_4_python_layering_no_reverse_imports(self) -> None:
        mcp_dir = ROOT_DIR / "core_python" / "mcp_server"
        forbidden_upper = (
            "tools_explorer",
            "tools_companion",
            "tools_logistics",
            "tools_surveyor",
            "tools_verifier",
            "tools_works",
            "tools_supervisory",
            "tools_library",
            "tools_research",
            "tools_governance",
            "greatwall_core_mcp",
        )

        # 底层契约源与公共助手严禁反向依赖控制面或业务工具模块
        for base_name in ("tool_registry.py", "mcp_core_helpers.py"):
            mods = _collect_imported_modules(mcp_dir / base_name)
            for mod in mods:
                for bad in (*forbidden_upper, "control_plane", "control_plane_service"):
                    self.assertNotIn(
                        bad,
                        mod.split("."),
                        f"底层模块 {base_name} 违反单向依赖，反向导入了 {mod}",
                    )

        # control_plane 子域严禁反向依赖 tools_*.py 或协议入口
        for cp_file in sorted((mcp_dir / "control_plane").glob("*.py")):
            mods = _collect_imported_modules(cp_file)
            for mod in mods:
                for bad in forbidden_upper:
                    self.assertNotIn(
                        bad,
                        mod.split("."),
                        f"控制面子域 control_plane/{cp_file.name} 违反单向依赖，反向导入了 {mod}",
                    )

    def test_5_backend_module_line_count_guard(self) -> None:
        mcp_dir = ROOT_DIR / "core_python" / "mcp_server"
        for py_file in [*sorted(mcp_dir.glob("*.py")), *sorted((mcp_dir / "control_plane").glob("*.py"))]:
            line_count = len(py_file.read_text(encoding="utf-8").splitlines())
            self.assertLess(
                line_count,
                1000,
                f"Python 后端文件超过 1000 行红线（防上帝文件回潮）: {py_file.relative_to(ROOT_DIR)} ({line_count} 行)",
            )

        # 兼容门面保持轻薄（<100 行）
        for facade in ("control_plane_service.py", "tools_library.py", "tools_research.py", "tools_governance.py"):
            line_count = len((mcp_dir / facade).read_text(encoding="utf-8").splitlines())
            self.assertLess(line_count, 100, f"兼容门面 {facade} 膨胀至 {line_count} 行")

        # Node 控制面后端模块（排除阶段 2 待重构的前端 client.js）均须 <950 行
        lib_dir = ROOT_DIR / "dsh_plugin" / "lib"
        js_targets = [
            *[p for p in sorted(lib_dir.glob("*.js")) if p.name != "client.js"],
            *sorted((lib_dir / "orchestrator").glob("*.js")),
            *sorted((lib_dir / "host").glob("*.js")),
        ]
        for js_file in js_targets:
            line_count = len(js_file.read_text(encoding="utf-8").splitlines())
            self.assertLess(
                line_count,
                950,
                f"Node 控制面文件超过 950 行红线（防上帝文件回潮）: {js_file.relative_to(ROOT_DIR)} ({line_count} 行)",
            )

    def test_6_doctor_cli_passes_json_diagnostics(self) -> None:
        doctor_path = ROOT_DIR / "dsh_plugin" / "tools" / "doctor.mjs"
        self.assertTrue(doctor_path.is_file(), f"缺少自检脚本: {doctor_path}")
        proc = subprocess.run(
            ["node", str(doctor_path), "--json"],
            cwd=str(ROOT_DIR / "dsh_plugin"),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=25,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, f"doctor.mjs 失败:\nstdout={proc.stdout}\nstderr={proc.stderr}")
        payload = json.loads(proc.stdout)
        self.assertTrue(payload.get("ok"), f"doctor.mjs 报告未通过: {payload}")
        by_id = {c["id"]: c for c in payload.get("checks", [])}
        for req_id in ("node_runtime", "python_runtime", "git_runtime", "tool_contracts_sync", "presets_integrity", "agent_templates"):
            self.assertIn(req_id, by_id)
            self.assertEqual(by_id[req_id]["status"], "ok", f"{req_id} 未通过: {by_id[req_id]}")


if __name__ == "__main__":
    unittest.main()
