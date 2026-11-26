"""GreatWall v0.3 静态审阅 15 项缺陷 Python 侧全链路回归测试（零 mock，真实 SQLite + 真实磁盘快照）。"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from core_python.mcp_server import control_plane_service as cp
from core_python.mcp_server.db_schema import (
    FailClosedError,
    open_rw_connection,
    resolve_storage_paths,
    rw_immediate_tx,
    utc_now_iso,
)
from core_python.mcp_server.tools_companion import tool_submit_node_handoff
from core_python.mcp_server.tools_explorer_eval import tool_run_isolated_eval
from core_python.mcp_server.tools_logistics import tool_fork_branch, tool_register_method_family, tool_triage_node
from core_python.mcp_server.tools_supervisory import tool_record_compliance_check
from core_python.mcp_server.tools_verifier import (
    tool_submit_stage1_blind_ledger,
    tool_submit_stage2_unblind_verdict,
)
from core_python.mcp_server.tools_works import tool_register_question_instrument


class TestV03ReviewRemediation(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name) / "ws"
        self.ws.mkdir(parents=True, exist_ok=True)
        self._old_data_dir = os.environ.get("GREATWALL_DATA_DIR")
        os.environ["GREATWALL_DATA_DIR"] = str(Path(self._tmp.name) / "gw_data")
        self.paths = resolve_storage_paths(str(self.ws))
        self.conn = open_rw_connection(self.paths["db_path"], init_schema=True)

    def tearDown(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass
        if self._old_data_dir is None:
            os.environ.pop("GREATWALL_DATA_DIR", None)
        else:
            os.environ["GREATWALL_DATA_DIR"] = self._old_data_dir
        self._tmp.cleanup()

    def _init_stage2(self, subquestions: list[str] | None = None, total_budget: dict | None = None) -> None:
        cp.init_parse0_contract(
            self.conn,
            goal_and_completion_md="完整求解所有子题并给出可复现证明与数值检验。",
            subquestions=subquestions or ["Q1", "Q2"],
            total_budget=total_budget or {},
            stage="STAGE2_EVOLVE",
            human_signed_at=utc_now_iso(),
            autonomy_mode="WAVE_CONFIRM",
        )

    def test_lock_evaluation_observes_pause_committed_before_writer_lock(self) -> None:
        self._init_stage2(["Q1"])
        writer = open_rw_connection(self.paths["db_path"], init_schema=False)
        try:
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("UPDATE subproblem_runtime_state SET desired_state='PAUSED' WHERE question_id='Q1'")

            # Commit the pending human request just as evaluation asks for its write lock.
            def release_writer(statement: str) -> None:
                if statement == "BEGIN IMMEDIATE":
                    writer.commit()

            self.conn.set_trace_callback(release_writer)
            result = cp.evaluate_subproblem_locks(self.conn, question_id="Q1")
            self.assertEqual(result["evaluated"][0]["dispatch_state"], "PAUSED_HUMAN")
            row = self.conn.execute("SELECT dispatch_state FROM subproblem_runtime_state WHERE question_id='Q1'").fetchone()
            self.assertEqual(row["dispatch_state"], "PAUSED_HUMAN")
        finally:
            self.conn.set_trace_callback(None)
            writer.close()

    def test_budget_pause_refreshes_usage_without_changing_generation(self) -> None:
        self._init_stage2(["Q1"])
        self.conn.execute(
            "UPDATE subproblem_runtime_state SET question_token_budget=100, spent_tokens=100 WHERE question_id='Q1'"
        )
        cp.evaluate_subproblem_locks(self.conn, question_id="Q1")
        query = "SELECT dispatch_generation, block_detail_md FROM subproblem_runtime_state WHERE question_id='Q1'"
        first = self.conn.execute(query).fetchone()
        self.conn.execute("UPDATE subproblem_runtime_state SET spent_tokens=125 WHERE question_id='Q1'")
        second = cp.evaluate_subproblem_locks(self.conn, question_id="Q1")["evaluated"][0]
        latest = self.conn.execute(query).fetchone()
        self.assertIn("125", latest["block_detail_md"])
        self.assertEqual(latest["dispatch_generation"], first["dispatch_generation"])
        self.assertTrue(second["changed"])
        repeat = cp.evaluate_subproblem_locks(self.conn, question_id="Q1")["evaluated"][0]
        self.assertFalse(repeat["changed"])

    def _register_inst(self, question_id: str = "Q1", inst_id: str = "ver_q1") -> None:
        ev_dir = self.ws / "evaluators"
        cal_dir = self.ws / "_hidden_calibrations"
        ev_dir.mkdir(parents=True, exist_ok=True)
        cal_dir.mkdir(parents=True, exist_ok=True)
        inst_fp = ev_dir / f"{inst_id}.py"
        inst_fp.write_text(
            "def evaluate(artifact, spec, tier):\n"
            "    if isinstance(artifact, dict) and artifact.get('ok') is False:\n"
            "        return {'status': 'OK', 'verdict': 'FAIL', 'tracks': {'score': 0.0}, 'details': 'bad'}\n"
            "    return {'status': 'OK', 'verdict': 'PASS', 'tracks': {'score': 1.0}, 'details': 'ok'}\n",
            encoding="utf-8",
        )
        cal_fp = cal_dir / f"{inst_id}_cal.json"
        cal_fp.write_text(
            json.dumps(
                [
                    {"case_id": "pos", "tier": "official", "spec": {}, "artifact": {"ok": True}, "expected_status": "OK", "expected_verdict": "PASS"},
                    {"case_id": "neg", "tier": "official", "spec": {}, "artifact": {"ok": False}, "expected_status": "OK", "expected_verdict": "FAIL"},
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        res = tool_register_question_instrument(
            conn=self.conn,
            workspace_root=str(self.ws),
            caller_role="works_engineer",
            session_id="s_works",
            question_id=question_id,
            instrument_id=inst_id,
            instrument_role="VERDICT",
            instrument_rel_path=f"evaluators/{inst_id}.py",
            artifact_schema="json_file",
            calibration_suite_rel_path=f"_hidden_calibrations/{inst_id}_cal.json",
        )
        self.assertTrue(res["ok"], res)

    def _spawn_branch(self, question_id: str = "Q1", family_id: str = "fam_a") -> tuple[str, str, Path]:
        tool_register_method_family(
            conn=self.conn,
            caller_role="logistics_coordinator",
            session_id="s_log",
            question_id=question_id,
            family_id=family_id,
            mechanism_signature=f"机理 {family_id}",
            orthogonal_contrast=f"与他族正交 {family_id}",
        )
        fk = tool_fork_branch(
            conn=self.conn,
            workspace_root=str(self.ws),
            caller_role="logistics_coordinator",
            session_id="s_log",
            question_id=question_id,
            fork_mode="orthogonal",
            target_family_id=family_id,
        )
        self.assertTrue(fk["ok"], fk)
        nid = fk["data"]["node_id"]
        bid = fk["data"]["branch_id"]
        wt = Path(fk["data"]["worktree_abs_path"])
        return nid, bid, wt

    def _publish_verified_l3(
        self,
        *,
        question_id: str,
        family_id: str,
        filename: str,
        title: str,
        goal_coverage: str = "PARTIAL_OR_LEMMA",
        publish_tier: str = "BASELINE_UPDATE",
        fulfilled_gap_ids: list[str] | None = None,
    ) -> tuple[str, str]:
        nid, bid, wt = self._spawn_branch(question_id, family_id)
        (wt / filename).write_text(f"# {title}\n", encoding="utf-8")
        ho = tool_submit_node_handoff(
            conn=self.conn,
            workspace_root=str(self.ws),
            caller_role="lineage_companion",
            session_id=f"sc_{nid}",
            question_id=question_id,
            branch_id=bid,
            node_id=nid,
            mechanism_summary=title[:40],
            evidence_grade="ARTIFACT_ONLY",
            column_a_facts_md=f"{title} 完整自包含推导：" + "严格推导步骤。" * 15,
            column_b_hypothesis_md="无额外未证假设。",
            will_md="提交盲审。",
            candidate_rel_path=filename,
            recommended_triage={"triage_level": "LEVEL_1", "rationale": "送盲审"},
        )
        self.assertTrue(ho["ok"], ho)
        rev_id = ho["data"]["auto_triage_data"]["created_review_id"]
        s1 = tool_submit_stage1_blind_ledger(
            conn=self.conn,
            caller_role="library_verifier",
            session_id=f"sv_{rev_id}",
            review_id=rev_id,
            question_id=question_id,
            stage1_verdict="PASS",
            ledger_items=[{"claim": "主推导", "evidence_location_and_quote": "manuscript_column_a.md:1 通过", "verdict": "PASS"}],
        )
        self.assertTrue(s1["ok"], s1)
        s2 = tool_submit_stage2_unblind_verdict(
            conn=self.conn,
            caller_role="library_verifier",
            session_id=f"sv_{rev_id}",
            review_id=rev_id,
            final_verdict="ACCEPT",
            l3_entry_kind="POS_THEOREM",
            goal_coverage=goal_coverage,
            publish_tier=publish_tier,
            title=title,
            abstract_md=f"{title} 已通过独立空白盲审沙箱全量复现验算，满足全部前提边界与形式化推导要求，可供本子题及全院后续直接引用。",
            exact_verified_scope_md="适用于全部合法题设域。",
            fulfilled_gap_ids=fulfilled_gap_ids or [],
        )
        self.assertTrue(s2["ok"], s2)
        return s2["data"]["created_l3_id"], nid

    def test_01_wave_reject_reopen_no_unique_collision_and_lock3_immediate_and_fail_release(self) -> None:
        self._init_stage2(["Q1"], total_budget={"max_waves": 1})
        self._spawn_branch("Q1", "fam_w1")
        opened1 = cp.check_and_open_wave_conference(self.conn, question_id="Q1", force=True)
        self.assertTrue(opened1["opened"])
        cid1 = opened1["conference_id"]
        self.assertEqual(opened1["wave_no"], 1)

        # 推进至 ADJUDICATING 并产出待人类拍板提案，随后人类驳回 (CANCELLED)
        with rw_immediate_tx(self.conn):
            self.conn.execute("UPDATE wave_conferences SET status = 'ADJUDICATING' WHERE conference_id = ?", (cid1,))
        v1 = cp.submit_wave_verdict_decision(
            self.conn,
            workspace_root=str(self.ws),
            conference_id=cid1,
            verdict_payload={"actions": []},
            rationale_md="第一波圆桌纪要：建议先保持现状并探索新学派方向。",
        )
        pid1 = v1["proposal_id"]
        rej = cp.approve_control_proposal(
            self.conn, workspace_root=str(self.ws), proposal_id=pid1, decision="REJECT", approved_by_source="human_ui"
        )
        self.assertEqual(rej["status"], "REJECTED")

        # 问题 #6：驳回后重开新圆桌绝不撞 UNIQUE(question_id, wave_no)
        opened2 = cp.check_and_open_wave_conference(self.conn, question_id="Q1", force=True)
        self.assertTrue(opened2["opened"])
        cid2 = opened2["conference_id"]
        self.assertEqual(opened2["wave_no"], 2)

        # 模拟节点熔断：mark_wave_conference_failed 释放开会锁后可再开 wave_no=3
        failed = cp.mark_wave_conference_failed(self.conn, conference_id=cid2, reason="WAVE_STALLED_CIRCUIT_BROKEN")
        self.assertEqual(failed["status"], "FAILED")
        opened3 = cp.check_and_open_wave_conference(self.conn, question_id="Q1", force=True)
        self.assertTrue(opened3["opened"])
        cid3 = opened3["conference_id"]
        self.assertEqual(opened3["wave_no"], 3)

        # 问题 #5：批准执行后 completed_waves 达上限 (1) 立即同事务结算锁三停派
        with rw_immediate_tx(self.conn):
            self.conn.execute("UPDATE wave_conferences SET status = 'ADJUDICATING' WHERE conference_id = ?", (cid3,))
        v3 = cp.submit_wave_verdict_decision(
            self.conn,
            workspace_root=str(self.ws),
            conference_id=cid3,
            verdict_payload={"actions": []},
            rationale_md="第三波圆桌纪要：完成首波正式结算。",
        )
        cp.approve_control_proposal(
            self.conn,
            workspace_root=str(self.ws),
            proposal_id=v3["proposal_id"],
            decision="APPROVE",
            approved_by_source="human_ui",
        )
        qrow = self.conn.execute("SELECT completed_waves, dispatch_state, block_reason_code FROM subproblem_runtime_state WHERE question_id = 'Q1'").fetchone()
        self.assertEqual(int(qrow["completed_waves"]), 1)
        self.assertEqual(qrow["dispatch_state"], "PAUSED_BLOCKED")
        self.assertEqual(qrow["block_reason_code"], "MAX_WAVES_EXHAUSTED")

    def test_02_synthesis_budget_decrement_and_exhaust_seal(self) -> None:
        self._init_stage2(["Q1"])
        nid1, bid1, wt1 = self._spawn_branch("Q1", "fam_syn")
        with rw_immediate_tx(self.conn):
            self.conn.execute(
                "UPDATE lineage_nodes SET branch_kind = 'SYNTHESIS', branch_budget_nodes_left = 2 WHERE node_id = ?",
                (nid1,),
            )
        (wt1 / "cand.py").write_text("x = 1\n", encoding="utf-8")
        ho1 = tool_submit_node_handoff(
            conn=self.conn,
            workspace_root=str(self.ws),
            caller_role="lineage_companion",
            session_id="s_c1",
            question_id="Q1",
            branch_id=bid1,
            node_id=nid1,
            mechanism_summary="合体第一班探索",
            evidence_grade="ARTIFACT_ONLY",
            column_a_facts_md="第一班已构建初步融合代码并验证语法结构完整。" * 2,
            column_b_hypothesis_md="下班继续测试边界。",
            will_md="继续调参并做正式检验。",
            candidate_rel_path="cand.py",
            recommended_triage={"triage_level": "ROUTINE_CONTINUATION", "rationale": "继续第二班试跑"},
        )
        self.assertTrue(ho1["ok"], ho1)
        nid2 = ho1["data"]["auto_triage_data"]["next_node_id"]
        n2_row = self.conn.execute("SELECT branch_kind, branch_budget_nodes_left FROM lineage_nodes WHERE node_id = ?", (nid2,)).fetchone()
        self.assertEqual(n2_row["branch_kind"], "SYNTHESIS")
        self.assertEqual(int(n2_row["branch_budget_nodes_left"]), 1)

        ho2 = tool_submit_node_handoff(
            conn=self.conn,
            workspace_root=str(self.ws),
            caller_role="lineage_companion",
            session_id="s_c2",
            question_id="Q1",
            branch_id=bid1,
            node_id=nid2,
            mechanism_summary="合体第二班收尾",
            evidence_grade="ARTIFACT_ONLY",
            column_a_facts_md="第二班完成试跑，暂未突破主线基线。",
            column_b_hypothesis_md="如需继续应由圆桌另行立项。",
            will_md="试跑配额耗尽。",
            candidate_rel_path="cand.py",
            recommended_triage={"triage_level": "ROUTINE_CONTINUATION", "rationale": "尝试续跑"},
        )
        self.assertTrue(ho2["ok"], ho2)
        triage_data = ho2["data"]["auto_triage_data"]
        self.assertTrue(triage_data.get("budget_exhausted"))
        self.assertIsNone(triage_data.get("next_node_id"))
        n2_after = self.conn.execute("SELECT node_status, branch_budget_nodes_left FROM lineage_nodes WHERE node_id = ?", (nid2,)).fetchone()
        self.assertEqual(n2_after["node_status"], "SEALED")
        self.assertEqual(int(n2_after["branch_budget_nodes_left"]), 0)

    def test_03_approved_ruling_isolation_no_unapproved_draft_and_no_cross_question_leak(self) -> None:
        self._init_stage2(["Q1", "Q2"])
        rulings_dir = self.ws / "rulings"
        rulings_dir.mkdir(parents=True, exist_ok=True)
        (rulings_dir / "unapproved_draft.md").write_text("# 未批准草稿\n不要生效", encoding="utf-8")

        amend = cp.apply_approved_ruling_amendment(
            self.conn,
            workspace_root=str(self.ws),
            affected_question_ids=["Q1"],
            ruling_markdown="Q1 专属口径修订 v1：容差改为 1e-6。",
            summary_md="Q1 容差 1e-6",
        )
        self.assertEqual(amend["latest_spec_revision"], 1)
        ruling_name = Path(amend["ruling_file"]).name

        n1, b1, wt1 = self._spawn_branch("Q1", "fam_q1")
        n2, b2, wt2 = self._spawn_branch("Q2", "fam_q2")
        self.assertTrue((wt1 / "inputs" / "rulings" / ruling_name).is_file())
        self.assertFalse((wt1 / "inputs" / "rulings" / "unapproved_draft.md").exists())
        self.assertFalse((wt2 / "inputs" / "rulings" / ruling_name).exists())
        self.assertFalse((wt2 / "inputs" / "rulings" / "unapproved_draft.md").exists())

        (wt1 / "sol1.py").write_text("# q1\n", encoding="utf-8")
        (wt2 / "sol2.py").write_text("# q2\n", encoding="utf-8")
        for nid, bid, rel, qid in [(n1, b1, "sol1.py", "Q1"), (n2, b2, "sol2.py", "Q2")]:
            ho = tool_submit_node_handoff(
                conn=self.conn,
                workspace_root=str(self.ws),
                caller_role="lineage_companion",
                session_id=f"sc_{nid}",
                question_id=qid,
                branch_id=bid,
                node_id=nid,
                mechanism_summary=f"{qid} 候选",
                evidence_grade="ARTIFACT_ONLY",
                column_a_facts_md=f"{qid} 完整自包含推导过程：" + "严谨证明步骤" * 15,
                column_b_hypothesis_md="无额外未证假设。",
                will_md="提交盲审。",
                candidate_rel_path=rel,
                recommended_triage={"triage_level": "LEVEL_1", "rationale": "送盲审"},
            )
            self.assertTrue(ho["ok"], ho)
        revs = {r["question_id"]: r["review_id"] for r in self.conn.execute("SELECT review_id, question_id FROM review_queue").fetchall()}
        sb1 = cp.stage_blind_review_sandbox(self.conn, workspace_root=str(self.ws), review_id=revs["Q1"])
        sb2 = cp.stage_blind_review_sandbox(self.conn, workspace_root=str(self.ws), review_id=revs["Q2"])
        self.assertTrue((Path(sb1["sandbox_abs_path"]) / "inputs" / "rulings" / ruling_name).is_file())
        self.assertFalse((Path(sb1["sandbox_abs_path"]) / "inputs" / "rulings" / "unapproved_draft.md").exists())
        self.assertFalse((Path(sb2["sandbox_abs_path"]) / "inputs" / "rulings" / ruling_name).exists())
        self.assertFalse((Path(sb2["sandbox_abs_path"]) / "inputs" / "rulings" / "unapproved_draft.md").exists())

    def test_04_local_lemma_independent_snapshot_and_excluded_from_orphan_revisions(self) -> None:
        self._init_stage2(["Q1"])
        nid1, bid1, wt1 = self._spawn_branch("Q1", "fam_lm")
        (wt1 / "lemma_proof.py").write_text("LEMMA_VERSION = 'V1_ORIGINAL'\n", encoding="utf-8")

        ho = tool_submit_node_handoff(
            conn=self.conn,
            workspace_root=str(self.ws),
            caller_role="lineage_companion",
            session_id="s_lm1",
            question_id="Q1",
            branch_id=bid1,
            node_id=nid1,
            mechanism_summary="主线继续并拆交局部引理",
            evidence_grade="ARTIFACT_ONLY",
            column_a_facts_md="主线阶段性推进，已独立证明辅助引理 A。",
            column_b_hypothesis_md="主线继续冲刺完整目标。",
            will_md="下代将重写 lemma_proof.py 做主线扩展。",
            candidate_rel_path="lemma_proof.py",
            recommended_triage={"triage_level": "ROUTINE_CONTINUATION", "rationale": "主线继续推进"},
            local_lemma_submissions=[
                {
                    "title": "局部引理 A（V1 版本）",
                    "column_a_self_contained_proof_md": "局部引理 A 完整自包含推导：" + "严密不等式链推导。" * 8,
                    "column_b_scope_notes_md": "适用于一般边界条件。",
                    "artifact_rel_path": "lemma_proof.py",
                }
            ],
        )
        self.assertTrue(ho["ok"], ho)
        lrev_id = ho["data"]["created_lemma_review_ids"][0]

        (wt1 / "lemma_proof.py").write_text("LEMMA_VERSION = 'V2_OVERWRITTEN_BY_NEXT_GEN'\n", encoding="utf-8")
        cp.backup_retained_candidate_snapshot(
            workspace_root=str(self.ws), branch_id=bid1, worktree_abs_path=str(wt1), candidate_rel_path="lemma_proof.py"
        )
        sb = cp.stage_blind_review_sandbox(self.conn, workspace_root=str(self.ws), review_id=lrev_id)
        staged_code = (Path(sb["sandbox_abs_path"]) / "lemma_proof.py").read_text(encoding="utf-8")
        self.assertIn("V1_ORIGINAL", staged_code)
        self.assertNotIn("V2_OVERWRITTEN", staged_code)

        s1 = tool_submit_stage1_blind_ledger(
            conn=self.conn,
            caller_role="library_verifier",
            session_id="s_ver_lm",
            review_id=lrev_id,
            question_id="Q1",
            stage1_verdict="REVISE",
            ledger_items=[{"claim": "边界常数", "evidence_location_and_quote": "lemma_proof.py:1 常数因子漏了 2", "verdict": "FAIL"}],
            revision_or_refutation_reason="补齐常数因子 2",
        )
        self.assertTrue(s1["ok"], s1)
        snap = cp.schedule_control_plane_snapshot(self.conn, workspace_root=str(self.ws))
        orphan_ids = [r["review_id"] for r in snap.get("orphaned_blind_review_revisions", [])]
        self.assertNotIn(lrev_id, orphan_ids)

    def test_05_gap_fulfillment_clears_revoked_requires_and_writes_will_and_baseline_update(self) -> None:
        self._init_stage2(["Q1"])
        # 先经真实盲审入库一条旧 L3，然后标记撤回 (is_active=0)
        old_l3, _ = self._publish_verified_l3(
            question_id="Q1",
            family_id="fam_old",
            filename="old_lm.py",
            title="将被撤回的旧引理",
            publish_tier="VERIFIED_INCREMENTAL",
        )
        with rw_immediate_tx(self.conn):
            self.conn.execute("UPDATE internal_research_ledger SET is_active = 0 WHERE entry_id = ?", (old_l3,))

        n_blk, _, _ = self._spawn_branch("Q1", "fam_blk")
        with rw_immediate_tx(self.conn):
            self.conn.execute(
                "UPDATE lineage_nodes SET node_status = 'AWAITING_TRIAGE', requires_json = ?, will_md = '等待替代引理。' WHERE node_id = ?",
                (json.dumps([old_l3]), n_blk),
            )
        tr_blk = tool_triage_node(
            conn=self.conn,
            workspace_root=str(self.ws),
            caller_role="logistics_coordinator",
            session_id="s_log",
            node_id=n_blk,
            triage_level="LEVEL_4B",
            action="PAUSE_TO_READY_QUEUE",
            assigned_family_id="fam_blk",
            rationale="旧引理被撤回，发布替代缺口悬赏。",
            reopen_condition="需要可替代旧引理的紧致界引理",
        )
        self.assertTrue(tr_blk["ok"], tr_blk)
        gap_id = tr_blk["data"]["created_gap_id"]

        new_l3, _ = self._publish_verified_l3(
            question_id="Q1",
            family_id="fam_hlp",
            filename="helper.py",
            title="紧致界引理（替代旧引理）",
            publish_tier="BASELINE_UPDATE",
            fulfilled_gap_ids=[gap_id],
        )

        # 验证问题 #10：BASELINE_UPDATE 已同步写入子题 baseline_entry_id
        qrow = self.conn.execute("SELECT baseline_entry_id FROM subproblem_runtime_state WHERE question_id = 'Q1'").fetchone()
        self.assertEqual(qrow["baseline_entry_id"], new_l3)

        # 验证问题 #9：被唤醒的新节点清除了已撤回旧 L3、注入了新 L3 与交接遗嘱，且不被 blocked_by_requires 挡死
        woken = self.conn.execute(
            "SELECT node_id, requires_json, will_md FROM lineage_nodes WHERE parent_node_id = ? ORDER BY created_at DESC LIMIT 1",
            (n_blk,),
        ).fetchone()
        self.assertIsNotNone(woken)
        reqs = json.loads(woken["requires_json"])
        self.assertNotIn(old_l3, reqs)
        self.assertIn(new_l3, reqs)
        self.assertIn(new_l3, woken["will_md"])
        self.assertIn(gap_id, woken["will_md"])

        snap = cp.schedule_control_plane_snapshot(self.conn, workspace_root=str(self.ws))
        blocked_ids = [n["node_id"] for n in snap["blocked_by_requires_nodes"]]
        self.assertNotIn(woken["node_id"], blocked_ids)

    def test_06_stage3_final_sign_blocks_after_amendment_and_legacy_exported_migration_heals(self) -> None:
        self._init_stage2(["Q1"])
        l3_id, nid = self._publish_verified_l3(
            question_id="Q1",
            family_id="fam_s3",
            filename="final_sol.py",
            title="Q1 完整通关解",
            goal_coverage="FULL_GOAL",
            publish_tier="BASELINE_UPDATE",
        )
        exp = cp.export_stage3_deliverables(
            self.conn,
            workspace_root=str(self.ws),
            delivery_mode="FULL",
            formal_paper_md=(
                f"# 正式总报告\n\n## Q1 求解综述\n\n依据独立空白沙箱验证通过的 {l3_id}，"
                "本文严格证明了子题 Q1 在全部题设范围内的完整解析解与可复现构造脚本，边界条件与数值检验全部闭环无遗漏。"
            ),
            selected_l3_ids_by_question={"Q1": [l3_id]},
            remaining_gaps_by_question={},
            reproduction_candidate_nodes=[nid],
        )
        did = exp["delivery_id"]

        cp.apply_approved_ruling_amendment(
            self.conn,
            workspace_root=str(self.ws),
            affected_question_ids=["Q1"],
            ruling_markdown="终签前新增高阶边界要求。",
            summary_md="新增高阶边界要求",
        )

        with self.assertRaises(FailClosedError) as ctx:
            cp.finalize_stage3_closure_on_verifier_accept(self.conn, target_delivery_id=did)
        self.assertEqual(ctx.exception.code, "ERR_CONFLICT")
        cs = self.conn.execute("SELECT status, verifier_revision_notes FROM project_closure_state WHERE id = 1").fetchone()
        self.assertEqual(cs["status"], "REVISION_REQUESTED")

        with rw_immediate_tx(self.conn):
            self.conn.execute(
                "UPDATE project_closure_state SET status = 'DELIVERY_EXPORTED', frozen_delivery_dir_abs_path = '', verifier_revision_notes = '' WHERE id = 1"
            )
        self.conn.close()
        self.conn = open_rw_connection(self.paths["db_path"], init_schema=True, force_init=True)
        healed = self.conn.execute("SELECT status, verifier_revision_notes FROM project_closure_state WHERE id = 1").fetchone()
        self.assertEqual(healed["status"], "REVISION_REQUESTED")
        self.assertIn("迁移", healed["verifier_revision_notes"])

    def test_07_human_edit_reconcile_fallback_eval_clears_dirty_and_handoff_blocks_stale_obs(self) -> None:
        self._init_stage2(["Q1"])
        self._register_inst("Q1", "ver_q1")
        nid, bid, wt = self._spawn_branch("Q1", "fam_ed")
        cand = wt / "solve.json"
        cand.write_text(json.dumps({"ok": True, "val": 1}), encoding="utf-8")

        ev1 = tool_run_isolated_eval(
            conn=self.conn,
            workspace_root=str(self.ws),
            caller_role="explorer",
            session_id="s_exp",
            question_id="Q1",
            node_id=nid,
            instrument_id="ver_q1",
            artifact_rel_path="solve.json",
            tier="official",
            linguistic_prediction="预期初版通过基线检验。",
        )
        self.assertTrue(ev1["ok"], ev1)
        obs1 = ev1["data"]["obs_id"]

        cp.pause_node(self.conn, node_id=nid, actor_source="human_ui", reason="人工调优")
        cp.mark_node_yielded(self.conn, node_id=nid)
        cand.write_text(json.dumps({"ok": True, "val": 2}), encoding="utf-8")

        res_r = cp.resume_node(self.conn, node_id=nid, actor_source="human_ui", cross_branch_note="调整了参数")
        self.assertTrue(res_r["artifact_dirty"])

        with self.assertRaises(FailClosedError) as ctx:
            tool_submit_node_handoff(
                conn=self.conn,
                workspace_root=str(self.ws),
                caller_role="lineage_companion",
                session_id="s_c",
                question_id="Q1",
                branch_id=bid,
                node_id=nid,
                mechanism_summary="尝试绑旧收据交班",
                evidence_grade="MEASURED",
                column_a_facts_md="尝试绑定改码前旧收据。",
                column_b_hypothesis_md="无",
                will_md="应被拦截。",
                candidate_rel_path="solve.json",
                obs_ids=[obs1],
            )
        self.assertEqual(ctx.exception.code, "ERR_LOCKED")

        ev2 = tool_run_isolated_eval(
            conn=self.conn,
            workspace_root=str(self.ws),
            caller_role="explorer",
            session_id="s_exp",
            question_id="Q1",
            node_id=nid,
            instrument_id="ver_q1",
            artifact_rel_path="solve.json",
            tier="official",
            linguistic_prediction="人工改码后重评验证通过。",
        )
        self.assertTrue(ev2["ok"], ev2)
        obs2 = ev2["data"]["obs_id"]
        dirty_after = int(
            self.conn.execute("SELECT artifact_dirty_since_last_obs FROM lineage_nodes WHERE node_id = ?", (nid,)).fetchone()[
                "artifact_dirty_since_last_obs"
            ]
        )
        self.assertEqual(dirty_after, 0)

        ho_ok = tool_submit_node_handoff(
            conn=self.conn,
            workspace_root=str(self.ws),
            caller_role="lineage_companion",
            session_id="s_c",
            question_id="Q1",
            branch_id=bid,
            node_id=nid,
            mechanism_summary="重评后交班",
            evidence_grade="MEASURED",
            column_a_facts_md=f"重评收据 {obs2} 与当前候选文件哈希一致。",
            column_b_hypothesis_md="准备进入下一轮。",
            will_md="继续深化。",
            candidate_rel_path="solve.json",
            obs_ids=[obs2],
        )
        self.assertTrue(ho_ok["ok"], ho_ok)

    def test_08_parse0_gate_blocks_missing_initial_instruments_and_sync_pressure_returns_control_state(self) -> None:
        cp.init_parse0_contract(
            self.conn,
            goal_and_completion_md="带初始仪器的课题目标",
            subquestions=["Q1"],
            initial_instruments=[{"question_id": "Q1", "instrument_id": "ver_q1", "instrument_role": "VERDICT"}],
            stage="STAGE1_PARSE0",
            human_signed_at=utc_now_iso(),
        )
        with self.assertRaises(FailClosedError) as ctx:
            tool_record_compliance_check(
                conn=self.conn,
                caller_role="supervisory_committee",
                session_id="s_sup",
                stage="PARSE0_GATE",
                status="PASSED",
                blocking_questions=[],
                notes="尝试绕过仪器直接放行",
            )
        self.assertEqual(ctx.exception.code, "ERR_LOCKED")

        self._register_inst("Q1", "ver_q1")
        cp.mark_stage1_works_checked(self.conn)
        ok_gate = tool_record_compliance_check(
            conn=self.conn,
            caller_role="supervisory_committee",
            session_id="s_sup",
            stage="PARSE0_GATE",
            status="PASSED",
            blocking_questions=[],
            notes="初始仪器就绪合规放行",
        )
        self.assertTrue(ok_gate["ok"], ok_gate)

        nid, _, _ = self._spawn_branch("Q1", "fam_sp")
        cp.pause_node(self.conn, node_id=nid, actor_source="human_ui", reason="检查让权")
        sp = cp.sync_session_pressure(self.conn, node_id=nid, pressure_tokens=12345)
        self.assertEqual(sp["control_state"], "PAUSE_DRAINING")
        self.assertEqual(sp["subproblem_dispatch_state"], "DISPATCHING")
        self.assertFalse(sp["human_stop_active"])


if __name__ == "__main__":
    unittest.main()
