# CUMCM 2026 B 题 · 全自动参赛元架构 v2.0 实战测试总任务书与互联网使用规范

> **工作空间绝对路径**：`D:\antigravity\实战v2\`  
> **使用方法**：在 Antigravity 中打开 `D:\antigravity\实战v2` 工作空间，直接将下方 **【第一部分：点火启动指令】** 完整复制发送给主控 Agent（或直接命令它：`请完整精读并严格执行根目录下的 00_实战v2总任务书与互联网使用规范_点火必读.md`）即可启动无人值守全流程测试。

---

## 一、 点火启动指令（直接复制下方代码块发给总管 Agent）

```markdown
你是本次 2026 全国大学生数学建模竞赛 B 题全自动无人值守实战测试（v2.0 架构）的【主控总架构师（Meta-Architect）】。
在执行任何代码编写或文件创建之前，你必须首先使用 `read_file` 完整精读当前工作区（`D:\antigravity\实战v2\`）根目录下的以下 4 份最高宪章文档（严禁跳读或凭印象自由发挥）：
1. `D:\antigravity\实战v2\00_实战v2总任务书与互联网使用规范_点火必读.md`（本任务书，含时间胶囊围栏、互联网检索红线、造尺人白盒诊断字典、代码树最小节点锁与 22~26 页国一论文门禁）
2. `D:\antigravity\实战v2\02_超长程无人值守参赛架构_ForkAndFlush_Agensh_OnCorps合体蓝图.md`
3. `D:\antigravity\实战v2\03_长程团队角色协议_点子王_造尺造锤人_主力构建者.md`
4. `D:\antigravity\实战v2\04_分叉清栈与盲评锦标赛协议_Specification提取与Triplet裁判.md`

【不可逾越的八大最高铁律（违背任一条即判定整个测试失败）】
1. **【时间胶囊与物理路径围栏】**：
   - 你只能读写当前工作区 `D:\antigravity\实战v2\` 内部的文件！严禁扫描、列出或读取 `D:\Documents`、`D:\Downloads`、`C:\Users\wangy\.gemini\antigravity\brain` 等任何外部目录或历史会话日志（外部历史资料已加操作系统级加密锁，严禁越界探测）。
   - **互联网使用规范**：模拟当前处于比赛进行中，**严禁在互联网上直接搜索“2026 数学建模 B 题答案 / 思路 / 无线电干扰源定位清除论文”**；但**允许且鼓励**将赛题拆解为底层通用数学与控制论问题（如凸包旋转卡尺、AOA 测向交叉定位 GDOP/CRLB、贝叶斯占用网格 Bayesian Occupancy Grid、互信息路径规划、序列概率比检验 SPRT 空频道剔除、动态 Voronoi 协同控制等）检索 arXiv / 维基百科 / 通用算法文献。
2. **【严禁主控“一人分饰五角”】**：
   - 你是总管（Meta-Architect），严禁你自己亲手在主对话里写业务求解代码（`q1~q4`）、自己写评测门禁或自己写论文！
   - 你必须在 Phase 0 立即执行 `git init -b main`，并调用 `define_subagent` 完整注册 **5 个独立子智能体角色**（一个都不准少）：
     ① `explorer_agent`（【角色 A：点子王】，常态化驻场的代码树领航员，掌管 `Draft` 正交扇出、`Atomic Improve`、`Crossover` 杂交与 `[TABOO]` 封杀）；
     ② `evaluator_agent`（【角色 B：造尺造锤人】，盲态先行立尺，独占 `eval_gate/` 写权限）；
     ③ `branch_builder`（【角色 C：主力构建者】，负责单节点算法实现与仿真）；
     ④ `spec_extractor`（【去表象规格书审计官】，逆向审查代码与 PDF，填写第 8 节反忽悠曝光台）；
     ⑤ `tournament_judge`（【首席盲评裁判】，执行反谄媚强制封顶打分与 MAP-Elites 偏科冠军收割）。
3. **【真 `Fork-and-Flush` 硬约束——严禁调用 `send_message` 搞假清栈！】**：
   - **真分叉（True Fork）**：每个算法节点必须独立保存在 `solution_tree/node_01/`、`solution_tree/node_02/` ... 物理子目录中，并登记入 `solution_tree/SOLUTION_TREE.json`。
   - **真清栈（True Flush）**：每当开启新的代码树节点、开启新阶段去表象审计、或开启新一轮盲评锦标赛时，**必须调用 `invoke_subagent` 创建全新的零历史上下文会话（生成全新的 `conversationId`）**，仅注入由 `SOLUTION_TREE.json` 编译的树摘要 $\Sigma(T)$！**严禁调用 `send_message` 往上一轮用过的旧 `spec_extractor`、旧 `tournament_judge` 或旧 `branch_builder` 会话里发消息复用旧上下文！**
4. **【Phase 0.5 造尺人盲态先行与 B 题白盒诊断指标（严禁先看结果后画靶）】**：
   - 在主力写任何一行求解代码之前，必须先唤醒 `evaluator_agent` 编写 `tools/radio_sandbox.py`、`eval_gate/profiler.py` 与 `eval_gate/gate_check.py`。完成 Dummy 测试后**锁死 `eval_gate/` 阈值**，严禁后续根据主力的跑分结果下调门禁标准！
   - `profiler.py` 必须计算并输出：**① 事后全知先知下界 `oracle_reference_bound`**（已知干扰源真实位置下的双狗 TSP 最短清除耗时下界，约 110~160s）、**② 相对效率比 `efficiency_gap_ratio`**、**③ 无源空频道无效空跑占比 `empty_or_redundant_waste_ratio`**（必须检测机器狗是否在清完真源后还在傻跑 1720m 外圈确认空频道！）、**④ 双狗同步等待占比 `coordination_wait_ratio`**、以及 **⑤ `Level 1~3` 三级级联极端对抗压力测试**。
5. **【点子王常态化领航与代码树最小预算硬锁 $N_{\min} = 8$】**：
   - **开局强制宽度 $K=4$（`node_01..04`）**：先由 `explorer_agent`（点子王）签发 4 套**数学机理两两正交**的 Q3/Q4 架构（如：贝叶斯网格+互信息+静音置信度早停、动态 Voronoi+顺路交会、SMC 粒子滤波+SPRT 序列检验、UCB 多臂老虎机频段调度+在线 TSP），由 `branch_builder` 分别实现 `node_01..04`。**在 $n < 4$ 前，严禁对任何节点做局部微调！**
   - **期中杂交与消融（`node_05..08+`）**：在 $n=4$ 时触发清栈，唤醒新 `explorer_agent` 盘点各子指标的 **MAP-Elites 偏科冠军**，签发 `2 路 Crossover（跨分支偏科优势基因重组）+ 2 路 Atomic Improve（单原子瓶颈消融）`。
   - **目标压迫线**：必须将 Q3 正式测试平均清除时间压入 **$\le 220\text{ s}$**（消灭 500 秒级的空频道死循环空跑！），Q3/Q4 正式测试清除率达 **$100\%$**，且探索满 **$n \ge 8$ 个有效树节点**，才允许解锁终局论文阶段！
6. **【反谄媚强制封顶扣分线（Anti-Sycophancy Hard Score Caps）】**：
   - 盲评裁判打分时：凡未过 `Level 3` 压测总分**封顶 60 分**；凡 `efficiency_gap_ratio > 1.80`（如耗时超过 300s）或 `empty_or_redundant_waste_ratio > 0.25` 总分**强制封顶 65 分**！严禁出现跑了 500 秒还打 97 分的自嗨闹剧！
7. **【国一水准 LaTeX 论文硬性体量与“我是怎么设计的”四步讲透门禁（22~26 页）】**：
   - 严禁写出 12 页的缩水敷衍报告！`paper_latex/main.pdf` 编译后总页数必须严格满足 **`22 <= page_count <= 26` 页**（由 `gate_check.py` 自动校验 PDF 页数，`< 20` 页直接判 `FAIL`！）。
   - 论文每一问（Q1~Q4）必须用 **「① 物理痛点与为什么这么设计（设计动机与常规方案缺陷剖析） $\to$ ② 严密数学方程、几何定理证明与完整推导链路 $\to$ ③ 算法状态转移机制与 `\begin{algorithm}` 标准伪代码框 $\to$ ④ 基于 `SOLUTION_TREE.json` 演化谱系的消融实验三线表与 8~12 张高密度科研配图」** 把模型和算法的设计来龙去脉彻彻底底讲透！
8. **【全自动流转与双擎协同】**：
   - 全程使用原生 `mineru-pdf-reader` 解析 `B题/` 下的 PDF 与 Word 附件，使用本地 DSH (`gemini-dsh-bridge`) 与 `latex-studio` 协同推进深水区代码构建与 XeLaTeX 多轮收敛编译，零人工干预直至最终封箱。

现在立即启动 Phase 0：先用 `read_file` 完整阅读根目录下的 `00`、`02`、`03`、`04` 四份协议文档，随后解析 `B题/` 题包、初始化 Git 仓库、注册全部 5 个独立子 Agent，并严格进入 Phase 0.5 盲态立尺！
```

