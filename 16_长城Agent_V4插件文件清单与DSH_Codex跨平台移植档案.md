# 长城 Agent V4.2 插件文件清单与 DSH / Codex 跨平台移植档案

> **文档定位**：记录 `greatwall-agent` V4.2 插件的物理存放路径、各模块文件职责，以及如何利用“内核与宿主壳层解耦”架构快速移植到 **DeepSeek Harness (DSH)** 与 **Codex CLI**。

---

## 一、物理存放位置（双端同步）

当前插件在本地维护了两份完全同步的目录：

1. **Git 源码主仓库路径（用于版本管理与跨平台打包）**：
   - 路径：[`d:\Documents\deepseek harness\长城Agent_框架设计\plugins\greatwall-agent\`](file:///d:/Documents/deepseek%20harness/长城Agent_框架设计/plugins/greatwall-agent/)
   - 远端仓库：`https://github.com/Qingzhu093/greatwall-agent.git` (`main` 分支)
2. **Google Antigravity 全局生效安装路径（IDE 实时加载）**：
   - 路径：[`C:\Users\wangy\.gemini\config\plugins\greatwall-agent\`](file:///C:/Users/wangy/.gemini/config/plugins/greatwall-agent/)

---

## 二、插件目录结构与各文件职责说明

在架构设计上，插件被严格切分为 **“100% 跨平台通用内核 (`lib/` + `bin/gw_mcp_server.py`)”** 与 **“宿主平台适配薄壳 (Manifest / Skill / Rule / Hook)”** 两层：

```text
greatwall-agent/
├── .antigravity-plugin/
│   └── plugin.json                 # [AGY 宿主壳] Antigravity 插件元数据清单
├── mcp.json                        # [通用/AGY] 标准 Stdio MCP 服务器启动配置
├── hooks/
│   └── hooks.json                  # [AGY 宿主壳] PreToolUse 钩子挂载声明
├── rules/
│   └── AGENTS.md                   # [通用/AGY] 核心工程铁律（可直接复用于 DSH / Codex）
├── skills/
│   └── greatwall-campaign/
│       └── SKILL.md                # [通用/AGY] 全流程编排技能手册（含 9 大工具调用SOP）
├── bin/
│   ├── gw_mcp_server.py            # [跨平台核心] 零依赖纯 Python Stdio MCP 服务端（暴露 9 个 gw_* 工具）
│   └── hook_gate.py                # [跨平台核心] 毫秒级清洁室路径越界与只读区防篡改拦截脚本
├── lib/
│   ├── __init__.py                 # [跨平台核心] Python 包初始化导出
│   ├── sandbox.py                  # [跨平台核心] 跨进程文件锁、路径监牢、64位 Job Object 进程树强杀、AST 微创替换与 diff 生成
│   ├── evaluator.py                # [跨平台核心] AST 法医级反作弊/防泄漏/过时模型拦截、跨分支差分互测、错题热勘误与 HMAC 签名评测器
│   ├── archive.py                  # [跨平台核心] 三级按需加载档案馆、PRIMITIVES_API 零源码签名提取、五件套遗产校验与撤回树
│   └── engine.py                   # [跨平台核心] 顶层状态机、EDA 静态数据探针、M 候选基线竞技、60步深挖锁、软清栈/硬分叉与终局打包
└── tests/
    └── test_plugin_e2e.py          # [跨平台验收] 10 大端到端与对抗测试套件（2.75秒跑完，零第三方依赖）
```

### 核心文件速查表

| 文件路径 | 层级 | 一句话功能说明 | 移植时是否需要修改 |
| :--- | :---: | :--- | :---: |
| [`lib/sandbox.py`](file:///d:/Documents/deepseek%20harness/长城Agent_框架设计/plugins/greatwall-agent/lib/sandbox.py) | 内核层 | 提供 `InterProcessFileLock`、`SandboxPathJail`、64位 Windows Job Object 强杀、无 `.git` 清洁室导出与支持类内方法的 `surgical_replace_block`。 | **0 修改直接复用** |
| [`lib/evaluator.py`](file:///d:/Documents/deepseek%20harness/长城Agent_框架设计/plugins/greatwall-agent/lib/evaluator.py) | 内核层 | 提供 `ASTCodeInspector`（防泄漏、禁过时模型、禁手搓轮子、$\mathcal{A}_{\text{data}}$ 完整性检查）与 `IsolatedEvaluator`（HMAC 防伪收据、差分互测、错题勘误平反）。 | **0 修改直接复用** |
| [`lib/archive.py`](file:///d:/Documents/deepseek%20harness/长城Agent_框架设计/plugins/greatwall-agent/lib/archive.py) | 内核层 | 管理 `shared_readonly/archive/`，自动提取 `PRIMITIVES_API.md`、统计跨血统真实引用、验证 `BarrierProof` 反例脚本、自动打共性死因补丁。 | **0 修改直接复用** |
| [`lib/engine.py`](file:///d:/Documents/deepseek%20harness/长城Agent_框架设计/plugins/greatwall-agent/lib/engine.py) | 内核层 | 串联 Phase 0 ~ Phase 4 全周期状态机、WAL 崩溃恢复、60 步内省室契约与 `final_delivery/` 五件套防吹牛编译。 | **0 修改直接复用** |
| [`bin/gw_mcp_server.py`](file:///d:/Documents/deepseek%20harness/长城Agent_框架设计/plugins/greatwall-agent/bin/gw_mcp_server.py) | 接口层 | 标准 JSON-RPC 2.0 Stdio MCP Server，向任何支持 MCP 的宿主暴露 `gw_init_campaign` 等 9 个工具。 | **0 修改直接复用** |
| [`bin/hook_gate.py`](file:///d:/Documents/deepseek%20harness/长城Agent_框架设计/plugins/greatwall-agent/bin/hook_gate.py) | 门禁层 | 拦截探索节点偷看 `.kernel_vault`、篡改 `shared_readonly/` 或跨槽位偷看 `../slot_*`。 | 仅需对齐宿主的 Hook 输入 JSON 字段名 |
| [`rules/AGENTS.md`](file:///d:/Documents/deepseek%20harness/长城Agent_框架设计/plugins/greatwall-agent/rules/AGENTS.md) & [`SKILL.md`](file:///d:/Documents/deepseek%20harness/长城Agent_框架设计/plugins/greatwall-agent/skills/greatwall-campaign/SKILL.md) | 提示层 | 规范主控 Agent 与探索节点的行为准则与标准调用流程。 | **95% 直接复用**（仅改目录头配置） |

---

## 三、如何移植到 DeepSeek Harness (DSH)

DSH 原生支持 **Stdio MCP Server**、**Skills (`SKILL.md`)** 与 **项目级/全局级 `AGENTS.md` 规则**。因此移植到 DSH 时，`lib/` 与 `bin/gw_mcp_server.py` **一行代码都不用改**，只需做以下 3 步配置封装：

### 1. 挂载 MCP Server (`gw_mcp_server.py`)
在 DSH 的配置文件（如 `~/.dsh/config.json` 或工作区 `.dsh/mcp.json`）中添加 `greatwall-agent` 服务：

```json
{
  "mcpServers": {
    "greatwall-agent": {
      "command": "python",
      "args": [
        "d:/Documents/deepseek harness/长城Agent_框架设计/plugins/greatwall-agent/bin/gw_mcp_server.py"
      ],
      "env": {
        "PYTHONUTF8": "1"
      }
    }
  }
}
```
> **说明**：挂载后，DSH 主控及内部 Teamwork 子智能体即可直接调用 `gw_init_campaign`、`gw_lock_distillation`、`gw_allocate_slot`、`gw_surgical_replace`、`gw_evaluate_slot`、`gw_submit_legacy`、`gw_lineage_control`、`gw_archive_query`、`gw_compile_delivery` 共 9 个工具。

### 2. 复制 Skill 与 Rule 到 DSH 目录
- 将 [`skills/greatwall-campaign/`](file:///d:/Documents/deepseek%20harness/长城Agent_框架设计/plugins/greatwall-agent/skills/greatwall-campaign/) 文件夹复制到 DSH 的技能目录（如 `~/.dsh/skills/greatwall-campaign/`）；
- 将 [`rules/AGENTS.md`](file:///d:/Documents/deepseek%20harness/长城Agent_框架设计/plugins/greatwall-agent/rules/AGENTS.md) 放入攻关项目根目录或合入 DSH 全局规则。

### 3. 适配 DSH 的智能体团队 (Teamwork) 并发槽位
- 在 DSH 中启动并行探索节点时，主控先调用 `gw_allocate_slot` 获取独立清洁室路径 `worktrees/slot_xx_node_yy/`，再将该子目录作为 DSH 子会话的工作目录传入，天然实现多节点并发隔离。

---

## 四、如何移植到 OpenAI Codex CLI

Codex CLI 同样支持 **MCP Server (`config.toml`)**、**`AGENTS.md` 指令文件**以及本地命令行脚本调用。移植步骤如下：

### 1. 在 Codex `~/.codex/config.toml` 中注册 MCP Server
在 Codex 的全局配置文件 `~/.codex/config.toml` 中加入：

```toml
[mcp_servers.greatwall_agent]
command = "python"
args = ["d:/Documents/deepseek harness/长城Agent_框架设计/plugins/greatwall-agent/bin/gw_mcp_server.py"]
env = { PYTHONUTF8 = "1" }
```

### 2. 挂载 `AGENTS.md` 与 `SKILL.md`
- Codex 原生识别全局 `~/.codex/AGENTS.md` 以及工作区下的 `AGENTS.md`（或通过 `skills/` 目录发现技能）：
  - 直接将 [`rules/AGENTS.md`](file:///d:/Documents/deepseek%20harness/长城Agent_框架设计/plugins/greatwall-agent/rules/AGENTS.md) 与 [`skills/greatwall-campaign/SKILL.md`](file:///d:/Documents/deepseek%20harness/长城Agent_框架设计/plugins/greatwall-agent/skills/greatwall-campaign/SKILL.md) 复制到 `~/.codex/skills/greatwall-campaign/` 或目标赛题工作区根目录。

### 3. （可选）为不支持 MCP 的纯 CLI 模式增加单行 CLI 入口
如果部分内测用户的旧版环境未开启 MCP，只需在 `bin/` 下新建一个 20 行的薄包装脚本 `gw_cli.py`，直接调用 [`bin/gw_mcp_server.py`](file:///d:/Documents/deepseek%20harness/长城Agent_框架设计/plugins/greatwall-agent/bin/gw_mcp_server.py#L317-L420) 中的 `handle_tool_call(tool_name, json_args)`，即可通过终端命令 `python gw_cli.py gw_evaluate_slot --slotId slot_01` 完成所有操作。

---

## 五、日常维护与同步命令速查

每次修改仓库中的插件源码后，在 PowerShell 7 (`pwsh`) 中执行以下两条命令即可完成 **端到端自检 + 同步到全局插件目录**：

```powershell
# 1. 运行 10 项全链路对抗验收测试（约 2.7 秒）
python -W default 'd:\Documents\deepseek harness\长城Agent_框架设计\plugins\greatwall-agent\tests\test_plugin_e2e.py'

# 2. 同步至 Antigravity 全局插件目录
Copy-Item -Path 'd:\Documents\deepseek harness\长城Agent_框架设计\plugins\greatwall-agent\*' -Destination 'C:\Users\wangy\.gemini\config\plugins\greatwall-agent' -Recurse -Force
```
