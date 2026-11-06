# 03 机制卡 B：证明发现（Cogentic）与 Station 两代开放世界环境

作者：proof-station（子代理）｜日期：2026-11-06｜对应任务：task-3｜状态：供 Lead 综合的材料，不是最终结论。

## 0. 读了什么、读到什么深度、命名先对齐

**材料与阅读深度**（绝对路径）

1. Cogentic：D:\Documents\deepseek harness\论文研读\2609.40324_Cogentic\source\main.tex——684 行**全文逐行读完**（§1–§4 正文 + 附录五个问题提示词）；中文综述只做对照抽查（发现其"独立简报天然保留多样性"是原文没有的推断）；PDF 未另读，.tex 即原文源文件。
2. Station-数学版：D:\Documents\deepseek harness\论文研读\2608.23691_AutonomousMathematicalDiscovery\source\ 下 dualverse.tex（329 行全文）、meta_analysis.tex（172 行全文）、station_appendix.tex（197 行全文）、additional_analysis.tex（90 行全文）；中文综述只做关键词抽查（发现"完全去中心化""断崖式坍塌"等原文没有的措辞）。
3. Station-开放科学版：D:\Documents\deepseek harness\论文研读\2610.08927_Station_OpenEndedDiscovery\source\sections\ 下 main.tex（237 行全文）、abstract.tex（全文）、appendix.tex 中 The Station、Implementation（Supervisor/Meta Reflection）、Evaluation Details、Resource Usage、Limitations 各节共约 700/1616 行；**未读**：sub-discovery rubric 细则、Consolidation 提示词全文、两个 exploratory 任务附录细节；中文综述仅抽查。
4. 用户既有材料（只读，用于冲突分析）：长程Agent_探索架构草案\01_架构设计.md、02_执行约定与提示词.md；长程Agent_资料研究\01_两个核心问题.md、05_Cogentic之后的精读入口.md、06_六份材料阅读与思路整理.md。V1/V2/V3 原始运行产物未读（由 archaeologist 负责）。

**命名对齐（重要）**：任务里的"Station v1"= 论文 2608.23691，但该论文正文把自己扩充的环境称为"Station v2"（相对 chung2025station 的 v1）；任务里的"Station v2"= 论文 2610.08927，它沿用同一环境代码库，只替换了 agent 组成、Supervisor 契约与 Meta Reflection 周期。下文统一用 **Cogentic / Station-数学版 / Station-开放科学版**，避免版本号错位。两篇 Station 核心作者重叠（Chung、Du）、同一 DualverseAI 代码库，但不是同一次研究的独立复现。

## 1. Cogentic（2609.40324）

### 机制卡 C1：Orchestrator——只分配、不做数学的中央调度器
- 来源：§2 Components、Workflow、§2.1、§2.5。
- 证据等级：**C**（设计声称 + 5 个案例；无逐角色消融）。
- 怎么运作：持有全局状态；每轮开头决定跑几个 Prover、每个去哪个"方向"（一个具体断言：某个界、常数、构造、找反例，或修最后一段证明）；派生 Summarizer；汇总验证器共识；管理 Record 与 Ledger；draft 过关后决定是否继续挖剩余方向，预算耗尽或方向挖尽即终止。原文明确"orchestrator 不做数学推导"。
- 报告的数字：5 项专家验证结果（Table 1）；多数问题 O(100) 次模型调用，最难 O(1000)（§1）。**未报告**：每轮 Prover 数、轮数、并发上限、token、墙钟。
- 边界：题目需要有可定义的"方向"和验证标准；验证器是唯一质量门；作者只选了自己领域内的问题。
- 解决：多竞争猜想下的资源分配、长程终止、中间结果不丢。
- 代价：单点调度；"往哪个方向投多少"本身就是数学判断，与红线存在张力（见 C5）。
- 启示：**[改造为]** 保留"轮次 + 方向配额 + 显式终止条件"，但把方向分配的理由写成可审计记录 [E-推断]。
- 最小验证：同预算 A/B——轮次制方向配额 vs 单 Prover 连续采样 K 次；指标=专家可核验的引理数、失败轮数、调用数。

