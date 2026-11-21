"""长城 V6-Up (v3.0) SQLite WAL 持久化底座、完整 17 组核心表 Schema、3 条硬触发器与 FTS5 辅助模块。

严格对齐《09长城 Agent V6-Up（v3.0）零前提工程架构与系统开发总说明书》第三章：
1. 零第三方依赖（纯 Python 标准库 + SQLite WAL / FTS5 / Foreign Keys）；
2. 物理隔离：数据库与产物全部落盘至 `$PLUGIN_DATA/workspaces/<ws_hash>/`；
3. “3 真相 + 2 视图” + 校准仪器 + 重型作业冻结 + 两步绑定版本终局闭环；
4. 三条数据库硬件级触发器 + 唯一部分索引：
   - `trg_reviews_lock_stage1`: Stage 1 锁死后永久禁止篡改证据账本与时间戳；
   - `trg_l3_require_verified_review` + `uq_l3_verified_review`: 强制校验同题、已过 Stage1+2 终审且一单仅可生成 1 条 L3；
   - `trg_obs_pending_reval_require_queue`: 观测转 PENDING_REVALIDATION 同事务必须已写入 `pending_revalidation_queue`。
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

ERR_AUTH = "ERR_AUTH"
ERR_INVALID_INPUT = "ERR_INVALID_INPUT"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_CONFLICT = "ERR_CONFLICT"
ERR_LOCKED = "ERR_LOCKED"
ERR_INVARIANT = "ERR_INVARIANT"
ERR_EXECUTION = "ERR_EXECUTION"
ERR_STORAGE = "ERR_STORAGE"

CORE_ERROR_CODES = frozenset(
    {
        ERR_AUTH,
        ERR_INVALID_INPUT,
        ERR_NOT_FOUND,
        ERR_CONFLICT,
        ERR_LOCKED,
        ERR_INVARIANT,
        ERR_EXECUTION,
        ERR_STORAGE,
    }
)

# 权威枚举集合（SSOT：全仓 JSON Schema 与服务端校验共用）
ALLOWED_INSTRUMENT_ROLES = frozenset({"VERDICT", "PROBE", "ENV"})
ALLOWED_INSTRUMENT_TIERS = frozenset({"probe", "official", "heavy"})
ALLOWED_INSTRUMENT_STATUSES = frozenset({"OK", "CANDIDATE_ERROR", "INSTRUMENT_ERROR", "INFRA_ERROR"})
ALLOWED_VERDICTS = frozenset({"PASS", "FAIL", "UNDECIDED"})
ALLOWED_OBS_STATUSES = frozenset(
    {
        "VALID_PASS",
        "MEASURED_REJECTION",
        "VALID_UNDECIDED",
        "CANDIDATE_ERROR",
        "INSTRUMENT_ERROR",
        "INFRA_ERROR",
        "PENDING_REVALIDATION",
        "SUPERSEDED_REVALIDATED",
        "INCOMPATIBLE",
    }
)
ALLOWED_NODE_STATUSES = frozenset(
    {"EXPLORING", "AWAITING_TRIAGE", "PENDING_REVIEW", "ACTIVE_REVISING", "BLOCKED_L4B", "SEALED", "CLOSED"}
)
ALLOWED_EVIDENCE_GRADES = frozenset({"NONE", "ARTIFACT_ONLY", "MEASURED"})
ALLOWED_DEAD_END_CATEGORIES = frozenset({"SCIENTIFIC_REFUTATION", "IMPL_FAILURE", "ENV_FAILURE"})
ALLOWED_READ_DEPTHS = frozenset({"full_text", "specified_sections", "abstract_only"})
ALLOWED_SUPPORT_SCOPES = frozenset(
    {
        "DIRECT_PROOF_OR_EXACT_MEASUREMENT",
        "CONDITIONALLY_VERIFIED",
        "NEGATIVE_REFUTATION",
        "HEURISTIC_CORRELATION",
        "BACKGROUND_REFERENCE",
    }
)
ALLOWED_L3_ENTRY_KINDS = frozenset({"POS_THEOREM", "NEG_COUNTEREXAMPLE", "BARRIER_PROOF"})
ALLOWED_GOAL_COVERAGES = frozenset({"FULL_GOAL", "PARTIAL_OR_LEMMA", "EQUIVALENT_REDUCTION"})
ALLOWED_L2_CATEGORIES = frozenset({"REFUTED", "UNRESOLVED_OBJECTION"})
ALLOWED_REVIEW_SOURCE_TYPES = frozenset({"LEVEL1_MANUSCRIPT", "LEVEL4A_BARRIER", "AUDITOR_SALVAGED_LEMMA"})
ALLOWED_STAGE1_VERDICTS = frozenset({"PASS", "REVISE", "REFUTED"})
ALLOWED_FINAL_VERDICTS = frozenset({"ACCEPT", "ACCEPT_NARROWED", "REVISE", "REFUTED"})
ALLOWED_CLAIMED_EDGE_TYPES = frozenset({"REQUIRED_PREMISE", "INDEPENDENT_SUPPORT", "MOTIVATING_REF"})
ALLOWED_FACT_EDGE_TYPES = frozenset({"READ", "RETRIEVED", "USED_TOOL"})
ALLOWED_TRIAGE_LEVELS = frozenset({"ROUTINE_CONTINUATION", "LEVEL_1", "LEVEL_2", "LEVEL_3", "LEVEL_4A", "LEVEL_4B"})
ALLOWED_TRIAGE_ACTIONS = frozenset(
    {"CONTINUE", "SUBMIT_BLIND_REVIEW", "INPLACE_REPAIR", "SPAWN_PROTECTED", "SEAL_BARRIER", "PAUSE_TO_READY_QUEUE"}
)
ALLOWED_FORK_MODES = frozenset({"orthogonal", "lateral", "cross_pollinate"})
ALLOWED_STAGNATION_LANES = frozenset({"EXPLORATION", "EXPLOITATION", "REVIVAL", "UNDERSTANDING", "STRATEGY"})
ALLOWED_DELIVERY_MODES = frozenset({"FULL", "PARTIAL_ON_BUDGET", "PARTIAL_ON_HUMAN_STOP"})
ALLOWED_COMPLIANCE_STAGES = frozenset({"PARSE0_GATE", "STAGE2_HEARTBEAT", "AMBIGUOUS_SPEC_ALERT", "CLOSURE_GATE"})
ALLOWED_COMPLIANCE_STATUSES = frozenset({"PASSED", "ALERT_AMBIGUOUS_SPEC", "ALERT", "BLOCKED"})
ALLOWED_COMPANION_MODES = frozenset({"PRE_SPAWN", "REFLECT_37", "HANDOFF_70", "CRASH_RECOVERY"})
ALLOWED_VERDICT_3STATE = frozenset({"SUFFICIENT_EVIDENCE", "MINIMAL_EXPERIMENT_NEXT", "NEED_CONTROL_GROUP"})

_FTS5_META_RE = re.compile(r"[:*(){}^+\-.,;!?/\\|=<>&~@#$%\[\]\"']+")
_FTS5_RESERVED_WORDS = frozenset({"AND", "OR", "NOT", "NEAR"})


class FailClosedError(Exception):
    """Fail-Closed 结构化阻断异常。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code if code in CORE_ERROR_CODES else ERR_INVALID_INPUT
        self.message = message

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error_code": self.code,
            "error": self.message,
        }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def reject_null_bytes(value: Any, field_name: str = "input") -> None:
    if isinstance(value, str) and "\x00" in value:
        raise FailClosedError(ERR_INVALID_INPUT, f"{field_name} 包含非法空字节 \\x00")


