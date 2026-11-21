# 长城 Agent V6-Up（v3.0）零前提工程架构与系统开发总说明书

> **文档性质与阅读前提**：  
> 本文是面向中层工程研发、DSH 插件开发与 Python MCP / 隔离沙箱实现团队的**完整、自包含工程施工蓝图**（完整的 **v3.0 零上下文基准规格**）。读者只需先阅读顶层架构白皮书 **[`04`](./04_长城%20Agent%20V6-Up：面向长周期自主科学发现的多智能体系统架构白皮书（v3.0）.md)** 理解架构动机，即可凭本文档与 **[`agent_kb/05`](../agent_kb/05_原论文级Prompt武器库与五大角色完整模板直抄库.md)**（31 窄工具签名与 7 份角色模板直抄库）从零完成全部工程落地。  
> **运行底座基准**：开源 DeepSeek Harness（`DSH 0.2.2-rc.3`, Desktop Runtime + Cordis Bundle）× Python 3.14 MCP Server / 双隔离执行内核。

---

## 第一章：系统分层架构、完整目录布局与工程施工红线

### 1.1 两层物理职责边界（Node/Cordis 控制面 × Python/SQLite 真相内核）

长城 V6-Up 严格划分为**控制面插件（TypeScript / JavaScript, Cordis Bundle）**与**状态与计算内核（Python 3.14 + SQLite WAL）**两层，通过标准 stdio JSON-RPC 2.0 桥接通信：

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│  层 1：DSH Cordis 插件控制面 (greatwall-v6up/dsh_plugin/)                                │
│  • 极薄确定性事件编排：5 治理角色单次无状态短会话 + 单节点内伴随暂停续传（不跨代）        │
│  • 唯一 Token 水位读取器：ctx.tokenMeter -> 同步 pressure_tokens / 500,000 至 SQLite    │
│  • 回合间隙顺序控制：37% 伴随扫目录反思、70% 探索者先立遗嘱再伴随单写、<70% 断线抢救     │
│  • 双隔离沙箱守卫：OS DACL + realpathSync Guard（探索 Worktree + 空白盲审临时沙箱）      │
│  • 客观遥测中间件：tools/result 自动写入 FACT_LOG 与干预指令透传                         │
└──────────────────────────────────────────┬─────────────────────────────────────────────┘
                                           │ stdio JSON-RPC 2.0 (分级对齐长超时)
                                           ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│  层 2：Python MCP 服务与隔离仪器内核 (greatwall-v6up/core_python/)                       │
│  • SQLite WAL 单一真相库（存放在被测工作区之外的 $PLUGIN_DATA 受控目录）                 │
│  • Single-Writer 状态机与 31 个单一职责窄工具 + 统一 next_step_guidance 回执外壳         │
│  • 隔离仪器执行器 (isolated_runner.py)：三档同码、四态映射、四元复合缓存与外部产物持久化  │
│  • 校准集回归引擎：VERDICT 仪器注册与升版前独立子进程实跑全量金/毒/格式预期校准用例       │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 全工程完整物理目录布局

#### A. 主工程仓库布局（`greatwall-v6up/`）
```text
greatwall-v6up/
├── dsh_plugin/                              # DSH Cordis Bundle 插件（零修改 DSH 原生源码）
│   ├── package.json                         # "type": "module"; files 必须显式包含 presets/ 与 lib/
│   ├── cordis.patch.yml                     # 仅注册本插件服务；按平台配置 Shell；禁用未注册模板变量
│   ├── presets/                             # 7 大角色轻量元数据定义（不走 dsh-subagent 派单树）
│   ├── lib/
│   │   ├── index.ts                         # Bundle 入口：声明 inject 服务并启动事件编排循环
│   │   ├── orchestrator.ts                  # External Orchestrator：ctx.agents.create() + 两级公平槽位调度
│   │   ├── clock_and_turn_gap.ts            # TokenMeter (500k) 采样、37% 回合间隙反思、70%/断线抢救
│   │   ├── sandbox_and_acl.ts               # 双隔离沙箱管理（探索 Worktree + 空白盲审沙箱）与 OS DACL / Guard
│   │   ├── worktree_and_snapshots.ts        # Git Worktree 生命周期与 Retained Candidate 物理快照备份/还原
│   │   ├── blackbox_projection.ts           # 从 sessionQuery 抽取去思维链轨迹与代码 Diff 摘要 Push
│   │   ├── fact_log_middleware.ts           # tools/result 后置确定性写入 FACT_LOG（带真实 session_id）
│   │   └── skillpack.ts                     # 技能说明加载器
│   └── test/                                # 零 Mock 真 Cordis 集成测试套件（结构化状态驱动，禁匹配自然语言文案）
│
├── core_python/                             # Python 3.14 MCP 状态机与隔离执行内核
│   ├── config.json                          # 与 04 第六章 100% 逐字段对齐的基准运行配置
│   ├── prompts/
│   │   └── holiday_prompts.yaml             # 逐字收录 agent_kb/05 全量 29 条夜科学启发题
│   ├── agents/                              # 100% 逐字直抄 agent_kb/05 的 7 份角色模板
│   │   ├── explorer.md
│   │   ├── lineage_companion.md
│   │   ├── logistics_coordinator.md
│   │   ├── library_surveyor.md
│   │   ├── library_verifier.md
│   │   ├── works_engineer.md
│   │   └── supervisory_committee.md
│   ├── evaluators/
│   │   ├── isolated_runner.py               # 通用跨进程隔离仪器容器与校准集实跑引擎
│   │   ├── base_instrument.py               # 标准取数辅助 get_public_input(spec) 与返回体协议校验器
│   │   ├── hooks/                           # 工造司按课题动态注册的仪器插件文件
│   │   ├── calibrations/                    # 对应 VERDICT 仪器的独立校准集 JSON 与样本文件
│   │   └── examples/                        # 异构科研标准验收样例（几何反例 / Lean4 / 多保真仿真 / Pareto）
│   ├── mcp_server/
│   │   ├── greatwall_core_mcp.py            # stdio JSON-RPC 2.0 入口与角色工具白名单硬校验分发
│   │   ├── db_schema.py                     # 外部隔离路径解析、WAL/FK/触发器 DDL、FTS5 查询净化器
│   │   ├── control_plane_service.py         # Single-Writer 事务控制面、脱敏导出、快照托管与状态跃迁
│   │   ├── tools_research.py                # explorer(5) + lineage_companion(4)
│   │   ├── tools_governance.py              # logistics(5) + surveyor(3) + verifier(5) + works(5) + supervisory(4)
│   │   └── mcp_core_helpers.py              # 统一 JSON 回执、next_step_guidance 路由、脱敏与复合指纹计算
│   └── skills/
│       └── SKILL_LEDGER.json                # 共享探针沉淀账本（skill_id 强匹配 ^[a-z0-9_]+$）
└── tests/                                   # Python 全场景正/负向回归测试集
```

#### B. 工作区外部物理隔离数据区（`$PLUGIN_DATA/workspaces/<ws_hash>/`）
所有数据库、隐藏测试/校准集、持久化 Stage A 输出与物理快照必须存放在被测科研工作区之外的独立目录，由操作系统 DACL 拒绝一线探索者与盲审沙箱进程访问：
```text
$PLUGIN_DATA/workspaces/<ws_hash>/
├── greatwall.db                             # SQLite WAL 唯一真相数据库
├── eval_artifacts/<obs_id>/                 # 持久化的 Stage A 原始输出（用于按需重评）
├── job_inputs/<job_id>/                     # heavy 异步作业入队时冻结的候选与 tools/ 不可变快照
├── snapshots/<branch_id>/retained_candidate/# Retained Candidate 物理文件快照
├── _hidden_calibrations/                    # 隐藏校准集与保留评测集（仅高权限执行域可读）
└── blind_sandboxes/blind_sandbox_<rev_id>/  # 每次盲审现建、审毕销毁的独立空白临时沙箱
```

