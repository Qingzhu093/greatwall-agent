"""
Tier 5 Evolution Dynamics & Adversarial Cheating Counteraction Probes (challenger_m5_2).
Milestone 5 Phase 2 Empirical Crucible Test Suite.

Probes Included:
1. Probe 1: Polymorphic Obfuscation & Advanced Lookup Cheating Penetration (Closure, Dynamic Table, Lambda Map)
2. Probe 2: 50-Epoch Long-Horizon Evolution & Anchor Island Monotonicity Under Severe Degradation Shocks (+1000% penalty)
3. Probe 3: Diversity Collapse Defense & AST Topological Novelty Sandbox Effectiveness (90% Monopolistic Dominance)
4. Probe 4: Full E2E & Core Test Suite Zero-Regression Verification

Author: challenger_m5_2 (Empirical Challenger Group)
Status: Verification Ready
"""

from __future__ import annotations

import ast
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
    DiffSpec,
    GateStatus,
    GateVerdict,
    IslandRole,
    PhysicalMetrics,
    WorktreeSpec,
)
from src.evolution.annealer import AnnealingController
from src.evolution.ast_judge import ASTDistanceAssessor
from src.evolution.island import IslandController
from src.worktree.manager import WorktreeManager
from src.worktree.validator import ValidationGate
from tests.mock_agents import MockAuditor, MockWorker, WorkerBehaviorMode


# =============================================================================
# 探针 1：多态变形与高级混淆查表作弊穿透测试
# =============================================================================

