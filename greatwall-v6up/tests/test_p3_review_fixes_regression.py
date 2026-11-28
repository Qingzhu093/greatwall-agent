"""P3 评审闭环专项回归测试：精准覆盖 5 大主场景与全部次级工程修复。"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core_python.evaluators.isolated_runner import run_isolated_instrument
from core_python.mcp_server import control_plane_service as cp
from core_python.mcp_server import db_schema as db
from core_python.mcp_server import greatwall_core_mcp as mcp


def _write_file(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


def _write_json(path: Path, obj: object) -> str:
    return _write_file(path, json.dumps(obj, ensure_ascii=False, indent=2))


class TestP3ReviewFixesRegression(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="gw_v3_p3_reg_")
        self.ws = Path(self._tmp.name) / "ws"
        self.ws.mkdir(parents=True, exist_ok=True)
        self.plugin_data = Path(self._tmp.name) / "plugin_data"
        self._old_env = os.environ.get("GREATWALL_PLUGIN_DATA_DIR")
        os.environ["GREATWALL_PLUGIN_DATA_DIR"] = str(self.plugin_data)

        paths = db.resolve_storage_paths(str(self.ws))
        # 验证环境变量确实落入隔离临时目录，不污染用户默认 ~/.dsh
        self.assertTrue(str(paths["db_path"]).startswith(str(Path(os.path.realpath(self.plugin_data)))))
        self.db_path = paths["db_path"]
        self.conn = db.open_rw_connection(self.db_path, init_schema=True)
        cp.init_parse0_contract(
            self.conn,
            goal_and_completion_md="# Goal\nQ1 通用科学发现验证。",
            subquestions=["Q1"],
            total_budget={"max_total_handoffs": 2},
            min_commitment_window_sec=0,
            stage="STAGE2_EVOLVE",
        )

    def tearDown(self) -> None:
        self.conn.close()
        if self._old_env is None:
            os.environ.pop("GREATWALL_PLUGIN_DATA_DIR", None)
        else:
            os.environ["GREATWALL_PLUGIN_DATA_DIR"] = self._old_env
        self._tmp.cleanup()

    def _call(self, tool: str, role: str, sid: str, **kwargs) -> dict:
        return mcp.dispatch_tool_call(
            tool,
            kwargs,
            workspace_root=str(self.ws),
            caller_role=role,
            session_id=sid,
        )

    def _make_branch(self, fid: str = "fam_reg") -> tuple[str, str, Path]:
        self.assertTrue(
            self._call(
                "register_method_family", "logistics_coordinator", "sl",
                question_id="Q1", family_id=fid,
                mechanism_signature="核心机理", orthogonal_contrast="基线",
            )["ok"]
        )
        b = self._call(
            "fork_branch", "logistics_coordinator", "sl",
            question_id="Q1", fork_mode="orthogonal", target_family_id=fid,
        )
        self.assertTrue(b["ok"], b)
        return b["data"]["branch_id"], b["data"]["node_id"], Path(b["data"]["worktree_abs_path"])

    def test_1_briefing_body_and_lane_assignment_reach_explorer_and_reflect37_gate(self) -> None:
        bid, nid, _ = self._make_branch()
        self.assertTrue(
            self._call(
                "save_lineage_briefing", "lineage_companion", "sc1",
                branch_id=bid, node_id=nid,
                sec1_mechanism="TAG_SEC1_MECH",
                sec2_verified_baseline="TAG_SEC2_BASE",
                sec3_bottleneck="TAG_SEC3_BOTTLE",
                sec4_dead_ends="TAG_SEC4_DEAD",
                sec5_immediate_will="TAG_SEC5_WILL",
            )["ok"]
        )
        with db.rw_immediate_tx(self.conn):
            self.conn.execute("UPDATE lineage_nodes SET lane_assignment = 'UNDERSTANDING: 分析边界失效机理' WHERE node_id = ?", (nid,))

        snap = cp.schedule_control_plane_snapshot(self.conn)
        ready = [r for r in snap["explorers_ready_to_run"] if r["node_id"] == nid]
        self.assertEqual(len(ready), 1)
        md = ready[0].get("briefing_snapshot_md", "")
        for tag in ("TAG_SEC1_MECH", "TAG_SEC2_BASE", "TAG_SEC3_BOTTLE", "TAG_SEC4_DEAD", "TAG_SEC5_WILL"):
            self.assertIn(tag, md)
        self.assertEqual(ready[0].get("lane_assignment"), "UNDERSTANDING: 分析边界失效机理")

        # 0% 水位调 REFLECT_37 获取上下文必须被拦截
        denied = self._call("get_companion_context", "lineage_companion", "sc1", branch_id=bid, node_id=nid, mode="REFLECT_37")
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["error_code"], db.ERR_LOCKED)

        # 推到 38% 水位后正常放行
        cp.sync_session_pressure(self.conn, node_id=nid, pressure_tokens=190000)
        allowed = self._call("get_companion_context", "lineage_companion", "sc1", branch_id=bid, node_id=nid, mode="REFLECT_37")
        self.assertTrue(allowed["ok"], allowed)

    def test_2_stage3_revise_loop_disk_tamper_repro_tools_and_atomic_export(self) -> None:
        bid, nid, wt = self._make_branch()
        _write_file(wt / "tools" / "util.py", "def helper():\n    return 42\n")
        _write_file(wt / "solve.py", "from tools.util import helper\nprint(helper())\n")

        self.assertTrue(
            self._call(
                "submit_node_handoff", "lineage_companion", "sc",
                node_id=nid, branch_id=bid, question_id="Q1",
                mechanism_summary="完备构造", evidence_grade="ARTIFACT_ONLY",
                column_a_facts_md="已验证 solve.py 与 tools/util.py",
                column_b_hypothesis_md="无额外未证假设",
                will_md="可直接送审", obs_ids=[], dead_ends=[],
                candidate_rel_path="solve.py", is_empty_crash=False,
            )["ok"]
        )
        rid = self._call(
            "triage_node", "logistics_coordinator", "sl",
            node_id=nid, assigned_family_id="fam_reg", triage_level="LEVEL_1",
            action="SUBMIT_BLIND_REVIEW", rationale="送审",
        )["data"]["created_review_id"]
        self._call("get_blind_manuscript", "library_verifier", "sv1", review_id=rid)
        self._call(
            "submit_stage1_blind_ledger", "library_verifier", "sv1",
            review_id=rid, question_id="Q1",
            ledger_items=[{"claim": "构造成立", "evidence_location_and_quote": "solve.py L1", "status": "VERIFIED"}],
            stage1_verdict="PASS",
            rigor_score=8,
        )
        self._call("get_unblinded_manuscript_and_peers", "library_verifier", "sv1", review_id=rid)
        s2_res = self._call(
            "submit_stage2_unblind_verdict", "library_verifier", "sv1",
            review_id=rid, final_verdict="ACCEPT", novelty_score=8, significance_score=8, l3_entry_kind="POS_THEOREM", goal_coverage="FULL_GOAL",
            title="Q1 完整定理",
            abstract_md="完整证明 Q1 主命题并给出了可执行构造，经独立盲审沙箱复现核验确认逻辑无漏洞、所有依赖模块齐备且边界条件与题面定义严格吻合。",
            exact_verified_scope_md="Q1 全域",
        )
        self.assertTrue(s2_res["ok"], s2_res)
        l3_id = s2_res["data"]["created_l3_id"]

        # 导出版本 A：验证 reproduction_suite 含节点隔离目录与 tools/util.py
        exp_a = self._call(
            "export_stage3_final_delivery", "library_chronicler", "ss",
            delivery_mode="FULL",
            formal_paper_md="# 论文初版 A\n本报告完整汇总 Q1 主定理的严格证明与最小复现套件，全部引用均已溯源核验并附带依赖模块。\n",
            selected_l3_ids_by_question={"Q1": [l3_id]},
            remaining_gaps_by_question={"Q1": ""},
            reproduction_candidate_nodes=[nid],
        )
        self.assertTrue(exp_a["ok"], exp_a)
        did_a = exp_a["data"]["delivery_id"]
        self.assertTrue((self.ws / "final_delivery" / "reproduction_suite" / f"Q1_{nid}" / "solve.py").is_file())
        self.assertTrue((self.ws / "final_delivery" / "reproduction_suite" / f"Q1_{nid}" / "tools" / "util.py").is_file())

        # 盲审终核判 REVISE -> 必须切为 stage3_revision_pending=True 且不再循环派审稿人！
        rev = self._call(
            "submit_stage2_unblind_verdict", "library_verifier", "sv_s3",
            review_id=f"STAGE3_FINAL_AUDIT:{did_a}",
            final_verdict="REVISE",
            revision_requests=["请补充边界条件表述"],
        )
        self.assertTrue(rev["ok"], rev)
        snap_rev = cp.schedule_control_plane_snapshot(self.conn)
        self.assertTrue(snap_rev["stage3_revision_pending"])
        self.assertFalse(snap_rev["stage3_final_audit_pending"])

        # 中途导出含非法复现节点报错：旧 final_delivery 必须毫发无损！
        bad_exp = self._call(
            "export_stage3_final_delivery", "library_chronicler", "ss",
            delivery_mode="FULL",
            formal_paper_md="# 失败导出测试\n此导出引用了不存在的候选节点，按原子导出协议应在替换 final_delivery 目录之前即报错中止，并保证旧版合法交付包完好无损。\n",
            selected_l3_ids_by_question={"Q1": [l3_id]},
            remaining_gaps_by_question={"Q1": ""},
            reproduction_candidate_nodes=["node_nonexistent_999"],
        )
        self.assertFalse(bad_exp["ok"])
        self.assertIn("论文初版 A", (self.ws / "final_delivery" / "01_formal_report.md").read_text(encoding="utf-8"))

        # 终稿官修订重导版本 B -> 篡改外部不可变冻结目录内容 -> 盲审官一步终签必须因 SHA-256 失配拦截！
        exp_b = self._call(
            "export_stage3_final_delivery", "library_chronicler", "ss",
            delivery_mode="FULL",
            formal_paper_md="# 论文修订版 B\n已严格按盲审官的修订清单补充全部边界条件、适用假设与精确验证范围，全部最小复现脚本及依赖模块均已随包归档并通过独立核验。\n",
            selected_l3_ids_by_question={"Q1": [l3_id]},
            remaining_gaps_by_question={"Q1": ""},
            reproduction_candidate_nodes=[nid],
        )
        self.assertTrue(exp_b["ok"], exp_b)
        did_b = exp_b["data"]["delivery_id"]
        frozen_dir = Path(exp_b["data"]["frozen_delivery_dir_abs_path"])
        report_p = frozen_dir / "01_formal_report.md"
        orig_text = report_p.read_text(encoding="utf-8")
        # 外部不可变冻结目录默认设只读权限；模拟越权篡改前先临时放开写位，验证 SHA-256 门禁仍死守底线
        os.chmod(report_p, 0o644)
        report_p.write_text(orig_text + "\n偷改一行结论\n", encoding="utf-8")
        tampered_sign = self._call(
            "submit_stage2_unblind_verdict", "library_verifier", "sv_s3_2",
            review_id=f"STAGE3_FINAL_AUDIT:{did_b}", final_verdict="ACCEPT",
        )
        self.assertFalse(tampered_sign["ok"])
        self.assertIn("SHA-256", tampered_sign["error"])

        # 恢复冻结目录内容后，盲审官一步原子终签通过并晋升 CLOSED_VERIFIED
        report_p.write_text(orig_text, encoding="utf-8")
        os.chmod(report_p, 0o444)
        ok_sign = self._call(
            "submit_stage2_unblind_verdict", "library_verifier", "sv_s3_3",
            review_id=f"STAGE3_FINAL_AUDIT:{did_b}", final_verdict="ACCEPT",
        )
        self.assertTrue(ok_sign["ok"], ok_sign)
        self.assertEqual(ok_sign["data"]["closure_status"], "CLOSED_VERIFIED")

    def test_3_all_three_bundled_example_instruments_pass_real_runner(self) -> None:
        ex_dir = ROOT_DIR / "core_python" / "evaluators" / "examples"

        # 1) 几何反例
        g_art = _write_json(self.ws / "g.json", {"points": [[0, 0], [1, 0], [10, 0]]})
        g_res = run_isolated_instrument(
            instrument_path=ex_dir / "geom_counterexample.py",
            instrument_role="VERDICT",
            artifact_path=g_art,
            spec={"public_input": {"dimension": 2, "conjecture_bound": 5.0}},
            tier="official",
            artifact_schema="json_file",
        )
        self.assertEqual(g_res["obs_status"], "VALID_PASS", g_res)

        # 2) Lean 协议样例：闭合 -> VALID_PASS；probe 有未闭合义务 -> VALID_UNDECIDED
        l_pass = _write_json(
            self.ws / "l_pass.json",
            {"theorem_statement": "forall n, n = n", "axioms_used": ["propext"], "obligations": [{"id": "g1", "proved": True}]},
        )
        r_l1 = run_isolated_instrument(
            instrument_path=ex_dir / "lean_formal_stub.py",
            instrument_role="VERDICT",
            artifact_path=l_pass,
            spec={"public_input": {"theorem_statement": "forall n, n = n"}},
            tier="official",
            artifact_schema="json_file",
        )
        self.assertEqual(r_l1["obs_status"], "VALID_PASS", r_l1)

        l_open = _write_json(
            self.ws / "l_open.json",
            {"theorem_statement": "forall n, n = n", "axioms_used": [], "obligations": [{"id": "g1", "proved": False}]},
        )
        r_l2 = run_isolated_instrument(
            instrument_path=ex_dir / "lean_formal_stub.py",
            instrument_role="VERDICT",
            artifact_path=l_open,
            spec={"public_input": {"theorem_statement": "forall n, n = n"}},
            tier="probe",
            artifact_schema="json_file",
        )
        self.assertEqual(r_l2["obs_status"], "VALID_UNDECIDED", r_l2)

        # 3) Pareto 协议样例：全维达标 -> VALID_PASS；漏交必填底线维度 -> MEASURED_REJECTION
        p_ok = _write_json(self.ws / "p_ok.json", {"objectives": {"accuracy": 0.9, "cost": 0.5}})
        r_p1 = run_isolated_instrument(
            instrument_path=ex_dir / "pareto_sim.py",
            instrument_role="VERDICT",
            artifact_path=p_ok,
            spec={"public_input": {"nadir_floors": {"accuracy": 0.8, "cost": 0.1}}},
            tier="heavy",
            artifact_schema="json_file",
        )
        self.assertEqual(r_p1["obs_status"], "VALID_PASS", r_p1)

        p_miss = _write_json(self.ws / "p_miss.json", {"objectives": {"cost": 0.5}})
        r_p2 = run_isolated_instrument(
            instrument_path=ex_dir / "pareto_sim.py",
            instrument_role="VERDICT",
            artifact_path=p_miss,
            spec={"public_input": {"nadir_floors": {"accuracy": 0.8}}},
            tier="official",
            artifact_schema="json_file",
        )
        self.assertEqual(r_p2["obs_status"], "MEASURED_REJECTION", r_p2)

    def test_4_pending_handoff_persistence_heavy_same_path_upgrade_and_reval_error_distinction(self) -> None:
        bid, nid, wt = self._make_branch()
        # 1) 持久化亲笔遗嘱后，节点进入 pending_handoff_nodes 而不被重复派探索者
        cp.record_pending_handoff(
            self.conn, node_id=nid, mode="HANDOFF_70", explorer_will_md="亲笔遗嘱：重点验证 k=3 边界", reason="HANDOFF_70"
        )
        snap = cp.schedule_control_plane_snapshot(self.conn)
        self.assertEqual([r["node_id"] for r in snap["pending_handoff_nodes"]], [nid])
        self.assertEqual(snap["pending_handoff_nodes"][0]["explorer_will_md"], "亲笔遗嘱：重点验证 k=3 边界")
        self.assertEqual([r["node_id"] for r in snap["explorers_ready_to_run"]], [])

        # 2) heavy 入队冻结仪器源码：即使工造司在原路径原地覆写仪器并升版，重跑仍执行冻结的 v1
        inst_file = self.ws / "evaluators" / "same_path_inst.py"
        _write_file(
            inst_file,
            """
