# 专项审计报告 E：DSH 原生工具/沙箱能力核查 × 上下文窗口演进溯源 × SLA 原论文状态管理对账

> **审计角色**：Subagent E（DSH 原生工具/沙箱能力核查 × 上下文窗口演进溯源 × SLA 原论文状态管理对账官）  
> **审计范围**：本机 DSH `app.asar` 官方包源码与桌面端 Profile 配置、`greatwall-v6up/` 及 `greatwall-v6up-plugin/` 源码、全部顶层设计文档（`手写project.md`、`04`、`05`、`06`、`agent_kb/02`）、第二轮实机轨迹（`session.v4.jsonl.zstd` / `audit_A`）以及本机 `SLA` (`arXiv:2610.07625`)、`Station v2` (`arXiv:2610.08927`) 一手资料。  
> **零幻觉与只读声明**：所有核查均以只读方式完成，未修改任何工作区、`.dsh/` 或测试资产文件；文中全部文件路径、包名、符号名、行号、报错文本及实测数字均直接取自工具原始输出。

---

## 核心摘要（Executive Verdict）

1. **DSH 原生能力起底（回答用户 #9 与 #11）**：DSH 官方并非功能残缺，而是提供了极其完备的 `@deepseek-ai/dsh-agent-preset`、`dsh-tool-subagent`（支持 `allowedAgentPresets` 与 `modelSelection`）、`dsh-sandbox-windows-acl`（写限制受限令牌，**明确不限读**）、`dsh-experimental-tool-worktree`（真实 Git worktree）、`dsh-token-meter` 与 `dsh-agent-team`。问题分为两类：
   - **第一类（没接上 + 重复造烂轮子）**：插件声称对接了 `dsh-agent-preset`、`dsh-sandbox-windows-acl`、`dsh-experimental-tool-worktree` 和 `ctx.subagents`，但实测全线脱节——`dsh-web-app` 的 `ptc`/`standard` preset 未配 `allowedAgentPresets` 导致模型根本看不见 `agent_preset` 参数；插件自造的 5 个 `preset-greatwall-*` 里写死了未注册变量 `{{cwd}}`（一旦真启用即崩溃）；`event_bus.js` 硬编码调用 DSH 中根本不存在的 `Symbol.for('dsh.subagent.deliverPrompt')`、`subagents.startContinuable` 与不存在的 provider `'in-process'`；`worktree_and_acl.js` 探测 `@deepseek-ai/dsh-sandbox-windows-acl` 直接 `Cannot find module` 失败，且自造正则轮子误杀 Epoch 2 自家目录 `26` 次、可被 `../` 绕过、甚至会反封杀官方 `.agents/worktrees/dsh-*`。
   - **第二类（DSH 架构范式与插件设计存在结构性冲突）**：DSH `dsh-subagent` 是严格的**单向父子激活树（默认 `maxDepth=1`、`maxActiveSubagents=8`，子代理启动即锁权限且无法再派生下级、也无法在无根会话介入下平行互建）**，且 `preset` 在会话创建/首轮即固化、**不支持在 37% 时同会话热切换 Minimal→PTC**。不重构为“外部控制面循环 + 无状态重建会话”，任何在旧套路上的小修都无法实现“一委三部平行互唤”或“同会话热切工具面”。
2. **上下文窗口 `1M → 357k/250k → 178.5k/125k` 四级缩水实锤（回答用户 #8）**：DeepSeek 官方模型窗口为 `1,048,576`（1M，`手写project.md` 原设 `37%=370k`、`70%~80%=700k~800k`）。设计文档 `04` 与 `agent_kb/02` 把“减半”直接写成停笔封顶 `250,000` 并保留 `70%`，迫使初版 `greatwall-v6up-plugin` 反推出 `357,000` 窗口（$250{,}000 / 0.70 \approx 357{,}143$，已砍至 1M 的 ~34%）；第一轮 `06` 热修复在未定位真因的情况下，**又在 `357k/250k` 基础上再次减半成 `178,500 / 125,000`**（且用 `Math.min(rawWin, 178500)` 强行截断宿主传入的 `1,048,576`）。最终停笔上限仅剩 1M 的 **12.5%**（`11.92%` of `1,048,576`），`37%` 仅 `66,045` tokens。在实测探索者 `09858243` 中，`system/message` 占 `106,989` 字节、Step 1 起跑即耗 `30,239` promptTokens，净增 `36.7k` tokens（Step 12）即触发 37% 停码。第二轮 13 个完整探索者全部在 Step 7–19 触及 37%（0/13 写出 `candidate.py`，0/13 提交 `[Obs]`）。
3. **`SLA` 状态管理遭遇“两级连续缩水”（回答上层架构质问 #2）**：`SLA`（`arXiv:2610.07625`）的精髓是 **“全角色（含协调者 Advisor）强制无状态重启 + Harness 确定性上下文推式重构（Push） + 局部 `Retained Candidate` 代码快照自动保底/全局最优重置 + `MEASURED_NON_IMPROVEMENT` 与错误严格隔离 + 确定性 Epoch/Trial 外环控制流”**；`Station v2` 更以 `ParallelTickRunner` + `FastLaneSubmissionService` 保证 Single-Writer 串行化提交。但顶层设计（`04`/`agent_kb/02`）已漏掉“协调者无状态化、确定性外环状态机、工作区代码自动重置、Push 视图与 Pull 图查询的 Token 冲突解决”五大支柱；施工阶段（`greatwall-v6up/`）进一步二次缩水为 **10 个被动散装 MCP 函数**，全靠大模型靠记忆手工串流程，结果 Epoch 2 出现 `0` 次 `triage_decision`、`0` 次 `fork_branch`、`0` 条 `reviews`、`0` 条 `saved_queries` 与 P26 静默版本号倒退破坏。

