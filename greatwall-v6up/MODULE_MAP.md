# GreatWall V6-Up 模块地图（MODULE_MAP · `v0.3.2`）

面向人类协作者与后续接手 AI Agent 的一页架构导航：快速定位代码边界、四大工程分层红线与整机验收命令。顶层设计论文见 [`../docs/agent_kb_v0_3/`](../docs/agent_kb_v0_3/)。

---

## 1. Python 核心与单写真相源（`core_python/`）

> **并发与一致性铁律（`v0.3.2`）**：**并发纯只读（`open_ro_connection` + `ro_consistent_tx`）+ 并发纯外部隔离计算（锁外 100% 并行，含观测代码快照冻结与 Stage 3 不可变冻结目录 SHA-256 计算）+ 严格进程级单写者短锁记总账（`_SINGLE_WRITER_LOCK` + `rw_immediate_tx`）+ 持久化事务 Outbox (`runtime_effects`) 并发车道驱动异步副作用**。

| 路径 | 职责 | 禁止放入 / 边界红线 |
| --- | --- | --- |
| `mcp_server/db/` | 模块化数据底座：`enums.py`（全量权威枚举）、`schema_base.py`（核心 19 表）、`schema_v03.py`（v0.3 新增 7 表）、`schema_v031.py`（v0.3.1 `run_arrangements` / `operation_receipts` / `operator_runtime_slots` / `branch_notes` / `project_epochs`）、`schema_v032.py`（院内专题综述与微型论文视图）、`migrations.py`（无损原地迁移 + FTS5 自动重建 + 外键校验） | 禁止直接 `ALTER RENAME` 不开 `PRAGMA legacy_alter_table = ON`；严禁破坏防自审/L3 审核硬触发器 |
| `mcp_server/db_runtime.py` & `db_schema.py` | 真只读连接、进程级单写者锁 `_SINGLE_WRITER_LOCK`、异常安全连接关闭与薄聚合门面 | 写短事务内禁止包含耗时子进程或大目录哈希计算 |
| `mcp_server/tool_registry.py` | **53 窄工具 × 10 角色单一契约源**：`gw_chief`、`explorer`、`lineage_companion`、`logistics_coordinator`、`external_surveyor`、`library_chronicler`、`conference_chair`、`library_verifier`、`works_engineer`、`supervisory_committee` | 严禁 import 业务实现 `tools_*.py` 或 `control_plane/` |
| `mcp_server/greatwall_core_mcp.py` & `control_plane_dispatch.py` | 双池并发 stdio JSON-RPC 2.0 入口（`fast_pool` / `compute_pool`）、`$/cancelRequest` 真取消注册表、53 窄工具与控制面原语分发 | 严禁堆砌 SQL 事务或重复手写工具 Schema |
| `mcp_server/mcp_core_helpers.py` & `mcp_schema_docs.py` | RBAC 鉴权、路径安全、统一回执外壳与 53 工具全量中文 Schema/枚举增强 | 严禁反向依赖 `tools_*.py` 或 `control_plane/` |
| `mcp_server/control_plane/` | 无环单写者子域：`operator_policy`（版本化运行安排与独立槽位账本）、`operator_ops`（日常直执与四态回执）、`epochs`（在线 `sqlite3.backup()` 纪元归档）、`effects_outbox`、`subproblem_locks`、`node_interventions`、`proposals`（4 类宪章正门确认单）、`wave_engine`、`wave_verdict_actions`（锁外准备、三阶段动作、双模收敛）、`context_holiday`、`delivery_freeze`、`blind_sandbox`、`lifecycle_ops`、`workspace_sync`、`snapshot_queries`、`scheduler_rules`、`ui_projection` | 严禁反向 import `tools_*.py`；单文件保持 `<1000` 行；已废除扫盘自动静默升版暗门 |
| `mcp_server/tools_*.py` & `triage_core.py` | 10 角色窄工具实现：`tools_chief`、`tools_explorer_eval` + `tools_explorer_pull`、`tools_companion`（支持确定性续班、非阻塞快照投稿与散会承接）、`triage_core`、`tools_logistics`、`tools_library_roles`（外搜 `external_surveyor` / 综述终稿 `library_chronicler` / 圆桌主席 `conference_chair`）、`tools_verifier` + `tools_verifier_helpers`（Stage 1 `PARTIAL_PASS` + `ACCEPT_NARROWED` + Stage 3 一步终签）、`tools_works`、`tools_supervisory` | 禁止恢复已退役的 `library_surveyor` 与 `dispatch_stagnation_five_lanes`；严禁 `external_surveyor` 访问院内成果 |
| `evaluators/isolated_runner.py` | 三档（`probe`/`official`/`heavy`）四态隔离仪器执行器、校准门禁与 `cancel_event` 实时强杀子进程树 | 严禁向探索者泄露 `_hidden_calibrations/` 或评测源码 |
| `mcp_server/control_plane/observation_artifacts.py` | 在短事务内将已暂存的观测快照绑定到正式观测编号，失败时撤销发布 | 快照复制、哈希与递归清理均在写事务外 |
| `mcp_server/tools_internal_survey.py` | 院内专题请求、Outbox 派发、按范围核验引用和报告结案 | 专题会话只使用院内证据，禁止对外联网 |
| `agents/*.md` & `config.json` | 10 份 v0.3 角色系统提示词与全局参数（弹性锚点卡预算、保护期、圆桌阈值、瞬时退避） | 修改工具名须同步更新对应 `.md`（架构门禁强制校验） |

---

## 2. DSH Cordis 插件层与模块化前端（`dsh_plugin/`）

