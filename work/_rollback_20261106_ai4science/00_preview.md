# V4 Teamwork Preview：六章立场与 Lead 裁决

> 日期：2026-11-06｜阶段：P0 Recon + P1 Preview 完成｜下一步：等你确认方向后进 P2–P5
> 输入：六份 `00_*_recon_preview.md` + `00_shared_frame.md` + 00–07 设计文档。
> 性质：架构设计；不写代码、不跑实验。

## 0. 本轮结论

六章方向基本成立，但 preview 暴露了 **4 个必须裁决的冲突 + 17 个对象缺口**。不裁决就进 P2，六章会各写各的。下面先给 V4 骨架，再给裁决，再给 P2–P5 计划。

## 1. V4 骨架（preview 版）

    使命层：TaskContract / Acceptance / DeliveryEnvelope / DomainProfile
      ↓
    Idea Loop（问题/假设/锦标赛/提案）
      ↓
    Empirical Loop（实验设计/执行/观察/证据）
      └─ Theory Phase（解释/预测/理论）——不是第五个循环，是 Empirical 的后半段
      ↓
    Trust Loop（个体/跨稿验证/复验/入库/更正）
      ↓
    Meta Loop（元反思/品味/流程/红队）→ 回到 Idea/Empirical

    三器官：Orchestrator（语义）/ Scheduler（路由）/ Judge（制度）
    两记忆：Public（Record/Ledger/Archive/Lineage 公共部分）/ Private（Lineage 私笔记）
    一免疫：Reflection / RedTeam / Maintainer / Auditor
    一底座：EventLog / Budget / Worktree / DecisionEpoch / Verdict
    横切：Human Interface（Actor/Approval/HumanAttentionBudget）

三条时间尺度：短周期（动作/决策代）→ 中周期（N 决策代，元反思）→ 长周期（换代/交接/隔离）。

## 2. 六章一句话立场

| 章 | 核心主张 | 关键证据 | 最大风险 |
|---|---|---|---|
| 01 科学本体 | 14 对象不够；补 Prediction/Assumption/EvaluationSpec；BeliefState 是从事件日志可重算的版本化投影，公共信念+私有 overlay | Station 28 findings：9 计分/7 要求未计分/12 皆非 [B]；V3 完成信号效应 [K] | BeliefGraph 变成没人读的文档 |
| 02 发现循环 | Idea/Empirical/Theory 是同一 Hypothesis 状态机上的相位，相位间只传对象；每个提案带最便宜测试/预期信号/kill 条件/delta_type | Co-Scientist 新颖性 6.14→2.38、Evolution 只增不改 [A]；MLE-STAR 25.8%→43.9% [A] | 状态跃迁作弊（ranked 直接写 supported） |
| 03 知识制度 | 档案是引用图不是文件柜；准入是门禁不是评分；信用=被用不是发表；引用即承诺，更正反向传播 | 21/28 findings 用到早期论文；Archive 整屋消融 0/3 vs 3/3；ARI 单评审漏全部硬伤 [B] | 制度成本反噬、评审变 attractor |
| 04 控制运行时 | 五个原语：EventLog/Budget/Worktree/DecisionEpoch/Verdict；总控做语义、调度做路由、内核做记账；异步执行+决策代，取消代际硬栅栏 | TIPEX 异步/截断 [A]；Anthropic 同步瓶颈 [D]；并发控制 [C] | 把测量装置制度化成事实；调度 scope creep |
| 05 元层评估 | 元层把过程证据编译成 PivotPolicy/TastePolicy；评估是预注册 rubric + 校准 judge + 红队 + frozen/live 双集 | Station 元反思 11 提示词+写回、联合消融 75.8→57.9 [A/B]；Diversity Vendi 8.08 vs 4.65 [A] | 反思变 attractor；提示词池隐性价值注入 |
| 06 人机领域 | 人是 Actor 不是审批弹窗；自主性=可逆性×成本×风险；DomainProfile 编码领域差异；AccountabilityRecord 落实责任 | Co-Scientist 三验证均 expert-in-the-loop；Station 75% 非重叠提案被评 1–2/5；ARI 25h/篇 [B] | 签字橡皮章+责任洗白；过度 gate 杀死自主性 |

## 3. Lead 裁决（P2 必须遵守）

