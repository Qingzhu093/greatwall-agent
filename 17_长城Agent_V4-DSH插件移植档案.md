# 长城 Agent V4.2 DSH 插件移植档案（`dsh-greatwall-agent`）

> **文档定位**：记录 `dsh-greatwall-agent` 4.2.0 的物理存放位置、包结构与文件职责、Antigravity → DeepSeek Harness (DSH) 的三项宿主能力映射、实测验证证据、发布分发地址，以及日常维护命令。本文是 [`16_长城Agent_V4插件文件清单与DSH_Codex跨平台移植档案.md`](./16_长城Agent_V4插件文件清单与DSH_Codex跨平台移植档案.md) 的“已落地版本”：16 号记录的是移植**方案**，本档案记录的是移植**成品**。

---

## 一、物理存放位置（源码 / 安装 / 发布三处）

1. **Git 源码主仓库路径（设计与发布源）**：
   - 路径：[`plugins/dsh-greatwall-agent/`](./plugins/dsh-greatwall-agent/)
   - 说明：原 Antigravity 插件 [`plugins/greatwall-agent/`](./plugins/greatwall-agent/) **保持只读**，逐字节复制进本包的 `greatwall-agent/` 子目录。
2. **DSH 本机生效安装路径（Electron `desktop` profile）**：
   - profile 清单：`C:\Users\wangy\.dsh\profiles\desktop\package.json`
   - 实际解析路径：`C:\Users\wangy\.dsh\profiles\desktop\node_modules\dsh-greatwall-agent`（`link:` 指向第 1 条路径）
   - 实测记录：`"dsh-greatwall-agent": "link:D:/Documents/deepseek harness/长城Agent_框架设计/plugins/dsh-greatwall-agent"`，并已加入 `dsh.profile.bundles`。
3. **发布后远端位置（本轮尚未发布）**：
   - GitHub 仓库：<https://github.com/Qingzhu093/dsh-greatwall-agent>
   - npm 包：`dsh-greatwall-agent@4.2.0`（`publishConfig.access: public`）
   - 插件市场索引（计划托管于 GitHub Pages）：`https://qingzhu093.github.io/dsh-greatwall-agent/market/index.json`

---

## 二、包结构与各文件职责

```text
dsh-greatwall-agent/
├── package.json                   # [宿主壳] npm 清单：engines、dsh.bundle、peerDependencies、files、icon、scripts（含 prepack）
├── cordis.patch.yml               # [宿主壳] bundle 层：一行 insert（id: greatwall-agent），不写 config
├── lib/
│   ├── index.js                   # [宿主壳] 宿主入口：挂 MCP、注册技能、安装清洁室门禁
│   ├── gate.js                    # [宿主壳] 清洁室门禁：hook_gate.py 的三条规则 + DSH 字段适配
│   └── skillpack.js               # [宿主壳] SKILL.md 发现/解析/校验与 ctx.skills 注册
├── locale/{zh,en}.json            # [宿主壳] 市场/设置页标题与描述（meta.title / meta.description）
├── icon.svg                       # [宿主壳] 插件图标（与 greatwall-agent/assets/logo.svg 同 SHA-256）
├── core-manifest.sha256           # [证据] 18 个内核文件 SHA-256
├── tools/
│   ├── clean-pycache.mjs          # [证据] prepack：清理 __pycache__/*.pyc，避免缓存进 tarball
│   ├── make-core-manifest.mjs     # [证据] 生成 core-manifest.sha256
│   └── verify-core.mjs            # [证据] 校验内核逐字节一致（CI/人工均可）
├── greatwall-agent/               # [跨平台内核] 原 Antigravity 插件树逐字节副本（18 文件）
│   ├── bin/gw_mcp_server.py       #   9 工具 JSON-RPC 2.0 stdio MCP 服务
│   ├── bin/hook_gate.py           #   PreToolUse 门禁脚本（规则对照物）
│   ├── lib/{sandbox,archive,evaluator,engine}.py
│   ├── skills/greatwall-campaign/SKILL.md   # 四阶段作业手册（技能正文来源）
│   ├── rules/AGENTS.md            #   常驻铁律（需手工复制，不自动装载）
│   ├── agents/gw-{distiller,explorer,auditor}.md  # 子智能体提示词（不自动注册）
│   ├── tests/test_plugin_e2e.py   #   10 项端到端验收
│   └── plugin.json / mcp_config.json / hooks.json / README.md / assets/logo.svg
├── market/
│   ├── index.json                 # [分发] DSH 插件市场索引（format 1；发布前含时间戳占位符；不随 npm tarball）
│   └── icons/dsh-greatwall-agent.svg
├── .release/verify-index.mjs      # [分发] 市场索引离线校验（--strict 用于发布构建）
└── docs/
    ├── INSTALL.md                 # 安装、验证、排障、卸载
    ├── ARCHITECTURE.md            # 文件级移植映射与适配细节
    ├── BUG_REPORT.md              # 原 Python 内核统一缺陷报告（由审计任务产出，见第七节）
    └── audit/                     # 审计原始证据（e2e 日志、哈希基线、MCP 探测输出等）
```