from core_python.evaluators.base_instrument import get_public_input
def evaluate(artifact, spec, tier="official"):
    _ = get_public_input(spec)
    return {"status": "OK", "verdict": "PASS", "tracks": {"ver": "V1_FROZEN"}, "details": "v1"}
""",
        )
        _write_json(
            self.ws / "evaluators" / "_hidden_calibrations" / "cal_same.json",
            [{"case_id": "c1", "tier": "heavy", "spec": {"public_input": {"k": 1}}, "artifact": {"x": 1}, "expected_status": "OK", "expected_verdict": "PASS"}],
        )
        self.assertTrue(
            self._call(
                "register_question_instrument", "works_engineer", "sw",
                question_id="Q1", instrument_id="inst_same", instrument_role="VERDICT",
                instrument_rel_path="evaluators/same_path_inst.py",
                calibration_suite_rel_path="evaluators/_hidden_calibrations/cal_same.json",
                artifact_schema="python_run", plugin_protocol_version="v3",
                default_spec={"public_input": {"k": 1}},
            )["ok"]
        )
        _write_file(wt / "cand.py", "def run(spec):\n    return {'x': 1}\n")
        enq = self._call(
            "run_isolated_eval", "explorer", "se",
            node_id=nid, question_id="Q1", instrument_id="inst_same", tier="heavy",
            artifact_rel_path="cand.py", linguistic_prediction="同路径升版冻结验证", declared_refs=[],
        )
        self.assertTrue(enq["ok"], enq)
        job_id = enq["data"]["job_id"]

        # 原地覆写同一个仪器文件为 V2_OVERWRITTEN 并升版
        _write_file(
            inst_file,
            """