### 1.3 四条工程施工不可逾越红线
1. **零修改 DSH 原生源码**：所有宿主能力仅通过 Cordis `inject` 服务挂载，严禁修改 `app.asar` 或引入未导出的私有包依赖。
2. **工作区磁盘零过程公文**：严禁任何角色在工作区磁盘写入 `HANDOFF.md`、`*_AUDIT.md`、`*_RELEASE.md`、`*_CLOSURE.md` 等过程汇报或审批文件；所有流转数据只写入 SQLite（仅 Stage 3 最终由服务端导出 `<workspace>/final_delivery/` 五件套）。
3. **单一真时钟与单写者事务**：上下文水位唯一来源为宿主 `TokenMeter` 同步写入的 `pressure_tokens`（严禁 Python 端按字符数反猜）；数据库写操作一律走 `BEGIN IMMEDIATE`（`rw_immediate_tx`），伴随助手独占 `submit_node_handoff` 写权。
4. **结构化断言与零 Mock 集成**：插件集成测试必须基于真实 `@deepseek-ai/cordis`、Agent Loop 与 `TokenMeter` 运行，以数据库结构化状态驱动测试流程，严禁依赖自然语言提示词字符串做脆弱匹配。

---

## 第二章：DSH 独立控制面与双隔离沙箱实施规格（`dsh_plugin/`）

### 2.1 Cordis Bundle 注册与宿主服务注入

插件通过 `plugin_manager(action: "install_bundle", target: "<abs_dir>")` 挂载至 Profile。由于外部 Bundle 不能直接 `import` 内部私有包，所有宿主能力必须声明 `export const inject = [...]` 注入：
- **`agents`**：`ctx.agents.create()`、`ctx.agents.resume()`、`handle.agent.followup()`（配合 `keepAliveAfterIdle` 保活续传）与 `handle.dispose()`，用于拉起一次性治理短会话以及单节点内同会话续传的探索者/伴随对；
- **`tools`**：`agentCtx.tools.restrict()`（Schema 层物理裁剪可见工具）与 `agentCtx.tools.guard()`（调用前实时参数与路径拦截）；
- **`systemPrompt`**：`agentCtx.systemPrompt.section()`，动态分段注入无状态启动 Push 视图与干预指令；
- **`tokenMeter`**：`ctx.tokenMeter.contextPressure()` 与 `ctx.tokenMeter.measure()`，唯一权威 Token 水位数据源；
- **`sessionProjections` / `sessionQuery`**：纯函数状态投影与去思维链黑匣子轨迹提取（严禁向官方 Session Log 写入未注册自定义事件）。

> **打包与配置细节**：`package.json` 的 `files` 字段必须显式包含 `lib/`、`presets/`、`cordis.patch.yml` 与 `locale/`，防止标准安装时丢失预设目录。

### 2.2 External Orchestrator：`ctx.agents.create()` 无 Root 编排骨架

系统不使用受限于 `maxDepth = 1` 与 `maxActiveSubagents = 8` 的父子派单树，而是由外部编排器直接拉起彼此平级的独立无状态会话：

```ts
// greatwall-v6up/dsh_plugin/lib/orchestrator.ts 核心拉起骨架
const expectedShell = process.platform === 'win32' ? 'pwsh' : 'bash';

const handle = await ctx.agents.create({
  sessionId: `gw-${epochId}-${role}-${unitId}-${gen}-${shortUuid}`,
  meta: { cwd: roleSandboxAbsPath }, // explorer->分支Worktree; library_verifier->独立空白blind_sandbox_<rev_id>
  agentOptions: {
    provider: config.provider,
    model: config.model,
    reasoningEffort: ROLE_EFFORT_MAP[role], // explorer/surveyor/verifier='high'; companion/works='medium'; logistics/supervisory='low'
  },
  setup: async (agentCtx, agent) => {
    const allowTools = resolvePlatformAllowedTools(role, expectedShell);
    agentCtx.tools.restrict({ allow: allowTools });
    // 启动前平台感知工具挂载强断言：校验应挂载工具 100% 存在（win32 验 pwsh，非 win32 验 bash）
    assertToolsMountedOrThrow(agentCtx, allowTools, role);
    installSandboxGuard(agentCtx, role, sandboxPolicy);
    agentCtx.systemPrompt.section({
      name: `gw-contract-${role}`,
      order: 650,
      text: () => assembleStatelessPrompt(role, pushPayload, activeInterventions), // 确定性注入活跃干预指令
    });
    if (role === 'explorer') {
      installClockAndTurnGapController(agentCtx, agent, unitState);
    }
  },
});

try {
  // 治理角色（5 类）：一次性短无状态会话，执行完毕立即在 finally 销毁；
  // 一线探索单元（explorer + lineage_companion）：在单个 node_id 内启用 keepAliveAfterIdle，
  // 同一伴随会话依次承接 PRE_SPAWN -> 暂停 -> REFLECT_37 -> 暂停 -> HANDOFF_70（节点结束即销毁，严禁跨代常驻！）
  await handle.agent.followup(startupManifest);
  await handle.agent.whenIdle();
} finally {
  await handle.dispose(); // 单次治理任务结束或单代节点完结时彻底销毁会话，释放槽位与上下文
  if (role === 'library_verifier') {
    await cleanupBlindSandbox(roleSandboxAbsPath);
  }
}
```

> **单节点伴随暂停续传与崩溃冷启动兜底规约**：  
> `pair_lifecycle` 驱动单个 `node_id` 时，将 `PRE_SPAWN` 阶段创建的 `lineage_companion` 会话句柄（`compSessionId`，带 `keepAliveAfterIdle: true`）绑定至该节点内存生命周期表；到达 `37%` 与 `70%` 时通过 `continueAliveAgent(compSessionId, ...)` 直接向同一个伴随对话传入新阶段消息，节点写完 `submit_node_handoff` 后在 `finally` 块立即 `dispose()`，**严禁跨节点/跨代复用**。若运行途中宿主重启、内存句柄丢失或发生 `< 70%` 意外断线抢救（`CRASH_RECOVERY`），控制面自动回退为按 `node_id` 从 SQLite **无状态冷启动**一个兜底伴随会话接管收尾。

**编排器必须实现的五项确定性调度行为**：
1. **两级公平并发槽位调度**：读取 `config.json` 的 `max_concurrent_workers`（默认 `6`，硬上限 `<= 10`），仅约束一线探索者槽位（后台治理短会话独立触发，不抢占科研槽位）。分配顺序为**先按子题（`question_id`）活跃数均衡，再在子题内按学派（`family_id`）活跃数均衡**。
2. **`AWAITING_TRIAGE` 禁抢跑硬锁**：某分支一旦存在状态为 `AWAITING_TRIAGE` 的节点，控制面在后勤完成 `triage_node` 并刷新 `retained_candidate` 物理快照之前，**物理禁止**为该分支拉起下一代 `explorer`。
3. **学派聚拢实时检测（无豁免刚性分流）**：每次 `triage_node` 或分支活跃状态变更后，控制面确定性计算各子题下每个 `family_id` 的活跃分支数 `branch_count_in_family` 与总活跃分支数 `total_active_branches`。一旦满足 **`branch_count_in_family >= 2 && (branch_count_in_family / total_active_branches) > 0.50`**，立刻发出 `FAMILY_CONCENTRATION` 事件唤醒 `logistics_coordinator` 执行强制 `orthogonal` 分流（**绝不设高产豁免**）。
4. **无人值守口径歧义红灯不停跑**：检测到 `compliance_alerts` 写入 `ALERT_AMBIGUOUS_SPEC` 时，向桌面 UI / 状态快照推送红灯告警，**事件总线严格按 Parse 0 原已签口径继续正常派单，绝不挂起停摆**。
5. **干预指令全链路闭环**：当外部触发定向干预（`interventions`）时，除了向运行中会话实时投递，还必须持久化并在该角色下次冷启动时由 `assembleStatelessPrompt` 确定性拼接进系统上下文，待 Agent 执行回执确认后才标记消费。

