# 04 控制与运行时：Recon + Preview

> 作者：control-runtime（task-9）｜日期：2026-11-06｜只写本文件，未改既有 00–07
> 读了：00 规范、shared_frame、05、06、07、04 复盘、work/01 考古（均全文）；Anthropic `article_blocks.txt` 全文（BLOCK 021–069）；OpenAI CDC `cdc_prompt.pdf` 两页原文；TIPEX 与并发控制两篇中文综述全文。
> 未读：TIPEX、并发控制两篇 PDF 原文与其中转引的一手实验——凡引自这两篇的数字标「转引」，不升格为 A。机制等级按 00 规范 A–E；自家复盘标 [K]，不计入 A–E。

## A. 约束备忘

### A1 本领域架构必须支持什么
1. **执行异步、决策收敛**：不设全局同步 tick，以决策代统一比较与分配，比较前冻结版本。[A-实验] TIPEX Table 1/2：L2 上 GS（等齐）281.5s vs TKS（Top-K 截断）261.5s；BP 下 n=3→5 准确率 32%→37%、时延 261→188s，但 token 79k→99k。
2. **物理隔离 + 读快照绑版本指纹 + 合并期语义校验**：每路线独立 worktree；读时记版本指纹，提交时校验；合并跑测试/AST/类型而非只看 diff。[C-框架] 并发控制 position §4.2（CAID 55.5%→63.3% 为其转引，未核原实验）。
3. **内核确定性**：预算、锁、worktree、超时、事件日志由代码记账并强制执行，LLM 只出 plan，代码账目为最终依据。[B-实验弱] 07 §1 的设计立场；设计系统 45/45 e2e 只证明编排库自身可跑（[R]，work/01 §5），不证明机制有效。
4. **三货币分账**：准入（有效性 binary）、质量（Pareto 向量）、探索信用（只发预算、必须有产物）不得折成一个总分。[C-框架] 06 §6.1；反例 [B]：AI Scientist 复评自产 7/7 全拒、漏掉全部硬伤（2502.14297 §2.6）。
5. **版本钉住 + 步级检查点 + 幂等工具 + 故障注入**。[D-自述] Anthropic §05 只有 "durably execute"、"resume from where the agent was" 等定性描述，无恢复率；自家 [K]：V2 有 4 个子会话因超时/额度中断无 transcript，V3 的 node_07/08 遇 429 耗尽、node_08 从未启动（work/01 §1.2–1.3）。
6. **总控窄上下文**：brief + frontier + 预算 + 决策记录约 8–10k token；子 Agent 只给 brief 与文件路径。[D-自述] Anthropic 附录 3 的 artifact 引用；06 §4 的 8–10k 是设计值，无外部证据。

### A2 现有设计缺什么
1. **事件 schema 缺失**：05/06 有 trace/state/artifact 三分，但事件类型、决策代边界、版本钉住字段、恢复语义均未定义。[E]
2. **预算只到"计量"**：探索信用公式 w1–w4 未标定（06 §12 自认），发行/回收/审计规则空白。[E]
3. **并发协议只到 worktree+决策代**：无 MVCC/快照读/冲突检测/回滚粒度的具体协议。[C]
4. **评判权限边界未定**：Maintainer 能否加 live 难度未拍板（06 §12.6）；Auditor 的触发与权限未定义。[E]
5. **恢复无验收指标**：缺"恢复后重复副作用次数、重放一致率"这类门禁。[E]

### A3 三条最关键约束
1. **时间不对称**：LLM 推理秒–分钟 vs 工具毫秒；悲观锁冻结系统，乐观回滚烧 token，只剩 MVCC/快照读 + 延迟校验。[C-框架] 并发控制 §1.2、§4.1。
2. **评判器是系统的一部分**：TIPEX 实测与 Oracle 差 5–15%，换 Judge 模型还原率 78.3% vs 65.9%（转引其附录）；AI Scientist 评审漏全部硬伤 [B]。→ frozen set 永不变 + 校准集 + Judge/红队/维护者/审计分离。[C]
3. **预算必须是硬上限**：CDC 只给 8 小时下限、没有上限（原文 Termination 节），是本项目必须补的缺口；Anthropic 多智能体约 15× chat token [D]；V3 因 429 断链 [K]。→ Budget 是准入条件，不是事后统计。[C/E]