---

## 第一部分：DSH 原生插件与工具架构真实能力大起底（回答 #9 与 #11）

通过只读解析本机桌面端配置（`C:\Users\wangy\.dsh\profiles\desktop\package.json`、`cordis.yml`、`cordis.patch.yml`）及 DSH 安装包核心源码包（`D:\DshDesktop\resources\app.asar` 内 `dsh/node_modules/@deepseek-ai/*`），并与 `greatwall-v6up/dsh_plugin/` 逐行对账，查明全部真相如下。

### 1.1 DSH 官方原生能力实测清单与真伪核验

| 官方原生包（`D:\DshDesktop\resources\app.asar`） | 官方真实设计定位与核心导出/机制 | 本机 Desktop 实际挂载状态 | `greatwall-v6up/dsh_plugin/` 对接现状 |
|---|---|---|---|
| **`@deepseek-ai/dsh-agent-preset`**<br>**`@deepseek-ai/dsh-agent-preset-registry`** | 在 Cordis YAML 声明多套独立 Preset，每套在独立 `cordis:group` / scope 中挂载各自的工具、技能与 `persona`；支持会话在**空白期**选择/切换 preset，启动后由 `agentPreset` 投影持久化（`README.zh.md:196-207`, `src/session.ts:343-387`）。 | `cordis.patch.yml:48-52` 启用 `agent-preset-registry`，`default: standard`、`selectedDefault: ptc`。 | `cordis.patch.yml:20-130` 声明了 5 个 `preset-greatwall-*`，但**存在致命模板变量错误且完全未被 `tool-subagent` 引入**。 |
| **`@deepseek-ai/dsh-tool-subagent`**<br>**`@deepseek-ai/dsh-tool-subagent-control`** | 向模型暴露 `subagent` 工具；仅当部署配置了 **`allowedAgentPresets`** 时才向模型公开 `agent_preset` 枚举参数；支持 `modelSelection`（动态切换子级 `provider`/`model`/`reasoning_effort`）与 `modelDiscovery`（`list_subagent_models`）；`dsh-tool-subagent-control` 提供 `send_message` / `list_agents` / `interrupt_agent` / `wait_agent`。 | `dsh-web-app/presets/ptc.patch.yml:471-482` 挂载 `tool-subagent` (`provider: spawn`, `modelSelection: true`, `modelDiscovery: true`) 与 `tool-subagent-fork`，**未配置 `allowedAgentPresets`**。 | 插件未写任何补丁覆写 `tool-subagent` 行，导致模型侧 `subagent` 工具**根本没有 `agent_preset` 参数**；全部子代理被迫继承父会话 `ptc`。 |
| **`@deepseek-ai/dsh-subagent`**<br>**`@deepseek-ai/dsh-subagent-spawn-in-process`**<br>**`@deepseek-ai/dsh-subagent-fork-in-process`** | 注册 `ctx.subagents` 服务与 `'spawn'` / `'fork'` 提供方；默认 **`maxDepth = 1`**、**`maxActiveSubagents = 8`**（`src/index.ts:196-197`）；公开 `startActivation()`、`sendMessage()`、`interrupt()`；`subagent/start` 与 `subagent/end` **仅作观察事件**（`README.zh.md:759`）。 | `dsh-base/cordis.patch.yml:369-380+` 挂载 `subagent` 与 `subagent-spawn-in-process` (`providerName: 'spawn'`)。 | `event_bus.js:30,339,359,377,435` 调用了**不存在的** `Symbol.for('dsh.subagent.deliverPrompt')`、**不存在的** `startContinuable` 与**不存在的** provider `'in-process'`。 |
| **`@deepseek-ai/dsh-sandbox-windows-acl`**<br>**`@deepseek-ai/dsh-sandbox`**<br>**`@deepseek-ai/dsh-sandbox-local`**<br>**`@deepseek-ai/dsh-sandbox-policy`** | `dsh-sandbox-local` 在 Win32 下自动以 `dsh-sandbox-windows-acl` 作为 `ctx.sandbox` 的 runner（`WRITE_RESTRICTED` 受限令牌 + Low Integrity Label）。官方明文限制：**“写入与删除受限；读取、网络与进程可见性不受限。两层都不交叉检查读取”**（`README.zh.md:396,459`）。 | `dsh-base` 挂载；但本机用户 `C:\Users\wangy\.dsh\profiles\desktop\cordis.patch.yml:21` 设 **`defaultPreset: danger-full-access`**（旁路沙箱）。 | `worktree_and_acl.js:67-94` 试图 `require('@deepseek-ai/dsh-sandbox-windows-acl')` 探测，实测**报错找不到模块 (`available: false`)**，且返回字段从未被消费。 |
| **`@deepseek-ai/dsh-experimental-tool-worktree`**<br>**`@deepseek-ai/dsh-experimental-worktree`** | 提供 `create_worktree` 工具及 `ctx.worktrees` 服务：从本地提交在 `<repo>/.agents/worktrees/<name>` 创建独立 Git 分支与检出目录，并调用 `ctx.workingDirectory.set` 切换会话目录（`README.zh.md:516-522`）。 | Desktop `package.json:28` 已在 `bundles` 中加载 `@deepseek-ai/dsh-experimental-tool-worktree`。 | 插件**完全未调用 `ctx.worktrees`**，手搓 `worktree_and_acl.js` 正则轮子，既误杀合法目录、又可被 `../` 绕过、还反封杀官方 `.agents/worktrees/`。 |
| **`@deepseek-ai/dsh-token-meter`** | 提供 `ctx.tokenMeter.contextPressure(session)`（返回 `pressureTokens` / `projectedTokens` / `contextWindow`）与 `measure(session)`，回放持久日志进行确定性计量（`README.zh.md:599-637`）。 | `dsh-base/cordis.patch.yml:358-359` 挂载于 Host 平面。 | `event_bus.js:167-187` **唯一真实接通的原生服务**；但未扣除系统/工具基线直接撞向 `178,500` 人工低顶。 |
| **`@deepseek-ai/dsh-agent-team`**<br>**`@deepseek-ai/dsh-tool-agent-team`** | 在开启 Team 模式的子树内提供持久化共享任务板（`team_task_create/list/get/update`），成员**共享同一检出目录**、靠 `subagent` 工具创建和通信。 | `dsh-base/cordis.patch.yml:372-378` 已挂载。 | 插件完全未参考/未协调 Team 机制，亦未在 `gate.js` 中考虑与之冲突或协同。 |