### 核心文件速查表

| 文件路径 | 层级 | 一句话功能说明 | 移植时是否修改 |
| :--- | :---: | :--- | :---: |
| [`greatwall-agent/bin/gw_mcp_server.py`](./plugins/dsh-greatwall-agent/greatwall-agent/bin/gw_mcp_server.py) | 内核层 | JSON-RPC 2.0 stdio MCP 服务，向 DSH 暴露 9 个 `gw_*` 工具（名称、参数、返回值不变）。 | **0 修改直接复用** |
| [`greatwall-agent/lib/`](./plugins/dsh-greatwall-agent/greatwall-agent/lib/) | 内核层 | `sandbox`（路径牢笼/Job Object/AST 替换）、`archive`（L0-L2 档案）、`evaluator`（AST 审计/HMAC 评测）、`engine`（状态机/60 步锁/终局编译）。 | **0 修改直接复用** |
| [`greatwall-agent/bin/hook_gate.py`](./plugins/dsh-greatwall-agent/greatwall-agent/bin/hook_gate.py) | 门禁层 | 原始 `PreToolUse` 门禁脚本；规则与拒绝文案的**对照物**，随包保留。 | **0 修改直接复用** |
| [`lib/gate.js`](./plugins/dsh-greatwall-agent/lib/gate.js) | 宿主壳 | 同一套三条规则的 DSH 工具守卫；新增 `file_path`/`command` 等 DSH 字段适配。 | 新写（宿主适配） |
| [`lib/index.js`](./plugins/dsh-greatwall-agent/lib/index.js) | 宿主壳 | `apply()`：`ctx.plugin(McpClient)` + `ctx.skills.register()` + `ctx.tools.guard()`，路径全部从 `import.meta.url` 解析。 | 新写（宿主适配） |
| [`lib/skillpack.js`](./plugins/dsh-greatwall-agent/lib/skillpack.js) | 宿主壳 | 读取 `SKILL.md`、极简 frontmatter 解析、名字/目录一致性校验、注册到 `ctx.skills`。 | 新写（宿主适配） |
| [`cordis.patch.yml`](./plugins/dsh-greatwall-agent/cordis.patch.yml) | 宿主壳 | bundle 层只含一行 `insert`；MCP/技能/门禁都由 `apply()` 交付。 | 新写（宿主适配） |
| [`greatwall-agent/rules/AGENTS.md`](./plugins/dsh-greatwall-agent/greatwall-agent/rules/AGENTS.md)、[`greatwall-agent/skills/`](./plugins/dsh-greatwall-agent/greatwall-agent/skills/)、[`greatwall-agent/agents/`](./plugins/dsh-greatwall-agent/greatwall-agent/agents/) | 提示层 | 铁律、四阶段手册、三份子智能体提示词；技能由插件注册，规则需手工复制，子智能体不自动注册。 | **0 修改直接复用**（技能仅前置一段工具名映射注记） |
| [`tools/verify-core.mjs`](./plugins/dsh-greatwall-agent/tools/verify-core.mjs)、[`core-manifest.sha256`](./plugins/dsh-greatwall-agent/core-manifest.sha256) | 证据层 | “内核未改一行”的机器可校验证明（18 文件 SHA-256）。 | 新写（发布证据） |
| [`tools/clean-pycache.mjs`](./plugins/dsh-greatwall-agent/tools/clean-pycache.mjs) | 证据层 | `prepack` 清理 `greatwall-agent/` 下的 `__pycache__`/`*.pyc`；配合 MCP 子进程的 `PYTHONDONTWRITEBYTECODE=1`，保证缓存不进 npm 包。 | 新写（发布证据） |

---

## 三、三项宿主能力映射（Antigravity → DSH）

