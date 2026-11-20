# dsh-greatwall-v6up (v2.2.0)

长城科研共同体 **V6-Up (v2.2)** 面向 DeepSeek Harness (`0.2.2-rc.3`) 的官方插件本体，遵循**双层解耦与单写并发控制面**架构：

## 核心架构
1. **上层 DSH 异步事件池编排器 (`lib/orchestrator.js`, `lib/agent_session_host.js`, `lib/pair_lifecycle.js`)**：
   - 基于 DSH 原生 `ctx.agents.create()` 管理 **7 大标准角色**（`explorer`, `lineage_companion`, `logistics_coordinator`, `library_surveyor`, `library_verifier`, `works_engineer`, `supervisory_committee`）；
   - 通过 `cordis.patch.yml` 声明式 `@deepseek-ai/dsh-agent-preset` + 运行时 `agentPresets.register()` 兜底注册 **5 套专用预设**（`greatwall-explorer` / `verifier` / `companion` / `works` / `governance`），并在 `setup` 内以 `tools.restrict()` + `tools.register()` 将 31 个 Python MCP 窄工具按角色精确切分为 3–5 个；
   - 保留桌面主控预设原能力不受限，子角色全部在同工作区归档、支持 UI 直接追问纠偏与冷恢复自动重挂。
2. **500,000 Token 真实水位时钟 & 回合间隙控制流 (`lib/clock_and_turn_gap.js`)**：
   - 结合 `sessionProjections(['contextPressure'])`、`tokenMeter.measure()` 与 `agent/pre-step` + `tools/result` 追帧监听，原子同步至 SQLite `lineage_nodes.pressure_tokens`；
   - 到达 `37%`（且首测完成）或 `70%` 时触发 `exec.concludeTurn()`，交由 `lineage_companion` 完成 `<=2` 轮反思对话并提炼**去思维链黑匣子摘要**独家写库。
3. **方案 A 混合读写隔离沙箱 (`lib/read_isolated_sandbox.js`)**：
   - 使用 `fs.realpathSync()` 解析最深祖先路径，免疫符号链接与 `..` 绕过；严密保护隔离 `$PLUGIN_DATA`（含 `greatwall.db`）、`evaluators/anchors/`、兄弟分支 worktree 与 `pwsh` 跨目录 / `$env:` / `sqlite3` 探测。
4. **右侧栏「长城控制台」(`lib/client.js`, `lib/console_routes.js`) & 轻量遥测 (`lib/telemetry.js`)**：
   - 通过 DSH Connection 鉴权路由 `/api/greatwall.status` 与 `/api/greatwall.control` 为右侧栏提供子题依赖锁、节点 `500k` 压力条、一键暂停/恢复/停止与人工定向 `intervene` 纠偏。
5. **底层 Single-Writer Python MCP 控制面 (`../core_python/mcp_server/greatwall_core_mcp.py`)**：
   - 持久化 stdio JSON-RPC 2.0 进程独占 SQLite WAL 写入与数据库触发器硬锁。

## 在 DeepSeek Harness 桌面端中调控课题
本插件通过软链挂载至 `~/.dsh/profiles/desktop` 后，主对话会话自动拥有入口工具 `greatwall_orchestrate` 与技能卡 `greatwall-research-loop`：
1. 初始化或异步启动：`greatwall_orchestrate(action="start", workspace_root="<项目绝对路径>", goal_md="...", required_questions=["Q1", "Q2"])`（非阻塞 ~1s 返回，免受 600s 墙钟误杀）；
2. 实时状态与纠偏：`greatwall_orchestrate(action="status" | "pause" | "resume" | "stop" | "intervene", workspace_root="...")` 或直接打开右侧栏 **「长城控制台」** Tab 可视化操作。
