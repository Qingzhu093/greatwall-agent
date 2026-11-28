"""v0.3.2 迁移与真实业务入口的验收剧本。"""

from __future__ import annotations

from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from core_python.mcp_server import db_schema as db
from core_python.mcp_server.control_plane.context_holiday import advance_context_holiday, begin_context_holiday
from core_python.mcp_server.control_plane.effects_outbox import claim_runtime_effects, complete_runtime_effect
from core_python.mcp_server.control_plane.observation_artifacts import publish_observation_in_tx
from core_python.mcp_server.control_plane.proposals import approve_control_proposal
from core_python.mcp_server.control_plane.scheduler_rules import get_question_order_status, schedule_control_plane_snapshot
from core_python.mcp_server.control_plane.wave_engine import (
    append_conference_statement, build_wave_hard_ledger, check_and_open_wave_conference, submit_wave_verdict_decision,
)
from core_python.mcp_server.tools_companion import tool_record_reflection_and_unlock_pull, tool_submit_node_handoff
from core_python.mcp_server.tools_explorer_eval import tool_run_isolated_eval, tool_submit_holiday_bet
from core_python.mcp_server.tools_explorer_pull import tool_query_library_catalog
from core_python.mcp_server.tools_internal_survey import (
    tool_get_internal_survey_report, tool_get_internal_survey_task, tool_publish_internal_survey_report,
    tool_request_internal_survey,
)
from core_python.mcp_server.tools_verifier import (
    tool_get_unblinded_manuscript_and_peers, tool_submit_stage1_blind_ledger, tool_submit_stage2_unblind_verdict,
)
from core_python.mcp_server.tools_library_roles import tool_publish_living_survey, tool_record_conference_minutes
from core_python.mcp_server.tools_works import tool_upgrade_instrument_with_calibration
from test_phase2_concurrency_and_cancel import _setup_eval_workspace


