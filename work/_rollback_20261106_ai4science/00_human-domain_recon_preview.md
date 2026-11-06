# 06 人机协作与领域适配：Recon + Preview

> 作者：human-domain｜日期：2026-11-06｜依据：Co-Scientist arXiv:2502.18864v2（正文 pp.1–42）；Station v2 main.tex §4–§7 与 appendix §Evaluation Details/Limitations；ARI 复评 AIS_-_Main_-_Pre_Print.tex §Preparing/§Costs and Effort/§Limitations/§Discussion；本团队 04、work/01（K/R 标记）；05 的 P0/P5/P7；06 §1.3/§9；shared_frame。未读：Co-Scientist SI Note 7（安全伦理，按正文引用标注）。

## A. 约束备忘

### A1. 本领域架构必须支持
1. **人类目标与约束注入、变更留痕**：TaskContract 保留 VERBATIM/DEFINITION/CONSTRAINT/ACCEPTANCE/ASSUMPTION/QUESTION 六类标签，ASSUMPTION 变更须人批 [B；06 §9]。
2. **提案评审与实验审批分开**：提案可机器排序，实验启动（尤其不可逆/高成本）须人签 [B；Co-Scientist 三个验证全为 expert-in-the-loop，pp.36–37]。
3. **领域验证经济学分型**：干实验（可执行+holdout+泄漏检查）、形式化（Lean 机检）、湿实验（协议+对照+统计功效+生物安全审批）、数据科学（预注册+holdout+null model），不能共用一套 gate [B；Co-Scientist 仅体外并自认非临床，p.13/p.24；ARI 单域失败，§Limitations]。
4. **安全/伦理/双用途/数据治理**：风险分级、数据许可与同意、代码沙箱、AI 贡献披露与署名 [C；ARI §Discussion；Co-Scientist 默认含 safety 准则，p.29]。
5. **竞赛→开放科学的迁移边界**：确定性评分器、固定终止、已知答案、无人评审不能直接搬；测量装置须先被验证（V3 完成信号污染见独立评议探针 [K]，本轮未重跑）[B]。

### A2. 现有设计缺什么
- shared_frame 无 **Actor/Approval/DomainProfile/AccountabilityRecord**；TaskContract 只写"人/契约官"生产者，无权限字段。[C]
- Budget 无 **人类注意力预算** [C]；人类时间在 Co-Scientist 是 <1h 设定+~3h 终审/案例（p.37）、ARI 是 25h/篇（§Costs）[B]。
- 无"不可逆/对外发布/高风险动作"清单与升级路径；JudgeVerdict 无人类申诉/覆盖字段；Review 有盲评标记但无人类评审者身份与权威。[C]
- ArchivePaper 消费者写"全体+人类"，却无审批、AI 披露、责任人与撤回接口。[C]

### A3. 三条最关键约束（每条附等级）
1. **四类动作必须人类批准**：不可逆、高成本、对外发布、高风险（生物/双用途/隐私）；其余在预算信封内自动。[B] 依据：Co-Scientist 三个验证均为 expert-in-the-loop（p.7），但人类介入点有限（<1h+~3h，p.37）；Station 运行期零人工干预、任务却由人设定（main.tex §4）；ARI 显示其仍需大量人工准备与审阅（§Costs、§Discussion）。
2. **验证门由 DomainProfile 实例化，不能全局统一**。[B] 依据：Co-Scientist 只做体外且明说不能替代临床前/临床（p.13、p.24）；ARI 单一数据集/领域为其自认局限（§Limitations）；Station 用隐匿真值+自动评审，并以盲评专家校准（66 个判断 97.0% 一致，appendix §Evaluation Details）。
3. **责任链不可外包**：每个 Claim/Paper/Program 必须有 accountable_human、AI 贡献声明、许可/同意与撤回联系人；系统不得自主对外发布。[C/D] 依据：ARI 提出披露与署名风险（§Discussion）；Co-Scientist 伦理细节在 SI Note 7（未读，不引用）。

