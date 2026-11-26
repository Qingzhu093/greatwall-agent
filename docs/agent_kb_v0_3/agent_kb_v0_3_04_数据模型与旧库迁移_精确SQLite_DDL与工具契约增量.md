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
-- 20. 子题级运行时调度与三道停工锁状态表 (subproblem_runtime_state)
-- ============================================================================
CREATE TABLE IF NOT EXISTS subproblem_runtime_state (
    question_id TEXT PRIMARY KEY,
    contract_id TEXT NOT NULL DEFAULT 'active' REFERENCES parse0_contract(contract_id),
    desired_state TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK(desired_state IN ('ACTIVE', 'PAUSED', 'CLOSED')),
    dispatch_state TEXT NOT NULL DEFAULT 'DISPATCHING'
        CHECK(dispatch_state IN (
            'DISPATCHING',       -- 正常派工
            'STOPPED_SOLVED',    -- 锁一：最新生效口径 FULL_GOAL 通关解或全局不可能证明
            'PAUSED_SATURATED',  -- 锁二：满最低投入窗且大外环确认明确缺口穷尽，待人类拍板
            'PAUSED_HUMAN',      -- 人类主动暂停
            'PAUSED_BLOCKED',    -- 锁三：预算保险丝触发、全员阻塞(ALL_BRANCHES_BLOCKED)、口径歧义或熔断阻断
            'CLOSED'             -- 已随终局结项关闭
        )),
    active_spec_revision INTEGER NOT NULL DEFAULT 0,        -- 本子题当前生效口径版本（改 Q1 时不连坐 Q2）
    solved_entry_id TEXT REFERENCES internal_research_ledger(entry_id),
    solved_at_spec_revision INTEGER,
    baseline_entry_id TEXT REFERENCES internal_research_ledger(entry_id),
    baseline_metric_value REAL,
    metric_direction TEXT CHECK(metric_direction IN ('HIGHER_BETTER', 'LOWER_BETTER', 'QUALITATIVE') OR metric_direction IS NULL),
    started_at TEXT NOT NULL DEFAULT '',
    min_commitment_sec INTEGER NOT NULL DEFAULT 0,          -- 最低投入时间窗（秒），未满窗前禁由大外环语义暂停
    question_token_budget INTEGER NOT NULL DEFAULT 0,       -- 硬 Token 预算保险丝（0 表示未设子题单独上限）
    spent_tokens INTEGER NOT NULL DEFAULT 0,
    completed_waves INTEGER NOT NULL DEFAULT 0,             -- 已完成宏观大外环波次
    max_waves INTEGER NOT NULL DEFAULT 0,                   -- 硬波次天花板（0 表示未设上限）
    completed_nodes_since_last_l3 INTEGER NOT NULL DEFAULT 0,   -- 仅作大外环硬账本观测统计，绝不单方面触发停工
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
-- 24. 高危控制操作与人类自由指令确认单 (control_proposals，Superagent/大外环整理 -> 人类一键确认)
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
        'SET_AUTONOMY_MODE'
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

-- ============================================================================
-- 25. 子题活体综述导览表 (subproblem_living_surveys，<=1500 字高密度导览索引)
--     由零外网 library_chronicler 维护，仅收已验真 L3/L2、可用仪器与 Top Explicit Gaps 索引
-- ============================================================================
CREATE TABLE IF NOT EXISTS subproblem_living_surveys (
    survey_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL REFERENCES subproblem_runtime_state(question_id),
    revision INTEGER NOT NULL,
    sec1_baseline_and_instruments_md TEXT NOT NULL,
    sec2_l3_lemma_tree_md TEXT NOT NULL,
    sec3_avoidance_radar_md TEXT NOT NULL,
    sec4_explicit_gaps_md TEXT NOT NULL,           -- Top 客观缺口摘要与高优悬赏编号索引（全量悬赏见 open_lemma_gaps）
    total_chars INTEGER NOT NULL CHECK(total_chars <= 1500),
    trigger_reason TEXT NOT NULL DEFAULT 'MANUAL',
    created_at TEXT NOT NULL,
    UNIQUE(question_id, revision)
);
CREATE INDEX IF NOT EXISTS idx_living_surveys_q_rev ON subproblem_living_surveys(question_id, revision DESC);

-- ============================================================================
-- 26. 波次圆桌对抗会议记录表 (wave_conferences，按子题计步触发)
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
    participant_nodes_json TEXT NOT NULL,          -- 参会节点及其已封存 companion_session_id（含慢分支上代快照标记）
    critiques_ledger_json TEXT NOT NULL DEFAULT '[]',
    minutes_md TEXT NOT NULL DEFAULT '',           -- 第 2 拍圆桌交锋纪要与争议焦点
    linked_survey_id TEXT REFERENCES subproblem_living_surveys(survey_id),  -- 第 3 拍刚刷新的子题总览版本
    chair_session_id TEXT NOT NULL DEFAULT '',
    verdict_json TEXT,                             -- OPEN_NEW_BRANCH / PROTECT / SPAWN_SYNTHESIS / HIBERNATE / DISCRIMINATOR / PAUSE_FOR_HUMAN
    synthesis_budget_nodes INTEGER NOT NULL DEFAULT 2,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(question_id, wave_no)
);