### 机制卡 C2：每 Prover 派生一个 Summarizer，写独立简报
- 来源：§2.1。
- 证据等级：**C**。
- 怎么运作：orchestrator 为每个 Prover 派生一个 Summarizer；Summarizer 读该方向此前全部尝试与验证判定，挑"最有信息量"的片段，并给出可能下一步的建议；每个 Summarizer 独立生成，因此同轮不同 Prover 得到同一历史的不同读法；长文档只给路径不给全文，Prover 可自行按需打开。
- 报告的数字：**未报告**简报长度、上下文预算、Summarizer 数量。
- 边界：历史体量大、且"值得读"的信号稀疏时收益最大；历史质量差时简报继承偏差。
- 解决：历史增长导致的上下文爆炸、失败原因被冲掉。
- 代价：每 Prover 多一次以上调用；"建议"小节会把路线偏好带进 Prover 上下文。
- 启示：**[采纳]** 简报是"有损但有方向"的压缩；**[拒绝]** 把"独立生成"当成"方法独立"或"多样性已解决"——原文只说不同读法，未测多样性 [E-推断]。
- 最小验证：3 臂（全历史直给 / 统一简报 / 每 Prover 独立简报），测路线相似度 + 成功率。

### 机制卡 C3：两层对抗验证（Individual + Cross-Draft）
- 来源：§1 末、§2.2。
- 证据等级：**C**（设计）；最终结果经领域专家核验，但那不是验证器有效性实验。
- 怎么运作：每份 draft 先由一名 individual verifier 全文审；另一名 cross-draft verifier 同轮并排读全部 draft，找共享盲点、比较各稿强度；两份验证都过才 accepted。两者都是对抗式：默认每一步错、每个引用未核实。
- 报告的数字：**未报告**验证器数量与模型、漏检率、误拒率、复核轮数。
- 边界：需要可读的自然语言证明；无形式化保证（与 Lean 路线相反）。
- 解决：单稿验证的漏检、同轮多稿共有的盲点。
- 代价：每稿至少两次验证调用，可能推高轮数与调用量。
- 启示：**[改造为]** 保留"逐稿 + 跨稿"两视角，但补多数票或错误注入校准 [E-推断]。
- 最小验证：向已知正确/已知含错的草稿注入错误，测两臂漏检率与误拒率——这是两篇都没做的实验。

### 机制卡 C4：Record（尝试账）+ Verified Ledger（已验证引理账本）
- 来源：§2.3。
- 证据等级：**C**。注意"失败案卷"是中文综述的译法，原文 Record 记录的是"尝试 + 判定"，成功与失败都记。
- 怎么运作：Record 按"想证明什么"聚合尝试，每条存所用方法 + 被驳倒的具体理由；Ledger 存跨轮确认的片段。轮末**auditor** 从"整篇被拒但含正确引理"的证明里抽出片段，改写为自包含引理，送去**隔离复验**；通过者进入 Ledger，之后任何 Prover 可免证复用。Ledger 也记死路（被已验证反例排除的界写成"已排除"）。
- 报告的数字：**未报告**每轮入库条数、复验通过率、账本规模、死路条数。
- 边界：只对"可孤立复验"的片段有效；纠缠在整体论证中的局部正确会被丢掉。
- 解决：整篇被拒时中间成果全丢、后续重复推导。
- 代价：每轮多一轮抽取 + 复验；"局部正确但依赖错误假设"的片段有入库风险（原文未报告错误率）。
- 启示：**[采纳]** 这是用户"垫脚石怎么存"的直接答案：扁平、带类型的账本 + 死路，不需要层层嵌套 [E-推断]。
- 最小验证：3 臂（无账本 / 只记录不复用 / 记录+复验+复用），测重复推导率与最终成功率。

### 机制卡 C5：Process Advisor 与 "No Mathematical Opinion" 红线
- 来源：§2.4。
- 证据等级：**C**（红线执行方式未报告，实为 **D**）。
- 怎么运作：每轮末，advisor 读本轮乃至全运行的验证日志，找跨轮模式（反复犯的错、常见论证缺口、某个验证器漏掉但被另一个抓住的盲区），据此建议调整给 Prover/Verifier 的指令，并向 orchestrator 建议配额。它独立存在的原因是 orchestrator 要同时管多个 agent、上下文不够。
- 红线原文（§2.4 末）："neither the advisor nor the orchestrator is permitted a mathematical opinion: they cannot speculate on what the answer is likely to be, recommend a technique, or declare a direction promising or dead."
- 执行方式：**未报告**——没有公开提示词、没有检查器、没有违规案例，只有这一句设计声明。
- 张力 [E-推断]：orchestrator 仍决定"跑几个 Prover、各去哪个方向、何时终止"，这些是资源层面的数学判断；红线约束的是内容（猜答案/荐技巧/判生死），不约束分配。所以"无数学意见"≠"无偏"。
- 启示：**[采纳]** 把红线写成可审计的禁止清单；**[拒绝]** 当成已验证的中立性保证。
- 最小验证：对 advisor/orchestrator 输出做分类（是否含答案猜测/技术推荐/方向判决），再测其与最终成功率的关系。