---

### 1.2 第一类问题：DSH 原生高稳定工具没用好 / 没接上，反而重复造了带 Bug 的烂轮子

#### 铁证 1：Preset 彻底悬空，且一旦真挂载会当场崩溃
1. **为什么模型在 `subagent` 中根本指定不了 `greatwall-*` Preset？**
   - 核查 `@deepseek-ai/dsh-tool-subagent/src/preset-selection.ts:426-429, 454-462` 与 `src/index.ts:706-712`：
     ```ts
     // dsh-tool-subagent/src/index.ts:706-712
     ...presets.choices === undefined ? {} : {
       agent_preset: {
         type: 'string' as const,
         enum: [...presets.choices],
         description: presets.description,
       },
     },
     ```
     只有当 `tool-subagent` 实例配置了 `allowedAgentPresets` 时，模型侧 `subagent` 工具才会有 `agent_preset` 参数；否则 `resolve()` 返回 `config.agentPreset ?? undefined`（直接继承父会话 preset）。
   - 核查 `dsh-web-app/presets/ptc.patch.yml:471-477` 与 `standard.patch.yml:251-257`：官方配置 `tool-subagent` 时仅设置了 `provider: spawn, toolName: subagent, modelSelection: true, modelDiscovery: true`，**没有设置 `allowedAgentPresets`**。
   - 核查 `greatwall-v6up/dsh_plugin/cordis.patch.yml:1-130`：插件仅插入了 5 行 `@deepseek-ai/dsh-agent-preset`，**没有任何补丁覆写 `id: tool-subagent` 去注入 `allowedAgentPresets`**！于是第二轮实机全部 37 个会话全部运行在默认 `ptc` preset 下，5 大角色 Preset 形同虚设，连带插件只能靠 `event_bus.js:44-54` 的 `matchRoleKeywords()` 猜子代理名字。
2. **如果真的选用了 `greatwall-v6up` 的 5 个 Preset 会发生什么？（实锤必崩溃）**
   - `greatwall-v6up/dsh_plugin/cordis.patch.yml:32, 60, 78, 98, 126` 在 5 个 preset 的 `@deepseek-ai/dsh-persona` 配置中全部写了 `suffix: '当前工作区: {{cwd}}'`（或 `'只读审计工作区: {{cwd}}'`）。
   - 然而核查 `dsh-system-prompt/src/index.ts:372-375` 与全仓 `.variable(` 注册点（`dsh-agent-loop/src/index.ts:336-337`）：整个 DSH 仅注册了 **`{{provider}}`** 与 **`{{model}}`** 两个变量，**根本没有注册 `{{cwd}}`！** 而 `dsh-system-prompt` 在渲染时执行严格校验：`if (!Object.hasOwn(variables, name)) throw new Error('unknown prompt variable "{{cwd}}" ...')`！一旦任意会话激活 `greatwall-*` preset，`systemPrompt.assemble()` 当场抛异常崩溃。
   - 此外，5 个 preset 中还使用了已废弃的 `@deepseek-ai/dsh-agent-tool-presentation`（`@deprecated`），且全部漏配了 `dsh-compaction-basic`、`dsh-tool-fs-search`（`grep`/`glob`）、`dsh-tool-subagent`、`dsh-agent-instructions` 等基础插件。