-- ============================================================================
-- 27. 排雷聚合只读视图 (v_library_avoidance_radar，不改变 L3/L2 底层口径)
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

### 二点一、现有表增量列、枚举升级与封存硬触发器

1. **`parse0_contract`** 新增列（安全 `ALTER TABLE ADD COLUMN`）：
   - `autonomy_mode TEXT NOT NULL DEFAULT 'WAVE_CONFIRM' CHECK(autonomy_mode IN ('WAVE_CONFIRM','AUTOPILOT'))`（`'WAVE_CONFIRM'` 波次确认档 / `'AUTOPILOT'` 夜间巡航档）
2. **`lineage_nodes`** 新增列（安全 `ALTER TABLE ADD COLUMN`）：
   - `branch_kind TEXT NOT NULL DEFAULT 'PURE' CHECK(branch_kind IN ('PURE','PROTECTED','SYNTHESIS','HUMAN_SEEDED'))`
   - `protection_generations_left INTEGER NOT NULL DEFAULT 2`（成长保护期剩余班次，保护期内禁止大外环裁撤）
   - `branch_budget_nodes_left INTEGER`（非空时为合体/定向验证支线的有限预算班次，归零后触发转正或销毁）
   - `companion_session_id TEXT NOT NULL DEFAULT ''`（确定性 `gw-comp-<node_id>`，供 DSH 按编号从硬盘按需重新打开）
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
3. **`internal_research_ledger`** 新增列：
   - `publish_tier TEXT NOT NULL DEFAULT 'BASELINE_UPDATE'`（`BASELINE_UPDATE / VERIFIED_INCREMENTAL`）
   - `verified_spec_revision INTEGER NOT NULL DEFAULT 0`
4. **`project_closure_state`** 新增列：
   - `frozen_delivery_dir_abs_path TEXT NOT NULL DEFAULT ''`
5. **`works_engineering_queue` 放开 `'DISCRIMINATOR'` 枚举（解决现版 `CHECK` 约束冲突）**：
   - 现版 `db_schema.py` 的 `works_engineering_queue.ticket_type` 仅允许 `'INSTRUMENT_ERROR','PAIN_POINT','DUPLICATE_TOOL','EXPLOIT'`；
   - `v0.3` 需将其 `CHECK` 约束升级为 `ticket_type IN ('INSTRUMENT_ERROR','PAIN_POINT','DUPLICATE_TOOL','EXPLOIT','DISCRIMINATOR')`（旧库通过 SQLite 标准重建表迁移完成，详见第三节）。
