# 知识卡 04：工造司（科研仪器科）——统一仪器、三档四态与校准集版本演进

> **模块归属**：`works_engineer`、`evaluators/isolated_runner.py`、校准集回归引擎与 `skills/SKILL_LEDGER.json`。  
> **配套阅读**：[`04` 顶层白皮书 §4.1](../architecture/04_长城%20Agent%20V6-Up：面向长周期自主科学发现的多智能体系统架构白皮书（v3.0）.md#41-工造司科研仪器科统一仪器三档四态与校准升级) ｜ [`09` 工程开发总说明书 §4](../architecture/09长城%20Agent%20V6-Up（v3.0）零前提工程架构与系统开发总说明书.md#第四章通用隔离执行器isolated_runnerpy与校准引擎实现规格)

---

## 一、第一性定位：实验室仪器提供商，而非科学判官

工造司是科研体系中的**“科研仪器科”**——它的核心使命是为一线探索者打造**透明、隔离、可信的测量仪器、诊断探针与计算环境**，而不是给每一道科学难题强行制造标量打分器。

1. **纯粹的 `plugin is everything`**：通用隔离容器（`isolated_runner.py`）保持极薄，只管进程隔离、数据键位标准化、外部产物持久化、复合缓存与返回协议校验；一切具体学科校验逻辑（是否需要参考基线、某题是否允许全零解、物理仿真误差容忍度等）全部属于课题级插件，通用底座一条都不硬编码。
2. **原生兼容无判定器开放任务与 Stage 1 统一核查**：在纯理论数学证明或无客观标尺的开放机理探索中，Parse 0 完全允许 **0 个判定器（`VERDICT`）开局**，梯度方向交给同行盲审、`37%` 元反思与人类检查点，工造司专攻搭建计算环境与高信噪比诊断探针。为了保持编排流程高度一致，**Stage 1 统一由 `works_engineer` 履行一次完整的初始仪器核查责任**：非空则锻造、校准并注册全部初始仪器（中途部分失败恢复仅续做未完成项）；为空则调用 `get_works_engineering_queue` 明确确认无需初始仪器并正常返回，经控制面核验 SQLite 状态后置 `stage1_works_checked = 1`。
3. **日常工作优先级（由高到低）**：
   - **① 修复故障与痛点工单（含显式结案闭环）**：优先处理 `INSTRUMENT_ERROR / INFRA_ERROR` 自动工单、前线上报的工具痛点（`PAIN_POINT`）、盲审发现的刷分漏洞（`EXPLOIT`），以及收编多分支重复手造的实用工具（`DUPLICATE_TOOL`）；对于已完成处理、重复或无需建仪器的非仪器工单，**必须调用第 6 个专属窄工具 `resolve_works_ticket(ticket_id, resolution, resolution_note)`**（统一置队列 `status = "RESOLVED"` 并将 `resolution ['RESOLVED'|'WONTFIX'|'DUPLICATE']` 与说明记入 `payload_json` 供审计），防止已解决工单滞留 `OPEN` 触发无效空转；
   - **② 扩张科研可观测性（最高杠杆价值）**：`Audit the Scaffold` 实证表明，复述冗长报错对解题进展的效应量为零（$F=0.50, p=0.61$），唯有提供能看到新物理/数学维度的透明探针（如分随机种子耗时拆解、长尾剖面、守恒律残差谱），才能在冻结模型权重下真实扩张可达假设空间 $\mathcal{H}_t(C)$；
   - **③ 防作弊加固与压力分级**：持续修补 Reward Hacking 漏洞；在需要渐进课程的仿真/优化任务中，可先发布宽容的部分进展轨道以保护早期创意萌芽，成熟后再发布更严格的新版本。

---

## 二、唯一核心抽象：仪器（`Instrument`）× 统一接口 × 三档四态

### 2.1 三类仪器角色与统一调用协议
系统中所有验证器、诊断探针与仿真环境统一抽象为 **Instrument**，分为三类 `instrument_role`：
- **`VERDICT`（判定器）**：产出正式科学结论 `verdict` 与 `[Obs###]` 收据（如数值验证器、Lean 4 编译检查器、通用反例校验器、学习型审稿插件）；
- **`PROBE`（只读探针）**：只产出多维诊断剖面（`tracks` + `details`），`verdict` 恒为 `null`；
- **`ENV`（环境与数据集）**：提供模拟器运行时、基准算例数据或符号计算依赖。

**全平台唯一调用协议**：
```python
evaluate(artifact, spec, tier) -> {
    "status":  "OK" | "CANDIDATE_ERROR" | "INSTRUMENT_ERROR" | "INFRA_ERROR",
    "verdict": "PASS" | "FAIL" | "UNDECIDED" | None,   # 仅 VERDICT 填写；PROBE 恒为 None
    "tracks":  dict[str, float | int | str | bool],    # 0..N 条独立进展轨道，不假设单一标量
    "details": str                                     # 结构化诊断文本
}
```
- `artifact` 形态由仪器插件自声明（Python `run(public_input)` 模块、`.lean` 源码目录、构造反例 JSON 数据包或文本手稿）；
- 平台测试输入唯一放置在 `evaluator_spec["public_input"]`，通过标准辅助函数 `get_public_input(spec)` 读取，严禁从候选返回值倒推输入，严禁缺键静默判 0 分。

### 2.2 四态物理隔离与“判不了绝不判负”铁律

| 返回 `status` | 精确归因 | 平台确定性处理动作 |
|---|---|---|
| **`OK`** | 仪器健康跑完并给出有效观测 | 按 `verdict`（`PASS` / `FAIL` / `UNDECIDED`）映射为 `VALID_PASS` / `MEASURED_REJECTION` / `VALID_UNDECIDED` 写入科学账本 |
| **`CANDIDATE_ERROR`** | 候选产物自身语法错、运行时崩溃、缺入口、超时 | 记入探索者修补账（触发后勤 `LEVEL_2` 原地修补上限 3 次），不计入科学否定 |
| **`INSTRUMENT_ERROR`** | 仪器自身抛未捕获异常、漏读键名、返回体违约 | **严格零处罚探索者**（不打 0 分、不扣修补配额、不推高停滞计数、不进永久缓存）！**同事务自动开单 `works_engineering_queue`** 并通知探索者已报修；同一仪器连续出错达 `3` 次自动熔断置 **`UNHEALTHY`** 拒绝 `official` 调用 |
| **`INFRA_ERROR`** | 容器、磁盘或 RPC 超时等底座故障 | 同样**零处罚探索者**、穿透幂等缓存允许重试，并记录系统告警 |

### 2.3 同一份仪器代码、三档调用模式（`probe / official / heavy`）
使用同一套仪器代码、仅切换挂载数据切片与记账策略，彻底保证开发自测与正式凭证协议 100% 同构：
1. **`probe`（快速探索档）**：挂载公开/开发样例，探索者可高频随时调用获取完整诊断剖面；**只写 `probe_diagnostic_logs`，不记入正式 `[Obs###]`**；
2. **`official`（正式受控凭证档）**：在受控隔离沙箱中不可篡改执行并产出正式 `[Obs###]`——**有保留/隐藏判定集的题跑隔离保留集；无隐藏集的开放数值/仿真发现题跑固定公开配置 + 多种子复现集（允许返回 `OK + UNDECIDED`），后续由盲审官在独立盲审沙箱内做变种子/扰动边界复现核验**；
3. **`heavy`（重型实验档，*可选高级特性*）**：面向超长耗时高成本仿真（常规科研以 `probe` + `official` + 四元复合缓存为主力），调用前强制填事前预期 `linguistic_prediction`，入队 `async_eval_jobs` 时同步冻结候选与 `tools/` 快照（`$PLUGIN_DATA/workspaces/<ws_hash>/job_inputs/<job_id>/`）、原 `instrument_version` 与验证规格，重启后按原冻结现场续跑，并支持探索者凭同一 `job_id` 调用 `run_isolated_eval` 幂等取回且仅扣一次预算。
*(注：探索者在自身 Worktree 始终保留随时用平台 Shell 写一次性微验证脚本的科研自由。)*

### 2.4 四元复合缓存键（严防跨档与辅助模块变更误命中）
```text
cache_key = sha256(
  candidate_entry_sha256
  + recursive_tools_dir_sha256
  + spec_sha256(必须包含 tier 字符串与该档实际挂载数据的 data_slice_sha256)
  + instrument_sha256
)
```
且 `INSTRUMENT_ERROR` 与 `INFRA_ERROR` 绝对穿透缓存，不写永久命中记录。

---

## 三、校准集回归驱动版本演进与版本域可比性

1. **上线与升版唯一门控：独立校准集（Calibration Suite）**
   - `PROBE` / `ENV` 类仪器可免配校准集（`null`）；**`VERDICT` 仪器注册与升版必须附带 `>= 1` 条独立校准用例**（JSON 数组，含 `{case_id, expected_status, expected_verdict, artifact_rel_path, public_input}`）；
   - **每个用例自声明精确预期 `(expected_status, expected_verdict)`**：
     - 格式/入口退化用例（空文件、语法错、缺 `run()`）$\to$ 预期 `("CANDIDATE_ERROR", null)`；
     - 课题作弊/平凡毒样本（照抄输入、硬编码已知值、历史刷分手法）$\to$ 预期 `("OK", "FAIL")`；
     - 金样本（已知参考正解、或该题物理定义下合法的零解/常数基态）$\to$ 预期 `("OK", "PASS")`；
   - **修 Bug 与堵漏零死锁流程**：发现仪器读数缺陷或刷分漏洞 $\to$ 先把复现案例写入校准集并确认旧版违背预期 $\to$ 修复仪器代码 $\to$ **服务端在独立子进程实跑全量校准集，100% 匹配所有用例的自声明预期即直接升版发布**。
2. **版本域隔离与诚实重评**
   - 所有 `[Obs###]` 永久绑定产出时的 `(instrument_id, instrument_version)`；跨版本得分严禁混排比较；
   - 需对历史产物按新版口径重算时，工造司先在 `get_works_engineering_queue` 查见 `pending_revalidation` 队列，再调用 `recompute_stage_b_only` 读取外部 `$PLUGIN_DATA/workspaces/<ws_hash>/eval_artifacts/<obs_id>/stage_a_output.json`：**永久保留旧 `[Obs###]` 不覆盖**（置 `SUPERSEDED_REVALIDATED`），重评成功生成绑定新版 `(instrument_id, new_version)` 的新 `[Obs###]` 收据（含 `revalidated_from_obs_id`）并将队列项置 `DONE`；若旧产物缺少新版本所需字段或测试输入本身已变更，**诚实将旧收据与队列项标记为 `INCOMPATIBLE`** 结案。
3. **仪器维修 vs 题目口径歧义边界**
   - 修读取错误、防作弊、加诊断维度属仪器内部完善，由工造司自主走校准集升版；
   - 若发现题目原始验收目标或输入定义本身存在根本歧义，向 `compliance_alerts` 亮起 **`ALERT_AMBIGUOUS_SPEC` 红灯**交人类事后核查，同时无人值守任务严格按原已签口径继续推进。

---

## 四、工具沉淀账本（`SKILL_LEDGER.json`）

分支私有 `<worktree>/tools/` 中的可复用脚本由宿主在每代探索者启动时自动扫描注入清单（每个模块 docstring 须写清 `What it does / Interface / What it does NOT do`）。当多个分支重复手造同类工具时，系统自动开单工造司收编为全社区共享只读探针，经可执行与文件实存校验后登记至 `skills/SKILL_LEDGER.json`（记录 `skill_id`（匹配 `^[a-z0-9_]+$`）、`applicable_scope`、`version`、`raw_success_count`、`raw_failure_count`、`verified_artifact_rel_path`、`rollback_pointer`）。
