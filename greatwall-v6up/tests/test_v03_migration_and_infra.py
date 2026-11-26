"""第一装回归测试：v0.2 -> v0.3 无损迁移、封存不可逆硬触发器、Outbox 租约、45% 人工接管对账与口径防连坐。"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from core_python.mcp_server.control_plane import (
    approve_control_proposal,
    authorize_early_handoff,
    claim_runtime_effects,
    complete_runtime_effect,
    create_control_proposal,
    enqueue_runtime_effect,
    evaluate_subproblem_locks,
    init_parse0_contract,
    mark_node_yielded,
    pause_node,
    resume_node,
)
from core_python.mcp_server.db_schema import (
    open_rw_connection,
    reset_initialized_db_cache,
    utc_now_iso,
)

FIXTURE_V020 = Path(__file__).resolve().parent / "fixtures" / "v020_legacy_sample.db"


class TestV03MigrationAndInfra(unittest.TestCase):
    def test_v020_lossless_migration_and_triggers(self) -> None:
        self.assertTrue(FIXTURE_V020.is_file(), f"缺少旧库夹具: {FIXTURE_V020}")
        with tempfile.TemporaryDirectory() as td:
            dst = Path(td) / "migrated.db"
            shutil.copy2(FIXTURE_V020, dst)
            reset_initialized_db_cache(dst)

            conn = open_rw_connection(dst, init_schema=True, force_init=True)
            try:
                # 1. L3 verified_spec_revision 从 review_queue 真实回填为 3（绝不误标 v0）
                l3 = conn.execute(
                    "SELECT entry_id, verified_spec_revision FROM internal_research_ledger WHERE entry_id = 'L3-001'"
                ).fetchone()
                self.assertEqual(int(l3["verified_spec_revision"]), 3)

                # 2. subproblem_runtime_state 自动回填：Q1 已达标 -> STOPPED_SOLVED，Q2 -> DISPATCHING
                srs = {
                    str(r["question_id"]): dict(r)
                    for r in conn.execute("SELECT * FROM subproblem_runtime_state").fetchall()
                }
                self.assertEqual(srs["Q1"]["dispatch_state"], "STOPPED_SOLVED")
                self.assertEqual(srs["Q1"]["solved_entry_id"], "L3-001")
                self.assertEqual(int(srs["Q1"]["active_spec_revision"]), 3)
                self.assertEqual(srs["Q2"]["dispatch_state"], "DISPATCHING")

                # 3. works_engineering_queue 已放开 DISCRIMINATOR
                now = utc_now_iso()
                conn.execute(
                    """
                    INSERT INTO works_engineering_queue(
                        ticket_id, question_id, ticket_type, instrument_id, payload_json, status, created_at, updated_at
                    ) VALUES ('tkt_disc1', 'Q2', 'DISCRIMINATOR', NULL, '{}', 'OPEN', ?, ?)
                    """,
                    (now, now),
                )

                # 4. 交接包封存不可逆硬触发器生效
                conn.execute("UPDATE lineage_nodes SET briefing_sealed_at = ? WHERE node_id = 'node_q1_leg1'", (now,))
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    conn.execute(
                        "UPDATE lineage_nodes SET column_a_facts_md = 'tampered' WHERE node_id = 'node_q1_leg1'"
                    )
                self.assertIn("SEALED_HANDOFF_IMMUTABLE", str(ctx.exception))

                # 5. 外键零违规
                fk = conn.execute("PRAGMA foreign_key_check;").fetchall()
                self.assertEqual(fk, [])
            finally:
                conn.close()

    def test_outbox_lease_recovery_and_supersede(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "gw.db"
            reset_initialized_db_cache(db_path)
            conn = open_rw_connection(db_path, init_schema=True, force_init=True)
            try:
                e1 = enqueue_runtime_effect(
                    conn,
                    effect_key="spawn:n1:g1",
                    kind="SPAWN_PAIR",
                    target_type="NODE",
                    target_id="n1",
                    target_generation=1,
                    external_handle_id="gw-exp-n1",
                )
                # 幂等重复入队
                e1_dup = enqueue_runtime_effect(
                    conn,
                    effect_key="spawn:n1:g1",
                    kind="SPAWN_PAIR",
                    target_type="NODE",
                    target_id="n1",
                    target_generation=1,
                )
                self.assertTrue(e1_dup["idempotent_hit"])
                self.assertEqual(e1["seq"], e1_dup["seq"])

                # 新代数暂停自动取消旧代数 PENDING SPAWN_PAIR
                e2 = enqueue_runtime_effect(
                    conn,
                    effect_key="drain:n1:g2",
                    kind="DRAIN_AND_STOP_NODE",
                    target_type="NODE",
                    target_id="n1",
                    target_generation=2,
                    supersede_older_kinds=("SPAWN_PAIR",),
                )
                st1 = conn.execute("SELECT status FROM runtime_effects WHERE seq = ?", (e1["seq"],)).fetchone()["status"]
                self.assertEqual(st1, "CANCELLED")

                # 领单 + 模拟过期租约崩溃认领
                claimed = claim_runtime_effects(conn, owner_instance_id="inst_A", lease_sec=60)
                self.assertEqual(claimed["count"], 1)
                self.assertEqual(claimed["claimed"][0]["seq"], e2["seq"])
                conn.execute("UPDATE runtime_effects SET lease_expires_at = '2020-01-01T00:00:00Z' WHERE seq = ?", (e2["seq"],))
                reclaimed = claim_runtime_effects(conn, owner_instance_id="inst_B", lease_sec=60)
                self.assertEqual(reclaimed["count"], 1)
                self.assertTrue(reclaimed["claimed"][0]["recovered_from_expired_lease"])
                done = complete_runtime_effect(conn, seq=e2["seq"], owner_instance_id="inst_B", status="DONE")
                self.assertEqual(done["status"], "DONE")
            finally:
                conn.close()

    def test_human_takeover_45pct_sha256_reconcile_and_proposal_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td) / "ws"
            wt = ws / "worktrees" / "b_q1_1"
            (wt / "tools").mkdir(parents=True, exist_ok=True)
            cand = wt / "solve.py"
            cand.write_text("x = 1\n", encoding="utf-8")
            db_path = Path(td) / "gw.db"
            reset_initialized_db_cache(db_path)
            conn = open_rw_connection(db_path, init_schema=True, force_init=True)
            try:
                init_parse0_contract(
                    conn,
                    goal_and_completion_md="Solve Q1 and Q2",
                    subquestions=["Q1", "Q2"],
                    stage="STAGE2_EVOLVE",
                )
                now = utc_now_iso()
                conn.execute(
                    """
                    INSERT INTO lineage_nodes(
                        node_id, question_id, branch_id, family_id, generation, node_status,
                        worktree_abs_path, candidate_rel_path, companion_session_id, created_at, updated_at
                    ) VALUES ('n_q1_1', 'Q1', 'b_q1_1', 'fam_a', 1, 'EXPLORING', ?, 'solve.py', 'gw-comp-n_q1_1', ?, ?)
                    """,
                    (str(wt), now, now),
                )
                # 先记一条对应 x = 1 的有效观测
                from core_python.evaluators.isolated_runner import compute_recursive_dir_sha256, sha256_file

                conn.execute(
                    """
                    INSERT INTO observations(
                        obs_id, question_id, branch_id, node_id, instrument_id, instrument_version, tier,
                        candidate_entry_sha256, tools_dir_sha256, spec_sha256, instrument_sha256,
                        obs_status, created_at, updated_at
                    ) VALUES ('Obs-001', 'Q1', 'b_q1_1', 'n_q1_1', 'inst1', 1, 'official', ?, ?, 's', 'i', 'VALID_PASS', ?, ?)
                    """,
                    (sha256_file(cand), compute_recursive_dir_sha256(wt / "tools"), now, now),
                )

                # 45% 暂停 -> 让权 -> 人类手改代码 -> 恢复对账发现 dirty
                p_res = pause_node(conn, node_id="n_q1_1", actor_source="human_ui")
                self.assertEqual(p_res["control_state"], "PAUSE_DRAINING")
                y_res = mark_node_yielded(conn, node_id="n_q1_1")
                self.assertEqual(y_res["control_state"], "HUMAN_ACTIVE")

                cand.write_text("x = 2  # human edited\n", encoding="utf-8")
                r_res = resume_node(conn, node_id="n_q1_1", actor_source="human_ui")
                self.assertTrue(r_res["artifact_dirty"])
                nrow = conn.execute("SELECT human_modified, artifact_dirty_since_last_obs FROM lineage_nodes WHERE node_id = 'n_q1_1'").fetchone()
                self.assertEqual(int(nrow["human_modified"]), 1)
                self.assertEqual(int(nrow["artifact_dirty_since_last_obs"]), 1)

                # 授权提前交班
                e_res = authorize_early_handoff(conn, node_id="n_q1_1", actor_source="human_ui")
                self.assertEqual(e_res["control_state"], "EARLY_HANDOFF_READY")

                # 改 Q1 口径不连坐 Q2，且原本 STOPPED_SOLVED 的 Q1 自动切回 DISPATCHING；同时验证提案双端乐观锁幂等
                conn.execute(
                    """
                    INSERT INTO review_queue(
                        review_id, question_id, source_node_id, source_type, proposer_session_id,
                        review_status, spec_revision, stage1_ledger_json, stage1_locked_at,
                        final_locked_at, final_verdict, created_at, updated_at
                    ) VALUES ('rev_q1', 'Q1', 'n_q1_1', 'LEVEL1_MANUSCRIPT', 'p1', 'CLOSED_ACCEPTED', 0, '[]', ?, ?, 'ACCEPT', ?, ?),
                             ('rev_q2', 'Q2', 'n_q1_1', 'LEVEL1_MANUSCRIPT', 'p2', 'CLOSED_ACCEPTED', 0, '[]', ?, ?, 'ACCEPT', ?, ?)
                    """,
                    (now, now, now, now, now, now, now, now),
                )
                conn.execute(
                    """
                    INSERT INTO internal_research_ledger(
                        entry_id, question_id, ledger_type, l3_entry_kind, goal_coverage, verified_spec_revision,
                        title, abstract_md, exact_verified_scope_md, body_proof_or_code_md, verified_review_id, is_active, created_at
                    ) VALUES ('L3-Q1', 'Q1', 'L3_VERIFIED', 'POS_THEOREM', 'FULL_GOAL', 0, 'T1', 'A'*50, 'S1', 'B1', 'rev_q1', 1, ?),
                             ('L3-Q2', 'Q2', 'L3_VERIFIED', 'POS_THEOREM', 'FULL_GOAL', 0, 'T2', 'A'*50, 'S2', 'B2', 'rev_q2', 1, ?)
                    """,
                    (now, now),
                )
                evaluate_subproblem_locks(conn)
                q1_pre = conn.execute("SELECT dispatch_state FROM subproblem_runtime_state WHERE question_id = 'Q1'").fetchone()["dispatch_state"]
                q2_pre = conn.execute("SELECT dispatch_state FROM subproblem_runtime_state WHERE question_id = 'Q2'").fetchone()["dispatch_state"]
                self.assertEqual(q1_pre, "STOPPED_SOLVED")
                self.assertEqual(q2_pre, "STOPPED_SOLVED")

                prop = create_control_proposal(
                    conn,
                    proposed_by="gw_chief",
                    action_type="AMEND_RULING_DRAFT",
                    target_id="Q1",
                    payload={"affected_question_ids": ["Q1"], "ruling_markdown": "Tighten Q1 tolerance by 2x."},
                    rationale_md="人类要求仅收紧 Q1 容差，不动 Q2。",
                )
                ap1 = approve_control_proposal(conn, workspace_root=str(ws), proposal_id=prop["proposal_id"], decision="APPROVE", approved_by_source="human_ui")
                self.assertFalse(ap1["already_resolved"])
                self.assertIn("Q1", ap1["execution"]["reopened_questions"])
                # 双端重复点击幂等跳过
                ap2 = approve_control_proposal(conn, workspace_root=str(ws), proposal_id=prop["proposal_id"], decision="APPROVE", approved_by_source="action_card_human")
                self.assertTrue(ap2["already_resolved"])

                srs_after = {
                    str(r["question_id"]): dict(r)
                    for r in conn.execute("SELECT question_id, active_spec_revision, dispatch_state FROM subproblem_runtime_state").fetchall()
                }
                self.assertEqual(int(srs_after["Q1"]["active_spec_revision"]), 1)
                self.assertEqual(srs_after["Q1"]["dispatch_state"], "DISPATCHING")
                # Q2 毫发无损！
                self.assertEqual(int(srs_after["Q2"]["active_spec_revision"]), 0)
                self.assertEqual(srs_after["Q2"]["dispatch_state"], "STOPPED_SOLVED")
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