class TestV032Upgrade(unittest.TestCase):
    def test_empty_and_legacy_migration_is_idempotent(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "v020_legacy_sample.db"
        for source in (None, fixture):
            with self.subTest(source=source), closing(sqlite3.connect(":memory:")) as clone:
                if source is not None:
                    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as original:
                        original.backup(clone)
                self._verify_migration(clone)

    def test_real_experiment_structure_migrates_from_readonly_backup(self) -> None:
        source = os.environ.get("GREATWALL_V032_MIGRATION_FIXTURE")
        if source is None:
            self.skipTest("未指定 GREATWALL_V032_MIGRATION_FIXTURE 实机数据库")
        with tempfile.TemporaryDirectory() as tmp, closing(sqlite3.connect(Path(tmp) / "clone.db")) as clone:
            uri = Path(source).resolve().as_uri() + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True)) as original:
                original.backup(clone)
            self._verify_migration(clone)
            author = clone.execute(
                "SELECT author_node_id, author_branch_id, author_family_id FROM internal_research_ledger WHERE entry_id = 'L3-001'"
            ).fetchone()
            self.assertIsNotNone(author)
            self.assertTrue(all(author))

    def _verify_migration(self, conn: sqlite3.Connection) -> None:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        for _ in range(2):
            db.init_database_schema(conn)
            core_count = conn.execute(
                "SELECT COUNT(*) FROM pragma_table_list WHERE schema = 'main' AND type = 'table' AND name NOT LIKE 'sqlite_%'"
            ).fetchone()[0]
            self.assertEqual(core_count, 33)
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM v_library_mini_papers_catalog").fetchone()[0],
                             conn.execute("SELECT COUNT(*) FROM internal_research_ledger WHERE is_active = 1").fetchone()[0])

    def test_artifact_publication_rolls_back_when_sqlite_commit_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, closing(sqlite3.connect(":memory:", isolation_level=None)) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("CREATE TABLE parent(id INTEGER PRIMARY KEY)")
            conn.execute("CREATE TABLE child(id INTEGER REFERENCES parent(id) DEFERRABLE INITIALLY DEFERRED)")
            staging = Path(tmp) / "_staging" / "request"
            (staging / "code_snapshot").mkdir(parents=True)
            final = Path(tmp) / "Obs-001" / "code_snapshot"
            with self.assertRaises(sqlite3.IntegrityError):
                with publish_observation_in_tx(conn, staging) as publish:
                    self.assertEqual(publish("Obs-001"), (str(final), None))
                    conn.execute("INSERT INTO child VALUES (1)")
            self.assertFalse(final.exists())
            self.assertTrue((staging / "code_snapshot").exists())
            with publish_observation_in_tx(conn, staging) as publish:
                publish("Obs-001")
            self.assertTrue(final.is_dir())

    def test_observation_freezes_tools_and_handoff_continues_after_edit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ):
            ws, db_path, node_id, _, worktree = _setup_eval_workspace(tmp)
            with closing(db.open_rw_connection(db_path)) as conn:
                wt = Path(worktree)
                tools = wt / "tools"
                tools.mkdir(exist_ok=True)
                (tools / "calc.py").write_text("VALUE = 111\n", encoding="utf-8")
                (tools / "__pycache__").mkdir()
                (tools / "__pycache__" / "calc.pyc").write_bytes(b"cache")
                obs = tool_run_isolated_eval(
                    conn, str(ws), "explorer", "explorer_v032", node_id=node_id, question_id="Q1",
                    instrument_id="inst_echo", artifact_rel_path="cand_a.py", tier="official",
                    linguistic_prediction="预期正值通过。",
                )
                self.assertTrue(obs["ok"], obs)
                obs_id = obs["data"]["obs_id"]
                self.assertEqual(obs_id, "Obs-001")
                row = conn.execute("SELECT * FROM observations WHERE obs_id = ?", (obs_id,)).fetchone()
                snapshot = Path(row["frozen_code_snapshot_path"])
                self.assertEqual(snapshot.parts[-2:], (obs_id, "code_snapshot"))
                self.assertEqual((snapshot / "cand_a.py").read_bytes(), (wt / "cand_a.py").read_bytes())
                (tools / "plot_debug.py").write_text("# 后续分析\n", encoding="utf-8")
                (tools / "calc.py").write_text("VALUE = 222\n", encoding="utf-8")
                self.assertEqual((snapshot / "tools" / "calc.py").read_text(encoding="utf-8"), "VALUE = 111\n")
                self.assertFalse((snapshot / "tools" / "__pycache__").exists())
                result = tool_submit_node_handoff(
                    conn, str(ws), "lineage_companion", "comp_v032", node_id, row["branch_id"], "Q1",
                    "实测局部性质", "MEASURED", "本代已实测正值。", "后续探索其推广。", "请核验余下边界。",
                    obs_ids=[obs_id], candidate_rel_path="cand_a.py", manuscript_submissions=[{
                        "title": "正值引理", "abstract_md": "实测观察", "claim_and_proof_md": "正值验证实录",
                        "exact_scope_md": "此评测用例", "bound_obs_ids": [obs_id], "declared_citations": [], "tags": [],
                    }],
                )
                self.assertTrue(result["ok"], result)
                review = conn.execute("SELECT * FROM review_queue WHERE source_node_id = ?", (node_id,)).fetchone()
                self.assertEqual((review["source_type"], review["non_blocking"]), ("SNAPSHOT_MANUSCRIPT", 1))
                next_node = conn.execute("SELECT * FROM lineage_nodes WHERE parent_node_id = ?", (node_id,)).fetchone()
                self.assertEqual((next_node["generation"], next_node["branch_id"], next_node["node_status"]),
                                 (2, row["branch_id"], "EXPLORING"))

    def test_calibration_closes_only_named_tickets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ):
            ws, db_path, _, _, _ = _setup_eval_workspace(tmp)
            with closing(db.open_rw_connection(db_path)) as conn:
                with db.rw_immediate_tx(conn):
                    conn.executemany(
                        """INSERT INTO works_engineering_queue(ticket_id, question_id, ticket_type, instrument_id, created_at, updated_at)
                           VALUES (?, 'Q1', 'INSTRUMENT_ERROR', 'inst_echo', 'now', 'now')""",
                        [("named",), ("unnamed",)],
                    )
                upgraded = tool_upgrade_instrument_with_calibration(
                    conn, str(ws), "works_engineer", "works_v032", "Q1", "inst_echo",
                    "evaluators/echo_inst.py", "evaluators/_hidden_calibrations/cal.json",
                    resolved_ticket_ids=["named"], upgrade_summary_md="校准复核通过",
                )
                self.assertTrue(upgraded["ok"], upgraded)
                tickets = conn.execute(
                    "SELECT status, resolution_note, resolved_by_version FROM works_engineering_queue ORDER BY ticket_id"
                ).fetchall()
                self.assertEqual([tuple(row) for row in tickets], [
                    ("RESOLVED", "[Instrument v2 校准通过自动结案] 校准复核通过", 2), ("OPEN", "", None),
                ])

    def test_stage1_scoring_lock_duplicate_and_marginal_gates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ):
            _, db_path, node_id, _, _ = _setup_eval_workspace(tmp)
            with closing(db.open_rw_connection(db_path)) as conn:
                with db.rw_immediate_tx(conn):
                    conn.executemany(
                        """
                        INSERT INTO review_queue(review_id, question_id, source_node_id, source_type,
                            proposer_session_id, created_at, updated_at)
                        VALUES (?, 'Q1', ?, ?, 'author', 'now', 'now')
                        """,
                        [(rid, node_id, kind) for rid, kind in (
                            ("duplicate", "SNAPSHOT_MANUSCRIPT"), ("marginal", "SNAPSHOT_MANUSCRIPT"),
                            ("shorter", "SNAPSHOT_MANUSCRIPT"), ("second-marginal", "SNAPSHOT_MANUSCRIPT"),
                            ("composite", "COMPOSITE_FULL_GOAL"),
                        )],
                    )
                with self.assertRaisesRegex(sqlite3.IntegrityError, "L3_REQUIRES_MATCHING_VERIFIED_REVIEW"):
                    with db.rw_immediate_tx(conn):
                        conn.execute(
                            """
                            INSERT INTO internal_research_ledger(entry_id, question_id, ledger_type, title,
                                abstract_md, body_proof_or_code_md, verified_review_id, goal_coverage, created_at)
                            VALUES ('forged','Q1','L3_VERIFIED','题','摘要','证明','composite','FULL_GOAL','now')
                            """
                        )
                ledger = [{"claim": "局部性质", "evidence_location_and_quote": "独立复算结果", "is_verified": True}]
                with self.assertRaisesRegex(db.FailClosedError, "rigor_score"):
                    tool_submit_stage1_blind_ledger(conn, "library_verifier", "reader", "duplicate", "Q1", ledger, "PASS", 6)
                for rid in ("duplicate", "marginal", "shorter", "second-marginal"):
                    tool_submit_stage1_blind_ledger(conn, "library_verifier", "reader", rid, "Q1", ledger, "PASS", 8)
                with self.assertRaisesRegex(sqlite3.IntegrityError, "STAGE1_LEDGER_IMMUTABLE"):
                    with db.rw_immediate_tx(conn):
                        conn.execute("UPDATE review_queue SET rigor_score = 9 WHERE review_id = 'marginal'")
                duplicate = tool_submit_stage2_unblind_verdict(
                    conn, "library_verifier", "reader", "duplicate", "ACCEPT", novelty_score=2, significance_score=8,
                    is_equivalent_reduction=True, cross_draft_comparison_notes="证明从 100 步减为 81 步，精简 19%。",
                )
                self.assertEqual(duplicate["data"]["review_status"], "CLOSED_DUPLICATE")
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM internal_research_ledger").fetchone()[0], 0)
                marginal = tool_submit_stage2_unblind_verdict(
                    conn, "library_verifier", "reader", "marginal", "ACCEPT", l3_entry_kind="POS_THEOREM",
                    goal_coverage="PARTIAL_OR_LEMMA", publish_tier="BASELINE_UPDATE", title="边缘注记",
                    abstract_md="仅记录一个在退化边界上的已核查现象。" * 4, exact_verified_scope_md="局部退化条件",
                    novelty_score=5, significance_score=3, reviewer_comment_md="局限于已核查的退化条件",
                )
                self.assertEqual(marginal["data"]["publish_tier"], "MARGINAL_NOTE")
                self.assertEqual(marginal["data"]["overall_score"], 5.5)
                self.assertIsNone(conn.execute("SELECT baseline_entry_id FROM subproblem_runtime_state").fetchone()[0])
                cards = tool_query_library_catalog(conn, "lineage_companion", "comp", node_id, "Q1")["data"]["cards"]
                self.assertEqual((cards[-1]["is_marginal"], cards[-1]["author_family_id"]), (True, "fam_a"))
                tool_submit_stage2_unblind_verdict(
                    conn, "library_verifier", "reader", "second-marginal", "ACCEPT", l3_entry_kind="POS_THEOREM",
                    goal_coverage="PARTIAL_OR_LEMMA", publish_tier="VERIFIED_INCREMENTAL", title="另一边缘现象",
                    abstract_md="第二篇论文只记录一个孤立的边缘现象，不涉及子题的核心条件。" * 3,
                    exact_verified_scope_md="另一个局部退化条件", novelty_score=7, significance_score=4,
                    reviewer_comment_md="核查了另一个局部退化条件",
                )
                snap = schedule_control_plane_snapshot(conn)
                self.assertEqual(snap["subproblem_states"]["Q1"]["streetlight_warning"], "STREETLIGHT_WARNING")
                self.assertEqual(build_wave_hard_ledger(conn, "Q1")["streetlight_warning"], "STREETLIGHT_WARNING")
                shorter = tool_submit_stage2_unblind_verdict(
                    conn, "library_verifier", "reader", "shorter", "ACCEPT", l3_entry_kind="POS_THEOREM",
                    goal_coverage="EQUIVALENT_REDUCTION", publish_tier="VERIFIED_INCREMENTAL", title="等价精简",
                    abstract_md="明确记录同一等价命题的新证明及等价关系。" * 4, exact_verified_scope_md="既有条件",
                    novelty_score=2, significance_score=8, reviewer_comment_md="核查了两条证明的步骤数量",
                    is_equivalent_reduction=True, cross_draft_comparison_notes="证明从 50 步减为 40 步，精简 20%。",
                )
                self.assertTrue(shorter["data"]["created_l3_id"])
                self.assertEqual(conn.execute("SELECT review_status FROM review_queue WHERE review_id = 'shorter'").fetchone()[0],
                                 "CLOSED_ACCEPTED")
                self.assertIsNone(build_wave_hard_ledger(conn, "Q1")["streetlight_warning"])

    def test_internal_survey_outbox_quota_and_citations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ):
            ws, db_path, node_id, _, _ = _setup_eval_workspace(tmp)
            with closing(db.open_rw_connection(db_path)) as conn:
                session_id = f"gw-exp-{node_id}"
                query = "汇总本题现有可复核的正值正式评测记录"
                with self.assertRaisesRegex(db.FailClosedError, "37%"):
                    tool_request_internal_survey(conn, "explorer", session_id, "Q1", query)
                with db.rw_immediate_tx(conn):
                    conn.execute("UPDATE lineage_nodes SET first_reflection_unlocked = 1 WHERE node_id = ?", (node_id,))
                obs = tool_run_isolated_eval(
                    conn, str(ws), "explorer", session_id, node_id=node_id, question_id="Q1",
                    instrument_id="inst_echo", artifact_rel_path="cand_a.py", tier="official",
                    linguistic_prediction="预期正值通过。",
                )
                obs_id = obs["data"]["obs_id"]
                req = tool_request_internal_survey(conn, "explorer", session_id, "Q1", query)["data"]
                self.assertEqual(req, tool_request_internal_survey(conn, "explorer", session_id, "Q1", query)["data"])
                req_id = req["survey_req_id"]
                claimed = claim_runtime_effects(conn, owner_instance_id="host", kinds=["RUN_INTERNAL_SURVEY"])["claimed"]
                self.assertEqual(claimed[0]["survey_status"], "RUNNING")
                task = tool_get_internal_survey_task(conn, "library_chronicler", "survey", req_id)["data"]
                self.assertEqual((task["query_md"], task["observations"][0]["obs_id"]), (query, obs_id))
                report = (
                    f"## 实测证据汇总\n\n"
                    f"| 编号 | 核心观测结论 |\n"
                    f"| --- | --- |\n"
                    f"| [{obs_id}] | 输入条件与正值输出均已通过复核 |\n\n"
                    f"综合来看，[{obs_id}] " + "该正式观测记录了输入条件和正值输出，适用范围限于此评测用例。\n"
                    + "本段跨行继续汇总边界条件与未覆盖假设。" * 45
                )
                with self.assertRaisesRegex(db.FailClosedError, "路线指令"):
                    tool_publish_internal_survey_report(
                        conn, "library_chronicler", "survey", req_id, report + "建议你放弃现有路线", [], [obs_id],
                    )
                with db.rw_immediate_tx(conn):
                    conn.execute(
                        """
                        INSERT INTO external_literature_cards(
                            ref_id, question_id, title, abstract_md, exact_preconditions_md,
                            formulas_or_operators_md, read_depth, support_scope, source_citation, created_at
                        ) VALUES ('R021','Q2','跨题引文',?,'Q2 前提','','abstract_only','BACKGROUND_REFERENCE','公开摘要','now')
                        """,
                        ("该公开摘要只记录了第二道子题的一个研究背景。" * 4,),
                    )
                with self.assertRaisesRegex(db.FailClosedError, "超出子题"):
                    tool_publish_internal_survey_report(conn, "library_chronicler", "survey", req_id,
                                                       report + " [R021]", ["R021"], [obs_id])
                tool_publish_internal_survey_report(conn, "library_chronicler", "survey", req_id, report, [], [obs_id])
                complete_runtime_effect(conn, seq=claimed[0]["seq"], owner_instance_id="host")
                result = tool_get_internal_survey_report(conn, "explorer", session_id, req_id)["data"]
                self.assertEqual((result["status"], result["cited_obs_ids"]), ("FULFILLED", [obs_id]))
                tool_request_internal_survey(conn, "explorer", session_id, "Q1", "继续对照本题其他实验与同题既有成果")
                with self.assertRaisesRegex(db.FailClosedError, "配额"):
                    tool_request_internal_survey(conn, "explorer", session_id, "Q1", "第三次检查同题的输入条件与限定范围")

    def test_wave_releases_full_quota_before_synthesis_and_salvages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ):
            ws, db_path, primary, _, _ = _setup_eval_workspace(tmp)
            with closing(db.open_rw_connection(db_path)) as conn:
                for branch in ("donor", "old"):
                    wt = ws / "worktrees" / branch
                    wt.mkdir()
                    (wt / "candidate.py").write_text("x = 1\n", encoding="utf-8")
                with db.rw_immediate_tx(conn):
                    conn.execute(
                        """
                        INSERT INTO method_families(family_id,question_id,mechanism_signature,orthogonal_contrast,created_at)
                        VALUES ('fam_b','Q1','副供体构造','正交基','now')
                        """
                    )
                    conn.executemany(
                        """
                        INSERT INTO lineage_nodes(node_id,question_id,branch_id,family_id,generation,
                            node_status,worktree_abs_path,mechanism_summary,column_a_facts_md,
                            briefing_sealed_at,protection_generations_left,created_at,updated_at)
                        VALUES (?, 'Q1', ?, ?, 1, 'EXPLORING', ?, '机制摘要', '可独立核验的局部引理', 'now', 0, 'now', 'now')
                        """,
                        [("donor", "donor", "fam_b", str(ws / "worktrees" / "donor")),
                         ("old", "old", "fam_a", str(ws / "worktrees" / "old"))],
                    )
                    conn.execute("UPDATE lineage_nodes SET briefing_sealed_at = 'now' WHERE node_id = ?", (primary,))
                    conn.execute(
                        "INSERT INTO operator_runtime_slots(node_id,owner_id,launch_id,started_at) VALUES ('old','host','lease','now')"
                    )
                conference = check_and_open_wave_conference(conn, question_id="Q1", force=True, human_agenda_md="核查前提接口")
                cid = conference["conference_id"]
                agenda = json.loads(conn.execute("SELECT agenda_json FROM wave_conferences").fetchone()[0])
                self.assertEqual((len(agenda["questions"]), agenda["human_agenda_md"]), (3, "核查前提接口"))
                for nid in (primary, "donor", "old"):
                    append_conference_statement(conn, conference_id=cid, node_id=nid, round_no=1,
                                                statement_md="说明本脉确证的证据底座以及适用域和失效边界。",
                                                unverified_ideas=["尚待验真的局部算子"])
                with self.assertRaisesRegex(db.FailClosedError, "target_node_ids"):
                    append_conference_statement(conn, conference_id=cid, node_id=primary, round_no=2,
                                                statement_md="给出明确的适用域、接口前提与边界核对建议。",
                                                speech_act="CRITIQUE_SEAM")
                append_conference_statement(conn, conference_id=cid, node_id=primary, round_no=2,
                                            statement_md="给出明确的适用域、接口前提与边界核对建议。",
                                            speech_act="CRITIQUE_SEAM", target_node_ids=["donor"])
                with self.assertRaisesRegex(db.FailClosedError, "6001"):
                    tool_record_conference_minutes(conn, "conference_chair", "chair", cid, "纪" * 6001)
                tool_record_conference_minutes(conn, "conference_chair", "chair", cid, "记" * 6000)
                tool_publish_living_survey(conn, "library_chronicler", "chronicler", "Q1",
                                           "活跃仪器", "核心引理", "证伪边界", "尚无承重缺口", conference_id=cid,
                                           marginal_notes_md="仅备查的退化输入细节")
                actions = [
                    {"action_type": "SPAWN_SYNTHESIS", "primary_node_id": primary, "secondary_node_id": "donor",
                     "target_family_id": "fam_a", "synthesis_goal_md": "核查两条路线最关键的退化边界接口"},
                    {"action_type": "HIBERNATE", "target_node_id": "old", "reason_md": "该支线的核心已封存", "salvage_audit": True},
                ]
                pending = submit_wave_verdict_decision(
                    conn, workspace_root=str(ws), conference_id=cid,
                    verdict_payload={"actions": actions, "rationale_md": "休眠旧分支并拼接双供体"}, rationale_md="休眠旧分支并拼接双供体",
                )
                execution = approve_control_proposal(conn, workspace_root=str(ws), proposal_id=pending["proposal_id"])["execution"]
                self.assertEqual([item["action"] for item in execution["executed"]], ["HIBERNATE", "SPAWN_SYNTHESIS"])
                salvage = conn.execute("SELECT source_type, non_blocking FROM review_queue WHERE source_node_id = 'old'").fetchone()
                self.assertEqual(tuple(salvage), ("AUDITOR_SALVAGED_LEMMA", 1))
                self.assertEqual(conn.execute("SELECT control_state FROM lineage_nodes WHERE node_id = 'old'").fetchone()[0], "DRAIN_AFTER_TURN")
                branch = conn.execute("SELECT * FROM lineage_nodes WHERE branch_kind = 'SYNTHESIS'").fetchone()
                manifest = Path(branch["worktree_abs_path"]) / ".greatwall_donors" / "donor" / "DONOR_MANIFEST.md"
                self.assertIn(actions[0]["synthesis_goal_md"], manifest.read_text(encoding="utf-8"))
                self.assertIn("边界核对建议", manifest.read_text(encoding="utf-8"))
                self.assertIn("candidate.py", manifest.read_text(encoding="utf-8"))
                manifest.chmod(0o666)
                (manifest.parent / "candidate.py").chmod(0o666)

    def test_composite_and_saturated_convergence_unlock_next_question(self) -> None:
        for mode in ("CONVERGE_FULL_COMPOSITE", "CONVERGE_SATURATED"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ):
                ws, db_path, node_id, _, _ = _setup_eval_workspace(tmp)
                with closing(db.open_rw_connection(db_path)) as conn:
                    with db.rw_immediate_tx(conn):
                        conn.execute("UPDATE parse0_contract SET question_order_json = '[\"Q1\",\"Q2\"]', subquestions_json = '[\"Q1\",\"Q2\"]', autonomy_mode = 'AUTOPILOT'")
                        conn.execute("INSERT INTO subproblem_runtime_state(question_id, updated_at) VALUES ('Q2','now')")
                        conn.execute("UPDATE subproblem_runtime_state SET min_commitment_sec=60, started_at='2020-01-01T00:00:00Z' WHERE question_id='Q1'")
                    self.assertFalse(get_question_order_status(conn)["Q2"]["unlocked"])
                    ids = []
                    ledger = [{"claim": "子域完备", "evidence_location_and_quote": "独立核查材料", "is_verified": True}]
                    if mode == "CONVERGE_FULL_COMPOSITE":
                        for index in range(2):
                            rid = f"piece{index}"
                            with db.rw_immediate_tx(conn):
                                conn.execute(
                                    """
                                    INSERT INTO review_queue(review_id, question_id, source_node_id, source_type,
                                        proposer_session_id, column_a_snapshot_md, created_at, updated_at)
                                    VALUES (?, 'Q1', ?, 'SNAPSHOT_MANUSCRIPT', 'author', '证明正文', 'now','now')
                                    """, (rid, node_id),
                                )
                            tool_submit_stage1_blind_ledger(conn, "library_verifier", "reader", rid, "Q1", ledger, "PASS", 8)
                            entry = tool_submit_stage2_unblind_verdict(
                                conn, "library_verifier", "reader", rid, "ACCEPT", l3_entry_kind="POS_THEOREM",
                                goal_coverage="PARTIAL_OR_LEMMA", title=f"互补片段 {index}",
                                abstract_md="独立证据验证其各自覆盖子域与边界。" * 4, exact_verified_scope_md=f"子域 {index}",
                                novelty_score=8, significance_score=8,
                            )["data"]["created_l3_id"]
                            ids.append(entry)
                    cid = check_and_open_wave_conference(conn, question_id="Q1", force=True)["conference_id"]
                    tool_publish_living_survey(conn, "library_chronicler", "chronicler", "Q1",
                                               "当前基线", "核心拼图", "排雷边界", "暂无承重缺口", conference_id=cid)
                    action = {"action_type": "CONVERGE_SUBPROBLEM", "convergence_mode": mode,
                              "rationale_md": "已完成子题目标核对", "composite_entry_ids": ids}
                    applied = submit_wave_verdict_decision(conn, workspace_root=str(ws), conference_id=cid,
                                                           verdict_payload={"actions": [action], "rationale_md": "收敛"}, rationale_md="收敛")
                    if mode == "CONVERGE_FULL_COMPOSITE":
                        self.assertFalse(get_question_order_status(conn)["Q2"]["unlocked"])
                        rid = applied["executed"][0]["review_id"]
                        tool_submit_stage1_blind_ledger(conn, "library_verifier", "reader", rid, "Q1", ledger, "PASS", 9)
                        pack = tool_get_unblinded_manuscript_and_peers(conn, str(ws), "library_verifier", "reader", rid)["data"]
                        self.assertEqual([entry["entry_id"] for entry in pack["composite_entries_full"]], ids)
                        result = tool_submit_stage2_unblind_verdict(
                            conn, "library_verifier", "reader", rid, "ACCEPT", l3_entry_kind="POS_THEOREM",
                            goal_coverage="FULL_GOAL", title="组合完备总成",
                            abstract_md="两个互补子域并集覆盖所有题面完成判据。" * 4,
                            exact_verified_scope_md="题面完整适用域", novelty_score=8, significance_score=9,
                        )
                        total = conn.execute("SELECT cited_entries_json FROM internal_research_ledger WHERE entry_id = ?",
                                             (result["data"]["created_l3_id"],)).fetchone()
                        self.assertEqual(json.loads(total[0]), ids)
                    state = conn.execute("SELECT dispatch_state FROM subproblem_runtime_state WHERE question_id='Q1'").fetchone()[0]
                    self.assertEqual(state, "STOPPED_SOLVED" if ids else "PAUSED_SATURATED")
                    self.assertTrue(get_question_order_status(conn)["Q2"]["unlocked"])

    def test_reflection_category_11_and_holiday_bet_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ):
            ws, db_path, node_id, _, _ = _setup_eval_workspace(tmp)
            with closing(db.open_rw_connection(db_path)) as conn:
                with db.rw_immediate_tx(conn):
                    conn.execute("UPDATE lineage_nodes SET pressure_tokens=187200 WHERE node_id=?", (node_id,))
                with self.assertRaisesRegex(db.FailClosedError, "入口"):
                    begin_context_holiday(conn, node_id, 0.52)
                tool_record_reflection_and_unlock_pull(
                    conn, "lineage_companion", "comp", node_id, ["C11_RESEARCH_TASTE"],
                    [{"question": "当前研究方向是否真正承重？", "answer": "研究证据" * 125}], "SUFFICIENT_EVIDENCE",
                )
                start = begin_context_holiday(conn, node_id, 0.52)
                self.assertFalse(start["holiday_completed"])
                self.assertEqual(advance_context_holiday(conn, node_id, 1)["turns_completed"], 1)
                self.assertEqual(begin_context_holiday(conn, node_id, 0.52)["turns_completed"], 1)
                response = tool_submit_holiday_bet(
                    conn, "explorer", "exp", node_id, "观察边界上的反常变化并连接到单参数阈值类比。" * 2,
                    "保持其他条件不变时阈值两侧应呈现不同的可复测结果。" * 2,
                    "对阈值的两侧执行配对实验，若结果分布相同即证伪。" * 2,
                )
                self.assertTrue(response["data"]["holiday_completed"])
                self.assertTrue(advance_context_holiday(conn, node_id, 2)["holiday_completed"])
                node = conn.execute("SELECT branch_id FROM lineage_nodes WHERE node_id=?", (node_id,)).fetchone()
                tool_submit_node_handoff(
                    conn, str(ws), "lineage_companion", "comp", node_id, node["branch_id"], "Q1",
                    "独立构造", "ARTIFACT_ONLY", "现有构造与题面对齐。", "阈值假设仍未核验。", "后续按对照实测。",
                    holiday_bet_outcome={"outcome": "UNTESTED", "note_md": "尚未完成配对实验"},
                )
                saved = conn.execute("SELECT holiday_bet_json FROM lineage_nodes WHERE node_id=?", (node_id,)).fetchone()
                self.assertEqual(json.loads(saved[0])["outcome"], "UNTESTED")

    def test_holiday_two_turn_timeout_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ):
            _, db_path, node_id, _, _ = _setup_eval_workspace(tmp)
            with closing(db.open_rw_connection(db_path)) as conn:
                with db.rw_immediate_tx(conn):
                    conn.execute("UPDATE lineage_nodes SET pressure_tokens=187200, first_reflection_unlocked=1 WHERE node_id=?", (node_id,))
                begin_context_holiday(conn, node_id, 0.52)
                self.assertFalse(advance_context_holiday(conn, node_id, 1)["holiday_completed"])
                result = advance_context_holiday(conn, node_id, 2)
                self.assertEqual(result, {"holiday_completed": True, "turns_completed": 2, "outcome": "SKIPPED_TIMEOUT"})
                self.assertTrue(begin_context_holiday(conn, node_id, 0.52)["holiday_completed"])

    def test_holiday_prompt_random_and_avoids_branch_repeats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ):
            _, db_path, node_id, _, _ = _setup_eval_workspace(tmp)
            with closing(db.open_rw_connection(db_path)) as conn:
                with db.rw_immediate_tx(conn):
                    conn.execute(
                        "UPDATE lineage_nodes SET pressure_tokens=187200, first_reflection_unlocked=1 WHERE node_id=?",
                        (node_id,),
                    )
                with patch("core_python.mcp_server.control_plane.context_holiday.random.choice") as mock_choice:
                    mock_choice.side_effect = lambda seq: seq[-1]
                    first = begin_context_holiday(conn, node_id, 0.52)
                    self.assertIn(first["holiday_prompt_id"], mock_choice.call_args[0][0])
                    # 同节点重复调用幂等返回已选卡片，不重新抽卡
                    self.assertEqual(begin_context_holiday(conn, node_id, 0.52)["holiday_prompt_id"], first["holiday_prompt_id"])
                    self.assertEqual(mock_choice.call_count, 1)

    def test_handoff_dedupes_snapshot_and_blocking_level1_no_double_submit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ):
            ws, db_path, node_id, _, _ = _setup_eval_workspace(tmp)
            with closing(db.open_rw_connection(db_path)) as conn:
                branch_id = conn.execute("SELECT branch_id FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()["branch_id"]
                res = tool_submit_node_handoff(
                    conn, str(ws), "lineage_companion", "comp", node_id, branch_id, "Q1",
                    "独立阶段构造", "ARTIFACT_ONLY",
                    "完整阶段推导与可运行校验脚本已就绪，核心不等式已通过验证。" * 2,
                    "后续拟进一步拓宽参数适用范围。",
                    "下一代先在边界处补充对照组实验。",
                    candidate_rel_path="candidate.py",
                    recommended_triage={
                        "assigned_family_id": "fam_a",
                        "triage_level": "LEVEL_1",
                        "action": "SUBMIT_BLIND_REVIEW",
                        "rationale": "本轮取得阶段突破",
                    },
                    manuscript_submissions=[{
                        "title": "阶段主引理",
                        "abstract_md": "在标准约束域内给出了紧致上界与构造脚本。",
                        "claim_and_proof_md": "自包含证明正文与验证步骤，完整覆盖主命题前提条件。",
                        "exact_scope_md": "标准有界参数域",
                        "bound_obs_ids": [],
                        "declared_citations": [],
                        "tags": ["上界"],
                    }],
                    local_lemma_submissions=[{
                        "title": "阶段主引理",
                        "column_a_self_contained_proof_md": "重复旧字段提交的同标题引理证明正文超过二十个字符。",
                    }],
                )["data"]
                self.assertTrue(res["deduped_blocking_level1"])
                self.assertEqual(len(res["created_lemma_review_ids"]), 1)
                reviews = conn.execute("SELECT source_type, non_blocking FROM review_queue WHERE source_node_id = ?", (node_id,)).fetchall()
                self.assertEqual([(r["source_type"], r["non_blocking"]) for r in reviews], [("SNAPSHOT_MANUSCRIPT", 1)])
                self.assertEqual(res["node_status"], "CLOSED")
                next_node = conn.execute("SELECT node_status FROM lineage_nodes WHERE parent_node_id = ?", (node_id,)).fetchone()
                self.assertEqual(next_node["node_status"], "EXPLORING")

    def test_wave_conference_includes_recently_sealed_branches_and_supports_3_rounds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ):
            ws, db_path, primary, _, _ = _setup_eval_workspace(tmp)
            with closing(db.open_rw_connection(db_path)) as conn:
                wt_b = ws / "worktrees" / "branch_b"
                wt_b.mkdir()
                (wt_b / "candidate.py").write_text("x = 2\n", encoding="utf-8")
                with db.rw_immediate_tx(conn):
                    conn.execute(
                        "INSERT INTO method_families(family_id,question_id,mechanism_signature,orthogonal_contrast,created_at) VALUES ('fam_b','Q1','谱分解','正交基','now')"
                    )
                    conn.execute(
                        """
                        INSERT INTO lineage_nodes(node_id,question_id,branch_id,family_id,generation,
                            node_status,worktree_abs_path,mechanism_summary,column_a_facts_md,
                            briefing_sealed_at,protection_generations_left,created_at,updated_at)
                        VALUES ('node_b','Q1','branch_b','fam_b',1,'SEALED',?,'谱分解构造','独立封存实证结果','2026-11-28T10:00:00Z',0,'2026-11-28T09:00:00Z','2026-11-28T10:00:00Z')
                        """,
                        (str(wt_b),),
                    )
                    conn.execute(
                        "UPDATE lineage_nodes SET node_status='SEALED', briefing_sealed_at='2026-11-28T10:05:00Z' WHERE node_id=?",
                        (primary,),
                    )
                conf = check_and_open_wave_conference(conn, question_id="Q1", force=True, discussion_rounds=3)
                self.assertEqual(conf["status"], "ROUND_1_CRITIQUE")
                self.assertEqual(conf["participant_count"], 2)
                self.assertEqual(conf["discussion_rounds"], 3)
                cid = conf["conference_id"]
                for nid in (primary, "node_b"):
                    append_conference_statement(
                        conn, conference_id=cid, node_id=nid, round_no=1,
                        statement_md="列出本分支实测证据底座与适用范围以及尚未验证的假设。",
                    )
                append_conference_statement(
                    conn, conference_id=cid, node_id=primary, round_no=2,
                    statement_md="指出对方谱分解假设在退化边界处存在接口缝隙。",
                    speech_act="CRITIQUE_SEAM", target_node_ids=["node_b"],
                )
                append_conference_statement(
                    conn, conference_id=cid, node_id="node_b", round_no=3,
                    statement_md="确认退化边界问题并给出补充正则项的修补方案。",
                    speech_act="CONFIRM_TAKEAWAY", target_node_ids=[primary],
                )
                tool_record_conference_minutes(conn, "conference_chair", "chair", cid, "第 1 至 3 轮同行讨论完整纪要，记录了退化边界接口排雷与修补共识。")
                takeaways = json.loads(conn.execute("SELECT peer_takeaways_json FROM wave_conferences WHERE conference_id=?", (cid,)).fetchone()[0])
                self.assertTrue(any(st["round"] == 3 for st in takeaways["branch_b"]))

    def test_l2_failure_record_clears_publish_tier_and_wave_growth_uses_config_and_requires(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ):
            ws, db_path, primary, _, _ = _setup_eval_workspace(tmp)
            with closing(db.open_rw_connection(db_path)) as conn:
                with db.rw_immediate_tx(conn):
                    conn.execute("UPDATE parse0_contract SET autonomy_mode = 'AUTOPILOT'")
                    conn.execute(
                        """
                        INSERT INTO review_queue(review_id, question_id, source_node_id, source_type,
                            proposer_session_id, column_a_snapshot_md, created_at, updated_at)
                        VALUES ('rev_l2_chk', 'Q1', ?, 'SNAPSHOT_MANUSCRIPT', 'author', '待审否定命题正文', 'now', 'now')
                        """,
                        (primary,),
                    )
                ledger = [{"claim": "反例证伪", "evidence_location_and_quote": "沙箱反例实测失败", "is_verified": False}]
                refuted = tool_submit_stage1_blind_ledger(
                    conn, "library_verifier", "reader", "rev_l2_chk", "Q1", ledger, "REFUTED", 3,
                    revision_or_refutation_reason="沙箱构造反例直接证伪主结论",
                    exact_refuted_scope_md="参数 k > 1 区域全部失效",
                )["data"]
                l2_row = conn.execute(
                    "SELECT publish_tier FROM internal_research_ledger WHERE entry_id = ?",
                    (refuted["created_l2_id"],),
                ).fetchone()
                self.assertEqual(l2_row["publish_tier"], "")

                cid = check_and_open_wave_conference(conn, question_id="Q1", force=True)["conference_id"]
                tool_publish_living_survey(
                    conn, "library_chronicler", "chronicler", "Q1",
                    "活跃仪器", "核心引理", "排雷记录", "待解承重缺口", conference_id=cid,
                )
                verdict = submit_wave_verdict_decision(
                    conn, workspace_root=str(ws), conference_id=cid,
                    verdict_payload={
                        "actions": [{
                            "action_type": "OPEN_NEW_BRANCH",
                            "family_id": "fam_req",
                            "mechanism_signature": "带前置依赖的新正交路线",
                            "orthogonal_contrast": "与 fam_a 底层算子互斥",
                            "requires": ["OBS:inst_q1:PASS"],
                        }],
                        "rationale_md": "按配置保护期开新枝并绑定前置观测依赖",
                    },
                    rationale_md="按配置保护期开新枝并绑定前置观测依赖",
                )
                new_nid = verdict["executed"][0]["node_id"]
                new_node = conn.execute(
                    "SELECT protection_generations_left, requires_json FROM lineage_nodes WHERE node_id = ?",
                    (new_nid,),
                ).fetchone()
                self.assertEqual(new_node["protection_generations_left"], 1)
                self.assertEqual(json.loads(new_node["requires_json"]), ["OBS:inst_q1:PASS"])
