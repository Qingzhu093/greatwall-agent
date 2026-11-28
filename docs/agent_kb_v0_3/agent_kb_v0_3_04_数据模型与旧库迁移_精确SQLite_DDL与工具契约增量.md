# 知识卡 04（`v0.3.2` 权威定稿）：全量数据模型、精确 SQLite DDL、旧库无损热迁移与 53 窄工具契约

> **权威基线**：本文件与 [`greatwall_v0_3_2_architecture_and_engineering_manual.md`](../greatwall_v0_3_2_architecture_and_engineering_manual.md) 及 [`core_python/mcp_server/db/`](../../greatwall-v6up/core_python/mcp_server/db) 100% 对齐，完整涵盖 **`33` 张核心物理表 + `2` 张 FTS5 全文检索表 + `2` 个只读聚合视图 + `4` 条硬件级防作弊触发器**，以及 **`53` 个内核 MCP 窄工具**（另加宿主 `chief_watchdog_status` 共 54 个）。所有 SQL 均已在开启 `PRAGMA foreign_keys = ON` 的空库、`v0.2.0` 旧库与第三轮实机运行库克隆体上实测零违例通过。

---

## 一、全院 33 张核心物理表全景总索引

| 分层 | 表序号与物理表名 | 主键 | 归属工程与核心职责 |
| :--- | :--- | :--- | :--- |
| **基础层 (`schema_base.py`，19 张)** | `01. parse0_contract` | `contract_id` | 立项契约、子题顺序 `question_order_json`、自主档位 `autonomy_mode`、纪元 `epoch_id` |
| | `02. instruments` | `(instrument_id, version)` | 三类仪器注册、版本快照与校准集路径 |
| | `03. observations` | `obs_id` | 正式观测收据账本（含四元哈希与 **`frozen_code_snapshot_path`**） |
| | `04. probe_diagnostic_logs` | `probe_id` | 高频 `probe` 诊断日志（隔离不污正式观测） |
| | `05. async_eval_jobs` | `job_id` | `heavy` 重型异步评测队列与单次扣费锁 |
| | `06. lineage_nodes` | `node_id` | 单班岗探索节点主表（`360k` 默认窗口、52% 夜科学赌注、圆桌同行备忘） |
| | `07. lineage_dead_ends` | `dead_end_id` | 分支私有死胡同只追加表 |
| | `08. lineage_briefings` | `briefing_id` | 五段式行前看板（硬限 `total_chars <= 3600`） |
| | `09. external_literature_cards` *(+FTS5)* | `ref_id` | 外藏公开参考与定理卡 `[R###]` |
| | `10. internal_research_ledger` *(+FTS5)* | `entry_id` | 馆藏微型学术论文库（署名、谱系、引文网、三维分、三档分层、审稿附页） |
| | `11. review_queue` | `review_id` | 两阶段三维盲审队列（支持非阻塞快照稿与多篇组合完备终核单） |
| | `12. pending_revalidation_queue` | `queue_id` | 仪器升版后 Stage B 待重评队列 |
| | `13. method_families` | `family_id` | 正交方法学派登记表（`ACTIVE / BLOCKED / ARCHIVED`） |
| | `14. epistemic_edges` | `edge_id` | 事实读取边（`FACT_LOG`）与承重引用边（`CLAIM_DECLARED`） |
| | `15a. works_engineering_queue` | `ticket_id` | 工造司 5 类工单表（含精确 `resolution_note` 与版本溯源） |
| | `15b. survey_requests` | `req_id` | 脱敏外网文献查新请求表（专供 `external_surveyor`） |
| | `16a. compliance_alerts` | `alert_id` | 立项门禁与口径歧义合规告警表 |
| | `16b. saved_graph_queries` | `query_name` | 受控只读 SQL 图查询视图表 |
| | `17. project_closure_state` | `id (=1)` | Stage 3 外部不可变冻结目录与终核哈希锁 |
| **三层治理层 (`schema_v03.py`，7 张)** | `20. subproblem_runtime_state` | `question_id` | 子题权重、并发上限、派工开关与三道停工锁 |
| | `21. node_interventions` | `intervention_id` | 人工接管、SHA-256 改码对账、导师便签与撤编审计表 |
| | `22. runtime_effects` | `seq` | 带 60 秒租约的 11 类宿主副作用 Outbox 队列 |
| | `23. open_lemma_gaps` | `gap_id` | 缺失引理悬赏榜（区分 `LOAD_BEARING` 与 `IMPROVEMENT`） |
| | `24. control_proposals` | `proposal_id` | 高危控制与宪章确认提案表 |
| | `25. subproblem_living_surveys` | `survey_id` | 子题全局总览（核心四栏 `<= 4000` 字 + 独立 `marginal_notes_md <= 1500` 字） |
| | `26. wave_conferences` | `conference_id` | 脉冲同行拼图工作坊表（三问议程、`<= 6000` 字纪要、分脉备忘、双模收敛） |
| **运维总控层 (`schema_v031.py`，6 张)** | `28. run_arrangements` | `arrangement_id` | 版本化人类运行安排栈（四维正交控制与智能到期覆盖） |
| | `29. operation_receipts` | `op_id` | 总控与面板共用的四态诚实操作回执表 |
| | `30a. chief_pinned_notes` | `note_id` | 总控置顶科研共识备忘（全院活跃上限 `<= 400` 字） |
| | `30b. handback_records` | `handback_id` | 带人类授权透传凭证的子节点越界转办单 |
| | `31. epoch_archives` | `epoch_id` | 跨轮重置纪元归档台账 |
| | `32. operator_runtime_slots` | `node_id` | 进程级真实占槽与退场状态账本 |
| **文献综述层 (`schema_v032.py`，1 张)** | `33. internal_survey_requests` | `survey_req_id` | **院内零外网专题文献综述请求与报告表（`Archive Surveyor` 专用）** |