### R1 Theory 的位置
**裁决：Theory 不是第五个循环，是 Empirical 的后半段（Theory Phase）。** V4 保持四循环；Theory Phase 的接口是 Evidence → Explanation → Prediction → Theory，出口经 Trust 评审。理由：shared_frame 的四循环已冻结；Theory 需要 Evidence 才能发生，独立成环会造出第二个 Experimental 入口。

### R2 新增科学对象
**裁决：采纳 Prediction、Assumption、EvaluationSpec。** Prediction 必须预注册（条件、预期信号、evaluator_ref）；Assumption 必须有范围与 invalidates；EvaluationSpec 必须有版本、oracle_type、阈值、已知失败模式、校准引用。L2 类型补 explanation/obstruction/bound。

### R3 Evidence 双标度
**裁决：拆 `provenance_grade`（A–E，来源可信度）与 `support_strength`（weak/moderate/strong，方向强度）。** 不再用一套三档混算。任何 L2+ 卡必须带 `evaluator_ref`、`scope`；无条件字段不算 L2。

### R4 BeliefState
**裁决：BeliefState 是从事件日志可重算的版本化投影，不是手工维护的表。** 节点 Claim/Theory，边 supports/refutes/undercuts/subsumes/replaces，带 conflicts 与 computed_from。公共信念 + 私有 overlay 双轨；撤销 append-only，优先缩范围。新增指标：belief_delta 改变下一动作的比例。

### R5 评审分层
**裁决：L1 不审、L2 复验、L3 评审+复审。** 确定性检查先行；单评审阈值不够；多评委 + 校准集 + 盲序 + 理由；ARI 的单 LLM 评审教训写入制度层。Review 补校准字段与评审者身份。

### R6 信用与引用
**裁决：信用 = 被使用（CreditEdge），不是发表数量；引用即承诺。** 下游引用必须记版本与证据等级；Correction 反向传播到受影响引用；自引打折/环检测；KPI 只认被使用。新增 Lineage、AdmissionDecision、Reproduction、Correction、CreditEdge。

### R7 控制原语
**裁决：EventLog、Budget、Worktree、DecisionEpoch、Verdict 升级为一级对象。** 总控做语义、调度做路由、内核做记账；异步执行 + 决策代；取消代际硬栅栏；预算为硬上限；版本钉住 + 幂等 + 恢复协议。

### R8 评判制度
**裁决：三货币（有效性/质量/探索信用）+ frozen/live 双集 + Judge/RedTeam/Maintainer/Auditor 四角色。** 探索信用只发预算、不发分数；frozen 永不改；live 可增；Maintainer 不能改 frozen；Auditor 独立。

### R9 元层对象
**裁决：ReflectionRecord、PivotPolicy、TastePolicy 补字段；新增 EvaluationProtocol、RedTeamCase。** 反思必须写回（无写回拒收）；TastePolicy 只进私有记忆与交接卡，不进质量分/探索信用；反思者/评委跨模型族。H3 以 2×2 拆分承诺×反思。

### R10 人机协作对象
**裁决：新增 Actor、Approval、DomainProfile、AccountabilityRecord、HumanAttentionBudget；TaskContract 扩展。** 四类动作必须人批：不可逆、高成本、对外发布、高风险；其余在预算信封内预授权。人类注意力显式计价；责任链不可外包；系统不得自主对外发布。

### R11 排名对象
**裁决：新增 RankingState（挂 BeliefState 或独立），承载 Elo/配对/轮次/评委分歧。** Co-Scientist 初值 1200 与多轮辩论有出处；Elo 只作调度信号，不作科学价值。

### R12 失败链
**裁决：不新增 Failure 对象；失败 = Record 条目（尝试/方法/被驳理由/条件）+ reopen_trigger。** Experiment.failed → Record → route dormant/blocked → 只有新机制/新条件才解封。

## 4. 对象字典 v1.1（P2 冻结）