### 1.6 Cogentic 证据状况与代价（单列，避免被机制卡盖过）
- 5 个案例全部经领域专家验证、各有配套论文；但正文**没有逐角色消融**（全文检索 "ablation" 为 0）、没有失败案例、没有成本表。
- "从问题陈述开始、无专家提示"要打折：附录 5 组提示词中，4 组直接给 arXiv/PDF 链接，1 组给论文名；autobidding 第一部分的机制与 1.5 猜想是作者已有的；inverseopt 与 anytime 的目标来自已知论文/猜想；multi-item 提示词要求"factor 3"，最终得到 3.52（未达 3，但优于 5.2）。"无提示"指没有告诉它怎么证，不是没有背景与目标。
- 代价：唯一量化是 O(100)–O(1000) 次模型调用；**并发数、token、墙钟、人工小时均未报告**。人工不是零：作者核验每个证明、写 exposition、有的还继续推进了结果；部分配套论文含早已研究该问题的合作者。
- 判断：Cogentic 是"架构存在性证明"（B- 到 C），不是"组件有效性证明"。

## 2. Station-数学版（2608.23691）

### 机制卡 S1：离散 tick + 房间 + 生命周期——世界规则本身就是机制
- 来源：§2 Method、Appendix A。
- 证据等级：**B-**（环境描述完整、结果依赖它，但环境本身无拆解消融）。
- 怎么运作：6 agents（2 GPT-5.5 / 2 Claude Opus 4.8 / 2 Gemini 3.1 Pro）；离散 tick，每个 tick 所有 agent 从同一状态取 observation 再回应；房间=Research Center（读任务、把自然语言指令交给 coding assistant 执行、读代码与结果）、Archive Room、Mail Room、Public Memory Room、Common Room、Reflection Chamber、Private Memory Room、Question Room（仅 tenured 可进，投票判定问题是否已解）。动作写成 /execute_action{...}。生命周期：最多 200 tick；**前 40 tick 隔离**（不能看公共知识、不能交流，只能看本谱系记录）；成熟后进公共房间；100 tick 后可离开；离开即同模型补位，维持 6 人。
- 报告的数字：每问题约 1,000–2,000 tick ≈ 1–2 周墙钟；上下文约 300k token 时要求写摘要续接。
- 边界：需要可运行 evaluator 与沙箱；任务要有可实验对象。
- 解决：长程研究没有共享时间线、知识不能跨代累积、个体寿命有限。
- 代价：同步 tick 每步等最慢者；规则复杂；6 agent × 千 tick 成本高。
- 启示：**[采纳]** "隔离期 + 谱系私笔记 + 公共房间"三段式，是用户"独立期/延迟授粉"的现成制度模板 [E-推断]；隔离期改为"以形成可讨论起点为准"。
- 最小验证：隔离期 0/20/40 tick 三臂，测路线相似度、重复实验率、成功率。

### 机制卡 S2：Archive + 审稿人——论文作为可准入的知识单元
- 来源：§2、Appendix A.3。
- 证据等级：**B-**（有消融：去掉 Archive Room 后 3 seeds 0/3 未达 594；但整屋移除，不能单归因于"论文"）。
- 怎么运作：论文必须综合科学贡献、不能是实验日志；GPT-5.5 reviewer 按 NeurIPS workshop 标准评 rigor/novelty/significance，1–10 分，≥6 接受，拒稿附意见可改投；接受论文永久可读、可引用、可被后代继承；Archive Surveyor（Codex/GPT-5.5）按需产出带引用的文献综述。kissing 第一次 Station：125 篇论文、923 条引用；55/125 曾被拒至少一次；总拒稿 199 次。
- 报告的数字：如上；未报告评审调用成本。
- 边界：需要可写清的评审标准；论文长、评审贵；评审可能压掉非常规但正确的结果。
- 解决：知识无法累积；错误结论被当事实传播（无 Archive 消融中出现"任何构型不可能超过 582 点"的伪定理，被其他 agent 采纳）。
- 代价：评审调用、发表延迟、被"为显得高产"灌水的风险（开放科学版的 Meta Reflection 提示词专门警告这一项）。
- 启示：**[采纳]** 门禁 + 可引用文献库；**[注意]** 消融是整屋移除，不能声称"评审本身有效" [E-推断]。
- 最小验证：有/无评审、阈值 4 vs 6、有/无引用查询，测"错误结论被后续采纳率"。

