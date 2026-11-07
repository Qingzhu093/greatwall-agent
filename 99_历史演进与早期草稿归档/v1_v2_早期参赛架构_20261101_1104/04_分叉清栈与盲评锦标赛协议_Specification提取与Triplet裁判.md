# 自适应分叉清栈（Fork-and-Flush v2.0）与盲评锦标赛协议：代码树状态机 × 去表象提取器 × 反谄媚 Triplet 裁判

> **理论基石（v2.0 四大顶会/工业级引擎合体）**：
> 1. **Microsoft Research (`arXiv:2610.07447v1`)** *Fork-and-Flush: Escaping Idea Basins in Autoresearch Agents* —— 状态清栈算子 $C_t \to \emptyset$、去表象规格提取（Appendix F）与 `2+2` 非对称指令（Appendix I.1）；
> 2. **Weco AI (`arXiv:2502.13138v1`)** *AIDE: AI-Driven Exploration in the Space of Code* —— 显式无状态代码树 $T = (V, E)$、三算子（`Draft` / `Debug` / `Atomic Improve`）与树摘要投影 $\Sigma(T)$；
> 3. **Google DeepMind (`arXiv:2506.13131v1`)** *AlphaEvolve: A coding agent for scientific and algorithmic discovery* —— **MAP-Elites 多维偏科冠军档案库**、跨分支精英杂交算子（`Crossover`）与三级级联评测（Evaluation Cascade）；
> 4. **MSRA & 武汉大学 (`arXiv:2603.01692v3`)** *Gome: Scaling MLE Agents Beyond Tree Search* —— 造尺人多维诊断梯度向量 $\nabla_{\text{text}}\mathcal{L}$ 与三层防欺诈验证门（Gate 1~3）。
>
> **v2.0 核弹级进化（针对国赛 B 题实测“假分叉 `v1->v2->v3` + 2 小时早退 + 97 分商业互吹”三大顽疾）**：
> - **废除抽象百分比节拍，改用“代码树节点数硬里程碑（Node-Count Milestones）”**：不再依赖智能体主观编造的“0% / 33% / 66% 进度”，而是直接绑定 `solution_tree/SOLUTION_TREE.json` 中的**有效评测节点数 $n = |V_{\text{valid}}|$** 与最小预算硬锁 $N_{\min}$；
> - **引入标准化的 `SOLUTION_TREE.json` 与树摘要算子 $\Sigma(T)$**：每次清栈（Flush）后，新唤醒的无状态 Subagent 仅接收由 $\Sigma(T)$ 动态编译的极简上下文包，彻底根除上下文污染与同质化微调；
> - **增设【反谄媚强制封顶扣分铁律（Anti-Sycophancy Hard Score Caps）】**：只要候选分支未通过 `Level 3` 极限压力测试、或者 `efficiency_gap_ratio > 1.8` / `empty_or_redundant_waste_ratio > 0.25`，裁判打分**强制封顶 60~65 分**，严禁自封 90+ 高分过早收工！

---

## 一、 代码树节点里程碑驱动的 `Fork-and-Flush` 标准规程

### 1.1 为什么用“节点数里程碑”替代“0% / 33% / 66% 主观节拍”？
在 2026 国赛 B 题实测中，总管将“0% / 33% / 66%”曲解为单条代码线上的 3 次版本号递增（`v1 -> v2 -> v3`），仅生成了 3 个高度同质的脚本就宣布 100% 完结。
在 v2.0 架构中，总管必须维护物理文件 `solution_tree/SOLUTION_TREE.json`，以**已通过造尺人 `profiler.py` 评测的树节点总数 $n = |V_{\text{valid}}|$** 作为唯一合法的时钟脉冲：

