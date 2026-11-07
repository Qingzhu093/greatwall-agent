---
name: greatwall-campaign
description: 长城 Agent V4.2 无人值守科研与竞赛全周期编排技能。当用户需要启动算法竞赛、数学建模或 AI for Science 长程自动探索、运行 Phase 0 开局知识蒸馏、调度无 .git 清洁室孤岛微创迭代、执行 60 步原位内省室或打包终局五件套交付信封时激活。触发词：长城 agent、无人值守攻关、开局蒸馏、清洁室沙箱、五件套遗产、跨分支拼图。
---

# 长城 Agent V4.2 无人值守攻关标准作业规程 (Great Wall Campaign Runbook)

本技能驱动 `greatwall-agent` MCP 服务器提供的 9 个原生工具与 3 个专用子智能体（`gw-distiller`、`gw-explorer`、`gw-auditor`），将长程无人值守攻关划分为 **4 个确定性阶段**。

> [!CAUTION]
> **总管（Orchestrator）最高角色隔离铁律（严禁犯“包工头越位综合征”！）**
> 1. **总管只管顶层架构、资源调度与裁决**：总管**绝对禁止**跳过 `invoke_subagent` 自己在主控会话里手搓 `NODE-001 ~ NODE-004` 的探索代码！
> 2. **三权分立强制派发**：
>    - **开局蒸馏与造尺**：必须调用 `invoke_subagent(TypeName="gw-distiller")` 派发开局蒸馏专家；
>    - **清洁室孤岛攻关**：每次 `gw_allocate_slot` 分配槽位后，必须调用 `invoke_subagent(TypeName="gw-explorer")` 派发独立的探索节点进驻 `worktrees/<slot_id>/` 内部迭代；
>    - **独立扒皮审计与内省**：每轮关键突破、满 60 步内省室及终局交付前，必须调用 `invoke_subagent(TypeName="gw-auditor")` 派发手握一票否决权的独立审计官进行穿透审查！
> 3. **严禁既当运动员又当记分员**：评测基准（`.kernel_vault/evaluator_suite/evaluate_runner.py`）必须在 Phase 0 锁死在内核保险箱中；严禁在候选脚本里写 `iso_gap = min(0.03, iso_gap)` 等截断作弊代码，严禁把“含未清除惩罚的折合耗时”谎报为“100% 清除率”！

---

## 阶段 0：开局前置消歧、盲态造尺与先蒸馏引擎 (Phase 0: Pre-Flight & Opening Distillation)

### Step 0.1：三步前置消歧与工作区初始化 (`gw_init_campaign`)
1. **数据静态探针（EDA Grounding）**：将解析后的题面与公开数据集放入 `<workspace>/shared_readonly/datasets_public/`，调用 `gw_init_campaign` 自动执行确定性 EDA 探针并生成 `eda_probe_report.json`，锁死 `task_config.yaml`（**绝对禁止在盘中分裂 $A / \neg A$ 歧义分支**）。
2. **盲态造尺锁定（Immutable Evaluator Suite）**：在 `.kernel_vault/evaluator_suite/evaluate_runner.py` 中锁死独立评测器（严格对齐官方单狗/边界/无作弊完成信号规则，分离输出综合得分与真实目标清除率 `clearance_rate` 等分项诊断指标），严禁后续探索节点篡改评测逻辑。

### Step 0.2：委派 `gw-distiller` 盲态造锤造尺、开局知识蒸馏与铸造【零号强基线 $s_0$】(`gw_lock_distillation`)
1. **强制调用 `invoke_subagent(TypeName="gw-distiller")`**：在独立上下文中检索近 3 年同类任务现代 SOTA 方案，划清《反预训练偏见黑名单》与《调库 vs 造轮子边界清单》。
2. **一等公民锁定物理模拟器与盲态评测器（杜绝模拟器和 `evaluate()` 混入 `src/main.py`）**：
   - 在调用 `gw_lock_distillation` 时，必须通过 `simulatorCode` 传入带 `def test_*():` 自检函数的独立物理模拟器（引擎自动验证无 `is_all_cleared` 作弊信号后写入 `shared_readonly/simulator.py` 供所有孤岛只读 `import simulator`）；
   - 必须通过 `evaluatorRunnerCode` 传入定义有 `def evaluate_candidate(cand_mod) -> dict:` 的三级级联盲态评测器（引擎自动锁入 `.kernel_vault/evaluator_suite/evaluate_runner.py`，显式分离输出 `clearance_rate` 真实清除率、`cascade_level` 与 `frozen_score` 含惩罚折合分）。
3. **候选基线竞技选优**：编写 1~3 个结构清晰、通过 `import simulator` 调用环境的候选基线代码，传入 `candidateBaselines`（或 `anchorBaselineCode`），在沙箱实跑竞技选优铸造【零号强基线 $s_0$】（测定 `anchor_s0_score` 与基线真实清除率）。

---

