# GreatWall Agent 参考文献、工程渊源与技术生态索引（REFERENCES）

> **配套文档**：[`ARCHITECTURE.md`](./ARCHITECTURE.md)（`v0.3.2` 现行架构） · [`ROADMAP.md`](./ROADMAP.md)（清账本与演进构想） · [`docs/greatwall_v0_3_2_architecture_and_engineering_manual.md`](./docs/greatwall_v0_3_2_architecture_and_engineering_manual.md)  
> **编写原则与学术规范声明**：  
> 1. **只收录真实影响设计的来源**：本清单严格限定为对 [`ARCHITECTURE.md`](./ARCHITECTURE.md)（已实现）或 [`ROADMAP.md`](./ROADMAP.md)（未来规划）产生直接设计影响的学术论文、工程报告、开源项目与开放标准，不以泛泛罗列文献数量作为背书。  
> 2. **严格区分“已落地”与“未来方向”**：每条来源均显式标注状态——**`✅ 已落地 (v0.3.x)`** 表示已进入当前代码库；**`🗺️ 路线图规划 (ROADMAP)`** 表示属于后续演进构想，**当前尚未实现**。  
> 3. **只记录“取了什么”与“如何适配”**：为确保学术客观性并便于协作者逐条核对校正，本文对每项来源统一记录四个可验证维度：**① 原作解决的核心问题 → ② 我们吸收的机制 → ③ 结合 DSH / GreatWall 的工程适配与落点 → ④ 公开可访问链接**。

---

## 目录