#### 铁证 2：`event_bus.js` 面向幻觉 API 编程，单测靠 Mock 掩盖
核查 `greatwall-v6up/dsh_plugin/lib/event_bus.js` 与 `app.asar` 内 `@deepseek-ai/dsh-subagent` 源码：
- `event_bus.js:30` 定义 `const DELIVER_SUBAGENT_PROMPT_SYM = Symbol.for('dsh.subagent.deliverPrompt')`，第 359 行尝试 `subagents[DELIVER_SUBAGENT_PROMPT_SYM](...)` —— **全 `app.asar` 检索证实该 Symbol 根本不存在**（真实公开 API 为 `ctx.subagents.sendMessage(sender, targetId, content, options)`，`dsh-subagent/src/index.ts:368`）。
- `event_bus.js:377, 392, 429, 478` 调用 `subagents.startContinuable(...)` —— **全 `app.asar` 检索证实该方法根本不存在**（真实 API 仅为 `ctx.subagents.startActivation(spec)`，`dsh-subagent/src/index.ts:267`）。
- `event_bus.js:339, 435` 默认回退 `provider = options.provider || rec?.provider || 'in-process'` —— 而 `dsh-subagent-spawn-in-process/src/index.ts:25` 注册的真实 provider 名称是 **`'spawn'`**，根本没有 `'in-process'`！一旦 `autoDispatchSubagents` 设为 `true`，调用 `startActivation({ provider: 'in-process', ... })` 必抛 `PROVIDER_NOT_FOUND` 异常。
- 集成测试 `greatwall-v6up/dsh_plugin/test/cordis_integration.test.mjs:18, 216-229` 既因硬编码路径 `C:\Users\wangy\nodejs\...` 在本机直接跳过，又用 `ctx.provide('subagents', { startContinuable: ... })` Mock 了虚假 API，导致上述三大接口错位在开发期零暴露。

#### 铁证 3：`dsh-sandbox-windows-acl` 未真正使用，且语义被严重误解
- 在 `C:\Users\wangy\nodejs\node.exe` 下直接导入 `worktree_and_acl.js` 实测调用 `probeWindowsAclCapability()`，返回：
  ```text
  { available: false, exports: [], error: "Cannot find module '@deepseek-ai/dsh-sandbox-windows-acl'" }
  ```
  因为插件以 `link:` 挂载于 `D:\antigravity\...`，无法解析封在 `D:\DshDesktop\resources\app.asar` 内部的私有包；且全插件没有任何地方读取返回的 `windowsAclReady` 字段。
- 更根本的是，即便在 DSH 运行时内部，`dsh-sandbox-windows-acl` 也**只管写入与删除（`WRITE_RESTRICTED` + Low IL），完全不限制读取（`README.zh.md:396`）**。计划书 `04` §7.1（L337）想当然地指望它“防探索者偷读兄弟分支与隐藏集”，本身就超出了 Windows `WRITE_RESTRICTED` 令牌的内核能力边界；况且桌面端 `cordis.patch.yml:21` 默认 `defaultPreset: danger-full-access`，原生写隔离也未开启。

#### 铁证 4：放着官方 `create_worktree` 不用，手造带三大 Bug 的正则轮子
- 桌面端已原生启用 `@deepseek-ai/dsh-experimental-tool-worktree`（`package.json:28`），会在 `<repo>/.agents/worktrees/<name>` 创建真 Git 工作树并切换 Session `workingDirectory`。
- 施工方完全没有对接 `ctx.worktrees` 或 `create_worktree`，而是手写了 `worktree_and_acl.js`：
  1. **Epoch 2 自锁误杀（实机命中 26 次）**：`extractCanonicalNodeRoot`（L27）正则 `/(?:^|[^a-z0-9])(n\d{1,5})(?:[_-]?g\d+|[a-z]?)(?=$|[^a-z0-9])/i` 只认识 `N001` 格式。Epoch 2 节点改名 `N_Q3` 而目录名为 `03_explorers/Q3/` 时，提取结果为 `N_Q3 !== Q3`，**当场拦截探索者读取/提交自己的工作文件**（如 `e8e2f112` 在 `01:28:15` 与 `01:28:23` 连遭两次 `GATE_BLOCK`，被迫复制代码到 `_q3_upload/` 绕过，见 `audit_A` L191）。
  2. **路径穿越 100% 绕过**：实测 `checkExplorerWorktreeIsolation('03_explorers/N001/../N002/secret.py', 'N001')` 返回 **`undefined`（放行）**，因为 `BRANCH_DIR_SEGMENT_RE`（L16）仅匹配首段 `N001` 即终止，完全不做路径规范化（`path.posix.normalize`）。
  3. **反封杀官方 Worktree**：实测 `checkExplorerWorktreeIsolation('.agents/worktrees/dsh-6b1f02c4-9a3e/cand.py', 'N001')` 返回 **`🔒 [V6-Up Worktree 分支隔离门禁]` 拦截**——因为 DSH 官方自动生成的目录名 `dsh-6b1f02c4-9a3e` 与节点根 `N001` 不一致！

---

### 1.3 第二类问题：DSH 架构范式本身与当前插件设计存在本质冲突（小修无法解决）

即便把上述 Bug 全部修平，**DSH 当前原生底层架构（`0.2.2-rc.3`）与插件“一委三部平行网状互唤 + 37% 同会话热切换 Minimal→PTC”的想当然设计之间，仍存在 4 条不可通过小补丁调和的范式冲突**：

1. **严格树形委派模型 vs “一委三部平行网状互唤”**：
   - DSH `dsh-subagent`（`README.zh.md:566-578, 595`）规定：委派默认 **`maxDepth = 1`**（只有根会话 `lead` 能创建子代理，一级子代理被系统提示词 `delegationDepthOf >= maxDepth` 明确禁止再调用 `subagent`），且 **`maxActiveSubagents = 8`**（整棵树在线+待唤醒上限 8 个）。
   - 子代理启动返回 `{ kind: 'activation', name }`，完成后只向**创建者 `parent`** 发送完成通知（`delivery: 'parent'`）。子代理之间虽有 `ctx.subagents.sendMessage()` 工具，但要求双方都在同一棵活树内，且**非根子代理无法自行 `startActivation` 新建另一部门的新无状态会话**（例如：探索者无法自己拉起“全新的匿名独立 `central_library` 盲审员”，伴随助手也无法自己拉起“第二任探索者”或“Coding Assistant”）。
   - **冲突结果**：只要沿用“根会话作为唯一 `lead` 发起全部子代理”，任何跨角色协作必然退化为第二轮实机所见的**单中心星型拓扑**（37 个子代理 100% 由 `session-56a36cab` 发起，173 次 `send_message` 由 ROOT 中转），无法做到真正的平行点对点自动唤醒。
