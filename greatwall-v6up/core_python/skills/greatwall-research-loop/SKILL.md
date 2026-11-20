---
name: greatwall-research-loop
description: 长城 Agent V6-Up (v2.2) DSH 外部无状态编排控制面 × Python 31 窄工具 MCP 内核“一委三部”科研攻关核心规程。
---

# 长城 Agent V6-Up (`dsh-greatwall-v6up` v2.2) “一委三部”科研攻关核心规程

> **主控入口与防越权红线（强制执行）**：
> 1. **主控会话唯一合法调度入口**是 **`greatwall_orchestrate`（`action: "start" | "status" | "pause" | "resume" | "stop" | "intervene"`）**，后台异步事件池启动后会在 1 秒内立即返回，人类可直接点击左侧栏工作区下各节点独立会话对话、或通过 `intervene` 下发纠偏指令；
> 2. **严禁主控直连 SQLite `greatwall.db`**（不得用 `sqlite3` / `pwsh` 手写 SQL 改写谱系、学派或门禁状态）；
> 3. **严禁主控读写 `worktrees/` 求解代码或篡改 `evaluators/` 验证钩子/容差**（所有代码研发与钩子升级均由独立无状态工作节点与工造司完成）；
> 4. **严禁使用原生 `subagent` 工具自行派发子代理**（所有角色统一由插件基于独立 Preset 与同工作区会话调度）。

> **架构铁律**：全系统采用 **DSH (`0.2.2-rc.3`) `ctx.agents.create()` 同工作区独立会话 × Python 31 单一职责窄工具 MCP + SQLite WAL 底座**，彻底取消 `dsh-subagent` 限制、取消中心化常驻 `ROOT` 官僚、取消一切过程 `.md` 公文落盘（工作区零 `HANDOFF.md` / `*_AUDIT.md` / `*_CLOSURE.md` / `REFLECTION_*.md`）。

---

## 一、7 大独立无状态角色与极简数据底座（3 真相 + 2 视图）

1. **三个唯一真相（只存 SQLite WAL + 分支 Git Worktree）**：
   - **真相 ① `observations`**：按子题隔离评估产出收据（`VALID / EXECUTION_ERROR / MEASURED_NON_IMPROVEMENT / INCONCLUSIVE / PENDING_REVALIDATION / INVALIDATED`），绑定 `(question_id, domain_hook_sha256, stage_a_artifact_path)`；
   - **真相 ② `lineage_nodes`（原 `L1` 直接合一）**：各门派私有实验记录本（`<2000` 字 A/B 双栏手记、遗嘱、`sanitized_code_diff_md`、`worktree_abs_path` 与 `Retained Candidate` 物理快照路径），严禁跨门派读取；零实测崩溃节点记入 `scratch_log_json` 不污染主谱系与看板；
   - **真相 ③ 中央图书馆物理分两翼**：
     - 左翼外藏 `external_literature_cards` (`[R###]`)：由 `library_surveyor` 写入，`0%` 起全程开放 Pull；
     - 右翼内藏 `internal_research_ledger` (`L3_VERIFIED` 黄金账本 + `L2_FAILURE_RECORD` 失败雷达)：由零磁盘工具的 `library_verifier` 通过两阶段盲审唯一入 `L3`，在 Stage 1/2 `REJECT`、Level 2 修补满 3 次或 Level 4a 阻碍证明时同事务自动入 `L2`。
2. **两个派生视图**：
   - **视图 ① 谱系状态看板 (`Briefing`, `<= 2200` 字)**：由 `lineage_companion` 在探索者出生前按五段定额预算（`200 / 400 / 350 / 650 / 400`）增量合成，严禁 `[:2000]` 硬切片；
   - **视图 ② 图书馆两级目录卡**：`query_library_catalog` $\to$ `get_library_entry`（`0–37%` 自动屏蔽内藏、`37%` 解锁后开放全馆）。
