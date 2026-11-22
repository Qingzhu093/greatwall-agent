---
name: greatwall-research-loop
description: 长城 Agent V6-Up (v3.0) DSH 极薄事件总线 × Python 32 窄工具 MCP 内核“一委三部 + 科研仪器科 + 双向隔离沙箱”通用自主科学发现规程。
---

# 长城 Agent V6-Up (`dsh-greatwall-v6up` v3.0) 主控实操规程

> **首先牢记（避免浪费任何一轮）**：
> - **本规程 + `greatwall_orchestrate` 工具参数即为你在主控会话所需的全部完整指引！**
> - **严禁满硬盘搜索插件安装目录、DSH `asar` 包或插件源码**——底层 7 角色专属提示词、32 窄工具、工作树与双向隔离沙箱全部由插件内核自动托管，无需主控去翻查插件源码。
> - 如需查看当前工作区运行状态，直接调用 `greatwall_orchestrate(action="status", workspace_root="<绝对路径>")`（在 `ptc` 模式下即 `tools.greatwall_orchestrate(...)`）。

---

## 一、主控唯一入口与防越权红线（强制执行）

1. **主控唯一合法调度入口**：`greatwall_orchestrate`（`action: "init" | "start" | "status" | "pause" | "resume" | "stop" | "human_stop" | "abort_node"`），后台事件池非阻塞运行。
2. **禁止运行时喊话纠偏**：严禁向运行中子会话广播 `steer`；如需澄清题意、追加时间截断或补充规则，采用确定性四步：**`pause` → 将《补充裁决文档》写入工作区 `rulings/` 目录（如 `rulings/ruling_01.md`）→（仅对需重跑的旧口径节点调 `abort_node`）→ `resume`**（插件自动递增 `spec_revision` 并同步给新派节点与治理层）。
3. **显式模型绑定硬门禁**：`start` 自动继承主控当前模型（或显式传 `provider`/`model`），解析失败直接拒启 `MISSING_MODEL_BINDING`，绝不静默跌落未授权渠道。
4. **物理越权红线**：
   - 严禁主控直连/篡改 SQLite `greatwall.db`；
   - 严禁主控代改探索者 `worktrees/` 代码或越权覆盖 `evaluators/` 与校准集；
   - 严禁使用原生 `subagent` 工具自行派单（所有 7 角色由插件外部事件池调度）；
   - 工作区磁盘**零过程公文**：严禁手写 `HANDOFF.md` / `*_AUDIT.md` / `*_CLOSURE.md` 等审批文档，一切科研流转只写 SQLite（仅 Stage 3 终局由服务端自动导出 `<workspace>/final_delivery/` 五件套）。

---

## 二、Stage 1 (Parse 0) 主控标准启动流程（4 步到位）

当人类给出一个科研/建模/理论课题要求按长城插件启动时，**立刻按以下 4 步推进，不要去翻插件目录**：

1. **第 1 步：读题与公开资料就位**
   - 检查当前工作区文件（如题面 PDF/DOCX/附件数据）。
   - 若人类要求先将 PDF/DOCX 转为无损 Markdown/配图，先在工作区公开目录（如 `inputs/` 或 `source_materials/`）整理好无损公开材料；若人类有硬性规则补充（如文献时间截断、误差模型约定、格式规范），整理为工作区 `rulings/ruling_00_parse0.md`。
   - 工作区顶层文档及 `inputs/`、`source_materials/`、`data/`、`rulings/`、`附件/` 目录会在派单时**自动只读挂载到每个探索者与盲审官的 `inputs/` 目录**，无需人工复制。
2. **第 2 步：拟定《Parse 0 六项启动表单》并与人类对齐签发**
   向人类清晰呈现以下 6 项草案，待人类确认/修订后方可落盘（遇题意歧义必须在此步先问清）：
   - **① 课题总目标与明确完成判据**（`goal_and_completion_md`）：每问做到什么程度算 `FULL_GOAL`；
   - **② 必答子题与推进顺序**（`subquestions` 如 `["Q1","Q2","Q3"]`，可选 `question_order`）；
   - **③ 初始科研仪器清单**（`initial_instruments`）：已有脚本则填路径/角色；若题目需要先造模拟器/验证器，可先留空数组 `[]` 或写明待建需求，并在 `goal_and_completion_md` 注明由工造司在 Stage 1/2 优先锻造；
   - **④ 种子方法学派提示**（`seed_families`）：可给若干初始思路方向，也可留空 `[]` 由后勤动态建档；
   - **⑤ 总预算与最短投入窗口**（`total_budget` 如 `{"max_total_handoffs": 40, "max_official_evals": 120}`，`min_commitment_window_sec` 默认 `0`）；
   - **⑥ 最终交付物形态规范**（`delivery_spec_md`）：如国赛标准论文结构、复现脚本、图表与禁止自吹边界。