| 宿主能力 | Antigravity 原实现 | DSH 新实现 | 代码位置 | 实测状态 |
| :--- | :--- | :--- | :--- | :--- |
| MCP stdio 服务 | `mcp_config.json`：`command`=`python.exe` 绝对路径，`args`=[脚本绝对路径]，`env.PYTHONUTF8=1` | `@deepseek-ai/dsh-mcp-client` 由 `lib/index.js` 在 `apply()` 内 `ctx.plugin()` 挂载；`command`=`pythonPath`，`args`=[从 `import.meta.url` 解析的脚本路径]，env 增加 `PYTHONIOENCODING=utf-8`、`PYTHONUNBUFFERED=1`、`PYTHONDONTWRITEBYTECODE=1`；`toolCallTimeoutMs=600000`、`failOnStartupError=false`、10 次有限重连 | [`lib/index.js`](./plugins/dsh-greatwall-agent/lib/index.js) | ✅ 9 个工具在 `Tool.listTools` 中可见 |
| 技能 | `skills/greatwall-campaign/SKILL.md` 磁盘目录 | `ctx.skills.register()` 运行时注册；正文 = 原 `SKILL.md` 逐字 + 仅前置工具名映射注记；`provider: dsh-greatwall-agent` | [`lib/skillpack.js`](./plugins/dsh-greatwall-agent/lib/skillpack.js)、[`lib/index.js`](./plugins/dsh-greatwall-agent/lib/index.js) | ✅ 安装验证时技能可用 |
| 清洁室门禁 | `hooks.json` 的 `PreToolUse`（matcher `read_file\|write_file\|edit_file\|run_command`）+ `bin/hook_gate.py`（stdin JSON → `{"decision":"deny","reason"}`） | `ctx.tools.guard(execution => reason \| undefined)`；四条固定拒绝文案逐字节一致，三条规则同序 | [`lib/gate.js`](./plugins/dsh-greatwall-agent/lib/gate.js) | ✅ 四类越界调用均被实拦 |
| 常驻规则 | `rules/AGENTS.md` | **未迁移为运行时能力**：原文件随包，按原说明复制到攻关工作区或全局规则 | `greatwall-agent/rules/AGENTS.md` | — （刻意不迁移） |
| 命名子智能体 | `agents/gw-*.md`（Antigravity 命名子智能体清单） | **未迁移为运行时能力**：DSH 没有同名注册表；三份提示词原样随包，可手工作为子智能体提示词 | `greatwall-agent/agents/` | — （刻意不迁移） |

> 后两项是**刻意不迁移为运行时特性**，不是遗漏，也没有用 DSH 不存在的机制去假装实现。详见 [`docs/ARCHITECTURE.md`](./plugins/dsh-greatwall-agent/docs/ARCHITECTURE.md) 第三、五、七节。

---

## 四、验证证据（2026-11-07，`desktop` profile）

环境：DSH `0.2.2-rc.1`、Node `24.20.0`、Python `3.14.7`，Windows + PowerShell 7。

| # | 证据 | 命令 / 调用 | 实测结果 |
| :---: | :--- | :--- | :--- |
| 1 | 安装生效 | 读 `C:\Users\wangy\.dsh\profiles\desktop\package.json` | `link:` 依赖 + `dsh.profile.bundles` 含 `dsh-greatwall-agent` |
| 2 | 配置行 | `cordis_inspect_query(host, Config, listConfigs, {name:"dsh-greatwall-agent"})` | `id: include:greatwall-agent`、`patchId: greatwall-agent`、`status: schema`、`acceptsMissing: true`；默认 `pythonPath=python`、`cleanroomGate=true` |
| 3 | 9 个工具 | `cordis_inspect_query(host, Tool, listTools)` | 9 条 `mcp__greatwall-agent__gw_*` |
| 4 | MCP 桥连通 | `list_mcp_resources(server="greatwall-agent")` | `{"resources": []}`（该服务无 resources 能力，有回复即连通） |
| 5 | MCP 协议 | 手工 stdio 探测 `initialize` / `tools/list` | `protocolVersion 2024-11-05`、`serverInfo.name=greatwall-agent`、`version=4.2.0`；`tools/list` 返回 9 个 |
| 6 | 内核逐字节 | `node plugins/dsh-greatwall-agent/tools/verify-core.mjs` | `OK: 18 core files match core-manifest.sha256 (byte-identical Antigravity tree)` |
| 7 | 端到端验收 | `python -W default plugins/dsh-greatwall-agent/greatwall-agent/tests/test_plugin_e2e.py` | 本轮 `Ran 10 tests in 2.882s / OK`；归档日志 `docs/audit/e2e_run.log` 记录 `2.990s` |
| 8 | 门禁实拦 | DSH 会话内四类越界调用 | `.kernel_vault`、`shared_readonly` 终端重定向、`../slot_*`、双槽位命令全部 deny；普通命令 allow |
| 9 | 市场索引 | `node plugins/dsh-greatwall-agent/.release/verify-index.mjs` | 待发布阶段通过（时间戳占位符给 warning）；`--strict` 用于发布构建 |

