# Project: 长城 Agent V6-Up 顶层架构与开源 DSH 原生系统总览（v3.0 去过拟合通用科研版）

> **开源 DeepSeek Harness (DSH) × Python MCP / 双隔离沙箱工程落地的唯一权威入口（2026-11-21 第四轮复盘后 v3.0 全面定版）**：  
> - **唯一权威顶层设计定稿（v3.0）**：[`docs/architecture/手写project.md`](./docs/architecture/手写project.md)（第一性思想原点） + **[`docs/architecture/04_十三篇前沿论文深度解惑与V6Up架构融合专报.md`](./docs/architecture/04_十三篇前沿论文深度解惑与V6Up架构融合专报.md)**（v3.0 唯一权威顶层架构总纲）。  
> - **面向中层的 v3.0 工程施工蓝图**：**[`docs/architecture/09_V6Up_v2.2_实施侧工程交接与系统开发总说明书.md`](./docs/architecture/09_V6Up_v2.2_实施侧工程交接与系统开发总说明书.md)**（DSH 插件、盲审沙箱、SQLite DDL 与 P0–P4 验收；若与 `04` / `agent_kb` 存在表述微差，以顶层定稿 `04` 及 `agent_kb` 为准）。  
> - **Agent 专用前沿工程知识库（`docs/agent_kb/` — 开发与运行态必读）**：**[总导航 `00_INDEX`](./docs/agent_kb/00_INDEX_Agent知识库总导航与必读映射.md)** 及 **`01–06` 全套细化知识卡**（涵盖二十五大反模式红灯清单、沙箱工具平权读写矩阵、科研仪器科接口、三态盲审与 **7 大角色 v3.0 零缩水直抄模板库 [`agent_kb/05`](./docs/agent_kb/05_原论文级Prompt武器库与五大角色完整模板直抄库.md)**）。  
> - **演进思辨、测试法医复盘与历史归档**：  
>   - [`docs/architecture/05_V6Up架构演进思辨与文献取舍絮语集.md`](./docs/architecture/05_V6Up架构演进思辨与文献取舍絮语集.md)（含 §1.7 第四轮复盘 $\to$ v3.0 收敛思辨）  
>   - [`docs/round4_audit/`](./docs/round4_audit/01_交顶层设计者_原文对照与架构讨论稿_对齐版.md) & [`docs/round2_audit/`](./docs/round2_audit/07_V6Up第二轮测试全链路复盘与设计归因档案.md)  
>   - [`archive/第四轮审阅后_v2.2顶层设计备份_20261121/`](./archive/第四轮审阅后_v2.2顶层设计备份_20261121/) & [`archive/第二轮测试前_顶层设计原稿备份_20261119/`](./archive/第二轮测试前_顶层设计原稿备份_20261119/)

---

## Architecture (V6-Up v3.0)

以第一性原理（**长周期、高并发、无人值守、通用 AI for Science**）为纲领，构筑 **“开源 DSH `ctx.agents.create()` 确定性极薄事件总线 + 3 真相 (`Obs` / `谱系 DAG + lineage_dead_ends` / `图书馆内外两翼`) 2 视图 + 沙箱平权 (`explorer` 与 `library_verifier` 均开放隔离沙箱执行工具) + 科研仪器科三档四态校准体系”**：

```text
╔════════════════════════════════════════════════════════════════════════════════════╗
║   开源 DSH 确定性极薄事件总线 (ctx.agents.create() · 零权力 / 零科学偏见)          ║
║   Parse 0 六项表单确认 -> 无人值守连续运行（口径歧义亮 ALERT_AMBIGUOUS_SPEC 红灯续跑）║
╚═══════╤═══════════════════╤════════════════════════════╤═══════════════════╤═══════╝
        ▼                   ▼                            ▼                   ▼
┌────────────────┐  ┌─────────────────────┐      ┌────────────────┐  ┌────────────────┐
│   监察委员会    │  │     后勤工作部       │      │   中央图书馆    │  │  工造司(仪器科) │
│ (supervisory_  │  │ (logistics_         │      │ (library_      │  │ (works_        │
│  committee)    │  │  coordinator)       │      │  surveyor +    │  │  engineer)     │
│ · 只读审计告警 │  │ · 分支级 requires   │      │  verifier)     │  │ · 统一三档仪器  │
│ · 口径红灯记录 │  │ · >50%无豁免聚拢分流│      │ · 左翼:未复验[R]│  │ · 判不了绝不判负│
│ · CDC双段终局锁│  │ · 四级分诊与物理快照│      │ · 右翼:盲审沙箱 │  │ · 校准集回归升级│
└────────────────┘  └──────────┬──────────┘      │   跑证三态->L3/2│  └────────────────┘
                               │ 1 对 1 结对护航  └────────────────┘
                               ▼
         ╔═════════════════════════════════════════════════════════╗
         ║   一线科学单元 = [ 探索者 (explorer) ◄── 1 对 1 ──►      ║
         ║                   分身伴随助手 (lineage_companion) ] × W ║
         ║   · 0–37% 维持极简纯 Push + 查外藏 + `pwsh` 自主试探    ║
         ║   · 37%（无 eval_count 锁）2 轮元反思当场解锁内藏 Pull  ║
         ║   · 70% 伴随单写者写 DAG 页 + lineage_dead_ends 只追加  ║
         ╚═════════════════════════════════════════════════════════╝
```