---

## 二、`v0.3.0` + `v0.3.1` + `v0.3.2` 精确建表与视图 DDL

```sql
-- ============================================================================
-- 20. 子题级运行时调度与三道停工锁状态表 (subproblem_runtime_state)
-- ============================================================================
CREATE TABLE IF NOT EXISTS subproblem_runtime_state (
    question_id TEXT PRIMARY KEY,
    priority_weight INTEGER NOT NULL DEFAULT 100,
    max_active_branches INTEGER NOT NULL DEFAULT 3,
    dispatch_policy TEXT NOT NULL DEFAULT 'NORMAL'
        CHECK(dispatch_policy IN ('NORMAL', 'NO_NEW_DISPATCH', 'PAUSED_ALL')),
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
        'EARLY_HANDOFF_AUTHORIZED',
        'ADVISOR_NOTE_SENT',
        'NODE_HIBERNATED',
        'NODE_RETIRED',
        'NODE_REACTIVATED'
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
-- 22. 事务后宿主副作用队列 (runtime_effects，11 类完整枚举)
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
        'RUN_INTERNAL_SURVEY',
        'RUN_WAVE_CONFERENCE',
        'NOTIFY_POLICY_CHANGED',
        'NOTIFY_CHIEF',
        'DELIVER_BRANCH_NOTE',
        'DELIVER_HANDBACK_RECEIPT'
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
-- 23. 纯命题引理悬赏榜 (open_lemma_gaps，含承重/改良双层区分)
-- ============================================================================
CREATE TABLE IF NOT EXISTS open_lemma_gaps (
    gap_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL REFERENCES subproblem_runtime_state(question_id),
    blocked_node_id TEXT NOT NULL REFERENCES lineage_nodes(node_id),
    formal_statement_md TEXT NOT NULL,
    verification_spec_md TEXT NOT NULL DEFAULT '',
    gap_tier TEXT NOT NULL DEFAULT 'LOAD_BEARING'
        CHECK(gap_tier IN ('LOAD_BEARING', 'IMPROVEMENT')),
    source_entry_id TEXT,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN', 'FULFILLED', 'CANCELLED')),
    fulfilled_by_entry_id TEXT REFERENCES internal_research_ledger(entry_id),
    created_at TEXT NOT NULL,
    fulfilled_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_lemma_gaps_q_status ON open_lemma_gaps(question_id, status);

-- ============================================================================
-- 24. 高危控制操作与宪章确认提案单 (control_proposals)
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
        'SET_AUTONOMY_MODE',
        'ADVANCE_EPOCH'
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
-- 25. 子题活体综述导览表 (subproblem_living_surveys，核心四栏<=4000字 + 边缘隔离栏)
-- ============================================================================
CREATE TABLE IF NOT EXISTS subproblem_living_surveys (
    survey_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL REFERENCES subproblem_runtime_state(question_id),
    revision INTEGER NOT NULL,
    sec1_baseline_and_instruments_md TEXT NOT NULL,
    sec2_l3_lemma_tree_md TEXT NOT NULL,
    sec3_avoidance_radar_md TEXT NOT NULL,
    sec4_explicit_gaps_md TEXT NOT NULL,
    marginal_notes_md TEXT NOT NULL DEFAULT '' CHECK(length(marginal_notes_md) <= 1500),
    total_chars INTEGER NOT NULL CHECK(total_chars <= 4000),
    trigger_reason TEXT NOT NULL DEFAULT 'MANUAL',
    created_at TEXT NOT NULL,
    UNIQUE(question_id, revision)
);
CREATE INDEX IF NOT EXISTS idx_living_surveys_q_rev ON subproblem_living_surveys(question_id, revision DESC);

-- ============================================================================
-- 26. 波次脉冲同行拼图工作坊表 (wave_conferences)
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
    agenda_json TEXT NOT NULL DEFAULT '{}',
    human_agenda_md TEXT NOT NULL DEFAULT '',
    critiques_ledger_json TEXT NOT NULL DEFAULT '[]',
    minutes_md TEXT NOT NULL DEFAULT '' CHECK(length(minutes_md) <= 6000),
    peer_takeaways_json TEXT NOT NULL DEFAULT '{}',
    linked_survey_id TEXT REFERENCES subproblem_living_surveys(survey_id),
    chair_session_id TEXT NOT NULL DEFAULT '',
    verdict_json TEXT,
    convergence_mode TEXT CHECK(convergence_mode IN ('NONE', 'CONVERGE_FULL_COMPOSITE', 'CONVERGE_SATURATED') OR convergence_mode IS NULL),
    synthesis_budget_nodes INTEGER NOT NULL DEFAULT 2,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(question_id, wave_no)
);

-- ============================================================================
-- 28~32. v0.3.1 运维总控平面持久表 (run_arrangements, operation_receipts 等)
-- ============================================================================
CREATE TABLE IF NOT EXISTS run_arrangements (
    arrangement_id TEXT PRIMARY KEY,
    arrangement_version INTEGER NOT NULL UNIQUE,
    epoch_id INTEGER NOT NULL DEFAULT 1,
    scope_type TEXT NOT NULL CHECK(scope_type IN ('PROJECT', 'QUESTION', 'NODE')),
    target_id TEXT NOT NULL,
    patch_json TEXT NOT NULL DEFAULT '{}',
    summary_md TEXT NOT NULL DEFAULT '',
    ends_on_kind TEXT NOT NULL DEFAULT 'MANUAL'
        CHECK(ends_on_kind IN ('MANUAL', 'AT_TIME', 'AFTER_INFLIGHT_BATCH')),
    expires_at TEXT,
    watch_node_ids_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK(status IN ('ACTIVE', 'EXPIRED', 'SUPERSEDED', 'REVOKED')),
    superseded_by_id TEXT,
    actor_source TEXT NOT NULL DEFAULT 'gw_chief_human',
    op_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_arrangements_active ON run_arrangements(status, arrangement_version ASC);
CREATE INDEX IF NOT EXISTS idx_arrangements_scope ON run_arrangements(scope_type, target_id, status);

CREATE TABLE IF NOT EXISTS operation_receipts (
    op_id TEXT PRIMARY KEY,
    epoch_id INTEGER NOT NULL DEFAULT 1,
    actor_source TEXT NOT NULL,
    command_kind TEXT NOT NULL,
    summary_md TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'SETTLED'
        CHECK(status IN ('SETTLED', 'DRAINING', 'PARTIAL_FAILED', 'SUPERSEDED')),
    pending_targets_json TEXT NOT NULL DEFAULT '[]',
    failed_items_json TEXT NOT NULL DEFAULT '[]',
    superseded_by_op_id TEXT,
    origin_handback_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    settled_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_op_receipts_recent ON operation_receipts(created_at DESC);

CREATE TABLE IF NOT EXISTS chief_pinned_notes (
    note_id TEXT PRIMARY KEY,
    epoch_id INTEGER NOT NULL DEFAULT 1,
    question_id TEXT NOT NULL DEFAULT 'ALL',
    content_md TEXT NOT NULL,
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
    origin_human_rpc_id TEXT NOT NULL DEFAULT '',
    origin_human_mandate INTEGER NOT NULL DEFAULT 0,
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

-- ============================================================================
-- 33. 院内零外网专题文献综述请求与报告表 (internal_survey_requests，v0.3.2 新增)
-- ============================================================================
CREATE TABLE IF NOT EXISTS internal_survey_requests (
    survey_req_id TEXT PRIMARY KEY,
    epoch_id INTEGER NOT NULL DEFAULT 1,
    question_id TEXT NOT NULL REFERENCES subproblem_runtime_state(question_id),
    requester_role TEXT NOT NULL CHECK(requester_role IN ('explorer', 'lineage_companion', 'gw_chief')),
    requester_node_id TEXT REFERENCES lineage_nodes(node_id),
    requester_session_id TEXT NOT NULL DEFAULT '',
    query_md TEXT NOT NULL CHECK(length(query_md) BETWEEN 10 AND 1500),
    focus_scope TEXT NOT NULL DEFAULT 'QUESTION_ONLY'
        CHECK(focus_scope IN ('QUESTION_ONLY', 'CROSS_QUESTION_ALL')),
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK(status IN ('PENDING', 'RUNNING', 'FULFILLED', 'FAILED')),
    report_md TEXT NOT NULL DEFAULT '' CHECK(length(report_md) <= 4000),
    cited_entry_ids_json TEXT NOT NULL DEFAULT '[]',
    cited_obs_ids_json TEXT NOT NULL DEFAULT '[]',
    chronicler_session_id TEXT NOT NULL DEFAULT '',
    error_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    fulfilled_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_int_survey_q_status
    ON internal_survey_requests(question_id, status, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_int_survey_node
    ON internal_survey_requests(requester_node_id, created_at DESC);

-- ============================================================================
-- 两个权威只读聚合视图 (v_library_avoidance_radar & v_library_mini_papers_catalog)
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

DROP VIEW IF EXISTS v_library_mini_papers_catalog;
CREATE VIEW v_library_mini_papers_catalog AS
SELECT
    l.entry_id,
    l.question_id,
    l.ledger_type,
    l.l3_entry_kind,
    l.goal_coverage,
    l.publish_tier,
    l.verified_spec_revision,
    l.author_node_id,
    l.author_branch_id,
    l.author_family_id,
    l.title,
    l.abstract_md,
    COALESCE(l.exact_verified_scope_md, l.exact_refuted_scope_md, '') AS scope_md,
    l.tags_json,
    l.cited_entries_json,
    l.bound_obs_ids_json,
    l.rigor_score,
    l.novelty_score,
    l.significance_score,
    l.overall_score,
    l.reviewer_comment_md,
    CASE WHEN l.publish_tier = 'MARGINAL_NOTE' THEN 1 ELSE 0 END AS is_marginal,
    l.created_at
FROM internal_research_ledger l
WHERE l.is_active = 1
ORDER BY
    is_marginal ASC,
    COALESCE(l.significance_score, 5) DESC,
    COALESCE(l.overall_score, 5.0) DESC,
    l.created_at DESC;
```