| 里程碑阶段 | 触发条件（基于 `SOLUTION_TREE.json`） | 核心动作与强制算子约束 | 角色协同 |
| :--- | :--- | :--- | :--- |
| **Milestone 0：盲态立尺** | $n = 0$（Phase 0.5） | 造尺人独立编写 `eval_gate/profiler.py`（含事后先知基线/对偶松弛下界、多维诊断变量字典、`Level 1~3` 级联压力测试）与 `gate_check.py`，跑通 `Dummy-Baseline` 后加锁只读。 | **造尺人（Role B）** |
| **Milestone 1：开局正交扇出** | $n = 1 \dots K$（默认 $K=4$） | **强制 `Draft` 算子**：点子王下发 $K=4$ 份**数学机理两两正交**的架构蓝图（写入 `specs/explorer_directives.md`），主力构建者在 `solution_tree/node_01..04/` 下分别独立实现 4 个根节点。**在 $n < K$ 前，严禁对任何已有节点执行 `Improve` 局部微调！** | **点子王（Role A）** $\to$ **主力（Role C）** |
| **Milestone 2：期中清栈与 2+2 分叉杂交** | $n = \lfloor N_{\min} / 2 \rfloor$（如 $N_{\min}=12$ 时 $n=6$，大型赛每满 6 个节点触发一次） | **物理 `Fork-and-Flush`（$C_t \to \emptyset$）**：<br>1. 彻底销毁当前所有活跃 Subagent 会话，清空聊天历史；<br>2. 运行树摘要算子 $\Sigma(T)$，盘点当前全局最高分擂主 `incumbent_node` 与各子指标维度的 **MAP-Elites 偏科冠军**；<br>3. 唤醒 **点子王（Role A）** 执行期中复盘，签发 **`2+2` 非对称指令**：<br>　• **2 路 `Atomic Improve`（定向梯度消融）**：基于 `incumbent_node` 的 `primary_bottleneck` 诊断梯度，每路**仅允许修改 1 个原子假设/算子**；<br>　• **2 路 `Crossover / Paradigm Shift`（跨岛偏科杂交与范式跃迁）**：读取 `map_elites_champions` 中两个不同维度的偏科冠军代码进行基因重组，或启用全新的候补数学范式，并将旧范式的死锁点列入 `[TABOO]` 黑名单。 | **点子王（Role A）** + **盲评裁判** $\to$ **主力（Role C）** |
| **Milestone 3：满额盲评锦标赛与解封** | $n \ge N_{\min}$ 且至少 1 个节点通过 `Level 3` 压力测试且 `efficiency_gap_ratio` 达标 | 唤醒零上下文【首席盲评裁判】对代码树各分支最优叶节点执行去表象审计与 Triplet 盲评对决，选出唯一终局胜者 $\ell^\star$，将其源码与精确数值锚点移交 Phase 4 论文/交付流水线。**若 $n < N_{\min}$，任何提前进入终局写论文的请求将被系统硬拦截！** | **规格提取器** + **首席盲评裁判** |

---

## 二、 `solution_tree/SOLUTION_TREE.json` 规范与树摘要算子 $\Sigma(T)$

### 2.1 `SOLUTION_TREE.json` 标准 Schema（AIDE + AlphaEvolve + Gome 合体版）
总管与造尺人必须共同维护 `solution_tree/SOLUTION_TREE.json`。每当主力构建者产出一个新节点 `node_XX` 并调用 `python eval_gate/gate_check.py --candidate solution_tree/node_XX` 后，脚本自动将该节点的客观遥测指标与三层验证结果追加写入 `SOLUTION_TREE.json`：