### 机制卡 S3：代际继承（lineage）——研究身份而非全文上下文
- 来源：Appendix A.2。
- 证据等级：**C**（设计描述，无消融）。
- 怎么运作：agent 以名字、私笔记、研究身份组成谱系；新 agent 可继承同模型谱系成为下一代（Noesis II→III），获得全部私笔记与记录；也可另开谱系。离开的 agent 可为后代写 role（更任务化、更明确的品味描述），等于让研究风格跨代演化。
- 报告的数字：未报告继承对结果的影响；只在讨论中说 agent 有时意识不到自己的研究与早期知识的联系。
- 边界：适合长跑多代；谱系过窄会同质化。
- 解决：换代即失忆、重复探索。
- 代价：私笔记与公共知识双轨，可能分裂；早期错误被继承放大。
- 启示：**[采纳]** "研究身份 + 私有笔记 + 角色描述"是比复制上下文更便宜的长期记忆 [E-推断]。
- 最小验证：有/无 lineage 继承，测跨代重复率与发现深度。

### 机制卡 S4：制度性反吸引子三件套（Holiday / Stagnation / Multistart）
- 来源：Appendix A.4、§4 Discussion、meta_analysis §2.4。
- 证据等级：**D**（机制贡献是作者回看对话的主观归因：holiday 23/28、archive 21/28、stagnation 14/28；不是消融）。
- 怎么运作：每 10 tick 的最后 2 tick 是 holiday，禁止实验与发论文，给随机反思提示（隐喻、跨领域、重访被放弃的想法）；evaluator 前沿 320 tick 无改进时启动 stagnation protocol，给成熟 agent 随机分 lane（exploration/exploitation/revival/understanding/strategy）要求重审假设；multistart 从同一状态跑 8 条 40-tick 分支，由 GPT-5.5 administrator 选出最有科学价值的分支继续（用于开局和 stagnation 之后）。
- 报告的数字：见上；未报告 holiday 产出率。
- 边界：需要长 tick 预算；multistart 需并行算力。
- 解决：attractor trap（反复调参、穷举局部最优）、局部搜索枯竭。
- 代价：holiday 占 20% tick；stagnation 可能强制切换；multistart 8 倍起步成本。
- 启示：**[改造为]** "强制停机反思 + 停滞分层重定向 + 多分支择优"比单一"新颖性奖励"更可实施 [E-推断]；但证据只有 D 级。
- 最小验证：holiday 0/10%/20%；stagnation 触发 vs 不触发；multistart 1 vs 8 分支（同总预算）。

### 2.5 结果、基线与消融（证据边界必须写清）
- 12 个 AlphaEvolve 问题 + 2 个案例；5/12 产生相对文献的新结果（有限域 Kakeya 新无限族与 53 点集、11 维 kissing 的 604 点构型、离散 Kakeya 针、sign uncertainty、Erdős minimum overlap），另有 Book Ramsey 两个新无限族、Jacobian 反例重构；全部有精确构造或 Lean 验证。
- 基线：同一 kissing 任务，4 种配置（OpenEvolve ×3 模型、Codex multiagent v2），3 seeds，按 8,000 分钟累计 evaluator 时间匹配；基线 0/3 达 594，Station 3/3 达 594 并进而达 604。
- 消融 1：去掉 Archive Room → 3 seeds 0/3 达 594。消融 2：六个全 Claude → 3 seeds 0/3 达 594。可复现：3 个独立 Station 都达 604，但路径与耗时差异大（作者建议多跑实例）。
- 证据判断：整系统 **B**；"archive 有用"是联合消融（房间含读+写+评审+surveyor+引用），只能支持"这个房间整体重要"；"跨模型协作有用"被全 Claude 消融支持，但混淆了模型能力（Claude 是 28 项中 18 项的主要发现者）与多样性。S4 的机制贡献统计是 **D**，不是因果。

## 3. Station-开放科学版（2610.08927）

### 机制卡 T1：Supervisor 契约——用预承诺对抗过早换向
- 来源：§3 Methods、Appendix B.1。
- 证据等级：**B-**（与 Meta Reflection 联合消融：75.8%→57.9%，3 seeds，仅一个任务；项目均长 67.0→55.5 tick）。
- 怎么运作：GPT agent 发表过论文后自动成为 Supervisor（同时一个；此后不能再交实验或发论文）；成熟 agent 首次例会提交 Research Proposal（方向、与任务及人类兴趣的理由、≥5 篇 archive 引用、含原文的 pre-commit 条款、时间表），承诺期 ≥60 tick；Supervisor 每 10 tick（tenured 每 20）一对一私信例会，结构是"报告—计划—指导"，可拒绝 pivot，除非方向确实不可继续；维护 Agent Record（存 Private Memory：批准、起止 tick、pivot 请求、警告）；**不得提出研究方向、不得给技术建议、不得 micromanage**。
- 报告的数字：92 次 meta reflection 事件中 71.7% 之后 10 tick 内出现深化/验证实验（描述统计，无对照）；项目均长 67.0 vs 55.5。
- 边界：开放问题、无即时指标、agent 有快速换向倾向。
- 解决：premature pivot 与路灯效应的一部分（"挑容易的"靠坚持难以完全解决）。
- 代价：强制坚持可能错过更好的方向；例会占 tick；Supervisor 是单点。
- 启示：**[采纳]** 预承诺 + pivot 审批，是"延迟授粉"的另一半：延迟共享之外还要**延迟放弃** [E-推断]。
- 最小验证：承诺期 0/60/120 tick 三臂，测时长、pivot 率、恢复率、成功率。