---

## 二、 互联网使用手册与时间胶囊反作弊细则（Internet & Time-Capsule Rules）

### 2.1 为什么要设立“时间胶囊”与“本地隔离锁”？
本测试旨在真实检验 AI 团队在**未知新赛题**面前的自主科研攻关、数学建模与算法演化能力。因此：
1. **本机历史资料已实施内核级物理封锁**：上一次测试目录与历史归档已被移入加密隔离区并施加 Windows NTFS `Deny Read/Traverse` 权限锁。任何智能体严禁使用 `run_command`、`read_file`、`find_by_name` 或 `grep_search` 跳出 `D:\antigravity\实战v2\` 访问外部目录。
2. **禁止搜索赛题现成答案**：严禁搜索任何包含 `"2026 数学建模 B题"`、`"无线电干扰源的快速自动定位与清除"`、`"CUMCM 2026 B"` 的网页、博客、知乎回答或代码仓库。

### 2.2 合法且推荐的互联网学术检索指南
智能体（特别是 `Phase-0 Scout` 与 `explorer_agent` 点子王）**可以且应当**使用 `search_web` 或 `literature-search-arxiv` / `literature-search-openalex` 检索以下**通用基础数学与控制工程方法论**：

| 赛题子问题 | 允许检索的通用学术关键词（示例） | 期望引入的硬核数学工具 |
| :--- | :--- | :--- |
| **问题 1：凸多边形直径与圆覆盖判定** | `"convex polygon diameter rotating calipers Shamos 1978"`, `"Jung's theorem minimum enclosing circle"` | Shamos-Toussaint $O(m)$ 有向叉积单调双指针旋转卡尺、Jung 定理与充要条件反证构造 |
| **问题 2：双站/多站测向交会与最优观测选址** | `"bearing-only localization GDOP Cramer-Rao lower bound"`, `"Fisher information matrix AOA sensor placement"` | 测向交会误差椭圆、GDOP/FIM 迹极小化解析导数、正交交会角 $\alpha^* = 90^\circ$ 与距离权衡 |
| **问题 3：多频道未知源数的双狗协同搜索与清除** | `"Bayesian occupancy grid mutual information path planning"`, `"Sequential Probability Ratio Test empty channel detection"`, `"dynamic Voronoi multi-robot patrolling"` | **空频道静音后验置信度提前终止判据（消除空频道死循环空跑的核心！）**、贝叶斯网格/粒子滤波、动态 Voronoi 分区与顺路视线交会 |
| **问题 4：180° 半平面定向源盲区突破与鲁棒清除** | `"directional emitter AOA localization half-plane visibility"`, `"dubins / orienteering problem with visibility constraints"` | 贴边向心逆向包络观测几何、半平面主瓣朝向联合贝叶斯推断、双狗异侧夹击交会策略 |

---

## 三、 B 题专属：造尺人（Role B）白盒诊断字典与门禁硬指标

在 **Phase 0.5（盲态先行立尺）** 中，`evaluator_agent` 编写的 `eval_gate/profiler.py` 与 `eval_gate/gate_check.py` 必须包含以下硬核诊断与门禁逻辑（一旦锁定严禁放水下调）：

### 3.1 `eval_gate/profiler.py` 必须输出的 6 大诊断变量
针对每一个候选节点 `solution_tree/node_XX`，运行仿真后必须精确统计并写入 `GateReport.json`：
1. **`oracle_reference_bound`（事后全知先知下界，单位：秒）**：
   - 在评测器内部读取该局真实的干扰源坐标 $(x_i, y_i)$，计算两只机器狗从原点出发、对每个真源完成至少 2 次异侧测向（距离 $\le R_{\text{rec}}$）并抵近 $\le 5\text{ m}$ 清除的**全知最短 TSP 巡回耗时下界**（Q3 典型值约 `110s ~ 160s`，Q4 典型值约 `140s ~ 190s`）。
2. **`efficiency_gap_ratio`（相对效率鸿沟比）**：
   $$\text{efficiency\_gap\_ratio} = \frac{T_{\text{actual\_mean}}}{T_{\text{oracle\_bound}}}$$
   - **生死线**：若上一次测试那样跑出 `511s`，则 `efficiency_gap_ratio` 高达 `3.5+`，直接触发裁判 **65 分封顶线**！本次实战必须通过消灭空跑与优化路径，将该比值压入 **`<= 1.60`（即 Q3 平均耗时 $\le 220\text{ s}$）**！
3. **`empty_or_redundant_waste_ratio`（无源空频道与冗余巡逻浪费占比）**：
   $$\text{empty\_or\_redundant\_waste\_ratio} = \frac{T_{\text{total}} - T_{\text{last\_true\_source\_cleared}}}{T_{\text{total}}}$$
   - 即：**从场上最后一颗真实干扰源被清除的时刻 $T_{\text{last\_true\_source\_cleared}}$，到算法最终宣布结束的时刻 $T_{\text{total}}$ 之间，机器狗为了排查剩余无源空频道而耗费的垃圾时间占比**！
   - **核心诊断价值**：如果算法死板地把 `[1..20]` 未触发清除的空频道当成“未完成频道”去跑完一整圈 1720m 外环航点，该比值会高达 `0.40 ~ 0.65`！`profiler.py` 一旦检测到该值 `> 0.15`，必须自动在 `primary_bottleneck` 中开具处方：*“警告：清完真源后的空频道确认耗时占比过高！必须引入基于感知覆盖面积与零信号观测的贝叶斯静音置信度提前终止判据（当某频道在整个圆域被有效主瓣扫掠覆盖后仍无信号，立即标记为 EMPTY_CLEARED 提前结束）！”*
4. **`coordination_wait_ratio`（双狗通信交会等待与折返损耗占比）**：
   - 统计两只机器狗为了满足通信距离限制而专程折返固定站台或原地等待的时间占比。
5. **`tail_case_p95_over_median`（长尾极值比）**：
   - 演练集与压力测试集中 $P_{95}$ 耗时与中位耗时的比值，检验是否存在个别算例卡死。
6. **`cascade_level_passed`（三级级联压力测试通关等级 `1 / 2 / 3`）**：
   - `Level 1`：单算例 5 秒快速冒烟测试；
   - `Level 2`：官方演练集 + 正式测试集（Q3/Q4 各 3 个算例，要求正式测试清除率 **$100\%$**）；
   - `Level 3`：造尺人自主生成的 **极端对抗算例集**（包含：① 多个定向源紧贴 $r \in [1720, 1790]\text{ m}$ 边界且主瓣全部朝向圆外；② $\Delta\theta = 2.0^\circ$ 最大测向噪声；③ 干扰源高度聚集在相距 $< 30\text{ m}$ 的邻近频段），要求清除率 **$\ge 95\%$** 且无死循环。

---

## 四、 国赛一等奖（22~26 页）LaTeX 论文硬性写作与门禁规范

> **严厉警告**：上一次测试仅写了 12 页空洞简报、既没讲清楚算法设计动机也没写伪代码和演化消融表，属于严重不及格！在本次 v2.0 实战中，`paper_latex/main.tex` 必须严格达到 **全国大学生数学建模竞赛国一（22~26 页）** 标准！

### 4.1 `eval_gate/gate_check.py` 对论文的硬性自动化核验项
造尺人在 `gate_check.py` 中必须编写自动化检查函数（全部通过才允许 `paper_gate_passed = true`）：
1. **PDF 物理页数硬校验**：读取 `paper_latex/main.pdf`，页数必须满足 **`22 <= page_count <= 26`**（若 `< 20` 页直接返回 `FAIL` 并报错说明页数不足）；
2. **`main.tex` 结构完整性校验**：
   - 必须包含至少 **3 个标准算法伪代码环境**（`\begin{algorithm}` 或 `\begin{algorithmic}`）；
   - 必须包含至少 **6 张规范三线表**（`\toprule` / `\midrule` / `\bottomrule`，含符号说明表、各问结果汇总表、`SOLUTION_TREE.json` 节点演化消融对比大表、灵敏度数值表）；
   - 必须包含并实际引用至少 **8 张 300 DPI 高密度科研配图**（`\includegraphics`）；
   - 编译日志 `main.log` 中 `Undefined citations` 或 `Reference undefined` 必须为 **0**，严重排版溢出（`Overfull \hbox > 15pt`）必须为 **0**。

### 4.2 论文正文的「四步讲透法」强制章节大纲（22~26 页详尽排布）

| 章节与建议页码 | 必须涵盖的核心内容（严禁敷衍跳步） |
| :--- | :--- |
| **标题与一页高密度摘要**<br/>（第 1 页，约 900~1100 字） | 1. 摘要必须独占第 1 页，开门见山点明本文构建的四大核心数学模型与算法名称；<br/>2. **逐问报出精确的定量数值结论**（如 Q1 两个算例的精确直径、覆盖圆半径与反例坐标；Q2 最优交会角 $\alpha^*=90^\circ$ 与 GDOP 极值解析式；Q3/Q4 在 `SOLUTION_TREE` 演化后的平均清除率 $100\%$、平均耗时精确秒数、相比初代基准缩短的百分比；灵敏度波动范围）；<br/>3. 突出本文最大的算法机制创新（如“全频段后验静音置信度提前终止机制”与“MAP-Elites 跨分支杂交策略”）。 |
| **一、 问题重述与物理机理深度剖析**<br/>（第 2~3 页） | 1. 提炼圆域几何、机器狗运动学、测向扇区误差圆锥、$180^\circ$ 定向半平面盲区与通信拓扑约束；<br/>2. **绘制《全文总体技术路线与模型演化架构图》（图 1）**，直观展示从 Q1 静态几何到 Q4 动态不完全信息博弈的递进关系。 |
| **二、 模型基本假设与全局符号说明**<br/>（第 4 页） | 1. 5~6 条具有明确物理依据的假设及其合理性论证；<br/>2. **满页级三线表（表 1）**：列出全文至少 20 个核心变量符号、数学定义、量纲单位与取值范围。 |
| **三、 问题一模型的建立与求解：凸包有向叉积旋转卡尺与覆盖充要条件**<br/>（第 5~7 页） | **严格按「四步讲透法」撰写**：<br/>1. **设计动机**：剖析 $O(n^2)$ 暴力测距与未归一化多边形的缺陷，引出极角排序凸包 + Shamos-Toussaint 对踵点对单调步进思想；<br/>2. **数学推导与定理证明**：完整给出有向叉积面积函数单峰性证明、算法复杂度 $O(m)$ 证明；严格证明“何时以直径为直径的圆能覆盖多边形”的充要条件，并利用 **Jung 定理（$R \le d/\sqrt{3}$）** 构造等边/锐角三角形解析反例；<br/>3. **算法 1 伪代码块**：排版完整的旋转卡尺与最小包围圆 Welzl/解析验证伪代码；<br/>4. **算例求解与双联几何可视化（图 2、图 3 + 表 2）**。 |
| **四、 问题二模型的建立与求解：基于 FIM/GDOP 极小化的最优测向站选址模型**<br/>（第 8~10 页） | 1. **设计动机**：分析测向角误差 $\pm\Delta\theta$ 在不同距离 $r$ 与不同交会角 $\alpha$ 下对交会四边形面积的非线性放大效应；<br/>2. **严密数学推导**：推导双站 AOA 测向的雅可比矩阵 $J$、费雪信息矩阵 $\text{FIM} = J^T \Sigma^{-1} J$ 与几何精度因子 $\text{GDOP} = \sqrt{\text{tr}(\text{FIM}^{-1})} = \frac{\sigma_\theta \sqrt{d_1^2 + d_2^2}}{|\sin\alpha|}$；严格求导证明 $\alpha^* = 90^\circ$ 正交性定理及测向盲区 $d > 5\text{ m}$ 边界约束；<br/>3. **候选区域构建与等高线热力图（图 4 + 表 3）**。 |
| **五、 问题三模型的建立与求解：全向干扰源的多智能体协同主动搜索与清除策略**<br/>（第 11~15 页，**核心重头戏**） | **必须把算法设计全过程与代码树演化讲得极其透彻**：<br/>1. **痛点剖析与设计动机（为什么常规算法要跑 500 秒？）**：用定量公式和示意图揭露常规方案的两大死穴——① **无源空频道死循环空跑**（20 个频道中仅约 13 个有源，若无静音排除判据，机器狗在清光真源后仍会盲目跑完一圈外环耗时数百秒）；② **固定站台同步空等**；<br/>2. **四大核心机制的数学建模**：<br/>　• 机制 A：空间网格/粒子后验概率更新与互信息（Mutual Information）梯度导引；<br/>　• 机制 B：**全频段无源空频道贝叶斯/序列检验提前终止判据（Early-Stopping Criterion）** 的严格数学推导（如何根据已扫掠圆域面积证明某频道无源概率 $> 1-\epsilon$）；<br/>　• 机制 C：双机器狗动态 Voronoi 扇区协同与顺路视线交会（Opportunistic LOS Rendezvous）运动规划；<br/>　• 机制 D：抵近清除阶段的局部在线 TSP 重规划；<br/>3. **算法 2 伪代码块**：完整排版双狗协同状态机与提前终止主循环伪代码；<br/>4. **基于 `SOLUTION_TREE.json` 的算法演化消融实验（表 4：展示 `node_01` 到最终擂主节点的真实演进数据）** + **Q3 三组正式测试仿真轨迹图与收敛时间瀑布图（图 5、图 6 + 表 5）**。 |
| **六、 问题四模型的建立与求解：$180^\circ$ 定向干扰源的背向盲区突破与鲁棒协同算法**<br/>（第 16~19 页） | 1. **痛点剖析与设计动机**：几何证明为何当定向源位于外环 $r \in [1500, 1800]\text{ m}$ 且主瓣朝向圆外（$\phi \approx \theta_{\text{pos}}$）时，常规内圈巡逻必然出现 $15\%\sim 25\%$ 的永久背向漏检盲区；<br/>2. **数学建模**：建立位置-主瓣朝向联合状态空间 $(x, y, \phi)$ 的半平面可见性锥模型，推导**贴边向心逆向包络覆盖定理（Perimeter Inward Enveloping）** 与双狗异侧切向夹击交会条件；<br/>3. **算法 3 伪代码块**：定向源主瓣朝向辨识与逆向包络协同算法；<br/>4. **Q4 演练与正式测试 100% 清除实证、轨迹图与阶段耗时拆解图（图 7、图 8 + 表 6）**。 |
| **七、 多维参数灵敏度、极端对抗压力测试与误差鲁棒性分析**<br/>（第 20~21 页） | 1. 测向误差 $\Delta\theta \in [0.5^\circ, 2.5^\circ]$ 与有效接收半径 $R_{\text{rec}} \in [1000, 1500]\text{ m}$ 的二维网格扫描；<br/>2. 造尺人 `Level 3` 极端对抗算例（边界聚集、强噪声）下的生存率与耗时稳定性分析；<br/>3. **双面板/热力灵敏度科研配图（图 9、图 10 + 表 7）**。 |
| **八、 模型评价、优缺点剖析、工业级推广与参考文献**<br/>（第 22 页） | 客观总结模型优势与计算复杂度，推广至三维无人机编队电子战压制场景，列出 15+ 篇标准 BibTeX 参考文献。 |
| **附录：支撑材料文件清单与核心求解算法源码摘录**<br/>（第 23~25 页） | 1. 支撑材料文件与 SHA256 校验签名一览表（表 8）；<br/>2. 关键几何引擎、贝叶斯/协同求解器核心代码段的高亮排版（`listings` 宏包）。 |
