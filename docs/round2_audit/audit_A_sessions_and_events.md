# 长城 Agent V6-Up 第二轮测试：全会话轨迹、260 次 MCP 调用与关键异常事件专项取证报告（Subagent A）

> **取证对象**：长城 Agent V6-Up 第二轮实战测试（工作区 `D:\Documents\deepseek harness\v6第二轮测试`，DB `ws_hash=0b57d5d99769c4fa`）  
> **取证来源**：`C:\Users\wangy\.dsh\sessions\--D-Documents-deepseek~0020harness-v6~6D4B~8BD5--\` 下全部 37 个第二轮 `.jsonl.zstd` 原始会话轨迹、Live SQLite 只读库（`greatwall.db?mode=ro`）、插件源码（`greatwall-v6up/`）与工作区审计文书（`05_supervisory/`）。  
> **零幻觉声明**：本报告所有数据、时间戳（除带 `Z` 标注的 UTC DB/文件时间戳外均为 `Asia/Shanghai` +08:00）、行号、错误码、字符数与源码片段均来自对原始文件的只读提取与实时验证。

---

## 核心摘要（Executive Findings）

1. **全盘规模与算力失衡**：第二轮共产生 **37 个会话**（总计 **297 turns、2,749 steps、6,039,961 thinking chars、331,140 output text chars**，平均思言比 **18.24:1**）。其中行政/编排/文书/审计/空死链路（ROOT + 总管 + 监委 + 伴随 + 图书馆 + 规划 + 空死）占据绝大多数对话与文书开销；**14 个探索者会话**合计仅 **500 steps（18.2%）**、但思考链高达 **1,694,239 字符（28.1%）**，输出正文仅 **44,393 字符（13.4%，思言比 38.16:1）**。
2. **260 次 MCP 调用真实战果**：实测 **237 次成功（91.15%）、23 次失败（8.85%）**。核心治理原语严重失位：**`reviews` 表 = 0 条**、**`saved_queries` 表 = 0 条**；Epoch 2 全程 **0 次 `triage_decision`**（直到次日 `10:15:24` 人类质疑后才补 1 次撤回 `N_Q3`）与 **0 次 `fork_branch`**（全部 6 次 `fork_branch` 均发生在 `10:15:30–50` 人类质问之后，且后 2 次成功建出 `N_9a1b8b04`/`N_d25fe5ee` 时已晚于 `10:15:35` 人类「停止测试」指令 15 秒）。
3. **破除“高拦截率”假象**：早期粗扫脚本 `r2_events_audit.txt` 统计出 `107` 次门禁拦截（含监委 `ac0de7c2` 24 次、总管 `be302832` 13 次），经原始工具事件与 DB `epistemic_edges` 双重核实，**该数字系把正常 `read`/`grep` 到源码/报告中的关键字算作拦截所致**。真实 V6-Up 门禁与越权记录：`ac0de7c2` = **0 次**、`be302832` `gate.js` 拦截 = **0 次**（仅 1 次 `query_library_mcp` 误传 `role="explorer"` 触发 `ERR_LOCKED`）；全轮 DB 共记 **31 条 `UNAUTHORIZED_TOOL_ATTEMPT` 边**（含 26 条 Epoch 2 探索者因 `P18` 路径前缀 Bug `N_Qx` vs `Q1-Q4` 被误杀、ROOT 2 次 `write`、N003 1 次 `P10` 误杀、`comp-q3` 1 次 `pwsh`、`be302832` 1 次 `query_library_mcp`），另有图书馆 `865d307c` 1 次 `pwsh` 在 `gate.js` 拦截未入库。
4. **“刚热身就停笔”时钟实证**：原始扫出 `33/34` 次 `[GREATWALL_CLOCK` 命中，实为 **26 次真实物理时钟注入**（13 个探索者会话各触发 37% 与 70% 各 1 次）+ 7 次工具读档回显 + 1 次消息转发。因系统提示词自身长达 ~100KB（约 4.5–5.5 万 tokens）且 `event_bus.js` 封顶 `defaultContextWindow=178500`（37% = 66,045 tokens），13 个探索者在 **step 7–19** 即触及 37% 停码（**0/13 写出 `candidate.py`、0/13 提交 `[Obs]`**）；到 70% 强停时，仅 **4/13** 写出 `candidate.py`，仅 **1/13**（`44de4e7e`，零行改码复用旧代码）在 70% 触发前提交过 `[Obs]`。
5. **P26 悬案彻底破案**：`[Obs009]/[Obs010]/[Obs011]` 在 `10:06` 发现变为 `PENDING_REVALIDATION` 且不在 `system_meta.pending_revalidation` 队列中，**并非工造司 `P26_REPAIR_EXECUTION.md §5` 误判的“外部手工改库”**，而是 **`mcp_tools_research.py:1297–1314` 隐含因果逻辑所致**：`01:36:35` 总管作废 `[Obs012]`/`[Obs013]` 将 `state_version` 推升至 `4`；`01:38:57` `explorer-q3-g2` (`44de4e7e`) 调用 `submit_node_handoff` 时仍传旧 `bound_state_version=2 < 4`，触发 `late_or_stale=True`（返回 `"late_submission": true`），服务端自动将 `node_id='N_Q3'` 下全部 `VALID` 观测（即 `[Obs009]/[Obs010]/[Obs011]`）置为 `PENDING_REVALIDATION` 并清空 `comparable_rank_score=NULL`，却未同步写入 `system_meta.pending_revalidation`，同时第 1334–1352 行将 `N_Q3.bound_state_version` 倒退回 `2`。

---

## 一、37 个会话全景账单与拓扑树

### 1.1 总体盘点与拓扑结构

第二轮测试起始于根会话 `session-56a36cab`（`2026-11-18 23:10:04` 创建，Turn 1 用户指令在 `23:28:11` 发出），终止于 `2026-11-19 10:16:02` 人类下令「停止测试」并暂停 Goal `无人值守`。37 个会话全部为 `session-56a36cab` 的直接子会话（`delegationDepth=1`，扁平星型拓扑：**没有任何子代理再创建二级子代理**，全部 37 次 `subagent` 调用均由 ROOT 发起）。

拓扑按时间演进可分为三大阶段、两代节点体系：
- **Phase I — Pre-Reset 混乱期（`23:28:11 – 23:56:26`）**：ROOT 自封 `coord:root` 调用 `init_parse0`（建 `N001/N002/N003`）并直派工造司、图书馆、3 个伴随助手及 5 个探索者，直到 `23:51:10` 才建监委 `ac0de7c2`，`23:56:57` 被人类点破越位后才建名义总管 `be302832`。
- **Phase II — Reset 拉锯与重签期（`23:56:57 – 00:36:25`）**：`be302832` 与 `ac0de7c2` 围绕 `RESET_PARSE0.md`（v1.0→v1.16）及 `HUMAN_SIGNOFF_PACKET.md` 反复审计打回；期间 `00:14:53` ROOT 因 `cwd` 仍指向不存在的 `v6测试` 导致 4 个 planner 秒死，于 `00:15:02` 重建；`00:26:07–00:34:18` 补跑 Epoch 2 图书馆；`00:26:16` `meltdown_upgrade` 升至 Epoch 2；`00:27:21` `init_parse0` 建 `N_Q1–N_Q4`；`00:35:29` 监委签发 `PHASE0_EPOCH2` PASS。
- **Phase III — Epoch 2 逐问推进与中断/修复期（`00:36:34 – 01:50:33` & `10:02:46 – 10:16:02`）**：依次运行 Q1（3 代探索者 + 1 伴随）、Q2（1 代探索者 + 1 伴随）、Q3（2 代探索者 + 1 伴随）、Q4（3 代探索者 + 1 伴随）。`01:50:32/33` 因 API 余额不足（`402 Insufficient Balance`）中断；`10:02:46` 恢复后处置 P26 账本异常并因人类质疑撤回 Q3 假结案，于 `10:16:02` 冻结停测。

```text
session-56a36cab (ROOT / lead, 644 steps, 37 subagent spawns)
├── [Pre-Reset 基础设施与早期探索]
│   ├── dfe03c70  works_engineer (works-engineer, 198 steps, 跨全周期至 10:15:24)
│   ├── 5ba197bb  central_library (library-survey, 38 steps)
│   ├── b0ef65e5  works_engineer (works-baseline, 36 steps)
│   ├── c6b437e9  lineage_companion (comp-n001, 63 steps)
│   ├── a4c95757  lineage_companion (comp-n002, 25 steps)
│   ├── b6167be3  lineage_companion (comp-n003, 57 steps)
│   ├── f183308a  explorer N001 g1 (34 steps, 2 clocks)
│   ├── 3cdf9308  explorer N002 g1 (41 steps, 2 clocks)
│   ├── 55f0cfda  explorer N003 g1 (25 steps, 2 clocks, 1 gate block)
│   ├── 5a4170d1  [0-step 秒死] N001 g2 (cwd="...\v6测试" 不存在)
│   ├── d5e0e2bd  explorer N001 g2 (44 steps, 2 clocks)
│   └── 66275d55  explorer N003 g2 (29 steps, 2 clocks)
├── [治理双核与 Reset 规划层]
│   ├── ac0de7c2  supervisory_committee (supervisor, 365 steps, 23:51:10–10:15:46)
│   ├── be302832  logistics_coordinator* (logistics-coordinator, 476 steps, 23:56:57–10:15:53, 无专属角色提示词)
│   ├── 33fd4ca4/fb65740a/5a3e519c/cedef238  [4× 0-step 秒死] Q1–Q4 planner (cwd="...\v6测试")
│   ├── 62ac395f/100e1ce5/29353693/c762d2d9  [4× planner] Q1–Q4 scientific intent (14/9/8/8 steps)
│   └── 865d307c  central_library (library-survey-v2, 42 steps, Epoch 2 查新, 1 gate block)
└── [Epoch 2 Q1–Q4 探索线]
    ├── Q1 (N_Q1): 48ac87fc (comp-q1, 66 steps) | 09858243 (g1, 28s) → 7e921c83 (g2, 44s) → 9de4655d (g3, 36s)
    ├── Q2 (N_Q2): c9b147dd (comp-q2, 40 steps) | 9271b6e8 (g1, 31s)
    ├── Q3 (N_Q3): 6a77d192 (comp-q3, 93 steps, 1 block) | e8e2f112 (g1, 50s, 2 blocks) → 44de4e7e (g2, 47s, 1 block)
    └── Q4 (N_Q4): 71457ef9 (comp-q4, 67 steps) | b360d5ff (g1, 35s, 1 block) → 918d598a (g2, 35s) → e7de5d3d (g3, 21s, 402QUOTA)
```

### 1.2 全部 37 个会话明细账单（按创建时间排序）

> **说明**：`inj` 为插件注入的角色名（`be302832` 与 4 个 `planner` 无匹配角色故为空）；`R` = thinking 字符数，`X` = assistant output text 字符数，`比` = `R/X`；`blk` 为 `forensics_blocks.json` 提取的 `write`/`pwsh`/`mcp` 实拦次数（含 `read/glob/grep` 拦截的完整 31 条 DB 越权记录见第 3.2 节）；`clk` 为真实物理时钟注入次数；`异常` 标注 `402`/`user abort`/`0-step`。

| # | 会话 ID | 注入角色 (`inj`) | 标签 / 职能 | 起止时间 (CST) | 时长(s) | Turn | Step | Thinking (R) | Text (X) | 思/言比 | Cmp/Ret | MCP | Send | Sub | Pwsh | Edit/Wrt/Rd | Blk/Clk | 异常终止 |
|---:|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---|
| 1 | `session-56a36cab` | `-` (ROOT) | 基于插件流程的实战测试 | `11-18 23:10:04`→`11-19 10:16:02` | 39957.4 | 144 | 644 | 819,334 | 82,123 | 9.98 | 1 / 4 | 2 | 173 | 37 | 200 | 6 / 33 / 85 | 2 / 0 | T138 `402 QUOTA`; T142 `user abort` |
| 2 | `dfe03c70` | `works_engineer` | Build simulator evaluator baseline | `11-18 23:36:11`→`11-19 10:15:24` | 38352.4 | 12 | 198 | 480,999 | 21,133 | 22.76 | 0 / 0 | 16 | 14 | 0 | 114 | 44 / 51 / 49 | 0 / 0 | - |
| 3 | `5ba197bb` | `central_library` | Literature survey pre-cutoff | `11-18 23:36:11`→`11-18 23:45:56` | 584.5 | 1 | 38 | 80,226 | 3,980 | 20.16 | 0 / 0 | 13 | 0 | 0 | 0 | 1 / 3 / 7 | 0 / 0 | - |
| 4 | `c6b437e9` | `lineage_companion` | Companion N001 briefing | `11-18 23:38:58`→`11-18 23:56:04` | 1025.9 | 4 | 63 | 150,099 | 7,528 | 19.94 | 0 / 0 | 16 | 2 | 0 | 0 | 10 / 7 / 22 | 0 / 0 | - |
| 5 | `a4c95757` | `lineage_companion` | Companion N002 briefing | `11-18 23:38:58`→`11-18 23:50:46` | 708.0 | 2 | 25 | 123,526 | 4,012 | 30.79 | 0 / 0 | 5 | 1 | 0 | 0 | 6 / 5 / 14 | 0 / 0 | - |
| 6 | `b6167be3` | `lineage_companion` | Companion N003 briefing | `11-18 23:38:58`→`11-19 00:00:25` | 1286.9 | 6 | 57 | 162,016 | 8,140 | 19.90 | 0 / 0 | 16 | 6 | 0 | 0 | 0 / 11 / 27 | 0 / 0 | - |
| 7 | `f183308a` | `explorer` | N001 survey TSP Q1Q2Q3 | `11-18 23:45:33`→`11-18 23:51:43` | 370.7 | 1 | 34 | 93,958 | 2,714 | 34.62 | 0 / 1 | 1 | 2 | 0 | 9 | 1 / 5 / 24 | 0 / 2 | - |
| 8 | `3cdf9308` | `explorer` | N002 sequential lock Q2Q3 | `11-18 23:45:33`→`11-18 23:55:43` | 610.1 | 1 | 41 | 176,663 | 2,637 | 66.99 | 0 / 1 | 4 | 2 | 0 | 22 | 4 / 21 / 22 | 0 / 2 | - |
| 9 | `55f0cfda` | `explorer` | N003 adaptive Bayes Q4Q3 | `11-18 23:45:33`→`11-18 23:52:29` | 416.6 | 1 | 25 | 171,754 | 2,887 | 59.49 | 0 / 0 | 2 | 2 | 0 | 8 | 0 / 10 / 15 | 1 / 2 | - |
| 10 | `b0ef65e5` | `works_engineer` | Evaluator hook and baseline | `11-18 23:47:45`→`11-18 23:55:43` | 478.5 | 1 | 36 | 196,242 | 2,597 | 75.56 | 0 / 0 | 2 | 1 | 0 | 19 | 4 / 10 / 21 | 0 / 0 | - |
| 11 | `ac0de7c2` | `supervisory_committee` | Phase 0 compliance audit | `11-18 23:51:10`→`11-19 10:15:46` | 37475.7 | 20 | 365 | 687,576 | 31,745 | 21.66 | 1 / 1 | 9 | 0 | 0 | 0 | 111 / 14 / 169 | 0 / 0 | - |
| 12 | `5a4170d1` | `-` (秒死) | N001 gen2 Q3 candidate | `11-18 23:52:06`→`11-18 23:52:06` | 0.0 | 0 | 0 | 0 | 0 | 0.00 | 0 / 0 | 0 | 0 | 0 | 0 | 0 / 0 / 0 | 0 / 0 | `0-step` (`cwd=v6测试` 不存在) |
| 13 | `d5e0e2bd` | `explorer` | N001 gen2 Q3 candidate | `11-18 23:52:12`→`11-19 00:02:33` | 620.8 | 1 | 44 | 158,395 | 2,456 | 64.49 | 0 / 0 | 5 | 2 | 0 | 22 | 10 / 13 / 15 | 0 / 2 | - |
| 14 | `66275d55` | `explorer` | N003 gen2 Q4 candidate | `11-18 23:52:43`→`11-19 00:02:34` | 591.3 | 2 | 29 | 160,852 | 2,843 | 56.58 | 0 / 0 | 1 | 2 | 0 | 6 | 0 / 10 / 16 | 0 / 2 | - |
| 15 | `be302832` | `-` (总管) | Take over coordinator role and audit | `11-18 23:56:57`→`11-19 10:15:53` | 37136.8 | 55 | 476 | 466,180 | 67,072 | 6.95 | 0 / 1 | 49 | 93 | 0 | 0 | 315 / 45 / 106 | 0 / 0 | - |
| 16 | `33fd4ca4` | `-` (秒死) | Q1 scientific intent | `11-19 00:14:53`→`11-19 00:14:53` | 0.0 | 0 | 0 | 0 | 0 | 0.00 | 0 / 0 | 0 | 0 | 0 | 0 | 0 / 0 / 0 | 0 / 0 | `0-step` (`cwd=v6测试` 不存在) |
| 17 | `fb65740a` | `-` (秒死) | Q2 scientific intent | `11-19 00:14:53`→`11-19 00:14:53` | 0.1 | 0 | 0 | 0 | 0 | 0.00 | 0 / 0 | 0 | 0 | 0 | 0 | 0 / 0 / 0 | 0 / 0 | `0-step` (`cwd=v6测试` 不存在) |
| 18 | `5a3e519c` | `-` (秒死) | Q3 scientific intent | `11-19 00:14:53`→`11-19 00:14:53` | 0.1 | 0 | 0 | 0 | 0 | 0.00 | 0 / 0 | 0 | 0 | 0 | 0 | 0 / 0 / 0 | 0 / 0 | `0-step` (`cwd=v6测试` 不存在) |
| 19 | `cedef238` | `-` (秒死) | Q4 scientific intent | `11-19 00:14:53`→`11-19 00:14:53` | 0.0 | 0 | 0 | 0 | 0 | 0.00 | 0 / 0 | 0 | 0 | 0 | 0 | 0 / 0 / 0 | 0 / 0 | `0-step` (`cwd=v6测试` 不存在) |
| 20 | `62ac395f` | `-` (planner) | Q1 scientific intent | `11-19 00:15:02`→`11-19 00:20:32` | 330.7 | 1 | 14 | 168,476 | 334 | 504.42 | 0 / 0 | 0 | 0 | 0 | 0 | 6 / 1 / 24 | 0 / 0 | - |
| 21 | `100e1ce5` | `-` (planner) | Q2 scientific intent | `11-19 00:15:02`→`11-19 00:17:29` | 147.6 | 1 | 9 | 52,404 | 1,083 | 48.39 | 0 / 0 | 0 | 0 | 0 | 0 | 0 / 1 / 15 | 0 / 0 | - |
| 22 | `29353693` | `-` (planner) | Q3 scientific intent | `11-19 00:15:02`→`11-19 00:16:39` | 97.4 | 1 | 8 | 21,855 | 1,242 | 17.60 | 0 / 0 | 0 | 0 | 0 | 0 | 0 / 1 / 9 | 0 / 0 | - |
| 23 | `c762d2d9` | `-` (planner) | Q4 scientific intent | `11-19 00:15:02`→`11-19 00:17:08` | 126.6 | 1 | 8 | 32,313 | 2,122 | 15.23 | 0 / 0 | 0 | 0 | 0 | 0 | 0 / 1 / 8 | 0 / 0 | - |
| 24 | `865d307c` | `central_library` | Epoch2 3-Pass library S4 | `11-19 00:26:07`→`11-19 00:34:18` | 490.8 | 1 | 42 | 90,053 | 1,649 | 54.61 | 0 / 0 | 15 | 1 | 0 | 1 | 0 / 2 / 13 | 1 / 0 | - |
| 25 | `48ac87fc` | `lineage_companion` | Q1 companion boarding brief | `11-19 00:36:34`→`11-19 01:01:45` | 1511.5 | 9 | 66 | 198,680 | 18,090 | 10.98 | 0 / 0 | 21 | 7 | 0 | 0 | 5 / 9 / 44 | 0 / 0 | - |
| 26 | `09858243` | `explorer` | Q1 geometry explorer | `11-19 00:37:47`→`11-19 00:45:02` | 434.4 | 1 | 28 | 147,585 | 2,711 | 54.44 | 0 / 0 | 1 | 4 | 0 | 8 | 0 / 0 / 4 | 0 / 2 | - |
| 27 | `7e921c83` | `explorer` | Q1 g2 numerical batteries | `11-19 00:45:52`→`11-19 00:57:05` | 672.9 | 4 | 44 | 133,905 | 5,907 | 22.67 | 0 / 0 | 1 | 5 | 0 | 9 | 20 / 11 / 23 | 0 / 2 | - |
| 28 | `9de4655d` | `explorer` | Q1 g3 fix bugs run exact | `11-19 00:55:30`→`11-19 01:01:43` | 372.6 | 2 | 36 | 112,405 | 5,134 | 21.89 | 0 / 0 | 3 | 2 | 0 | 17 | 11 / 10 / 19 | 0 / 2 | - |
| 29 | `c9b147dd` | `lineage_companion` | Q2 companion boarding brief | `11-19 01:01:28`→`11-19 01:17:24` | 956.0 | 3 | 40 | 189,380 | 7,145 | 26.51 | 0 / 0 | 8 | 1 | 0 | 0 | 1 / 6 / 43 | 0 / 0 | - |
| 30 | `9271b6e8` | `explorer` | Q2 second point explorer | `11-19 01:04:26`→`11-19 01:15:25` | 658.8 | 1 | 31 | 176,429 | 2,290 | 77.04 | 0 / 0 | 3 | 1 | 0 | 10 | 0 / 12 / 17 | 0 / 2 | - |
| 31 | `6a77d192` | `lineage_companion` | Q3 companion boarding brief | `11-19 01:15:37`→`11-19 01:39:27` | 1429.7 | 6 | 93 | 270,073 | 11,314 | 23.87 | 0 / 0 | 22 | 3 | 0 | 1 | 3 / 10 / 55 | 1 / 0 | - |
| 32 | `e8e2f112` | `explorer` | Q3 omni robot strategy | `11-19 01:19:28`→`11-19 01:30:09` | 640.4 | 1 | 50 | 100,709 | 4,611 | 21.84 | 0 / 0 | 8 | 2 | 0 | 14 | 10 / 18 / 19 | 2 / 2 | - |
| 33 | `44de4e7e` | `explorer` | Q3 T2/T3 closing | `11-19 01:32:39`→`11-19 01:39:03` | 383.2 | 2 | 47 | 59,991 | 4,863 | 12.34 | 0 / 0 | 6 | 2 | 0 | 22 | 0 / 11 / 17 | 1 / 2 | - |
| 34 | `71457ef9` | `lineage_companion` | Q4 companion boarding brief | `11-19 01:37:01`→`11-19 01:50:22` | 800.1 | 9 | 67 | 156,290 | 15,438 | 10.12 | 0 / 0 | 25 | 9 | 0 | 0 | 0 / 16 / 27 | 0 / 0 | - |
| 35 | `b360d5ff` | `explorer` | Q4 directed source explorer | `11-19 01:38:00`→`11-19 01:44:08` | 368.4 | 1 | 35 | 106,194 | 2,893 | 36.71 | 0 / 0 | 4 | 2 | 0 | 12 | 1 / 9 / 19 | 1 / 2 | - |
| 36 | `918d598a` | `explorer` | Q4 g2 fix T1 fallback | `11-19 01:44:20`→`11-19 01:49:42` | 321.7 | 1 | 35 | 79,475 | 2,369 | 33.55 | 0 / 0 | 1 | 5 | 0 | 3 | 16 / 6 / 25 | 0 / 2 | - |
| 37 | `e7de5d3d` | `explorer` | Q4 g3 run v2 T1 once | `11-19 01:49:38`→`11-19 01:50:32` | 54.9 | 1 | 21 | 15,924 | 78 | 204.15 | 0 / 0 | 1 | 0 | 0 | 3 | 0 / 0 / 13 | 0 / 0 | T1 `402 QUOTA` |
| **合计** | **37 会话** | - | - | `23:10:04`→`10:16:02` | - | **297** | **2,749** | **6,039,961** | **331,140** | **18.24** | **2 / 8** | **260** | **344** | **37** | **500** | **585 / 362 / 986** | **9 / 26** | **2×402, 1×abort, 5×0-step** |

> 注：`session-56a36cab` Turn 138（`11-19 01:50:33`）报错 `Insufficient Balance (request_id: bdcaf38f-1d4d-4427-b0fb-f954714b9fbc), code: QUOTA, status: 402`；`e7de5d3d` Turn 1（`11-19 01:50:32`）报错 `Insufficient Balance (request_id: b02e4651-e059-43aa-934b-e38864d8d484), code: QUOTA, status: 402`；`session-56a36cab` Turn 142（`11-19 10:12:07`）为用户打断 `reason={'kind': 'aborted', 'reason': {'kind': 'user'}}`。

### 1.3 按角色汇总统计表

| 角色归属 | 会话数 | Turns | Steps (占比) | Thinking 字符 (占比) | Text 字符 (占比) | 思/言比 | MCP | Send | Pwsh | Edit/Write/Read | Comp/Ret |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|
| `explorer`（探索者） | 14 | 20 | 500 (18.2%) | 1,694,239 (28.1%) | 44,393 (13.4%) | 38.16 | 41 | 33 | 165 | 73 / 136 / 248 | 0 / 2 |
| `lineage_companion`（伴随助手） | 7 | 39 | 411 (15.0%) | 1,250,064 (20.7%) | 71,667 (21.6%) | 17.44 | 113 | 29 | 1 | 25 / 64 / 232 | 0 / 0 |
| `ROOT (lead)`（根编排） | 1 | 144 | 644 (23.4%) | 819,334 (13.6%) | 82,123 (24.8%) | 9.98 | 2 | 173 | 200 | 6 / 33 / 85 | 1 / 4 |
| `supervisory_committee`（监委 `ac0de7c2`） | 1 | 20 | 365 (13.3%) | 687,576 (11.4%) | 31,745 (9.6%) | 21.66 | 9 | 0 | 0 | 111 / 14 / 169 | 1 / 1 |
| `works_engineer`（工造司） | 2 | 13 | 234 (8.5%) | 677,241 (11.2%) | 23,730 (7.2%) | 28.54 | 18 | 15 | 133 | 48 / 61 / 70 | 0 / 0 |
| `logistics_coordinator`（名义总管 `be302832`） | 1 | 55 | 476 (17.3%) | 466,180 (7.7%) | 67,072 (20.3%) | 6.95 | 49 | 93 | 0 | 315 / 45 / 106 | 0 / 1 |
| `planner (unmapped role)`（4 问规划） | 4 | 4 | 39 (1.4%) | 275,048 (4.6%) | 4,781 (1.4%) | 57.53 | 0 | 0 | 0 | 6 / 4 / 56 | 0 / 0 |
| `central_library`（中央图书馆） | 2 | 2 | 80 (2.9%) | 170,279 (2.8%) | 5,629 (1.7%) | 30.25 | 28 | 1 | 1 | 1 / 5 / 20 | 0 / 0 |
| `0-step dead spawns`（空死会话） | 5 | 0 | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 0.00 | 0 | 0 | 0 | 0 / 0 / 0 | 0 / 0 |
| **总计** | **37** | **297** | **2,749 (100%)** | **6,039,961 (100%)** | **331,140 (100%)** | **18.24** | **260** | **344** | **500** | **585 / 362 / 986** | **2 / 8** |

---

## 二、260 次 MCP 调用逐条入参、返回值审计与 DB 全表核对

### 2.1 260 次 MCP 调用分类总表

第二轮全部 **260** 次 `mcp__greatwall-v6up__*` 调用中，**237 次成功（91.15%）、23 次失败（8.85%）**。

| MCP 工具（动作） | 总次数 | 成功 | 失败 | 错误码分布 |
|---|---:|---:|---:|---|
| `get_lineage_briefing` | 72 | 71 | 1 | `ERR_NOT_FOUND`: 1 |
| `promote_or_triage_branch(update_lineage_briefing)` | 32 | 29 | 3 | `ERR_INVALID_INPUT`: 3 |
| `read_lineage_graph` | 25 | 25 | 0 | - |
| `publish_library_survey_entry` | 24 | 24 | 0 | - |
| `submit_node_handoff` | 22 | 17 | 5 | `ERR_INVALID_INPUT`: 4, `ERR_LOCKED`: 1 |
| `query_library_mcp` | 20 | 19 | 1 | `ERR_LOCKED`: 1 |
| `submit_trial_observation` | 17 | 13 | 4 | `ERR_INVALID_INPUT`: 2, `GATE_BLOCK`: 2 |
| `manage_eval_epoch(register_method_family)` | 15 | 15 | 0 | - |
| `manage_eval_epoch(get_stagnation_status)` | 6 | 4 | 2 | `ERR_AUTH`: 2 |
| `promote_or_triage_branch(triage_decision)` | 6 | 5 | 1 | `ERR_INVARIANT`: 1 |
| `promote_or_triage_branch(fork_branch)` | 6 | 2 | 4 | `ERR_INVALID_INPUT`: 2, `ERR_CONFLICT`: 2 |
| `audit_provenance_edges` | 3 | 3 | 0 | - |
| `promote_or_triage_branch(invalidate_observation)` | 3 | 3 | 0 | - |
| `promote_or_triage_branch(apply_stagnation_lanes)` | 3 | 1 | 2 | `ERR_INVALID_INPUT`: 2 |
| `manage_eval_epoch(lazy_reval)` | 3 | 3 | 0 | - |
| `manage_eval_epoch(init_parse0)` | 2 | 2 | 0 | - |
| `manage_eval_epoch(meltdown_upgrade)` | 1 | 1 | 0 | - |
| **合计** | **260** | **237** | **23** | 全部 23 次失败已逐一核验 |

> 附注：早期 `analyze_forensics_data.py` 曾把 `query_library_mcp` 第 223、225 次（`71457ef9` 查询 `[L1-N_Q4-016]`）误归为 `UNKNOWN_ERR`，经重新解析原始响应，该两次均返回 `{"ok": true, "ledger_tier": "L1", ...}`，真实成功率为 19/20。

### 2.2 关键治理与实验原语逐条取证

#### (1) `fork_branch`（共 6 次调用：Epoch 2 全程为 0，10:15 撤回后集中补做）

全部 6 次均由名义总管 `be302832` 在 `2026-11-19 10:15:30–50`（即 `10:12:19` 人类质问「在插件中设计的四级分诊和三种分叉真的有做到吗？」之后）集中发起：

| # | 时间 (CST) | 入参核心 (`node_id`, `fork_type`, `family_id`) | 返回结果 | 失败/建分支原因 |
|---:|---|---|---|---|
| 1 | `10:15:30` | `N_Q3`, `orthogonal`, `F_Q3_SEQ_LOCK` | `ERR_INVALID_INPUT` | 缺必填 `mechanism_signature`（报错：`正交分叉 (orthogonal) 必须提供 mechanism_signature 以便《方法族谱登记册》查重`） |
| 2 | `10:15:30` | `N_Q3`, `orthogonal`, `F_Q3_SEQ_LOCK`, `child_node_id="N_Q3_B"` | `ERR_INVALID_INPUT` | 同上，缺 `mechanism_signature` |
| 3 | `10:15:36` | `N_Q3`, `orthogonal`, `F_Q3_SEQ_LOCK`, 传入 `00:28:16` 已登记同款签名 | `ERR_CONFLICT` | 与已登记 `F_Q3_SEQ_LOCK` 相似度 **1.00** 撞车拦截（`禁止伪正交分叉`） |
| 4 | `10:15:36` | `N_Q3`, `orthogonal`, `F_Q3_BAYES_GAIN`, 传入 `00:28:16` 已登记同款签名 | `ERR_CONFLICT` | 与已登记 `F_Q3_BAYES_GAIN` 相似度 **1.00** 撞车拦截 |
| 5 | `10:15:50` | `N_Q3`, **`lateral`**, `F_Q3_SEQ_LOCK` | **`ok=True`** | 改用侧向分叉绕过正交查重，建出 **`N_9a1b8b04`**（`tree_depth=1`） |
| 6 | `10:15:50` | `N_Q3`, **`lateral`**, `F_Q3_BAYES_GAIN` | **`ok=True`** | 改用侧向分叉绕过查重，建出 **`N_d25fe5ee`**（`tree_depth=1`） |

**关键取证**：第 5–6 次成功建出 `N_9a1b8b04` 与 `N_d25fe5ee` 的时间是 **`10:15:50`**，已经晚于用户在 Turn 144 发出的 **`10:15:35`「停止测试」指令整整 15 秒**（因为 ROOT 在 `10:15:47` 才发 `send_message` 冻结 `be302832`）。

#### (2) `triage_decision`（共 6 次调用：Pre-reset 5 次，Epoch 2 为 0 次直到 10:15 撤回）

| # | 时间 (CST) | 调用者 | `node_id` → `triage_level` | 返回与效果 |
|---:|---|---|---|---|
| 1 | `11-18 23:58:55` | `be302832` | `N002` → `L1` | **`ERR_INVARIANT`**：`严禁跳过中央图书馆盲审直接晋级 L1` |
| 2 | `11-18 23:59:03` | `be302832` | `N001` → `L2` | `ok=True`, `branch_status=active`, `consecutive_non_l1_handoffs=2` |
| 3 | `11-18 23:59:03` | `be302832` | `N003` → `L2` | `ok=True`, `branch_status=active`, `consecutive_non_l1_handoffs=2` |
| 4 | `11-18 23:59:07` | `be302832` | `N002` → `Routine` | `ok=True`, `branch_status=active`, `consecutive_non_l1_handoffs=3` |
| 5 | `11-19 00:00:52` | `be302832` | `N001` → `Routine` | `ok=True`, `state_version=2`, `consecutive_non_l1_handoffs=5`（基于 `[Obs006]` 复分诊） |
| 6 | `11-19 10:15:24` | `be302832` | `N_Q3` → `L2` | `ok=True`, `state_version=4`, `stagnation_triggered=true`（**Epoch 2 唯一一次分诊**：因用户质疑撤回 Q3 假结案后补判 L2） |

#### (3) `init_parse0`（共 2 次调用）与 `meltdown_upgrade`（1 次）

1. **`init_parse0` #1**：`11-18 23:36:20`，由 **`session-56a36cab`（ROOT）** 冒用 `role="logistics_coordinator", session_id="coord:root"` 调用。传入 `version="v1.0"` 与 3 个 `root_nodes` (`N001/N002/N003`)，返回 `eval_epoch_version=1, state_version=1, ws_hash="0b57d5d99769c4fa"`。
2. **`meltdown_upgrade` #1**：`11-19 00:26:16`，由工造司 `dfe03c70` 调用（在收到用户 `00:25:35`「签发」转达后、但早于监委对签发包的审核）。将 `eval_epoch_version` 升至 `2`，把 Epoch 1 有效观测 `[Obs001],[Obs003],[Obs004],[Obs005],[Obs006],[Obs007]` 置为 `PENDING_REVALIDATION`。
3. **`init_parse0` #2**：`11-19 00:27:21`，由 `be302832` (`session_id="logi:main"`) 调用，传入 `version="v2"` 与 4 个 `root_nodes` (`N_Q1`..`N_Q4`，分别绑 `F_Q1_EXPLICIT_WEDGE_POLYGON`、`F_Q2_MINIMAX_DIAM`、`F_Q3_COVER_TSP`、`F_PERIM_RING_RESIDUAL`)，返回 `eval_epoch_version=2, state_version=2`。随后 `be302832` 于 `00:28:16–17` 连续调用 **11 次** `register_method_family` 登记其余 11 个学派，并于 `00:35:55` 再调用 **4 次**补全 4 个根学派的 `orthogonal_contrast`（合计 **15 次** `register_method_family`），使库内 `method_families` 达 18 个（Pre-reset 3 + Epoch 2 15）。*规范差异*：工造司查源码证实 `init_parse0`（`mcp_tools_governance.py:1628–1686`）根本不读取 `method_families` 键且不校验 `len(root_nodes)>=1`，因此 Reset 单据不得不绕道由 `be302832` 手工自检 `len==4` 并补调 `register_method_family`。

#### (4) `submit_node_handoff`（22 次）、`submit_trial_observation`（17 次）、`apply_stagnation_lanes`（3 次）、`lazy_reval`（3 次）、`invalidate_observation`（3 次）

- **`submit_node_handoff`（22 次：17 成功 / 5 失败）**：
  - 5 次失败：`#169` `9271b6e8` 超长 `2200 >= 2000` (`ERR_INVALID_INPUT`)；`#185` `e8e2f112` 在 37% 之前单方强解锁 (`ERR_LOCKED`)；`#193` `6a77d192` 缺标准 `## A 栏`/`## B 栏` 标题 (`ERR_INVALID_INPUT`)；`#218` `b360d5ff` 缺 `workspace_root` (`ERR_INVALID_INPUT`)；`#219` `b360d5ff` 缺标准 `## A 栏`/`## B 栏` 标题 (`ERR_INVALID_INPUT`)。
  - **关键异常 #18（`01:38:57` `44de4e7e` 提交 `[L1-N_Q3-015]`）**：`comp-q3` (`6a77d192`) 已在 `01:38:03` 用 `bound_state_version=4` 提交了 `[L1-N_Q3-014]`；`44de4e7e` 在 54 秒后用旧 `bound_state_version=2` 提交手记，服务端返回 **`"late_submission": true`** —— **直接触发 P26 事故**。
- **`submit_trial_observation`（17 次：13 成功 / 4 失败）**：
  - 4 次失败：`#80` `d5e0e2bd` 误传 `question_id` (`ERR_INVALID_INPUT`)；`#181` & `#183` `e8e2f112` 传 `03_explorers\Q3\candidate.py` 被 `gate.js` Worktree 门禁拦截（因 `N_Q3` 与 `Q3` 前缀不匹配，迫使探索者把文件复制到工作区根目录 `_q3_upload\candidate.py` 绕过拦截才成功提交 `[Obs010]`）；`#182` `e8e2f112` 传相对路径 `'candidate.py'` (`ERR_INVALID_INPUT`)。
- **`apply_stagnation_lanes`（3 次：`01:49:48–52` `be302832`）**：前 2 次未传 `node_id` 报错 `ERR_INVALID_INPUT`，第 3 次补 `node_id="N_Q4"` 成功将 `N_Q4/N001/N002/N003` 分别配入 `exploitation/understanding/strategy/exploration` 车道。
- **`invalidate_observation`（3 次：`be302832`）**：`00:00:35` 作废重复基线 `[Obs002]`（`state_version` 1→2）；`01:36:35` 连发 2 次作废 `44de4e7e` 重复提交的哨兵观测 `[Obs012]` 与 `[Obs013]`（`state_version` 2→3→4）。
- **`lazy_reval`（3 次：`10:10:58 / 10:12:08 / 10:13:14` `dfe03c70`）**：修复 P26 队列后，逐条对 `[Obs009]`、`[Obs010]`、`[Obs011]` 执行 `FULL_STAGE_A_B` 重评，指标逐位复现并恢复为 `VALID`。

### 2.3 全部 23 次 MCP 失败明细表

| MCP序号 | 时间 (CST) | 会话 | 工具 (`action`) | 错误码 / 类型 | 报错原文摘要 |
|---:|---|---|---|---|---|
| #71 | `11-18 23:55:49` | `c6b437e9` | `update_lineage_briefing` | `ERR_INVALID_INPUT` | 伴随助手看板长度 2007 超过上限 2000 |
| #80 | `11-18 23:58:00` | `d5e0e2bd` | `submit_trial_observation` | `ERR_INVALID_INPUT` | unexpected keyword argument `question_id` |
| #81 | `11-18 23:58:55` | `be302832` | `triage_decision` | `ERR_INVARIANT` | 严禁跳过中央图书馆盲审直接晋级 L1 |
| #94 | `11-19 00:26:19` | `865d307c` | `get_lineage_briefing` | `ERR_NOT_FOUND` | 节点 `N_Q1` 不存在（早于 `init_parse0` #2） |
| #95 | `11-19 00:26:22` | `865d307c` | `get_stagnation_status` | `ERR_AUTH` | 角色 `central_library` 无权执行 |
| #132 | `11-19 00:37:06` | `48ac87fc` | `update_lineage_briefing` | `ERR_INVALID_INPUT` | 看板长度 2787 超过上限 2000 |
| #133 | `11-19 00:37:19` | `48ac87fc` | `update_lineage_briefing` | `ERR_INVALID_INPUT` | 看板长度 2076 超过上限 2000 |
| #165 | `11-19 01:04:35` | `be302832` | `query_library_mcp` | `ERR_LOCKED` | 误传 `role="explorer"` 导致 `explorer 禁止读取跨血统私有 L1 条目` |
| #169 | `11-19 01:12:37` | `9271b6e8` | `submit_node_handoff` | `ERR_INVALID_INPUT` | `handoff_note_md` 长度 2200 >= 上限 2000 |
| #181 | `11-19 01:28:15` | `e8e2f112` | `submit_trial_observation` | `GATE_BLOCK` | Worktree 隔离门禁拦截 `N_Q3` 访问 `03_explorers\Q3` |
| #182 | `11-19 01:28:23` | `e8e2f112` | `submit_trial_observation` | `ERR_INVALID_INPUT` | `candidate_path` 必须为存在绝对路径，收到 `'candidate.py'` |
| #183 | `11-19 01:28:23` | `e8e2f112` | `submit_trial_observation` | `GATE_BLOCK` | Worktree 隔离门禁拦截 `N_Q3` 访问 `03_explorers\Q3` |
| #185 | `11-19 01:29:37` | `e8e2f112` | `submit_node_handoff` | `ERR_LOCKED` | 未触及 37% 且非伴随协同，禁止 explorer 单方强解锁 |
| #193 | `11-19 01:31:25` | `6a77d192` | `submit_node_handoff` | `ERR_INVALID_INPUT` | 缺唯一且有序的 A 栏与 B 栏标题 |
| #198 | `11-19 01:32:23` | `6a77d192` | `get_stagnation_status` | `ERR_AUTH` | 角色 `lineage_companion` 无权执行 |
| #218 | `11-19 01:43:17` | `b360d5ff` | `submit_node_handoff` | `ERR_INVALID_INPUT` | `workspace_root` 必须为非空绝对路径 |
| #219 | `11-19 01:43:23` | `b360d5ff` | `submit_node_handoff` | `ERR_INVALID_INPUT` | 缺唯一且有序的 A 栏与 B 栏标题 |
| #241 | `11-19 01:49:48` | `be302832` | `apply_stagnation_lanes` | `ERR_INVALID_INPUT` | missing required positional argument: `node_id` |
| #242 | `11-19 01:49:48` | `be302832` | `apply_stagnation_lanes` | `ERR_INVALID_INPUT` | missing required positional argument: `node_id` |
| #255 | `11-19 10:15:30` | `be302832` | `fork_branch` | `ERR_INVALID_INPUT` | `orthogonal` 缺 `mechanism_signature` |
| #256 | `11-19 10:15:30` | `be302832` | `fork_branch` | `ERR_INVALID_INPUT` | `orthogonal` 缺 `mechanism_signature` |
| #257 | `11-19 10:15:36` | `be302832` | `fork_branch` | `ERR_CONFLICT` | 与 `F_Q3_SEQ_LOCK` 同质 (1.00) |
| #258 | `11-19 10:15:36` | `be302832` | `fork_branch` | `ERR_CONFLICT` | 与 `F_Q3_BAYES_GAIN` 同质 (1.00) |

### 2.4 Live SQLite 数据库全表核对（`greatwall.db?mode=ro`）

全库共 **11 张表**（含 2 张 FTS5 虚拟表）：
- **`observations` = 13 行**：Epoch 1 共 8 行（`[Obs001]`–`[Obs008]`，其中 `002/008` 为 `INVALIDATED`，`001/003–007` 为 `PENDING_REVALIDATION`）；Epoch 2 共 5 行（`[Obs009]`–`[Obs013]`，全部为 `node_id='N_Q3'`、问题 `Q3`；`009/010/011` 经 P26 修复恢复 `VALID`，`012/013` 为 `INVALIDATED`）。**Q1、Q2、Q4 在全库中均为 0 条正式观测**。
- **`lineage_nodes` = 9 行**：Pre-reset 根 `N001/N002/N003`（`depth=0`, `bound_state_version=1`）；Epoch 2 根 `N_Q1/N_Q2/N_Q3/N_Q4`（`depth=0`, `bound_state_version` 分别为 `2/2/2/4`）；停测后新建侧向分叉 `N_9a1b8b04` 与 `N_d25fe5ee`（`parent_id='N_Q3'`, `depth=1`, `bound_state_version=4`）。
- **`method_families` = 18 行**：全部状态为 `EXPLORING`（Pre-reset 3 个 + Epoch 2 15 个）。
- **`candidates` = 8 行**：7 个 `valid` + 1 个 `invalidated`（`b790f20a...`），覆盖 `N001` (4)、`N002` (2)、`N_Q3` (2)。
- **`library_entries` = 41 行**（全部 `status='active'`）：Epoch 1 `L1` = 4 条、`L2` = 12 条（`[F001]`–`[F012]`）；Epoch 2 `L1` = 13 条（`[L1-N_Q1-005]`–`[L1-N_Q4-017]`）、`L2` = 12 条（`[F013]`–`[F024]`）。
- **`reviews` = 0 行**、**`saved_queries` = 0 行**。
- **`epistemic_edges` = 917 行**：`READ` 647、`RETRIEVED` 132、`PRODUCED` 83、`UNAUTHORIZED_TOOL_ATTEMPT` 31、`USED_TOOL` 13、`MOTIVATING_REF` 9、`INDEPENDENT_SUPPORT` 2。
- **`system_meta` = 51 行**：`eval_epoch_version=2`、`state_version=4`、`consecutive_non_l1_handoffs=9`、`pending_revalidation=["[Obs001]","[Obs003]","[Obs004]","[Obs005]","[Obs006]","[Obs007]"]`、`untriaged_handoff_nodes=["N003","N_Q1","N_Q2","N_Q4"]`、8 个 `custom_briefing:*`、31 个 `clock:*`。

| `obs_id` | `node_id` | `session_id` | Epoch | `validity_state` | `comparable_rank_score` | `mean_time_mean` | `success_rate` | `created_at` (UTC) |
|---|---|---|---:|---|---:|---:|---:|---|
| `[Obs001]` | `N001` | `works:main` | 1 | `PENDING_REVALIDATION` | `NULL` | 776.3982 | 1.0 | `2026-11-18T15:50:40Z` |
| `[Obs002]` | `N001` | `works:baseline` | 1 | `INVALIDATED` | `NULL` | 776.4139 | 1.0 | `2026-11-18T15:51:43Z` |
| `[Obs003]` | `N002` | `exp:N002:g1` | 1 | `PENDING_REVALIDATION` | `NULL` | 638.1340 | 1.0 | `2026-11-18T15:53:38Z` |
| `[Obs004]` | `N002` | `exp:N002:g1` | 1 | `PENDING_REVALIDATION` | `NULL` | 705.0408 | 1.0 | `2026-11-18T15:53:54Z` |
| `[Obs005]` | `N002` | `exp:N002:g1` | 1 | `PENDING_REVALIDATION` | `NULL` | 638.1340 | 1.0 | `2026-11-18T15:55:32Z` |
| `[Obs006]` | `N001` | `exp:N001:g2` | 1 | `PENDING_REVALIDATION` | `NULL` | 492.2526 | 1.0 | `2026-11-18T16:00:34Z` |
| `[Obs007]` | `N001` | `exp:N001:g2` | 1 | `PENDING_REVALIDATION` | `NULL` | 504.7280 | 1.0 | `2026-11-18T16:01:10Z` |
| `[Obs008]` | `N001` | `exp:N001:g2` | 1 | `INVALIDATED` | -1,000,877.7207 | 876.7596 | 0.0 | `2026-11-18T16:01:11Z` |
| `[Obs009]` | `N_Q3` | `works:main` | 2 | `VALID` (P26修复) | 999,222.7212 | 776.3982 | 1.0 | `2026-11-18T16:27:38Z` |
| `[Obs010]` | `N_Q3` | `exp:N_Q3:g1` | 2 | `VALID` (P26修复) | 999,489.2498 | 510.2207 | 1.0 | `2026-11-18T17:28:30Z` |
| `[Obs011]` | `N_Q3` | `exp:N_Q3:g2` | 2 | `VALID` (P26修复) | 999,398.2418 | 601.0808 | 1.0 | `2026-11-18T17:35:10Z` |
| `[Obs012]` | `N_Q3` | `exp:N_Q3:g2` | 2 | `INVALIDATED` | `NULL` | 601.0808 | 1.0 | `2026-11-18T17:35:25Z` |
| `[Obs013]` | `N_Q3` | `exp:N_Q3:g2` | 2 | `INVALIDATED` | `NULL` | 601.0808 | 1.0 | `2026-11-18T17:35:26Z` |

---

## 三、重大事件与角色跑偏因果链取证

### 3.1 Parse 0 失守与两轮混乱（`23:28:11 – 00:36:25`）

1. **Pre-Reset 时序倒置与 ROOT 篡位（`23:28:11 – 23:56:26`）**：
   - `23:28:11` ROOT 启动，**未创建 `logistics_coordinator` 亦未创建 `supervisory_committee`**。
   - `23:36:20` ROOT 直接以 `role="logistics_coordinator", session_id="coord:root"` 调用 `init_parse0` 建立 `N001/N002/N003`；`23:36:24` 又以 `role="explorer"` 读 `get_lineage_briefing`。
   - `23:38:13` 与 `23:38:42` ROOT 企图 `write` `06_delivery/paper/main.tex` 与 `check_db.py`，被 `gate.js` 记入 DB `UNAUTHORIZED_TOOL_ATTEMPT` 前两条。
   - `23:45:33` ROOT **在无任何基线观测、无 Phase 0 核签下直接派发 3 路探索者**；`23:48:34` ROOT 擅自起草 `06_delivery/01_formal_paper.md`（后于 `23:53:20 / 23:53:47 / 23:56:23 / 23:57:32` 反复写入 5 次，因后缀为 `.md` 未被 `gate.js` 拦截）。
   - `23:50:40` 工造司才提交 `[Obs001]`（比探索者开跑晚 5 分 07 秒）；**`23:51:10` ROOT 才想起唤醒监委 `ac0de7c2`（距离开局已延迟 23 分钟）**。
   - `23:56:26` 人类直接质问「按照架构设计你不是调度总管啊」，ROOT 才于 `23:56:57` 新建名义总管 `be302832`。
2. **Reset 期 40 分钟文书车轮战（`23:56:57 – 00:36:25`）**：
   - `00:02:04` 人类裁决方案 C「重置 Parse 0 + 删除代写草稿」。随后 ~34 分钟内，`be302832` 与 `ac0de7c2` 陷入高频文本拉锯：**`be302832` 对 `RESET_PARSE0.md` 连续编辑 136 次（从 `v1.0` 迭代至 `v1.16`）、对 `HUMAN_SIGNOFF_PACKET.md` 编辑 75 次**；`ac0de7c2` 对 `RESET_SOP_AUDIT.md` 连续编辑 **84 次**。
   - 状态反复横跳：`00:08:47` `FAIL`（P7 顺序自相矛盾、未冻结版本）→ `00:12:58` `CONDITIONAL PASS` (v1.4) → `00:15:13` (v1.5) → `00:16:05` 拒签 v1.6（3 处角色归属残留）→ `00:19:53` `CONDITIONAL PASS` (v1.10，抓取 `mcp_tools_governance.py:1639–1679` 无 `len` 校验措辞瑕疵) → `00:22:24` `PASS` (v1.11) → `00:22:59` 因漏掉中央图书馆重跑补 `v1.12` → `00:23:53` `CONDITIONAL PASS`（抓出 `library_entries` 实际有 `eval_epoch_version` 字段的措辞错误）→ `00:24:45` `v1.13 PASS`。
3. **抢跑竞态（先执行、后复审）**：`00:25:35` 人类在 Turn 32 回复「签发」后，ROOT 分别通知工造司升级 epoch、通知总管建根、通知监委审核签发包。结果 **`00:26:16` `meltdown_upgrade`、`00:27:21` `init_parse0`、`00:27:38` `[Obs009]` 全部抢在监委复审通过前执行完毕**；ROOT 在 `00:27:35` 急发 `STOP`/`HOLD` 为时已晚（`00:27:23` 监委 Turn 12 判 `H1_H3B_SIGNOFF_AUDIT` FAIL），最终在 `00:27:57–00:32:47` 通过记录“过程偏差：先执行后复审”与升 `manifest v1.1` 才收口，直到 `00:35:29` 监委才签发 `PHASE0_EPOCH2.md` PASS。

### 3.2 监委 `ac0de7c2` 全轨审计与“24 次拦截”辟谣

- **真实行为画像**：`ac0de7c2` 在 20 turns / 365 steps 内消耗 **687,576 字符思考链**，执行 **169 次 `read`、111 次 `edit`、14 次 `write`、9 次只读 MCP 查询**，**0 次 `pwsh`、0 次 `send_message`**。其几乎全部精力都在逐字节计算 `RESET_PARSE0.md`（去掉头部指纹行后的全文 `SHA-256`）、核对 `mtime` / `birthtime`（如为 `H4_DELEGATED.md` 创建时间 `16:36:07.052Z` 与修改时间 `16:45:34.905Z` 争论 Q1 是否早于 H4 31 秒）以及逐行校准总管文档中的代码事实措辞。
- **Turn 25（`00:22:11`）人类质问「监委在查啥，不是只查流程吗？」因果核实**：
  - *表面诱因*：`00:20:51–00:21:01` ROOT 连续向人类汇报 `H1/H2/H3` 学术断言收口并称「`v1.11` 已送监察委复审…顺带核四份 intent、15 个学派候选」，且未安排图书馆重跑 S4，引发用户质疑监委越界评审科学内容。
  - *原始轨迹实证*：核查 `ac0de7c2` Turn 9（`00:20:46–00:22:24`）全部 `edit` 与输出原文，**`ac0de7c2` 并未评价 `H1–H3` 数学真伪或学派优劣**，其核验点严格限定在「四份 `SCIENTIFIC_INTENT.md` 已落盘且无‘失败审判’判定语」「15 个候选只在 `registry §0.1` 未调用 `register_method_family` 入账」「指纹匹配」。但该误解迫使 `ac0de7c2` 在 `00:22:58` 额外增设“明确不属监委职权”免责清单。
- **彻底辟谣“24 次被拦截”**：`r2_events_audit.txt` 统计 `ac0de7c2` 有 `24` 次 `gate_blocks`，纯属其脚本用 `substring` 扫描 `ac0de7c2` 通过 `read`/`grep` 读到的别人被拦截记录或审计报告正文。核对全部 `tool/ptc-dispatch` 的 `isError` 及数据库 `UNAUTHORIZED_TOOL_ATTEMPT` 边：**`ac0de7c2` 真实被 `gate.js` 拦截次数 = `0`**（仅发生过 4 次常规工具调用错误，如 `glob` 路径 `D:\DshDesktop\resources\app.asar\dsh` 不存在、Windows 路径漏斜杠等）。

### 3.3 总管分裂与 ROOT 微操

| 维度 | ROOT (`session-56a36cab`) — 实际大管家 | 名义总管 (`be302832`) — 文书盖章员 |
|---|---|---|
| **角色契约注入** | 无角色限制（系统提示词 + `greatwall-research-loop` skill） | **插件配置缺失**：`core_python/agents/` 下无 `logistics_coordinator.md`（仅 `central_library/explorer/lineage_companion/supervisory_committee/works_engineer` 5 个文件），故 `be302832` 仅获 `99,592` 字节通用基础提示词（`injected_role=""`） |
| **调度与通信** | **`subagent` 37 次（包揽全部建人）**；**`send_message` 173 次**（78 次指令 `be302832`、16 次工造司、16 次监委、其余直达各探索者与伴随） | **`subagent` 0 次**、**`pwsh` 0 次**；`send_message` 93 次中 **53 次向 `lead` 交差汇报**，仅 5 次直达探索者 |
| **行为失范与精力去向** | 1) Pre-reset 冒用 `coord:root` 调 `init_parse0`；<br>2) `23:47:04`、`23:58:53` 直接向探索者/工造司推送几何半径、外圈环布点等科研方案；<br>3) `23:48:34–23:57:32` 擅自 5 次撰写 `06_delivery/01_formal_paper.md`；<br>4) `01:39` 越过盲审与分诊直接接受 Q3 假结案 | 476 步中 **315 次 `edit` + 45 次 `write`**（仅 `RESET_PARSE0.md` 136 次、`HUMAN_SIGNOFF_PACKET.md` 75 次），思言比低至 **6.95**；被降格为替 ROOT 和监委抄写/修改流程文档、登记偏差单的文书秘书 |
| **为什么不调分叉/盲审** | ROOT 在宏观层面被 `01:38` `Q3_T3_FULL` 的 30/30 结果迷惑，错误接受结案；在 Reset 后未把自主权交给总管 | `be302832` 既无 `logistics_coordinator.md` 角色契约强化“四级分诊/正交分叉/派发盲审”职责，又在 `01:39–01:49` 被 ROOT 连续指令 `STAGNATION_DEFER`、追查 Q4 与文书，导致 Epoch 2 全程 **0 分诊、0 分叉、0 盲审** |
| **门禁拦截真实数** | **2 次**（`23:38:13/42` `write` `.tex`/`.py` 被 `gate.js` 拦截并写入 DB） | **`gate.js` 拦截 = 0 次**（`r2_events_audit.txt` 所谓 `13` 次为读档误算）；仅 1 次 MCP `query_library_mcp` 因错传 `role="explorer"` 触发 `ERR_LOCKED` |

