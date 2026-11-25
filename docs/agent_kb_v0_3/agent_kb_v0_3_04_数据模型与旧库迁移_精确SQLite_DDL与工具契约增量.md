# 知识卡 04（v0.3 终稿）：数据模型、精确 SQLite DDL、旧库迁移与契约增量

> **权威基线**：本文件所有外键、触发器与字段增量均 100% 对齐现版 [`db_schema.py`](file:///d:/antigravity/%E9%95%BF%E5%9F%8Eagent%E8%AE%BE%E8%AE%A1v6up%EF%BC%88Gemini%E8%B4%9F%E8%B4%A3%EF%BC%89/greatwall-v6up/core_python/mcp_server/db_schema.py)（19 张现有表 + 3 条硬触发器），**绝不修改任何现有表名、主键名或既有分诊/账本枚举**。

---

## 一、现版真实表与主键锚点

- `parse0_contract(contract_id)`（活跃行 `contract_id = 'active'`）
- `lineage_nodes(node_id)`、`lineage_briefings(briefing_id)`、`lineage_dead_ends(dead_end_id)`
- `observations(obs_id)`、`review_queue(review_id)`、`internal_research_ledger(entry_id)`、`project_closure_state(id)`

---

## 二、v0.3 精确增量 SQLite DDL（已通过真实 `PRAGMA foreign_keys = ON` 全量实测）

```sql
-- ============================================================================
-- 18. 子题级运行时调度与快慢双闸门状态表 (subproblem_runtime_state) [M1/M2]
-- ============================================================================
CREATE TABLE IF NOT EXISTS subproblem_runtime_state (
    question_id TEXT PRIMARY KEY,
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
    solved_entry_id TEXT REFERENCES internal_research_ledger(entry_id),
    solved_at_spec_revision INTEGER,
    baseline_entry_id TEXT REFERENCES internal_research_ledger(entry_id),
    baseline_metric_value REAL,
    metric_direction TEXT CHECK(metric_direction IN ('HIGHER_BETTER', 'LOWER_BETTER', 'QUALITATIVE') OR metric_direction IS NULL),
    question_token_budget INTEGER NOT NULL DEFAULT 0,
    spent_tokens INTEGER NOT NULL DEFAULT 0,
    completed_nodes_since_last_l3 INTEGER NOT NULL DEFAULT 0,
    max_stagnant_nodes INTEGER NOT NULL DEFAULT 6,
    completed_nodes_since_last_conference INTEGER NOT NULL DEFAULT 0,
    drain_grace_sec INTEGER NOT NULL DEFAULT 60,
    block_reason_code TEXT NOT NULL DEFAULT '',
    block_detail_md TEXT NOT NULL DEFAULT '',
    dispatch_generation INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);

-- ============================================================================
-- 19. 节点人工接管、改码对账与介入审计表 (node_interventions) [M1]
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
        'EARLY_HANDOFF_AUTHORIZED'
    )),
    actor_source TEXT NOT NULL CHECK(actor_source IN ('human_ui', 'control_plane', 'chief_approved')),
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
-- 20. 事务后宿主副作用队列 (runtime_effects，带租约、稳定外部标识与代数防竞态) [M1]
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
        'NOTIFY_CHIEF'
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
-- 21. 纯命题引理悬赏榜 (open_lemma_gaps，承接 LEVEL_4B 自动唤醒) [M2]
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
-- 22. 高危控制操作建议单 (control_proposals，gw-chief 起草 -> 人类真实授权落签) [M2]
-- ============================================================================
CREATE TABLE IF NOT EXISTS control_proposals (
    proposal_id TEXT PRIMARY KEY,
    proposed_by TEXT NOT NULL DEFAULT 'gw_chief',
    action_type TEXT NOT NULL CHECK(action_type IN (
        'SET_SUBPROBLEM_STATE',
        'AUTHORIZE_EARLY_HANDOFF',
        'AMEND_RULING_DRAFT',
        'AUTHORIZE_PARTIAL_DELIVERY'
    )),
    target_id TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    rationale_md TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING_HUMAN'
        CHECK(status IN ('PENDING_HUMAN', 'APPROVED_EXECUTED', 'REJECTED', 'EXPIRED')),
    approved_by_source TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

-- ============================================================================
-- 23. 子题活体综述地图版本表 (subproblem_living_surveys，<=1500 字硬限) [M2]
--     由零外网 library_chronicler 维护，仅收已验真 L3/L2、悬赏缺口与可用仪器表
-- ============================================================================
CREATE TABLE IF NOT EXISTS subproblem_living_surveys (
    survey_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL REFERENCES subproblem_runtime_state(question_id),
    revision INTEGER NOT NULL,
    sec1_baseline_and_instruments_md TEXT NOT NULL,
    sec2_l3_lemma_tree_md TEXT NOT NULL,
    sec3_avoidance_radar_md TEXT NOT NULL,
    sec4_open_lemma_gaps_md TEXT NOT NULL,
    total_chars INTEGER NOT NULL CHECK(total_chars <= 1500),
    trigger_reason TEXT NOT NULL DEFAULT 'MANUAL',
    created_at TEXT NOT NULL,
    UNIQUE(question_id, revision)
);
CREATE INDEX IF NOT EXISTS idx_living_surveys_q_rev ON subproblem_living_surveys(question_id, revision DESC);

-- ============================================================================
-- 24. 波次圆桌对抗会议记录表 (wave_conferences，按子题计步触发) [M3]
-- ============================================================================
CREATE TABLE IF NOT EXISTS wave_conferences (
    conference_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL REFERENCES subproblem_runtime_state(question_id),
    wave_no INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'ASSEMBLING' CHECK(status IN (
        'ASSEMBLING', 'ROUND_1_CRITIQUE', 'ROUND_2_REBUTTAL', 'ADJUDICATING', 'COMPLETED'
    )),
    participant_nodes_json TEXT NOT NULL,          -- 参会节点及其已封存 companion_session_id 列表
    critiques_ledger_json TEXT NOT NULL DEFAULT '[]',
    verifier_session_id TEXT NOT NULL DEFAULT '',
    verdict_json TEXT,                             -- PROTECT / HIBERNATE / SPAWN_SYNTHESIS / DISCRIMINATOR
    synthesis_budget_nodes INTEGER NOT NULL DEFAULT 2,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(question_id, wave_no)
);

-- ============================================================================
-- 25. 排雷聚合只读视图 (v_library_avoidance_radar，不改变 L3/L2 底层口径) [M1]
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
```

### 二点一、现有表增量列与封存硬触发器（安全 `ALTER TABLE`）

1. **`lineage_nodes`** 新增列：
   - `companion_session_id TEXT NOT NULL DEFAULT ''`（确定性 `gw-comp-<node_id>`，供 DSH 按需水合）
   - `briefing_sealed_at TEXT`（`70%` 交接封存时间戳）
   - `secondary_donor_node_id TEXT`（双供体合体支线次供体节点 ID）
   - `control_state TEXT NOT NULL DEFAULT 'AUTO_RUNNING'`
   - `control_generation INTEGER NOT NULL DEFAULT 1`
   - `personal_turn_active INTEGER NOT NULL DEFAULT 0`
   - `human_modified INTEGER NOT NULL DEFAULT 0`
   - `artifact_dirty_since_last_obs INTEGER NOT NULL DEFAULT 0`
   - `last_reconciled_candidate_sha256 TEXT NOT NULL DEFAULT ''`
   - `last_reconciled_tools_sha256 TEXT NOT NULL DEFAULT ''`
   - `transient_retry_count INTEGER NOT NULL DEFAULT 0`
2. **`internal_research_ledger`** 新增列：
   - `publish_tier TEXT NOT NULL DEFAULT 'BASELINE_UPDATE'`（`BASELINE_UPDATE / VERIFIED_INCREMENTAL`）
   - `verified_spec_revision INTEGER NOT NULL DEFAULT 0`
3. **`project_closure_state`** 新增列：
   - `frozen_delivery_dir_abs_path TEXT NOT NULL DEFAULT ''`
4. **交接包封存不可逆触发器（防圆桌参会后反向涂改本脉交接）**：
   ```sql
   CREATE TRIGGER IF NOT EXISTS trg_nodes_lock_sealed_handoff
   BEFORE UPDATE OF column_a_facts_md, column_b_hypothesis_md, will_md ON lineage_nodes
   WHEN OLD.briefing_sealed_at IS NOT NULL
     AND (
         COALESCE(NEW.column_a_facts_md, '') != COALESCE(OLD.column_a_facts_md, '')
         OR COALESCE(NEW.column_b_hypothesis_md, '') != COALESCE(OLD.column_b_hypothesis_md, '')
         OR COALESCE(NEW.will_md, '') != COALESCE(OLD.will_md, '')
     )
   BEGIN
       SELECT RAISE(ABORT, 'SEALED_HANDOFF_IMMUTABLE');
   END;
   ```

---

## 三、旧库（`v0.2.0-alpha.1`）平滑升级迁移规范

启动 `init_db()` 时单事务幂等执行：
1. 执行现版 `SCHEMA_SQL` 与 v0.3 新增表/视图 `CREATE IF NOT EXISTS`；
2. 逐列检测并对 `lineage_nodes`、`internal_research_ledger`、`project_closure_state` 执行 `ALTER TABLE ADD COLUMN`，并安装 `trg_nodes_lock_sealed_handoff`；
3. 从 `parse0_contract(contract_id='active')` 自动回填 `subproblem_runtime_state`（已存在活跃最新口径 `FULL_GOAL` `L3` 的子题直接回填 `STOPPED_SOLVED`）；
4. 升级验收门禁：`PRAGMA foreign_key_check` 返回空，且旧库可直接插入、读取、续跑快闸门与人工接管。

---

## 四、新增控制面原语契约速查

| 控制面原语 | 鉴权要求 | 核心语义 |
| :--- | :---: | :--- |
| `control_plane/pause_node` / `mark_node_yielded` / `resume_node` / `authorize_early_handoff` | `human_ui` 或人类确认单 | 节点接管停止新回合、记录让权时间、恢复时实时 SHA-256 工件对账与授权提前交接 |
| `control_plane/set_subproblem_state` / `evaluate_subproblem_gates` | `human_ui` / 确定性内核 | 幂等设置子题 `desired_state`，独立结算快闸门停派与慢闸门饱和暂停 |
| `control_plane/claim_runtime_effects` / `complete_runtime_effect` | Node 宿主执行器 | 带租约领单、崩溃按 `external_handle_id` 认领与代数竞态收敛 |
| `control_plane/trigger_living_survey_refresh` / `assemble_wave_conference` | 确定性内核 | 按波次或馆藏累积排单 `library_chronicler` 刷新综述；按子题计步排单 `wave_conferences` |