### 2.3 `TokenMeter` 真时钟、回合间隙控制流与断线抢救

1. **权威水位采样（分母固定 `500,000`）**：
   - 在 `tools/result`、`tools/post-execute`、`agent/pre-step` 读取 `ctx.tokenMeter.contextPressure(agent.session)`（优先 `projectedTokens`，Step 0 回退 `measure(agent.session).totalTokens`）；
   - 计算 `pressure_pct = pressure_tokens / 500000` 并原子更新 `lineage_nodes.pressure_tokens`。
2. **`37%` 回合间隙情报赋能型元反思控制流（无 `eval_count` 门槛）**：
   - **触发条件**：`pressure_pct >= 0.37 && first_reflection_unlocked == 0`（无论探索者此前是否调用过数值仪器，纯解析推导同样正常触发）；
   - **顺序切换与情报前置**：当前工具调用正常返回（严禁在 MCP 工具内部阻塞套娃调用子代理） $\to$ 控制面在回合结束处（`agent/turn-stopping`）使探索者干净进入 `idle` $\to$ 从 `sessionQuery` 提取去思维链轨迹摘要，并从 `holiday_prompts.yaml` 第 **`1–28` 条中随机抽取 1–2 条候选** $\to$ 通过 `continueAliveAgent(compSessionId, ...)` 续传本节点暂停待命的 **`lineage_companion(mode="REFLECT_37")`**（若句柄失效则按 `node_id` 冷启动兜底） $\to$ 伴随先调用 `get_companion_context(mode="REFLECT_37")`（**服务端同步返回本脉 `lineage_dead_ends` 摘要 + 同题中央图书馆 `L3/L2` 目录卡摘要 + 抽样夜科学题**） $\to$ 伴随切换外部严苛专家，以**《临床诊断师 + 避坑情报员》**尺度与探索者完成 **$\le 2$ 轮、每轮 $\le 300$ 字**短问答（允许输出事实盲区诊断 + 最多 **2 条**高度相关的 `[L2/L3]` 或死胡同编号指针 + 1 道夜科学追问；**严守 `AgentDiscover meta.md` 三不给红线：绝不给算力配额、方案排序表或算法/代码实现**） $\to$ 伴随调用 `record_reflection_and_unlock_pull` 当场置位 `first_reflection_unlocked = 1` 并重新暂停挂起（不销毁，等待 `70%`） $\to$ 控制面续传恢复探索者进入 `37%–70%` 开放 Pull 阶段。
3. **`70%` / `Cost Note` 两步清醒交接与 `< 70%` 意外断线抢救**：
   - **正常 `70%` / `Cost Note` 两步接力**：
     - **Step 1（探索者亲笔整理成果与《科研遗嘱》）**：水位到达 `350,000` Token（`>= 0.70`）或触发 `Cost Note` 经济重启阈值时，控制面在当前回合间隙先通过 `continueAliveAgent(expSessionId, ...)` 向仍清醒的探索者发送**最后一轮只读纯文本收官指令**（禁止修改代码或执行耗时脚本），要求其亲笔总结本代核心成果、反常线索并撰写《科研遗嘱》（下一步最小鉴别实验、关键怀疑点与判定翻转条件）；待该轮返回后归档并 `dispose()` 探索者句柄；
     - **Step 2（伴随核对客观证据并独占单写落库）**：控制面随即通过 `continueAliveAgent(compSessionId, ...)` 续传本节点同一伴随会话进入 `HANDOFF_70`（句柄失效时冷启动兜底），将探索者亲笔遗嘱文本与黑匣子轨迹一并交予伴随；伴随对照 Worktree Diff 与客观 `[Obs###]` 日志执行去人称、A/B 双栏核验后，唯一调用 `submit_node_handoff` 写 DAG 新页与 `lineage_dead_ends` 并置 `AWAITING_TRIAGE`，随后在 `finally` 块彻底 `dispose()` 伴随会话。
   - **异常 `< 70%` 意外断线抢救（`CRASH_RECOVERY`）**：若探索者会话在 `< 70%`（哪怕 `< 37%`）意外断开或超时（无法执行 Step 1），控制面立刻标记 **`interrupted_unclaimed`** 并续传或冷启动 `lineage_companion(mode="CRASH_RECOVERY")` 扫描 Worktree 与调用记录——只要**非一字未产空崩溃（`is_empty_crash == false`）**，一律按对应 `evidence_grade`（如 `ARTIFACT_ONLY` / `MEASURED`）抢救写入正式 DAG 页并置 `AWAITING_TRIAGE`，完结后销毁伴随会话。

### 2.4 双隔离沙箱落地与 7 大角色原生工具矩阵

操作系统级隔离与 Cordis Guard 构成双层防线：
1. **OS DACL / 低权限子进程域**：Windows 宿主为 `explorer` 与 `library_verifier` 的本地子进程 / Shell 配置显式 Windows DACL Deny ACE（或独立低权限沙箱账户），从内核层拒绝其读取 `$PLUGIN_DATA/workspaces/<ws_hash>/` 下的 `greatwall.db`、`_hidden_calibrations/`、其他分支 Worktree 与盲审未授权文件；Python MCP 与隔离评估执行域运行在受控高权限服务域内。
2. **空白盲审临时沙箱（`blind_sandbox_<review_id>/`）**：每次拉起 `library_verifier` 前，控制面创建全新空目录，**仅向其中拷贝**手稿 A 栏文本、脱敏候选代码/证明源码/反例数据及关联 `[Obs###]` JSON；物理不挂载 DB、B 栏、作者元信息、隐藏集与探索 Worktree，且禁外网；审毕 `finally` 彻底清理。
3. **`tools.guard` 路径规范化白名单**：对全部文件类工具入参基于节点 `cwd` 执行 `path.resolve` + 最近存在祖先 `fs.realpathSync()`，拦截 `../`、符号链接逃逸、越界读取及任何过程 `.md` 公文写入。