### 机制卡 T2：Meta Reflection——换模型做"外部同行评审"
- 来源：§3、Appendix B.2。
- 证据等级：**B-**（联合消融；71.7% 是描述统计；无单机制消融）。
- 怎么运作：每 50 tick，成熟 agent 必须进 Reflection Chamber 做 meta_reflect；系统从提示词池随机抽一题，加两轮续问，三轮内模型**临时切换为 GPT-5.5**（理由：观察到 GPT agent 更严谨、更中性）。提示池含 Overclaiming、Planning、Reward hacking、Scientific value、Research taste、Knowledge crystallization 等。模板要求它以"外部人类研究者"第一人称评审该 agent 的近期工作，且明令不得借这次反思解题。
- 报告的数字：92 次事件、71.7%；一个案例（把"静态墙"框架改用到 movable boxes）。未报告：换模型 vs 不换的差异、周期 25 vs 50 的差异（数学版附录写"至少每 25 tick"）。**研究 taste 的证据**只有提示词本身（要求 agent 反思自己是否有独特品味、借鉴领域领袖的启发式、形成可保有的 policy）与描述统计；数学版把"缺乏多样研究品味"列为限制（同模型族 agent 提出相似想法），但没有任何 taste 干预的对照。
- 边界：需要足够长的轨迹可评；提示池本身就是价值注入。
- 解决：judgment misalignment、reward hacking、长期方向漂移。
- 代价：每次 3 轮调用；强制中断；Supervisor 与 Meta Reflection 都用 GPT-5.5，可能带同族偏好。
- 启示：**[采纳]** "换模型 + 外部人设"是低成本去自我合理化 [E-推断]；**[注意]** 未做换模型消融。
- 最小验证：换模型 vs 原模型；周期 25/50/100；固定提示 vs 随机。

### 机制卡 T3：Consolidation Agent + 子发现评估协议
- 来源：§3、§4、Appendix C/D、Limitations。
- 证据等级：**B-**（自动评审 + 盲评一致性 97.0%/66 个判断；但任务数少）。
- 怎么运作：跑完后 Consolidation Agent（Codex + GPT-5.5）把发现整合成约 8,000 字研究报告；每个 run 独立调用 3 次生成 3 份报告，每份由 GPT-5.5 评审 3 次 → 9 个分。Rediscovery 任务把 oracle 论文主要发现拆成约 10 个 sub-discovery，报告须"实质相似 + 有证据"才算恢复；6 份输出的盲评与自动评审在 64/66 个判断上一致。
- 报告的数字：Station 62.7±2.8 vs Codex Multiagent-v2 15.4±2.4 vs AI Scientist-v2 14.4–20.6；三任务分别 75.8/70.4/41.9；tick 100 时已有 61.2。
- 边界：oracle 任务的 ground truth 是论文；exploratory 任务无 oracle，靠人工筛。
- 解决：开放任务没有单一分数时"输出什么"的问题。
- 代价：3×3 评审成本；rubric 设计是人工。
- 启示：**[采纳]** 把最终输出定义成"可被外部审读的报告"而非"最高分算法" [E-推断]；**[注意]** 自动评审 + 人工校准是弱人类对照，不是人类基线。
- 最小验证：报告长度 2k/8k/16k 对恢复率的影响；自动评审 vs 盲评的偏差方向。

### 3.4 结果与结论边界（含原文 Limitations）
- 5 个任务：3 个 rediscovery（ICLR oral 论文，扣住结论、禁网、3 seeds）+ 2 个 exploratory（subliminal learning、VLM hallucination，各 1 run）；6 agents（3 Gemini 3.1 Pro / 1 GPT-5.5 / 2 Claude Opus 4.8）× 300 tick。
- exploratory 上复现了 concurrent work（inverted-U、leading singular modes、末两层 MLP 输出 ×0.5），其中"只训练 early layers 可修复 rank-128 失效"作者称为 novel。
- 边界：① 模型知识截止 2025-01 至 2026-01，最早 oracle 论文 2025-04，**不能排除训练暴露**（但基线同样差，且要求给出证据）；② 明确"**不把增益归因于去中心化**"（基线模型组成与流程也不同）；③ 主要评的是 rediscovery，不是科学价值；④ 共 50 个 run、3,400+ 小时、760M output tokens；⑤ **75% 的 24 个非重叠 proposal 被 oracle 作者评 1–2/5**（判断错位仍是主要限制）。
- **人类对照的性质**：没有把人类研究者作为基线；人类只出现在两处——6 份输出的盲评一致性（66 个判断）与 oracle 作者给 24 个 proposal 打分。这是弱对照，不是人机对比。

