"""Durable operator-plane arrangements, receipts, pinned notes and handbacks."""

V031_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS run_arrangements (
    arrangement_id TEXT PRIMARY KEY,
    arrangement_version INTEGER NOT NULL UNIQUE,
    epoch_id INTEGER NOT NULL DEFAULT 1,
    scope_type TEXT NOT NULL CHECK(scope_type IN ('PROJECT', 'QUESTION', 'NODE')),
    target_id TEXT NOT NULL,                  -- 'ALL' / question_id / node_id
    patch_json TEXT NOT NULL DEFAULT '{}',    -- 如 {"priority_weight":200, "max_active_branches":2, "dispatch_policy":"NO_NEW_DISPATCH", "inflight_drain_mode":"FINISH_CURRENT_TURN"}
    summary_md TEXT NOT NULL DEFAULT '',      -- 供置顶锚点卡与面板展示的一句话自然语言摘要
    ends_on_kind TEXT NOT NULL DEFAULT 'MANUAL'
        CHECK(ends_on_kind IN ('MANUAL', 'AT_TIME', 'AFTER_INFLIGHT_BATCH')),
    expires_at TEXT,                          -- ends_on_kind = 'AT_TIME' 时的 UTC ISO 时间戳
    watch_node_ids_json TEXT NOT NULL DEFAULT '[]', -- ends_on_kind = 'AFTER_INFLIGHT_BATCH' 时受理瞬间冻结的在途节点列表
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK(status IN ('ACTIVE', 'EXPIRED', 'SUPERSEDED', 'REVOKED')),
    superseded_by_id TEXT,
    actor_source TEXT NOT NULL DEFAULT 'gw_chief_human',
    op_id TEXT NOT NULL DEFAULT '',           -- 关联本次操作的回执编号
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_arrangements_active ON run_arrangements(status, arrangement_version ASC);
CREATE INDEX IF NOT EXISTS idx_arrangements_scope ON run_arrangements(scope_type, target_id, status);

-- ============================================================================
-- 29. 总控与面板共用的四态操作回执表 (operation_receipts)
-- ============================================================================
CREATE TABLE IF NOT EXISTS operation_receipts (
    op_id TEXT PRIMARY KEY,
    epoch_id INTEGER NOT NULL DEFAULT 1,
    actor_source TEXT NOT NULL,               -- 'gw_chief_human' / 'human_ui' / 'branch_handback'
    command_kind TEXT NOT NULL,               -- 'APPLY_ARRANGEMENT' / 'NODE_INTERVENE' / 'SEED_BRANCH' / ...
    summary_md TEXT NOT NULL,                 -- 人类可读操作摘要
    status TEXT NOT NULL DEFAULT 'SETTLED'
        CHECK(status IN ('SETTLED', 'DRAINING', 'PARTIAL_FAILED', 'SUPERSEDED')),
    pending_targets_json TEXT NOT NULL DEFAULT '[]', -- 仍在收尾退场中的具体 node_id 清单
    failed_items_json TEXT NOT NULL DEFAULT '[]',    -- 失败项详情 [{"target_id":..., "error":..., "retry_hint":...}]
    superseded_by_op_id TEXT,
    origin_handback_id TEXT,                  -- 若源于分支转办，关联原转办单以便回写分支确认
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    settled_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_op_receipts_recent ON operation_receipts(created_at DESC);

-- ============================================================================
-- 30. 总控置顶科研备忘与分支授权转办记录表 (chief_pinned_notes & handback_records)
-- ============================================================================
CREATE TABLE IF NOT EXISTS chief_pinned_notes (
    note_id TEXT PRIMARY KEY,
    epoch_id INTEGER NOT NULL DEFAULT 1,
    question_id TEXT NOT NULL DEFAULT 'ALL',
    content_md TEXT NOT NULL,                 -- 单条 <=200 字，全院活跃置顶总长硬限 <=400 字
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS handback_records (
    handback_id TEXT PRIMARY KEY,
    epoch_id INTEGER NOT NULL DEFAULT 1,
    source_node_id TEXT NOT NULL REFERENCES lineage_nodes(node_id),
    question_id TEXT NOT NULL,
    human_request_md TEXT NOT NULL,
    explorer_reason_md TEXT NOT NULL DEFAULT '',
    origin_human_rpc_id TEXT NOT NULL DEFAULT '',  -- 非空代表宿主实证捕获到分支内真实人类发言
    origin_human_mandate INTEGER NOT NULL DEFAULT 0, -- 1=赋予 gw_chief 一次性当面直执凭证
    status TEXT NOT NULL DEFAULT 'PENDING_CHIEF'
        CHECK(status IN ('PENDING_CHIEF', 'EXECUTED', 'ANSWERED_OR_DISMISSED')),
    resolved_op_id TEXT,
    resolution_summary_md TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_handbacks_status ON handback_records(status, created_at ASC);
CREATE TABLE IF NOT EXISTS epoch_archives (
    epoch_id INTEGER PRIMARY KEY,
    archive_abs_path TEXT NOT NULL,
    last_spec_revision INTEGER NOT NULL,
    proposal_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    inherited_external_literature INTEGER NOT NULL,
    inherited_instruments INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS operator_runtime_slots (
    node_id TEXT PRIMARY KEY REFERENCES lineage_nodes(node_id),
    owner_id TEXT NOT NULL,
    launch_id TEXT NOT NULL,
    slot_tier TEXT NOT NULL DEFAULT 'normal',
    worker_exited INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS trg_lineage_session_epoch AFTER INSERT ON lineage_nodes
WHEN NEW.session_epoch_id = 1
BEGIN
    UPDATE lineage_nodes SET session_epoch_id=COALESCE(
        (SELECT epoch_id FROM parse0_contract WHERE contract_id='active'), 1
    ) WHERE node_id=NEW.node_id;
END;
"""
