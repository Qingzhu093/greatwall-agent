# GreatWall Agent (`v0.3.2`) 子系统架构知识库（`agent_kb_v0_3`）

> **编写原则**：本目录收录 GreatWall Agent `v0.3.2` 四大核心子系统的独立架构说明书与精确数据模型定义。全套文档坚持平实、清晰的自然语言风格，不预设任何历史对话背景，确保没有上下文的开发者打开任意一篇即可完整理解该子系统的问题背景、核心规则、状态机、边界约束与代码落点。

---

## 系统架构速览

- **四大正交子系统**：
  1. **设施工程**：Node 插件编排层 + Python 单写者 SQLite 内核（33 张表、双线程池、11 类并发 Outbox、双向目录沙箱），以及面向人类研究者的常驻总控 `gw_chief` 与只读观测面板。
  2. **仪器科学工程**：极薄通用隔离评测容器，支持判定器 / 探针 / 仿真环境三类插件与 `probe / official / heavy` 三档调用；四态归因隔离保证平台故障对探索者零处罚；正式观测瞬间冻结代码快照解除后续开发束缚；通过自声明校准集回归升版。
  3. **后勤与谱系工程**：有状态的外部搜索 × `360k` 无状态短会话接力（`0%` 行前摘要 → `0%–37%` 前期独立探索 → `37%` 11 类结构化元反思解锁内藏 → `52%` 短时只读暂停编程反思与随机灵感卡 → `70%` 两步交接封存）；支持默认异步快照投稿、确定性交接分诊、方法族多样性保护与旁路跨路线融合。
  4. **图书馆与评审工程**：4 个权限物理隔离的无状态角色（对外文献检索员、独立盲审官、馆内综述官、同行研讨会主席），承载外藏/内藏双库、零外网按需院内专题综述、独立空白沙箱两阶段同行评审（严谨度 / 新颖度 / 重要性三维评估与边缘笔记分流）、周期性跨分支同行研讨会（两轮点对点讨论 + 三阶段无损拓扑执行 + 多篇组合/开放饱和收敛）以及 Stage 3 不可变冻结终核交付。

---

## 文档导航

1. **四大子系统独立架构说明书（推荐按需精读）**
   - [设施工程架构说明：运行底座与人机交互控制面 (`ARCH_PAPER_01`)](./ARCH_PAPER_01_设施工程_Infrastructure_Engineering.md)
   - [仪器科学工程架构说明：隔离评测、观测快照与校准升版 (`ARCH_PAPER_02`)](./ARCH_PAPER_02_仪器科学工程_Instrument_Science_Engineering.md)
   - [后勤与谱系工程架构说明：探索周期、反思机制与分支管理 (`ARCH_PAPER_03`)](./ARCH_PAPER_03_后勤工程_Logistics_and_Lineage_Engineering.md)
   - [图书馆与评审工程架构说明：知识库、同行评审与跨分支研讨 (`ARCH_PAPER_04`)](./ARCH_PAPER_04_图书馆工程_Library_and_PeerReview_Engineering.md)
2. **总览、精确数据模型与施工手册**
   - [总纲导航：三层职责分离与角色工具映射 (`00_INDEX`)](./agent_kb_v0_3_00_INDEX_总导航_三层职责分离与里程碑路线.md)
   - [数据模型与旧库迁移：33 张 SQLite 表精确 DDL、触发器与工具契约 (`04_数据模型`)](./agent_kb_v0_3_04_数据模型与旧库迁移_精确SQLite_DDL与工具契约增量.md)
   - [完整工程施工手册 (`greatwall_v0_3_2_architecture_and_engineering_manual.md`)](../greatwall_v0_3_2_architecture_and_engineering_manual.md)
3. **底层宿主开发手册与源码地图**
   - [DSH 0.2.2-rc.5 插件开发手册 (`dsh_development_handbook.md`)](../dsh_development_handbook.md)
   - [源码模块单源地图 (`greatwall-v6up/MODULE_MAP.md`)](../../greatwall-v6up/MODULE_MAP.md)