def test_probe_1_polymorphic_obfuscated_lookup_cheats() -> None:
    """
    探针 1：多态变形与高级混淆查表作弊穿透
    
    对抗目标：
    合成 3 类高级查表变种代码，试图绕过 AFEVA 门禁与法医审计：
    1. 闭包字典字面量（嵌套在闭包函数与工厂内部，>30 entries）；
    2. Lambda 查表映射（嵌套于高阶匿名函数内，>30 entries）；
    3. 动态构建大表（通过循环和运行时动态构建 >30 条目表，试图逃逸纯字面量 AST 字典匹配）。
    
    实证检验：
    AFEVA Tier 2 门禁是否能通过深度 AST 语法树遍历与 Level 1/2 捕食者对抗测试实现 100% 拒止！
    """
    print("\n[PROBE 1] Testing Polymorphic Obfuscated Lookup Cheats Penetration...")

    with tempfile.TemporaryDirectory() as tmp_root:
        base_dir = Path(tmp_root) / "base_repo"
        base_dir.mkdir(parents=True, exist_ok=True)
        (base_dir / "main.py").write_text("def solve(x):\n    return sum(x)\n", encoding="utf-8")

        mgr = WorktreeManager(root_dir=tmp_root, base_repo_dir=str(base_dir))
        gate = ValidationGate(baseline_execution_time_s=1.0)
        auditor = MockAuditor(max_lookup_table_entries=30)

        # ---------------------------------------------------------------------
        # 变种 1：闭包字典字面量 (Closure with 38 entries embedded inside inner scope)
        # ---------------------------------------------------------------------
        closure_cheat_code = (
            "def make_solver():\n"
            "    # 闭包深层嵌套字典 (38 个硬编码条目)\n"
            "    closure_table = {\n"
            + ",\n".join(f"        {i}: {i * 2}" for i in range(38)) + "\n"
            "    }\n"
            "    def _inner(data):\n"
            "        return sum(closure_table.get(x, x) for x in data)\n"
            "    return _inner\n\n"
            "solve = make_solver()\n"
        )
        wt_closure = mgr.create_worktree("task_probe1_closure", base_commit="base_c0")
        (Path(wt_closure.worktree_path) / "main.py").write_text(closure_cheat_code, encoding="utf-8")
        diff_closure = DiffSpec("c0", "c1", ("main.py",), "solve", 45, 5, 0.95)

        # Tier 1 冒烟
        v1_closure = gate.validate_tier1(wt_closure, diff_closure)
        assert v1_closure.status in (GateStatus.APPROVE, GateStatus.PROBATIONARY_PASS), (
            f"Expected Tier 1 to allow smoke test, got {v1_closure.status}"
        )

        # Tier 2 必须 100% 拒止 (AST 遍历识别闭包内部的超标字典)
        v2_closure = gate.validate_tier2(wt_closure, diff_closure)
        assert v2_closure.status == GateStatus.REJECT, (
            f"Closure cheat MUST be REJECTED at Tier 2! Got: {v2_closure.status}"
        )
        assert any("CHEAT_LOOKUP_TABLE detected" in d for d in v2_closure.diagnostics), (
            f"Expected CHEAT_LOOKUP_TABLE diagnostic, got: {v2_closure.diagnostics}"
        )
        print("  -> Variant 1 (Closure Dictionary > 30 entries): 100% Intercepted (REJECT).")

        # ---------------------------------------------------------------------
        # 变种 2：Lambda 查表映射 (Lambda with 42 entries embedded in parameter)
        # ---------------------------------------------------------------------
        lambda_cheat_code = (
            "# 高阶 Lambda 查表硬编码 (42 个条目)\n"
            "solve = (lambda tbl: lambda data: sum(tbl.get(x, x) for x in data))({\n"
            + ",\n".join(f"    {i}: {i * 3}" for i in range(42)) + "\n"
            "})\n"
        )
        wt_lambda = mgr.create_worktree("task_probe1_lambda", base_commit="base_c0")
        (Path(wt_lambda.worktree_path) / "main.py").write_text(lambda_cheat_code, encoding="utf-8")
        diff_lambda = DiffSpec("c0", "c2", ("main.py",), "solve", 50, 4, 0.95)

        # Tier 1 冒烟
        v1_lambda = gate.validate_tier1(wt_lambda, diff_lambda)
        assert v1_lambda.status in (GateStatus.APPROVE, GateStatus.PROBATIONARY_PASS)

        # Tier 2 必须 100% 拒止 (AST 遍历识别 Lambda 参数中的超标字典)
        v2_lambda = gate.validate_tier2(wt_lambda, diff_lambda)
        assert v2_lambda.status == GateStatus.REJECT, (
            f"Lambda cheat MUST be REJECTED at Tier 2! Got: {v2_lambda.status}"
        )
        assert any("CHEAT_LOOKUP_TABLE detected" in d for d in v2_lambda.diagnostics)
        print("  -> Variant 2 (Lambda Lookup Table > 30 entries): 100% Intercepted (REJECT).")

        # ---------------------------------------------------------------------
        # 变种 3：动态构建大表 (Dynamic table generation attempting to bypass AST Dict)
        # ---------------------------------------------------------------------
        # 试图在运行时动态构建 60 个条目，规避 AST 字面量字典匹配，
        # 但在面对 Level 1/2 捕食者测试集（包含大范围和负数如 -999999）时，由于缺乏完整泛化而崩溃或产生惩罚
        dynamic_cheat_code = (
            "def solve(data):\n"
            "    # 运行时动态构建 60 条目字典 (无静态大字面量字典)\n"
            "    table = {}\n"
            "    for i in range(60):\n"
            "        table[i] = i\n"
            "    # 仅命中 0~59，遇到其他未命中项抛出 KeyError 或返回非法值\n"
            "    total = 0\n"
            "    for x in data:\n"
            "        total += table[x]\n"
            "    return total\n"
        )
        wt_dynamic = mgr.create_worktree("task_probe1_dynamic", base_commit="base_c0")
        (Path(wt_dynamic.worktree_path) / "main.py").write_text(dynamic_cheat_code, encoding="utf-8")
        diff_dynamic = DiffSpec("c0", "c3", ("main.py",), "solve", 15, 3, 0.8)

        # Tier 2 捕食者对抗测试 (Level 2 注入 -999999 与超过 60 的数，触发 KeyError，exit_code != 0)
        v2_dynamic = gate.validate_tier2(wt_dynamic, diff_dynamic)
        assert v2_dynamic.status in (GateStatus.REJECT, GateStatus.RETRY_WITH_PATCH), (
            f"Dynamic lookup cheat MUST NOT pass Tier 2! Got: {v2_dynamic.status}"
        )
        assert v2_dynamic.status != GateStatus.APPROVE, "Dynamic cheat fraudulently passed Tier 2!"
        assert any("Predator confrontation failed" in d for d in v2_dynamic.diagnostics), (
            f"Expected Predator confrontation failure diagnostics, got: {v2_dynamic.diagnostics}"
        )
        print("  -> Variant 3 (Dynamic Table Generation): 100% Intercepted by Predator Test (RETRY_WITH_PATCH/REJECT).")

        # 综合法医审计核查
        audit_res = auditor.audit_candidate(wt_closure, v1_closure.evaluated_metrics)
        assert audit_res.is_clean_pass() is False

        # 清理
        mgr.remove_worktree(wt_closure.worktree_id)
        mgr.remove_worktree(wt_lambda.worktree_id)
        mgr.remove_worktree(wt_dynamic.worktree_id)

    print(">>> [PROBE 1 RESULT: CONFIRMED] All polymorphic lookup cheats 100% intercepted by AFEVA Tier 2 Gate.")


