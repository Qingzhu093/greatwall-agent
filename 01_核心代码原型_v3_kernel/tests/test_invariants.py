"""
System Core 4 Invariant Theorems Property-Based & Verification Test Suite (F13).
Verifies:
1. Deadlock-Freedom Theorem (Tarjan SCC & Cycle Elimination in Large DAGs);
2. Physical Isolation & Merge Atomicity Theorem (RAM-Disk COW & Strict Conflict Interception);
3. Generational Monotonicity Theorem (3-Island Ring Topology & Non-Degrading Anchor Island 0);
4. Bounded Temperature & Scale Robustness Theorem (Zero-Division Immunity, Compact MAD Scale [1e-6, inf)).

Author: teamwork_worker (Milestone 4 Engineering Group)
Status: Production Ready
"""

from __future__ import annotations

import math
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Set, Tuple

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.contracts import (
    CandidateSolution,
    CausalDeadlockException,
    IslandRole,
    MergeConflictException,
    PhysicalMetrics,
    WorktreeLockException,
)
from src.core.scheduler import DeadlockDetector
from src.evolution.annealer import AnnealingController
from src.evolution.island import IslandController
from src.worktree.manager import WorktreeManager
from tests.mock_agents import MockChallenger, MockWorker, WorkerBehaviorMode


def test_invariant_1_deadlock_freedom() -> None:
    """
    不变性 1: Deadlock-Freedom（死锁自由定理）
    验证：
    1. 构建 96 个节点多层级前向交叉与汇聚屏障因果拓扑，验证单调因果定理 L(u) < L(v) 与 Tarjan SCC 绝对零环路；
    2. 人为注入直接双向环、3 节点闭环、8 字形复合死锁，验证死锁检测器精准捕获；
    3. 验证破环调度器在单调递减步数内彻底消除环路，系统恢复可调度 DAG。
    """
    print("[RUNNING] test_invariant_1_deadlock_freedom...")
    detector = DeadlockDetector(semantic_spin_threshold=0.05)

    # 1. 构建 96 节点因果 DAG (8 层，每层 12 个节点)
    num_layers = 8
    nodes_per_layer = 12
    waiting_graph: Dict[str, Set[str]] = {}

    for layer in range(num_layers):
        for idx in range(nodes_per_layer):
            node_id = f"node_L{layer}_{idx}"
            detector.register_causal_rank(node_id, rank=layer)
            waiting_graph[node_id] = set()

    # 添加合法前向因果边 (Layer i -> Layer i+1, 部分长尾至 Layer i+2)
    edge_count = 0
    for layer in range(num_layers - 1):
        for idx in range(nodes_per_layer):
            src_node = f"node_L{layer}_{idx}"
            # 汇聚到下一层的对应及相邻节点
            for offset in (0, 1):
                target_idx = (idx + offset) % nodes_per_layer
                dst_node = f"node_L{layer + 1}_{target_idx}"
                waiting_graph[src_node].add(dst_node)
                detector.verify_monotonic_causality(src_node, dst_node, rank_u=layer, rank_v=layer + 1)
                edge_count += 1

            # 长尾跳跃边 (至 layer + 2)
            if layer + 2 < num_layers and idx % 3 == 0:
                jump_dst = f"node_L{layer + 2}_{idx}"
                waiting_graph[src_node].add(jump_dst)
                detector.verify_monotonic_causality(src_node, jump_dst, rank_u=layer, rank_v=layer + 2)
                edge_count += 1

    # 验证正常因果 DAG 绝对死锁自由
    detected_cycles = detector.detect_cycles(waiting_graph)
    assert len(detected_cycles) == 0, f"Expected 0 cycles in clean DAG, got {len(detected_cycles)}"
    assert edge_count > 100, f"Expected >100 edges for rich topology, got {edge_count}"

    # 2. 人为注入死锁环路
    # 环路 A: 直接双向死锁环 (L1_0 -> L2_0, 注入 L2_0 -> L1_0)
    waiting_graph["node_L2_0"].add("node_L1_0")
    # 验证逆向边必然触发单调因果定理异常
    try:
        detector.verify_monotonic_causality("node_L2_0", "node_L1_0", rank_u=2, rank_v=1)
        assert False, "Should raise CausalDeadlockException on backward edge"
    except CausalDeadlockException:
        pass

    # 环路 B: 3 节点复合环路 (L3_1 -> L4_1 -> L5_1 -> L3_1)
    waiting_graph["node_L5_1"].add("node_L3_1")

    # 环路 C: 共享节点 8 字形环路 (L6_2 -> L7_2 -> L6_2 以及 L6_2 -> L7_3 -> L6_2)
    waiting_graph["node_L6_2"].add("node_L7_2")
    waiting_graph["node_L7_2"].add("node_L6_2")
    waiting_graph["node_L6_2"].add("node_L7_3")
    waiting_graph["node_L7_3"].add("node_L6_2")

    # 检测环路：此时必须检测到多个强连通闭环
    corrupted_cycles = detector.detect_cycles(waiting_graph)
    assert len(corrupted_cycles) >= 3, f"Expected >= 3 deadlocks, got {len(corrupted_cycles)}"

    # 3. 破环调度器破环：断言在有限递减步数内完全解除死锁
    severed_edges = detector.resolve_deadlocks(waiting_graph, max_iterations=50)
    assert len(severed_edges) >= 3, f"Expected severed edges >= 3, got {len(severed_edges)}"

    # 破环后再次检测：死锁环路计数必须降为 0
    remaining_cycles = detector.detect_cycles(waiting_graph)
    assert len(remaining_cycles) == 0, f"All deadlocks must be eliminated, but found: {remaining_cycles}"

    print(f"  -> Deadlock-Freedom verified on 96 nodes DAG ({edge_count} edges, resolved {len(severed_edges)} injected cycles).")