3. **第 3 步：落盘 Parse 0 契约**
   - 获人类确认后，调用 `greatwall_orchestrate(action="init", workspace_root="<绝对路径>", goal_and_completion_md=..., subquestions=..., question_order=..., initial_instruments=..., seed_families=..., total_budget=..., min_commitment_window_sec=..., delivery_spec_md=..., shared_inputs_rel_paths=[...])`。
4. **第 4 步：非阻塞启动后台事件池**
   - 调用 `greatwall_orchestrate(action="start", workspace_root="<绝对路径>")`（自动锁定主控模型与自适应窗口 $W = \min(500\text{k}, \text{model\_window})$）。
   - 启动后向人类简明回报 `started` 状态、绑定模型与当前阶段；后续由后台事件池全自动运行，主控仅按人类指令调 `status` / `pause` / `resume` / `abort_node` / `human_stop` / `stop`。

---

## 三、底层自动托管体系速览（供主控读懂 `status` 汇报）

1. **“3 真相 + 2 视图”与 7 角色双向隔离沙箱**：
   - **三真相**（SQLite WAL 隔离于 `$PLUGIN_DATA/workspaces/<ws_hash>/greatwall.db`）：① `observations`（`official/heavy` 科学收据，永久绑定仪器版本；高频 `probe` 仅入 `probe_diagnostic_logs`）；② `lineage_nodes` + `lineage_dead_ends`（门派私有手记与只追加排除边界，由一对一 `lineage_companion` 独占单写）；③ 中央图书馆两翼——左翼外藏 `[R###]`（0% 开放，客观缺失时走 `UNAVAILABLE_REPORT` 结案为 `CLOSED_UNAVAILABLE` 严禁造伪卡）+ 右翼内藏 `L3_VERIFIED` / `L2_FAILURE_RECORD`（37% 后按需拉取）。
   - **两视图**：① `lineage_briefings`（`<= 2200` 字滚动看板）；② 图书馆目录卡（`query_library_catalog` → `get_library_entry`）。
   - **双向隔离沙箱**：探索者（本分支 worktree + 只读 `inputs/`）、工造司（`evaluators/` & `skills/`）与盲审官（现建空白沙箱 `blind_sandbox_<review_id>/`，按手稿绑定 `spec_revision` 只读挂载 `inputs/`）均按 OS 开放真实 Shell（`win32->pwsh`, `非win32->bash`），物理隔离 `greatwall.db` / `_hidden_*` / 他脉 worktree；后勤与监察委物理 `0` 原生工具。
2. **自适应真时钟与单节点四幕节律**：
   - `pressure_pct = pressure_tokens / effective_context_window`，其中 $W = \min(500{,}000,\ \text{model\_physical\_window})$；`0.37` 解锁元反思与内藏拉取（无 `eval_count` 门槛），硬跑至 `0.70` 触发两步清醒交接（先持久化探索者亲笔 `will_md` 至 SQLite 再销毁探索者，随后伴随核验 Diff 与 `[Obs###]` 独占单写 `submit_node_handoff`）。
   - 同一探索节点内复用单会话伴随（`PRE_SPAWN -> REFLECT_37 -> HANDOFF_70`），节点完结即随探索者销毁。
3. **三阶段门禁**：
   - **Stage 1**：`init` 签署 Parse 0 → 后台**固定统一拉起一次 `works_engineer`** 核查初始仪器落标 `stage1_works_checked=1` → 采编预建 `[R###]` → 后勤开枝 → 监察委核签 `PARSE0_GATE` 进入 Stage 2。
   - **Stage 2**：仪器科三档四态 `evaluate(artifact, spec, tier)`（判不了绝不判负，校准集 100% 回归后注册并自动 Push 给对应子题探索者）+ 单条待办项级 2 次无进展熔断器 + 后勤分支级 `requires` / `>=2 && >50%` 聚拢正交打散 / `AWAITING_TRIAGE` 防抢跑 + 空白沙箱两阶段盲审（旧口径禁标最新 `FULL_GOAL`）+ 监察委口径歧义红灯不停摆。
   - **Stage 3**：满足 `FULL` / `PARTIAL_ON_BUDGET` / 控制面真实 `PARTIAL_ON_HUMAN_STOP` → 采编导出 `<workspace>/final_delivery/` 五件套生成 `(delivery_id, delivery_sha256)` → 盲审官终核不夸大且复现一致 → 监察委绑定版本核签 `CLOSURE_GATE(PASSED)` 晋升 `CLOSED_VERIFIED`。
