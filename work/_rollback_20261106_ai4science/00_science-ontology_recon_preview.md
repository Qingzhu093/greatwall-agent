# 00 科学本体与信念状态：Recon + Preview（P0/P1）

- 作者：science-ontology（DeepSeek Harness 团队，task-6）｜日期：2026-11-06
- 读了：00 团队规范、00、02–07 各设计文档、ai4science/00_shared_frame、work/01（全文）；Station 数学版全部 .tex（dualverse、station_appendix、meta_analysis、selected_findings、additional_analysis，全文）；Cogentic main.tex（全文）；Co-Scientist PDF pp.1–40（主体；补充注部分略读）。
- 口径：2608.23691 附录自称「Station v2 环境」、05 按论文序号称「Station v1」；本文按「Station 数学版」引用，不混用。

## A. 约束备忘

**必须支持**
1. **多类型发现**：Station 28 个 selected findings 分四类（construction / explanation / obstruction / bounds），仅 9 个被 evaluator 计分、7 个任务要求但未计分、12 个两者皆非 [B]（meta-analysis §4.1；selected_findings 表）。只表达可计分构造，会丢掉 19/28 的产出。
2. **证据相对于装置**：V3 屏蔽官方不提供的 is_all_cleared 后，node_06 的 L1 从 173.94 升到 333.05 s/源 [K]（work/01 §3 第10条）。每条 Evidence/Claim 必须绑 evaluator 版本与条件。
3. **公共记忆须评审准入**：无 Archive 的 Station 中，某 Agent 宣称「一大类构造不可能超过 582 点」，他人采纳 [B]（meta-analysis §4.2）；有评审时 125 篇论文、923 条引用、199 次拒稿、55/125 至少被拒一次，1–10 分、≥6 接收 [B]（station_appendix A.3.2）。
4. **失败与障碍留痕**：Cogentic 的 Record 存「尝试+方法+被哪条反对驳回」，Ledger 记「被已证伪反例排除的界」[C]（§2.3）；Co-Scientist 的 Evolution 只生成新假设、不修改旧假设，新假设须重新参赛 [B-]（p.35）。
5. **解释可检验**：Station 的 604 点 kissing 给出显式代数构造，sign uncertainty 先证 evaluator 家族局限再跳出该族 [B]（dualverse §Introduction）；Co-Scientist 会把假设拆成子假设、判断错误是否根本 [C]（p.33）。

**现有设计缺什么**
- 05/06 的成果卡类型（lemma/component/experiment/counterexample/literature/conjecture，06 §3；05 §P2）缺 explanation、obstruction、bound，与 Station 的分类不匹配 [B]。
- 没有 BeliefState 的可计算 schema：05 只在 P7 说「证据等级与状态」，矛盾如何表达/消解/版本化未定义 [E]。
- 缺 Prediction、Assumption 对象（06 §9 的 ASSUMPTION 仅在任务契约层）[E]。
- 缺 Evaluator 规格对象：Evidence 无处指向「哪一版装置」[K/E]。

**3 条最关键约束**
- C1 任何 L2+ 卡必须带 `evaluator_ref`、`scope`；无条件字段不算 L2（沿用 06 §3 并加引用）[E]。
- C2 分数、解释、障碍、界分开验收，不折算单一分数（否则优化活动量；05 P0/P9）[B/E]。
- C3 信念更新是 append-only 事件 + 可重算投影；撤销 = 新版本 + 反证/障碍卡 + 降级边，不物理删除（只增不改 [B-/C]）。

**3 个待定问题**
- Q1 更新粒度：每动作增量更新，还是每决策代批处理？文献无此消融 [E]。
- Q2 公共/私有偏差：Station 私笔记不评审、Co-Scientist 未验证假设可参赛；允许多大偏差而不污染公共信念？无直接证据 [E]。
- Q3 解释的准入：Station 靠外部专家筛 + Lean 验证定理，无「解释质量」度量；Co-Scientist 有 novelty/feasibility rubric 但无解释专项 [C][E]。

## B. 设计立场