### A4 三个待定问题
1. **调度 Agent 用 LLM 还是规则**：07 §1 定"两个都是 Agent、手是代码"，但 8–12 活跃节点下 LLM 调度是否优于规则调度，无任何对照。[E]
2. **决策代频率与长度**：按 N 动作、预算区间，还是 TKS 式"等一半"？TIPEX 的 TKS 是单任务内选拔，能否搬到跨路线决策未证。[E]
3. **worktree 上限的依据**：06 §5.4 的"活跃 8–12、每节点≤3 子节点"没有出处，需与预算/时延一起标定。[E]

## B. 设计立场

### B1 核心主张
控制层的最小充分集是**五个原语**，其余（总控/调度/红队/维护者）都是原语上的策略：EventLog（唯一事实源，append-only）、Budget（三货币账本）、Worktree（隔离与生命周期）、DecisionEpoch（决策代）、Verdict（三层门禁判定）。
**总控做语义（选方向/批生长/定预算），调度做路由（排队/合成 brief/升级冲突），内核做记账与强制执行；三者只通过 EventLog 与 Budget 交换事实。** 拒绝代际硬栅栏（用决策代 + Top-K 截断替代）；拒绝把探索奖励塞进质量分。
- **worktree 生长**：发芽 = 子 Agent 提案 + 总控批准 + 调度器校验预算/容量；休眠保留理由与复活条件；复活必须有新证据（新测试/新文献/跨路线组合）；防爆炸用"每节点≤3 子节点、活跃≤8–12、每分支预算上限、同族同假设去重"。[E]
- **恢复协议**：EventLog 重放 + 步级 checkpoint；写动作带 idempotency_key；恢复先校验 base_fingerprint，不一致走重新对齐而非盲重放；版本钉住 prompt/工具/模型。[E]
- **测试集与权限四边界**：frozen（永不变，跨版本可比）+ live（红队/维护者可增，防过拟合），交付两套都报；总控不改账、调度不改方向、Judge 不改集合、Maintainer 不改 frozen。[C]

### B2 对象/接口草案（与 shared_frame 对齐）
| 对象 | 来源 | 关键字段 | 关系/冲突 |
|---|---|---|---|
| EventLog | 本文补 | seq, ts, epoch_id, actor, action_type, input_hash, output_refs[], budget_delta, version_pin, idempotency_key | shared_frame §3 只列层名、无对象卡 → 缺口 |
| Budget | 本文补 | epoch_id, route_id, currency{admission,quality,credit}, allocated, consumed, credit_issued, credit_spent | 同上 → 缺口 |
| Worktree | 本文补 | id, node_id, base_fingerprint, branch, status(seed/active/dormant/merged/archived), dormancy_reason, regrow_condition, budget_cap | 与 06 §5.1 节点字段一致 |
| DecisionEpoch | 本文补 | epoch_id, window(actions/budget), frozen_snapshot, comparisons[], allocations[], pruned[] | **冲突：shared_frame 无此对象**，只在 05/06 正文出现 → 建议升级 |
| NodeBrief | 已有 | 父 handoff + 总控约束 + 2–4 卡 + 契约摘要，≤2–4k token | 沿用，不改名 |
| JudgeVerdict | 已有 | 契约：有效性 binary、质量向量、探索信用；**三货币不合并** | 沿用命名 |

### B3 与其它章的依赖
- **01 本体**：Claim/Evidence 状态机定义 Verdict 引用的科学对象；本层只记录判定，不判定科学内容。
- **02 发现循环**：ExperimentSpec→Worktree；ObservationBundle/EvidenceRecord 写 EventLog；next-node 提案触发发芽。
- **03 知识制度**：Verdict.pass 是 Ledger 准入门；版本指纹是复验依据；Archive 准入不由本层决定。
- **05 元层**：ProcessChange 只能改本层参数（预算比例、代长、门禁阈值），不能改路线；本层提供参数表与审计。
- **06 人机**：TaskContract 的 ACCEPTANCE 定义 frozen set；人工 veto 只写 EventLog，不改历史。

### B4 最大风险
**把测量装置制度化成事实**：V3 曾把官方不提供的完成信号当成绩 [K]；TIPEX 的 Judge 与 Oracle 差 5–15%；AI Scientist 评审漏全部硬伤。若 frozen set、Judge 模型、门禁阈值没有校准与版本审计，本层会把"能通过的假象"固化为准入标准。次风险：调度 Agent scope creep 成第二个总控（07 §1 明示），用上下文预算 + 权限清单卡死。