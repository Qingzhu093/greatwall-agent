"""Round 4 P0/P1 内核安全漏洞、门禁与截断专项验收测试。

覆盖 Hard Gate #1 全量新增点：
1. caller_role / session_id / workspace_root 伪造参数丢弃（宿主 _meta 不可覆写）；
2. 空 session_id 盲审拦截 (SELF_REVIEW_FORBIDDEN)；
3. get_blind_manuscript 携带引用卡片与 read_depth + get_library_entry 剥离 L2 method_family_id；
4. publish_external_literature_card 仅按 fulfilled_request_ids 精准核销；
5. Stage 2 禁止 register_question_domain_hook 静默覆盖；
6. RQGM Q_P 对抗池精确计算 (p_+, p_-, r_P) 与阻断退化/平局升级；
7. 37% Token 水位服务端硬校验 + submit_node_handoff bound_obs_ids_json 落库；
8. update_skill_ledger 写向工作区隔离路径（绝不写脏仓库源码）；
9. trg_reviews_lock_final 终审不可篡改 + DEPENDS_ON 三分类级联 propagate_dependency_recheck；
10. depends_on_questions 前置依赖拦截 + 消除 [:220] 硬截断 + public_input_sample 自动注入。
"""

from __future__ import annotations

import json
import os
import pathlib
import sqlite3
import tempfile
import unittest
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE_PYTHON = PROJECT_ROOT / "core_python"
if str(CORE_PYTHON) not in sys.path:
    sys.path.insert(0, str(CORE_PYTHON))

from mcp_server.control_plane_service import extract_sanitized_code_diff_md, schedule_control_plane_snapshot  # noqa: E402
from mcp_server.db_schema import (  # noqa: E402
    ERR_CONFLICT,
    ERR_INVARIANT,
    ERR_LOCKED,
    open_ro_connection,
    open_rw_connection,
    propagate_dependency_recheck,
    resolve_storage_paths,
)
from mcp_server.greatwall_core_mcp import dispatch_control_call, dispatch_tool_call  # noqa: E402


