# GreatWall V6-Up 模块地图（MODULE_MAP · `v0.2.0-alpha.1`）

面向人类协作者与后续接手 AI Agent 的一页架构导航：快速定位代码边界、分层红线与验收命令。完整设计见仓库根目录 [`../ARCHITECTURE.md`](../ARCHITECTURE.md)。

---

## 1. Python 核心与单写真相源（`core_python/`）

> **并发与一致性铁律（`v0.2.0-alpha.1`）**：**并发纯只读（`open_ro_connection` + `ro_consistent_tx`）+ 并发纯外部隔离计算（子进程在锁外 100% 并行）+ 严格进程级单写者记总账（`_SINGLE_WRITER_LOCK` + `rw_immediate_tx`）**。

| 路径 | 职责 | 禁止放入 / 边界红线 |
| --- | --- | --- |
| `mcp_server/tool_registry.py` | **32 窄工具单一契约源**：集中定义 7 角色授权、read/write、长耗时、回合收尾与 JSON Schema | 严禁 import 业务实现 `tools_*.py` 或 `control_plane/` |
| `mcp_server/greatwall_core_mcp.py` | **双池并发** stdio JSON-RPC 2.0 入口（`fast_pool` / `compute_pool`）、`$/cancelRequest` 取消注册表与 32 工具/16 原语分发 | 严禁堆砌 SQL 事务或重复手写工具 Schema |
| `mcp_server/db_runtime.py` | 真只读连接、`ro_consistent_tx`、进程级可重入单写者大闸 `_SINGLE_WRITER_LOCK` 与 `rw_immediate_tx` | 写短事务内禁止包含耗时子进程调用 |
| `mcp_server/db_schema.py` | SQLite WAL 19 张表 DDL、3 条防作弊硬触发器与增量迁移 | 严禁删除 `_migrate_survey_requests_check_constraint` 中的 `idx_survey_status` 补建逻辑 |
| `mcp_server/mcp_core_helpers.py` | RBAC 鉴权、路径安全、统一回执外壳与公共辅助（角色白名单直接从 `tool_registry` 导入） | 严禁反向依赖 `tools_*.py` 或 `control_plane/` |
| `mcp_server/mcp_schema_docs.py` | 公开输入目录同步与运行期文档契约常量 | 不含调度状态机逻辑 |
| `mcp_server/control_plane/` | 控制面 7 个无环子域（`workspace_sync` / `blind_sandbox` / `lifecycle_ops` / `scheduler_rules` / `snapshot_queries` / `delivery_and_jobs` / `ui_projection`） | 严禁反向 import `tools_*.py`；单文件保持 `<1000` 行；Stage 3 导出与失败目录补偿同受单写者锁保护 |
| `mcp_server/control_plane_service.py` | 薄门面（Re-export `control_plane/`，保持既有 import 兼容） | 严禁在此新增业务逻辑 |
| `mcp_server/tools_*.py` | 7 角色窄工具实现：`tools_explorer`、`tools_companion`、`tools_logistics`、`tools_surveyor`、`tools_verifier`、`tools_works`、`tools_supervisory`（`tools_library` / `tools_research` / `tools_governance` 为薄兼容门面） | 每文件仅归属单一角色；领号与取消复核必须在 `rw_immediate_tx` 内完成；在途旧观测遇仪器升版须自动入待重评队列 |
| `evaluators/isolated_runner.py` | 三档（`probe`/`official`/`heavy`）四态隔离仪器执行器、校准门禁与 `cancel_event` 实时强杀子进程树 | 严禁向探索者泄露 `_hidden_calibrations/` 或评测源码 |
| `agents/*.md` & `config.json` | 7 份角色系统提示词与全局运行参数（500k 物理时钟、37%/70% 阈值、熔断参数） | 修改工具名须同步更新对应 `.md`（门禁测试强制校验） |

---

## 2. DSH Cordis 插件层（`dsh_plugin/`）

> **与 DSH 的关系边界**：不修改 DSH 原生工具与宿主核心行为，依托 DSH `0.2.2-rc.5` Cordis 插件生态（单源 `cordis.patch.yml` Preset、Standard Schema v1 `Config`、Agent Session、Tool Hook、Console Routes、Web Client 槽位与 `uiWorkspace.openSession`）构建无侵入科研运行时。