from core_python.evaluators.base_instrument import get_public_input
def evaluate(artifact, spec, tier="official"):
    _ = get_public_input(spec)
    return {"status": "OK", "verdict": "PASS", "tracks": {"ver": "V2_OVERWRITTEN"}, "details": "v2"}
""",
        )
        self.assertTrue(
            self._call(
                "upgrade_instrument_with_calibration", "works_engineer", "sw2",
                question_id="Q1", instrument_id="inst_same",
                new_instrument_rel_path="evaluators/same_path_inst.py",
                calibration_suite_rel_path="evaluators/_hidden_calibrations/cal_same.json",
            )["ok"]
        )
        cp.recover_pending_heavy_jobs(self.conn, workspace_root=str(self.ws))
        polled = self._call(
            "run_isolated_eval", "explorer", "se",
            node_id=nid, question_id="Q1", instrument_id="inst_same", tier="heavy",
            artifact_rel_path="cand.py", linguistic_prediction="查询重型结果", declared_refs=[], job_id=job_id,
        )
        self.assertEqual(polled["data"]["tracks"]["ver"], "V1_FROZEN")

        # 3) recompute_stage_b_only 遇到新版仪器在历史输入上的内部 RuntimeError 不误判旧观测 INCOMPATIBLE
        #    同时验证：工作区文件直接被原地篡改（未升版）时，冻结快照仍安全保护 v2 重评不被污染
        obs_id = polled["data"]["obs_id"]
        _write_file(
            inst_file,
            """
