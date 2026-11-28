# dsh-greatwall-v6up（`v0.3.2`）

长城科研共同体 **GreatWall Agent V6-Up** 的 DeepSeek Harness Cordis 插件包，最低宿主版本为 **`0.2.2-rc.5`**。

## `v0.3.2` 核心升级亮点（统合 `v0.3.1` 运维总控平面）

1. **学术文献馆重塑、观测快照解耦与三维反路灯盲审**：
   - **观测瞬间轻量代码快照（`frozen_code_snapshot_path`）**：每次 `official / heavy` 评测同步冻结入口文件与本地 `tools/` 快照，彻底解除后续增写辅助脚本引发的交班拒绑锁；
   - **默认非阻塞微型学术论文投稿（`manuscript_submissions`）**：70% 交班随时切出阶段成果快照送审，原分支不停工直接续推下一代；馆藏完整记录署名、学派、引文网、三维评分与公开审稿评语；
   - **两阶段三维盲审（`Rigor / Novelty / Significance`）**：Stage 1 盲评严密性并严打过度声称（`PARTIAL_PASS -> ACCEPT_NARROWED`）；Stage 2 注入《全馆摘要锚点包》评定新颖性与重要性，`novelty <= 3` 判 `REJECT_DUPLICATE` 查重退稿，`significance <= 4` 强制分流至 `MARGINAL_NOTE` 掐断边角料路灯效应；
   - **零外网院内专题综述员（`Archive Surveyor` 模式）**：`library_chronicler` 按需响应 `request_internal_survey`（通过 `RUN_INTERNAL_SURVEY` 异步 Outbox 驱动），出具 `800–4000` 字带精确编号的客观专题综述。
2. **脉冲式同行拼图工作坊、三阶段无损执行与双模收敛**：
   - [`lib/orchestrator/wave_conference_runner.js`](./lib/orchestrator/wave_conference_runner.js) 确定性驱动 4 拍同行工作坊：第 1 拍确定性硬账本与三问议程 → 第 2 拍 `ctx.agents.resume` 唤醒各脉已封存 `gw-comp-<node_id>`（物理撤除档案写权，Round 2 强制点对点回复链 `CRITIQUE_SEAM / ENDORSE_AND_OFFER / WARN_STREETLIGHT / CONFIRM_TAKEAWAY`）并落盘 `<=6000` 字不截断纪要与各脉 `peer_takeaways_json` → 第 3 拍零外网 `library_chronicler` 刷新核心四栏 `<=4000` 字 + 边缘隔离栏 `<=1500` 字总览 → 第 4 拍原地 `resume` 同一 `gw-chair-<conference_id>` 签发宏观决断；
   - 执行器严格按 **Phase 1 先休眠腾槽与真实打捞遗产 → Phase 2 合体（豁免单学派 `>50%` 锁并生成 `DONOR_MANIFEST.md`）与开枝 → Phase 3 工单与双模收敛（`CONVERGE_FULL_COMPOSITE` 组合终核通关 / `CONVERGE_SATURATED` 饱和止盈，均自动解锁 `question_order` 后续子题）** 落地；散会后由下代伴随助手自主消化 `latest_wave_takeaways` 执笔重写 `<=3600` 字看板。
3. **微观 `360k` 四段时钟、完整 11 类元反思与 52% 停码夜科学绿洲**：
   - 单班岗默认有效窗口收紧至 `360,000` tokens（`maxEffectiveContextWindow` 可配）；37% 问诊补齐 11 类元反思（含 `C11_RESEARCH_TASTE` 科研品味，单轮 `<=500` 字）；
   - 新增 **52% 停码夜科学绿洲**（`contextHolidayPct = 0.52`，[`lib/host/context_holiday.js`](./lib/host/context_holiday.js)）：宿主物理只读锁 2 回合，仅豁免放行 `submit_holiday_bet` 登记可证伪赌注，随后解锁在 `52%–70%` 实测验证；
   - 沙箱守卫（[`lib/read_isolated_sandbox.js`](./lib/read_isolated_sandbox.js)）支持 `read / glob / grep` 缺省路径自动锚定绑定沙箱、精确路径段 `..` 校验，以及 `external_surveyor` arXiv `/html/` 自动改写。