def compute_workspace_hash(workspace_root: str) -> str:
    norm = os.path.realpath(workspace_root or os.getcwd())
    if os.name == "nt":
        norm = norm.lower()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def resolve_storage_paths(workspace_root: str = "") -> dict[str, Path]:
    """解析并准备 `$PLUGIN_DATA/workspaces/<ws_hash>/` 全套物理隔离受控目录。"""
    base_data = (
        os.environ.get("GREATWALL_PLUGIN_DATA_DIR")
        or os.environ.get("PLUGIN_DATA")
        or os.environ.get("GREATWALL_DATA_DIR")
        or str(Path(os.environ.get("DSH_HOME") or (Path.home() / ".dsh")) / "greatwall-v6up")
    )
    ws_hash = compute_workspace_hash(workspace_root)
    data_dir = Path(os.path.realpath(base_data)) / "workspaces" / ws_hash
    eval_artifacts_dir = data_dir / "eval_artifacts"
    job_inputs_dir = data_dir / "job_inputs"
    snapshots_dir = data_dir / "snapshots"
    hidden_calibrations_dir = data_dir / "_hidden_calibrations"
    blind_sandboxes_dir = data_dir / "blind_sandboxes"
    instrument_snapshots_dir = data_dir / "instrument_snapshots"
    skills_dir = data_dir / "skills"

    for d in (
        data_dir,
        eval_artifacts_dir,
        job_inputs_dir,
        snapshots_dir,
        hidden_calibrations_dir,
        blind_sandboxes_dir,
        instrument_snapshots_dir,
        skills_dir,
    ):
        d.mkdir(parents=True, exist_ok=True)

    return {
        "data_dir": data_dir,
        "db_path": data_dir / "greatwall.db",
        "eval_artifacts_dir": eval_artifacts_dir,
        "job_inputs_dir": job_inputs_dir,
        "snapshots_dir": snapshots_dir,
        "hidden_calibrations_dir": hidden_calibrations_dir,
        "blind_sandboxes_dir": blind_sandboxes_dir,
        "instrument_snapshots_dir": instrument_snapshots_dir,
        "skills_ledger_path": skills_dir / "SKILL_LEDGER.json",
    }


