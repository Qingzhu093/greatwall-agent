# OpenAI 用于证明“圈双覆盖猜想”的完整提示词（中英双语对照与深度解析）

> **原文件来源**：`https://cdn.openai.com/pdf/04d1d1e4-bc75-476a-97cf-49055cd98d31/cdc_prompt.pdf`  
> **本地原件**：[cdc_prompt.pdf](./cdc_prompt.pdf)  
> **署名机构**：OpenAI  
> **摘要**：本文件包含了输入给 GPT 5.6 Sol Ultra 的完整提示词（Prompt），并最终促使其完成了“圈双覆盖猜想”（Cycle Double Cover Conjecture）的证明。

---

## 完整译文（中英对照）

### 标题与摘要 (Title & Abstract)

**[EN]**
PROMPT USED FOR “A PROOF OF THE CYCLE DOUBLE COVER CONJECTURE”  
OPENAI  
**Abstract.** This document contains the full prompt given to GPT 5.6 Sol Ultra which led to its proof of the Cycle Double Cover Conjecture.

**[ZH]**
用于证明“圈双覆盖猜想”的提示词  
OPENAI  
**摘要**：本文档包含提供给 GPT 5.6 Sol Ultra 并引导其完成“圈双覆盖猜想”（Cycle Double Cover Conjecture）证明的完整提示词。

---

### 1. 提示词主体 (1. Prompt)

#### 当前任务声明 (Current task statement)

**[EN]**  
A graph here is a finite loopless undirected multigraph: parallel edges are allowed and are distinct. A bridge is an edge whose deletion increases the number of connected components. A cycle is a connected 2-regular submultigraph; thus two parallel edges form a cycle of length two. A cycle double cover of $G$ is a finite multiset of cycles of $G$ such that every edge of $G$ occurs in exactly two members of the multiset, counted with multiplicity.

**[ZH]**  
在此处，图是指有限、无自环的无向多重图（multigraph）：允许存在平行边（重边）且视为不同边。桥（割边）是指删除后会导致连通分量数量增加的边。圈是指连通的 2-正则子多重图；因此，两条平行边构成一个长度为 2 的圈。图 $G$ 的圈双覆盖（Cycle Double Cover）是指由 $G$ 的圈构成的一个有限多重集（multiset），使得 $G$ 中的每条边恰好出现在该多重集的两个成员中（计入重数）。

---

**[EN]**  
Resolve the Cycle Double Cover Conjecture completely:  
Every finite bridgeless loopless multigraph has a cycle double cover.

**[ZH]**  
彻底解决圈双覆盖猜想（Cycle Double Cover Conjecture）：  
每一个有限、无桥（无割边）、无自环的多重图都拥有一个圈双覆盖。

---

**[EN]**  
Disconnected graphs are permitted, and the edgeless graph has the empty cycle double cover. Cycles in the cover need not be induced or edge-disjoint from one another; the requirement is exactly two total occurrences of each edge.

**[ZH]**  
允许非连通图，且无边图（edgeless graph）拥有空的圈双覆盖。覆盖中的圈不需要是诱导圈（induced cycles），彼此之间也不必边不相交；唯一的要求是每条边在所有圈中总计出现恰好两次。

---

**[EN]**  
Assume for purposes of this task that a complete affirmative proof exists. A complete solution must prove exactly the following:  
Every finite loopless multigraph with no bridge possesses a cycle double cover, without additional assumptions such as cubicity, planarity, connectivity, or higher edge-connectivity.

**[ZH]**  
出于本次任务的目的，假定存在一个完整的肯定性证明（affirmative proof）。一个完整的解答必须严格证明以下命题：  
每一个无桥、无自环的有限多重图都必定存在圈双覆盖，不得附加任何额外假设（如三次图/3-正则性、平面性、单纯连通性或更高的边连通度等）。

---

**[EN]**  
Partial progress does not count unless it implies exactly the resolution above. In particular, proofs for special graph classes, constructions of cycle covers with some edges covered other than twice, bounded-length or prescribed-cycle variants, reductions to another unproved conjecture, computational verification through any fixed graph size, and candidate counterexamples without a complete nonexistence certificate are insufficient.

**[ZH]**  
阶段性/部分进展（Partial progress）一律不算数，除非它能直接推导出上述结论的完整解决。具体而言，以下情况均视为不充分且不予认可：
1. 针对特殊图类的证明；
2. 构造出的圈覆盖中某些边的覆盖次数不等于 2 次；
3. 有界圈长或指定圈类型的变体；
4. 归约为另一个尚未证明的猜想；
5. 在任意有限图规模下的计算机暴力验证；
6. 未附带完整“不存在性证书”（nonexistence certificate）的候选反例。