验证证据的原始文件在 [`plugins/dsh-greatwall-agent/docs/audit/`](./plugins/dsh-greatwall-agent/docs/audit/)：`e2e_run.log`（10 项验收日志）、`orig_tree_hashes_before.txt`（内核哈希基线）、`mcp_conformance.log` 与 `mcp_conformance_result.json`（MCP 协议一致性探测，由审计任务产出）。

> 本机 PATH 上的独立 `dsh` CLI 自报 `0.1.5-rc.1`，**不满足**本包 `engines.dsh`，且对 Electron 托管的 `desktop` profile 任何 `dsh plugin` / `--dump-config` 调用都会报 `profile "desktop" is managed exclusively by the Electron application`。因此上表中的安装与验证都通过 Desktop 内的 DSH `0.2.2-rc.1` 完成。

---

## 五、发布与分发

| 项目 | 值 | 状态 |
| :--- | :--- | :--- |
| npm 包名 / 版本 | `dsh-greatwall-agent` / `4.2.0` | 未发布 |
| `engines.dsh` | `>=0.2.2-rc.1 <0.3.0-0` | 已写入 `package.json`；市场索引同值 |
| `engines.node` | `^22.19.0 \|\| >=24.0.0` | 已写入 |
| GitHub 仓库 | `https://github.com/Qingzhu093/dsh-greatwall-agent` | 未创建 |
| 插件市场索引 | `market/index.json`（`format: 1`，含 `market/icons/`） | 已就绪；`publishTimestamp` 仍为占位符 |
| 计划托管地址 | `https://qingzhu093.github.io/dsh-greatwall-agent/market/index.json` | 未上线（未验证可访问） |
| 许可证 | MIT（`LICENSE`，版权 Great Wall Agent Contributors） | 已就绪 |

> `market/`、`.release/` 与 `docs/` 不在 `package.json` 的 `files` 白名单内：npm tarball 只含运行所需文件，市场索引与文档随源码仓库分发（npm 页面上的文档链接指向 GitHub）。

三种安装通道（详见 [`docs/INSTALL.md`](./plugins/dsh-greatwall-agent/docs/INSTALL.md)）：

```powershell
# A. CLI 托管 profile：从 npm 安装（发布后）
dsh plugin --profile <profile-name> add dsh-greatwall-agent

# B. CLI 托管 profile：从本地目录 link 安装
dsh plugin --profile <profile-name> add 'D:\Documents\deepseek harness\长城Agent_框架设计\plugins\dsh-greatwall-agent'

# C. DSH Desktop：在应用内插件管理入口安装（本机验证通道；desktop profile 由 Electron 独占管理）
```

市场通道：托管后按 DSH 官方流程 **Plugins → More → Custom plugin markets → Discover → Add index source** 添加索引 URL；DSH 不自带中心市场，索引必须由发布方自行托管。

---

## 六、日常维护命令速查

```powershell
# 0) 进入设计仓库根目录
Set-Location 'D:\Documents\deepseek harness\长城Agent_框架设计'
```

### 6.1 内核逐字节校验（每次改动后必跑）

```powershell
node 'plugins\dsh-greatwall-agent\tools\verify-core.mjs'
# 预期：OK: 18 core files match core-manifest.sha256 (byte-identical Antigravity tree)
```

### 6.2 端到端验收（约 3 秒）

```powershell
$env:PYTHONUTF8 = '1'
python -W default 'plugins\dsh-greatwall-agent\greatwall-agent\tests\test_plugin_e2e.py'
# 预期：Ran 10 tests in ~3s / OK
```

### 6.3 本地安装自测（不污染 `desktop` profile）

```powershell
# 用一个 CLI 管理的独立 profile 做 link 安装与冒烟（需要 dsh CLI 满足 engines.dsh 且 PATH 有 pnpm）
dsh plugin --profile gwtest add 'D:\Documents\deepseek harness\长城Agent_框架设计\plugins\dsh-greatwall-agent'
dsh --profile gwtest --dump-config          # 应出现 dsh-greatwall-agent 层与 greatwall-agent 行
dsh --profile gwtest --help                 # 确认 profile 可启动（具体 surface 以模板为准）
dsh plugin --profile gwtest remove dsh-greatwall-agent
```

### 6.4 npm 打包检查