| 角色契约 | 允许的 DSH 原生工具（平台感知：`win32 -> pwsh`, `非 win32 -> bash`） | 物理隔离边界 | 挂载 MCP 工具数 |
|---|---|---|:---:|
| `explorer` | `read`, `write`, `edit`, `read_image`, `glob`, `grep`, 平台 Shell | 仅限自身 `worktree_abs_path` 与公开题面；OS 拒读 DB / 隐藏集 / 他脉；禁外网 | **5** |
| `lineage_companion` | `read`, `glob`, `grep` | 仅单向只读配对探索节点的 `worktree_abs_path`（禁写、禁 Shell） | **4** |
| `logistics_coordinator` | **`[]`（0 原生工具）** | 纯数据库状态机调度 | **5** |
| `library_surveyor` | `read`, `read_image`, `glob`, `grep`, `web_search`, `web_fetch` | 外部学术文献/PDF 读取与 Stage 3 整编 | **3** |
| `library_verifier` | `read`, `glob`, `grep`, **平台 Shell** | 仅限当次现建的 `blind_sandbox_<review_id>/`；OS 拒读 DB / B 栏 / 隐藏集 / 探索 Worktree；禁外网 | **5** |
| `works_engineer` | `read`, `write`, `edit`, `read_image`, `glob`, `grep`, 平台 Shell | 锁定在 `evaluators/` 与 `skills/`，严禁修改研究分支 Worktree | **5** |
| `supervisory_committee` | **`[]`（0 原生工具）** | 纯只读数据库审计视图（零磁盘写入、零 Shell） | **4** |

### 2.5 Stage 3 两步联合核签编排触发（绑定具体导出版本，防“审 A 放 B”）

当 `library_surveyor` 调用 `export_stage3_final_delivery` 落盘 `<workspace>/final_delivery/` 五件套时，服务端同事务生成唯一 `delivery_id` 并计算整包五件套（报告正文 + 复现脚本目录 + 清单）的确定性摘要 **`delivery_sha256`**，写入 `project_closure_state(latest_delivery_id, latest_delivery_sha256)`，并**强制将 `status` 置为 `DELIVERY_EXPORTED`、同时重置 `verifier_final_audit_passed = 0`**（若馆员重新导出新版本 B，旧版本 A 的终核通过记录立即失效）。事件总线监听该状态，自动依次拉起：
1. **`library_verifier`（终核模式，不新增独立工具）**：控制面将当前 `latest_delivery_id` 对应的 `<workspace>/final_delivery/` 五件套只读拷贝进本次新建的空白验证沙箱；`library_verifier` 调用 **`get_unblinded_manuscript_and_peers(review_id="STAGE3_FINAL_AUDIT:<delivery_id>")`** 获取本次待核 `delivery_id`、`delivery_sha256` 以及全部被引 `L3` 的原始 `exact_verified_scope_md` 清单，实跑复现脚本并逐条核对总报告未夸大任何 `L3` 成立边界（如把 `ACCEPT_NARROWED` 特例写成全成立），最后调用 **`submit_stage2_unblind_verdict(review_id="STAGE3_FINAL_AUDIT:<delivery_id>", final_verdict="ACCEPT" | "REVISE", ...)`** 落签：
   - 核验通过（`ACCEPT`）：服务端同事务写入 `verifier_audited_delivery_id = latest_delivery_id`、`verifier_audited_delivery_sha256 = latest_delivery_sha256`、`verifier_final_audit_passed = 1`；
   - 查出夸大或复现不一致（`REVISE`）：保留 `DELIVERY_EXPORTED` 并退回 `library_surveyor` 修正后重新导出（产生新 `delivery_id / sha256` 重走终核）。
2. **`supervisory_committee`**：调用 `record_compliance_check(stage="CLOSURE_GATE", status="PASSED")` 时，**服务端硬校验三项同时成立**：`verifier_final_audit_passed == 1` **且** `verifier_audited_delivery_id == latest_delivery_id` **且** `verifier_audited_delivery_sha256 == latest_delivery_sha256`，全部匹配方将状态正式晋升为 **`CLOSED_VERIFIED`**（若审过报告 A 后馆员又重新导出报告 B，A 的核签被硬拦截，绝不能放行 B；人工显式叫停时由控制面记录 `human_stop_requested_at` 放行当前已导出的部分五件套）。

---

## 第三章：完整 SQLite WAL 数据库 Schema 与一致性触发器（`db_schema.py`）

数据库统一存放在 `$PLUGIN_DATA/workspaces/<ws_hash>/greatwall.db`，启用 `PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;`，全部写操作使用 `BEGIN IMMEDIATE`（`rw_immediate_tx`）。FTS5 全文检索接口必须配置查询净化器（自动转义特殊符号、处理中英文混合多关键词分词），严禁因标点或运算符触发 SQLite FTS5 语法崩溃。

### 3.1 完整 17 张核心表结构定义

