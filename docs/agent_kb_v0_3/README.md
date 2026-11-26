# GreatWall Agent `v0.3` 顶层架构正式定稿

> **版本与写作原则说明**：本设计定稿时的运行代码为 **`v0.2.0-alpha.1`**，本目录记录当时规划的 **`v0.3.0-alpha.1` 统一大更新**最终顶层工程架构定稿。当前实现状态见[仓库首页](../../README.md)。全套文档严守 GreatWall **三大项目根本原则**（第一性原理、钱学森《工程控制论》、清晰自然语言表达原则），坚持**稳健性（Robustness）而非防御性（Defensiveness）**，已取消历史 M1/M2/M3 割裂妥协路线，并通过真实 SQLite 外键、迁移与硬触发器全量实测校验。原有 `docs/agent_kb/` 与根目录 `ARCHITECTURE.md` 保持原貌未覆盖。

## 核心架构升级摘要

- **微 / 中 / 宏三层严格分离**：微观单班岗（0/37/70% 与双角色桌面）$\to$ 中观单分支快流转（6 类去向与双通道缺引理唤醒）$\to$ 图书馆主导的脉冲式**宏观大外环**（代码硬对账 $\to$ 圆桌 2 轮对抗 $\to$ 1500 字《子题全局总览与明确缺口清单》$\to$ 同一圆桌裁判读总览拍板 6 类树结构调整）。
- **图书馆四角色一对一物理分权**：`external_surveyor`（唯一联网、禁读内藏）、`library_verifier`（零外网空白沙箱实跑、Stage 2 `ACCEPT_NARROWED` 同事务降级收编与冻结包终核）、`conference_chair`（零外网零代码执行、两阶段主持与拍板）、`library_chronicler`（零外网零代码执行、全局总览与结项总论文）。
- **Super-agent 范式人机协同（融入设施工程）**：以物理剥权的 `gw-chief`（Superagent）作为全院唯一推荐人机对话入口，沿院内事件生命周期落地「两阶段事件过滤与隐式批处理 $\to$ 轻量只读领域态 UI 输出与 8 类宪章正门确认提案单 $\to$ 科研四级 `Inline & Spill` + 强外键回忆链（配 Compacting 与 400 字动态锚点） $\to$ 零副作用推测预演」，配 +1 人类优先保留槽位与 `NOTIFY_POLICY_CHANGED` 温和热传播，并克制保留一键查底账、暂停直连子节点对话/改码与 `handback_to_chief` 越界退回权。
- **三道子题停工锁**：① 硬证据通关（最新口径 `FULL_GOAL` 解或全局不可能证明）随时停派；② 最低投入时间窗约束下的大外环语义暂停待人类拍板；③ 物理硬 Token / 波次天花板兜底。

## 文档导航

1. **`v0.3` 顶层工程架构论文与迁移规范（`docs/agent_kb_v0_3/`）**
   - [总纲导航、全生命周期、角色权限总表与里程碑路线](./agent_kb_v0_3_00_INDEX_总导航_三层职责分离与里程碑路线.md)
   - [设施工程架构论文 (`ARCH_PAPER_01`)](./ARCH_PAPER_01_设施工程_Infrastructure_Engineering.md)
   - [仪器科学工程架构论文 (`ARCH_PAPER_02`)](./ARCH_PAPER_02_仪器科学工程_Instrument_Science_Engineering.md)
   - [后勤工程架构论文 (`ARCH_PAPER_03`)](./ARCH_PAPER_03_后勤工程_Logistics_and_Lineage_Engineering.md)
   - [图书馆工程架构论文 (`ARCH_PAPER_04`)](./ARCH_PAPER_04_图书馆工程_Library_and_PeerReview_Engineering.md)
   - [精确 SQLite DDL、旧库迁移与契约增量](./agent_kb_v0_3_04_数据模型与旧库迁移_精确SQLite_DDL与工具契约增量.md)
2. **工程交接与底层开发实战手册（`docs/`）**
   - [v0.2.0-alpha.1 工程交接手册 (`handover_manual_v020.md`)](../handover_manual_v020.md)
   - [DSH 0.2.2-rc.5 工程开发实战手册 (`dsh_development_handbook.md`)](../dsh_development_handbook.md)
