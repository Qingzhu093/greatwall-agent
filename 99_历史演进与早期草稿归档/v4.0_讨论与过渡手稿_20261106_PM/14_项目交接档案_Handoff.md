# 长城 Agent 项目交接档案（Handoff）

> 生成日期：2026-11-06
> 用途：在 AI/维护者之间转手时，快速定位文件、了解已有成果、已知问题与文献出处。
> 路径基准：`D:/Documents/deepseek harness`。路径统一用正斜杠表示；Windows 资源管理器可直接使用反斜杠等价路径。
> 状态声明：项目处于**架构设计阶段**。当前没有 V4 代码实现、没有运行中的实验、没有最终定稿的 V4 架构。
> 本档案只记录路径、内容、状态、已知缺口与来源；不含评价性判断。

---

## 1. 项目概况

### 1.1 项目目标

设计「长城 Agent」：一个面向 AI for Science 的超长程研究系统。系统以研究纲领为长期主体，执行者可换代；研究成果以带条件与证据的条目积累；V4.0 先落在可验证的竞赛/算法任务，V4.1 再扩展到开放式科学发现。

### 1.2 当前阶段

| 项 | 状态 |
|---|---|
| 架构设计 | 已有 00–13 多份文档；12/13 是 Codex（ChatGPT）产出的 V4 draft；未定稿 |
| 代码实现 | 无 V4 实现；存在 V2/V3/设计系统的历史代码与测试 |
| 实验运行 | 无 V4 实验；V2/V3 有历史运行档案；V4 文档声明不运行实验 |
| 论文阅读 | 本地有论文 PDF/LaTeX/中文综述/抽取文本；阅读深度见第 5 节 |
| 团队 | Agent Team 成员均 inactive；任务板 task-1–5 completed，task-6–11 deleted |
| V4 Teamwork Preview | 已回档到 `work/_rollback_20261106_ai4science/` |

### 1.3 版本关系（按讨论顺序）

| 名称 | 指代 | 相关文件 |
|---|---|---|
| V1 | 只有 skill 的一代 | 未定位到工程档案；描述见 04 与 work/01 |
| V2 | 加了机制的一代（Fork-and-Flush、角色协议、盲评锦标赛） | `D:/antigravity/实战v2/` |
| V3 | 竞赛实战（AFEVA；7 节点、门禁、Borda/MAP-Elites） | `D:/Documents/deepseek harness/实战v3/` |
| 0.1 草案 | 以可继承成果为单位的探索架构草案 | `长程Agent_探索架构草案/` |
| 设计系统 | AFEVA 的编排库/仿真器（Mock 测试） | `长程 Agent 设计系统/` |
| V4 | 当前要设计的下一代 AI for Science 架构 | `12_V4总体架构_研究纲领与知识演化.md`、`13_V4设计依据_原文核对与裁决.md` |

---

## 2. 文件位置总表

### 2.1 架构设计目录（主目录）

`D:/Documents/deepseek harness/长城Agent_框架设计/`

| 文件 | 大小 | 内容 | 状态 |
|---|---:|---|---|
| `00_一页纸总纲.md` | 10,004 | 一页纸总纲（v1） | 保留；其中「五平面」组织方式被 05 取代 |
| `01_框架设计_v1.md` | 34,743 | 框架设计 v1（五平面、执行/认知/信任/探索/元） | 保留；组织方式被 05 取代 |
| `02_机制裁决表.md` | 25,548 | 论文机制逐条裁决、证据等级、话术清单 | 保留 |
| `03_实验与评测计划.md` | 11,972 | 实验、指标、消融、12 周路线 | 保留 |
| `04_三版实战复盘.md` | 7,083 | V1/V2/V3 可核复盘与可复用资产 | 保留 |
| `05_设计问题与自顶向下框架.md` | 41,261 | P0–P9 设计问题链；当前讨论主线之一 | 保留 |
| `06_评判器_worktree_与执行协议.md` | 21,888 | 三货币/两测试集/四角色；worktree 生长；语义对齐 | 保留 |
| `07_补充_调度Agent_元反思阶段_邻域新颖性.md` | 9,514 | 调度 Agent、元反思阶段、邻域新颖性 | 保留 |
| `11_讨论全记录_20261106.md` | 45,444 | 讨论详版记录（时间线、用户观点、设计判断、原文事实、未决问题、原话摘录） | 保留 |
| `12_V4总体架构_研究纲领与知识演化.md` | 55,047 | Codex 产出的 V4 架构 draft（17 节 + 案例） | V4 draft；未定稿 |
| `13_V4设计依据_原文核对与裁决.md` | 17,653 | V4 依据：阅读边界、原文核对、采纳/改造/不照搬、覆盖核对 | V4 draft 附录；未定稿 |

