# `distributed_agent` 官方仓库框架与工程架构深度解析

> **源码基准**：本文基于官方开源仓库 [`jinlabneurogenomics/distributed_agent`](https://github.com/jinlabneurogenomics/distributed_agent)（本地归档路径：[`notes/distributed_agent/`](./notes/distributed_agent/)）的真实代码与契约文档撰写，所有模块路径、类名、环境变量与约束规则均核自仓库源码。

---

## 一、全局设计哲学：从“单智能体长上下文”到“两阶段冻结语料 + 自适应推理”

在阅读 `distributed_agent` 源码时，最直观的震撼在于它**完全不是一个“把 Prompt 包装成并行脚本”的学术 Demo**，而是一套面向高通量科学发现的**生产级 Agent Harness（智能体脚手架）**。

整个仓库围绕一个核心工程命题展开：**如何让上千个并行 LLM 智能体在面对 10.8 GB 级单细胞扰动数据时，既能深挖局部细节、又不产生幻觉，还能在全局层面被安全、可审计地二次推理？**

为此，仓库将系统清晰地解耦为四大顶层命令面（Command Surfaces，见 `src/distributed_agents/cli/` 与 `src/bioeval/cli/`）：

```text
┌───────────────────────────────────────────────────────────────────────────┐
│  1. 构建层 (distributed_agents build)                                     │
│     • OpenAI Agents SDK + gpt-rosalind-260428                             │
│     • 单靶点并行隔离执行 (ShellTool 只读数据 + WebSearchTool 文献)         │
│     • 输出 7 节科学报告 + 6 个 JSONL 账本 (Fail-Closed Schema 校验)        │
└──────────────────────────────────┬────────────────────────────────────────┘
                                   ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  2. 语料库与服务层 (distributed_agents corpus + MCP Server)                │
│     • 实体归一化 (MGI 6.24 基因符号 + 精确 DOI/PMID 映射)                  │
│     • 冻结发行版：shi (2,046 靶点) / shi_holdout (1,773 靶点)              │
│     • 只读 JSON-RPC/STDIO MCP 服务 + 可选 Neo4j 图投影                    │
└──────────────────────────────────┬────────────────────────────────────────┘
                                   ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  3. 自适应查询与对话层 (distributed_agents query / chat)                   │
│     • 双执行后端：Codex CLI Allowlist 沙箱 (默认) / OpenAI Agents SDK API  │
│     • 双查询模式：adaptive (宿主预诊断 + 连续证据循环) / direct (对照组)    │
│     • 运行时技能：adaptive-query / dataset-orchestrator / corpus-sweep     │
└──────────────────────────────────┬────────────────────────────────────────┘
                                   ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  4. 跨框架评测层 (bioeval)                                                 │
│     • 同台竞技：distributed_agents vs codex vs claude-code vs biomni       │
│     • 防泄密过滤 PubMed MCP (DenyPolicy) + LiteLLM 代理成本核算            │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## 二、阶段一（`build/`）：受控单兵分析与六账本 Fail-Closed 校验

### 1. 执行器隔离与模型配置（`build/runner.py`）

阶段一的入口是 `build_findings_report()`（位于 `src/distributed_agents/build/runner.py`）：
- **专用推理模型**：默认模型环境变量 `DISTRIBUTED_AGENTS_MODEL` 指向 `gpt-rosalind-260428`，并支持通过 `ModelSettings(reasoning=Reasoning(effort=...))` 显式控制推理深度。
- **最小权限沙箱**：智能体仅挂载两个工具：`ShellTool` 与 `WebSearchTool`。其中 `make_local_shell_executor(readable_roots=(parquet_path, *skill_dirs), writable_dir=run_dir)` 将原始 Parquet 数据集与技能目录严格设为**只读根目录**，仅允许向目标 `run_dir` 写入产物，并在 `tool_calls.jsonl` 中完整记录每次工具调用。
- **契约哈希溯源**：运行清单（`run.json`）与追踪元数据（`trace_metadata`）会强制写入 `report_prompt_sha256`、`base_contract_sha256` 与 `appendix_schema_sha256`，确保任何一次提示词或 Schema 变动都可被精确审计。

### 2. 六账本结构化校验（`build/validation.py`）

为了防止自然语言报告在下游聚合时发生“引用漂移”或“凭空编造”，`validation.py` 对每份报告末尾的 `Structured Appendix` 执行 **Fail-Closed（失败即阻断，但保留诊断信息）** 校验：

1. **Schema 防篡改**：加载 `legacy_findings_appendix.schema.json` 前先核对硬编码的 SHA-256 指纹（`e4e4de66...`），随后使用 `Draft202012Validator` 校验字段类型。
2. **严格有序解析**：必须按固定顺序包含 6 个 `jsonl` 代码块：
   - `Evidence JSONL`（`[E###]`）：仅记录数据集实测事实；
   - `References JSONL`（`[R###]`）：仅记录文献来源；
   - `Biological Findings JSONL`（`[F###]`）：解释性发现；
   - `Literature Comparisons JSONL`（`[C###]`）：文献比对；
   - `Pathways JSONL` & `Cell Type Specificity JSONL`：派生聚合视图。
3. **跨账本语义链接检查（`_semantic_errors`）**：
   - 所有 `evidence_id`、`ref_id`、`finding_id`、`comparison_id` 必须全局唯一；
   - 每条 `Biological Finding` 引用的 `evidence_ids` 和 `ref_ids` 必须真实存在于前两个账本中；若 `literature_status` 不为 `None` 或 `"novel_no_direct_literature"`，则**必须**至少引用 1 个 `ref_id`；
   - `Pathways` 与 `Cell Type Specificity` 仅可引用已存在的 `finding_id`，严禁在派生视图中偷渡新结论。

### 3. 确定性实体归一化（`normalization.py` & `reference_normalization.py`）

构建完单个靶点报告后，仓库并不依赖 LLM 自己去对齐基因别名或文献 ID，而是用确定性脚本完成清洗：
- **基因符号归一化**：消费本地固定 SHA-256 的 MGI 6.24 `MRK_List1.rpt.gz`，显式输出 `official-symbol`、`withdrawn-symbol`、`synonym`、`ambiguous`、`unmapped` 五类结果，绝不隐式联网拉取可变词表。
- **文献引用归一化**：基于精确标识符（DOI / PMID / PMCID / Europe PMC MED/PMC 定位符）建立映射账本，排除检索页或法规页 URL，保留冲突与未解析条目，**绝不篡改原始不可变引用记录**。

---

## 三、语料库与只读 MCP 层（`corpus/`）：把报告变成“可计算图谱”

经过校验与归一化的数千份报告被打包为自包含的 **Corpus Release**（仓库内置 `shi` 2,046 靶点与 `shi_holdout` 1,773 靶点两个发行版，通过 `release.json` 清单管理）。

### 1. 只读 MCP 服务（`corpus/mcp/application.py` & `service.py`）

`McpApplication` 通过标准 JSON-RPC/STDIO 协议向外部 AI 助手（如 Codex CLI）或阶段二查询智能体暴露受 `CapabilityPolicy` 权限控制的只读工具：
- **`query_ledger` / `resolve_evidence`**：按靶点基因、类型或局部 ID 精确检索账本，并将返回的 `E###`/`R###` 解析为原始实测证据与文献条目（注意：`Local IDs are target-gene scoped`）。
- **`search_findings`**：基于 BM25 的概念级检索，并在指令中明确警示智能体：**BM25 排名仅代表检索相关性，绝非生物学重要性排序**。
- **`query_claims` / `related_targets`**：访问经由自底向上聚合形成的 `Claim` 层；`related_targets` 支持单锚点直接证据路径以及 1–20 个靶点的**等权随机游走重启（Random Walk with Restart, RWR）**，同样显式声明其平稳概率仅代表“图可达性（graph reachability）”，而非生物学排名。
- **`suggest_target_analogs`**：当用户查询的鼠源基因不在语料库中时，从冻结的 CORUM 复合物、通路、GO 功能与 STRING 物理互作证据中交叉提名类比靶点，但不输出预测结果或聚合相似分。

---

## 四、阶段二（`query/`）：宿主预诊断 + 自适应科学推理引擎

阶段二是整个仓库中最具架构巧思的部分。不同于常见的“给 Agent 一个问题和几个工具就让它自由发挥”，`distributed_agents query` 提供了 **`adaptive`（默认）** 与 **`direct`（无预诊断对照组）** 两种模式，默认支持 **Codex CLI 沙箱后端**（`query/backends/codex.py`）与 **OpenAI Agents SDK 直接 API 后端**（`query/backends/api.py`）。

### 1. 宿主预准备阶段（`query/adaptive.py`）

在推理模型看到用户问题之前，宿主（Host）先执行一系列确定性诊断并将结果注入 `<runtime>` 上下文：
1. **`task_bindings.json`**：解析任务中的实体集合，严格保留其 `ranked`（全排序）、`partial_ranked`（部分排序）或 `unranked`（无序）语义，防止智能体把无序列表的文件行号误当作监督排序信号。
2. **`coverage` 紧凑覆盖度摘要**：预先告知智能体哪些靶点在语料库中有报告、哪些缺失，避免智能体盲目翻找。
3. **`capability_manifest.json`**：只暴露当前 Release 与策略允许的能力入口，并附带 `accepted_arguments`、`example` 和 `output_bound`（输出上限），防止智能体在普通发现阶段反复执行 `--help` 浪费上下文。
4. **Loopback Relay 探活**：若运行在无外网沙箱中，宿主预先探测 Neo4j HTTP 服务健康度（`_neo4j_runtime_readiness`），并通过本地回环中继暴露给沙箱内的模型。

### 2. 不可违背的科学不变量（`adaptive_query_contract.md` & `adaptive_query_scientific_policy.md`）

在提示词层面，阶段二强制嵌入了极高水准的“科研方法论护栏”：
- **图谱仅作导航，严禁图拓扑打分**：明确规定关系图谱、路径、度数、共有靶点数、BM25 排名与嵌入相似度**永远不能**直接作为生物学候选分数或最终排序依据。
- **同源隔离原则（Source Isolation）**：明确提醒智能体——**Parquet 原始差异表达数据与 Claim/Finding 语料库是“同一实验的两种表征”，而不是两次独立的实验重复**。
- **紧致因果迁移链（Causal Transfer Chain）**：当试图将 A 基因的观测结果迁移推演到相关基因 B 时，智能体必须显式走完一条 6 步因果链：
  $$\text{Intervention} \rightarrow \text{Molecular Consequence} \rightarrow \text{Complex/Pathway Propagation} \rightarrow \text{Exposure/Selection} \rightarrow \text{Sampling/Survivorship} \rightarrow \text{Measured Endpoint}$$
  只有在共同受损于同一限速功能且因果方向一致时才允许正向迁移；若拒绝迁移，必须指出链条中具体断裂的环节，而不能笼统以“细胞类型不同”搪塞。
- **防偏置预测性图审（`corpus.predictive_graph_review`）**：当待预测的终点指标在输入数据中完全缺失时，智能体先基于定量特征建立排序基线，再调用 `nominate` 联合“定量 top-k”与“图挑战者（`graph_only_challenger`）”组成裁决并集。**关键细节在于：`nominate` 返回的序列化列表有意隐藏了旧的 Finding 总结文本**，强迫智能体必须通过独立证据（`evidence_read=true`）而非轻信先验摘要来做出晋升/淘汰裁决，并在冻结答案后调用 `finalize` 记录完整遥测审计日志。

---

## 五、技能生态（`skills/`）：40+ 生信工具与确定性全量清扫器

仓库的 `src/distributed_agents/skills/` 目录下沉淀了三层技能体系：
1. **`skills/life-sciences/`（40+ 外部数据库技能）**：涵盖 AlphaFold、Bgee、BindingDB、ChEMBL、CIViC、ClinicalTrials、ClinVar、ENCODE、Ensembl、eQTL Catalogue、FinnGen/UKB/BiobankJapan PheWAS、gnomAD、OpenTargets、QuickGO、Reactome、RCSB PDB、STRING、UniProt 等，由 `research-router-skill` 作为统一路由入口，并附带标准化的 `scripts/rest_request.py` 或 GraphQL 客户端。
2. **`skills/runtime/adaptive-query-skill` & `dataset-orchestrator-skill`**：提供 `coverage_probe.py`、`perturbseq_feature_workbench.py`（特征汇总与留一交叉验证校准）以及 `validate_plan.py` 等运行时辅助脚本。
3. **`skills/runtime/exhaustive-corpus-sweep-skill`（受控全量清扫子智能体框架）**：
   - 当任务明确要求对整个语料库进行“无遗漏逐单元语义审查”时才激活（普通聚合或 top-k 检索禁止激活）。
   - 采用严格的 **Coordinator -> Bounded Readers -> Reduction** 模式：受环境变量 `DISTRIBUTED_AGENTS_MAX_CONCURRENT_SUBAGENTS`（最大并发数）与 `DISTRIBUTED_AGENTS_MAX_SUBAGENTS`（含重试在内的最大启动次数）硬性约束；所有切片计划（`sweep_plan.schema.json`）、切片输出（`slice_result.schema.json`）与全局对账（`sweep_audit.schema.json`）均通过预设脚本与 JSON Schema 校验，**若预算不足覆盖全部切片，直接禁止启动或禁止宣称“全量完成”**。

---

## 六、评测基础设施（`bioeval/`）：防作弊、防时间穿越与成本对齐

在 `src/bioeval/` 中，研究团队构建了一套让 `distributed_agents` 与 `codex`、`claude-code`、`biomni` 同台公平竞技的评测 Harness，其中两个工程细节尤为值得借鉴：

1. **防时间穿越 / 防泄密文献过滤服务器（`bioeval/runtime/filtered_search_server.py`）**：
   - 在评测“无手稿复现原论文结论”或“留出集预测”时，如果直接给智能体开放通用 `WebSearchTool` 或任意 URL 抓取，智能体极易直接搜到原论文手稿或后续引用文章导致“数据泄露”。
   - 为此，`bioeval` 用纯 Python 标准库实现了一个极简 Streamable HTTP MCP 服务器（`bioeval-filtered-literature`），仅代理 NCBI E-utilities PubMed 检索，并内置 `DenyPolicy`：对标题、摘要与元数据进行标点/大小写归一化（`_plain()`）后匹配黑名单模式，彻底封堵原论文手稿与泄密信息源。
2. **全链路成本代理（`bioeval/accounting/proxy.py`）**：
   - 通过集成 `litellm-proxy` 与回调统计，在统一口径下精确记录每个框架的请求次数、输入/输出 Token 及美元花费，为论文中“时间-成本前沿对比图（Fig. 2D）”提供了可复现的审计数据。

---

## 七、总结：对工程化 Multi-Agent Harness 设计的三大核心启示

1. **契约先行，账本兜底**：在长程科研任务中，自由文本的“总结”是不可靠的；通过 **Prompt 契约 + 6 账本 JSONL + SHA-256 防篡改 Schema + 跨账本 ID 强引用校验**，才能把 LLM 的输出变成可组合、可审计的工程资产。
2. **把“记忆隔离”和“盲审防偏置”写进运行时代码**：无论是 `adaptive.py` 对实体排序语义的保护、`predictive_graph_review` 刻意隐藏旧 Finding 摘要防诱导，还是 `filtered_search_server.py` 对 PubMed 检索的 `DenyPolicy` 过滤，都体现出“**不能只靠 Prompt 叮嘱模型别作弊，而要在运行时接口层做物理隔离**”的硬核工程思维。
3. **动态路由与预算硬上限**：从单进程连续证据循环（`adaptive`）到受严格并发/重试预算约束的 `exhaustive-corpus-sweep-skill`，系统始终遵循“**能用确定性 SQL/Parquet/MCP 工具一步查清的，绝不启动多智能体**”的奥卡姆剃刀原则——这正是大规模多智能体系统能够兼顾 32 分钟极速与可控成本的根本原因。
