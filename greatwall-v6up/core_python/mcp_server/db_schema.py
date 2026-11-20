"""SQLite WAL 持久化底座、V6-Up (v2.2) 三真相极简 Schema、物理触发器锁与 FTS5 辅助模块。

设计铁律（对齐《04》§7.2 &《09_V6Up_v2.2_实施侧工程交接与系统开发总说明书》§4.2）：
1. 零第三方依赖（纯 Python 3.14 标准库 + SQLite WAL/FTS5）。
2. 三真相两翼：
   - 真相 ① `observations`（绑定 question_id + domain_hook_sha256 + stage_a_artifact_path）
   - 真相 ② `lineage_nodes`（原 L1 合一，含 worktree_abs_path / sanitized_code_diff_md / scratch_log_json，废除 bound_state_version）
   - 真相 ③ 中央图书馆物理分表：`external_literature_cards`（外藏 [R###]）与 `internal_research_ledger`（内藏 L3_VERIFIED / L2_FAILURE_RECORD）
3. 数据库硬件级触发器门禁：
   - `trg_reviews_lock_stage1`: Stage 1 锁死后永久禁止篡改证据账本或初判；
   - `trg_l3_require_stage2_pass`: 任何 L3_VERIFIED 必须关联已通过 Stage 2 盲审的 `review_queue` 记录；
   - `trg_obs_pending_reval_require_queue`: 观测转 PENDING_REVALIDATION 时同一事务必须已写入 `pending_revalidation_queue`（根治 P26）。
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

_FTS5_META_RE = re.compile(r"[:*(){}^+\-.,;!?/\\|=<>&~@#$%\[\]]+")
_FTS5_RESERVED_WORDS = frozenset({"AND", "OR", "NOT", "NEAR"})

_OPEN_FENCE_RE = re.compile(r"^[ \t]*(?P<fence>`{3,}|~{3,})(?P<info>.*)$")
_CLOSE_FENCE_RE = re.compile(r"^[ \t]*(?P<fence>`{3,}|~{3,})[ \t]*$")
_COL_A_LINE_RE = re.compile(
    r"^[ \t]*#{1,6}[ \t]*(?:A[ \t]*栏|Column[ \t]*A(?:$|[ \t]+|[:：—\-（(【\[]))",
    re.IGNORECASE,
)
_COL_B_LINE_RE = re.compile(
    r"^[ \t]*#{1,6}[ \t]*(?:B[ \t]*栏|Column[ \t]*B(?:$|[ \t]+|[:：—\-（(【\[]))",
    re.IGNORECASE,
)

ALLOWED_CLAIMED_EDGE_TYPES = frozenset(
    {"REQUIRED_PREMISE", "INDEPENDENT_SUPPORT", "MOTIVATING_REF"}
)

ALLOWED_READ_DEPTHS = frozenset({"full_text", "specified_sections", "abstract_only"})

ALLOWED_SUPPORT_SCOPES = frozenset(
    {
        "DIRECT_PROOF_OR_EXACT_MEASUREMENT",
        "CONDITIONALLY_VERIFIED",
        "NEGATIVE_REFUTATION",
        "HEURISTIC_CORRELATION",
        "BACKGROUND_REFERENCE",
        "direct_target_matched_context",
        "target_specific_different_context",
        "related_pathway_complex_module",
        "broad_biological_process",
        "indirect_or_speculative",
    }
)


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
    """返回含微秒精度的 UTC ISO-8601 时间戳。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def reject_null_bytes(value: str, field_name: str = "path") -> str:
    """拦截路径或输入中的空字节 \\x00。"""
    if "\x00" in (value or ""):
        raise FailClosedError(ERR_INVALID_INPUT, f"{field_name} 包含非法空字节 \\x00")
    return value


def _validate_abs_workspace_root(workspace_root: str) -> str:
    """严格校验 workspace_root 为非空绝对路径。"""
    reject_null_bytes(workspace_root or "", "workspace_root")
    ws = (workspace_root or "").strip()
    if not ws:
        raise FailClosedError(
            ERR_INVALID_INPUT,
            "workspace_root 必须为非空绝对路径（禁止空串或污染代码仓库根目录）",
        )
    if not os.path.isabs(ws):
        raise FailClosedError(
            ERR_INVALID_INPUT,
            f"workspace_root 必须为绝对路径，当前收到: {ws!r}",
        )
    if os.name == "nt":
        drive, tail = os.path.splitdrive(ws)
        if not drive or not (tail.startswith("\\") or tail.startswith("/")):
            raise FailClosedError(
                ERR_INVALID_INPUT,
                f"Windows workspace_root 必须包含完整盘符或 UNC 根路径: {ws!r}",
            )
    return ws


