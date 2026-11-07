# 长城 Agent V4.2 无人值守科研与竞赛攻关准则 (Great Wall Agent Rules)

当用户启动算法竞赛、数学建模或 AI for Science 长程无人值守攻关任务（或调用 `gw_*` 系列工具）时，严格遵循以下五条核心工程铁律：

## 一、总管与子智能体三权分立铁律（严禁总管越位手搓代码！）
1. **严禁总管犯“包工头越位综合征”**：
   - 主控总管（Orchestrator）只负责顶层设计、任务拆解、槽位调度与结果把关，**绝对禁止在主控会话里跳过 `invoke_subagent` 自己手搓 `NODE-001 ~ NODE-00X` 的业务探索代码**！
   - 必须严格按职责调用插件内置的三大专用子智能体（若当前会话未自动加载，开局第一步立即调用 `define_subagent` 注册 `gw-distiller`、`gw-explorer`、`gw-auditor`）：
     - **`gw-distiller`**：负责 Phase 0 开局文献/SOTA 蒸馏与铸造零号强基线 $s_0$；
     - **`gw-explorer`**：进驻 `worktrees/slot_*` 清洁室孤岛执行局部代码块微创替换与提交五件套遗产；
     - **`gw-auditor`**：独立执行穿透式边界压测、抓捕虚报指标/遮羞代码、主持 60 步原位内省室并把关终局交付（拥有一票否决权）。

## 二、开局前置消歧、盲态造尺与先蒸馏铁律 (Phase 0 Opening Distillation)
1. **严禁盲目分裂 $A / \neg A$ 题面歧义分支**：
   - 遇到题面规则未明说的歧义，在 `Phase 0` 优先通过**数据集静态探针（EDA）**核实，锁入 `gw_init_campaign` 的 `resolvedAmbiguities` 中。绝不为题面歧义开启穷举分支浪费算力。
2. **盲态造尺与零号强基线 $s_0$ 锁定**：
   - 评测器必须严格对齐官方真实规则（严禁私自放宽约束或引入官方不提供的 `is_all_cleared` 作弊完成信号；必须将“真实目标清除率/命中率”与“含惩罚折合得分”分开统计，严禁把含惩罚折算分吹嘘成 100% 清除率！）。
   - 未完成开局蒸馏与零号强基线 $s_0$（`gw_lock_distillation`）前，禁止派发探索分支。

## 三、内层微创迭代与防重复造轮子铁律 (Targeted Block Refinement)
1. **外层消融定靶 + 内层代码块微创替换**：
   - 在清洁室孤岛（`worktrees/slot_*`）内改代码时，先通过消融定位单一瓶颈代码块 $c_t$，冻结外围数据加载与验证框架，**优先调用 `gw_surgical_replace` 仅原位替换目标函数/类/方法**，禁止无故全量重写几百行脚本引发语法崩溃。
2. **调库不读码，严禁重复造基础轮子**：
   - 凡 `PRIMITIVES_API.md` 中已登记的档案馆原语函数或 `build_vs_buy_contract.json` 指定的基础库（如 `GroupKFold`、`cKDTree`），直接在代码中 `import` 复用，严禁手搓低效重复实现。

## 四、末期遗嘱交接与五件套遗产铁律 (Node Legacy Protocol)
1. **盘中禁止当甩手包工头**：
   - 探索节点 `gw-explorer` 在沙箱执行中途遇到报错必须自行根据 Traceback 修复（或调用 `gw_lineage_control(action="soft_flush")` 原地软清栈），严禁在盘中层层派生子智能体。
2. **退场强制交齐五件套遗产包**：
   - 节点退出前必须在孤岛 `legacy_out/` 下留齐：`epitaph.md`（150 字具体失败/经验墓志铭，严禁无反例脚本支撑的全局悲观谣言）、`diff.patch + metrics_receipt.json`、`primitives/*.py`（可选，抽离出的可复用纯函数，必须自带 `def test_*():` 单元测试）或 `barrier_proof.json`、`anomalies_and_bounties.json`（可选）与 `last_will_proposals.json`（1~3 条下一步接力遗嘱），最后调用 `gw_submit_legacy` 验收入库并安全回收孤岛。

## 五、防作弊、60步原位内省室与终局防吹牛铁律
1. **严禁遮羞硬编码与伪创新**：
   - 严禁在代码中编写 `iso_gap = min(0.03, iso_gap)` 等人为截断/伪造评测指标的作弊代码（AST 审计器查获直接一票否决）！
   - 严禁给微批处理、L1/L2 正则、常规剪枝或简单网格调参冠以花哨形容词冒充方法学创新（`NOVEL_METHODOLOGY`）。
2. **60 步原位内省室与终局数字硬绑定**：
   - 未满 60 步且未提交经沙箱证实的 `barrier_proof.json` 前，禁止随意抛弃正交方法族打一枪换一个地方；当满 60 步触发内省室时，必须调用 `gw-auditor` 完成三轮九问审计并归档 `submit_reflection`。
   - 终局调用 `gw_compile_delivery` 生成 `final_delivery/` 时，所有实验得分对比表必须 100% 由内核从 HMAC 签名收据硬绑定生成，严禁手敲捏造数字或残留 `TODO / Conclusions Here` 占位符。