### A4. 三个待定问题
1. **人类介入的最小频率与粒度？** Co-Scientist 每案例 <1h+3h、Station 零介入、ARI 25h/篇，三者任务与自主性不可比；无对照证明最优比例。[B/E]
2. **开放式任务由谁定义"好"，如何防专家偏见/权威坍塌？** Station 中 oracle 作者把 75% 的非重叠提案打 1–2/5（main.tex §Gaps），说明判定本身有主观性；Co-Scientist 承认可能同质化研究方向（p.25）。盲评、预注册 rubric、多专家面板如何组合未定。[B/E]
3. **湿实验自动化与双用途边界在哪？** Co-Scientist 把实验室自动化列为未来工作（p.25）；AI 能否驱动自动实验、哪些领域须前置安全审查，未读到可核规范。[C/E]

## B. 设计立场

### B1. 核心主张
**人不是"审批弹窗"，而是有权限边界的 Actor；自主性由"可逆性 × 成本 × 风险"三因子决定；领域差异编码进 DomainProfile；责任落到 accountable_human。** 人类注意力是稀缺预算，必须显式计价。[E-推断，锚点见 A1–A3]

### B2. 对象/接口草案（与 shared_frame 对齐）
新增对象（不改既有命名，冲突另行标注）：
- **Actor**{id, role(goal_setter/PI/reviewer/safety_officer/data_steward), authority_scope, human_cost}；
- **Approval**{subject_ref(ExperimentSpec/ArchivePaper/Artifact/对外发布), required_by: DomainProfile, approver: Actor, decision, conditions, rationale, signature}；
- **DomainProfile**{domain(dry/wet/formal/data_science), validation_mode, cost_model, irreversibility, risk_class, allowed_actions, forbidden_actions, required_approvals, publication_rule}；
- **AccountabilityRecord**{subject_ref, accountable_human, AI_contribution, license/consent, disclosure, retraction_contact}；
- **HumanAttentionBudget**：Budget 扩展字段 human_hours/stage。

接口：
- **TaskContract 扩展**：+domain_profile_ref、allowed_actions、requires_approval[]、human_owner、publication_rule；六类标签不变。
- **HumanGate**：Orchestrator 出 ApprovalRequest（含证据包：claim/evidence/不确定性/成本）→ Actor 决策 → Scheduler/Empirical/Trust 执行；无 Approval 不得执行。
- **DomainValidation**：Judge 按 DomainProfile 选验证器；人工审批与机器门禁**串联**，不互相替代。
- **Escalation**：Auditor/RedTeam → safety_officer，可阻断。

**冲突标注**：
1. shared_frame 无 Human/Actor/Approval/DomainProfile 对象——本章新增，不擅改既有对象名。
2. Budget 无 human_hours；ArchivePaper 无审批/披露字段；JudgeVerdict 无人类申诉/覆盖字段；Review 的"盲评标记"无人类评审者身份。建议主文档统一补字段。

### B3. 与其它章的依赖
- **01 科学本体**：Claim/Evidence/Paper 需 accountable_human 与证据等级字段；
- **02 发现循环**：ExperimentSpec 需 Approval + DomainProfile；Idea Loop 需人类目标/约束注入与提案评审；
- **03 知识制度**：ArchivePaper/Review/Lineage 需人类评审权威、披露与撤回；
- **04 控制运行时**：Scheduler 阻塞在 Approval；StateStore 持久化审批；HumanAttentionBudget 进入调度；
- **05 元层评估**：RedTeam 必须含伦理/双用途；评估需盲评与预注册；人类反馈用于校准 taste。

### B4. 最大风险
**"人机协作"退化为事后签字与责任洗白**：人类在 3h/25h 量级内无法真正审阅，LLM 评审又漏硬伤（ARI §Discussion）。缓解：风险分级审批（只把四类动作推给人）、审批证据包、人类注意力预算、审批留痕与事后审计、Judge 与人类冲突的升级协议。次风险：过度 gate 杀死长程自主性——用"预算内可逆动作预授权"解决；第三风险：人类目标设定导致方向同质化（Co-Scientist p.25），需盲评+多专家目标。