```powershell
Set-Location 'plugins\dsh-greatwall-agent'
npm pack --dry-run                        # 先由 prepack 清理 Python 缓存，再列出 tarball 内容
# 检查 tarball 含：package.json、cordis.patch.yml、lib/*.js、locale/*.json、icon.svg、
#   core-manifest.sha256、tools/*.mjs、greatwall-agent/bin/gw_mcp_server.py、
#   greatwall-agent/lib/*.py、greatwall-agent/skills/**、README.md、README.en.md、LICENSE
# 且不含 greatwall-agent/lib/__pycache__ 等缓存（.gitignore 已排除）
```

### 6.5 市场索引更新与校验

索引由人工维护（无生成器）。发布时把占位符换成真实 Unix 秒，再跑严格校验：

```powershell
$ts = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$p  = 'plugins\dsh-greatwall-agent\market\index.json'
(Get-Content $p -Raw).Replace('__PUBLISH_TIMESTAMP__', "$ts") | Set-Content $p -Encoding utf8

node 'plugins\dsh-greatwall-agent\.release\verify-index.mjs'           # 日常：允许占位符，给 warning
node 'plugins\dsh-greatwall-agent\.release\verify-index.mjs' --strict  # 发布：占位符直接失败
```

### 6.6 从原 Antigravity 插件同步内核（仅当原插件升级时）

```powershell
# 只复制内核树，排除 Python 缓存；robocopy 退出码 0/1 都属成功（1 = 复制了文件）
robocopy 'plugins\greatwall-agent' 'plugins\dsh-greatwall-agent\greatwall-agent' /E /XD '__pycache__' /XF '*.pyc' /NFL /NDL /NJH /NJS

# 重新生成清单并校验；确需同步时，这一步必须与 verify:core 一起完成
node 'plugins\dsh-greatwall-agent\tools\make-core-manifest.mjs'
node 'plugins\dsh-greatwall-agent\tools\verify-core.mjs'
python -W default 'plugins\dsh-greatwall-agent\greatwall-agent\tests\test_plugin_e2e.py'
```

> 顺序不可颠倒：先复制、再重建清单、再校验、最后跑 e2e。未经 `make-core-manifest` 的复制会让 `verify-core.mjs` 失败——这正是它存在的意义。

---

## 七、缺陷与审计入口

- **统一缺陷报告**：[`plugins/dsh-greatwall-agent/docs/BUG_REPORT.md`](./plugins/dsh-greatwall-agent/docs/BUG_REPORT.md)（见 BUG_REPORT.md（本轮生成））。
- **原则：报告而不修复**。`greatwall-agent/` 必须保持逐字节一致，因此原 Python 内核的任何缺陷都只记录、不就地修改；修复应回到 `plugins/greatwall-agent/` 主仓库进行，再按 6.6 同步。
- **原始审计证据**：[`docs/audit/`](./plugins/dsh-greatwall-agent/docs/audit/)，包含 e2e 日志、内核哈希基线、MCP 协议一致性探测与 stdout/stderr 抓取。

---

## 八、与 16 号档案的口径校正

16 号档案写于移植方案阶段，与落地成品存在少量差异，以真实文件为准：

| 16 号档案的表述 | 实际落地 |
| :--- | :--- |
| 原插件目录树写作 `.antigravity-plugin/plugin.json`、`mcp.json`、`hooks/hooks.json` | 实际原插件树是根目录的 `plugin.json`、`mcp_config.json`、`hooks.json`（无 `.antigravity-plugin/`、无 `hooks/` 子目录） |
| “移植到 DSH 需要 3 步配置”：改配置挂 MCP、复制 Skill 到 `~/.dsh/skills/`、复制 `AGENTS.md` | 前两步已由插件自动化（`apply()` 挂 MCP + `ctx.skills.register()` 注册技能）；**`AGENTS.md` 仍需手工复制**，第三步不变 |
| 技能“含 9 大工具调用 SOP” | 技能正文实际写的是“8 个原生工具”，覆盖 8 个；MCP 实际暴露 9 个（`gw_lineage_control` 只在工具描述中） |
| 给出 `~/.dsh/config.json` / 工作区 `.dsh/mcp.json` 的 `mcpServers` 配置示例 | DSH 实际以 profile + bundle patch 组织插件；本包用 `cordis.patch.yml` 一行 bundle 层 + `apply()` 动态挂载，无需手写 `mcpServers` |

---

## 九、许可证

MIT。原 `greatwall-agent` 插件以同一许可证随包分发，版权归 Great Wall Agent Contributors；本包新增的宿主适配代码（`lib/*.js`、`tools/*.mjs`、`market/`、文档）同属 MIT。