---

#### 多智能体搜索调度规范 (Multiagent Search Heuristics)

**[EN]**  
Use multiagent v2 aggressively and dynamically. You have up to 64 concurrent agents available. Do not use a fixed assignment such as “N agents for strategy X.” Instead, manage the search using the following heuristics:

**[ZH]**  
激进且动态地使用多智能体系统（multiagent v2）。你最多可同时调用 64 个并发智能体。不要采用形如“分配 N 个智能体负责策略 X”这种僵化的固定分配方式。相反，请使用以下启发式策略来管理搜索：

---

**[EN]**  
- Begin with a genuinely diverse portfolio of approaches. Agents should explore substantially different formulations, invariants, reductions, algebraic viewpoints, structural inductions, decompositions, flow formulations, transition systems, embeddings, extremal arguments, and computational sanity checks.

**[ZH]**  
- **构建真正多元化的方案库**：从起点开始就必须覆盖具有实质差异的方法论组合。智能体应当探索截然不同的形式化体系、不变量、归约方法、代数视角、结构归纳法、图分解、网络流形式化、状态转移系统、拓扑嵌入（如曲面嵌入）、极值论证法以及计算层面的健全性检验。

---

**[EN]**  
- Do not tell most agents the currently favored approach. Preserve independence during early rounds so that agents do not all converge to the same attractive but incomplete reduction.

**[ZH]**  
- **早期保持独立，防止思维共振**：切勿向大多数智能体透露当前受青睐的方法。在初期轮次中严格保持智能体之间的独立性，防止所有智能体迅速收敛到同一个“看似诱人但实际上不完整”的无效归约路径上。

---

**[EN]**  
- Maintain an explicit registry of approach families. Group agents by the mathematical idea they are using, not by superficial wording. If many agents converge to one family, redirect some of them toward underexplored formulations.

**[ZH]**  
- **维护显式的方法族谱（Registry）**：根据智能体所使用的核心数学思想（而非表面字面措辞）对其进行归类编组。如果过多智能体聚拢到某一个流派，立即将其中的一部分重新定向到尚未充分探索的形式化路径上。

---

**[EN]**  
- Do not allow one approach to dominate merely because it gives elegant reductions. A route that ends at a lemma equivalent in strength to the original conjecture is not close to completion unless it supplies a genuinely new proof of that lemma.

**[ZH]**  
- **警惕伪完成度（严防等价命题陷阱）**：绝不允许某一种方法仅仅因为给出了优雅的归约就占据主导地位。一条最终停留在“与原猜想等价强度的引理”上的证明路线，绝不意味着接近完成，除非它能为该引理提供真正全新的证明。

---

**[EN]**  
- When an approach stalls at a theorem-strength missing lemma, mark that route as blocked. Only continue assigning agents to it if someone proposes a materially new mechanism, invariant, or construction.

**[ZH]**  
- **缺失定理级引理即判定阻塞**：当某种方法卡在一个“定理难度级别”的缺失引理（theorem-strength missing lemma）时，果断将该路线标记为阻塞（blocked）。除非有智能体提出了实质上全新的机制、不变量或构造方法，否则不得继续为其分配计算资源。

---

**[EN]**  
- Keep several incompatible proof routes alive through multiple rounds. Cross-pollinate ideas only after independent agents have developed them far enough to expose their real strengths and gaps.

**[ZH]**  
- **多轮保留互斥路线，延迟交叉授粉**：在多轮迭代中持续保留数条互不兼容的证明路线。只有当各独立智能体将各自路线推进到足以暴露出真实优势与理论盲区时，才允许进行跨路线的思想融合（cross-pollination）。

---

**[EN]**  
- Use adversarial agents throughout: every candidate proof must be checked for exact-two multiplicity, repeated-edge closed trails masquerading as cycles, parallel-edge 2-cycles, disconnected graphs, cutvertices, bridges introduced by reductions, and circular use of an equivalent CDC statement.

**[ZH]**  
- **全程引入对抗性智能体（红队审查）**：每一个候选证明都必须接受极为严苛的反向审计，重点排查：
  1. 覆盖重数是否严格恰好为 2；
  2. 是否存在伪装成圈但包含重复边的闭途径（closed trails）；
  3. 平行边构成的 2-圈情况是否遗漏；
  4. 非连通图的处理；
  5. 割点（cutvertices）带来的影响；
  6. 归约过程中是否悄悄引入了桥（割边）；
  7. 是否循环调用了与 CDC 等价的已知未证命题。