4. **常驻科研总控 (`gw-chief`) 与设施运行底座（继承 `v0.3.1`）**：
   - 独立 Preset **`greatwall-chief`**（物理零写码/零终端/零外网、弹性 `<=1500` 字置顶锚点卡与 `chief_read` 分页器），人类当面下令可直执版本化 `run_arrangements`、导师便签、8000 字蓝图种枝并返回四态 `operation_receipts`；仅 4 类高危宪章动作走双端幂等确认单；
   - `instance_lock.js` + `worker_slots.js`（`maxWorkers + 1` 人类优先槽）+ `effects_consumer.js`（11 类 Outbox 副作用并发消费）+ `human_takeover.js`（`source.rpcId` 人类插话让权与 `ctx.jobs` 清理）；
   - [`lib/config.js`](./lib/config.js) 动态探测 `@deepseek-ai/schemastery`（含 `maxEffectiveContextWindow` 与 `contextHolidayPct` 表单项），前端 [`client_src/`](./client_src/) 经 [`tools/build_client.mjs`](./tools/build_client.mjs) 构建生成 [`lib/client.js`](./lib/client.js)。

## 8 套单源角色 Preset（[`cordis.patch.yml`](./cordis.patch.yml)）

覆盖全院 10 大角色与 53 个窄 MCP 工具，全量挂载 `@deepseek-ai/dsh-tool-executor-native`：

- `greatwall-chief`：Superagent 总控（零写/零终端/零外网，启用 `dsh-compaction-basic`）
- `greatwall-explorer`：一线探索者（读写 fs + search + 平台 Shell，锁在分支 worktree，严禁开启 `pruner`）
- `greatwall-verifier`：空白沙箱盲审官（只读 fs + search + 平台 Shell，四重 Fail-Closed 物理禁写/禁外网/禁 DB，含 Stage 3 冻结包一步终签）
- `greatwall-companion`：单节点伴随助手（只读 fs + search，确定性 ID `gw-comp-<node_id>` 跨阶段按需 `resume`，封存参会撤写权）
- `greatwall-works`：科研仪器科（读写 fs + search + 平台 Shell，锁在 `evaluators/` 与 `skills/`，禁改 `worktrees/`）
- `greatwall-external-surveyor`：对外文献采编（**唯一挂载 `dsh-tool-web`**，物理禁读院内成果与工作树）
- `greatwall-chronicler`：对内综述与终稿官（零外网、零终端、零写盘，维护 4000 字核心总览和 1500 字边缘附栏，撰写专题报告并冻结终稿）
- `greatwall-db-only`：物理 0 原生工具（专供 `logistics_coordinator`、`supervisory_committee` 与 `conference_chair` 纯 SQLite 状态机驱动）

## 从 DSH 0.2.2-rc.3 升级到 0.2.2-rc.5 说明

- **RC4 模型拒答**：DeepSeek 流式拒答以 `turn/end` 的 `error.code = CONTENT_REFUSED` 结束；长城保留原始错误并在遥测记录 `model_content_refused`，且不触发无意义瞬时重试。
- **RC5 文献搜索**：仅 `external_surveyor` 使用 DSH 的 `web_search` 与 `web_fetch`；搜索路由与自定义网关配置沿用 DSH RC5 官方设置。

## 构建、测试与自检

```bash
npm run build:client   # 从 client_src/ 重新生成 lib/client.js
npm test               # 运行 64 项 Node 单测、v0.3.2 运维/夜科学/圆桌测试与 L2 假模型全链路沙盘
npm run doctor         # 检查 53 个工具、10 个角色、8 套 Preset 与运行环境
```