2. **预设（Preset）创建即锁定 vs “37% 后同会话由 Minimal 热切到 PTC”**：
   - 核查 `dsh-agent-preset-registry/README.zh.md:196-200, 233` 与 `src/session.ts:345-351`：Preset 只能在空白会话（首轮前）选择，一旦产生首轮消息即固化至该会话全部生命周期（为保 KV-Cache 前缀稳定，且 `dsh-subagent/README.zh.md:733` 明确提示子代理权限在启动时锁定）。
   - **结论**：插件设计“探索者在同一个会话里 0–37% 用 Minimal、过 37% 后热切为 PTC”在 DSH 原生范式下**绝对不可实现**（除非通过外部 Harness 直接销毁旧会话并新建启用 PTC 的新会话，或在 `gate.js` 中放行已挂载工具——但那就违背了 Minimal Preset 工具面裁减的初衷）。
3. **事件钩子只供观察 vs 插件依赖 `subagent/end` 驱动编排流转**：
   - `dsh-subagent/README.zh.md:759` 明确指出：**“生命周期事件只供观察——影响运行的 `subagent/end` 延续或决策接口仍需等待具体消费方。”** 并且 `startActivation` 需要传入**精确的实时存活 `parent: Agent` 实例**（`dsh-subagent/src/index.ts:162-164`），如果父会话已离线或正处于非受控状态，后台总线钩子无法凭空替其安全创建并维持后续接力循环。
4. **共享任务板 `dsh-agent-team` 假设共享工作区 vs 科研隔离要求**：
   - 官方 `dsh-agent-team/README.zh.md:13, 35` 明确写着：**“成员共享同一检出目录……Team 不创建隔离工作目录”**，其设计针对的是“同仓协作改代码”。而长城 V6-Up 要求“首轮学徒隔离”、“跨分支禁读”、“阶段一物理盲审”。
- **结构性出路**：若要在 DSH 上真正落地 SLA 与平行科研共同体，必须放弃“在聊天主窗口里靠 `lead` 和 `tools/post-execute` 钩子糊编排”的旧路，改为**外部 Node/Python 编排器（或 Headless DSH SDK / Typert 控制面）持有研究状态与唯一写权，显式按 Epoch/Trial 调用独立、短命、带正确 Preset（含有效 `allowedAgentPresets`）的新建会话**；不再幻想由 `ROOT` 聊天机器人兼任调度总线。

---

## 第二部分：`1M → 250k / 357k → 178.5k / 125k` 上下文窗口演进全链条溯源（回答 #8）

逐一核对全部原始设计文档、源码、测试与第二轮实机日志，完整还原“好心减半”是如何演变成“双重腰斩剩 12.5%、探索者 15 步猝死”的全过程。

### 2.1 四阶段演变溯源表

| 演变阶段 | 一手出处（精确文件与行号） | `defaultContextWindow` / 窗口上限 | `37%` 元反思线 | `70%` 强停笔线 (`handoff_token_cap`) | 占 DeepSeek 1M (`1,048,576`) 比例 | 演变原因与数学逻辑偏差 |
|---|---|---|---|---|---|---|
| **Stage 0：原始 1M 基准** | `dsh-llm-deepseek/src/models.ts:5`；<br>`手写project.md:72` | `1,048,576`<br>(约 1,000k) | `370,000`<br>(`37%`) | `700,000 ~ 800,000`<br>(`70% ~ 80%`) | 窗口 100%<br>停笔 **66.8%~76.3%** | 用户原始设想按 DeepSeek 1M 满窗设计，37% 元反思留足近 37 万 tokens 供深入试错。 |
| **Stage 1：首次“减半”被写成 `250k / 357k`（实砍至 ~1/3）** | `04` 专报 L197, L336, L384-386；<br>`05` L32；`agent_kb/02` L20；<br>`greatwall-v6up-plugin/config.json:5`；<br>`greatwall-v6up-plugin/mcp_server/greatwall_core_mcp.py:64,67,363` | **`357,000`** | `132,090`<br>(`357k × 37%`) | **`250,000`**<br>(`357k × 70%`) | 窗口 **34.05%**<br>停笔 **23.84%**<br>(相对于 1,000k 为 **25%**) | 用户因 1M 跑满太慢要求“减半”（本应设窗口 `500k`，对应 70% 停笔线 **`350k`**）。但 `04` 与 `agent_kb/02` 直接把 `handoff_token_cap` 写成了 `250,000` 并保留 `0.70`；初版施工方在 `greatwall-v6up-plugin` 中为了使 `70%` 恰好吻合 `250k`，按 $250{,}000 / 0.70 \approx 357{,}143$ 反推出 `default_total_context_window = 357,000`，**第一次已暗中从 1M 砍到 34%**。 |
| **Stage 2：`06` 热修复“再次减半”至 `178.5k / 125k`** | `06_QuarticOscillator实机复盘...md` §1.3 L50；<br>`greatwall-v6up/core_python/config.json:5-6`；<br>`greatwall-v6up/dsh_plugin/lib/index.js:39,469`；<br>`greatwall-v6up/dsh_plugin/cordis.patch.yml:18`；<br>`greatwall-v6up/dsh_plugin/lib/event_bus.js:15-20,198`；<br>`tests/test_v6up_new_kernels.py:689`；`plugin.test.mjs:76` | **`178,500`** | **`66,045`**<br>(`178.5k × 37%`) | **`125,000`**<br>(`178.5k × 70% = 124,950`) | 窗口 **17.02%** (`17.85%` of 1M)<br>停笔 **11.92%** (**12.5%** of 1M)<br>37% 仅 **6.30%** | 第一轮 `quartic-oscillator-v1` 出现 5 个探索者 `corrupt`（真因之一是插件调用 `subagents.interrupt` 强行打断运行中 `run_code` 且 `additionalContexts` 缺 `id`/`source`，见 `06` §1.3 L52, L55-56）。热修复团队却把 **`357k / 250k` 当成基数再次减半**成 `178,500 / 125,000`，并用 `Math.min(rawWin, 178500)` **强制无视宿主传入的 `1,048,576`**，还写了单测锁死该封顶！ |
| **Stage 3：第二轮实机“未扣基线”雪上加霜** | `09858243-f2a4-4195-aa01-b19f924a1d6f/session.v4.jsonl.zstd`；<br>`第二轮测试分析/audit_A_sessions_and_events.md:14,320-338` | `178,500` 封顶<br>实测初始基线占 **`30,239`** | 净可用仅 **~11k–36k**<br>(实机第 **7–19 步**触发) | 净可用仅 **~70k–95k**<br>(实机第 **20–46 步**强停) | 扣除初始基线后净实验上限仅剩 1M 的 **~9%** | `event_bus.js:167-199` 直接用含系统提示词的 `TokenMeter.contextPressure().pressureTokens` 对比 `66k` / `125k` 绝对值，**完全未扣除固定基线**！ |

