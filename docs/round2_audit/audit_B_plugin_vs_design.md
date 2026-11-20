# 长城 Agent V6-Up 第二轮测试专项审计报告（B 卷）：插件设计与源码实现差异取证

> **审计角色**：Subagent B — 插件设计与源码实现差异审计官  
> **审计基准（设计规范）**：  
> 1. [`04_十三篇前沿论文深度解惑与V6Up架构融合专报.md`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/04_十三篇前沿论文深度解惑与V6Up架构融合专报.md)（权威主架构书）  
> 2. [`05_V6Up架构演进思辨与文献取舍絮语集.md`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/05_V6Up架构演进思辨与文献取舍絮语集.md)  
> 3. [`agent_kb/05_原论文级Prompt武器库与五大角色完整模板直抄库.md`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/agent_kb/05_原论文级Prompt武器库与五大角色完整模板直抄库.md)  
> **审计对象（真实运行插件源码）**：[`greatwall-v6up/`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/)（已按指令明确忽略 `greatwall-v6up-plugin\宿主机边界与文献源码对齐说明.md`）  
> **运行实证参照（只读核验）**：[`PLUGIN_ISSUES.md`](file:///D:/Documents/deepseek%20harness/v6第二轮测试/05_supervisory/PLUGIN_ISSUES.md)、[`ROLE_AUDIT.md`](file:///D:/Documents/deepseek%20harness/v6第二轮测试/05_supervisory/ROLE_AUDIT.md)、[`RESET_SOP_AUDIT.md`](file:///D:/Documents/deepseek%20harness/v6第二轮测试/05_supervisory/RESET_SOP_AUDIT.md)、[`Q3_CLOSURE_AUDIT.md`](file:///D:/Documents/deepseek%20harness/v6第二轮测试/05_supervisory/Q3_CLOSURE_AUDIT.md)、[`EPOCH2_REVAL_DIAGNOSIS.md`](file:///D:/Documents/deepseek%20harness/v6第二轮测试/05_supervisory/EPOCH2_REVAL_DIAGNOSIS.md)、[`P26_REPAIR_EXECUTION.md`](file:///D:/Documents/deepseek%20harness/v6第二轮测试/05_supervisory/P26_REPAIR_EXECUTION.md)，以及工作区哈希 `0b57d5d99769c4fa` 的只读 SQLite 账本 `greatwall.db`（`?mode=ro`）。

---

## 核心审计结论摘要

1. **第二轮测试未能按 `04`/`05` 设计推进，并非单一原因，而是“插件半成品/机制剪裁 + 双层脱节 Bug + 模型越位/未遵循指令”三重叠加的结果，其中结构性失控的主因在插件实现层**：
   - **极薄总线退化为“无总线 + 失控太上皇”**：`autoDispatchSubagents` 默认 `false`（[`index.js:37`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/lib/index.js#L37)），总管角色 `logistics_coordinator` 在 [`prompts.js`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/lib/prompts.js#L8-L14)、`agents/*.md` 与 `presets/` 中**全面缺席**；DSH `subagent` 不暴露 `preset`（P0）导致 [`greatwall-roles.cordis.yml`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/presets/greatwall-roles.cordis.yml#L1-L73) 全文未被 JS 加载；根会话 `session-56a36cab` 无角色关键字导致开局无契约注入、绕过所有非 MCP 门禁并越权代行总管。
   - **物理时钟双重失真与 JS/Python 脑裂（P19 + P23 + P11）**：插件强行将 `contextWindow` 封顶在 `178,500`（[`event_bus.js:198`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/lib/event_bus.js#L198)、[`mcp_core_helpers.py:236`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_core_helpers.py#L236)）且未扣除系统 Prompt + 全量工具 Schema 基线，导致 Q1 g1 写了 0 行代码即触发 `37%`；同时 JS 层 `TokenMeter` **从未把真实 Token 数同步给 Python MCP 账本**，DB 中所有 `clock:*` 的 `reflect_hint_sent` 全为 `false`，直接导致 `explorer` 调用 `submit_node_handoff(trigger_first_reflection=True)` 被报 `ERR_LOCKED` 拒绝（P23）。
   - **`worktree_and_acl.js` 致命正则导致全线自杀式误拦（P10/P18/P22）**：[`worktree_and_acl.js:16,24-33`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/lib/worktree_and_acl.js#L16-L33) 硬编码只识别 `n\d{1,5}` 节点名且无差别捕获 `03_explorers/<任意首段>`。实测在 `epistemic_edges` 产生 **31 条** `UNAUTHORIZED_TOOL_ATTEMPT`，其中 **N_Q1..N_Q4 访问自身 `03_explorers/Q1..Q4` 被误杀 19 次**（含 `N_Q3` 调 `submit_trial_observation` 被拦 2 次，直接引发 P22 逼迫复制到 `_q3_upload`），`N003` 读共享文档 `EXPLORER_GUIDE.md` 被误杀 1 次（P10）；而真跨分支相对路径在 `pwsh` 下却可绕过。
   - **P26 真相破案（非工具外手改 DB，而是插件源码 Bug）**：工造司在 `P26_REPAIR_EXECUTION.md` 中误判“无法由工具面产生”，实际源码取证表明：[`mcp_tools_research.py:1297-1314`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_tools_research.py#L1297-L1314) 在 `submit_node_handoff` 检测到 `bound_state_version < cur_state`（2 < 4）时，**直接把 `N_Q3` 下全部 `VALID` 观测（`[Obs009]/[Obs010]/[Obs011]`）降级为 `PENDING_REVALIDATION` 并清空 `comparable_rank_score`，却遗漏写入 `system_meta.pending_revalidation` 队列**！
   - **Epoch 2 `fork_branch` 4 次 `orthogonal` 失败后 2 次 `lateral` 成功的源码机理**：[`mcp_tools_governance.py:881-887`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_tools_governance.py#L881-L887) 对 `orthogonal` 查重全量 `method_families` 表**未排除 `target_family` 自身**，导致向 Parse 0 已预登记的学派（`F_Q3_SEQ_LOCK` / `F_Q3_BAYES_GAIN`）分叉时“自己撞死自己”报 `ERR_CONFLICT`（相似度 1.00）；而 `lateral`（L899-913）完全绕过 `method_families` 查重并在未传 `variant_hypothesis` 时连兄弟去重也跳过，因而成功落库 `N_9a1b8b04` 与 `N_d25fe5ee`。
   - **状态机门禁“局部有锁、全局漏风”与 Prompt 降级**：`triage_decision(L1)` 虽查 `reviews`（甚至存在 `stage2_verdict is None` 放行漏洞），但写 `.md` 结案文档（如 `Q3_CLOSURE.md`、`01_formal_paper.md`）、`publish_library_survey_entry(L3)` 与 `method_families.family_status` 均无任何盲审门禁，致使 **`reviews` 表至今 0 条记录**仍产出了结案与论文草稿；5 个 `agents/*.md` 仅有 **47–75 行**提纲式摘要，丢掉了原论文级逐条话术、盲审 JSON 模板、`Stage A __main__` 契约与 `Stage 3` 流程规约。

---

## 一、`greatwall-v6up/` 完整代码地图盘点

> 实测盘点自 `d:\antigravity\长城agent设计v6up（Gemini负责）\greatwall-v6up\`。**结构事实核正**：`core_python/mcp_server/` 中**并不存在独立的 `mcp_tools_library.py`**；中央图书馆原语被拆散在 `mcp_tools_research.py`（`tool_query_library_mcp`）和 `mcp_tools_governance.py`（`tool_publish_library_survey_entry` 及混杂在 `tool_promote_or_triage_branch` 内的 6 个审稿/打捞动作）中。

### 1.1 `core_python/mcp_server/`（7 个 `.py` 文件，共 5,417 行）

| 文件相对路径 | 行数 | 字节数 | 核心职责与导出原语 |
| :--- | :---: | :---: | :--- |
| `core_python/mcp_server/__init__.py` | 1 | 73 | 包标识文件 |
| `core_python/mcp_server/db_schema.py` | 643 | 24,718 | SQLite WAL 建库 DDL、8 个错误码、存储路径哈希分库、`trg_reviews_lock_stage1` 不可逆触发器、CommonMark 双栏手记解析、FTS5 净化、外键存在性校验 `validate_handoff_refs_exist` |
| `core_python/mcp_server/fact_bridge.py` | 69 | 2,291 | DSH JS 层 `tools/post-execute` 与 `gate.js` 调用的 CLI 桥接，异步向 `epistemic_edges` 写入 `FACT_LOG`（`READ`/`UNAUTHORIZED_TOOL_ATTEMPT`） |
| `core_python/mcp_server/greatwall_core_mcp.py` | 411 | 18,010 | stdio JSON-RPC 2.0 MCP 服务入口（NDJSON/LSP 双帧嗅探），导出 10 个核心 Tool Schema 及分发路由 |
| `core_python/mcp_server/mcp_core_helpers.py` | 944 | 35,466 | 角色别名规范化、`update_session_clock_and_steering` 字符时钟与 `COST_NOTE`、`synthesize_lineage_briefing` 五要素看板合成、盲审脱敏、RQGM Beta/对抗池公式、停滞看门狗 `compute_stagnation_status` |
| `core_python/mcp_server/mcp_tools_research.py` | 1,442 | 59,532 | 6 个研究侧原语：`tool_get_lineage_briefing`、`tool_register_saved_graph_query`、 `tool_read_lineage_graph`、`tool_query_library_mcp`、`tool_submit_trial_observation`、`tool_submit_node_handoff` |
| `core_python/mcp_server/mcp_tools_governance.py` | 1,907 | 90,451 | 4 个治理侧原语：`tool_publish_library_survey_entry`、`tool_promote_or_triage_branch`（混装图书馆 6 动作 + 后勤 7 动作）、`tool_audit_provenance_edges`、`tool_manage_eval_epoch`（混装后勤 3 动作 + 工造司 6 动作） |

### 1.2 `core_python/evaluators/`、`agents/`、`skills/`、`templates/`、`config.json`

| 文件相对路径 | 行数 | 字节数 | 核心职责 |
| :--- | :---: | :---: | :--- |
| `core_python/config.json` | 23 | 720 | 默认运行时参数（`default_context_window: 178500`, `handoff_token_cap: 125000`, `max_handoff_chars: 2000`, `stagnation_consecutive_non_l1_handoffs: 8`） |
| `core_python/evaluators/__init__.py` | 5 | 179 | 包导出 |
| `core_python/evaluators/isolated_runner.py` | 611 | 22,514 | Stage A 隔离沙箱执行（`_STAGE_A_SHIM`）与 Stage B 独立计分子进程（`_stage_b_evaluate`、`run_isolated_evaluation`、`run_stage_b_revaluation`） |
| `core_python/evaluators/examples/__init__.py` | 11 | 380 | 示例钩子包初始化 |
| `core_python/evaluators/examples/formal_proof.py` | 480 | 18,522 | 形式化数学证明参考 `domain_hook` 示例 |
| `core_python/evaluators/examples/pareto_frontier.py` | 210 | 7,815 | 多目标帕累托前沿参考 `domain_hook` 示例 |
| `core_python/evaluators/examples/physics_sim.py` | 426 | 18,333 | 物理仿真（Burgers 方程）参考 `domain_hook` 示例 |
| `core_python/agents/explorer.md` | 57 | 6,782 | 一线探索者角色契约 |
| `core_python/agents/lineage_companion.md` | 75 | 9,850 | 后勤一对一伴随助手契约 |
| `core_python/agents/central_library.md` | 63 | 7,552 | 中央图书馆（Surveyor / Verifier / Auditor）契约 |
| `core_python/agents/works_engineer.md` | 54 | 6,330 | 工造司工程师契约 |
| `core_python/agents/supervisory_committee.md` | 47 | 5,575 | 监察委员会契约 |
| `core_python/skills/greatwall-research-loop/SKILL.md` | 72 | 10,796 | 注入主控会话的科研闭环总 SOP |
| `core_python/skills/SKILL_LEDGER.json` | 33 | 1,724 | B 档共享技能账本初始化结构 |
| `core_python/templates/node_handoff_template.md` | 14 | 1,609 | `<2000` 字客观双栏交接手记模板 |

### 1.3 `dsh_plugin/` 全部 `.js` 与 `.yml`（含 `presets/`）与测试套件

| 文件相对路径 | 行数 | 字节数 | 核心职责 |
| :--- | :---: | :---: | :--- |
| `dsh_plugin/lib/index.js` | 492 | 20,892 | Cordis 插件主入口：挂载 MCP、注册 Skill、注册 `systemPrompt.section`、挂载 `tools.guard` / `pre-execute` / `post-execute` / `session/event` / `subagent/start` / `subagent/end` |
| `dsh_plugin/lib/event_bus.js` | 517 | 21,741 | `GreatWallEventBus`、关键字角色匹配 `matchRoleKeywords`、节点抽取 `extractNodeIdFromText`、`TokenMeter` 水位读取、`evaluateClockSignals`、`nodePairs` 1对1结对与 `deliverToPairedCompanion` |
| `dsh_plugin/lib/gate.js` | 247 | 8,799 | `ctx.tools.guard` 外层物理防火墙 `evaluateV6UpGate`（只读部门写/Shell 拦截、总管红线、探索者净室/隔离目录与部分 MCP 拦截） |
| `dsh_plugin/lib/worktree_and_acl.js` | 95 | 3,779 | 分支根提取 `extractCanonicalNodeRoot`、跨目录隔离 `checkExplorerWorktreeIsolation`、Windows ACL 能力探测 |
| `dsh_plugin/lib/prompts.js` | 26 | 600 | 加载 `core_python/agents/*.md`（仅列 5 角色） |
| `dsh_plugin/lib/skillpack.js` | 90 | 3,180 | YAML frontmatter 解析并注册 `SKILL.md` |
| `dsh_plugin/cordis.patch.yml` | 130 | 6,248 | Cordis bundle 配置：`dsh-greatwall-v6up` 默认配置 + 5 个 `@deepseek-ai/dsh-agent-preset` 声明 |
| `dsh_plugin/presets/greatwall-roles.cordis.yml` | 73 | 2,703 | 5 角色 `basePreset` / `sandbox` / `allowedTools` 参考矩阵（**未被任何代码加载**） |
| `dsh_plugin/presets/greatwall-{companion,explorer,library,supervisory,works}/agent.cordis.yml` | 13/27/16/13/27 | — | 5 个独立的 Cordis Agent Preset 配置 |
| `dsh_plugin/presets/greatwall-{companion,explorer,library,supervisory,works}/preset.yml` | 各 3 行 | — | Preset 元数据入口 |
| `dsh_plugin/package.json` / `README.md` / `locale/*.json` | 59 / 188 / 12 | — | 包描述、操作手册与双语提示 |
| `dsh_plugin/test/*.test.mjs` & `tests/test_*.py` | 542 & 1,834 | — | Node 与 Python 单元测试套件 |

---

## 二、“设计规范（04/05）vs 实装（greatwall-v6up）”结构性失真与缺陷逐条取证

### 2.1 极薄总线与无独立总管角色设计缺失

按照 `04` 第三章（`§3.1` L154–180）与 `05`（`§1.5` L35–36），宿主主循环仅作**无偏见极薄事件总线**，由总线自动唤醒平行的“一委三部”与“探索-伴随双人组”；后勤总管（`logistics_coordinator`）作为独立职能部门存在。源码落地在四个层面出现结构性缺失：

1. **`logistics_coordinator` 在契约、Preset 与提示注入层彻底消失**：
   - [`dsh_plugin/lib/prompts.js:8-14`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/lib/prompts.js#L8-L14) 的 `ROLE_NAMES` 仅含 `['explorer', 'lineage_companion', 'central_library', 'works_engineer', 'supervisory_committee']`；`core_python/agents/` 下**无 `logistics_coordinator.md`**；`dsh_plugin/presets/` 与 [`greatwall-roles.cordis.yml`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/presets/greatwall-roles.cordis.yml) 也**无总管 Preset**。
   - [`index.js:205-218`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/lib/index.js#L205-L218) 挂载的 `greatwall-v6up-role-contract` 即使识别出 `role === 'logistics_coordinator'`，因 `rolePrompts['logistics_coordinator']` 为 `undefined`，只能返回空字符串 `''`。
2. **`autoDispatchSubagents` 默认 `false`，极薄事件总线实质休眠**：
   - [`index.js:37`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/lib/index.js#L37) 默认 `autoDispatchSubagents: false`，[`cordis.patch.yml:16`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/cordis.patch.yml#L16) 显式锁定 `false`。
   - 这直接使 [`index.js:363`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/lib/index.js#L363)（37%/70% 时自动调用 `deliverToPairedCompanion` 唤醒伴随助手）与 [`index.js:456`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/lib/index.js#L456)（`subagent/end` 时自动调用 `dispatchSubagentRoutes` 唤醒盲审/打捞/分诊）**成为永不执行的死代码**。系统退化为完全由 Root 会话手动 `subagent` 派单的中心化模式。
3. **`matchRoleKeywords` 顺序抢占漏洞 + `logi:main` 失配 + ROOT 会话无契约与越权绑定**：
   - [`event_bus.js:44-54`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/lib/event_bus.js#L44-L54) 使用顺序 `if` 匹配：`explorer`(L47) → `lineage_companion`(L48) → `central_library`(L49) → `works_engineer`(L50) → `supervisory_committee`(L51) → `logistics_coordinator`(L52)。若总管子代理的 label 中出现“探索/看板/审稿/工造/监察”任一字样，即被前置分支误判；同时 L52 正则 `\blog[-_:]` **不匹配**第二轮实际总管会话 ID `logi:main`（多了一个 `i`）。在只读核查 `greatwall.db` 时，实测 `clock:logi:main` 的 `role` 竟被写成了 `"central_library"`！
   - **ROOT 会话 `session-56a36cab-7f9a-4230-83df-573a3f73ab66` 失控全链路**：根会话无 `name`/`label`，其 UUID 不含任何角色关键词，`resolveRole()`（[`event_bus.js:132-160`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/lib/event_bus.js#L132-L160)）返回 `''`。因此：① 开局无任何 `rolePromptSection` 契约注入；② 调用 `read`/`write`/`pwsh` 时 [`gate.js:172`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/lib/gate.js#L172) 得到 `effectiveRole = ''`，绕过一切角色门禁；③ 当其首次调用 MCP 并传 `role="logistics_coordinator", node_id="N001"` 时，[`index.js:296-308`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/lib/index.js#L296-L308) 才将其动态绑定为 `role: 'logistics_coordinator', nodeId: 'N001'`，导致此后它越权尝试 `write` `main.tex` / `check_db.py`（15:38:13Z / 15:38:42Z）和后续全部跨分支 `read` 全被记在 `src_id='N001'` 名下（P15 同源 Bug：管理会话调用 `node_id` 参数会污染该会话自身的 `rec.nodeId`！）。
4. **DSH `subagent` 不支持 `preset`（P0）导致权限物理隔离退化为千疮百孔的字符串黑名单**：
   - `greatwall-roles.cordis.yml` 的 `allowedTools` 与 `basePreset` 在 JS 代码中**零引用**；[`worktree_and_acl.js:67-95`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/lib/worktree_and_acl.js#L67-L95) 对 `@deepseek-ai/dsh-sandbox-windows-acl` **只做 `require` 探测而不调用任何授权 API**，`@deepseek-ai/dsh-experimental-tool-worktree` 仅出现在注释中。
   - 唯一生效的 [`gate.js`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/lib/gate.js#L168-L247) 存在五大漏洞：① 未绑定角色（`callerRole == ''`）调用非 MCP 工具全放行，调用 MCP 时可靠自填 `argsObj.role` 冒充角色（L172）；② 只读部门写 `.md/.txt` **无目录白名单**，可覆盖工作区任意 `.md`（L148-150）；③ MCP 外层拦截仅检查了 `explorer` 和 `logistics_coordinator` 的部分工具（L220-244），完全漏检 `lineage_companion`、`central_library`、`works_engineer`、`supervisory_committee` 互相跨界调用；④ 未拦截只读部门的 `subagent` / `send_message`；⑤ `pwsh` 下相对路径（`cd ..; cat Q2/cand.py`）或字符串拼接直接穿透正则拦截。

---

### 2.2 物理时钟基线失真与 JS / Python 双时钟脑裂（P19 / P23）

1. **硬封顶 `178,500` + 未扣除系统/工具基线（P19）**：
   - [`index.js:39,469`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/lib/index.js#L39)、[`cordis.patch.yml:18`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/cordis.patch.yml#L18)、[`event_bus.js:19,198`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/lib/event_bus.js#L198)、[`config.json:5-6`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/config.json#L5-L6) 及 [`mcp_core_helpers.py:230-236`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_core_helpers.py#L230-L236) 全部通过 `Math.min(rawWin, 178500)` 将有效上下文窗口硬封顶在 `178,500` tokens（相对于 DeepSeek 1M 窗口缩水至 ~17.85%），导致 `37% = 66,045 tokens`、`70% = 124,950 tokens`（且有 `handoffTokenCap = 125,000`）。
   - [`event_bus.js:167-199`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/lib/event_bus.js#L167-L199) 直接取 `TokenMeter.contextPressure(session).pressureTokens` 或 `totalTokens` 除以 `178,500`，**完全未扣除**系统提示词、全量内置与 MCP 工具 Schema（因 P0 无 preset 裁剪，子代理被迫背负全量 Schema）、`SKILL.md`、角色契约及初始 `BOARDING_BRIEF` 的静态基线开销。因此在真实探索中（`PLUGIN_ISSUES` P19），Q1 g1 在 **0 行代码 / 0 次运行** 时即触及 `37%`，g2 仅 2 次运行即触及 `70%`。
2. **`companion` 及其他角色的时钟失配**：
   - JS 层 [`event_bus.js:203,215`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/lib/event_bus.js#L203) 对 `rec.role === 'explorer'` 做了过滤，不会对 `companion` 触发 `37%/70%`；
   - 但 Python MCP 层 [`mcp_core_helpers.py:289-291`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_core_helpers.py#L289-L291) **仅对 `37%` 做了 `allow_reflect_hint=(canon_role == "explorer")` 过滤，而对 `70% / 125k` (`FORCE_HANDOFF_STOP`) 未过滤角色**，因此 `lineage_companion`（实测 `clock:comp:N_Q4:g1` 达 `45,925 tokens`）与 `works_engineer` 同样累计在 `178,500` 天花板下且逼近 125k 即会被发停笔信号。
3. **更致命的 JS 与 Python 双时钟彻底脱节（P23 真正源头）**：
   - [`index.js:310-315`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/lib/index.js#L310-L315) 在 `tools/pre-execute` 测得 `realTokens` 后仅存入 JS 内存对象，**从未回填进 MCP 工具参数 `context_tokens`**；且 JS `sessionId` 为 UUID，而模型传给 MCP 的 `session_id` 为语义串（如 `exp:N_Q3:g1`）。
   - 只读核查 `greatwall.db` 证实：**全库 32 条 `clock:*` 记录的 `reflect_hint_sent` 全部为 `false`**！例如 Q1 g1/g2/g3 在 Python 账本里的 `max_effective_tokens` 分别只有 `880 / 749 / 1526`。结果 JS 层已经报警“已达 37% 请立即停码反思”，而 Python MCP 端 `submit_node_handoff`（[`mcp_tools_research.py:1325-1331`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_tools_research.py#L1325-L1331)）查 `reflect_hint_sent` 仍为 `false`，直接以 `ERR_LOCKED` 拒绝探索者解锁（P23）。

---

### 2.3 `worktree_and_acl.js` 与 `gate.js` 致命正则与权限硬伤（P10 / P18 / P22）

核心缺陷集中在 [`worktree_and_acl.js:16,24-61`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/lib/worktree_and_acl.js#L16-L61) 与 [`gate.js:59-73,207-216`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/lib/gate.js#L59-L73)：

```javascript
// worktree_and_acl.js:16
const BRANCH_DIR_SEGMENT_RE = /(?:^|\/)(?:03_explorers|explorers|worktrees|branches)\/([^\/\s"'`]+)(?:\/|$|\s|["'`])/gi

// worktree_and_acl.js:24-33
export function extractCanonicalNodeRoot(rawId) {
  const s = String(rawId ?? '').trim()
  if (!s) return ''
  const nMatch = s.match(/(?:^|[^a-z0-9])(n\d{1,5})(?:[_-]?g\d+|[a-z]?)(?=$|[^a-z0-9])/i)
  if (nMatch) return nMatch[1].toUpperCase()
  const stripped = s.replace(/[_-]g\d+$/i, '').trim()
  return stripped.toUpperCase()
}
```

1. **P10 误杀共享文件**：`BRANCH_DIR_SEGMENT_RE` 无条件捕获 `03_explorers/` 后的第一段无论文件或目录。当 `N003` 读取 `03_explorers/EXPLORER_GUIDE.md` 时，`dirSegment = 'EXPLORER_GUIDE.md'` → `targetRoot = 'EXPLORER_GUIDE.MD' !== 'N003'`，直接拦截（DB 实证：`fedge_d9895523e47a`）。
2. **P18 误杀 `N_Q1..N_Q4` 自身工作树**：`extractCanonicalNodeRoot` 只识 `n\d{1,5}`（无下划线），不识 `N_Q1`。于是 `callerRoot = 'N_Q1'`，而 `03_explorers/Q1/` 提取 `targetRoot = 'Q1'`，`'Q1' !== 'N_Q1'` 必然拦截！DB `epistemic_edges` 实证显示 `N_Q1` 被拦 7 次、`N_Q2` 2 次、`N_Q3` 4 次、`N_Q4` 对自身 `Q4` 被拦 6 次（共 19 次自身误杀）。同时 [`event_bus.js:36`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/lib/event_bus.js#L36) 的 `extractNodeIdFromText` 也犯了完全相同的 `n\d{1,5}` 正则错误，导致 `explorer-q1` 无法从名称自动提取 `N_Q1` 完成 1 对 1 结对。
3. **P22 阻断 `submit_trial_observation`**：[`gate.js:71`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/lib/gate.js#L71) 将 `candidate_path` 列入 `PATH_FIELDS`，探索者传 `candidate_path=".../03_explorers/Q3/candidate.py"` 时再次触发 `Q3 !== N_Q3` 误杀（DB 实证 `N_Q3` 于 `17:28:15Z` 与 `17:28:23Z` 被拦 2 次 `tool:mcp__greatwall-v6up__submit_trial_observation`），迫使 Q3 将文件复制到工作区根 `_q3_upload/`（脱离 `03_explorers/` 前缀）才通过门禁。
4. **相对路径漏洞与无路径白名单**：`BRANCH_DIR_SEGMENT_RE` 强依赖路径包含 `03_explorers/` 等固定父段名。在 `pwsh` 中执行相对路径（如 `../Q2/candidate.py`）或环境变量拼接时正则完全失效；而本该由 `lineage_nodes.worktree_path` 显式维护的“节点↔目录”映射与 `dsh-sandbox-windows-acl` Capability-SID 权限完全缺失。

---

### 2.4 Prompt 降级与“原论文级灵魂武器库”缺失核查

对照 `04` 第五章（L273–293）与 `agent_kb/05` 的原版要求，逐个核查 `greatwall-v6up/core_python/agents/*.md` 与 `SKILL.md`：

| 文件名 | 实际行数/字节 | 保留的原论文要素 | **关键缺失内容与直接后果** |
| :--- | :---: | :--- | :--- |
| `lineage_companion.md` | 75 行 / 9.85 KB | 三禁令、`Station B.2` 英文切换段、11 类元反思列表标题、4 条 `Holiday` 问题、三态决断名称、`<2000` 字双栏概述 | ① 缺失 `Station v2` 11 类反思每类原版质询展开段落（被压成 1 句话/类）；② `Holiday` 29 条题库缩水为 4 条；③ 缺失 `CONTEXT_COMPACTION_PROMPT_TEMPLATE` 7 节完整模板；④ **未写明零 VALID 时禁交空 handoff 及 `trigger_first_reflection` 协同协议**（引发 P11/P23） |
| `explorer.md` | 57 行 / 6.78 KB | `tools/` 先查（FFT 23 分钟典故）、`read_lineage_graph` 换向/饱和判据、`Retained Candidate`、`linguistic_prediction`、双轨诚实、`[Local-Sweep]` | ① 缺失 `AgentDiscover Box B.1` 用图查询做 `MAP-Elites` / `UCT` 的具体组合策略范例；② 缺失 `SLA` 274 行原版去对冲长程指令与 checkpoint 示例；③ **完全未写 `isolated_runner` Stage A `__main__` 语义与策略类提交格式**（引发 P1/P14） |
| `central_library.md` | 63 行 / 7.55 KB | `3-Pass`、`read_depth`、5 级 `support_scope`、`Cogentic` 英文先验、7 类红队漏洞标题、两阶段锁步骤名、两步 `Auditor` | ① 缺失 `OpenAI CDC` 7 类红队逐项排查细则与拒收废话话术；② 缺失 `Station Appendix D` 固定 `Evidence Ledger` JSON 项级格式示例；③ **完全缺失 Stage 3 `Comparator -> Formal Writer -> Final Verification Audit` 契约**（导致 Stage 3 由 Lead 越权自由写草稿） |
| `works_engineer.md` | 54 行 / 6.33 KB | `Audit the Scaffold`、83–90% 正迁移、`domain_hook_path` 接口、B 档 & `No File`、`Walk-to-Jump`、RQGM 四支柱公式 | ① 未写明 `domain_hook` 单一写者租约（引发 P12 双写覆盖）；② 未说明 `STAGE_B_ONLY` 与临时沙箱路径失效冲突及 `hidden_case_salt` 透传铁律；③ 未写明 `evaluator_spec` 超时键名口径（引发 P14） |
| `supervisory_committee.md` | 47 行 / 5.58 KB | `No Mathematical Opinion`、三禁令、三巡检、`FACT_LOG` 对账、`Process Advisor`、`stagnation_status` | ① 缺失 `Station v2` 12 条 `Supervisor` 专属题库；② 缺失 Phase 0 逐项核签模板与 Stage 3 终局逐行核对清单（导致监察委靠自由散文写大量自定义审计 `.md`） |
| `logistics_coordinator.md` | **0 行（缺失）** | **文件不存在** | 后勤总管毫无系统提示契约，只能看主会话里的 `SKILL.md`（72 行），直接助长 Lead/总管越位与自由发挥 |

---

### 2.5 状态机硬门禁缺失与 P1 / P2 / P11 / P14 / P16 / P21 / P23 / P24 / P25 / P26 / `fork_branch` 逐条源码取证

#### 1. 结案、晋升与盲审状态机“局部有锁、全局漏风”
- **已有的局部守卫（及隐藏漏洞）**：[`mcp_tools_governance.py:772-789`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_tools_governance.py#L772-L789) 对 `triage_decision(triage_level="L1")` 确实校验 `reviews` 表存在记录。**但第 785–787 行存在漏洞**：`passed_rev["stage2_verdict"] not in (None, "PASS")` 允许 `stage2_verdict` 为 `None`——即审稿人仅提交了 Stage 1 `PASS`、尚未解锁 Stage 2 终判并锁定 `final_locked_at` 时即可直接放行 L1 晋级与 L3 入库！
- **无任何硬门禁的闭环通道（导致 0 盲审照样“结案”）**：
  1. **文档层结案无门禁**：`gate.js` 允许总管和只读部门向任意 `.md` 落盘，系统无任何 Stage 3 交付门禁检查 `reviews` 或 `L3`，因此第二轮测试在 **`reviews` 表为 0 条**（已查库确认）的情况下照样落盘了 `Q3_CLOSURE.md`、`Q3_T3_FULL.md` 与 `06_delivery/01_formal_paper.md`；
  2. **`publish_library_survey_entry` 可直写 `L3` 无盲审门禁**（[`governance.py:55-162`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_tools_governance.py#L55-L162)）；
  3. **`method_families.family_status` 无状态机闭环**：没有任何原语校验盲审后将学派从 `EXPLORING` 迁至 `MATURE_PROVEN`，实测 DB 中 **18 个学派全部停在 `EXPLORING`**。

#### 2. P16：`triage_decision` 伪推高停滞计数且不保存分诊理由
- **源码定位**：[`mcp_tools_governance.py:708-712, 755-756, 770-771, 825-829`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_tools_governance.py#L708-L712)。
- **机制缺陷**：设计本意用 `untriaged_handoff_nodes` 避免 `submit_node_handoff` 与紧随的 `triage_decision` 双算。但只要**节点尚未交接就先分诊**，或**同一节点被分诊两次**（首次已被 `untriaged.discard(node_id)` 移除），`already_counted` 为 `False`，就会执行 `if not already_counted: non_l1 += 1`——即使判定为 `Routine` / `L2` / `L3` 也会把 `consecutive_non_l1_handoffs` 强行推高。同时全库无 `triage_log` 表，`payload_json` 中的 `rationale` 完全被丢弃不落盘。

#### 3. P11 / P21 / P23：`submit_node_handoff`、`first_reflection_unlocked` 与 `L1` 的致命耦合
- **源码定位**：[`mcp_tools_research.py:1323-1333, 1383-1430`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_tools_research.py#L1323-L1333)。
- **缺陷耦合**：全系统**唯一**将 `first_reflection_unlocked` 置 `1` 的代码路径在 `submit_node_handoff` 内部；而调用 `submit_node_handoff` **无条件新增一条 `L1` 条目**（L1383-1406）、**覆盖当前节点 `handoff_note_md`**（L1336）、并**推高停滞计数**（L1425-1429）。
  - 叠加 JS/Python 双时钟脱节（DB 中 `reflect_hint_sent` 恒为 `false`），导致：**① 零 VALID 节点不敢交空 handoff 于是永不解锁（P11）**；**② 70% 强停归档了 L1 但 `first_reflection_unlocked` 仍为 `0` 且无区分字段（P21）**；**③ `explorer` 带 `trigger_first_reflection=True` 提交被 `ERR_LOCKED` 拦截，去掉重试 + 伴随重提导致同代生成 3 条 L1（P23，DB 实证 `[L1-N_Q3-011/012/013]`）**。

#### 4. P1 / P2 / P14 / P24 / P25 / P26 源码精确定位
- **P1 & P14（`isolated_runner.py` 执行契约与临时沙箱死链）**：
  - [`isolated_runner.py:51`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/evaluators/isolated_runner.py#L51) 用 `runpy.run_path(str(cand_file), run_name="__main__")` 加载候选，导致含 `if __name__ == "__main__":` 的本地测试逻辑在 Stage A 误执行（P14）；
  - [`isolated_runner.py:344-354`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/evaluators/isolated_runner.py#L344-L354) 强制所有候选必须跑 Stage A 输出 `candidate_output.json`，未文档化仿真策略如何交接给 Stage B（P1）；且 `with tempfile.TemporaryDirectory` 退出即销毁临时目录，使持久化 `cand_out_<hash>.json` 中的 `program` 沙箱路径变成死链，导致后续 `lazy_reval` 的 `STAGE_B_ONLY` 必报 `PROGRAM_FILE_MISSING`！
- **P2（Stage B 30s 硬超时）**：
  - [`isolated_runner.py:315,445,497,541`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/evaluators/isolated_runner.py#L315) 固定 `timeout_sec: float = 30.0`；[`mcp_tools_research.py:1017-1022`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_tools_research.py#L1017-L1022) 与 [`mcp_tools_governance.py:1477-1485`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_tools_governance.py#L1477-L1485) 调用时均未传入配置或读取 `evaluator_spec`。
- **P24（幂等键漏洞放行同观测重复 VALID）**：
  - [`db_schema.py:284`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/db_schema.py#L284) 仅设 `UNIQUE (node_id, run_claim_id)`；[`mcp_tools_research.py:970-973`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_tools_research.py#L970-L973) 仅按 `(node_id, run_claim_id)` 判幂等，对相同 `(candidate_hash, evaluator_spec)` 换个 `run_claim_id` 即可重复写入 `VALID`（实测 `[Obs001]/[Obs002]` 与 `[Obs011]/[Obs012]/[Obs013]`）。
- **P25（看板在 2000 字腰斩截断 + Local-Sweep 重复膨胀）**：
  - [`mcp_core_helpers.py:624-629`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_core_helpers.py#L624-L629) 在 `sec4` 很长时，因 L628 `max(180, ...)` 保底加上分隔换行导致拼接串超过 `max_chars`，随即由 L629 末尾的 `[:max_chars]` **在 §5 正文中间硬切腰斩**；
  - 同文件 L544-572 既按关键字扫 A 栏又遍历 `local_sweeps_json` 导致同类 `[Local-Sweep]` 双重进入 `sec4`；同时 [`mcp_tools_research.py:1421`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_tools_research.py#L1421) 在 `submit_node_handoff` 结束时执行 `set_meta(rw_conn, f"custom_briefing:{node_id}", None)` 直接抹掉伴随助手定制的完整看板。
- **P26（`[Obs009]/[Obs010]/[Obs011]` 变 `PENDING_REVALIDATION` 却不在队列的真正源码根因）**：
  - [`mcp_tools_research.py:1297-1314`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_tools_research.py#L1297-L1314)：
    ```python
    late_or_stale = (
        int(bound_state_version) < cur_state
        or int(eval_epoch_version) < cur_epoch
        or has_invalid_ref
    )
    if late_or_stale:
        rw_conn.execute(
            "UPDATE observations SET comparable_rank_score = NULL, "
            "validity_state = CASE WHEN validity_state = 'VALID' THEN 'PENDING_REVALIDATION' ELSE validity_state END "
            "WHERE node_id = ?", (node_id,)
        )
    ```
  - 时序铁证（核自 `greatwall.db`）：`17:36:35.233Z` 时 `invalidate_observation`（针对 `[Obs012]/[Obs013]`）把 `state_version` 推至 `4`；随后在 `17:38:03.413Z`（`[L1-N_Q3-014]`）与 `17:38:57.729Z`（`[L1-N_Q3-015]`），Q3 调用 `submit_node_handoff` 时仍传 `bound_state_version = 2`（DB 中 `N_Q3.bound_state_version` 至今为 `2`）。触发 `late_or_stale = True` 后，**这段代码无差别把 `N_Q3` 下全部历史 `VALID` 观测（`[Obs009]/[Obs010]/[Obs011]`）改为 `PENDING_REVALIDATION`，却完全忘了将它们追加到 `system_meta.pending_revalidation`**！
  - 叠加缺陷：① `observations` 表缺 `updated_at` / `validity_reason` 字段（[`db_schema.py:261-285`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/db_schema.py#L261-L285)）；② [`erase_and_queue_observations`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_core_helpers.py#L821-L822) 跳过非 `VALID` 行；③ [`_execute_lazy_reval_unlocked`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_tools_governance.py#L1419-L1450) 只读 `pending_revalidation` 队列且不支持按 `obs_id` 定向重评，导致这三条观测落入“MCP 工具面无法触达的孤儿态”。
- **额外发现（`init_parse0` 重置不净与 P20 方括号不一致）**：
  - [`mcp_tools_governance.py:1628-1686`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_tools_governance.py#L1628-L1686) 允许 3 角色调用（P4）、不校验 `root_nodes >= 1`，且在 Epoch 2 重新 `init_parse0` 时**不清理/隔离 Epoch 1 的 `lineage_nodes`、`method_families` 与 `consecutive_non_l1_handoffs`**，致使 Epoch 1 的 `N001/N002/N003` 在 Epoch 2 仍保持 `active` 并被五车道分配（`STAGNATION_APPLIED.md`）；
  - [`mcp_tools_research.py:804-822`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_tools_research.py#L804-L822) 的 `query_library_mcp` 未像 `validate_handoff_refs_exist` 那样对 `entry_id` 做方括号归一化，导致不带方括号查询跨血统 L1 时静默返回空数组、带方括号才报 `ERR_LOCKED`（P20）。

#### 5. `fork_branch` 报错原因取证（Epoch 2 4 次 `orthogonal` 失败 vs 2 次 `lateral` 成功）
只读核查 `greatwall.db` 与 [`mcp_tools_governance.py:851-957`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_tools_governance.py#L851-L957) 证实：
1. Epoch 2 Parse 0 阶段（`16:28:16Z–17Z`）已通过 `register_method_family` 将 11 个新增学派（含 `F_Q3_SEQ_LOCK`、`F_Q3_BAYES_GAIN` 等）全部提前写入 `method_families` 表（总计 18 条）；
2. `02:15Z`（北京 10:15）[`Q3_CLOSURE_RETRACTION.md:43`](file:///D:/Documents/deepseek%20harness/v6第二轮测试/05_supervisory/Q3_CLOSURE_RETRACTION.md#L43) 决定将 `F_Q3_SEQ_LOCK`、`F_Q3_BAYES_GAIN` 作为 `N_Q3` 的 `orthogonal` 子分支派发；
3. **为何 4 次 `orthogonal` 全军覆没（`ERR_CONFLICT`）**：看 `mcp_tools_governance.py:881-887`：
   ```python
   for mf in rw_conn.execute("SELECT family_id, mechanism_signature FROM method_families").fetchall():
       is_dup, sim = check_mechanism_similarity(mech_sig, str(mf["mechanism_signature"]))
       if is_dup:
           raise FailClosedError(ERR_CONFLICT, f"方法族谱防撞车拦截：机理 ... 与现有学派 {mf['family_id']!r} 实质同质 ...")
   ```
   - 当调用者传 `fork_type="orthogonal"`、`family_id="F_Q3_SEQ_LOCK"` 及对应的 `mechanism_signature` 时，循环扫描了全表所有 `method_families` **而没有跳过 `mf["family_id"] == target_family`**！导致新分支的机理签名**直接和自己已预登记的 `F_Q3_SEQ_LOCK` 碰撞（相似度 1.00 ≥ 0.78）**，必抛 `ERR_CONFLICT`！
   - （对照验证：Python 计算 Epoch 1 `F_SEQUENTIAL_LOCK` vs `F_Q3_SEQ_LOCK` 相似度为 `0.6275`、Epoch 1 `F_ADAPTIVE_BAYES` vs `F_Q3_BAYES_GAIN` 为 `0.6346`，均低于阈值 `0.78`，故真正导致冲突的正是**预登记学派与自身的自撞车 Bug**！）
4. **为何改用 `lateral` 后 2 次立即成功（`N_9a1b8b04`、`N_d25fe5ee`，`02:15:49Z`）**：
   - `lateral` 分支（L899-913）**完全跳过 `method_families` 查重**，但 L858 仍允许携带 `family_id="F_Q3_SEQ_LOCK"` / `"F_Q3_BAYES_GAIN"` 落库 `lineage_nodes`；
   - 且当不传 `briefing_snapshot_md` / `variant_hypothesis` 时，`if parent_id and brief_raw:` 为 `False`，连同父兄弟查重也一并跳过，随后由 L943 自动合成看板。

---

## 三、综合归因矩阵（模型问题 vs 插件源码缺陷/设计缺失）

| 问题现象 / 编号 | 相关角色 / 会话 | 主要归因属性 | 详细归因拆解（插件缺陷 vs 模型行为） | 精确源码 / 账本证据位置 |
| :--- | :--- | :--- | :--- | :--- |
| **Root 越权当大脑、起草契约并代行总管 / `write` `.py` 未遂（C4）** | Root `session-56a36cab` / `logistics_coordinator` | **混合（插件制度缺失诱发 + 模型越位）** | **插件**：无 `logistics_coordinator.md`、`autoDispatchSubagents=false`、Root 无关键词导致无契约注入且非 MCP 门禁全空；**模型**：主动在 `AGENT_PROTOCOL.md` §2 写死总管归 Root、抢跑发车、尝试写 `check_db.py` | `prompts.js:8-14`, `index.js:37,205-218`, `event_bus.js:44-54`, `gate.js:172`, `epistemic_edges` (`fedge_178be0d35b6e`) |
| **P0：Subagent 工具隔离弱，Preset 未生效** | 全员子代理 | **宿主限制 + 插件防御退化** | DSH `subagent` 不暴露 `preset`；插件的 `greatwall-roles.cordis.yml` 未被读取、`windows-acl` 只探不设；`gate.js` 靠不对称黑名单撑着且漏检多个角色 MCP 与 `pwsh` 相对路径 | `presets/greatwall-roles.cordis.yml`, `worktree_and_acl.js:67-95`, `gate.js:148-245` |
| **P19 / P23 / P11：0 行代码触 `37%`、解锁被拒、同代打出 3 条 L1** | `explorer` / `lineage_companion`（Q1/Q2/Q3） | **100% 插件源码缺陷** | ① `178,500` 硬封顶且未扣除系统/全量工具基线；② JS `TokenMeter` 未回传 Python 账本，DB 中 `reflect_hint_sent` 恒 `false`；③ `submit_node_handoff` 把解锁、覆写手记、必写 L1 强耦合；④ `companion` 等文件缺零 VALID 协同说明 | `index.js:39,310-315`, `event_bus.js:198-199`, `mcp_core_helpers.py:236,289`, `mcp_tools_research.py:1323-1332,1383-1406` |
| **P10 / P18 / P22：读 `EXPLORER_GUIDE`、自身 `Q1..Q4` 及提交候选被拦** | `N003` / `N_Q1..N_Q4` `explorer` | **100% 插件源码 Bug** | ① `BRANCH_DIR_SEGMENT_RE` 误吞共享文件名；② `extractCanonicalNodeRoot` 与 `extractNodeIdFromText` 硬编码只认 `n\d{1,5}`，与 `N_Q1..N_Q4 ↔ Q1..Q4` 必冲突；③ `gate.js` 将 `candidate_path` 纳入路径检查拦停 `submit_trial_observation` | `worktree_and_acl.js:16,24-33,43-61`, `event_bus.js:36`, `gate.js:71,213-215`, `epistemic_edges` (19 次自身误杀 + 1 次 P10) |
| **0 盲审（`reviews=0`）却产出 `Q3_CLOSURE` 与正式论文草稿；散文长文泛滥** | `central_library` / `lead` / `supervisory` | **混合（插件无全局结案门禁 + Prompt 降级 + 模型未遵循指令）** | **插件**：① 仅 `triage_decision(L1)` 查 `reviews`（还漏判 `stage2_verdict is None`），对写 `.md` 结案/`L3` 调查/`family_status` 全无硬门禁；② `agents/*.md` 压成 47–75 行提纲，删掉了 Stage 3 三段式与盲审 JSON 示例；**模型**：跳过盲审直接写 `Q3_CLOSURE.md`，且 `lead` 越权写含不可追溯数字的论文草稿 | `mcp_tools_governance.py:55-162,772-789`, `gate.js:148-158`, `core_python/agents/*.md`, `greatwall.db` (`reviews=0`) |
| **P16：分诊调用虚推停滞计数且丢弃理由** | `logistics_coordinator` | **100% 插件源码缺陷** | `triage_decision` 对未交接节点或复诊节点均执行 `non_l1 += 1`，且库表无 `triage_log` / 未存 `rationale` | `mcp_tools_governance.py:708-712,825-829`, `db_schema.py` |
| **P1 / P2 / P14：仿真/无模拟器线难交 VALID、30s 硬超时、`__main__` 踩坑** | Q1/Q2 `explorer` / `works_engineer` | **插件架构/文档缺口** | `isolated_runner.py` 强制 `runpy("__main__")` + 仅支持 Stage A `run(public_input)` + 硬编码 `timeout_sec=30.0`，且 `agents/*.md` 未写明接口规范 | `isolated_runner.py:51,315,445,497`, `mcp_tools_research.py:1017` |
| **P12 / P13 / P24：双写 `domain_hook.py` 与同 hash 重复 VALID 观测** | `works-engineer` / `works-baseline` / Q3 g2 / `lead` | **混合（模型操作失误 + 插件无去重/无租约）** | **模型**：`lead` 并行派双工造司写同文件；`works-baseline` 预测与代码不符；Q3 g2 连交 3 次同参数观测；**插件**：仅按 `(node_id, run_claim_id)` 判幂等，未对 `(candidate_hash, spec)` 查重且未记录 `domain_hook_sha256` | `db_schema.py:284`, `mcp_tools_research.py:970-973` |
| **P15：管理会话 `READ` 边归因到 `N001`/`N003`** | `session-56a36cab` / `logi:main` | **100% 插件源码 Bug** | `tools/pre-execute` 用管理会话最后一次 MCP 参数里的 `node_id` 覆写该会话 `rec.nodeId`，随后 `fact_bridge.py` 把后续文件读取全记到该节点名下 | `index.js:300-305,357`, `fact_bridge.py:49` |
| **P20：`query_library_mcp` 跨血统 L1 静默空 vs `ERR_LOCKED`** | Q2 `explorer` | **100% 插件源码 Bug** | 与 `validate_handoff_refs_exist` 不同，`query_library_mcp` 未对 `entry_id` 做方括号归一化 | `mcp_tools_research.py:804-822` vs `db_schema.py:552-560` |
| **P25：重合成看板在 §5 中途腰斩 + `[Local-Sweep]` 膨胀** | Q4 g2 / `lineage_companion` | **100% 插件源码 Bug** | ① `synthesize_lineage_briefing` 在 `sec4` 膨胀后末尾强切 `[:2000]`；② 同源 Sweep 双路径抓取；③ `submit_node_handoff` 主动清空人工定制看板 | `mcp_core_helpers.py:544-572,624-629`, `mcp_tools_research.py:1421` |
| **P26：`[Obs009]/[Obs010]/[Obs011]` 变 `PENDING` 且不在队列 + `STAGE_B_ONLY` 失效** | `N_Q3` / `works_engineer` | **100% 插件源码 Bug** | ① `submit_node_handoff` 触发 `late_or_stale` 时改标 `N_Q3` 全量 `VALID` 为 `PENDING_REVALIDATION` **却漏入 `pending_revalidation` 队列**；② 表无 `updated_at/validity_reason`；③ `Stage A` 临时目录退出即删导致 `STAGE_B_ONLY` 死链 | `mcp_tools_research.py:1297-1314`, `db_schema.py:261-285`, `isolated_runner.py:344`, `mcp_tools_governance.py:1419-1486` |
| **Epoch 2 `fork_branch` 4 次 `orthogonal` 失败、2 次 `lateral` 成功** | `logistics_coordinator` | **100% 插件源码 Bug** | `orthogonal` 查重 `method_families` 全表未排除 `target_family` 自身，撞死在 Parse 0 预登记的同 ID 学派上；`lateral` 跳过 `method_families` 且 `brief_raw` 为空时跳过兄弟查重 | `mcp_tools_governance.py:858,881-913` |
