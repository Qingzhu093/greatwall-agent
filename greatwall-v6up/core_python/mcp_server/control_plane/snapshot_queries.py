"""控制面只读 SQL 汇总查询层（从 scheduler_rules.py 拆出，严禁包含任何写操作）。

职责边界：
- 所有函数均为纯 SELECT 只读查询，天然兼容 `open_ro_connection` 与一致只读事务；
- 仅向上层 `scheduler_rules.py` 提供结构化行/计数字典，不含复杂业务策略判断。
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def fetch_active_parse0_row(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM parse0_contract WHERE contract_id = 'active'").fetchone()
    return dict(row) if row is not None else None


def fetch_closure_state_row(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM project_closure_state WHERE id = 1").fetchone()
    return dict(row) if row is not None else None


def fetch_l3_counts_by_question(conn: sqlite3.Connection) -> tuple[dict[str, int], dict[str, int]]:
    """按各子题当前生效口径 `subproblem_runtime_state.active_spec_revision` 统计 FULL_GOAL 与总 L3 数（改 Q1 不连坐 Q2）。"""
    spec_by_q = {
        str(r["question_id"]): int(r["active_spec_revision"] or 0)
        for r in conn.execute("SELECT question_id, active_spec_revision FROM subproblem_runtime_state").fetchall()
    }
    p0_row = conn.execute("SELECT latest_spec_revision FROM parse0_contract WHERE contract_id = 'active'").fetchone()
    fallback_rev = int(p0_row["latest_spec_revision"] or 0) if p0_row else 0

    full_counts: dict[str, int] = {}
    any_counts: dict[str, int] = {}
    for r in conn.execute(
        """
        SELECT question_id, goal_coverage, verified_spec_revision
        FROM internal_research_ledger
        WHERE ledger_type = 'L3_VERIFIED' AND is_active = 1
        """
    ).fetchall():
        q = str(r["question_id"])
        any_counts[q] = any_counts.get(q, 0) + 1
        req_rev = spec_by_q.get(q, fallback_rev)
        if str(r["goal_coverage"] or "") == "FULL_GOAL" and int(r["verified_spec_revision"] or 0) >= req_rev:
            full_counts[q] = full_counts.get(q, 0) + 1
    return full_counts, any_counts


def fetch_subproblem_states(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    return {
        str(r["question_id"]): dict(r)
        for r in conn.execute("SELECT * FROM subproblem_runtime_state ORDER BY question_id ASC").fetchall()
    }


def fetch_v03_queues(conn: sqlite3.Connection) -> dict[str, Any]:
    pending_proposals = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM control_proposals WHERE status = 'PENDING_HUMAN' ORDER BY created_at ASC"
        ).fetchall()
    ]
    active_conferences = [
        dict(r)
        for r in conn.execute(
            """
            SELECT * FROM wave_conferences
            WHERE status NOT IN ('COMPLETED','CANCELLED','EXPIRED','FAILED')
            ORDER BY created_at ASC
            """
        ).fetchall()
    ]
    open_lemma_gaps = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM open_lemma_gaps WHERE status = 'OPEN' ORDER BY question_id, created_at ASC"
        ).fetchall()
    ]
    living_surveys: dict[str, dict[str, Any]] = {}
    for r in conn.execute(
        """
        SELECT s.* FROM subproblem_living_surveys s
        INNER JOIN (
            SELECT question_id, MAX(revision) AS max_rev
            FROM subproblem_living_surveys
            GROUP BY question_id
        ) m ON s.question_id = m.question_id AND s.revision = m.max_rev
        ORDER BY s.question_id ASC
        """
    ).fetchall():
        living_surveys[str(r["question_id"])] = dict(r)
    pending_effects_count = int(
        conn.execute("SELECT COUNT(*) AS cnt FROM runtime_effects WHERE status IN ('PENDING','RUNNING')").fetchone()["cnt"] or 0
    )
    return {
        "pending_proposals": pending_proposals,
        "active_conferences": active_conferences,
        "open_lemma_gaps": open_lemma_gaps,
        "living_surveys": living_surveys,
        "pending_effects_count": pending_effects_count,
    }


def fetch_active_branch_family_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in conn.execute(
            """
            SELECT question_id, branch_id, family_id
            FROM lineage_nodes
            WHERE node_status IN ('EXPLORING', 'ACTIVE_REVISING', 'AWAITING_TRIAGE', 'PENDING_REVIEW')
            GROUP BY question_id, branch_id
            """
        ).fetchall()
    ]


def fetch_topology_raw_data(conn: sqlite3.Connection, question_filter: str = "ALL") -> dict[str, Any]:
    qf = str(question_filter or "ALL").strip()
    is_all = qf.upper() == "ALL"

    if is_all:
        fam_rows = [dict(r) for r in conn.execute("SELECT * FROM method_families ORDER BY question_id, family_id").fetchall()]
        all_nodes = [
            dict(r)
            for r in conn.execute(
                """
                SELECT node_id, question_id, branch_id, family_id, parent_node_id, generation,
                       spec_revision, node_status, worktree_abs_path, retained_snapshot_abs_path,
                       mechanism_summary, evidence_grade, candidate_rel_path, revise_count,
                       inplace_repair_count, last_revision_requests_json, pending_handoff_reason,
                       pressure_tokens, effective_context_window, first_reflection_unlocked,
                       created_at, updated_at
                FROM lineage_nodes
                ORDER BY generation ASC, created_at ASC
                """
            ).fetchall()
        ]
        rev_rows = [
            dict(r)
            for r in conn.execute(
                """
                SELECT r.review_id, r.question_id, r.source_node_id, r.manuscript_title,
                       r.final_verdict, r.revision_requests_json, r.updated_at,
                       n.branch_id, n.family_id, n.retained_snapshot_abs_path, n.worktree_abs_path
                FROM review_queue r
                LEFT JOIN lineage_nodes n ON n.node_id = r.source_node_id
                WHERE r.review_status = 'CLOSED_REVISE'
                  AND r.source_type != 'LOCAL_LEMMA_SUBMISSION'
                ORDER BY r.updated_at DESC
                """
            ).fetchall()
        ]
    else:
        fam_rows = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM method_families WHERE question_id = ? ORDER BY family_id",
                (qf,),
            ).fetchall()
        ]
        all_nodes = [
            dict(r)
            for r in conn.execute(
                """
                SELECT node_id, question_id, branch_id, family_id, parent_node_id, generation,
                       spec_revision, node_status, worktree_abs_path, retained_snapshot_abs_path,
                       mechanism_summary, evidence_grade, candidate_rel_path, revise_count,
                       inplace_repair_count, last_revision_requests_json, pending_handoff_reason,
                       pressure_tokens, effective_context_window, first_reflection_unlocked,
                       created_at, updated_at
                FROM lineage_nodes
                WHERE question_id = ?
                ORDER BY generation ASC, created_at ASC
                """,
                (qf,),
            ).fetchall()
        ]
        rev_rows = [
            dict(r)
            for r in conn.execute(
                """
                SELECT r.review_id, r.question_id, r.source_node_id, r.manuscript_title,
                       r.final_verdict, r.revision_requests_json, r.updated_at,
                       n.branch_id, n.family_id, n.retained_snapshot_abs_path, n.worktree_abs_path
                FROM review_queue r
                LEFT JOIN lineage_nodes n ON n.node_id = r.source_node_id
                WHERE r.review_status = 'CLOSED_REVISE'
                  AND r.source_type != 'LOCAL_LEMMA_SUBMISSION'
                  AND r.question_id = ?
                ORDER BY r.updated_at DESC
                """,
                (qf,),
            ).fetchall()
        ]

    total_live_branches = int(
        conn.execute(
            """
            SELECT COUNT(DISTINCT branch_id) AS cnt
            FROM lineage_nodes
            WHERE node_status IN ('EXPLORING', 'ACTIVE_REVISING', 'AWAITING_TRIAGE', 'PENDING_REVIEW')
            """
        ).fetchone()["cnt"]
        or 0
    )
    reviewed_source_nodes = {
        str(r["source_node_id"])
        for r in conn.execute("SELECT source_node_id FROM review_queue").fetchall()
    }
    return {
        "fam_rows": fam_rows,
        "all_nodes": all_nodes,
        "rev_rows": rev_rows,
        "total_live_branches": total_live_branches,
        "reviewed_source_nodes": reviewed_source_nodes,
    }


def fetch_closure_gate_raw_data(conn: sqlite3.Connection) -> dict[str, Any]:
    p0 = fetch_active_parse0_row(conn)
    closure = fetch_closure_state_row(conn)
    full_counts, all_l3_counts = fetch_l3_counts_by_question(conn)
    pending_reval = [
        dict(r)
        for r in conn.execute(
            "SELECT queue_id, obs_id, question_id FROM pending_revalidation_queue WHERE status = 'PENDING'"
        ).fetchall()
    ]
    pending_reviews = [
        dict(r)
        for r in conn.execute(
            "SELECT review_id, question_id, review_status FROM review_queue WHERE review_status IN ('STAGE1_BLIND', 'STAGE2_UNBLIND')"
        ).fetchall()
    ]
    used_handoffs = int(
        conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM lineage_nodes
            WHERE node_status IN ('AWAITING_TRIAGE','PENDING_REVIEW','BLOCKED_L4B','SEALED','CLOSED')
               OR (column_a_facts_md IS NOT NULL AND TRIM(column_a_facts_md) != '')
            """
        ).fetchone()["cnt"]
        or 0
    )
    used_official_evals = int(
        conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM observations
            WHERE tier IN ('official','heavy') AND revalidated_from_obs_id IS NULL
            """
        ).fetchone()["cnt"]
        or 0
    )
    return {
        "p0": p0,
        "closure": closure,
        "full_counts": full_counts,
        "all_l3_counts": all_l3_counts,
        "pending_reval": pending_reval,
        "pending_reviews": pending_reviews,
        "used_handoffs": used_handoffs,
        "used_official_evals": used_official_evals,
    }


def fetch_snapshot_queues_and_tables(conn: sqlite3.Connection) -> dict[str, Any]:
    awaiting_triage = [
        dict(r)
        for r in conn.execute(
            """
            SELECT node_id, question_id, branch_id, family_id, evidence_grade, mechanism_summary
            FROM lineage_nodes
            WHERE node_status = 'AWAITING_TRIAGE'
            ORDER BY updated_at ASC
            """
        ).fetchall()
    ]
    active_nodes = [
        dict(r)
        for r in conn.execute(
            """
            SELECT node_id, question_id, branch_id, family_id, generation, branch_kind,
                   protection_generations_left, branch_budget_nodes_left, companion_session_id,
                   briefing_sealed_at, secondary_donor_node_id, node_status, control_state,
                   control_generation, personal_turn_active, human_modified, artifact_dirty_since_last_obs,
                   worktree_abs_path, requires_json, premise_revoked, pressure_tokens,
                   effective_context_window, spec_revision,
                   first_reflection_unlocked, last_revision_requests_json, lane_assignment,
                   will_md, explorer_will_md, pending_handoff_mode, pending_handoff_reason, updated_at
            FROM lineage_nodes
            WHERE node_status IN ('EXPLORING', 'ACTIVE_REVISING')
            ORDER BY created_at ASC
            """
        ).fetchall()
    ]
    latest_briefings: dict[str, str] = {}
    for br in conn.execute(
        """
        SELECT node_id, sec1_mechanism, sec2_verified_baseline, sec3_bottleneck,
               sec4_dead_ends, sec5_immediate_will, created_at
        FROM lineage_briefings
        ORDER BY created_at ASC
        """
    ).fetchall():
        bnid = str(br["node_id"])
        latest_briefings[bnid] = "\n\n".join(
            [
                f"#### 1. 核心机制\n{br['sec1_mechanism']}",
                f"#### 2. 已证实基线与返工要求\n{br['sec2_verified_baseline']}",
                f"#### 3. 当前瓶颈\n{br['sec3_bottleneck']}",
                f"#### 4. 关键死胡同\n{br['sec4_dead_ends']}",
                f"#### 5. 本代首要遗嘱 (Immediate Will)\n{br['sec5_immediate_will']}",
            ]
        )

    blind_reviews = [
        dict(r)
        for r in conn.execute(
            """
            SELECT review_id, question_id, source_node_id, source_type, review_status, proposer_session_id
            FROM review_queue
            WHERE review_status IN ('STAGE1_BLIND', 'STAGE2_UNBLIND')
            ORDER BY created_at ASC
            """
        ).fetchall()
    ]
    pending_surveys = [
        dict(r)
        for r in conn.execute(
            "SELECT req_id, question_id, node_id, topic_query, reason FROM survey_requests WHERE status = 'PENDING' ORDER BY created_at ASC"
        ).fetchall()
    ]
    open_works = [
        dict(r)
        for r in conn.execute(
            "SELECT ticket_id, question_id, ticket_type, instrument_id, payload_json, updated_at FROM works_engineering_queue WHERE status = 'OPEN' ORDER BY created_at ASC"
        ).fetchall()
    ]
    pending_reval = [
        dict(r)
        for r in conn.execute(
            "SELECT queue_id, obs_id, question_id, target_instrument_id, target_version, updated_at FROM pending_revalidation_queue WHERE status = 'PENDING' ORDER BY created_at ASC"
        ).fetchall()
    ]
    unhealthy_instruments = [
        dict(r)
        for r in conn.execute(
            "SELECT instrument_id, version, question_id, instrument_role, consecutive_error_count, updated_at FROM instruments WHERE is_active = 1 AND health_status = 'UNHEALTHY'"
        ).fetchall()
    ]
    active_instruments = [
        dict(r)
        for r in conn.execute(
            """
            SELECT instrument_id, version, question_id, instrument_role,
                   artifact_schema, health_status, default_spec_json, updated_at
            FROM instruments
            WHERE is_active = 1
            ORDER BY instrument_id, version
            """
        ).fetchall()
    ]
    ambiguous_alerts = [
        dict(r)
        for r in conn.execute(
            "SELECT alert_id, stage, notes, created_at FROM compliance_alerts WHERE status = 'ALERT_AMBIGUOUS_SPEC' ORDER BY created_at DESC LIMIT 10"
        ).fetchall()
    ]
    external_lit_count = int(conn.execute("SELECT COUNT(*) AS cnt FROM external_literature_cards").fetchone()["cnt"] or 0)
    latest_hb_row = conn.execute(
        """
        SELECT alert_id, stage, status, blocking_questions_json, notes, created_at
        FROM compliance_alerts
        WHERE stage = 'STAGE2_HEARTBEAT'
        ORDER BY created_at DESC LIMIT 1
        """
    ).fetchone()
    return {
        "awaiting_triage": awaiting_triage,
        "active_nodes": active_nodes,
        "latest_briefings": latest_briefings,
        "blind_reviews": blind_reviews,
        "pending_surveys": pending_surveys,
        "open_works": open_works,
        "pending_reval": pending_reval,
        "unhealthy_instruments": unhealthy_instruments,
        "active_instruments": active_instruments,
        "ambiguous_alerts": ambiguous_alerts,
        "external_lit_count": external_lit_count,
        "latest_hb_row": dict(latest_hb_row) if latest_hb_row is not None else None,
    }


def fetch_parse0_subquestions_and_order(conn: sqlite3.Connection) -> tuple[list[str], list[str]]:
    row = conn.execute("SELECT subquestions_json, question_order_json FROM parse0_contract WHERE contract_id = 'active'").fetchone()
    req_qs = json.loads(row["subquestions_json"]) if row else ["Q1"]
    q_order = json.loads(row["question_order_json"]) if row else []
    return req_qs, q_order
