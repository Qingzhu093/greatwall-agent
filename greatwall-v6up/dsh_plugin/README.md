# dsh-greatwall-v6up (v3.0.0)

长城科研共同体 **GreatWall Agent V6-Up (v3.0)** 的 DeepSeek Harness (`0.2.2-rc.3`) 官方 Cordis 插件包。

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
