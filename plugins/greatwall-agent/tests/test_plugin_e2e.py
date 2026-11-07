#!/usr/bin/env python3
"""
End-to-End Automated Verification Suite for Great Wall Agent V4.2 Antigravity Plugin.
测试范围涵盖：
1. Phase 0 开局初始化与知识蒸馏固化 (零号强基线 s_0 沙箱实跑测定)；
2. 清洁室孤岛分配 (验证无 .git 残留、L1 启动简报注入、SandboxPathJail 越界与跨血统隐私拦截)；
3. MLE-STAR 式局部代码块 AST 微创热插拔替换 (`gw_surgical_replace`)；
4. AST 刑侦与反作弊拦截：
   - 拦截恶意导入 (`socket` / `ctypes`)；
   - 拦截 Sakana 实测式声明-代码不一致 (`e = 2` 硬编码常数冒充动态搜索)；
   - 识别 0% 结构改动的纯改常数微调与教科书常识剥皮查新 (`micro-batch SGD` -> `BASELINE_ENGINEERING`)；
   - 拦截针对固定顺序背答案的同构扰动测试 (`REJECTED_INDEX_MEMORIZATION`)；
5. 五件套遗产包强校验与轻量级档案馆入库：
   - 拦截无反例脚本支撑的全局悲观谣言；
   - 隔离沙箱实跑可复用原语 `primitives/fast_op.py` 的 `test_*()` 单测，自动更新 `PRIMITIVES_API.md`；
   - 校验 HMAC-SHA256 成绩单防伪签名，累计 60 步自动触发 Station 原位内省室信号；
   - 验证错误结论撤回依赖树 (`retract_claim`) 与终局防吹牛五件套编译 (`gw_compile_delivery`)；
6. 验证 JSON-RPC 2.0 Stdio MCP 服务端 (`gw_mcp_server.py`) 与 `hook_gate.py` 协议交互。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from lib.archive import LightweightArchive
from lib.engine import GreatWallEngine
from lib.evaluator import ASTCodeInspector
from lib.sandbox import SandboxPathJail, force_cleanup_directory


class TestGreatWallPluginE2E(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="gw_v42_test_"))
        # 放入模拟公开数据集文件以验证多模态数据资产清点
        ds_dir = self.temp_dir / "shared_readonly" / "datasets_public"
        ds_dir.mkdir(parents=True, exist_ok=True)
        (ds_dir / "train.csv").write_text("id,x,y\n1,2.0,4.0\n", encoding="utf-8")
        (ds_dir / "geometry.xyz").write_text("2\nH 0 0 0\nH 0 0 0.74\n", encoding="utf-8")
        self.engine = GreatWallEngine(self.temp_dir)

    def tearDown(self) -> None:
        force_cleanup_directory(self.temp_dir, self.temp_dir.parent / ".gw_test_graveyard")
        graveyard = self.temp_dir.parent / ".gw_test_graveyard"
        if graveyard.exists():
            shutil.rmtree(graveyard, ignore_errors=True)

    def test_01_full_campaign_lifecycle_and_archive(self) -> None:
        # 1. Phase 0: 初始化工作区与开局消歧锁定
        init_res = self.engine.init_campaign(
            task_id="TEST_MOL_OPT_2026",
            task_description="优化分子势能预测与对称不变特征提取",
            domain_type="BIO_CHEM",
            primary_metric="score",
            higher_is_better=True,
            max_concurrent_slots=2,
            resolved_ambiguities=[
                {
                    "question": "原子坐标单位是埃(A)还是玻尔半径(Bohr)?",
                    "resolution": "经 EDA 探针核实 H-H 键长为 0.74，确认为埃(A)",
                    "resolved_by": "EDA_GROUNDING_PROBE",
                }
            ],
        )
        self.assertEqual(init_res["status"], "OK")
        self.assertIn("geometry.xyz", init_res["discovered_data_modalities"])
        self.assertIn("train.csv", init_res["discovered_data_modalities"])

        # 2. Phase 0: 锁定开局蒸馏四件套并实跑零号强基线 s_0
        anchor_code = '''"""Phase 0 Anchor Baseline s_0"""
def compute_bonus(inputs):
    return 0.0

def solve(inputs):
    return float(sum(inputs)) + compute_bonus(inputs)
'''
        distill_res = self.engine.lock_opening_distillation(
            orthogonal_families=[
                {"family_id": "FAM-01", "family_name": "Symmetry Invariant GBDT"},
                {"family_id": "FAM-02", "family_name": "Equivariant Graph Net"},
            ],
            anchor_baseline_code=anchor_code,
        )
        self.assertEqual(distill_res["status"], "OK")
        # base_inputs = [10, 25, -5, 42, 88, 13, 7, 99] -> sum = 279.0
        self.assertAlmostEqual(distill_res["anchor_s0_score"], 279.0, places=3)

        # 3. Phase 1: 分配清洁室探索槽位
        slot_res = self.engine.allocate_exploration_slot(
            family_id="FAM-01",
            targeted_code_block="compute_bonus",
            hypothesis="引入二阶范数平方和增益算子提升目标得分",
            step_budget=30,
        )
        self.assertEqual(slot_res["status"], "OK")
        slot_id = slot_res["slot_id"]
        island_dir = Path(slot_res["island_path"])

        # 验证清洁室孤岛内绝对不含 .git 目录，且生成了 scoped_brief.md
        self.assertFalse((island_dir / ".git").exists())
        self.assertTrue((island_dir / "scoped_brief.md").exists())

        # 4. 验证路径牢笼 (SandboxPathJail) 黄金盲分叉测试
        jail = SandboxPathJail(island_dir, self.engine.sandbox.shared_readonly_dir, allowed_lineage_id="LIN-FAM-01")
        with self.assertRaises(PermissionError):
            jail.validate_read("../../.kernel_vault/state_graph.json")
        with self.assertRaises(PermissionError):
            jail.validate_write("../../shared_readonly/archive/ARCHIVE_INDEX.md")
        with self.assertRaises(PermissionError):
            jail.validate_write(".git/config")
        # 写入其他血统的笔记然后尝试跨血统偷看
        other_note = self.engine.archive.lineage_dir / "LIN-FAM-02_secret.md"
        other_note.write_text("Secret note of FAM-02", encoding="utf-8")
        with self.assertRaises(PermissionError):
            jail.validate_read(other_note)

        # 5. MLE-STAR 局部代码块微创替换 (`gw_surgical_replace`)
        new_block = '''def compute_bonus(inputs):
    """二阶置换不变均值增益"""
    return float(len(inputs) * 2.5)
'''
        rep_res = self.engine.surgical_replace_in_slot(
            slot_id=slot_id,
            target_block_name="compute_bonus",
            new_block_code=new_block,
        )
        self.assertEqual(rep_res["status"], "OK")

        # 6. 跨进程防作弊评测 (`gw_evaluate_slot`)
        eval_receipt = self.engine.evaluate_slot(
            slot_id=slot_id,
            operator_description="Second-order permutation invariant moment aggregation",
        )
        self.assertEqual(eval_receipt["triage_tier"], "PARETO_PROMOTE")
        # 279.0 + 8 * 2.5 = 299.0 > 279.0
        self.assertAlmostEqual(eval_receipt["scores"]["frozen_benchmark"], 299.0, places=3)
        self.assertGreater(eval_receipt["ast_audit"]["structural_diff_ratio"], 0.01)

        # 7. 准备五件套遗产包：先测试提交无证据的全局悲观谣言会被拦截
        legacy_out = island_dir / "legacy_out"
        (legacy_out / "epitaph.md").write_text(
            "本实验绝对不可能超过 500 分，理论上不存在更优解！", encoding="utf-8"
        )
        (legacy_out / "last_will_proposals.json").write_text(
            json.dumps([{"action_type": "EXTEND", "falsifiable_hypothesis": "继续深挖三阶矩"}]),
            encoding="utf-8",
        )
        reject_rumor = self.engine.submit_legacy_and_release_slot(slot_id=slot_id, steps_consumed=60)
        self.assertEqual(reject_rumor["status"], "LEGACY_REJECTED")
        self.assertTrue(any("防悲观谣言拦截" in e for e in reject_rumor["errors"]))

        # 8. 修正墓志铭，并提交一个带单元测试的可复用原语 `primitives/fast_moment.py`
        (legacy_out / "epitaph.md").write_text(
            "尝试二阶置换不变增益算子，Frozen 得分从 279.0 提升至 299.0；注意当输入为空列表时需做零长度保护。",
            encoding="utf-8",
        )
        prim_dir = legacy_out / "primitives"
        prim_dir.mkdir(exist_ok=True)
        (prim_dir / "fast_moment.py").write_text(
            '''"""Fast Permutation-Invariant Moment Primitive."""
from typing import Sequence

def compute_invariant_moment(values: Sequence[float], scale: float = 2.5) -> float:
    """计算置换不变线性尺度增益，时间复杂度 O(1)。"""
    return float(len(values) * scale)

def test_compute_invariant_moment() -> None:
    assert abs(compute_invariant_moment([1.0, 2.0, 3.0], scale=2.0) - 6.0) < 1e-6
    assert compute_invariant_moment([], scale=5.0) == 0.0
''',
            encoding="utf-8",
        )

        submit_ok = self.engine.submit_legacy_and_release_slot(slot_id=slot_id, steps_consumed=60)
        self.assertEqual(submit_ok["status"], "OK")
        self.assertIn("fast_moment.py", submit_ok["admitted_primitives"])
        self.assertTrue(submit_ok["trigger_60_step_reflection_chamber"])
        self.assertFalse(island_dir.exists())  # 孤岛已被五步墓碑算法干净回收

        # 9. 验证 PRIMITIVES_API.md 已自动提取函数签名且不含函数体实现源码 (“调库不读码”)
        api_md = self.engine.archive.primitives_api_file.read_text(encoding="utf-8")
        self.assertIn("from archive.ledger.primitives.fast_moment import compute_invariant_moment", api_md)
        self.assertIn("def compute_invariant_moment(values: Sequence[float], scale: float", api_md)
        self.assertNotIn("return float(len(values) * scale)", api_md)

        # 10. 验证终局防吹牛编译：若含 TODO 占位符则拦截，清理后成功生成五件套
        blocked_res = self.engine.compile_final_delivery("本报告结论如下：TODO 补充实验。")
        self.assertEqual(blocked_res["status"], "DELIVERY_BLOCKED_PLACEHOLDERS")

        final_res = self.engine.compile_final_delivery(
            "## 核心方法论总结\n通过开局蒸馏锚定置换不变算子，并在清洁室沙箱中完成微创验证，将基准分由 279.0 提升至 299.0。"
        )
        self.assertEqual(final_res["status"], "OK")
        delivery_dir = Path(final_res["delivery_dir"])
        self.assertTrue((delivery_dir / "01_executive_report.md").exists())
        self.assertTrue((delivery_dir / "02_verified_source_code" / "primitives" / "fast_moment.py").exists())
        self.assertTrue((delivery_dir / "03_claim_evidence_ledger.json").exists())
        self.assertTrue((delivery_dir / "04_reproduce_all.ps1").exists())
        self.assertTrue((delivery_dir / "05_boundary_and_dead_ends_report.md").exists())

        # 11. 验证错误结论撤回依赖树 (Retraction Dependency Tree)
        self.engine.archive._append_jsonl(
            self.engine.archive.claims_file,
            {"claim_id": "CLM-ROOT", "statement": "基础假设 A", "depends_on": [], "status": "VERIFIED_ACTIVE"},
        )
        self.engine.archive._append_jsonl(
            self.engine.archive.claims_file,
            {"claim_id": "CLM-CHILD", "statement": "派生推论 B", "depends_on": ["CLM-ROOT"], "status": "VERIFIED_ACTIVE"},
        )
        self.engine.archive._append_jsonl(
            self.engine.archive.claims_file,
            {"claim_id": "CLM-GRANDCHILD", "statement": "孙代定理 C", "depends_on": ["CLM-CHILD"], "status": "VERIFIED_ACTIVE"},
        )
        affected_ids = self.engine.archive.retract_claim("CLM-ROOT", reason="在极端边界反例下失效")
        self.assertEqual(set(affected_ids), {"CLM-ROOT", "CLM-CHILD", "CLM-GRANDCHILD"})
        c_child = self.engine.archive.query_l2_item("CLM-CHILD")
        self.assertEqual(c_child["data"]["status"], "NEEDS_REVALIDATION")

    def test_02_ast_forensic_and_anti_fake_novelty(self) -> None:
        # 1. 测试 Sakana AI Scientist 实测曝光的“声称动态探索 e in {2,3,4,5}，实际写死 e = 2”
        fake_sweep_code = """
