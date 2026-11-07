# 2026 全国大学生数学建模竞赛 B 题 AFEVA 全自动无人值守研发看板 (BOARD.md)

## 一、 系统架构与元数据
- **工程物理路径**：`D:\Documents\deepseek harness\实战v3`
- **主控总架构师**：Meta-Architect (Antigravity)
- **演化架构体系**：AFEVA (Anti-Fragile Evolutionary & Verifiable Architecture)
- **当前阶段**：Phase 2.1 - 定点瓶颈消融与终局合流主干 (Atomic Improvement & Gold Standard)
- **Git 状态**：Phase 2 两大杂交分支 (`node_05`, `node_06`) 双双斩获 Tier 2 PASS 满贯

---

## 二、 角色梯队与智能体分工

| 角色代码 | 智能体名称 | 职责定位 | 状态 |
|---|---|---|---|
| 00 | **Meta-Architect** | 主控总架构师，掌管全局节拍、版本调度与门禁把关 | 活跃中 (Phase 2.1) |
| 01 | **evaluator_agent** | 造尺造锤人，高保真物理沙箱、白盒性能剖析字典与三级阶梯门禁 | 交付完成 (Phase 0) |
| 02 | **explorer_agent** | 点子王，签发两两正交设计方案、特征杂交与偏科火种挖掘 | 交付完成 (Phase 1) |
| 03 | **branch_builder** | 主力构建者，单节点物理隔离实现算法与仿真 | 活跃中 (Phase 2 推进) |
| 04 | **spec_extractor** | 去表象规格书审计官，代码与日志逆向白盒审计，击穿口头幻觉 | 交付完成 (Phase 1.2a) |
| 05 | **tournament_judge** | 首席盲评裁判，MAP-Elites 行为空间映射与 Borda 序数多维盲评仲裁 | 交付完成 (Phase 1.2b) |

---

## 三、 AFEVA 三级阶梯门禁全景

| 门禁级别 | 名称 | 准入目标 | 核心准入条件 | 当前全场达标情况 |
|---|---|---|---|---|
| **Tier 1** | **粗野探索门 (Rough Gate)** | 鼓励速度创新，粉碎早熟收敛，保护偏科幼苗 | Q3 耗时/均时 $\le 320\text{s}$，Q3 清除率 $\ge 95\%$ | **node_01~04 全部 100% 通过** |
| **Tier 2** | **集成中继门 (Staging Gate)** | 动态修补包络，多场景对抗检验 | Q3 清除率 $100\%$，Q4 清除率 $\ge 90\%$，平均耗时 $\le 260\text{s}$ | **node_01, node_05, node_06 荣获 PASS** |
| **Tier 3** | **钢铁交付门 (Iron Gate)** | 终局国一合流选拔，严苛物理交付 | Level 1~3 全部 100% 跑通，$\text{Eff\_Gap} \le 1.60$，$\text{Waste\_Ratio} \le 0.15$ | **node_08 终局冲击目标** |

---

## 四、 代码树演化规划与全量战报 (Solution Tree)

| 节点代号 | 范式类别 / 杂交机理 | 核心数学机理 | Q3 均时 | 效率比 (Gap) | L3 清除率 | 冗余比 (Waste) | 门禁判定 |
|---|---|---|---|---|---|---|---|
| `node_01` | 贝叶斯信息论 | 概率栅格 + 互信息增益 (MIG) + 逆向向心包络网 | 282.00s | 3.52 | **100.0%** | 12.07% | **Tier 1 PASS / Tier 2 PASS** |
| `node_02` | 几何空间突进 | 动态 Voronoi 分区 + 顺路视线交会 (LOS) + 快速清除 | **210.08s** | 2.91 | 75.0% | **0.00%** | **Tier 1 PASS** (速度幼苗) |
| `node_03` | 统计序列推断 | SMC 粒子滤波 + 序列概率比检验 (SPRT) 极速早停 | 224.68s | 3.14 | **87.5%** | **0.00%~1.08%** | **Tier 1 PASS** (剪枝中枢) |
| `node_04` | 聚类强化启发 | 在线分层聚类 + UCB1 多臂老虎机 + 局部自适应 TSP | **147.21s** | **1.90** | 75.0% | **0.00%** | **Tier 1 PASS** (速度王者) |
| `node_05` | **Crossover 1** | node_04 极速调度 + node_01 向心包络网 + 抽屉早停 | 254.89s | 3.52 | **100.0%** | **0.00%** | **Tier 2 PASS** (全满贯) |
| `node_06` | **Crossover 2** | node_02 几何突进 + node_03 软静音 SPRT + 切线扫掠 | **175.73s** | 2.43 | **100.0%** | **0.00%** | **Tier 2 PASS** (全满贯 195s) |
| `node_07` | **Atomic Improve 1** | 极速突进与多目标动态分配消融优化 | 构建中 | - | - | - | Phase 2.1 |
| `node_08` | **Gold Standard** | 终局合流金标主干，冲击 Tier 3 钢铁交付门 | 待构建 | - | - | - | Phase 2.2 终局 |

---

## 五、 阶段节拍追踪

- [x] **Phase 0.1**: 初始化工作目录 `D:\Documents\deepseek harness\实战v3` 与 Git 仓库
- [x] **Phase 0.2**: 建立项目看板与五大智能体注册 (`evaluator`, `explorer`, `builder`, `extractor`, `judge`)
- [x] **Phase 0.3**: 派发 `evaluator_agent` 盲态编写评测套件 (`tools/radio_sandbox.py`, `eval_gate/profiler.py`, `eval_gate/gate_check.py`)
- [x] **Phase 0.4**: 评测套件自测试跑与环境基准锁定
- [x] **Phase 1.0**: `explorer_agent` 签发 4 套正交设计方案
- [x] **Phase 1.1**: `branch_builder` 并发构建 `node_01 ~ node_04`（全部通过 Tier 1）
- [x] **Phase 1.2**: `spec_extractor` 与 `tournament_judge` 实施白盒审计与 MAP-Elites 锦标赛盲评
- [x] **Phase 2.0**: 构建 Crossover 1 (`node_05`) 与 Crossover 2 (`node_06`)（双双斩获 Tier 2 PASS 全满贯）
- [ ] **Phase 2.1**: 构建 Atomic Improve 1 (`node_07`) 与 Gold Standard (`node_08`)
- [ ] **Phase 2.2**: `node_08` 冲击并通过 Tier 3 钢铁交付门（Gap <= 1.60，Waste <= 0.15，L1~L3 100% 全清）
- [ ] **Phase 3.0**: 22~26 页国一 XeLaTeX 论文全息编撰与收敛封箱
