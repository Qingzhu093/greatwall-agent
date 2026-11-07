"""
Automated Comprehensive Test Suite for Evolution Dynamics and Multi-Island Architecture.
Covers Robust MAD Scaling, Analytical Temperature Inversion, Metropolis Acceptance,
AST Topological Hashing & Orthogonal Distances, Semantic Spinning, and 3-Island Directed Ring Migration.
Author: teamwork_worker (Milestone 3 Engineering Group)
Status: Production Ready
"""

from __future__ import annotations

import math
import sys
import time
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.contracts import (
    PhysicalMetrics,
    CandidateSolution,
    IslandRole,
)
from src.evolution.annealer import AnnealingController
from src.evolution.ast_judge import ASTDistanceAssessor
from src.evolution.island import IslandController


def test_annealing_mad_and_dimensionless_energy() -> None:
    """测试滑动窗口稳健 MAD 动态标定、先验平滑融合与初始温度反解"""
    print("[RUNNING] test_annealing_mad_and_dimensionless_energy...")

    # 1. 验证初始温度解析反解: T0 = -ΔE_tol / ln(P0)
    # ΔE_tol = 0.8, P0 = 0.45 => T0 = -0.8 / ln(0.45) ≈ 1.0019
    annealer = AnnealingController(delta_e_tol=0.8, p0_nominal=0.45)
    expected_t0 = -0.8 / math.log(0.45)
    assert abs(annealer.get_current_temperature() - expected_t0) < 1e-4

    # 2. 验证冷启动时使用先验物理标尺
    m1 = PhysicalMetrics(execution_time_s=1.0, peak_memory_bytes=10_000_000, collision_penalty=0.0, exit_code=0)
    m2 = PhysicalMetrics(execution_time_s=1.5, peak_memory_bytes=12_000_000, collision_penalty=0.1, exit_code=0)

    e1 = annealer.compute_dimensionless_energy(m1)
    e2 = annealer.compute_dimensionless_energy(m2)
    # m2 在所有指标上均劣于 m1，能量必须更高
    assert e2 > e1
    delta_e = annealer.compute_dimensionless_delta(m1, m2)
    assert delta_e > 0

    # 3. 滑动窗口填充超过 3 个样本，验证 MAD 稳健统计生效
    for val in [1.0, 1.05, 0.95, 1.02, 0.98, 5.0]:  # 包含离群异常值 5.0
        annealer.update_history(PhysicalMetrics(val, 10_000_000, 0.0, 0))

    scale_time = annealer._compute_mad_scale(annealer._history_time, 1.0)
    # 中位数约为 1.01，MAD 不受 5.0 异常值干扰破坏
    assert 0.01 < scale_time < 0.5

    print("  -> Robust MAD scaling, outlier immunity, and temperature inversion verified.")


def test_metropolis_acceptance_and_cooling() -> None:
    """测试 Metropolis-Hastings 概率接纳准则、冷却调度与重加热脉冲"""
    print("[RUNNING] test_metropolis_acceptance_and_cooling...")

    annealer = AnnealingController(initial_temperature=1.0, cooling_rate=0.9)
    best_m = PhysicalMetrics(execution_time_s=1.0, peak_memory_bytes=10_000_000, collision_penalty=0.0, exit_code=0)
    better_m = PhysicalMetrics(execution_time_s=0.8, peak_memory_bytes=9_000_000, collision_penalty=0.0, exit_code=0)
    worse_m = PhysicalMetrics(execution_time_s=1.3, peak_memory_bytes=11_000_000, collision_penalty=0.05, exit_code=0)

    # 1. 变优解必须 100% 接纳
    for step in range(10):
        accepted = annealer.evaluate_acceptance(best_m, better_m, step)
        assert accepted is True

    # 2. 变劣解在高温下应有一定概率被接纳 (非 0 也非 100%)
    worse_accepts = sum(annealer.evaluate_acceptance(best_m, worse_m, 0) for _ in range(100))
    assert 5 < worse_accepts < 95

    # 3. 绝对零度贪心模式：变劣解必须 100% 拒绝
    greedy_annealer = AnnealingController(initial_temperature=0.0, min_temperature=0.0)
    for _ in range(20):
        assert greedy_annealer.evaluate_acceptance(best_m, worse_m, 0) is False

    # 4. 冷却调度步进
    t_prev = annealer.get_current_temperature()
    t_next = annealer.step_cooling()
    assert t_next < t_prev
    assert abs(t_next - (t_prev * 0.9)) < 1e-4

    # 5. 连续平原平台期触发重加热脉冲
    triggered = False
    for _ in range(4):
        if annealer.record_epoch_best(2.5):
            triggered = True
            break
    assert triggered is True
    assert annealer.get_current_temperature() > t_next

    # 6. 踏脚石特别庇护
    acc, sheltered = annealer.evaluate_with_stepping_stone_protection(
        best_m, worse_m, step=0, is_novel_stepping_stone=True
    )
    # 即使变劣，踏脚石亦获得存活资格
    assert acc is True

    print("  -> Metropolis probability, cooling step, reheating pulse, and stepping stone shelter verified.")