| 编号 | 表名 | 所属分层 | 核心字段与强约束（可直接照表建 DDL） |
|---:|---|---|---|
| **1** | `parse0_contract` | 启动契约 | `contract_id PK`, `goal_and_completion_md NOT NULL`, `subquestions_json NOT NULL`, `question_order_json DEFAULT '[]'`, `initial_instruments_json DEFAULT '[]'`, `seed_families_json DEFAULT '[]'`, `total_budget_json NOT NULL`, `min_commitment_window_sec INTEGER NOT NULL`, `delivery_spec_md NOT NULL`, `human_signed_at TEXT NOT NULL` |
| **2** | `instruments` | 仪器科 | `instrument_id TEXT`, `version INTEGER`, `PRIMARY KEY(instrument_id, version)`, `question_id TEXT NOT NULL`, `instrument_role TEXT CHECK(instrument_role IN ('VERDICT','PROBE','ENV'))`, `instrument_rel_path TEXT NOT NULL`, `instrument_sha256 TEXT NOT NULL`, `calibration_suite_rel_path TEXT` *(VERDICT 必非空)*, `artifact_schema TEXT NOT NULL`, `health_status TEXT CHECK(health_status IN ('HEALTHY','UNHEALTHY')) DEFAULT 'HEALTHY'`, `consecutive_error_count INTEGER DEFAULT 0`, `is_active INTEGER DEFAULT 1`, `created_at TEXT` |
| **3** | `observations` | **真相 ①** | `obs_id PK`, `question_id NOT NULL`, `branch_id NOT NULL`, `node_id NOT NULL`, `instrument_id NOT NULL`, `instrument_version INTEGER NOT NULL`, `tier TEXT CHECK(tier IN ('official','heavy'))`, `candidate_entry_sha256 NOT NULL`, `tools_dir_sha256 NOT NULL`, `spec_sha256 NOT NULL`, `instrument_sha256 NOT NULL`, `stage_a_artifact_path TEXT`, `revalidated_from_obs_id TEXT REFERENCES observations(obs_id)`, `obs_status TEXT CHECK(obs_status IN ('VALID_PASS','MEASURED_REJECTION','VALID_UNDECIDED','CANDIDATE_ERROR','INSTRUMENT_ERROR','INFRA_ERROR','PENDING_REVALIDATION','SUPERSEDED_REVALIDATED','INCOMPATIBLE'))`, `tracks_json TEXT NOT NULL`, `details_text TEXT`, `linguistic_prediction TEXT`, `created_at TEXT`, `updated_at TEXT` *(旧收据永久保留不可覆盖；重评成功生成绑定新版本的新 `[Obs###]` 并经 `revalidated_from_obs_id` 关联)* |
| **4** | `probe_diagnostic_logs` | 诊断日志 | `probe_id PK`, `node_id NOT NULL`, `question_id NOT NULL`, `instrument_id NOT NULL`, `instrument_version INTEGER NOT NULL`, `status TEXT`, `tracks_json TEXT`, `details_text TEXT`, `created_at TEXT` *(高频快速试探日志，绝不污染 `observations`)* |
| **5** | `async_eval_jobs` | 重型排队 | `job_id PK`, `obs_id TEXT`, `question_id NOT NULL`, `branch_id NOT NULL`, `node_id NOT NULL`, `instrument_id NOT NULL`, `instrument_version INTEGER NOT NULL`, `artifact_snapshot_path TEXT NOT NULL`, `spec_snapshot_json TEXT NOT NULL`, `cache_key TEXT NOT NULL`, `linguistic_prediction TEXT NOT NULL`, `declared_refs_json TEXT DEFAULT '[]'`, `status TEXT CHECK(status IN ('QUEUED','RUNNING','COMPLETED','FAILED'))`, `budget_charged INTEGER DEFAULT 0`, `created_at TEXT`, `updated_at TEXT` *(入队即冻结候选快照、仪器版本、验证规格与事前预测；重启按原冻结规格续跑并支持 `job_id` 幂等取回、仅扣费一次)* |
| **6** | `lineage_nodes` | **真相 ②** | `node_id PK`, `question_id NOT NULL`, `branch_id NOT NULL`, `family_id TEXT`, `parent_node_id TEXT`, `generation INTEGER NOT NULL`, `node_status TEXT CHECK(node_status IN ('EXPLORING','AWAITING_TRIAGE','PENDING_REVIEW','ACTIVE_REVISING','BLOCKED_L4B','SEALED','CLOSED'))`, `worktree_abs_path TEXT NOT NULL`, `retained_snapshot_abs_path TEXT`, `mechanism_summary TEXT` *(`<100` 字)*, `evidence_grade TEXT CHECK(evidence_grade IN ('NONE','ARTIFACT_ONLY','MEASURED'))`, `requires_json TEXT DEFAULT '[]'`, `premise_revoked INTEGER DEFAULT 0`, `revise_count INTEGER DEFAULT 0` *(Stage 1/2 共用)*, `column_a_facts_md TEXT`, `column_b_hypothesis_md TEXT`, `will_md TEXT`, `sanitized_code_diff_md TEXT`, `pressure_tokens INTEGER DEFAULT 0`, `first_reflection_unlocked INTEGER DEFAULT 0`, `inplace_repair_count INTEGER DEFAULT 0`, `reopen_condition TEXT`, `reflections_json TEXT`, `scratch_log_json TEXT`, `created_at TEXT`, `updated_at TEXT` |
| **7** | `lineage_dead_ends` | **真相 ②** | `dead_end_id PK`, `question_id NOT NULL`, `branch_id NOT NULL`, `node_id NOT NULL`, `category TEXT CHECK(category IN ('SCIENTIFIC_REFUTATION','IMPL_FAILURE','ENV_FAILURE'))`, `scope_condition_md NOT NULL`, `failure_mechanism_md NOT NULL`, `bound_obs_id TEXT`, `created_at TEXT` *(只追加表，承载历代全量已排除边界)* |
| **8** | `lineage_briefings` | **视图 ①** | `briefing_id PK`, `branch_id NOT NULL`, `node_id NOT NULL`, `sec1_mechanism TEXT`, `sec2_verified_baseline TEXT`, `sec3_bottleneck TEXT`, `sec4_dead_ends TEXT`, `sec5_immediate_will TEXT`, `total_chars INTEGER CHECK(total_chars <= 2200)`, `created_at TEXT` |
| **9** | `external_literature_cards` | **真相 ③左** | `ref_id PK`, `question_id NOT NULL`, `title NOT NULL`, `abstract_md TEXT CHECK(length(abstract_md) BETWEEN 60 AND 1500)`, `exact_preconditions_md NOT NULL`, `formulas_or_operators_md NOT NULL`, `read_depth TEXT CHECK(read_depth IN ('full_text','specified_sections','abstract_only'))`, `support_scope TEXT CHECK(support_scope IN ('DIRECT_PROOF_OR_EXACT_MEASUREMENT','CONDITIONALLY_VERIFIED','NEGATIVE_REFUTATION','HEURISTIC_CORRELATION','BACKGROUND_REFERENCE'))`, `source_citation NOT NULL`, `is_unverified_external INTEGER DEFAULT 1`, `created_at TEXT` *(配套 `external_literature_fts` FTS5 虚表)* |
| **10** | `internal_research_ledger` | **真相 ③右** | `entry_id PK`, `question_id NOT NULL`, `ledger_type TEXT CHECK(ledger_type IN ('L3_VERIFIED','L2_FAILURE_RECORD'))`, `l3_entry_kind TEXT CHECK(l3_entry_kind IN ('POS_THEOREM','NEG_COUNTEREXAMPLE','BARRIER_PROOF') OR l3_entry_kind IS NULL)`, `goal_coverage TEXT CHECK(goal_coverage IN ('FULL_GOAL','PARTIAL_OR_LEMMA','EQUIVALENT_REDUCTION') OR goal_coverage IS NULL)`, `l2_category TEXT CHECK(l2_category IN ('REFUTED','UNRESOLVED_OBJECTION') OR l2_category IS NULL)`, `title NOT NULL`, `abstract_md NOT NULL`, `exact_verified_scope_md TEXT`, `exact_refuted_scope_md TEXT`, `body_proof_or_code_md NOT NULL`, `bound_obs_ids_json TEXT`, `verified_review_id TEXT REFERENCES review_queue(review_id)`, `is_active INTEGER DEFAULT 1`, `created_at TEXT` *(配套 FTS5 虚表；工程错误禁入)* |
| **11** | `review_queue` | 盲审状态机 | `review_id PK`, `question_id NOT NULL`, `source_node_id NOT NULL`, `source_type TEXT CHECK(source_type IN ('LEVEL1_MANUSCRIPT','LEVEL4A_BARRIER','AUDITOR_SALVAGED_LEMMA'))`, `proposer_session_id TEXT NOT NULL`, `review_status TEXT CHECK(review_status IN ('STAGE1_BLIND','STAGE2_UNBLIND','CLOSED_ACCEPTED','CLOSED_REVISE','CLOSED_REFUTED'))`, `stage1_ledger_json TEXT`, `stage1_locked_at TEXT`, `final_locked_at TEXT`, `final_verdict TEXT CHECK(final_verdict IN ('ACCEPT','ACCEPT_NARROWED','REVISE','REFUTED') OR final_verdict IS NULL)`, `revision_requests_json TEXT`, `created_at TEXT`, `updated_at TEXT` |
| **12** | `pending_revalidation_queue` | 重评队列 | `queue_id PK`, `obs_id TEXT NOT NULL REFERENCES observations(obs_id)`, `question_id NOT NULL`, `target_instrument_id NOT NULL`, `target_version INTEGER NOT NULL`, `status TEXT CHECK(status IN ('PENDING','DONE','INCOMPATIBLE')) DEFAULT 'PENDING'`, `created_at TEXT` |
| **13** | `method_families` | 方法族谱 | `family_id PK`, `question_id NOT NULL`, `mechanism_signature NOT NULL`, `orthogonal_contrast NOT NULL`, `family_status TEXT CHECK(family_status IN ('ACTIVE','BLOCKED')) DEFAULT 'ACTIVE'`, `blocking_lemma TEXT`, `created_at TEXT` |
| **14** | `epistemic_edges` | 审计与依赖 | `edge_id PK`, `source_id NOT NULL`, `target_id NOT NULL`, `edge_track TEXT CHECK(edge_track IN ('FACT_LOG','CLAIM_DECLARED'))`, `edge_type TEXT CHECK(edge_type IN ('READ','RETRIEVED','USED_TOOL','REQUIRED_PREMISE','INDEPENDENT_SUPPORT','MOTIVATING_REF'))`, `session_id TEXT`, `created_at TEXT` *(`CLAIM_DECLARED` 写入默认值必须为 `'MOTIVATING_REF'`)* |
| **15** | `works_engineering_queue` & `survey_requests` | 部门工单 | `works_engineering_queue(ticket_id PK, question_id, ticket_type('INSTRUMENT_ERROR'|'PAIN_POINT'|'DUPLICATE_TOOL'|'EXPLOIT'), instrument_id, payload_json, status, created_at)`；`survey_requests(req_id PK, question_id, node_id, topic_query, reason, status, created_at)` |
| **16** | `compliance_alerts` & `saved_graph_queries` | 监察委 | `compliance_alerts(alert_id PK, stage, status('PASSED'|'ALERT_AMBIGUOUS_SPEC'|'ALERT'|'BLOCKED'), blocking_questions_json, notes, created_at)`；`saved_graph_queries(query_name PK, description, sql_select NOT NULL, created_at)` |
| **17** | `project_closure_state` | 两步终局 | `id INTEGER PRIMARY KEY CHECK(id=1)`, `status TEXT CHECK(status IN ('OPEN','DELIVERY_EXPORTED','CLOSED_VERIFIED')) DEFAULT 'OPEN'`, `delivery_mode TEXT`, `latest_delivery_id TEXT`, `latest_delivery_sha256 TEXT`, `verifier_audited_delivery_id TEXT`, `verifier_audited_delivery_sha256 TEXT`, `verifier_final_audit_passed INTEGER DEFAULT 0`, `human_stop_requested_at TEXT` *(仅人类通过 UI/CLI 控制面可写，任何 Agent 工具禁写)*, `supervisory_signed_at TEXT`, `updated_at TEXT` |