### 2.2 work 材料目录

`D:/Documents/deepseek harness/长城Agent_框架设计/work/`

| 文件/目录 | 大小 | 内容 | 状态 |
|---|---:|---|---|
| `00_团队协作规范与证据等级.md` | 3,756 | 证据等级 A–E、机制卡模板、禁止事项 | 保留 |
| `01_现状考古与资产盘点.md` | 25,096 | V1/V2/V3、设计系统、0.1 的盘点与可复用资产 | 保留 |
| `02_机制卡_基础设施_检索_评测.md` | 36,474 | Anthropic/OpenAI/MLE-STAR/ARI 机制卡 | 保留 |
| `03_机制卡_证明发现与Station.md` | 35,435 | Cogentic/Station 两篇机制卡 | 保留 |
| `04_机制卡_多样性_并发_上下文.md` | 31,277 | Novelty/Diversity/上下文/并发机制卡 | 保留 |
| `05_机制卡_Coscientist与前沿定位.md` | 27,771 | Co-Scientist 机制卡与 2026 前沿定位 | 保留 |
| `2502.18864_coscientist.pdf` | 5,885,207 | Co-Scientist arXiv 原文 PDF | 保留 |
| `v4_reading/` | — | 12/13 使用的论文抽取缓存：`ari.txt`、`cdc.txt`、`cogentic.txt`、`coscientist.txt`、`diversity.txt`、`mle.txt` | 阅读缓存；非原文 |
| `_rollback_20261106_ai4science/` | — | 已回档的 V4 Teamwork Preview：共享框架、六份 preview、`00_preview.md`、`ROLLBACK.md` | 历史留档；不作活跃设计资产 |

### 2.3 相关项目与历史档案

| 路径 | 内容 | 状态 |
|---|---|---|
| `D:/antigravity/实战v2/` | V2 竞赛运行档案：BOARD、总任务书、02/03/04 号协议、`eval_gate/`、`solution_tree/`、`logs/`、`.incumbent/` | 历史档案 |
| `D:/Documents/deepseek harness/实战v3/` | V3 竞赛运行档案：BOARD、PROJECT_DOSSIER、`B题/`、`tools/`、`eval_gate/`、`specs/`、`node_01`–`node_07`、git 仓库 | 历史档案 |
| `D:/Documents/deepseek harness/长程 Agent 设计系统/` | AFEVA 设计系统：`docs/` 三份规范、`src/core`（contracts/engine/events/ledger/scheduler/snapshot/state/wal）、`src/evolution`、`src/worktree`、`tests/`、`e2e_tests/`、`TEST_READY.md` | 历史代码；测试为 Mock |
| `D:/Documents/deepseek harness/长程Agent_探索架构草案/` | 0.1 草案：README、01 架构设计、02 执行约定与提示词、03 完整推演、04 学术依据与研究计划 | 设计文档；未实测 |
| `D:/Documents/deepseek harness/长程Agent_资料研究/` | 01 两个核心问题、02 厂商项目社区、03 论文索引、04 OpenAI 并发案例、05 Cogentic 精读入口、06 六份材料阅读与思路整理、README | 阅读笔记 |
| `D:/Documents/deepseek harness/综测竞赛/` | 02/03/04 协议文档、05 v2 复盘、06 多智能体长程并发、07 十条思考、08/09 前沿文献映射、README | 竞赛/背景材料 |

### 2.4 论文研读目录

`D:/Documents/deepseek harness/论文研读/`