# =============================================================================
# 探针 2：超长程 50 代演化与极端劣解冲击下的 Anchor 岛单调性测试
# =============================================================================

def test_probe_2_fifty_epochs_anchor_monotonicity_under_severe_shocks() -> None:
    """
    探针 2：超长程 50 代演化与极端劣解冲击下的 Anchor 岛单调性
    
    对抗目标：
    在 50 代三孤岛（Anchor=0, Anneal=1, Novelty=2）演化与 0->1->2->0 环形迁移总线中，
    在激进退火岛（Island 1）每代注入持续的高强度极端劣解（耗时增加 1000% ~ 2500%，内存激增，甚至崩溃），
    并借助多次周期迁移（每 5 代 1 次迁移，共 10 次迁移跨岛渗透）。
    
    实证检验：
    Anchor 岛（Island 0）的代际最优综合能量与物理指标必须 100% 保持代际非递减（严格单调递优，零性能倒退）。
    """
    print("\n[PROBE 2] Testing 50-Epoch Long-Horizon Evolution & Anchor Monotonicity Under +1000% Shocks...")

    epochs_to_run = 50
    migration_interval = 5
    controller = IslandController(migration_interval=migration_interval, island_capacity=15)
    worker = MockWorker()

    # 初始化三孤岛初始种子解 (耗时 1.0s, 内存 10MB)
    genesis_metrics = PhysicalMetrics(
        execution_time_s=1.0,
        peak_memory_bytes=10_000_000,
        collision_penalty=0.0,
        exit_code=0
    )
    for iid in range(3):
        cand = worker.create_candidate_solution(
            candidate_id=f"genesis_isl_{iid}",
            island_id=iid,
            metrics=genesis_metrics
        )
        controller._island_populations[iid].append(cand)

    island_0_best_energies: List[float] = []
    island_0_best_times: List[float] = []
    migrations_executed = 0

    annealer_anchor = controller._annealers[0]

    for epoch in range(epochs_to_run):
        # 1. 为三孤岛生成本代候选解
        for iid in range(3):
            candidates: List[CandidateSolution] = []
            role = controller.get_island_role(iid)

            if role == IslandRole.ISLAND_0_ANCHOR:
                # 锚点岛：提出微小优化变异解与偶发的扰动解
                # 优秀候选：耗时平稳微步递减 (从 1.0s 逐渐逼近 0.15s)
                improved_time = max(0.15, 1.0 - (epoch * 0.018))
                c_opt = worker.create_candidate_solution(
                    candidate_id=f"c0_opt_ep{epoch}",
                    island_id=0,
                    metrics=PhysicalMetrics(
                        execution_time_s=improved_time,
                        peak_memory_bytes=9_500_000,
                        collision_penalty=0.0,
                        exit_code=0
                    )
                )
                # 本地恶化尝试 (故意变慢)
                c_bad_local = worker.create_candidate_solution(
                    candidate_id=f"c0_bad_ep{epoch}",
                    island_id=0,
                    metrics=PhysicalMetrics(
                        execution_time_s=3.5,
                        peak_memory_bytes=20_000_000,
                        collision_penalty=0.4,
                        exit_code=0
                    )
                )
                candidates.extend([c_opt, c_bad_local])

            elif role == IslandRole.ISLAND_1_ANNEAL:
                # 激进退火岛：遭遇极端恶化冲击 (+1000% ~ +2500% 耗时剧增与崩溃毒丸)
                # 注入极端劣解群
                for shock_idx in range(4):
                    bad_time = 10.0 + shock_idx * 5.0  # 10s ~ 25s (增加 1000% ~ 2500%)
                    c_shock = worker.create_candidate_solution(
                        candidate_id=f"shock_ep{epoch}_{shock_idx}",
                        island_id=1,
                        metrics=PhysicalMetrics(
                            execution_time_s=bad_time,
                            peak_memory_bytes=80_000_000,
                            collision_penalty=0.8,
                            exit_code=0 if shock_idx < 3 else 1  # 偶发崩溃
                        )
                    )
                    candidates.append(c_shock)

            else:
                # 新颖性岛：探索新颖多样性分支
                c_novel = worker.create_candidate_solution(
                    candidate_id=f"c2_novel_ep{epoch}",
                    island_id=2,
                    metrics=PhysicalMetrics(
                        execution_time_s=0.9,
                        peak_memory_bytes=8_000_000,
                        collision_penalty=0.0,
                        exit_code=0
                    )
                )
                candidates.append(c_novel)

            # 推进代际演化
            summary = controller.step_epoch(island_id=iid, epoch=epoch, candidates=candidates)
            if iid == 0:
                island_0_best_energies.append(summary.best_energy)
                # 获取实际当前最优个体的耗时
                best_cand = controller._island_populations[0][0]
                island_0_best_times.append(best_cand.metrics.execution_time_s)

        # 2. 周期性执行迁移总线交换 (0 -> 1 -> 2 -> 0)
        if (epoch + 1) % migration_interval == 0:
            bundles = controller.exchange_migrants()
            migrations_executed += len(bundles)

    # -------------------------------------------------------------------------
    # 严格不变性实证核验
    # -------------------------------------------------------------------------
    assert len(island_0_best_times) == 50, f"Expected 50 epochs, got {len(island_0_best_times)}"
    assert migrations_executed >= 20, f"Expected multiple migrations, got {migrations_executed}"

    # 1. 验证物理耗时指标严格代际非递退 (耗时单调递减，绝不发生性能倒退)
    monotonicity_violations_time = 0
    for ep in range(len(island_0_best_times) - 1):
        t_curr = island_0_best_times[ep]
        t_next = island_0_best_times[ep + 1]
        if t_next > t_curr + 1e-9:
            monotonicity_violations_time += 1
            print(f"  [VIOLATION] Epoch {ep} -> {ep+1}: Execution time degraded from {t_curr:.4f}s to {t_next:.4f}s")

    assert monotonicity_violations_time == 0, (
        f"Island 0 violated execution time monotonicity! Total violations: {monotonicity_violations_time}"
    )

    # 2. 验证固定统一标尺下的综合能量严格单调非递减 (消除滑动窗口 MAD 动态收缩引入的尺度坐标漂移)
    # 统一使用基准退火标尺对各代最优个体计算客观能量
    fixed_scale_annealer = AnnealingController(
        initial_temperature=0.0,
        min_temperature=0.0,
        prior_scales=(1.0, 10_000_000.0, 0.1)
    )
    pop_best_individuals = [
        # 从每代记录提取最佳个体
        controller._island_populations[0][0]
    ]
    # 在固定先验标尺下，耗时单调递减必然蕴含客观能量单调递减
    for ep in range(len(island_0_best_times) - 1):
        m_curr = PhysicalMetrics(island_0_best_times[ep], 9_500_000, 0.0, 0)
        m_next = PhysicalMetrics(island_0_best_times[ep + 1], 9_500_000, 0.0, 0)
        e_curr_fixed = fixed_scale_annealer.compute_dimensionless_energy(m_curr)
        e_next_fixed = fixed_scale_annealer.compute_dimensionless_energy(m_next)
        assert e_next_fixed <= e_curr_fixed + 1e-9, (
            f"Objective fixed-scale energy degraded at epoch {ep}->{ep+1}: {e_curr_fixed} -> {e_next_fixed}"
        )

    # 3. 验证面对激进岛 10 次迁移注入与本地劣解，Anchor 岛绝对零接纳劣解
    pop_0 = controller._island_populations[0]
    for cand in pop_0:
        # 种群内保留的个体耗时绝不允许超过初始基准 1.0s (即无任何 +1000% 劣解被接纳)
        assert cand.metrics.execution_time_s <= 1.0 + 1e-7, (
            f"Contaminated candidate found in Anchor Island: time={cand.metrics.execution_time_s}s"
        )
        assert cand.metrics.exit_code == 0, "Crashed candidate contaminated Anchor Island!"
        assert cand.metrics.collision_penalty == 0.0, "High penalty candidate contaminated Anchor Island!"

    # 4. 验证终态性能显著优于初始状态 (零性能倒退，性能提升 > 80%)
    init_time = island_0_best_times[0]
    final_time = island_0_best_times[-1]
    assert final_time <= init_time, f"Final time {final_time:.4f}s degraded compared to init {init_time:.4f}s"
    assert final_time <= 0.20, f"Expected long horizon convergence <= 0.20s, got {final_time:.4f}s"
    speedup = (init_time - final_time) / init_time * 100.0

    print(f"  -> Ran 50 Epochs, executed {migrations_executed} ring migrations across 3 islands.")
    print(f"  -> Island 0 Best Time: {init_time:.4f}s -> {final_time:.4f}s (Speedup: +{speedup:.1f}%, Violations: 0).")
    print(f"  -> All {len(pop_0)} resident candidates in Anchor Island verified 100% free of shock contamination.")
    print(">>> [PROBE 2 RESULT: CONFIRMED] Anchor Island Monotonicity 100% Maintained Under Severe Shocks.")


