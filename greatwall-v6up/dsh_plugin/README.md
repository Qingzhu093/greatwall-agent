# dsh-greatwall-v6up（`v0.2.0-alpha.1` · 协议 v3.0）

长城科研共同体 **GreatWall Agent V6-Up** 的 DeepSeek Harness Cordis 插件包，最低宿主版本为 **`0.2.2-rc.5`**（已通过真实 RC5 CLI + DeepSeek Flash 主控与子会话工具调用实测）。

## `v0.2.0-alpha.1` 核心升级亮点

1. **DSH `0.2.2-rc.5` 原生深度对齐**：
   - **单源 Preset 与原生工具执行器**：删除旧 `presets/` 12 份冗余 YAML，统一收敛为 [`cordis.patch.yml`](./cordis.patch.yml) 单源声明，6 套子角色 Preset 全量挂载 `@deepseek-ai/dsh-tool-executor-native`；
   - **Cordis 4.1.0 Standard Schema v1 `Config`**：[`lib/config.js`](./lib/config.js) 实现零依赖 `~standard.validate` 运行时校验与默认值填充，仅暴露 6 项真接线配置（`corePythonRoot`、`pythonBin`、`dataDir`、`requestTimeoutMs`、`longToolTimeoutMs`、`defaultAgentOptions`），彻底清除假配置旋钮；注：因刻意保持零第三方依赖，支持 YAML 配置与运行时校验，暂不提供原生 Schemastery 图给 `--dump-config-schema` 静态投影；
   - **严格 JSON Schema 子集适配（[`lib/bridge/dsh_schema_adapter.js`](./lib/bridge/dsh_schema_adapter.js)）**：32 个 MCP 工具参数无损转译至 RC5 严格子集（可空联合转 `oneOf`、约束摘要拼入 `description`、重叠联合与裸数组缺 `items` 严格 Fail-Closed）；
   - **完整插件生命周期回收**：[`lib/index.js`](./lib/index.js) 通过 `ctx.effect` 返回异步清理 Promise，停用/卸载时等待工具、技能、路由、活跃子会话与 Python 子进程完整释放；[`package.json`](./package.json) 补齐 `"./icon"` 与 `"./locale/*.json"` 导出。
2. **双池并发、端到端真取消与单写者强一致**：
   - Python MCP 服务端拆分为 `fast_pool`（纯只读连接 + 控制面短写）与 `compute_pool`（评测/校准/重型任务/Stage 3 导出），彻底消除 stdio 队头阻塞；
   - Node `AbortSignal` 经 `$/cancelRequest` 透传至 Python 实时强杀隔离评测子进程树，并在写锁内复核取消标志杜绝幽灵落库；
   - 引入进程级单写者大闸 `_SINGLE_WRITER_LOCK`，根治并发正式评测撞号串写、Stage 3 “审 A 放 B”及失败目录补偿竞态、`heavy` 恢复撞车与在途旧观测绕过升版重评。
3. **跨 `cwd` 原生对话直达与真实归档语义**：
   - 右侧栏指挥舱（[`lib/client.js`](./lib/client.js)）支持探索者、伴随、盲审官及治理会话经 DSH 原生 `uiWorkspace.openSession(sessionId)` 一键打开实时/历史对话；
   - 会话收尾严格遵循 RC5 语义：**先 `handle.dispose()` 解除活跃占用，再调用原生 `workspaceRegistry.archiveSession`（含跨 `cwd` 子会话），最后将真实归档结果写入遥测**；
   - 读/写控制路由（[`lib/console_routes.js`](./lib/console_routes.js)）在显式指定 `workspaceRoot` 时均禁止回退至其他工作区；主控工具与 HTTP 路由统一收口至 [`lib/control_service.js`](./lib/control_service.js)。

## 从 DSH 0.2.2-rc.3 升级到 0.2.2-rc.5