- [0. 全局速查总表](#0-全局速查总表)
- [1. 系统思想原点与核心架构基石（✅ 已落地）](#1-系统思想原点与核心架构基石-已落地)
- [2. 协作协议、实证边界、工程博客与单点构件（✅ 已落地）](#2-协作协议实证边界工程博客与单点构件-已落地)
- [3. 演进路线图前沿参考（🗺️ 规划于 ROADMAP，尚未实现）](#3-演进路线图前沿参考-规划于-roadmap尚未实现)
- [4. 运行底座、开放协议与开源科研生态](#4-运行底座开放协议与开源科研生态)
- [5. 协作者按模块快速阅读指南](#5-协作者按模块快速阅读指南)

---

## 0. 全局速查总表

| 编号 | 名称 | 类型 | 状态 | 对应 GreatWall 工程与落点 |
| :---: | :--- | :--- | :---: | :--- |
| **1.0** | 钱学森《工程控制论》(1954) | 经典专著 | ✅ 已落地 | 全局系统边界律与“稳健性优先于防御性”原则（`ARCHITECTURE §1.3`） |
| **1.1** | **DeepSeek Super-agent** (`dsh-superagent-prototype`) | 工程报告 + 代码 | ✅ 已落地 (`v0.3.1`) | 设施工程：常驻 `gw-chief`、人类注意力预算、`Human-Mandate Gate`、`Inline & Spill` + `Chain of Recall`、+1 保留槽、Outbox 与 `handback_to_chief` |
| **1.2** | **Google DeepMind Quantum Swarm** (`arXiv:2611.09822`) | 学术论文 | ✅ 已落地 (`v0.3.0 / v0.3.2`) | 图书馆工程：Verified Wiki × Conference 双轨制、五步点对点接口排雷（Seam Pitfall）、`[UNVERIFIED]` 构想、主席 `No Mathematical Micro-Management` |
| **1.3** | **The Station v1 & v2** (`2608.23691`, `2610.08927`) | 学术论文 + 代码 | ✅ 已落地 (`v0.3.0 / v0.3.2`) | 图书馆/后勤/仪器：`Rigor/Novelty/Significance` 三维评审与反过度声称、`create/preview/read/survey` 与 `ARCHIVE_SURVEYOR` 三不铁律、完整 11 类元反思（含 `Research Taste`）、52% 停码 `Holiday` 绿洲 |
| **1.4** | **Cogentic** (`arXiv:2609.40324`) | 学术论文 | ✅ 已落地 | 设施/后勤/图书馆：零偏见调度、两阶段空白沙箱对抗盲审、沉船遗产打捞复验 |
| **1.5** | **Stateless Language Agents (SLA)** (`2610.07625`) | 学术论文 + 代码 | ✅ 已落地 | 设施/后勤/仪器：`360k` 短生命周期无状态会话、代码报错与科学证伪分离、`Retained Candidate` 快照 |
| **1.6** | **AgentDiscover** (`2610.05334`) | 学术论文 + 代码 | ✅ 已落地 | 后勤/探索：按结构定向 Pull、`next_step_guidance` 路标、`linguistic_prediction`、`<worktree>/tools/`、顾问“三不给” |
| **1.7** | **Red Queen Gödel Machine (RQGM)** (`2606.26294`) | 学术论文 | ✅ 已落地 | 仪器科学：版本域可比、作弊样本沉淀校准集回归升级、Stage A 留存按需重评 |
| **1.8** | **Audit the Scaffold** (`2609.34924`) | 学术论文 | ✅ 已落地 | 仪器科学/后勤：可观测探针优先、金/毒样本自检测试器、多学派正交分流 |
| **2.1** | **Stanford Virtual Lab** (*Nature* 2025) | 学术论文 + 代码 | ✅ 已落地 (`v0.3.2`) | 图书馆脉冲工作坊：`agenda + 3道必答议程问题 + 固定2轮 + 主席总结` 极简确定性会议编排 |
| **2.2** | **ColMAD** (`LFhase/ColMAD`) | 学术论文 + 代码 | ✅ 已落地 (`v0.3.2`) | 图书馆脉冲工作坊：以非零和协作议程替代零和红蓝互撕，消除 `Debate Hacking` 与单向广播 |
| **2.3** | **ProofCouncil** (`arXiv:2607.09474`) | 学术论文 | ✅ 已落地 (`v0.3.2`) | 图书馆/收敛：多篇互补证明分解与 `COMPOSITE_FULL_GOAL` 组合完备终核 |
| **2.4** | **OpenAI CDC 64-Agent Prompt** | 官方规范 | ✅ 已落地 | 后勤/图书馆/监察：动态族谱与 `>50%` 分流、等价归约禁标完成、7 类漏洞清单、最短投入窗与部分交付 |
| **2.5** | **GPT-Rosalind (`distributed_agent`)** | 论文 + 代码 + 博客 | ✅ 已落地 | 图书馆/提示词：第 1 拍代码硬对账、归约同时保留正反证据、`Explicit Gaps` 派单、百字工具速查表与 JSON 范例 |
| **2.6** | **Anthropic: Multi-Agent Research System** | 官方工程博客 | ✅ 已落地 | 设施/后勤：子智能体上下文隔离、外部状态解耦防“传话失真”、工具描述打磨与检查点恢复 |
| **2.7** | **The Tasteful Agent / Diversity Collapse / Concurrency Control / Sakana Audit / Novelty Search / Arbor / Bayesian-Agent / ResearchOS** | 学术论文 + 代码 | ✅ 已落地 | 仪器/后勤/设施/图书馆：`probe` 探针、0–37% 隔离、SQLite 单写者事务、防终稿夸大、`LEVEL_3` 垫脚石、Git Worktree、`SKILL_LEDGER` 与 `read_depth` 标注 |
| **3.1** | **Harness²** (`2610.14224`) | 学术论文 + 代码 | 🗺️ 路线图规划 | 仪器科学/图书馆/设施：8 大脚手架表面、局部轨迹对比（Mini-Probe）、一阶归零 + 二阶演化库双轨分离（`ROADMAP §3`） |
| **4.1** | **DeepSeek Harness (`DSH`) & Cordis** | 开源宿主底座 | ✅ 现行底座 | 设施：Cordis 插件服务注入、`ctx.agents.resume`、Action Cards 与 8 套单源 Preset |
| **4.2** | **Model Context Protocol (`MCP`)** | 开放标准 | ✅ 现行协议<br>🗺️ 生态扩展 | 设施/仪器：Node ↔ Python 53 窄工具标准桥接；`ROADMAP §4` 科研标准插座 |
| **4.3** | **Lean 4** | 形式化证明生态 | ✅ 验收桩<br>🗺️ 深度接入 | 仪器/图书馆：`evaluators/examples/` 桩接口；`ROADMAP §4` 形式化验证生态 |
| **4.4** | **Agent Client Protocol (`ACP`)** | 开放标准 | 🗺️ 路线图规划 | 设施：`ROADMAP §4` 脱离单一宿主绑定、跨 Harness 协议适配 |
| **4.5** | **Biomni / `scientific-agent-skills`** | 科研开源生态 | 🗺️ 路线图规划 | 开放科研生态：`ROADMAP §4` 跨学科工具链编排与开放科研技能标准 |

---

## 1. 系统思想原点与核心架构基石（✅ 已落地）

本节记录构成了 GreatWall Agent `v0.3.2` 主干骨架的理论与方法论来源。

### 1.0 钱学森《工程控制论》（*Engineering Cybernetics*）
- **状态**：`✅ 已落地` · [`ARCHITECTURE.md §1.3`](./ARCHITECTURE.md#13-greatwall-三大根本原则与五组核心张力)
- **出处**：H. S. Tsien (钱学森), *Engineering Cybernetics*, McGraw-Hill, 1954（中文修订版：《工程控制论》，科学出版社）。
- **原作解决的核心问题**：如何设计由多个复杂子系统耦合而成的工程控制系统，使整体在存在扰动、噪声与不确定性的环境下保持稳定、可控与全局协调，而非追求局部最优却引发全局振荡。
- **我们吸收的机制与工程适配**：确立“系统边界律”与“追求稳健性（Robustness）而非堆砌防御性（Defensiveness）”的最高准则——用确定性 SQLite 事务、触发器、沙箱守卫与三阶段拓扑执行器守住硬底线，把科学探索与评议自由完整交还给模型与人类 PI。

### 1.1 DeepSeek Harness Team: *Exploring Super-agent Design* & `dsh-superagent-prototype`
- **状态**：`✅ 已落地 (v0.3.1)` · 设施工程（人机总控与运维平面）
- **出处**：DeepSeek Harness Team, *Exploring Super-agent Design: Toward More Autonomous Agent Systems* (2026) & `dsh-superagent-prototype`.
- **公开链接**：[GitHub (`deepseek-ai/deepseek-harness`)](https://github.com/deepseek-ai/deepseek-harness)
- **原作解决的核心问题**：当单模型执行能力足够强后，多任务智能体系统的核心瓶颈转向人类注意力；需要通过物理剥权的主控入口、事件过滤、异步 Outbox 与回忆链保护人类注意力。
- **我们吸收的机制与工程适配**：
  - 落地常驻 **`gw-chief`**（物理零写码/零终端/零外网，配只读 `read/glob/grep` 审码）、三层防失忆上下文（`<=1500` 字置顶动态锚点卡 + `chief_read` 4000 字分页读取器 + `Chain of Recall` 外键回忆链）；
  - 落地两阶段院内事件过滤、+1 人类优先保留槽（`worker_slots.js`）、`Human-Mandate Gate` 当面直执版本化 `run_arrangements` 与四态 `operation_receipts`、订阅直通 + `handback_to_chief` 越界退回，以及 11 类并发 Outbox（`effects_consumer.js`）。

### 1.2 Google DeepMind: Quantum Algorithms Swarm
- **状态**：`✅ 已落地 (v0.3.0 / v0.3.2)` · 图书馆工程（文献馆与脉冲同行拼图工作坊）
- **出处**：Google DeepMind Quantum Algorithms Swarm, `arXiv:2611.09822` (2026), Appendix C & Figs. S4–S5.
- **公开链接**：[arXiv:2611.09822](https://arxiv.org/abs/2611.09822)
- **原作解决的核心问题**：在多团队并发优化复杂量子电路与形式化成本证明时，如何兼顾各团队独立深潜与跨团队突破传播（实证跨团队共享 Wiki 与定期 Conference 合计贡献 39% 总收益）。
- **我们吸收的机制与工程适配**：
  - **Verified Wiki × Conference 双轨制**：平时经盲审通过的微型论文随时入馆（对应 Verified Wiki），未验真半成品构想强制打 `[UNVERIFIED]` 标签仅在波次脉冲会议碰撞；
  - **五步点对点接口排雷（Seam Pitfall）与主席 `No Mathematical Micro-Management`**：落地为 `submit_conference_statement` 的点对点 `target_node_ids` 回复链、双供体 `DONOR_MANIFEST.md` 清单与 `conference_chair` 禁止数学微操纪律；基线刷新保留 $\ge 5\%$ 提升或 $\ge 20\%$ 精简门槛。

### 1.3 The Station (v1 & v2): Open-World Multi-Agent Scientific Discovery
- **状态**：`✅ 核心机制已全部落地 (v0.3.0 / v0.3.2)` · 图书馆工程 / 后勤工程 / 仪器科学工程
- **作者与出处**：
  - v1: Stephen Chung, Wenyu Du, William J. Wesley (DualverseAI / Cambridge / HKU / UCSD), *Autonomous Mathematical Discovery in an Open-World Multi-Agent Environment*, `arXiv:2608.23691` (2026).
  - v2: Wenyu Du, Stephen Chung (DualverseAI / HKU / Cambridge), *Can AI Agents Make Open-Ended Scientific Discovery? Evidence from Station*, `arXiv:2610.08927` (2026).
- **公开链接**：
  - v1: [arXiv:2608.23691](https://arxiv.org/abs/2608.23691) · [GitHub (`dualverse-ai/station`)](https://github.com/dualverse-ai/station)
  - v2: [arXiv:2610.08927](https://arxiv.org/abs/2610.08927) · [GitHub (`dualverse-ai/station-open-reseach`)](https://github.com/dualverse-ai/station-open-reseach)
- **原作解决的核心问题**：实证剖析 AI 智能体在开放式科学发现中普遍陷入“路灯效应 / 引力任务”、早期跟风与过度声称问题，探索通过三维审稿、文献综述助手、完整 11 类元反思与停码 Holiday 破局。
- **我们吸收的机制与工程适配**：
  - **三维评审 + 反过度声称**（`REVIEWER.md`）：落地为 [`tools_verifier.py`](./greatwall-v6up/core_python/mcp_server/tools_verifier.py) 的 Stage 1 `rigor_score`（反 Overclaim 强制 `PARTIAL_PASS -> ACCEPT_NARROWED`）+ Stage 2 `novelty_score`（`<=3` 查重退稿）与 `significance_score`（`<=4` 强制分流至 `MARGINAL_NOTE`）；
  - **微型论文库四原语与 `ARCHIVE_SURVEYOR` 铁律**：落地为默认非阻塞快照投稿（`create`）、目录卡（`preview`）、全文含审稿附页（`read`）与 [`tools_internal_survey.py`](./greatwall-v6up/core_python/mcp_server/tools_internal_survey.py) 零外网院内专题综述员（`survey`，严守“绝不代出新点子或下达指令”）；
  - **完整 11 类元反思 + 52% 停码 `Holiday` 绿洲**：落地为 [`meta_reflection_categories.yaml`](./greatwall-v6up/core_python/prompts/meta_reflection_categories.yaml)（含第 11 类 `C11_RESEARCH_TASTE`）与 [`context_holiday.py`](./greatwall-v6up/core_python/mcp_server/control_plane/context_holiday.py) / [`context_holiday.js`](./greatwall-v6up/dsh_plugin/lib/host/context_holiday.js)（52% 宿主物理只读锁 2 回合 + `submit_holiday_bet`）；同时有意识地拒绝了其常驻公共水贴聊天室，坚持脉冲会议制防群体趋同。

### 1.4 Cogentic: Multi-Agent Orchestration for Automated Proof Discovery
- **状态**：`✅ 已落地` · 设施工程 / 后勤工程 / 图书馆工程
- **作者与出处**：Yang Cai, Vineet Gupta, Yanchen Jiang, Christopher Liaw, Aranyak Mehta, Grigoris Velegkas, Di Wang (Google Research / Google DeepMind / Yale University), `arXiv:2609.40324` (2026).
- **公开链接**：[arXiv:2609.40324](https://arxiv.org/abs/2609.40324) · [Project Page](https://sites.google.com/view/cogentic)
- **我们吸收的机制与工程适配**：协调层 `No Mathematical Opinion` 映射到零原生工具的 `logistics_coordinator` 与 `supervisory_committee`；单篇 + 跨篇双阶段审查与独立 `Auditor` 沉船引理打捞落地为 [`tools_verifier.py`](./greatwall-v6up/core_python/mcp_server/tools_verifier.py) 的两阶段空白沙箱盲审与 `propose_salvaged_lemma` / `enqueue_salvage_review`。

### 1.5 Stateless Language Agents (SLA): Scaling Long-Horizon Automated Research
- **状态**：`✅ 已落地` · 设施工程 / 后勤工程 / 仪器科学工程
- **作者与出处**：Qizheng Zhang, Changxiu Ji, Isaac Sun, Yuetai Li et al. (Stanford / CMU / UW / SambaNova / UC Berkeley), `arXiv:2610.07625` (2026).
- **公开链接**：[arXiv:2610.07625](https://arxiv.org/abs/2610.07625) · [GitHub (`Alex-q-z/stateless-language-agents`)](https://github.com/Alex-q-z/stateless-language-agents)
- **我们吸收的机制与工程适配**：有状态外部搜索（SQLite + Git Worktree）× 无状态短会话（`v0.3.2` 收紧至 `360k` 有效窗口），严格区分代码故障（`CANDIDATE_ERROR` 原地修补最多 3 次）与科学证伪。

### 1.6 AgentDiscover: Autonomous Discovery with Minimal Search Scaffolding
- **状态**：`✅ 已落地` · 后勤工程 / 探索执行层
- **作者与出处**：Mahdi Farahbakhsh, Ilan Sela, Fatemeh Doudi et al. (Texas A&M University), `arXiv:2610.05334` (2026).
- **公开链接**：[arXiv:2610.05334](https://arxiv.org/abs/2610.05334) · [GitHub (`mhdfb/AgentDiscover`)](https://github.com/mhdfb/AgentDiscover)
- **我们吸收的机制与工程适配**：全院 53 窄工具统一附带 `next_step_guidance` 动态路标、`run_isolated_eval` 必填 `linguistic_prediction`、`<worktree>/tools/` 持久化与伴随顾问“三不给”红线。

### 1.7 The Red Queen Gödel Machine (RQGM) & 1.8 Audit the Scaffold
- **状态**：`✅ 已落地` · 仪器科学工程
- **出处与公开链接**：
  - RQGM: Alex Iacob, Andrej Jovanović, William F. Shen, Nicholas D. Lane et al., [arXiv:2606.26294](https://arxiv.org/abs/2606.26294) (2026).
  - Audit the Scaffold: Sebastian Bobadilla-Suarez, Bob Suh, Ryan Fortin (OnCorps Research), [arXiv:2609.34924](https://arxiv.org/abs/2609.34924) (NeurIPS 2026 Preprint).
- **我们吸收的机制与工程适配**：观测永久绑定 `(instrument_id, version)` 与 `frozen_code_snapshot_path`、Stage A 留存按需 Stage B 重评、作弊样本沉淀入隐藏校准集驱动 `upgrade_instrument_with_calibration`，以及优先扩张高分辨率只读诊断探针（`PROBE`）。

---

## 2. 协作协议、实证边界、工程博客与单点构件（✅ 已落地）

### 2.1 The Virtual Lab (Stanford / *Nature* 2025)
- **状态**：`✅ 已落地 (v0.3.2)` · 图书馆工程（脉冲同行工作坊编排）
- **作者与出处**：Kyle Swanson, Wesley Wu, Nash L. Bulaong, John E. Pak, James Zou (Stanford University / Chan Zuckerberg Biohub), *The Virtual Lab of AI agents designs new SARS-CoV-2 nanobodies*, *Nature* (2025).
- **公开链接**：[GitHub (`zou-group/virtual_lab`)](https://github.com/zou-group/virtual_lab)
- **我们吸收的机制与工程适配**：吸收其 `run_meeting` 极简确定性编排结构——用 `agenda`（第 1 拍客观硬账本）+ `agenda_questions`（3 道必答结构化议程问题）+ `agenda_rules`（严禁套话与微操）+ 固定 2 轮发言 + 主席总结，直接落在 [`wave_engine.py`](./greatwall-v6up/core_python/mcp_server/control_plane/wave_engine.py) 与 [`wave_conference_runner.js`](./greatwall-v6up/dsh_plugin/lib/orchestrator/wave_conference_runner.js)，无需引入臃肿自由群聊框架。

### 2.2 ColMAD: Collaborative Multi-Agent Debate
- **状态**：`✅ 已落地 (v0.3.2)` · 图书馆工程（脉冲同行工作坊发言协议）
- **公开链接**：[GitHub (`LFhase/ColMAD`)](https://github.com/LFhase/ColMAD)
- **我们吸收的机制与工程适配**：针对零和竞争辩论诱发 `Debate Hacking`（隐瞒自家短板、死抠对手边角瑕疵）的病灶，将脉冲会议上半场重构为非零和拼图协作协议：Round 1 自曝真实失效边界与 `[UNVERIFIED]` 模块，Round 2 强制非空 `target_node_ids` 点对点执行 `CRITIQUE_SEAM / ENDORSE_AND_OFFER / WARN_STREETLIGHT / CONFIRM_TAKEAWAY`。

### 2.3 ProofCouncil (`arXiv:2607.09474`)
- **状态**：`✅ 已落地 (v0.3.2)` · 图书馆工程（多篇组合完备收敛）
- **公开链接**：[arXiv:2607.09474](https://arxiv.org/abs/2607.09474)
- **我们吸收的机制与工程适配**：将“多篇互补局部引理拼齐整题证明时的接口与覆盖完备性核查”落地为 `CONVERGE_FULL_COMPOSITE` 动作与 `review_queue(source_type='COMPOSITE_FULL_GOAL')` 组合终核单，经空白沙箱盲审验证无缝隙后合法签发总成 `FULL_GOAL L3`，零后门满足 `trg_l3_require_verified_review`。

### 2.4 OpenAI CDC 64-Agent Prompt & 2.5 GPT-Rosalind (`distributed_agent`) & 2.6 Anthropic Multi-Agent Blog
- **状态**：`✅ 已落地`
- **公开链接**：
  - OpenAI CDC Prompt: [cdc_prompt.pdf](https://cdn.openai.com/pdf/04d1d1e4-bc75-476a-97cf-49055cd98d31/cdc_prompt.pdf)
  - GPT-Rosalind (`distributed_agent`): [bioRxiv:2026.10.15.759436](https://www.biorxiv.org/content/10.64898/2026.10.15.759436v1) · [GitHub (`jinlabneurogenomics/distributed_agent`)](https://github.com/jinlabneurogenomics/distributed_agent)
  - Anthropic Multi-Agent Research System: [Anthropic Engineering Blog](https://www.anthropic.com/research/multi-agent-research-system)
- **工程适配**：动态学派与 `>50%` 聚拢分流、7 类红队盲审清单、最低投入时间窗；第 1 拍代码硬对账、同时保留正反证据与 `Explicit Gaps` 派单、百字工具速查表与 JSON 范例（[`mcp_schema_docs.py`](./greatwall-v6up/core_python/mcp_server/mcp_schema_docs.py)）；外部工件解耦与断点检查点恢复。

### 2.7 其余单点机理与实证边界来源（汇总表）

| 论文 / 出处 | 原作解决的核心问题 | 我们吸收的机制 | 在 GreatWall (`v0.3.2`) 的精确落点 | 公开链接 |
| :--- | :--- | :--- | :--- | :--- |
| **The Tasteful Agent**<br>*(Pan et al., 2026)* | 测量长视界分叉决策时的“科研品味” | 用低成本快速探针与三态元反思替代闭门长考 | `run_isolated_eval(tier="probe")` + `37%` 元反思 | [arXiv:2609.25804](https://arxiv.org/abs/2609.25804) · [GitHub](https://github.com/wbopan/tastebench) |
| **Diversity Collapse in MAS**<br>*(Chen et al., ACL 2026)* | 揭示开放任务中群体多样性坍塌机理 | 切断未审高分假说广播，保留独立探索净室 | `0–37%` 锁定内藏 `L3/L2` 与院内专题 `survey`（[`tools_explorer_pull.py`](./greatwall-v6up/core_python/mcp_server/tools_explorer_pull.py)） | [arXiv:2604.18005](https://arxiv.org/abs/2604.18005) · [GitHub](https://github.com/Xtra-Computing/MAS_Diversity) |
| **MAS Should Prioritize Concurrency Control**<br>*(Yang et al., ICML 2026)* | 指出多智能体失败常源于共享状态写冲突 | 以数据库单写者事务与版本哈希绑定治理并发 | SQLite WAL `BEGIN IMMEDIATE` 单写者、Outbox 代数版本号、Stage 3 不可变冻结目录哈希锁 | [arXiv:2608.18092](https://arxiv.org/abs/2608.18092) |
| **Evaluating Sakana's AI Scientist**<br>*(Beel et al., 2025)* | 实测首个全自动 AI 科研系统的真实失效模式 | 文献实证复核、防终稿夸大与有限次 `REVISE` | 外藏 `[R###]` 标明未复验；Stage 3 严查边界夸大；异步 `REVISE` 回流 | [arXiv:2502.14297](https://arxiv.org/abs/2502.14297) |
| **Abandoning Objectives (Novelty Search)**<br>*(Lehman & Stanley, 2011)* | 欺骗性地形中保护“垫脚石”解 | 为低分但具罕见反常现象的节点保留保护分支 | `LEVEL_3` 保护支线与 2 班岗成长保护期 | [DOI:10.1162/EVCO_a_00025](https://doi.org/10.1162/EVCO_a_00025) |
| **Arbor / Bayesian-Agent / ResearchOS**<br>*(2026)* | 分支隔离、技能回滚与文献阅读深度防幻觉 | Git Worktree 隔离、原始成败台账与 `read_depth` 枚举 | 独立 Worktree、`SKILL_LEDGER.json`、`external_literature_cards.read_depth` | [Arbor](https://arxiv.org/abs/2606.11926) · [Bayesian-Agent](https://arxiv.org/abs/2606.08348) · [ResearchOS](https://doi.org/10.20944/preprints202610.2216.v1) |

---

## 3. 演进路线图前沿参考（🗺️ 规划于 ROADMAP，尚未实现）

### 3.1 Harness²: Recursive Agent Harnessing for an Open World
- **状态**：`🗺️ 路线图规划` · [`ROADMAP.md §3`](./ROADMAP.md#3-p2-仪器科学演进守正补短吸收-harness²-迈向科学库--工程演化库双轨)
- **作者与出处**：Ruiyao Xu, Yanfei Chen, Zhongying CuiZhu, Bhavana Dalvi Mishra, Yifei Ming, Han Yu, Rujun Han, Chen-Yu Lee, Tomas Pfister (Northwestern University / Google Cloud AI Research), `arXiv:2610.14224` (2026).
- **公开链接**：[arXiv:2610.14224](https://arxiv.org/abs/2610.14224) · [GitHub (`google-research/harness2`)](https://github.com/google-research/harness2)
- **适配规划**：在保留现有工造司四项底座优势的前提下，引入局部轨迹对比（Mini-Probe）与“中央科学图书馆 × 工造司工程演化库”双轨分离，一阶归零防过拟合、二阶跨课题复利积累。

---

## 4. 运行底座、开放协议与开源科研生态

- **DeepSeek Harness (`DSH`) & Cordis**（`✅ 现行底座`）：[GitHub (`deepseek-ai/deepseek-harness`)](https://github.com/deepseek-ai/deepseek-harness) —— `dsh_plugin/` 零修改宿主源码，挂载 `agents / tools / systemPrompt / tokenMeter / sessionProjections / actionCards` 与 8 套单源 Preset。
- **Model Context Protocol (`MCP`)**（`✅ 现行协议` / `🗺️ 科研插座扩展`）：[modelcontextprotocol.io](https://modelcontextprotocol.io) —— 承载 Node ↔ Python 53 窄工具 `stdio JSON-RPC 2.0` 桥接。
- **Lean 4**（`✅ 验收桩` / `🗺️ 深度接入`）：[lean-lang.org](https://lean-lang.org) —— `evaluators/examples/` 二值形式化编译验收桩，后续接入开箱即用公理审计插件。
- **Agent Client Protocol (`ACP`)**（`🗺️ 路线图规划`）：[agentclientprotocol.com](https://agentclientprotocol.com) —— 调研跨宿主运行时适配，降低单宿主耦合。
- **Biomni & `scientific-agent-skills`**（`🗺️ 路线图规划`）：[snap-stanford/Biomni](https://github.com/snap-stanford/Biomni) · [K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills) —— 跨学科科学工具链与开放技能标准对照。

---

## 5. 协作者按模块快速阅读指南

- **想改设施工程 / 常驻总控 / 并发状态机**：[DSH Super-agent](https://github.com/deepseek-ai/deepseek-harness) + [SLA (`2610.07625`)](https://arxiv.org/abs/2610.07625) + [Concurrency Control (`2608.18092`)](https://arxiv.org/abs/2608.18092) + [Anthropic Blog](https://www.anthropic.com/research/multi-agent-research-system)
- **想改工造司 / 评测校准 / 观测快照 / 工具自演化**：[RQGM (`2606.26294`)](https://arxiv.org/abs/2606.26294) + [Audit the Scaffold (`2609.34924`)](https://arxiv.org/abs/2609.34924) + [Harness² (`2610.14224`)](https://arxiv.org/abs/2610.14224)
- **想改微观节拍 / 11 类元反思 / 52% 夜科学绿洲**：[The Station v2 (`2610.08927`)](https://arxiv.org/abs/2610.08927) + [AgentDiscover (`2610.05334`)](https://arxiv.org/abs/2610.05334) + [Diversity Collapse (`2604.18005`)](https://arxiv.org/abs/2604.18005)
- **想改图书馆 / 三维盲审 / 院内专题综述 / 脉冲同行工作坊**：[Quantum Swarm (`2611.09822`)](https://arxiv.org/abs/2611.09822) + [The Station v2 (`2610.08927`)](https://arxiv.org/abs/2610.08927) + [ColMAD](https://github.com/LFhase/ColMAD) + [Virtual Lab](https://github.com/zou-group/virtual_lab) + [ProofCouncil (`2607.09474`)](https://arxiv.org/abs/2607.09474) + [Cogentic (`2609.40324`)](https://arxiv.org/abs/2609.40324)