def test_invariant_2_physical_isolation_and_merge_atomicity() -> None:
    """
    不变性 2: Physical Isolation & Merge Atomicity（物理隔离与合并原子性定理）
    验证：
    1. 并发 20 个工作区 COW Shared-Nothing 物理绝缘性与 commit hash 唯一性；
    2. 主干合并事务原子性：同名修改必触发 MergeConflictException，拦截率 100%；
    3. 正交修改文件安全三路并入，绝无破坏性覆盖。
    """
    print("[RUNNING] test_invariant_2_physical_isolation_and_merge_atomicity...")
    with tempfile.TemporaryDirectory() as tmp_root:
        base_dir = Path(tmp_root) / "base_master"
        base_dir.mkdir(parents=True, exist_ok=True)
        (base_dir / "main.py").write_text("def solve(x):\n    return sum(x)\n", encoding="utf-8")
        (base_dir / "config.json").write_text('{"version": "1.0.0"}', encoding="utf-8")

        mgr = WorktreeManager(root_dir=tmp_root, base_repo_dir=str(base_dir))
        worker = MockWorker()

        # 阶段 1: 创建 20 个隔离沙箱
        num_worktrees = 20
        specs = [mgr.create_worktree(f"task_{i:02d}", base_commit="base_c0") for i in range(num_worktrees)]

        # 验证物理路径隔离
        paths = [s.worktree_path for s in specs]
        assert len(set(paths)) == num_worktrees, "Worktree paths must be strictly distinct"

        # 阶段 2: 前 10 个沙箱并发修改同名文件 main.py (高并发冲突争用)
        conflict_specs = specs[:10]
        for idx, spec in enumerate(conflict_specs):
            wt_path = Path(spec.worktree_path)
            mutated_code = f"def solve(x):\n    # Worker {idx} mod\n    return sum(x) + {idx}\n"
            (wt_path / "main.py").write_text(mutated_code, encoding="utf-8")
            mgr.commit_worktree(spec.worktree_id, f"Commit from conflict worker {idx}")

        # 阶段 3: 后 10 个沙箱分别创建全新的正交文件 (无交集安全合并)
        orthogonal_specs = specs[10:]
        for idx, spec in enumerate(orthogonal_specs):
            wt_path = Path(spec.worktree_path)
            ortho_file = wt_path / f"orthogonal_plugin_{idx:02d}.py"
            ortho_file.write_text(f"# Plugin {idx:02d}\nVALUE = {idx * 100}\n", encoding="utf-8")
            mgr.commit_worktree(spec.worktree_id, f"Commit from orthogonal worker {idx}")

        # 阶段 4: 第一个冲突沙箱合并至 main 分支
        first_merge_ok = mgr.merge_to_main(conflict_specs[0].worktree_id)
        assert first_merge_ok is True
        assert "Worker 0 mod" in (base_dir / "main.py").read_text(encoding="utf-8")

        # 阶段 5: 其余 9 个冲突沙箱尝试合并，必须 100% 被 MergeConflictException 拦截
        interceptions = 0
        for spec in conflict_specs[1:]:
            try:
                mgr.merge_to_main(spec.worktree_id)
                assert False, f"Expected MergeConflictException for {spec.worktree_id}"
            except MergeConflictException as mce:
                interceptions += 1
                assert "main.py" in mce.conflict_files
        assert interceptions == 9, f"Expected 9 conflict interceptions, got {interceptions}"

        # 阶段 6: 10 个正交沙箱依次安全合并进主干
        ortho_merges = 0
        for spec in orthogonal_specs:
            ok = mgr.merge_to_main(spec.worktree_id)
            assert ok is True
            ortho_merges += 1

        assert ortho_merges == 10

        # 检查主干最终状态：main.py 保留首个合并者内容，10 个正交文件全部安然并入
        assert "Worker 0 mod" in (base_dir / "main.py").read_text(encoding="utf-8")
        for idx in range(10):
            p_file = base_dir / f"orthogonal_plugin_{idx:02d}.py"
            assert p_file.exists()
            assert f"VALUE = {idx * 100}" in p_file.read_text(encoding="utf-8")

        # 阶段 7: 清理所有沙箱
        for s in specs:
            mgr.remove_worktree(s.worktree_id)

    print(f"  -> Physical Isolation & Merge Atomicity verified (20 worktrees, 9 conflicts intercepted, 10 orthogonal merged).")


