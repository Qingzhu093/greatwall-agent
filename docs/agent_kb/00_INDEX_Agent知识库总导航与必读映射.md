# 长城 Agent V6-Up 前沿工程知识库 (`agent_kb`) 总导航与必读映射（v3.0 去过拟合通用科研版）

> **使用声明（专供架构师、中层开发、Prompt 编写与运行态 Agent 阅读）**：  
> 本知识库是**长城 Agent V6-Up（面向开源 `DeepSeek Harness / DSH` 原生底座）** 的**高信噪比工程设计说明书与原论文机制武器库**。  
> 经过第四轮实测停摆复盘（[`../round4_audit/01_交顶层设计者_原文对照与架构讨论稿_对齐版.md`](../round4_audit/01_交顶层设计者_原文对照与架构讨论稿_对齐版.md)、[`03_顶层设计深度审阅_原文溯源与决策对照_对齐版.md`](../round4_audit/03_顶层设计深度审阅_原文溯源与决策对照_对齐版.md)、[`第六轮审阅（针对第四轮测试）.md`](../round4_audit/第六轮审阅（针对第四轮测试）.md)）与三轮收敛定音，V6-Up **v3.0** 全面剥离针对单一建模竞赛（如 CUMCM B 题）的特例硬编码，确立五大刚性不变量与四大内核重构：
> 1. **“工造司”降维回归【科研仪器科】**：唯一对象为统一 `evaluate(artifact, spec, tier)` 三档运行（`probe / official / heavy`）与四态隔离（`OK / CANDIDATE_ERROR / INSTRUMENT_ERROR / INFRA_ERROR`）的可插拔仪器；**判不了绝不准判负**；校准集（金/毒样本）回归驱动升级，废除平局保在位与计数回退，只在同版本口径内比对。
> 2. **隔离靠沙箱，绝不靠砍工具（沙箱平权）**：OS DACL + 独立盲审沙箱物理隔绝敏感数据，不仅 `explorer` 保留 `pwsh/bash` 自主试探自由，**`library_verifier` 亦彻底解除 `0` 原生工具阉割，在隔离盲审沙箱内开放 `pwsh/bash`/SymPy/Lean 4 实测跑证权限**。
> 3. **“3 真相 + 2 视图” + 极简 `0–37%` 设计**：`0–37%` 保持极简只查外藏 `[R###]` 与本工作区试探，**废除 `eval_count >= 1` 阻塞门槛**，经 `37%` 元反思（必查第 7 类路灯效应）提神校准后才解锁公共内藏 `L3/L2` 与深层 DAG；底层 `lineage_dead_ends` 只追加表承担“历代全量只增不忘”，看板保留 `<= 2200` 字增量合成。
> 4. **三态审稿、分支级调度与无豁免高并发分流**：审稿裁决分为 `ACCEPT/ACCEPT_NARROWED`（入 `L3`，含确证反例与障碍证明）、`REVISE`（退回返工 `<= 2` 轮，禁打捞插手）、`REFUTED`（入 `L2`）；工程报错踢出图书馆；依赖收束为 `question_order` + 分支级 `requires`（严禁跨分支取并集）；同题同一学派下聚拢多个分支且占比 `> 50%` 时**无豁免刚性打散**；Parse 0 六项表单 + 无人值守遇口径歧义按原口径续跑并亮 **`ALERT_AMBIGUOUS_SPEC` 红灯**等人裁决；CDC 双段式终局（最短投入时间锁定 + 诚实部分交付）。
>
> **历史归档**：v2.2 原稿已完整归档于 [`../../archive/第四轮审阅后_v2.2顶层设计备份_20261121/`](../../archive/第四轮审阅后_v2.2顶层设计备份_20261121/)；二轮测试前原稿归档于 [`../../archive/第二轮测试前_顶层设计原稿备份_20261119/`](../../archive/第二轮测试前_顶层设计原稿备份_20261119/)。

---

## 一、知识库目录结构与模块路由矩阵

