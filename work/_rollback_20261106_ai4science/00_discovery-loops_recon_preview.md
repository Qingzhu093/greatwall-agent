# 02 发现循环：Idea / Empirical / Theory（P0 Recon + P1 Preview）

- 作者：discovery-loops（teammate）· 2026-11-06
- 材料：00_shared_frame.md、00_团队协作规范与证据等级.md、05/06/07/04 号设计文档、work/01 考古盘点（均全文）；Co-Scientist PDF（p.2–12、29–37、48–51、54–55）；MLE-STAR 3_method.tex、4_experiments.tex（全文）；Cogentic main.tex（全文）；Station v2 sections/main.tex（全文）。
- 未读：Co-Scientist p.38–47、56+ 补充材料；Station v2 appendix 实现细节。

## A. 约束备忘

**A1 本领域架构必须支持什么**
1. 多假设并行与显式竞争：Co-Scientist 用 Elo 锦标赛（初值 1200），高排名多轮辩论、低排名单轮比较（Methods p.34）；Evolution 只新增假设、不改不替换旧假设（p.35）[A-实验]。
2. 生成与判定分离，且判定带检索：Reflection 无检索把已发表想法判为新颖 6.14/10，有检索降到 2.38；正确性置信 7.4→8.46（Suppl. Note 3, p.50）[A-实验]。
3. 检索必须变成可执行基线：MLE-STAR 检索 M=4 个候选模型逐个真跑、按验证分贪心合并（§3.1）；精炼由消融选块，K=4 内环、T=4 外环（§3.2、§4.1 设置）；22 赛题×3 seeds 下使 AIDE 的 any-medal 率 25.8%→43.9%、above-median 39.4%→63.6%（§4.1 Main results）[A-实验]。
4. 对抗双验证：单稿验证 + 同轮全稿并读验证，两者都过才接受；审计员从被拒稿中抽中间引理、隔离复验后入库（Cogentic §2.2、§2.3）[C-框架，无消融]；每问题约 O(100)、最难 O(1000) 次模型调用（Intro）。
5. 长程坚持与强回退：Supervisor 设承诺期，换向只在包不可用等例外获批；每 50 tick 元反思（Station v2 Methods）；移除二者再发现率 75.8%→57.9%、项目时长 67.0→55.5 tick（Results §6.1）[A-实验，单任务]。
6. 解释能力是短板：Station 三任务恢复 75.8%/70.4%/41.9%，因果干预类最弱（Results）[A-实验]。

**A2 现有设计缺什么**
1. 05 主链（立题→预研→决策→执行→成果→验证→入库，§3）没有假设级锦标赛，只有工程路线级比较；Idea 循环缺"排名/淘汰"对象。
2. shared_frame 有 Explanation 对象，但接口表没有其 producer→consumer 行；Theory 循环无出口。
3. ExperimentSpec 只在接口表出现，06 的 worktree 节点无"实验设计"字段；MLE-STAR 式"消融选块"无对象承载。
4. EvidenceRecord 的"方向/强度/条件"如何从 ObservationBundle 抽取，05 P7 只讲验证、未讲抽取。
5. 失败回退无载体：Experiment.failed 如何进失败清单、如何触发 Idea 重开，未定义（05 P4 只有 blocked）。

**A3 三条最关键约束**
1. 新颖性必须由独立、带检索的判定给出；生成者自评会系统性高估（6.14 vs 2.38）[A]。
2. 每个发展动作必须留下可复用中间物或扩张可达集，否则只是重采样（05 P4、LocalOptima 定理）[A/E]。
3. 评测装置先于结果被验证：V3 中屏蔽 is_all_cleared 后 node_06 的 L1 由 173.94 升至 333.05s/源（内部档案 K），否则 EvidenceRecord 只是测量假象[C，内部核实]。