### 2.2 第二轮原始会话轨迹硬核实证（以 `09858243` 为例）

直接解压并逐行解析 `C:\Users\wangy\.dsh\sessions\--D-Documents-deepseek~0020harness-v6~6D4B~8BD5--\09858243-f2a4-4195-aa01-b19f924a1d6f\session.v4.jsonl.zstd`（Q1 首代探索者）：
- **Line 13 (`system/message`)**：系统提示词 JSON 记录长度高达 **`106,989` 字节（约 104.5 KB）**（含 DSH 基础提示词、PTC SDK、工具描述与插件注入的 `explorer.md` 契约）；
- **Line 26 (Step 1 首次 LLM 返回)**：模型刚读入首条任务指令、`promptTokens` 起始基线即达 **`30,239` tokens**（`input=2,463, cacheRead=27,776, output=167, totalTokens=30,406`）；
- **Line 132 (Step 12) → Line 143**：`promptTokens` 刚跨过 **`66,971`**（超过 $178{,}500 \times 0.37 = 66{,}045$），插件立即在 `Line 143` 注入 `[GREATWALL_CLOCK 37% | META_REFLECTION_AND_HOLIDAY]` 要求“立即冻结功能代码改动”——此时距起跑**仅推进了 11 步、净增 `36,732` tokens**；
- **Line 202 (Step 20) → Line 213**：`promptTokens` 刚到 **`126,705`**（超过 $178{,}500 \times 0.70 = 124{,}950$ / `125,000`），插件立即注入 `[GREATWALL_CLOCK 70% / 125k | FORCE_HANDOFF_STOP]` 强令退场——净增仅 `96,466` tokens，距 Step 1 仅 **19 步**。
- **全盘统计（`audit_A` L14, L322-338）**：第二轮 13 个完整运行的探索者会话中，**13/13 在 Step 7–19 触及 37% 停码反思（0/13 写出 `candidate.py`、0/13 提交 `[Obs]`）**；即使撑到 70% 强停线，也仅 4/13 写出 `candidate.py`，新写代码者中 **0 人在 70% 响起前完成 `[Obs]` 提交**。

---

## 第三部分：基于 `SLA` 原论文的状态管理对账（回答上层架构质问 #2）

直接对照本机 `2610.07625_StatelessLanguageAgents_中文综述.md`、`2610.07625_StatelessLanguageAgents_原文解析.md`（§3.1–3.3、§4.3–4.4、Appendix B.1）以及 `Station v2`（`parallel_runner.py`、`fast_lane_service.py`），逐项审计 V6-Up 从 **SLA 原论文 → 顶层设计（`04`/`agent_kb/02`） → 施工代码（`greatwall-v6up/`）** 的**两级连续缩水**。

### 3.1 SLA 原论文（及 Station v2）的外部状态管理 6 大精髓