### 3.2 三条必建数据库硬触发器与唯一索引（SQLite Triggers & Index）
1. **`trg_reviews_lock_stage1`**：当 `review_queue.stage1_locked_at IS NOT NULL` 时，任何试图篡改 `stage1_ledger_json` 或 `stage1_locked_at` 的 `UPDATE` 直接 `RAISE(ABORT, 'STAGE1_LEDGER_IMMUTABLE')`。
2. **`trg_l3_require_verified_review` + 唯一部分索引 `uq_l3_verified_review`**：
   - 业务层 `submit_stage2_unblind_verdict` 在同一事务中必须从 `review_queue` 派生 `question_id`、送审正文与核验范围并写入 `final_locked_at`；
   - 数据库触发器在向 `internal_research_ledger` 插入 `ledger_type = 'L3_VERIFIED'` 时，强校验 **`NEW.verified_review_id IS NOT NULL`** 且在 `review_queue` 中存在满足全部五项条件的行：`r.review_id = NEW.verified_review_id` **AND `r.question_id = NEW.question_id`** **AND `r.review_status = 'CLOSED_ACCEPTED'`** **AND `r.stage1_locked_at IS NOT NULL`** **AND `r.final_locked_at IS NOT NULL`** **AND `r.final_verdict IN ('ACCEPT','ACCEPT_NARROWED')`**，否则 `RAISE(ABORT, 'L3_REQUIRES_MATCHING_VERIFIED_REVIEW')`；
   - 配套唯一部分索引 `CREATE UNIQUE INDEX IF NOT EXISTS uq_l3_verified_review ON internal_research_ledger(verified_review_id) WHERE ledger_type = 'L3_VERIFIED'`，从内核层同时封死“无审稿单入库”、“Q2 借用 Q1 审稿单串题入库”与“单张审稿单重复多插 `L3`”。
3. **`trg_obs_pending_reval_require_queue`**：观测更新为 `PENDING_REVALIDATION` 时，强保同一事务内已在 `pending_revalidation_queue` 插入对应活跃重评行，杜绝观测被孤立作废。

---

## 第四章：通用隔离执行器（`isolated_runner.py`）与校准引擎实现规格

### 4.1 统一入口、取数辅助与路径基准
1. **统一取数契约（`base_instrument.py`）**：平台下发给候选与仪器的可信测试数据，**唯一放置键位为 `evaluator_spec["public_input"]`**。基类提供标准辅助函数 `get_public_input(spec)`；严禁仪器代码从候选输出返回值中反向寻找输入，也严禁在缺少输入时静默返回 `0` 分（缺键必抛受控异常映射为 `INSTRUMENT_ERROR`）。
2. **相对路径唯一基准**：`artifact_rel_path` 统一以当前分支的 **`worktree_abs_path`** 为相对基准解析（在工具 Schema 与报错回执中明确给出示例），杜绝多层目录重复拼接。
3. **Python 候选模块隔离执行**：对 Python 类型 `artifact`，默认以 `runpy.run_path(str(cand_file), run_name="_gw_candidate")` 动态加载模块并调用 `run(public_input)`（使用 `_gw_candidate` 避免误触发候选脚本内的 `if __name__ == "__main__":` 本地调试代码）；**绝不依赖解析终端 `stdout` 字符串判分**。对 `.lean`、JSON 反例或数据包等其他形态，交由仪器插件按自身声明的 `artifact_schema` 校验执行。

### 4.2 三档同码、四元复合缓存指纹与错误穿透
1. **四元复合幂等缓存键**：
   ```text
   cache_key = sha256(
     candidate_entry_sha256
     + recursive_tools_dir_sha256          // 覆盖分支 <worktree>/tools/ 下全部辅助模块内容
     + spec_sha256(含 tier + data_slice_sha256) // 严防 probe/official/heavy 同码串用缓存！
     + instrument_sha256
   )
   ```
2. **错误穿透规则**：凡执行结果为 `INSTRUMENT_ERROR` 或 `INFRA_ERROR`，**绝对不写入永久幂等缓存**，保障仪器修好或环境恢复后探索者可直接重跑。
3. **连续故障熔断**：同一 `(instrument_id, version)` 连续返回 `INSTRUMENT_ERROR` 达到 `config.json` 阈值（默认 `3` 次）时，服务端自动置 `health_status = 'UNHEALTHY'` 并熔断该仪器的 `official` 调用，同时保留对工造司工单的提示。
4. **Stage A 外部持久化、不可覆写历史收据与诚实重评**：
   - 每次 `official` / `heavy` 执行将 Stage A 候选输出持久化至外部受控目录 `$PLUGIN_DATA/workspaces/<ws_hash>/eval_artifacts/<obs_id>/stage_a_output.json`（不随临时沙箱销毁而丢失）；
   - 仪器升版后，工造司调用 `get_works_engineering_queue` 必可同时看到 `pending_revalidation` 待重评队列；调用 `recompute_stage_b_only(obs_id, question_id)` 时，服务端读外部持久化产物交新版仪器重算并执行**严格不可覆写落库**：
     - **重评成功**：**永久保留旧 `[Obs###]` 收据不覆盖**（保留其旧 `(instrument_id, old_version)` 历史记录并将状态置为 `SUPERSEDED_REVALIDATED`），同时**新增一条绑定 `(instrument_id, new_version)` 的新 `[Obs###]` 收据**（`revalidated_from_obs_id` 指向旧收据），并在同一事务内将 `pending_revalidation_queue.status` 置为 `DONE` 结案；
     - **字段缺失或输入规格变化**：不生成虚假新收据，同事务将旧收据与 `pending_revalidation_queue.status` 同步置为 `INCOMPATIBLE` 结案。