**核心主张**：14 对象覆盖主干，但「最小集合」不完整：补 Prediction、Assumption、EvaluationSpec，并把 BeliefState 定义为**从事件日志可重算的版本化投影**，不是手工维护的表。解释与预测的区分不靠措辞：Claim 可判定，Explanation 是机制假说，Prediction 是解释对未观测条件的预先承诺；解释须挂 ≥1 条预注册预测才 draft→reviewed；Theory = 范围内 claim + 解释 + 预测承诺；推翻优先缩范围，最后整条撤销。更新规则：Record/Evidence(draft) 不触发信念更新，Ledger 级复验通过才允许；撤销 = contradiction 边+降级→Obstruction 卡；每次更新写 belief_delta 与理由。

**对象/接口草案**（名从 shared_frame，只加字段/新对象）
- `Prediction{id, owner(Claim|Theory), condition_set, pre_registered_at, expected_signal, evaluator_ref, outcome, verdict: confirmed|refuted|inconclusive}`
- `Assumption{id, statement, scope, evidence_refs, status, invalidates[]}`；Claim/Hypothesis/Theory 持 assumption_refs。
- `EvaluationSpec{id, version, oracle_type: deterministic|formal|human_rubric|llm_rubric, metric, threshold, known_failure_modes, calibration_ref}`
- `BeliefGraph{version, nodes(Claim|Theory), edges: supports|refutes|undercuts|subsumes|replaces, conflicts[], computed_from: event_seq}`；Evidence 拆 `provenance_grade A–E`（来源可信度）与 `support_strength weak|moderate|strong`（方向强度），不混算。
- L2 卡加 `hypothesis_id, prediction_ids[], assumption_refs[], contradicts[], evaluator_ref, scope, belief_delta`，类型补 explanation|obstruction|bound。
- 映射：Record→Evidence(draft)+Attempt；Ledger→Claim(verified)+Evidence(strong)；Archive→Paper/Explanation/Theory；Lineage→私有 belief overlay（不评审）。

**与 shared_frame / 既有设计的冲突（先标注，不擅自改名）**
1. 其 Evidence 只有 strength 三档，与 00 规范 A–E 是两套标度 → 建议拆分。
2. 其只有单一 versioned BeliefState；Station 私笔记与 Co-Scientist 未验证假设表明需「公共信念 + 私有 overlay」两轨 [B-/C]。
3. Explanation 的 draft/reviewed/accepted 无验收条件，Theory 无预测承诺字段 → 需加字段。
4. 「最小集合」缺 Prediction/Assumption/EvaluationSpec，严格说不够用 [E]。
5. 与既有设计：0.1 成果卡无信念/矛盾字段；V2 的 spec_extractor 抓到「互信息导引」实为硬编码偏移，说明 Claim 必须记 mechanism/condition（work/01 §1.2）[K]；建议这三类字段进 0.1 模板，不新增运行时。

**与其它章（shared_frame §6 编号）的依赖**：02 发现循环定 Hypothesis→Assumption/Prediction 的创建与 novelty 检索；03 知识制度的准入/评审是 BeliefGraph 的信任来源（provenance_grade 由它给）；04 控制运行时把 belief_delta 写入事件日志与决策代，并给冲突消解预算；06 人机协作需为人类假设/反馈标 source_type（Co-Scientist 专家假设可进锦标赛，p.37）；05 元层的 taste/偏好不得进 BeliefGraph（只进私有 overlay/Policy）。

**最大风险**：BeliefState 变成「又一份没人读的文档」。若 BeliefGraph 不能自动重算、不进 Scheduler/Orchestrator 的 frontier、也不改变下一步动作（预算/信用/停止），它就只是日志。最小验证：P0 两周闭环加一条指标「belief_delta 改变下一动作的比例」；Station/Cogentic 均未测 [E]。

**最可靠 3 条**：① 发现多类型（9/28 计分、7/28 要求未计分、12/28 皆非），单一分数对象不够 [B]；② 未评审共享传播错误（582 点例），公共记忆须评审准入 [B]；③ 证据必须绑装置（V3 完成信号效应）[K]。
**最不确定 3 个**：BeliefGraph 更新粒度与成本；公共/私有信念共存不互污；解释的量化准入标准 [E]。