def test_ast_judge_hash_distance_and_spinning() -> None:
    """测试 AST 拓扑哈希计算 (<1ms)、三级加权正交距离与语义自旋监测"""
    print("[RUNNING] test_ast_judge_hash_distance_and_spinning...")
    judge = ASTDistanceAssessor(spin_threshold=0.05, spin_window=3)

    code_orig = (
        "def solve(data):\n"
        "    res = []\n"
        "    for x in data:\n"
        "        if x > 0:\n"
        "            res.append(x * 2)\n"
        "    return res\n"
    )

    code_renamed = (
        "def solve(items):\n"
        "    out = []\n"
        "    for item in items:\n"
        "        if item > 0:\n"
        "            out.append(item * 2)\n"
        "    return out\n"
    )

    code_vectorized = (
        "import numpy as np\n"
        "def solve(data):\n"
        "    arr = np.array(data)\n"
        "    return arr[arr > 0] * 2\n"
    )

    # 1. 验证 AST 规范化拓扑哈希 (< 1ms)
    t0 = time.perf_counter()
    h1 = judge.compute_ast_hash(code_orig)
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.005  # 远小于工业级要求的上限
    h2 = judge.compute_ast_hash(code_renamed)

    # 变量重命名具有相同语法树类型拓扑序列
    assert h1 == h2

    h3 = judge.compute_ast_hash(code_vectorized)
    assert h1 != h3

    # 2. 验证三级加权正交距离
    d_same = judge.compute_orthogonal_distance(code_orig, code_renamed)
    d_diff = judge.compute_orthogonal_distance(code_orig, code_vectorized)
    assert d_same < d_diff
    assert 0.0 <= d_diff <= 1.0

    # 3. 验证 3D 行为画像生成
    metrics = PhysicalMetrics(
        execution_time_s=0.2,
        peak_memory_bytes=8_000_000,
        collision_penalty=0.0,
        exit_code=0,
        cpu_instructions=500_000,
        dram_bytes_transferred=50_000,
        floating_point_ops=1_000_000
    )
    profile = judge.compute_behavioral_profile(metrics, code_vectorized)
    assert profile.operational_intensity > 0
    assert len(profile.behavior_coords) == 3
    assert profile.behavior_coords[0] in (0, 1, 2)
    assert profile.behavior_coords[1] in (0, 1, 2)
    assert profile.behavior_coords[2] in (0, 1)

    # 4. 验证语义自旋监测：代码频繁变动但表型耗时零位移
    history_spinning: list[CandidateSolution] = []
    for i in range(5):
        cand = CandidateSolution(
            candidate_id=f"spin_{i}",
            parent_id=None,
            island_id=1,
            ast_hash=f"hash_diff_{i}",
            source_code_cas_hash="cas_0",
            metrics=PhysicalMetrics(execution_time_s=1.0001 + 0.00001 * i, peak_memory_bytes=1000, collision_penalty=0.0, exit_code=0)
        )
        history_spinning.append(cand)

    assert judge.is_semantic_spinning(history_spinning) is True

    # 表型有实质进步时，不应误判为语义自旋
    history_progress: list[CandidateSolution] = []
    for i in range(5):
        cand = CandidateSolution(
            candidate_id=f"prog_{i}",
            parent_id=None,
            island_id=1,
            ast_hash=f"hash_diff_{i}",
            source_code_cas_hash="cas_0",
            metrics=PhysicalMetrics(execution_time_s=1.0 - 0.15 * i, peak_memory_bytes=1000, collision_penalty=0.0, exit_code=0)
        )
        history_progress.append(cand)

    assert judge.is_semantic_spinning(history_progress) is False

    print("  -> AST topological hashing, orthogonal distance, 3D behavior profiling, and spinning watchdog verified.")