from core_python.evaluators.base_instrument import get_public_input
def evaluate(artifact, spec, tier="official"):
    _ = get_public_input(spec)
    if isinstance(artifact, dict) and artifact.get("x") == 1:
        raise RuntimeError("new instrument internal crash on historical payload")
    return {"status": "OK", "verdict": "PASS", "tracks": {"ver": "V3_CRASH_ON_X1"}, "details": "v3"}
""",
        )
        # 校准集 payload 是 {'x': 1}，这里更新校准集为 {'x': 2} 使 v3 合规通过校准并升版
        _write_json(
            self.ws / "evaluators" / "_hidden_calibrations" / "cal_same.json",
            [{"case_id": "c1", "tier": "heavy", "spec": {"public_input": {"k": 1}}, "artifact": {"x": 2}, "expected_status": "OK", "expected_verdict": "PASS"}],
        )
        self.assertTrue(
            self._call(
                "upgrade_instrument_with_calibration", "works_engineer", "sw2b",
                question_id="Q1", instrument_id="inst_same",
                new_instrument_rel_path="evaluators/same_path_inst.py",
                calibration_suite_rel_path="evaluators/_hidden_calibrations/cal_same.json",
            )["ok"]
        )
        rec_err = self._call("recompute_stage_b_only", "works_engineer", "sw3", obs_id=obs_id, question_id="Q1")
        self.assertTrue(rec_err["ok"], rec_err)
        self.assertEqual(rec_err["data"]["status"], "INSTRUMENT_ERROR")
        cur_obs = self.conn.execute("SELECT obs_status FROM observations WHERE obs_id = ?", (obs_id,)).fetchone()
        self.assertNotEqual(cur_obs["obs_status"], "INCOMPATIBLE")

    def test_5_legacy_v2_db_rejected_cleanly_and_budget_exhaustion_gate(self) -> None:
        # 1) 旧版 v2.2 数据库明确报错提示换文件夹
        mem = sqlite3.connect(":memory:")
        mem.row_factory = sqlite3.Row
        mem.execute("CREATE TABLE observations (obs_id TEXT PRIMARY KEY, validity_state TEXT);")
        with self.assertRaises(db.FailClosedError) as ctx:
            db.init_database_schema(mem)
        self.assertEqual(ctx.exception.code, db.ERR_STORAGE)
        self.assertIn("更换工作区目录", ctx.exception.message)
        mem.close()

        # 2) PARTIAL_ON_BUDGET 未耗尽预算时必被拒，耗尽后放行
        g1 = cp.check_stage2_closure_gate_data(self.conn, mode="PARTIAL_ON_BUDGET")
        self.assertFalse(g1["closure_allowed"])
        self.assertEqual(g1["gate_code"], "GATE_BLOCKED_BUDGET_NOT_EXHAUSTED")

        # 产生 2 次已交接节点（达到 max_total_handoffs=2）
        bid1, nid1, _ = self._make_branch("fam_b1")
        bid2, nid2, _ = self._make_branch("fam_b2")
        for b_i, n_i in ((bid1, nid1), (bid2, nid2)):
            self._call(
                "submit_node_handoff", "lineage_companion", "sc",
                node_id=n_i, branch_id=b_i, question_id="Q1",
                mechanism_summary="测试预算", evidence_grade="NONE",
                column_a_facts_md="无突破", column_b_hypothesis_md="待定",
                will_md="继续", obs_ids=[], dead_ends=[], is_empty_crash=False,
            )
        g2 = cp.check_stage2_closure_gate_data(self.conn, mode="PARTIAL_ON_BUDGET")
        self.assertTrue(g2["closure_allowed"])
        self.assertEqual(g2["gate_code"], "GATE_PASSED_PARTIAL_BUDGET")

    def test_6_cross_branch_cache_reuse_materializes_local_obs_and_passes_handoff(self) -> None:
        inst_file = self.ws / "evaluators" / "cache_inst.py"
        _write_file(
            inst_file,
            """
from core_python.evaluators.base_instrument import get_public_input
def evaluate(artifact, spec, tier="official"):
    _ = get_public_input(spec)
    val = artifact.get("score", 0) if isinstance(artifact, dict) else 0
    return {"status": "OK", "verdict": "PASS" if val > 0 else "FAIL", "tracks": {"score": val}, "details": "ok"}
