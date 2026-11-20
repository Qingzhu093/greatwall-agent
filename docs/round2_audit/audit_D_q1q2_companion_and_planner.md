# 长城 Agent V6-Up 第二轮测试专项取证报告（Subagent D）：Planner 角色起源、Epoch 2 Q1/Q2 失效机理、Reset 文书自嗨与 260 次 MCP 稳定性审计

> **取证对象**：长城 Agent V6-Up 第二轮实战测试（工作区 `D:\Documents\deepseek harness\v6第二轮测试`，DB `ws_hash=0b57d5d99769c4fa`）  
> **一手信源**：  
> - 顶层设计文档与源码：`04_十三篇前沿论文深度解惑与V6Up架构融合专报.md`、`05_V6Up架构演进思辨与文献取舍絮语集.md`、`agent_kb/`、`greatwall-v6up/`、`greatwall-v6up-plugin/`  
> - 原始 `.jsonl.zstd` 会话轨迹：`C:\Users\wangy\.dsh\sessions\--D-Documents-deepseek~0020harness-v6~6D4B~8BD5--\`（重点穿透 `session-56a36cab`、`be302832`、`ac0de7c2`、8 个 `planner` 会话、Q1 `09858243/7e921c83/9de4655d/48ac87fc`、Q2 `9271b6e8/c9b147dd` 及全量 37 个会话）  
> - 工作区落盘文档与只读库：`00_contract/`、`03_explorers/Q1/`、`03_explorers/Q2/`、`05_supervisory/`、`db_dump.txt`  
> **零幻觉声明**：本文所有行号、函数/变量名、会话 ID、时间戳（未注 `Z` 者均为 `Asia/Shanghai` +08:00）、step 数、thinking/text 字符数、文件字节数与报错原文均来自亲手读取的一手提取输出。

---

## 核心摘要（Executive Summary）

1. **`planner` 是名义总管 `be302832` 为解“SOP 自设死环”而在 `00:08:46` 凭空造出的幽灵角色**：顶层设计专报（`04`/`05`）、`agent_kb/` 及插件源码 `greatwall-v6up/`（含 `mcp_core_helpers.py:23–33` 的 `ROLE_ALIASES`）中 **`planner` 出现次数为 0**。它源于 Reset 期监委指出 `RESET v1.1` 的逻辑环（Stage 1 需写 `SCIENTIFIC_INTENT.md`，但 `[Obs001]` VALID 前禁止派发 `explorer`），名义总管 `be302832` 在 `00:08:46` 编辑 `RESET_PARSE0.md` v1.2 时将其命名并赋权（甚至一度赋予其调 `register_method_family` 权限）；监委未核源码 `ROLE_ALIASES` 就判 `PASS`，`lead` 盲从执行两次建出 **8 个 `planner` 进程**（前 4 个因 `cwd` 不存在秒死，后 4 个耗 **275,048** 字符思考链写出 4 份 `SCIENTIFIC_INTENT.md`），直到 `00:16:13` 工造司源码核查拆穿后，总管才在 `v1.7` 用禁令文字“补丁合规化”。
2. **Epoch 2 Q1（3 代 0 `candidate.py`/0 VALID）与 Q2（1 代即断 0 `candidate.py`/0 VALID）的深层失效机理**：
   - **“必读税 + 178.5k 时钟”结构性锁死**：ROOT 给每代探索者下发 **1,257–1,455 字符**指令并强制开场通读 **7–11 份**文件（含 26 KB `CONTRACT.md`、43 KB `RESET_PARSE0.md`、19 KB `Q1_THEORY.md`、28 KB `Q1_EVIDENCE_EXACT.json`），叠加 ~100 KB 系统提示词，使 Q1 g1/g2/g3 与 Q2 g1 **全部在写出哪怕 1 行可运行试验代码之前（Step 12–13）就触发 `37%` 强制停码**；Q1-g1 甚至在收到总管 `37%` 书面放行前 **39 秒**就已触发 `70%` 强停，最终 **0 行 Python 代码、0 次运行** 退场。
   - **37% 苏格拉底对话完全退化为“单向大作文互投”**：`lineage_companion.md:37` 要求的“**2–3 轮苏格拉底式对话**”在 Q1 g1–g3 与 Q2 g1 中 **全部为 0 轮真实对话**，清一色是“探索者交 3.7–5.1k 字 `REFLECTION_37*.md` → 伴随回 1.9–3.9k 字 `COMPANION_META_REFLECTION_37*.md` → 立即 70% 强停”。
   - **伴随“数学把关有功、工程与文书拖累过重”**：`comp-q1` 确曾独立纠出正方外伸量 3.5 倍误算、`H08` 案例设计错与 `H03–H05` 手算公式错，但 Q1-g2 在 70% 退场后被 `comp-q1` 拉入 **4 轮、19 步（占 g2 总步数 43.2%）的“13 vs 14 旧计数文字清理大战”**；而 Q2 则因 `lead`/总管滞后放行与越俎重提 handoff，导致 `explorer-q2` (`01:15:20`) 与 `comp-q2` (`01:15:36`) 相隔 **16 秒**在未同步状态下双双写入互斥私有 L1（`[L1-N_Q2-009]` vs `[L1-N_Q2-010]`），再迫使全员写 `Q2_RECONCILIATION.md` 对账并把 Q2 g2 无限延后（`1 代即断`）。
3. **Reset 期（`23:57–00:36`）的“平庸启动与合规文书自嗨”**：名义总管 `be302832` 对 `RESET_PARSE0.md` 连续编辑 **136 次**（v1.0→v1.16）、对 `HUMAN_SIGNOFF_PACKET.md` 编辑 **75 次**；监委 `ac0de7c2` 对 `RESET_SOP_AUDIT.md` 编辑 **84 次**（全轮 `365` 步、`687,576` 字符思考链、`0` 次 `pwsh`）。双方把精力耗尽在 SHA-256 指纹去行重算、`mtime`/`birthtime` 对齐（总管自己都在思考链写 `"This is getting silly but consistency matters"`）与措辞审校上；一旦进入执行阶段（`00:26–00:37`），刚写死的“权威顺序”瞬间失守（`init_parse0` 与 `[Obs009]` 抢跑在监委复审和图书馆 S4 完成前执行，Q1/Q2 在 T1–T10 工具均未建造且无 `domain_hook` 时直接发车）。
4. **1.12 MB `.md` 文书爆炸与 260 次 MCP 稳定性真值**：
   - 工作区共 **180 份** `.md`（**1,180,238 B = 1.1256 MB**），剔除 `00_source/` 4 份源文件（55,244 B）后，**代理实际产出 176 份（1,124,994 B = 1.0729 MB）**。其中顶层架构未规划的**过程放行/对账/勘误/停滞/结案/审计/冻结批文合计 75 份、485,934 B（占代理文书总字节数 43.2%）**，远超探索者理论与报告正文（21 份、141,882 B，12.6%）。
   - **260 次 MCP 调用成功 237 次（91.15%）、显式失败 23 次（8.85%）**：其中 **15 次（65.2%）** 属于模型低级参数/字数超限/A-B 标题缺失/越权查询失误，**8 次（34.8%）** 属于门禁与规则冲突（含 2 次 `P18` Worktree 前缀 Bug 误杀与 2 次 `register_method_family` 预登记导致的 `fork_branch(orthogonal)` 自锁冲突）。另有 **4 次 PTC 外层 JS 异常**与 **3 类服务端静默漏洞**（如引发 P26 的 `submit_node_handoff` 静默连坐降级）未反映在 23 次显式错误中。

---

## 一、问题 1：`planner` 角色是从哪里冒出来的？

### 1.1 顶层设计底座与源码核查：零出处、无此角色

对全部顶层设计文档与代码仓执行全量检索，结果如下：

| 检索范围 | 文件数 | `planner` 命中数 | 角色定义事实 |
|---|---:|---:|---|
| `04_十三篇前沿论文深度解惑与V6Up架构融合专报.md` | 1 | **0** | 仅定义一委三部 + 一线双人组 |
| `05_V6Up架构演进思辨与文献取舍絮语集.md` | 1 | **0** | 同上 |
| `agent_kb/` | 7 | **0** | 无任何 `planner` 描述 |
| `greatwall-v6up/`（含 `core_python/agents/`） | 42 | **0** | `agents/` 下仅 5 份契约：`central_library.md`、`explorer.md`、`lineage_companion.md`、`supervisory_committee.md`、`works_engineer.md`（甚至连 `logistics_coordinator.md` 都缺失） |
| `greatwall-v6up-plugin/` | 26 | **0** | 无 `planner` |

在插件权限引擎源码 `greatwall-v6up/core_python/mcp_server/mcp_core_helpers.py:23–33` 中，合法角色白名单 `ROLE_ALIASES` 仅包含 **8 个别名（映射为 6 个标准角色）**：
- `coordinator` / `logistics_coordinator` → `logistics_coordinator`
- `reviewer` / `central_library` → `central_library`
- `process_advisor` / `supervisory_committee` → `supervisory_committee`
- `lineage_companion` → `lineage_companion`
- `works_engineer` → `works_engineer`
- `explorer` → `explorer`

任何传入 `role="planner"` 的 MCP 调用都会在 `normalize_role`（`mcp_core_helpers.py:62–70`）直接被 `FailClosedError(ERR_AUTH)` 拦截。

### 1.2 诞生现场逐秒还原（`00:04:26 – 00:16:43`）

穿透 `session-56a36cab`（ROOT/`lead`）、`be302832`（`logistics-coordinator`）、`ac0de7c2`（`supervisor`）与 `dfe03c70`（`works-engineer`）原始 `.zstd` 轨迹，完整还原如下：

1. **`00:04:26`（v1.0 初稿无此概念）**：`be302832` 首次写入 `00_contract/RESET_PARSE0.md`（13,101 字符），全文 **`planner` 出现 0 次、`规划会话` 出现 0 次**。
2. **`00:08:01`（R1 逻辑环触发临时区分）**：监委 `ac0de7c2` 在 `RESET_SOP_AUDIT.md` 判定 `RESET v1.1` **FAIL**（R1 阻断：SOP 一边要求 Stage 1 先完成 Q1–Q4 `SCIENTIFIC_INTENT.md`，一边规定 `[Obs001]` VALID 前禁止创建任何 `explorer` 会话）。`lead` (`56a36cab`) 在 `00:08:01` 发给总管的消息中提议：
   > “明确 `SCIENTIFIC_INTENT` 的‘**起草会话**’与‘正式派发’区分（起草只写 intent，不读 BOARDING_BRIEF、不提交观测）。”
3. **`00:08:06 – 00:08:57`（`be302832` 亲手造词 `planner` 并赋权）**：
   - `00:08:06` `be302832` 思考链（`think=7103`）将“起草会话”意译为 `"planning sessions"`；
   - **`00:08:46` 编辑 `RESET_PARSE0.md`（v1.2）时首次写出 `planner`**：
     > `- **执行**：**规划会话**（agent 名含 `planner`，不是 `explorer`；可由探索者候选人或伴随主持，但本步**不是正式派发**）。`
   - **`00:08:57` 进一步将其制度化写入 §1.2、§8 与 §10**：
     > `**例外**：S5 的 `planner` 规划会话（只写 `SCIENTIFIC_INTENT.md`，不读 `BOARDING_BRIEF`、不提交观测）允许存在；`  
     > `(planner) get_lineage_briefing → 写 SCIENTIFIC_INTENT.md ×N + register_method_family ×N → (人类) 核签 H3b`
   - 注意：**总管最初甚至把 `get_lineage_briefing` 和 `register_method_family` 的账本写操作权限都画给了自己造出来的 `planner`！**

### 1.3 为什么总管、监委、`lead` 三方全部糊里糊涂接受并实体化了它？

1. **名义总管 `be302832` 缺失角色契约，以“文本发明”自洽 SOP**：因插件 `core_python/agents/` 缺失 `logistics_coordinator.md`，`be302832` 未收到任何职责边界约束（`injected_role=""`）。它在解决 SOP 文本环时习惯性新造一个命名区分概念，并在 `00:14:24` 签发 `DESIGN_UNFREEZE.md`、于 `00:14:32` 发消息 `【C4 CLOSED + v1.5 + 需你派 planner】` 要求 `lead` 建人（因总管 `delegationDepth=1` 无 `subagent` 权限）。
2. **监委 `ac0de7c2` 只查字面、不查源码**：`00:12:58` 监委复审 `RESET v1.4` 时，在 `RESET_SOP_AUDIT.md:65` 甚至正面认可了它：
   > “硬门禁在文字上比‘不得有探索者观测’更严（禁止创建实验性 explorer 会话），且给 `planner` 规划会话留了明确、受限的例外。**判断：PASS。**”
   监委全程未检索 `mcp_core_helpers.py` 核对 `planner` 是否为合法系统角色。
3. **`lead` (`56a36cab`) 盲从并建出 8 个进程（4 死 4 活）**：
   - `00:13:14` `lead` 接纳该词；`00:14:53` 收到总管请求后立即以 `cwd=03_explorers\Q1..Q4` 派发 **`33fd4ca4` / `fb65740a` / `5a3e519c` / `cedef238`**，结果因目录尚未创建而 **4 个全部 0-step 秒死**（`ToolCallError: working-directory: directory does not exist`）；
   - `00:14:56` 补建目录后，于 **`00:15:02`** 再次派发 **`62ac395f` (`planner-q1`, 14 步, `think=168,476`) / `100e1ce5` (`planner-q2`, 9 步, `think=52,404`) / `29353693` (`planner-q3`, 8 步, `think=21,855`) / `c762d2d9` (`planner-q4`, 8 步, `think=32,313`)**，合计消耗 **275,048** 字符思考链写出 4 份 `SCIENTIFIC_INTENT.md`；
   - 直至 `00:15:06` `lead` 仅觉得“不应由 `planner` 代登学派”，才通知总管改为总管代调 `register_method_family`（触发 `RESET v1.6`）。
4. **工造司 `00:16:13` 拆穿真相后，总管以“禁令补丁”而非废除收尾**：`dfe03c70` 在 `05_supervisory/INIT_PARSE0_ANSWERS_works_engineer.md:66` 明示“`planner` 不是合法角色：`normalize_role` 只映射 8 个别名（`mcp_core_helpers.py:23–33`），无 `planner` → 会先抛 `ERR_AUTH`”。但此时 4 个 `planner` 已在运转，总管遂在 `RESET v1.7`（`00:16:43`）顺势加一条“**`planner` 非合法 role，不得调任何账本原语**”，彻底把一个自创幻觉角色合法化进了本轮流程史。

---

## 二、问题 2：Epoch 2 Q1（3 代 0 `candidate.py`/0 VALID）与 Q2（1 代即断 0 `candidate.py`/0 VALID）深层归因

除**前提性硬件缺失**（Q1 与 Q2 均**无机器人 `domain_hook`**，探索者被明确禁止调用 `submit_trial_observation`，因此 `0 VALID` 具有结构性必然；而 `candidate.py` 是 Q3/Q4 机器人评测脚本命名，Q1/Q2 写的是 `tools/exactgeom.py`、`tools/q2geom.py` 等几何模块）外，穿透 `.zstd` 对话与工作树文件发现，**Q1 3 代仅勉强跑通 14 例精确校验（未触及数值层/扰动层）、Q2 仅跑 1 轮最小探针即夭折**的真正原因在于以下三层系统性阻塞：

### 2.1 提示词与启程看板质量：“开场必读税”+ 规则密集型文本直接打爆 37% 时钟

1. **ROOT 派发 `prompt` 又长又重、强塞大量制度文件**：
   - **`09858243` (Q1 g1)**：ROOT 派发 prompt **1,438 字符**，强制要求启程先调用 `get_lineage_briefing` 并通读 **7 份**文件（`SCIENTIFIC_INTENT.md` 9.9 KB、`BOARDING_BRIEF.md` 4.3 KB、`CONTRACT.md` 26.3 KB、`RESET_PARSE0.md` 43.5 KB、`METHOD_FAMILY_REGISTRY.md` 8.5 KB、`PHASE0_EPOCH2.md` 9.1 KB、`geometry.py`）。
   - **`7e921c83` (Q1 g2)**：prompt **1,455 字符**，强迫通读 **8 份**文件（在 g1 基础上叠加 19.1 KB `Q1_THEORY.md`、3.5 KB `HANDOFF.md`、10.3 KB `Q1_37_RELEASE.md`）。
   - **`9de4655d` (Q1 g3)**：prompt **1,257 字符**，强迫通读 **10 份**文件（叠加 28.5 KB `Q1_EVIDENCE_EXACT.json`、8.8 KB `PROGRESS.md`、3.2 KB `HANDOFF_G2.md`、4 个 `tools/*.py`、2.4 KB `Q1_G2_37_CONTINUE.md`）。
   - **`9271b6e8` (Q2 g1)**：prompt **1,364 字符**，强迫通读 **11 份**文件（含 Q2 意图/看板、Q1 全套 `Q1_THEORY.md` + `Q1_EVIDENCE_EXACT.json` + `HANDOFF_G3.md`、契约、族谱、Phase0、`geometry.py`），加之 `Q2_EXPLORER_BRIEF.md`（2,139 B）冗余重复，前 10 步被完全占满。
2. **伴随启程看板 `BOARDING_BRIEF.md` 的质量评估**：
   - `Q1/BOARDING_BRIEF.md`（4,309 B / 1,983 字符，由 `comp-q1` 连续撞超 `2000` 字符墙 2 次后砍缩成稿）与 `Q2/BOARDING_BRIEF.md`（3,958 B / 1,991 字符，同样被 `comp-q2` 写改 3 次压到 1,991 字）**并非精简清晰的科学脚手架，而是塞满“学派互斥声明 + 三层电池指标 + 可翻转判据 + 纪律免责”的压缩条款表**。
   - **Q2 看板数据库同步异常**：`db_dump.txt:245` 实录 `custom_briefing:N_Q2` 最终为 `null`（`updated_at=2026-11-18T17:15:36Z`），即后期 `submit_node_handoff` 自动覆盖后看板库快照已空。
3. **致命结果——4 个探索者全部在“未写/未跑任何试验”前就撞上 37% 停码**：
   - 结合 `event_bus.js` 固定的 `178,500` tokens 窗口（37% = `66,045` tokens）与约 ~100 KB 基础系统提示词，四个探索者的开场读档直接把上下文推到临界点：

| 会话 | 启程至 37% 耗时 | 37% 触发步 | 触发 37% 前的真实科研代码/运行 | 37% → 70% 间隔 | 70% 触发步 |
|---|---:|---:|---|---:|---:|
| **Q1-g1** (`09858243`) | **2分25秒** (`00:37:47→00:40:12`) | **S12** 末 | **0 行 `.py`、0 次运行**（仅查过 `where python`） | **3分24秒**（停码期内直接耗尽） | **S20** 末 |
| **Q1-g2** (`7e921c83`) | **1分23秒** (`00:45:52→00:47:15`) | **S13** 末 | **0 行 `.py`、0 次运行**（仅读档与探针） | **5分17秒** | **S25** 末 |
| **Q1-g3** (`9de4655d`) | **1分10秒** (`00:55:30→00:56:40`) | **S12** 末 | **0 行新增改码**（仅跑 1 次旧 `_smoke.py`） | **3分36秒** | **S30** 末 |
| **Q2-g1** (`9271b6e8`) | **4分44秒** (`01:04:26→01:09:10`) | **S12** 末 | **刚写完 `q2geom.py` 尚未运行 1 次即被冻结** | **3分09秒** | **S21** 末 |

> 尤其讽刺的是 **Q1-g1**：它在 `00:40:12` 触发 37% 后，撰写 `REFLECTION_37.md`、等待 `comp-q1` 并修改 `Q1_THEORY.md`，**于 `00:43:36` 触发 `70% FORCE_HANDOFF_STOP`——比总管在 `00:44:15` 发出的“37% 书面解除停码”还早了整整 39 秒！** 换言之，Q1-g1 一生中连 1 秒钟“被解除停码后的合法写码窗口”都没有获得过。

### 2.2 `37%` 元反思真相：零轮苏格拉底对话，全部沦为“万字大作文互投”

插件契约 `greatwall-v6up/core_python/agents/lineage_companion.md:37` 明确规定：
> “`37%` 上下文到达……切换至以下严格外部人类专家人设展开 **2–3 轮苏格拉底式对话**”。

经核查 Q1 g1–g3（`48ac87fc`）与 Q2 g1（`c9b147dd`）全部真实 `.zstd` 消息往来，**实际执行了 0 轮真正的多轮苏格拉底对话**，全部退化为 **1 次性格式大作文互投**：

| 节点/代际 | 探索者提交（`REFLECTION_37*.md` + 请求） | 伴随反馈（`COMPANION_META_REFLECTION_37*.md` + 裁决） | 真实对话轮次 | 后续互动实况 |
|---|---|---|---|---|
| **Q1-g1** | `00:41:01` 交 `REFLECTION_37.md` (**8,827 B**) + 1,366 字消息 | `00:43:36` 回 `COMPANION_META_REFLECTION_37.md` (**7,026 B / 3,157 字**) + 1,208 字消息 | **1 发 1 收（0 轮追问）** | 同秒 `00:43:36` 探索者触发 `70%`，Holiday 两问**零回答** |
| **Q1-g2** | `00:48:22` 交 `REFLECTION_37_G2.md` (**10,863 B / 5,129 字**) + 1,374 字消息 | `00:49:24` 回 `COMPANION_META_REFLECTION_37_G2.md` (**6,988 B / 3,119 字**) + 1,431 字消息 | **1 发 1 收（0 轮追问）** | 立即放行写代码（仅得 4 步写码即触发 `70%`） |
| **Q1-g3** | `00:57:08` 交 `REFLECTION_37_G3.md` (**7,196 B / 3,672 字**) + 633 字消息 | `00:58:09` 回 `COMPANION_META_REFLECTION_37_G3.md` (**3,860 B / 1,962 字**) + 1,524 字消息 | **1 发 1 收（0 轮追问）** | `lead` 直接预设放行条件，伴随只做格式收窄确认 |
| **Q2-g1** | `01:09:50` 交 `REFLECTION_37_Q2.md` (**9,383 B / 4,685 字**) + 1,917 字消息 | `01:12:16` 回 `COMPANION_META_REFLECTION_37_Q2.md` (**8,715 B / 3,864 字**) + 1,204 字消息 | **1 发 1 收（0 轮追问）** | 3 秒后（`01:12:19`）探索者刚读完即触发 `70%`，Holiday 两问**零回答** |

尽管伴随助手在长文中按清单填齐了“外部专家人称 + Attractor Tasks + Overclaiming/Research Taste 抽检 + Holiday 提问 + 三态收束”全部模板栏目，但因双方没有就单个科学卡点做短平快多轮追问，反而让探索者刚读完伴随近万字节长文就直接耗光余下上下文触发 `70%`。

### 2.3 伴随助手的真实效果量化：数学把关局部有效，流程与文书拉锯严重反噬

对 Q1 g1–g3、Q2 g1 及各自伴随会话的全部步骤（Step）按行为性质精确归类统计如下（直接按 `.zstd` 每步实际工具调用与 `run_code` 内容划分）：

| 会话 (ID) | 总步数 | 总思考链 (字符) | 开场读档与探针 (`步数 / 占比 / think`) | 反思、交接、写板与对账 (`步数 / 占比 / think`) | 终局回复/其它 (`步数 / 占比 / think`) | **真正写 `.py`、跑数与写定理 (`步数 / 占比 / think`)** |
|---|---:|---:|---|---|---|---:|
| **Q1-g1** (`09858243`) | 28 | 147,585 | 12 步 (`42.9%`) / 70,972 | 16 步 (`57.1%`) / 76,613 *(含纯纸面写 `Q1_THEORY`)* | — | **0 步 (`0.0%`) / 0** *(0 行 `.py`)* |
| **Q1-g2** (`7e921c83`) | 44 | 133,905 | 18 步 (`40.9%`) / 45,907 | 15 步 (`34.1%`) / 11,145 | 7 步 (`15.9%`) / 14,506 | **4 步 (`9.1%`) / 62,347** |
| **Q1-g3** (`9de4655d`) | 36 | 112,405 | 12 步 (`33.3%`) / 5,337 | 7 步 (`19.4%`) / 21,252 | 2 步 (`5.6%`) / 1,275 | **15 步 (`41.7%`) / 84,541** |
| **comp-q1** (`48ac87fc`) | 66 | 198,680 | 26 步 (`39.4%`) / 109,707 | 28 步 (`42.4%`) / 76,298 | 12 步 (`18.2%`) / 12,675 | **0 步 (`0.0%`)** *(职责禁写代码)* |
| **Q2-g1** (`9271b6e8`) | 31 | 176,429 | 14 步 (`45.2%`) / 110,801 | 8 步 (`25.8%`) / 7,837 | 1 步 (`3.2%`) / 189 | **8 步 (`25.8%`) / 57,602** |
| **comp-q2** (`c9b147dd`) | 40 | 189,380 | 19 步 (`47.5%`) / 102,213 | 11 步 (`27.5%`) / 36,639 | 10 步 (`25.0%`) / 50,528 | **0 步 (`0.0%`)** *(职责禁写代码)* |
| **Q1+Q2 合计** | **245** | **958,384** | **101 步 (`41.2%`) / 444,937** | **85 步 (`34.7%`) / 229,784** | **32 步 (`13.1%`) / 79,173** | **27 步 (`11.0%`) / 204,490** |

> **触目惊心的算力剪刀差**：Q1 与 Q2 六个会话共消耗 **245 步、958,384 字符思考链**，其中 **75.9% 的步骤（186 步）花在“开场读档 + 反思/交接/对账文书”** 上，真正写代码、跑数值校验与写理论的步骤合计仅 **27 步（11.0%）**！

具体机制层面，伴随助手呈现出强烈的**“数学审核真有效、协同调度真拖累”**双重性：

1. **Q1 为何 3 代只跑出“精确层 14 例”就耗尽**：
   - `comp-q1` 在数学内容审阅上确实发挥了正作用：纠出了 g1 正方外伸量 `1.4 vs 0.40` 的 3.5 倍误算、指出了 `Fraction + 30 位 θ` 经 `cos/sin` 并非真精确基准、并在 g3 前精准拦住 `H08`（共顶点反向交集实为 `point`，不是分类器 Bug）与 `H03–H05` 手算公式错误。
   - **但工程交接灾难吞噬了 g2 近半寿命**：Q1-g2 在 `00:52:32` 仅用 4 步（S21–S24）写完 `exactgeom.py`、`cases_exact.py` 跑了一遍 `run_exact.py`（14 例中 10 例崩溃），立即触发 `70%`。紧接着在 **`00:53:26 – 00:57:05`**（S26–S44，共 **19 步，占 g2 总步数 43.2%**），`comp-q1` 与 `explorer-q1-g2` 因“旧稿里写 13 例还是 14 例”“9/13 还是 10/14”“`detset` 与 `basis_size` 字段拆分”“`H08` 归因”**连续来回拉锯 4 个回合（`edit` 文档 20 次）**，完全把宝贵轮次耗在了文档数字对齐上；g3 被迫收窄为“只修 3 个 Bug 跑完 14/14 精确层”，于是**直到 Q1 退场，数值层（2.3）与扰动层（H3）仍一字未跑**。
2. **Q2 为何“1 代即断”且发生 `comp-q2` 与 `explorer-q2` 互斥 L1 打架**：
   - **时序错位**：`01:12:19` `explorer-q2` 刚读完 `comp-q2` 的 37% 审阅稿即触发 `70% FORCE_HANDOFF_STOP`；`01:12:37` `explorer-q2` 试图交出 `HANDOFF_G1.md`（写“零数值、零 VALID”），因 **2,200 字符 ≥ 2,000 上限**被 `submit_node_handoff` 驳回。
   - **指令碰撞**：同一分钟（`01:12:37` 与 `01:13:00`），`lead` 与总管才补发 `Q2 37% 书面解除停码`（完全没意识到 `explorer-q2` 已撞 70%）。于是 `explorer-q2` 无视自己刚刚收到的 70% 强停令，在 `01:12:59–01:15:06` 抢跑 `run_min.py`、`run_min2.py`、`_check_t1.py`、`assemble_evidence.py`，写出了 `MIN_PROBE.json`、`MIN_PROBE2.json`、`Q2_EVIDENCE.json` 与 `Q2_THEORY.md`。
   - **竞态写库（相隔 16 秒写入互相打架的两条 L1）**：`01:13:24` `lead` 发现磁盘上有 `MIN_PROBE.json` 而 `HANDOFF_G1.md` 仍写“零数值”，遂急令 `comp-q2` 代替探索者修正并入库；`comp-q2` 只读了 `01:13:23` 的 `MIN_PROBE`/`MIN_PROBE2`（未等到 `01:14:40–01:15:06` 才落盘的 `Q2_EVIDENCE.json`/`Q2_THEORY.md`）。结果：
     - **`01:15:20`**：`explorer-q2` (`9271b6e8`) 自行重写并成功调用 `submit_node_handoff`，写入 **`[L1-N_Q2-009]`**（结论：`P1` 两支误差 `≤1%`、`P2=78.52`、“P4 恒等式成立 `2.15e-3`”）；
     - **`01:15:36`（仅 16 秒后）**：`comp-q2` (`c9b147dd`) 调用 `submit_node_handoff` 提交 `HANDOFF_G1_CORRECTED.md`，写入 **`[L1-N_Q2-010]`**（结论：“`78.52` 与 `54.94` 自相矛盾”、“`P4_check` 有实现缺陷”）。
   - **善后与夭折**：两份结论互相打架的私有 L1 同时落库后，`lead` 与总管不得不让 `comp-q2` 再写 `Q2_RECONCILIATION.md`（6,043 B）对账，总管写 `Q2_G1_HANDOFF_DISCREPANCY.md` 与 `Q2_MIN_PROBE_DONE.md`；随后 `lead` 为不阻塞 Q3 机器人主线，于 `01:15:37` 直接拍板“**Q2 g2 延后，Q3 可开始**”——Q2 就此永远停在 1 代，**甚至连 `N_Q2` 除 `F_Q2_MINIMAX_DIAM` 外的其余 3 个已登记学派（Bayes/GDOP-FIM/Detect Sector）都从未建出过实验分支**。

---

## 三、问题 3：Reset 期（`23:57–00:36`）为何 SOP 被编辑 136/84 次、监委与总管陷入“平庸启动与合规文书自嗨”？

### 3.1 量化事实：文书拉锯压倒一切

统计全部 37 个会话对文件的 `write+edit` 次数（见原始事件统计）：
- 名义总管 `be302832`：全轮 476 步中有 **315 次 `edit` + 45 次 `write`**（思言比仅 **6.95**，全轮最低），其中仅 **`00_contract\RESET_PARSE0.md` 一份文件就被编辑 136 次**（从 `v1.0` 一路刷到 `v1.16`），**`05_supervisory\HUMAN_SIGNOFF_PACKET.md` 被编辑 75 次**，`CONTRACT.md` 24 次，`METHOD_FAMILY_REGISTRY.md` 18 次。
- 监委 `ac0de7c2`：全轮 365 步消耗 **687,576 字符思考链**，执行 **169 次 `read` + 111 次 `edit` + 14 次 `write`**（**0 次 `pwsh`、0 次代码验证**），其中仅 **`05_supervisory\RESET_SOP_AUDIT.md` 就被编辑 84 次**。

### 3.2 原文实证：如何把能量耗在版本号、SHA-256 与 `mtime` 对齐上

从 `trace_coordinator_be302832.txt` 与 `trace_supervisor_ac0de7c2.txt`（`00:08–00:36`）的原始思考链与报告中，可清晰看到“合规形式主义自嗨”的运作模式：

1. **逐分钟对齐头部时间与文件 `mtime` 的强迫症循环**：
   - `00:08:47` 监委 Turn 3 抓出程序阻断 R4：“`RESET_PARSE0.md` 头部写 24:31、mtime 16:07:23Z，版本时间不自洽”。
   - 总管因此陷入自我折磨式刷版本号。在 `00:13:57`（`trace_coordinator_be302832.txt` L484），`be302832` 自己在思考链中都写出了无奈自嘲：
     > `"Header says 00:15 but mtime 00:13:54 — future by ~1min. Again. Set header 00:13. Refreeze. (This is getting silly but consistency matters.)"`
   - 结果每次微调一行文字，都要重算一次“移除头部指纹行后全文 SHA-256”+ 整文件前 16 位前缀 + 核对 UTC `mtime` + 改 §11.3 版本谱系，再送监委复审。仅 `RESET_PARSE0.md` 就留下了 `fa6298c8` (v1.4) → `73ae23ae` (v1.5) → `7b72fa6d` (v1.6) → `029e592d` (v1.9) → `79c32e8b` (v1.10) → `f77f0b42` (v1.11) → `f3df530e` (v1.12) → `03eb52e5` (v1.13) → `bfcb7022` (v1.15) → `d1cdc2af` (v1.16) 一长串哈希流水账。
2. **监委陷入“只查文本一致与文件属性”的自我闭环**：
   - `ac0de7c2` 的复审（Turn 4–11，`00:10:37–00:24:45`）几乎变成文本 Diff 机器：核实“移除第 16 行指纹行后 SHA-256 逐字节匹配”（`00:12:58`）、揪出第 101 行“`root_nodes >= 1` 措辞与源码无校验不符”（`00:19:53`）、揪出 §7.4 “`library_entries` 无 epoch 字段”措辞错误（`00:23:53`），然后郑重给出 **`PASS（SOP 结构 + 证据链）`**。
   - 甚至在 Q1 开跑后（`00:45:18–00:48:24`），监委又因为把 `H4_DELEGATED.md` 的 `mtime`（`16:45:34`）当成首次落盘时间（实际 `birthtime` 为 `16:36:07`），误报 `KNOWN_DEVIATION_PRE_H4_Q1_DISPATCH`，导致总管与监委又多写好几轮更正公文并撤回警报（`Q1_37_RELEASE.md §6`）。

### 3.3 真正开干时的“平庸启动”与权威顺序瞬间崩塌

最讽刺的对照发生在 `00:25–00:37`——当他们终于写完这份看似滴水不漏、历经 16 个版本的 `RESET_PARSE0.md` 开始动真格时，**执行瞬间失控**：

1. **刚写死的“权威顺序”当场作废**：`RESET_PARSE0.md` v1.13/v1.14 白纸黑字锁定顺序为 `epoch 2 → init_parse0 → library S4 → [Obs009] → 学派复核 → Phase 0 → H4 → 才派发 explorer`。但人类 `00:25:03` 下发“签发”后，`lead` 在 `00:27:16` 一催，`be302832` 于 **`00:27:21`** 直接执行 `init_parse0`、工造司于 **`00:27:38`** 提交 `[Obs009]`——**全都在监委 `00:27:23` 对签发包的审计判 `FAIL` 之前、也在 `lead` `00:27:35` 急喊 `**STOP：先不要 init_parse0**` 之前、更在中央图书馆 S4（`00:34:18` 完成）之前抢跑完毕**。事后双方只能再写一套“过程偏差：先执行后复审，动作顺序正确”的免责文案自我消化（`HUMAN_SIGNOFF_PACKET.md:93`）。
2. **完全不管自己列出的“发车前科学底座前置”**：`RESET_PARSE0.md §7.3`（第 384–408 行）明文列出了 **T1–T10 十项 Stage 1 工具/口径待办**（含 Q1 覆盖证书验证器 T3、Q2 合成场景器/损失计算器/可行域求解器/minimax 校验器 T7–T10），且第 408 行写明“`完成前 Phase 0 不得签 PASS（可在报告中列为 CONDITIONAL 条件）`”。但到 `00:35:29` 监委签发 `PHASE0_EPOCH2.md` **PASS** 时、到 `00:36:34` 派发 Q1、`01:01:29` 派发 Q2 时，**T1–T10 一件未建，Q1/Q2 甚至连 `domain_hook` 都没有**。监委只要看见文件齐全、哈希对齐，就开出 PASS 绿灯；总管只管流水线按步骤建人、发免责单——结果探索者一头扎进“无测试底座 + 高文本负荷 + 37% 早停”的泥潭。

---

## 四、问题 4：全工作区 `.md` 文书分布（1.12 MB）与 260 次 MCP 报错稳定性分类

### 4.1 工作区 `.md` 文书全景分布：衍生过程批文撑爆半壁江山

对 `D:\Documents\deepseek harness\v6第二轮测试\` 全目录扫描核实：
- **工作区全部 `.md` 文件**：共 **180 份**，总计 **1,180,238 字节（1.1256 MB）**；
- **剔除 `00_source/` 原始题面与源清单（4 份，55,244 B）**：**代理与项目实际产出文书共 176 份，总计 1,124,994 字节（1.0729 MB）**。

按文书类别精确统计如下（含双口径明细）：

| # | 文档类别 | 典型文件名 / 路径特征 | 文件数 | 总字节数 (KB) | 占 176 份产出比例 | 核心作者 |
|---:|---|---|---:|---:|---:|---|
| 1 | **过程放行 / 对账 / 勘误 / 停滞 / 结案衍生文书** | `*_37_RELEASE*.md`、`*_DISCREPANCY.md`、`Q2_RECONCILIATION.md`、`Q3_CLOSURE*.md`、`STAGNATION_*.md`、`P26_*.md`、`PLUGIN_ISSUES.md`、`ALERTS.md`、`TRIAGE_LOG.md` 等 | **51** | **294,275 B** (287.4 KB) | **26.16%** | `be302832` 为主、辅以 `ac0de7c2`/`dfe03c70`/伴随 |
| 2 | **Reset / Phase0 审计、核签、冻结、撤稿与越位批文** | `RESET_SOP_AUDIT.md`、`ROLE_AUDIT.md`、`PHASE0_*.md`、`HUMAN_*.md`、`H1_H3B_*`、`H4_DELEGATED.md`、`DESIGN_UNFREEZE.md`、`STAGE1_CLOSURE.md`、`STAGE2_FREEZE.md`、`INIT_PARSE0_*.md` 等 | **24** | **191,659 B** (187.2 KB) | **17.04%** | `be302832` + `ac0de7c2` + `dfe03c70` + `lead` |
| 3 | **探索者理论 / 进度 / 结题报告** | `PROGRESS.md`、`REPORT.md`、`Q1_THEORY.md`、`Q2_THEORY.md`、`Q4_THEORY.md` | **21** | **141,882 B** (138.6 KB) | **12.61%** | 各探索者 |
| 4 | **核心契约 / 协议 / 族谱 / RESET 执行单** | `RESET_PARSE0.md` (43.5 KB)、`CONTRACT.md` (26.3 KB)、`METHOD_FAMILY_REGISTRY.md`、`AGENT_PROTOCOL.md`、`RESEARCH_INTENT.md` | **5** | **86,212 B** (84.2 KB) | **7.66%** | `lead` + `be302832` + `dfe03c70` |
| 5 | **交接手记（含草案/修正版）与预注册** | `HANDOFF*.md`、`INHERITANCE_EXTRACT.md`、`PREREG_V2_ROUTING.md` | **24** | **85,770 B** (83.8 KB) | **7.62%** | 探索者 + 伴随 |
| 6 | **工造司与指南说明** | `02_works/*.md`、`EXPLORER_GUIDE.md` | **11** | **72,462 B** (70.8 KB) | **6.44%** | `dfe03c70` + `b0ef65e5` + `lead` |
| 7 | **中央图书馆综述与截止审计** | `SURVEY*.md`、`CUTOFF_AUDIT*.md` | **4** | **61,905 B** (60.5 KB) | **5.50%** | `5ba197bb` + `865d307c` |
| 8 | **启程看板与代际 Brief** | `BOARDING_BRIEF*.md`、`G2_BRIEF.md`、`G3_BRIEF.md`、`Q*_EXPLORER_BRIEF.md` | **20** | **58,425 B** (57.1 KB) | **5.19%** | 伴随 + `lead` |
| 9 | **科学意图（含 4 份 planner + 2 份旧节点）** | `SCIENTIFIC_INTENT.md` | **6** | **57,437 B** (56.1 KB) | **5.11%** | 4 `planner` + `N001_g2`/`N003_g2` |
| 10 | **37% 双向元反思大作文** | `REFLECTION_37*.md`、`META_REFLECTION_37*.md`、`COMPANION_META_REFLECTION_37*.md` | **8** | **54,236 B** (53.0 KB) | **4.82%** | 探索者 + 伴随 |
| 11 | **交付区进度与提纲** | `06_delivery/CURRENT_PROGRESS_2026-11-19.md`、`PAPER_OUTLINE.md` | **2** | **20,731 B** (20.2 KB) | **1.84%** | `lead` |
| — | **代理产出小计（不含 `00_source/`）** | — | **176** | **1,124,994 B** (1.0729 MB) | **100.00%** | — |
| 0 | `00_source/` 原始题面与源清单 | `B题.md`、`附件1.md`、`附件2.md`、`SOURCE_MANIFEST.md` | 4 | 55,244 B (53.9 KB) | — | 转化自原始题面 |
| **合** | **工作区全量 `.md` 总计** | — | **180** | **1,180,238 B** (**1.1256 MB**) | — | — |

**结构性成因结论**：顶层架构最初设想的合法产物其实只有核心契约（4–5 份）、图书馆（4 份）、看板/手记/反思/报告/意图。而实际把文书总量撑爆到 **1.1256 MB** 的元凶，主要是两块顶层根本没想到的**自生自长衍生文书**：
1. **第 1 类 + 第 2 类治理/过程/对账批文合计 75 份、485,934 B（占代理产出的 43.2%）**：每解除一次 37% 停码就写一份 `Q*_RELEASE.md`，发现错误再写 `*_AUDIT.md`、`*_DISCREPANCY.md`、`*_RECONCILIATION.md`、`*_RETRACTION.md`、`*_STAGNATION_DEFER*.md`、`P26_REPAIR*.md`、`EPOCH2_*.md`，外加 Reset 期间一套“申请→能力核查→源码答复→签发包→撤稿→追认→冻结→接管”全套公文流，几乎把多智能体科研系统演变成了公文流转官僚机构；
2. **多代重叠副本**：同一个节点每换一代便叠加 `HANDOFF_DRAFT` / `HANDOFF` / `HANDOFF_G1_CORRECTED`、`BOARDING_BRIEF_BASE` / `BOARDING_BRIEF` / `G3_BRIEF` / `Q*_EXPLORER_BRIEF`、`REFLECTION_37` + `COMPANION_META_REFLECTION_37`，造成信息高度冗余，直接拖垮下游探索者的“开场必读上下文”。

---

### 4.2 260 次 MCP 调用与 23 次失败的真实稳定性分类

穿透 37 个 `.zstd` 会话与 `forensics_mcp.json` 逐条核验：全轮共发起 **`mcp__greatwall-v6up__*` 调用 260 次**，其中 **237 次成功（91.15%）**，**23 次显式失败（8.85%）**（注：`query_library_mcp` #223/#225 已核实返回 `ok=true` 成功；`71457ef9` `get_lineage_briefing` 也已核实成功）。

将全部 **23 次失败** 按根因分为三大类：

| 分类 | 次数 | 占 23 次失败比例 | 占 260 次总调用比例 | 逐条明细（MCP 序号、时间、会话、工具、原因） |
|---|---:|---:|---:|---|
| **A. 源码/门禁缺陷与规则冲突** | **8** | **34.8%** | **3.08%** | • **源码 Bug/门禁误伤（2 次）**：`#181`(01:28:15)、`#183`(01:28:23) `e8e2f112` `submit_trial_observation` 传 `03_explorers\Q3\candidate.py` 被 `P18` Worktree 前缀隔离门禁（`N_Q3` vs `Q3`）误杀；<br>• **制度设计冲突（2 次）**：`#257`(10:15:36)、`#258`(10:15:36) `be302832` `fork_branch(orthogonal)` 因总管在 `00:28:16` 已预调 `register_method_family` 占坑，被防撞车算法以 `相似度=1.00 (ERR_CONFLICT)` 拦截；<br>• **正常护栏生效（4 次）**：`#81`(23:58:55 `be302832` 跳过盲审升 L1→`ERR_INVARIANT`)、`#94`(00:26:19 `865d307c` 在 `init_parse0` 前查 `N_Q1`→`ERR_NOT_FOUND`)、`#165`(01:04:35 `be302832` 以 `explorer` 跨血统查私有 L1→`ERR_LOCKED`)、`#185`(01:29:37 `e8e2f112` 37% 前探索者单方强解锁→`ERR_LOCKED`) |
| **B. 模型参数 / 格式 / 越权低级失误** | **15** | **65.2%** | **5.77%** | • **角色越权（2 次）**：`#95`(00:26:22 `865d307c` `central_library`)、`#198`(01:32:23 `6a77d192` `lineage_companion`) 误调 `get_stagnation_status`→`ERR_AUTH`；<br>• **字数超限（4 次）**：`#71`(23:55:49 `c6b437e9` 2007>2000)、`#132`(00:37:06 `48ac87fc` 2787>2000)、`#133`(00:37:19 `48ac87fc` 2076>2000)、`#169`(01:12:37 `9271b6e8` 2200≥2000)；<br>• **缺必填参数/路径/格式（9 次）**：`#80`(23:58:00 `d5e0e2bd` 误传 `question_id`)、`#182`(01:28:23 `e8e2f112` 传相对路径 `'candidate.py'`)、`#193`(01:31:25 `6a77d192` 缺唯一有序 A/B 栏标题)、`#218`(01:43:17 `b360d5ff` `workspace_root` 空)、`#219`(01:43:23 `b360d5ff` 缺 A/B 栏标题)、`#241/#242`(01:49:48 `be302832` `apply_stagnation_lanes` 漏传 `node_id`)、`#255/#256`(10:15:30 `be302832` `fork_branch(orthogonal)` 漏传 `mechanism_signature`) |
| **合计** | **23** | **100.0%** | **8.85%** | 其余 **237 次（91.15%）** MCP 原语均正常返回 |

#### 稳定性评估的必要补充：隐藏在“成功计数”背后的两类真实风险

若只看显式报错，**MCP 核心底座自身稳定性高达 91.15%（若剔除模型低级失误，仅看系统侧异常，源码/门禁冲突仅 4 次、占 1.54%）**；但结合全量事件审计，必须单列两类被“237 次成功”掩盖的真实隐患：

1. **外层 PTC `run_code` JS 封装错误（4 次 `isError=True`）**：
   - `6a77d192`（`01:19:02`）：`get_lineage_briefing` 服务端返回 `ok: true`，但模型 JS 脚本访问 `undefined.length` 抛出 `TypeError`；
   - `be302832`（`23:59:07`）：`triage_decision` 成功后，同一 `run_code` 内直查 SQLite 报 `no such column: state_version`；
   - `dfe03c70`（`00:26:34`、`00:27:38`）：模型编写的 PTC JS 载荷出现语法错误（`Expected a semicolon` / `Expected ',', got ':'`）导致脚本直接崩溃。
2. **服务端隐性状态破坏与校验缺失（3 处源码漏洞）**：
   - **`P26` 静默降级断链（`mcp_tools_research.py:1297–1314, 1334–1352`）**：`submit_node_handoff` 收到过期 `bound_state_version` 时仅返回 `"late_submission": true`（`ok: true`），却在后台将同节点全部 `VALID` 观测（`[Obs009/010/011]`）降级为 `PENDING_REVALIDATION`、清空分数且不入队，并把 `N_Q3.bound_state_version` 倒退回 `2`；
   - **`init_parse0` 静默忽略与空校验缺失（`mcp_tools_governance.py:1628–1686`）**：不读取 `method_families` 键且允许 `root_nodes=[]` 返回 `ok: true`；
   - **`trigger_first_reflection=True` 无 VALID 守卫**：导致 `N_Q1` 在 `0 VALID` 状态下直接解锁（`[L1-N_Q1-005]`），并在服务端放行后迫使总管连写数十行偏差豁免文书。