class TestRound4P0Gates(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="gw_r4_p0_")
        self.ws = pathlib.Path(self._tmp.name) / "ws"
        self.data_dir = pathlib.Path(self._tmp.name) / "plugin_data"
        self.ws.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._old_plugin_data = os.environ.get("PLUGIN_DATA")
        os.environ["PLUGIN_DATA"] = str(self.data_dir)
        self._ledger_src = CORE_PYTHON / "skills" / "SKILL_LEDGER.json"
        self._orig_ledger_bytes = self._ledger_src.read_bytes()

        (self.ws / "evaluators").mkdir(parents=True, exist_ok=True)
        (self.ws / "baselines" / "Q1").mkdir(parents=True, exist_ok=True)
        (self.ws / "baselines" / "Q2").mkdir(parents=True, exist_ok=True)
        (self.ws / "baselines" / "Q1" / "b1.py").write_text("X = 1\n", encoding="utf-8")
        (self.ws / "baselines" / "Q2" / "b2.py").write_text("X = 2\n", encoding="utf-8")
        (self.ws / "evaluators" / "hook_q1.py").write_text(
            "def evaluate_candidate(art, spec):\n"
            "    val = float(art.get('val', 0.0))\n"
            "    return {'passed': val >= 1.0, 'metrics': {'rank_score': val}, 'details': f'val={val}'}\n",
            encoding="utf-8",
        )
        (self.ws / "evaluators" / "hook_q2_v1.py").write_text(
            "def evaluate_candidate(art, spec):\n"
            "    s = float(art.get('s', 0.0))\n"
            "    return {'passed': 0.40 <= s <= 1.20, 'metrics': {'rank_score': s}, 'details': f'v1={s}'}\n",
            encoding="utf-8",
        )
        # 故意写一个正样本多通过 1 个（提高 BB_eps），但去掉上限导致对抗高分例被放行从而 Q_P 下降的作弊 challenger
        (self.ws / "evaluators" / "hook_q2_adv_bad.py").write_text(
            "def evaluate_candidate(art, spec):\n"
            "    s = float(art.get('s', 0.0))\n"
            "    return {'passed': s >= 0.40, 'metrics': {'rank_score': s}, 'details': f'adv_bad={s}'}\n",
            encoding="utf-8",
        )
        # 真正同时提升 BB_eps 与 Q_P 的严格版本
        (self.ws / "evaluators" / "hook_q2_good.py").write_text(
            "def evaluate_candidate(art, spec):\n"
            "    s = float(art.get('s', 0.0))\n"
            "    return {'passed': 0.75 <= s <= 1.30, 'metrics': {'rank_score': s}, 'details': f'good={s}'}\n",
            encoding="utf-8",
        )
        (self.ws / "evaluators" / "anchors" / "Q2").mkdir(parents=True, exist_ok=True)
        (self.ws / "evaluators" / "anchors" / "Q2" / "cases.json").write_text(
            json.dumps(
                [
                    {"stage_a_artifact": {"s": 0.80}, "expected_passed": True, "is_adversarial": False},
                    {"stage_a_artifact": {"s": 0.85}, "expected_passed": True, "is_adversarial": False},
                    {"stage_a_artifact": {"s": 0.90}, "expected_passed": True, "is_adversarial": False},
                    {"stage_a_artifact": {"s": 1.25}, "expected_passed": True, "is_adversarial": False},
                    {"stage_a_artifact": {"s": 0.35}, "expected_passed": False, "is_adversarial": False},
                    {"stage_a_artifact": {"s": 0.50}, "expected_passed": False, "is_adversarial": True},
                    {"stage_a_artifact": {"s": 2.00}, "expected_passed": False, "is_adversarial": True},
                ]
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        if self._old_plugin_data is None:
            os.environ.pop("PLUGIN_DATA", None)
        else:
            os.environ["PLUGIN_DATA"] = self._old_plugin_data
        self._ledger_src.write_bytes(self._orig_ledger_bytes)
        self._tmp.cleanup()

    def _call(self, tool: str, role: str, sid: str, **args) -> dict:
        return dispatch_tool_call(tool, args, workspace_root=str(self.ws), caller_role=role, session_id=sid)

    def test_role_spoofing_blocked_and_skill_ledger_isolated(self) -> None:
        dispatch_control_call("control_plane/init_epoch", {"workspace_root": str(self.ws), "required_questions": ["Q1"]})
        # 模型在 arguments 里企图伪造 caller_role="works_engineer"，宿主 _meta 固定是 explorer -> 必须被 RBAC 拒绝
        spoofed = dispatch_tool_call(
            "register_question_domain_hook",
            {
                "caller_role": "works_engineer",
                "session_id": "sess_we_fake",
                "question_id": "Q1",
                "hook_rel_path": "evaluators/hook_q1.py",
                "baseline_rel_path": "baselines/Q1/b1.py",
                "fidelity_max_error_pct": 1.0,
                "_meta": {"workspace_root": str(self.ws), "caller_role": "explorer", "session_id": "sess_exp_real"},
            },
        )
        self.assertFalse(spoofed["ok"])

        # update_skill_ledger 写向 PLUGIN_DATA 工作区隔离目录，源码目录零修改
        res = self._call(
            "update_skill_ledger",
            "works_engineer",
            "sess_we_1",
            skill_id="r4_isolated_probe",
            applicable_scope="R4 isolation test",
            version=1,
            raw_success_count=3,
            raw_failure_count=0,
            verified_artifact_rel_path="evaluators/hook_q1.py",
            rollback_pointer="none",
        )
        self.assertTrue(res["ok"], res)
        self.assertEqual(self._ledger_src.read_bytes(), self._orig_ledger_bytes)
        isolated_path = resolve_storage_paths(str(self.ws))["skill_ledger_path"]
        self.assertTrue(pathlib.Path(isolated_path).is_file())
        self.assertIn("r4_isolated_probe", json.loads(pathlib.Path(isolated_path).read_text(encoding="utf-8"))["skills"])

    def test_contract_sample_injection_no_truncation_and_37pct_hard_gate(self) -> None:
        ws_str = str(self.ws)
        dispatch_control_call(
            "control_plane/init_epoch",
            {
                "workspace_root": ws_str,
                "goal_md": "REAL GOAL Q1 -> Q2",
                "required_questions": ["Q1", "Q2"],
                "contracts": {"Q2": {"depends_on_questions": ["Q1"]}},
                "stage": "STAGE1_PARSE0",
            },
        )
        # 注册钩子附带 public_input_sample
        self.assertTrue(
            self._call(
                "register_question_domain_hook",
                "works_engineer",
                "sess_we_1",
                question_id="Q1",
                hook_rel_path="evaluators/hook_q1.py",
                baseline_rel_path="baselines/Q1/b1.py",
                fidelity_max_error_pct=0.5,
                public_input_sample={"cases": [{"id": "c1", "x": 42}]},
            )["ok"]
        )
        self.assertTrue(
            self._call(
                "register_question_domain_hook",
                "works_engineer",
                "sess_we_1",
                question_id="Q2",
                hook_rel_path="evaluators/hook_q2_v1.py",
                baseline_rel_path="baselines/Q2/b2.py",
                fidelity_max_error_pct=0.5,
            )["ok"]
        )

        # dashboard 能看到 goal_md 与 question_dependencies
        dash = self._call("get_logistics_dashboard", "logistics_coordinator", "sess_log_1", question_id="ALL")
        self.assertTrue(dash["ok"])
        self.assertEqual(dash["data"]["epoch_config"]["goal_md"], "REAL GOAL Q1 -> Q2")
        self.assertFalse(dash["data"]["question_dependencies"]["Q2"]["unlocked"])

        # Q2 依赖 Q1 的 L3，未解锁前禁止 fork_branch Q2
        self.assertTrue(
            self._call(
                "register_method_family",
                "logistics_coordinator",
                "sess_log_1",
                question_id="Q2",
                family_id="fam_q2_dep",
                mechanism_signature="依赖 Q1 黄金基线的 Q2 学派",
                orthogonal_contrast="等待 Q1",
                depends_on_questions=["Q1"],
            )["ok"]
        )
        blk = self._call("fork_branch", "logistics_coordinator", "sess_log_1", question_id="Q2", fork_mode="orthogonal", target_family_id="fam_q2_dep")
        self.assertFalse(blk["ok"])
        self.assertEqual(blk["error_code"], ERR_LOCKED)

        # 注册 Q1 学派并派分支
        self.assertTrue(
            self._call(
                "register_method_family",
                "logistics_coordinator",
                "sess_log_1",
                question_id="Q1",
                family_id="fam_q1_a",
                mechanism_signature="Q1 主求解学派",
                orthogonal_contrast="独立",
            )["ok"]
        )
        fb = self._call("fork_branch", "logistics_coordinator", "sess_log_1", question_id="Q1", fork_mode="orthogonal", target_family_id="fam_q1_a")
        self.assertTrue(fb["ok"])
        nid = fb["data"]["node_id"]
        bid = fb["data"]["branch_id"]
        wt = pathlib.Path(fb["data"]["worktree_abs_path"])

        # 候选强制要求读取注入的 public_input.cases（不允许本地写死 fallback）
        long_lines = "\n".join(f"    # line_{i}" for i in range(260))
        (wt / "src" / "cand.py").write_text(
            "def run(public_input):\n"
            "    cases = public_input.get('cases')\n"
            "    if not cases:\n"
            "        raise ValueError('missing cases')\n"
            f"{long_lines}\n"
            "    return {'val': float(cases[0]['x']) / 21.0}\n",
            encoding="utf-8",
        )
        # 不手动传 evaluator_spec.public_input -> 服务端自动注入注册好的 public_input_sample！
        ev = self._call(
            "run_isolated_eval",
            "explorer",
            "sess_exp_q1",
            node_id=nid,
            question_id="Q1",
            candidate_rel_path="src/cand.py",
            linguistic_prediction="预期自动注入 public_input 并返回 val=2.0, rank_score=2.0",
        )
        self.assertTrue(ev["ok"], ev)
        self.assertEqual(ev["data"]["obs_status"], "VALID")
        self.assertEqual(ev["data"]["comparable_rank_score"], 2.0)
        obs_id = ev["data"]["obs_id"]

        # 无 220 行硬截断
        diff_md = extract_sanitized_code_diff_md(str(wt), "src/cand.py", "", bid, nid)
        self.assertIn("line_259", diff_md)

        # 37% 服务端水位硬拦截（当前 pressure_tokens=0 < 185000）
        ref_blocked = self._call(
            "record_reflection_and_unlock_pull",
            "lineage_companion",
            "sess_comp_1",
            node_id=nid,
            selected_categories=["7. Attractor Tasks"],
            holiday_prompt_id=1,
            turns=[{"question": "是否达37%?", "answer": "测试拦截。"}],
            verdict_3state="SUFFICIENT_EVIDENCE",
        )
        self.assertFalse(ref_blocked["ok"])
        self.assertEqual(ref_blocked["error_code"], ERR_LOCKED)

        # 推高水位至 >= 185000 后解锁成功
        dispatch_control_call("control_plane/sync_pressure", {"workspace_root": ws_str, "node_id": nid, "pressure_tokens": 186000})
        self.assertTrue(
            self._call(
                "record_reflection_and_unlock_pull",
                "lineage_companion",
                "sess_comp_1",
                node_id=nid,
                selected_categories=["7. Attractor Tasks"],
                holiday_prompt_id=1,
                turns=[{"question": "是否达37%?", "answer": "已过185k并有实测。"}],
                verdict_3state="SUFFICIENT_EVIDENCE",
            )["ok"]
        )

        # 交接校验 bound_obs_ids_json 落库
        ho = self._call(
            "submit_node_handoff",
            "lineage_companion",
            "sess_comp_1",
            node_id=nid,
            branch_id=bid,
            question_id="Q1",
            column_a_facts_md=f"依 [{obs_id}] 验证 val=2.0。",
            column_b_hypothesis_md="理论模型闭环自洽。",
            will_md="建议提交盲审。",
            obs_ids=[obs_id],
            candidate_rel_path="src/cand.py",
        )
        self.assertTrue(ho["ok"], ho)
        conn = open_ro_connection(resolve_storage_paths(ws_str)["db_path"])
        try:
            row = conn.execute("SELECT bound_obs_ids_json FROM lineage_nodes WHERE node_id = ?", (nid,)).fetchone()
            self.assertEqual(json.loads(row["bound_obs_ids_json"]), [obs_id])
        finally:
            conn.close()

    def test_blind_review_survey_stage2_hook_lock_rqgm_qp_and_depends_cascade(self) -> None:
        ws_str = str(self.ws)
        dispatch_control_call("control_plane/init_epoch", {"workspace_root": ws_str, "required_questions": ["Q1", "Q2"], "stage": "STAGE2_EVOLVE"})
        self.assertTrue(
            self._call(
                "register_question_domain_hook",
                "works_engineer",
                "sess_we_1",
                question_id="Q2",
                hook_rel_path="evaluators/hook_q2_v1.py",
                baseline_rel_path="baselines/Q2/b2.py",
                fidelity_max_error_pct=0.5,
            )["ok"]
        )
        # STAGE2 下禁止再用 register_question_domain_hook 静默覆盖既有钩子
        ov = self._call(
            "register_question_domain_hook",
            "works_engineer",
            "sess_we_1",
            question_id="Q2",
            hook_rel_path="evaluators/hook_q2_good.py",
            baseline_rel_path="baselines/Q2/b2.py",
            fidelity_max_error_pct=0.5,
        )
        self.assertFalse(ov["ok"])
        self.assertEqual(ov["error_code"], ERR_LOCKED)

        # RQGM Q_P 门禁：hook_q2_adv_bad 虽然通过了一部分但 Q_P 未严格超越（且 r_p 没拉开）-> 拦截！
        bad_up = self._call(
            "upgrade_hook_with_rqgm_gate",
            "works_engineer",
            "sess_we_1",
            question_id="Q2",
            new_hook_rel_path="evaluators/hook_q2_adv_bad.py",
            gt_success_count=10,
            gt_failure_count=0,
        )
        self.assertFalse(bad_up["ok"])
        self.assertEqual(bad_up["error_code"], ERR_INVARIANT)

        # 严格提升 BB_eps 与 Q_P 的 hook_q2_good 通过
        good_up = self._call(
            "upgrade_hook_with_rqgm_gate",
            "works_engineer",
            "sess_we_1",
            question_id="Q2",
            new_hook_rel_path="evaluators/hook_q2_good.py",
            gt_success_count=10,
            gt_failure_count=0,
        )
        self.assertTrue(good_up["ok"], good_up)

        # publish_external_literature_card 仅精确核销指定 request_id，不误消同题其它单
        self._call("register_method_family", "logistics_coordinator", "sess_log_1", question_id="Q1", family_id="fam_s", mechanism_signature="S1", orthogonal_contrast="O1")
        fb = self._call("fork_branch", "logistics_coordinator", "sess_log_1", question_id="Q1", fork_mode="orthogonal", target_family_id="fam_s")
        nid = fb["data"]["node_id"]
        sr1 = self._call("request_literature_survey", "explorer", "sess_e1", node_id=nid, question_id="Q1", topic_query="T1", reason="R1")
        sr2 = self._call("request_literature_survey", "explorer", "sess_e1", node_id=nid, question_id="Q1", topic_query="T2", reason="R2")
        req1_id = sr1["data"]["request_id"]
        req2_id = sr2["data"]["request_id"]
        pub = self._call(
            "publish_external_literature_card",
            "library_surveyor",
            "sess_surv",
            ref_id="R010",
            question_id="Q1",
            title="Exact Bounds",
            abstract_md="本文建立并严格证明了指定约束集合上的精确不变量收敛上界定理，完整推导并分析了所有正则化边界条件与极限行为，可直接用于下游校验。",
            exact_preconditions_md="光滑流形边界",
            formulas_or_operators_md="||x|| <= C",
            read_depth="full_text",
            support_scope="DIRECT_PROOF_OR_EXACT_MEASUREMENT",
            source_citation="Doe 2025",
            fulfilled_request_ids=[req1_id],
        )
        self.assertTrue(pub["ok"])
        reqs = self._call("get_survey_requests", "library_surveyor", "sess_surv", question_id="Q1")
        pending_ids = [r["request_id"] for r in reqs["data"]["pending_requests"]]
        self.assertNotIn(req1_id, pending_ids)
        self.assertIn(req2_id, pending_ids)

        # 测试空 session_id 盲审拦截、引用卡片附带与 trg_reviews_lock_final 终审锁
        db_path = resolve_storage_paths(ws_str)["db_path"]
        conn = open_rw_connection(db_path, init_schema=True)
        try:
            conn.execute(
                "INSERT INTO review_queue(review_id, source_node_id, question_id, source_type, proposer_session_id, review_status, manuscript_title, column_a_snapshot_md, column_b_snapshot_md, sanitized_code_diff_md, bound_obs_ids_json, created_at) VALUES ('rev_901', ?, 'Q1', 'LEVEL1_MANUSCRIPT', 'sess_e1', 'STAGE1_BLIND', 'Title', '依据 [R010] 得到上界', 'Mech', 'diff', '[]', '2026-01-01T00:00:00Z')",
                (nid,),
            )
        finally:
            conn.close()

        empty_sid = self._call("get_blind_manuscript", "library_verifier", "", review_id="rev_901")
        self.assertFalse(empty_sid["ok"])
        self.assertEqual(empty_sid["error_code"], ERR_CONFLICT)

        blind_ok = self._call("get_blind_manuscript", "library_verifier", "sess_ver_9", review_id="rev_901")
        self.assertTrue(blind_ok["ok"], blind_ok)
        refs_in_blind = blind_ok["data"]["referenced_library_cards"]
        self.assertTrue(any(c.get("ref_id") == "R010" and c.get("read_depth") == "full_text" for c in refs_in_blind))

        # Stage 1 -> Stage 2 PASS 后 trg_reviews_lock_final 永久锁死终审结论 + L2 get_library_entry 剥离 method_family_id
        self.assertTrue(
            self._call(
                "submit_stage1_blind_ledger",
                "library_verifier",
                "sess_ver_9",
                review_id="rev_901",
                question_id="Q1",
                ledger_items=[{"claim": "引用 R010 成立", "evidence_location_and_quote": "R010 full_text", "is_verified": True}],
                stage1_verdict="PASS",
            )["ok"]
        )
        stage2_ver = self._call(
            "submit_stage2_unblind_verdict",
            "library_verifier",
            "sess_ver_9",
            review_id="rev_901",
            final_verdict="PASS",
            title="Verified Upper Bound",
            abstract_md="经过盲审核验的精确上界结论与完整边界限制条件，已对齐外藏 R010 原文前提，可直接供下游模块作为独立前提引用。",
            exact_verified_scope_md="Q1 全可行域",
        )
        self.assertTrue(stage2_ver["ok"], stage2_ver)
        conn = open_rw_connection(db_path, init_schema=False)
        try:
            with self.assertRaises(sqlite3.DatabaseError):
                conn.execute("UPDATE review_queue SET final_verdict = 'REJECT' WHERE review_id = 'rev_901'")

            # 验证 L2 get_library_entry 剥离 method_family_id，并验证 DEPENDS_ON 三分类传播
            conn.execute(
                "INSERT INTO internal_research_ledger(entry_id, question_id, ledger_type, source_type, method_family_id, title, abstract_md, exact_refuted_scope_md, created_at) VALUES ('L2-901', 'Q1', 'L2_FAILURE_RECORD', 'L4A_BARRIER_PROOF', 'secret_fam', 'Fail', 'Failed', 'Scope', '2026-01-01T00:00:00Z')"
            )
            conn.execute("UPDATE lineage_nodes SET pressure_tokens = 200000, eval_count = 1, first_reflection_unlocked = 1 WHERE node_id = ?", (nid,))
            # 插入 L3-902 (REQUIRED_PREMISE -> L3-001) 与 L3-903 (INDEPENDENT_SUPPORT -> L3-001)
            conn.execute("INSERT INTO review_queue(review_id, source_node_id, question_id, source_type, proposer_session_id, review_status, manuscript_title, column_a_snapshot_md, stage1_verdict, stage1_locked_at, final_verdict, final_locked_at, created_at) VALUES ('rev_902', ?, 'Q1', 'LEVEL1_MANUSCRIPT', 'sess_x', 'CLOSED_ACCEPTED_TO_L3', 'T2', 'A2', 'PASS', '2026-01-01T00:00:00Z', 'PASS', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')", (nid,))
            conn.execute("INSERT INTO review_queue(review_id, source_node_id, question_id, source_type, proposer_session_id, review_status, manuscript_title, column_a_snapshot_md, stage1_verdict, stage1_locked_at, final_verdict, final_locked_at, created_at) VALUES ('rev_903', ?, 'Q1', 'LEVEL1_MANUSCRIPT', 'sess_x', 'CLOSED_ACCEPTED_TO_L3', 'T3', 'A3', 'PASS', '2026-01-01T00:00:00Z', 'PASS', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')", (nid,))
            conn.execute("INSERT INTO internal_research_ledger(entry_id, question_id, ledger_type, source_type, title, abstract_md, exact_verified_scope_md, verified_review_id, created_at) VALUES ('L3-902', 'Q1', 'L3_VERIFIED', 'LEVEL1_MANUSCRIPT', 'ReqDep', 'Abs', 'S', 'rev_902', '2026-01-01T00:00:00Z')")
            conn.execute("INSERT INTO internal_research_ledger(entry_id, question_id, ledger_type, source_type, title, abstract_md, exact_verified_scope_md, verified_review_id, created_at) VALUES ('L3-903', 'Q1', 'L3_VERIFIED', 'LEVEL1_MANUSCRIPT', 'Indep', 'Abs', 'S', 'rev_903', '2026-01-01T00:00:00Z')")
            conn.execute("INSERT INTO epistemic_edges(edge_id, src_id, dst_id, edge_track, edge_type, created_at) VALUES ('ce_req', 'L3-902', 'L3-001', 'CLAIM_DECLARED', 'REQUIRED_PREMISE', '2026-01-01T00:00:00Z')")
            conn.execute("INSERT INTO epistemic_edges(edge_id, src_id, dst_id, edge_track, edge_type, created_at) VALUES ('ce_ind', 'L3-903', 'L3-001', 'CLAIM_DECLARED', 'INDEPENDENT_SUPPORT', '2026-01-01T00:00:00Z')")
            prop = propagate_dependency_recheck(conn, ["L3-001"])
            self.assertIn("L3-902", prop["recheck_triggered_entries"])
            self.assertNotIn("L3-903", prop["recheck_triggered_entries"])
            self.assertIn("L3-903", prop["independent_or_motivating_unaffected"])
        finally:
            conn.close()

        l2_entry = self._call("get_library_entry", "explorer", "sess_e1", node_id=nid, entry_id="L2-901")
        self.assertTrue(l2_entry["ok"], l2_entry)
        self.assertNotIn("method_family_id", l2_entry["data"]["entry"])


if __name__ == "__main__":
    unittest.main()