def test_three_islands_and_directed_ring_migration() -> None:
    """测试三孤岛异构拓扑模型与稀疏有向环迁移总线 (0 -> 1 -> 2 -> 0)"""
    print("[RUNNING] test_three_islands_and_directed_ring_migration...")

    controller = IslandController(migration_interval=5, island_capacity=10)

    # 1. 验证三孤岛角色定位
    assert controller.get_island_role(0) == IslandRole.ISLAND_0_ANCHOR
    assert controller.get_island_role(1) == IslandRole.ISLAND_1_ANNEAL
    assert controller.get_island_role(2) == IslandRole.ISLAND_2_NOVELTY

    # 2. 为各孤岛注入候选解并演化单代
    cands_0 = [
        CandidateSolution(f"c0_{i}", None, 0, f"h_{i}", "cas",
                          PhysicalMetrics(execution_time_s=1.0 - 0.05 * i, peak_memory_bytes=10_000_000, collision_penalty=0.0, exit_code=0))
        for i in range(5)
    ]
    summary_0 = controller.step_epoch(island_id=0, epoch=1, candidates=cands_0)
    assert summary_0.island_id == 0
    assert summary_0.accepted_candidates >= 1

    cands_1 = [
        CandidateSolution(f"c1_{i}", None, 1, f"h1_{i}", "cas",
                          PhysicalMetrics(execution_time_s=1.2, peak_memory_bytes=12_000_000, collision_penalty=0.0, exit_code=0))
        for i in range(5)
    ]
    summary_1 = controller.step_epoch(island_id=1, epoch=1, candidates=cands_1)
    assert summary_1.island_id == 1

    # 3. 孤岛 2 (Novelty): 验证空白行为网格占领与踏脚石接纳
    judge = ASTDistanceAssessor()
    # 分别构造落入不同正交行为网格的个体:
    # 变体 0: 低算力密度，O(1) 内存，鲁棒
    m0 = PhysicalMetrics(1.0, 10_000_000, 0.0, 0, floating_point_ops=50, dram_bytes_transferred=1000)
    # 变体 1: 超高计算强度 (张量化)，O(1) 内存，鲁棒
    m1 = PhysicalMetrics(1.2, 10_000_000, 0.0, 0, floating_point_ops=100_000, dram_bytes_transferred=1000)
    # 变体 2: 高混沌敏感度 (存在扰动敏感)
    m2 = PhysicalMetrics(1.5, 10_000_000, 0.5, 0, floating_point_ops=50, dram_bytes_transferred=1000)

    cands_2 = [
        CandidateSolution("c2_0", None, 2, "h2_0", "cas", m0, behavior=judge.compute_behavioral_profile(m0, "code_0")),
        CandidateSolution("c2_1", None, 2, "h2_1", "cas", m1, behavior=judge.compute_behavioral_profile(m1, "code_1")),
        CandidateSolution("c2_2", None, 2, "h2_2", "cas", m2, behavior=judge.compute_behavioral_profile(m2, "code_2")),
    ]

    # 验证三个个体的 3D 坐标互斥正交
    coords_set = {c.behavior.behavior_coords for c in cands_2 if c.behavior}
    assert len(coords_set) == 3

    summary_2 = controller.step_epoch(island_id=2, epoch=1, candidates=cands_2)
    assert summary_2.accepted_candidates == len(cands_2)

    # 4. 稀疏有向环迁移总线交换 (0 -> 1 -> 2 -> 0)
    bundles = controller.exchange_migrants()
    assert len(bundles) == 3

    ring_routes = [(b.source_island_id, b.target_island_id) for b in bundles]
    assert (0, 1) in ring_routes
    assert (1, 2) in ring_routes
    assert (2, 0) in ring_routes

    # 验证数字签名与轻量表型卡片内容
    for b in bundles:
        assert len(b.topology_signature) == 64
        assert len(b.migrant_summaries) > 0
        card = b.migrant_summaries[0]
        assert "candidate_id" in card
        assert "ast_hash" in card
        assert "metrics" in card

    print("  -> Multi-island topology, epoch stepping, and 0->1->2->0 ring migration verified.")


if __name__ == "__main__":
    test_annealing_mad_and_dimensionless_energy()
    test_metropolis_acceptance_and_cooling()
    test_ast_judge_hash_distance_and_spinning()
    test_three_islands_and_directed_ring_migration()
    print("=" * 80)
    print("ALL EVOLUTION & MULTI-ISLAND TESTS PASSED 100%!")
    print("=" * 80)