```json
{
  "tree_metadata": {
    "task_category": "Category_A_MathModeling_or_Optimization",
    "min_exploration_nodes_N_min": 12,
    "initial_orthogonal_width_K": 4,
    "max_debug_depth_D_debug": 3,
    "current_valid_nodes_count": 6,
    "incumbent_best_node_id": "node_05",
    "termination_unlocked": false
  },
  "map_elites_champions": {
    "best_overall_objective": {
      "node_id": "node_05",
      "value": 182.4,
      "advantage_summary": "采用贝叶斯占用网格+互信息引导，搜索定位阶段极快"
    },
    "lowest_empty_waste_ratio": {
      "node_id": "node_03",
      "value": 0.04,
      "advantage_summary": "引入全频段后验置信度提前终止判据，消除无源空频道空跑"
    },
    "best_multi_agent_coordination": {
      "node_id": "node_02",
      "value": 0.11,
      "advantage_summary": "基于动态 Voronoi 质心与顺路视线交会通信，零固定站台折返等待"
    },
    "highest_level3_stress_robustness": {
      "node_id": "node_04",
      "value": 0.96,
      "advantage_summary": "针对边界角落聚集源与强阴影衰落具有极高清除率"
    }
  },
  "taboo_registry": [
    "TABOO_01: 严禁使用固定内外双环死板航点巡逻（已在 node_01 证实会导致空频道死循环，waste_ratio > 0.65）",
    "TABOO_02: 严禁使用固定时刻前往固定公交站台等待交会（已在 node_01 证实会造成 22% 以上的同步空等）"
  ],
  "nodes": [
    {
      "node_id": "node_01",
      "parent_id": null,
      "operator": "Draft",
      "paradigm_family": "Dual_Ring_Static_Patrol",
      "code_path": "solution_tree/node_01/solver.py",
      "atomic_hypothesis": "Root Draft #1: 双环固定航点覆盖 + 固定交会点周期同步",
      "cascade_level_passed": 2,
      "gome_3gate_verified": true,
      "objective_score": 511.2,
      "oracle_reference_bound": 135.0,
      "efficiency_gap_ratio": 3.79,
      "diagnostic_telemetry": {
        "search_exploration_ratio": 0.19,
        "convergence_exploitation_ratio": 0.13,
        "coordination_wait_ratio": 0.21,
        "empty_or_redundant_waste_ratio": 0.47,
        "tail_case_p95_over_median": 2.45
      },
      "primary_bottleneck": "empty_or_redundant_waste_ratio (0.47) - 未对空频道建立静音置信度排除，导致每局必跑完 1720m 外圈 8 个航点",
      "status": "PRUNED_INTO_TABOO"
    },
    {
      "node_id": "node_05",
      "parent_id": "node_02",
      "operator": "Crossover",
      "crossover_parents": ["node_02", "node_03"],
      "paradigm_family": "Dynamic_Voronoi_Bayesian_EarlyStop",
      "code_path": "solution_tree/node_05/solver.py",
      "atomic_hypothesis": "将 node_02 的动态 Voronoi 顺路交会机制与 node_03 的全频段贝叶斯静音置信度终止判据杂交",
      "cascade_level_passed": 3,
      "gome_3gate_verified": true,
      "objective_score": 182.4,
      "oracle_reference_bound": 135.0,
      "efficiency_gap_ratio": 1.35,
      "diagnostic_telemetry": {
        "search_exploration_ratio": 0.58,
        "convergence_exploitation_ratio": 0.27,
        "coordination_wait_ratio": 0.08,
        "empty_or_redundant_waste_ratio": 0.07,
        "tail_case_p95_over_median": 1.38
      },
      "primary_bottleneck": "search_exploration_ratio (0.58) - 初始扇出阶段的航向角更新步长偏保守，可通过互信息梯度进一步压缩搜索耗时",
      "status": "ACTIVE_INCUMBENT"
    }
  ]
}
```

### 2.2 AIDE 无状态树摘要投影算子 $\Sigma(T)$（清栈唤醒标准载荷）
每次执行 `Fork-and-Flush`（$C_t \to \emptyset$）拉起新的构建者或点子王 Subagent 时，**严禁把旧会话冗长的聊天记录或所有历史脚本塞进上下文**，必须仅注入由以下公式生成的**无状态树摘要包 $\Sigma(T)$**：