---

## 三、基础表 `v0.3.2` 幂等增量列、枚举重建与四条防作弊硬触发器

### 3.1 基础表新增列完整对照（`ALTER TABLE ADD COLUMN` 幂等执行）

1. **`observations`**：`frozen_code_snapshot_path TEXT NOT NULL DEFAULT ''`
2. **`lineage_nodes`**（新建默认 `effective_context_window = 360000`）：
   - `holiday_prompt_id INTEGER`
   - `holiday_bet_json TEXT NOT NULL DEFAULT '{}'`
   - `holiday_completed INTEGER NOT NULL DEFAULT 0`
   - `pending_review_feedback_json TEXT NOT NULL DEFAULT '[]'`
   - `peer_takeaways_json TEXT NOT NULL DEFAULT '[]'`
3. **`review_queue`**：
   - `non_blocking INTEGER NOT NULL DEFAULT 1`
   - `declared_citations_json TEXT NOT NULL DEFAULT '[]'`
   - `composite_entry_ids_json TEXT NOT NULL DEFAULT '[]'`
   - `rigor_score INTEGER`、`novelty_score INTEGER`、`significance_score INTEGER`
   - 表重建放开枚举：`source_type` 增加 `'SNAPSHOT_MANUSCRIPT'`, `'COMPOSITE_FULL_GOAL'`；`review_status` 增加 `'CLOSED_DUPLICATE'`；`final_verdict` 增加 `'REJECT_DUPLICATE'`。
