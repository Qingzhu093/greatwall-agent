# Agent 快速读取导航索引：Stateless Language Agents (arXiv:2610.07625)

> **设计目的**：本目录已将原论文 PDF 与 LaTeX 源码 **100% 无损转换**为结构化纯 Markdown（KaTeX 公式 + 标准 GFM 表格 + 相对路径高清 PNG 配图），并按章节切分为独立分片，以便 Agent 按需精准读取，避免读取二进制 PDF 或检索冗余 `.tex`/`.sty` 源码。

---

## 1. 推荐读取入口（按场景选择）

| 读取需求 | 推荐文件 | 说明 |
| :--- | :--- | :--- |
| **快速掌握核心思想、公式、对比与启示** | [`2610.07625_Stateless_Language_Agents_Scaling_Long-Horizon_Automated_Research_中文综述.md`](./2610.07625_StatelessLanguageAgents_中文综述.md) | 中文精读综述，含直觉类比表、核心战绩表与工程启发 |
| **按章节精准按需阅读原文（最省上下文）** | [`sections/`](./sections/)（见下方分片清单） | 10 个无损原文分片，每个仅 7–274 行 |
| **一次性全文检索 / 全文精读** | [`2610.07625_Stateless_Language_Agents_Scaling_Long-Horizon_Automated_Research_原文解析.md`](./2610.07625_StatelessLanguageAgents_原文解析.md) | 由 10 个分片无损拼接的完整单文件（644 行） |
| **核对原始排版与页码** | [`Stateless_Language_Agents.pdf`](./Stateless_Language_Agents.pdf) | arXiv 官方原版 PDF |

---

## 2. 原文无损分片清单 (`sections/`)

| 分片文件 | 行数 | 字节 | 核心内容与包含的图表 |
| :--- | :---: | :---: | :--- |
| [`01_abstract_and_intro.md`](./sections/01_abstract_and_intro.md) | 38 | 8,854 | 论文元数据、Abstract、Section 1 Introduction、**Figure 1** (`sla_teaser_arxiv.png`) |
| [`02_background_and_motivation.md`](./sections/02_background_and_motivation.md) | 21 | 5,408 | Section 2.1 AutoResearch 相关工作、Section 2.2 长程评测挑战、**Figure 2** (`motivation_arxiv.png`) |
| [`03_sla_framework.md`](./sections/03_sla_framework.md) | 27 | 5,099 | Section 3 SLA 框架、3.1 Harness 上下文重构、3.2 证据驱动派发、3.3 实现与沙箱、**Figure 3** (`workflow_arxiv.png`) |
| [`04_results_and_tables.md`](./sections/04_results_and_tables.md) | 132 | 19,449 | Section 4 实验设置、主结果、消融实验、缩放与成本、**Table 1–6**（全部核心数值表） |
| [`05_discussion_and_limitations.md`](./sections/05_discussion_and_limitations.md) | 11 | 2,422 | Section 5 结论、Post-Training 启示、安全性、Advisor 扩展与局限性 |
| [`06_appendix_related_work.md`](./sections/06_appendix_related_work.md) | 7 | 5,979 | Appendix A 扩展相关工作（Open-ended Discovery / AI Scientists / Self-Improvement Memory） |
| [`07_appendix_impl_and_baselines.md`](./sections/07_appendix_impl_and_baselines.md) | 27 | 6,608 | Appendix B.1 SLA 工程实现细节（Landlock/Modal/Checkpoint）、B.2 EvoX/CORAL/SwarmResearch 基线配置 |
| [`08_appendix_extended_results.md`](./sections/08_appendix_extended_results.md) | 26 | 3,557 | Appendix C.1 等成本 Worker 模型选型（**Figure 4**）、C.2 Epoch 内局部 Trial 数敏感性（**Table 7**） |
| [`09_appendix_trace_analysis.md`](./sections/09_appendix_trace_analysis.md) | 54 | 9,822 | Appendix D 轨迹显微镜：CORAL Lua/libexpat 案例（**Table 8–9**）、SLA 消融轨迹对比（**Figure 5**） |
| [`10_appendix_prompts.md`](./sections/10_appendix_prompts.md) | 274 | 30,839 | Appendix E 完整系统提示词模板：Anthropic Kernel / FrontierSWE / SOL-ExecBench 的 Advisor 与 Worker Prompts（共 6 套） |

---

## 3. 高清配图资产 (`配图/`)

- [`配图/sla_teaser_arxiv.png`](./配图/sla_teaser_arxiv.png) — Figure 1: Anthropic Kernel 曲线与 FrontierSWE 25%/100% 预算反转对比
- [`配图/motivation_arxiv.png`](./配图/motivation_arxiv.png) — Figure 2: 26-Circle Packing 饱和曲线与 CORAL GPU Kernel 后期停滞空转
- [`配图/workflow_arxiv.png`](./配图/workflow_arxiv.png) — Figure 3: SLA 框架（Stateful Search with Stateless Agents）系统架构图
- [`配图/microbenchmark_weak_worker_arxiv.png`](./配图/microbenchmark_weak_worker_arxiv.png) — Figure 4: 等美元成本下 GPT-5.5 vs GPT-5.4 mini Worker 对比
- [`配图/appendix_ablation_trace_analysis_arxiv.png`](./配图/appendix_ablation_trace_analysis_arxiv.png) — Figure 5: libexpat 消融轨迹对比（无指派撞车 vs 完整 SLA 接力）
