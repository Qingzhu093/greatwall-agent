# 参与贡献 GreatWall Agent（CONTRIBUTING）

感谢你关注 **GreatWall Agent（长城）**！

如 [`ARCHITECTURE.md §1.5`](./ARCHITECTURE.md#15-开源初心apache-20--dco) 所说，本项目目前是一个处于 **`v0.1-alpha`** 早期实验阶段的开源科研基座，发起者为数学系背景、工程能力有限，代码中存在不少技术债与尚未解开的核心问题。无论你想**修一个小 Bug、拆分上帝文件、重做 UI、加固容器沙箱、接入新学科仪器/技能，还是单纯提一个尖锐的 Issue 讨论多智能体科研机制**，都非常欢迎！

---

## 一、贡献前建议阅读

建议花 10–15 分钟按以下顺序快速对齐上下文：
1. [`README.md`](./README.md) — 了解项目定位、目录布局与 DSH 挂载方式；
2. [`ARCHITECTURE.md`](./ARCHITECTURE.md) — 了解四大工程划分、32 窄工具与 SQLite 契约、以及 §5 已知技术债；
3. [`ROADMAP.md`](./ROADMAP.md) — 查看 P0–P3 优先级与当前最需要社区协助的开放方向；
4. [`REFERENCES.md`](./REFERENCES.md) — 按需查阅对应子系统背后的原论文与开源生态。

---

## 二、你可以从哪里切入？（参考 `ROADMAP.md`）

不需要啃完整个仓库才能动手，以下任意独立方向都非常欢迎认领：

- **P0 · 止血、强沙箱与解耦重构**：
  - 将桌面应用层软沙箱升级为带 cgroups CPU/内存/磁盘/断网硬限额的 **Docker / WSL2 容器沙箱**；
  - 拆分千行级高耦合文件（如 `control_plane_service.py`、`orchestrator.js`、`tools_library.py`、`agent_session_host.js`）；
  - 设计并运行“零工程事故下 GreatWall 多智能体 vs 单 Agent 裸跑”的受控基线实验。
- **P1 · 人机体验与引导层重构**：
  - 重构右侧栏「长城科研指挥舱」UI 的美术视觉与谱系/盲审钻取交互（[`client.js`](./greatwall-v6up/dsh_plugin/lib/client.js)）；
  - 借鉴 DSH `SuperAgent` 范式升级面向人类的科研主控体验；
  - 精简与优化 7 类角色的 `System Prompt / Tool Guidance / Guardrails`。
- **P2 · 工造司进化与双轨知识库**：
  - 在完整保留工造司三档四态与校准集优势的前提下，探索 `Harness²` 局部轨迹对比（Mini-Probe）与跨课题轻量演化经验库。
- **P3 · 开放科研生态与跨宿主适配**：
  - 基于 **MCP / Agent Skills / Lean 4** 贡献新学科仪器插件、校准样例与科研技能；
  - 调研与实现 **ACP（Agent Client Protocol）** 或抽象 Runtime Adapter，摆脱对单一宿主的绑定；
  - 开展“夜科学实效 / 窗口百分比 vs 离散 Tick / 严格隔离 vs 小组讨论”的开放对照实验。

> **小建议**：如果你打算做较大规模的重构或新机制设计，建议先开一个 **Issue / Discussion** 简单聊两句思路，避免重复投入或与主线规划冲突。

---

## 三、许可证与 DCO（Developer Certificate of Origin）签署要求

本项目采用 **Apache License 2.0**（见 [`LICENSE`](./LICENSE) 与 [`NOTICE`](./NOTICE)），并实行 **DCO 1.1**（开发者原创声明）认证：

### 1. 提交 Commit 时请务必加上 `-s`（`Signed-off-by`）

每次提交都需要在 Commit Message 末尾包含你的真实署名行：

```text
Signed-off-by: Your Name <your.email@example.com>
```

使用 Git 的 `-s` / `--signoff` 参数即可自动生成：

```bash
git commit -s -m "fix(sandbox): block symlink traversal on Windows worktree"
```

如果忘记加 `-s`，可以在推送前补签最近一次提交：

```bash
git commit --amend --no-edit -s
```

### 2. DCO 1.1 原文摘要

通过添加 `Signed-off-by` 行，你声明你对本次提交遵守 [Developer Certificate of Origin 1.1](https://developercertificate.org/)：
- 贡献完全或部分由你创作，且你有权按本项目所采用的开源协议（Apache 2.0）提交；
- 或贡献基于你所知采用兼容开源协议的已有作品，且你保留了原始归属说明；
- 你理解并同意你的贡献及提交记录将公开留存并随本项目再分发。

---

## 四、本地开发环境

- **DeepSeek Harness (DSH)**：`>= 0.2.2-rc.5 < 0.3.0-0`
- **Node.js**：`>= 22.19.0` 或 `>= 24.0.0`
- **Python**：`>= 3.11`（控制面内核仅依赖 Python 标准库）

---

## 五、工程红线与 PR 提交规范

1. **零修改 DSH 原生源码**：插件扩展必须通过 Cordis `inject` 服务与标准接口完成，禁止依赖或修改宿主 `app.asar` 内部私有实现。
2. **契约变更须保持同源**：若修改 SQLite Schema、32 窄工具参数或角色模板，请同步更新 [`core_python/agents/*.md`](./greatwall-v6up/core_python/agents/) 与 Schema 定义（如有架构级变更，请一并更新 [`ARCHITECTURE.md`](./ARCHITECTURE.md)）。
3. **严禁提交本地私密与运行态脏文件**：请勿将 API Key、个人本机绝对路径、`greatwall.db*`、运行产生的 `worktrees/` 或临时日志提交入仓。
4. **Commit 与 PR 风格**：
   - 推荐遵循 [Conventional Commits](https://www.conventionalcommits.org/)（例如 `feat(works): ...`、`fix(orchestrator): ...`、`refactor(mcp): ...`、`docs(readme): ...`）；
   - PR 描述尽量简洁说清：**改了什么 → 为什么改 → 实际验证情况**（如涉及 UI 改动，欢迎附前后对比截图）。

---

## 六、友善协作准则

本项目是一群对“AI for Science 与自主科研多智能体”怀有好奇心的研究者与开发者的开放实验场。请保持理性、真诚、对事不对人的技术讨论——**指出漏洞、证伪假设、提出反例在这里和写出好代码一样受尊重。**