4. **`internal_research_ledger`**：
   - `author_node_id TEXT`、`author_branch_id TEXT`、`author_family_id TEXT`
   - `tags_json TEXT NOT NULL DEFAULT '[]'`、`cited_entries_json TEXT NOT NULL DEFAULT '[]'`
   - `rigor_score INTEGER`、`novelty_score INTEGER`、`significance_score INTEGER`、`overall_score REAL`
   - `reviewer_comment_md TEXT NOT NULL DEFAULT ''`
   - `publish_tier` 支持三档：`'BASELINE_UPDATE' | 'VERIFIED_INCREMENTAL' | 'MARGINAL_NOTE'`。
5. **`works_engineering_queue`**：
   - `resolution_note TEXT NOT NULL DEFAULT ''`、`resolved_by_version INTEGER`
   - 表重建放开 `status` 枚举：`('OPEN', 'RESOLVED', 'WONTFIX', 'DUPLICATE')`。

### 3.2 四条硬件级防篡改触发器精确 SQL

```sql
-- 1. 盲审 Stage 1 证据账本与严密性分锁定不可逆触发器（v0.3.2 纳入 rigor_score 保护）
DROP TRIGGER IF EXISTS trg_reviews_lock_stage1;
CREATE TRIGGER trg_reviews_lock_stage1
BEFORE UPDATE OF stage1_ledger_json, stage1_locked_at, rigor_score ON review_queue
WHEN OLD.stage1_locked_at IS NOT NULL
  AND (
      COALESCE(NEW.stage1_ledger_json, '') != COALESCE(OLD.stage1_ledger_json, '')
      OR COALESCE(NEW.stage1_locked_at, '') != COALESCE(OLD.stage1_locked_at, '')
      OR COALESCE(NEW.rigor_score, -1) != COALESCE(OLD.rigor_score, -1)
  )
BEGIN
    SELECT RAISE(ABORT, 'STAGE1_LEDGER_IMMUTABLE');
END;

-- 2. L3_VERIFIED 入馆强制双阶段过审校验触发器（含 COMPOSITE_FULL_GOAL 统一适用）
DROP TRIGGER IF EXISTS trg_l3_require_verified_review;
CREATE TRIGGER trg_l3_require_verified_review
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

-- 3. 观测待重评状态必须伴随活跃重评队列行触发器
DROP TRIGGER IF EXISTS trg_obs_pending_reval_require_queue;
CREATE TRIGGER trg_obs_pending_reval_require_queue
BEFORE UPDATE OF obs_status ON observations
WHEN NEW.obs_status = 'PENDING_REVALIDATION'
  AND NOT EXISTS (
      SELECT 1 FROM pending_revalidation_queue q
      WHERE q.obs_id = NEW.obs_id AND q.status = 'PENDING'
  )
BEGIN
    SELECT RAISE(ABORT, 'PENDING_REVALIDATION_MISSING_QUEUE_ROW');
END;

-- 4. 70% 交班封存不可逆触发器（保护封存伴随参会时绝不反向涂改档案）
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
```