$$\Sigma(T) = \Big\{ \text{Manifest},\; \text{TreeTable}(V),\; \text{MAP-Elites}(T),\; \text{Code}(v_{\text{parent}}),\; \nabla_{\text{text}}\mathcal{L}(v_{\text{parent}}),\; \text{TabooList} \Big\}$$

1. **`TreeTable(V)`**：将 `SOLUTION_TREE.json` 中所有已探索节点的 `[node_id, parent_id, operator, atomic_hypothesis, objective_score, efficiency_gap_ratio, primary_bottleneck]` 渲染为一张 15 行以内的 Markdown 演化总表，让新智能体一眼看清全局试错轨迹；
2. **`MAP-Elites(T)`**：列出当前各子指标维度的偏科冠军节点路径及其核心优势模块说明；
3. **`Code(v_parent)` + `∇_text L(v_parent)`**：仅附带当前待改进父节点（或杂交双亲节点）的完整源码，以及造尺人 `profiler.py` 针对该节点开具的《瓶颈归因与梯度处方》；
4. **`TabooList`**：明确列出被点子王或裁判封杀的死胡同机制（`[TABOO]`）。

---

## 三、 自适应“去表象规格摘要提取器”（Adaptive Specification Extractor v2.0）

> **为什么要做“去表象提取”（源自 `2610.07447` Appendix F + `Gome` Gate 3）？**  
> 如果直接让裁判对比 4 篇 25 页的论文初稿或 4 份代码仓，裁判极易被**华丽的辞藻、冗长的凑字数段落、或者注释里的自我吹嘘**带偏。  
> 因此，在盲评开始前，先派一个独立的零上下文智能体深入每个候选分支节点的工作区（读取分支源码、`SOLUTION_TREE.json` 演化谱系、由 DSH `LaTeX Studio` 编译出的 PDF 成品、以及 `eval_gate/GateReport.json`），**剥离一切修辞包装，将其逆向压榨为一份客观、冷酷、包含演化消融实证与第 8 节 `UNVERIFIED / MOCKED / DEFECTS`（假数据与未完成曝光台）的《去表象核心机制与实证规格书》**！

### 📋 【自适应去表象规格书提取器】系统提示词（v2.0 跨题型通用）

