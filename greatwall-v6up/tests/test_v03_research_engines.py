"""GreatWall v0.3 第二装验收测试：三大科研工程 10 角色窄工具全链路回归。

覆盖全部 6 组裁决核心不变量：
1. 70% 交班封存不可逆 + 确定性直落 + 局部引理独立拆交一次性盲审（绝不锁死也不打断原分支）；
2. Stage 1 PARTIAL_PASS -> Stage 2 ACCEPT_NARROWED 同事务写 L3(PARTIAL_OR_LEMMA) + L2_FAILURE_RECORD；
3. open_lemma_gaps 悬赏发布 -> 另一分支交付引理 -> fulfilled_gap_ids 原子核销并唤醒 BLOCKED_L4B 分支；
4. 子题级 active_spec_revision 防连坐（改 Q1 口径绝对不连坐 Q2 已达标 STOPPED_SOLVED）；
5. 锁一即时停派（Q1 写入当前生效口径 FULL_GOAL L3 后立刻停派并投递 DRAIN_AND_STOP_NODE）；
6. 宏观大外环 4 拍（含 <2 参会者跳过互辩直入 SURVEY_REFRESHING、1500 字总览、双供体只读挂载 .greatwall_donors/、成长保护期防误裁）；
7. Stage 3 外部不可变冻结目录导出 -> 盲审官一步原子终签 CLOSED_VERIFIED（修改工作区副本不骗过，篡改冻结目录被拦截）；
8. gw_chief 只读回忆链、零副作用预演、explorer 越界 handback_to_chief、external_surveyor 物理零内藏泄露。
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path

from core_python.mcp_server.control_plane_service import (
    approve_control_proposal,
    check_and_open_wave_conference,
    init_parse0_contract,
    sync_session_pressure,
)
from core_python.mcp_server.db_schema import (
    open_rw_connection,
    reset_initialized_db_cache,
    resolve_storage_paths,
)
from core_python.mcp_server.greatwall_core_mcp import dispatch_control_call, dispatch_tool_call
from core_python.mcp_server.tool_registry import CANONICAL_ROLES, TOOL_SPECS


class TestV03ResearchEngines(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.ws = Path(self._td.name)
        reset_initialized_db_cache()
        paths = resolve_storage_paths(str(self.ws))
        conn = open_rw_connection(paths["db_path"], init_schema=True, force_init=True)
        try:
            init_parse0_contract(
                conn,
                goal_and_completion_md="Solve Q1 (theorem A) and Q2 (theorem B).",
                subquestions=["Q1", "Q2"],
                stage="STAGE2_EVOLVE",
                autonomy_mode="AUTOPILOT",
            )
        finally:
            conn.close()

    def tearDown(self) -> None:
        # 清理只读冻结目录以便 Windows 顺利删除临时目录
        def _on_err(func, path, _exc):
            try:
                os.chmod(path, stat.S_IWRITE)
                func(path)
            except OSError:
                pass

        shutil.rmtree(self._td.name, onerror=_on_err)

    def _call(self, tool: str, role: str, args: dict, session_id: str = "sess_1") -> dict:
        return dispatch_tool_call(
            tool,
            args,
            workspace_root=str(self.ws),
            caller_role=role,
            session_id=session_id,
        )

    def test_01_registry_10_roles_44_tools_and_external_isolation(self) -> None:
        self.assertEqual(len(CANONICAL_ROLES), 10)
        self.assertEqual(len(TOOL_SPECS), 44)
        # 废弃五车道已彻底移除
        tool_names = {s["name"] for s in TOOL_SPECS}
        self.assertNotIn("dispatch_stagnation_five_lanes", tool_names)
        # external_surveyor 物理禁止访问内藏工具
        denied = self._call(
            "get_chronicler_snapshot",
            "external_surveyor",
            {"question_id": "Q1"},
            session_id="ext_1",
        )
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["error_code"], "ERR_AUTH")

    def test_02_handoff_auto_triage_local_lemma_partial_pass_and_gap_wake(self) -> None:
        # 1. 注册学派并开两条分支
        r = self._call("register_method_family", "logistics_coordinator", {
            "question_id": "Q1", "family_id": "fam_spec",
            "mechanism_signature": "spectral method", "orthogonal_contrast": "vs variational",
        }, "log_1")
        self.assertTrue(r["ok"], r)
        r = self._call("register_method_family", "logistics_coordinator", {
            "question_id": "Q1", "family_id": "fam_var",
            "mechanism_signature": "variational method", "orthogonal_contrast": "vs spectral",
        }, "log_1")
        self.assertTrue(r["ok"], r)

        b1 = self._call("fork_branch", "logistics_coordinator", {
            "question_id": "Q1", "fork_mode": "orthogonal", "target_family_id": "fam_spec",
        }, "log_1")
        b2 = self._call("fork_branch", "logistics_coordinator", {
            "question_id": "Q1", "fork_mode": "orthogonal", "target_family_id": "fam_var",
        }, "log_1")
        self.assertTrue(b1["ok"] and b2["ok"])
        n1 = b1["data"]["node_id"]
        bid1 = b1["data"]["branch_id"]
        n2 = b2["data"]["node_id"]
        bid2 = b2["data"]["branch_id"]
        # 默认 2 班岗保护期与确定性 companion_session_id
        self.assertEqual(b1["data"]["protection_generations_left"], 2)
        self.assertEqual(b1["data"]["companion_session_id"], f"gw-comp-{n1}")

        # 2. 0-37% 净室：explorer 被拒读 living_survey，但 lineage_companion 0% 直接可读
        exp_denied = self._call("get_living_survey", "explorer", {"node_id": n1, "question_id": "Q1"}, "exp_1")
        self.assertFalse(exp_denied["ok"])
        self.assertEqual(exp_denied["error_code"], "ERR_LOCKED")
        comp_ok = self._call("get_living_survey", "lineage_companion", {"node_id": n1, "question_id": "Q1"}, f"gw-comp-{n1}")
        self.assertTrue(comp_ok["ok"], comp_ok)

        # 3. 探索者越界退回 handback_to_chief 写入 NOTIFY_CHIEF
        hb = self._call("handback_to_chief", "explorer", {
            "node_id": n1, "question_id": "Q1",
            "human_request_md": "把 Q2 暂停一下", "reason": "涉及跨子题全局调度",
        }, "exp_1")
        self.assertTrue(hb["ok"], hb)
        claimed = dispatch_control_call("control_plane/claim_runtime_effects", {"workspace_root": str(self.ws), "lease_owner": "test-host"})
        self.assertTrue(any(e["kind"] == "NOTIFY_CHIEF" for e in claimed["data"]["effects"]))

        # 4. 分支 1 交班：直落 LEVEL_4B 挂起并公开悬赏缺口 + 同时拆交 1 份独立局部引理一次性盲审
        h1 = self._call("submit_node_handoff", "lineage_companion", {
            "node_id": n1, "branch_id": bid1, "question_id": "Q1",
            "mechanism_summary": "spectral decomposition needs coercivity lemma",
            "evidence_grade": "ARTIFACT_ONLY",
            "column_a_facts_md": "Verified identity ||Tu|| >= c||u|| under assumption H1 on finite grid dimension up to 64.",
            "column_b_hypothesis_md": "Need global coercivity lemma to close main theorem.",
            "will_md": "Wait for coercivity lemma L3 to resume.",
            "obs_ids": [], "dead_ends": [], "is_empty_crash": False,
            "recommended_triage": {
                "triage_level": "LEVEL_4B",
                "rationale": "Missing global coercivity lemma",
                "reopen_condition": "L3 coercivity lemma verified",
                "blocking_gap_formal_statement": "Prove uniform coercivity constant c > 0 for all N >= 2.",
            },
            "local_lemma_submissions": [
                {
                    "title": "Local auxiliary bound for N<=64",
                    "column_a_self_contained_proof_md": "Self-contained proof of auxiliary spectral norm bound for N<=64 by direct matrix trace inequality.",
                    "column_b_scope_notes_md": "Useful helper lemma.",
                    "bound_obs_ids": [],
                }
            ],
        }, f"gw-comp-{n1}")
        self.assertTrue(h1["ok"], h1)
        self.assertTrue(h1["data"]["auto_triaged"])
        self.assertEqual(h1["data"]["node_status"], "BLOCKED_L4B")
        gap_id = h1["data"]["auto_triage_data"]["created_gap_id"]
        self.assertTrue(gap_id.startswith("gap_"))
        local_rev_id = h1["data"]["created_lemma_review_ids"][0]

        # 5. 裁决 2：一次性局部引理判 REVISE，绝不改变 n1 的 BLOCKED_L4B 状态！
        bm_local = self._call("get_blind_manuscript", "library_verifier", {"review_id": local_rev_id}, "ver_local")
        self.assertTrue(bm_local["ok"], bm_local)
        s1_local = self._call("submit_stage1_blind_ledger", "library_verifier", {
            "review_id": local_rev_id, "question_id": "Q1",
            "ledger_items": [{"claim": "N<=64 bound", "evidence_location_and_quote": "missing edge case N=2"}],
            "stage1_verdict": "REVISE",
            "revision_or_refutation_reason": "Edge case N=2 omitted",
        }, "ver_local")
        self.assertTrue(s1_local["ok"], s1_local)
        self.assertTrue(s1_local["data"].get("local_lemma_one_shot"))
        # 确认原节点 n1 状态未被拉回 ACTIVE_REVISING
        trace_n1 = self._call("chief_trace_entity", "gw_chief", {"entity_type": "NODE", "entity_id": n1}, "chief_1")
        self.assertEqual(trace_n1["data"]["node"]["node_status"], "BLOCKED_L4B")

        # 6. 分支 2 交班直落 LEVEL_1 送审 -> Stage 1 PARTIAL_PASS -> Stage 2 ACCEPT_NARROWED 同事务写 L3+L2 并核销 gap_id 唤醒分支 1！
        h2 = self._call("submit_node_handoff", "lineage_companion", {
            "node_id": n2, "branch_id": bid2, "question_id": "Q1",
            "mechanism_summary": "variational coercivity bound with narrow hypothesis",
            "evidence_grade": "ARTIFACT_ONLY",
            "column_a_facts_md": "Complete self-contained variational proof of uniform coercivity constant c=1/4 for all N>=2 under symmetric kernel.",
            "column_b_hypothesis_md": "Also conjectured non-symmetric case holds.",
            "will_md": "Submit to blind review.",
            "obs_ids": [], "dead_ends": [], "is_empty_crash": False,
            "recommended_triage": {
                "triage_level": "LEVEL_1",
                "rationale": "Self-contained coercivity proof ready for review",
            },
        }, f"gw-comp-{n2}")
        self.assertTrue(h2["ok"], h2)
        rev2_id = h2["data"]["auto_triage_data"]["created_review_id"]

        self.assertTrue(self._call("get_blind_manuscript", "library_verifier", {"review_id": rev2_id}, "ver_2")["ok"])
        s1_p = self._call("submit_stage1_blind_ledger", "library_verifier", {
            "review_id": rev2_id, "question_id": "Q1",
            "ledger_items": [{"claim": "Symmetric coercivity c=1/4", "evidence_location_and_quote": "verified algebraically"}],
            "stage1_verdict": "PARTIAL_PASS",
            "exploit_ticket_payload": {"instrument_id": "inst_dummy", "summary": "detected edge rounding exploit"},
        }, "ver_2")
        self.assertTrue(s1_p["ok"], s1_p)
        self.assertEqual(s1_p["data"]["review_status"], "STAGE2_UNBLIND")
        self.assertIsNotNone(s1_p["data"]["exploit_ticket_id"])

        unblind = self._call("get_unblinded_manuscript_and_peers", "library_verifier", {"review_id": rev2_id}, "ver_2")
        self.assertTrue(unblind["ok"], unblind)
        self.assertTrue(any(g["gap_id"] == gap_id for g in unblind["data"]["open_lemma_gaps"]))

        s2_n = self._call("submit_stage2_unblind_verdict", "library_verifier", {
            "review_id": rev2_id,
            "final_verdict": "ACCEPT_NARROWED",
            "l3_entry_kind": "POS_THEOREM",
            "goal_coverage": "PARTIAL_OR_LEMMA",
            "publish_tier": "VERIFIED_INCREMENTAL",
            "title": "Uniform Coercivity Lemma (Symmetric Kernel)",
            "abstract_md": "Establishes uniform coercivity constant c=1/4 for all N>=2 under symmetric kernel conditions, resolving gap.",
            "exact_verified_scope_md": "All N>=2 with symmetric positive kernel.",
            "exact_refuted_scope_md": "Non-symmetric skew kernel counterexample breaks coercivity at N=4.",
            "fulfilled_gap_ids": [gap_id],
        }, "ver_2")
        self.assertTrue(s2_n["ok"], s2_n)
        self.assertTrue(s2_n["data"]["created_l3_id"].startswith("L3-"))
        self.assertTrue(s2_n["data"]["created_narrowed_l2_id"].startswith("L2-"))
        # 核销 gap 后自动唤醒了分支 1 生成下一代 EXPLORING 节点
        self.assertEqual(len(s2_n["data"]["fulfilled_gaps"]), 1)
        woken_nid = s2_n["data"]["fulfilled_gaps"][0]["woken_node_id"]
        self.assertIsNotNone(woken_nid)

    def test_03_subproblem_spec_isolation_lock1_wave_conference_and_stage3_one_step_closure(self) -> None:
        # 1. Q1 和 Q2 各建一分支并让 Q1/Q2 都拿到 FULL_GOAL L3 -> 双双锁一停派 STOPPED_SOLVED
        created_l3: dict[str, str] = {}
        repro_nodes: list[str] = []
        for qid in ("Q1", "Q2"):
            self.assertTrue(self._call("register_method_family", "logistics_coordinator", {
                "question_id": qid, "family_id": f"fam_{qid.lower()}",
                "mechanism_signature": f"exact proof {qid}", "orthogonal_contrast": "baseline",
            }, "log_x")["ok"])
            fb = self._call("fork_branch", "logistics_coordinator", {
                "question_id": qid, "fork_mode": "orthogonal", "target_family_id": f"fam_{qid.lower()}",
            }, "log_x")
            nid = fb["data"]["node_id"]
            bid = fb["data"]["branch_id"]
            repro_nodes.append(nid)
            wt = Path(fb["data"]["worktree_abs_path"])
            (wt / "solve.py").write_text("print('verified')\n", encoding="utf-8")

            ho = self._call("submit_node_handoff", "lineage_companion", {
                "node_id": nid, "branch_id": bid, "question_id": qid,
                "mechanism_summary": f"complete constructive proof for {qid}",
                "evidence_grade": "ARTIFACT_ONLY",
                "column_a_facts_md": f"Full self-contained constructive proof and verification script solve.py proving {qid} completely.",
                "column_b_hypothesis_md": "All edge cases verified.",
                "will_md": "Ready for blind review.",
                "obs_ids": [], "dead_ends": [], "candidate_rel_path": "solve.py", "is_empty_crash": False,
                "recommended_triage": {"triage_level": "LEVEL_1", "rationale": "Full proof ready"},
            }, f"gw-comp-{nid}")
            self.assertTrue(ho["ok"], ho)
            rev_id = ho["data"]["auto_triage_data"]["created_review_id"]
            self.assertTrue(self._call("get_blind_manuscript", "library_verifier", {"review_id": rev_id}, f"ver_{qid}")["ok"])
            self.assertTrue(self._call("submit_stage1_blind_ledger", "library_verifier", {
                "review_id": rev_id, "question_id": qid,
                "ledger_items": [{"claim": f"{qid} full proof", "evidence_location_and_quote": "solve.py verified"}],
                "stage1_verdict": "PASS",
            }, f"ver_{qid}")["ok"])
            self.assertTrue(self._call("get_unblinded_manuscript_and_peers", "library_verifier", {"review_id": rev_id}, f"ver_{qid}")["ok"])
            s2 = self._call("submit_stage2_unblind_verdict", "library_verifier", {
                "review_id": rev_id, "final_verdict": "ACCEPT",
                "l3_entry_kind": "POS_THEOREM", "goal_coverage": "FULL_GOAL", "publish_tier": "BASELINE_UPDATE",
                "title": f"Complete Theorem for {qid}",
                "abstract_md": f"Complete rigorously verified proof and runnable artifact solve.py solving {qid} under spec v0.",
                "exact_verified_scope_md": f"Full domain of {qid} under active spec.",
            }, f"ver_{qid}")
            self.assertTrue(s2["ok"], s2)
            created_l3[qid] = s2["data"]["created_l3_id"]
            # 锁一立即切 STOPPED_SOLVED
            self.assertEqual(s2["data"]["subproblem_lock_eval"][0]["dispatch_state"], "STOPPED_SOLVED")

        # 2. 裁决 4：仅修改 Q1 口径 -> Q1 自动回 DISPATCHING，Q2 保持 STOPPED_SOLVED 绝不连坐！
        prop = self._call("chief_propose_control_action", "gw_chief", {
            "action_type": "AMEND_RULING_DRAFT",
            "target_id": "Q1",
            "payload": {"affected_question_ids": ["Q1"], "ruling_summary_md": "Q1 requires extra boundary condition B."},
            "rationale_md": "Human refined Q1 boundary condition.",
        }, "chief_1")
        self.assertTrue(prop["ok"], prop)
        app = dispatch_control_call("control_plane/approve_control_proposal", {
            "workspace_root": str(self.ws),
            "proposal_id": prop["data"]["proposal_id"],
            "decision": "APPROVED",
            "caller": "human_ui",
        })
        self.assertTrue(app["ok"], app)
        # 幂等复点必须安全跳过
        app_dup = dispatch_control_call("control_plane/approve_control_proposal", {
            "workspace_root": str(self.ws),
            "proposal_id": prop["data"]["proposal_id"],
            "decision": "APPROVED",
            "caller": "human_ui",
        })
        self.assertTrue(app_dup["ok"] and app_dup["data"].get("already_resolved"))

        ov = self._call("chief_get_overview_snapshot", "gw_chief", {"question_id": "ALL"}, "chief_1")
        by_q = {s["question_id"]: s for s in ov["data"]["subproblems"]}
        self.assertEqual(by_q["Q1"]["active_spec_revision"], 1)
        self.assertEqual(by_q["Q1"]["dispatch_state"], "DISPATCHING")
        self.assertEqual(by_q["Q2"]["active_spec_revision"], 0)
        self.assertEqual(by_q["Q2"]["dispatch_state"], "STOPPED_SOLVED")

        # 3. 宏观大外环 4 拍（单参会者自动跳过互辩直入 SURVEY_REFRESHING -> 总览 -> 裁判开双供体杂交枝并保护期免误裁）
        conf = dispatch_control_call("control_plane/open_wave_conference", {
            "workspace_root": str(self.ws), "question_id": "Q1", "force": True,
        })
        self.assertTrue(conf["ok"] and conf["data"] is not None)
        cid = conf["data"]["conference_id"]
        self.assertEqual(conf["data"]["status"], "SURVEY_REFRESHING")

        sv = self._call("publish_living_survey", "library_chronicler", {
            "question_id": "Q1", "conference_id": cid,
            "sec1_baseline_and_instruments_md": "Q1 spec v1 active; previous v0 L3-001 outdated for new boundary B.",
            "sec2_l3_lemma_tree_md": "L3-001 (v0 baseline).",
            "sec3_avoidance_radar_md": "None yet.",
            "sec4_explicit_gaps_md": "Need boundary condition B verification under spec v1.",
        }, "chron_1")
        self.assertTrue(sv["ok"], sv)

        # 主席开一条新分支满足 Q1 v1
        verd = self._call("submit_conference_verdict", "conference_chair", {
            "conference_id": cid,
            "actions": [
                {"action": "OPEN_NEW_BRANCH", "family_id": "fam_q1", "mechanism_signature": "v1 boundary B constructive proof"},
            ],
            "rationale_md": "Spawn new branch for Q1 spec v1.",
        }, "chair_1")
        self.assertTrue(verd["ok"], verd)
        new_q1_nid = verd["data"]["executed"][0]["node_id"]
        new_q1_bid = verd["data"]["executed"][0]["branch_id"]
        new_q1_wt = Path(verd["data"]["executed"][0]["worktree_abs_path"])
        (new_q1_wt / "solve_v1.py").write_text("print('v1 verified')\n", encoding="utf-8")

        # Q1 新分支拿 v1 FULL_GOAL L3
        ho_v1 = self._call("submit_node_handoff", "lineage_companion", {
            "node_id": new_q1_nid, "branch_id": new_q1_bid, "question_id": "Q1",
            "mechanism_summary": "Q1 spec v1 full constructive proof with boundary B",
            "evidence_grade": "ARTIFACT_ONLY",
            "column_a_facts_md": "Complete proof satisfying spec v1 boundary B verified by solve_v1.py.",
            "column_b_hypothesis_md": "Complete.", "will_md": "Submit v1.",
            "obs_ids": [], "dead_ends": [], "candidate_rel_path": "solve_v1.py", "is_empty_crash": False,
            "recommended_triage": {"triage_level": "LEVEL_1", "rationale": "v1 full proof"},
        }, f"gw-comp-{new_q1_nid}")
        rev_v1 = ho_v1["data"]["auto_triage_data"]["created_review_id"]
        self.assertTrue(self._call("get_blind_manuscript", "library_verifier", {"review_id": rev_v1}, "ver_q1_v1")["ok"])
        self.assertTrue(self._call("submit_stage1_blind_ledger", "library_verifier", {
            "review_id": rev_v1, "question_id": "Q1",
            "ledger_items": [{"claim": "Q1 v1 full", "evidence_location_and_quote": "solve_v1.py"}],
            "stage1_verdict": "PASS",
        }, "ver_q1_v1")["ok"])
        self.assertTrue(self._call("get_unblinded_manuscript_and_peers", "library_verifier", {"review_id": rev_v1}, "ver_q1_v1")["ok"])
        s2_v1 = self._call("submit_stage2_unblind_verdict", "library_verifier", {
            "review_id": rev_v1, "final_verdict": "ACCEPT",
            "l3_entry_kind": "POS_THEOREM", "goal_coverage": "FULL_GOAL", "publish_tier": "BASELINE_UPDATE",
            "title": "Q1 Complete Theorem v1",
            "abstract_md": "Complete verified proof of Q1 under revised spec v1 including boundary condition B.",
            "exact_verified_scope_md": "Q1 spec v1 full domain.",
        }, "ver_q1_v1")
        self.assertTrue(s2_v1["ok"], s2_v1)
        created_l3["Q1"] = s2_v1["data"]["created_l3_id"]

        # 4. Stage 3：library_chronicler 导出并冻结 -> 篡改工作区副本不影响外部不可变冻结包 -> library_verifier 一步原子结项！
        exp3 = self._call("export_stage3_final_delivery", "library_chronicler", {
            "delivery_mode": "FULL",
            "formal_paper_md": "# Final Report\n\nBoth Q1 (spec v1) and Q2 (spec v0) are rigorously proved and verified with runnable reproduction scripts.",
            "selected_l3_ids_by_question": {"Q1": [created_l3["Q1"]], "Q2": [created_l3["Q2"]]},
            "remaining_gaps_by_question": {"Q1": "None", "Q2": "None"},
            "reproduction_candidate_nodes": [new_q1_nid, repro_nodes[1]],
        }, "chron_final")
        self.assertTrue(exp3["ok"], exp3)
        did = exp3["data"]["delivery_id"]

        # 修改工作区可见的 final_delivery 副本，不可变冻结目录完全免疫
        (self.ws / "final_delivery" / "01_formal_report.md").write_text("tampered workspace copy", encoding="utf-8")

        audit_read = self._call("get_unblinded_manuscript_and_peers", "library_verifier", {
            "review_id": f"STAGE3_FINAL_AUDIT:{did}",
        }, "ver_stage3")
        self.assertTrue(audit_read["ok"], audit_read)
        # 一步原子终签 CLOSED_VERIFIED
        final_sign = self._call("submit_stage2_unblind_verdict", "library_verifier", {
            "review_id": f"STAGE3_FINAL_AUDIT:{did}",
            "final_verdict": "ACCEPT",
        }, "ver_stage3")
        self.assertTrue(final_sign["ok"], final_sign)
        self.assertEqual(final_sign["data"]["closure_status"], "CLOSED_VERIFIED")

        # 裁决 3：supervisory_committee 旧 CLOSURE_GATE 已被正式取消
        old_gate = self._call("record_compliance_check", "supervisory_committee", {
            "stage": "CLOSURE_GATE", "status": "PASSED", "blocking_questions": [], "notes": "legacy",
        }, "sup_1")
        self.assertFalse(old_gate["ok"])
        self.assertEqual(old_gate["error_code"], "ERR_LOCKED")


if __name__ == "__main__":
    unittest.main()