| 路径 | 职责 | 禁止放入 / 边界红线 |
| --- | --- | --- |
| `cordis.patch.yml` & `lib/presets.js` | **单源** 6 套角色 DSH Preset 声明（全量挂载 `@deepseek-ai/dsh-tool-executor-native`，已删除旧 `presets/` 冗余目录）与程序化补注册 | Preset 注册仅保留 `lib/index.js` 单点；禁止向 `~/.dsh/.agent-presets/` 写磁盘文件 |
| `lib/index.js` | Cordis 插件极薄装配入口：导出 Standard Schema v1 `Config`、单点注册 Preset/Skills/主控工具/路由，卸载经 `ctx.effect` 返回异步 Promise 全量回收 | 不直接编写业务分发或调度循环 |
| `lib/config.js` | 零依赖 Standard Schema v1（`~standard.validate`）与 6 项真接线配置解析（`corePythonRoot` / `pythonBin` / `dataDir` / `requestTimeoutMs` / `longToolTimeoutMs` / `defaultAgentOptions`） | 严禁暴露未消费的假配置旋钮 |
| `lib/control_service.js` | 统一控制面（**One Operation, Two Callers**）：收口 `agent_tool` 与 `human_ui` 动作权限、`callerSource` 溯源、按工作区串行互斥锁与 `initParse0`/`initEpoch` 兼容 | 仅在服务端返回 `ok: true` 后更新 `sharedInputPaths` |
| `lib/orchestrate_tool.js` | 11 动作 `greatwall_orchestrate` 主控工具声明与参数转交 | 业务逻辑统一委托给 `GreatwallControlService` |
| `lib/orchestrator.js` | 后台事件池主控壳、生命周期启停与资源回收 | 单次派发逻辑拆至 `lib/orchestrator/`；向子模块统一暴露 `DispatchRuntimePort` |
| `lib/orchestrator/` | 5 个编排子域：`runtime_port.js`（窄能力端口与盲审沙箱四重 Fail-Closed 校验）、`circuit_breaker.js`、`dispatch_stage1.js`、`dispatch_stage2.js`、`dispatch_stage3.js` | 不直接写 SQLite；所有状态变更走 `port.control` |
| `lib/agent_session_host.js` | DSH `ctx.agents.create` 会话宿主、**先 `handle.dispose()` 再原生 `archiveSession` 并写入真实归档结果** | **红线 1**：严禁删除 `_inheritParentPermissionState`；**红线 2**：严禁为探索者开启 `dsh-compaction-tool-result-pruner`；**红线 3**：严禁用期望值覆写 `archived: true` |
| `lib/host/` | `model_binding.js`（显式模型绑定、事件流继承、有效窗口与原生工具断言）+ `capability_mount.js`（角色工具、Prompt 与沙箱挂载） | 保持低耦合可单测性，不持有全局控制器状态 |
| `lib/bridge/dsh_schema_adapter.js` | DSH RC5 严格 JSON Schema 子集适配器（可空联合转 `oneOf`、约束摘要进 `description`、裸数组/重叠联合 Fail-Closed） | 禁止静默改写字段语义或给裸数组偷补类型 |
| `lib/pair_lifecycle.js` | 探索者与伴随助手单节点同会话伴随、37% 反思解锁与 70% 两步清醒交接（单一窄端口契约） | 禁止跨代复用伴随会话；关键端口能力缺失直接显式抛错 |
| `lib/read_isolated_sandbox.js` | 双向读写沙箱 Guard（探索 Worktree、空白盲审沙箱 Fail-Closed、工造司隔离、70% 动态只读锁） | 严禁用仅拦写不拦读的外部文件系统沙箱替代 |
| `lib/clock_and_turn_gap.js` | TokenMeter 物理时钟采样、`concludeTurn()` 回合边界与基础设施/业务错误语义二分 | 严禁恢复 `evalCount >= 1` 反思锁 |
| `lib/mcp_bridge.js` | 常驻 Python JSON-RPC 桥接、分层超时、`AbortSignal -> $/cancelRequest` 真取消、`spawn` 错误防崩与 `describeContracts()` 握手 | 不做业务决策 |
| `lib/prompts.js` | 7 角色工具路由表与平台感知原生工具白名单 | 工具清单须与 Python `tool_registry.py` 100% 同步 |
| `lib/console_routes.js` & `lib/client.js` | 工作区鉴权 HTTP 路由与侧边栏驾驶舱 UI（已支持跨 `cwd` 会话经 `uiWorkspace.openSession` 一键直达；`client.js` 仍待前端模块化重塑） | 读/写路由显式指定 `workspaceRoot` 时均禁止回退到其他工作区；写操作统一经 `controlService` |
| `tools/doctor.mjs` | 运行环境、Python↔Node 32 工具契约与 DSH 挂载状态一键诊断 | 保持零额外 npm 依赖，支持 `--json` |

---

## 3. 验收与防腐门禁命令

在 `greatwall-v6up/` 目录下执行（`v0.2.0-alpha.1` 当前全绿基线：Python `54/54`、Node `39/39`、Doctor `7/7`）：

```powershell
# 1. Python 全量单元、并发一致性/真取消回归与架构防腐门禁
python -m unittest discover -s tests -p "test_*.py" -v

# 2. Node DSH 插件全量单元、RC5 Schema 适配与 L2 假模型全链路沙盘
Set-Location dsh_plugin
node --test --test-reporter=spec test/*.test.mjs

# 3. 一键环境与契约自检
node tools/doctor.mjs
```
