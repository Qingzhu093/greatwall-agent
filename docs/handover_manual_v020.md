# GreatWall Agent (`v0.2.0-alpha.1`) 开发转交手册与踩坑复盘

> **交接基线**：Commit `476f5f3` (`main`) ｜ Tag & Pre-release [`v0.2.0-alpha.1`](https://github.com/Qingzhu093/greatwall-agent/releases/tag/v0.2.0-alpha.1)  
> **配套技术参考**：若需查阅纯客观、去业务化的 DSH 运行时 API 规范，请先读同目录下的 [`dsh_development_handbook.md`](./dsh_development_handbook.md)。  
> **文档目的**：这份手册写给下一位接手开发的人类协作者或 AI Agent。它不粉饰太平，而是把这一轮重构里**真正踩过的坑、走过的弯路、做减法确立的底线，以及哪些地方故意没动**全部如实交底，帮你省下至少 3 轮试错成本。

---

## 1. 接手基线速览

- **自动化全绿基线**：
  - Python 单元 + 并发一致性/真取消 + 架构防腐门禁：**`54/54`** 通过
  - Node 插件单元 + RC5 Schema 严检 + L2 假模型全链路：**`39/39`** 通过（连续 10 轮 L2 压测零抖动）
  - Doctor 环境与 32 工具跨层契约体检：**`7/7`** 通过
- **真实运行实测边界**：
  - 已在真实 **DSH `0.2.2-rc.5` CLI + DeepSeek Flash**（临时隔离 Profile）跑通主控 `greatwall_orchestrate`（`init` / `status`）以及补齐 `agentPresets` 后的子会话真实工具调用（收到完整 `tools/result` 回执）。
  - **尚未完成**：真实 DSH Desktop 图形界面下的完整多小时课题长跑、前端面板交互与 `uiWorkspace.openSession` 视觉验收、以及“长城多智能体 vs 单 Agent 裸跑”的受控科学对照实验。

---

## 2. 本轮最核心的架构心法（先立住，再动代码）

这一轮一开始我们也走过弯路（给并发打补丁、给跨 `cwd` 造本地假归档、给接口留新旧双轨兜底），结果越补越复杂，反而引出了更多边界 Bug。最后回归**第一性原理**做了一次彻底减法，确立了两条总纲：

1. **Python 内核总纲：「并发只读 + 并发纯外部计算 + 严格进程级单写者记总账」**
   - 真正耗时的是外部隔离评测子进程（几秒到几分钟），真正怕乱的是写 SQLite 总账（每笔仅 1–3ms）。
   - 不要试图在 SQLite 里搞复杂的多写者细粒度并发控制！直接用进程级可重入锁 `_SINGLE_WRITER_LOCK`（`db_runtime.py`）包住所有 `rw_immediate_tx` 短写事务，把所有读查询（`open_ro_connection` + `ro_consistent_tx`）和外部子进程计算（`isolated_runner.py`）全部放到锁外 100% 真并行。
   - **效果**：代码极简、延迟极低，同时在根子上消灭了绝大部分并发交错状态 bug。
2. **DSH 插件总纲：「以本机实装源码为唯一真相，信任原生能力，拒绝双账本与假轮子」**
   - DSH 迭代很快，线上文档经常落后于实装版本（例如本机 Desktop 是 `0.2.2-rc.5`，而全局 PATH 的 CLI 可能还是 `rc.3`）。
   - **永远不要凭印象猜 DSH API**——直接只读探测本机 `D:\DshDesktop\resources\app.asar` 里的真实 JS 源码与 `dsh-doc/references/*.md`。
   - 凡是宿主原生就能干好的事（如 `workspaceRegistry.archiveSession` 全局归档、Cordis 异步 `ctx.effect` 清理、`cordis.patch.yml` 单源 Preset），绝不自己另造一套假状态或双轨兜底。

---

## 3. 开发全程踩过的 12 个真实深坑与根因复盘

> 下面每一条都是我们在这一轮里实打实撞过墙、甚至被独立审阅复现出来的真坑。

### 坑 1：盲猜 Cordis `Config` 格式，导致插件在进 `apply()` 前当场崩溃
- **当时怎么踩的**：想做到零第三方依赖，直接把一个普通 JSON Schema 描述对象 `{ type: 'object', properties: ... }` 导出为 `export const Config`。单测直接调 `apply()` 和 `resolvePluginConfig()`，全部绿灯，完全没发现问题！
- **真实根因**：本机 RC5 内置 `@deepseek-ai/cordis@4.1.0` 在 `resolveConfig` 里直接调用 `runtime.Config["~standard"].validate(config)`，缺少 `~standard` 会在进入 `apply()` 前直接抛 `Cannot read properties of undefined (reading 'validate')`。
- **根治方案**：在 `dsh_plugin/lib/config.js` 实现标准 **Standard Schema v1**（`['~standard']: { version: 1, vendor, validate(input) }`），并直接抽取本机 `app.asar` 里真实 Cordis 运行时实测装载通过。
- **教训**：**凡涉及宿主装载协议的改动，绝不能只靠绕过宿主的单测自嗨，必须用真实宿主运行时（哪怕是抽取出来的核心模块）跑一遍装载！**

### 坑 2：只想着解“队头阻塞”，把 Python handler 直接丢进线程池导致产物串写
- **当时怎么踩的**：为了解决 Python stdio 串行阻塞，最初计划直接把工具分发丢进线程池。
- **真实根因**：原代码中 `obs_id = next_prefixed_id(...)` 和 Stage A 文件写入发生在 `BEGIN IMMEDIATE` 之前。两个并发 `official` 评测同时拿到 `Obs-001`，后者虽然撞主键失败，但已经把前者的磁盘 Stage A 文件覆盖成自己的产物！
- **根治方案**：先拆出真正的只读连接与事务（`db_runtime.py`），再让计算结果写入**请求独占的临时 staging 目录**，最后在单写者短事务 `rw_immediate_tx` 内原子分配 `Obs-###` 编号、移动产物并入库。

### 坑 3：Stage 3 “审 A 放 B” 与失败目录补偿跑到写锁外面
- **当时怎么踩的**：
  1. 导出侧虽然重置了终核标记，但监察委签发和盲审落签是在事务外核对版本与哈希、事务内仅按 `WHERE id = 1` 更新——并发导出 B 插队后，审过 A 的签字直接把未审的 B 放行成了 `CLOSED_VERIFIED`！
  2. 第一轮修完后，把 `try/except` 扩大覆盖了 `COMMIT` 异常，但异常触发目录恢复时已经退出了 `rw_immediate_tx` 并释放了写锁——此时第二笔合法导出 B 插队成功，随后第一笔的 `except` 把磁盘目录又回滚回了更旧的 A！
- **根治方案**：
  1. 盲审落签与监察终签把状态/版本/哈希核验和带完整 `WHERE` 条件的更新全部收进同一单写者事务；
  2. 导出侧用外层 `with _SINGLE_WRITER_LOCK:` 同时护住 `rw_immediate_tx` 和 `except` 里的目录回滚，直到磁盘与数据库重新一致才放锁。

### 坑 4：`heavy` 取消时把 `RUNNING → QUEUED` 一起回滚了 + 同进程恢复撞车
- **当时怎么踩的**：
  1. `recover_pending_heavy_jobs` 传了 `allow_recover_running=True`，允许抢夺任意 `RUNNING` 作业，结果普通领取刚进 runner，并发调一次恢复，两边都跑完并生成了两条 `Obs`；
  2. 后来在最终提交事务里检测到 `cancel_event.is_set()`，先执行了 `UPDATE status = 'QUEUED'`，紧接着 `raise RequestCancelledError`——结果 `with rw_immediate_tx` 捕获异常直接 `ROLLBACK`，把刚刚写好的 `QUEUED` 又回滚回了 `RUNNING`，作业永久卡死！
- **根治方案**：
  1. 进程内维护 `_ACTIVE_HEAVY_JOB_IDS`（受锁保护），恢复只复位不在活跃集里的真孤儿 `RUNNING`，结案强校验 `WHERE job_id = ? AND status = 'RUNNING' AND obs_id IS NULL`；
  2. 取消复位时在事务内 `UPDATE` 后设布尔标志**正常退出事务完成 `COMMIT`**，出了 `with` 块再 `raise RequestCancelledError`。
- **教训**：**永远记住在事务上下文管理器里 `raise` 会连同你在里面写的补偿 `UPDATE` 一起回滚！**

### 坑 5：在途旧观测绕过升版重评 + Stage B 连续升版留下无待办孤儿
- **当时怎么踩的**：
  1. v1 `official` 评测在途期间，工造司把仪器升版到了 v2（并把当时已入库的 v1 观测挂进待重评队列）；随后在途的 v1 跑完直接写成了 `VALID_PASS`，绕过了重评队列！
  2. 修完这条后，又遇到 v1→v2 重评在途、仪器又升到 v3：我们把迟到的 v2 标成了 `PENDING_REVALIDATION`，但因为原 v1 已经有一条指向 v3 的队列，就没给 v2 挂队列——结果 v3 重评完后，v2 永远孤零零卡在 `PENDING_REVALIDATION`！
- **根治方案**：
  1. `official` / `heavy` 入库进写锁后检查最新活跃版本，若 `active_ver > run_ver` 自动标 `PENDING_REVALIDATION` 并 1:1 插入待重评队列；
  2. Stage B 重评时若原观测已存在指向更高版本的 `PENDING` 队列，迟到的中间版重评记录直接落为 `SUPERSEDED_REVALIDATED`（绝不制造无待办的 `PENDING_REVALIDATION` 孤儿），且队列结案强制带 `AND target_version = ?`。

### 坑 6：`Path("").is_dir()` 在 Python 里永远返回 `True`！
- **当时怎么踩的**：`delivery_and_jobs.py` 里原本写着：
  ```python
  src_base = Path(str(node["retained_snapshot_abs_path"] or ""))
  if not src_base.is_dir():
      src_base = Path(str(node["worktree_abs_path"] or ""))
  ```
- **真实根因**：当节点还没生成快照（`retained_snapshot_abs_path` 为 `None` 或 `""`）时，`Path("")` 等价于当前工作目录 `Path(".")`，`is_dir()` 恒为 `True`！导致代码永远不会回退去读 `worktree_abs_path`，导出复现清单直接报错找不到工件！
- **根治方案**：先 `.strip()` 判断字符串非空，再构造 `Path(...)` 并判 `is_dir()`。

### 坑 7：自造跨 `cwd` 假归档 + 归档顺序颠倒 + 用期望值覆写说谎
- **当时怎么踩的**：
  1. 发现跨 `cwd` 会话调 `ws.attachSession()` 会报错后，想当然以为 `workspaceRegistry.archiveSession()` 也不能调，于是给跨 `cwd` 造了个 `localOnly: true` 假归档；
  2. 在 `disposeAll` 里先调 `archiveSession` 再调 `handle.dispose()`，导致宿主因为会话仍活跃直接拒绝归档；
  3. 紧接着 `recordSessionEnd({ ..., archived: shouldArchive })` 又拿期望值把 `archived` 强行改回 `true`，彻底掩盖了归档失败！
- **根治方案**：读了 `app.asar` 里 `dsh-workspace/lib/index.js` 真源码后豁然开朗——`archiveSession` 操作全局归档集，跨 `cwd` 也能调，只需**严格先 `await handle.dispose()`，再 `await archiveSession(sid)`，最后把真实结果 `Boolean(archRes?.archived)` 和 `archiveError` 写入遥测**。

### 坑 8：RC5 严格 JSON Schema 子集的隐蔽拒收点
- **当时怎么踩的**：以为把 `type: ["string", "null"]` 改成 `oneOf: [{ type: "string" }, { type: "null" }]` 就完了。
- **真实根因**：原 Schema 同层还挂着 `enum`（甚至含 `null`）或 `items`，直接改 `type` 会留下 `oneOf` 同层兄弟关键字，被 RC5 `ONE_OF_SIBLING_KEYWORDS` 拒收；另外给裸数组悄悄补 `{ type: 'string' }` 会扭曲数字/对象数组的真实契约。
- **根治方案**：在 `dsh_schema_adapter.js` 中把 `enum`（去 `null`）、`items`、`properties` 完整迁入 `oneOf` 主分支，剥离 `minLength/minimum/pattern` 等关键字并将约束摘要无损拼进 `description`，遇到重叠联合或裸数组缺 `items` 直接 Fail-Closed 抛错。

### 坑 9：`ctx.effect` 里多写了一个 `void`，异步卸载形同虚设
- **当时怎么踩的**：写了 `ctx.effect(() => () => { void cleanupAll().catch(() => {}) })`。
- **真实根因**：Cordis 4.1.0 的 `runDisposable` 会直接返回并等待 disposer 返回的 Promise；加了 `void` 就返回 `undefined`，插件卸载瞬间结束，子进程和子会话根本没等关完。
- **根治方案**：直接 `ctx.effect(() => () => cleanupAll(), ...)` 返回 Promise（内部各清理步骤各自 `try/catch` 保护）。

### 坑 10：为了省事留“双轨兜底”，反而埋下暗雷
- **当时怎么踩的**：拆出 `control_service.js` 和 `runtime_port.js` 后，在 `console_routes.js` 末尾保留了 40 行旧动作分发，在 `pair_lifecycle.js` 里留了 `orchestrator.host?.setSessionReadonly?.()`，在 `agent_session_host.js` 里留了二次 Preset 注册。
- **真实根因**：双轨导致两套代码逐渐漂移（例如新入口修复了某参数校验，旧兜底分支没修；或者关键能力缺失时因为 `?.` 静默跳过，70% 只读锁没加上还以为成功了）。
- **根治方案**：果断砍掉全部冗余兜底，走单轨契约，关键能力缺失（如 `setSessionReadonly`）直接抛 `RUNTIME_PORT_CONTRACT_ERROR`。

### 坑 11：并发提速后，L2 测试暴露竞态（12 轮挂 8 轮）
- **当时怎么踩的**：双池并发打开后，L2 剧本 2 测试里的 `assert.equal(worksRuns, 2)` 突然频繁报 `3 !== 2`。
- **真实根因**：剧本里探索者第 1 轮会调 `resumeBackground()`，而 `resumeBackground()` 按设计会复位熔断器计数。提速后工造司经常抢在 `resumeBackground()` 前跑完第 1 次，被复位后再跑 2 次才熔断，总计 3 次。
- **根治方案**：绝不为了迁就测试去改熔断业务政策，而是把测试断言锚定在 `resumeBackground()` 之后（验证复位后最多再跑 2 次即止血，绝不无限自旋）。修完后连续 15 轮（本机 10 轮 + 外部审阅 5 轮）100% 全绿。

### 坑 12：Windows 工具链与环境细节坑
- **PowerShell 双引号吞变量**：内联 `pwsh -Command "... $var ..."` 极易被外层 shell 吞掉 `$` 变量或搞乱引号；复杂脚本统一写 `.ps1` 文件用 `pwsh -NoProfile -File` 执行，或直接用 `python -c`。
- **ASAR 文件偏移 4 字节对齐**：手工解析 Electron `app.asar` 时，正文起始偏移必须是 `16 + Math.ceil(headerSize / 4) * 4`，直接用 `16 + headerSize` 会错位导致读出来的 `package.json` 乱码报错。
- **Desktop vs CLI 版本错位**：本机 Desktop 安装包（`D:\DshDesktop\resources\app.asar`）已是 RC5，而 PATH 上的全局 `dsh` CLI 可能是旧版 RC3，排查问题时务必核对实际执行的到底是哪一份运行时。

---

## 4. 不可触碰的 7 条工程红线（Do NOT Touch）

后续任何重构或新特性开发，**严禁破坏以下 7 条经过血泪教训确立的红线**：

1. **严禁删除 `agent_session_host.js` 中的 `_inheritParentPermissionState`**：否则 Windows headless 下子会话跌落 `workspace-write` 会导致 `pwsh` 报 `0xC0000142` 崩溃。
2. **严禁为探索者启用 `@deepseek-ai/dsh-compaction-tool-result-pruner`**：否则会破坏 37%/70% 物理上下文压力时钟的真实性。
3. **严禁在 `dsh_plugin/lib/client.js` 中 `require('@deepseek-ai/dsh-client-ui-primitives')`**：会触发 DSH 前端槽位崩溃（`slot entry crashed`）。
4. **严禁恢复 `eval_count >= 1` 才允许 37% 反思的旧门槛**：必须兼容零判定器纯数学推导/构造反例课题。
5. **严禁向运行中会话池广播实时干预指令**：统一走 `rulings/` 版本化裁决（`spec_revision`）+ `pause → abort_node → resume`。
6. **严禁在 `rw_immediate_tx` 写锁内执行耗时子进程计算**，也严禁在 `rw_immediate_tx` 异常退出前依赖锁内补偿写库（会被 `ROLLBACK` 吞掉）。
7. **严禁把探索者/盲审沙箱的过程态 `.md` 写回工作区**，所有过程状态必须走 SQLite 单真源；盲审沙箱必须保持四重 Fail-Closed，缺沙箱路径绝不允许回退主工作区。

---

## 5. 刻意暂缓的 3 项边界（请勿盲目补丁化）

我们在 `v0.2.0-alpha.1` 收官前，明确决定把以下 3 项**先放一放**，避免陷入无止境的对抗防御与过度工程化。接手者请知悉原因，除非业务需求明确变化，否则不建议优先折腾它们：

1. **跨独立 Python 进程的 `heavy` 作业互斥（数据库租约/心跳表）**：
   - 现状：长城按“一工作区一单写者 Python 内核”设计，同进程已有 `_ACTIVE_HEAVY_JOB_IDS` 互斥，且即便强行双进程并发，数据库最终条件提交（`WHERE status='RUNNING' AND obs_id IS NULL`）也已保住绝不双写观测。
   - 暂缓原因：引入跨进程租约、心跳续期与超时抢占会大幅增加状态机复杂度，而正常单宿主使用场景下几乎不会触发。
2. **Stage 3 终签哈希计算拆出全局写锁**：
   - 现状：终签时在单写者事务内实时重算 `final_delivery/` SHA-256。
   - 暂缓原因：整个课题只在结项最后一秒执行 1 次，交付包通常几百 KB、算哈希仅几毫秒，此时探索者已全部停工、纯只读快照也不受阻，没必要为了几毫秒搞不可变版本目录与二段锁。
3. **强制迁移到原生 `@deepseek-ai/schemastery` 以支持 `--dump-config-schema`**：
   - 现状：`config.js` 采用零依赖 Standard Schema v1，已在真实 RC5 CLI 正常装载并校验 YAML 配置，仅 `--dump-config-schema` 静态投影会提示非原生 Schemastery。
   - 暂缓原因：保持 `dsh_plugin/` 零第三方 npm 依赖、开箱即用与独立单测体验。若未来正式向 DSH 插件市场分发、需要宿主自动生成可视化配置表单，再按 `dsh_development_handbook.md §3.2` 路线 A 切换即可。

---

## 6. 给下一任接手者的建议优先级

如果从 `v0.2.0-alpha.1` 继续往下推进，最值得投入的 3 件事（按价值排序）：

1. **真实 DSH Desktop 端到端实跑一次完整小课题**：
   - 重点验收：Desktop 挂载启用、右侧栏指挥舱面板渲染、点击跨 `cwd` 探索者/伴随/盲审会话能否通过 `uiWorkspace.openSession` 丝滑打开、暂停/恢复/强停后子进程是否零残留。
2. **前端指挥舱 (`dsh_plugin/lib/client.js`) 模块化与视觉交互重塑**：
   - 目前后端和插件底座已经非常干净，最大的工程与体验短板就在 1,200+ 行无构建链手写 JSX 的 `client.js`（以及借鉴 `SuperAgent` 范式升级主控交互体验）。
3. **容器/资源限额强沙箱（Docker / WSL2 + cgroups）与受控对照实验**：
   - 解决“探索者跑失控脚本拖死宿主机”的老大难安全债，然后在零工程事故基线下，做一次干净的“长城多智能体 vs 单 Agent 裸跑”科研对照实验，真正检验制度净收益。

---

## 7. 一分钟快速接手验证命令

在仓库 `greatwall-v6up/` 目录下执行：

```powershell
# 1. Python 54 项全量单测、并发一致性/真取消与架构防腐门禁
python -m unittest discover -s tests -p "test_*.py"

# 2. Node 39 项全量单测、RC5 Schema 校验与 L2 假模型全链路
Set-Location dsh_plugin
npm test

# 3. 7 项环境与 32 窄工具跨层契约一键体检
npm run doctor
```

祝下一阶段的研发顺利、克制、少踩坑！