1. **全角色无状态（含顶层协调者 Advisor）**：不仅 Worker 每次 Trial 销毁重启（清理本地持久化会话与临时文件，并禁用 Codex 内置多智能体以防嵌套有状态，Appendix B.1 L263），**Advisor 在每个 Epoch 也从全新零历史会话重启**（§3.2 L88, §6.2）。正是因此，Advisor 每次只读约 8K 摘要，仅消耗总 Token 的 **0.24%–0.51%**（总成本的 **1.20%–2.29%**），而有状态的 SwarmResearch Shepherd 每次平均读 99K 输入、耗费 **8.39%–10.70%** Token（§4.4 L201-210）。
2. **Harness 控制的确定性上下文重构（Push View，而非自由 Pull）**：State 归 Harness，Context 只是 Harness 对当前 State 执行的一次“只读视图投影”。Harness 在每个 Epoch/Trial **运行前主动合成并推送**结构化证据摘要给 Advisor、推送 `(Task Spec + Assignment + Retained Candidate + Compact Local Feedback)` 给 Worker（§3.1 L78-82）。**SLA 消融实验（§4.3 表 4 L195）铁证：一旦去掉 Harness 预先合成摘要、改让 Advisor 自己通过只读接口去查完整历史记录，研究进展暴跌 `23.3% ~ 72.2%`！**
3. **严格的故障分类隔离（`Measured Non-improvements` vs `Inconclusive Failures`）**：Advisor 上下文摘要在 Harness 层将“经过正确评测但未提分的方案”与“实现/运行时/正确性报错导致的无效失败”严格分栏隔离，防止协调者将一次语法错误误判为“该技术方向不可行”（§3.1 L80）。
4. **`Retained Candidate` 局部基线自动保护 + 全局最优硬重置**：每个 Worker 的工作区由 Harness 持久化托管其 `Retained Candidate`——即使暂落后于全局最优也保留局部增量改进以渡过重构阵痛期；当且仅当 Advisor 决定令其转向新方向时，**由 Harness 自动将该 Worker 的磁盘工作区重置为 Global Best**，并将新方向首个通过评测的解设为新局部基线（§3.2 L88, Appendix B.1 L265）。
5. **确定性外环控制流与固定步调循环**：`SLA` 由外环 Harness 程序确定性执行 `Epoch (Advisor 派发) → W=3 并行 Worker × 3 局部 Trial (隔离执行 + 保护评测) → 状态持久化与快照检查点 → 下一 Epoch`，**不依赖任何 LLM 记住或自觉调用状态转移函数**（§3 L68, B.1 L269）。
6. **`Station v2` 并发状态机补强（`parallel_runner.py:1-13` & `fast_lane_service.py:24-103`）**：采用 **Two-Phase 确定性并行步调**（先统一准备所有 Agent 的不可变观测快照 $\to$ 并发推理 $\to$ 快车道动作经 `Queue` 由 `FastLaneSubmissionService` 单写者线程串行执行 $\to$ 统一中心化提交状态变更），彻底消除读写竞态与状态版本号撕裂。

### 3.2 两级缩水全对账表：SLA 原论文 → 顶层设计（`04`/`agent_kb/02`） → 施工代码（`greatwall-v6up/`）

| 状态管理维度 | `SLA` 原论文 + `Station v2` 标准工程 | 第一次缩水：顶层设计（`04` / `agent_kb/02`）的漏写与偏差 | 第二次缩水：插件代码（`greatwall-v6up/`）的二次降级与实机崩溃 |
|---|---|---|---|
| **1. 协调/治理层是否真正无状态** | **全角色无状态**：包括 Advisor 在内，每次调用均从全新会话重启（仅占 0.24%–0.51% Token）。 | **漏写管理层无状态重置**：只强调探索者 `70%` 重启，默认把 `ROOT`、总管、监委、伴随、工造司设为**常驻/冷恢复长会话**（仅模糊写了一句“累积上下文已高建议新建”）。 | 实机中治理/伴随/ROOT 全部沦为超长有状态会话：ROOT 644 steps、总管 476 steps、监委 365 steps、工造司 198 steps，**探索者反仅占全轮 steps 的 18.2%**（`audit_A` L11, L109-118）。 |
| **2. 确定性外环状态机 vs 大模型自觉调用** | 外环 Python Harness 拥有确定性 `Epoch/Trial` 调度状态机与 `Two-Phase` 提交；`FastLaneSubmissionService` 保证 Single-Writer 串行写状态。 | **放弃确定性外环驱动**：`04` §3.1 将主控降格为“极薄无偏见事件总线”，**未编写正规状态迁移表**（未规定何种事件必须触发何种状态跳转，把 `triage_decision`、`fork_branch`、盲审触发全寄托于 LLM 自觉调用 MCP）。 | 彻底退化为 **10 个松散被动 MCP 函数**（`greatwall_core_mcp.py:41-250`）+ 手动触发。无外环队列、无确定性迁移驱动，导致第二轮 Epoch 2 全程 **0 次 `triage_decision`、0 次 `fork_branch`、0 条 `reviews`、0 条 `saved_queries`**（`audit_A` L12）。 |
| **3. 上下文重构：Push 投影视图 vs Pull 自查** | Harness 在每次唤醒前按角色 **Push** 重构视图；明确证伪“让 Agent 自己用只读接口查历史”（进展降 23%–72%）。 | **自相矛盾地混合 Push 与 Pull**：既要求合成 `~2000` 字看板（Push），又把 `AgentDiscover` 的自主 `read_lineage_graph`（Pull）设为探索者核心动作。 | `synthesize_lineage_briefing` 初版漏查 `L3`，看板更新依赖伴随助手手工调用 `update_lineage_briefing`；探索者起跑花大量步数自己 Pull 读文档，直接撞爆 66k/125k 窗口。 |
| **4. `Retained Candidate` 代码快照自动保底与重置** | Harness **物理托管**每个 Worker 工作区代码快照：局部提分则更新保留；转向新方向时自动将工作区文件硬重置为 Global Best。 | **只借用了名词，漏写了物理恢复协议**：`04` 与 `agent_kb/02` 只说在 `L2` 原地修补“保持私有 `Retained Candidate`”，未设计跨会话或转向时的**工作区文件系统自动重置与同步机制**。 | `mcp_tools_research.py:1142-1154` 仅在 SQLite 里更新一个 `retained_candidate_id` 哈希字符串，**从未操作过磁盘上的工作目录或代码文件**；下一代探索者依然靠肉眼读文件接盘，发生 P18/代码错乱时毫无保底恢复能力。 |
| **5. `EXECUTION_ERROR` 与 `VALID` 隔离及自动恢复** | 摘要严格隔离 `Measured Non-improvements` 与 `Inconclusive Failures`；`Station coder_manager` 遇崩溃自动指数退避恢复。 | `04` §3.3 定义了 `L2` 原地修补（限 3 次、连续 2 次错唤 `Coding Assistant`），但未定义自动重构摘要与自动触发接口。 | 直到后期才在 `submit_trial_observation` 补上 `consec_errs >= 2` 信号字符串（`mcp_tools_research.py:1175-1180`），但**无自动拉起 `Coding Assistant` 机制**，且 `autoDispatchSubagents` 默认为 `false`（`index.js:37`）。 |
| **6. 并发版本闸门与 Single-Writer 串行化** | `Station v2` 统一准备观测快照再集中有序提交；无版本号回退风险。 | `04` §4.3 提出 `bound_state_version` 并在交接时对迟到提交标 `PENDING_REVALIDATION`，但**未规定谁来更新队列与何人负责重评**。 | 引发 **P26 重大状态破坏 Bug**（`mcp_tools_research.py:1297-1352`）：`44de4e7e` 携旧 `bound_state_version=2 < 4` 提交手记时，代码把 `[Obs009/010/011]` 全降为 `PENDING_REVALIDATION` 且清空分数，**却漏写入 `system_meta.pending_revalidation`，还顺手把 `N_Q3.bound_state_version` 倒退写回 `2`**！ |

