# dsh-greatwall-v6up（`v0.3.0-alpha.1`）

长城科研共同体 **GreatWall Agent V6-Up** 的 DeepSeek Harness Cordis 插件包，最低宿主版本为 **`0.2.2-rc.5`**。

## `v0.3.0-alpha.1` 核心升级亮点

1. **Superagent 科研总控 (`gw-chief`) 与双端幂等确认单**：
   - 新增独立 Preset **`greatwall-chief`（「长城 · 科研总控 (gw-chief)」）**：物理零写码/零终端/零外网，启用 DSH 原生 `@deepseek-ai/dsh-compaction-basic` 与弹性字数「全院现况锚点卡」（`min(hardCap, max(400, 180 + 100 * 子题数))`，默认硬封顶 1200 字，压缩后自动重注零断链）；
   - 通过 [`lib/sessions/chief_runtime.js`](./lib/sessions/chief_runtime.js) 注册 DSH RC5 原生 `actionCards`（`greatwall_proposal`），与右侧工作台待拍板卡共享同一单写者乐观锁事务，任一端点击均幂等防重；
   - [`lib/orchestrate_tool.js`](./lib/orchestrate_tool.js) 精简为 `init / start / status / stop` 4 个极简薄入口供 Headless 自动化与冷启动拉起，严禁任何模型工具伪造 `human_ui`。
2. **设施运行底座升级（`lib/runtime/` & `lib/sessions/`）**：
   - `instance_lock.js`：`host.lock` 单实例独占锁防双活 + 死 PID 自动回收；
   - `worker_slots.js`：`maxWorkers` 普通槽 + `+1` 人类优先保留槽；
   - `transient_retry.js`：429 / 5xx / 网络瞬时错误原地指数退避（15s→30s→60s），401 / `CONTENT_REFUSED` 零重试快失败；
   - `effects_consumer.js`：消费 SQLite 持久化 Outbox（60s 租约续期、崩溃认领、热注入 `NOTIFY_POLICY_CHANGED`、路由 `NOTIFY_CHIEF`）；
   - `human_takeover.js`：基于 DSH `user/message` + `source.rpcId` + 插件自发白名单精准识别人类插话让权，并经原生 `ctx.jobs` 清理残留后台 Shell 作业（无服务时平滑降级）。
3. **宏观大外环四拍脉冲与确定性会话唤醒**：
   - [`lib/orchestrator/wave_conference_runner.js`](./lib/orchestrator/wave_conference_runner.js) 确定性驱动 4 拍圆桌：代码硬对账 → 按 Round 1/2 `ctx.agents.resume` 唤醒已封存 `gw-comp-<node_id>`（物理撤除写权仅挂 `SEALED_COMPANION_CONFERENCE_TOOLS`）→ 零外网 `library_chronicler` 刷新 `<=1500` 字总览 → 原地 `resume` 同一 `gw-chair-<conference_id>` 拍板；参会助手 `<2` 名时自动跳过互辩直入总览刷新；会后严格先 `dispose()` 再 `archiveSession()`。
4. **动态 Config Schema 与模块化三问前端（`client_src/`）**：
   - [`lib/config.js`](./lib/config.js) 优先动态探测宿主 `@deepseek-ai/schemastery`（原生支持 Plugin Manager 自动表单渲染），缺宿主时自动回退零依赖 Standard Schema v1；
   - 前端彻底拆分为 [`client_src/`](./client_src/)（`ThreeQuestionsView` / `LivingSurveyView` / `BranchDetailDrawer` / `api.js` / `styles.js`），经零依赖 [`tools/build_client.mjs`](./tools/build_client.mjs) 生成 [`lib/client.js`](./lib/client.js)，纯 `--dsw-alias-*` 令牌且零 `dsh-client-ui-primitives` 依赖。

## 8 套单源角色 Preset（[`cordis.patch.yml`](./cordis.patch.yml)）

覆盖全院 10 大角色与 44 个窄 MCP 工具，全量挂载 `@deepseek-ai/dsh-tool-executor-native`：

- `greatwall-chief`：Superagent 总控（零写/零终端/零外网，启用 `dsh-compaction-basic`）
- `greatwall-explorer`：一线探索者（读写 fs + search + 平台 Shell，锁在分支 worktree，严禁开启 `pruner`）
- `greatwall-verifier`：空白沙箱盲审官（只读 fs + search + 平台 Shell，四重 Fail-Closed 物理禁写/禁外网/禁 DB，含 Stage 3 冻结包一步终签）
- `greatwall-companion`：单节点伴随助手（只读 fs + search，确定性 ID `gw-comp-<node_id>` 跨阶段按需 `resume`，封存参会撤写权）
- `greatwall-works`：科研仪器科（读写 fs + search + 平台 Shell，锁在 `evaluators/` 与 `skills/`，禁改 `worktrees/`）
- `greatwall-external-surveyor`：对外文献采编（**唯一挂载 `dsh-tool-web`**，物理禁读院内成果与工作树）
- `greatwall-chronicler`：对内综述与终稿官（零外网/零终端/零写盘，专司 `<=1500` 字总览与 Stage 3 冻结导出）
- `greatwall-db-only`：物理 0 原生工具（专供 `logistics_coordinator`、`supervisory_committee` 与 `conference_chair` 纯 SQLite 状态机驱动）

## 从 DSH 0.2.2-rc.3 升级到 0.2.2-rc.5 说明

- **RC4 模型拒答**：DeepSeek 流式拒答以 `turn/end` 的 `error.code = CONTENT_REFUSED` 结束；长城保留原始错误并在遥测记录 `model_content_refused`，且不触发无意义瞬时重试。
- **RC5 文献搜索**：仅 `external_surveyor` 使用 DSH 的 `web_search` 与 `web_fetch`；搜索路由与自定义网关配置沿用 DSH RC5 官方设置。

## 构建、测试与自检

```bash
npm run build:client   # 从 client_src/ 重新生成 lib/client.js
npm test               # 运行 48 项 Node 单测、v0.3 运行时/总控/圆桌测试与 L2 假模型全链路沙盘
npm run doctor         # 运行 8 项环境、44 工具 × 10 角色跨层契约、8 套 Preset 与红线一键体检
```
