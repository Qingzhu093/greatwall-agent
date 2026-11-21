# 知识卡 03：中央图书馆与隔离沙箱盲审——两翼分表、可核验准入、三态裁决与双段终局

> **模块归属**：`library_surveyor`（外藏采编 & Stage 3 成文）、`library_verifier`（隔离沙箱实测盲审 & Auditor 异会话打捞）与 `supervisory_committee` 终局核签。  
> **配套阅读**：[`04` 顶层白皮书 §4.3](../architecture/04_长城%20Agent%20V6-Up：面向长周期自主科学发现的多智能体系统架构白皮书（v3.0）.md#43-中央图书馆与沙箱盲审两翼分表可核验准入三态裁决与非连坐引用) ｜ [`05` 角色模板直抄库](./05_原论文级Prompt武器库与五大角色完整模板直抄库.md)

---

## 一、两翼物理分表：外部先验参考 vs 内部确证知识与否定雷达

中央图书馆是全社区跨门派交流与知识沉淀的唯一权威枢纽。底层物理分为两张独立的 SQLite 表，上层共用统一的**两级按需目录检索**（`query_library_catalog` 浏览 `<= 350` 字独立摘要目录卡 $\to$ `get_library_entry` 按 ID 拉取全文）：

1. **左翼·外藏表 `external_literature_cards` (`[R###]`)**
   - **可见性与维护者**：从 `0%` 起全程对全员开放两级 Pull；由 `library_surveyor`（持搜索与文档读取权限，无审稿写权）在 Stage 1 预采编或在 Stage 2 响应 `request_literature_survey` 补充。
   - **认识论定位**：明确标定为**“带来源出处但未经本系统独立实证复验的外部参考摘要”**。入库时服务端强校验元数据完整性、公式与前置假设、`read_depth`（`full_text / specified_sections / abstract_only`）、5 选 1 英文 `support_scope` 枚举及独立撰写的 `abstract_md`（推荐 `120–300` 字，服务端硬限 `60–1500` 字符）。**文献中公式的学术正确性与适用性，由引用该文献的手稿作者与 Stage 1 盲审在推导/计算中自行核验**。
2. **右翼·内藏表 `internal_research_ledger`（`L3_VERIFIED` 确证库 & `L2_FAILURE_RECORD` 否定雷达）**
   - **可见性与解锁**：`0–37%` 物理锁定，探索者完成 `37%` 元反思当场置位 `first_reflection_unlocked = 1` 后开放两级 Pull。
   - **`L3_VERIFIED`（硬科学确证库）**：不仅收录正向定理与最优算法（`POS_THEOREM`），也收录所有通过隔离盲审实测、逻辑与计算完全无懈可击的**严格构造反例（`NEG_COUNTEREXAMPLE`）**与**结构阻碍证明（`BARRIER_PROOF`）**！每条 `L3` 显式携带：
     - `l3_entry_kind`：`POS_THEOREM` | `NEG_COUNTEREXAMPLE` | `BARRIER_PROOF`
     - `goal_coverage`：`FULL_GOAL` | `PARTIAL_OR_LEMMA` | `EQUIVALENT_REDUCTION`
   - **`L2_FAILURE_RECORD`（纯粹的科学否定雷达）**：仅存储两类高价值否定经验——① 被盲审实锤证伪、发现致命反例或不可修复逻辑崩坏的假说路线（`REFUTED`）；② 经最多 `2` 轮 `REVISE` 返工仍无法解决的审稿异议（`UNRESOLVED_OBJECTION`）。
   - **工程故障隔离**：一切候选代码语法错、运行超时、修补满 3 次失败或沙箱异常，统一归属工造司工单或本门派私有 `lineage_dead_ends` 表，**严禁写入中央图书馆 `L2`**。

---

## 二、按科学主张形态匹配的可核验送审准入标准

后勤在 `LEVEL_1` / `LEVEL_4A` 送审时，只检验材料与主张类型的形式匹配度（不判真伪），由“单节点最多送审 1 份手稿”与“超限退回降权”机制防止灌水：

| 手稿科学主张形态 | 送审必需可核验载体（至少齐备一项） | 盲审沙箱复核方式 |
|---|---|---|
| **数值 / 物理仿真 / 优化主张** | 合法 `official` / `heavy` 档 `[Obs###]` 收据（含 `VALID_PASS` / `VALID_UNDECIDED`；无隐藏集的开放发现题附固定配置多种子复跑 `[Obs###]`）及脱敏核心代码 | 在盲审沙箱中运行脱敏代码，执行独立变种子或扰动边界复现验算 |
| **形式化定理证明主张** | 证明检查器（如 Lean 4 `lake build`）仪器 `PASS` 凭证及完整源码文件 | 在盲审沙箱核对原命题声明哈希、`#print axioms` 公理审计并实跑编译 |
| **构造性反例主张** | 明确具体的反例对象参数/数据 + 最小可运行复核校验脚本 | 在盲审沙箱直接运行复核脚本验算前提成立与原命题被破坏 |
| **纯解析数学推导主张** | 自包含分步推导正文 + 完整前提公理与边界声明 + 极端特例自检说明 | 在盲审沙箱借助 Python/SymPy 逐行验证代数恒等式、边界极值并排查 7 类结构漏洞 |

---

## 三、隔离沙箱两阶段实测盲审与三态裁决状态机

### 3.1 独立空白盲审沙箱（跑着验证，而非瞪眼猜）
每次唤醒 `library_verifier`，控制面为其现建独立空白临时沙箱目录 `blind_sandbox_<review_id>/`：
- **沙箱内开放工具**：`read`, `glob`, `grep` 及按 OS 平台开放的 Shell（Windows 开放 `pwsh`，类 Unix 开放 `bash`，附 Python/SymPy 及已安装的 Lean 4 等验证工具）；
- **OS 与 Guard 双重封死禁区**：物理拒读 `greatwall.db`、`_hidden_calibrations/`、手稿 B 栏主观叙事、探索者 Worktree 目录与外部网络；审毕立即清理。

### 3.2 Stage 1 盲态跑证（`STAGE1_BLIND`）
1. 事件总线在启动消息注入 `review_id`；调用 `get_blind_manuscript(review_id)` 后，控制面将手稿 **A 栏、脱敏代码/证明/反例文件与原始 `[Obs###]`** 拷贝进当前空白沙箱（物理剥离作者、分支 ID、历史得分与 B 栏）。
2. 盲审官对照 **OpenAI CDC 7 类结构漏洞红队清单**（隐式假设、退化极限、局部冒充全局、伪等价引理归约、循环“显而易见”跳跃、代理指标作弊、混杂变量充因果），并**亲手在沙箱内执行脚本、SymPy 或 Lean 实测验算**。
3. 严格按 `Station Appendix D` 6 步法则构建 **`Evidence Ledger`**（每条断言必须引述精确位置或沙箱实测输出，缺证必填 `"No direct evidence found"`），调用 `submit_stage1_blind_ledger` 永久锁定不可逆时间戳 `stage1_locked_at`：
   - **`PASS`**：进入 `STAGE2_UNBLIND`；
   - **`REVISE`**：核心方向未证伪但缺关键子检验或边界步，扣减与 Stage 2 共用的 `revise_count`（`<= 2` 次切回原分支 `ACTIVE_REVISING` 返工；第 `3` 次仍未过审直入 `L2` 并置 `SEALED`）；
   - **`REFUTED`**：实测发现致命反例或不可修复逻辑矛盾，直接短路结案置 `SEALED` 并写入 `L2(REFUTED)`。

### 3.3 Stage 2 解盲横审（`STAGE2_UNBLIND`）与三态终判
仅当 `stage1_locked_at IS NOT NULL` 且 Stage 1 `PASS` 时调用 `get_unblinded_manuscript_and_peers(review_id)`，解开本篇 B 栏机理阐释、同子题他脉 `L3`/在审稿横向快照（`Cross-Draft`）与**参考性 `FACT_LOG` 轨迹**（仅作辅助核对参考，绝不因未调读卡工具引用常规公理而机械惩罚）。随后调用 `submit_stage2_unblind_verdict` 给出三态终判：

| 三态终判 (`final_verdict`) | 判定语义 | 数据库事务与分支去向 |
|---|---|---|
| **`ACCEPT` / `ACCEPT_NARROWED`** | 论证严密或收窄适用范围后严密成立（含确证反例与障碍证明） | 同事务剥离作者写入 **`L3_VERIFIED`**，显式标注 `l3_entry_kind` 与 `goal_coverage`（**凡 `ACCEPT_NARROWED` 缩窄特例、局部引理、`is_equivalent_reduction=true` 伪等价归约、或契约未认可的证伪均严禁标为 `FULL_GOAL`**）；若属结案送审则置分支 `SEALED`；可提名 `cross_pollinate_nomination`（须双方学派各有 `>= 1` 条 `L3`） |
| **`REVISE`**（Stage 1/2 共用最多 `2` 次退回） | 论证存在局部缺口或边界遗漏，但核心路线未证伪 | 原分支从 `PENDING_REVIEW` 恢复 **`ACTIVE_REVISING`**，审稿 `revision_requests` 注入下代看板作为明确改进梯度（**返工期间严禁 `Auditor` 插手**）；第 `3` 次送审仍无法通过则服务端直接结案置 `SEALED` 并写入 `L2(UNRESOLVED_OBJECTION)` |
| **`REFUTED`** | 核心命题被反例击穿或存在根本不可修复矛盾 | 同事务提炼精确失灵边界写入 **`L2_FAILURE_RECORD(REFUTED)`** 并置分支 `SEALED` |

### 3.4 `Auditor` 废墟引理打捞（零旁路后门）
仅针对**已关闭或阻塞的节点**（`REFUTED`、`LEVEL_4B` 或 `REVISE` 超限关闭；**服务端强校验原分支不处于 `ACTIVE_REVISING` 返工期**），可唤醒 `Auditor` 调用 `propose_salvaged_lemma` 将残骸中有价值的局部引理剥离原上下文重写为自包含命题，作为一张全新的 `STAGE1_BLIND` 审稿单投入 `review_queue`（记录 `proposer_session_id`）。控制面拉起**另一名独立 `library_verifier` 会话**（服务端硬校验 `session_id != proposer_session_id`）按标准两阶段沙箱盲审复验通过后方可入 `L3`。

---

## 四、默认非连坐引用传播与 CDC 双段式终局门禁

### 4.1 引用边默认 `MOTIVATING_REF`（防无差别全军连坐）
- 探索者提交的 `declared_refs: list[str]` 写入 `epistemic_edges` 时，**默认边类型为 `MOTIVATING_REF`**（背景/启发参考，上游变动不触发下游连坐撤回）；
- 唯有 Stage 2 盲审官在 `submit_stage2_unblind_verdict` 中通过 `edge_type_overrides` **显式认证某上游 `L3` 为当前结论承重必要前提（`REQUIRED_PREMISE`）**时，若日后该前置被推翻，才沿着这批精准的 `REQUIRED_PREMISE` 边级联撤回重审。

### 4.2 双段式终局门禁（`check_stage2_closure_gate`）与两步联合终核
1. **完全结题（`mode="FULL"`）**：Parse 0 契约列出的每一道必答子题均在 `internal_research_ledger` 存在至少 `1` 条活跃且 **`goal_coverage == "FULL_GOAL"`** 的 `L3_VERIFIED`。
2. **最短投入时间约束与诚实部分交付**：
   - 未满 Parse 0 设定的 **`min_commitment_window`** 时，**物理禁止 Agent 自行申请 `PARTIAL_ON_BUDGET` 提前收工**（遇阻必须走五车道停滞复苏）；
   - 仅当越过最短投入时间且预算耗尽（`PARTIAL_ON_BUDGET`），或人类通过控制面 UI/CLI 显式紧急叫停并由宿主写入不可伪造的 **`project_closure_state.human_stop_requested_at`**（`PARTIAL_ON_HUMAN_STOP`，不受窗口阻拦；**服务端严禁轻信 Agent 自传 `human_aborted=true`**）时，方允许部分导出；
   - **严禁未审稿充数**：终局报告正文只允许组装已通过两阶段盲审的 `L3` 成果，并逐题如实列出精确剩余断点（Remaining Gaps）。
3. **五件套导出与绑定版本的两步终局状态（`DELIVERY_EXPORTED` $\to$ `CLOSED_VERIFIED`）**：
   - `library_surveyor` 调用 `export_stage3_final_delivery` 导出五件套（正式报告/复现套件/阻碍与否定清单/谱系路线/后续研究笔记）至 `<workspace>/final_delivery/`，生成唯一 `delivery_id` 与整包 `delivery_sha256`、重置 `verifier_final_audit_passed = 0`，数据库先置为 **`DELIVERY_EXPORTED`**；
   - 事件总线随即自动唤醒 **`library_verifier` + `supervisory_committee` 绑定该版本的联合终核**：`library_verifier` 在空白验证沙箱内经 `STAGE3_FINAL_AUDIT:<delivery_id>` 逐项核对总报告正文**未夸大任何 `L3` 的 `exact_verified_scope_md`** 且实跑复现套件一致后落签写入 `verifier_audited_delivery_id / sha256`；监察委写下 `CLOSURE_GATE(PASSED)` 时服务端硬校验终核绑定与最新导出版本完全匹配，方晋升 **`CLOSED_VERIFIED`**（若审过 A 又重导 B，A 的核签自动失效不可放行 B；人工紧急叫停允许直接带走当前已导出的部分五件套）。