5. **重型实验（`heavy`）入队现场冻结与断线重启幂等续接**：
   - 当探索者发起 `run_isolated_eval(..., tier="heavy", job_id=null)` 时，服务端在入队 `async_eval_jobs` 的同一事务内，将当前候选入口文件与 `<worktree>/tools/` 不可变拷贝至 `$PLUGIN_DATA/workspaces/<ws_hash>/job_inputs/<job_id>/`，并冻结锁定 `instrument_version`、`spec_snapshot_json`、`cache_key`、`linguistic_prediction` 与 `declared_refs_json`，同时将 `budget_charged` 记为 `1`（立返 `job_id`）；
   - 若执行前或执行中探索者改动了工作树、工造司升级了仪器版本、甚至宿主进程重启，后台恢复器只从 `async_eval_jobs` 读取**冻结的 `artifact_snapshot_path + 原 instrument_version + spec_snapshot_json`** 完成执行并回写 `obs_id` 与 `status='COMPLETED'`（绝不重复扣减预算）；
   - 探索者凭已获 `job_id` 再次调用 `run_isolated_eval(..., tier="heavy", job_id="<job_id>")` 即可幂等取回该作业的当前进度或已完成的 `[Obs###]` 收据。

### 4.3 校准集回归引擎与读写分离轮询
1. **校准集运行逻辑**：调用 `register_question_instrument`（当 `instrument_role == 'VERDICT'`）或 `upgrade_instrument_with_calibration` 时，服务端在独立子进程逐条执行 `calibration_suite_rel_path` 中的全部用例：
   ```json
   [
     {"case_id": "missing_entry", "expected_status": "CANDIDATE_ERROR", "expected_verdict": null, "artifact_rel_path": "...", "public_input": {}},
     {"case_id": "poison_echo",   "expected_status": "OK",              "expected_verdict": "FAIL", "artifact_rel_path": "...", "public_input": {}},
     {"case_id": "gold_ref",      "expected_status": "OK",              "expected_verdict": "PASS", "artifact_rel_path": "...", "public_input": {}}
   ]
   ```
   服务端强校验每一条用例的实测 `(status, verdict)` **100% 匹配其自声明的 `(expected_status, expected_verdict)`**，全通过即直接激活/升版。
2. **读写分离轮询原则**：`get_logistics_dashboard`、`get_supervisory_audit_snapshot` 等只读轮询接口**只能查询 SQLite 已持久化的状态字段**，响应延迟控制在 `< 50 ms` 以内，严禁在轮询调用中动态导入并运行任何 Python 仪器或候选脚本。
3. **JSON-RPC 分级超时对齐**：Node 控制面调用 Python MCP 时，常规元数据/查询工具采用默认短超时（如 `60s`），而 `run_isolated_eval` 与校准集实跑调用必须显式传入与底层沙箱一致的长超时上限（或针对 `heavy` 档立返 `job_id` 走异步轮询），避免 Node 提前断开而 Python 子进程仍在写库造成状态错位。

---

## 第五章：31 个授权窄工具总览、统一回执协议与直抄模板同步

### 5.1 统一 JSON 回执外壳与 JIT 路标
所有 31 个 MCP 工具统一返回如下结构（并在工具入口按当前会话角色做白名单越权硬拦截，参数枚举与长度约束必须在 JSON Schema `description` / `enum` / `minLength` / `maxLength` 中完整暴露，与服务端校验 100% 同源）：
```json
{
  "ok": true,
  "tool": "<tool_name>",
  "state_snapshot": {
    "question_id": "Q1", "branch_id": "b_q1_famA", "node_id": "node_p1_n2",
    "node_status": "EXPLORING", "pressure_tokens": 192000,
    "context_window_tokens": 500000, "pressure_pct": 0.384, "first_reflection_unlocked": 1
  },
  "data": {},
  "warnings": [],
  "next_step_guidance": "[JIT-Guidance] 服务端确定性生成的 1-2 句下一步提示"
}
```

### 5.2 七大角色 31 个单一职责窄工具清点（精确入参签名与范例详见 [`agent_kb/05` §0.2](../agent_kb/05_原论文级Prompt武器库与五大角色完整模板直抄库.md)）
- **`explorer`（5 个：`3[R] + 2[W]`）**：`run_isolated_eval`（含 `instrument_id`, `tier`, `artifact_rel_path`, `linguistic_prediction`, `declared_refs`, 可选 `job_id` 用于 `heavy` 异步作业幂等取回）、`query_library_catalog`（`0–37%` 仅返 `EXTERNAL_R`，解锁后全馆开放）、`get_library_entry`（静默记 `FACT_LOG(READ)`）、`request_literature_survey`、`read_lineage_graph`（解锁后开放 `view="nodes"|"dead_ends"`，强隔离他脉）。
- **`lineage_companion`（4 个：`1[R] + 3[W]`）**：`get_companion_context`（`PRE_SPAWN / REFLECT_37 / HANDOFF_70 / CRASH_RECOVERY`；`PRE_SPAWN` 严禁下发 37% 专属目录摘要，`REFLECT_37` 同步返回本脉 `lineage_dead_ends` 摘要 + 同题 `L3/L2` 目录卡摘要 + 抽样夜科学题）、`save_lineage_briefing`（按 $\text{Rewrite}_{\le 2200}(\text{旧看板}, \text{最新手记})$ 定额滚动重压缩，总长 `<= 2200` 校验）、`record_reflection_and_unlock_pull`（`<=2` 轮 $\le 300$ 字，即时置位解锁）、`submit_node_handoff`（独占单写者，对照探索者亲笔遗嘱 + Diff + `[Obs###]` 写 `<100` 字 `mechanism_summary`、`evidence_grade` 与 `dead_ends`）。
- **`logistics_coordinator`（5 个：`1[R] + 4[W]`）**：`get_logistics_dashboard`、`register_method_family`、`triage_node`（含 `assigned_family_id`、按主张形态检验可核验性、物理快照托管与 `PENDING_REVIEW` 冻结）、`fork_branch`（分支级确定性 `requires`、`WHERE branch_id != :self` 查重、跨脉授粉双 `L3` 门槛）、`dispatch_stagnation_five_lanes`。
- **`library_surveyor`（3 个：`1[R] + 2[W]`）**：`get_survey_requests`、`publish_external_literature_card`（严格 5 枚举 `support_scope` 与 `60–1500` 字符独立 `abstract_md`）、`export_stage3_final_delivery`（仅允许组装 `L3` 与精确剩余断点，导出五件套生成 `delivery_id / delivery_sha256`，重置 `verifier_final_audit_passed = 0` 并置 `DELIVERY_EXPORTED`）。
- **`library_verifier`（5 个：`2[R] + 3[W]`）**：`get_blind_manuscript`（挂载空白盲审沙箱并拷贝脱敏材料）、`submit_stage1_blind_ledger`（强校验异会话审稿、锁 `stage1_locked_at`、支持 `PASS/REVISE/REFUTED`）、`get_unblinded_manuscript_and_peers`（解盲 B 栏、横向快照与参考 `FACT_LOG`；当 `review_id="STAGE3_FINAL_AUDIT:<delivery_id>"` 时返回当前导出五件套与被引 `L3` 边界清单供终核）、`submit_stage2_unblind_verdict`（三态裁决、由服务端从审稿单派生 `question_id` 并锁 `final_locked_at`、`l3_entry_kind`、`goal_coverage`、`revise_count` 共用计数与 `edge_type_overrides`；终核模式下写入 `verifier_audited_delivery_id / sha256` 落签）、`propose_salvaged_lemma`（仅限已闭/阻塞节点，直入 `STAGE1_BLIND` 异会话复验）。
- **`works_engineer`（5 个：`1[R] + 4[W]`）**：`get_works_engineering_queue`（同步返回仪器清单、故障工单、前线痛点、重复轮子线索与 **`pending_revalidation` 待重评队列**）、`register_question_instrument`（`VERDICT` 强跑校准集）、`upgrade_instrument_with_calibration`（100% 过校准集即升版）、`recompute_stage_b_only`（不覆盖旧收据，成功生成绑定新版的新 `[Obs###]` 并置队列 `DONE`；缺字段诚实标 `INCOMPATIBLE`）、`update_skill_ledger`。
- **`supervisory_committee`（4 个：`2[R] + 2[W]`）**：`get_supervisory_audit_snapshot`、`check_stage2_closure_gate`（支持 `FULL / PARTIAL_ON_BUDGET / PARTIAL_ON_HUMAN_STOP`；凡人类叫停放行**服务端强校验控制面已记录 `project_closure_state.human_stop_requested_at IS NOT NULL`**，绝不轻信 Agent 伪造 `human_aborted=true`）、`record_compliance_check`（零 `.md` 写库；`CLOSURE_GATE(PASSED)` 强校验终核绑定匹配 `latest_delivery_id / sha256`）、`register_saved_graph_query`。

