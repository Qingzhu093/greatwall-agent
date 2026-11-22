# dsh-greatwall-v6up (v3.0.0)

长城科研共同体 **GreatWall Agent V6-Up (v3.0)** 的 DeepSeek Harness Cordis 插件包，最低宿主版本为 `0.2.2-rc.5`。

## 从 DSH 0.2.2-rc.3 升级到 0.2.2-rc.5

- **宿主版本。** Desktop 请核对桌面应用内置的 DSH 版本。用 CLI 启动 Web Profile 时，可用 `dsh --version` 核对当前 CLI 版本。
- **RC4 模型拒答。** DeepSeek 流式拒答现在以 `turn/end` 的 `error.code = CONTENT_REFUSED` 结束。长城保留 DSH 原始回合错误，并在状态遥测中记录 `model_content_refused`。RC4 也修复了桌面 LiveShare 创建分享失败的问题。[RC4 发布说明](https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.2.2-rc.4) · [拒答错误码迁移指南](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.2-rc.5/docs/upgrade-guide/v0.2.2-rc.3/deepseek-refusal-code/guide.zh.md)
- **RC5 文献搜索。** 文献员继续使用 DSH 的 `web_search` 和 `web_fetch`。搜索提供方设为「自动选择」时，`deepseek-official` 和 `deepseek-account` 模型路由优先走 DeepSeek 服务端搜索，按模型 token 计费，无按次搜索费。其他路由优先走 DeepSeek Search API，`web_fetch` 默认仍走 `http`。已有的搜索提供方显式配置继续生效。[RC5 发布说明](https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.2.2-rc.5) · [搜索路由迁移指南](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.2-rc.5/docs/upgrade-guide/v0.2.2-rc.4/web-search-deepseek-model-default/guide.zh.md)
- **自定义网关。** 若文献员沿用 `deepseek-official` 路由，但模型流量走代理，服务端搜索的端点独立于聊天端点。需要同样通过网关时，请在 DSH 网页搜索设置中配置服务端搜索的 Base URL，或显式选择 DeepSeek Search API 延续原有的搜索路由。[搜索端点与配置说明](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.2-rc.5/docs/upgrade-guide/v0.2.2-rc.4/web-search-deepseek-model-default/guide.zh.md)

## 核心架构特性（v3.0）

- **6 套职责极净预设（`cordis.patch.yml` + `lib/presets.js`）**：
  - `greatwall-explorer`：读写 fs + search + 平台 Shell（锁在分支 `worktree`）
  - `greatwall-verifier`：只读 fs + search + 平台 Shell（锁在现建独立空白盲审沙箱，物理禁写/禁外网/禁 DB）
  - `greatwall-companion`：只读 fs + search（单节点同会话暂停续传）
  - `greatwall-works`：读写 fs + search + 平台 Shell（锁在 `evaluators/` 与 `skills/`，严禁修改 `worktrees/`）
  - `greatwall-surveyor`：只读 fs + search + web（外藏文献与 Stage 3 五件套导出）
  - `greatwall-db-only`：物理 0 原生工具（专供 `logistics_coordinator` 与 `supervisory_committee` 纯 SQLite 状态机驱动）
- **Single-Writer Python MCP 桥（`lib/mcp_bridge.js`）**：常驻单进程 `python -u -m core_python.mcp_server.greatwall_core_mcp`，支持常规 60s / 重计算与校准 300s 分级 RPC 超时。
- **双隔离沙箱与动态只读保护（`lib/read_isolated_sandbox.js`）**：探索 Worktree + 盲审空白沙箱 + 70% 探索者最后一轮亲笔遗嘱只读瞬时锁。
- **单节点同会话伴随暂停续传与 70% 两步清醒交接（`lib/pair_lifecycle.js`）**：废除 `eval_count >= 1` 反思门槛，支持纯数学推导与多学科通用科研。
- **两步联合终核与人类叫停真源（`lib/orchestrator.js` + `lib/console_routes.js`）**：`export_stage3_final_delivery` 绑定 `(delivery_id, delivery_sha256)`，支持 UI/MCP `human_stop` 写入控制面真源 `human_stop_requested_at`。

## 快速自检（纯模块单元测试）

```bash
node --test --test-reporter=spec --test-timeout=15000 ./test/v3_control_plane_unit.test.mjs
```
