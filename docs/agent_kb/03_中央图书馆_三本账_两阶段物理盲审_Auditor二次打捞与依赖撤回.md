# 知识卡 03：中央图书馆两翼、沙箱化实测盲审、三态分流与双段式终局（v3.0）

> **核心依据来源**：  
> - [`../architecture/手写project.md`](../architecture/手写project.md)（L144–156 图书馆自包含手稿、对抗审稿；L114–119 反常反例保护）  
> - [`../round4_audit/01_交顶层设计者_原文对照与架构讨论稿_对齐版.md`](../round4_audit/01_交顶层设计者_原文对照与架构讨论稿_对齐版.md) & [`03_顶层设计深度审阅_原文溯源与决策对照_对齐版.md`](../round4_audit/03_顶层设计深度审阅_原文溯源与决策对照_对齐版.md) & [`第六轮审阅（针对第四轮测试）.md`](../round4_audit/第六轮审阅（针对第四轮测试）.md)（盲审沙箱开放执行工具、废除 `passed=1` 与缺 `READ` 强制降级、三态分流、`REVISE` 与打捞互不冲突、确证反例入 `L3`、CDC 双段式终局）  
> - `Cogentic` [`§2.2, §2.3, §2.5`](file:///D:/Documents/deepseek%20harness/论文研读/2609.40324_Cogentic_Multi-Agent_Orchestration_for_Automated_Proof_Discovery/2609.40324_Cogentic_中文综述.md#L167-L233) & `Station v2` [`App D`](file:///D:/Documents/deepseek%20harness/论文研读/2610.08927_Can_AI_Agents_Make_Open-Ended_Scientific_Discovery_Evidence_from_Station/2610.08927_Station_OpenEndedDiscovery_中文翻译.md#L584-L603)  
> - `OpenAI CDC Prompt` [`#L162-L191`](file:///D:/Documents/deepseek%20harness/论文研读/OpenAI_Prompt_Used_for_A_Proof_of_the_Cycle_Double_Cover_Conjecture/OpenAI_圈双覆盖猜想Prompt_中文全译与深度解析.md#L162-L191)（最短投入时间 + 只交严密证明及精确剩余缺口）

---

## 一、外藏（参考先验）与内藏（确证知识 + 否定雷达）重构边界

### 1.1 “外藏 + 内藏”物理分表与两级目录 Pull（`0–37%` 锁内藏维持极简）
1. **左翼·外藏表 `external_literature_cards` (`[R###]`)**：
   - `0%` 起全程对全员开放两级 Pull；由 `library_surveyor`（有搜索/PDF 工具，无审稿写权）维护；
   - **定位纠偏**：`[R###]` 本质是**“带出处但未经本系统独立复验的外部参考摘要”**（防如第四轮 `R001` Jung 定理不等号写反后被当作免死金牌）；入库只校验基本元数据、公式字段、阅读深度（`full_text / specified_sections / abstract_only`）、5 选 1 英文 `support_scope` 枚举与真实独立 `abstract_md`（**编写建议 120–300 字；服务端硬拒边界 60–1500 字符**），**学术正确性由引用该文献的手稿作者与 Stage 1 盲审在推导/计算中自行核实**。
2. **右翼·内藏表 `internal_research_ledger`（`L3_VERIFIED` 确证库 & `L2_FAILURE_RECORD` 否定雷达）**：
   - `0–37%` 保持物理锁定，**必须经过 `37%` 元反思提神校准后才解锁**；
   - **v3.0 确证知识边界扩容（解决正反例混装垃圾堆）**：
     - **`L3_VERIFIED` 不仅存正向定理/最优算法**！任何通过两阶段盲审实测、逻辑与计算完全无懈可击的**严格构造反例（`NEG_COUNTEREXAMPLE`）**与**结构阻碍证明（`BARRIER_PROOF`）**同样属于已确立的硬科学事实，带上 **`l3_entry_kind` 标签（`POS_THEOREM` | `NEG_COUNTEREXAMPLE` | `BARRIER_PROOF`）** 堂堂正正入库 **`L3`**，可直接供后续分支免证引用和 Stage 3 写入论文正文！
     - **`L2_FAILURE_RECORD` 严格减负瘦身**：仅存储两类否定经验——① 被盲审实锤证伪、发现致命反例或逻辑崩坏的假说路线（`REFUTED`）；② 经最多 `2` 轮 `REVISE` 退回仍无法解决的审稿异议（`UNRESOLVED_OBJECTION`）。
   - **工程报错彻底踢出图书馆**：所有候选语法错误、运行崩溃、修补满 3 次超时或沙箱故障，**绝对不得污染 `L2` 失败雷达**！统一归属工造司工单或本门派私有 `lineage_dead_ends` 表。

---

## 二、废除 `passed=1` 死锁：按主张类型匹配可核验性准入

第四轮 `tools_logistics.py#L325` 硬要求 `VALID && passed=1` 才准送审，直接堵死了纯数学推导与构造反例通道。v3.0 送审准入只检**“主张类型与可核验载体是否匹配”**（后勤只检形式完整性，不判真伪）：

| 手稿科学主张形态 | 送审必需核验载体（至少齐备一项） | 防灌水守卫 |
|---|---|---|
| **数值 / 物理仿真 / 优化主张** | 合法 `official` / `heavy` 档（非 `probe`、非仪器故障）的 `[Obs###]` 收据（含 `VALID_PASS` / `VALID_UNDECIDED`；若为无隐藏集的开放发现题，则附固定配置与多种子复跑 `[Obs###]`）及脱敏核心代码，供盲审沙箱做独立变种子/扰动复现 | • 每个谱系节点最多送审 **1 份**手稿<br>• 同分支 `revise_count` 超限归档后降权 |
| **形式化定理证明主张** | 对应的证明检查器（如 Lean 4 `lake build`）仪器 `PASS` 凭证及源码文件 | 同上 |
| **构造性反例主张** | 明确具体的反例对象参数/数据 + 最小可运行复核校验脚本（供盲审沙箱当场跑验算） | 同上 |
| **纯解析数学推导主张** | 自包含（Self-Contained）分步推导正文 + 前提公理边界声明 + 极端特例自检说明（供带计算沙箱的盲审官逐行拆解验算） | 同上 |

---

## 三、盲审沙箱工具平权 & 三态两阶段盲审状态机

### 3.1 彻底解除“0 原生工具阉割”：建立独立隔离盲审沙箱
1. **沙箱平权裁决**：在 v2.2 中 `library_verifier` 只有 0 个原生工具（`[]`），纯靠瞪眼猜推导。v3.0 为每次盲审会话拉起**物理隔离的临时盲审沙箱工作区**：
   - **允许开放原生工具**：`read`, `glob`, `grep`, **`pwsh`, `bash`**（可内置 Python/SymPy 及未来的 Lean 4 证明检查器插件）；
   - **OS 层与 Guard 物理封死禁区**：绝不允许读取 `greatwall.db`、`_hidden_*` 隐藏测试集、探索者 Worktree 目录、B 栏主观叙事以及外部网络。
2. **Stage 1 盲态跑证（`STAGE1_BLIND`）**：
   - 事件总线在启动消息注入 `review_id`，控制面仅将**手稿 A 栏 + 脱敏候选脚本/证明源码/反例数据 + 原始 `[Obs###]`** 拷贝进该临时盲审沙箱；
   - 盲审官先对照 `OpenAI CDC` 7 类结构漏洞清单，并**亲自在沙箱内运行 `pwsh`/Python/SymPy/Lean 脚本复算反例数值、核对特例极限与守恒恒等式**；
   - 严格履行 `Station Appendix D` 6 步构建 **`Evidence Ledger`**（缺实证必须一字不差填 `"No direct evidence found"`），调用 `submit_stage1_blind_ledger` 永久锁死 `stage1_locked_at`。**若 Stage 1 判 `REFUTED`（发现确定反例或逻辑矛盾），短路结案同事务置 `SEALED` 并入 `L2`；若判 `REVISE`（缺某步证明/数据补充），扣减同 Stage 2 共用的 `revise_count`（`<= 2` 次退回原分支恢复 `ACTIVE_REVISING`，第 `3` 次仍未过审直入 `L2`）！**

### 3.2 Stage 2 解盲 & 三态审稿分流（消灭“退回返工 vs Auditor 打捞”冲突）
Stage 1 通过后调用 `get_unblinded_manuscript_and_peers(review_id)` 解开 B 栏、同题其他流派 `L3`/在审稿横向快照（`Cross-Draft`）与**仅作参考的 `FACT_LOG` 对照信息（废除“缺 `READ` 边就强制缩窄或拒稿”！）**，随后调用 `submit_stage2_unblind_verdict` 裁决为以下**三态之一**：

| 三态终审裁决 (`final_verdict`) | 触发判定语义 | 数据库事务与后续路线流向 |
|---|---|---|
| **1. `ACCEPT` / `ACCEPT_NARROWED`** | 论证严密或收窄成立范围后严密无误（含严格证伪反例/障碍证明） | 同事务剥离作者写入 **`L3_VERIFIED`**（附 `l3_entry_kind` 与 **`goal_coverage: "FULL_GOAL"|"PARTIAL_OR_LEMMA"|"EQUIVALENT_REDUCTION"`**：凡 `ACCEPT_NARROWED`、局部引理、`is_equivalent_reduction=true` 或不符合契约要求的证伪均不得标为 `FULL_GOAL`），原分支如属结案送审则置 `SEALED`；可附 `cross_pollinate_nomination`（需双方各有 `>= 1` 条 `L3`） |
| **2. `REVISE`（退回原分支返工，Stage 1/2 共用最多 `2` 次退回机会）** | 材料欠缺、边界情况遗漏、存在局部可修补跳跃，**但核心路线未被证伪** | **原分支由 `PENDING_REVIEW` 回切为 `ACTIVE_REVISING` 原汁原味返工！** Stage 1 与 Stage 2 共用唯一 `revise_count`，每次判 `REVISE` 时 `revise_count += 1`：第 `1–2` 次退回进看板充当改进梯度（**返工期间严禁 `Auditor` 插手**）；**若第 `3` 次仍无法 `ACCEPT*`（不允许第 3 次退回），服务端直接结案置 `SEALED` 并转入 `L2 (UNRESOLVED_OBJECTION)`** |
| **3. `REFUTED`（确定性证伪）** | 被确定反例击穿核心命题，或核心架构存在不可修复矛盾 | 同事务提炼精确失灵范围写入 **`L2_FAILURE_RECORD (REFUTED)`**；仅针对此类已关闭分支（或 `LEVEL_4B` 阻塞、`REVISE` 超限分支），才允许唤醒 `Auditor` 调用 `propose_salvaged_lemma` 从残骸打捞自包含局部引理，投回 `STAGE1_BLIND` 交**另一独立盲审会话**复验 |

---

## 四、默认无连坐引用边界与 CDC 双段式终局门禁

### 4.1 反转默认引用边类型为 `MOTIVATING_REF`（G1 + B10 纠偏）
- 探索者提交的 `declared_refs: list[str]`（包含 `[R###]` 与 `[L3-###]`）在写入 `epistemic_edges` 时，**默认边类型从 `REQUIRED_PREMISE` 彻底改回 `MOTIVATING_REF`（启发/背景参考，不传播级联撤回）**；
- 唯独 Stage 2 盲审官在 `submit_stage2_unblind_verdict` 中通过 `edge_type_overrides` **明确认证某条上游 `L3` 为当前结论承重基石（`REQUIRED_PREMISE`）**时，若日后该前置 `L3` 被推翻，才沿着这批精准的 `REQUIRED_PREMISE` 边级联撤回重审，绝不搞“随手一引就全军连坐”。

### 4.2 CDC 双段式终局交付门禁（`check_stage2_closure_gate` — F4 定案）
沿袭 [`OpenAI CDC Prompt#L162-L191`](file:///D:/Documents/deepseek%20harness/论文研读/OpenAI_Prompt_Used_for_A_Proof_of_the_Cycle_Double_Cover_Conjecture/OpenAI_圈双覆盖猜想Prompt_中文全译与深度解析.md#L162-L191) “跑满最短时间，否则绝不轻言退出；真穷尽时只交严格证明过的结果与精确剩余缺口”的双段硬标准：
1. **标准完全结题线 (`mode="FULL"`)**：Parse 0 契约列出的每一道必答子题均在 `internal_research_ledger` 至少有 `1` 条活跃且 **`goal_coverage == "FULL_GOAL"`** 的 `L3_VERIFIED`（仅局部特例 `ACCEPT_NARROWED`、中间引理与 `EQUIVALENT_REDUCTION` 均不算全题完成；若契约明确允许证伪，该子题的 `NEG_COUNTEREXAMPLE` / `BARRIER_PROOF` 方可标 `FULL_GOAL`）。
2. **最短投入时间硬锁定（仅防 Agent 自行提前交差）**：只要系统尚未跑满 Parse 0 设定的 **`min_commitment_window`（例如 8 小时或对应总预算比例）**，**物理禁止 Agent 以 `PARTIAL_ON_BUDGET` 或“无解”收工**——遇阻必须强制触发 Station 五车道停滞自救与学派重分配。
3. **诚实部分交付 (`mode="PARTIAL_ON_BUDGET"` / 人类紧急叫停 `human_aborted`)**：① 越过 `min_commitment_window` 且预算耗尽时，或 **② 人类用户显式主动叫停（`human_aborted == true`，不受 `min_commitment_window` 阻拦，立即停止派单）**时，允许 `library_surveyor` 调用 `export_stage3_final_delivery` 出具部分成果交付包——但**强硬铁律是：终局正文只允许组装已通过两阶段盲审入库的 `L3` 成果，并逐题如实列出未完成子题的精确剩余断点（Remaining Gaps），绝对禁止把任何未过盲审的草稿、吹捧总结塞进最终交付！**