3. **7 大无状态角色工具分工（严格执行 31 个唯一授权窄工具）**：
   - `explorer` (5 MCP + 本分支 `read/write/edit/glob/grep/pwsh` 受 OS 读隔离 + Guard 约束)：`run_isolated_eval`, `query_library_catalog`, `get_library_entry`, `request_literature_survey`, `read_lineage_graph`；
   - `lineage_companion` (4 MCP + 只读工作树)：`get_companion_context`, `save_lineage_briefing`, `record_reflection_and_unlock_pull`, `submit_node_handoff`（独占 DAG 单写权）；
   - `logistics_coordinator` (5 MCP，零科研代码写权)：`get_logistics_dashboard`, `register_method_family`, `triage_node`, `fork_branch`, `dispatch_stagnation_five_lanes`；
   - `library_surveyor` (3 MCP + 网络/PDF/读工具)：`get_survey_requests`, `publish_external_literature_card`, `export_stage3_final_delivery`；
   - `library_verifier` (5 MCP，**物理零磁盘、零网络、零终端工具**)：`get_blind_manuscript`, `submit_stage1_blind_ledger`, `get_unblinded_manuscript_and_peers`, `submit_stage2_unblind_verdict`, `propose_salvaged_lemma`；
   - `works_engineer` (5 MCP + 评估器工作区)：`get_works_engineering_queue`, `register_question_domain_hook`, `upgrade_hook_with_rqgm_gate`, `recompute_stage_b_only`, `update_skill_ledger`；
   - `supervisory_committee` (4 MCP，超然只读零公文)：`get_supervisory_audit_snapshot`, `check_stage2_closure_gate`, `record_compliance_check`, `register_saved_graph_query`。

---

## 二、500,000 Token 真实时钟与回合间隙顺序反思

- **统一计算公式**：`pressure_pct = pressure_tokens / 500000`（`37% = 185,000` 且 `eval_count >= 1`；`70% = 350,000`）。
- **回合间隙 `37%` 顺序反思**：`run_isolated_eval` 先返回成绩单并标记回合收敛（`concludesTurn`），控制面于回合间隙暂停探索者、抽取黑匣子轨迹与夜科学 `1–28` 随机 `1–2` 题候选推送给 `lineage_companion(REFLECT_37)` 完成 `<= 2` 轮（每轮 `<= 300` 字）问答并调 `record_reflection_and_unlock_pull` 当场置位 `first_reflection_unlocked = 1`，随后放行探索者继续 `37%–70%` 攻坚。

---

## 三、四阶段科研流水线与结题硬锁

- **Stage 1（`Parse 0` 基建）**：`works_engineer` 为每一子题 `Q1..Qn`（含纯理论与仿真）注册 `evaluators/hooks/hook_<question_id>.py` 与隔离 `baselines/baseline_<question_id>.py`（误差 `< 5.0%`）；`library_surveyor` 补充 `[R###]`；`logistics_coordinator` 登记每题 `>= 2` 互斥学派并在 `max_concurrent_workers = 6`（硬上限 `10`）下公平派单；`supervisory_committee` 核签 `STAGE1_GATE`。
- **Stage 2（并行演化）**：探索者-伴随双人组按统一时间轴推进；`triage_node` 驱动四级分诊与 `Retained Candidate` 物理快照保存/恢复；`library_verifier` 两阶段纯 DB 盲审及异会话 `Auditor` 打捞；`works_engineer` 执行 `RQGM`（真值锚点实跑优先）与 `DEPENDS_ON` 局部同事务重评（零跨题连坐）。
- **Stage 3（收官交付 — 死守 `L3_VERIFIED >= 1` 硬锁）**：`check_stage2_closure_gate()` 全题通过后，`library_verifier` 任 `Comparator` 择优各题 `L3_VERIFIED` -> `library_surveyor` 任 `Formal Writer` 调 `export_stage3_final_delivery` 导出 `<workspace>/final_delivery/` 五件套 -> `library_verifier` + `supervisory_committee` 逐行核对收据后正式结项。
