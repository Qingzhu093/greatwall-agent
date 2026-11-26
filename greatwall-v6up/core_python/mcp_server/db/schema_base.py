"""GreatWall Agent v0.3 基础表 DDL（既有 19 张核心表与 3 条防作弊硬触发器，含 v0.3 增量列与枚举）。"""

from __future__ import annotations

BASE_SCHEMA_SQL = """
-- ============================================================================
-- 1. Parse 0 六项启动契约表 (parse0_contract)
-- ============================================================================
CREATE TABLE IF NOT EXISTS parse0_contract (
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
    autonomy_mode TEXT NOT NULL DEFAULT 'WAVE_CONFIRM'
        CHECK(autonomy_mode IN ('WAVE_CONFIRM','AUTOPILOT')),
    human_signed_at TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT 'STAGE1_PARSE0'
        CHECK(stage IN ('STAGE1_PARSE0','STAGE2_EVOLVE','STAGE3_CONSOLIDATE','CLOSED_VERIFIED')),
    consecutive_non_l1_handoffs INTEGER NOT NULL DEFAULT 0,
    epoch_id INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- ============================================================================
-- 2. 科研仪器科注册与版本表 (instruments)
-- ============================================================================
CREATE TABLE IF NOT EXISTS instruments (
    instrument_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    question_id TEXT NOT NULL,
    instrument_role TEXT NOT NULL CHECK(instrument_role IN ('VERDICT','PROBE','ENV')),
    instrument_rel_path TEXT NOT NULL,
    frozen_snapshot_path TEXT,
    instrument_sha256 TEXT NOT NULL,
    calibration_suite_rel_path TEXT,
    artifact_schema TEXT NOT NULL DEFAULT 'python_run',
    plugin_protocol_version TEXT NOT NULL DEFAULT 'v3',
    health_status TEXT NOT NULL DEFAULT 'HEALTHY' CHECK(health_status IN ('HEALTHY','UNHEALTHY')),
    consecutive_error_count INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    default_spec_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (instrument_id, version)
);
CREATE INDEX IF NOT EXISTS idx_instruments_q_active ON instruments(question_id, is_active);

-- ============================================================================
-- 3. 真相 ①：观测账 (observations，旧收据永久不可覆写)
-- ============================================================================
CREATE TABLE IF NOT EXISTS observations (
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
    obs_status TEXT NOT NULL CHECK(obs_status IN (
        'VALID_PASS','MEASURED_REJECTION','VALID_UNDECIDED',
        'CANDIDATE_ERROR','INSTRUMENT_ERROR','INFRA_ERROR',
        'PENDING_REVALIDATION','SUPERSEDED_REVALIDATED','INCOMPATIBLE'
    )),
    tracks_json TEXT NOT NULL DEFAULT '{}',
    details_text TEXT DEFAULT '',
    linguistic_prediction TEXT DEFAULT '',
    spec_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_obs_node_q ON observations(question_id, node_id, obs_status);
CREATE INDEX IF NOT EXISTS idx_obs_cache_key ON observations(cache_key, obs_status);
CREATE INDEX IF NOT EXISTS idx_obs_inst ON observations(instrument_id, instrument_version, obs_status);

-- ============================================================================
-- 4. 诊断日志 (probe_diagnostic_logs，高频 probe 绝不污染 observations)
-- ============================================================================
CREATE TABLE IF NOT EXISTS probe_diagnostic_logs (
    probe_id TEXT PRIMARY KEY,
    node_id TEXT NOT NULL,
    question_id TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    instrument_version INTEGER NOT NULL,
    status TEXT NOT NULL,
    tracks_json TEXT NOT NULL DEFAULT '{}',
    details_text TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_probe_node ON probe_diagnostic_logs(node_id, created_at);

-- ============================================================================
-- 5. 重型排队作业 (async_eval_jobs，入队即冻结现场，幂等取回仅扣费一次)
-- ============================================================================
CREATE TABLE IF NOT EXISTS async_eval_jobs (
    job_id TEXT PRIMARY KEY,
    obs_id TEXT,
    question_id TEXT NOT NULL,
    branch_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    instrument_version INTEGER NOT NULL,
    artifact_snapshot_path TEXT NOT NULL,
    frozen_instrument_path TEXT,
    spec_snapshot_json TEXT NOT NULL,
    cache_key TEXT NOT NULL,
    linguistic_prediction TEXT NOT NULL,
    declared_refs_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL CHECK(status IN ('QUEUED','RUNNING','COMPLETED','FAILED')),
    budget_charged INTEGER NOT NULL DEFAULT 0,
    error_text TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_async_jobs_status ON async_eval_jobs(status, created_at);

-- ============================================================================
-- 6. 真相 ②：门派私有谱系 DAG (lineage_nodes，含 v0.3 保护期/合体/接管字段)
-- ============================================================================
CREATE TABLE IF NOT EXISTS lineage_nodes (
    node_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL,
    branch_id TEXT NOT NULL,
    family_id TEXT,
    parent_node_id TEXT,
    generation INTEGER NOT NULL DEFAULT 1,
    branch_kind TEXT NOT NULL DEFAULT 'PURE'
        CHECK(branch_kind IN ('PURE','PROTECTED','SYNTHESIS','HUMAN_SEEDED')),
    protection_generations_left INTEGER NOT NULL DEFAULT 2,
    branch_budget_nodes_left INTEGER,
    companion_session_id TEXT NOT NULL DEFAULT '',
    briefing_sealed_at TEXT,
    secondary_donor_node_id TEXT,
    node_status TEXT NOT NULL DEFAULT 'EXPLORING' CHECK(node_status IN (
        'EXPLORING','AWAITING_TRIAGE','PENDING_REVIEW','ACTIVE_REVISING',
        'BLOCKED_L4B','SEALED','CLOSED'
    )),
    control_state TEXT NOT NULL DEFAULT 'AUTO_RUNNING',
    control_generation INTEGER NOT NULL DEFAULT 1,
    personal_turn_active INTEGER NOT NULL DEFAULT 0,
    human_modified INTEGER NOT NULL DEFAULT 0,
    artifact_dirty_since_last_obs INTEGER NOT NULL DEFAULT 0,
    last_reconciled_candidate_sha256 TEXT NOT NULL DEFAULT '',
    last_reconciled_tools_sha256 TEXT NOT NULL DEFAULT '',
    transient_retry_count INTEGER NOT NULL DEFAULT 0,
    worktree_abs_path TEXT NOT NULL,
    retained_snapshot_abs_path TEXT,
    mechanism_summary TEXT DEFAULT '',
    evidence_grade TEXT NOT NULL DEFAULT 'NONE' CHECK(evidence_grade IN ('NONE','ARTIFACT_ONLY','MEASURED')),
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
    pending_handoff_mode TEXT CHECK(pending_handoff_mode IS NULL OR pending_handoff_mode IN ('HANDOFF_70','CRASH_RECOVERY')),
    pending_handoff_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nodes_q_branch_status ON lineage_nodes(question_id, branch_id, node_status);
CREATE INDEX IF NOT EXISTS idx_nodes_family ON lineage_nodes(question_id, family_id, node_status);

-- ============================================================================
-- 7. 真相 ②：门派结构化死胡同只追加表 (lineage_dead_ends)
-- ============================================================================
CREATE TABLE IF NOT EXISTS lineage_dead_ends (
    dead_end_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL,
    branch_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    category TEXT NOT NULL CHECK(category IN ('SCIENTIFIC_REFUTATION','IMPL_FAILURE','ENV_FAILURE')),
    scope_condition_md TEXT NOT NULL,
    failure_mechanism_md TEXT NOT NULL,
    bound_obs_id TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dead_ends_branch ON lineage_dead_ends(branch_id, created_at);

-- ============================================================================
-- 8. 视图 ①：谱系状态看板 (lineage_briefings，<= 2200 字硬限)
-- ============================================================================
CREATE TABLE IF NOT EXISTS lineage_briefings (
    briefing_id TEXT PRIMARY KEY,
    branch_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    sec1_mechanism TEXT NOT NULL,
    sec2_verified_baseline TEXT NOT NULL,
    sec3_bottleneck TEXT NOT NULL,
    sec4_dead_ends TEXT NOT NULL,
    sec5_immediate_will TEXT NOT NULL,
    total_chars INTEGER NOT NULL CHECK(total_chars <= 2200),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_briefings_node ON lineage_briefings(node_id, created_at);

-- ============================================================================
-- 9. 真相 ③左翼：外藏文献与标准定理卡 (external_literature_cards + FTS5)
-- ============================================================================
CREATE TABLE IF NOT EXISTS external_literature_cards (
    ref_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL,
    title TEXT NOT NULL,
    abstract_md TEXT NOT NULL CHECK(length(abstract_md) BETWEEN 60 AND 1500),
    exact_preconditions_md TEXT NOT NULL,
    formulas_or_operators_md TEXT NOT NULL,
    read_depth TEXT NOT NULL CHECK(read_depth IN ('full_text','specified_sections','abstract_only')),
    support_scope TEXT NOT NULL CHECK(support_scope IN (
        'DIRECT_PROOF_OR_EXACT_MEASUREMENT',
        'CONDITIONALLY_VERIFIED',
        'NEGATIVE_REFUTATION',
        'HEURISTIC_CORRELATION',
        'BACKGROUND_REFERENCE'
    )),
    source_citation TEXT NOT NULL,
    is_unverified_external INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS external_literature_fts USING fts5(
    ref_id UNINDEXED,
    title,
    abstract_md,
    exact_preconditions_md,
    formulas_or_operators_md,
    content='external_literature_cards',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS trg_ext_lit_ai AFTER INSERT ON external_literature_cards BEGIN
    INSERT INTO external_literature_fts(rowid, ref_id, title, abstract_md, exact_preconditions_md, formulas_or_operators_md)
    VALUES (new.rowid, new.ref_id, new.title, new.abstract_md, new.exact_preconditions_md, new.formulas_or_operators_md);
END;

CREATE TRIGGER IF NOT EXISTS trg_ext_lit_ad AFTER DELETE ON external_literature_cards BEGIN
    INSERT INTO external_literature_fts(external_literature_fts, rowid, ref_id, title, abstract_md, exact_preconditions_md, formulas_or_operators_md)
    VALUES ('delete', old.rowid, old.ref_id, old.title, old.abstract_md, old.exact_preconditions_md, old.formulas_or_operators_md);
END;

CREATE TRIGGER IF NOT EXISTS trg_ext_lit_au AFTER UPDATE ON external_literature_cards BEGIN
    INSERT INTO external_literature_fts(external_literature_fts, rowid, ref_id, title, abstract_md, exact_preconditions_md, formulas_or_operators_md)
    VALUES ('delete', old.rowid, old.ref_id, old.title, old.abstract_md, old.exact_preconditions_md, old.formulas_or_operators_md);
    INSERT INTO external_literature_fts(rowid, ref_id, title, abstract_md, exact_preconditions_md, formulas_or_operators_md)
    VALUES (new.rowid, new.ref_id, new.title, new.abstract_md, new.exact_preconditions_md, new.formulas_or_operators_md);
END;

-- ============================================================================
-- 11. 盲审状态机 (review_queue)
-- ============================================================================
CREATE TABLE IF NOT EXISTS review_queue (
    review_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL,
    source_node_id TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK(source_type IN (
        'LEVEL1_MANUSCRIPT','LEVEL4A_BARRIER','AUDITOR_SALVAGED_LEMMA','LOCAL_LEMMA_SUBMISSION'
    )),
    proposer_session_id TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'STAGE1_BLIND' CHECK(review_status IN (
        'STAGE1_BLIND','STAGE2_UNBLIND','CLOSED_ACCEPTED','CLOSED_REVISE','CLOSED_REFUTED'
    )),
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
    final_verdict TEXT CHECK(final_verdict IN ('ACCEPT','ACCEPT_NARROWED','REVISE','REFUTED') OR final_verdict IS NULL),
    revision_requests_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_review_status ON review_queue(review_status, question_id);

-- ============================================================================
-- 10. 真相 ③右翼：内藏确证库与否定雷达 (internal_research_ledger + FTS5)
-- ============================================================================
CREATE TABLE IF NOT EXISTS internal_research_ledger (
    entry_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL,
    ledger_type TEXT NOT NULL CHECK(ledger_type IN ('L3_VERIFIED','L2_FAILURE_RECORD')),
    l3_entry_kind TEXT CHECK(l3_entry_kind IN ('POS_THEOREM','NEG_COUNTEREXAMPLE','BARRIER_PROOF') OR l3_entry_kind IS NULL),
    goal_coverage TEXT CHECK(goal_coverage IN ('FULL_GOAL','PARTIAL_OR_LEMMA','EQUIVALENT_REDUCTION') OR goal_coverage IS NULL),
    publish_tier TEXT NOT NULL DEFAULT 'BASELINE_UPDATE',
    verified_spec_revision INTEGER NOT NULL DEFAULT 0,
    l2_category TEXT CHECK(l2_category IN ('REFUTED','UNRESOLVED_OBJECTION') OR l2_category IS NULL),
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
CREATE INDEX IF NOT EXISTS idx_ledger_q_type ON internal_research_ledger(question_id, ledger_type, is_active);

CREATE UNIQUE INDEX IF NOT EXISTS uq_l3_verified_review
ON internal_research_ledger(verified_review_id)
WHERE ledger_type = 'L3_VERIFIED';

CREATE VIRTUAL TABLE IF NOT EXISTS internal_research_fts USING fts5(
    entry_id UNINDEXED,
    title,
    abstract_md,
    exact_verified_scope_md,
    exact_refuted_scope_md,
    content='internal_research_ledger',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS trg_int_led_ai AFTER INSERT ON internal_research_ledger BEGIN
    INSERT INTO internal_research_fts(rowid, entry_id, title, abstract_md, exact_verified_scope_md, exact_refuted_scope_md)
    VALUES (new.rowid, new.entry_id, new.title, new.abstract_md, COALESCE(new.exact_verified_scope_md,''), COALESCE(new.exact_refuted_scope_md,''));
END;

CREATE TRIGGER IF NOT EXISTS trg_int_led_ad AFTER DELETE ON internal_research_ledger BEGIN
    INSERT INTO internal_research_fts(internal_research_fts, rowid, entry_id, title, abstract_md, exact_verified_scope_md, exact_refuted_scope_md)
    VALUES ('delete', old.rowid, old.entry_id, old.title, old.abstract_md, COALESCE(old.exact_verified_scope_md,''), COALESCE(old.exact_refuted_scope_md,''));
END;

CREATE TRIGGER IF NOT EXISTS trg_int_led_au AFTER UPDATE ON internal_research_ledger BEGIN
    INSERT INTO internal_research_fts(internal_research_fts, rowid, entry_id, title, abstract_md, exact_verified_scope_md, exact_refuted_scope_md)
    VALUES ('delete', old.rowid, old.entry_id, old.title, old.abstract_md, COALESCE(old.exact_verified_scope_md,''), COALESCE(old.exact_refuted_scope_md,''));
    INSERT INTO internal_research_fts(rowid, entry_id, title, abstract_md, exact_verified_scope_md, exact_refuted_scope_md)
    VALUES (new.rowid, new.entry_id, new.title, new.abstract_md, COALESCE(new.exact_verified_scope_md,''), COALESCE(new.exact_refuted_scope_md,''));
END;

-- ============================================================================
-- 12. 待重评队列 (pending_revalidation_queue)
-- ============================================================================
CREATE TABLE IF NOT EXISTS pending_revalidation_queue (
    queue_id TEXT PRIMARY KEY,
    obs_id TEXT NOT NULL REFERENCES observations(obs_id),
    question_id TEXT NOT NULL,
    target_instrument_id TEXT NOT NULL,
    target_version INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','DONE','INCOMPATIBLE')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reval_status ON pending_revalidation_queue(status, question_id);

-- ============================================================================
-- 13. 动态方法族谱 (method_families)
-- ============================================================================
CREATE TABLE IF NOT EXISTS method_families (
    family_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL,
    mechanism_signature TEXT NOT NULL,
    orthogonal_contrast TEXT NOT NULL,
    family_status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(family_status IN ('ACTIVE','BLOCKED')),
    blocking_lemma TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_families_q ON method_families(question_id, family_status);

-- ============================================================================
-- 14. 认知与审计边表 (epistemic_edges)
-- ============================================================================
CREATE TABLE IF NOT EXISTS epistemic_edges (
    edge_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    edge_track TEXT NOT NULL CHECK(edge_track IN ('FACT_LOG','CLAIM_DECLARED')),
    edge_type TEXT NOT NULL CHECK(edge_type IN (
        'READ','RETRIEVED','USED_TOOL',
        'REQUIRED_PREMISE','INDEPENDENT_SUPPORT','MOTIVATING_REF'
    )),
    session_id TEXT DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_edges_src_dst ON epistemic_edges(source_id, target_id, edge_track);
CREATE INDEX IF NOT EXISTS idx_edges_target ON epistemic_edges(target_id, edge_type);

-- ============================================================================
-- 15. 部门工单表 (works_engineering_queue & survey_requests)
-- ============================================================================
CREATE TABLE IF NOT EXISTS works_engineering_queue (
    ticket_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL,
    ticket_type TEXT NOT NULL CHECK(ticket_type IN ('INSTRUMENT_ERROR','PAIN_POINT','DUPLICATE_TOOL','EXPLOIT','DISCRIMINATOR')),
    instrument_id TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','RESOLVED')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_works_tickets_status ON works_engineering_queue(status, question_id);

CREATE TABLE IF NOT EXISTS survey_requests (
    req_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    topic_query TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','FULFILLED','CLOSED_UNAVAILABLE')),
    fulfilled_ref_id TEXT,
    resolution_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_survey_status ON survey_requests(status, question_id);

-- ============================================================================
-- 16. 合规告警与只读图视图 (compliance_alerts & saved_graph_queries)
-- ============================================================================
CREATE TABLE IF NOT EXISTS compliance_alerts (
    alert_id TEXT PRIMARY KEY,
    stage TEXT NOT NULL CHECK(stage IN ('PARSE0_GATE','STAGE2_HEARTBEAT','AMBIGUOUS_SPEC_ALERT','CLOSURE_GATE')),
    status TEXT NOT NULL CHECK(status IN ('PASSED','ALERT_AMBIGUOUS_SPEC','ALERT','BLOCKED')),
    blocking_questions_json TEXT NOT NULL DEFAULT '[]',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS saved_graph_queries (
    query_name TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    sql_select TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- ============================================================================
-- 17. 终局冻结与核签状态表 (project_closure_state，单行 id=1)
-- ============================================================================
CREATE TABLE IF NOT EXISTS project_closure_state (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','DELIVERY_EXPORTED','REVISION_REQUESTED','CLOSED_VERIFIED')),
    delivery_mode TEXT,
    latest_delivery_id TEXT,
    latest_delivery_sha256 TEXT,
    frozen_delivery_dir_abs_path TEXT NOT NULL DEFAULT '',
    verifier_audited_delivery_id TEXT,
    verifier_audited_delivery_sha256 TEXT,
    verifier_final_audit_passed INTEGER NOT NULL DEFAULT 0,
    verifier_revision_notes TEXT NOT NULL DEFAULT '',
    human_stop_requested_at TEXT,
    supervisory_signed_at TEXT,
    updated_at TEXT NOT NULL
);

-- ============================================================================
-- 既有三条硬触发器
-- ============================================================================
CREATE TRIGGER IF NOT EXISTS trg_reviews_lock_stage1
BEFORE UPDATE OF stage1_ledger_json, stage1_locked_at ON review_queue
WHEN OLD.stage1_locked_at IS NOT NULL
  AND (
      COALESCE(NEW.stage1_ledger_json, '') != COALESCE(OLD.stage1_ledger_json, '')
      OR COALESCE(NEW.stage1_locked_at, '') != COALESCE(OLD.stage1_locked_at, '')
  )
BEGIN
    SELECT RAISE(ABORT, 'STAGE1_LEDGER_IMMUTABLE');
END;

CREATE TRIGGER IF NOT EXISTS trg_l3_require_verified_review
BEFORE INSERT ON internal_research_ledger
WHEN NEW.ledger_type = 'L3_VERIFIED'
  AND (
      NEW.verified_review_id IS NULL
      OR NOT EXISTS (
          SELECT 1 FROM review_queue r
          WHERE r.review_id = NEW.verified_review_id
            AND r.question_id = NEW.question_id
            AND r.review_status = 'CLOSED_ACCEPTED'
            AND r.stage1_locked_at IS NOT NULL
            AND r.final_locked_at IS NOT NULL
            AND r.final_verdict IN ('ACCEPT', 'ACCEPT_NARROWED')
      )
  )
BEGIN
    SELECT RAISE(ABORT, 'L3_REQUIRES_MATCHING_VERIFIED_REVIEW');
END;

CREATE TRIGGER IF NOT EXISTS trg_obs_pending_reval_require_queue
BEFORE UPDATE OF obs_status ON observations
WHEN NEW.obs_status = 'PENDING_REVALIDATION'
  AND NOT EXISTS (
      SELECT 1 FROM pending_revalidation_queue q
      WHERE q.obs_id = NEW.obs_id AND q.status = 'PENDING'
  )
BEGIN
    SELECT RAISE(ABORT, 'PENDING_REVALIDATION_MISSING_QUEUE_ROW');
END;
"""