| 子目录 | 主要文件 | 内容 |
|---|---|---|
| `Anthropic_MultiAgent_Research_System/` | 中文全译与精读 `.md`；`notes/article_blocks.txt`；配图 | Anthropic 多智能体研究系统 |
| `2506.15692_MLE-STAR/` | PDF、LaTeX `source/`、中文综述 | MLE-STAR |
| `2502.14297_Evaluating_AIScientist/` | PDF、LaTeX `source/`、中文综述 | AI Scientist 独立复评 |
| `Lehman2011_AbandoningObjectives/` | PDF、`notes/mineru_extracted.md`、中文综述 | Novelty Search |
| `OpenAI_GPT5.6_CDC_Prompt/` | `cdc_prompt.pdf`、中文全译与解析 | 圈双覆盖猜想提示词 |
| `2609.40324_Cogentic/` | PDF、`source/main.tex`、中文综述 | Cogentic |
| `2608.23691_AutonomousMathematicalDiscovery/` | PDF、`source/`（dualverse/appendix/meta_analysis/additional_analysis 等）、中文综述、配图 | Station 数学版 |
| `2610.08927_Station_OpenEndedDiscovery/` | PDF、`source/sections/main.tex`、`source/sections/appendix.tex`、中文综述 | Station 开放科学版 |
| `2604.18005_DiversityCollapse/` | PDF、`source/acl_latex_cameraready.tex`、中文综述 | 多智能体多样性坍塌 |
| `2608.05791_TwoTierParallelism/` | PDF、`source/main.tex`、中文综述 | 两级推理期并行（TIPEX） |
| `2608.18092_ConcurrencyControl/` | PDF、中文综述 | 并发控制 position paper |
| `2606.10209_ContextEngineering/` | PDF、中文综述、上下文工程解析 | 长程上下文工程 |
| `2609.34924_LocalOptima/` | 综述、`2609.34924v1_extracted.txt` | Agent 自我改进局部最优 |
| `2610.11959_MiMo-V2.6/` | PDF、中文综述等 | MiMo-V2.6（背景材料） |
| `2510.04618_AgenticContextEngineering/` | 当前 0 个文件 | ACE（被 01/05 引用，本地无正文） |
| `2605.10341_PaperFit/` | 1 个文件 | PaperFit（非 V4 主线） |

---

## 3. 现有成果

### 3.1 设计文档

- `00`–`04`：第一轮框架、机制裁决、评测计划、三版复盘；
- `05`：P0–P9 设计问题链（目标/预研/成果/传承/决策/视野/执行/信任/自省/裁决）；
- `06`：评判器（三货币、frozen/live、Judge/RedTeam/Maintainer/Auditor）、worktree 生长、语义对齐防火墙；
- `07`：总控/调度双 Agent、元反思阶段、邻域新颖性；
- `11`：讨论详版记录；
- `12`：Codex V4 架构 draft；`13`：其依据与原文核对。

### 3.2 团队材料

- `work/00`：证据与协作规范；
- `work/01`：V1/V2/V3/设计系统/0.1 的考古；
- `work/02`–`05`：Anthropic/OpenAI/MLE-STAR/ARI、Cogentic/Station、Novelty/Diversity/上下文/并发、Co-Scientist 的机制卡。

### 3.3 V2 历史档案（客观记录）

- 位置：`D:/antigravity/实战v2/`；
- 文件：`BOARD.md`、`00_实战v2总任务书...`、`02_超长程无人值守参赛架构...`、`03_长程团队角色协议...`、`04_分叉清栈与盲评锦标赛协议...`、`WORKFLOW_MANIFEST.md`、`BRIEF_AND_PROBLEM.md`；
- 目录：`eval_gate/`、`solution_tree/`、`logs/`、`.incumbent/`；
- 档案记录：25 个子会话、12 个节点、22 case 的 `GateReport`；终局候选 `node_12` Q3 250.22s/70.6%、`termination_unlocked=false`；Q4 指标在 `node_08`–`node_12` 间沿用未重测；物理隔离/盲写未实现；中后期节点链为 `node_08→09→10→11`。

### 3.4 V3 历史档案（客观记录）