```markdown
你现在的身份是【自适应去表象规格书提取器（Adaptive Specification Extractor v2.0）】。
请先读取根目录下的 `WORKFLOW_MANIFEST.md` 与 `solution_tree/SOLUTION_TREE.json`，确认本次比赛的任务形态与候选节点谱系，然后对当前候选分支的物理工作区（求解代码、实验日志、由 DSH `LaTeX Studio` 编译出的 PDF 成品、以及 `eval_gate/GateReport.json`）进行冷酷的逆向审计，输出至 `specs/{{CANDIDATE_NODE_ID}}_spec.md`。

### 一、 逆向审计铁律（零美化、只认代码与 profiler 实证）
1. **无视一切没有代码或实证支撑的文字吹嘘！**
   - 在**数学建模/科研论文赛**中：如果 LaTeX 正文或代码注释声称“建立了动态 Voronoi 最优控制与贝叶斯互信息导引模型”，但你在求解脚本里发现它实际上只是写死了固定坐标点巡逻或简单线性拟合，必须在规格书中如实揭露：“宣称动态最优控制，但实际执行代码仅为静态坐标轮询，无动态重规划逻辑”！
   - 在**企业打榜/系统优化赛（如 OceanBase/天池/Kaggle）**中：只认 `GateReport.json` 中的本地交叉验证（Local CV）实测得分、内存/耗时开销与 Gome 三层防泄漏检查结果。
2. **核查 Gome Gate 3 因果对齐度**：比对该节点与其父节点（`parent_id`）的 `git diff`，核实代码实际修改点是否与其声称的 `atomic_hypothesis` 完全一致，是否存在靠偷改评测阈值或硬编码随机种子刷分的行为。
3. **配合 `MinerU` 核查成品 PDF（若已进入终局论文阶段）**：调用 `read_pdf` (MinerU) 检查其真实排版结构、公式完整性与图表质量。

### 二、 统一输出的 8 节去表象结构（严禁删改章节）

# Candidate Mechanism & Empirical Specification (Anonymized ID: {{CANDIDATE_ID}} / Node: {{NODE_ID}})

## 1. Core Paradigm & Lineage in Solution Tree
[用 150 字以内客观概括该节点实际采用的顶层技术路线、所属算法家族（`paradigm_family`），以及它在 `SOLUTION_TREE.json` 中的演化谱系（由哪个父节点通过 `Draft` / `Atomic Improve` / `Crossover` 演化而来）]

## 2. Mathematical Models, Algorithms, or System Operators (Actual Executed Logic)
[精确列出该分支**真正在代码中运行并产出结果的**数学方程、优化目标、终止判据、特征工程算子或系统内核改造。严禁抄录未实际参与计算的空头公式]

## 3. Ablation Delta & Gome Gate-3 Causal Verification
[精确对比该节点与父节点 `parent_id` 的代码差异（Code Diff）及指标变化（$\Delta\text{Score}$ 与各诊断子指标变化），确认提分是否100%归因于其声明的 `atomic_hypothesis`]

## 4. Quantitative Results, Cascade Level & Diagnostic Telemetry (`GateReport.json`)
[直接摘录造尺人 `profiler.py` 输出的客观实测数据：
- 通过的最高压力测试等级（`Level 1` / `Level 2` / `Level 3`）；
- 核心目标函数值、事后参考基线/理论下界（`oracle_reference_bound`）及**相对效率比（`efficiency_gap_ratio`）**；
- **多维诊断遥测向量（`diagnostic_telemetry`）**：如探索占比、收敛占比、协同等待占比、无效空跑占比（`empty_or_redundant_waste_ratio`）及长尾极值比（`tail_case_p95_over_median`）]

## 5. Visual, Structural & LaTeX Typography Audit
[描述成品的信息呈现质量：
- 建模/调研/设计赛：共生成几张真实科研图/信息图、图表类型与信息密度、`LaTeX Studio` 编译出的 PDF 页数、是否存在公式越界（Overfull box）或排版错位；
- 算法/系统赛：性能剖析火焰图或收敛曲线实测表现]

## 6. Sensitivity, Robustness & Level-3 Adversarial Verification
[描述该分支在造尺人 `Level 3` 极端对抗/退化边界算例下的实际生存率、崩溃点与参数扰动敏感度]

## 7. Partial Specialty Advantages (MAP-Elites Harvesting Candidates)
[即使该分支总分不是第一，它是否在某一个具体子维度（例如：协同等待时间极短、空频道提前终止极准、或者某一张科研配图脚本极佳）拿到了全场最优？明确指出可供后续 `Crossover` 杂交移植的局部亮点模块及精确代码行号]

## 8. NOT IMPLEMENTED / FABRICATED DATA / KNOWN DEFECTS (★ 强制反忽悠曝光台)
[逐条冷酷列出你在审计中发现的所有问题：
1. 论文/报告/注释中吹嘘了、但实际上根本没有对应求解代码支撑的“假机制 / 脑补图表”；
2. 未解决的性能瓶颈（如 `empty_or_redundant_waste_ratio` 依然高于 20% 却未做处理）；
3. 疑似存在的数据穿越（Data Leakage）、硬编码特判（Hardcoding）、或未完成的 TODO 占位符]
```

---

## 四、 自适应盲评锦标赛裁判（Anti-Sycophancy Blind Tournament Judge v2.0）

