"""GreatWall Agent v0.3 新增表、只读视图与封存不可逆硬触发器 DDL（100% 对齐 agent_kb_v0_3_04）。"""

from __future__ import annotations

V03_SCHEMA_SQL = """
-- ============================================================================
-- 20. 子题级运行时调度与三道停工锁状态表 (subproblem_runtime_state)
-- ============================================================================
CREATE TABLE IF NOT EXISTS subproblem_runtime_state (
    question_id TEXT PRIMARY KEY,
    priority_weight INTEGER NOT NULL DEFAULT 100,
    max_active_branches INTEGER NOT NULL DEFAULT 3,
    dispatch_policy TEXT NOT NULL DEFAULT 'NORMAL',
    contract_id TEXT NOT NULL DEFAULT 'active' REFERENCES parse0_contract(contract_id),
    desired_state TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK(desired_state IN ('ACTIVE', 'PAUSED', 'CLOSED')),
    dispatch_state TEXT NOT NULL DEFAULT 'DISPATCHING'
        CHECK(dispatch_state IN (
            'DISPATCHING',
            'STOPPED_SOLVED',
            'PAUSED_SATURATED',
            'PAUSED_HUMAN',
            'PAUSED_BLOCKED',
            'CLOSED'
        )),
    active_spec_revision INTEGER NOT NULL DEFAULT 0,
    solved_entry_id TEXT REFERENCES internal_research_ledger(entry_id),
    solved_at_spec_revision INTEGER,
    baseline_entry_id TEXT REFERENCES internal_research_ledger(entry_id),
    baseline_metric_value REAL,
    metric_direction TEXT CHECK(metric_direction IN ('HIGHER_BETTER', 'LOWER_BETTER', 'QUALITATIVE') OR metric_direction IS NULL),
    started_at TEXT NOT NULL DEFAULT '',
    min_commitment_sec INTEGER NOT NULL DEFAULT 0,
    question_token_budget INTEGER NOT NULL DEFAULT 0,
    spent_tokens INTEGER NOT NULL DEFAULT 0,
    completed_waves INTEGER NOT NULL DEFAULT 0,
    max_waves INTEGER NOT NULL DEFAULT 0,
    completed_nodes_since_last_l3 INTEGER NOT NULL DEFAULT 0,
    completed_nodes_since_last_conference INTEGER NOT NULL DEFAULT 0,
    drain_grace_sec INTEGER NOT NULL DEFAULT 60,
    block_reason_code TEXT NOT NULL DEFAULT '',
    block_detail_md TEXT NOT NULL DEFAULT '',
    dispatch_generation INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);

-- ============================================================================
-- 21. 节点人工接管、改码对账与介入审计表 (node_interventions)
-- ============================================================================
CREATE TABLE IF NOT EXISTS node_interventions (
    intervention_id TEXT PRIMARY KEY,
    node_id TEXT NOT NULL REFERENCES lineage_nodes(node_id),
    question_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN (
        'PAUSE_REQUESTED',
        'CONTROL_YIELDED',
        'HUMAN_CHAT_DETECTED',
        'CODE_RECONCILED',
        'RESUME_REQUESTED',
        'EARLY_HANDOFF_AUTHORIZED', 'ADVISOR_NOTE_SENT', 'NODE_HIBERNATED', 'NODE_RETIRED', 'NODE_REACTIVATED'
    )),
    actor_source TEXT NOT NULL CHECK(actor_source IN ('human_ui', 'control_plane', 'chief_approved', 'chief_direct')),
    prev_candidate_sha256 TEXT NOT NULL DEFAULT '',
    curr_candidate_sha256 TEXT NOT NULL DEFAULT '',
    prev_tools_sha256 TEXT NOT NULL DEFAULT '',
    curr_tools_sha256 TEXT NOT NULL DEFAULT '',
    artifact_dirty INTEGER NOT NULL DEFAULT 0,
    cross_branch_note TEXT NOT NULL DEFAULT '',
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_node_interventions_node ON node_interventions(node_id, created_at);

-- ============================================================================
-- 22. 事务后宿主副作用队列 (runtime_effects，单机进程锁 + 租约 + 固定会话ID)
-- ============================================================================
CREATE TABLE IF NOT EXISTS runtime_effects (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    effect_key TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL CHECK(kind IN (
        'SPAWN_PAIR',
        'DRAIN_AND_STOP_NODE',
        'CANCEL_NODE_SESSION',
        'WAKE_BLOCKED_BRANCH',
        'REFRESH_LIVING_SURVEY',
        'RUN_WAVE_CONFERENCE',
        'NOTIFY_POLICY_CHANGED',
        'NOTIFY_CHIEF', 'DELIVER_BRANCH_NOTE', 'DELIVER_HANDBACK_RECEIPT'
    )),
    target_type TEXT NOT NULL CHECK(target_type IN ('NODE', 'QUESTION', 'PROJECT')),
    target_id TEXT NOT NULL,
    target_generation INTEGER NOT NULL DEFAULT 1,
    external_handle_id TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN (
        'PENDING', 'RUNNING', 'DONE', 'CANCELLED', 'FAILED'
    )),
    owner_instance_id TEXT NOT NULL DEFAULT '',
    claimed_at TEXT,
    lease_expires_at TEXT,
    superseded_by_seq INTEGER,
    attempts INTEGER NOT NULL DEFAULT 0,
    due_at TEXT NOT NULL DEFAULT '',
    last_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_effects_status_due ON runtime_effects(status, due_at, seq);
CREATE INDEX IF NOT EXISTS idx_effects_target ON runtime_effects(target_type, target_id, status);

-- ============================================================================
-- 23. 纯命题引理悬赏榜 (open_lemma_gaps，承接 LEVEL_4B 盲审 Stage 2 核销唤醒)
-- ============================================================================
CREATE TABLE IF NOT EXISTS open_lemma_gaps (
    gap_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL REFERENCES subproblem_runtime_state(question_id),
    blocked_node_id TEXT NOT NULL REFERENCES lineage_nodes(node_id),
    formal_statement_md TEXT NOT NULL,
    verification_spec_md TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN', 'FULFILLED', 'CANCELLED')),
    fulfilled_by_entry_id TEXT REFERENCES internal_research_ledger(entry_id),
    created_at TEXT NOT NULL,
    fulfilled_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_lemma_gaps_q_status ON open_lemma_gaps(question_id, status);

-- ============================================================================
-- 24. 高危控制操作与人类自由指令确认单 (control_proposals)
-- ============================================================================
CREATE TABLE IF NOT EXISTS control_proposals (
    proposal_id TEXT PRIMARY KEY,
    proposed_by TEXT NOT NULL DEFAULT 'gw_chief',
    action_type TEXT NOT NULL CHECK(action_type IN (
        'SET_SUBPROBLEM_STATE',
        'AUTHORIZE_EARLY_HANDOFF',
        'AMEND_RULING_DRAFT',
        'AUTHORIZE_PARTIAL_DELIVERY',
        'APPROVE_WAVE_VERDICT',
        'SEED_HUMAN_BRANCH',
        'SUBMIT_WORKS_OR_SURVEY_TICKET',
        'SET_AUTONOMY_MODE', 'ADVANCE_EPOCH'
    )),
    target_id TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    rationale_md TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING_HUMAN'
        CHECK(status IN ('PENDING_HUMAN', 'APPROVED_EXECUTED', 'REJECTED', 'EXPIRED', 'SUPERSEDED')),
    approved_by_source TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_proposals_status ON control_proposals(status, created_at);

-- ============================================================================
-- 25. 子题活体综述导览表 (subproblem_living_surveys，<=1500 字高密度导览索引)
-- ============================================================================
CREATE TABLE IF NOT EXISTS subproblem_living_surveys (
    survey_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL REFERENCES subproblem_runtime_state(question_id),
    revision INTEGER NOT NULL,
    sec1_baseline_and_instruments_md TEXT NOT NULL,
    sec2_l3_lemma_tree_md TEXT NOT NULL,
    sec3_avoidance_radar_md TEXT NOT NULL,
    sec4_explicit_gaps_md TEXT NOT NULL,
    total_chars INTEGER NOT NULL CHECK(total_chars <= 1500),
    trigger_reason TEXT NOT NULL DEFAULT 'MANUAL',
    created_at TEXT NOT NULL,
    UNIQUE(question_id, revision)
);
CREATE INDEX IF NOT EXISTS idx_living_surveys_q_rev ON subproblem_living_surveys(question_id, revision DESC);

-- ============================================================================
-- 26. 波次圆桌对抗会议记录表 (wave_conferences)
-- ============================================================================
CREATE TABLE IF NOT EXISTS wave_conferences (
    conference_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL REFERENCES subproblem_runtime_state(question_id),
    wave_no INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'ASSEMBLING' CHECK(status IN (
        'ASSEMBLING',
        'ROUND_1_CRITIQUE',
        'ROUND_2_REBUTTAL',
        'SURVEY_REFRESHING',
        'ADJUDICATING',
        'PENDING_HUMAN_APPROVAL',
        'COMPLETED',
        'CANCELLED',
        'EXPIRED',
        'FAILED'
    )),
    participant_nodes_json TEXT NOT NULL,
    critiques_ledger_json TEXT NOT NULL DEFAULT '[]',
    minutes_md TEXT NOT NULL DEFAULT '',
    linked_survey_id TEXT REFERENCES subproblem_living_surveys(survey_id),
    chair_session_id TEXT NOT NULL DEFAULT '',
    verdict_json TEXT,
    synthesis_budget_nodes INTEGER NOT NULL DEFAULT 2,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(question_id, wave_no)
);

-- ============================================================================
-- 27. 排雷聚合只读视图 (v_library_avoidance_radar)
-- ============================================================================
CREATE VIEW IF NOT EXISTS v_library_avoidance_radar AS
SELECT
    entry_id,
    question_id,
    ledger_type,
    COALESCE(l3_entry_kind, l2_category) AS radar_kind,
    title,
    abstract_md,
    COALESCE(exact_refuted_scope_md, exact_verified_scope_md) AS scope_md,
    created_at
FROM internal_research_ledger
WHERE is_active = 1
  AND (
      ledger_type = 'L2_FAILURE_RECORD'
      OR (ledger_type = 'L3_VERIFIED' AND l3_entry_kind IN ('NEG_COUNTEREXAMPLE', 'BARRIER_PROOF'))
  );
"""

