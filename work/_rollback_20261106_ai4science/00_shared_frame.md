# V4 共享框架：对象字典、接口表、章节地图

> 用途：六名 teammate 的共同起点。对象名、接口名、状态名以本文为准；发现冲突先在自己的文件里标注「冲突」，不要擅自改名。
> 项目：长城 Agent V4 = AI for Science 超长程研究系统。只做架构设计，不写代码、不跑实验。

## 1. V4 一句话

四循环（Idea / Empirical / Trust / Meta）+ 三器官（Orchestrator / Scheduler / Judge）+ 两记忆（Public / Private）+ 一免疫（Reflection / RedTeam / Maintainer / Auditor）+ 一底座（State / Event / Worktree / Budget），外加科学对象与信念状态作为「研究的世界模型」、人机协作作为横切接口。

## 2. 四个循环（接口级定义）

| 循环 | 输入 | 核心动作 | 输出 |
|---|---|---|---|
| **Idea** | 研究目标、文献、失败清单、信念状态 | 问题生成、gap 识别、假设生成、辩论/锦标赛、研究提案 | 排序后的 ResearchProposal / GapCard |
| **Empirical** | 假设、实验条件、预算 | 实验设计、执行、观察、证据提取 | Experiment + Observation + Evidence |
| **Trust** | claim、草稿、实验记录 | 个体/跨稿验证、复验、评审、入库 | VerifiedClaim / LedgerEntry / ArchivePaper |
| **Meta** | 日志、过程指标、路线状态 | 元反思、品味校准、流程调整、红队 | ProcessChange / PivotPolicy / TastePolicy |

## 3. 六个纵向层

1. 使命层：TaskContract、Acceptance、DeliveryEnvelope；
2. 科学对象层：Question / Hypothesis / Experiment / Observation / Evidence / Claim / Explanation / Theory / Method / Artifact / Paper / Review / Program / BeliefState；
3. 发现循环层：Idea / Empirical / Theory（Theory 作为 Empirical 与 Trust 之间的解释环节）；
4. 控制层：Orchestrator / Scheduler / Judge；
5. 制度层：Record / Ledger / Archive / Lineage；
6. 运行时层：StateStore / EventLog / Worktree / Budget / ModelAdapter。

## 4. 对象字典（最小集合）

| 对象 | 一句话定义 | 关键字段 | 状态 |
|---|---|---|---|
| **Question** | 一个值得研究的问题 | id、问题陈述、范围、重要性、可解性、来源 | open / active / answered / abandoned |
| **Hypothesis** | 可检验的假设 | id、陈述、假设前提、预测、最近邻工作、新颖性 | draft / ranked / testing / supported / refuted |
| **Experiment** | 一次实验设计 | id、变量、对照、预算、成功/失败判据、停止条件 | designed / running / done / failed |
| **Observation** | 一次实验的原始观察 | id、条件、数值/日志、不确定性 | raw / processed |
| **Evidence** | 观察与假设/claim 的链接 | id、方向（支持/反驳）、强度、条件、来源 | weak / moderate / strong |
| **Claim** | 一条可判定陈述 | id、陈述、条件、证据、状态、provenance | conjecture / supported / verified / refuted |
| **Explanation** | 为什么 claim 成立/机制 | id、机制、类比、统一范围、可检验预测 | draft / reviewed / accepted |
| **Theory** | claim + explanation 的有范围集合 | id、范围、核心 claim、解释、预测 | provisional / established / revised |
| **Method** | 可复用方法/工具/流程 | id、输入输出、适用条件、证据 | proposed / validated / deprecated |
| **Artifact** | 代码/数据/证明/构造 | id、路径、版本、校验、许可 | draft / frozen |
| **Paper** | 经过评审的综述/论文 | id、claims、evidence、citations、review | draft / under_review / accepted / rejected / retracted |
| **Review** | 对 paper/claim 的评审 | id、对象、维度、分数、理由、盲评标记 | open / resolved |
| **Program** | 长期研究纲领 | id、目标、开放问题、路线、taste、代际 | active / paused / archived |
| **BeliefState** | 当前世界模型 | claim 图、置信、矛盾、未决问题、版本 | versioned |