""",
        )
        _write_json(
            self.ws / "evaluators" / "_hidden_calibrations" / "cal_cache.json",
            [
                {"case_id": "p", "tier": "official", "spec": {"public_input": {"k": 1}}, "artifact": {"score": 10}, "expected_status": "OK", "expected_verdict": "PASS"},
                {"case_id": "n", "tier": "official", "spec": {"public_input": {"k": 1}}, "artifact": {"score": 0}, "expected_status": "OK", "expected_verdict": "FAIL"},
            ],
        )
        reg = self._call(
            "register_question_instrument", "works_engineer", "sw",
            question_id="Q1", instrument_id="inst_cache", instrument_role="VERDICT",
            instrument_rel_path="evaluators/cache_inst.py",
            calibration_suite_rel_path="evaluators/_hidden_calibrations/cal_cache.json",
            artifact_schema="python_run", plugin_protocol_version="v3",
            default_spec={"public_input": {"k": 1}},
        )
        self.assertTrue(reg["ok"], reg)

        b1, n1, wt1 = self._make_branch("fam_cache_a")
        b2, n2, wt2 = self._make_branch("fam_cache_b")
        same_code = "def run(spec):\n    return {'score': 42}\n"
        _write_file(wt1 / "cand.py", same_code)
        _write_file(wt2 / "cand.py", same_code)

        ev1 = self._call(
            "run_isolated_eval", "explorer", "se1",
            node_id=n1, question_id="Q1", instrument_id="inst_cache", tier="official",
            artifact_rel_path="cand.py", linguistic_prediction="分支A首次执行基线得分预期为42", declared_refs=[],
        )
        self.assertTrue(ev1["ok"], ev1)
        self.assertFalse(ev1["data"]["cache_hit"])
        obs_a = ev1["data"]["obs_id"]

        # 分支 B 用相同代码命中缓存：必须签发归属 B 的新收据，并标注来源 obs_a
        ev2 = self._call(
            "run_isolated_eval", "explorer", "se2",
            node_id=n2, question_id="Q1", instrument_id="inst_cache", tier="official",
            artifact_rel_path="cand.py", linguistic_prediction="分支B复用同基线验证一致结果", declared_refs=[],
        )
        self.assertTrue(ev2["ok"], ev2)
        self.assertTrue(ev2["data"]["cache_hit"])
        obs_b = ev2["data"]["obs_id"]
        self.assertNotEqual(obs_b, obs_a)
        self.assertEqual(ev2["data"]["reused_from_obs_id"], obs_a)

        # B 用自己的复用收据交接 MEASURED 必须一次通过，不再报归属冲突
        ho_b = self._call(
            "submit_node_handoff", "lineage_companion", "sc2",
            node_id=n2, branch_id=b2, question_id="Q1",
            mechanism_summary="B验证基线一致", evidence_grade="MEASURED",
            column_a_facts_md=f"复用 {obs_b}", column_b_hypothesis_md="准备改进",
            will_md="下一步改进", obs_ids=[obs_b], dead_ends=[], is_empty_crash=False,
        )
        self.assertTrue(ho_b["ok"], ho_b)

        # 预算统计只计 1 次真实正式评测，不因跨分支缓存复用虚增
        gate = cp.check_stage2_closure_gate_data(self.conn, mode="PARTIAL_ON_BUDGET")
        self.assertEqual(gate["budget_usage"]["used_official_evals"], 1)

    def test_7_consecutive_instrument_upgrade_v1_v2_v3_and_keyerror_vs_incompatible(self) -> None:
        inst_file = self.ws / "evaluators" / "evolve_inst.py"
        cal_file = self.ws / "evaluators" / "_hidden_calibrations" / "cal_evolve.json"
        _write_json(
            cal_file,
            [
                {"case_id": "p", "tier": "official", "spec": {"public_input": {"k": 1}}, "artifact": {"val": 10}, "expected_status": "OK", "expected_verdict": "PASS"},
                {"case_id": "n", "tier": "official", "spec": {"public_input": {"k": 1}}, "artifact": {"val": -1}, "expected_status": "OK", "expected_verdict": "FAIL"},
            ],
        )

        # v1
        _write_file(
            inst_file,
            """
from core_python.evaluators.base_instrument import get_public_input
def evaluate(artifact, spec, tier="official"):
    _ = get_public_input(spec)
    v = artifact.get("val", -1) if isinstance(artifact, dict) else -1
    return {"status": "OK", "verdict": "PASS" if v > 0 else "FAIL", "tracks": {"impl": "v1_impl"}, "details": "v1"}
""",
        )
        reg = self._call(
            "register_question_instrument", "works_engineer", "sw",
            question_id="Q1", instrument_id="inst_ev", instrument_role="VERDICT",
            instrument_rel_path="evaluators/evolve_inst.py",
            calibration_suite_rel_path="evaluators/_hidden_calibrations/cal_evolve.json",
            artifact_schema="python_run", plugin_protocol_version="v3",
            default_spec={"public_input": {"k": 1}},
        )
        self.assertTrue(reg["ok"], reg)
        bid, nid, wt = self._make_branch("fam_ev")
        _write_file(wt / "cand.py", "def run(spec):\n    return {'val': 10}\n")
        ev1 = self._call(
            "run_isolated_eval", "explorer", "se",
            node_id=nid, question_id="Q1", instrument_id="inst_ev", tier="official",
            artifact_rel_path="cand.py", linguistic_prediction="仪器v1首次基线测试预期通过", declared_refs=[],
        )
        self.assertTrue(ev1["ok"], ev1)
        obs1 = ev1["data"]["obs_id"]
        self.assertEqual(ev1["data"]["tracks"]["impl"], "v1_impl")

        # 升 v2（不处理队列）
        _write_file(
            inst_file,
            """
from core_python.evaluators.base_instrument import get_public_input
def evaluate(artifact, spec, tier="official"):
    _ = get_public_input(spec)
    v = artifact.get("val", -1) if isinstance(artifact, dict) else -1
    return {"status": "OK", "verdict": "PASS" if v > 0 else "FAIL", "tracks": {"impl": "v2_impl"}, "details": "v2"}
