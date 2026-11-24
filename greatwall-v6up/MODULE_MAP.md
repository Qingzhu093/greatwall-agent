# GreatWall V6-Up 模块地图（MODULE_MAP）

面向人类协作者与后续接手 AI Agent 的一页架构导航：快速定位代码边界、分层红线与验收命令。完整设计见仓库根目录 [`../ARCHITECTURE.md`](../ARCHITECTURE.md)。

---

## 1. Python 核心与单写真相源（`core_python/`）

| 路径 | 职责 | 禁止放入 / 边界红线 |
| --- | --- | --- |
| `mcp_server/tool_registry.py` | **32 窄工具单一契约源**：集中定义 7 角色授权、read/write、长耗时、回合收尾与 JSON Schema | 严禁 import 业务实现 `tools_*.py` 或 `control_plane/` |
| `mcp_server/greatwall_core_mcp.py` | Stdio JSON-RPC 2.0 协议入口与工具/控制面分发器（Single-Writer 唯一写入口） | 严禁堆砌 SQL 事务或重复手写工具 Schema |
| `mcp_server/db_schema.py` | SQLite WAL 19 张表 DDL、3 条防作弊硬触发器与增量迁移 | 严禁删除 `_migrate_survey_requests_check_constraint` 中的 `idx_survey_status` 补建逻辑 |
| `mcp_server/mcp_core_helpers.py` | 连接管理、RBAC 鉴权、路径安全与公共辅助（角色白名单直接从 `tool_registry` 导入） | 严禁反向依赖 `tools_*.py` 或 `control_plane/` |
| `mcp_server/mcp_schema_docs.py` | 公开输入目录同步与运行期文档契约常量 | 不含调度状态机逻辑 |
| `mcp_server/control_plane/` | 控制面 6 个无环子域（`workspace_sync` / `blind_sandbox` / `lifecycle_ops` / `scheduler_rules` / `delivery_and_jobs` / `ui_projection`） | 严禁反向 import `tools_*.py`；单文件保持 `<1000` 行 |
| `mcp_server/control_plane_service.py` | 薄门面（Re-export `control_plane/`，保持既有 import 兼容） | 严禁在此新增业务逻辑 |
| `mcp_server/tools_*.py` | 7 角色窄工具实现：`tools_explorer`、`tools_companion`、`tools_logistics`、`tools_surveyor`、`tools_verifier`、`tools_works`、`tools_supervisory`（`tools_library` / `tools_research` / `tools_governance` 为薄兼容门面） | 每文件仅归属单一角色；禁止跨角色越权写表 |
| `evaluators/isolated_runner.py` | 三档（`probe`/`official`/`heavy`）四态隔离仪器执行器、校准门禁与重型异步作业 | 严禁向探索者泄露 `_hidden_calibrations/` 或评测源码 |
| `agents/*.md` & `config.json` | 7 份角色系统提示词与全局运行参数（500k 物理时钟、37%/70% 阈值、熔断参数） | 修改工具名须同步更新对应 `.md`（门禁测试强制校验） |

---

## 2. DSH Cordis 插件层（`dsh_plugin/`）

> **与 DSH 的关系边界**：不修改 DSH 原生工具与宿主核心行为，依托 DSH Cordis 插件生态（Preset、Agent Session、Tool Hook、Console Routes、Web Client 槽位）构建无侵入科研运行时。

| 路径 | 职责 | 禁止放入 / 边界红线 |
| --- | --- | --- |
| `lib/index.js` | Cordis 插件主入口：注册 6 套 Preset、11 动作 `greatwall_orchestrate` 工具、HTTP 路由与前端 bundle | 不直接编写复杂调度循环 |
| `lib/orchestrator.js` | 后台事件池主控壳、生命周期启停与资源回收 | 单次派发逻辑拆至 `lib/orchestrator/` |
| `lib/orchestrator/` | 4 个编排子域：`circuit_breaker.js`（单待办熔断与探索者选派）、`dispatch_stage1.js`（Parse 0）、`dispatch_stage2.js`（五治理角色与探索并发）、`dispatch_stage3.js`（退修/终核/联合终签） | 不直接写 SQLite；所有状态变更走 `bridge.control` |
| `lib/agent_session_host.js` | DSH `ctx.agent.create` 会话宿主、工具白名单、沙箱 Guard 注入与流式运行 | **红线 1**：严禁删除 `_inheritParentPermissionState`（防 Windows headless `pwsh` ACL 崩溃）；**红线 2**：严禁为探索者开启 `dsh-compaction-tool-result-pruner`（防破坏 37%/70% 物理时钟） |
| `lib/host/model_binding.js` | 模型显式绑定校验、事件流模型继承、272k/500k 有效窗口计算与平台原生工具强断言 | 保持纯函数与可单测性，不直接持有会话状态 |
| `lib/pair_lifecycle.js` | 探索者与伴随助手单节点同会话伴随、37% 反思解锁与 70% 两步清醒交接 | 禁止跨代复用伴随会话 |
| `lib/read_isolated_sandbox.js` | 双向读写沙箱 Guard（探索 Worktree、空白盲审沙箱、工造司隔离、70% 动态只读锁） | 严禁用仅拦写不拦读的外部文件系统沙箱替代 |
| `lib/clock_and_turn_gap.js` | TokenMeter 物理时钟采样与 `concludeTurn()` 回合边界判定 | 严禁恢复 `evalCount >= 1` 反思锁 |
| `lib/mcp_bridge.js` | 常驻 Python Single-Writer JSON-RPC 桥接、分层超时与 `describeContracts()` 握手 | 不做业务决策 |
| `lib/prompts.js` & `lib/presets.js` | 7 角色工具路由表、平台感知原生工具白名单与 6 套 DSH Preset 声明 | 工具清单须与 Python `tool_registry.py` 100% 同步 |
| `lib/console_routes.js` & `lib/client.js` | 工作区路由与侧边栏驾驶舱 UI（`client.js` 计划在阶段 2 模块化重构） | 写操作必须显式校验目标工作区，禁止兜底误杀 |
| `tools/doctor.mjs` | 运行环境、Python↔Node 32 工具契约与 DSH 挂载状态一键诊断 | 保持零额外 npm 依赖，支持 `--json` |

---

## 3. 验收与防腐门禁命令

在 `greatwall-v6up/` 目录下执行：

```powershell
# 1. Python 全量单元 + 架构防腐门禁（含跨语言契约、AST 分层、行数守卫与 doctor 校验）
python -m unittest discover -s tests -p "test_*.py" -v

# 2. Node DSH 插件全量单元 + L2 假模型全链路沙盘 + 实时契约握手
Set-Location dsh_plugin
node --test --test-reporter=spec test/*.test.mjs

# 3. 一键环境与契约自检
node tools/doctor.mjs
```