---

## Feature Inventory & Milestones

| # | Milestone / Feature | Scope & Highlights | Status | Output Artifact |
|---|---|---|---:|---|
| M0–M9 | 早期架构、第一/二轮实机测试法医复盘 | 揭露 `P1–P29` 行政公文泛滥、假时钟与全局 `state_version` 误杀 | DONE | [`docs/round2_audit/`](./docs/round2_audit/07_V6Up第二轮测试全链路复盘与设计归因档案.md) |
| M10 | V6-Up v2.2 顶层设计重整（3 真相 + 2 视图 + 时间轴大一统） | 确立无状态 7 角色、`500k` 时钟、`L1` 并入 DAG 与两翼物理分表 | ARCHIVED | [`archive/第四轮审阅后_v2.2顶层设计备份_20261121/`](./archive/第四轮审阅后_v2.2顶层设计备份_20261121/) |
| **M11** | **第四轮现场审阅与 V6-Up v3.0 通用科研大重构** | **去 CUMCM B 题过拟合**：仪器科重构（四态隔离/三档/校准集）、**盲审沙箱开放跑证工具**、三态盲审与确证反例入 `L3`、废 `eval_count` 锁、分支 `requires`、**同题学派 `>=2` 且 `>50%` 无豁免打散**、无人值守红灯续跑、CDC 双段式终局 | **DONE (当前最新唯一权威顶层基准)** | **[`04`](./docs/architecture/04_十三篇前沿论文深度解惑与V6Up架构融合专报.md) + [`09`](./docs/architecture/09_V6Up_v2.2_实施侧工程交接与系统开发总说明书.md) + [`docs/agent_kb/`](./docs/agent_kb/00_INDEX_Agent知识库总导航与必读映射.md)** |

---

## Code & Document Layout

- **[`docs/architecture/手写project.md`](./docs/architecture/手写project.md)**：最高原创第一性纲领（只读保留）
- **[`docs/architecture/04_十三篇前沿论文深度解惑与V6Up架构融合专报.md`](./docs/architecture/04_十三篇前沿论文深度解惑与V6Up架构融合专报.md)**：v3.0 唯一权威顶层架构总纲
- **[`docs/architecture/09_V6Up_v2.2_实施侧工程交接与系统开发总说明书.md`](./docs/architecture/09_V6Up_v2.2_实施侧工程交接与系统开发总说明书.md)**：面向中层的 v3.0 实施蓝图（DSH 插件、盲审沙箱、SQLite DDL、31+ 工具签名与 P0–P4 验收）
- **[`docs/architecture/05_V6Up架构演进思辨与文献取舍絮语集.md`](./docs/architecture/05_V6Up架构演进思辨与文献取舍絮语集.md)**：演进思辨（含 §1.7 v3.0 纠偏定音）与文献重评
- **[`docs/agent_kb/`](./docs/agent_kb/00_INDEX_Agent知识库总导航与必读映射.md)**：v3.0 全套 7 份高密度知识卡与零缩水 Prompt 直抄库
- **[`docs/round4_audit/`](./docs/round4_audit/01_交顶层设计者_原文对照与架构讨论稿_对齐版.md)**：第四轮实测对齐审计与用户第六轮批注原件
- **[`greatwall-v6up/`](./greatwall-v6up/)**：待按 `09` 说明书 P0–P4 同步重构落地的 DSH 插件与 Python MCP 工程代码仓