---

## 四、旧库（`v0.2.0` / `v0.3.0` / `v0.3.1`）原地无损热迁移流水线

`init_database_schema(conn)` 启动时按以下确定性顺序幂等执行：
1. 执行基础表、治理表、运维总控表与 `v0.3.2` 新增表 `CREATE TABLE IF NOT EXISTS`；
2. 逐列执行 `PRAGMA table_info` 检查并补齐全部增量列（必须在创建 `v_library_mini_papers_catalog` 视图前先补齐 `internal_research_ledger` 的三维分与署名列！）；
3. 复用 `_rebuild_table_without_fk(conn, ...)`（事务外切 `foreign_keys = OFF` + `legacy_alter_table = ON`，单事务重建表、拷全量旧行、重挂索引与触发器，恢复 `foreign_keys = ON` 并立即校验 `PRAGMA foreign_key_check` 0 违例）完成 `lineage_briefings`（`<= 3600` 字）、`subproblem_living_surveys`（`<= 4000` 字）、`review_queue`、`runtime_effects` 与 `works_engineering_queue` 的约束升级；
4. 重装上述 4 条防篡改触发器与 2 个只读视图，并对两张 FTS5 虚拟表执行 `'rebuild'` 同步索引；
5. 自动执行历史数据无损回填：回填既有 `L3` 的真实 `verified_spec_revision`，并通过 `review_queue -> lineage_nodes` 外键链自动回填历史馆藏论文的 `author_node_id`、`author_branch_id` 与 `author_family_id`。