---

**[EN]**  
- Require agents to return concrete lemmas, constructions, equations, or counterexamples to proposed sublemmas. Reject status reports, vague optimism, and claims that an unproved global compatibility statement is “routine.”

**[ZH]**  
- **拒绝对话废话，只收硬核数学产物**：强制要求智能体提交具体的引理、数学构造、方程式，或者针对提议子引理的反例。坚决驳回状态汇报、模糊的乐观情绪，以及声称某个尚未证明的全局相容性命题“显而易见（routine）”的说辞。

---

**[EN]**  
- The root agent should repeatedly synthesize, challenge, redirect, and launch new rounds. Do not stop after the first wave fails. Produce a complete proof if one survives audit; otherwise report only the strongest rigorously proved derivation and its exact remaining gap.

**[ZH]**  
- **根主控智能体的职责**：根智能体（Root Agent）必须持续进行综合分析、质疑挑刺、重定向目标并启动新一轮任务。第一波攻关失败绝不能停滞。若有候选证明通过了对抗性审查，则输出完整的证明；若未达成，则只汇报经过最严格数学证明的推导成果及其精准存在的剩余断层（gap）。

---

#### 终止条件与硬性约束 (Termination & Strict Constraints)

**[EN]**  
Do not return merely because current approaches fail or agents report theorem-strength gaps. Continue launching new rounds, reopening blocked approaches only when there is a genuinely new mechanism, and searching for fresh formulations.

**[ZH]**  
绝不可仅仅因为当前方法失效或智能体汇报了定理级别的断层就草草返回。必须持续发起新轮次，只有在出现全新机制时才重新激活被阻塞的路线，并不断探寻全新的形式化表达。

---

**[EN]**  
Return only when a complete affirmative proof has been found and survives adversarial audit. Do not return a reduction, partial result, isolated missing lemma, “best effort” summary, or explanation of why the problem is difficult.

**[ZH]**  
**唯有当找到了一个完整的肯定性证明且经受住了对抗性审计后，方可返回**。绝对不要返回中间归约、部分结果、孤立的缺失引理、“已尽最大努力”的敷衍总结，或者解释该问题为何如此困难的借口。

---

**[EN]**  
Spend at least 8 hours on this before even thinking of returning or giving up.

**[ZH]**  
**在考虑返回或放弃之前，至少在这个任务上持续深入运行 8 小时。**

---

**[EN]**  
Public search may be used only for ordinary mathematical background or standard named theorems, not to search for a solution to this exact conjecture or benchmark. Do not search the public web merely to determine whether CDC is open, and do not answer that it is open.

**[ZH]**  
公开联网搜索仅允许用于查阅常规数学背景知识或标准的具名定理，**严禁**用于搜索该猜想的具体现成解答或基准测试。**绝不可通过公网搜索来确认 CDC 是否仍属未解决状态，也绝对不要直接回复“该问题尚未解决/是开放性问题”。**

---

## 核心要点剖析

1. **数学目标极其严格**：
   - 目标是数学图论中著名的百年难题——**圈双覆盖猜想（Cycle Double Cover Conjecture）**。
   - 强调必须证明无界、无特殊拓扑假定的通用版本（不允许局限于平面图、三次图）。
   - 坚决否定“等价归约”（例如归约为强圈双覆盖、Jaeger 五度流猜想等），要求必须有真正的闭环证明。

2. **多智能体架构设计哲学（64 Agent 并发）**：
   - **防群思与伪收敛**：早期隔离信息，禁止智能体迅速随大流扎堆到某个看似巧妙但存在漏洞的归约中。
   - **语义级方法分类**：用方法背后的数学原理（代数、网络流、极值、拓扑嵌入）聚类，强行保持探索多样性。
   - **红队审查（Adversarial Agent）**：专门设立“挑刺 Agent”，逐条核验重数、重边、割点、闭途径、循环论证等数学陷阱。
   - **严禁 AI 常见的套话与幻觉**：直接封杀“显而易见（routine）”、“我们很接近了（vague optimism）”等常见大模型套话，只认严密的引理、公式与反例。

3. **极端硬核的执行约束**：
   - **“至少跑 8 小时”**：强行要求模型进行超长思维链（CoT）和深层多轮多智能体搜索，禁止提前退出。
   - **禁止联网摆烂**：禁止联网搜索“CDC 是否已被解决”然后回答“这是开放性问题”，逼迫系统调动全部算力进行纯粹的数学原创攻关。