def resolve_storage_paths(workspace_root: str = "") -> dict[str, Any]:
    """解析隔离外部数据根目录与 SQLite 路径（优先 GREATWALL_DB_PATH，其次 PLUGIN_DATA/<ws_hash>）。"""
    reject_null_bytes(workspace_root or "", "workspace_root")
    env_db = os.environ.get("GREATWALL_DB_PATH", "").strip()
    if env_db:
        reject_null_bytes(env_db, "GREATWALL_DB_PATH")
        if not os.path.isabs(env_db):
            raise FailClosedError(
                ERR_STORAGE,
                f"GREATWALL_DB_PATH 必须为绝对路径，当前收到: {env_db!r}",
            )
        if os.name == "nt":
            drive, tail = os.path.splitdrive(env_db)
            if not drive or not (tail.startswith("\\") or tail.startswith("/")):
                raise FailClosedError(
                    ERR_STORAGE,
                    f"Windows GREATWALL_DB_PATH 必须包含完整盘符或 UNC 根路径: {env_db!r}",
                )
        db_path = Path(os.path.realpath(env_db))
        ws_clean = (workspace_root or "").strip()
        if ws_clean:
            _validate_abs_workspace_root(ws_clean)
            norm_ws = os.path.normcase(os.path.realpath(ws_clean))
            ws_hash = hashlib.sha256(norm_ws.encode("utf-8")).hexdigest()[:16]
        else:
            norm_ws = ""
            ws_hash = "explicit_db"
        data_dir = db_path.parent / "artifacts"
        return {
            "db_path": db_path,
            "data_dir": data_dir,
            "eval_artifacts_dir": data_dir / "eval_artifacts",
            "snapshots_dir": data_dir / "snapshots",
            "outputs_dir": data_dir / "outputs",
            "skill_ledger_path": data_dir / "skills" / "SKILL_LEDGER.json",
            "ws_hash": ws_hash,
            "normalized_workspace": norm_ws,
        }

    plugin_data = os.environ.get("PLUGIN_DATA", "").strip()
    ws = _validate_abs_workspace_root(workspace_root)
    norm_ws = os.path.normcase(os.path.realpath(ws))
    ws_hash = hashlib.sha256(norm_ws.encode("utf-8")).hexdigest()[:16]

    if not plugin_data:
        dsh_home = os.environ.get("DSH_HOME", "").strip()
        base_dir = Path(os.path.realpath(dsh_home)) if dsh_home else (Path.home() / ".dsh")
        data_dir = base_dir / "greatwall-v6up" / "workspaces" / ws_hash
    else:
        reject_null_bytes(plugin_data, "PLUGIN_DATA")
        if not os.path.isabs(plugin_data):
            raise FailClosedError(
                ERR_STORAGE,
                f"PLUGIN_DATA 必须为绝对路径，当前收到: {plugin_data!r}",
            )
        data_dir = Path(os.path.realpath(plugin_data)) / "workspaces" / ws_hash

    db_path = data_dir / "greatwall.db"
    return {
        "db_path": db_path,
        "data_dir": data_dir,
        "eval_artifacts_dir": data_dir / "eval_artifacts",
        "snapshots_dir": data_dir / "snapshots",
        "outputs_dir": data_dir / "outputs",
        "skill_ledger_path": data_dir / "skills" / "SKILL_LEDGER.json",
        "ws_hash": ws_hash,
        "normalized_workspace": norm_ws,
    }


SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS epoch_config (
    config_id TEXT PRIMARY KEY DEFAULT 'active',
    epoch_id INTEGER NOT NULL DEFAULT 1,
    goal_md TEXT NOT NULL DEFAULT '',
    required_questions_json TEXT NOT NULL DEFAULT '[]',
    contracts_json TEXT NOT NULL DEFAULT '{}',
    stage TEXT NOT NULL DEFAULT 'STAGE1_PARSE0'
        CHECK(stage IN ('STAGE0_SMOKE', 'STAGE1_PARSE0', 'STAGE2_EVOLVE', 'STAGE3_CONSOLIDATE', 'CLOSED')),
    consecutive_non_l1_handoffs INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS method_families (
    epoch_id INTEGER NOT NULL DEFAULT 1,
    question_id TEXT NOT NULL,
    family_id TEXT NOT NULL,
    mechanism_signature TEXT NOT NULL,
    orthogonal_contrast TEXT NOT NULL DEFAULT '',
    family_status TEXT NOT NULL DEFAULT 'EXPLORING'
        CHECK(family_status IN ('EXPLORING', 'MATURE_PROVEN', 'BLOCKED_MISSING_LEMMA', 'REFUTED')),
    depends_on_questions_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (epoch_id, question_id, family_id)
);

CREATE TABLE IF NOT EXISTS domain_hooks_by_question (
    question_id TEXT PRIMARY KEY,
    hook_rel_path TEXT NOT NULL,
    hook_sha256 TEXT NOT NULL,
    baseline_rel_path TEXT NOT NULL,
    fidelity_max_error_pct REAL NOT NULL,
    plugin_protocol_version TEXT NOT NULL DEFAULT 'v1',
    eval_epoch_version INTEGER NOT NULL DEFAULT 1,
    bb_epsilon_score REAL NULL,
    adversarial_qp_score REAL NULL,
    public_input_sample_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 真相 ②：谱系 DAG（原 L1 直接合一，废除 bound_state_version）
CREATE TABLE IF NOT EXISTS lineage_nodes (
    node_id TEXT PRIMARY KEY,
    epoch_id INTEGER NOT NULL DEFAULT 1,
    question_id TEXT NOT NULL,
    branch_id TEXT NOT NULL,
    family_id TEXT NOT NULL,
    parent_node_id TEXT NULL REFERENCES lineage_nodes(node_id),
    generation INTEGER NOT NULL DEFAULT 1,
    node_status TEXT NOT NULL DEFAULT 'EXPLORING'
        CHECK(node_status IN ('EXPLORING', 'AWAITING_TRIAGE', 'BLOCKED_L4B', 'CLOSED')),
    triage_level TEXT NOT NULL DEFAULT '',
    stagnation_lane TEXT NOT NULL DEFAULT '',
    worktree_abs_path TEXT NOT NULL,
    retained_candidate_id TEXT NOT NULL DEFAULT '',
    retained_snapshot_abs_path TEXT NOT NULL DEFAULT '',
    column_a_facts_md TEXT NOT NULL DEFAULT '',
    column_b_hypothesis_md TEXT NOT NULL DEFAULT '',
    will_md TEXT NOT NULL DEFAULT '',
    sanitized_code_diff_md TEXT NOT NULL DEFAULT '',
    briefing_snapshot_md TEXT NOT NULL DEFAULT '',
    local_sweeps_json TEXT NOT NULL DEFAULT '[]',
    pressure_tokens INTEGER NOT NULL DEFAULT 0,
    eval_count INTEGER NOT NULL DEFAULT 0,
    first_reflection_unlocked INTEGER NOT NULL DEFAULT 0 CHECK(first_reflection_unlocked IN (0, 1)),
    inplace_repair_count INTEGER NOT NULL DEFAULT 0,
    consecutive_exec_errors INTEGER NOT NULL DEFAULT 0,
    reopen_condition TEXT NOT NULL DEFAULT '',
    bound_obs_ids_json TEXT NOT NULL DEFAULT '[]',
    reflections_json TEXT NOT NULL DEFAULT '[]',
    scratch_log_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 真相 ①：客观观测账（按子题绑定 hook_sha256 与持久化 Stage A 产物路径）
CREATE TABLE IF NOT EXISTS observations (
    obs_id TEXT PRIMARY KEY,
    epoch_id INTEGER NOT NULL DEFAULT 1,
    question_id TEXT NOT NULL,
    branch_id TEXT NOT NULL,
    node_id TEXT NOT NULL REFERENCES lineage_nodes(node_id),
    run_claim_id TEXT NOT NULL,
    candidate_hash TEXT NOT NULL,
    spec_hash TEXT NOT NULL,
    domain_hook_sha256 TEXT NOT NULL,
    eval_epoch_version INTEGER NOT NULL DEFAULT 1,
    stage_a_artifact_path TEXT NOT NULL DEFAULT '',
    obs_status TEXT NOT NULL
        CHECK(obs_status IN (
            'VALID',
            'EXECUTION_ERROR',
            'MEASURED_NON_IMPROVEMENT',
            'INCONCLUSIVE',
            'PENDING_REVALIDATION',
            'INVALIDATED'
        )),
    passed INTEGER NOT NULL DEFAULT 0 CHECK(passed IN (0, 1)),
    metrics_json TEXT NOT NULL DEFAULT '{}',
    details_text TEXT NOT NULL DEFAULT '',
    linguistic_prediction TEXT NOT NULL,
    validity_reason TEXT NOT NULL DEFAULT '',
    comparable_rank_score REAL NULL,
    evaluator_spec_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (node_id, run_claim_id)
);

-- 观测重评队列专表（配合触发器根治 P26）
CREATE TABLE IF NOT EXISTS pending_revalidation_queue (
    queue_id TEXT PRIMARY KEY,
    obs_id TEXT NOT NULL REFERENCES observations(obs_id),
    question_id TEXT NOT NULL,
    old_hook_sha256 TEXT NOT NULL,
    new_hook_sha256 TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING', 'COMPLETED', 'FAILED')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS trg_obs_pending_reval_require_queue
BEFORE UPDATE OF obs_status ON observations
WHEN NEW.obs_status = 'PENDING_REVALIDATION'
  AND NOT EXISTS (
      SELECT 1 FROM pending_revalidation_queue q
      WHERE q.obs_id = NEW.obs_id AND q.status = 'PENDING'
  )
BEGIN
    SELECT RAISE(ABORT, 'PENDING_REVALIDATION_MISSING_QUEUE_ROW: 观测进入 PENDING_REVALIDATION 必须同事务先入队 pending_revalidation_queue');
END;

-- 真相 ③ 左翼：外藏文献与定理算子卡 ([R###]，0% 起开放 Pull)
CREATE TABLE IF NOT EXISTS external_literature_cards (
    ref_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL,
    title TEXT NOT NULL,
    abstract_md TEXT NOT NULL,
    exact_preconditions_md TEXT NOT NULL,
    formulas_or_operators_md TEXT NOT NULL,
    read_depth TEXT NOT NULL CHECK(read_depth IN ('full_text', 'specified_sections', 'abstract_only')),
    support_scope TEXT NOT NULL CHECK(support_scope IN (
        'DIRECT_PROOF_OR_EXACT_MEASUREMENT',
        'CONDITIONALLY_VERIFIED',
        'NEGATIVE_REFUTATION',
        'HEURISTIC_CORRELATION',
        'BACKGROUND_REFERENCE',
        'direct_target_matched_context',
        'target_specific_different_context',
        'related_pathway_complex_module',
        'broad_biological_process',
        'indirect_or_speculative'
    )),
    source_citation TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- 两阶段合流盲审队列
CREATE TABLE IF NOT EXISTS review_queue (
    review_id TEXT PRIMARY KEY,
    source_node_id TEXT NOT NULL REFERENCES lineage_nodes(node_id),
    question_id TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'LEVEL1_MANUSCRIPT'
        CHECK(source_type IN ('LEVEL1_MANUSCRIPT', 'AUDITOR_SALVAGED_LEMMA')),
    proposer_session_id TEXT NOT NULL DEFAULT '',
    reviewer_session_id TEXT NOT NULL DEFAULT '',
    review_status TEXT NOT NULL DEFAULT 'STAGE1_BLIND'
        CHECK(review_status IN ('STAGE1_BLIND', 'STAGE2_UNBLIND', 'CLOSED_REJECTED_TO_L2', 'CLOSED_ACCEPTED_TO_L3')),
    manuscript_title TEXT NOT NULL DEFAULT '',
    salvage_abstract_md TEXT NOT NULL DEFAULT '',
    column_a_snapshot_md TEXT NOT NULL,
    column_b_snapshot_md TEXT NOT NULL DEFAULT '',
    sanitized_code_diff_md TEXT NOT NULL DEFAULT '',
    bound_obs_ids_json TEXT NOT NULL DEFAULT '[]',
    stage1_ledger_json TEXT NOT NULL DEFAULT '[]',
    stage1_verdict TEXT NULL CHECK(stage1_verdict IS NULL OR stage1_verdict IN ('PASS', 'REJECT')),
    reject_failure_reason TEXT NULL,
    exact_refuted_scope_md TEXT NULL,
    stage1_locked_at TEXT NULL,
    final_verdict TEXT NULL CHECK(final_verdict IS NULL OR final_verdict IN ('PASS', 'PASS_WITH_NARROWED_SCOPE', 'REJECT')),
    stage2_comparison_notes TEXT NOT NULL DEFAULT '',
    cross_pollinate_json TEXT NULL,
    final_locked_at TEXT NULL,
    created_at TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS trg_reviews_lock_stage1
BEFORE UPDATE ON review_queue
WHEN OLD.stage1_locked_at IS NOT NULL
  AND (
      NEW.stage1_ledger_json != OLD.stage1_ledger_json
      OR IFNULL(NEW.stage1_verdict, '') != IFNULL(OLD.stage1_verdict, '')
      OR NEW.stage1_locked_at != OLD.stage1_locked_at
      OR NEW.source_node_id != OLD.source_node_id
      OR NEW.proposer_session_id != OLD.proposer_session_id
      OR NEW.reviewer_session_id != OLD.reviewer_session_id
  )
BEGIN
    SELECT RAISE(ABORT, 'STAGE1_LEDGER_IMMUTABLE: Stage 1 证据账本已锁定，永久禁止篡改');
END;

CREATE TRIGGER IF NOT EXISTS trg_reviews_lock_final
BEFORE UPDATE ON review_queue
WHEN OLD.final_locked_at IS NOT NULL
  AND (
      NEW.review_status != OLD.review_status
      OR IFNULL(NEW.final_verdict, '') != IFNULL(OLD.final_verdict, '')
      OR NEW.final_locked_at != OLD.final_locked_at
      OR NEW.stage2_comparison_notes != OLD.stage2_comparison_notes
      OR IFNULL(NEW.exact_refuted_scope_md, '') != IFNULL(OLD.exact_refuted_scope_md, '')
      OR IFNULL(NEW.cross_pollinate_json, '') != IFNULL(OLD.cross_pollinate_json, '')
      OR NEW.stage1_ledger_json != OLD.stage1_ledger_json
      OR NEW.source_node_id != OLD.source_node_id
      OR NEW.proposer_session_id != OLD.proposer_session_id
      OR NEW.reviewer_session_id != OLD.reviewer_session_id
  )
BEGIN
    SELECT RAISE(ABORT, 'STAGE2_FINAL_VERDICT_IMMUTABLE: 盲审终审结论已锁定，永久禁止篡改');
END;

-- 真相 ③ 右翼：内藏研究账本（L3_VERIFIED 黄金账本 + L2_FAILURE_RECORD 失败雷达）
CREATE TABLE IF NOT EXISTS internal_research_ledger (
    entry_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL,
    ledger_type TEXT NOT NULL CHECK(ledger_type IN ('L3_VERIFIED', 'L2_FAILURE_RECORD')),
    source_type TEXT NOT NULL CHECK(source_type IN (
        'LEVEL1_MANUSCRIPT',
        'AUDITOR_SALVAGED_LEMMA',
        'STAGE1_BLIND_REJECT',
        'STAGE2_UNBLIND_REJECT',
        'L2_REPAIR_EXHAUSTED',
        'L4A_BARRIER_PROOF'
    )),
    method_family_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    abstract_md TEXT NOT NULL,
    exact_verified_scope_md TEXT NOT NULL DEFAULT '',
    exact_refuted_scope_md TEXT NOT NULL DEFAULT '',
    body_proof_or_code_md TEXT NOT NULL DEFAULT '',
    bound_obs_ids_json TEXT NOT NULL DEFAULT '[]',
    depends_on_ids_json TEXT NOT NULL DEFAULT '[]',
    domain_hook_sha256 TEXT NOT NULL DEFAULT '',
    eval_epoch_version INTEGER NOT NULL DEFAULT 1,
    verified_review_id TEXT NULL REFERENCES review_queue(review_id),
    ledger_status TEXT NOT NULL DEFAULT 'active'
        CHECK(ledger_status IN ('active', 'recheck_triggered', 'downgraded', 'retracted_premise_invalid', 'retracted_insufficient_support')),
    created_at TEXT NOT NULL,
    CHECK (ledger_type != 'L3_VERIFIED' OR verified_review_id IS NOT NULL)
);

CREATE TRIGGER IF NOT EXISTS trg_l3_require_stage2_pass
BEFORE INSERT ON internal_research_ledger
WHEN NEW.ledger_type = 'L3_VERIFIED'
  AND NOT EXISTS (
      SELECT 1 FROM review_queue r
      WHERE r.review_id = NEW.verified_review_id
        AND r.review_status = 'CLOSED_ACCEPTED_TO_L3'
        AND r.stage1_locked_at IS NOT NULL
        AND r.final_locked_at IS NOT NULL
  )
BEGIN
    SELECT RAISE(ABORT, 'L3_REQUIRES_BLIND_REVIEW_PASS: 未通过两阶段盲审禁止写入 L3_VERIFIED');
END;

CREATE TRIGGER IF NOT EXISTS trg_obs_invalidated_cascade_recheck
AFTER UPDATE OF obs_status ON observations
WHEN NEW.obs_status IN ('INVALIDATED', 'PENDING_REVALIDATION')
  AND OLD.obs_status = 'VALID'
BEGIN
    UPDATE internal_research_ledger
    SET ledger_status = 'recheck_triggered'
    WHERE ledger_type = 'L3_VERIFIED'
      AND ledger_status = 'active'
      AND (
          EXISTS (
              SELECT 1 FROM json_each(bound_obs_ids_json) jb
              WHERE jb.value = NEW.obs_id
          )
          OR EXISTS (
              SELECT 1
              FROM epistemic_edges e
              JOIN json_each(internal_research_ledger.bound_obs_ids_json) jb ON jb.value = e.src_id
              WHERE e.edge_track = 'CLAIM_DECLARED'
                AND e.edge_type = 'REQUIRED_PREMISE'
                AND e.dst_id = NEW.obs_id
          )
      );
END;

CREATE TRIGGER IF NOT EXISTS trg_l3_retract_cascade_recheck
AFTER UPDATE OF ledger_status ON internal_research_ledger
WHEN NEW.ledger_status IN ('downgraded', 'retracted_premise_invalid', 'retracted_insufficient_support')
  AND OLD.ledger_status IN ('active', 'recheck_triggered')
BEGIN
    UPDATE internal_research_ledger
    SET ledger_status = 'recheck_triggered'
    WHERE entry_id != NEW.entry_id
      AND ledger_type = 'L3_VERIFIED'
      AND ledger_status = 'active'
      AND EXISTS (
          SELECT 1
          FROM epistemic_edges e
          JOIN json_each(internal_research_ledger.bound_obs_ids_json) jb ON jb.value = e.src_id
          WHERE e.edge_track = 'CLAIM_DECLARED'
            AND e.edge_type = 'REQUIRED_PREMISE'
            AND e.dst_id = NEW.entry_id
      );
END;

CREATE TABLE IF NOT EXISTS epistemic_edges (
    edge_id TEXT PRIMARY KEY,
    src_id TEXT NOT NULL,
    dst_id TEXT NOT NULL,
    edge_track TEXT NOT NULL CHECK(edge_track IN ('FACT_LOG', 'CLAIM_DECLARED')),
    edge_type TEXT NOT NULL CHECK(edge_type IN (
        'REQUIRED_PREMISE',
        'INDEPENDENT_SUPPORT',
        'MOTIVATING_REF',
        'READ',
        'RETRIEVED',
        'USED_TOOL',
        'PRODUCED',
        'UNAUTHORIZED_TOOL_ATTEMPT'
    )),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS works_engineering_queue (
    ticket_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL,
    node_id TEXT NOT NULL DEFAULT '',
    source_type TEXT NOT NULL CHECK(source_type IN ('AUTO_CONSECUTIVE_ERRORS', 'COMPANION_PAIN_POINT')),
    description_md TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN', 'RESOLVED', 'DISMISSED')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS survey_requests (
    request_id TEXT PRIMARY KEY,
    node_id TEXT NOT NULL DEFAULT '',
    question_id TEXT NOT NULL,
    topic_query TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING', 'FULFILLED')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS compliance_alerts (
    alert_id TEXT PRIMARY KEY,
    stage TEXT NOT NULL CHECK(stage IN ('STAGE1_GATE', 'STAGE2_HEARTBEAT', 'STAGE2_CLOSURE_GATE', 'STAGE3_FINAL_AUDIT')),
    status TEXT NOT NULL CHECK(status IN ('PASSED', 'ALERT', 'BLOCKED')),
    blocking_questions_zero_l3_json TEXT NOT NULL DEFAULT '[]',
    unread_citation_nodes_json TEXT NOT NULL DEFAULT '[]',
    notes TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS saved_graph_queries (
    query_name TEXT PRIMARY KEY,
    author_role TEXT NOT NULL,
    author_session_id TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL,
    sql_select TEXT NOT NULL,
    usage_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS lineage_fts USING fts5(
    node_id UNINDEXED,
    question_id UNINDEXED,
    branch_id UNINDEXED,
    column_a_facts_md,
    tokenize='unicode61'
);

CREATE VIRTUAL TABLE IF NOT EXISTS external_literature_fts USING fts5(
    ref_id UNINDEXED,
    question_id UNINDEXED,
    title,
    abstract_md,
    exact_preconditions_md,
    tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS trg_ext_lit_ai AFTER INSERT ON external_literature_cards BEGIN
    INSERT INTO external_literature_fts(rowid, ref_id, question_id, title, abstract_md, exact_preconditions_md)
    VALUES (NEW.rowid, NEW.ref_id, NEW.question_id, NEW.title, NEW.abstract_md, NEW.exact_preconditions_md);
END;

CREATE TRIGGER IF NOT EXISTS trg_ext_lit_ad AFTER DELETE ON external_literature_cards BEGIN
    DELETE FROM external_literature_fts WHERE rowid = OLD.rowid;
END;

CREATE TRIGGER IF NOT EXISTS trg_ext_lit_au AFTER UPDATE ON external_literature_cards BEGIN
    DELETE FROM external_literature_fts WHERE rowid = OLD.rowid;
    INSERT INTO external_literature_fts(rowid, ref_id, question_id, title, abstract_md, exact_preconditions_md)
    VALUES (NEW.rowid, NEW.ref_id, NEW.question_id, NEW.title, NEW.abstract_md, NEW.exact_preconditions_md);
END;

CREATE VIRTUAL TABLE IF NOT EXISTS internal_ledger_fts USING fts5(
    entry_id UNINDEXED,
    question_id UNINDEXED,
    ledger_type UNINDEXED,
    title,
    abstract_md,
    exact_verified_scope_md,
    exact_refuted_scope_md,
    tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS trg_int_ledger_ai AFTER INSERT ON internal_research_ledger BEGIN
    INSERT INTO internal_ledger_fts(rowid, entry_id, question_id, ledger_type, title, abstract_md, exact_verified_scope_md, exact_refuted_scope_md)
    VALUES (NEW.rowid, NEW.entry_id, NEW.question_id, NEW.ledger_type, NEW.title, NEW.abstract_md, NEW.exact_verified_scope_md, NEW.exact_refuted_scope_md);
END;

CREATE TRIGGER IF NOT EXISTS trg_int_ledger_ad AFTER DELETE ON internal_research_ledger BEGIN
    DELETE FROM internal_ledger_fts WHERE rowid = OLD.rowid;
END;

CREATE TRIGGER IF NOT EXISTS trg_int_ledger_au AFTER UPDATE ON internal_research_ledger BEGIN
    DELETE FROM internal_ledger_fts WHERE rowid = OLD.rowid;
    INSERT INTO internal_ledger_fts(rowid, entry_id, question_id, ledger_type, title, abstract_md, exact_verified_scope_md, exact_refuted_scope_md)
    VALUES (NEW.rowid, NEW.entry_id, NEW.question_id, NEW.ledger_type, NEW.title, NEW.abstract_md, NEW.exact_verified_scope_md, NEW.exact_refuted_scope_md);
END;

CREATE INDEX IF NOT EXISTS idx_lineage_branch ON lineage_nodes(question_id, branch_id, node_status);
CREATE INDEX IF NOT EXISTS idx_obs_node_hook ON observations(question_id, node_id, domain_hook_sha256, obs_status);
CREATE INDEX IF NOT EXISTS idx_reval_status ON pending_revalidation_queue(question_id, status);
CREATE INDEX IF NOT EXISTS idx_review_status ON review_queue(question_id, review_status);
CREATE INDEX IF NOT EXISTS idx_ledger_q_type ON internal_research_ledger(question_id, ledger_type, ledger_status);
CREATE INDEX IF NOT EXISTS idx_edges_src ON epistemic_edges(src_id, edge_track);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON epistemic_edges(dst_id, edge_type);
"""


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl_fragment: str) -> None:
    """对既有 SQLite 库幂等补列，避免升级表结构时缺字段。"""
    cols = {str(r["name"]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_fragment}")


def ensure_schema(conn: sqlite3.Connection) -> None:
    """在已开启 WAL 与外键的读写连接上幂等建表与触发器。"""
    conn.executescript(SCHEMA_DDL)
    _ensure_column(conn, "method_families", "depends_on_questions_json", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(conn, "domain_hooks_by_question", "public_input_sample_json", "TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(conn, "lineage_nodes", "bound_obs_ids_json", "TEXT NOT NULL DEFAULT '[]'")


def propagate_dependency_recheck(conn: sqlite3.Connection, root_ids: list[str]) -> dict[str, list[str]]:
    """沿 REQUIRED_PREMISE 递推标记受影响 L3_VERIFIED 为 recheck_triggered；INDEPENDENT_SUPPORT/MOTIVATING_REF 仅记提示绝不吊销。"""
    visited: set[str] = set()
    queue = [str(r) for r in root_ids if str(r).strip()]
    recheck_entries: list[str] = []
    non_blocking_mentions: list[str] = []

    while queue:
        cur = queue.pop(0)
        if cur in visited:
            continue
        visited.add(cur)
        rows = conn.execute(
            """
            SELECT l.entry_id, l.ledger_status, e.edge_type
            FROM epistemic_edges e
            JOIN internal_research_ledger l ON (
                e.src_id = l.entry_id OR EXISTS (
                    SELECT 1 FROM json_each(l.bound_obs_ids_json) jb WHERE jb.value = e.src_id
                )
            )
            WHERE e.edge_track = 'CLAIM_DECLARED' AND e.dst_id = ? AND l.ledger_type = 'L3_VERIFIED'
            """,
            (cur,),
        ).fetchall()
        for r in rows:
            eid = str(r["entry_id"])
            etype = str(r["edge_type"])
            if etype == "REQUIRED_PREMISE":
                if str(r["ledger_status"]) == "active":
                    conn.execute(
                        "UPDATE internal_research_ledger SET ledger_status = 'recheck_triggered' WHERE entry_id = ?",
                        (eid,),
                    )
                    recheck_entries.append(eid)
                queue.append(eid)
            else:
                if eid not in non_blocking_mentions:
                    non_blocking_mentions.append(eid)
    return {"recheck_triggered_entries": recheck_entries, "independent_or_motivating_unaffected": non_blocking_mentions}


def open_rw_connection(db_path: Path, init_schema: bool = False) -> sqlite3.Connection:
    """打开启用 WAL、busy_timeout=5000、foreign_keys=ON 的读写连接。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=5.0, autocommit=True)
    conn.row_factory = sqlite3.Row
    wal_row = conn.execute("PRAGMA journal_mode=WAL;").fetchone()
    wal_mode = str(wal_row[0]).lower() if wal_row else ""
    if wal_mode != "wal":
        conn.close()
        raise FailClosedError(
            ERR_STORAGE,
            f"SQLite journal_mode 必须为 'wal'，实际返回 {wal_mode!r}",
        )
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    if init_schema:
        ensure_schema(conn)
    return conn


@contextmanager
def rw_immediate_tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """显式 BEGIN IMMEDIATE 写事务上下文，异常安全回滚。"""
    conn.execute("BEGIN IMMEDIATE;")
    try:
        yield conn
    except BaseException:
        try:
            if conn.in_transaction:
                conn.execute("ROLLBACK;")
        except sqlite3.Error:
            pass
        raise
    else:
        if conn.in_transaction:
            conn.execute("COMMIT;")


def open_ro_connection(db_path: Path) -> sqlite3.Connection:
    """打开短寿命只读连接（?mode=ro + autocommit=True + query_only=ON）。"""
    if not db_path.exists():
        raise FailClosedError(
            ERR_STORAGE,
            f"数据库文件尚未初始化，禁止提前以只读模式打开: {db_path}",
        )
    uri = db_path.as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0, autocommit=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA query_only=ON;")
    return conn


def _find_column_headers(text: str) -> tuple[list[int], list[int]]:
    """逐行扫描 Markdown 文本，按 CommonMark 围栏状态机跳过代码块后收集 A/B 栏标题偏移量。"""
    a_offsets: list[int] = []
    b_offsets: list[int] = []
    fence_char = ""
    fence_len = 0
    pos = 0

    for line in text.splitlines(keepends=True):
        line_no_nl = line.rstrip("\r\n")
        if not fence_char:
            open_m = _OPEN_FENCE_RE.match(line_no_nl)
            if open_m:
                marker = open_m.group("fence")
                info = open_m.group("info")
                if not (marker[0] == "`" and "`" in info):
                    fence_char = marker[0]
                    fence_len = len(marker)
                    pos += len(line)
                    continue
            if _COL_A_LINE_RE.match(line):
                a_offsets.append(pos)
            elif _COL_B_LINE_RE.match(line):
                b_offsets.append(pos)
        else:
            close_m = _CLOSE_FENCE_RE.match(line_no_nl)
            if close_m:
                marker = close_m.group("fence")
                if marker[0] == fence_char and len(marker) >= fence_len:
                    fence_char = ""
                    fence_len = 0
        pos += len(line)

    return a_offsets, b_offsets


def split_handoff_columns(handoff_note_md: str) -> tuple[str, str]:
    """将双栏交接手记拆分为 (A 栏客观事实, B 栏主观洞察)。"""
    text = handoff_note_md or ""
    a_offsets, b_offsets = _find_column_headers(text)
    if a_offsets and b_offsets and a_offsets[0] < b_offsets[0]:
        b_start = b_offsets[0]
        return text[:b_start].strip(), text[b_start:].strip()
    if a_offsets and not b_offsets:
        return text[a_offsets[0] :].strip(), ""
    return "", ""


def has_dual_column_structure(handoff_note_md: str) -> bool:
    """校验手记文本是否包含唯一且有序的 A 栏与 B 栏标题（跳过代码围栏）。"""
    text = handoff_note_md or ""
    a_offsets, b_offsets = _find_column_headers(text)
    return len(a_offsets) == 1 and len(b_offsets) == 1 and a_offsets[0] < b_offsets[0]


def sanitize_fts5_query(raw_query: str, target_cols: str | list[str]) -> str | None:
    """净化用户输入并构造指定列的 FTS5 MATCH 表达式。"""
    if not raw_query or not raw_query.strip():
        return None
    cleaned = _FTS5_META_RE.sub(" ", raw_query)
    cols = [target_cols] if isinstance(target_cols, str) else [c for c in target_cols if c]
    if not cols:
        return None
    safe_tokens: list[str] = []
    for tok in cleaned.split():
        if tok.upper() in _FTS5_RESERVED_WORDS:
            continue
        if not tok.replace('"', ""):
            continue
        escaped = tok.replace('"', '""')
        if len(cols) == 1:
            safe_tokens.append(f'{cols[0]} : "{escaped}"')
        else:
            col_expr = " OR ".join(f'{c} : "{escaped}"' for c in cols)
            safe_tokens.append(f"({col_expr})")
    if not safe_tokens:
        return None
    return " ".join(safe_tokens)


def normalize_ref_candidates(ref_id: str) -> list[str]:
    """为引用 ID 生成原始、去方括号及带方括号候选形式。"""
    s = (ref_id or "").strip()
    if not s:
        return []
    bare = s[1:-1].strip() if s.startswith("[") and s.endswith("]") else s
    cands = []
    for cand in (s, bare, f"[{bare}]"):
        if cand and cand not in cands:
            cands.append(cand)
    return cands


def resolve_ref_target(conn: sqlite3.Connection, raw_id: str) -> tuple[str, str]:
    """解析引用 ID 在三真相表中的目标类型与规范主键。"""
    for cand in normalize_ref_candidates(raw_id):
        row = conn.execute("SELECT obs_id FROM observations WHERE obs_id = ?", (cand,)).fetchone()
        if row is not None:
            return "obs", str(row["obs_id"])
        row = conn.execute("SELECT ref_id FROM external_literature_cards WHERE ref_id = ?", (cand,)).fetchone()
        if row is not None:
            return "external_r", str(row["ref_id"])
        row = conn.execute("SELECT entry_id, ledger_type FROM internal_research_ledger WHERE entry_id = ?", (cand,)).fetchone()
        if row is not None:
            return str(row["ledger_type"]).lower(), str(row["entry_id"])
        row = conn.execute("SELECT node_id FROM lineage_nodes WHERE node_id = ?", (cand,)).fetchone()
        if row is not None:
            return "lineage_node", str(row["node_id"])
    raise FailClosedError(
        ERR_NOT_FOUND,
        f"外键阻断：声明引用的条目 {raw_id!r} 在 observations / external_literature_cards / internal_research_ledger / lineage_nodes 中不存在",
    )