---

## 五、`v0.3.2` 新增与扩充窄工具契约速查表（`CONTRACTS_SCHEMA_VERSION = "0.3.2"`）

| 工具名 | 变更类型 | 授权角色 | 核心参数与硬校验契约 |
| :--- | :---: | :--- | :--- |
| `request_internal_survey` | **新增 (#49)** | `explorer`(37%+), `lineage_companion`, `gw_chief` | `(question_id, query_md[10..1500], focus_scope="QUESTION_ONLY", node_id=None)` $\to$ 投递 `RUN_INTERNAL_SURVEY` 秒返 `survey_req_id` |
| `get_internal_survey_report` | **新增 (#50)** | `explorer`(37%+), `lineage_companion`, `gw_chief` | `(survey_req_id="", question_id="ALL")` $\to$ 读取已完成专题综述报告及引用列表 |
| `get_internal_survey_task` | **新增 (#51)** | `library_chronicler` | `(survey_req_id)` $\to$ 拉取待办问题、全馆三维分目录卡、排雷视图与有效观测摘要 |
| `publish_internal_survey_report` | **新增 (#52)** | `library_chronicler` | `(survey_req_id, report_md[800..4000], cited_entry_ids, cited_obs_ids=[])` $\to$ 核验引用实存并严禁违规指令，结案推送 |
| `submit_holiday_bet` | **新增 (#53)** | `explorer` | `(node_id, anomaly_or_analogy_md, testable_hypothesis_md, falsification_experiment_md)` $\to$ 52% 只读绿洲唯一放行工具，落库即恢复写/评测权 |
| `submit_node_handoff` | 兼容扩充 | `lineage_companion` | 新增 `manuscript_submissions`（默认 `non_blocking=True`，兼容 `local_lemma_submissions`）与 `holiday_bet_outcome`；总长 `<= 5000` 字，免 `tools/` 连坐哈希锁 |
| `submit_stage1_blind_ledger` | 兼容扩充 | `library_verifier` | 新增必填 `rigor_score` (`1..10`)；判 `PASS` 须 `rigor_score >= 7`，声称越界含局部真引理须判 `PARTIAL_PASS` |
| `submit_stage2_unblind_verdict` | 兼容扩充 | `library_verifier` | 新增 `novelty_score`, `significance_score`, `reviewer_comment_md`, `tags`, `confirmed_citations`；支持 `REJECT_DUPLICATE` 与 `MARGINAL_NOTE` 强制分流 |
| `submit_conference_statement` | 兼容扩充 | `lineage_companion`(封存态) | 新增 `speech_act` (`PROPOSE_AND_SELF_AUDIT` / 4类点对点回复动作) 与 `unverified_ideas`；Round 2 参会数 $\ge 2$ 时硬校验 `target_node_ids` 非空 |
| `record_conference_minutes` | 兼容扩充 | `conference_chair` | `minutes_md` 硬限升至 `<= 6000` 字（超限报错精简，禁静默切片）；同事务分拣 `peer_takeaways_json` |
| `publish_living_survey` | 兼容扩充 | `library_chronicler` | 核心四栏 `<= 4000` 字 + 新增独立 `marginal_notes_md <= 1500` 字物理隔离边角吐槽 |
| `submit_conference_verdict` | 兼容扩充 | `conference_chair` | 新增 `CONVERGE_SUBPROBLEM` (`CONVERGE_FULL_COMPOSITE \| CONVERGE_SATURATED`)；执行器固定按 Phase 1 腾槽 $\to$ Phase 2 合体/开枝 $\to$ Phase 3 收敛执行 |