## 4. 跨篇必答问题

### 4.1 「如何存储和完备垫脚石？难道要层层嵌套吗？」
- 两篇都答"扁平 + 类型 + 链接"，没有嵌套。Cogentic：Record（按方向聚合的尝试 + 失败理由）+ Ledger（自包含引理，隔离复验，含"已排除"死路）；单位=引理，准入=复验，链接=方向与尝试。Station：Archive（经评审、可引用的论文；125 篇/923 链接）；单位=论文，准入=评审 ≥6，链接=引用；另加 lineage 私笔记（沿族谱一维继承）。
- "完备"不是覆盖所有路径，而是**失败也留痕**：Cogentic 记死路，Station 保留 199 次拒稿与 revision。两者都没解决"太纠缠、无法孤立复验的中间成果"——这是 Ledger 类型的天花板 [E-推断]。
- 能否合流：可以，作为两种对象共存——可复验断言（ledger 型）+ 可阅读叙事（paper 型）。前提是共享来源/条件/证据字段，并把"已验证"与"已发表"写成两种状态，不用同一评分混算 [E-推断]。
- 代价：ledger 每轮多一次抽取+复验，单元小、成本低、类型窄；archive 评审贵、延迟高、能承载解释与障碍，但会压掉非常规结果。取决于下一轮要用"断言"还是"理解"。

### 4.2 「汇报有效成果如何保留多样性？和延迟授粉是否矛盾？」
- 原文事实：① Cogentic 每轮 Prover 互不通信，简报独立生成（不同读法），但所有 Prover 共享 literature survey 与 verified ledger（共享事实），且简报会带"下一步建议"（路线级信息）；原文**没有测量**多样性是否保留。② Station 的共同知识是 Archive，但它用三种与共享正交的结构保留差异：异构模型族、lineage 私笔记、生命早期隔离期（40/20 tick）；全 Claude 消融失败（3/3 未达 594），作者解读为跨模型族协作重要，但混淆了模型能力。③ 开放科学版的 Supervisor 明确"防止重复工作"，说明共享不只是灵感，也是去重机制。
- 判断：**不矛盾，但"汇报成果"本身是汇聚力，必须配一个反汇聚结构**。延迟授粉（延迟共享方法与表述）与保留多样性同向；真正的矛盾在"延迟共享"与"早期去重/纠错"之间：越晚共享，重复越贵。Station 的解法是只隔离公共知识、保留谱系与任务事实；Cogentic 的解法是共享事实（ledger）但隔离草稿。
- 用户若把"汇报有效成果"定义为"只报事实与证据、不报路线建议"，原文支持把"事实/证据"与"建议/品味"分开（但 Cogentic 简报确实带建议，所以这是 [E-推断] 改造，不是原文结论）。
- 可测量：路线相似度（问题表述/方法标签）、重复实验率、sub-discovery 恢复分布、pivot 率；两篇都没有把这些作为多样性指标系统报告。

### 4.3 「完全去中心化」到「一般去中心化」的谱系
- 用四个轴看（[E-推断]，每轴有原文依据）：① **方向选择**：Station 去中心（agent 自主提案、自选房间与动作，无中央派单）；Cogentic 中心（orchestrator 分配方向与席位）。② **质量门禁**：两者都中心（Station：reviewer ≥6 + Lean；Cogentic：双验证 + auditor + comparator + final audit）。③ **资源分配**：Station 半去中心（agent 自选，但 tick/寿命/评测前沿间接调节，stagnation 与 multistart 是系统级中央干预）；Cogentic 中心（orchestrator + advisor）。两版 Station 另设 Supervisor（v1 随机任命、离任后空 200 tick；开放科学版常设），名义上只督导不选方向，但通过拒绝 pivot 与审批 proposal 间接影响方向。④ **知识准入**：两者都中心（评审 / 复验 + auditor）。
- 结论：**Station 只在"方向与执行"上去中心，其余三轴都是中心化；开放科学版的 Supervisor 契约让它更中心**。准确说法是"方向去中心 + 质量/知识中心 + 资源半中心"，"完全去中心化"不成立。
- 失败模式：Station（去中心侧）——重复投入、attractor trap、路灯效应、判断错位、知识吸收不足（in-context learning 限制）、run 间高方差；Cogentic（中心侧）——每稿单验证器（无多数票）、单点调度、方向分配依赖 orchestrator 但禁止其有数学意见（责任与权限错位）、无失败案例、成本不透明。
- 对用户谱系：不要问"要不要去中心"，要问"四个轴各自中心还是去中心、跨轴不一致时靠什么补偿" [E-推断]。

