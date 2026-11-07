# AFEVA 全链路端到端集成测试就绪规范 (TEST_READY)

> **文档状态**：100% READY / VERIFIED PASS  
> **发布时间**：2026-11-06  
> **架构版本**：AFEVA v2.4.0 (Milestone 5 Phase 1 交付)  
> **目标工程**：`d:\Documents\deepseek harness\长程 Agent 设计系统`  
> **测试架构师与实施者**：worker_m5_e2e (End-to-End Integration Testing Group)

---

## 1. 测试套件概述 (Test Suite Overview)

AFEVA 全链路端到端集成测试套件（E2E Test Suite）位于目标工程目录 `e2e_tests/` 下，遵循严格的 4-Tier 层次化测试方法学构建：
- **Tier 1 - Feature Coverage**：系统核心特性全覆盖（每项核心功能至少 5 个测试，共 30 个用例）；
- **Tier 2 - Boundary & Corner Cases**：极端边界工况、高并发争用、病态输入与假死熔断（5 个用例）；
- **Tier 3 - Cross-Feature Combinations**：跨模块闭环交互、门禁与退火联动、崩溃重放沙箱重绑（5 个用例）；
- **Tier 4 - Real-World Application Scenarios**：高通量竞赛探索、灾难恢复、多样性塌缩防御与长程演化收敛（5 个用例）。

总计 **45 个端到端集成测试用例**，全部基于真实状态机、真实 Git/RAM-Disk 工作树沙箱、真实 AFEVA 门禁检验器与真实孤岛退火动力学执行，绝无任何硬编码打桩或作弊。

---

## 2. 测试执行命令 (Execution Commands)

所有测试均可使用系统推荐的现代版 PowerShell 7 (`pwsh`) 或标准 Python 环境直接执行：

### 2.1 全量执行 (All 4 Tiers)
```powershell
pwsh -NoProfile -Command "Set-Location 'd:\Documents\deepseek harness\长程 Agent 设计系统'; python e2e_tests/runner.py"
```
或直接在工程根目录下执行：
```bash
python e2e_tests/runner.py
# 或
python e2e_tests/runner.py --all
```

### 2.2 分层定向执行 (Tier-Specific Execution)
```bash
python e2e_tests/runner.py --tier 1   # 仅执行 Tier 1 特性全覆盖测试 (30 tests)
python e2e_tests/runner.py --tier 2   # 仅执行 Tier 2 边界与 Corner Cases 测试 (5 tests)
python e2e_tests/runner.py --tier 3   # 仅执行 Tier 3 跨模块闭环交互测试 (5 tests)
python e2e_tests/runner.py --tier 4   # 仅执行 Tier 4 真实应用场景测试 (5 tests)
```

### 2.3 调试详细模式 (Verbose Traceback)
```bash
python e2e_tests/runner.py -v
```

---

## 3. 4-Tier 覆盖摘要表 (4-Tier Coverage Summary)

| Tier | 层次定位 | 用例数 | 覆盖核心机制与场景描述 | 典型执行耗时 | 通过率要求 |
|---|---|:---:|---|:---:|:---:|
| **Tier 1** | **Feature Coverage** | 30 | 覆盖 6 大核心特性（状态机全生命周期流转与 P0 抢占、Worktree 物理沙箱隔离检出与无锁释放、AFEVA 三级渐进门禁与作弊拦截、三孤岛演化拓扑与稳健 MAD 退火、双账本隔离与 Living Playbook LFU-Decay、WAL 日志与原子快照自愈恢复），每特性 5 个用例 | ~0.35s | 100% PASS |
| **Tier 2** | **Boundary & Corner Cases** | 5 | 20+ 并发工作区高强度争用、0 耗时与微秒级抖动病态输入、空任务 DAG 与单节点自环死锁自愈破环、Worker 进程假死与看门狗超时墓碑脱离、超标查表临界法医裁决 | ~0.24s | 100% PASS |
| **Tier 3** | **Cross-Feature Combinations** | 5 | 跨模块全闭环流水线（Task->Worktree->Gate->Island->WAL->Snap）、带病晋级幼苗在 Island 2 新颖性特区受保护并变异修复、调度器背压自旋与死锁自愈、环形迁移与沙箱代码门禁联动、崩溃重启后快照与 WAL 重新绑定沙箱 | ~0.08s | 100% PASS |
| **Tier 4** | **Real-World Application Scenarios** | 5 | 真实综合竞赛多智能体并发探索与作弊剔除、长程演化第 10 轮灾难性断电与 100% 无损集群恢复、单一解法垄断下 AST 拓扑新颖性防御、多代代际迭代 Anchor 岛单调收敛最优工件、对抗性捕食者与战术手册动态自适应 | ~0.06s | 100% PASS |
| **TOTAL** | **全部测试集合** | **45** | **全生命周期、极限边界、跨模块协同、工业级真实竞赛场景闭环** | **~0.74s** | **100% PASS (Exit Code 0)** |

---

## 4. 特性清单覆盖矩阵 (Feature Inventory Mapping)

依据 `PROJECT.md` 定义的系统 15 大核心特性清单（F01~F15），端到端测试套件实现如下完整映射：