- 位置：`D:/Documents/deepseek harness/实战v3/`；
- 文件：`BOARD.md`、`PROJECT_DOSSIER.md`、`BRIEF_AND_PROBLEM.md`、`format2026.doc`；
- 目录：`B题/`、`tools/`、`eval_gate/`、`specs/`、`node_01`–`node_07`、`paper_latex/`、`solution_tree/`、`figures_publication/`；
- 档案记录：7 个节点、40 个 `.py`、8,041 行；`node_06` 三场景均时 195.60s 可由 `run_metrics` 复算；`radio_sandbox.py` 默认两只狗、`is_all_cleared` 终止信号、拒绝走出 R=1800m；`node_08` 从未启动；`node_07` 在 429 中断；`dossier` 的 `node_07` 数字与 `run_metrics/run.log` 不一致。

### 3.5 设计系统（客观记录）

- 位置：`D:/Documents/deepseek harness/长程 Agent 设计系统/`；
- 文档：`docs/ARCHITECTURE_SPECIFICATION.md`、`docs/INTERFACE_CONTRACTS.md`、`docs/TOPOLOGY_AND_EVOLUTION.md`、`TEST_READY.md`；
- 代码：`src/core`（contracts/engine/events/ledger/scheduler/snapshot/state/wal）、`src/evolution`、`src/worktree`；
- 测试：`tests/`、`e2e_tests/`；`TEST_READY.md` 记录 e2e 45/45；
- 档案记录：全仓无 LLM/网络/Git 调用；Worktree 为 temp 目录复制；测试使用 Mock；与 0.1 草案是两条路线。

### 3.6 0.1 草案

- 位置：`D:/Documents/deepseek harness/长程Agent_探索架构草案/`；
- 内容：研究目标/预算、独立执行、证据审阅、成果卡、前沿、组合、研究循环、执行约定与提示词、完整推演、学术依据与研究计划；
- 状态：设计文档，未实测。

### 3.7 任务板与团队

- task-1–task-5：completed（第一轮机制卡/考古）；
- task-6–task-11：deleted（V4 Teamwork Preview 回档时删除）；
- Agent Team 成员：lead、archaeologist、infra-papers、proof-station、diversity-papers、coscientist-scout、science-ontology、discovery-loops、knowledge-institution；当前均 inactive；
- 无运行中的实验或后台任务。

---

## 4. 面对的问题（中性清单）

### 4.1 版本与索引

- `00`/`01` 使用「五平面」组织；`05` 改为 P0–P9 问题链，并在文件顶部标注「五平面被取代」；两者同时存在。
- `12`/`13` 是 V4 draft，但目录中没有 README/INDEX 指明「哪份是 V4 主文档、哪些是历史材料」；`12`/`13` 内部互相引用，未引用 `00`–`07` 的版本关系表。
- `11` 是讨论记录；`14` 是本交接档案；`08`–`10` 不存在。

### 4.2 V4 draft（12/13）的已知缺口

- 没有对象字典/字段表；
- 没有 producer → artifact → consumer 接口表；
- 没有状态机/协议附录（决策代、裁决、反思写回、worktree 生长）；
- 没有 V4.0 最小实例（必须实现/可延后/可人工替代的分层）；
- `Theory` 在 12 中是独立第五循环；此前讨论中出现过「Empirical 后半段」的说法，二者未统一；
- 「红黑皇后对抗」在 12/13 中未出现；12 使用 `RedTeam`；用户原话中的该名称未映射；
- 12 正文部分数字未给页码/图表号；13 的引用更细，但仍有「未逐篇核验」「未重跑」的边界；
- 12 长 55KB/631 行，无 Executive Summary/决策表；
- 12 未给出 CUMCM B 的 task adapter（单狗/双狗、`is_all_cleared`、L1–L3、评分口径）；
- `12` 声明 V4.0 包含 Theory/Meta/Archive；V4.0 的最小范围未定义。

### 4.3 V1/V2/V3 的档案缺口

