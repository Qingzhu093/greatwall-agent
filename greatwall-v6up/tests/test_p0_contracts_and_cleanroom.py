"""P0 验收门禁测试：验证原型清理、7 大角色模板 100% 逐字直抄、29 条夜科学完整落盘与 config.json v2.2 对齐。"""

from __future__ import annotations

import json
import pathlib
import re
import unittest

WORKSPACE_ROOT = pathlib.Path(__file__).resolve().parents[2]
PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE_ROOT = PROJECT_ROOT / "core_python"
KB05_PATH = WORKSPACE_ROOT / "docs" / "agent_kb" / "05_原论文级Prompt武器库与五大角色完整模板直抄库.md"
SPEC04_PATH = WORKSPACE_ROOT / "docs" / "architecture" / "04_十三篇前沿论文深度解惑与V6Up架构融合专报.md"

EXPECTED_ROLES = [
    "explorer",
    "lineage_companion",
    "logistics_coordinator",
    "library_surveyor",
    "library_verifier",
    "works_engineer",
    "supervisory_committee",
]


class TestP0ContractsAndCleanroom(unittest.TestCase):
    def test_legacy_prototype_directory_removed_from_root(self) -> None:
        self.assertFalse(
            (WORKSPACE_ROOT / "greatwall-v6up-plugin").exists(),
            "早期原型 greatwall-v6up-plugin 必须已清理或归档，保持 greatwall-v6up 唯一主仓",
        )
        self.assertFalse(
            (CORE_ROOT / "agents" / "central_library.md").exists(),
            "旧版 central_library.md 必须已废除",
        )

    def test_config_json_matches_04_section_7_3_verbatim(self) -> None:
        spec_text = SPEC04_PATH.read_text(encoding="utf-8")
        m = re.search(r"### 7\.3 .*?\n```json\r?\n(.*?)\r?\n```", spec_text, re.S)
        self.assertIsNotNone(m, "未在 04 §7.3 找到基准 config.json")
        expected_cfg = json.loads(m.group(1))
        actual_cfg = json.loads((CORE_ROOT / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(actual_cfg, expected_cfg)
        self.assertEqual(actual_cfg["session_context_clock"]["context_window_tokens"], 500000)
        self.assertEqual(actual_cfg["session_context_clock"]["max_briefing_chars"], 2200)
        self.assertEqual(actual_cfg["session_context_clock"]["max_handoff_chars"], 2000)
        self.assertEqual(actual_cfg["orchestration_and_eval"]["allowed_role_presets"], EXPECTED_ROLES)

    def test_seven_agent_templates_match_kb05_verbatim(self) -> None:
        kb_text = KB05_PATH.read_text(encoding="utf-8")
        pattern = re.compile(
            r"core_python/agents/([a-z_]+\.md).*?````markdown\r?\n(.*?)\r?\n````", re.S
        )
        matches = dict(pattern.findall(kb_text))
        self.assertEqual(sorted(matches.keys()), sorted(f"{r}.md" for r in EXPECTED_ROLES))
        # Round 4 中特意修订去掉误导示例并强化契约护栏的两个角色单独校验，其余 5 个保持逐字对齐 agent_kb/05
        round4_updated_roles = {"logistics_coordinator", "works_engineer"}
        for role in EXPECTED_ROLES:
            file_path = CORE_ROOT / "agents" / f"{role}.md"
            self.assertTrue(file_path.is_file(), f"缺少角色契约模板: {file_path}")
            actual = file_path.read_text(encoding="utf-8").strip()
            self.assertNotIn("{{cwd}}", actual)
            if role in round4_updated_roles:
                self.assertIn("## 1. Identity", actual)
                self.assertIn("## 2.", actual)
                for stale in ("阿伦尼乌斯", "倍率 >2C", "fam_q3_arrhenius_drift"):
                    self.assertNotIn(stale, actual, f"{role}.md 不得保留跨题误导示例 {stale!r}")
                if role == "logistics_coordinator":
                    self.assertIn("epoch_config.goal_md", actual)
                    self.assertIn("depends_on_questions", actual)
                elif role == "works_engineer":
                    self.assertIn("public_input_sample", actual)
                    self.assertIn("metrics.rank_score", actual)
                    self.assertIn("mpmath", actual)
            else:
                expected = matches[f"{role}.md"].strip()
                self.assertEqual(actual, expected, f"{role}.md 未与 agent_kb/05 逐字一致")

    def test_holiday_prompts_yaml_contains_all_29_items(self) -> None:
        yaml_path = CORE_ROOT / "prompts" / "holiday_prompts.yaml"
        self.assertTrue(yaml_path.is_file(), "缺少 holiday_prompts.yaml")
        raw = yaml_path.read_text(encoding="utf-8")
        ids = [int(x) for x in re.findall(r"^\s*-\s+id:\s+(\d+)\s*$", raw, re.M)]
        self.assertEqual(ids, list(range(1, 30)), "holiday_prompts.yaml 必须完整包含 1–29 条")
        scopes = re.findall(r"^\s*scope:\s+(\S+)\s*$", raw, re.M)
        self.assertEqual(scopes[:28], ["reflect_37"] * 28)
        self.assertEqual(scopes[28], "supervisor_only")

    def test_skill_ledger_conforms_to_v22_keys_and_no_stale_tokens(self) -> None:
        ledger = json.loads((CORE_ROOT / "skills" / "SKILL_LEDGER.json").read_text(encoding="utf-8"))
        for sid, entry in ledger["skills"].items():
            self.assertRegex(sid, r"^[a-z0-9_]+$", f"skill_id 规范不符: {sid}")
            self.assertIn("verified_artifact_rel_path", entry)
            artifact = CORE_ROOT / entry["verified_artifact_rel_path"]
            self.assertTrue(artifact.is_file() and artifact.stat().st_size > 0, f"No File 校验失败: {artifact}")

        # 对 P0 已落盘契约文件扫描零残留违禁串
        checked_files = [
            CORE_ROOT / "config.json",
            CORE_ROOT / "prompts" / "holiday_prompts.yaml",
            CORE_ROOT / "skills" / "SKILL_LEDGER.json",
            CORE_ROOT / "skills" / "greatwall-research-loop" / "SKILL.md",
            *[CORE_ROOT / "agents" / f"{r}.md" for r in EXPECTED_ROLES],
        ]
        forbidden = ("178500", "178,500", "central_library", "Coding Assistant", "bound_state_version")
        for fpath in checked_files:
            content = fpath.read_text(encoding="utf-8")
            for bad in forbidden:
                self.assertNotIn(bad, content, f"P0 文件 {fpath.name} 残留废弃字符串 {bad!r}")


if __name__ == "__main__":
    unittest.main()