# =============================================================================
# 探针 3：多样性塌缩防御与 AST 拓扑新颖性沙箱特区有效性测试
# =============================================================================

def test_probe_3_diversity_collapse_defense_and_ast_novelty_sandbox() -> None:
    """
    探针 3：多样性塌缩防御与 AST 拓扑新颖性沙箱特区有效性
    
    对抗目标：
    构造极端单一强势解法垄断场景（占据种群 90% 份额），
    检验 Island 2（新颖性沙箱特区，MAP-Elites 行为网格与正交 AST 拓扑判定）
    能否识别并制度化接纳非典型创新解（即使能量初生期稍弱），
    防止种群多样性彻底归一塌缩，维持健康的 Vendi Score 表型熵。
    """
    print("\n[PROBE 3] Testing Diversity Collapse Defense & AST Novelty Sandbox Effectiveness...")

    judge = ASTDistanceAssessor(spin_threshold=0.05, spin_window=3)
    worker = MockWorker()

    # 1. 模拟极端垄断解法 A (90% 种群垄断，单一简单的遍历求和 AST 拓扑)
    code_monopoly = (
        "def solve(data):\n"
        "    s = 0\n"
        "    for x in data:\n"
        "        s += x\n"
        "    return s\n"
    )
    hash_monopoly = judge.compute_ast_hash(code_monopoly)

    # 2. 构造非典型创新分支解法 B (正交向量化/生成器表达式，AST 拓扑显著不同)
    code_novel_vector = (
        "import numpy as np\n"
        "def solve(data):\n"
        "    arr = np.array(data, dtype=np.int64)\n"
        "    return int(np.sum(arr))\n"
    )
    hash_novel_vector = judge.compute_ast_hash(code_novel_vector)

    # 3. 构造非典型创新分支解法 C (递归/分治拓扑结构)
    code_novel_divide = (
        "def solve(data):\n"
        "    if not data:\n"
        "        return 0\n"
        "    if len(data) == 1:\n"
        "        return data[0]\n"
        "    mid = len(data) // 2\n"
        "    return solve(data[:mid]) + solve(data[mid:])\n"
    )
    hash_novel_divide = judge.compute_ast_hash(code_novel_divide)

    # 验证 AST 规范哈希正交性
    assert hash_monopoly != hash_novel_vector
    assert hash_monopoly != hash_novel_divide

    # 计算加权正交拓扑距离
    d_ortho_vec = judge.compute_orthogonal_distance(code_monopoly, code_novel_vector)
    d_ortho_div = judge.compute_orthogonal_distance(code_monopoly, code_novel_divide)
    assert d_ortho_vec > 0.30, f"Expected significant AST distance for vector branch, got {d_ortho_vec:.3f}"
    assert d_ortho_div > 0.30, f"Expected significant AST distance for divide branch, got {d_ortho_div:.3f}"

    # -------------------------------------------------------------------------
    # 场景 A：无新颖性沙箱保护的单一垄断种群 (90% 复制体)
    # -------------------------------------------------------------------------
    monopoly_population: List[CandidateSolution] = []
    # 18 个垄断解 (90%)
    for i in range(18):
        m = PhysicalMetrics(0.30, 8_000_000, 0.0, 0)
        profile_mono = judge.compute_behavioral_profile(m, code_monopoly)
        cand = CandidateSolution(
            candidate_id=f"mono_{i}",
            parent_id=None,
            island_id=0,
            ast_hash=hash_monopoly,
            source_code_cas_hash=f"cas_mono_{i}",
            metrics=m,
            behavior=profile_mono
        )
        monopoly_population.append(cand)

    # 计算垄断基线种群的 Vendi 多样性得分
    controller = IslandController(island_capacity=20)
    vendi_monopoly = controller._calculate_vendi_score(monopoly_population)
    # 90% 垄断下，Vendi 得分严重衰减 (接近 1.0)
    assert vendi_monopoly < 1.05, f"Expected severe diversity collapse (Vendi < 1.05), got {vendi_monopoly:.4f}"
    print(f"  -> Monopolistic Population (90% dominance) Vendi Score: {vendi_monopoly:.4f} (Collapsed).")

    # -------------------------------------------------------------------------
    # 场景 B：Island 2 新颖性沙箱特区介入
    # -------------------------------------------------------------------------
    # 注入非典型创新解 (虽然耗时 0.35s 稍逊于垄断解的 0.30s，但具有全新行为画像和空白网格)
    m_vec = PhysicalMetrics(0.35, 9_000_000, 0.0, 0, floating_point_ops=500_000, dram_bytes_transferred=2_000)
    profile_vec = judge.compute_behavioral_profile(m_vec, code_novel_vector)

    m_div = PhysicalMetrics(0.36, 12_000_000, 0.0, 0, floating_point_ops=10_000, dram_bytes_transferred=50_000)
    profile_div = judge.compute_behavioral_profile(m_div, code_novel_divide)

    cand_vec = CandidateSolution(
        candidate_id="novel_vec",
        parent_id=None,
        island_id=2,
        ast_hash=hash_novel_vector,
        source_code_cas_hash="cas_novel_vec",
        metrics=m_vec,
        behavior=profile_vec
    )
    cand_div = CandidateSolution(
        candidate_id="novel_div",
        parent_id=None,
        island_id=2,
        ast_hash=hash_novel_divide,
        source_code_cas_hash="cas_novel_div",
        metrics=m_div,
        behavior=profile_div
    )

    # 验证行为网格坐标正交性
    coords_mono = profile_mono.behavior_coords
    coords_vec = profile_vec.behavior_coords
    coords_div = profile_div.behavior_coords
    print(f"  -> Behavior Coords: Monopoly={coords_mono}, Vector={coords_vec}, Divide={coords_div}")

    # 将垄断解与创新解共同输入 Island 2 进行代际选择
    candidates_with_novel = monopoly_population[:10] + [cand_vec, cand_div]
    summary_island2 = controller.step_epoch(island_id=2, epoch=1, candidates=candidates_with_novel)

    # 检验 Island 2 成功接纳非典型创新解 (即使能量稍低，仍被踏脚石制度化接纳)
    island2_pop = controller._island_populations[2]
    retained_ids = [c.candidate_id for c in island2_pop]
    assert "novel_vec" in retained_ids, "Novel vector candidate was unjustly discarded in Island 2!"
    assert "novel_div" in retained_ids, "Novel divide candidate was unjustly discarded in Island 2!"

    vendi_novel_protected = summary_island2.island_diversity_vendi
    assert vendi_novel_protected > vendi_monopoly * 1.5, (
        f"Novelty Sandbox must significantly revive diversity! Got {vendi_novel_protected:.4f} vs {vendi_monopoly:.4f}"
    )

    print(f"  -> Novelty Sandbox (Island 2) Sheltered Population Vendi Score: {vendi_novel_protected:.4f}")
    print(f"  -> Vendi Diversity Boost: +{(vendi_novel_protected - vendi_monopoly) / vendi_monopoly * 100:.1f}%")
    print(">>> [PROBE 3 RESULT: CONFIRMED] AST Novelty Sandbox effectively prevented diversity collapse.")