- V1：四个候选取证位置未定位到工程档案；仅存 V2 文档的二手转述；
- V2：未通过自设终局门（`termination_unlocked=false`）；Q4 指标未重测；物理隔离/盲写未实现；`.incumbent` 为空；部分口径（5,734 步/15h49m/初代 Q3 511.39s）与归档不一致；
- V3：使用双狗+自建沙箱+`is_all_cleared` 的代理任务；屏蔽完成信号后 `node_06` 从 173.94 升至 333.05 s/源；`node_08` 未启动；`dossier` 数字与 `run_metrics` 不一致；
- 设计系统：e2e 45/45 为 Mock/仿真；无真实 LLM/Git 接入；
- 上述档案与 V4 的继承/拒绝关系只在 `04`、`12` §16 中有文字描述，未形成逐项映射表。

### 4.4 文献与证据

- 本地论文同时存在 PDF、LaTeX 源、中文综述、MinerU 抽取文本；中文综述与原文存在差异（讨论中已记录若干处：如 Station v1 元反思 25 tick vs v2 50 tick；Co-Scientist 70.9→75.4 的 CI 跨零；MLE-STAR 未消融检索；ARI 评审细节）；
- 部分材料只读了综述或摘要，未逐页读原文；
- `v4_reading/` 是抽取缓存，不是原文；
- 未联网核对 GitHub 仓库当前状态；未重跑 V2/V3 或设计系统测试；
- 未进行 V4 实验；无 V4 运行时、任务集、评分器或基线结果。

### 4.5 运行与工程

- 无 V4 代码仓库；无 `pyproject.toml`/依赖锁/构建脚本/CI；
- 无模型适配器（未确定 API/CLI/密钥/成本口径）；
- 无 V4 任务数据与评分器（CUMCM B 沙箱仍在 V3 目录，需改造）；
- 无事件日志/状态库/预算账本的实际实现；
- 无实验记录与可复现脚本。

### 4.6 未决设计问题

1. Theory 是第五循环，还是 Empirical 的后半段？
2. 是否采用 12 的完整对象集；是否补 `Prediction`/`Assumption`/`EvaluationSpec` 等对象？
3. V4.0 的最小范围：哪些对象/循环/角色必须实现，哪些可延后？
4. 人机门槛与 `HumanAttentionBudget` 的具体规则；
5. 调度 Agent 与规则内核的边界；决策代频率/触发；
6. worktree 活跃数/子节点上限/预算比例；
7. 行为距离、探索信用权重、元反思频率；
8. 开放式评估的 judge 与专家校准；
9. 「红黑皇后」与 `RedTeam` 的命名/机制映射；
10. V4 与 00–07 的版本合并方式（是否重写 00/01，是否建立 README/INDEX）。

---

## 5. 论文、文献与出处

### 5.1 本地已归档的主要文献