### 5.3 静态资产 100% 同步要求
- `core_python/config.json` 逐字段对齐 [`04` 第六章](./04_长城%20Agent%20V6-Up：面向长周期自主科学发现的多智能体系统架构白皮书（v3.0）.md#第六章基准运行配置configjson与权威文档导航)；
- `core_python/prompts/holiday_prompts.yaml` 逐字收录 `agent_kb/05` 全部 29 条夜科学启发题（`1–28` 运行态随机抽 1–2 条，`29` 专作全局停滞锚点）；
- `core_python/agents/*.md` 全部 **7 个文件 100% 逐字直抄** [`agent_kb/05`](../agent_kb/05_原论文级Prompt武器库与五大角色完整模板直抄库.md) 中的完整模板。

---

## 第六章：分阶段施工路线图（P0–P4）与真实可失败验收体系

| 阶段 | 核心施工交付物 | 必须跑通的真实可失败验收测试（严禁 Mock 假 API 或文案字符串硬耦合） |
| :---: | :--- | :--- |
| **P0：<br>配置与模板对齐** | 同步 `config.json`、`holiday_prompts.yaml` 与 7 份逐字直抄 `agents/*.md`；确保 `dsh_plugin/package.json` `files` 包含 `presets/` 与 `lib/`。 | 静态一致性校验：`agents/*.md` 与 `agent_kb/05` 完全一致；所有 31 工具 JSON Schema 与服务端校验枚举/长度同源；全仓现行文档零断链。 |
| **P1：<br>数据库与隔离执行器** | 落地完整 17 表 + 3 触发器 + `uq_l3_verified_review` 唯一索引 `db_schema.py`（含 FTS5 查询净化器）；落地三档四态 `isolated_runner.py`、四元复合缓存、外部持久化、重型作业现场冻结与校准集运行引擎。 | Python 单测实证：① 漏读 `public_input` 必返 `INSTRUMENT_ERROR` 且零处罚；② 修改 `tools/` 或切换 `tier` 时复合缓存键独立重算；③ 校准集拦截空输入误放版、放行合法零解金样本；④ Q4 升版后 `get_works_engineering_queue` 可见 3 条待重评单，删除临时沙箱目录后调 `recompute_stage_b_only` 可查到新旧两版 `[Obs###]` 与结案状态（缺新字段标 `INCOMPATIBLE`），Q1–Q3 保持原样；⑤ **`heavy` 排队拿 `job_id` 后改工作树候选、升仪器 v1->v2 并模拟进程重启，再凭同一 `job_id` 取回按原冻结规格执行的结果，核对预算仅扣 1 次**；⑥ FTS5 中英文多关键词检索零崩溃；⑦ 只读轮询接口耗时 `< 50 ms`。 |
| **P2：<br>31 窄工具与完整状态机** | 实现 `control_plane_service.py`、`tools_research.py` 与 `tools_governance.py` 全量状态流转、分支级确定性 `requires`、`>=2 && >50%` 聚拢信号与双段终局门禁。 | 正/负向场景全回归：① 纯推导无 `Obs` 节点正常过 `37%` 解锁并写 `DAG(ARTIFACT_ONLY)`；② **盲审入库防串题与负向硬拦截**：无审稿单插 `L3` 被拒、**Q2 借用 Q1 已通过审稿单插 `L3` 被触发器与服务双重拒绝**、同一审稿单重复插 `L3` 被唯一索引拒绝、未过 `37%` 偷读 `L3/L2` 与跨分支读 DAG 被拒、同会话自审或越权调工具被拒；③ **终稿版本绑定拦截**：馆员夸大 `ACCEPT_NARROWED` 边界时阻断 `CLOSED_VERIFIED`，**报告 A 终核通过后若馆员重新导出报告 B，A 的核签记录不可用于签发 B**；④ `LEVEL_4A` 判 `REVISE` 可切回 `ACTIVE_REVISING` 返工，Stage 1/2 共用 `revise_count` 第 3 次不通过入 `L2`；⑤ **人工叫停真源成对测试**：无人点击叫停时即使 Agent 自传 `human_aborted=true` 也被拒（`HUMAN_STOP_NOT_RECORDED`）；控制面写入真实 `human_stop_requested_at` 后，即便未满 `min_commitment_window` 也立即停止新派单并放行导出。 |
| **P3：<br>DSH 控制面与双隔离沙箱** | 实现 `dsh_plugin/` 外部编排器、`TokenMeter` 500k 采样、单节点同会话伴随暂停续传（与冷启动兜底）、回合间隙 37% 情报型反思、70% 两步交接、断线抢救、`AWAITING_TRIAGE` 防抢跑硬锁、双隔离沙箱（探索 Worktree + 空白盲审沙箱）与干预透传。 | 无 Mock 真 Cordis 集成测试：① Windows 平台正确挂载 `pwsh`（不误报缺 `bash`），探索与盲审沙箱内正常执行脚本且越界读 `greatwall.db`/B 栏/他脉遭 OS + Guard 双重阻断；② 单节点伴随在 `PRE_SPAWN -> REFLECT_37 -> HANDOFF_70` 复用同一 `sessionId` 且节点完结后彻底销毁（下代换新 `sessionId`），同时实测 **`PRE_SPAWN` 拿不到 37% 专属目录摘要**、**`70%` 探索者只读收官回合尝试写文件被 Guard 拒绝**且必先完成亲笔遗嘱输出后再由伴随落库；③ **双窗口断线恢复**：45% 强杀自动标 `interrupted_unclaimed` 抢救入 DAG，且 **70% 遗嘱已写出但伴随尚未调 `submit_node_handoff` 时模拟宿主重启，能冷启动恢复、仅写库 1 次且同分支下代不抢跑**；④ `AWAITING_TRIAGE` 完成分诊前强试启动同分支下代必被宿主阻断；⑤ `ALERT_AMBIGUOUS_SPEC` 亮红灯时继续正常派单；⑥ `2/3` 聚拢超 50% 自动唤醒后勤打散。 |
| **P4：<br>异构科研 E2E 联调验收** | 用**非同质化混合验证集**（至少同时覆盖：纯解析几何反例、Lean/符号验证、多目标 Pareto 仿真与无隐藏集开放发现）跑通完整 `Stage 1–3` 闭环。 | 终局放行标准：全程 `0` 次修改 DSH 原生源码、`0` 份工作区过程 `.md` 公文、`0` 次平台故障误记科学负结果；各异构课题均可经独立盲审沙箱实测入库 `L3`，导出五件套（`DELIVERY_EXPORTED`）并经联合终核无范围夸大后正式升为 `CLOSED_VERIFIED`。 |