# =============================================================================
# 探针 4：全量 E2E 测试回归核验
# =============================================================================

def test_probe_4_full_regression_and_e2e_verification() -> None:
    """
    探针 4：全量 E2E 测试回归核验
    
    对抗目标：
    在完成上述极限挑战探针后，执行全链路 4-Tier 端到端集成测试，
    确保全部 45 个用例 100% 满分通过，零回归，退出码严格为 0。
    """
    print("\n[PROBE 4] Verifying Full E2E & Invariant Test Suites for Zero Regression...")

    from e2e_tests.runner import E2ERunner

    runner = E2ERunner(verbose=False)
    t0 = time.perf_counter()

    for tier_id in [1, 2, 3, 4]:
        results = runner.run_tier(tier_id)
        failed = [r for r in results if not r.passed]
        assert len(failed) == 0, f"Tier {tier_id} had regressions: {[f.name for f in failed]}"

    elapsed = time.perf_counter() - t0
    exit_code = runner.print_summary_matrix(elapsed)

    assert exit_code == 0, f"E2E Runner exit code was {exit_code}, expected 0"
    assert len(runner.results) == 45, f"Expected 45 total tests, got {len(runner.results)}"
    assert all(r.passed for r in runner.results), "Not all tests passed 100%!"

    print(">>> [PROBE 4 RESULT: CONFIRMED] Full E2E 4-Tier (45 tests) passed 100% with zero regressions.")


# =============================================================================
# 独立执行入口
# =============================================================================

def run_all_tier5_probes() -> None:
    print("=" * 80)
    print("  AFEVA TIER 5 EVOLUTION DYNAMICS & CHEATING ADVERSARIAL PROBES")
    print("=" * 80)

    t_start = time.perf_counter()

    test_probe_1_polymorphic_obfuscated_lookup_cheats()
    test_probe_2_fifty_epochs_anchor_monotonicity_under_severe_shocks()
    test_probe_3_diversity_collapse_defense_and_ast_novelty_sandbox()
    test_probe_4_full_regression_and_e2e_verification()

    total_time = time.perf_counter() - t_start
    print("\n" + "=" * 80)
    print(f"  ALL 4 TIER 5 ADVERSARIAL PROBES PASSED 100%! Total Time: {total_time:.2f}s")
    print("  VERDICT: CONFIRM CORRECTNESS (AFEVA Evolution Dynamics & Gate Hardened)")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    run_all_tier5_probes()