SEALED_HANDOFF_TRIGGER_SQL = """
DROP TRIGGER IF EXISTS trg_nodes_lock_sealed_handoff;
CREATE TRIGGER trg_nodes_lock_sealed_handoff
BEFORE UPDATE OF briefing_sealed_at, column_a_facts_md, column_b_hypothesis_md, will_md, bound_obs_ids_json, candidate_rel_path ON lineage_nodes
WHEN OLD.briefing_sealed_at IS NOT NULL
  AND OLD.node_status NOT IN ('EXPLORING', 'ACTIVE_REVISING')
  AND NEW.node_status != 'ACTIVE_REVISING'
  AND (
      COALESCE(NEW.briefing_sealed_at, '') != COALESCE(OLD.briefing_sealed_at, '')
      OR COALESCE(NEW.column_a_facts_md, '') != COALESCE(OLD.column_a_facts_md, '')
      OR COALESCE(NEW.column_b_hypothesis_md, '') != COALESCE(OLD.column_b_hypothesis_md, '')
      OR COALESCE(NEW.will_md, '') != COALESCE(OLD.will_md, '')
      OR COALESCE(NEW.bound_obs_ids_json, '') != COALESCE(OLD.bound_obs_ids_json, '')
      OR COALESCE(NEW.candidate_rel_path, '') != COALESCE(OLD.candidate_rel_path, '')
  )
BEGIN
    SELECT RAISE(ABORT, 'SEALED_HANDOFF_IMMUTABLE');
END;
"""