| # | 主题 | 标题/作者 | 编号/URL | 本地位置（根：`论文研读/`） | 阅读记录 |
|---|---|---|---|---|---|
| 1 | Anthropic 多智能体 | How we built our multi-agent research system（Anthropic Engineering，2025-06-13） | https://www.anthropic.com/engineering/multi-agent-research-system | `Anthropic_MultiAgent_Research_System/`（中文全译、`notes/article_blocks.txt`） | 读过原文 blocks 全文与中文全译；无「执行引擎」「straggler」量化 |
| 2 | OpenAI CDC 提示词 | A proof of the Cycle Double Cover Conjecture（prompt） | https://cdn.openai.com/pdf/04d1d1e4-bc75-476a-97cf-49055cd98d31/cdc_prompt.pdf | `OpenAI_GPT5.6_CDC_Prompt/cdc_prompt.pdf` | 读过两页全文 |
| 3 | MLE-STAR | MLE-STAR: Machine Learning Engineering Agent via Search and Targeted Refinement（Google Cloud AI/KAIST） | arXiv:2506.15692 | `2506.15692_MLE-STAR/`（PDF、`source/`、中文综述） | 读过 `3_method.tex`、`4_experiments.tex`；§4 只消融换模型/集成 |
| 4 | AI Scientist 复评 | Evaluating Sakana's AI Scientist...（ARI） | arXiv:2502.14297 | `2502.14297_Evaluating_AIScientist/`（PDF、LaTeX、中文综述） | 读过 §2.1–2.8；关键词新颖性、评审漏检等 |
| 5 | Novelty Search | Abandoning Objectives: Evolution Through the Search for Novelty Alone（Lehman & Stanley, 2011） | DOI:10.1162/EVCO_a_00025；Evolutionary Computation 19(2):189–223 | `Lehman2011_AbandoningObjectives/`（PDF、MinerU 抽取、中文综述） | 读过 §3–6、§6.2、§6.4、§9.1 |
| 6 | Co-Scientist | Accelerating scientific discovery with Co-Scientist（Google） | arXiv:2502.18864v2 | `work/2502.18864_coscientist.pdf`；`work/v4_reading/coscientist.txt` | 读过 pp.1–40；p.54 位置偏差图；消融页 |
| 7 | Cogentic | Cogentic: Multi-Agent Orchestration for Automated Proof Discovery（Google） | arXiv:2609.40324v2 | `2609.40324_Cogentic/`（PDF、`source/main.tex`、中文综述） | 读过 `main.tex` 的 Harness/验证/结果/讨论 |
| 8 | Station 数学版 | Autonomous Mathematical Discovery in an Open-World Multi-Agent Environment | arXiv:2608.23691v2 | `2608.23691_AutonomousMathematicalDiscovery/`（PDF、`source/`、中文综述） | 读过 dualverse/appendix/meta_analysis/additional_analysis |
| 9 | Station 开放版 | Can AI Agents Make Open-Ended Scientific Discovery? Evidence from Station | arXiv:2610.08927v1 | `2610.08927_Station_OpenEndedDiscovery/`（PDF、`source/sections/`、中文综述） | 读过 main.tex 与 appendix 关键节 |
| 10 | 多样性坍塌 | Diversity Collapse in Multi-Agent LLM Systems | arXiv:2604.18005 | `2604.18005_DiversityCollapse/`（PDF、LaTeX、中文综述） | 读过 cognition 节、Vendi、Unbound Junior 等 |
| 11 | 两级并行 | A Two-Tier Perspective on Inference-Time Parallelism in Multi-Agent LLM Systems | arXiv:2608.05791 | `2608.05791_TwoTierParallelism/`（PDF、`source/main.tex`、中文综述） | 讨论中主要读中文综述；PDF 原文未逐页 |
| 12 | 并发控制 | Multi-Agent Systems Should Prioritize Concurrency Control（position） | arXiv:2608.18092 | `2608.18092_ConcurrencyControl/`（PDF、中文综述） | 讨论中主要读中文综述；position paper，转引数字未核 |
| 13 | 上下文工程 | Less Context, Better Agents | arXiv:2606.10209 | `2606.10209_ContextEngineering/`（PDF、中文综述） | 讨论中主要读中文综述 |
| 14 | 局部最优 | Avoiding Local Optima in Agentic Self-Improvement | arXiv:2609.34924 | `2609.34924_LocalOptima/`（综述、抽取文本） | 讨论中读综述与抽取文本 |
| 15 | MiMo-V2.6 | MiMo-V2.6: Scaling Reinforcement Learning Towards Self-Improvement | arXiv:2610.11959 | `2610.11959_MiMo-V2.6/` | 背景材料；非 V4 主线 |
| 16 | ACE | Agentic Context Engineering | arXiv:2510.04618 | `2510.04618_AgenticContextEngineering/`（当前 0 文件） | 被 `01`/`05` 引用；本地无正文 |

### 5.2 其他引用但未在本地的文献

- MAP-Elites（Mouret & Clune 2015）、POET、OMNI、Voyager、STP、ACE、Manus/OpenAI Harness 等：在 `长程Agent_资料研究/01_两个核心问题.md`、`03_论文索引.md` 中被引用；
- V4 draft 引用的 GitHub 仓库：`dualverse-ai/station`、`station-open-reseach`、`station-open-reseach_data`；未联网核对当前状态。

### 5.3 证据口径

- 设计文档曾使用 A–E 证据等级与 K/R 标记；本交接档案不重复评级；
- 中文综述为二手材料；原文以 PDF/LaTeX 为准；
- `work/v4_reading/` 是抽取缓存，可能出现 OCR/分块误差；
- 讨论中记录的原文事实、阅读边界、未核实项，见 `11_讨论全记录_20261106.md` 与 `13_V4设计依据_原文核对与裁决.md`。

