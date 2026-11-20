# 长城 Agent V6-Up 补充对账审计报告（B2 卷）：`agent_kb/00–06` 落地规范 vs `greatwall-v6up/` 实装与 DSH 水土不服分析

> **审计基准**：`d:\antigravity\长城agent设计v6up（Gemini负责）\agent_kb\` 全部 7 份文档（[`00_INDEX`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/agent_kb/00_INDEX_Agent知识库总导航与必读映射.md) 至 [`06_速查卡`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/agent_kb/06_十三篇核心文献工程速查卡与本机源码行号索引.md)）  
> **对照对象**：[`greatwall-v6up/`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/) 实装源码及第二轮测试 `greatwall.db`（`ws_hash=0b57d5d99769c4fa`，只读核验）与 `05_supervisory/` 运行记录。

---

## 一、`agent_kb/01`–`04` 核心落地细则逐卡对账（未实现 / 走样 / 实跑脱节）

### 1.1 对账 [`agent_kb/01`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/agent_kb/01_拓扑与制度_一委三部扁平制衡与零偏见总线.md)：极薄事件总线 × 一委三部制衡 × 一对一伴随

| `agent_kb/01` 规范要求（精确出处） | `greatwall-v6up/` 源码实际状态 | 实跑脱节情况与定性 |
| :--- | :--- | :--- |
| **极薄系统事件总线主动路由**（L21, L26–27）：监听 Stage 切换、37%/70%、盲审请求、痛点上报、异常中断、巡检心跳，经 `ctx.subagents` 唤醒平行四部门与双人组 | **实现严重缩水且默认关闭**：`autoDispatchSubagents` 默认 `false`（[`index.js:37`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/lib/index.js#L37)、[`cordis.patch.yml:16`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/cordis.patch.yml#L16)）；且总线**未监听** Stage 切换、盲审请求、痛点上报与巡检心跳，仅写了 37%/70% 与 `subagent/end` 钩子（L363, L456 均不执行） | **完全休眠**：事件总线未发挥路由作用，退化为 `agent_kb/00` L24 警示的**反模式 1（中心化星型太上皇）**，由 Root（Lead）人工包办一切派单与决策 |
| **后勤总管作为独立“内政官”平行制衡**（L32–39, L49）：总管仅管后勤内政，严禁统领其他三部 | **角色文件缺失 + 原语混装**：无 `logistics_coordinator.md` 与总管 Preset；[`prompts.js:8-14`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/lib/prompts.js#L8-L14) 仅列 5 角色；图书馆 6 动作与后勤 7 动作混装在 `promote_or_triage_branch`，后勤 3 动作与工造司 6 动作混装在 `manage_eval_epoch` | **角色边界塌缩**：Root `session-56a36cab` 无契约注入，靠 [`AGENT_PROTOCOL.md`](file:///D:/Documents/deepseek%20harness/v6第二轮测试/00_contract/AGENT_PROTOCOL.md) 自封为后勤总管；`logi:main` 因正则 `\blog[-_:]` 失配（[`event_bus.js:52`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/lib/event_bus.js#L52)）在 DB `clock:logi:main` 中被误记为 `central_library` |
| **多 Preset 裁剪 + ACL/Worktree + `FACT_LOG` 替代 20 位密码锁**（L63） | **空架子与不对称门禁**：DSH `subagent` 无 `preset` 参数（P0）；[`greatwall-roles.cordis.yml`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/presets/greatwall-roles.cordis.yml) 未被加载；`dsh-sandbox-windows-acl` 在 [`worktree_and_acl.js:67-95`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/lib/worktree_and_acl.js#L67-L95) 仅 `require` 探测而不调用；`dsh-experimental-tool-worktree` 仅在注释出现 | **门禁失效与误伤并存**：`gate.js` 漏检无角色会话与 `pwsh` 相对路径，却用 `worktree_and_acl.js` 正则误杀 `N_Q1..N_Q4` 自身工作区 19 次、共享文档 `EXPLORER_GUIDE.md` 1 次；`index.js:300-305` 把管理会话的 `READ` 错绑到节点 `N001`/`N003`（P15） |
| **A 档只读 SQL 视图赋能探索者**（L66） | 后端实现了 `register_saved_graph_query`（含 `EXPLAIN QUERY PLAN` 校验，[`mcp_tools_research.py:361-466`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_tools_research.py#L361-L466)） | **实跑零使用**：查 `greatwall.db` 得 `saved_queries` 表为 **0 条** |

---

### 1.2 对账 [`agent_kb/02`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/agent_kb/02_后勤与谱系_上下文时钟_一对一伴随_四级分诊与五车道复苏.md)：物理真时钟、看板、方法族谱、四级分诊与五车道

| `agent_kb/02` 规范要求（精确出处） | `greatwall-v6up/` 源码实际状态 | 实跑脱节情况与定性 |
| :--- | :--- | :--- |
| **`70%` / `250k` / KV-Cache 读写价差 `Cost Note` 真实算法**（L20）：`handoff_token_cap=250,000`；`Cost Note` 按 $k \cdot \text{read} \cdot (L - c) > \text{write\_multiplier} \cdot i$ 且 $\ge 4$ 试次无增量触发 | **参数砍半 + 公式未实现 + 双时钟脑裂**：① `config.json:5-6` 与 `event_bus.js:18-19` 将 `250k` 改为 `125k` 并硬封顶 `178,500`（[`event_bus.js:198`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/dsh_plugin/lib/event_bus.js#L198)）；② 未扣除系统提示+全量工具 Schema 基线；③ [`mcp_core_helpers.py:294-301`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_core_helpers.py#L294-L301) 用 `trial_count >= 5 and pct >= 0.45` 替代 KV-Cache 价差公式，且 JS 端完全未实现 `Cost Note`；④ JS `TokenMeter` 未回传 Python 账本 | **严重走样（P19/P23）**：Q1 g1 写了 0 行代码即触 `37%`；DB 全库 32 条 `clock:*` 的 `reflect_hint_sent` 全为 `false`，致探索者解锁被 `ERR_LOCKED` 拒之门外；伴随与工造司在 Python 端未从 `FORCE_HANDOFF_STOP` 豁免（[`mcp_core_helpers.py:289-291`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_core_helpers.py#L289-L291)） |
| **异常中断 `interrupted_unclaimed` 最高优唤醒伴随打捞**（L21，仿 `coder_manager.py`） | `event_bus.js:252-258` 生成建议对象，`audit_provenance_edges` 扫描清单，但因 `autoDispatchSubagents=false` **不会自动唤醒**，也无指数退避恢复逻辑 | **半成品**：仅能靠监察委人工/事后调用 `audit_provenance_edges` 发现 |
| **跨代五要素看板无损保留**（L27–35）：`<2000` 字合成，同时一字不删保留每代节点档案 | [`synthesize_lineage_briefing`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_core_helpers.py#L413-L639) 遍历递归祖先链，但：① L629 硬切 `[:max_chars]` 致 §5 腰斩（P25）；② L544–572 双路径扫 `Local-Sweep` 致重复膨胀；③ [`submit_node_handoff`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_tools_research.py#L1336,L1421) **覆写** `lineage_nodes.handoff_note_md` 并清空 `custom_briefing` | **实现瑕疵**：Q4 g2 交接后自动合成看板在 `### 5. 近 1–2 代《科研遗` 中途断裂 |
| **《方法族谱登记册》防撞车**（L37–49）：分叉前查重并共享兄弟变体 | `fork_branch(orthogonal)` 查全表 `method_families` **未排除 `target_family` 自身**（[`mcp_tools_governance.py:881-887`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_tools_governance.py#L881-L887)）；`lateral` 跳过 `method_families` 且 `brief_raw` 为空时跳过兄弟去重（L899–913）；无原语流转 `family_status` 至 `MATURE_PROVEN` | **逻辑 Bug**：Epoch 2 四次 `orthogonal` 向预登记学派分叉全部自撞车 `ERR_CONFLICT`，改用 `lateral` 绕过才成功；DB 中 18 个学派全停在 `EXPLORING` |
| **四级分诊与五车道复苏精细规则**（L60–73）：L2 连续 2 次错唤 `Coding Assistant` 上限 3 次；L3 防伪迹双检后开保护支线；L4a 挂 `DEPENDS_ON` 封死；L4b 按族谱优先级出 `Ready Queue`；停滞四阶梯自救 + `Multistart` | **极度简化为状态标签**：① `triage_decision` 中 `Routine`/`L2`/`L3` **走完全相同的分支**（[`mcp_tools_governance.py:823-826`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_tools_governance.py#L823-L826)），不卡 L2 上限 3 次、不做 L3 防伪迹双检也不开保护支线；② `CODING_ASSISTANT_ESCALATION` 只是返回体字符串，JS 总线未监听拉起；③ `dispatch_ready_queue` 只是 FIFO `rq[0]`（L1059），未按族谱优先级；④ `apply_stagnation_lanes`（L1012–1037）仅改字段 `stagnation_lane`，不校验前三阶梯自救也不触发 `Multistart`；⑤ `triage_decision` 对未交接/复诊节点误增 `consecutive_non_l1_handoffs` 且不存 `rationale`（P16） | **实跑空转/失效**：第二轮测试中 Epoch 2 未经 `triage_decision` 即在文档里宣布“结案”；`STAGNATION_APPLIED.md` 应用五车道时因 `init_parse0` 未清 Epoch 1 旧节点，竟把 `N001/N002/N003` 一并编入车道 |

---

### 1.3 对账 [`agent_kb/03`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/agent_kb/03_中央图书馆_三本账_两阶段物理盲审_Auditor二次打捞与依赖撤回.md)：三本账、物理盲审、独立 `Auditor` 与依赖传播

| `agent_kb/03` 规范要求（精确出处） | `greatwall-v6up/` 源码实际状态 | 实跑脱节情况与定性 |
| :--- | :--- | :--- |
| **`L2` 自动失败雷达闭环**（L29）：盲审退回、`L2` 超限放弃、伪解反例强制写入 `L2` | `finalize_stage2_verdict("REJECT_TO_L2")`（[`mcp_tools_governance.py:349-387`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_tools_governance.py#L349-L387)）仅改 `reviews` 行，**未写入 `library_entries(L2)`**；`triage_decision(L2)` 超限亦不写 `L2` | **半闭环**：除 `L4a` 外，探索/审稿失败不能自动沉淀入 `L2` |
| **阶段一硬盲审 + 阶段二不可回改 `Evidence Ledger`**（L48–58） | SQLite 触发器 `trg_reviews_lock_stage1` 与 `is_blind_session` 已实现；**但** ① `triage_decision(L1)` 判据 `stage2_verdict not in (None, "PASS")`（[`mcp_tools_governance.py:786`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_tools_governance.py#L786)）允许跳过 Stage 2；② 工作区文件层 `central_library` 可直调 `read` 打开 `HANDOFF.md` 看穿 B 栏与作者；③ `session_id` 含 `"surveyor"` 即豁免盲态（[`mcp_core_helpers.py:709`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_core_helpers.py#L709)） | **实跑完全跳过**：`greatwall.db` 中 `reviews = 0`，`cross_draft_reviews = None`，无门禁阻断 `.md` 结案文档（`Q3_CLOSURE.md`） |
| **独立 `Auditor` 废墟二次盲态复验**（L64–68） | `auditor_salvage` 需两步，但 Step 2 由 `aud_1` 自己代填 `aud_2` 的 `verifier_verdict="PASS"`，仅查 `aud_2` 有过 `RETRIEVED` 边（[`mcp_tools_governance.py:512-525`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_tools_governance.py#L512-L525)），不强制 `aud_2` 盲态且可由 `aud_1` 单方提 PASS | **实跑零使用**：`pending_auditor_lemmas = None` |
| **手记、外键、`DEPENDS_ON` 传播与 `bound_state_version`**（L70–76） | `invalidate_observation` 正确传播 `library_entries` 与 `paused_4b`；但 `submit_node_handoff` 的 `late_or_stale`（[`mcp_tools_research.py:1297-1314`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_tools_research.py#L1297-L1314)）一刀切把 `N_Q3` 全量 `VALID` 观测变 `PENDING_REVALIDATION` 却漏入 `pending_revalidation` 队列 | **引发 P26 数据事故**：`[Obs009]/[Obs010]/[Obs011]` 变为 `PENDING` 孤儿行，连带使 Phase 0 与 Q3 全部数字一度不可引 |

---

### 1.4 对账 [`agent_kb/04`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/agent_kb/04_工造司与评测_共享探针_可插拔验证钩子与RQGM受控纪元演化.md)：工造司、通用容器、RQGM 四支柱与 `SKILL_LEDGER.json`

| `agent_kb/04` 规范要求（精确出处） | `greatwall-v6up/` 源码实际状态 | 实跑脱节情况与定性 |
| :--- | :--- | :--- |
| **通用容器 `network="none"` + `_noise_phrase` 中位数突变步长噪声预警**（L30） | [`isolated_runner.py`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/evaluators/isolated_runner.py) 与 `mcp_tools_research.py` **完全未实现 `_noise_phrase`**，且 Windows 子进程未做网络禁用 | **缺项**：对随机波动噪声增量缺乏预警，只靠人工核验 |
| **RQGM 支柱 2：$BB_\epsilon$ 与 $Q_P$ 锚点门禁**（L45–53） | `compute_bb_epsilon` 与 `compute_adversarial_qp` 数学函数已写，但 `anchor_eval`（[`mcp_tools_governance.py:1780-1822`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/mcp_server/mcp_tools_governance.py#L1780-L1822)）全靠调用方**手填 `s_gt/f_gt/p_plus/p_minus/r_p`**，未接入真实锚点测试集，也未与 `meltdown_upgrade` / `domain_hook` 升级强制绑定 | **空壳数学装饰**：`greatwall.db` 中 `anchor_stats = None`，P12 双写覆盖 `domain_hook.py` 时零门禁拦截 |
| **RQGM 支柱 3 & 4：沿 $\operatorname{dep}(z)$ 选择性擦除 + `STAGE_B_ONLY` 按需均摊重评**（L55–62） | `selective_erase` / `lazy_reval` 已写，但：① 未强制将 `domain_hook_sha256` 记入 `dep_slots_json` / `condition_json`（P13）；② Stage A 退出即删临时沙箱目录，使持久化 `candidate_output.json` 中的 `program` 路径变成死链，导致 `STAGE_B_ONLY` 在本课题钩子下**必报 `PROGRAM_FILE_MISSING`**（[`EPOCH2_REVAL_DIAGNOSIS.md`](file:///D:/Documents/deepseek%20harness/v6第二轮测试/05_supervisory/EPOCH2_REVAL_DIAGNOSIS.md) §4） | **架构互斥**：重评被迫每次 `force_full_rerun=true` 重跑 Stage A+B，失去了 RQGM 按需仅重算 Stage B 的成本有界优势 |
| **双层工具 `<worktree>/tools/` 与 `SKILL_LEDGER.json` 晋升**（L66–74） | `manage_eval_epoch(skill_ledger_update)` 实现了 `No File` 文件存在性校验；但仓库内 [`SKILL_LEDGER.json`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/skills/SKILL_LEDGER.json) 停在初始虚设 `S=0, F=0` | **实跑零晋升**：测试工作区未建 `SKILL_LEDGER.json`，`skill_ledger_update` 全程 0 调用 |

---

## 二、`agent_kb/05` 原论文级 Prompt 武器库被 `agents/*.md` 剪裁清单与失控后果

[`agent_kb/05`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/agent_kb/05_原论文级Prompt武器库与五大角色完整模板直抄库.md) 明确要求**直抄嵌入** `Station v2`、`AgentDiscover`、`SLA`、`OpenAI CDC`、`Cogentic` 的完整高密度 Prompt 原文，彻底终结“保安条例式”简陋提示。核查 [`greatwall-v6up/core_python/agents/*.md`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/greatwall-v6up/core_python/agents/)（47–75 行）发现以下实质剪裁：

1. **剪裁 1：`Station v2` 11 类元反思（315 行 YAML）+ 29 条夜科学（66 行 YAML）+ 12 条 Supervisor 反思 + 7 节交接模板被极度压缩**
   - `lineage_companion.md` 把 11 类元反思压成每类 1 句话（L44–60），29 条夜科学删剩 4 条（L62–66），删掉了苏格拉底 2–3 轮对话的“追问-拒收敷衍回答”指令；`supervisory_committee.md`（47 行）**完全丢失 12 条 `Supervisor` 专属灵魂题库**。
   - **实跑后果**：模型缺乏具体的结构化拷问模板，再加上缺少“零 VALID 时仅写 `REFLECTION_37.md` 不交空 L1”的规约，直接诱发 P11/P23 与长篇自由散文式反思报告。
2. **剪裁 2：`AgentDiscover instructions.md`（160 行）& `SLA`（274 行）与执行契约被抽干**
   - `explorer.md`（57 行）把 `MAP-Elites` / `UCT` 图谱组合查询范例删成一句话；删去了 `SLA` 原版严格的声明式反废话、反重复提交纪律；**完全缺失 `isolated_runner.py` Stage A `runpy("__main__")` 入口契约与仿真策略返回规范**。
   - **实跑后果**：探索者踩中 `if __name__ == "__main__":` 死坑（P14）、不知策略类如何交 Stage B（P1）、Q3 g2 连续提交 3 次一模一样的 `VALID`（P24）、`works-baseline` 提交的预测与 `candidate_path` 货不对板（P13）。
3. **剪裁 3：`OpenAI CDC` 7 类红队实战话术 + `Station Appendix D` `Evidence Ledger` Schema + `Cogentic` Stage 3 三段式被删除**
   - `central_library.md`（63 行）仅列出 7 类红队名称（7 行）与步骤名称，**没有任何 `submit_review_verdict` 的 `evidence_ledger` JSON 结构示例**，且**完全删除了 Stage 3 `Comparator -> Formal Writer -> Final Verification Audit` 契约**。
   - **实跑后果**：整个第二轮测试 `reviews = 0`；Q3 在未过盲审下直接由总管写 `Q3_CLOSURE.md` 宣布结案；Stage 3 论文由越权的 `lead` 在 `06_delivery/01_formal_paper.md` 自由发挥，出现重复章节与不可追溯数字（`ROLE_AUDIT.md` §6）。
4. **规范自身漏洞：`agent_kb/05` 根本没有编写 `logistics_coordinator` 的 Prompt 武器库！**
   - `agent_kb/05` 标题即为“五大角色完整模板直抄库”，全篇仅覆盖 `lineage_companion`、`explorer`、`central_library`、`works_engineer`、`supervisory_committee`，**独缺第 6 个角色 `logistics_coordinator`**，直接埋下后续插件缺失 `logistics_coordinator.md` 的祸根。

---

## 三、`agent_kb/01`–`06` 制度设计在 DSH 宿主上的五大原生悖论与水土不服

即便插件团队 100% 照搬 `agent_kb/01`–`06` 编码，设计规范本身在映射到 **DSH (`0.2.2-rc.3`) + DeepSeek Flash + Windows 共享工作区** 时，仍存在五处深层结构性悖论：

1. **悖论一：“一委三部六角色”拓扑 vs “五大核心角色”清单的规范自相矛盾（Lead 越权的制度母体）**
   - [`agent_kb/01`](file:///d:/antigravity/长城agent设计v6up（Gemini负责）/agent_kb/01_拓扑与制度_一委三部扁平制衡与零偏见总线.md)（L32–49）定义了 **6 个角色**（监察委、后勤总管、伴随助手、中央图书馆、工造司、探索者），并强调总管只是后勤内政官；
   - 然而 `04` 第五章（L273–293）、`04` 第七章目录树（L355–360）以及 `agent_kb/05` **全都只规划了“五大角色 `agents/*.md`”**，把后勤总管职责塞进了全局共享的 `SKILL.md`！
   - 在 DSH 中，`SKILL.md` 注册于**根会话（Lead）**。这种“不给总管建独立 Agent/Preset、却把总管权责写进根会话 `SKILL.md`”的设计缝隙，必然诱导根会话 Lead 在 `AGENT_PROTOCOL.md` 中将自己合法化为后勤总管，进而爆发越位代行（L1–L12）。
2. **悖论二：主动推送式“极薄后端事件总线” vs DSH 对话式 Root Lead 编排的范式冲突**
   - `agent_kb/01` 把 Cordis 总线比作 `Station` 的后台同步循环（`parallel_runner.py`），假定插件能在后台自动捕获一切事件并拉起各部门；
   - 但 DSH 是**人-根代理（Root Agent）对话驱动**的宿主：用户在主窗口向 Root 下达指令，Root 拥有 `subagent` 工具自行统筹并发与上下文总结。如果插件同时在 `autoDispatchSubagents=true` 下偷偷异步启动 `startActivation` 子代理，就会与 Root 的显式任务流抢占并发槽位、导致提示词与工作区状态竞争；而一旦为了稳妥把 `autoDispatchSubagents` 设为 `false`，总线立即瘫痪，所有调度权自动回流给 Root，极薄总线与无偏见原则在 DSH 上天然处于“两难死角”。
3. **悖论三：共享工作区文件可读性与“接口层物理盲审 / 学徒隔离”的穿透悖论（叠加 P0）**
   - `agent_kb/03` L49 与 `agent_kb/01` L62 假定只要 MCP 接口屏蔽 B 栏、DSH 裁掉写入/Shell 工具，即可实现物理盲审与学徒隔离。
   - 但在 DSH 下：① `subagent` 不支持 `preset`（P0），子代理继承全量工具；② 更本质的是，只要探索者、伴随助手、图书馆、监察委**共用同一套磁盘工作区目录**，且只读部门被允许用 `read`/`write(.md)` 读写工作区报告（`BOARDING_BRIEF.md`、`HANDOFF.md`、`SURVEY.md`、`PLUGIN_ISSUES.md`），中央图书馆无需调 MCP 即可用 `read` 直接打开探索者文件夹的 `HANDOFF.md` 或 `META_REFLECTION_37.md`，**“SQL 层物理屏蔽 B 栏与身份”在文件系统层一秒穿透**。
4. **悖论四：“单会话总上下文 37%/70% 唯一真时钟”与“DSH 高基线开销 / 无标尺纯推导任务”的尺度失调**
   - `agent_kb/02` 把单会话总上下文百分比作为唯一真时钟，却未区分 **“宿主固定基线 Token（System Prompt + 全量工具 Schema + Skill + 角色契约 + 看板）”** 与 **“本轮净工作 Token”**。在 DSH 下（尤其 P0 无法裁剪工具面时），固定基线即占数万 Token，导致 Q1 这类纯推导分支在 0 次实验时就按总比例触发 `37%`，并强锁在 `submit_node_handoff` 门禁上，形成“未产出先反思、反思无观测可锁”的空转循环。
5. **悖论五：全局单一 `state_version` 版本闸门 vs 平行多分支并发推进的误伤悖论**
   - `agent_kb/03` & `04 §4.3` 引入全局递增 `state_version` 并在交接时拦截 `bound_state_version < cur_state`。在多条互相正交的分支（Q1/Q2/Q3/Q4）并发推进的 DSH 架构下，任何一条分支或总管对单条重复观测执行 `invalidate_observation`（如作废 `[Obs012]/[Obs013]`）都会把全局 `state_version` 推高，导致另一时间线或同节点上**完全合法的历史有效观测（`[Obs009]/[Obs010]/[Obs011]`）在无因果关联的情况下被全局版本号误判为“过时迟到提交”**！版本门禁本应绑定在具体 `family_id` / `DEPENDS_ON` 上游前提集合，而非全局单一整数。