| 组 | 对象 |
|---|---|
| 科学对象 | Question、Hypothesis、Experiment、Observation、Evidence、Claim、Explanation、Theory、Method、Artifact、Paper、Review、Program、BeliefState、Prediction、Assumption、EvaluationSpec、RankingState |
| 制度对象 | Record、LedgerEntry、ArchivePaper、Lineage、AdmissionDecision、Reproduction、Correction、CreditEdge、HandoffCard |
| 控制对象 | OrchestratorDecision、NodeBrief、SchedulerPlan、JudgeVerdict、ExplorationCredit |
| 运行时对象 | EventLog、Budget、Worktree、DecisionEpoch、Action、StateSnapshot |
| 治理对象 | Actor、Approval、DomainProfile、AccountabilityRecord、HumanAttentionBudget、TaskContract |
| 元层对象 | ReflectionRecord、PivotPolicy、TastePolicy、EvaluationProtocol、RedTeamCase、ProcessChange |

命名规则：对象英文单数首字母大写；字段 snake_case；状态小写 snake_case；不允许 P2 擅自改名；新增对象先报 Lead。

## 5. P2–P5 详细计划

### P2 分章草稿（每章 3–5k 字）
| 章 | 负责人 | 文件 | 必含 |
|---|---|---|---|
| 01 | science-ontology | `01_科学本体与信念状态.md` | 对象字段、BeliefGraph 更新/撤销、公共/私有 overlay、到 L2/Ledger/Archive 的映射 |
| 02 | discovery-loops | `02_发现循环.md` | 三相位状态机、对象接口、触发/回退、锦标赛、Theory Phase、失败链 |
| 03 | knowledge-institution | `03_知识制度.md` | 三层准入、评审分层、复现/更正/撤稿、Lineage/代际、CreditEdge |
| 04 | control-runtime | `04_控制与运行时.md` | 五原语、总控/调度/内核、决策代、worktree 生长、恢复/预算/版本 |
| 05 | meta-taste-eval | `05_元层与评估.md` | 反思两模式/写回、TastePolicy、EvaluationProtocol、红队、H1/H2/H3 |
| 06 | human-domain | `06_人机协作与领域适配.md` | Actor/Approval/DomainProfile、四类人批、验证经济学分型、安全治理 |

固定模板：问题 → 需求 → 对象/数据契约 → 组件/角色 → 流程 → 接口 → 失败模式 → 开放问题 → 证据映射（A–E）。

### P3 交叉评审（每人审两章）
检查表：对象名/状态名冲突；接口 producer/consumer 缺失；职责重叠；失败模式遗漏；无证据断言；与 R1–R12 冲突；与 00–07 重复。Lead 汇总成分歧表。

### P4 综合
Lead 写 `08_AI4Science_超长架构设计.md`（十章，20–30k 字）；control-runtime 协助 `09_AI4Science_架构实施计划.md`（模块/接口/阶段/里程碑/测试/风险，不含实验执行）。

### P5 终审
`10_Teamwork_设计评审记录.md` + README 索引 + 未决问题清单 + 全员签收。

### 验收标准
1. 十章齐全，每章按模板；2. 对象字典 v1.1 全章一致；3. 每条设计决策标 A–E 与来源；4. 明确 V4 与 V1/V2/V3 的继承/拒绝；5. 09 含模块边界/里程碑/测试/验收，不含实验；6. 评审记录含分歧与未决问题；7. 不写代码、不跑实验、不改 00–07。

## 6. 需要你确认的 5 件事

1. **Theory 的位置**：按 R1 作为 Empirical 的后半段，还是坚持独立成第五循环？
2. **新增对象规模**：R2/R4/R6/R9/R10/R11 共新增约 17 个对象；接受，还是先砍到最小集？
3. **人机门槛**：R10 的四类人批 + 人类注意力预算，是否符合你的实际使用方式？
4. **V4 边界**：V4 先做「可验证竞赛任务 + 人机协作」的 v4.0，开放式 AI4Science 放 v4.1，是否同意？
5. **是否现在开 P2**：以上裁决若认可，我按 P2–P5 展开六章并综合 08/09/10；若要改哪条，现在改成本最低。

## 7. 文件索引

- `00_shared_frame.md`：共享框架 v1（对象字典 v1.0）；
- `00_science-ontology_recon_preview.md`、`00_discovery-loops_recon_preview.md`、`00_knowledge-institution_recon_preview.md`、`00_control-runtime_recon_preview.md`、`00_meta-taste-eval_recon_preview.md`、`00_human-domain_recon_preview.md`：六份 preview；
- 本文件 `00_preview.md`：preview 汇总 + Lead 裁决 + P2–P5 计划。