**A4 三个待定问题**
1. 开放式任务里 Elo 只排相对优劣、不代表科学价值；评委同族化（Station 反思全用 GPT-5.5；Co-Scientist 全用 Gemini 2.0）的影响未做换模型消融[未核实]。
2. Theory 何时算"成立"？Co-Scientist 未见"解释"对象与准入规则，Station 未报告解释层评估[未核实]。
3. 三循环触发用什么单位：tick（Station 50）、预算区间（05 建议）还是动作/决策代？无对照数据[E]。

## B. 设计立场

**B1 核心主张**
不造三个独立流水线。Idea/Empirical/Theory 是同一状态机（Hypothesis→Experiment→Evidence→Claim→Explanation）上的三个相位，共享 BeliefState；相位间只传对象、不传自然语言摘要；判定权外置给 Judge/Trust，循环自身只生产候选与证据。每个 ResearchProposal 必须带四件套：最便宜测试、预期信号、kill 条件、delta_type（local/adjacent/orthogonal，07 §4.3）。

**B2 对象/接口草案（对齐 shared_frame）**
- Idea：Question+GapCard+失败清单+BeliefState → ResearchProposal；触发=决策代、contradicts 边新增、某族无活跃节点。产出 Hypothesis.ranked。
- Empirical：ResearchProposal → ExperimentSpec（变量/对照/预算/停止条件）→ Experiment → ObservationBundle → EvidenceRecord。触发=Orchestrator 接受提案（不能由 Idea 自触发）；证据抽取前必须先过"装置有效性检查"（V3 教训）。
- Theory：EvidenceRecord 簇或未解释矛盾 → Explanation（机制/类比/范围/可检验预测）；解释须拆成可独立验证子假设（Co-Scientist deep verification，[B]），预测交 Empirical 做判别实验；预测未验证不得升 accepted。
- 回退：kill 条件满足 → Experiment.failed + 失败清单 + 路线 dormant/blocked，只有新机制/新条件才解封（05 P4）。
- 冲突标注：①shared_frame §2 四循环无 Theory，§3 又把 Theory 列入"发现循环层"——Theory 是循环还是环节未定，本文暂按循环写；②接口表缺 Explanation 的输入输出与 PredictionCard；③缺锦标赛/排名状态对象（Elo 初值 1200 无处存），建议挂 BeliefState.ranking 或新增对象，不擅自命名。

**B3 依赖**
- 01 science-ontology：Claim/Explanation 状态机、BeliefState 写回 API。
- 04 control-runtime：触发点放决策代；JudgeVerdict 作比较输入；每条 Experiment 一个 worktree。
- 03 knowledge-institution：EvidenceRecord→LedgerEntry 的复验准入；Theory 只能经 Trust 进 Archive。
- 05 meta-taste-eval：pivot policy 改触发/预算，不改 Evidence；taste 只作 proposal 排序的软项。
- 06 human-domain：acceptance=script/rubric 决定 Empirical 判据与"可检验预测"的形式。

**B4 最大风险**
三相位共用一个 Hypothesis 状态机会诱发"状态跃迁作弊"：把 ranked 假设直接写成 supported Claim，把未验证解释写成 accepted Theory。V2 有先例（node_01 宣称互信息、实为硬编码偏移，内部 K）。对策：状态机硬门 + 每次跃迁写 provenance + Judge 独立于生成者。

## C. 速记（供汇总）
- 最可靠 3 条：①生成/判定分离且判定带检索 [A]；②Evolution 只新增不替换，避免污染头部 [A]；③对抗双验证+中间引理隔离复验方向正确但未消融 [C]。
- 最不确定 3 个：①Elo 锦标赛对开放式科研的因果收益（Co-Scientist 只给相关性与无饱和观察）[未核实]；②Theory 是否值得独立成环，还是 Empirical 的后处理 [E]；③三循环共享状态机的收益 [E]。
- 与既有设计冲突：shared_frame 的 Theory 定位歧义；05 主链无锦标赛、无 Theory 位置；06 的路线级决策与假设级锦标赛如何合并未定。