- **宿主版本。** Desktop 请核对桌面应用内置的 DSH 版本。用 CLI 启动 Web Profile 时，可用 `dsh --version` 核对当前 CLI 版本。
- **RC4 模型拒答。** DeepSeek 流式拒答现在以 `turn/end` 的 `error.code = CONTENT_REFUSED` 结束。长城保留 DSH 原始回合错误，并在状态遥测中记录 `model_content_refused`。RC4 也修复了桌面 LiveShare 创建分享失败的问题。[RC4 发布说明](https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.2.2-rc.4) · [拒答错误码迁移指南](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.2-rc.5/docs/upgrade-guide/v0.2.2-rc.3/deepseek-refusal-code/guide.zh.md)
- **RC5 文献搜索。** 文献员继续使用 DSH 的 `web_search` 和 `web_fetch`。搜索提供方设为「自动选择」时，`deepseek-official` 和 `deepseek-account` 模型路由优先走 DeepSeek 服务端搜索，按模型 token 计费，无按次搜索费。其他路由优先走 DeepSeek Search API，`web_fetch` 默认仍走 `http`。已有的搜索提供方显式配置继续生效。[RC5 发布说明](https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.2.2-rc.5) · [搜索路由迁移指南](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.2-rc.5/docs/upgrade-guide/v0.2.2-rc.4/web-search-deepseek-model-default/guide.zh.md)
- **自定义网关。** 若文献员沿用 `deepseek-official` 路由，但模型流量走代理，服务端搜索的端点独立于聊天端点。需要同样通过网关时，请在 DSH 网页搜索设置中配置服务端搜索的 Base URL，或显式选择 DeepSeek Search API 延续原有的搜索路由。[搜索端点与配置说明](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.2-rc.5/docs/upgrade-guide/v0.2.2-rc.4/web-search-deepseek-model-default/guide.zh.md)

## 核心架构特性

- **6 套职责极净单源预设（`cordis.patch.yml` + `lib/presets.js`）**：
  - `greatwall-explorer`：读写 fs + search + 平台 Shell（锁在分支 `worktree`）
  - `greatwall-verifier`：只读 fs + search + 平台 Shell（锁在现建独立空白盲审沙箱，四重 Fail-Closed 物理禁写/禁外网/禁 DB）
  - `greatwall-companion`：只读 fs + search（单节点同会话暂停续传）
  - `greatwall-works`：读写 fs + search + 平台 Shell（锁在 `evaluators/` 与 `skills/`，严禁修改 `worktrees/`）
  - `greatwall-surveyor`：只读 fs + search + web（外藏文献与 Stage 3 五件套导出）
  - `greatwall-db-only`：物理 0 原生工具（专供 `logistics_coordinator` 与 `supervisory_committee` 纯 SQLite 状态机驱动）
- **双池并发 Python MCP 桥（`lib/mcp_bridge.js`）**：常驻单进程 `python -u -m core_python.mcp_server.greatwall_core_mcp`，支持常规 60s / 重计算与校准 300s 分级 RPC 超时与 `AbortSignal -> $/cancelRequest` 透传。
- **双隔离沙箱与动态只读保护（`lib/read_isolated_sandbox.js`）**：探索 Worktree + 盲审空白沙箱 + 70% 探索者最后一轮亲笔遗嘱只读瞬时锁。
- **单节点同会话伴随暂停续传与 70% 两步清醒交接（`lib/pair_lifecycle.js`）**：废除 `eval_count >= 1` 反思门槛，支持纯数学推导与多学科通用科研。
- **两步联合终核与人类叫停真源（`lib/orchestrator.js` + `lib/control_service.js` + `lib/console_routes.js`）**：`export_stage3_final_delivery` 绑定 `(delivery_id, delivery_sha256)` 并在单写者事务内校验与回滚，支持 UI/MCP `human_stop` 写入控制面真源 `human_stop_requested_at`。

## 快速自检

```bash
npm test
npm run doctor
```