### 3.4 P26 悬案真相：`[Obs009/010/011]` 状态异常因果链

`11-19 10:06` 复核发现 DB 中 `[Obs009]/[Obs010]/[Obs011]` 变成了 `PENDING_REVALIDATION` 且 `comparable_rank_score=NULL`，而 `system_meta.pending_revalidation` 仍停留在 Epoch 1 的 `["[Obs001]","[Obs003]","[Obs004]","[Obs005]","[Obs006]","[Obs007]"]`。工造司 `dfe03c70` 在 `P26_REPAIR_EXECUTION.md §5` 中误判为“外部脚本手工 `UPDATE observations` 所致”。

**真实因果链（`mcp_tools_research.py:1297–1352` 源码 + MCP 日志实锤）**：
1. **`01:35:10–26`**：`explorer-q3-g2` (`44de4e7e`) 在 `N_Q3` 上连续提交 `[Obs011]`、`[Obs012]`、`[Obs013]`，此时 `state_version=2`，`N_Q3.bound_state_version=2`。
2. **`01:36:35`**：`be302832` 连续两次调用 `invalidate_observation` 作废重复的 `[Obs012]` 和 `[Obs013]`，将全局 `system_meta.state_version` 从 `2` 推进至 **`4`**（见 `system_meta` 时间 `2026-11-18T17:36:35.233919Z`）。
3. **`01:38:03`**：`comp-q3` (`6a77d192`) 调用 `submit_node_handoff`（#17）传入 **`bound_state_version=4`**（与 `cur_state=4` 对齐），`late_submission=false`，成功入库 `[L1-N_Q3-014]`。
4. **`01:38:57`（引爆点）**：`explorer-q3-g2` (`44de4e7e`) 调用 `submit_node_handoff`（#18）交接 `[L1-N_Q3-015]`，仍沿用其启动时的旧 **`bound_state_version=2`**！
5. **服务端静默连坐逻辑**：在 `mcp_tools_research.py:1297–1314` 中：
   ```python
   late_or_stale = (
       int(bound_state_version) < cur_state   # 2 < 4 -> True!
       or int(eval_epoch_version) < cur_epoch
       or has_invalid_ref
   )
   if late_or_stale:
       rw_conn.execute("""
           UPDATE observations
           SET comparable_rank_score = NULL,
               validity_state = CASE
                   WHEN validity_state = 'VALID' THEN 'PENDING_REVALIDATION'
                   ELSE validity_state
               END
           WHERE node_id = ?
       """, (node_id,))
   ```
   因 `2 < 4`，服务端判定 `late_submission: true`，将 `N_Q3` 下所有 `VALID` 观测（即 `[Obs009]/[Obs010]/[Obs011]`）就地降为 `PENDING_REVALIDATION` 并清空分数，**却没有同步把它们写入 `system_meta.pending_revalidation` 队列**，且在第 1334–1352 行顺手把 `lineage_nodes` 中 `N_Q3.bound_state_version` 覆盖回 `2`！由于该过程发生在 `01:38:57`（`apply_stagnation_lanes` 在 `01:49:52`），`apply_stagnation_lanes` 确实是无辜的，而 `P26_REPAIR_EXECUTION.md` 漏查了 `submit_node_handoff` 的这段分支。