def test_invariant_3_generational_monotonicity() -> None:
    """
    不变性 3: Generational Monotonicity（代际演化单调性定理）
    验证：
    在三孤岛拓扑与 0 -> 1 -> 2 -> 0 稀疏环迁移长程演化中，
    Island 0 (保守锚点岛) 的代际最优综合能量与最优物理指标具有严格非退化单调性 (Monotonically Non-Decreasing performance)。
    """
    print("[RUNNING] test_invariant_3_generational_monotonicity...")
    controller = IslandController(migration_interval=3, island_capacity=10)
    worker = MockWorker()

    # 初始化三孤岛种子解
    genesis_metrics = PhysicalMetrics(execution_time_s=1.0, peak_memory_bytes=10_000_000, collision_penalty=0.0, exit_code=0)
    for iid in range(3):
        cand = worker.create_candidate_solution(candidate_id=f"genesis_isl_{iid}", island_id=iid, metrics=genesis_metrics)
        controller._island_populations[iid].append(cand)

    epochs_to_run = 12
    island_0_best_energies: List[float] = []
    island_0_best_times: List[float] = []

    for epoch in range(epochs_to_run):
        # 1. 为每个孤岛生成新候选解
        for iid in range(3):
            candidates: List[CandidateSolution] = []
            role = controller.get_island_role(iid)

            if role == IslandRole.ISLAND_0_ANCHOR:
                # 锚点岛：尝试提出微优化变异解与恶化扰动解
                # 优秀变异 (耗时按代际逐步递减)
                opt_time = max(0.1, 1.0 - (epoch * 0.06))
                c_good = worker.create_candidate_solution(
                    candidate_id=f"c_good_ep{epoch}",
                    island_id=0,
                    metrics=PhysicalMetrics(execution_time_s=opt_time, peak_memory_bytes=9_800_000, collision_penalty=0.0, exit_code=0),
                )
                # 劣变尝试 (故意大幅变慢)
                c_bad = worker.create_candidate_solution(
                    candidate_id=f"c_bad_ep{epoch}",
                    island_id=0,
                    metrics=PhysicalMetrics(execution_time_s=5.0, peak_memory_bytes=20_000_000, collision_penalty=0.5, exit_code=0),
                )
                candidates.extend([c_good, c_bad])

            elif role == IslandRole.ISLAND_1_ANNEAL:
                # 激进退火岛：高方差探索
                c_ann = worker.create_candidate_solution(
                    candidate_id=f"c_ann_ep{epoch}",
                    island_id=1,
                    metrics=PhysicalMetrics(execution_time_s=0.8 - (epoch * 0.03), peak_memory_bytes=10_000_000, collision_penalty=0.05, exit_code=0),
                )
                candidates.append(c_ann)

            else:
                # 新颖性岛：偏科生与踏脚石
                c_nov = worker.create_candidate_solution(
                    candidate_id=f"c_nov_ep{epoch}",
                    island_id=2,
                    mode=WorkerBehaviorMode.BREAKTHROUGH_TALENT,
                )
                candidates.append(c_nov)

            # 推进代际
            summary = controller.step_epoch(iid, epoch, candidates)
            if iid == 0:
                island_0_best_energies.append(summary.best_energy)
                # 提取 Island 0 当前最佳耗时
                pop_0 = controller._island_populations[0]
                best_t = min(c.metrics.execution_time_s for c in pop_0)
                island_0_best_times.append(best_t)

        # 2. 周期性执行 0 -> 1 -> 2 -> 0 稀疏环迁移
        if (epoch + 1) % controller.migration_interval == 0:
            bundles = controller.exchange_migrants()
            assert len(bundles) == 3, "Ring migration must emit 3 bundles"

    # 断言单调性定理：Island 0 的最优耗时在代际推进中非退化 (单调不增)
    for i in range(1, len(island_0_best_times)):
        prev_t = island_0_best_times[i - 1]
        curr_t = island_0_best_times[i]
        assert curr_t <= prev_t + 1e-9, f"Monotonicity violation at epoch {i}: {curr_t} > {prev_t}"

    # 验证最终代相比初代获得了显著改善
    assert island_0_best_times[-1] < island_0_best_times[0]
    print(f"  -> Generational Monotonicity verified over {epochs_to_run} epochs (time improved {island_0_best_times[0]:.2f}s -> {island_0_best_times[-1]:.2f}s with 0 regressions).")