### 3.3 结论汇总：可直接向原设计者与施工方质问的 5 个硬核问题

1. **质问设计者 & 施工方（Preset 与原生能力脱节）**：既然知道 DSH `0.2.2-rc.3` 存在 `@deepseek-ai/dsh-agent-preset` 和 `dsh-tool-subagent`，为什么在 `greatwall-v6up/dsh_plugin/cordis.patch.yml` 里既不给 `tool-subagent` 补配 `allowedAgentPresets`（导致模型完全选不到 preset），又在 5 个 preset 里塞入 DSH 根本未注册的变量 `{{cwd}}`（一旦真正挂载即在 `systemPrompt.assemble()` 必崩）？`event_bus.js` 里的 `Symbol.for('dsh.subagent.deliverPrompt')`、`startContinuable`、`provider: 'in-process'` 究竟是照哪个不存在的文档编的，为什么单测用 Mock 掩盖并在集成测试里跳过？
2. **质问设计者 & 施工方（Worktree 与 ACL 轮子）**：DSH 已在桌面端加载 `@deepseek-ai/dsh-experimental-tool-worktree`，而官方 `@deepseek-ai/dsh-sandbox-windows-acl` 文档白纸黑字写明“**不限制读取**”且在插件目录根本 `require` 不到，为何不采用官方 `create_worktree` + 独立评测环境，反而手搓 `worktree_and_acl.js` 导致 Epoch 2 自身被误杀 26 次、可被 `../` 绕过、还反封杀官方 `.agents/worktrees/`？
3. **质问架构与热修复团队（1M → 125k 双重腰斩）**：`手写project.md` 基于 1M 设计 `70% = 700k`；从 1M 减半本应是 `500k`（70% = `350k`）。为何 `04` 直接写成 `250k`（`357k × 70%`），`06` 热修复在未修清 `subagents.interrupt` 与 `id/source` 真因时又对 `357k/250k` **再次减半成 `178.5k/125k`**，并用 `Math.min(rawWin, 178500)` 强行截死 `1,048,576`？在未扣除 `106,989` 字节（Step 1 `30,239` tokens）系统基线的前提下，把 1M 模型锁死在 `66k / 125k` 让探索者 7–19 步就停码，到底是在测科研还是在测早停？
4. **质问顶层架构设计者（DSH 树形范式冲突 + SLA 协调者有状态反弹）**：DSH `dsh-subagent` 原生 `maxDepth=1`、`maxActiveSubagents=8`、Preset 启动即锁定且不支持同会话 37% 热切，为什么不做外部确定性控制面循环（如 SLA / Station v2 的 Runner），而幻想在聊天主窗口里靠 `ROOT` 与观测级事件 `subagent/end` 自动编排平行网状共同体？同时，为何只让探索者无状态重启，却让协调者/伴随/监委/工造司保持有状态长会话运行，直接摧毁了 SLA `0.24%–0.51%` 协调开销的核心前提？
5. **质问后端工程实现（状态机散架与 P26 状态撕裂）**：没有合法状态迁移表、没有 Single-Writer 串行队列、没有磁盘级 `Retained Candidate` 物理快照与重启重置，把复杂科研状态机拆成 10 个被动 MCP 函数让模型自由发挥，甚至在 `submit_node_handoff` 里写出倒退写回 `bound_state_version` 却不入重评队列的 P26 Bug——这距离 `SLA` 与 `Station v2` 的“Stateful Search in Harness”究竟缩水了多少？