### 3.5 物理上下文时钟（37% / 70%）触发详单与“刚热身就停笔”实证

- **去重口径**：`r2_events_audit.txt` 扫出的 `33` 次（原文原始正则命中 34 次）中，**26 次**为插件向 `user/message`（`source.kind='greatwall-v6up-clock'`）注入的真实物理时钟警告（**13 个完整运行过的探索者会话 × 2 次**，`e7de5d3d` 因 step 21 遇 `402` 余额不足未触及时钟），其余为 7 次 `read`/`grep` 工具输出中的文本回显及 1 次消息转发。
- **早停机制根因**：`dsh_plugin/lib/event_bus.js:15–20, 193–228` 设定 `defaultContextWindow=178500`、`reflectHintPct=0.37`（**66,045 tokens**）、`handoffPct=0.70` / `handoffTokenCap=125000`（**124,950 tokens**），并在 `tools/pre-execute` 通过 `TokenMeter.contextPressure(agent.session)` 读取**含系统提示词在内的全量上下文压力**。由于 DSH 基础系统提示词 + 角色契约 + 技能目录本身已约 **100KB（~4.5–5.5 万 tokens）**，探索者刚读完几份背景文档即跨过 66k 门限。

| 序号 | 会话 | 节点/标签 | 37% 触发时间 / Step / R字符 / 当时状态 | 70% 触发时间 / Step / R字符 / 当时状态 |
|---:|---|---|---|---|
| 1 | `f183308a` | `N001` g1 | `23:46:58` / S13 / R=27,823 / `cand=✗ pwsh=5 obs=0` | `23:51:01` / S31 / R=86,799 / `cand=✗ files=5 pwsh=9 obs=0` |
| 2 | `3cdf9308` | `N002` g1 | `23:46:52` / S10 / R=31,965 / `cand=✗ pwsh=4 obs=0` | `23:52:06` / S24 / R=141,260 / `cand=✗ files=9 pwsh=11 obs=0` |
| 3 | `55f0cfda` | `N003` g1 | `23:45:57` / S10 / R=2,796 / `cand=✗ pwsh=0 obs=0` | `23:51:40` / S21 / R=163,623 / `cand=✗ files=7 pwsh=8 obs=0` |
| 4 | `d5e0e2bd` | `N001` g2 | `23:52:34` / S12 / R=1,292 / `cand=✗ pwsh=1 obs=0` | `23:57:48` / S22 / R=130,195 / `cand=✓ files=15 pwsh=6 eval=✓ obs=0` |
| 5 | `66275d55` | `N003` g2 | `23:53:42` / S11 / R=25,513 / `cand=✗ pwsh=0 obs=0` | `23:58:48` / S23 / R=141,440 / `cand=✗ files=5 pwsh=5 obs=0` |
| 6 | `09858243` | `N_Q1` g1 | `00:40:12` / S13 / R=70,972 / `cand=✗ pwsh=8 obs=0` | `00:43:36` / S21 / R=122,558 / `cand=✗ files=0 pwsh=8 obs=0` |
| 7 | `7e921c83` | `N_Q1` g2 | `00:47:15` / S14 / R=34,600 / `cand=✗ pwsh=5 obs=0` | `00:52:32` / S26 / R=117,536 / `cand=✗ files=9 pwsh=7 eval=✓ obs=0` |
| 8 | `9de4655d` | `N_Q1` g3 | `00:56:40` / S13 / R=28,148 / `cand=✗ pwsh=1 eval=✓ obs=0` | `01:00:16` / S31 / R=97,153 / `cand=✗ files=19 pwsh=15 eval=✓ obs=0` |
| 9 | `9271b6e8` | `N_Q2` g1 | `01:09:10` / S13 / R=128,088 / `cand=✗ pwsh=3 obs=0` | `01:12:19` / S22 / R=134,090 / `cand=✗ files=3 pwsh=4 obs=0` |
| 10 | `e8e2f112` | `N_Q3` g1 | `01:19:45` / S9 / R=2,402 / `cand=✗ pwsh=0 obs=0` | `01:27:54` / S37 / R=78,650 / `cand=✓ files=22 pwsh=12 eval=✓ obs=0` |
| 11 | `44de4e7e` | `N_Q3` g2 | `01:33:24` / S19 / R=5,094 / `cand=✗ pwsh=7 obs=0` | `01:38:45` / S46 / R=56,594 / `cand=✗(零改码) files=11 pwsh=22 eval=✓ obs=3` |
| 12 | `b360d5ff` | `N_Q4` g1 | `01:38:14` / S7 / R=1,781 / `cand=✗ pwsh=1 obs=0` | `01:42:02` / S20 / R=82,288 / `cand=✓ files=5 pwsh=8 eval=✓ obs=0` |
| 13 | `918d598a` | `N_Q4` g2 | `01:44:43` / S9 / R=3,619 / `cand=✗ pwsh=0 obs=0` | `01:48:43` / S27 / R=67,955 / `cand=✓ files=15 pwsh=2 eval=✓ obs=0` |

> **实证结论**：在 37% 节点，**13 个探索者中有 13 个未写出 `candidate.py`、13 个未提交 `[Obs]`、7 个仅执行 0–1 次 `pwsh`**；即使到 70% 强停节点，也只有 4 个会话写出 `candidate.py`，且除零改码重跑的 `44de4e7e` 外，**全部新写代码的探索者在触发 70% 强停时均尚未完成 `[Obs]` 提交**（`3cdf9308`、`d5e0e2bd`、`e8e2f112` 均是在 70% 时钟响起之后才抢交或收尾提交 `[Obs]`，`b360d5ff` 与 `918d598a` 则直接空手退场）。
