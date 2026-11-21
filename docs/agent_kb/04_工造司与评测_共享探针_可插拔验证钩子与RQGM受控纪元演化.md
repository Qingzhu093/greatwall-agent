# 知识卡 04：工造司重构为【科研仪器科】——统一三档仪器、四态隔离与校准升级（v3.0）

> **核心依据来源**：  
> - [`../architecture/手写project.md`](../architecture/手写project.md)（L3, L166–170 透明模拟器、不压死早期萌芽、防作弊、不拿竞赛特例污染通用底座）  
> - [`../round4_audit/01_交顶层设计者_原文对照与架构讨论稿_对齐版.md`](../round4_audit/01_交顶层设计者_原文对照与架构讨论稿_对齐版.md) & [`03_顶层设计深度审阅_原文溯源与决策对照_对齐版.md`](../round4_audit/03_顶层设计深度审阅_原文溯源与决策对照_对齐版.md) & [`第六轮审阅（针对第四轮测试）.md`](../round4_audit/第六轮审阅（针对第四轮测试）.md)（工造司大范围重构、废除全题强制基线/5%门禁/AST特例/平局保在位/计数回退、`Obs-031` 冤案复盘）  
> - `Audit the Scaffold` [`2609.34924#L312-L329`](file:///D:/Documents/deepseek%20harness/论文研读/2609.34924_Audit_the_Scaffold_Not_the_Checkpoint_A_Stationarity_Dichotomy_for_Recursive_Self-Improvement_in_Agentic_Coding/2609.34924_AuditTheScaffold_%E4%B8%AD%E6%96%87%E7%BB%BC%E8%BF%B0.md#L312-L329)（工具扩张才是突破天花板的唯一杠杆 + **黄金补丁自测测试器揪出 23/50 测坏的科研诚实铁律**）  
> - `RQGM` [`2606.26294_中文翻译.md#L76-L109`](file:///D:/Documents/deepseek%20harness/论文研读/2606.26294_The_Red_Queen_Godel_Machine_Co-Evolving_Agents_and_Their_Evaluators/2606.26294_RedQueenGodelMachine_%E4%B8%AD%E6%96%87%E7%BF%BB%E8%AF%91.md#L76-L109)（只在同一版本口径内比较、独立锚点门控、对抗池沉淀回归、保留全部产物按需重评、83%–90% 改进落在共享基建）  
> - `AgentDiscover` [`evaluator.py#L197-L267`](file:///D:/Documents/deepseek%20harness/论文研读/2610.05334_AgentDiscover_Autonomous_Discovery_with_Minimal_Search_Scaffolding/AgentDiscover/agentdiscover/server/evaluator.py#L197-L267) & `Station` [`STAGNATION.md#L28-L36`](file:///D:/Documents/deepseek%20harness/论文研读/2608.23691_Autonomous_Mathematical_Discovery_in_an_Open-World_Multi-Agent_Environment/station/example/doc/STAGNATION.md#L28-L36)（多条独立进展轨道 `progress_records`）

---

## 一、定位纠正：从“强行判生死的判官”回归【科研仪器科】

### 1.1 v2.2 工造司为什么必须推倒重构？
在 v2.2 与第四轮实机中，工造司被错误写成了带有 CUMCM B 题强烈印记的“全卷判官”：强迫每道纯理论题凭空写零号基线、写死 `<5%` 分布门禁、在通用底座里硬塞“全零/常数解拦截”和“`Q3` 脚本禁出现 `second_pass`”、拿 Beta 分位数和 `tie -> incumbent` 卡死修 Bug 的 `hook_Q1` v4、并在漏读 `spec.public_input` 时给 `Obs-031` 反例判 `0` 分记为“算法无改进”。

**v3.0 根本重置**：
- **工造司是基础设施与仪器提供商，不是科学结论的裁决者**。
- 剥离全部竞赛特异性硬编码，底座贯彻纯粹的 **`plugin is everything`**：所有领域校验规则（含是否需要基线、是否禁常数解、分布容差指标等）完全下放给具体课题的插件实例，**通用容器一条都不硬写**。
- 在开放式无客观标尺任务中，允许 Parse 0 **一个判定器都不注册**（梯度的方向交给同行盲审 + `37%` 元反思 + 人类检查点），工造司只负责搭环境、写探针、加速工具、确保沙箱可复现。

### 1.2 工造司日常工作优先级（由高到低）
1. **修故障工单**：处理来自 `INSTRUMENT_ERROR` / `INFRA_ERROR` 自动开单、探索者提报痛点、盲审发现的刷分漏洞、以及多个探索分支重复手写的轮子（收编成公共仪器）。
2. **扩张科研可观测性（最高杠杆价值）**：遵循 [`Audit the Scaffold`](file:///D:/Documents/deepseek%20harness/论文研读/2609.34924_Audit_the_Scaffold_Not_the_Checkpoint_A_Stationarity_Dichotomy_for_Recursive_Self-Improvement_in_Agentic_Coding/2609.34924_AuditTheScaffold_%E4%B8%AD%E6%96%87%E7%BB%BC%E8%BF%B0.md#L314-L329) 与 [`../architecture/手写project.md#L168`](../architecture/手写project.md#L168) 洞见——啰嗦复述报错对进展效应归零；唯有透明化黑盒（如分随机种子耗时分解、长尾比例剖面、守恒量残差轨迹等探针），才能真实扩张探索者可达假设类 $\mathcal{H}_t(C)$。
3. **堵住刷分漏洞（Reward Hacking 加固）**与**压力分级管理**（早期可先提供宽容的部分进展轨道以免扼杀萌芽，成熟后再升版严苛口径）。

---

## 二、唯一核心抽象：仪器（Instrument）× 统一接口 × 三档四态

### 2.1 三类仪器与统一调用签名
系统中所有判定脚本、验证器、诊断探针、仿真环境统一抽象为 **Instrument**，分三种 `instrument_role`：
- **`VERDICT`（判定器）**：可产出正式科学结论 `verdict` 与 `[Obs###]`；
- **`PROBE`（只读探针）**：只产出结构化多维诊断剖面，不打 `verdict`；
- **`ENV`（环境与数据集）**：提供模拟器、算例数据流、Lean/SymPy 计算运行时。

**全平台唯一标准化调用协议**：
```text
evaluate(artifact, spec, tier) -> {
  "status":  "OK" | "CANDIDATE_ERROR" | "INSTRUMENT_ERROR" | "INFRA_ERROR",
  "verdict": "PASS" | "FAIL" | "UNDECIDED" | null,   # 仅 VERDICT 类填写；PROBE 恒为 null
  "tracks":  dict[str, float | int | str | bool],     # 0..N 条独立进展轨道（不假定单一标量）
  "details": str                                      # 结构化诊断回执
}
```
- `artifact` 可为 Python 模块（默认 `run(public_input)`）、`.lean` 源码目录、构造反例 JSON 或数据文件集，由仪器插件自声明校验；
- 通用容器（`isolated_runner.py`）仅做：环境变量白名单隔离、`network="none"`（若需无网）、标准化取数 `get_public_input(spec)`（防再漏读 `public_input`）、持久化输出（用于按需重评）、以及校验返回体格式合规。

### 2.2 四态物理隔离与“判不了绝不判负”铁律（根治 `Obs-031`）
| 返回 `status` | 精确归因 | 平台处理铁律 |
|---|---|---|
| **`OK`** | 仪器健康跑完并给出有效观测 | 按 `verdict`（`PASS` / `FAIL` / `UNDECIDED`）和 `tracks` 正常登记科学事实 |
| **`CANDIDATE_ERROR`** | 候选产物自身语法错、崩溃、缺入口、超时 | 记入探索者修补账（触发后勤 `LEVEL_2` 原地修补），不计入科学否定 |
| **`INSTRUMENT_ERROR`** | 仪器本身抛未捕获异常、读错键名（如 `Obs-031` 漏 `spec.public_input`） | **严格零处罚探索者**（不记 0 分、不记非改进、不扣修补配额、不推高停滞计数）！**同事务自动开单进 `works_engineering_queue` 并通知探索者“平台仪器故障已报修”**；若同一仪器连续出错达阈值（默认 `3` 次），自动熔断置为 **`UNHEALTHY`** 拒绝 `official` 调用 |
| **`INFRA_ERROR`** | 容器、磁盘、RPC 超时等底座故障 | 同样**零处罚探索者**、穿透幂等缓存允许直接重试，并自动告警 |

### 2.3 同一套仪器代码、三档调用模式（`probe / official / heavy`）
终结“本地自测走 CLI stdout、官方沙箱调 `run()`”的两套契约割裂事故：
1. **`probe`（快速探索档）**：使用公开/开发集样例，探索者可高频随时调用获得完整诊断输出；**只写诊断日志，不生成正式 `[Obs###]`**；
2. **`official`（正式受控凭证档）**：在受控沙箱中以不可篡改方式产出正式 `[Obs###]`（含 `VALID_PASS / MEASURED_REJECTION / VALID_UNDECIDED`），作为分诊与盲审凭据——**有保留/隐藏判定集的题跑隔离保留集；无隐藏集的开放数值/仿真发现题则跑固定公开配置+多种子复现集，后续由 `library_verifier` 在隔离盲审沙箱内变种子/扰动边界独立复现核验，绝不为过审硬造假隐藏集**；
3. **`heavy`（重型实验档）**：高成本长耗时仿真，强制探索者先填预期 `linguistic_prediction` 后异步排队执行（记入 `async_eval_jobs`）。
> **自由微验证保留**：彻底废除 `[Local-Sweep]` 强制格式术语与“强制先自测再正式交”；保留探索者随时用 `pwsh` 写一次性微型校验脚本的科研自由，但凡提交正式科学凭证统一调用对应仪器。

---

## 三、校准集驱动版本演进（`RQGM` + `Audit the Scaffold` 纯净落地）

把原论文中针对万次带噪采样的复杂 Beta 分位数（$BB_\epsilon = I^{-1}_\epsilon$）、提交计数回退、以及强迫“平局保在位”等不适配条款**彻底剔除**，保留最纯粹、最有生命力的三根工程支柱：

1. **上线与升版的唯一门控：独立校准集（Calibration Suite）**
   - **最低校准门槛**：纯探测/环境类（`PROBE` / `ENV`）允许免配校准集（`null`）；**`VERDICT` 仪器上线与升版至少须配 `>= 1` 条回归或毒样本用例**（若开放题目尚无参考正例，允许暂缺 `gold` 案例但必须有结构退化/反作弊拦截或边界冒烟校准）。
   - **每个案例自声明预期 `(expected_status, expected_verdict)`（绝不把全零/空输入在通用底座写死为 `OK + FAIL`！）**：
     - **格式/入口退化用例**（如空文件、缺 `run()` 入口、语法崩溃）：预期 **`expected_status = "CANDIDATE_ERROR"`、`expected_verdict = null`**（确保仪器不把候选报错误判成仪器异常或科学失败）；
     - **课题退化/作弊毒样本（Poison Cases）**：如照抄输入作输出、把已知公开样硬编码进返回值、已知历史刷分手法（或在该题被领域规约禁用的平凡退化解）：预期 **`expected_status = "OK"`、`expected_verdict = "FAIL"`**；**注意：若某物理/数学问题在定义上允许零解，则零解属于 `gold` 用例（预期 `OK + PASS`），通用底座禁止一刀切禁零！**
     - **金样本（Gold Cases — 有则必测）**：已知正确参考解或构造验证通过实例：预期 **`expected_status = "OK"`、`expected_verdict = "PASS"`**（借鉴 `Audit the Scaffold` 上线前金补丁实测揪出 23/50 测试器 Bug 之法）。
   - **Bugfix 与堵漏零死锁流程**：发现仪器 Bug（如空输入误判通过 `10/16` 或漏读 `public_input` 崩溃）或刷分漏洞，**先将复现案例写成校准集用例并标定预期结果，确认旧版确实违背预期，再修补仪器代码；只要新版 100% 匹配全部校准用例的 `(expected_status, expected_verdict)` 即可直接上线发布**，绝不强求在老考卷上刷出更高通过率！
2. **版本域隔离（只在同 `(instrument_id, version)` 内比高下）**
   - 任何 `[Obs###]` 永久锁定产出时的 `(instrument_id, instrument_version, artifact_sha256)`；
   - 跨版本排名与突破比较禁止混算；历史产物确实需要跨版本对齐时，调 `recompute_stage_b_only` 用持久化的阶段产物按新版本重跑——若老产物缺少新口径所需字段或测试输入本身已变更，**诚实标记为 `INCOMPATIBLE`（不可比），绝不做“秒级重算必然恢复 VALID”的空头保证**。
3. **仪器内部修复 vs 题目口径变更的权限界线（红灯续跑原则）**
   - 修读取错误、防作弊、加诊断维度属于仪器内部完善，**工造司自主校准升级即可**；
   - 若工造司判定题目原验收目标、输入口径存在根本性歧义（超出内部维修范围）：**在 `compliance_alerts` 与系统界面亮起 `ALERT_AMBIGUOUS_SPEC` 红灯请求人类事后核查，同时无人值守任务严格按照原已签口径继续推进（绝不停机挂起）**。

---

## 四、工具沉淀账本（`SKILL_LEDGER.json`）
保留分支私有 `<worktree>/tools/` 自动扫描清单；当某类实用工具在多条分支重复手造时自动开单工造司收编为公共只读探测仪器，经可执行与 **`No File` 落盘检验**后登记 `skills/SKILL_LEDGER.json`（保留原始 `(S, F)` 计数、`applicable_scope`、`verified_artifact_rel_path`、`rollback_pointer`）。
