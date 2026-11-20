# 知识卡 03：中央图书馆“外藏 + 内藏”两翼建设与两阶段合流物理盲审深度规约（v2.1 五大冲突消解详版）

> **核心依据来源**：  
> - [`手写project.md`](../手写project.md)（中央图书馆作为服务一线科研人员的权威知识中心、委托代搜、成果论文文化与失败避坑案卷）  
> - [`07_V6Up第二轮测试全链路复盘与设计归因档案.md`](../第二轮测试分析/07_V6Up第二轮测试全链路复盘与设计归因档案.md) & [`08_审阅质询与架构重整报告_面向设计者与施工方.md`](../第二轮测试分析/08_审阅质询与架构重整报告_面向设计者与施工方.md)（根治 P20/P21/P22/P23/P26/P27）  
> - `Cogentic` [`§2.2–2.3, §2.5`](file:///D:/Documents/deepseek%20harness/论文研读/2609.40324_Cogentic_Multi-Agent_Orchestration_for_Automated_Proof_Discovery/2609.40324_Cogentic_中文综述.md#L167-L233)（`Individual + Cross-Draft Verifier`、`The Record + The Verified Ledger`、独立 `Auditor` 废墟打捞二次复验）  
> - `Station v2 (10 月新版开源仓)`：[`eval_archive_surveyor.py`](file:///D:/Documents/deepseek%20harness/论文研读/2610.08927_Can_AI_Agents_Make_Open-Ended_Scientific_Discovery_Evidence_from_Station/station-open-reseach/station/eval_archive_surveyor.py#L1-L450) & [`eval_archive/auto_evaluator.py`](file:///D:/Documents/deepseek%20harness/论文研读/2610.08927_Can_AI_Agents_Make_Open-Ended_Scientific_Discovery_Evidence_from_Station/station-open-reseach/station/eval_archive/auto_evaluator.py#L1-L300)  
> - `Station v2` [`Appendix D`](file:///D:/Documents/deepseek%20harness/论文研读/2610.08927_Can_AI_Agents_Make_Open-Ended_Scientific_Discovery_Evidence_from_Station/2610.08927_Station_OpenEndedDiscovery_中文翻译.md#L584-L603)（无标尺盲审固定 `Evidence Ledger` 6 步法则；英文解析 [`原文解析#L785-L857`](file:///D:/Documents/deepseek%20harness/论文研读/2610.08927_Can_AI_Agents_Make_Open-Ended_Scientific_Discovery_Evidence_from_Station/2610.08927_Station_OpenEndedDiscovery_原文解析.md#L785-L857)）  
> - `GPT-Rosalind (distributed_agent)` [`官方仓库解析#L46-L115`](file:///D:/Documents/deepseek%20harness/论文研读/Sun2026_Distributed_AI_Agents_Enable_Comprehensive_Discovery_of_Biological_Insights_at_Scale/Sun2026_GPT-Rosalind_DistributedAgents_官方仓库框架与工程架构深度解析.md#L46-L115)（六账本 Fail-Closed 外键检查、返回值物理隐藏先验摘要）  
> - `ResearchOS` [`2610.2216`](file:///D:/Documents/deepseek%20harness/论文研读/2610.2216_ResearchOS_Research_Compilation_for_Multi-Agent_Scientific_Discovery/2610.2216_ResearchOS_中文综述.md)（外藏三档阅读深度与证据权限粒度）

---

## 一、顶层重构：消解图书馆设计的五大底层冲突

在将旧版“三本账 (`L1/L2/L3`)”升级为**“各门派私有谱系 DAG（原 `L1`）+ 中央图书馆内外两翼”**的过程中，我们彻底厘清并消解了以下 **5 处底层逻辑冲突**：

```text
                       ╔══════════════════════════════════════════════════════╗
                       ║             真相 ③：中央图书馆 (Central Library)      ║
                       ╚══════════════╤════════════════════════╤══════════════╝
                                      │                        │
        ┌─────────────────────────────▼──────────┐  ┌──────────▼───────────────────────────────┐
        │ 左翼：【外藏】(`external_literature_cards`)│  │ 右翼：【内藏】(`internal_research_ledger`)│
        │ · 编号：[R###] 外部文献/教材定理/算子卡  │  │ · [L3-###] 黄金验证账本 (社区已证实成果) │
        │ · 性质：输入先验（带 read_depth 深度）  │  │ · [L2-###] 失败与反例雷达 (同事务自动入) │
        │ · 采编者：library_surveyor (可搜文献)   │  │ · 守门人：library_verifier (纯DB零磁盘)  │
        ├────────────────────────────────────────┤  ├──────────────────────────────────────────┤
        │ ★ 借阅时机（冲突一消解）：              │  │ ★ 借阅时机（冲突一消解）：                │
        │   从 0% 起全程向探索者开放两级 Pull！   │  │   0%–37% 物理暂锁（防开局抄兄弟门派作业）│
        │   探索者中途可调 request_literature_    │  │   37% 完成 2 轮短反思当场解锁两级 Pull！ │
        │   survey 委托馆员补充新 [R###] 卡片     │  │   伴随助手在出生看板中可嵌 1 句索引提示  │
        └────────────────────────────────────────┘  └────────────────────▲─────────────────────┘
                                                                         │
          ┌──────────────────────────────────────────────────────────────┴───────────────────┐
          │          内藏唯一准入通道：两阶段合流物理盲审状态机（冲突四 & 冲突五消解）        │
          │  • 待审单来源：① 后勤分诊 Level 1 突破手稿；② Auditor 剥离的自包含局部引理       │
          │  • Stage 1 (单篇盲态硬核验 Individual Blind Verifier)：                          │
          │      物理屏蔽作者/得分/B栏/遗嘱 -> 对照 7 类漏洞清单锁死不可逆 Evidence Ledger   │
          │        ├─ 若 Stage 1 REJECT ──> 【短路结案：同事务自动写入内藏 L2 失败雷达】      │
          │        └─ 若 Stage 1 PASS   ──> 进入 Stage 2                                     │
          │  • Stage 2 (解盲核对 B 栏 + Cross-Draft 横向比对 Verifier)：                     │
          │      单向降级锁（禁回改 Stage 1 账本）+ 横向排比同题他脉结论 + 提名跨脉交叉授粉  │
          │        ├─ 若 Stage 2 REJECT ──> 【同事务自动写入内藏 L2 失败雷达】               │
          │        └─ 若 Stage 2 PASS   ──> 【同事务剥离作者自动写入内藏 L3 黄金账本】       │
          └──────────────────────────────────────────────────────────────────────────────────┘
```

### 1.1 冲突一消解：外藏 `[R###]` 从 `0%` 全程开放 Pull vs 内藏 `L3/L2` 在 `0–37%` 暂锁、`37%` 解锁
- **为什么必须区分借阅时机？**
  - `The Station` 的“学徒隔离”与 `Diversity Collapse` 防盲从，防的是**新探索者一出生就去抄同期其他门派兄弟分支写出的内部解法（内藏 `L3 / L2`）**；
  - 但**左翼【外藏 `[R###]`】**是馆员在 Stage 1 搜集好的外部基础论文、经典物理公式与教科书定理算子卡（如阿伦尼乌斯方程、Fokker-Planck 首达时间定理）。如果 `0–37%` 连外藏基础文献都不让查，等于逼科研人员闭着眼睛凭记忆瞎编公式！
- **精确权限规则**：
  1. **左翼·外藏 `[R###]`**：**从探索者会话启动的 `0%` 起全程开放两级目录 Pull**！且探索者在研究中途若发现缺乏某特定方向的外部文献或解析算子，可随时调用 `request_literature_survey(question_id, topic_query, reason)` 委托馆员定向补查入库。
  2. **右翼·内藏 `L3 / L2`（及本脉历史 DAG 深层祖先页）**：在 **`0% ~ 37%` 物理暂锁**（迫使探索者先依据看板与基础文献独立思考、跑通至少 $\ge 1$ 次真实实验）；一旦在 `37%` 完成 2 轮短对话元反思（`first_reflection_unlocked = 1`），**当场向该探索者全面开放内藏 `L3 / L2` 与本脉谱系 DAG 的两级 Pull**！

### 1.2 冲突二消解：外藏表与内藏表【底层物理分表 + 上层共用两级目录视图】
- **为什么不能塞在同一张表里？** 外藏 `[R###]` 是**外部输入先验**（关心文献来源、`read_depth` 阅读深度、已知定理前提，没有沙箱 `[Obs###]`，也不走内部代码盲审）；内藏 `L3 / L2` 是**本社区自产实证**（审稿人 100% 审了全文与沙箱 `[Obs###]`，根本不存在 `abstract_only`，关心的是绑定的 `bound_obs_ids`、`hook_sha256`、`DEPENDS_ON` 与盲审账本）。
- **底层分两张 SQLite 表，上层共用同一套两级 Pull 接口**（详见第二节 §2.1 & §2.2）。

### 1.3 冲突三消解：探索者与一对一伴随助手在“查图书馆”上的清晰分工
- **出生前（伴随助手“织索引入看板”）**：伴随助手在增量合成 `~2000` 字《谱系状态看板 Briefing》时，可扫描内藏 `L2 / L3` 中与本子题直接相关的重大禁区或已证引理，在看板里写下 **1 句话高价值索引提示**（如 `"注：内藏 L2-003 已证实纯线性老化假设在低温高倍率下发散；L3-001 已证阿伦尼乌斯修正项收敛，37% 后可调阅详情"`）。
- **探索期（探索者自己掌舵两级 Pull，伴随/馆员负责重型代搜）**：
  - 探索者自己直接调用极轻量的 `query_library_catalog`（第一级看卡片，每张卡 $\le 350$ 字）和 `get_library_entry`（挑中 1–2 篇看全文），无需伴随助手传话中转；
  - 唯独当需要**跨多篇外部文献做广撒网 `3-Pass` 查新**时，才通过 `request_literature_survey` 唤醒专职馆员 `library_surveyor` 在独立无状态会话中检索蒸馏为干净的 `[R###]` 卡入库。

### 1.4 冲突四消解：将 `Cogentic` 双层审稿与 `Station` 两阶段盲审合流为单一两阶段状态机
- 彻底取消“既分单篇/跨篇、又分阶段一/阶段二”的四重迷宫，直接合流：
  - **`Stage 1` = 单篇盲态硬证据核验（`Individual Blind Verifier`）**，且 **`STAGE1_REJECT` 直接短路自动入 `L2` 结案**；
  - **`Stage 2` = 解盲机理核对 + 跨篇横向比对与交叉授粉提名（`Unblinded Mechanism & Cross-Draft Verifier`）**（详见第三节 §3.2 & §3.3）。

### 1.5 冲突五消解：图书馆内部“采编室 (`library_surveyor`) vs 审稿庭 (`library_verifier`)”Preset 物理分离，打捞引理直入标准盲审队列
- 为防止盲审官利用馆员的文件/搜索工具偷看工作区明文（P21），并杜绝 `Auditor` 自审自入库（P22），中央图书馆在 DSH Preset 层拆为两个工具面物理正交的子角色入口：
  1. **`library_surveyor`（外藏采编馆员 Preset）**：挂载外部检索 / PDF 阅读工具 + `publish_external_literature_card`；**无任何审稿或写内藏 `L3` 权限**。
  2. **`library_verifier`（内藏盲审与打捞审计官 Preset）**：**零通用磁盘 `read` 工具、零外网工具**！仅挂载纯 SQLite MCP 盲审与打捞工具；且当其执行 `Auditor` 打捞调用 `propose_salvaged_lemma` 时，**直接生成一张标准 `STAGE1_BLIND` 待审单（记录 `proposer_session_id`）投入盲审队列，由另一名独立唤醒的 `library_verifier` 会话（强校验 `session_id != proposer_session_id`）按标准两阶段盲审复验入 `L3`**！

---

## 二、外藏与内藏底层物理分表 Schema 及【两级按需 Pull 目录视图】

### 2.1 两翼物理分表结构与写入触发器

| 物理表名与馆藏翼 | 编号与可见性 | 唯一写入触发器（数据库事务保障） | 核心必填字段（SQLite WAL） |
| :--- | :--- | :--- | :--- |
| **表 1：`external_literature_cards`**<br>**左翼：【外藏 `[R###]`】**<br>*外部资料与基础算子库* | `ref_id` (`R001`, `R002`...)<br>**从 `0%` 起全程对全员开放两级 Pull** | ① `Stage 1` 由 `library_surveyor` 执行 `3-Pass + Anchor-and-Refine` 查新后调用 `publish_external_literature_card` 入库；<br>② `Stage 2` 响应探索者 `request_literature_survey` 委托查新入库；<br>③ **离线/受限环境兜底铁律（根治 P23）**：若外网不可达或仅能抓到残缺摘要，馆员必须结合经典数学物理教材构建**带精确公式、量纲与前置假设的《标准定理/解析算子卡片》**入库，严禁塞入无公式的空洞摘要！ | • `ref_id` (`PRIMARY KEY`)<br>• `question_id` (`Q1..Qn` 或 `GLOBAL`)<br>• `title`<br>• **`abstract_md`**（独立撰写 100–300 字高密度摘要，**严禁 `[:120]` 截断**）<br>• `exact_preconditions_md`（定理/公式成立的精确前置条件）<br>• `formulas_or_operators_md`（核心数学表达式/算子定义）<br>• `read_depth`（`full_text` / `specified_sections` / `abstract_only`）<br>• `support_scope`（5 级支持粒度；`abstract_only` 严禁充当硬因果证明）<br>• `source_citation` |
| **表 2：`internal_research_ledger`**<br>**右翼：【内藏 `L3` 黄金账本】**<br>*`The Verified Ledger`* | `entry_id` (`L3-001`...)<br>**`0–37%` 暂锁；过 `37%` 短反思后全员开放两级 Pull 并免重证引用；子题结题唯一法定凭证** | **唯一入口**：仅当待审手稿（来自后勤 `Level 1` 送审或 `Auditor` 打捞送审）在 **`Stage 2` 解盲终审被裁决为 `PASS`（含 `PASS_WITH_NARROWED_SCOPE`）时，由 `submit_stage2_unblind_verdict` 在同一 SQLite 事务内自动剥离作者与历史得分写入本表**！ | • `entry_id` (`L3-###`)<br>• `question_id` (`Q1..Qn`)<br>• `ledger_type = 'L3_VERIFIED'`<br>• `source_type` (`LEVEL1_MANUSCRIPT` / `AUDITOR_SALVAGED_LEMMA`)<br>• `title` & **独立撰写的 `abstract_md`**<br>• `exact_verified_scope_md`（经审稿人核准的成立前提与精确适用边界）<br>• `body_proof_or_code_md`（核心证明推导、解析方程或关键算法摘要）<br>• `bound_obs_ids`（JSON 数组，Fail-Closed 强校验存在于 `observations` 表）<br>• `depends_on_ids`（依赖的上游 `R### / L3-### / Obs###`）<br>• `domain_hook_sha256` & `eval_epoch_version`<br>• `review_id`（关联锁定的 `Evidence Ledger`，**物理不含作者 branch_id 与排名分**） |
| **表 2（同表分型）：`internal_research_ledger`**<br>**右翼：【内藏 `L2` 失败雷达】**<br>*`The Record` 反例与死胡同案卷* | `entry_id` (`L2-001`...)<br>**`0–37%` 暂锁；过 `37%` 短反思后全员开放两级 Pull 防跨门派重踩坑** | **三大全自动事务触发器（根治 P20 `L2=0` 漏洞）**：<br>① **Stage 1 盲审裁决 `REJECT`** 时，同事务自动短路入库 `L2`；<br>② **Stage 2 解盲终审裁决 `REJECT`** 时，同事务自动入库 `L2`；<br>③ **后勤 `triage_node` 判定 `Level 2` 原地修补满 3 次超限或确认 `Level 4a` 《结构阻碍证明》**时，同事务自动入库 `L2`！ | • `entry_id` (`L2-###`)<br>• `question_id` & `method_family_id`<br>• `ledger_type = 'L2_FAILURE_RECORD'`<br>• `source_type` (`STAGE1_BLIND_REJECT` / `STAGE2_UNBLIND_REJECT` / `L2_REPAIR_EXHAUSTED` / `L4A_BARRIER_PROOF`)<br>• `title` & **独立撰写的 `abstract_md`**<br>• `exact_refuted_scope_md`（被证伪或卡死的具体条件区间与失败机理）<br>• `body_proof_or_code_md`（反例证据、阻碍证明或报错根因）<br>• `bound_obs_ids` & `domain_hook_sha256` |

### 2.2 视图 ②：统一两级按需 Pull 目录接口（`query_library_catalog` $\to$ `get_library_entry`）

1. **第一级：查目录卡抽屉 `query_library_catalog(node_id, question_id, scope="ALL" | "EXTERNAL_R" | "INTERNAL_L3" | "INTERNAL_L2", keyword="")`**：
   - **服务端权限自动裁剪**：服务端先检查调用方 `node_id` 的 `first_reflection_unlocked` 状态：
     - 若 `first_reflection_unlocked == 0`（处于 `0% ~ 37%` 首轮独思期）：自动只查询并返回 `external_literature_cards`（**外藏 `[R###]`**），并在 `next_step_guidance` 温和提示：`"当前处于 0-37% 净室独思期，已为你返回外藏 [R###] 基础文献/算子卡；内藏 L3/L2 将在你完成首轮实测与 37% 简短元反思后当场解锁。"`
     - 若 `first_reflection_unlocked == 1`（处于 `37% ~ 70%` 开放攻坚期）或调用方为伴随助手/后勤/图书馆：完整返回外藏 `[R###]` + 内藏 `L3` + 内藏 `L2` 的匹配目录卡！
   - **目录卡高信噪比格式（每张卡 $\le 350$ 字，绝不塞爆上下文）**：
     ```text
     [ID: R002 | 翼: 外藏基础算子 | 子题: Q1/Q3 | 阅读深度: full_text | 支持度: DIRECT_PROOF_OR_EXACT_MEASUREMENT]
     标题: 锂离子电池低温阿伦尼乌斯内阻激增与极化电压压降方程
     摘要 (abstract_md): ...（真实独立摘要，严禁 [:120] 截断）
     精确前提/边界: 适用于 T ∈ [-20°C, 45°C] 连续与脉冲放电，活化能参数 E_a 需按倍率标定。
     ```
2. **第二级：按 ID 调阅全文详情 `get_library_entry(node_id, entry_id)`**：
   - 探索者从目录卡中选定真正需要的 1–2 张卡片（如 `R002` 或 `L3-001`）后，调用 `get_library_entry` 拉取完整的公式推导、定理证明、代码片段与关联的 `[Obs###]` 详情（同时由宿主中间件自动在 `FACT_LOG` 记下一条真实的 `READ` 暴露边，供监察委与声明引用对账！）。

---

## 三、两阶段合流物理盲审状态机（`Stage 1` 单篇盲态锁账本 $\to$ `Stage 2` 解盲核机理 & 跨篇横审）

### 3.1 物理防泄密铁律：待审稿只存 SQLite `review_queue` 表，且 `library_verifier` 零磁盘读取工具（根治 P21）
- 谱系 DAG 的节点交接手记与所有待审手稿**100% 存储在 SQLite 数据库（`lineage_nodes` 与 `review_queue` 表）**，**工作区磁盘任何目录下严禁生成 `HANDOFF.md` 或手稿 `.md` 文件**；
- `library_verifier` 角色在 DSH Preset 中**物理剥离通用磁盘 `read / glob / grep / bash` 工具**，只能调用下方 4 个 MCP 盲审专用窄工具，从物理架构上做到 100% 不可绕过！

### 3.2 第一阶段（`STAGE1_BLIND` = 单篇盲态硬证据核验 `Individual Blind Verifier`）
1. **拉取盲态裸材料与数据库内嵌脱敏代码 Diff `get_blind_manuscript(review_id)`**：
   - 当 `review_status == 'STAGE1_BLIND'` 时，SQL `SELECT` 语句**物理不查询、不返回**：手记 B 栏机理解释与猜想、作者《科研遗嘱》、祖先推导叙事、作者 `node_id / branch_id / lineage_id / proposer_session_id` 以及历史得分；
   - **零磁盘权限下的代码 Diff 载体**：当伴随助手调用 `submit_node_handoff` 入库时，后端自动从该节点 Worktree 提取脱敏后的核心代码 Diff（剥离作者分支路径头与个人注释）存入 SQLite `lineage_nodes.sanitized_code_diff_md` 字段；
   - **`get_blind_manuscript` 仅从 DB 返回四项客观硬材料**：① 子题规格与验证契约（`question_id` 对应的契约检查项与验证钩子定义）；② 待审稿 **A 栏（实测事实与严格数学推导正文）** + **数据库脱敏代码核心 Diff (`sanitized_code_diff_md`)**；③ 隔离评估容器出具的原始 `[Obs###]` 收据与验证钩子分项指标；④ 声明引用的外键 `[R###]` / `[L3-###]` 原始条目。
2. **对照 `OpenAI CDC` 7 类漏洞清单提交锁定账本 `submit_stage1_blind_ledger`**：
   - 审稿人逐条对照子题契约检查项与 7 类结构漏洞（偷加隐式假设、极限/边界崩溃、局部冒充全局、伪等价引理、循环论证、代理指标伪优、混杂变量充因果），提交结构化 **`evidence_ledger` JSON**（每条必含原始 `[Obs###]` 或推导行精确引文，缺证必填 `"No direct evidence found"`）；
   - 数据库写入 `stage1_ledger_json` 并打上不可逆时间戳 **`stage1_locked_at = CURRENT_TIMESTAMP`**（数据库写接口永久拦截任何对已锁 `stage1_ledger_json` 的修改）；
   - **短路分流（Short-Circuit on Stage 1 Reject）**：
     - 若 `stage1_verdict == 'REJECT'`：无需再走 Stage 2！数据库**在同一事务内直接将该手稿的 `reject_failure_reason` 与 `exact_refuted_scope_md` 自动写入 `internal_research_ledger`（生成内藏 `[L2-###]` 失败雷达记录）**，并将审稿单置为 `CLOSED_REJECTED_TO_L2`；
     - 若 `stage1_verdict == 'PASS'`（满足“语义等价匹配 + 主张专属直接实证 + 无逻辑/守恒律矛盾”三条件）：审稿单状态跃迁为 `STAGE2_UNBLIND`。

### 3.3 第二阶段（`STAGE2_UNBLIND` = 解盲机理对质 + 跨篇横向比对 `Cross-Draft Verifier`）
1. **拉取解盲 B 栏与同题横向快照 `get_unblinded_manuscript_and_peers(review_id)`**：
   - 仅当 `stage1_locked_at IS NOT NULL` 时可调用；
   - **一并返回两部分材料**：
     ① **本篇解盲材料**：作者的 B 栏机理阐释、适用边界声明与 `FACT_LOG` 客观阅读对账结果（直接高亮标注作者声明引用的 `[R###]/[L3-###]` 是否真的在 `FACT_LOG` 中有 `READ` 记录）；
     ② **同子题跨篇横向比对快照（`Cross-Draft` 视野）**：当前同一 `question_id` 下其他门派已入库的 `L3` 摘要及近期在审手稿的核心结论对比表。
2. **提交终审裁决与跨脉授粉提名 `submit_stage2_unblind_verdict(review_id, final_verdict, title, abstract_md, exact_verified_scope_md, exact_refuted_scope_md, cross_draft_comparison_notes, cross_pollinate_nomination)`**：
   - **核对本篇机理（单向降级锁）**：对比 Stage 1 冷酷证据账本 vs 作者 B 栏叙事。若发现作者把单次种子/局部网格结论吹成全局定理、存在未读假引或辅助项掩盖主目标退化，审稿人只能维持 `PASS`、缩窄适用范围 `PASS_WITH_NARROWED_SCOPE` 或下调为 `REJECT`（**数据库层物理禁止把 Stage 1 `REJECT` 翻案为 `PASS`，也禁止回改 Stage 1 `Evidence Ledger`**）；
   - **跨篇横向比对与延迟交叉授粉星探（`Cross-Draft Verifier`）**：排比不同门派结论是否存在共性未证假设盲区；若发现“本脉已证实的局部原语恰好能补上另一门派分支 `branch_Y` 的核心瓶颈”，在参数 `cross_pollinate_nomination`（`{"target_branch_id": str, "rationale": str}`）中填写嫁接提名，供后勤调度总管触发 `fork_branch(mode="cross_pollinate")`；
   - **同事务自动入库内藏 `L3` 或 `L2`**：
     - 若 `final_verdict` 为 `PASS` 或 `PASS_WITH_NARROWED_SCOPE`：数据库在**同一事务内**自动剥离作者分支与得分，以 `exact_verified_scope_md` 生成正式 **`[L3-###]`** 写入 `internal_research_ledger`（内藏黄金验证账本）；
     - 若 `final_verdict == 'REJECT'`：数据库在**同一事务内**自动提取被驳回的夸大主张与 `exact_refuted_scope_md`，生成正式 **`[L2-###]`** 写入 `internal_research_ledger`（内藏失败与反例雷达）！

---

## 四、`Auditor` 废墟引理打捞（直入标准盲审通道）、细粒度 `DEPENDS_ON` 与【结题硬锁】

### 4.1 `Auditor` 废墟引理打捞：直入 Stage 1 盲审队列，强制异会话复验（根治 P22）
- **打捞触发时机**：当某节点因 `Level 4b` 条件阻塞退场、或手稿在盲审中被判 `REJECT` 时，虽然其主结论未达标，但其中可能包含有价值的**局部中间引理（Intermediate Lemma）、解析变换技巧或精确反例包络**。
- **两步同构闭环（零旁路后门）**：
  1. **打捞会话（会话 A）调用 `propose_salvaged_lemma`**：将有效局部引理**彻底剥离原失败上下文**，改写为自包含命题（独立标题 + 独立 `abstract_md` + 明确前置假设与适用边界 A 栏 + 绑定的独立 `[Obs###]`）；数据库**直接将其作为一张 `source_type = 'AUDITOR_SALVAGED_LEMMA'`、`review_status = 'STAGE1_BLIND'` 的新审稿单插入 `review_queue` 表**，并记录 `proposer_session_id = Session_A`；
  2. **独立盲审会话（会话 B）执行标准 Stage 1/2 盲审**：事件总线拉起另一名全新的 `library_verifier` 会话 B，在调用 `submit_stage1_blind_ledger` 与 `submit_stage2_unblind_verdict` 时，**服务端代码硬性校验 `current_session_id != proposer_session_id` 且不为原探索者会话**（若相同直接报错 `SELF_REVIEW_FORBIDDEN`）！只有通过会话 B 的标准盲审，该引理才会由 Stage 2 事务自动写入内藏 `L3`！

### 4.2 废除全局 `state_version` 连坐，实行沿 `DEPENDS_ON` 细粒度作废与同事务重评入队（根治 P26）
1. **彻底废除“全局单一整数 `state_version` 递增即全军 `Obs` 作废”的粗暴机制**！
2. 每条观测 `[Obs###]` 与每条内藏 `[L3-###]` 在入库时，显式记录其**真实依赖边 `DEPENDS_ON`**：具体绑定哪一个子题验证钩子指纹 `(question_id, domain_hook_sha256)` 以及哪些上游 `[R###] / [L3-###] / [Obs###]`。
3. **跨题零误杀 + 同题同事务自动入队重评**：
   - 当工造司仅更新了 **Q4** 的验证钩子 `hook_Q4.py` 时，**Q1、Q2、Q3 的所有 `VALID` 观测与已入库的 `[L3-###]` 100% 保持有效，丝毫不受影响**！
   - 对于绑定了旧 `hook_Q4.py` 的历史观测，数据库在**同一个 SQLite 事务内**将其状态置为 `PENDING_REVALIDATION` 并**自动插入 `pending_revalidation_queue` 表**，由工造司调用 `recompute_stage_b_only` 读取持久化的 `stage_a_output.json` 秒级重算恢复，彻底杜绝“只打 `INVALIDATED` 标签却不进重评队列导致全军清零”的死锁灾难！
4. **上游引理被证伪时的三分类传播**：
   - `REQUIRED_PREMISE`（承重必要前提）$\to$ 下游 `L3` 条目标为 `retracted_premise_invalid` 移出有效集并唤醒后勤；
   - `INDEPENDENT_SUPPORT`（多条独立实证之一）$\to$ 仅切断该失效边并标为 `recheck_triggered` 送盲审凭剩余独立证据重定级，绝不一刀切连坐；
   - `MOTIVATING_REF`（背景启发参考）$\to$ 不影响下游已由自身独立实证撑住的结论；
   - 同步扫描 `Level 4b` 阻塞分支的 `reopen_condition`，凡因“假优基准被撤回”而解封的分支立即推入 `Ready Queue`。

### 4.3 子题与全卷【结题硬锁】（根治 P9/P27 `0 L3` 空转结题）
- 任何子题 `Q_i` 想要标记为完成，或系统想要从 `Stage 2` 进入 `Stage 3`（终稿论文合成），服务端函数 `check_stage2_closure_gate()` 强制执行 SQL 核验：
  ```sql
  SELECT question_id, COUNT(*) AS l3_verified_count
  FROM internal_research_ledger
  WHERE ledger_type = 'L3_VERIFIED'
  GROUP BY question_id;
  ```
- **凡有任何必答子题的 `l3_verified_count == 0`（没有哪怕 1 条通过 Stage 2 解盲终审入库的 `L3` 黄金结论）**，服务端直接硬拦截返回 `GATE_BLOCKED_ZERO_L3`，并列出缺失 `L3` 的子题与当前 `review_queue` / `pending_revalidation_queue` 待办项，**物理禁止任何角色靠写总结文档宣布结题**！