""",
        )
        up2 = self._call(
            "upgrade_instrument_with_calibration", "works_engineer", "sw",
            question_id="Q1", instrument_id="inst_ev",
            new_instrument_rel_path="evaluators/evolve_inst.py",
            calibration_suite_rel_path="evaluators/_hidden_calibrations/cal_evolve.json",
        )
        self.assertTrue(up2["ok"], up2)

        # 立即再升 v3（中间 v2 队列仍为 PENDING）
        _write_file(
            inst_file,
            """
from core_python.evaluators.base_instrument import get_public_input
def evaluate(artifact, spec, tier="official"):
    _ = get_public_input(spec)
    v = artifact.get("val", -1) if isinstance(artifact, dict) else -1
    return {"status": "OK", "verdict": "PASS" if v > 0 else "FAIL", "tracks": {"impl": "v3_impl"}, "details": "v3"}
""",
        )
        up3 = self._call(
            "upgrade_instrument_with_calibration", "works_engineer", "sw",
            question_id="Q1", instrument_id="inst_ev",
            new_instrument_rel_path="evaluators/evolve_inst.py",
            calibration_suite_rel_path="evaluators/_hidden_calibrations/cal_evolve.json",
        )
        self.assertTrue(up3["ok"], up3)

        # 队列中的 PENDING 单应已收敛到 target_version == 3
        q_row = self.conn.execute(
            "SELECT target_version, status FROM pending_revalidation_queue WHERE obs_id = ? AND status = 'PENDING'",
            (obs1,),
        ).fetchone()
        self.assertIsNotNone(q_row)
        self.assertEqual(q_row["target_version"], 3)

        # 即使把工作区原文件改成无关垃圾，重评仍必须读取冻结的 v3 快照并记录 instrument_version == 3
        _write_file(inst_file, "def evaluate(a, s, tier='official'): return {'status':'OK','verdict':'PASS','tracks':{'impl':'POLLUTED'},'details':'bad'}\n")
        rec = self._call("recompute_stage_b_only", "works_engineer", "sw", obs_id=obs1, question_id="Q1")
        self.assertTrue(rec["ok"], rec)
        new_obs_id = rec["data"]["new_obs_id"]
        new_obs = self.conn.execute("SELECT instrument_version, tracks_json FROM observations WHERE obs_id = ?", (new_obs_id,)).fetchone()
        self.assertEqual(new_obs["instrument_version"], 3)
        self.assertEqual(json.loads(new_obs["tracks_json"])["impl"], "v3_impl")

        # 升 v4：仪器内部本地字典触发 KeyError，绝不能误判历史产物 INCOMPATIBLE
        _write_file(
            inst_file,
            """
from core_python.evaluators.base_instrument import get_public_input
def evaluate(artifact, spec, tier="official"):
    _ = get_public_input(spec)
    v = artifact.get("val", -1) if isinstance(artifact, dict) else -1
    if v == 10:
        local_cfg = {"a": 1}
        _ = local_cfg["missing_internal_key"]
    return {"status": "OK", "verdict": "PASS" if v > 0 else "FAIL", "tracks": {"impl": "v4_impl"}, "details": "v4"}
