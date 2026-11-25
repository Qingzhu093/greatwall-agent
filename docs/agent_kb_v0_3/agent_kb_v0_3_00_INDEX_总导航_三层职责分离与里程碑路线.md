# GreatWall Agent `v0.3` 顶层架构总纲导航与实施路线（终稿）

> **定位**：本文是 GreatWall Agent `v0.3` 完整顶层设计套件的总索引。本套件彻底采用**零前提、自包含的工程架构论文体例**——任何未接触过历史讨论的架构师或中层工程师，按本导航阅读 4 篇工程架构论文与 1 份精确数据迁移契约，即可无歧义理解整座系统的终态全貌、模块拆解、接口契约、学术溯源与验收标准。

---

## 一、全套终态顶层设计文档导航（权威真相源）

| 文档 | 核心主题与完整覆盖内容 |
| :--- | :--- |
| **[`ARCH_PAPER_01` 设施工程架构论文](file:///C:/Users/wangy/.gemini/antigravity/brain/fd5c9c24-425d-4297-87e2-c24e2a98225c/ARCH_PAPER_01_%E8%AE%BE%E6%96%BD%E5%B7%A5%E7%A8%8B_Infrastructure_Engineering.md)** | 双层运行时、三层正交职责分离、全院角色 Preset 与物理权限隔离矩阵、DSH 原生 Session 按需水合（`gw-comp-<node_id>`）、`runtime_effects` 租约与崩溃认领恢复、节点 `45%` 接管/改码哈希对账/交还状态机、DSH `0.2.2-rc.5` 适配边界 |
| **[`ARCH_PAPER_02` 仪器科学工程架构论文](file:///C:/Users/wangy/.gemini/antigravity/brain/fd5c9c24-425d-4297-87e2-c24e2a98225c/ARCH_PAPER_02_%E4%BB%AA%E5%99%A8%E7%A7%91%E5%AD%A6%E5%B7%A5%E7%A8%8B_Instrument_Science_Engineering.md)** | 实验室仪器科第一性定位、`plugin is everything` 隔离容器、三档同码、四态隔离、四元复合缓存、自声明校准集回归、Stage B 诚实重评、`SKILL_LEDGER.json`，以及与后勤/盲审/波次圆桌/活体综述的四条跨部门耦合管道 |
| **[`ARCH_PAPER_03` 后勤工程架构论文](file:///C:/Users/wangy/.gemini/antigravity/brain/fd5c9c24-425d-4297-87e2-c24e2a98225c/ARCH_PAPER_03_%E5%90%8E%E5%8B%A4%E5%B7%A5%E7%A8%8B_Logistics_and_Lineage_Engineering.md)** | 伴随助手 `0%` 恒定 $O(1)$ 冷启动与全馆 Pull 视野、科研人员 `0%` 极简实验台与 `37%` 后三层确定性漏斗自主 Pull、`70%` 硬锁精确优先级、停笔后伴随 4 大真源与 5 种行动轨迹、分诊与打捞三截面无重叠合一、彻底移除五车道、子题快慢双闸门独立收敛 |
| **[`ARCH_PAPER_04` 图书馆工程架构论文](file:///C:/Users/wangy/.gemini/antigravity/brain/fd5c9c24-425d-4297-87e2-c24e2a98225c/ARCH_PAPER_04_%E5%9B%BE%E4%B9%A6%E9%A6%86%E5%B7%A5%E7%A8%8B_Library_and_PeerReview_Engineering.md)** | 三角色物理分权（`external_surveyor` / `library_verifier` / `library_chronicler`）× 四大正式支柱（外部资料整理、空白沙箱盲审与当场降级收编/沉船打捞、《子题活体综述地图》与 Stage 3 不可变终稿、按子题计步触发的波次圆桌对抗）、`2%` 跨线达标与基线发布两步分离、原口径 `LEVEL_4A` 入 `L3_VERIFIED` |
| **[`agent_kb_v0_3_04` 精确 DDL、迁移与契约增量](file:///C:/Users/wangy/.gemini/antigravity/brain/fd5c9c24-425d-4297-87e2-c24e2a98225c/agent_kb_v0_3_04_%E6%95%B0%E6%8D%AE%E6%A8%A1%E5%9E%8B%E4%B8%8E%E6%97%A7%E5%BA%93%E8%BF%81%E7%A7%BB_%E7%B2%BE%E7%A1%AESQLite_DDL%E4%B8%8E%E5%B7%A5%E5%85%B7%E5%A5%91%E7%BA%A6%E5%A2%9E%E9%87%8F.md)** | 100% 对齐现版 `db_schema.py` 且经真实内存 SQLite（`foreign_keys=ON`）全量实测通过的增量 DDL、触发器、旧库平滑升级脚本规范与控制面原语契约 |

---

## 二、全院 7 条核心架构共识速览

1. **三层正交分离**：科学判定（解出来了吗）$\perp$ 设施调度（还该不该派工）$\perp$ 权限授权（谁有权改方向/接管/交付）。
2. **双角色对称上下文与三层确定性 Pull**：伴随助手 `0%` 即享全馆只读 Pull 且 Push 恒定 $O(1)$；科研人员 `0–37%` 保持独思净室，`37%` 后顺着《子题活体综述地图 `<=1500` 字》$\to$《契约卡 `<=350` 字》$\to$《全文/模块》自主高命中率 Pull。
3. **DSH 原生 Session 按需水合**：`gw-comp-<node_id>` 依托磁盘 Session Log 跨 `0% / 37% / 70% / 波次圆桌` 按需唤醒并按阶段动态重挂工具（封存后物理卸载写看板工具），零空闲内存占用、不怕重启、绝不跨代。
4. **分诊与打捞三截面合一**：`70%` 活节点主动走 `LEVEL_1` 送独立局部引理；盲审主稿被击穿但局部引理已在 Stage 1 实测通过时当场 `ACCEPT_NARROWED` 收编入 `L3`；仅从未送审即休眠的多代沉船按需清点遗产。
5. **图书馆三角色物理分权**：`external_surveyor`（纯对外联网、禁读内藏）、`library_verifier`（零外网空白沙箱盲审 + 主持波次圆桌）、`library_chronicler`（零外网零执行、专司活体综述与 Stage 3 不可变终稿）。
6. **彻底移除五车道停滞复苏**：横向破局由图书馆《活体综述》、`LEVEL_4B` 悬赏唤醒、盲审降级收编与波次圆桌双供体合体承载，彻底消除口号式停滞标签。
7. **100% 兼容现版表名与枚举**：严格沿用 `internal_research_ledger(entry_id)`、`lineage_nodes(node_id)`、`LEVEL_1`~`LEVEL_4B`、`L3_VERIFIED`（含 `NEG_COUNTEREXAMPLE / BARRIER_PROOF`）原口径。

---

## 三、渐进式施工与验收路线（顶层设计完整，落地分步可控）

- **M1（首批主线 —— RC5 端到端实测验收）**：
  1. 子题快闸门自动停派（含 `2%` 跨线达标必过且停派的验收用例，Q1 停派收尾释槽、Q2 持续运行）；
  2. 运行中节点 `45%` 人工接管 $\to$ 可见收尾 $\to$ IDE 改码对话 $\to$ 重启宿主 $\to$ SHA-256 工件哈希对账 $\to$ 交还托管或授权提前交接；
  3. `runtime_effects` 租约恢复、`gw-comp-<node_id>` 按需水合、Stage 3 不可变冻结目录核签与 `v0.2.0-alpha.1` 旧库平滑迁移。
- **M2（独立增强）**：
  1. 设施层独立饱和暂停（无圆桌循环依赖的慢闸门）；
  2. 拆出零外网 `library_chronicler` 与《子题活体综述地图》自动更新 + 科研人员三层确定性 Pull；
  3. 右侧栏「三问」控制台重构 + 只读/起草型 `gw-chief` + `open_lemma_gaps` 悬赏自动唤醒。
- **M3（波次对抗闭环）**：
  1. 启用按子题计步触发的波次圆桌对抗会议（`wave_conferences`）、双供体只读挂载合体支线与圆桌 `DISCRIMINATOR` 鉴别仪器工单，并在等预算下与 M1+M2 基线做受控对照评估。
