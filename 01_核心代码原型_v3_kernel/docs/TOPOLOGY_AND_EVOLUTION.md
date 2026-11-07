# 超长程多并发 Agent 演化拓扑、沙箱隔离与因果流架构规范
## Topology, Isolation & Evolutionary Dynamics Specification (AFEVA Framework)

> **文档状态**：PROD-READY / AUTHORITATIVE SPECIFICATION  
> **设计版本**：v2.4.0 (2026 工业级综合竞赛与超长程探索基准规范)  
> **目标工程**：`d:\Documents\deepseek harness\长程 Agent 设计系统`  
> **核心使命**：详尽定义大规模物理隔离沙箱的生命周期管理、Windows 文件锁冲突彻底解决方案、三孤岛稀疏有向环迁移演化拓扑、反应式因果 DAG 事件流驱动模型与捕食者-猎物协同演化全周期调度，为系统并发执行提供终极拓扑保障。

---

## 目录导读

1. [拓扑与并发体系总览](#1-拓扑与并发体系总览)
2. [大规模 Worktree 物理隔离与 RAM-Disk 沙箱架构](#2-大规模-worktree-物理隔离与-ram-disk-沙箱架构)
   - 2.1 Git Bare 共享母本与零拷贝（COW）内存挂载
   - 2.2 租约生命周期（Lease Lifecycle）与自动回收状态机
   - 2.3 Windows NTFS 文件句柄占用（错误码 32）终极解决契约
   - 2.4 零数据泄漏清理与原子回滚机制
3. [三孤岛自适应模拟退火与稀疏有向环迁移拓扑](#3-三孤岛自适应模拟退火与稀疏有向环迁移拓扑)
   - 3.1 孤岛 0：保守冠军锚点岛 (Conservative Anchor)
   - 3.2 孤岛 1：激进退火探索岛 (Aggressive Annealing)
   - 3.3 孤岛 2：MAP-Elites 新颖性特区沙箱 (Novelty Sandbox)
   - 3.4 稀疏有向环迁移总线协议（Sparse Directed Ring Migration）
   - 3.5 阻断选择性扫荡与希钦-骑乘效应的隔离屏障
4. [反应式因果 DAG 事件流与无锁流水线调度](#4-反应式因果-dag-事件流与无锁流水线调度)
   - 4.1 偏序因果 DAG 与局部就绪门（破除全局代际木桶效应）
   - 4.2 单调分层因果等级定理与死锁自由度（Deadlock-Free）形式化证明
   - 4.3 需求反向拉取流控（Credit-based Demand Backpressure）
   - 4.4 投机执行令牌与 Saga 级联毒丸清算（Poison-Pill Protocol）
   - 4.5 Tarjan 强连通分量动态破环算法
5. [捕食者-猎物协同演化全周期排期与阶梯门禁流转](#5-捕食者-猎物协同演化全周期排期与阶梯门禁流转)
   - 5.1 求解器（猎物）与造尺人（捕食者）动态对抗模型
   - 5.2 动态课程排期（幼年期、成长期与生产期）
   - 5.3 偏科生带病晋级与定向杂交补丁工作流
   - 5.4 终局交付 Master 主干推进协议

---

## 1. 拓扑与并发体系总览

超长程多智能体探索的成败，本质上取决于底层**物理拓扑（Physical Topology）**与**信息流拓扑（Information Topology）**的解耦程度。AFEVA 架构确立了“三维立体解耦拓扑”：
1. **执行域（Execution Domain）**：基于 RAM-Disk 的绝对物理无共享沙箱，支撑上百个并发 Worker 高速运行，物理隔离任何互斥文件锁；
2. **时序域（Temporal Domain）**：基于偏序因果 DAG 与需求背压流，消灭集中代际死锁，快跑分支异步超前推进，慢跑分支按需追赶；
3. **演化域（Evolutionary Domain）**：基于三孤岛稀疏有向环，严格隔离局部精修、大步长跃迁与纯新颖性踏脚石孵化，杜绝全网基因同质化雪崩。

```mermaid
graph TD
    subgraph ExecutionDomain["1. 执行域：RAM-Disk 物理沙箱池"]
        BareRepo["Git Bare 仓库母本 (只读挂载)"]
        RD1["RAM-Disk 沙箱 WT_01<br/>(Island 0 Anchor)"]
        RD2["RAM-Disk 沙箱 WT_02<br/>(Island 1 Anneal)"]
        RD3["RAM-Disk 沙箱 WT_03<br/>(Island 2 Novelty)"]
        BareRepo --> RD1
        BareRepo --> RD2
        BareRepo --> RD3
    end

    subgraph TemporalDomain["2. 时序域：反应式因果 DAG 总线"]
        DAG_NodeA["Task A (Level 1)"] --> DAG_NodeB["Task B (Level 2)"]
        DAG_NodeA --> DAG_NodeC["Task C (Level 2)"]
        DAG_NodeB --> DAG_Join["Local Causal Join (Level 3)"]
        DAG_NodeC --> DAG_Join
        Backpressure["Credit-based Demand Stream<br/>(下游沙箱反向申领配额)"] -.-> TemporalDomain
    end

    subgraph EvolutionaryDomain["3. 演化域：三孤岛稀疏有向环迁移拓扑"]
        Island0["孤岛 0: Anchor 锚点<br/>(T=0 贪心精修, 守住历史高分)"]
        Island1["孤岛 1: Anneal 退火<br/>(自适应 MAD, 势垒跃迁)"]
        Island2["孤岛 2: Novelty 新颖性<br/>(3D MAP-Elites, 踏脚石孵化)"]
        
        Island0 -- "最优精炼卡片 (P-Migration)" --> Island1
        Island1 -- "高潜变异表型" --> Island2
        Island2 -- "正交踏脚石基因" --> Island0
    end

    ExecutionDomain <--> TemporalDomain
    TemporalDomain <--> EvolutionaryDomain
```

---

## 2. 大规模 Worktree 物理隔离与 RAM-Disk 沙箱架构

### 2.1 Git Bare 共享母本与零拷贝（COW）内存挂载
针对传统基于物理硬盘执行 `git worktree add/remove` 引发 I/O 队列打爆和 MFT 锁争用的问题，系统实施全内存化工作区管理：
1. **只读裸库基座（Bare Git Anchor）**：系统在物理 SSD 上维持唯一的纯净裸库（`repo.git`），该裸库作为只读数据卷挂载，严禁任何并发进程对其内部文件直接执行写操作；
2. **RAM-Disk 虚拟工作区映射**：在系统启动时，通过 Windows 内存映射（Memory-Mapped Files）或专有内存盘（RAM-Disk，容量 4GB~8GB）挂载专有工作盘符（如 `R:\sandboxes\`）；
3. **纳秒级写时复制（COW）检出**：
   - 创建新沙箱时，底层管理器在 RAM-Disk 内部建立独立的虚拟树结构；
   - 采用轻量化符号链接与只读对象池共享，代码检出耗时稳定在 **15ms ~ 45ms** 以内；
   - 彻底避免向物理磁盘写入临时 `.pyc`、中间编译产物或日志，吞吐量相比物理 SSD 提升两个数量级。

### 2.2 租约生命周期（Lease Lifecycle）与自动回收状态机

```
                      沙箱租约全生命周期流转状态机
   ┌───────────────┐     创建租约     ┌────────────────┐
   │ LEASE_CREATED ├─────────────────►│ LEASE_ACQUIRED │
   └───────────────┘                  └───────┬────────┘
                                              │
                                              ▼ (执行算法与测试)
   ┌───────────────┐                  ┌────────────────┐
   │ LEASE_CLEANUP │◄─────────────────┤ LEASE_RELEASED │
   └───────┬───────┘   (正常显式释放) └───────┬────────┘
           │                                  │ (超时未归还)
           ▼                                  ▼
   ┌───────────────┐                  ┌────────────────┐
   │ LEASE_EXPIRED │◄─────────────────┤ LEASE_ZOMBIE   │
   └───────────────┘   (守护协程强杀) └────────────────┘
```

1. **租约获取（`LEASE_ACQUIRED`）**：Worker 申领到沙箱时，自动绑定物理租约时钟（默认租约期 $T_{\text{lease}} = 300\text{s}$）；
2. **租约续约（Heartbeat Extension）**：Worker 处于正常活跃状态时，每隔 15s 随任务进度上报心跳更新租约时间；
3. **僵尸冻结与无情处决（Zombie & Ruthless SIGKILL）**：若沙箱进程发生未捕获的死锁、无限递归或超时挂起，且超过租约期限，状态机判定为 `LEASE_ZOMBIE`。宿主看门狗直接向该进程树发送操作系统级强制终止信号（Windows `TerminateProcess` / Linux `SIGKILL`），强制回收 RAM-Disk 空间。

### 2.3 Windows NTFS 文件句柄占用（错误码 32）终极解决契约
在 Windows 环境下，动态链接库加载、杀毒软件扫描及管道泄露极易导致 `[WinError 32] 另一个程序正在使用此文件，进程无法访问`。AFEVA 实施三重防御契约：

```
                              Windows 文件锁终极防御契约
   ┌────────────────────────────────────────────────────────────────────────┐
   │ 契约 1: 物理绝缘原则 (RAM-Disk Isolation)                              │
   │ 所有频繁增删的 Worktree 建立在 RAM-Disk 上，绕开 NTFS 物理 MFT 锁。   │
   ├────────────────────────────────────────────────────────────────────────┤
   │ 契约 2: 抖动退避重试 (Exponential Backoff with Jitter)                  │
   │ 遇到 WinError 32 时，执行指数退避重试 (10ms, 20ms, 40ms, 80ms)。       │
   ├────────────────────────────────────────────────────────────────────────┤
   │ 契约 3: 强制句柄重置 (Kernel-Level Handle Cleansing)                    │
   │ 3 次重试失败后，调用 Win32 Restart Manager API 强制解绑残留进程句柄，  │
   │ 随后以原子操作移动至废弃回收桶 (Recycle Bin Folder) 异步擦除。        │
   └────────────────────────────────────────────────────────────────────────┘
```

### 2.4 零数据泄漏清理与原子回滚机制
1. **原子重命名隔离（Atomic Tombstoning）**：当沙箱需要被删除时，系统不直接在原地执行递归文件删除，而是原子性地将目录重命名为 `tombstone_{worktree_id}_{timestamp}`，确保该 Worktree ID 能够立即被后续任务复用；
2. **异步后台物理消杀**：后台专有垃圾回收协程负责将 `tombstone` 目录擦除，彻底消除删除操作对主任务调度流的时延阻塞。

---

## 3. 三孤岛自适应模拟退火与稀疏有向环迁移拓扑

### 3.1 孤岛 0：保守冠军锚点岛 (Conservative Anchor)
- **演化使命**：守住全场历史最高分防线，负责局部高价值盆地的极值深潜与工业级打磨；
- **动力学参数**：控制温度恒定 $T = 0.0$（绝对贪心优化，严禁接纳任何导致综合指标变劣的突变）；
- **变异算子**：高斯微步长扰动算子（Gaussian Creep），针对已知高分算法的代码超参数、内层循环展开与缓存对其进行精细微调；
- **门禁准入**：执行 Tier 3 级别严苛验证，保证该岛保留的代码随时具备主干合并与最终交付能力。

### 3.2 孤岛 1：激进退火探索岛 (Aggressive Annealing)
- **演化使命**：大跨度探索全新算法范式，主动跃迁跨越非凸能量势垒，跳出局部死坑；
- **动力学参数**：采用基于滑动窗口 MAD 稳健标度的无量纲模拟退火，初始温度 $T_0 \approx 1.00$，按几何速率降温（$\gamma = 0.88$）；
- **变异算子**：柯西长尾宏突变算子（Cauchy Jump），敢于推倒核心数据结构与求解流形（如由连续凸松弛重构为张量化广播）；
- **劣解接纳准则**：严格遵循 Metropolis-Hastings 概率准则：
  $$\alpha(\mathbf{x} \to \mathbf{x}') = \min\left(1, \; \exp\left(-\frac{\Delta \tilde{E}}{T}\right)\right)$$
- **重加热保护**：连续 3 代能量方差停滞时，注入 $\Delta T = 0.5 T_0$ 重加热脉冲，震碎局部锁定。

### 3.3 孤岛 2：MAP-Elites 新颖性特区沙箱 (Novelty Sandbox)
- **演化使命**：制度化保护非直观的“革命性踏脚石（Stepping Stones）”，彻底摆脱当前测试跑分的功利诱导；
- **动力学准则**：**适应度豁免（Fitness-Free Quality-Diversity）**。该岛完全不以“运行耗时更短”为优化方向，唯一的入选标准是**行为特征正交距离与空白行为网格占有率**；
- **3D 行为网格划分**：
  1. 计算强度阶次 $b_{\text{compute}} \in [\text{Low}, \text{Medium}, \text{High}]$；
  2. 空间复杂度增长斜率 $b_{\text{memory}} \in [O(1), O(N), O(N^2)]$；
  3. 混沌敏感度 $b_{\text{stability}} \in [\text{Robust}, \text{Sensitive}]$；
- **Yield 准则考核**：根据离散最大团（Maximum Clique）理论，不断最大化不兼容图中的有效解集势，为系统储备异构容灾方案。

### 3.4 稀疏有向环迁移总线协议（Sparse Directed Ring Migration）
为了平衡全网多样性与知识共享，三大孤岛建立**稀疏有向环形迁移拓扑（Sparse Directed Ring）**：
$$\text{Island } 0 \xrightarrow{\text{P-Migration}} \text{Island } 1 \xrightarrow{\text{P-Migration}} \text{Island } 2 \xrightarrow{\text{P-Migration}} \text{Island } 0$$

```
                           稀疏有向环迁移拓扑
              ┌─────────────────────────────────────────┐
              ▼                                         │
     ┌─────────────────┐                       ┌─────────────────┐
     │ 孤岛 0: Anchor  ├──────────────────────►│ 孤岛 1: Anneal  │
     │ (保守冠军锚点)  │   最优精细骨架卡片    │ (激进退火探索)  │
     └─────────────────┘                       └────────┬────────┘
                                                        │
                                                        │ 高潜异构表型
                                                        ▼
                                               ┌─────────────────┐
                                               │ 孤岛 2: Novelty │
                                               │ (新颖性沙箱特区)│
                                               └─────────────────┘
```

- **低频迁移时钟**：每隔固定代际 $\Delta E_{\text{migration}} = 5$ 代激活一次迁移总线；
- **轻量表型卡片交换**：禁止跨孤岛直接拷贝原始 Python 源码全文！迁移介质仅为不可变强类型表型摘要（包括核心 AST 特征哈希、实测物理度量、3D 行为坐标与 Stanford ACE 战术条目）；
- **非贪心抽样**：迁出个体采用轮盘赌或新颖度前沿抽样，坚决杜绝单纯将本岛第 1 名强灌邻岛。

### 3.5 阻断选择性扫荡与希钦-骑乘效应的隔离屏障
传统退火系统在某一单点突破后，优势基因会以指数级扩散横扫所有岛屿（Selective Sweep），导致全网多样性归零。AFEVA 通过有向拓扑与门禁实施**扫荡阻断（Sweep Barrier）**：
1. **单向不可逆单向流**：新颖性岛的踏脚石可以单向流入锚点岛作为备选，但锚点岛的贪心优势解必须经过激进退火岛的充分高温洗礼，方可间接渗入新颖性特区；
2. **非同源杂交拦截**：严禁大模型将 AST 距离超标的异构代码进行生硬文本拼接；跨流派融合必须通过“速度核心模块提取 + 兜底包络模块集成”的受控双向打补丁完成，彻底消灭希钦-骑乘非本质缺陷传染。

---

## 4. 反应式因果 DAG 事件流与无锁流水线调度

### 4.1 偏序因果 DAG 与局部就绪门（破除全局代际木桶效应）
系统彻底废除将整个集群卡死的集中式 Epoch Barrier Lock，全面确立基于偏序关系的**动态因果有向无环图（Dynamic Causal DAG）**：
$$\mathcal{G} = (\mathcal{V}, \mathcal{E}, \prec)$$
- **顶点 $\mathcal{V}$**：代表原子执行任务（如假说推演、代码合成、门禁检验）；
- **边 $\mathcal{E}$**：代表不可变构件的生产与消费因果依赖；
- **局部就绪触发准则（Local Causal Trigger）**：
  $$\text{Ready}(v) \iff \forall u \in \text{Pred}(v), \quad \text{Status}(u) = \text{COMPLETED} \land \text{Artifact}(u) \neq \emptyset$$
  只要上游直接前驱完备，下游节点立即激活执行。慢速分支在超时截断前在自身因果链条上追赶，快跑分支高速向前展开，全局木桶短板时延被彻底粉碎。

### 4.2 单调分层因果等级定理与死锁自由度（Deadlock-Free）形式化证明

#### 定义 1：因果等级映射（Causal Stratification Level）
定义映射函数 $\mathcal{L}: \mathcal{V} \to \mathbb{N}$，为系统中的每个计算顶点赋予一个全局单调的非负整数因果等级。

#### 定理 1：单调因果图死锁自由定理（Deadlock Freedom via Monotonic Causal Ranks）
若系统因果依赖拓扑 $\mathcal{G} = (\mathcal{V}, \mathcal{E})$ 满足**单调分层不变量（Monotonic Stratification Invariant）**：
$$\forall e = (u, v) \in \mathcal{E}, \quad \mathcal{L}(u) < \mathcal{L}(v)$$
则系统在数学上**绝对不存在任何有向环路（Directed Cycles）**，因而在有限时间内必定满足死锁自由（Deadlock-Free）。

#### 形式化证明：
1. （反证法）假设系统中存在一个由 $K$ 个节点构成的死锁环路 $\mathcal{C} = (v_1, v_2, \dots, v_K, v_1)$，其中 $(v_i, v_{i+1}) \in \mathcal{E}$ 且 $(v_K, v_1) \in \mathcal{E}$；
2. 依据单调分层不变量，对于环路中每一条有向依赖边，其因果等级必须满足严格递增：
   $$\mathcal{L}(v_1) < \mathcal{L}(v_2) < \dots < \mathcal{L}(v_K) < \mathcal{L}(v_1)$$
3. 由整数偏序关系的传递性，必然导出：
   $$\mathcal{L}(v_1) < \mathcal{L}(v_1)$$
4. 显然产生数学矛盾（任何整数不可能严格小于自身）。因此假设不成立，图中不存在任何有向环路，$\mathcal{G}$ 严格为有向无环图（DAG），得证。

### 4.3 需求反向拉取流控（Credit-based Demand Backpressure）
为了防止上游自回归模型生成速率远高于物理沙箱测试速率引发的信箱爆仓（Bufferbloat），系统全面引入反应式拉取模型：
1. 下游沙箱池根据可用物理核心数，动态向调度器反向发放信用额度：`Subscription.request(n)`；
2. 信用池实时方程：
   $$\text{Credit}_{\text{pool}}(t) = \text{Capacity}_{\text{max}} - \text{ActiveSandboxes}(t)$$
3. 当且仅当 $\text{Credit}_{\text{pool}}(t) > 0$ 时，调度引擎才激活就绪队列中的下一个生成任务；当沙箱饱和时，背压自动阻断上游任务激活，系统算力永远处于最佳吞吐工况。

### 4.4 投机执行令牌与 Saga 级联毒丸清算（Poison-Pill Protocol）
为了实现极致流水线吞吐，系统采用两阶段乐观执行协议：
1. **投机令牌发放（Speculative Execution Token）**：Worker 提交代码通过 Tier 1 粗审后，系统立刻签发带有 `is_speculative=True` 属性的 `CausalToken`，下游任务凭此凭证乐观启动后续推演；
2. **后台深度审计（Tier 2 & 3）**：由独立的法医法庭池在后台以独占物理核心方式开展深度校验；
3. **Saga 补偿与级联毒丸（Poison-Pill Cascading Cleanup）**：
   - 一旦后台发现该投机代码存在致命硬编码作弊或段错误，系统立刻发射 `P0` 级 `PoisonPillEvent`；
   - 调度器沿着因果 DAG 前向边，在毫秒级内递归搜寻以该作弊节点为祖先的所有正在运行的派生 Worker；
   - 强制发送终止信号并释放对应 RAM-Disk 内存，同时在 DAG 中标记为毒丸墓碑（Poison Tombstone），保证系统的最终一致性。

### 4.5 Tarjan 强连通分量动态破环算法
针对非预期的非因果性软死锁（例如外部资源争用导致的相互等待），常驻的 **Tarjan-Watchdog** 守护协程执行毫秒级巡检与外科手术式自愈：

```python
# Tarjan 动态破环核心算法机制
def resolve_deadlocks_via_tarjan(dag: DynamicCausalDAG) -> List[str]:
    # 1. 提取所有处于 WAITING / BLOCKED 状态的等待图
    waiting_graph = dag.get_blocked_dependency_subgraph()
    
    # 2. 运行 Tarjan 强连通分量 (SCC) 算法
    sccs = tarjan_scc(waiting_graph)
    resolved_cycles = []
    
    for component in sccs:
        if len(component) > 1:
            # 3. 识别出死锁闭环，选定环路中“投机凭证级别最低、运行时间最长”的依赖边
            victim_edge = select_optimal_victim_edge(component)
            
            # 4. 执行依赖截断，注入死信墓碑
            dag.sever_edge_and_inject_tombstone(victim_edge)
            resolved_cycles.append(f"Severed cycle at {victim_edge}")
            
    return resolved_cycles
```

---

## 5. 捕食者-猎物协同演化全周期排期与阶梯门禁流转

### 5.1 求解器（猎物）与造尺人（捕食者）动态对抗模型
彻底打破静态评测集的僵化垄断，建立双向对抗协同进化动力学：
- **猎物种群（Prey: Solvers）**：多并发 Worker 不断演化出速度更高、结构更新颖的算法代码；
- **捕食者种群（Predator: Adversarial Graders）**：专门针对当前领跑的高速算法，由独立的异构模型基于几何凹凸性、边界极限值生成定制挑战算例。

### 5.2 动态课程排期（幼年期、成长期与生产期）

| 演化时期 | 代际跨度 | 捕食者开放测试难度 | 准入策略与门禁动作 | 重点保护对象与使命 |
| :--- | :--- | :--- | :--- | :--- |
| **幼年探索期 (Childhood)** | Epoch 0 ~ 3 | **Level 0 (语法) + Level 1 (基础通用工况)**；物理屏蔽 Level 3 变态 Corner Cases。 | Tier 1 粗野放行。全域速度提升即予晋级，边界缺陷不扣分。 | **绝对保护 `node_02` 级革命性火种**，绝不让幼苗死在开局严苛用例下。 |
| **协同成长期 (Growth)** | Epoch 4 ~ 8 | **Level 0 ~ Level 2 (压力与核心规模)**；激活捕食者生成针对性 Corner Cases。 | 偏科生进入暂存池；与捕食者对抗反例配对，强制实施定向杂交打补丁。 | 融合优势速度模块与稳健兜底模块，打磨健壮抗体。 |
| **生产终局期 (Mastery)** | Epoch 9+ | **Level 0 ~ Level 3 (全量极端对抗测试套件)**；引入法医审计防作弊穿透。 | Tier 3 钢铁门禁终审。全量用例 100% 满分通过，零方差全息重现。 | 守死 Master 分支生产级质量底线，确保绝对交付安全。 |

### 5.3 偏科生带病晋级与定向杂交补丁工作流
1. **偏科特征登记**：当某算法在幼年期展现出极端速度优势（如 300s，比基准提速 40%），但遇到极端凹边界用例报错时，Tier 1 门禁标记为 `PROBATIONARY_PASS`，记录其几何薄弱特征；
2. **定向反例注入**：成长期启动时，捕食者 Agent 针对该算法的凹边界特征生成针对性测试集；
3. **杂交补丁合成（Hybrid Patching）**：调度器提取保守岛的成熟安全边界包络逻辑，引导杂交突变算子将其作为兜底外壳包裹在高速核心外部，完成偏科代码向工业级全能代码的蜕变。

### 5.4 终局交付 Master 主干推进协议
1. **生产分支合并互斥锁**：本地 Git `main` 主分支推进必须持有全局排他性 `MasterMergeLock`；
2. **CAID 终局全量扫描**：
   - 提取最新候选解源码；
   - 静态类型检查 `mypy --strict` 零告警；
   - 物理独占核心执行 3 次全息回放，关键度量方差 $\le 1.0\%$；
3. **原子指针更新**：主干指针推进成功后，自动触发全代收敛广播，向系统所有活跃节点通报全局基线更新。

---

> **拓扑签署**：AFEVA 演化拓扑与沙箱设计委员会（worker_m1_synth）  
> **审定状态**：正式归档，完全指导 M2/M3 代码落地与 M4/M5 自动化仿真测试。
