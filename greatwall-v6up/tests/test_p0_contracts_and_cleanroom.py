"""P0 静态契约、31 工具 Schema 同源性与 v3.0 清仓防过拟合测试。"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = ROOT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core_python.mcp_server import db_schema as db
from core_python.mcp_server import greatwall_core_mcp as mcp
from core_python.mcp_server import mcp_core_helpers as helpers


class TestP0ContractsAndCleanroom(unittest.TestCase):
    def test_config_json_exact_v3_contract(self) -> None:
        cfg_path = ROOT_DIR / "core_python" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        clk = cfg["session_context_clock"]
        self.assertEqual(clk["context_window_cap_tokens"], 360000)
        self.assertEqual(clk["min_evals_before_reflection"], 0)
        self.assertEqual(clk["context_reflect_hint_pct"], 0.37)
        self.assertEqual(clk["context_handoff_pct"], 0.70)
        self.assertFalse(clk["allow_early_voluntary_handoff"])
        self.assertNotIn("cost_note_enable", clk)
        self.assertTrue(clk["reflection_sequential_turn_boundary"])
        self.assertTrue(clk["handoff_explorer_final_will_turn"])
        self.assertEqual(clk["reflection_max_pointer_hints"], 2)
        self.assertEqual(clk["reflection_max_turns"], 2)

        orch = cfg["orchestration_and_eval"]
        self.assertTrue(orch["require_explicit_model_binding"])
        self.assertTrue(orch["stage1_always_verify_initial_instruments"])
        self.assertEqual(orch["governance_item_circuit_breaker_max_stalled_runs"], 2)
        self.assertTrue(orch["versioned_spec_revision_binding"])
        self.assertTrue(orch["mount_public_inputs_readonly_into_sandboxes"])
        self.assertTrue(orch["companion_resume_by_deterministic_session_id"])
        self.assertTrue(orch["companion_forbid_cross_generation_persistence"])
        self.assertTrue(orch["verifier_isolated_execution_sandbox"])
        self.assertTrue(orch["external_r_open_from_0pct"])
        self.assertEqual(orch["min_initial_method_families_per_question"], 0)
        self.assertEqual(orch["family_concentration_min_branches_in_family"], 2)
        self.assertEqual(orch["family_concentration_share_threshold"], 0.50)
        self.assertFalse(orch["family_concentration_allow_high_yield_exemption"])
        self.assertEqual(orch["default_declared_ref_edge_type"], "MOTIVATING_REF")
        self.assertEqual(orch["unattended_ambiguous_spec_policy"], "CONTINUE_BASELINE_WITH_RED_ALERT")
        self.assertEqual(orch["max_revise_rounds_before_l2"], 2)
        self.assertEqual(orch["level2_max_inplace_repairs"], 3)
        self.assertEqual(orch["instrument_tiers"], ["probe", "official", "heavy"])
        self.assertEqual(orch["instrument_status_enum"], ["OK", "CANDIDATE_ERROR", "INSTRUMENT_ERROR", "INFRA_ERROR"])
        self.assertEqual(orch["instrument_unhealthy_consecutive_error_threshold"], 3)
        self.assertEqual(orch["rqgm_upgrade_policy"], "CALIBRATION_SUITE_REGRESSION")
        self.assertEqual(orch["cdc_closure_modes"], ["FULL", "PARTIAL_ON_BUDGET", "PARTIAL_ON_HUMAN_STOP"])

        raw_text = cfg_path.read_text(encoding="utf-8")
        for forbidden in ("simulator_fidelity_max_error_pct", "is_zero_eval_crash", "BB_eps"):
            self.assertNotIn(forbidden, raw_text)

    def test_seven_agent_templates_match_kb05_verbatim(self) -> None:
        kb05_path = REPO_DIR / "docs" / "agent_kb" / "05_原论文级Prompt武器库与五大角色完整模板直抄库.md"
        if not kb05_path.exists():
            self.skipTest("docs/agent_kb/05 不在当前目录")
        kb_text = kb05_path.read_text(encoding="utf-8")
        pattern = re.compile(
            r"#{2,3}\s+[^\n]*`(?:core_python/agents/)?([a-z_]+\.md)`[^\n]*\n+````markdown\n(.*?)\n````",
            re.DOTALL,
        )
        extracted = {m.group(1): m.group(2).strip() for m in pattern.finditer(kb_text)}
        expected_files = {
            "explorer.md",
            "lineage_companion.md",
            "logistics_coordinator.md",
            "library_surveyor.md",
            "library_verifier.md",
            "works_engineer.md",
            "supervisory_committee.md",
        }
        self.assertEqual(set(extracted.keys()), expected_files)
        for fname in sorted(expected_files):
            disk_path = ROOT_DIR / "core_python" / "agents" / fname
            self.assertTrue(disk_path.is_file(), f"缺少模板文件 {fname}")
            disk_text = disk_path.read_text(encoding="utf-8").strip()
            self.assertEqual(disk_text, extracted[fname], f"{fname} 与 agent_kb/05 不一致")

    def test_holiday_prompts_29_entries(self) -> None:
        yaml_path = ROOT_DIR / "core_python" / "prompts" / "holiday_prompts.yaml"
        text = yaml_path.read_text(encoding="utf-8")
        ids = [int(m) for m in re.findall(r"^\s*-\s*id:\s*(\d+)\s*$", text, re.MULTILINE)]
        self.assertEqual(ids, list(range(1, 30)))
        self.assertIn("supervisor_only", text)

    def test_skill_ledger_v3_and_artifacts_exist(self) -> None:
        ledger_path = ROOT_DIR / "core_python" / "skills" / "SKILL_LEDGER.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        self.assertEqual(ledger.get("schema_version"), "3.0.0")
        skills = ledger.get("skills") or {}
        self.assertIsInstance(skills, dict)
        self.assertGreaterEqual(len(skills), 1)
        for sid, item in skills.items():
            rel = item.get("verified_artifact_rel_path", "")
            self.assertTrue(rel, f"{sid} 缺少 verified_artifact_rel_path")
            self.assertTrue((ROOT_DIR / "core_python" / rel).is_file(), f"技能产物不存在: {rel}")
            rb = item.get("rollback_pointer", "")
            self.assertTrue((ROOT_DIR / "core_python" / rb).is_file(), f"回滚指针不存在: {rb}")

    def test_44_tools_schema_consistency_and_enums(self) -> None:
        defs = mcp.TOOL_DEFINITIONS
        self.assertEqual(len(defs), 53)
        def_names = {d["name"] for d in defs}
        self.assertEqual(def_names, set(mcp._TOOL_REGISTRY.keys()))
        self.assertEqual(def_names, set(helpers.ALL_TOOL_NAMES))
        union_roles = set().union(*helpers.ALLOWED_TOOLS_BY_ROLE.values())
        self.assertEqual(def_names, union_roles)

        by_name = {d["name"]: d for d in defs}
        for name, spec in by_name.items():
            self.assertTrue(spec.get("description"), f"{name} 缺少 description")
            props = spec.get("inputSchema", {}).get("properties", {})
            for p_name, p_schema in props.items():
                self.assertTrue(p_schema.get("description"), f"{name}.{p_name} 缺少 description")

        # 核对核心枚举与 db_schema 同源
        pub_props = by_name["publish_external_literature_card"]["inputSchema"]["properties"]
        self.assertEqual(set(pub_props["outcome"]["enum"]), set(db.ALLOWED_SURVEY_OUTCOMES))
        self.assertEqual({x for x in pub_props["support_scope"]["enum"] if x is not None}, set(db.ALLOWED_SUPPORT_SCOPES))
        self.assertEqual({x for x in pub_props["read_depth"]["enum"] if x is not None}, set(db.ALLOWED_READ_DEPTHS))
        self.assertEqual(pub_props["abstract_md"]["minLength"], 60)
        self.assertGreaterEqual(pub_props["abstract_md"]["maxLength"], 600)

        res_props = by_name["resolve_works_ticket"]["inputSchema"]["properties"]
        self.assertEqual(set(res_props["resolution"]["enum"]), set(db.ALLOWED_TICKET_RESOLUTIONS))

        eval_props = by_name["run_isolated_eval"]["inputSchema"]["properties"]
        self.assertEqual(set(eval_props["tier"]["enum"]), {"probe", "official", "heavy"})

    def test_dsh_package_json_v3_files_whitelist(self) -> None:
        pkg = json.loads((ROOT_DIR / "dsh_plugin" / "package.json").read_text(encoding="utf-8"))
        self.assertTrue(str(pkg["version"]) == "0.3.2", f"unexpected version: {pkg['version']}")
        files = pkg.get("files", [])
        self.assertIn("lib", files)
        self.assertIn("cordis.patch.yml", files)
        self.assertIn("icon.svg", files)
        self.assertNotIn("presets", files)
        self.assertEqual(pkg.get("icon"), "./icon.svg")

    def test_core_python_cleanroom_no_v22_overfitting_tokens(self) -> None:
        forbidden = (
            "register_question_domain_hook",
            "upgrade_hook_with_rqgm_gate",
            "is_zero_eval_crash",
            "simulator_fidelity_max_error_pct",
            "second_pass",
            "阿伦尼乌斯",
        )
        for py_file in (ROOT_DIR / "core_python").rglob("*.py"):
            content = py_file.read_text(encoding="utf-8")
            for tok in forbidden:
                self.assertNotIn(tok, content, f"{py_file} 仍残留 v2.2 过拟合标识: {tok}")


if __name__ == "__main__":
    unittest.main()