## 阶段 1 & 2：清洁室孤岛并发深耕与微创代码手术 (Clean-Room Slot Loop)

### Step 1.1：总管分配无 `.git` 清洁室孤岛 (`gw_allocate_slot`) 并派发 `gw-explorer`
- 总管调用 `gw_allocate_slot` 为指定 `familyId` 分配槽位，明确指明本轮锁定的单一微创手术代码块 `targetedCodeBlock` 与可证伪假说 `hypothesis`。
- 总管调用 `invoke_subagent(TypeName="gw-explorer")`，将 `<island_path>` 与 `<slot_id>` 交给探索节点子智能体独立执行（支持并行启动多个 `gw-explorer` 探索不同正交方法族）。

### Step 1.2：`gw-explorer` 在孤岛内执行代码块微创替换 (`gw_surgical_replace`)
- `gw-explorer` 先读取 `<island_path>/scoped_brief.md`（含 `PRIMITIVES_API.md` 可直接 `import` 的原语函数签名表与死胡同避坑表）。
- 调用 `gw_surgical_replace` 传入 `slotId`、`targetBlockName`（支持顶层函数/类及 `ClassName.method`）与 `newBlockCode`，原位微创替换目标代码块并自动生成 `legacy_out/diff.patch`。
- 若中途改乱代码，可调用 `gw_lineage_control(action="soft_flush")` 原地软清栈回滚至干净基底快照。

### Step 1.3：跨进程防作弊评测与四级分诊 (`gw_evaluate_slot`)
- 调用 `gw_evaluate_slot` 在 64 位 Windows Job Object 硬件限额与脱敏环境变量下运行跨进程隔离评测：
  - 自动执行 AST 安全扫描（拦截 `min(0.03, iso_gap)` 等遮羞作弊）、过时模型与手搓轮子拦截、多模态完整性对账与同构置换扰动测试；
  - 在 `legacy_out/metrics_receipt.json` 生成带 HMAC-SHA256 防伪签名的成绩单，并返回四级分诊结果（`PARETO_PROMOTE` / `NICHE_CHAMPION` / `IN_PLACE_REPAIR` / `DEAD_END_ARCHIVE`）。

### Step 1.4：五件套遗产验收入库与五步墓碑回收 (`gw_submit_legacy`)
- `gw-explorer` 退场前，在 `<island_path>/legacy_out/` 下备齐【五件套遗产包】：
  1. `epitaph.md`：$\le 150$ 字死胡同避坑或核心物理机理总结；
  2. `diff.patch` + `metrics_receipt.json`（已自动生成）；
  3. `primitives/<name>.py`（附类型注解、Docstring 与 `def test_<name>():` 单元测试）或 `barrier_proof.json`（死路反例验证脚本）；
  4. `anomalies_and_bounties.json`（可选）；
  5. `last_will_proposals.json`：1~3 条下一步接力遗嘱提案（`REPAIR | GRAFT | EXTEND | ORTHOGONAL`）。
- 调用 `gw_submit_legacy` 验收入库、统计跨血统原语真实引用次数、自动提炼共性死因补丁并回收孤岛目录。

---

## 阶段 3：独立审计官穿透审查与 60 步原位内省室 (`gw-auditor`)

1. **穿透式反自欺审计**：
   - 总管调用 `invoke_subagent(TypeName="gw-auditor")` 进驻审查：编写极限边界压测脚本（如小交角 GDOP 发散、50 随机种子盲测）或调用 `gw_lineage_control(action="differential_test")` 开展跨分支无标签差分互测，对任何虚报清除率或物理伪解行使**一票否决权（REJECT）**！
2. **60 步原位 3 轮内省室 (`submit_reflection`)**：
   - 当某方法族谱系累计运行满 60 步（`trigger_60_step_reflection_chamber: true`）时，由 `gw-auditor` 主持三轮九大拷问，并调用 `gw_lineage_control(action="submit_reflection")` 将未来 20 步军令状持久化至 `.kernel_vault/reflections/`。

---

## 阶段 4：跨分支结构拼图与终局五件套交付 (`gw_compile_delivery`)

1. **跨分支结构拼图（Structural Synthesis）**：
   - 调用 `gw_archive_query(action="get_l0_index")` 查阅 `PRIMITIVES_API.md` 中各方法族沉淀的高引用原语；
   - 派发拼图槽位（`action_type: GRAFT`），直接 `from archive.ledger.primitives.xxx import yyy` 嫁接互补算子，实跑消融验证净收益。
2. **编译终局五件套交付信封 (`gw_compile_delivery`) 并由 `gw-auditor` 终审签字**：
   - 调用 `gw_compile_delivery` 生成 `final_delivery/`（报告、脱机自包含源码与原语包、HMAC 证据总账本、带 UTF-8 BOM 兼容 PowerShell 5.1/7 的 `04_reproduce_all.ps1`、适用边界与死胡同避坑档案）。
