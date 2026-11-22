# 长城 Agent V6-Up 工程知识库 (`agent_kb`) 总导航与设计红线总表（v3.0）

> **定位与阅读指南**：  
> 本目录是 **[`04` 顶层架构白皮书](../architecture/04_长城%20Agent%20V6-Up：面向长周期自主科学发现的多智能体系统架构白皮书（v3.0）.md)** 与 **[`09` 工程开发总说明书](../architecture/09长城%20Agent%20V6-Up（v3.0）零前提工程架构与系统开发总说明书.md)** 的子系统细化规范集，供系统架构师、中层开发团队与运行态 Prompt 构建者查阅。全套知识卡零历史前提、完全自包含，从第一性原理出发定义系统每一条边界。

---

## 一、知识库目录结构与模块路由矩阵

| 知识卡 | 核心主题 | 对应角色契约 / 工程模块 | 核心一手文献来源 |
| :--- | :--- | :--- | :--- |
| **[`01_拓扑与制度_一委三部扁平制衡与零偏见总线.md`](./01_拓扑与制度_一委三部扁平制衡与零偏见总线.md)** | 极薄无偏见事件总线（`ctx.agents.create()`）；**“3 个真相 + 2 个视图”**数据模型；**双隔离沙箱平权**（探索与盲审双开放执行工具）；全员 7 角色 Push/Pull/Write 矩阵；无状态高熟练度四把手术刀；Parse 0 六项表单与无人值守红灯续跑 | DSH 宿主事件总线、全部 7 个角色契约、`supervisory_committee.md` | • [`../architecture/手写project.md`](../architecture/手写project.md)<br>• [`Cogentic §2.1–2.4`](file:///D:/Documents/deepseek%20harness/论文研读/2609.40324_Cogentic_Multi-Agent_Orchestration_for_Automated_Proof_Discovery/2609.40324_Cogentic_中文综述.md#L150-L239)<br>• [`SLA 中文综述`](file:///D:/Documents/deepseek%20harness/论文研读/2610.07625_Stateless_Language_Agents_Scaling_Long-Horizon_Automated_Research/2610.07625_StatelessLanguageAgents_中文综述.md#L56-L85)<br>• [`AgentDiscover meta.md`](file:///D:/Documents/deepseek%20harness/论文研读/2610.05334_AgentDiscover_Autonomous_Discovery_with_Minimal_Search_Scaffolding/AgentDiscover/harness-instructions/meta.md#L99-L140) |
| **[`02_后勤与谱系_上下文时钟_一对一伴随_四级分诊与五车道复苏.md`](./02_后勤与谱系_上下文时钟_一对一伴随_四级分诊与五车道复苏.md)** | 自适应物理时钟 `W = min(500,000, 模型窗口)`、单节点伴随暂停续传（绝不跨代）与硬性跑满四幕生命周期（`0–37%` 独思 / `37%` 情报型元反思与三不给红线 / `37–70%` Pull / `70%` 探索者先立遗嘱再伴随单写与断线抢救）；`lineage_dead_ends` 真相表与 `<= 2200` 字定额滚动重压缩看板解耦；`question_order` + 分支级 `requires`；`mechanism_summary` 动态族谱与 `>=2 && >50%` 无豁免打散；`AWAITING_TRIAGE` 硬锁、四级分诊与五车道复苏 | 后勤工作部、`logistics_coordinator.md`、`lineage_companion.md`、`explorer.md` | • [`Station STAGNATION.md`](file:///D:/Documents/deepseek%20harness/论文研读/2608.23691_Autonomous_Mathematical_Discovery_in_an_Open-World_Multi-Agent_Environment/station/example/doc/STAGNATION.md#L1-L81)<br>• [`Station coder_manager.py`](file:///D:/Documents/deepseek%20harness/论文研读/2610.08927_Can_AI_Agents_Make_Open-Ended_Scientific_Discovery_Evidence_from_Station/station-open-reseach/station/eval_research/coder_manager.py#L1-L450)<br>• [`AgentDiscover tools_search.py`](file:///D:/Documents/deepseek%20harness/论文研读/2610.05334_AgentDiscover_Autonomous_Discovery_with_Minimal_Search_Scaffolding/AgentDiscover/agentdiscover/server/tools_search.py#L568-L608)<br>• [`OpenAI CDC Prompt`](file:///D:/Documents/deepseek%20harness/论文研读/OpenAI_Prompt_Used_for_A_Proof_of_the_Cycle_Double_Cover_Conjecture/OpenAI_圈双覆盖猜想Prompt_中文全译与深度解析.md#L80-L192) |
| **[`03_中央图书馆_三本账_两阶段物理盲审_Auditor二次打捞与依赖撤回.md`](./03_中央图书馆_三本账_两阶段物理盲审_Auditor二次打捞与依赖撤回.md)** | 外藏 `[R###]`（未复验外部摘要 + 无解查新核销）与内藏 `L3/L2` 物理分表；四类主张可核验送审准入；独立空白沙箱两阶段实测盲审；三态终判（`ACCEPT*` 含确证反例与障碍入 `L3` / `REVISE` 共用 `<=2` 轮返工 / `REFUTED` 入 `L2`）；`Auditor` 独立异会话打捞边界；默认 `MOTIVATING_REF` 非连坐传播；CDC 双段终局与两步联合核签 | 中央图书馆、`library_surveyor.md`、`library_verifier.md`、`supervisory_committee.md` | • [`Cogentic §2.2–2.5`](file:///D:/Documents/deepseek%20harness/论文研读/2609.40324_Cogentic_Multi-Agent_Orchestration_for_Automated_Proof_Discovery/2609.40324_Cogentic_中文综述.md#L167-L233)<br>• [`Station v2 App D`](file:///D:/Documents/deepseek%20harness/论文研读/2610.08927_Can_AI_Agents_Make_Open-Ended_Scientific_Discovery_Evidence_from_Station/2610.08927_Station_OpenEndedDiscovery_中文翻译.md#L584-L603)<br>• [`GPT-Rosalind 解析`](file:///D:/Documents/deepseek%20harness/论文研读/Sun2026_Distributed_AI_Agents_Enable_Comprehensive_Discovery_of_Biological_Insights_at_Scale/Sun2026_GPT-Rosalind_DistributedAgents_官方仓库框架与工程架构深度解析.md#L46-L115)<br>• [`OpenAI CDC Prompt`](file:///D:/Documents/deepseek%20harness/论文研读/OpenAI_Prompt_Used_for_A_Proof_of_the_Cycle_Double_Cover_Conjecture/OpenAI_圈双覆盖猜想Prompt_中文全译与深度解析.md#L162-L191) |
| **[`04_工造司与评测_共享探针_可插拔验证钩子与RQGM受控纪元演化.md`](./04_工造司与评测_共享探针_可插拔验证钩子与RQGM受控纪元演化.md)** | 工造司【科研仪器科】定位与 Stage 1 统一核查；统一 `Instrument` 抽象与 `evaluate(artifact, spec, tier)` 协议；同一代码三档调用（`probe / official / heavy`）；四态物理隔离（判不了绝不判负）与 3 次连续报错熔断；校准集（自声明预期）驱动注册与升级；版本域可比性与诚实重评；`resolve_works_ticket` 工单闭环与 `SKILL_LEDGER.json` | 工造司、`works_engineer.md`、`evaluators/isolated_runner.py`、`skills/SKILL_LEDGER.json` | • [`RQGM 中文翻译`](file:///D:/Documents/deepseek%20harness/论文研读/2606.26294_The_Red_Queen_Godel_Machine_Co-Evolving_Agents_and_Their_Evaluators/2606.26294_RedQueenGodelMachine_中文翻译.md#L76-L109)<br>• [`Audit the Scaffold`](file:///D:/Documents/deepseek%20harness/论文研读/2609.34924_Audit_the_Scaffold_Not_the_Checkpoint_A_Stationarity_Dichotomy_for_Recursive_Self-Improvement_in_Agentic_Coding/2609.34924_AuditTheScaffold_中文综述.md#L312-L329)<br>• [`The Tasteful Agent`](file:///D:/Documents/deepseek%20harness/论文研读/2609.25804_The_Tasteful_Agent_Measuring_and_Improving_Taste_in_Long-Horizon_Tasks/2609.25804_TastefulAgent_中文综述.md#L132-L210) |
| **[`05_原论文级Prompt武器库与五大角色完整模板直抄库.md`](./05_原论文级Prompt武器库与五大角色完整模板直抄库.md)** | 全系统 **32 个窄工具**精确入参签名总表与 `next_step_guidance` 路由表；11 类元反思全表、29 条夜科学启发题原文、`Station App D` 盲审 6 步法则、`SLA` 6 套声明式准则，以及 **7 份可直接复制落盘至 `core_python/agents/*.md` 的完整角色模板** | 全部 7 个角色运行态 Prompt 与 MCP 工具接口 | • [`holiday_prompts.yaml`](file:///D:/Documents/deepseek%20harness/论文研读/2608.23691_Autonomous_Mathematical_Discovery_in_an_Open-World_Multi-Agent_Environment/station/example/station/default/holiday_prompts.yaml#L1-L66)<br>• [`SLA Appendix E`](file:///D:/Documents/deepseek%20harness/论文研读/2610.07625_Stateless_Language_Agents_Scaling_Long-Horizon_Automated_Research/sections/10_appendix_prompts.md#L1-L274)<br>• [`AgentDiscover instructions.md`](file:///D:/Documents/deepseek%20harness/论文研读/2610.05334_AgentDiscover_Autonomous_Discovery_with_Minimal_Search_Scaffolding/AgentDiscover/harness-instructions/instructions.md#L1-L160) |
| **[`06_十三篇核心文献工程速查卡与本机源码行号索引.md`](./06_十三篇核心文献工程速查卡与本机源码行号索引.md)** | 核心思想本体、工程加固件与经典边界文献的本机真实路径与精确行号对照表 | 理论溯源、架构审阅与防遗漏核查 | • [`论文研读/README.md`](file:///D:/Documents/deepseek%20harness/论文研读/README.md) |

---

## 二、全系统二十条工程设计红线（反模式自检清单）

研发与代码审阅过程中，凡触犯下列任一条反模式即直接判定不合格：

### A. 拓扑、权限与沙箱安全红线
1. **常驻官僚总管与满地公文反模式**：禁止让调度者或监察委跨周期常驻聊天；禁止在工作区磁盘生成任何审批、汇报或审计类 `.md` 文件，一切流转状态只落 SQLite。
2. **因噎废食阉割验证工具或误拦公开题面反模式**：禁止以防泄密为名将 `library_verifier` 裁减为 0 执行工具，也禁止把工作区公开题面与《补充裁决文档》挡在探索/盲审沙箱之外；正确做法是建立双向隔离沙箱（开放公开 `inputs/` 只读进内部，严防内部读取工作区外 DB/隐藏集/`evaluators/`/他脉），沙箱内大方开放平台 Shell 与计算工具。
3. **跨门派隐私泄漏与明文手稿落盘反模式**：禁止把未审手稿写入共享目录明文文件，禁止 B 学派读取 A 学派私有谱系 DAG；跨门派只能通过中央图书馆交流。
4. **越权混用多合一巨型工具或无闭环工单反模式**：每个角色严格挂载 3–6 个单一职责窄工具，并在 Schema 层清晰暴露全部枚举与长度边界，禁止把 9 参数五合一工具塞给模型；所有治理队列必须具备显式闭环接口（如 `resolve_works_ticket`、`publish_external_literature_card(outcome="UNAVAILABLE_REPORT")`）与**单条待办项连续 2 次无客观进展熔断器**。
5. **脆弱正则猜路径、静默模型降级与实时广播串扰反模式**：分支 Worktree 与物理快照路径一律在数据库明文登记，文件工具统一基于 `realpathSync()` 做路径校验（放行 `dsh-spill-*` 且盘符正则带左边界）；启动前未解析到权威模型绑定必须硬拒启（`MISSING_MODEL_BINDING`）；严禁向在线会话池广播实时干预消息或拼接冷启动便签条，澄清统一走版本化 `spec_revision` 公开裁决文档（同步摘要入 DB 供零工具角色可见，送审手稿按绑定口径盲审）+ 极简 `abort_node`。

### B. 仪器、评测与版本演化红线
6. **判不了就判 0 分反模式**：任何 `INSTRUMENT_ERROR` 或 `INFRA_ERROR` 绝对禁止映射为 `FAIL`、`0` 分或“算法无改进”，不得扣探索者修补配额、不得增停滞计数、不得写入永久幂等缓存。
7. **特定学科/竞赛规则硬编码进通用底座反模式**：通用容器严禁硬编码“每题必建数值零号基线”“全局 `<5%` 误差门禁”“全局拦截全零/常数解”“按固定题名扫描 AST 禁词”等特例逻辑，所有学科判据必须下放至课题仪器插件。
8. **自测与正式评测两张皮反模式**：禁止要求探索者用一套 CLI/stdout 契约本地自测、正式沙箱又跑另一套 `run()` 契约；同一份仪器代码必须原生提供 `probe / official / heavy` 三档调用。
9. **修 Bug 被“平局保在位”或跨样本分数卡死反模式**：工程缺陷修复与防作弊加固只需将复现用例写入独立校准集并 100% 通过即可升版，禁止强求修 Bug 补丁在旧指标上刷出更高分，禁止拿不同样本量分数跨版本硬比。
10. **在只读状态轮询中动态运行重型脚本反模式**：仪表盘与审计快照接口必须纯查 SQLite 持久化字段（`< 50 ms`），严禁在轮询中导入执行候选或仪器 Python 代码。

### C. 时钟、谱系与调度多样性红线
11. **开场行政必读税与过早锁死纯推导反模式**：探索者 `0–37%` 仅凭轻量 Push 看板与外藏 `[R###]` 启动，禁止强读全局行政文档；`37%` 元反思与 `70%` 正式 DAG 交接严禁强卡数值 `eval_count >= 1`，确保纯解析推导与构造反例畅通无阻。
12. **延迟解锁、越界代打与跳过亲笔遗嘱反模式**：`37%` 元反思允许伴随扫目录给盲区诊断与最多 2 条编号指针，但严禁越界代定方案或写代码，结束当场置位 `first_reflection_unlocked = 1`；`70%` 必先给探索者最后一轮只读回合亲笔总结并立《科研遗嘱》，退场后再由伴随独占单写 `submit_node_handoff`（伴随仅单节点内暂停续传，严禁跨代常驻）；`AWAITING_TRIAGE` 完成分诊并刷新快照前严禁抢跑启动同分支下代。
13. **硬切片截断或简单累加拼接看板反模式**：禁止使用 `[:2000]` 截断句子，也禁止把看板当作“旧看板 + 新手记”无限拼接；看板必须按 `Rewrite_<=2200` 定额滚动重压缩（段 5 整体替换、段 3 覆盖刷新、段 2 合并覆写、段 4 Top-K 淘汰下沉），历代全量死胡同永久沉淀在 `lineage_dead_ends` 只追加表。
14. **题级依赖并集死锁与默认全军连坐反模式**：禁止把同一子题下不同学派的前置依赖取并集锁死整题（仅允许分支级 `requires` 锁单分支）；声明引用边默认记为 `MOTIVATING_REF`，仅经 Stage 2 盲审显式认证为 `REQUIRED_PREMISE` 才传播撤回。
15. **高并发聚拢设高产豁免后门反模式**：同题任一学派一旦满足 `branch_count_in_family >= 2 && share > 0.50`，必须无豁免刚性正交分流；严禁跨分支广播当前最高分假说诱发盲从。

### D. 盲审、图书馆与终局交付红线
16. **单一布尔 `passed=1` 垄断送审反模式**：送审准入只核对主张形态与可核验载体是否匹配（数值、形式化证书、反例对象+校验脚本、自包含解析推导四轨并行）。
17. **正反例混装垃圾堆与打捞抢断返工反模式**：通过盲审的严格反例与障碍证明带标签入 `L3`；论证不足但方向未否定的手稿判 `REVISE` 退回原分支返工（共用 `<= 2` 轮，期间严禁 `Auditor` 插手）；工程代码崩溃只入本脉 `lineage_dead_ends` 或工单，绝不污染图书馆 `L2`。
18. **形式主义日志替代实质学术核验反模式**：`FACT_LOG(READ)` 在 Stage 2 仅作参考展示，严禁因作者未调读卡工具引用常规公理而机械拒稿或缩窄结论；外藏 `[R###]` 标定为未复验先验摘要，须由作者与盲审实证核查。
19. **未满最短投入时间提前交差或拿未审稿充数反模式**：未过 Parse 0 设定的 `min_commitment_window` 禁止 Agent 自行申请部分交付（仅人类显式紧急叫停可即时导出）；终局交付正文严禁混入任何未通过两阶段盲审的草稿。
20. **无人值守遇口径歧义整夜停摆或终稿夸大结题反模式**：无人值守期间遇根本题意歧义须亮 `ALERT_AMBIGUOUS_SPEC` 红灯并按原已签口径继续推进；五件套导出后处于 `DELIVERY_EXPORTED`，必须经盲审官与监察委联合核验正文未夸大 `L3` 成立边界后方升为 `CLOSED_VERIFIED`。