""",
        )
        _write_json(
            cal_file,
            [
                {"case_id": "p", "tier": "official", "spec": {"public_input": {"k": 1}}, "artifact": {"val": 5}, "expected_status": "OK", "expected_verdict": "PASS"},
                {"case_id": "n", "tier": "official", "spec": {"public_input": {"k": 1}}, "artifact": {"val": -1}, "expected_status": "OK", "expected_verdict": "FAIL"},
            ],
        )
        up4 = self._call(
            "upgrade_instrument_with_calibration", "works_engineer", "sw",
            question_id="Q1", instrument_id="inst_ev",
            new_instrument_rel_path="evaluators/evolve_inst.py",
            calibration_suite_rel_path="evaluators/_hidden_calibrations/cal_evolve.json",
        )
        self.assertTrue(up4["ok"], up4)
        rec4 = self._call("recompute_stage_b_only", "works_engineer", "sw", obs_id=new_obs_id, question_id="Q1")
        self.assertTrue(rec4["ok"], rec4)
        self.assertEqual(rec4["data"]["status"], "INSTRUMENT_ERROR")
        obs3_after = self.conn.execute("SELECT obs_status FROM observations WHERE obs_id = ?", (new_obs_id,)).fetchone()
        self.assertNotEqual(obs3_after["obs_status"], "INCOMPATIBLE")

        # 篡改冻结快照文件时必须 fail-closed 拦截
        snap_row = self.conn.execute(
            "SELECT frozen_snapshot_path FROM instruments WHERE instrument_id = 'inst_ev' AND version = 4"
        ).fetchone()
        Path(snap_row["frozen_snapshot_path"]).write_text("# tampered\n", encoding="utf-8")
        tampered = self._call("recompute_stage_b_only", "works_engineer", "sw", obs_id=new_obs_id, question_id="Q1")
        self.assertFalse(tampered["ok"])
        self.assertEqual(tampered["error_code"], db.ERR_INVARIANT)

    def test_8_stage3_export_guards_closed_locked_cross_question_empty_full_and_missing_artifact(self) -> None:
        # 设为多子题以便测试串题拦截，先按正规盲审路径产生 Q1 的 FULL_GOAL L3
        with db.rw_immediate_tx(self.conn):
            self.conn.execute("UPDATE parse0_contract SET subquestions_json = '[\"Q1\", \"Q2\"]'")
        b1, n1, wt1 = self._make_branch("fam_s3_q1")
        _write_file(wt1 / "q1_solve.py", "print('q1')\n")
        self.assertTrue(
            self._call(
                "submit_node_handoff", "lineage_companion", "sc",
                node_id=n1, branch_id=b1, question_id="Q1",
                mechanism_summary="Q1完整解", evidence_grade="ARTIFACT_ONLY",
                column_a_facts_md="推导完整并产出 q1_solve.py", column_b_hypothesis_md="无",
                will_md="可直接送审", obs_ids=[], dead_ends=[],
                candidate_rel_path="q1_solve.py", is_empty_crash=False,
            )["ok"]
        )
        rid = self._call(
            "triage_node", "logistics_coordinator", "sl",
            node_id=n1, assigned_family_id="fam_s3_q1", triage_level="LEVEL_1",
            action="SUBMIT_BLIND_REVIEW", rationale="送审",
        )["data"]["created_review_id"]
        self._call("get_blind_manuscript", "library_verifier", "sv1", review_id=rid)
        self._call(
            "submit_stage1_blind_ledger", "library_verifier", "sv1",
            review_id=rid, question_id="Q1",
            ledger_items=[{"claim": "构造成立", "evidence_location_and_quote": "q1_solve.py L1", "status": "VERIFIED"}],
            stage1_verdict="PASS",
            rigor_score=8,
        )
        self._call("get_unblinded_manuscript_and_peers", "library_verifier", "sv1", review_id=rid)
        s2 = self._call(
            "submit_stage2_unblind_verdict", "library_verifier", "sv1",
            review_id=rid, final_verdict="ACCEPT", novelty_score=8, significance_score=8, l3_entry_kind="POS_THEOREM", goal_coverage="FULL_GOAL",
            title="Q1 完整定理",
            abstract_md="完整证明 Q1 主命题并给出了可执行脚本 q1_solve.py，经独立盲审沙箱复现核验确认逻辑无漏洞且边界条件与题面定义严格吻合。",
            exact_verified_scope_md="Q1 全域",
        )
        self.assertTrue(s2["ok"], s2)
        l3_q1 = s2["data"]["created_l3_id"]
        paper_md = "# 正式研究报告\n本报告完整汇总 Q1 主定理的严格证明与最小复现套件，全部引用均已溯源核验且无任何越界断言。\n"

        # 退回到单题 Q1 以便验证其他门禁
        with db.rw_immediate_tx(self.conn):
            self.conn.execute("UPDATE parse0_contract SET subquestions_json = '[\"Q1\"]'")

        # 1) FULL 模式空壳 {} 必须被拦截
        r_empty = self._call(
            "export_stage3_final_delivery", "library_chronicler", "ss",
            delivery_mode="FULL", selected_l3_ids_by_question={}, formal_paper_md=paper_md,
            remaining_gaps_by_question={"Q1": ""}, reproduction_candidate_nodes=[n1],
        )
        self.assertFalse(r_empty["ok"])
        self.assertEqual(r_empty["error_code"], db.ERR_INVALID_INPUT)

        # 2) 传入未知子题 key 必须被拦截
        r_bad_q = self._call(
            "export_stage3_final_delivery", "library_chronicler", "ss",
            delivery_mode="FULL", selected_l3_ids_by_question={"Q1": [l3_q1], "Q_FAKE": []},
            formal_paper_md=paper_md, remaining_gaps_by_question={"Q1": ""},
            reproduction_candidate_nodes=[n1],
        )
        self.assertFalse(r_bad_q["ok"])
        self.assertEqual(r_bad_q["error_code"], db.ERR_INVALID_INPUT)

        # 3) 串题挂载：把 Q1 的 L3 挂到 Q2 下必须被拦截（先满足预算耗尽以测试 PARTIAL_ON_BUDGET）
        with db.rw_immediate_tx(self.conn):
            self.conn.execute("UPDATE parse0_contract SET subquestions_json = '[\"Q1\", \"Q2\"]', total_budget_json = '{\"max_total_handoffs\": 1}'")
        r_cross = self._call(
            "export_stage3_final_delivery", "library_chronicler", "ss",
            delivery_mode="PARTIAL_ON_BUDGET",
            selected_l3_ids_by_question={"Q1": [l3_q1], "Q2": [l3_q1]},
            formal_paper_md=paper_md, remaining_gaps_by_question={"Q1": "", "Q2": "未解"},
            reproduction_candidate_nodes=[n1],
        )
        self.assertFalse(r_cross["ok"])
        self.assertEqual(r_cross["error_code"], db.ERR_INVALID_INPUT)

        # 4) 复现包声明文件在工作树与托管快照均丢失时必须报错，不得静默空复制
        with db.rw_immediate_tx(self.conn):
            self.conn.execute("UPDATE parse0_contract SET subquestions_json = '[\"Q1\"]'")
        snap_row = self.conn.execute("SELECT retained_snapshot_abs_path FROM lineage_nodes WHERE node_id = ?", (n1,)).fetchone()
        snap_file = Path(str(snap_row["retained_snapshot_abs_path"])) / "q1_solve.py" if snap_row and snap_row["retained_snapshot_abs_path"] else None
        (wt1 / "q1_solve.py").unlink()
        if snap_file and snap_file.exists():
            snap_file.unlink()
        r_missing = self._call(
            "export_stage3_final_delivery", "library_chronicler", "ss",
            delivery_mode="FULL", selected_l3_ids_by_question={"Q1": [l3_q1]},
            formal_paper_md=paper_md, remaining_gaps_by_question={"Q1": ""},
            reproduction_candidate_nodes=[n1],
        )
        self.assertFalse(r_missing["ok"])
        self.assertEqual(r_missing["error_code"], db.ERR_NOT_FOUND)

        # 5) 恢复工作树复现脚本、导出并一步终签 CLOSED_VERIFIED 后，严禁再次重导倒退状态
        _write_file(wt1 / "q1_solve.py", "print('q1')\n")
        if snap_file:
            _write_file(snap_file, "print('q1')\n")
        r_ok = self._call(
            "export_stage3_final_delivery", "library_chronicler", "ss",
            delivery_mode="FULL", selected_l3_ids_by_question={"Q1": [l3_q1]},
            formal_paper_md=paper_md, remaining_gaps_by_question={"Q1": ""},
            reproduction_candidate_nodes=[n1],
        )
        self.assertTrue(r_ok["ok"], r_ok)
        did = r_ok["data"]["delivery_id"]
        fin = self._call(
            "submit_stage2_unblind_verdict", "library_verifier", "sv_fin",
            review_id=f"STAGE3_FINAL_AUDIT:{did}", final_verdict="ACCEPT",
        )
        self.assertTrue(fin["ok"], fin)
        self.assertEqual(fin["data"]["closure_status"], "CLOSED_VERIFIED")
        r_reexport = self._call(
            "export_stage3_final_delivery", "library_chronicler", "ss",
            delivery_mode="FULL", selected_l3_ids_by_question={"Q1": [l3_q1]},
            formal_paper_md=paper_md + "\n试图覆盖已终签终稿\n",
            remaining_gaps_by_question={"Q1": ""}, reproduction_candidate_nodes=[n1],
        )
        self.assertFalse(r_reexport["ok"])
        self.assertEqual(r_reexport["error_code"], db.ERR_LOCKED)

    def test_9_budget_exhaustion_stops_dispatch_supports_wall_clock_and_migrates_legacy_closure_table(self) -> None:
        # 1) 时间预算 max_wall_clock_sec 耗尽时，不再派发新探索者/看板
        bid, nid, _ = self._make_branch("fam_wc")
        with db.rw_immediate_tx(self.conn):
            self.conn.execute(
                "UPDATE parse0_contract SET total_budget_json = '{\"max_wall_clock_sec\": 1}', human_signed_at = '2020-01-01T00:00:00Z'"
            )
        snap = cp.schedule_control_plane_snapshot(self.conn)
        self.assertTrue(snap["closure_gate"]["closure_allowed"])
        self.assertEqual(snap["closure_gate"]["gate_code"], "GATE_PASSED_PARTIAL_BUDGET")
        self.assertEqual(snap["explorers_needing_briefing"], [])
        self.assertEqual(snap["explorers_ready_to_run"], [])

        # 2) 早期 v3 数据库缺 REVISION_REQUESTED 的 CHECK 约束，init_database_schema 自动迁移后可正常写入
        mem = sqlite3.connect(":memory:")
        mem.row_factory = sqlite3.Row
        db.init_database_schema(mem)
        # 人为回退 project_closure_state 为缺少 REVISION_REQUESTED 的旧表结构
        mem.execute("DROP TABLE project_closure_state;")
        mem.execute(
            """
            CREATE TABLE project_closure_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                status TEXT NOT NULL DEFAULT 'OPEN'
                    CHECK (status IN ('OPEN', 'EXPORTED_PENDING_REVIEW', 'CLOSED_VERIFIED')),
                delivery_mode TEXT NOT NULL DEFAULT 'NONE',
                report_path TEXT NOT NULL DEFAULT '',
                report_sha256 TEXT NOT NULL DEFAULT '',
                manifest_path TEXT NOT NULL DEFAULT '',
                review_session_id TEXT NOT NULL DEFAULT '',
                review_verdict TEXT NOT NULL DEFAULT '',
                review_critique_md TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );
            """
        )
        mem.execute("INSERT INTO project_closure_state (id, status, updated_at) VALUES (1, 'OPEN', '2026-01-01T00:00:00Z');")
        mem.commit()

        db.init_database_schema(mem)
        mem.execute("UPDATE project_closure_state SET status = 'REVISION_REQUESTED' WHERE id = 1;")
        row = mem.execute("SELECT status FROM project_closure_state WHERE id = 1;").fetchone()
        self.assertEqual(row["status"], "REVISION_REQUESTED")
        mem.close()

    def test_10_readonly_snapshot_no_side_effect_and_empty_goal_rejected(self) -> None:
        # 1) 对从未初始化的新工作区调用只读 schedule_snapshot 绝不可创建数据目录或空库
        fresh_ws = Path(self._tmp.name) / "never_initialized_ws"
        fresh_ws.mkdir(parents=True, exist_ok=True)
        probe_paths = db.resolve_storage_paths(str(fresh_ws), create_dirs=False)
        self.assertFalse(probe_paths["data_dir"].exists())

        snap_res = mcp.dispatch_control_call("control_plane/schedule_snapshot", {"workspace_root": str(fresh_ws)})
        self.assertTrue(snap_res["ok"], snap_res)
        self.assertFalse(snap_res["data"]["initialized"])
        self.assertFalse(snap_res["data"]["parse0_signed"])
        self.assertFalse(probe_paths["data_dir"].exists(), "只读 status/snapshot 严禁在磁盘上创建空目录或空库")
        self.assertFalse(probe_paths["db_path"].exists())

        # 2) init_parse0 传入空白 goal_and_completion_md 必须被拒
        bad_init = mcp.dispatch_control_call(
            "control_plane/init_parse0",
            {"workspace_root": str(fresh_ws), "goal_and_completion_md": "   ", "subquestions": ["Q1"]},
        )
        self.assertFalse(bad_init["ok"])
        self.assertEqual(bad_init["error_code"], db.ERR_INVALID_INPUT)

        # 3) Stage 2 人在环路修订 Parse 0（更新目标/预算，不传 stage）必须成功且保留 STAGE2_EVOLVE 不倒退
        upd = mcp.dispatch_control_call(
            "control_plane/init_parse0",
            {
                "workspace_root": str(self.ws),
                "goal_and_completion_md": "# Goal (Revised)\n人类中途补充口径说明并扩容预算。",
                "subquestions": ["Q1"],
                "total_budget": {"max_total_handoffs": 50},
            },
        )
        self.assertTrue(upd["ok"], upd)
        self.assertEqual(upd["data"]["stage"], "STAGE2_EVOLVE")
        snap_after = cp.schedule_control_plane_snapshot(self.conn)
        self.assertEqual(snap_after["stage"], "STAGE2_EVOLVE")
        self.assertIn("人类中途补充口径说明", snap_after["goal_and_completion_md"])


if __name__ == "__main__":
    unittest.main()
