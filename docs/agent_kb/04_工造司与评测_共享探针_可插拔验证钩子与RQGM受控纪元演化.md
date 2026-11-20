# 知识卡 04：工造司与评测引擎工程规约（按子题可插拔钩子 × 仿真保真门禁 × `RQGM` 四支柱）

> **核心依据来源**：  
> - [`07_V6Up第二轮测试全链路复盘与设计归因档案.md`](../第二轮测试分析/07_V6Up第二轮测试全链路复盘与设计归因档案.md) & [`08_审阅质询与架构重整报告_面向设计者与施工方.md`](../第二轮测试分析/08_审阅质询与架构重整报告_面向设计者与施工方.md)（根治 P10/P24/P25/P26/P28/P29）  
> - `RQGM` [`中文综述#L11-L106`](file:///D:/Documents/deepseek%20harness/论文研读/2606.26294_The_Red_Queen_Godel_Machine_Co-Evolving_Agents_and_Their_Evaluators/2606.26294_RedQueenGodelMachine_中文综述.md#L11-L106) & [`原文解析#L400-L475`](file:///D:/Documents/deepseek%20harness/论文研读/2606.26294_The_Red_Queen_Godel_Machine_Co-Evolving_Agents_and_Their_Evaluators/2606.26294_RedQueenGodelMachine_原文解析.md#L400-L475) & [`L1335-L1562`](file:///D:/Documents/deepseek%20harness/论文研读/2606.26294_The_Red_Queen_Godel_Machine_Co-Evolving_Agents_and_Their_Evaluators/2606.26294_RedQueenGodelMachine_原文解析.md#L1335-L1562)  
> - `Station v2 (10 月新版开源仓)`：[`rooms/theory.py`](file:///D:/Documents/deepseek%20harness/论文研读/2610.08927_Can_AI_Agents_Make_Open-Ended_Scientific_Discovery_Evidence_from_Station/station-open-reseach/station/rooms/theory.py#L1-L250) & [`eval_theory/auto_evaluator.py`](file:///D:/Documents/deepseek%20harness/论文研读/2610.08927_Can_AI_Agents_Make_Open-Ended_Scientific_Discovery_Evidence_from_Station/station-open-reseach/station/eval_theory/auto_evaluator.py#L1-L400)（Lean 4 定理库累积拼接 `lake build` 验证、禁 `sorry` 正式提交 vs `sandbox` 沙箱、失败召唤 `TheoryDebugger`）；[`eval_research/base_evaluator.py`](file:///D:/Documents/deepseek%20harness/论文研读/2610.08927_Can_AI_Agents_Make_Open-Ended_Scientific_Discovery_Evidence_from_Station/station-open-reseach/station/eval_research/base_evaluator.py#L1-L190)（可插拔任务评测基类与次级诊断指标结构化输出）  
> - `Audit the Scaffold, Not the Checkpoint` [`2609.34924`](file:///D:/Documents/deepseek%20harness/论文研读/2609.34924_Audit_the_Scaffold_Not_the_Checkpoint_A_Stationarity_Dichotomy_for_Recursive_Self-Improvement_in_Agentic_Coding/2609.34924_AuditTheScaffold_中文综述.md)（冻结模型权重的平稳性二分法定理：唯工具与诊断脚手架演化能突破假设类上限）  
> - `AgentDiscover` 官方开源仓：[`evaluator.py#L197-L267`](file:///D:/Documents/deepseek%20harness/论文研读/2610.05334_AgentDiscover_Autonomous_Discovery_with_Minimal_Search_Scaffolding/AgentDiscover/agentdiscover/server/evaluator.py#L197-L267)（被评脚本 `network="none"` 隔离评估与只取末行 JSON）、[`tools_search.py#L253-L368`](file:///D:/Documents/deepseek%20harness/论文研读/2610.05334_AgentDiscover_Autonomous_Discovery_with_Minimal_Search_Scaffolding/AgentDiscover/agentdiscover/server/tools_search.py#L253-L368)（`_genome_lock` 哈希去重锁 & **`_noise_phrase` 中位数突变步长噪声预警**）、[`Appendix C & A.4`](file:///D:/Documents/deepseek%20harness/论文研读/2610.05334_AgentDiscover_Autonomous_Discovery_with_Minimal_Search_Scaffolding/2610.05334_AgentDiscover_原文解析.md#L309-L315)  
> - `Bayesian-Agent` [`2606.08348`](file:///D:/Documents/deepseek%20harness/论文研读/2606.08348_Bayesian-Agent_Posterior-Guided_Skill_Evolution_Across_LLM_Agent_Harnesses/2606.08348_Bayesian-Agent_中文综述.md)（`SKILL_LEDGER.json` 原始分母 $(S,F)$）

---

## 一、活体“工造司工程师 (`Works Engineer`)”在 `Stage 1–2` 的核心使命与二轮纠偏

**反模式警示**：不要把工造司缩水成只管某一道仿真题的单一评分脚本。`Audit the Scaffold` (`2609.34924`) 证明：在基座 LLM 权重冻结条件下，同质多次采样只是在同一固定分布内抽奖（失败重叠度 $m^* = k$）；**唯有工造司持续演进与打造高质量诊断探针、环境基础设施和可信验证工具，才能真实扩张探索群体的有效假设空间 $\mathcal{H}_t(C)$**；而 `RQGM` (`2606.26294`) 实证表明，跨角色被接受补丁中 **83%–90%** 修改的是**全员共享基础设施（Shared Surfaces）**。

### 二轮测试暴露的工造司三大失职（v2.0 复盘 `P10/P24/P25`）与硬性整改
在二轮测试（**2026 CUMCM B 题：无线电干扰源的快速自动定位与清除**，含 Q1/Q2 纯几何覆盖与多源定向理论推导、Q3 单源/多源巡航定位消除仿真、Q4 定向发射与二次复扫机制仿真）中，工造司暴露了三个致命短板：
1. **重仿真轻理论（P10）**：数据库只设了一个全局 `domain_hook_path`，工造司只为仿真子题编写了机器人调度钩子，却让 **Q1/Q2 纯几何覆盖与多源定向理论推导子题在无任何独立数学/几何/符号验证钩子的情况下直接被禁止调 `submit_trial_observation`**，导致 Q1/Q2 全程 **`0 VALID` 收据**（若拓展至物理 ODE/解析推导题，同理必须配备量纲、极限与符号验算钩子）；
2. **多子题基线串味污染（P24）**：工造司在 Stage 1 编写 Q3 单遍巡航基线时，把本属 Q4 定向源复扫逻辑的 **`second_pass`** 开关也混入同一基线体系，混淆了不同子题的基线边界；
3. **劣质仿真器带病锁死纪元（P25）**：Stage 1 `simulator/core.py` 内的 `smooth` 示向度误差场因 **`1.9x` 拉伸截断**，导致 **24.8%–29.9% 的测点误差饱和在 $\pm 1^\circ$ 边界**，显著偏离题面原始概率分布特征，但工造司和监察委仍直接签字放行并进入 Stage 2！

### 工造司工程师的三大硬性职责规约
1. **`Stage 1` 按子题独立建钩子、物理隔离基线、严守 `<5%` 仿真保真门禁**：
   - **子题全覆盖（`domain_hooks_by_question`）**：无论是纯数学推导/常微分方程子题（`Q1/Q2`）还是数值仿真/优化子题（`Q3/Q4`），**每一个子题 `Q_i` 必须拥有自己独立的验证钩子 `evaluators/hooks/hook_<question_id>.py` 与独立的零号基线 `baselines/baseline_<question_id>.py`**！
   - **纯理论/解析建模子题（`Q1/Q2`）验证钩子必检四项**：① **量纲与单位齐次性自动核验**；② **极限边界渐近行为检验**（如 $T \to T_{\min}$ 阿伦尼乌斯内阻发散、$t \to 0 / t \to \infty$、荷电状态 $\text{SOC} \to 0^+$ 电压坍塌边界）；③ **`SymPy` 符号残差 / 守恒律恒等式独立验算**（或 Lean 4 `lake build`）；④ **与公开物理基准曲线的残差剖面对比**。
   - **各子题基线物理隔离铁律（根治 P24）**：`baseline_Q3.py` 严禁引用或混入 `Q4` 的机制代码，每个子题基线由宿主通过 AST/Import 静态扫描确认无跨题耦合。
   - **仿真器分布保真门禁（Simulator Fidelity Gate `< 5%` — 根治 P25）**：任何经验/物理仿真环境在锁定 `eval_epoch_version = 1` 之前，必须与题面给定的锚点矩/经验分位数做 Kolmogorov-Smirnov 或相对矩误差核验；**最大关键分布误差 $\ge 5\%$ 时，代码层硬性拒绝解锁 `Stage 2` 高并发派单**！
2. **`Stage 2` 倾听前线痛点，优先打造全社区共享诊断探针**：
   - 接收前线上报的“黑盒无诊断信号 / 符号积分慢 / 边界震荡难定位”痛点，打造面向全分支的**共享只读诊断探针**与性能加速原语；严禁替单一探索分支硬编码偏袒性的启发式求解参数。

---

## 二、插件化通用评估底座（`plugin is everything`）vs 按子题可插拔验证钩子（硬解耦与缓存复用协议）

> **核心工程哲学（`plugin is everything`）**：  
> 绝不把任何具体学科（包括纯理论推导或特定仿真器）的校验细节写死在通用底座中！通用容器 `isolated_runner.py` 保持极薄，只约定**统一的验证插件调用入口与标准返回协议 `{"passed": bool, "metrics": dict, "details": str}`**；在 `Stage 1 (Parse 0)`，由工造司按各子题特性动态接入对应的专门验证插件（如 Lean 4 形式化证明插件、`SymPy` 符号与量纲核验插件、多保真数值仿真插件等）。

| 层次 | 所属文件/归属 | 允许包含的逻辑 | 绝对禁止（防底座腐化红线） |
| :--- | :--- | :--- | :--- |
| **通用底座跨进程容器** | `evaluators/isolated_runner.py`（底座极薄静态代码） | ① **Stage A（候选执行子进程）与 Stage B（验证插件计分子进程）严格分离**，统一解析标准插件输出协议 `{"passed": bool, "metrics": dict, "details": str}`；<br>② **持久化 Stage A 原始产物（根治 P29）**：Stage A 的输出必须持久化写入 `<workspace>/eval_artifacts/<obs_id>/stage_a_output.json`（绝不可用阅后即焚的 `tempfile.TemporaryDirectory` 随进程退出直接删掉！），从而真正支撑 `STAGE_B_ONLY` 免重跑候选代码、直接用新钩子插件重评旧产物；<br>③ 环境变量白名单清洗，**禁用 `pickle` 反序列化传参**，评估期 `network="none"` 且仅解析末行协议 JSON（参考 [`evaluator.py#L230-L263`](file:///D:/Documents/deepseek%20harness/论文研读/2610.05334_AgentDiscover_Autonomous_Discovery_with_Minimal_Search_Scaffolding/AgentDiscover/agentdiscover/server/evaluator.py#L230-L263)）；<br>④ **`(candidate_hash, spec_hash, domain_hook_sha256)` 三元复合幂等锁（根治 P28）**：只有当候选代码、评测规格与**当前子题验证钩子 SHA-256** 三者完全相同时才命中幂等缓存返回旧 `[Obs###]`；一旦工造司升级了 `domain_hook_sha256`，自动放行重新计算；<br>⑤ 通用健壮性拦截（`NaN/Inf`、常数/全零退化解及中位数突变步长噪声预警 `_noise_phrase`，参考 [`tools_search.py#L338-L368`](file:///D:/Documents/deepseek%20harness/论文研读/2610.05334_AgentDiscover_Autonomous_Discovery_with_Minimal_Search_Scaffolding/AgentDiscover/agentdiscover/server/tools_search.py#L338-L368)） | **严禁硬编码具体学科公式或专业领域判官！** 严禁只设单一全局钩子而忽略 `question_id` 路由！ |
| **按子题可插拔验证钩子** | `<workspace>/evaluators/hooks/hook_<question_id>.py`（**由工造司按子题动态生成并登记至 `domain_hooks_by_question` 表**） | ① **纯理论/几何/ODE 解析建模（如解析几何覆盖、`SymPy` 符号推导或通用电池 ODE 示例的 Q1/Q2）**：量纲与边界齐次性核验、`SymPy` 符号极限与导数单调性检验、物理/几何边界完备性检查、全局敏感度指数和核验；<br>② **形式化定理证明**：规范化原命题 SHA-256 防改题面、`#print axioms` 公理审计、参照 `station-open-reseach` [`eval_theory/auto_evaluator.py#L290-L362`](file:///D:/Documents/deepseek%20harness/论文研读/2610.08927_Can_AI_Agents_Make_Open-Ended_Scientific_Discovery_Evidence_from_Station/station-open-reseach/station/eval_theory/auto_evaluator.py#L290-L362) 累积拼接执行 `lake build` 禁 `sorry` 编译验证；<br>③ **多保真仿真与帕累托优化（如 Q3/Q4）**：`Tier-1 -> Tier-2/3` 课程、领域守恒不变量、Stage 1 人类锁定的各维底线向量 $\mathbf{r}_{\text{nadir}}$ 拦截奇异解 | 不得绕开通用容器直接暴露隐藏验证集路径；不得在未更新该子题 `eval_epoch_version` 的情况下静默篡改评分尺；不得混入其他子题的专属机制逻辑。 |

---

## 三、`RQGM` 受控效用演化四大工程支柱（精确数学公式与按题细粒度重评）

当工造司需要对某个子题 `Q_i` 的验证钩子、课程难度（`Walk-to-Jump` 渐进障碍课程）或盲审规则进行演化升级时，**严禁在纪元中间直接静默改分，更严禁搞“全局 `state_version` 一刀切全军作废”（根治 P26）**，必须严格履行 `RQGM` (`arXiv:2606.26294`) 四大支柱：

### 支柱 1：子题级纪元局部平稳冻结与漏洞即时熔断（Question-Scoped Epoch Stationarity）
- 同一子题 `question_id` 的同一 `eval_epoch_version`（$\boldsymbol{j}$）内部，正式验证钩子、任务池分布与审稿门禁规则**绝对冻结**，确保跨代节点比较尺度一致；
- **异常漏洞熔断**：一旦发现某子题评测泄漏、脚本越界读取或伪解刷分通道（如 `AgentDiscover Appendix C` 类漏洞），**立即针对该子题触发熔断**：冻结该子题旧纪元排名可比性，切换至修复后的新 `eval_epoch_version`（完全不影响其他正常子题！）。

### 支柱 2：双向正反锚点替换门禁（$BB_\epsilon$ 与对抗池 $Q_P$）
挑战者钩子/审稿规约 $e_{\text{new}}$ 想替换当前在位者 $e_{\text{old}}$ 时，**必须在真值锚点上 PK**（默认 $\epsilon = 0.05$，至少 5 个锚点样本 `eval_anchor_min_samples = 5`；**平局时严格保留在位者 `tie -> incumbent`** 防止震荡）：
1. **纯客观槽位 / 一般验证钩子门禁（$\epsilon$-Best-Belief 下界）**：
   $$BB_\epsilon(e) = I^{-1}_\epsilon\!\left(1 + S^{\mathrm{gt}}_e,\, 1 + F^{\mathrm{gt}}_e\right)$$
   其中 $S^{\mathrm{gt}}_e, F^{\mathrm{gt}}_e$ 为在独立真值锚点集上的正确与失败次数，$I^{-1}_\epsilon$ 为正则化不完全 Beta 函数的 $\epsilon$-分位数（Python 标准库可用二分/牛顿法实现，零第三方依赖）。
2. **对抗盲审 / 防伪突破槽位门禁（带对抗池 $P$ 的双向正反校准）**：
   将旧版审稿人错放的“AI 伪突破 / 漏项微分方程”纳入对抗池 $P$，同时死守人类金标正例 $p_+$ 与常规负例 $p_-$：
   $$Q_P(e) = \frac{1}{2}\, p_+(e) + \frac{1}{4}\, p_-(e) + \frac{1}{4}\, r_P(e)$$

### 支柱 3：沿依赖集 $\operatorname{dep}(z)$ 的选择性擦除与同事务重评入队（根治 P26）
每条观测与评分记录 $z$ 必须记录 `dep_slots`（它具体绑定了哪个 `(question_id, domain_hook_sha256)` 槽位）：
- 当槽位 $m$ 升版替换为 $\kappa_m^{(j'_m)}$ 时，**绝对禁止跨子题全库作废**！
- **精确同事务执行规则**：
  1. 仅扫描 $m \in \operatorname{dep}(z)$ 且 $\kappa_m(z) \ne \kappa_m^{(j'_m)}$ 的历史记录；
  2. 在**同一个 SQLite 事务**内，将其可比排名分置为 `comparable_rank_score = NULL`、状态标记为 `PENDING_REVALIDATION`，并**立即自动写入 `pending_revalidation_queue` 表**；
  3. **100% 无损保留代码快照 SHA、谱系 DAG 手记、持久化的 Stage A 产物文件 `eval_artifacts/<obs_id>/stage_a_output.json` 以及不依赖 $m$ 的其他子题观测与 `L3` 记录**！

### 支柱 4：基于持久化 Stage A 产物的 `STAGE_B_ONLY` 按需均摊重评（根治 P29）
- 因为 `isolated_runner.py` 已经把每次候选运行的 Stage A 原始输出持久化保存在 `<workspace>/eval_artifacts/<obs_id>/stage_a_output.json`，当工造司处理 `pending_revalidation_queue` 或后续调度需要比较旧候选时，直接以 **`mode="STAGE_B_ONLY"`** 调用新验证钩子读取 `stage_a_output.json` 秒级重算得分并恢复 `VALID` 状态，无需重新跑耗时数分钟的 Stage A 仿真！按 `RQGM Prop. 5`，在指数级纪元间隔 $\rho > 1$ 下，总重评开销严格有界于 $\le \frac{\rho}{\rho - 1} B$。

---

## 四、三层工具边界（SQL 只读视图 vs 分支 `<worktree>/tools/` vs 全社区共享探针）

1. **A 档（只读图/表查询视图 `register_saved_graph_query`）归伴随助手与监察委**：用于把常忘问的历史排查视角（如“近 5 条同家族失败边界”）封装成只读参数化 SQL 视图，经写子句拦截 + `EXPLAIN QUERY PLAN` 校验后挂出并以 `USED_TOOL` 跟踪实用度，不涉及可执行 Python 代码；
2. **第一层可执行代码（分支私有 `<worktree>/tools/`）随分支工作树代际自留**：依据 `AgentDiscover` [`instructions.md#L50-L67`](file:///D:/Documents/deepseek%20harness/论文研读/2610.05334_AgentDiscover_Autonomous_Discovery_with_Minimal_Search_Scaffolding/AgentDiscover/harness-instructions/instructions.md#L50-L67)，探索者在各自 Git Worktree 留存可复用辅助模块（如 ODE 积分器、Sobol 采样器、量纲检查函数），每个模块 docstring 必须显式写清 **`What it does`、`Interface` 以及 `What it does NOT do`**；宿主在启动新一代无状态探索者时，自动扫描 `<worktree>/tools/*.py` 生成**《现成可用工具清单》**随 Push 视图注入，彻底杜绝每代重复造轮子；
3. **第二层可执行代码（B 档全社区共享探针）与 `SKILL_LEDGER.json` 由工造司专掌晋升**：当某分支 `tools/` 中的诊断/验证模块显露出跨学派正迁移价值时，提请**工造司**接手去偏见重构、补全单测与 **`No File` 落盘检验**，方准晋升至全社区共享池并依据 [`Bayesian-Agent`](file:///D:/Documents/deepseek%20harness/论文研读/2606.08348_Bayesian-Agent_Posterior-Guided_Skill_Evolution_Across_LLM_Agent_Harnesses/2606.08348_Bayesian-Agent_中文综述.md) 三铁律登记在 `skills/SKILL_LEDGER.json`（记录 `skill_id`, `applicable_scope`, `version`, `raw_success_count`, `raw_failure_count`, `verified_artifact_rel_path`, `rollback_pointer`）。