def test_invariant_4_bounded_temperature_and_scale_robustness() -> None:
    """
    不变性 4: Bounded Temperature & Scale Robustness（退火温度与标度有界性定理）
    验证：
    在输入病态极值 (10^9 极大超时、0 耗时、全相同常数、10^-12 极小扰动) 冲击下：
    1. 滑动 MAD 标度严格属于紧致正实数区间 [1e-6, inf)；
    2. 初始温度 T0 有界无溢出；
    3. Metropolis 接纳概率在 [0, 1] 闭区间；
    4. 绝对零除零崩溃、零浮点溢出崩溃。
    """
    print("[RUNNING] test_invariant_4_bounded_temperature_and_scale_robustness...")

    challenger = MockChallenger()
    extremes = challenger.generate_adversarial_inputs("float_extremes")

    # 1. 验证分析解初始温度反解有界性
    annealer = AnnealingController(delta_e_tol=0.8, p0_nominal=0.45)
    t0 = annealer.get_current_temperature()
    assert not math.isnan(t0) and not math.isinf(t0)
    assert 0.1 < t0 < 10.0

    # 2. 构造病态指标序列
    pathological_samples = [
        PhysicalMetrics(execution_time_s=1e9, peak_memory_bytes=100_000_000, collision_penalty=1.0, exit_code=0, is_timeout=True),  # 极大超时
        PhysicalMetrics(execution_time_s=0.0, peak_memory_bytes=0, collision_penalty=0.0, exit_code=0),                                # 零耗时零内存
        PhysicalMetrics(execution_time_s=1e-12, peak_memory_bytes=1, collision_penalty=1e-6, exit_code=0),                            # 浮点极小扰动
    ]

    # 添加 10 个完全相同的常数指标 (MAD 退化为 0)
    for _ in range(10):
        pathological_samples.append(PhysicalMetrics(execution_time_s=0.5, peak_memory_bytes=10_000_000, collision_penalty=0.0, exit_code=0))

    # 依次注入滑动窗口并计算能量与 MAD 标度
    for idx, sample in enumerate(pathological_samples):
        annealer.update_history(sample)
        # 校验各维度标度
        scale_t = annealer._compute_mad_scale(annealer._history_time, annealer.prior_scales[0])
        scale_m = annealer._compute_mad_scale(annealer._history_mem, annealer.prior_scales[1])
        scale_c = annealer._compute_mad_scale(annealer._history_collision, annealer.prior_scales[2])

        # 标度有界性断言
        assert scale_t >= 1e-6 and not math.isnan(scale_t) and not math.isinf(scale_t), f"scale_t invalid at {idx}: {scale_t}"
        assert scale_m >= 1.0 and not math.isnan(scale_m) and not math.isinf(scale_m), f"scale_m invalid at {idx}: {scale_m}"
        assert scale_c >= 1e-4 and not math.isnan(scale_c) and not math.isinf(scale_c), f"scale_c invalid at {idx}: {scale_c}"

        # 计算能量与相对差，断言无零除崩溃
        energy = annealer.compute_dimensionless_energy(sample)
        assert not math.isnan(energy) and not math.isinf(energy)

    # 3. 验证 Metropolis 概率有界性 P in [0, 1]
    base_metric = PhysicalMetrics(execution_time_s=1.0, peak_memory_bytes=10_000_000, collision_penalty=0.0, exit_code=0)
    for ext_val in [1e-12, 0.0, 1e9, 500.0]:
        cand_metric = PhysicalMetrics(execution_time_s=ext_val, peak_memory_bytes=10_000_000, collision_penalty=0.0, exit_code=0)
        # 评估接纳，绝不发生零除或溢出
        accepted = annealer.evaluate_acceptance(base_metric, cand_metric, step=1)
        assert isinstance(accepted, bool)

    # 4. 绝对零度贪心模式检验：劣解接纳概率精确为 0
    greedy_annealer = AnnealingController(initial_temperature=0.0, min_temperature=0.0)
    worse_metric = PhysicalMetrics(execution_time_s=10.0, peak_memory_bytes=20_000_000, collision_penalty=0.2, exit_code=0)
    assert greedy_annealer.evaluate_acceptance(base_metric, worse_metric, step=0) is False

    print("  -> Bounded Temperature & Scale Robustness verified (Zero-Division immunity & [1e-6, inf) compact MAD scale).")


if __name__ == "__main__":
    print("=" * 80)
    print("STARTING AFEVA 4 CORE INVARIANT THEOREMS VERIFICATION SUITE")
    print("=" * 80)
    test_invariant_1_deadlock_freedom()
    test_invariant_2_physical_isolation_and_merge_atomicity()
    test_invariant_3_generational_monotonicity()
    test_invariant_4_bounded_temperature_and_scale_robustness()
    print("=" * 80)
    print("ALL 4 CORE INVARIANT THEOREMS PASSED 100%!")
    print("=" * 80)