### 4.4 「探索退化 / 路灯效应 / 过早换向」的精确定义
- **重要更正**：三篇原文都没有"探索退化（exploration degeneracy）"这个概念术语（v1 里出现的 degenerate 是数学上的"非退化"，与探索无关），它是中文综述/笔记的概括词。原文有的是三个可测现象：
  1. **路灯效应（streetlight effect）**：开放科学版 §1 定义——没有客观标准时，agent 会挑容易研究的问题并论证其重要，因为"容易"优先于"科学价值"（引 fingerman2002 / battaglia2015 / demirdjian2005）。测量=按子发现类别看恢复率（probing 99.1% vs intervention 60.5%；sequence-level 100% vs functional 18.5%；linear 60.5% vs nonlinear 7.4%），以及 24 个 proposal 被评 1–2/5 占 75%。最严重的任务是 temporal RNN（41.9%）。
  2. **过早换向（premature pivot）**：原文没有形式定义，操作性测量是"研究项目时长"= agent 在同一方向上停留的 tick 数（从首次实验提交到 pivot/离开/tick 300）；67.0 vs 55.5 tick。数学版里只是定性观察（Gemini 遇 peer feedback 容易改向）。
  3. **判断错位（judgment misalignment）**：§1 定义——主观判断与人类研究者不一致的风险；测量=24 个 proposal 的人工评分 + 恢复率离 100% 的差距。
- 若"探索退化"指 ablated Station 的持续性下降，原文支持的只是"去掉两个机制后恢复率与项目时长下降"，不是"探索能力整体退化"这一判断。

## 5. 数字速查（Lead 可直接引用）

| 数字 | 出处 |
|---|---|
| O(100) / O(1000) 次模型调用（多数 / 最难） | Cogentic §1 |
| 5 项专家验证结果；无消融 | Cogentic §3、Table 1 |
| 12+2 问题，5 项相对文献新结果 | Station-数学版 §3 |
| 125 篇论文、923 链接、199 次拒稿 | meta_analysis §2.2 |
| 21/28 结果用到早期论文；13/28 在 tick>1000 | meta_analysis §2.2；additional_analysis §2 |
| 46.4% 涉及跨模型族；19/28 多 agent | meta_analysis §2.3 |
| 3 seeds：Station 3/3 达 604，无 Archive / 全 Claude 均 0/3 | meta_analysis §2.5 |
| 达到 604 点需 25.6–26.8M output tokens | additional_analysis §3 |
| 62.7% vs 15.4% vs 14.4–20.6% 恢复率 | 开放科学版 §5、Table 3 |
| 75.8→57.9；67.0→55.5；71.7%/92 次；75% proposal 得 1–2 分 | 开放科学版 §5.1、§5.2、附录 D |
| 50 runs / 3,400+ 小时 / 760M output tokens | 开放科学版 Limitations |

## 6. 本节最可靠的 3 条结论
1. **[B-]** "扁平、带准入、可引用的中间成果库"被两个不同团队、不同任务独立采用：Cogentic 用 ledger（复验准入），Station 用 archive（评审准入）；Station 还报告了它对后续发现的作用（21/28 结果用到早期论文），Cogentic 有 5 个专家验证案例作旁证。
2. **[B-]** 开放/长程任务的主要失败不是"想不出"，而是"过早放弃 + 挑容易的"：开放科学版的联合消融（75.8→57.9）、行为统计（67.0→55.5 tick、71.7% 深化）一致指向"持续性"是可被制度改善的变量——但只能支持联合效果，不能拆到单机制。
3. **[B-]** 去中心化不是二值：两篇的真实配置都是"方向/执行去中心 + 质量门禁中心"；开放科学版原文明确不把增益归因于去中心化。任何"完全去中心化"的说法都与原文冲突。