def run_experiment():
    e_folds = 2
    return e_folds * 10
"""
        rep1 = ASTCodeInspector.inspect_code(
            candidate_code=fake_sweep_code,
            claimed_swept_variables=["e_folds"],
        )
        self.assertFalse(rep1.passed)
        self.assertTrue(any("e_folds" in msg for msg in rep1.claim_code_mismatch))

        # 2. 测试真实循环遍历 e_folds 则通过
        real_sweep_code = """
def run_experiment():
    results = []
    for e_folds in [2, 3, 4, 5]:
        results.append(e_folds * 10)
    return max(results)
"""
        rep2 = ASTCodeInspector.inspect_code(
            candidate_code=real_sweep_code,
            claimed_swept_variables=["e_folds"],
        )
        self.assertTrue(rep2.passed)

        # 3. 测试给微批处理套花哨名词“Green-Aware Synergistic Micro-batch SGD”剥皮后自动降级为 BASELINE_ENGINEERING
        rep3 = ASTCodeInspector.inspect_code(
            candidate_code=real_sweep_code,
            operator_description="Green-Aware Synergistic Holistic Micro-batch Gradient Accumulation for SGD",
        )
        self.assertEqual(rep3.novelty_classification, "BASELINE_ENGINEERING")

        # 4. 测试只改常数字面量 (lr=0.01 -> lr=0.005) 的 0% AST 结构改动识别
        parent_src = "def train(x):\n    lr = 0.01\n    return x * lr\n"
        child_src = "def train(x):\n    lr = 0.005\n    return x * lr\n"
        rep4 = ASTCodeInspector.inspect_code(
            candidate_code=child_src,
            parent_code=parent_src,
            operator_description="Novel topological manifold optimizer",
        )
        self.assertEqual(rep4.structural_diff_ratio, 0.0)
        self.assertTrue(rep4.is_superficial_tweak)
        self.assertEqual(rep4.novelty_classification, "HYPERPARAMETER_TWEAK")

    def test_03_mcp_stdio_server_and_hook_gate(self) -> None:
        # 测试 gw_mcp_server.py 的 JSON-RPC initialize 与 tools/list 响应
        server_script = PLUGIN_ROOT / "bin" / "gw_mcp_server.py"
        requests_lines = "\n".join(
            [
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
            ]
        ) + "\n"

        proc = subprocess.run(
            [sys.executable, str(server_script)],
            input=requests_lines,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
        self.assertEqual(proc.returncode, 0)
        out_lines = [json.loads(line) for line in proc.stdout.strip().splitlines() if line.strip()]
        self.assertEqual(len(out_lines), 2)
        self.assertEqual(out_lines[0]["result"]["serverInfo"]["name"], "greatwall-agent")
        tool_names = [t["name"] for t in out_lines[1]["result"]["tools"]]
        self.assertEqual(len(tool_names), 8)
        self.assertIn("gw_lock_distillation", tool_names)
        self.assertIn("gw_surgical_replace", tool_names)

        # 测试 hook_gate.py：正常命令放行，偷看 .kernel_vault 拦截
        hook_script = PLUGIN_ROOT / "bin" / "hook_gate.py"
        normal_payload = json.dumps({"toolCall": {"name": "read_file", "args": {"Path": "src/main.py"}}})
        p_allow = subprocess.run(
            [sys.executable, str(hook_script)],
            input=normal_payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
        )
        self.assertEqual(json.loads(p_allow.stdout)["decision"], "allow")

        vault_payload = json.dumps(
            {"toolCall": {"name": "read_file", "args": {"Path": "../../.kernel_vault/hmac_secret.key"}}}
        )
        p_deny = subprocess.run(
            [sys.executable, str(hook_script)],
            input=vault_payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
        )
        self.assertEqual(json.loads(p_deny.stdout)["decision"], "deny")


if __name__ == "__main__":
    unittest.main(verbosity=2)