6. **交接包封存不可逆触发器（锁死时间戳、两栏正文、观测清单与候选路径）**：
   ```sql
   CREATE TRIGGER IF NOT EXISTS trg_nodes_lock_sealed_handoff
   BEFORE UPDATE OF briefing_sealed_at, column_a_facts_md, column_b_hypothesis_md, will_md, bound_obs_ids_json, candidate_rel_path ON lineage_nodes
   WHEN OLD.briefing_sealed_at IS NOT NULL
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

## 三、旧库（`v0.2.0-alpha.1`）平滑升级迁移与 `v0.3` 单真源重构要点

启动 `init_db()` 时幂等执行：
1. 执行现版 `SCHEMA_SQL` 与 v0.3 新增表/视图 `CREATE IF NOT EXISTS`；
2. 逐列检测并对 `parse0_contract`、`lineage_nodes`、`internal_research_ledger`、`project_closure_state` 执行 `ALTER TABLE ADD COLUMN`，并安装（或先 `DROP` 再重建）`trg_nodes_lock_sealed_handoff`；
3. **回填既有 `L3` 条目的真实核验口径**：执行 `UPDATE internal_research_ledger SET verified_spec_revision = COALESCE((SELECT r.spec_revision FROM review_queue r WHERE r.review_id = internal_research_ledger.verified_review_id), 0) WHERE verified_spec_revision = 0 AND verified_review_id IS NOT NULL`，避免老库 `v3` 过审成果被误标为 `v0`；
4. **检测并幂等重建 `works_engineering_queue`**：检查 `sqlite_master` 中 `works_engineering_queue` 的 `sql` 定义，若不包含 `'DISCRIMINATOR'`，则在事务外短暂切 `PRAGMA foreign_keys = OFF`、单事务内执行「创建 `works_engineering_queue_v3`（含 `'DISCRIMINATOR'` 约束） $\to$ 全量 `INSERT INTO ... SELECT ...` 拷贝原数据 $\to$ `DROP TABLE works_engineering_queue` $\to$ `ALTER TABLE works_engineering_queue_v3 RENAME TO works_engineering_queue` $\to$ 重建原索引」，随后恢复 `PRAGMA foreign_keys = ON` 并立刻执行 `PRAGMA foreign_key_check`；
5. 从 `parse0_contract(contract_id='active')` 自动回填 `subproblem_runtime_state`（同步每道子题的 `active_spec_revision`，已存在匹配当前生效口径的活跃 `FULL_GOAL` `L3` 的子题直接回填 `STOPPED_SOLVED`）；
6. **`v0.3` 施工必须同步收编的四处 `v0.2` 旧代码真源**（消除新旧两套逻辑打架）：
   - 废除旧的“扫磁盘 `rulings/` 自动升版”暗门，统一由人类确认口径提案触发冻结升版；
   - 全卷结项门禁与子题达标停派复用同一套“当前生效口径 `FULL_GOAL`”查询，且盲审终审在 `BEGIN IMMEDIATE` 写锁内复核最新口径；
   - 局部引理独立送审仅挂冻结快照建审单，不再将来源节点锁成 `PENDING_REVIEW`；
   - 所有写入入口强制校验同子题归属（`question_id` 一致），杜绝跨子题引用。

---

## 四、新增控制面与关键业务原语契约速查

| 原语 / 工具 | 鉴权要求 | 核心语义 |
| :--- | :---: | :--- |
| `control_plane/pause_node` / `mark_node_yielded` / `resume_node` / `authorize_early_handoff` | `human_ui` 或人类确认单 | 节点接管停止新回合、记录让权时间、恢复时实时 SHA-256 工件对账与授权提前交接 |
| `control_plane/set_subproblem_state` / `set_autonomy_mode` / `approve_control_proposal` / `evaluate_subproblem_locks` | `human_ui` / 确定性内核 | 幂等设置子题 `desired_state`、热切换全院自主档位（`WAVE_CONFIRM / AUTOPILOT`）、原子落签 8 类人类提案并独立结算三道停工锁 |
| `chief_get_overview_snapshot` / `chief_trace_entity` / `chief_get_wave_digest` / `chief_preview_impact` / `chief_propose_control_action` | `gw-chief`（Superagent） | 物理零写权只读回忆链（强制 `Inline & Spill` + 内联下一跳 ID）、零副作用影响面/排雷预演，以及唯一结构化提案提交口（含 `human_action` 单问题确认卡） |
| `handback_to_chief` | `explorer`（直连子节点） | 人类直连具体分支时若顺口提出跨分支/全局诉求，原样退回 `gw-chief` 收件箱（经 `NOTIFY_CHIEF` 副作用路由），严守单一授权事实来源 |
| `control_plane/claim_runtime_effects` / `complete_runtime_effect` | Node 宿主执行器 | 带租约领单、崩溃按 `external_handle_id` 认领、+1 人类优先槽调度、`NOTIFY_POLICY_CHANGED` 温和热传播与代数竞态收敛 |
| `submit_stage2_unblind_verdict`（增强） | `library_verifier` | 支持 `ACCEPT_NARROWED` 同事务收编 `L3_VERIFIED(PARTIAL_OR_LEMMA)` + `L2_FAILURE_RECORD`（100% 过 `trg_l3_require_verified_review`）及 `fulfilled_gap_ids` 原子核销唤醒 `LEVEL_4B` 分支 |
| `record_conference_minutes` / `submit_conference_verdict` | `conference_chair` | 第 2 拍落盘交锋纪要切 `SURVEY_REFRESHING`；第 3 拍综述官刷新总览后第 4 拍唤醒同一裁判签发 6 类宏观调整单（半自动模式挂 `PENDING_HUMAN_APPROVAL` + `APPROVE_WAVE_VERDICT` 提案） |