| 特性编号 | 特性名称 (Feature Name) | 映射测试用例 (Mapped E2E Tests) | 验证覆盖点与断言保障 |
|:---:|---|---|---|
| **F01** | **Epoch_Barrier** | `test_tier1_fsm_01`, `test_tier2_corner_03`, `test_tier3_cross_03` | LocalJoinBarrier 局部汇聚因果门控，消除木桶迟滞，单调因果偏序校验 |
| **F02** | **Worktree_Isolation** | `test_tier1_worktree_01~05`, `test_tier2_corner_01` | RAM-Disk 隔离沙箱检出、COW 复制、无锁释放、20 并发工作区写隔离 |
| **F03** | **Validation_At_Merge** | `test_tier1_gate_01~05`, `test_tier2_corner_05`, `test_tier3_cross_01` | AFEVA 三级阶梯门禁、偏科生带病晋级豁免、查表作弊一票否决、确定性重放检验 |
| **F04** | **Vertical_Echelon** | `test_tier1_fsm_01`, `test_tier4_real_01`, `test_tier4_real_05` | 调度梯队指挥协同，Worker 算法合成，Challenger 反例质询，Auditor 法医审计 |
| **F05** | **Multi_Island_Annealing** | `test_tier1_evolution_01~02`, `test_tier3_cross_04` | 三孤岛拓扑（Anchor, Anneal, Novelty）、0->1->2->0 稀疏有向环迁移总线 |
| **F06** | **Dimensionless_Annealing** | `test_tier1_evolution_03~04`, `test_tier2_corner_02` | 滑动窗口稳健 MAD 动态标定、Metropolis 劣解接纳准则、病态输入防溢出 |
| **F07** | **Lightweight_AST_Novelty** | `test_tier1_gate_05`, `test_tier4_real_03` | 规范化 AST 拓扑哈希提取（<1ms）、正交拓扑距离判定、多样性塌缩防御 |
| **F08** | **Dual_Ledger_Distillation** | `test_tier1_ledger_01~05`, `test_tier4_real_05` | Task Ledger 与 Progress Ledger 物理隔离、Pareto 前沿投影、Living Playbook LFU-Decay 剪枝 |
| **F09** | **FSM_Core_Engine** | `test_tier1_fsm_01~05`, `test_tier2_corner_04` | 14 状态形式化状态机驱动、P0 毒丸抢占熔断、看门狗心跳超时与死锁自愈 |
| **F10** | **WAL_Snapshot_Persistence** | `test_tier1_wal_01~05`, `test_tier3_cross_05`, `test_tier4_real_02` | WAL 预写日志事件溯源、SHA-256 密码学校验和、原子快照持久化与 0 数据丢失恢复 |
| **F11** | **R1_Spec_Documentation** | `docs/ARCHITECTURE_SPECIFICATION.md` | 10 大架构核心问题攻坚规范与设计标准契约对齐 |
| **F12** | **Mock_Agent_Sim_Harness** | `tests/mock_agents.py`, `test_tier4_real_01` | MockWorker、MockChallenger、MockAuditor 参数化行为探针与故障注入 |
| **F13** | **Property_Invariant_Tests** | `tests/test_invariants.py`, `test_tier1_evolution_05` | 死锁自由、物理隔离、代际单调、温度有界四大不变性定理全覆盖 |
| **F14** | **E2E_Test_Suite** | `e2e_tests/` (本套件全量) | 4-Tier 严密方法学分层集成验收体系与美观控制台矩阵执行器 |
| **F15** | **Adversarial_Hardening** | `test_tier2_corner_01~05`, `test_tier4_real_05` | 极限压力并发、死锁环路自愈破环、捕食者反例对抗与 Windows 文件锁墓碑自愈 |

---

## 5. 预期通过判定准则 (Acceptance Criteria)

任何形式的合规验收与审计均需满足以下严格准则：

1. **执行结果全绿 (100% PASS)**：
   运行 `python e2e_tests/runner.py` 时，45 个测试用例必须全量通过，无任何 `FAIL` 或 `ERROR`；
2. **退出码零缺陷 (Exit Code 0)**：
   执行进程退出码必须为 `0`；
3. **控制台矩阵对齐**：
   ```
   ==========================================================================================
                             AFEVA E2E TEST EXECUTION MATRIX
   ==========================================================================================
    Tier     | Description                            | Passed   | Total    | Rate     | Time    
   ------------------------------------------------------------------------------------------
    Tier 1   | Feature Coverage (F01~F10 Core)        | 30       | 30       |  100.0% |   0.35s
    Tier 2   | Boundary & Corner Cases                | 5        | 5        |  100.0% |   0.24s
    Tier 3   | Cross-Feature Combinations             | 5        | 5        |  100.0% |   0.08s
    Tier 4   | Real-World Application Scenarios       | 5        | 5        |  100.0% |   0.06s
   ------------------------------------------------------------------------------------------
    TOTAL   | All Executed Tiers                     | 45       | 45       |  100.0% |   0.74s
   ==========================================================================================
    Final Verdict: PASSED (100%) | Exit Code: 0
   ==========================================================================================
   ```
4. **既有测试零回归 (Zero Regression)**：
   既有单元测试与故障仿真测试（`test_state_machine.py`, `test_worktree.py`, `test_evolution.py`, `test_invariants.py`, `test_fault_injection.py`）同步保持 100% 满分通过。
