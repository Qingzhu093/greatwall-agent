---
name: greatwall-research-loop
description: 长城 Agent v0.3.2 科研自主发现主控冷启动与协同规程（10 角色物理分权 × 53 窄工具 × 非阻塞微型论文与三维盲审 × 脉冲同行拼图工作坊 × 360k 四段时钟与 52% 夜科学绿洲 × 常驻 gw-chief 科研总控）。
---

# 长城 Agent `v0.3.2` 启动总控实操规程

> **首先牢记（避免浪费任何一轮）**：
> - **本规程 + `greatwall_orchestrate` 工具参数即为冷启动所需的全部完整指引！**
> - **严禁满硬盘搜索插件安装目录、DSH `asar` 包或插件源码**——底层 10 角色专属提示词、53 窄工具、Git Worktree 与双向隔离沙箱全部由插件内核自动托管。
> - **冷启动角色分工**：常规会话（如 `standard` / `ptc`）可通过 `greatwall_orchestrate` 完成 `init -> start`；启动后的日常科研讨论、审码、发起院内专题文献综述（`request_internal_survey`）、调整运行安排（优先级/分支上限/停新派/到期恢复）、撤编挂起、发导师便签、带完整蓝图种枝与高危提案签字，统一通过常驻 **「长城 · 科研总控 (`gw-chief`)」** 或右侧「长城科研指挥舱」进行。

---

## 一、主控唯一冷启动入口与 `v0.3.2` 权限边界（强制执行）

1. **`greatwall_orchestrate` 仅开放 4 个薄动作**：
   - `init`：签署 Parse 0 启动契约；
   - `start`：锁定显式模型并拉起非阻塞后台事件池；
   - `status`：只读查询全院轻量态势骨架（每子题一行核心状态，绝不倾倒长原文）；
   - `stop`：停止事件池并释放活跃子会话。
   - **已废除旧版动作**：`greatwall_orchestrate` **不再提供 `pause`、`resume`、`human_stop`、`abort_node`、`sync_rulings`**，严禁尝试调用，否则会被权限门禁直接拒止。
2. **已废除扫盘自动升版暗门；日常运维直执与宪章正门清晰分层**：
   - 严禁靠手写 `rulings/` 文件触发静默升版；
   - **日常运行安排直执**：在 `gw-chief` 会话中人类当面下令，总控可直接落库执行运行安排（主次优先级、`NO_NEW_DISPATCH`、分支上限、到期自动恢复）、分支撤编/挂起/接管、发导师便签与完整蓝图种枝，并返回四态回执；
   - **4 类宪章正门确认单**：仅改题升版（`AMEND_RULING_DRAFT`）、部分结题（`AUTHORIZE_PARTIAL_DELIVERY`）、推进新纪元（`ADVANCE_EPOCH`，在线归档旧库并可选继承外藏文献与健康仪器）与后台圆桌拍板（`APPROVE_WAVE_VERDICT`，支持 `CONVERGE_FULL_COMPOSITE` 组合完备通关与 `CONVERGE_SATURATED` 饱和止盈自动解锁后续 `question_order` 子题）需经确认单显式签字。
3. **`v0.3.2` 核心科研自治节拍（由插件后台自动托管）**：
   - **单班岗 `360k` 四段节拍**：`0%` 伴随精编看板（`<=3600` 字）$\to$ `37%` 11 类外部专家元反思（含 `Research Taste` 科研品味，解锁内藏与院内专题 `survey`）$\to$ `52%` 停码夜科学绿洲（2 回合宿主只读锁 + `submit_holiday_bet` 可证伪赌注）$\to$ `70%` 清醒交班与默认非阻塞微型论文投稿（`manuscript_submissions`，观测自带 `frozen_code_snapshot_path` 快照解耦）。
   - **反路灯三维盲审与脉冲同行工作坊**：空白沙箱两阶段审定 `Rigor / Novelty / Significance`，低重要性成果物理分流至 `MARGINAL_NOTE`；波次脉冲会议由封存伴随代表点对点排雷搭桥，三阶段执行器先休眠腾槽再建双供体合体与双模收敛。
3. **显式模型绑定硬门禁**：`start` 自动继承当前主控模型（或显式传 `provider` / `model`），解析失败直接拒启 `MISSING_MODEL_BINDING`。
4. **物理越权红线**：
   - 严禁直连/篡改 SQLite `greatwall.db`、代改 `worktrees/` 或覆盖 `evaluators/`；
   - 严禁使用原生 `subagent` 工具自行派单（全院 10 角色由插件外部事件池调度）；
   - 工作区磁盘**零过程公文**：严禁手写 `HANDOFF.md` / `*_AUDIT.md` 等过程文档，仅 Stage 3 终局由服务端导出 `<workspace>/final_delivery/` 五件套。

---

## 二、Stage 1 (Parse 0) 标准冷启动流程（4 步到位）

当人类给出科研/数模课题要求按长城启动时，**按以下 4 步推进**：

1. **第 1 步：读题与公开资料就位**
   - 检查工作区里的题面文档（PDF/DOCX/Markdown）与数据目录（如 `inputs/`、`data/`、`附件/`）。
   - 若人类要求先将 PDF/DOCX 转为 Markdown，先在工作区公开目录整理好；默认顶层公开文档及 `inputs/`、`data/`、`附件/` 会在派单与盲审时自动只读挂载到各分支 `inputs/`。
2. **第 2 步：拟定《Parse 0 六项启动表单》并与人类对齐确认**
   向人类清晰呈现以下 6 项草案，获确认后再落盘：
   - **① 课题总目标与明确完成判据**（`goal_and_completion_md`）：每问做到什么程度算 `FULL_GOAL`；
   - **② 必答子题与推进顺序**（`subquestions` 如 `["Q1","Q2","Q3"]`，可选 `question_order`）；
   - **③ 初始科研仪器清单**（`initial_instruments`）：无现成脚本可传 `[]`（由工造司在 Stage 1 锻造），已有脚本则传 `[{ instrument_id, question_id, instrument_type, script_rel_path, description }]`；
   - **④ 种子方法学派**（`seed_families`）：可传 `[]` 或 `[{ family_id, question_id, mechanism_signature }]`；
   - **⑤ 总预算与最短投入窗口**（`total_budget` 如 `{"max_total_handoffs": 40, "max_official_evals": 120}`，`min_commitment_window_sec` 默认 `0`）；
   - **⑥ 自主档位与交付规范**（`autonomy_mode`: `"WAVE_CONFIRM"` 默认波次确认 / `"AUTOPILOT"` 夜间巡航；`delivery_spec_md`）。
3. **第 3 步：调用 `init` 落盘 Parse 0 契约**
   - 调用 `greatwall_orchestrate(action="init", workspace_root="<绝对路径>", goal_and_completion_md=..., subquestions=..., ...)`。
4. **第 4 步：调用 `start` 启动后台事件池并交接退场**
   - 调用 `greatwall_orchestrate(action="start", workspace_root="<绝对路径>")`。
   - 收到 `started: true` 后，**立即向人类简明汇报启动成功、绑定模型与当前阶段，并引导人类后续打开右侧「长城科研指挥舱」面板或点击打开「长城 · 科研总控 (`gw-chief`)」进行日常查账、审阅提案与暂停接管**——启动总控无需原地轮询等待。