SCHEMA_SQL = """
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
-- 6. 真相 ②：门派私有谱系 DAG (lineage_nodes)
-- ============================================================================
CREATE TABLE IF NOT EXISTS lineage_nodes (
    node_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL,
    branch_id TEXT NOT NULL,
    family_id TEXT,
    parent_node_id TEXT,
    generation INTEGER NOT NULL DEFAULT 1,
    node_status TEXT NOT NULL DEFAULT 'EXPLORING' CHECK(node_status IN (
        'EXPLORING','AWAITING_TRIAGE','PENDING_REVIEW','ACTIVE_REVISING',
        'BLOCKED_L4B','SEALED','CLOSED'
    )),
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
-- 11. 盲审状态机 (review_queue) — 先建供 internal_research_ledger 外键引用
-- ============================================================================
CREATE TABLE IF NOT EXISTS review_queue (
    review_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL,
    source_node_id TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK(source_type IN ('LEVEL1_MANUSCRIPT','LEVEL4A_BARRIER','AUDITOR_SALVAGED_LEMMA')),
    proposer_session_id TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'STAGE1_BLIND' CHECK(review_status IN (
        'STAGE1_BLIND','STAGE2_UNBLIND','CLOSED_ACCEPTED','CLOSED_REVISE','CLOSED_REFUTED'
    )),
    manuscript_title TEXT NOT NULL DEFAULT '',
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

-- 唯一部分索引：严禁单张审稿单重复插入多条 L3_VERIFIED
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
-- 14. 认知与审计边表 (epistemic_edges，CLAIM_DECLARED 默认 MOTIVATING_REF)
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
    ticket_type TEXT NOT NULL CHECK(ticket_type IN ('INSTRUMENT_ERROR','PAIN_POINT','DUPLICATE_TOOL','EXPLOIT')),
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
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','FULFILLED')),
    fulfilled_ref_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_survey_status ON survey_requests(status, question_id);

-- ============================================================================
-- 16. 监察委合规告警与安全只读查询视图 (compliance_alerts & saved_graph_queries)
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
-- 17. 两步终局核签状态表 (project_closure_state，单行 id=1)
-- ============================================================================
CREATE TABLE IF NOT EXISTS project_closure_state (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','DELIVERY_EXPORTED','REVISION_REQUESTED','CLOSED_VERIFIED')),
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

-- ============================================================================
-- 三条必建数据库硬触发器 (09 §3.2)
-- ============================================================================

-- 触发器 1：Stage 1 盲审账本锁定后不可篡改
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

-- 触发器 2：L3_VERIFIED 强校验绑定同题、双阶段锁定且审定通过的 review_queue 记录
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

-- 触发器 3：观测转 PENDING_REVALIDATION 同事务必须已有活跃待重评队列行
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


def _detect_legacy_v2_database(conn: sqlite3.Connection) -> None:
    """检测旧版 v2.2 数据库：不做隐式迁移，直接抛出清晰提示让人类换新文件夹。"""
    tables = {
        str(r["name"])
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }
    if "observations" in tables:
        obs_cols = {str(r["name"]) for r in conn.execute("PRAGMA table_info(observations)").fetchall()}
        if "cache_key" not in obs_cols or "obs_status" not in obs_cols:
            raise FailClosedError(
                ERR_STORAGE,
                "检测到旧版 v2.2 数据库（observations 表结构不兼容），请更换新的工作区文件夹（或手动移走旧版 greatwall.db）后再启动 GreatWall v3.0！",
            )
    if "lineage_nodes" in tables:
        node_cols = {str(r["name"]) for r in conn.execute("PRAGMA table_info(lineage_nodes)").fetchall()}
        if "node_status" not in node_cols:
            raise FailClosedError(
                ERR_STORAGE,
                "检测到旧版 v2.2 数据库（lineage_nodes 表结构不兼容），请更换新的工作区文件夹（或手动移走旧版 greatwall.db）后再启动 GreatWall v3.0！",
            )


def _migrate_closure_state_check_constraint(conn: sqlite3.Connection) -> None:
    """兼容早期 v3.0 数据库：若 project_closure_state 的 CHECK 约束缺少 REVISION_REQUESTED，单事务安全重建该单行表。"""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'project_closure_state'"
    ).fetchone()
    ddl = str(row["sql"] or "") if row else ""
    if not ddl or "REVISION_REQUESTED" in ddl:
        return
    cols = {str(r["name"]) for r in conn.execute("PRAGMA table_info(project_closure_state)").fetchall()}
    target_cols = [
        ("id", "1"),
        ("status", "'OPEN'"),
        ("delivery_mode", "NULL"),
        ("latest_delivery_id", "NULL"),
        ("latest_delivery_sha256", "NULL"),
        ("verifier_audited_delivery_id", "NULL"),
        ("verifier_audited_delivery_sha256", "NULL"),
        ("verifier_final_audit_passed", "0"),
        ("verifier_revision_notes", "''"),
        ("human_stop_requested_at", "NULL"),
        ("supervisory_signed_at", "NULL"),
        ("updated_at", "''"),
    ]
    insert_cols = ", ".join(name for name, _ in target_cols)
    select_exprs = ", ".join(name if name in cols else default_expr for name, default_expr in target_cols)
    with rw_immediate_tx(conn):
        conn.execute("ALTER TABLE project_closure_state RENAME TO _project_closure_state_old")
        conn.execute(
            """
            CREATE TABLE project_closure_state (
                id INTEGER PRIMARY KEY CHECK(id = 1),
                status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','DELIVERY_EXPORTED','REVISION_REQUESTED','CLOSED_VERIFIED')),
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
            )
            """
        )
        conn.execute(
            f"""
            INSERT INTO project_closure_state({insert_cols})
            SELECT {select_exprs}
            FROM _project_closure_state_old
            """
        )
        conn.execute("DROP TABLE _project_closure_state_old")


def init_database_schema(conn: sqlite3.Connection) -> None:
    _detect_legacy_v2_database(conn)
    conn.executescript(SCHEMA_SQL)
    _migrate_closure_state_check_constraint(conn)
    # 轻量补齐 v3.0 内部新增可选列（仅限已创建的 v3.0 库）
    for tbl, col, col_def in (
        ("instruments", "frozen_snapshot_path", "TEXT"),
        ("async_eval_jobs", "frozen_instrument_path", "TEXT"),
        ("lineage_nodes", "explorer_will_md", "TEXT NOT NULL DEFAULT ''"),
        ("lineage_nodes", "pending_handoff_mode", "TEXT"),
        ("lineage_nodes", "pending_handoff_reason", "TEXT NOT NULL DEFAULT ''"),
        ("project_closure_state", "verifier_revision_notes", "TEXT NOT NULL DEFAULT ''"),
    ):
        existing = {str(r["name"]) for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()}
        if col not in existing:
            conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {col_def}")
    now = utc_now_iso()
    conn.execute(
        """
        INSERT OR IGNORE INTO project_closure_state(id, status, verifier_final_audit_passed, updated_at)
        VALUES (1, 'OPEN', 0, ?)
        """,
        (now,),
    )
    conn.commit()


def open_rw_connection(db_path: str | Path, *, init_schema: bool = True) -> sqlite3.Connection:
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=30000;")
    if init_schema:
        init_database_schema(conn)
    return conn


def open_ro_connection(db_path: str | Path) -> sqlite3.Connection:
    p = Path(db_path)
    uri = f"file:{p.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON;")
    return conn


@contextmanager
def rw_immediate_tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Single-Writer SQLite `BEGIN IMMEDIATE` 独占写事务上下文管理器（支持嵌套透传）。"""
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def sanitize_fts5_query(raw_query: str) -> str:
    """净化中英文混合与标点查询词，确保 SQLite FTS5 MATCH 永远零语法崩溃。"""
    cleaned = _FTS5_META_RE.sub(" ", str(raw_query or "")).strip()
    if not cleaned:
        return ""
    tokens: list[str] = []
    for tok in cleaned.split():
        if not tok:
            continue
        if tok.upper() in _FTS5_RESERVED_WORDS:
            continue
        safe = tok.replace('"', "")
        if safe:
            tokens.append(f'"{safe}"')
    if not tokens:
        return ""
    return " OR ".join(tokens)


