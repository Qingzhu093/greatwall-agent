# GreatWall Agent 参考文献、工程渊源与技术生态索引（REFERENCES）

> **配套文档**：[`ARCHITECTURE.md`](./ARCHITECTURE.md)（`v0.1-alpha` 现行架构） · [`ROADMAP.md`](./ROADMAP.md)（未解难题与演进构想）  
> **编写原则与学术规范声明**：  
> 1. **只收录真实影响设计的来源**：本清单严格限定为对 [`ARCHITECTURE.md`](./ARCHITECTURE.md)（已实现）或 [`ROADMAP.md`](./ROADMAP.md)（未来规划）产生直接设计影响的学术论文、工程报告、开源项目与开放标准，不以泛泛罗列文献数量作为背书。  
> 2. **严格区分“已落地”与“未来方向”**：每条来源均显式标注状态——**`✅ 已落地 (v0.1-alpha)`** 表示已进入当前代码库；**`🗺️ 路线图规划 (ROADMAP)`** 表示属于后续演进构想，**当前尚未实现**。  
> 3. **只记录“取了什么”与“如何适配”**：为确保学术客观性并便于协作者逐条核对校正，本文对每项来源统一记录四个可验证维度：**① 原作解决的核心问题 → ② 我们吸收的机制 → ③ 结合 DSH / GreatWall 的工程适配与落点 → ④ 公开可访问链接**。

---

## 目录