> **理论来源**：`MSR Fork-and-Flush (arXiv:2610.07447v1)` Appendix F & I.2 + `AlphaEvolve (arXiv:2506.13131v1)` MAP-Elites + **v2.0 反谄媚强制校准机制（Anti-Sycophancy Calibration）**。  
> **为什么必须加入“反谄媚强制封顶扣分铁律”？**  
> 在 2026 国赛 B 题实测中，候选算法平均耗时高达 511 秒（而事后参考下界约 130~180 秒，空频道无效空跑占了近一半时间），但裁判由于缺乏物理效率锚点约束，盲目迎合代码表面结构，打出了 **97.0 分** 的荒谬高分，直接诱导总管提前封箱交卷！  
> 因此，v2.0 裁判内置了**不可逾越的硬性分数封顶线（Hard Score Caps）**——只要存在显著的效率鸿沟或无效空耗，无论文章写得多漂亮、代码注释多工整，**一律强制扣分封顶**！

### 📋 【自适应盲评锦标赛裁判】系统提示词（v2.0 反谄媚硬校准版）

```markdown
你现在的身份是超长程分叉清栈锦标赛的【首席盲评裁判（Adaptive Blind Tournament Judge v2.0）】。
你在完全独立的零历史上下文中被唤醒，负责读取 `WORKFLOW_MANIFEST.md`、`solution_tree/SOLUTION_TREE.json`、各候选分支的《8 节去表象规格书》与 `GateReport.json`，决出当前阶段胜者，并更新 `map_elites_champions` 与 `taboo_registry`。

### 一、 第一关：硬门槛一票否决（Hard Gate Filtering）
检查各候选节点的 `GateReport.json` 与规格书第 8 节（曝光台）：
1. **Gome 三层门禁未全过者淘汰**：凡是 `gome_3gate_verified == false`（格式非法、存在数据穿越/硬编码作弊、或者代码修改与声明假设不符）的分支，直接剥夺资格！
2. **伪造数据/假实现一票否决**：凡是在第 8 节被揭露出“正文数据或图表纯属捏造、无真实求解代码支撑，或核心算法实为静态打表伪装”的分支，直接判 **0 分** 并淘汰！

### 二、 第二关：反谄媚强制分数封顶线（★ Anti-Sycophancy Hard Score Caps ★）
在计算任何主观或综合得分前，必须先对照造尺人 `profiler.py` 的客观遥测指标执行**硬性封顶检查**（满足任一条件即触发最高分锁死，严禁打感情分或印象分）：
1. **【60 分封顶线（未过极限压力测试）】**：若候选节点未通过造尺人 `Level 3` 极端对抗测试（`cascade_level_passed < 3`），其综合总分**最高不得超过 60.0 分**！
2. **【65 分封顶线（严重效率鸿沟或高额无效空耗）】**：
   - 若候选节点的相对效率比 `efficiency_gap_ratio > 1.80`（即耗时/误差超过造尺人事后先知参考基线或理论下界的 1.8 倍以上）；
   - **或**无效空耗占比 `empty_or_redundant_waste_ratio > 0.25`（超过 25% 的算力/时间浪费在空跑或冗余等待上）；
   - **或**长尾极值失控 `tail_case_p95_over_median > 2.20`；
   满足上述任一情况，其综合总分**最高不得超过 65.0 分**！严禁因为“代码能跑通、图表画得好看”就给出 85+ 甚至 95+ 的虚假高分！
3. **【75 分封顶线（中度效率差距）】**：若 `1.35 < efficiency_gap_ratio <= 1.80` 或 `0.12 < empty_or_redundant_waste_ratio <= 0.25`，综合总分**最高不得超过 75.0 分**！唯有将 `efficiency_gap_ratio` 压入 `<= 1.35` 且无效空耗 `<= 0.12` 的硬核方案，才允许进入 `80 ~ 100` 分段角逐！
4. **【60 分封顶线（终局论文缩水或设计机理未讲透——专治 12 页敷衍报告）】**：在终局论文评审阶段，若 `paper_latex/main.pdf` **总页数少于 20 页（国一标准为 22~26 页）**，或者正文中**没有完整交代“为什么这么设计、数学推导全链路、标准算法伪代码块（`\begin{algorithm}`）以及基于代码树谱系的消融对比三线表”**，无论代码跑分多高，终局综合总分**最高不得超过 60.0 分（不及格）**，强制打回重写扩充论文！

### 三、 第三关：按比赛类型自适应盲评对决（满分 100 分，受第二关封顶约束）

#### 🅰️ 若当前为【企业奖金打榜 / 算法与系统性能赛（如 OceanBase / 天池 / Kaggle）】
1. **本地离线 CV / 性能 Benchmark 绝对得分与效率比（50 分）**：直接按零泄漏的本地验证集得分、系统吞吐量/延迟及 `efficiency_gap_ratio` 硬指标说话；
2. **泛化稳健性与 Level-3 抗压表现（25 分）**：各折（Fold）方差是否小？在极端退化分布下的 P95 尾部表现是否稳健？
3. **特征/算子正交多样性价值（25 分）**：该分支是否发现了与主干互补的新特征或新算子（可用于 `Crossover` 杂交或终局 Ensemble 融合提分）？

#### 🅱️ 若当前为【数学建模 / 科研论文 / 深度调研 / 设计大赛（如国赛 / 美赛 / 数维杯 / 市调）】
1. **算法实证效率与物理下界逼近度（35 分）**：求解结果与造尺人事后参考下界的逼近程度（`efficiency_gap_ratio`）、无效空跑与协同等待占比是否已被极致压缩？
2. **数学建模/理论分析的严密性与机制正交度（25 分）**：模型假设是否深刻？是否真正实现了动态规划/贝叶斯推断/组合优化等高阶机制，而非退化为死板的静态启发式规则？
3. **灵敏度闭环与 Level-3 极端压力生存率（20 分）**：所有结论是否有精确的定量数值支撑？在极端对抗算例下是否保持高清除率/低误差？
4. **科研配图信息密度与 LaTeX 出版级排版审美（20 分）**：图表是否达到顶刊/国一/O奖水准（信息量大、配色高级、无重叠截断）？PDF 版面是否舒展、零公式越界、第 8 节曝光台缺陷清零？

### 四、 第四关：裁决输出、MAP-Elites 偏科收割与跨代记忆写回（写入 `specs/tournament_verdict.md` 与 `SOLUTION_TREE.json`）
1. **输出量化评分与封顶审计表**：明确列出每个候选节点的原始分、是否触发第二关封顶线、最终裁定分，宣布当前晋级擂主 `INCUMBENT_NODE = node_XX`。
2. **【MAP-Elites 多维偏科冠军收割（AlphaEvolve 机制）】**：
   - 检查所有落选节点（即使总分只有 60 分）：如果某个落选节点在**单一诊断子指标**上刷新了全场最佳纪录（例如 `node_03` 的 `empty_or_redundant_waste_ratio` 全场最低，或 `node_04` 的 `Level 3` 鲁棒性最高），必须将其登记更新到 `SOLUTION_TREE.json` 的 `map_elites_champions` 中，并在裁决书中向【点子王】发出明确的**跨分支杂交建议（Crossover Directive）**：“下一轮请将 `node_02` 的协同框架与 `node_03` 的第 XX~YY 行提前终止模块进行基因重组！”
3. **【死胡同封杀与瓶颈清剿令】**：
   - 将落选分支中被证实无效或导致高额空耗的机制提炼为 `[TABOO]` 写入 `SOLUTION_TREE.json` 与 `BOARD.md`；
   - 若当前最高分仍被封顶在 75 分以下，或总探索节点数 $n < N_{\min}$，必须在裁决书末尾签发强制性的**《下一阶段瓶颈清剿令（Next-Epoch Bottleneck Hunt Mandate）》**，严禁总管提前终止探索！
```
