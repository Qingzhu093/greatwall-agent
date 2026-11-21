---
name: greatwall-research-loop
description: 长城 Agent V6-Up (v3.0) DSH 极薄事件总线 × Python 31 窄工具 MCP 内核“一委三部 + 科研仪器科 + 双隔离沙箱”通用自主科学发现规程。
---

# 长城 Agent V6-Up (`dsh-greatwall-v6up` v3.0) 通用自主科研核心规程

> **主控入口与防越权红线（强制执行）**：
> 1. **主控会话唯一合法调度入口**是 **`greatwall_orchestrate`（`action: "init" | "start" | "status" | "pause" | "resume" | "stop" | "human_stop" | "intervene"`）**，后台事件池非阻塞运行；
> 2. **严禁主控直连 SQLite `greatwall.db`**（不得用 `sqlite3` / Shell 篡改谱系、学派、盲审或终局状态）；
> 3. **严禁主控代改研究 `worktrees/` 代码或越权覆盖校准集与仪器版本**；
> 4. **严禁使用原生 `subagent` 工具自行派单**（所有角色由外部事件总线以独立无状态短会话或单节点保活伴随调度）。
> 5. **工作区磁盘零过程公文**：严禁任何角色在工作区写出 `HANDOFF.md` / `*_AUDIT.md` / `*_CLOSURE.md` 等审批文件，一切流转只写 SQLite（仅 Stage 3 终局由服务端导出 `<workspace>/final_delivery/` 五件套）。

---

## 一、“3 真相 + 2 视图”与 7 角色沙箱平权矩阵

1. **三真相（SQLite WAL，物理隔离于 `$PLUGIN_DATA/workspaces/<ws_hash>/`）**：
   - **真相 ① `observations`**：仅 `official` / `heavy` 档写入的科学收据（`VALID_PASS / MEASURED_REJECTION / VALID_UNDECIDED / CANDIDATE_ERROR / INSTRUMENT_ERROR / INFRA_ERROR / PENDING_REVALIDATION / SUPERSEDED_REVALIDATED / INCOMPATIBLE`），永久绑定 `(instrument_id, instrument_version)`；高频 `probe` 仅写 `probe_diagnostic_logs`；
   - **真相 ② `lineage_nodes` + `lineage_dead_ends`**：各门派私有实验记录本（由一对一 `lineage_companion` 独占单写；历代全部排除边界永久只追加写入 `lineage_dead_ends`，跨门派物理不可见）；
   - **真相 ③ 中央图书馆物理分两翼**：左翼外藏 `external_literature_cards` (`[R###]`，未复验参考先验，0% 开放) + 右翼内藏 `internal_research_ledger`（`L3_VERIFIED` 含 `POS_THEOREM / NEG_COUNTEREXAMPLE / BARRIER_PROOF` 与 `goal_coverage`；`L2_FAILURE_RECORD` 仅存 `REFUTED / UNRESOLVED_OBJECTION`，工程故障绝不入库）。
2. **两视图**：
   - **视图 ① `lineage_briefings`（`<= 2200` 字定额滚动重压缩看板）**：$\text{Rewrite}_{\le 2200}(\text{旧看板}, \text{最新手记})$；
   - **视图 ② 图书馆两级目录卡**：`query_library_catalog` $\to$ `get_library_entry`。
3. **双隔离沙箱平权**：
   - 探索者（本分支 Worktree）、工造司（`evaluators/` & `skills/`）与盲审官（每次现建独立空白沙箱 `blind_sandbox_<review_id>/`）均按 OS 开放真实平台 Shell（`win32 -> pwsh`, `非win32 -> bash`）；`logistics_coordinator` 与 `supervisory_committee` 物理 `0` 原生工具。

---

## 二、500k 物理时钟与单节点四幕节律

- **单一真时钟**：`pressure_pct = pressure_tokens / 500000`（`0.37` = 185k 触发反思，**无 `eval_count` 前置门槛**；`0.70` = 350k 触发两步清醒交接）。
- **单节点伴随暂停续传**：同一探索节点内复用同一个 `lineage_companion` 会话依次承接 `PRE_SPAWN -> REFLECT_37 -> HANDOFF_70`，节点完结即随探索者销毁（绝不跨代常驻；断线崩溃支持冷启动抢救 `CRASH_RECOVERY`）。
- **70% 两步交接**：先给清醒探索者最后一轮只读纯文本收官回合亲笔总结并立《科研遗嘱》，退场后由伴随核对客观 Diff 与 `[Obs###]` 独占单写 `submit_node_handoff`。

---

## 三、三阶段生命周期与核心制度

- **Stage 1 (Parse 0)**：人类签发六项启动表单写入 `parse0_contract`（允许 0 `VERDICT` 判定器开局与空 `question_order`）；采编预建 `[R###]`；后勤按提示开枝；监察委核签 `PARSE0_GATE`。
- **Stage 2 (无人值守演化)**：
  - 仪器科统一 `evaluate(artifact, spec, tier)` 三档四态，**判不了绝不判负**（`INSTRUMENT_ERROR/INFRA_ERROR` 零处罚、不进缓存、连续 3 次自动熔断 `UNHEALTHY`），`VERDICT` 注册与升版走独立校准集 100% 回归；
  - 后勤实行分支级 `requires`、无豁免 `branch_count >= 2 && share > 0.50` 聚拢正交打散、`AWAITING_TRIAGE` 禁抢跑硬锁、四轨可核验准入与五车道停滞复苏；
  - 盲审官在独立空白沙箱跑证执行两阶段盲审与三态裁决（`ACCEPT* / REVISE(共用<=2轮) / REFUTED`），默认引用边为 `MOTIVATING_REF`；
  - 监察委遇口径歧义亮 `ALERT_AMBIGUOUS_SPEC` 红灯且维持原口径不停摆。
- **Stage 3 (双段门禁与两步联合核签)**：满足 `FULL`（全题 `FULL_GOAL` L3）或满最短投入时间 `PARTIAL_ON_BUDGET` 或人类控制面真实 `human_stop_requested_at` 触发 `PARTIAL_ON_HUMAN_STOP` $\to$ 采编导出五件套生成 `(delivery_id, delivery_sha256)` 置 `DELIVERY_EXPORTED` $\to$ `library_verifier(STAGE3_FINAL_AUDIT:<delivery_id>)` 核对不夸大边界且复现一致 $\to$ `supervisory_committee` 绑定版本核签 `CLOSURE_GATE(PASSED)` 晋升 `CLOSED_VERIFIED`。