## 5. 接口表（producer → artifact → consumer）

| 产物 | 生产者 | 消费者 | 契约要点 |
|---|---|---|---|
| TaskContract | 人 / 契约官 | 所有 Agent | 六类标签；VERBATIM 不可改 |
| GapCard | Idea Loop | Orchestrator / Scheduler | 问题、最近邻、进展标准、最便宜测试 |
| ResearchProposal | Idea Loop | Orchestrator / Judge | 问题、假设、预算、预期信号、kill 条件 |
| ExperimentSpec | Empirical Loop | Scheduler / Worker | 变量、对照、预算、停止条件 |
| ObservationBundle | Worker | Empirical Loop | 条件、原始数据、不确定性 |
| EvidenceRecord | Empirical Loop | Trust Loop / BeliefState | 方向、强度、条件、来源 |
| ClaimCard | Empirical/Theory | Trust Loop | 陈述、条件、证据、状态 |
| LedgerEntry | Trust Loop | 全体 | 自包含、复验通过、可免证引用 |
| ArchivePaper | Trust Loop / Consolidator | 全体 + 人类 | 评审通过、可引用、带限制 |
| ReflectionRecord | Meta Loop | Orchestrator / Scheduler | 写回 JSON、变更、下一步 |
| ProcessChange | Meta Loop | Orchestrator / Judge | 只改流程参数，不改内容 |
| JudgeVerdict | Judge | Orchestrator / Scheduler | 有效性、质量向量、探索信用 |
| NodeBrief | Scheduler / 父节点 | Worker | 父 handoff + 约束 + 2–4 卡 + 契约摘要 |
| HandoffCard | 任意节点/代际 | 下一代 | 目标、成果、活跃路线、未决、失败、下一步、身份 |

## 6. 章节地图（六名 teammate 分章）

| 章 | 主题 | 负责人 | 输出 |
|---|---|---|---|
| 01 | 科学本体与信念状态 | science-ontology | `00_science-ontology_recon_preview.md` |
| 02 | 发现循环（Idea/Empirical/Theory） | discovery-loops | `00_discovery-loops_recon_preview.md` |
| 03 | 知识制度（档案/评审/复现/谱系/信用） | knowledge-institution | `00_knowledge-institution_recon_preview.md` |
| 04 | 控制与运行时（总控/调度/评判/worktree） | control-runtime | `00_control-runtime_recon_preview.md` |
| 05 | 元层与评估（元反思/品味/开放式评估/红队） | meta-taste-eval | `00_meta-taste-eval_recon_preview.md` |
| 06 | 人机协作与领域适配 | human-domain | `00_human-domain_recon_preview.md` |
| 主文档 | 综合 | Lead | `08_AI4Science_超长架构设计.md` |
| 实施计划 | 模块/接口/里程碑 | Lead + control-runtime | `09_AI4Science_架构实施计划.md` |
| 评审记录 | preview/交叉评审/签收 | Lead | `10_Teamwork_设计评审记录.md` |

## 7. 命名与证据规则

1. 对象名用英文单数、首字母大写：Question、Hypothesis、Experiment、Observation、Evidence、Claim、Explanation、Theory、Method、Artifact、Paper、Review、Program、BeliefState；
2. 状态名用小写 snake_case：conjecture / supported / verified / refuted / dormant / regrow 等；
3. 每个设计主张标 [A]/[B]/[C]/[D]/[E]；原文数字给章节/页码；未读到写「未核实」；
4. 只写自己的文件；不修改既有 00–07；不写代码、不跑实验；
5. 发现对象/接口冲突：先在自己的文件中标注「冲突：shared_frame 的 X 与 Y」，不要擅自改名。