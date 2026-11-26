"""生成原汁原味的 v0.2.0-alpha.1 SQLite 数据库迁移夹具（纯 v0.2 DDL，独立于 v0.3 代码）。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

V020_MINIMAL_SCHEMA = """
CREATE TABLE parse0_contract (
    contract_id TEXT PRIMARY KEY,
    goal_and_completion_md TEXT NOT NULL,
    subquestions_json TEXT NOT NULL DEFAULT '["Q1"]',
    question_order_json TEXT NOT NULL DEFAULT '[]',
    initial_instruments_json TEXT NOT NULL DEFAULT '[]',
    seed_families_json TEXT NOT NULL DEFAULT '[]',
    total_budget_json TEXT NOT NULL DEFAULT '{}',
    min_commitment_window_sec INTEGER NOT NULL DEFAULT 0,
    delivery_spec_md TEXT NOT NULL DEFAULT '',
    shared_inputs_json TEXT NOT NULL DEFAULT '[]',
    stage1_works_checked INTEGER NOT NULL DEFAULT 0,
    latest_spec_revision INTEGER NOT NULL DEFAULT 0,
    latest_ruling_summary_md TEXT NOT NULL DEFAULT '',
    ruling_fingerprint_sha256 TEXT NOT NULL DEFAULT '',
    human_signed_at TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT 'STAGE1_PARSE0'
        CHECK(stage IN ('STAGE1_PARSE0','STAGE2_EVOLVE','STAGE3_CONSOLIDATE','CLOSED_VERIFIED')),
    consecutive_non_l1_handoffs INTEGER NOT NULL DEFAULT 0,
    epoch_id INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE observations (
    obs_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL,
    branch_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    instrument_version INTEGER NOT NULL,
    tier TEXT NOT NULL CHECK(tier IN ('official','heavy')),
    candidate_entry_sha256 TEXT NOT NULL,
    tools_dir_sha256 TEXT NOT NULL,
    spec_sha256 TEXT NOT NULL,
    instrument_sha256 TEXT NOT NULL,
    cache_key TEXT NOT NULL DEFAULT '',
    stage_a_artifact_path TEXT,
    revalidated_from_obs_id TEXT REFERENCES observations(obs_id),
    obs_status TEXT NOT NULL,
    tracks_json TEXT NOT NULL DEFAULT '{}',
    details_text TEXT DEFAULT '',
    linguistic_prediction TEXT DEFAULT '',
    spec_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE lineage_nodes (
    node_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL,
    branch_id TEXT NOT NULL,
    family_id TEXT,
    parent_node_id TEXT,
    generation INTEGER NOT NULL DEFAULT 1,
    node_status TEXT NOT NULL DEFAULT 'EXPLORING',
    worktree_abs_path TEXT NOT NULL,
    retained_snapshot_abs_path TEXT,
    mechanism_summary TEXT DEFAULT '',
    evidence_grade TEXT NOT NULL DEFAULT 'NONE',
    requires_json TEXT NOT NULL DEFAULT '[]',
    premise_revoked INTEGER NOT NULL DEFAULT 0,
    revise_count INTEGER NOT NULL DEFAULT 0,
    column_a_facts_md TEXT DEFAULT '',
    column_b_hypothesis_md TEXT DEFAULT '',
    will_md TEXT DEFAULT '',
    sanitized_code_diff_md TEXT DEFAULT '',
    candidate_rel_path TEXT,
    bound_obs_ids_json TEXT NOT NULL DEFAULT '[]',
    pressure_tokens INTEGER NOT NULL DEFAULT 0,
    effective_context_window INTEGER NOT NULL DEFAULT 500000,
    spec_revision INTEGER NOT NULL DEFAULT 0,
    first_reflection_unlocked INTEGER NOT NULL DEFAULT 0,
    inplace_repair_count INTEGER NOT NULL DEFAULT 0,
    reopen_condition TEXT,
    last_revision_requests_json TEXT NOT NULL DEFAULT '[]',
    reflections_json TEXT NOT NULL DEFAULT '[]',
    scratch_log_json TEXT NOT NULL DEFAULT '[]',
    lane_assignment TEXT DEFAULT '',
    explorer_will_md TEXT NOT NULL DEFAULT '',
    pending_handoff_mode TEXT,
    pending_handoff_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE review_queue (
    review_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL,
    source_node_id TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK(source_type IN ('LEVEL1_MANUSCRIPT','LEVEL4A_BARRIER','AUDITOR_SALVAGED_LEMMA')),
    proposer_session_id TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'STAGE1_BLIND',
    manuscript_title TEXT NOT NULL DEFAULT '',
    spec_revision INTEGER NOT NULL DEFAULT 0,
    column_a_snapshot_md TEXT NOT NULL DEFAULT '',
    column_b_snapshot_md TEXT NOT NULL DEFAULT '',
    bound_obs_ids_json TEXT NOT NULL DEFAULT '[]',
    artifact_rel_path TEXT,
    sanitized_code_diff_md TEXT NOT NULL DEFAULT '',
    stage1_ledger_json TEXT,
    stage1_locked_at TEXT,
    final_locked_at TEXT,
    final_verdict TEXT,
    revision_requests_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE internal_research_ledger (
    entry_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL,
    ledger_type TEXT NOT NULL,
    l3_entry_kind TEXT,
    goal_coverage TEXT,
    l2_category TEXT,
    title TEXT NOT NULL,
    abstract_md TEXT NOT NULL,
    exact_verified_scope_md TEXT,
    exact_refuted_scope_md TEXT,
    body_proof_or_code_md TEXT NOT NULL,
    bound_obs_ids_json TEXT NOT NULL DEFAULT '[]',
    verified_review_id TEXT REFERENCES review_queue(review_id),
    is_active INTEGER NOT NULL DEFAULT 1,
    recheck_required INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE works_engineering_queue (
    ticket_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL,
    ticket_type TEXT NOT NULL CHECK(ticket_type IN ('INSTRUMENT_ERROR','PAIN_POINT','DUPLICATE_TOOL','EXPLOIT')),
    instrument_id TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','RESOLVED')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE project_closure_state (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    status TEXT NOT NULL DEFAULT 'OPEN',
    delivery_mode TEXT,
    latest_delivery_id TEXT,
    latest_delivery_sha256 TEXT,
    verifier_audited_delivery_id TEXT,
    verifier_audited_delivery_sha256 TEXT,
    verifier_final_audit_passed INTEGER NOT NULL DEFAULT 0,
    verifier_revision_notes TEXT NOT NULL DEFAULT '',
    human_stop_requested_at TEXT,
    supervisory_signed_at TEXT,
    updated_at TEXT NOT NULL
);
"""


def build_fixture(out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()
    conn = sqlite3.connect(str(out_path))
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(V020_MINIMAL_SCHEMA)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    with conn:
        conn.execute(
            """
            INSERT INTO parse0_contract(
                contract_id, goal_and_completion_md, subquestions_json, question_order_json,
                initial_instruments_json, seed_families_json, total_budget_json,
                min_commitment_window_sec, delivery_spec_md, shared_inputs_json,
                stage1_works_checked, latest_spec_revision, latest_ruling_summary_md,
                ruling_fingerprint_sha256, human_signed_at, stage, consecutive_non_l1_handoffs,
                epoch_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "active",
                "Solve Q1 and Q2 with rigorous verification.",
                json.dumps(["Q1", "Q2"]),
                "[]",
                "[]",
                "[]",
                json.dumps({"max_total_handoffs": 20}),
                0,
                "Deliver full report and runnable scripts.",
                "[]",
                1,
                3,
                "v3 ruling amendment",
                "fp_v3_legacy",
                now,
                "STAGE2_EVOLVE",
                0,
                1,
                now,
                now,
            ),
        )
        conn.execute("INSERT INTO project_closure_state(id, status, updated_at) VALUES (1, 'OPEN', ?)", (now,))
        conn.execute(
            """
            INSERT INTO lineage_nodes(
                node_id, question_id, branch_id, family_id, generation, node_status,
                worktree_abs_path, mechanism_summary, evidence_grade, spec_revision, created_at, updated_at
            ) VALUES ('node_q1_leg1', 'Q1', 'b_q1_1', 'fam_a', 1, 'SEALED', 'C:/tmp/wt1', 'old mech', 'MEASURED', 3, ?, ?)
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO review_queue(
                review_id, question_id, source_node_id, source_type, proposer_session_id,
                review_status, manuscript_title, spec_revision, column_a_snapshot_md,
                column_b_snapshot_md, stage1_ledger_json, stage1_locked_at, final_locked_at,
                final_verdict, created_at, updated_at
            ) VALUES ('rev_leg1', 'Q1', 'node_q1_leg1', 'LEVEL1_MANUSCRIPT', 'sess_p1',
                      'CLOSED_ACCEPTED', 'Legacy Q1 Full Sol', 3, 'A facts', 'B hyp',
                      ?, ?, ?, 'ACCEPT', ?, ?)
            """,
            (json.dumps([{"claim": "c1", "evidence_location_and_quote": "q1"}]), now, now, now, now),
        )
        conn.execute(
            """
            INSERT INTO internal_research_ledger(
                entry_id, question_id, ledger_type, l3_entry_kind, goal_coverage,
                title, abstract_md, exact_verified_scope_md, body_proof_or_code_md,
                verified_review_id, is_active, created_at
            ) VALUES ('L3-001', 'Q1', 'L3_VERIFIED', 'POS_THEOREM', 'FULL_GOAL',
                      'Legacy Q1 Full Sol',
                      'A sufficiently long abstract describing the verified legacy Q1 full goal result under v3.',
                      'Valid under v3', 'Proof body', 'rev_leg1', 1, ?)
            """,
            (now,),
        )
        conn.execute(
            """
            INSERT INTO works_engineering_queue(
                ticket_id, question_id, ticket_type, instrument_id, payload_json, status, created_at, updated_at
            ) VALUES ('tkt_leg1', 'Q1', 'PAIN_POINT', NULL, ?, 'OPEN', ?, ?)
            """,
            (json.dumps({"description": "old pain"}), now, now),
        )
    conn.close()


if __name__ == "__main__":
    target = ROOT / "tests" / "fixtures" / "v020_legacy_sample.db"
    build_fixture(target)
    print(f"Created {target} ({target.stat().st_size} bytes)")