| 知识卡 | 核心主题 | 服务的系统模块 / 7 大角色契约 | 必查的一手论文与本地审计位置 |
| :--- | :--- | :--- | :--- |
| **[`01_拓扑与制度_一委三部扁平制衡与零偏见总线.md`](./01_拓扑与制度_一委三部扁平制衡与零偏见总线.md)** | 极薄无偏见事件总线（`ctx.agents.create()`）；**“3 个真相 + 2 个视图”与沙箱平权拓扑**；全员 7 角色“谁 Push / Pull / Write 什么”与原生沙箱权限总表；无状态高熟练度四把手术刀；**无人值守续跑亮红灯准则** | 整体架构、DSH 宿主事件循环、全员 7 角色契约、`supervisory_committee.md` | • [`../architecture/手写project.md`](../architecture/手写project.md)<br>• [`2609.40324_Cogentic_中文综述.md`](file:///D:/Documents/deepseek%20harness/论文研读/2609.40324_Cogentic_Multi-Agent_Orchestration_for_Automated_Proof_Discovery/2609.40324_Cogentic_中文综述.md#L150-L239) & [`main.tex`](file:///D:/Documents/deepseek%20harness/论文研读/2609.40324_Cogentic_Multi-Agent_Orchestration_for_Automated_Proof_Discovery/source/main.tex#L209-L251)<br>• [`AgentDiscover meta.md`](file:///D:/Documents/deepseek%20harness/论文研读/2610.05334_AgentDiscover_Autonomous_Discovery_with_Minimal_Search_Scaffolding/AgentDiscover/harness-instructions/meta.md#L99-L140) & [`exposure.py`](file:///D:/Documents/deepseek%20harness/论文研读/2610.05334_AgentDiscover_Autonomous_Discovery_with_Minimal_Search_Scaffolding/AgentDiscover/agentdiscover/orchestrator/exposure.py#L1-L106)<br>• [`2604.18005_DiversityCollapse_中文综述.md`](file:///D:/Documents/deepseek%20harness/论文研读/2604.18005_Diversity_Collapse_in_Multi-Agent_LLM_Systems_Structural_Coupling_and_Collective_Failure_in_Open-Ended_Idea_Generation/2604.18005_DiversityCollapse_中文综述.md) |
| **[`02_后勤与谱系_上下文时钟_一对一伴随_四级分诊与五车道复苏.md`](./02_后勤与谱系_上下文时钟_一对一伴随_四级分诊与五车道复苏.md)** | `pressure_tokens / 500,000` 纯净时钟（**废除 `eval_count >= 1` 锁**）；**维持 `0–37%` 极简设计 -> `37%` 元反思解锁 -> `37–70%` 开放 Pull**；`lineage_dead_ends` 只追加真相表与 `<= 2200` 字增量看板解耦；**分支级 `requires`（禁跨分支并集）**；**学派 `branch_count_in_family >= 2 && share > 0.50` 无豁免刚性打散**；`mechanism_summary` 思想归类 | 后勤工作部、`logistics_coordinator.md`、`lineage_companion.md`、`explorer.md` | • [`station-open-reseach/station/sync/parallel_runner.py`](file:///D:/Documents/deepseek%20harness/论文研读/2610.08927_Can_AI_Agents_Make_Open-Ended_Scientific_Discovery_Evidence_from_Station/station-open-reseach/station/sync/parallel_runner.py#L1-L328) & [`coder_manager.py`](file:///D:/Documents/deepseek%20harness/论文研读/2610.08927_Can_AI_Agents_Make_Open-Ended_Scientific_Discovery_Evidence_from_Station/station-open-reseach/station/eval_research/coder_manager.py#L1-L450)<br>• [`STAGNATION.md`](file:///D:/Documents/deepseek%20harness/论文研读/2608.23691_Autonomous_Mathematical_Discovery_in_an_Open-World_Multi-Agent_Environment/station/example/doc/STAGNATION.md#L1-L81)<br>• [`tools_search.py#L568-L608`](file:///D:/Documents/deepseek%20harness/论文研读/2610.05334_AgentDiscover_Autonomous_Discovery_with_Minimal_Search_Scaffolding/AgentDiscover/agentdiscover/server/tools_search.py#L568-L608)<br>• [`OpenAI_圈双覆盖猜想Prompt_中文全译与深度解析.md`](file:///D:/Documents/deepseek%20harness/论文研读/OpenAI_Prompt_Used_for_A_Proof_of_the_Cycle_Double_Cover_Conjecture/OpenAI_圈双覆盖猜想Prompt_中文全译与深度解析.md#L80-L192) |
| **[`03_中央图书馆_三本账_两阶段物理盲审_Auditor二次打捞与依赖撤回.md`](./03_中央图书馆_三本账_两阶段物理盲审_Auditor二次打捞与依赖撤回.md)** | 外藏 `[R###]`（标注未经复验外部摘要）vs 内藏 `L3/L2`；**盲审沙箱工具平权（开放 `pwsh`/Python/SymPy/Lean 4 跑证，物理隔绝 DB/Worktree/B 栏）**；**三态审稿（`ACCEPT/ACCEPT_NARROWED / REVISE(<=2轮返工) / REFUTED`）**；**确证反例与障碍证明带类型标签入 `L3`**；工程报错踢出图书馆；取消缺 `READ` 强制降级；**默认 `MOTIVATING_REF`**；**CDC 双段式终局（最短投入时间 + 诚实部分交付）** | 中央图书馆、`library_surveyor.md`、`library_verifier.md`、`supervisory_committee.md` | • [`2609.40324_Cogentic_中文综述.md`](file:///D:/Documents/deepseek%20harness/论文研读/2609.40324_Cogentic_Multi-Agent_Orchestration_for_Automated_Proof_Discovery/2609.40324_Cogentic_中文综述.md#L167-L233)<br>• [`2610.08927_Station_OpenEndedDiscovery_中文翻译.md`](file:///D:/Documents/deepseek%20harness/论文研读/2610.08927_Can_AI_Agents_Make_Open-Ended_Scientific_Discovery_Evidence_from_Station/2610.08927_Station_OpenEndedDiscovery_中文翻译.md#L584-L603)<br>• [`GPT-Rosalind 官方仓库解析`](file:///D:/Documents/deepseek%20harness/论文研读/Sun2026_Distributed_AI_Agents_Enable_Comprehensive_Discovery_of_Biological_Insights_at_Scale/Sun2026_GPT-Rosalind_DistributedAgents_官方仓库框架与工程架构深度解析.md#L46-L115)<br>• [`OpenAI CDC Prompt#L162-L191`](file:///D:/Documents/deepseek%20harness/论文研读/OpenAI_Prompt_Used_for_A_Proof_of_the_Cycle_Double_Cover_Conjecture/OpenAI_圈双覆盖猜想Prompt_中文全译与深度解析.md#L162-L191) |
| **[`04_工造司与评测_共享探针_可插拔验证钩子与RQGM受控纪元演化.md`](./04_工造司与评测_共享探针_可插拔验证钩子与RQGM受控纪元演化.md)** | **工造司“科研仪器科”重构**：唯一 `evaluate(artifact, spec, tier)` 接口（`probe / official / heavy` 三档同码）+ **四态硬隔离（`OK / CANDIDATE_ERROR / INSTRUMENT_ERROR / INFRA_ERROR`，判不了绝不判负）**；**校准集（金/毒样本）回归驱动升级**（废除平局保在位与计数回退、版本号内可比、缺字段标 `INCOMPATIBLE`）；废除每题强建基线、`<5%` 硬门禁、全零拦截与 `Q3` 禁 `second_pass`；保留 `pwsh` 自由试探与可观测性优先 | 工造司、`works_engineer.md`、`evaluators/isolated_runner.py`、`skills/SKILL_LEDGER.json` | • [`2606.26294_RedQueenGodelMachine_中文翻译.md`](file:///D:/Documents/deepseek%20harness/论文研读/2606.26294_The_Red_Queen_Godel_Machine_Co-Evolving_Agents_and_Their_Evaluators/2606.26294_RedQueenGodelMachine_中文翻译.md#L76-L109)<br>• [`2609.34924_AuditTheScaffold_中文综述.md`](file:///D:/Documents/deepseek%20harness/论文研读/2609.34924_Audit_the_Scaffold_Not_the_Checkpoint_A_Stationarity_Dichotomy_for_Recursive_Self-Improvement_in_Agentic_Coding/2609.34924_AuditTheScaffold_中文综述.md#L312-L329)<br>• [`2610.05334_AgentDiscover/evaluator.py`](file:///D:/Documents/deepseek%20harness/论文研读/2610.05334_AgentDiscover_Autonomous_Discovery_with_Minimal_Search_Scaffolding/AgentDiscover/agentdiscover/server/evaluator.py#L197-L267) & [`tools_search.py#L250-L380`](file:///D:/Documents/deepseek%20harness/论文研读/2610.05334_AgentDiscover_Autonomous_Discovery_with_Minimal_Search_Scaffolding/AgentDiscover/agentdiscover/server/tools_search.py#L250-L380) |
| **[`05_原论文级Prompt武器库与五大角色完整模板直抄库.md`](./05_原论文级Prompt武器库与五大角色完整模板直抄库.md)** | **v3.0 零缩水直抄终极母本（涵盖 v3.0 窄工具统一签名总表 + `next_step_guidance` + 全部 29 条夜科学启发题 + 11 类元反思 + 6 套 `SLA` 声明式准则 + `Station Appendix D` 盲审 6 步法则 + 7 份可直接复制进 `core_python/agents/*.md` 的完整模板）** | 全部 7 个角色 Preset（含盲审工具沙箱声明、三态审稿、三档仪器与校准集升级协议） | • [`holiday_prompts.yaml`](file:///D:/Documents/deepseek%20harness/论文研读/2608.23691_Autonomous_Mathematical_Discovery_in_an_Open-World_Multi-Agent_Environment/station/example/station/default/holiday_prompts.yaml#L1-L66)<br>• [`SLA sections/10_appendix_prompts.md`](file:///D:/Documents/deepseek%20harness/论文研读/2610.07625_Stateless_Language_Agents_Scaling_Long-Horizon_Automated_Research/sections/10_appendix_prompts.md#L1-L274)<br>• [`AgentDiscover instructions & meta`](file:///D:/Documents/deepseek%20harness/论文研读/2610.05334_AgentDiscover_Autonomous_Discovery_with_Minimal_Search_Scaffolding/AgentDiscover/harness-instructions/instructions.md#L1-L160) |
| **[`06_十三篇核心文献工程速查卡与本机源码行号索引.md`](./06_十三篇核心文献工程速查卡与本机源码行号索引.md)** | 三大本体基石 + 三大加固件 + 经典工程先验（含 `The Tasteful Agent` 与 `Audit the Scaffold` 对开放问题与仪器校准确立的关键依据）在本机 `论文研读/` 中的完整行号总表 | 全局检索、重构验收、防遗漏核对 | • [`论文研读/README.md`](file:///D:/Documents/deepseek%20harness/论文研读/README.md)<br>• [`../architecture/04`](./../architecture/04_十三篇前沿论文深度解惑与V6Up架构融合专报.md) & [`05`](./../architecture/05_V6Up架构演进思辨与文献取舍絮语集.md) |

---

## 二、全项目二十五大“低品味 / 过拟合”红灯清单 v3.0（看到即判定不合格）

### A 组：顶层拓扑与制度基线十大红灯
1. **中心化星型太上皇反模式**；
2. **CTF 密码预注册反模式**（用权限/沙箱边界隔离，不用高熵随机口令防自己人）；
3. **伴随助手双模阉割反模式**；
4. **`[:120]` 伪摘要与只读空壳图书馆反模式**；
5. **不合成跨代看板反模式**；
6. **空壳方法族谱与兄弟失忆反模式**；
7. **硬编码 `False` 全局停滞看门狗反模式**；
8. **30 行“保安条例式”干瘪 Prompt 反模式**；
9. **将具体学科公式硬编码进通用底座反模式**；
10. **无标尺任务失去退场与交付尺度反模式**。

### B 组：二轮实机暴露的十大实战红灯（P1–P29 血泪提炼）
11. **数百步常驻官僚与满地公文 `.md` 反模式**：全员事件驱动短无状态调用，磁盘零审批 `.md` 公文；
12. **开场“必读行政文件税”与双重腰斩假时钟反模式**：固定 `500,000` Token 基准窗口，禁读全局行政文档；
13. **交接双写抢方向盘与 `37%` 解锁拖延到 `70%` 反模式**：`37%` 元反思完成当场置位解锁；
14. **机械拼串后 `[:2000]` 拦腰截断看板反模式**：总长硬限 `<= 2200` 校验拒收而非静默截断；
15. **手稿落盘共享目录致盲审穿帮反模式**：只存 SQLite + 脱敏拷入隔离盲审沙箱；
16. **全局单一 `state_version` 整数连坐作废反模式**：按 `(instrument_id, version)` 与显式 `REQUIRED_PREMISE` 精细传播；
17. **`0 L3` 空转自批圆满结题反模式**；
18. **物理跨子题串联污染基线反模式**；
19. **五合一巨型工具与 `orthogonal` 自锁反模式**；
20. **DSH 非法 `{{cwd}}` 与脆弱正则猜路径反模式**。

### C 组：第四轮复盘新增五大顶层硬红灯（v3.0 铁律）
21. **判不了就判 0 分 / 基础设施报错当算法失败反模式（`Obs-031` 冤案）**：任何 `INSTRUMENT_ERROR` 或 `INFRA_ERROR` **绝对禁止**写 `passed=False` 或 `MEASURED_NON_IMPROVEMENT`，不得扣探索者修补配额或推高停滞计数！
22. **竞赛特例硬编码进通用底座反模式**：强迫纯理论题造零号基线、全局硬卡 `<5%` 误差、底座全局拦截全零/常数解、AST 禁 `second_pass`、强制每题开局硬凑两条互斥路线——全部红牌禁止！
23. **修 Bug 被 `tie -> incumbent` 堵死 & 拿不同样本量分数硬比反模式**：工程缺陷修复走**校准集回归测试合入**，永久禁止用 `BB_eps` 平局或跨样本数 `0.7169 vs 0.9757` 拦截仪器 Bugfix！
24. **因噎废食砍掉盲审验证工具 & 缺 `READ` 边机械拒稿反模式**：必须给 `library_verifier` 配隔离沙箱下的计算/`pwsh`/Lean 跑证工具，不得将其阉割为 `0` 原生工具瞎子；不得仅因缺少 `READ` 日志边就强制降级严密证明；工程修补报错不得污染图书馆 `L2`。
25. **无人值守因口径疑义停摆死等 & 学派聚拢设高产豁免反模式**：无人值守期间遇口径争议须按原口径续跑并在后台亮红灯 `ALERT_AMBIGUOUS_SPEC` 等人处理；同题学派聚拢（`>=2` 分支且占比 `>50%`）强制无豁免打散分流。