---

## 6. 时间线与版本关系

| 时间（2026-11-06） | 文件/事件 |
|---|---|
| 20:32–20:55 | 00–05 生成/更新；work/00–05 生成 |
| 21:22 | 06 更新 |
| 21:30 | 07 更新 |
| 21:46–21:57 | V4 Teamwork Preview 生成；随后回档到 `_rollback_20261106_ai4science/` |
| 22:12 | 11 讨论全记录更新 |
| 22:49 | 12/13 由 Codex 生成 |
| 23:38 | 本交接档案生成 |

版本关系：`05` 在文件顶部声明取代 `01` 的五平面；`12/13` 声明 V4 draft；`11` 是讨论记录；`14` 是本档案。`08`–`10` 未生成。

---

## 7. 交接阅读顺序（按依赖，不是评价）

1. `11_讨论全记录_20261106.md`：用户原话、设计判断、未决问题；
2. `05_设计问题与自顶向下框架.md`：P0–P9 问题链；
3. `06`/`07`：评判器/worktree、调度/元反思/邻域新颖性；
4. `12`/`13`：V4 draft 与依据；
5. `00`–`04`、`work/00`–`05`：历史设计与机制卡；
6. `04`、`work/01`：V1/V2/V3 档案事实；
7. 第 5 节的论文原文；
8. `work/_rollback_20261106_ai4science/`：仅当需要查 V4 Preview 历史时阅读。

交接时先核对：路径是否存在、文件大小是否与第 2 节一致、`12`/`13` 是否为最新版本、任务板是否仍为 task-1–5。

---

## 8. 附录：已知未核实/未读取项

| 项 | 状态 |
|---|---|
| V1 工程档案 | 未定位 |
| V2 终局/Q4 口径 | 档案内部不一致；未重跑 |
| V3 完成信号 probe | 独立评议做过；本次未重跑 |
| 设计系统 45/45 e2e | `TEST_READY.md` 记录；本次未重跑 |
| TIPEX/并发控制/上下文工程原文 | 讨论中主要读中文综述；PDF 未逐页 |
| Co-Scientist 全部补充材料 | 未逐页；只读 pp.1–40 与消融页 |
| Station 全部数学证明/任务细节 | 未逐篇核验 |
| GitHub 仓库当前状态 | 未联网核对 |
| V4 代码/运行/实验 | 不存在 |

---

## 9. 术语表

| 术语 | 含义 |
|---|---|
| 长城 Agent | 本项目名称；V4 指其下一代 AI for Science 架构 |
| V1/V2/V3 | 三代历史系统；V1 无档案，V2 在 `D:/antigravity/实战v2`，V3 在 `实战v3` |
| AFEVA | V3/设计系统的架构名；V3 与设计系统的 AFEVA 展开不同 |
| 0.1 草案 | `长程Agent_探索架构草案/`，以可继承成果为单位的设计 |
| 三货币 | 有效性（门禁）、质量（Pareto 向量）、探索信用（预算） |
| frozen/live | 冻结测试集/活体对抗测试集 |
| Record/Ledger/Archive/Lineage | 尝试记录/可复用主张/评审文献/研究身份与私笔记 |
| Theory Phase / Theory Loop | 讨论中出现两种说法；12 采用独立第五循环 |
| 红黑皇后 | 用户提到的名称；12/13 未出现；12 使用 RedTeam |

---

## 10. 维护入口（事实性）

- 新增/修改设计文档后，更新本档案第 2 节与第 6 节；
- 若采纳/否决 12 的 V4 draft，记录到本档案第 4.6 节与 `11` 的新增记录；
- 若建立 V4 代码仓库，记录仓库路径、依赖、运行命令、任务集与评分器位置；
- 若重跑 V2/V3/设计系统测试，记录命令、结果文件与时间；
- 若新增论文阅读，更新第 5 节的本地路径与阅读深度。

---

本档案只描述路径、内容、状态、缺口与来源；不评价文档质量，不替维护者做取舍。