## 7. 本节最不确定的 3 个判断
1. **[E-推断]** "独立简报 / 独立 Prover 能保留多样性"：原文只有设计描述，没有任何多样性测量；共享 ledger 与 literature 反而会压缩差异。用户的怀疑成立。
2. **[E-推断]** "60 tick 预承诺在开放研究里普遍有效"：只有一个任务、3 seeds、且与 Meta Reflection 联合消融；数学版的对照配置是"无承诺 + 每 25 tick 反思"，并非干净对照。
3. **[E-推断]** "角色越多越好 / 三职能不够"：两篇角色多但无逐角色消融；反过来，Cogentic 的 advisor 存在理由是"上下文不够"，不是"角色本身有价值"。角色数不是证据。

## 8. 与用户已有设计（V1/V2/V3、草案 0.1）可能冲突的点
1. **三职能（主持/执行/审阅）vs 两篇的 6–8 角色**：没有证据说三职能不够；但 Cogentic 的 advisor 说明"流程观察"与"调度"分开是因上下文，不是因角色数。冲突是表象，实质是"职责是否被同一上下文压垮" [E-推断]。
2. **草案"异步执行，空出席位即选择动作" vs 两篇都同步**：Station 用同一 tick 快照（新版只把观察准备并行化以减墙钟），Cogentic 用轮次屏障。异步省墙钟，但失去"同条件可比"与"同一时间线"；两篇都没有异步证据。这是真实冲突，建议列为待验证项。
3. **草案"主持只看成果卡，不读原始轨迹" vs Cogentic 的 advisor 必须读全运行日志**（虽压缩方式未报告）；Station 的 Supervisor 只看例会与提案。两种配置都存在，但没有"只看卡"的对照。建议把"主持读什么"写成可调参数。
4. **草案 60/25/15 预算比例**：两篇都没有这种比例——Cogentic 是方向配额 + 预算终止，Station 无预算分配（agent 自主）。该比例是 [E-推断]，不要写成文献依据。
5. **草案"只归档不续投无法形成垫脚石"**：原文补了另一半——失败记录本身有"防止重复"价值（Record），Station 的 holiday 还让 agent 重访被放弃的想法。建议把"续投"与"重访"分开。
6. **草案"组合需接口解释 + 产物 + 同条件比较"**：两篇都没有显式组合协议；Station 的跨模型协作是通过 Archive 自然发生的（46.4%），Cogentic 是 orchestrator 分方向 + Prover 读 ledger。用户的组合提示词是 [E-推断]，需自测。
7. **V3 的"杂交/合流是唯一工程可行路径"**：两篇证据都不支持"唯一"。Station 的可复现性分析显示同一 604 结果可由三条不同数学路径达到（lattice core / 根系统 / motif 变形），说明"路径多样"与"收敛"可以共存，但这不检验组合。V3 的措辞应降级为待证假设。
8. **"盲评"**：两篇都没有盲评——Cogentic 的 cross-draft verifier 看全部草稿；Station 的 reviewer 没有盲审设计（其上下文里含最近提交的论文）。用户若要"门禁/盲评"，需自建，不能引这两篇。
9. **用户 06 笔记的判断"主控不发表数学意见 ≠ 无偏"**：原文直接支持（红线只禁内容判断，不禁配额与终止）；且 Cogentic 未报告执行方式，属 D 级。
10. **草案"证据强度按领域处理（形式化证明/可审阅推导/可复现实验/案例观察/猜想）"**：与两篇一致（Cogentic 自然语言 + 专家；Station Lean + 实验 + 评审），是少数与原文相容的设计。

## 9. 任务没要求、但可能重要的发现
1. **两种"验证经济学"**：Cogentic 赌"自然语言 + 专家最终核验"，Station 赌"可执行实验 + Lean + 评审"。前者成本被隐藏，后者可计量。用户若要"可验证"，得先选验证经济学。
2. **Cogentic 的偏好入口不在调度器** [E-推断]："no math opinion" 只约束 advisor/orchestrator；真正注入偏好的是 Summarizer（写建议）与 Literature Reviewer（选材料）。这两处原文没有任何约束。
3. **继承的单位应该是"断言/构造"而不是"路径"**：两篇 Station 都出现"同一结果、不同路径"（604 三路径；Book Ramsey 三族）。用户草案的成果卡若绑定"路线"，会把可复用的东西绑死在路径上。
4. **裁判模型与执行模型分离**：开放科学版 6 个 agent 只有 1 个 GPT，但 Supervisor 与 Meta Reflection 都用 GPT-5.5。两篇都没做"裁判换模型"消融，但这是一个现成可测变量。
5. **门禁是高频事件**：v1 的 199 次拒稿、55/125 一次以上被拒，说明评审不是一次性闸门；用户草案若只写"最终门禁"，会低估评审调用量与延迟。
6. **验证器可靠性没有被测量**：两篇都没有注入错误草稿做校准，也没有报告漏检率。所以"对抗验证"目前是设计声明（C/D），不是测量结果。