- [0. 全局速查总表](#0-全局速查总表)
- [1. 系统思想原点与六大核心架构基石（✅ 已落地）](#1-系统思想原点与六大核心架构基石-已落地)
- [2. 实证边界、工程博客与单点构件（✅ 已落地）](#2-实证边界工程博客与单点构件-已落地)
- [3. 演进路线图前沿参考（🗺️ 规划于 ROADMAP，尚未实现）](#3-演进路线图前沿参考-规划于-roadmap尚未实现)
- [4. 运行底座、开放协议与开源科研生态](#4-运行底座开放协议与开源科研生态)
- [5. 协作者按模块快速阅读指南](#5-协作者按模块快速阅读指南)

---

## 0. 全局速查总表

| 编号 | 名称 | 类型 | 状态 | 对应 GreatWall 工程与落点 |
| :---: | :--- | :--- | :---: | :--- |
| **1.0** | 钱学森《工程控制论》(1954) | 经典专著 | ✅ 已落地 | 全局系统边界与耦合克制原则（`ARCHITECTURE §1.3`） |
| **1.1** | **Cogentic** (`arXiv:2609.40324`) | 学术论文 | ✅ 已落地 | 设施/后勤/图书馆：零偏见调度、两阶段对抗盲审、`Auditor` 复验打捞 |
| **1.2** | **The Station v1 & v2** (`2608.23691`, `2610.08927`) | 学术论文 + 代码 | ✅ 已落地<br>🗺️ 部分规划 | 后勤/图书馆/仪器：初期隔离、`37%` 专家反思与 29 题夜科学、`Evidence Ledger`、五车道、多轨道 `tracks`（v2 监督冻结见 `ROADMAP §2.5`） |
| **1.3** | **Stateless Language Agents (SLA)** (`2610.07625`) | 学术论文 + 代码 | ✅ 已落地 | 设施/后勤/仪器：短生命周期无状态会话、报错与科学负结果分离、`Retained Candidate` 快照 |
| **1.4** | **AgentDiscover** (`2610.05334`) | 学术论文 + 代码 | ✅ 已落地 | 后勤/探索：按需定向 Pull、`next_step_guidance` 路标、`linguistic_prediction`、`<worktree>/tools/`、顾问“三不给” |
| **1.5** | **Red Queen Gödel Machine (RQGM)** (`2606.26294`) | 学术论文 | ✅ 已落地 | 仪器科学：仪器版本域可比、对抗/校准集回归升级、Stage A 留存按需重评 |
| **1.6** | **Audit the Scaffold** (`2609.34924`) | 学术论文 | ✅ 已落地 | 仪器科学/后勤：可观测探针优先、金/毒样本自检测试器、多学派正交分流 |
| **2.1** | **OpenAI CDC 64-Agent Prompt** | 官方规范 | ✅ 已落地 | 后勤/图书馆/监察：动态族谱与 `>50%` 分流、等价归约防伪完成、7 类漏洞清单、最短投入窗与部分交付 |
| **2.2** | **GPT-Rosalind (`distributed_agent`)** | 论文 + 代码 + 博客 | ✅ 已落地 | 设施/提示词：百字工具速查表 + 单行合法 JSON 范例、外键结构化约束 |
| **2.3** | **Anthropic: Multi-Agent Research System** | 官方工程博客 | ✅ 已落地 | 设施/后勤：子智能体上下文隔离、外部状态解耦防“传话失真”、工具描述打磨与检查点恢复 |
| **2.4** | **The Tasteful Agent** (`2609.25804`) | 学术论文 + 代码 | ✅ 已落地 | 仪器科学/后勤：`probe` 轻量探针与三态元反思替代闭门长考 |
| **2.5** | **Diversity Collapse** (`2604.18005`) | 学术论文 + 代码 | ✅ 已落地 | 后勤/图书馆：禁止广播高分假说、`0–37%` 锁定内藏公共库 |
| **2.6** | **MAS Should Prioritize Concurrency Control** (`2608.18092`) | 立场论文 | ✅ 已落地 | 设施：Single-Writer 事务串行、显式 Worktree 路径映射、终稿版本哈希绑定 |
| **2.7** | **Evaluating Sakana's AI Scientist** (`2502.14297`) | 实证论文 | ✅ 已落地 | 图书馆：外部文献实证复核、防终稿夸大与防全拒偏执 |
| **2.8** | **Abandoning Objectives (Novelty Search)** (2011) | 经典论文 | ✅ 已落地 | 后勤：`LEVEL_3` 反常/偏科垫脚石保护支线 |
| **2.9** | **Arbor / Bayesian-Agent / ResearchOS** | 学术论文 + 代码 | ✅ 已落地 | 设施/仪器/图书馆：Git Worktree 隔离、原始成败台账与回滚指针、`read_depth` 标注 |
| **3.1** | **Harness²** (`2610.14224`) | 学术论文 + 代码 | 🗺️ 路线图规划 | 仪器科学/图书馆/设施：8 大脚手架表面、局部轨迹对比（Mini-Probe）、一阶归零 + 二阶演化库双轨分离（`ROADMAP §2.6 / §3.3 / §5.1`） |
| **4.1** | **DeepSeek Harness (`DSH`) & Cordis** | 开源宿主底座 | ✅ 现行底座<br>🗺️ 主控规划 | 设施：Cordis 插件服务注入底座；`ROADMAP §1.2` 借鉴 `SuperAgent` 重塑主控层 |
| **4.2** | **Model Context Protocol (`MCP`)** | 开放标准 | ✅ 现行协议<br>🗺️ 生态扩展 | 设施/仪器：Node ↔ Python 32 工具标准桥接；`ROADMAP §2.2` 科研标准插座 |
| **4.3** | **Lean 4** | 形式化证明生态 | ✅ 验收桩<br>🗺️ 深度接入 | 仪器/图书馆：`evaluators/examples/` 桩接口；`ROADMAP §2.2` 形式化验证生态 |
| **4.4** | **Agent Client Protocol (`ACP`)** | 开放标准 | 🗺️ 路线图规划 | 设施：`ROADMAP §1.3 / §2.2` 脱离单一宿主绑定、跨 Harness 协议适配 |
| **4.5** | **Biomni / Virtual Lab / `scientific-agent-skills`** | 科研开源生态 | 🗺️ 路线图规划 | 开放科研生态：`ROADMAP §2.2 / §4.3` 跨学科工具链编排、科研技能标准与小组协作对照 |

---

## 1. 系统思想原点与六大核心架构基石（✅ 已落地）

本节记录构成了 GreatWall Agent `v0.1-alpha` 主干骨架的理论与方法论来源。

### 1.0 钱学森《工程控制论》（*Engineering Cybernetics*）
- **状态**：`✅ 已落地 (v0.1-alpha)` · [`ARCHITECTURE.md §1.3`](./ARCHITECTURE.md#13-钱学森工程控制论与仍在摸索中的核心张力)
- **出处**：H. S. Tsien (钱学森), *Engineering Cybernetics*, McGraw-Hill, 1954（中文修订版：《工程控制论》，科学出版社）。
- **原作解决的核心问题**：如何设计由多个复杂子系统耦合而成的工程控制系统，使整体在存在扰动、噪声与不确定性的环境下保持稳定、可控与全局协调，而非追求局部最优却引发全局振荡。
- **我们吸收的机制**：核心系统设计律——*“真正优秀的系统往往不是大量最优子系统的强行拼凑，而是由配合良好、边界清晰的组件构成的和谐整体。”*
- **结合 DSH / GreatWall 的工程适配**：成为本项目做架构决策与模块解耦的最高准则——在确定性代码与模型自主权、群体隔离与知识共享、权限收紧与执行便利等张力中优先选择简单正交的硬边界（如确定性 SQLite 触发器与单待办熔断），避免用繁复的行政公文或脆弱启发式脚本过度干预科学探索。

### 1.1 Cogentic: Multi-Agent Orchestration for Automated Proof Discovery
- **状态**：`✅ 已落地 (v0.1-alpha)` · 设施工程 / 后勤工程 / 图书馆工程
- **作者与出处**：Yang Cai, Vineet Gupta, Yanchen Jiang, Christopher Liaw, Aranyak Mehta, Grigoris Velegkas, Di Wang (Google Research / Google DeepMind / Yale University), `arXiv:2609.40324` (2026).
- **公开链接**：[arXiv:2609.40324](https://arxiv.org/abs/2609.40324) · [Project Page](https://sites.google.com/view/cogentic)
- **原作者解决的核心问题**：在没有客观标量打分器的开放数学与理论计算机科学难题中，如何组织多智能体协同完成高度严谨的长篇自然语言定理证明，并从失败的证明草稿中抢救可复用的正确中间引理。
- **我们吸收的机制**：
  1. 协调层与流程顾问严守 **`No Mathematical Opinion`**（绝不下场指导具体数学解法，只管流程与资源调度）；
  2. **单篇独立核验（Individual Verifier）+ 跨篇横向对照（Cross-Draft Verifier）**的双层对抗审查；
  3. 区分工作草稿（The Record）与已验证引理账本（The Verified Ledger），并设立独立 **`Auditor`** 从失败残骸中剥离中间引理、强制二次复验后入库。
- **结合 DSH / GreatWall 的工程适配**：
  - 将协调层的“无数学偏见”映射到零原生工具的 `logistics_coordinator`（[`tools_logistics.py`](./greatwall-v6up/core_python/mcp_server/tools_logistics.py)）与 `supervisory_committee`（[`tools_supervisory.py`](./greatwall-v6up/core_python/mcp_server/tools_supervisory.py)），并由确定性 DSH Cordis 编排器（[`orchestrator.js`](./greatwall-v6up/dsh_plugin/lib/orchestrator.js)）承载路由；
  - 将双层审查与引理打捞落地为 [`tools_library.py`](./greatwall-v6up/core_python/mcp_server/tools_library.py) 的两阶段物理盲审（`STAGE1_BLIND → STAGE2_UNBLIND`）与 `propose_salvaged_lemma`（强校验 `session_id != proposer_session_id` 异会话复验，且禁止在原分支 `ACTIVE_REVISING` 返工期抢断插手）。

### 1.2 The Station (v1 & v2): Open-World Multi-Agent Scientific Discovery
- **状态**：`✅ 核心机制已落地 (v0.1-alpha)` · `🗺️ 全局监督冻结机制规划于 ROADMAP §2.5`
- **作者与出处**：
  - v1: Stephen Chung, Wenyu Du, William J. Wesley (DualverseAI / Cambridge / HKU / UCSD), *Autonomous Mathematical Discovery in an Open-World Multi-Agent Environment*, `arXiv:2608.23691` (2026).
  - v2: Wenyu Du, Stephen Chung (DualverseAI / HKU / Cambridge), *Can AI Agents Make Open-Ended Scientific Discovery? Evidence from Station*, `arXiv:2610.08927` (2026).
- **公开链接**：
  - v1: [arXiv:2608.23691](https://arxiv.org/abs/2608.23691) · [GitHub (`dualverse-ai/station`)](https://github.com/dualverse-ai/station)
  - v2: [arXiv:2610.08927](https://arxiv.org/abs/2610.08927) · [GitHub (`dualverse-ai/station-open-reseach`)](https://github.com/dualverse-ai/station-open-reseach)
- **原作者解决的核心问题**：实证剖析 AI 智能体在开放式科学发现中普遍陷入“路灯效应 / 引力任务”（75% 自发提案质量偏低）、早期跟风与无标量评估困难的问题，并探索通过去中心化科研社区机制、元反思与先锁证据账本的同行评议提升开放研究深度。
- **我们吸收的机制**：
  1. **初期学徒隔离（Apprentice Isolation）**防止新人一开局就抄袭同化；
  2. **强制外部专家视角元反思（Meta-Reflection）**（完整 11 类元反思诊断题库，必查第 7 类 `Attractor Tasks` 引力任务）与 **`Holiday` 夜科学启发题库**（逐字收录原仓全部 29 条 `holiday_prompts.yaml`）；
  3. **不可逆 `Evidence Ledger` 盲审法则**（`Station v2 Appendix D` 6 步法则：先逐条锚定证据位置锁定账本再做终判）；
  4. **停滞五车道复苏协议（Stagnation Protocol）**（`EXPLORATION / EXPLOITATION / REVIVAL / UNDERSTANDING / STRATEGY`）与**无标量多轨道进展记录**；
  5. *(路线图规划)* v2 的 **Supervisor + 周期性 Meta-Reflection** 全局算力调度与已达标子题自动冻结机制。
- **结合 DSH / GreatWall 的工程适配**：
  - 在 DSH `TokenMeter` 驱动下，将学徒期与反思期映射为单节点 `0–37%` 独思净室（锁定内藏 `L3/L2`）→ `37%` 回合间隙续传 `lineage_companion` 执行元反思与夜科学追问（[`clock_and_turn_gap.js`](./greatwall-v6up/dsh_plugin/lib/clock_and_turn_gap.js)、[`holiday_prompts.yaml`](./greatwall-v6up/core_python/prompts/holiday_prompts.yaml)）→ 当场解锁 `37–70%` Pull；
  - 用 SQLite 触发器 `trg_reviews_lock_stage1`（[`db_schema.py`](./greatwall-v6up/core_python/mcp_server/db_schema.py)）将 `Evidence Ledger` 不可逆性固化为数据库硬约束；多轨道进展落地为统一仪器接口的 `tracks: dict`；五车道落地为 `dispatch_stagnation_five_lanes`；
  - 全局监督冻结机制列为 [`ROADMAP.md §2.5`](./ROADMAP.md#25-全局算力调度与收敛控制借鉴-the-station-监督与冻结机制) 后续方向。

### 1.3 Stateless Language Agents (SLA): Scaling Long-Horizon Automated Research
- **状态**：`✅ 已落地 (v0.1-alpha)` · 设施工程 / 后勤工程 / 仪器科学工程
- **作者与出处**：Qizheng Zhang, Changxiu Ji, Isaac Sun, Yuetai Li, Shubhangi Upasani, Sherry Ruan, Boyuan Ma, Fenglu Hong, Vamsidhar Kamanuru, Yoonho Lee (Stanford / CMU / UW / SambaNova / UC Berkeley), `arXiv:2610.07625` (2026).
- **公开链接**：[arXiv:2610.07625](https://arxiv.org/abs/2610.07625) · [GitHub (`Alex-q-z/stateless-language-agents`)](https://github.com/Alex-q-z/stateless-language-agents)
- **原作者解决的核心问题**：长程自动化研究中，长期常驻的有状态对话智能体在后期极易发生上下文退化与“体面怠惰”（高比例会话空转并宣称已达最优），且代码运行故障常被误判为科学路线失败。
- **我们吸收的机制**：
  1. **“有状态的搜索 + 无状态的智能体（Stateful Search with Stateless Agents）”**核心解耦范式；
  2. 严格区分**代码执行错误（`CANDIDATE_ERROR`）**与**真实科学负结果**，避免一次编码报错直接枪毙有效科学假说；
  3. **`Retained Candidate` 物理快照**托管与回滚保护，以及 `Appendix E` 的 6 套声明式一线探索准则。
- **结合 DSH / GreatWall 的工程适配**：
  - 依托 DSH `ctx.agents.create()` + `handle.dispose()`（[`agent_session_host.js`](./greatwall-v6up/dsh_plugin/lib/agent_session_host.js)、[`pair_lifecycle.js`](./greatwall-v6up/dsh_plugin/lib/pair_lifecycle.js)），所有 5 类治理角色均为一次性无状态短会话，一线伴随仅在单个节点生命周期内暂停续传、绝不跨代常驻；全部持久化研究状态托管于工作区外 SQLite WAL 与 Git Worktree；
  - 代码报错转后勤 `LEVEL_2` 基于 `retained_candidate` 物理快照原地修补（上限 3 次），与科学证伪彻底分轨；6 套探索准则内化进 [`core_python/agents/explorer.md`](./greatwall-v6up/core_python/agents/explorer.md)。

### 1.4 AgentDiscover: Autonomous Discovery with Minimal Search Scaffolding
- **状态**：`✅ 已落地 (v0.1-alpha)` · 后勤工程 / 探索执行层
- **作者与出处**：Mahdi Farahbakhsh, Ilan Sela, Fatemeh Doudi, Vishnu Teja Kunde, Krishna Narayanan, Jean-Francois Chamberland, Dileep Kalathil (Texas A&M University), `arXiv:2610.05334` (2026).
- **公开链接**：[arXiv:2610.05334](https://arxiv.org/abs/2610.05334) · [GitHub (`mhdfb/AgentDiscover`)](https://github.com/mhdfb/AgentDiscover)
- **原作者解决的核心问题**：过重、写死的外部进化搜索算法会束缚前沿模型的自主研究能力；同时展示如何在极简脚手架下让编程智能体通过结构化记忆、工具复用和过程顾问实现高效自主科学发现。
- **我们吸收的机制**：
  1. 将历史记录存入结构化图库，由探索者**按需定向 Pull**（而非固定外环硬塞）；
  2. 每次工具返回附带确定性的**动态导航提示（Steering）**，引导模型在无状态短会话下准确衔接流程；
  3. 评测提交前强制填写**事前预测（`linguistic_prediction`）**，以及分支内 `<worktree>/tools/` 可复用分析工具的跨代持久化；
  4. **`meta.md` 过程顾问“三不给”红线**（顾问只帮探索者决定“怎么想”，绝不给算力配额、排好序的执行方案菜单、或具体算法/代码实现）。
- **结合 DSH / GreatWall 的工程适配**：
  - 所有 32 个 MCP 工具统一通过 [`mcp_core_helpers.py`](./greatwall-v6up/core_python/mcp_server/mcp_core_helpers.py) 返回 `next_step_guidance` JIT 路标；
  - `run_isolated_eval` 将 `linguistic_prediction` 设为必填字段；探索者启动时由宿主自动扫描注入 `<worktree>/tools/` 清单；
  - 顾问“三不给”红线直接写入 `lineage_companion` 在 `37%` 元反思中的角色契约（[`core_python/agents/lineage_companion.md`](./greatwall-v6up/core_python/agents/lineage_companion.md)）。

### 1.5 The Red Queen Gödel Machine (RQGM): Co-Evolving Agents and Their Evaluators
- **状态**：`✅ 已落地 (v0.1-alpha)` · 仪器科学工程
- **作者与出处**：Alex Iacob, Andrej Jovanović, William F. Shen, Nicholas D. Lane et al. (University of Cambridge MLSys Lab / NVIDIA / Flower Labs / MBZUAI / Inria), `arXiv:2606.26294` (2026).
- **公开链接**：[arXiv:2606.26294](https://arxiv.org/abs/2606.26294)
- **原作者解决的核心问题**：在静态评估器下，持续演化的智能体必然遭遇刷分饱和（Reward Hacking）与自偏好退化；而评估器一旦演化，新旧版本之间的分数便不再具有直接可比性。
- **我们吸收的机制**：
  1. **版本域可比性（Version-Scoped Comparability）**：观测指标仅在同一评估器版本口径内可比，禁止跨版本混排；
  2. **对抗/错放样本沉淀**：将旧评估器错放或暴露漏洞的案例持久化为回归约束，防止升级后退化；
  3. **保留原始执行产物以支持按需重评**，以及“高杠杆修改主要落在全员共享基础设施上”的实证规律。
- **结合 DSH / GreatWall 的工程适配**：
  - [`isolated_runner.py`](./greatwall-v6up/core_python/evaluators/isolated_runner.py) 与 [`tools_works.py`](./greatwall-v6up/core_python/mcp_server/tools_works.py) 将全部 `[Obs###]` 永久绑定 `(instrument_id, instrument_version)`；
  - 每次 `official / heavy` 将 Stage A 候选输出持久化至 `$PLUGIN_DATA/.../eval_artifacts/<obs_id>/stage_a_output.json`，支持 `recompute_stage_b_only` 保留旧收据生成新版收据（缺字段诚实标记 `INCOMPATIBLE`）；错放与漏洞用例直接沉淀进仪器校准集驱动 `upgrade_instrument_with_calibration`。

### 1.6 Audit the Scaffold, Not the Checkpoint
- **状态**：`✅ 已落地 (v0.1-alpha)` · 仪器科学工程 / 后勤工程
- **作者与出处**：Sebastian Bobadilla-Suarez, Bob Suh, Ryan Fortin (OnCorps Research), *Audit the Scaffold, Not the Checkpoint: A Stationarity Dichotomy for Recursive Self-Improvement in Agentic Coding*, `arXiv:2609.34924` (NeurIPS 2026 Preprint).
- **公开链接**：[arXiv:2609.34924](https://arxiv.org/abs/2609.34924)
- **原作者解决的核心问题**：从理论（平稳性二分法定理）与实证两方面回答“当底层模型权重冻结时，究竟是什么决定了智能体持续改进的上限”，并揭示评测脚本本身存在大量未察觉缺陷的现实。
- **我们吸收的机制**：
  1. 冻结权重下仅靠堆砌冗长报错话术的提升效应量为零，**扩张工具与可观测性维度**才是突破可达假设空间上限的真正杠杆；
  2. 用官方金补丁反测自家测试器可揪出大量测坏的题目 → 确立**判定器上线前必须跑金/毒/格式自声明校准集**的硬门禁；
  3. 同族采样失败高度重叠的实证结论 → 支撑后勤多学派正交分流设计。
- **结合 DSH / GreatWall 的工程适配**：
  - 将工造司日常工作的核心价值明确定位为**“修故障 + 扩张高信噪比可观测性探针（`PROBE`）+ 校准集回归升版”**（[`tools_works.py`](./greatwall-v6up/core_python/mcp_server/tools_works.py)、[`isolated_runner.py`](./greatwall-v6up/core_python/evaluators/isolated_runner.py)）。

---

## 2. 实证边界、工程博客与单点构件（✅ 已落地）

本节收录在 GreatWall `v0.1-alpha` 中贡献了明确单点构件、工程规范或反模式边界的论文、提示词规范与官方工程博客。

### 2.1 OpenAI: Prompt Used for "A Proof of the Cycle Double Cover Conjecture"
- **状态**：`✅ 已落地 (v0.1-alpha)` · 后勤工程 / 图书馆工程 / 监察委员会
- **出处**：OpenAI 官方公开提示词规范（用于多智能体并发攻克圈双覆盖猜想）。
- **公开链接**：[cdc_prompt.pdf (OpenAI CDN)](https://cdn.openai.com/pdf/04d1d1e4-bc75-476a-97cf-49055cd98d31/cdc_prompt.pdf)
- **原规范解决的核心问题**：如何调度大规模并发数学推理智能体在长周期内攻克开放猜想，防止算力扎堆、伪等价归约、跳步证明与过早放弃。
- **我们吸收的机制与工程适配**：
  - 按核心数学思想归类的动态方法族谱（`method_families` + `<100` 字纯机制 `mechanism_summary`）与同题同流派聚拢超半数强制正交分流（`branch_count >= 2 && share > 0.50`）；
  - 区分实质证明与等价归约（`goal_coverage = "EQUIVALENT_REDUCTION"` 禁止标为 `FULL_GOAL`）；
  - 7 类结构漏洞红队清单写入 `library_verifier` 审稿规程；
  - 最短投入时间窗（`min_commitment_window_sec`）与“要么交付经审计完整成果，要么诚实交付已证部分与精确剩余缺口”的双段终局门禁（`check_stage2_closure_gate`）。

### 2.2 GPT-Rosalind & `distributed_agent` (OpenAI × Scripps × PerturbAI)
- **状态**：`✅ 已落地 (v0.1-alpha)` · 设施工程 / 工具契约与提示词层
- **作者与出处**：A. Sun, J. J. Park, D. DeTomaso, X. Jin et al. (OpenAI / Scripps Research / PerturbAI), *Distributed AI agents enable comprehensive discovery of biological insights at scale*, `bioRxiv:2026.10.15.759436` (2026).
- **公开链接**：[bioRxiv:2026.10.15.759436](https://www.biorxiv.org/content/10.64898/2026.10.15.759436v1) · [OpenAI Blog](https://openai.com/index/scaling-ai-research-for-complex-biological-data/) · [GitHub (`jinlabneurogenomics/distributed_agent`)](https://github.com/jinlabneurogenomics/distributed_agent)
- **原作解决的核心问题**：面向大规模高通量生物实验数据，构建可分布式扩展、具备清晰接口契约与可追踪推理图谱的科学发现智能体系统。
- **我们吸收的机制与工程适配**：
  - **百字工具速查表 + 单行合法 JSON 调用范例**写法，落地到 7 份角色模板（[`core_python/agents/*.md`](./greatwall-v6up/core_python/agents/)）与 [`mcp_schema_docs.py`](./greatwall-v6up/core_python/mcp_server/mcp_schema_docs.py) 的 Schema 自动增强中，降低无状态短会话的首次传参出错率；
  - 物理隔离与数据库外键约束设计思路（同时在盲审规程中明确外键存在不代表逻辑蕴含）。

### 2.3 Anthropic Engineering: *How we built our multi-agent research system*
- **状态**：`✅ 核心工程模式已落地 (v0.1-alpha)` · `🗺️ PTC 探索列于 ROADMAP §2.4`
- **作者与出处**：Jeremy Hadfield, Barry Zhang, Kenneth Lien, Florian Scholz, Jeremy Fox, Daniel Ford (Anthropic Engineering Team), 2025-06-13.
- **公开链接**：[Anthropic Engineering Blog](https://www.anthropic.com/research/multi-agent-research-system)
- **原博客解决的核心问题**：总结将多智能体研究系统推向工业级真实运行的工程实践——如何管理上下文污染、避免智能体间“传话游戏”失真、提升工具调用可靠性并支持长程任务检查点恢复。
- **我们吸收的机制与工程适配**：
  - **上下文强隔离**：每路探索节点与盲审会话在独立上下文中消化原始日志与代码细节，仅通过结构化手记与目录卡交换高信噪比摘要；
  - **外部工件系统解耦**：用工作区外 SQLite WAL 与物理文件快照承载研究产物，终结对话转述失真；
  - **检查点恢复与工具描述治理**：对应 `pending_handoff_mode` / `will_md` 先持久化后销毁的崩溃恢复机制，以及持续迭代 `Tool Guidance` 的工程路线。

### 2.4 其余单点机理与实证边界来源（汇总表）

| 论文 / 出处 | 原作解决的核心问题 | 我们吸收的机制 | 在 GreatWall (`v0.1-alpha`) 的精确落点 | 公开链接 |
| :--- | :--- | :--- | :--- | :--- |
| **The Tasteful Agent**<br>*(Pan et al., CityU & Microsoft, 2026)* | 测量并分析长视界任务中智能体面对未验证分叉决策时的“科研品味” | 长视界分叉单靠加长思考准确率极低的实证规律 → 用低成本快速探针与三态元反思做分叉决断 | `run_isolated_eval(tier="probe")` 快速诊断档 + `37%` 三态元反思（`verdict_3state`） | [arXiv:2609.25804](https://arxiv.org/abs/2609.25804) · [GitHub](https://github.com/wbopan/tastebench) |
| **Diversity Collapse in MAS**<br>*(Chen et al., NUS & CUHK-SZ, ACL 2026 Findings)* | 揭示开放式创意任务中多智能体因结构耦合导致群体多样性坍塌的机理 | 切断未审高分假说的跨分支广播，保留独立探索窗口 | 严禁广播当前 Leader 假说；`0–37%` 元反思前锁定内藏 `L3/L2`（[`tools_explorer.py`](./greatwall-v6up/core_python/mcp_server/tools_explorer.py)） | [arXiv:2604.18005](https://arxiv.org/abs/2604.18005) · [GitHub](https://github.com/Xtra-Computing/MAS_Diversity) |
| **Position: MAS Should Prioritize Concurrency Control**<br>*(Yang et al., ZJU / THU / HKUST / ETH Zürich, ICML 2026)* | 指出多智能体规模化失败的大量根因本质是共享状态并发控制问题 | 以数据库并发控制与版本绑定治理多智能体写冲突 | SQLite WAL `BEGIN IMMEDIATE` 单写者事务、显式 Worktree 路径登记、Stage 3 `delivery_id + sha256` 绑定终核（[`db_schema.py`](./greatwall-v6up/core_python/mcp_server/db_schema.py)） | [arXiv:2608.18092](https://arxiv.org/abs/2608.18092) |
| **Evaluating Sakana's AI Scientist**<br>*(Beel, Kan & Baumgart, Siegen & NUS, 2025)* | 独立全流程复现与实测首个全自动 AI 科研系统的真实瓶颈 | 揭示文献检索浅层、终稿夸大、实验崩溃率高与机械拒稿等失效模式 | 外藏 `[R###]` 标明未复验先验须由引用方核实；Stage 3 终核严查 `exact_verified_scope_md` 夸大；审稿提供 `REVISE` 返工而非一刀切拒稿 | [arXiv:2502.14297](https://arxiv.org/abs/2502.14297) |
| **Abandoning Objectives (Novelty Search)**<br>*(Lehman & Stanley, Evolutionary Computation, 2011)* | 解决欺骗性优化地形中目标函数直接引导陷入局部最优的问题 | 保护暂不占优但呈现独特结构/行为新颖性的“垫脚石”解 | 后勤分诊 `LEVEL_3`（偏科/反常特异保护支线，[`tools_logistics.py`](./greatwall-v6up/core_python/mcp_server/tools_logistics.py)） | [DOI:10.1162/EVCO_a_00025](https://doi.org/10.1162/EVCO_a_00025) |
| **Arbor**<br>*(RUC GSAI × MSRA, 2026)* | 解决长上下文“肥胖房间”下的自主研究分支管理与工作区污染 | Git Worktree 物理隔离不同假设分支；原始观测与精简视图分层 | 每条探索分支绑定独立 Git Worktree；3 份只追加真相表与 2 份轻量派生视图分离 | [arXiv:2606.11926](https://arxiv.org/abs/2606.11926) · [GitHub](https://github.com/RUC-NLPIR/Arbor) |
| **Bayesian-Agent**<br>*(Wu et al., IDEA / HKUST-GZ, 2026)* | 在跨框架演化中建立可追踪、可回滚的技能资产治理记录 | 记录技能的原始成功/失败计数、适用范围、实存路径与回滚指针 | `skills/SKILL_LEDGER.json` 台账与 `update_skill_ledger` 文件实存校验（[`tools_works.py`](./greatwall-v6up/core_python/mcp_server/tools_works.py)） | [arXiv:2606.08348](https://arxiv.org/abs/2606.08348) · [GitHub](https://github.com/DataArcTech/Bayesian-Agent) |
| **ResearchOS**<br>*(Liang et al., Preprints 2026)* | 通过结构化权限与阅读深度标注抑制科研智能体对文献的幻觉引述 | 显式标注外部文献真实阅读深度（全文 / 指定章节 / 仅摘要） | 外藏表 `external_literature_cards.read_depth` 强制枚举（`full_text / specified_sections / abstract_only`） | [DOI:10.20944/preprints202610.2216.v1](https://doi.org/10.20944/preprints202610.2216.v1) |

---

## 3. 演进路线图前沿参考（🗺️ 规划于 ROADMAP，尚未实现）

> **状态声明**：以下来源属于 GreatWall 下一阶段演进（见 [`ROADMAP.md`](./ROADMAP.md)）的核心方法论参考，**尚未合入当前 `v0.1-alpha` 主线代码**。

### 3.1 Harness²: Recursive Agent Harnessing for an Open World
- **状态**：`🗺️ 路线图规划` · [`ROADMAP.md §2.6`](./ROADMAP.md#26-工具易用性与底层引导体系重构) / [`§3.3`](./ROADMAP.md#33-harness²-与-ai-for-science-在工造司的精准合体构想) / [`§5.1`](./ROADMAP.md#51-核心演进方向效仿-harness²确立科学库--工程演化库双轨分离)
- **作者与出处**：Ruiyao Xu (Northwestern University), Yanfei Chen, Zhongying CuiZhu, Bhavana Dalvi Mishra, Yifei Ming, Han Yu, Rujun Han, Chen-Yu Lee, Tomas Pfister (Google Cloud AI Research), `arXiv:2610.14224` (2026).
- **公开链接**：[arXiv:2610.14224](https://arxiv.org/abs/2610.14224) · [GitHub (`google-research/harness2`)](https://github.com/google-research/harness2)
- **原作者解决的核心问题**：在缺乏外部 Ground-Truth Verifier 的开放世界任务流中，如何一边通过受控行为对比优化当前任务的执行脚手架（$\mathcal{H}$），一边防止上一任务的特化细节污染下一任务（特化与泛化张力），同时持续积累跨任务可复用的“脚手架改进能力”（$\mathcal{R}_t$）。
- **我们计划吸收的机制**：
  1. **8 大正交可编辑脚手架表面**（`System Prompt / Guardrails / Memory / Skills / Tool Guidance / Scripts / Subagents / Plugin`）与**“故障 → 最廉价有效组件”的映射梯队**（常规排序进精简常驻指导 → 机械重复封装为 `Scripts` → 场景化专家规程做成零闲置开销的按需 `Skills` → 仅当文字规则被反复无视时才动用代码级 `Plugin` 硬拦截）；
  2. **无真值反馈下的受控行为对比（Propose → Probe → Compose）**：区分流程视角（INV）与领域视角（DOM），要求所有组合决策严格锚定具体轨迹时刻，无效或退化即 `KEEP_BASE`；
  3. **一阶归零 + 二阶复利与反归因谬误**：切换新任务时执行脚手架从 $\mathcal{H}_0$ 归零起步防过拟合，跨任务仅沉淀经严格轨迹对比裁决（`helped / hurt / no observed effect / confounded`）的二阶改进经验库 $\mathcal{R}_t$。
- **结合 DSH / GreatWall 的工程适配规划**：
  - **工造司守正补短（`ROADMAP §3.3`）**：完整保留现有工造司的三档同码、四态隔离与校准集回归（守住“仪器本体准不准”），新增面向 `PROBE` 探针 / `SKILL.md` / `Tool Guidance` 的**双需求信号监听（Pain + Emergence）**与轻量**局部轨迹对比（Mini-Probe）**（验证“探索者用不用得稳”）；
  - **图书馆双轨分离（`ROADMAP §5.1`）**：借 DSH 插件与按需 `Skills` 架构，将长期记忆中枢演进为**“中央科学图书馆（当前课题科学真相）× 工造司轻量演化库（跨课题工程与脚手架经验）”**两条独立轨道。

---

## 4. 运行底座、开放协议与开源科研生态

本节记录 GreatWall 当前所依赖的运行底座、通信协议，以及 [`ROADMAP.md`](./ROADMAP.md) 中计划对接与借鉴的开源科研生态项目。

### 4.1 DeepSeek Harness (`DSH`) & Cordis
- **状态**：`✅ 现行运行底座 (v0.1-alpha)` · `🗺️ SuperAgent 主控范式参考 (ROADMAP §1.2)`
- **公开链接**：[GitHub (`deepseek-ai/deepseek-harness`)](https://github.com/deepseek-ai/deepseek-harness)
- **原项目解决的核心问题**：提供以 **Cordis** 可组合插件框架为核心的“Everything-is-a-Plugin”开放智能体运行时，将模型适配、工具注册、会话日志、权限守卫、Token 计量与前端扩展全部解耦为可插拔服务。
- **我们吸收的机制与工程适配**：
  - **现行底座（`✅`）**：[`greatwall-v6up/dsh_plugin/`](./greatwall-v6up/dsh_plugin/) 零修改 DSH 原生源码，通过 Cordis `inject` 挂载 `agents / tools / systemPrompt / tokenMeter / sessionProjections / sessionQuery` 服务，实现无 Root 扁平会话编排、双向路径 Guard 与右侧栏观测面板；
  - **主控演进（`🗺️`）**：[`ROADMAP.md §1.2`](./ROADMAP.md#12-重点方向重塑当前鸡肋的主控层借鉴-dsh-superagent-范式) 计划借鉴 DSH `SuperAgent` 在人机交互中枢、全局态势感知与意图转译上的范式，重塑当前偏底层的科研主控会话。

### 4.2 Model Context Protocol (`MCP`)
- **状态**：`✅ 现行工具协议 (v0.1-alpha)` · `🗺️ 科研标准插座底座 (ROADMAP §2.2)`
- **公开链接**：[Official Specification (`modelcontextprotocol.io`)](https://modelcontextprotocol.io) · [GitHub (`modelcontextprotocol/modelcontextprotocol`)](https://github.com/modelcontextprotocol/modelcontextprotocol)
- **原标准解决的核心问题**：为大语言模型宿主与外部工具、数据源之间提供统一、跨语言、基于 JSON-RPC 2.0 的开放通信标准。
- **我们的工程适配**：当前用于 Node 编排插件与 Python 单写者内核（32 窄工具 + 15 内部原语）的 `stdio JSON-RPC 2.0` 桥接（[`mcp_bridge.js`](./greatwall-v6up/dsh_plugin/lib/mcp_bridge.js)、[`greatwall_core_mcp.py`](./greatwall-v6up/core_python/mcp_server/greatwall_core_mcp.py)）；后续作为 `ROADMAP §2.2`“科研标准插座”的通用工具接入协议。

### 4.3 Lean 4
- **状态**：`✅ 仪器验收桩 (v0.1-alpha)` · `🗺️ 深度形式化验证插件生态 (ROADMAP §2.2)`
- **公开链接**：[Official Site (`lean-lang.org`)](https://lean-lang.org) · [GitHub (`leanprover/lean4`)](https://github.com/leanprover/lean4)
- **原项目解决的核心问题**：提供支持机器可检验数学定理证明与公理审计（如 `#print axioms`）的现代交互式定理证明器与编程语言。
- **我们的工程适配**：当前在仪器协议与 [`evaluators/examples/`](./greatwall-v6up/core_python/evaluators/examples/) 中以二值编译检验桩验证了非标量数学证明兼容性；后续计划在 `ROADMAP §2.2` 中接入开箱即用的 Lean 4 形式化编译与公理审计插件。

### 4.4 Agent Client Protocol (`ACP`)
- **状态**：`🗺️ 路线图规划 (ROADMAP §1.3 / §2.2)`
- **公开链接**：[Official Site (`agentclientprotocol.com`)](https://agentclientprotocol.com) · [GitHub (`agentclientprotocol`)](https://github.com/agentclientprotocol)
- **原标准解决的核心问题**：标准化编辑器/客户端与各类 AI 编程智能体运行时之间的结构化会话、工具调用与权限交互协议，打破工具与特定客户端的强绑定。
- **我们的适配规划**：作为脱离单一 DSH 宿主耦合、构建抽象运行时适配层（Runtime Adapter）的重点调研与标准对接方向。

### 4.5 Biomni (Stanford SNAP Lab)
- **状态**：`🗺️ 路线图规划 (ROADMAP §2.2)`
- **公开链接**：[Official Platform (`biomni.stanford.edu`)](https://biomni.stanford.edu) · [GitHub (`snap-stanford/Biomni`)](https://github.com/snap-stanford/Biomni)
- **原项目解决的核心问题**：构建面向生物医学领域的通用自主科研智能体，将海量领域数据库、分析软件库与多步科研工作流整合为可执行工具生态。
- **我们的借鉴规划**：作为 GreatWall 打造跨学科“科研标准插座”时，在领域科学工具链封装、数据库检索接入与多步实验编排上的重点工程参考。

### 4.6 The Virtual Lab (Stanford / Nature)
- **状态**：`🗺️ 路线图规划 (ROADMAP §2.2 / §4.3)`
- **作者与出处**：Kyle Swanson, Wesley Wu, Nash L. Bulaong, John E. Pak, James Zou (Stanford University / Chan Zuckerberg Biohub), *The Virtual Lab of AI agents designs new SARS-CoV-2 nanobodies*, *Nature* (2025).
- **公开链接**：[GitHub (`zou-group/virtual_lab`)](https://github.com/zou-group/virtual_lab)
- **原工作解决的核心问题**：通过模拟跨学科科研团队会议（Team Meetings）与个体专题会话，组织多位领域专家智能体协同设计并验证真实生物实验方案（如纳米抗体设计）。
- **我们的借鉴规划**：为 [`ROADMAP.md §2.2`](./ROADMAP.md#22-重点方向科研底座面向更广泛的开放性科研标准插座与多维开放) 的跨学科角色分工与 [`§4.3`](./ROADMAP.md#43-后勤总管效用存疑与群体协作拓扑严格隔离-vs-小组讨论) 中“严格隔离 vs 适度小组讨论”的群体协作拓扑对照实验提供直接参照。

### 4.7 K-Dense-AI / `scientific-agent-skills`（原 `claude-scientific-skills`）
- **状态**：`🗺️ 路线图规划 (ROADMAP §2.2)`
- **公开链接**：[GitHub (`K-Dense-AI/scientific-agent-skills`)](https://github.com/K-Dense-AI/scientific-agent-skills)
- **原项目解决的核心问题**：将生物信息、化学信息、临床研究、机器学习与科学数据库等跨学科程序性科研知识，沉淀为符合开放 Agent Skills 标准（`SKILL.md`）的即插即用技能库。
- **我们的兼容规划**：在后续解耦脚手架层与“科研标准插座”建设中，作为兼容社区开源科学技能生态的首选对照标准之一。

---

## 5. 协作者按模块快速阅读指南

如果你刚加入或准备拆改 GreatWall 的某一个子系统，无需通读上述全部文献，按关注模块读下面 **2–3 份**即可快速对齐全部设计语境：

- **想改设施工程 / 编排解耦 / 并发状态机**：[SLA (`2610.07625`)](https://arxiv.org/abs/2610.07625) + [Concurrency Control (`2608.18092`)](https://arxiv.org/abs/2608.18092) + [Anthropic Multi-Agent Blog](https://www.anthropic.com/research/multi-agent-research-system) + [DSH](https://github.com/deepseek-ai/deepseek-harness)
- **想改工造司 / 评测校准 / 工具级自演化**：[RQGM (`2606.26294`)](https://arxiv.org/abs/2606.26294) + [Audit the Scaffold (`2609.34924`)](https://arxiv.org/abs/2609.34924) + [Harness² (`2610.14224`)](https://arxiv.org/abs/2610.14224)
- **想改探索节律 / 元反思 / 谱系分流**：[The Station v2 (`2610.08927`)](https://arxiv.org/abs/2610.08927) + [AgentDiscover (`2610.05334`)](https://arxiv.org/abs/2610.05334) + [Diversity Collapse (`2604.18005`)](https://arxiv.org/abs/2604.18005)
- **想改图书馆 / 沙箱同行盲审 / 终局交付**：[Cogentic (`2609.40324`)](https://arxiv.org/abs/2609.40324) + [OpenAI CDC Prompt](https://cdn.openai.com/pdf/04d1d1e4-bc75-476a-97cf-49055cd98d31/cdc_prompt.pdf) + [The Station v2 App. D (`2610.08927`)](https://arxiv.org/abs/2610.08927)
- **想接入新学科科研工具 / 跨宿主生态**：[MCP Spec](https://modelcontextprotocol.io) + [ACP](https://agentclientprotocol.com) + [Biomni](https://github.com/snap-stanford/Biomni) + [`scientific-agent-skills`](https://github.com/K-Dense-AI/scientific-agent-skills)
