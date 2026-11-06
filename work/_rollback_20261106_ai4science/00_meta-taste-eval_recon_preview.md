# 05 元层与评估：Recon + Preview

> 角色：meta-taste-eval｜日期：2026-11-06｜只写本文件，不写代码、不跑实验、不改既有文件。
> 读：05（P8/P9、§4）、06（§6）、07（§3–4）、04、work/01（§4、§7）全文；00_shared_frame、00 规范。
> 原文核：Station v2 appendix 398–709（元反思）、main 64–77/166–168（再发现协议/消融）；Lehman notes §3–9；2604.18005 tex（§4、Vendi、Unbound Junior）；LocalOptima 综述全文。

## A. 约束备忘

**本领域必须支持**
1. 元反思 = 外部视角 + 强制写回 + 执行隔离。Station v2：每 50 tick、3 轮、模型临时换 GPT-5.5、11 个问题池；每条提示词都以"写回"结尾（appendix 398–709）。[A-原文]
2. 开放式评估 = 预注册子发现 rubric + 证据要求 + 多评委/seeds + 盲专家一致性。Station：跑前把 oracle 拆约 10 个子发现；只有"实质相似且有证据"才算恢复；rubric 要求机制级证据（探针超基线/干预/held-out/对照），不按关键词命中计数；GPT-5.5×3 seeds 评 3 份报告、取 9 个分数均值；专家盲评"高一致"（未给阈值）。[A-原文]
3. 评判/红队/校准分离：frozen holdout 永不变、红队只加 live、Judge 与 Maintainer 分权、校准集测漏检/误杀。[C-06]
4. 品味可表示、可继承、跨模型族异构。Diversity Collapse：Horizontal Vendi 8.08 vs Interdisciplinary 4.65，坍塌源于"专家身份+层级权威"组合而非资历；同族模型换皮增益有限（异构 +34.0%，p=0.0003）。[A-实验]

**现有设计缺什么**
1. P8/07 有触发/输入包/写回/指标，但无 TastePolicy 的字段级表示与传承路径；shared_frame 仅 Program.taste 一句。[E]
2. P9/06 有校准、红队、frozen/live，但无再发现协议的操作细节（子发现拆分、rubric 预注册、专家一致率报告）与红队覆盖率指标。[E]
3. 反奖励黑客只有提示词/原则，没有"hack 率"的测量装置。[E]
4. 元层与 Judge 的隔离未定义：Advisor 改阈值可间接改判据、与评审串通。[E]

**3 条最关键约束**
1. 不写回=不生效：反思必须产出结构化 ReflectionRecord + PivotPolicy/TastePolicy 变更，Scheduler 拒收无写回。[A/B]
2. 无校准不门禁：关键词匹配、单次 LLM 打分不得作为准入或新颖性判据。[C/E]
3. 共享事实、隔离品味：否则 H2 不成立，多路线会坍塌。[A/E]

**3 个待定问题**
1. 同 Agent 换模型 vs 独立反思 Agent 的收益差：Station 未做该消融；H3 只能拆"承诺×反思"。[B]
2. 品味的可计算表示与跨族异构成本：用几族、如何合并而不平均化成"无品味"？[E]
3. 开放式评估的 judge 上限与专家一致率门槛：Station 只写"high agreement"，数字未核实。[B/未核实]

## B. 设计立场

**核心主张**：元层不是"让 Agent 自省"，而是把过程证据编译成可审计、可消融的 policy 对象（PivotPolicy/TastePolicy）；评估不是"打分"，是"预注册 rubric + 校准 judge + 红队 + 冻结/活体双集"的测量装置。H3 是本层唯一可直接裁决的实验：承诺窗口 × 反思模式（无/轻/独立），指标=驻留时长、pivot 率、attractor 占比、恢复率；Station 是 Supervisor+反思联合移除（75.8%→57.9%、67.0→55.5 tick），不能归因到反思单机制。[B]

**协议要点（07 + Station，落成接口）**：触发=每 N 动作/每 M 决策代/停滞/换向前；输入包 6–8k token（契约摘要+动作-观察摘要+路线状态+3–5 成果卡+过程指标+问题池）；问题池从 Station 11 个取 5–6；写回=meta-prompt/私有笔记/路线计划/PivotPolicy/成果卡状态；行为指标=深化率、pivot 率、attractor 占比、重复率、采纳率；限时限 token，连续两次无行为变化降频。[A-原文/B/E]

**对象/接口草案**（对齐 shared_frame；冲突先标注）
- ReflectionRecord（已有）：补 mode=switch_model|independent、trigger、input_hash、problems_used、writeback_refs、adopted；Meta→Orchestrator/Scheduler。
- PivotPolicy（已有）：commitment_window、pivot_evidence、attractor_flags、cooldown；写回后由 Scheduler 强制。
- TastePolicy（§2 有输出名，§4/§5 无字段定义——**冲突：shared_frame 的 TastePolicy 缺字段/契约**）：方法族权重、问题框架偏好、证据标准阈值、反例容忍度；版本化，存 Program.taste，只进 HandoffCard，不广播。
- TastePolicy 传承=版本化 diff + HandoffCard + Program，只进私有记忆与交接卡；防同族同质化=反思者/评委跨族、各路线给不同品味起点、品味不进质量分与探索信用（对应 H2 隔离）。[E]
- EvaluationProtocol、RedTeamCase（新增，建议挂 Review/Judge）：子发现 rubric（跑前冻结）、judges/seeds、frozen/live、专家一致率；RedTeamCase 带 coverage_tag，红队覆盖率=（被攻击并暴露的 claim/应攻击 claim）；红队 case 只入 live。[E]
- 不擅自改名；新增对象请 Lead 在 frame 裁决。

**与其它章的依赖**：01 提供 Claim/Evidence 字段；02 提供问题池与 pivot 触发；03 提供 frozen holdout/复现/谱系；04 的 Scheduler 执行 PivotPolicy、Judge 执行 JudgeVerdict；06 提供专家盲评接口。H1 的"每轮可达集新增项"须由 Judge/RedTeam 记录；H2 靠 taste 隔离与多样性指标；H3 由本层主导。

**最大风险**：①反思变成新 attractor（用反思逃避做事）；②11 提示词池本身是价值注入，未披露即隐性偏好；③同族模型自我合理化（需跨族反思者/评委 + 独立输入包）；④开放式评估被 hack——Station 提示词已列 5 类（hack 评测器、浅捷径、灌水 archive、无尽诊断工具、错误论证宣布不可能），但只提示、未测量；⑤撞车：Station 已覆盖"11 提示词元反思+写回+再发现 rubric"，Cogentic 有 Process Advisor，Co-Scientist 有 meta-review——差异化只能落在 H3 拆分归因、品味对象化×跨族异构、评估装置可审计（校准/红队/双集/hack 率），不能宣称"首创元反思/开放式评估"。[E]
