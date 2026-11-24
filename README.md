# GreatWall Agent（长城）

[English](./README_EN.md) | **简体中文**

> **面向长周期、多学派并发自主科学发现的开源多智能体实验基座**  
> **版本状态**：`v0.1.0-alpha.4`（早期实验性 Demo · **阶段 1 后端解耦版本，尚未经过人工代码审阅** · **非开箱即用的生产工具**）  
> **开源协议**：[Apache License 2.0](./LICENSE) + [DCO 1.1](./CONTRIBUTING.md#三许可证与-dcodeveloper-certificate-of-origin签署要求) ｜ **运行底座**：[DeepSeek Harness (DSH)](https://github.com/deepseek-ai/deepseek-harness) `>= 0.2.2-rc.5` × Python `3.11+` × [MCP](https://modelcontextprotocol.io)

---

> ⚠️ **坦诚的前置说明**  
> 本项目目前处于非常早期的 **`v0.1.0-alpha.4`** 实验状态（注：`alpha.4` 阶段 1 后端解耦代码**尚未经过作者人工逐行审阅**，仅通过自动化单元与架构门禁测试）。虽然后端核心千行文件已完成首轮拆解，但代码库仍存在前端原型简陋（`client.js` 待重构）、应用层软沙箱安全局限、对 DSH 原生能力利用不足等债务，且整套多智能体科研制度尚未在零工程事故基线下完成充分的受控对照实验（详见 [`ARCHITECTURE.md §5`](./ARCHITECTURE.md#5-已知技术债与当前局限)）。  
> 我们选择现在以 **Apache 2.0 + DCO** 完全开源，是希望把前沿 AI for Science 多智能体架构思路真正做成可运行、可拆改、可共同演进的开放实验基座，欢迎任何拆解、复现、批评与协作。

---

## 为什么做 GreatWall Agent？

在把大语言模型推向十小时级、多路并行、无人值守的数学建模与开放科学探索时，通用单智能体或简单的父子多代理框架往往会迅速撞上三堵墙：

1. **长上下文注意力退化与“体面怠惰”**：对话拉长到数十万 Token 后，模型被早期直觉锚定，用流畅的学术辞令宣布“已接近理论极限”并停止实质探索；
2. **高并发下的群体思维坍塌**：多个分支若共享未经审定的公告板，几轮之内就会蜂拥向同一个表面好写、实则存在结构天花板的局部方案；
3. **工具损坏与科学失败混淆**：评测脚本报错、数据键位缺失或环境异常若直接折算为 0 分，会把真正有价值的科学突破埋没在工程事故里。

**GreatWall Agent** 试图借鉴学术界近期多项自主科研前沿成果（*Cogentic*、*The Station*、*SLA*、*AgentDiscover*、*RQGM*、*Audit the Scaffold* 等，完整溯源见 [`REFERENCES.md`](./REFERENCES.md)），构建一座**服务一线科研探索者的扁平学术共同体**——兼容纯解析数学推导与构造反例、形式化定理证明（如 Lean 4）、多保真数值仿真、多目标 Pareto 优化以及无客观标量尺度的开放机理探索。

---

## 系统全景与四大工程

![GreatWall Agent 系统架构全景图](./docs/assets/greatwall_architecture.svg)

### 极简科研闭环流程

```mermaid
flowchart LR
    A["独思净室 (0–37%)"] --> B["元反思与开放 Pull (37–70%)"]
    B --> C["亲笔遗嘱与伴随单写 DAG (70%)"]
    C --> D["工造司三档隔离评测"]
    D --> E["两阶段盲审与知识库沉淀"]
    E -. "六类分诊 / 五车道复苏" .-> A
```

在逻辑治理上，系统由确定性外部编排内核串联扁平制衡的**“一委三部 + 一线探索单元”**；在软件实现上，收口为四个正交的工程模块：

| 工程划分 | 对应逻辑机构 / 角色 | 核心机制（`v0.1.0-alpha.4` 已实现） |
| :--- | :--- | :--- |
| **1. 设施工程** | 插件编排内核 (`Orchestrator`)<br>监察委员会 (`supervisory_committee`)<br>外围人机接入原型 (`Console UI`) | 无 Root 扁平短会话调度（`ctx.agents.create()`）；显式模型绑定拒启门禁；自适应有效窗口 `W = min(500k, 模型窗口)`；单条待办项 2 次无进展熔断；版本化公开裁决 (`spec_revision`)；双向隔离沙箱；SQLite WAL 单写者真相库（19 表 + 2 FTS5 + 3 业务硬触发器） |
| **2. 仪器科学工程** | 工造司 (`works_engineer`)<br>隔离执行容器 (`isolated_runner.py`) | 统一 `evaluate(artifact, spec, tier)` 三档同码协议（`probe / official / heavy`）；四态物理隔离（`INSTRUMENT_ERROR / INFRA_ERROR` 零处罚、不判负、自动开单熔断）；四元复合缓存；自声明预期校准集回归升版；版本域可比与按需重评 |
| **3. 后勤工程** | 后勤工作部 (`logistics_coordinator`)<br>探索者 (`explorer`) ◄─1:1─► 伴随 (`lineage_companion`) | 单节点同会话伴随暂停续传（不跨代常驻）；`0–37%` 独思净室（锁内藏、开外藏 `[R###]`）→ `37%` 情报型元反思与 29 题夜科学解锁 → `37–70%` 开放 Pull → `70%` 先持久化亲笔《科研遗嘱》再伴随单写 DAG；`<=2200` 字定额重压缩看板 + 全量 `lineage_dead_ends`；六类分诊、`>50%` 无豁免学派分流与五车道复苏 |
| **4. 图书馆工程** | 外藏采编 (`library_surveyor`)<br>沙箱实测盲审 (`library_verifier`) | 外藏 `[R###]`（含无解查新 `UNAVAILABLE_REPORT` 诚实结案不伪造文献卡）与内藏 `L3/L2` 物理分表；四轨可核验送审准入；独立空白临时沙箱跑证两阶段盲审（`STAGE1_BLIND` 不可逆锁账本 → `STAGE2_UNBLIND` 三态分流）；`Auditor` 异会话打捞；默认 `MOTIVATING_REF` 非连坐引用；Stage 3 五件套导出与 `(delivery_id, delivery_sha256)` 绑定两步终核 |

全系统 7 大角色通过 **MCP (`stdio JSON-RPC 2.0`)** 按岗位白名单严格挂载 **32 个单一职责窄工具**，并坚持“工作区磁盘零过程 `.md` 公文”，所有过程状态统一落库。

---

## 核心文档导航

| 文档 | 内容定位 |
| :--- | :--- |
| **[`ARCHITECTURE.md`](./ARCHITECTURE.md)** | 系统设计哲学、四大工程深度拆解、基于真实源码的 32 窄工具与 19 表接口契约、以及 §5 已知技术债与局限 |
| **[`ROADMAP.md`](./ROADMAP.md)** | 问题清账本与 P0–P3 演进构想（UI 与 `SuperAgent` 主控、深度解耦、容器强沙箱、`Harness²` 工造司进化与双轨知识库、科研标准插座与开放实验议题） |
| **[`REFERENCES.md`](./REFERENCES.md)** | 全部影响架构或路线图的学术论文、工程博客、开源项目与开放协议完整溯源（严格区分 `✅ 已落地` 与 `🗺️ 路线图规划`，仅附公共链接） |
| **[`docs/paper_study/README.md`](./docs/paper_study/README.md)** | 前沿文献与背景知识研读库（37 篇核心论文、工程博客与官方提示词的中文深度精读综述与配图，供协作者快速对齐背景） |
| **[`greatwall-v6up/MODULE_MAP.md`](./greatwall-v6up/MODULE_MAP.md)** | 一页式源码模块地图（后端各子域职责、架构红线边界与一键验收/自检命令） |
| **[`CONTRIBUTING.md`](./CONTRIBUTING.md)** | 开源协作切入指南、Apache 2.0 + DCO 1.1（`git commit -s`）签署流程与 PR 规范 |
| [`greatwall-v6up/dsh_plugin/README.md`](./greatwall-v6up/dsh_plugin/README.md) | DSH `0.2.2-rc.5` 插件包迁移说明与 Preset 详情 |

---

## 快速上手

### 1. 环境依赖
- **DeepSeek Harness (DSH)**：`>= 0.2.2-rc.5 < 0.3.0-0`
- **Node.js**：`>= 22.19.0` 或 `>= 24.0.0`
- **Python**：`>= 3.11`（控制面仅依赖 Python 标准库；科研课题按需安装 `numpy` / `scipy` / `sympy` / `lean` 等）

### 2. 克隆并挂载至 DSH Profile

先克隆本仓库：

```bash
git clone https://github.com/Qingzhu093/greatwall-agent.git
```

再在 `~/.dsh/profiles/desktop/package.json`（或对应 Web Profile）中通过本地软链挂载 `greatwall-v6up/dsh_plugin` 并加入 `dsh.profile.bundles`：

```json
{
  "dependencies": {
    "dsh-greatwall-v6up": "link:/path/to/greatwall-agent/greatwall-v6up/dsh_plugin"
  },
  "dsh": {
    "profile": {
      "bundles": ["...其他 bundles...", "dsh-greatwall-v6up"]
    }
  }
}
```

> 详细升级与 DSH `0.2.2-rc.5` 适配说明请见 [`greatwall-v6up/dsh_plugin/README.md`](./greatwall-v6up/dsh_plugin/README.md)。

---

## 仓库目录结构

```text
greatwall-agent/
├── README.md                  # 项目总览与快速入口（本文档）
├── ARCHITECTURE.md            # v0.1.0-alpha 系统架构、代码地图、精确契约与已知局限
├── ROADMAP.md                 # 未解难题、P0–P3 演进方向与开放研究议题
├── REFERENCES.md              # 学术论文、工程博客与开源生态完整溯源
├── CONTRIBUTING.md            # 贡献指南与 DCO 1.1 签署规约
├── LICENSE & NOTICE           # Apache License 2.0 协议正文与第三方归属声明
├── greatwall-v6up/            # 核心可运行源码（~1.8 万行）
│   ├── core_python/           # Python Single-Writer 控制面、32 窄工具、隔离执行器与 7 套角色模板
│   ├── dsh_plugin/            # DSH (0.2.2-rc.5+) Cordis 插件、编排器、双向沙箱与指挥舱前端原型
│   └── tests/                 # Python 单元测试与回归套件
└── docs/                      # 架构图资产 (assets/)、历史顶层白皮书与研发知识库归档
```

---

## 当前主要局限（完整清单见 `ARCHITECTURE.md §5`）

- **前端与剩余解耦债务**：后端千行上帝文件已在 `v0.1.0-alpha.4` 完成首轮无损拆解并建立跨语言契约门禁，但前端指挥舱原型（`client.js`）尚未模块化重构；
- **应用层软沙箱局限**：当前桌面直跑沙箱依赖路径规范化与命令拦截，尚无 Docker / WSL2 + cgroups 的 OS 内核级资源限额与强隔离；
- **DSH 生态能力利用不足与简陋原型 UI**：原则上坚持不侵入修改 DSH 正常功能、依托 DSH 插件生态推广协作，但对 DSH 原生 UI 原语与配置能力的工程化利用仍很粗糙，也尚未抽离跨宿主适配层；
- **核心科研假设尚待干净对照实证**：多智能体制度相比单 Agent 裸跑在开放科研任务上的净收益、以及非标量科学任务的梯度引导难题，仍在持续验证探索中。

---

## 参与贡献与开源协议

我们诚挚欢迎任何形式的 Issue、讨论与 PR——无论是前端 UI 美化、底座解耦、容器沙箱、新学科 MCP/Skill 插件，还是关于多智能体科研方法论的实证探讨。提交前请先阅读 [`CONTRIBUTING.md`](./CONTRIBUTING.md) 并使用 `git commit -s` 完成 DCO 签署。

本项目基于 **[Apache License 2.0](./LICENSE)** 开源，第三方引用与归属声明见 **[`NOTICE`](./NOTICE)**。