> **与 DSH `0.2.2-rc.5` 的原生融合**：8 套单源 `cordis.patch.yml` Preset（含独立 `greatwall-chief`）、动态探测 `@deepseek-ai/schemastery` + Standard Schema v1 回退、`ctx.agents.resume` 确定性会话唤醒、`@deepseek-ai/dsh-action-cards` 原生待拍板卡、`ctx.jobs` 暂停清理后台作业、`source.rpcId` 人类插话让权、零第三方依赖前端打包 `client_src/ -> lib/client.js`。

| 路径 | 职责 | 禁止放入 / 边界红线 |
| --- | --- | --- |
| `cordis.patch.yml` & `lib/presets.js` | **单源 8 套 Preset**（覆盖全院 10 角色）：`greatwall-chief`（启用 `dsh-compaction-basic`）、`greatwall-explorer`（严禁开 `pruner`）、`greatwall-verifier`、`greatwall-companion`、`greatwall-works`、`greatwall-external-surveyor`（唯一联网）、`greatwall-chronicler`（零外网）、`greatwall-db-only` | 严禁给 `explorer` 开 `dsh-compaction-tool-result-pruner`；严禁写磁盘 Preset 文件 |
| `lib/index.js` & `lib/config.js` | Cordis 插件极薄装配入口；动态探测 `@deepseek-ai/schemastery`（缺宿主时回退零依赖 Standard Schema v1） | 严禁暴露未消费的假配置旋钮 |
| `lib/runtime/` | 设施运行底座：`instance_lock.js`（`host.lock` 防双活与死 PID 回收）、`worker_slots.js`（`maxWorkers + 1` 人类保留槽）、`transient_retry.js`（429/5xx 指数退避 vs 401/拒答不重试）、`effects_consumer.js`（SQLite Outbox 60s 租约消费与热注入） | 不做科研业务裁决 |
| `lib/sessions/` | `human_takeover.js`（`source.rpcId` 人类插话让权 + 白名单防误判 + `ctx.jobs` 杀残留作业）与 `chief_runtime.js`（弹性字数锚点卡 `min(hardCap, max(400, 180 + 100 * N))`、高信噪比收件箱、原生 `greatwall_proposal` Action Card 注册） | 严禁任何大模型 MCP 工具伪造 `caller: 'human_ui'` |
| `lib/control_service.js` & `lib/orchestrate_tool.js` | 统一控制服务（乐观锁审批幂等、45% 人工接管、自主档位切换）与极简 4 动作 `greatwall_orchestrate` (`init / start / status / stop`) | 严禁绕过 `control_proposals` 直接执行需人类拍板的宪章动作 |
| `lib/orchestrator.js` & `lib/orchestrator/` | 后台事件池主控（已瘦身至 ~700 行）+ 6 个编排子域：`runtime_port.js`、`circuit_breaker.js`、`dispatch_stage1.js`、`dispatch_stage2.js`、`dispatch_stage3.js`（一步终签）、`wave_conference_runner.js`（宏观圆桌四拍确定性驱动） | 不直接写 SQLite；`resume` 严禁扫盘静默升版 |
| `lib/agent_session_host.js` & `lib/host/` | `ctx.agents.create` / `ctx.agents.resume` 会话宿主、`model_binding.js`（10 角色原生工具断言）、`capability_mount.js`（支持封存伴随参会工具覆盖与 `extraContextProvider` 动态锚点卡注入） | **红线**：必须保留 `_inheritParentPermissionState`；收尾严格先 `dispose()` 再 `archiveSession()` |
| `lib/pair_lifecycle.js` & `lib/read_isolated_sandbox.js` & `lib/clock_and_turn_gap.js` | 单节点确定性伴随生命周期（支持 `HUMAN_ACTIVE` 让权、`EARLY_HANDOFF_READY`、`.greatwall_donors/` 杂交只读挂载）、10 角色双向隔离 Guard 与 TokenMeter 37%/52%/70% 时钟 | 严禁恢复 `evalCount >= 1` 反思锁；严禁向运行中探索者广播粗暴 steer |
| `lib/bridge/dsh_schema_adapter.js` & `lib/mcp_bridge.js` | DSH RC5 严格 JSON Schema 子集适配与常驻 Python JSON-RPC 2.0 桥接 | 裸数组/重叠联合必须 Fail-Closed |
| `client_src/` + `tools/build_client.mjs` → `lib/client.js` | 模块化三问极简工作台源码（`ThreeQuestionsView`、`LivingSurveyView`、`BranchDetailDrawer`、`api.js`、`styles.js`）与零第三方依赖构建器 | 严禁引用 `@deepseek-ai/dsh-client-ui-primitives`；仅使用 DSH `--dsw-alias-*` 主题令牌 |
| `tools/doctor.mjs` | 运行环境、Python↔Node 53 工具 × 10 角色跨层契约、8 套 Preset、前端红线与 DSH 挂载一键体检 | 零额外 npm 依赖，支持 `--json` |

---

## 3. 验收与防腐门禁命令

在 `greatwall-v6up/` 目录下执行以下验收。跨层契约由 Python 注册表生成至 `dsh_plugin/lib/contracts.generated.json`，随前端一并构建。

```powershell
# 1. Python 全量单元、旧库无损迁移、三大科研工程、并发一致性/真取消与架构防腐门禁
pwsh -NoProfile -Command "python -m unittest discover -s tests -p 'test_*.py' -v"

# 2. Node 前端产物构建、全量单测、v0.3 运行时/Superagent/大外环测试与 L2 假模型全链路沙盘
pwsh -NoProfile -Command "Set-Location dsh_plugin; node tools/build_client.mjs; npm test; npm run doctor"
```