def propagate_dependency_recheck(conn: sqlite3.Connection, revoked_ids: list[str]) -> dict[str, list[str]]:
    """仅沿 Stage 2 显式认证的 `REQUIRED_PREMISE` 边精准传播依赖重审；`MOTIVATING_REF` / `INDEPENDENT_SUPPORT` 绝不连坐！"""
    raw_list = [revoked_ids] if isinstance(revoked_ids, str) else list(revoked_ids or [])
    clean_ids = [str(x).strip() for x in raw_list if str(x).strip()]
    if not clean_ids:
        return {
            "recheck_triggered_entries": [],
            "premise_revoked_branches": [],
            "motivating_or_independent_unaffected": [],
        }

    placeholders = ",".join("?" for _ in clean_ids)
    edges = conn.execute(
        f"""
        SELECT source_id, target_id, edge_type
        FROM epistemic_edges
        WHERE edge_track = 'CLAIM_DECLARED' AND target_id IN ({placeholders})
        """,
        tuple(clean_ids),
    ).fetchall()

    recheck_entries: set[str] = set()
    unaffected: set[str] = set()
    for e in edges:
        src = str(e["source_id"])
        et = str(e["edge_type"])
        if et == "REQUIRED_PREMISE":
            recheck_entries.add(src)
        else:
            unaffected.add(src)

    if recheck_entries:
        ph = ",".join("?" for _ in recheck_entries)
        conn.execute(
            f"UPDATE internal_research_ledger SET recheck_required = 1 WHERE entry_id IN ({ph})",
            tuple(sorted(recheck_entries)),
        )

    # 同时检查在研分支的 `requires_json`：若分支显式依赖被撤回的 L3，标记 `premise_revoked = 1`（不强杀运行中会话）
    revoked_set = set(clean_ids)
    revoked_branches: set[str] = set()
    rows = conn.execute(
        "SELECT node_id, branch_id, requires_json FROM lineage_nodes WHERE node_status IN ('EXPLORING', 'ACTIVE_REVISING', 'AWAITING_TRIAGE')"
    ).fetchall()
    for r in rows:
        import json as _json
        reqs = _json.loads(r["requires_json"] or "[]")
        if any(str(req) in revoked_set for req in reqs):
            conn.execute("UPDATE lineage_nodes SET premise_revoked = 1 WHERE node_id = ?", (r["node_id"],))
            revoked_branches.add(str(r["branch_id"]))

    return {
        "recheck_triggered_entries": sorted(recheck_entries),
        "premise_revoked_branches": sorted(revoked_branches),
        "motivating_or_independent_unaffected": sorted(unaffected - recheck_entries),
    }
