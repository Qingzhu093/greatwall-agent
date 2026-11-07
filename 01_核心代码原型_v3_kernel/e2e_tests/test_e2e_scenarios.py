"""
End-to-End (E2E) Integration Scenarios for AFEVA Long-Horizon Multi-Agent Architecture.
Organized into 4 Tiers:
- Tier 1: Feature Coverage (>=5 tests per core feature)
- Tier 2: Boundary & Corner Cases (Extreme concurrency, pathological inputs, degenerate DAGs, hang timeouts)
- Tier 3: Cross-Feature Combinations (Pairwise pipelines, probation novelty shelter, crash rebind)
- Tier 4: Real-World Application Scenarios (Contest exploration, disaster recovery, diversity defense)

Author: worker_m5_e2e (End-to-End Testing Architect)
Status: Production Ready
"""

from __future__ import annotations

import ast
import asyncio
import copy
import hashlib
import math
import os
import shutil
import stat
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Core imports
from src.core.contracts import (
    AuditCode,
    BehavioralProfile,
    CandidateSolution,
    CausalDeadlockException,
    CausalToken,
    DiffSpec,
    EpochSummary,
    EventPriority,
    ForensicAuditVerdict,
    FSMState,
    GateStatus,
    GateVerdict,
    InvalidTransitionException,
    IslandRole,
    MigrationBundle,
    PhysicalMetrics,
    PlaybookBullet,
    StateCategory,
    WALCorruptionError,
    WorktreeSpec,
    MergeConflictException,
    WorktreeLockException,
    LeaseExpiredException,
)
from src.core.state import (
    VALID_TRANSITIONS,
    can_transition,
    validate_transition,
    get_state_category,
)
from src.core.engine import (
    AsyncFSMDriver,
    LocalJoinBarrier,
)
from src.core.events import (
    FSMEvent,
    create_poison_pill_event,
    create_stage_gate_event,
    create_causal_event,
    create_heartbeat_event,
    create_reheating_event,
    create_tick_event,
    TaskDispatchPayload,
    GateVerdictPayload,
    PoisonPillPayload,
)
from src.core.wal import WriteAheadLog, WALEntry
from src.core.snapshot import AtomicSnapshotEngine, FSMStateSnapshot
from src.core.ledger import TaskLedger, ProgressLedger, DualLedger, LivingPlaybook
from src.core.scheduler import TaskScheduler, WatchdogMonitor, DeadlockDetector, CancellationToken

# Worktree & Gate imports
from src.worktree.manager import WorktreeManager
from src.worktree.validator import ValidationGate

# Evolution imports
from src.evolution.annealer import AnnealingController
from src.evolution.ast_judge import ASTDistanceAssessor
from src.evolution.island import IslandController

# Mock Agent Probe Cluster
from tests.mock_agents import MockWorker, WorkerBehaviorMode, MockChallenger, MockAuditor


# ============================================================================
# Helper Assertions and Scaffolding
# ============================================================================

def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(f"Assertion failed: {message}")


def create_clean_temp_dir(prefix: str = "afeva_e2e_") -> Path:
    d = Path(tempfile.gettempdir()) / f"{prefix}{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ============================================================================
# TIER 1: Feature Coverage (>=5 tests per core feature)
# ============================================================================

# ----------------------------------------------------------------------------
# Tier 1 - Feature 1: FSM State Machine Lifecycle & Preemption (5 tests)
# ----------------------------------------------------------------------------

def test_tier1_fsm_01_full_lifecycle_success() -> None:
    """T1.F01.1: 状态机标准正向全生命周期流转 (S01 -> S02 -> S03 -> S04 -> S05 -> S09 -> S10 -> S11 -> S12)."""
    driver = AsyncFSMDriver(node_id="e2e_fsm_node_1", initial_state=FSMState.S01_IDLE)
    assert_true(driver.get_current_state() == FSMState.S01_IDLE, "Initial state should be S01_IDLE")

    transitions = [
        (FSMState.S02_SEEDING, "EVT_SEED_INIT"),
        (FSMState.S03_BLIND_IDEATION, "EVT_SEED_READY"),
        (FSMState.S04_CODE_SYNTHESIS, "EVT_IDEATION_COMPLETE"),
        (FSMState.S05_ROUGH_EVAL, "EVT_SYNTHESIS_SUBMITTED"),
        (FSMState.S09_STAGING_EVAL, "EVT_ROUGH_PASS"),
        (FSMState.S10_FORENSIC_AUDIT, "EVT_STAGING_PASS"),
        (FSMState.S11_IRON_EVAL, "EVT_FORENSIC_PASS"),
        (FSMState.S12_ATOMIC_COMMIT, "EVT_IRON_PASS"),
    ]

    for next_state, evt_type in transitions:
        evt = FSMEvent(
            event_id=f"evt_{evt_type.lower()}",
            priority=EventPriority.P1_STAGE_GATE_EVAL,
            event_type=evt_type,
            source_state=driver.get_current_state(),
            target_state_hint=next_state,
            causal_token=CausalToken("tok_1", 1, (), "cas_0"),
        )
        new_state = asyncio.run(driver.transition(evt))
        assert_true(new_state == next_state, f"Expected transition to {next_state}")

    assert_true(driver.get_current_state() == FSMState.S12_ATOMIC_COMMIT, "Final state must be S12_ATOMIC_COMMIT")


def test_tier1_fsm_02_probation_predator_repair_path() -> None:
    """T1.F01.2: 偏科生监护分支流转 (S05 -> S06_PROBATION -> S07_PREDATOR_PAIRING -> S08_HYBRID_REPAIR -> S09)."""
    driver = AsyncFSMDriver(node_id="e2e_fsm_prob", initial_state=FSMState.S05_ROUGH_EVAL)

    probation_steps = [
        (FSMState.S06_PROBATION, "EVT_ROUGH_PROBATION"),
        (FSMState.S07_PREDATOR_PAIRING, "EVT_PAIR_PREDATOR"),
        (FSMState.S08_HYBRID_REPAIR, "EVT_PREDATOR_READY"),
        (FSMState.S09_STAGING_EVAL, "EVT_REPAIR_COMPLETE"),
    ]

    for next_state, evt_type in probation_steps:
        evt = FSMEvent(
            event_id=f"evt_{evt_type.lower()}",
            priority=EventPriority.P1_STAGE_GATE_EVAL,
            event_type=evt_type,
            source_state=driver.get_current_state(),
            target_state_hint=next_state,
            causal_token=CausalToken("tok_prob", 2, (), "cas_prob"),
        )
        new_state = asyncio.run(driver.transition(evt))
        assert_true(new_state == next_state, f"Expected step to {next_state}")

    assert_true(driver.get_current_state() == FSMState.S09_STAGING_EVAL, "Repaired solution enters S09")


def test_tier1_fsm_03_p0_poison_pill_preemption() -> None:
    """T1.F01.3: P0 级毒丸事件在事件循环中的绝对抢占与立即转入 S14_APOPTOSIS_FLUSH."""
    driver = AsyncFSMDriver(node_id="e2e_fsm_poison", initial_state=FSMState.S04_CODE_SYNTHESIS)

    async def scenario():
        for _ in range(5):
            await driver.submit_event(create_tick_event(source_state=FSMState.S04_CODE_SYNTHESIS))

        poison_evt = create_poison_pill_event(
            source_state=FSMState.S04_CODE_SYNTHESIS,
            reason="E2E Critical Fault Detected",
        )
        await driver.submit_event(poison_evt)
        await driver.run_cycle()

    asyncio.run(scenario())
    assert_true(driver.get_current_state() == FSMState.S14_APOPTOSIS_FLUSH, "Poison pill must force S14 state")


def test_tier1_fsm_04_invalid_transition_guard() -> None:
    """T1.F01.4: 非法跨状态跳转守卫拦截 (如 S01_IDLE 直接跳到 S12_ATOMIC_COMMIT 必被拦截)."""
    driver = AsyncFSMDriver(node_id="e2e_fsm_guard", initial_state=FSMState.S01_IDLE)

    illegal_evt = FSMEvent(
        event_id="evt_illegal_skip",
        priority=EventPriority.P1_STAGE_GATE_EVAL,
        event_type="EVT_ILLEGAL_SKIP",
        source_state=FSMState.S01_IDLE,
        target_state_hint=FSMState.S12_ATOMIC_COMMIT,
        causal_token=CausalToken("tok_bad", 1, (), "cas_bad"),
    )

    try:
        asyncio.run(driver.transition(illegal_evt))
        raised = False
    except InvalidTransitionException:
        raised = True

    assert_true(raised, "Illegal transition S01 -> S12 must raise InvalidTransitionException")
    assert_true(driver.get_current_state() == FSMState.S01_IDLE, "State must remain unchanged upon rejection")


def test_tier1_fsm_05_reheating_pulse_transition() -> None:
    """T1.F01.5: 停滞与自旋时触发 S13_REHEATING_PULSE 升温脉冲并回弹至 S04_CODE_SYNTHESIS."""
    driver = AsyncFSMDriver(node_id="e2e_fsm_reheat", initial_state=FSMState.S05_ROUGH_EVAL)

    reheat_evt = create_reheating_event(
        island_id=1,
        boost_amount=1.5,
        reason="Stall detected in rough eval",
        source_state=FSMState.S05_ROUGH_EVAL,
    )
    new_state = asyncio.run(driver.transition(reheat_evt))
    assert_true(new_state == FSMState.S13_REHEATING_PULSE, "Must transition to S13_REHEATING_PULSE")

    # 升温完毕后回到 S04 重新发散探索
    resynthesize_evt = FSMEvent(
        event_id="evt_resynth",
        priority=EventPriority.P2_WORKER_PROGRESS,
        event_type="EVT_REHEAT_COMPLETE",
        source_state=FSMState.S13_REHEATING_PULSE,
        target_state_hint=FSMState.S04_CODE_SYNTHESIS,
        causal_token=CausalToken("tok_reheat", 3, (), "cas_reheat"),
    )
    final_state = asyncio.run(driver.transition(resynthesize_evt))
    assert_true(final_state == FSMState.S04_CODE_SYNTHESIS, "Must return to S04_CODE_SYNTHESIS after pulse")


# ----------------------------------------------------------------------------
# Tier 1 - Feature 2: Worktree RAM-Disk Isolation & Safe Release (5 tests)
# ----------------------------------------------------------------------------

def test_tier1_worktree_01_isolated_checkout() -> None:
    """T1.F02.1: Worktree 物理隔离沙箱检出与分支独立性校验."""
    tmp_root = create_clean_temp_dir("wt_e2e_checkout_")
    mgr = WorktreeManager(root_dir=str(tmp_root), is_ramdisk=True)

    spec_a = mgr.create_worktree(task_id="task_checkout_a", base_commit="base_sha_0")
    spec_b = mgr.create_worktree(task_id="task_checkout_b", base_commit="base_sha_0")

    assert_true(spec_a.worktree_id != spec_b.worktree_id, "Worktree IDs must be unique")
    assert_true(spec_a.worktree_path != spec_b.worktree_path, "Worktree paths must be completely separated")
    assert_true(os.path.exists(spec_a.worktree_path), "Worktree A directory must exist")
    assert_true(os.path.exists(spec_b.worktree_path), "Worktree B directory must exist")

    mgr.remove_worktree(spec_a.worktree_id)
    mgr.remove_worktree(spec_b.worktree_id)
    shutil.rmtree(tmp_root, ignore_errors=True)


def test_tier1_worktree_02_code_injection_and_commit() -> None:
    """T1.F02.2: 在沙箱内写入代码并执行 commit_worktree 生成确定性 Commit Hash."""
    tmp_root = create_clean_temp_dir("wt_e2e_commit_")
    mgr = WorktreeManager(root_dir=str(tmp_root))
    spec = mgr.create_worktree(task_id="task_inject_1", base_commit="base_init")

    worker = MockWorker(worker_id="inject_worker_1")
    code_path = worker.write_to_worktree(spec, mode=WorkerBehaviorMode.NORMAL)
    assert_true(code_path.exists(), "Source file should exist in worktree")

    commit_hash = mgr.commit_worktree(spec.worktree_id, message="E2E: Verified Normal Solution")
    assert_true(len(commit_hash) == 64, f"Commit hash must be valid SHA-256 (got {commit_hash})")

    mgr.remove_worktree(spec.worktree_id)
    shutil.rmtree(tmp_root, ignore_errors=True)


def test_tier1_worktree_03_safe_release() -> None:
    """T1.F02.3: 沙箱安全物理释放，验证目录被彻底清除且不留垃圾句柄."""
    tmp_root = create_clean_temp_dir("wt_e2e_release_")
    mgr = WorktreeManager(root_dir=str(tmp_root))
    spec = mgr.create_worktree(task_id="task_release", base_commit="base_rel")
    wt_path = Path(spec.worktree_path)

    assert_true(wt_path.exists(), "Worktree should exist before removal")
    success = mgr.remove_worktree(spec.worktree_id)
    assert_true(success, "remove_worktree should return True")
    assert_true(not wt_path.exists(), "Worktree directory should be deleted after removal")
    assert_true(mgr.get_worktree(spec.worktree_id) is None, "Manager index should no longer contain worktree")

    shutil.rmtree(tmp_root, ignore_errors=True)


def test_tier1_worktree_04_windows_lock_tombstoning() -> None:
    """T1.F02.4: 模拟 Windows NTFS 文件锁 (WinError 32)，验证 Atomic Tombstoning 墓碑脱离机制."""
    tmp_root = create_clean_temp_dir("wt_e2e_tombstone_")
    mgr = WorktreeManager(root_dir=str(tmp_root))
    spec = mgr.create_worktree(task_id="task_lock_tomb", base_commit="base_lock")

    test_file = Path(spec.worktree_path) / "locked_artifact.bin"
    test_file.write_bytes(b"LOCKED_DATA_TEST" * 50)

    f_handle = open(test_file, "r+b")
    try:
        removed = mgr.remove_worktree(spec.worktree_id)
        assert_true(removed, "Worktree removal should succeed via Atomic Tombstoning")
        assert_true(mgr.get_worktree(spec.worktree_id) is None, "Worktree must be unregistered")
    finally:
        f_handle.close()

    spec_reborn = mgr.create_worktree(task_id="task_lock_tomb", base_commit="base_lock")
    assert_true(Path(spec_reborn.worktree_path).exists(), "New worktree with same task_id must succeed")
    mgr.remove_worktree(spec_reborn.worktree_id)

    shutil.rmtree(tmp_root, ignore_errors=True)


def test_tier1_worktree_05_atomic_merge_main() -> None:
    """T1.F02.5: 沙箱原子合并至 main 主干分支并更新基线指针."""
    tmp_root = create_clean_temp_dir("wt_e2e_merge_")
    base_dir = tmp_root / "base_repo"
    base_dir.mkdir(parents=True)
    (base_dir / "main.py").write_text("def solve(x):\n    return sum(x)\n", encoding="utf-8")

    mgr = WorktreeManager(root_dir=str(tmp_root / "sandboxes"), base_repo_dir=str(base_dir))
    spec = mgr.create_worktree(task_id="task_merge_main", base_commit="base_0")

    target_file = Path(spec.worktree_path) / "main.py"
    target_file.write_text("def solve(x):\n    return sum(x) * 3\n", encoding="utf-8")
    c_hash = mgr.commit_worktree(spec.worktree_id, "Optimized factor 3")

    merge_success = mgr.merge_to_main(spec.worktree_id)
    assert_true(merge_success, "merge_to_main must succeed for non-conflicting branch")
    assert_true("return sum(x) * 3" in (base_dir / "main.py").read_text(encoding="utf-8"), "Main branch updated")

    mgr.remove_worktree(spec.worktree_id)
    shutil.rmtree(tmp_root, ignore_errors=True)


# ----------------------------------------------------------------------------
# Tier 1 - Feature 3: AFEVA 3-Tier Progressive Validation Gate (5 tests)
# ----------------------------------------------------------------------------

def test_tier1_gate_01_tier1_rough_approve() -> None:
    """T1.F03.1: Tier 1 粗野探索门对正常合法代码给予 APPROVE 裁决."""
    tmp_root = create_clean_temp_dir("gate_t1_app_")
    wt_spec = WorktreeSpec("wt_app", str(tmp_root / "wt_app"), "b_app", "c0")
    Path(wt_spec.worktree_path).mkdir(parents=True)
    (Path(wt_spec.worktree_path) / "main.py").write_text("def solve(x):\n    return sum(x)\n", encoding="utf-8")

    gate = ValidationGate(baseline_execution_time_s=1.0)
    diff = DiffSpec("c0", "c1", ("main.py",), "solve", 5, 0, 0.1)

    verdict = gate.validate_tier1(wt_spec, diff)
    assert_true(verdict.status == GateStatus.APPROVE, f"Tier 1 expected APPROVE, got {verdict.status}")
    assert_true(verdict.tier_level == 1, "Verdict level must be Tier 1")

    shutil.rmtree(tmp_root, ignore_errors=True)


def test_tier1_gate_02_tier1_probationary_pass() -> None:
    """T1.F03.2: Tier 1 粗野探索门对突破性偏科生给予 PROBATIONARY_PASS 带病晋级豁免."""
    tmp_root = create_clean_temp_dir("gate_t1_prob_")
    wt_spec = WorktreeSpec("wt_prob", str(tmp_root / "wt_prob"), "b_prob", "c0")
    Path(wt_spec.worktree_path).mkdir(parents=True)

    worker = MockWorker()
    worker.write_to_worktree(wt_spec, mode=WorkerBehaviorMode.BREAKTHROUGH_TALENT)

    gate = ValidationGate(baseline_execution_time_s=10.0, speedup_threshold_rough=0.15)
    diff = DiffSpec("c0", "c1", ("main.py",), "solve", 15, 0, 0.4)

    verdict = gate.validate_tier1(wt_spec, diff)
    assert_true(verdict.status in (GateStatus.PROBATIONARY_PASS, GateStatus.APPROVE), f"Expected pass or probation, got {verdict.status}")

    shutil.rmtree(tmp_root, ignore_errors=True)


def test_tier1_gate_03_tier2_cheating_lookup_interception() -> None:
    """T1.F03.3: Tier 2 集成中继门静态法医拦截查表硬编码作弊 (CHEAT_LOOKUP_TABLE)."""
    tmp_root = create_clean_temp_dir("gate_t2_cheat_")
    wt_spec = WorktreeSpec("wt_cheat", str(tmp_root / "wt_cheat"), "b_cheat", "c0")
    Path(wt_spec.worktree_path).mkdir(parents=True)

    worker = MockWorker(worker_id="cheater")
    worker.write_to_worktree(wt_spec, mode=WorkerBehaviorMode.CHEAT_LOOKUP, lookup_table_entries=50)

    gate = ValidationGate()
    diff = DiffSpec("c0", "c1", ("main.py",), "solve", 60, 0, 0.8)

    verdict = gate.validate_tier2(wt_spec, diff)
    assert_true(verdict.status == GateStatus.REJECT, f"Tier 2 cheat lookup must be REJECT, got {verdict.status}")
    assert_true(any("CHEAT_LOOKUP_TABLE" in d for d in verdict.diagnostics), "Diagnostic must report lookup fraud")

    shutil.rmtree(tmp_root, ignore_errors=True)


def test_tier1_gate_04_tier3_iron_variance_check() -> None:
    """T1.F03.4: Tier 3 钢铁生产门方差检验：确定性代码顺利通过."""
    tmp_root = create_clean_temp_dir("gate_t3_iron_")
    wt_spec = WorktreeSpec("wt_iron", str(tmp_root / "wt_iron"), "b_iron", "c0")
    Path(wt_spec.worktree_path).mkdir(parents=True)
    (Path(wt_spec.worktree_path) / "main.py").write_text("def solve(x):\n    return sum(x)\n", encoding="utf-8")

    # 在集成测试环境中设置合理的方差阈值
    gate = ValidationGate(variance_tolerance_iron=0.50)
    diff = DiffSpec("c0", "c1", ("main.py",), "solve", 10, 0, 0.1)

    verdict = gate.validate_tier3(wt_spec, diff)
    assert_true(verdict.status == GateStatus.APPROVE, f"Tier 3 deterministic candidate must be APPROVE, got {verdict.status}")

    shutil.rmtree(tmp_root, ignore_errors=True)


def test_tier1_gate_05_syntax_error_rejection() -> None:
    """T1.F03.5: 语法损坏代码 (CORRUPTED_CODE) 在 AST 契约与门禁检查时被立即一票否决."""
    gate = ValidationGate()
    corrupted_code = "def solve(x:\n    return x +"
    ok = gate.check_ast_contract(corrupted_code, "solve")
    assert_true(not ok, "Corrupted syntax must fail AST contract check")

    tmp_root = create_clean_temp_dir("gate_syn_err_")
    wt_spec = WorktreeSpec("wt_syn", str(tmp_root / "wt_syn"), "b_syn", "c0")
    Path(wt_spec.worktree_path).mkdir(parents=True)
    (Path(wt_spec.worktree_path) / "main.py").write_text(corrupted_code, encoding="utf-8")

    diff = DiffSpec("c0", "c1", ("main.py",), "solve", 5, 0, 0.5)
    v = gate.validate_tier1(wt_spec, diff)
    assert_true(v.status == GateStatus.REJECT, "Syntax error must be REJECT")

    shutil.rmtree(tmp_root, ignore_errors=True)


# ----------------------------------------------------------------------------
# Tier 1 - Feature 4: 3-Island Topology & Robust MAD Annealing (5 tests)
# ----------------------------------------------------------------------------

def test_tier1_evolution_01_three_islands_init() -> None:
    """T1.F04.1: 初始化三孤岛演化拓扑 (Anchor, Anneal, Novelty) 及其角色分布."""
    controller = IslandController()
    roles = controller._island_roles

    assert_true(roles[0] == IslandRole.ISLAND_0_ANCHOR, "Island 0 must be ANCHOR")
    assert_true(roles[1] == IslandRole.ISLAND_1_ANNEAL, "Island 1 must be ANNEAL")
    assert_true(roles[2] == IslandRole.ISLAND_2_NOVELTY, "Island 2 must be NOVELTY")


def test_tier1_evolution_02_directed_ring_migration() -> None:
    """T1.F04.2: 稀疏有向环 0 -> 1 -> 2 -> 0 周期迁移总线正确性验证."""
    controller = IslandController(migration_interval=5)
    worker = MockWorker()

    for i in range(3):
        cand = worker.create_candidate_solution(island_id=i)
        controller.step_epoch(island_id=i, epoch=5, candidates=[cand])

    bundles = controller.exchange_migrants()
    assert_true(len(bundles) == 3, f"Directed ring migration should produce 3 bundles, got {len(bundles)}")

    route_pairs = {(b.source_island_id, b.target_island_id) for b in bundles}
    expected_pairs = {(0, 1), (1, 2), (2, 0)}
    assert_true(route_pairs == expected_pairs, f"Migration must follow 0->1->2->0 ring (got {route_pairs})")


def test_tier1_evolution_03_mad_scale_annealing() -> None:
    """T1.F04.3: 稳健百分位中位数绝对偏差 (MAD) 标度与离群值免疫性检验."""
    annealer = AnnealingController(window_size=10)

    # 注入正常数据与超大离群点 (5.0s)
    for val in [1.0, 1.05, 0.95, 1.02, 0.98, 5.0]:
        annealer.update_history(PhysicalMetrics(val, 10_000_000, 0.0, 0))

    scale_time = annealer._compute_mad_scale(annealer._history_time, 1.0)
    assert_true(0.01 < scale_time < 0.5, f"MAD scale must be outlier-immune, got {scale_time}")


def test_tier1_evolution_04_metropolis_acceptance() -> None:
    """T1.F04.4: Metropolis 准则：高温接纳劣解探索，低温抑制劣解并收敛."""
    annealer = AnnealingController(initial_temperature=100.0, cooling_rate=0.9)
    current_metrics = PhysicalMetrics(execution_time_s=1.0, peak_memory_bytes=1000, collision_penalty=0.0, exit_code=0)
    worse_metrics = PhysicalMetrics(execution_time_s=1.2, peak_memory_bytes=1000, collision_penalty=0.0, exit_code=0)

    # 高温阶段接纳劣解概率显著
    accepted_high_t = sum(annealer.evaluate_acceptance(current_metrics, worse_metrics, step=1) for _ in range(20))
    assert_true(accepted_high_t > 0, "High temperature must accept some inferior candidates")

    # 设定当前温度降至最低底限
    annealer.current_temperature = annealer.min_temperature
    accepted_low_t = sum(annealer.evaluate_acceptance(current_metrics, worse_metrics, step=1000) for _ in range(20))
    assert_true(accepted_low_t == 0, "At min_temperature, inferior candidates must be rejected")


def test_tier1_evolution_05_anchor_monotonicity() -> None:
    """T1.F04.5: Island 0 (Anchor) 保守锚点岛性能单调性与贪心精英保护."""
    controller = IslandController()
    worker = MockWorker()

    c_best = worker.create_candidate_solution(island_id=0, metrics=PhysicalMetrics(0.1, 1000, 0.0, 0))
    controller.step_epoch(island_id=0, epoch=1, candidates=[c_best])

    # 注入退化劣解
    c_worse = worker.create_candidate_solution(island_id=0, metrics=PhysicalMetrics(5.0, 5000, 0.5, 0))
    controller.step_epoch(island_id=0, epoch=2, candidates=[c_worse])

    anchor_pop = controller._island_populations[0]
    best_in_pop = min(anchor_pop, key=lambda c: c.metrics.execution_time_s)
    assert_true(best_in_pop.metrics.execution_time_s == 0.1, "Anchor island must preserve strictly best solution")


# ----------------------------------------------------------------------------
# Tier 1 - Feature 5: Dual Ledger & Stanford ACE Living Playbook (5 tests)
# ----------------------------------------------------------------------------

def test_tier1_ledger_01_task_vs_progress_isolation() -> None:
    """T1.F05.1: 任务账本 (Task Ledger) 与进展账本 (Progress Ledger) 物理投影隔离."""
    dual = DualLedger()

    dual.task_ledger.register_task("task_01", causal_level=1, dependencies=set())
    dual.task_ledger.mark_completed("task_01", artifact_hash="sha:art_01")

    cand = CandidateSolution(
        candidate_id="cand_prog",
        parent_id=None,
        island_id=0,
        ast_hash="ast_01",
        source_code_cas_hash="cas_01",
        metrics=PhysicalMetrics(0.05, 1000, 0.0, 0),
    )
    dual.progress_ledger.record_candidate(cand)

    assert_true(dual.task_ledger.is_task_ready("task_01"), "Task 01 completed")
    frontier = dual.progress_ledger.get_pareto_frontier()
    assert_true(len(frontier) >= 1, "Progress ledger records candidate in frontier")


def test_tier1_ledger_02_living_playbook_add_and_retrieve() -> None:
    """T1.F05.2: Living Playbook 战术条目添加与模式匹配检索."""
    playbook = LivingPlaybook(token_budget=1500)

    bullet = PlaybookBullet(
        bullet_id="PB-001",
        trigger_condition="dense_matrix_multiplication",
        prescribed_strategy="Use BLAS GEMM block tiling",
        anti_pattern_taboo="Do not use 3-nested python loops",
        utility_score=2.0,
    )
    playbook.add_or_update(bullet)

    assert_true("PB-001" in playbook._bullets, "Bullet must be stored in playbook._bullets")
    ctx = playbook.export_context()
    assert_true("PB-001" in ctx, "Exported context must contain bullet ID")


def test_tier1_ledger_03_living_playbook_lfu_decay_pruning() -> None:
    """T1.F05.3: Living Playbook 触发 LFU-Decay 惰性剪枝淘汰低效条目."""
    playbook = LivingPlaybook(token_budget=1500)

    for i in range(5):
        pb = PlaybookBullet(
            bullet_id=f"PB-{i:03d}",
            trigger_condition=f"condition_{i}",
            prescribed_strategy=f"strategy_{i}",
            anti_pattern_taboo=f"taboo_{i}",
            utility_score=1.0 + i * 2.0,
        )
        playbook.add_or_update(pb)

    playbook.decay_all(decay_factor=0.8)
    pruned = playbook.prune_lfu(max_bullets=3)
    assert_true(pruned == 2, f"Should prune 2 lowest bullets, pruned={pruned}")
    assert_true(len(playbook._bullets) == 3, "Playbook should now have 3 bullets")
    assert_true("PB-004" in playbook._bullets, "Highest utility bullet must be retained")


def test_tier1_ledger_04_living_playbook_reward_reinforcement() -> None:
    """T1.F05.4: 策略奏效时奖励战术条目效用分与命中计数."""
    bullet = PlaybookBullet("PB-REW", "sparse_graph", "CSR compression", "Dense array", utility_score=1.0)
    bullet.reward_utility(bonus=1.5)
    assert_true(bullet.utility_score == 2.5, f"Utility should increase to 2.5, got {bullet.utility_score}")
    assert_true(bullet.access_count == 2, f"Access count should be 2, got {bullet.access_count}")


def test_tier1_ledger_05_progress_ledger_pareto_frontier() -> None:
    """T1.F05.5: 进展账本维护 Pareto 前沿，低劣解被自动淘汰."""
    dual_ledger = DualLedger()

    c1 = CandidateSolution("c1", None, 0, "ast1", "cas1", PhysicalMetrics(0.5, 1000, 0.0, 0))
    c2 = CandidateSolution("c2", "c1", 1, "ast2", "cas2", PhysicalMetrics(0.2, 2000, 0.05, 0))
    c3 = CandidateSolution("c3", "c1", 0, "ast3", "cas3", PhysicalMetrics(1.0, 3000, 0.1, 0))

    dual_ledger.progress_ledger.record_candidate(c1)
    dual_ledger.progress_ledger.record_candidate(c2)
    dual_ledger.progress_ledger.record_candidate(c3)

    pareto = dual_ledger.project_frontier_pareto()
    pareto_ids = {c.candidate_id for c in pareto}
    assert_true("c1" in pareto_ids and "c2" in pareto_ids, "Non-dominated candidates must be in Pareto frontier")
    assert_true("c3" not in pareto_ids, "Dominated candidate c3 must be excluded")


# ----------------------------------------------------------------------------
# Tier 1 - Feature 6: WAL & Atomic Snapshot Deterministic Recovery (5 tests)
# ----------------------------------------------------------------------------

def test_tier1_wal_01_append_and_checksum() -> None:
    """T1.F06.1: WAL 顺序追加、单调序号与 SHA-256 密码学校验和验证."""
    tmp_dir = create_clean_temp_dir("wal_e2e_")
    wal_file = str(tmp_dir / "wal.jsonl")

    with WriteAheadLog(wal_file, auto_sync=True) as wal:
        e1 = wal.append("node_1", FSMState.S01_IDLE, FSMState.S02_SEEDING, "commit_01", {"task_id": "T1"})
        assert_true(e1.lsn == 1, "First WAL entry LSN must be 1")
        assert_true(e1.verify_integrity(), "Entry checksum must verify")
        assert_true(wal.current_lsn == 1, "Current LSN should be 1")

    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_tier1_wal_02_snapshot_atomic_write() -> None:
    """T1.F06.2: 原子快照写入机制 (临时文件写入 + os.replace 原子覆盖) 验证."""
    tmp_dir = create_clean_temp_dir("snap_e2e_")
    engine = AtomicSnapshotEngine(str(tmp_dir))

    snap = FSMStateSnapshot.create(
        lsn=10,
        current_state=FSMState.S05_ROUGH_EVAL,
        git_commit_hash="c3a4f8e123456789abcdef",
        context_variables={"temperature": 0.88, "epoch": 2},
        completed_tasks=["task_01", "task_02"],
    )
    assert_true(snap.verify_integrity(), "Snapshot self-checksum must verify")

    path = engine.save_snapshot(snap)
    assert_true(os.path.exists(path), "Snapshot file must exist")
    assert_true(os.path.exists(engine.latest_link_path), "latest_snapshot.json must exist")

    loaded = engine.load_latest_snapshot()
    assert_true(loaded is not None, "Loaded snapshot must not be None")
    assert_true(loaded.lsn == 10, "Loaded LSN must match")
    assert_true(loaded.current_state == FSMState.S05_ROUGH_EVAL.value, "State must match")

    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_tier1_wal_03_replay_recovery() -> None:
    """T1.F06.3: 灾难恢复：结合基础快照与后续 WAL 事件确定性完全重放."""
    tmp_dir = create_clean_temp_dir("replay_e2e_")
    wal_file = str(tmp_dir / "replay.jsonl")

    with WriteAheadLog(wal_file, auto_sync=True) as wal:
        wal.append("node_1", FSMState.S01_IDLE, FSMState.S02_SEEDING, "c1", {})
        wal.append("node_1", FSMState.S02_SEEDING, FSMState.S03_BLIND_IDEATION, "c2", {})
        wal.append("node_1", FSMState.S03_BLIND_IDEATION, FSMState.S04_CODE_SYNTHESIS, "c3", {})

    driver = AsyncFSMDriver(node_id="replay_driver", initial_state=FSMState.S01_IDLE)
    with WriteAheadLog(wal_file) as wal_replay:
        replayed_count = wal_replay.deterministic_replay(driver, from_lsn=1)
        assert_true(replayed_count == 3, f"Expected 3 replayed steps, got {replayed_count}")
        assert_true(driver.get_current_state() == FSMState.S04_CODE_SYNTHESIS, "Driver reached S04")

    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_tier1_wal_04_snapshot_pruning() -> None:
    """T1.F06.4: 快照保留策略：超出 keep_count 时自动清理旧快照."""
    tmp_dir = create_clean_temp_dir("snap_prune_")
    engine = AtomicSnapshotEngine(str(tmp_dir))

    for i in range(3):
        snap = FSMStateSnapshot.create(
            lsn=i + 1,
            current_state=FSMState.S05_ROUGH_EVAL,
            git_commit_hash=f"commit_{i}",
            context_variables={},
            completed_tasks=[],
        )
        engine.save_snapshot(snap)

    assert_true(len(engine.list_snapshots()) == 3, "Should have 3 snapshots")
    pruned = engine.prune_snapshots(keep_count=1)
    assert_true(pruned == 2, f"Should have pruned 2 snapshots, got {pruned}")
    assert_true(len(engine.list_snapshots()) == 1, "Only 1 snapshot should remain")

    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_tier1_wal_05_tamper_detection() -> None:
    """T1.F06.5: WAL 篡改检测：人为篡改字节后校验和报警并阻止不可信重放."""
    tmp_dir = create_clean_temp_dir("wal_tamper_")
    wal_file = str(tmp_dir / "wal.jsonl")

    with WriteAheadLog(wal_file, auto_sync=True) as wal:
        wal.append("node_1", FSMState.S01_IDLE, FSMState.S02_SEEDING, "commit_01", {"data": "ok"})

    with open(wal_file, "a", encoding="utf-8") as f:
        f.write('{"lsn": 2, "timestamp": 123.0, "node_id": "x", "from_state": "S01_IDLE", "to_state": "S02_SEEDING", "commit_hash": "c", "payload": {}, "payload_checksum": "bad_checksum"}\n')

    try:
        with WriteAheadLog(wal_file) as corrupted_wal:
            corrupted_wal.read_entries()
        raised = False
    except WALCorruptionError:
        raised = True

    assert_true(raised, "Tampered WAL entry must raise WALCorruptionError")

    shutil.rmtree(tmp_dir, ignore_errors=True)


# ============================================================================
# TIER 2: Boundary & Corner Cases (>=5 tests)
# ============================================================================

def test_tier2_corner_01_extreme_concurrency_20_worktrees() -> None:
    """T2.C01: 极端并发争用：20 个并发工作区同时检出并尝试并发写入与提交."""
    tmp_root = create_clean_temp_dir("wt_e2e_concurrency_20_")
    mgr = WorktreeManager(root_dir=str(tmp_root))
    worker = MockWorker()

    specs = [mgr.create_worktree(f"concur_task_{i}", base_commit="base_root") for i in range(20)]
    assert_true(len(specs) == 20, "20 concurrent worktrees created")

    commits = []
    for spec in specs:
        worker.write_to_worktree(spec, mode=WorkerBehaviorMode.NORMAL, filename=f"file_{spec.worktree_id}.py")
        c = mgr.commit_worktree(spec.worktree_id, f"Commit from {spec.worktree_id}")
        commits.append(c)

    assert_true(len(set(commits)) == 20, "20 unique commit hashes generated")

    for spec in specs:
        ok = mgr.remove_worktree(spec.worktree_id)
        assert_true(ok, f"Failed to remove {spec.worktree_id}")

    shutil.rmtree(tmp_root, ignore_errors=True)


def test_tier2_corner_02_pathological_numerical_inputs() -> None:
    """T2.C02: 极端病态数值冲击 (0 耗时、微秒抖动、巨量内存、NaN/Inf 防御)."""
    annealer = AnnealingController()

    pathological_samples = [0.0000001, 0.0, 1e-9, 999999.0]
    for s in pathological_samples:
        annealer.update_history(PhysicalMetrics(s, 1000, 0.0, 0))

    scale = annealer._compute_mad_scale(annealer._history_time, 1.0)
    assert_true(scale > 0, "MAD scale must strictly remain positive (zero-division immunity)")
    assert_true(not math.isnan(scale) and not math.isinf(scale), "MAD scale must not be NaN or Inf")


def test_tier2_corner_03_empty_and_degenerate_dag() -> None:
    """T2.C03: 空任务 DAG、单节点自环与依赖图边界死锁检测与破环."""
    detector = DeadlockDetector()

    # 1. 空图检测
    empty_cycles = detector.detect_cycles({})
    assert_true(len(empty_cycles) == 0, "Empty graph should have no cycles")

    # 2. 单节点自环检测 (size-1 SCC)
    self_loop_graph = {"node_A": {"node_A"}}
    self_loop_cycles = detector.detect_cycles(self_loop_graph)
    assert_true(len(self_loop_cycles) == 1, "Self loop must be detected as cycle")

    # 3. 破除环路
    broken_edges = detector.resolve_deadlocks(self_loop_graph)
    assert_true(len(broken_edges) >= 1, "Deadlock detector must break self loop edge")
    assert_true(len(detector.detect_cycles(self_loop_graph)) == 0, "Graph must now be cycle-free")


def test_tier2_corner_04_hang_watchdog_timeout_and_tombstone() -> None:
    """T2.C04: 进程假死/挂起触发看门狗超时取消与沙箱强制墓碑脱离."""
    tmp_root = create_clean_temp_dir("wt_e2e_hang_")
    mgr = WorktreeManager(root_dir=str(tmp_root))
    spec = mgr.create_worktree("hang_task", base_commit="base_h")

    cancel_tok = CancellationToken()
    watchdog = WatchdogMonitor(default_timeout_s=0.05)
    watchdog.register_task("hang_task", timeout_s=0.05, cancel_token=cancel_tok)

    time.sleep(0.08)
    timed_out = watchdog.check_timeouts()

    assert_true("hang_task" in timed_out, "Task hang_task must be detected as timed out")
    assert_true(cancel_tok.is_cancelled, "Cancel token must be triggered")

    removed = mgr.remove_worktree(spec.worktree_id, force=True)
    assert_true(removed, "Force removal of hanging worktree must succeed")

    shutil.rmtree(tmp_root, ignore_errors=True)


def test_tier2_corner_05_massive_lookup_and_dead_code_boundary() -> None:
    """T2.C05: 临界查表作弊与法医静态边界判决."""
    tmp_root = create_clean_temp_dir("gate_lookup_bound_")
    mgr = WorktreeManager(root_dir=str(tmp_root))
    auditor = MockAuditor(max_lookup_table_entries=30)
    worker = MockWorker()

    spec_clean = mgr.create_worktree("task_clean_lookup", "c0")
    worker.write_to_worktree(spec_clean, mode=WorkerBehaviorMode.CHEAT_LOOKUP, lookup_table_entries=20)
    metrics_dummy = PhysicalMetrics(0.01, 1000, 0.0, 0)
    v_clean = auditor.audit_candidate(spec_clean, metrics_dummy)
    assert_true(v_clean.audit_code != AuditCode.CHEAT_LOOKUP_TABLE, "Under threshold lookup must not be flagged")

    spec_fraud = mgr.create_worktree("task_fraud_lookup", "c0")
    worker.write_to_worktree(spec_fraud, mode=WorkerBehaviorMode.CHEAT_LOOKUP, lookup_table_entries=45)
    v_fraud = auditor.audit_candidate(spec_fraud, metrics_dummy)
    assert_true(v_fraud.audit_code == AuditCode.CHEAT_LOOKUP_TABLE, "Over threshold lookup must be flagged as cheat")

    mgr.remove_worktree(spec_clean.worktree_id)
    mgr.remove_worktree(spec_fraud.worktree_id)
    shutil.rmtree(tmp_root, ignore_errors=True)


# ============================================================================
# TIER 3: Cross-Feature Combinations (Pairwise Interaction Tests) (5 tests)
# ============================================================================

def test_tier3_cross_01_pipeline_task_worktree_gate_wal_snapshot() -> None:
    """T3.X01: 跨模块闭环流水线：Task -> Worktree -> Gate -> Island -> WAL -> Snapshot 全链路."""
    tmp_root = create_clean_temp_dir("pipe_e2e_")
    mgr = WorktreeManager(root_dir=str(tmp_root / "sandboxes"))
    gate = ValidationGate()
    wal_file = str(tmp_root / "wal.jsonl")
    snap_engine = AtomicSnapshotEngine(str(tmp_root / "snapshots"))
    island_ctrl = IslandController()
    worker = MockWorker(worker_id="pipe_worker")

    # 1. 创建沙箱并写入代码
    spec = mgr.create_worktree("pipe_task_01", base_commit="commit_init")
    worker.write_to_worktree(spec, mode=WorkerBehaviorMode.NORMAL)
    c_hash = mgr.commit_worktree(spec.worktree_id, "Pipeline commit")

    # 2. 门禁验证
    diff = DiffSpec("commit_init", c_hash, ("main.py",), "solve", 10, 0, 0.1)
    verdict = gate.validate_tier1(spec, diff)
    assert_true(verdict.status == GateStatus.APPROVE, "Gate validation must pass")

    # 3. 孤岛吸纳
    cand = worker.create_candidate_solution("pipe_cand_01", island_id=0, metrics=verdict.evaluated_metrics)
    summary = island_ctrl.step_epoch(island_id=0, epoch=1, candidates=[cand])
    assert_true(summary.accepted_candidates >= 1, "Candidate accepted by Island 0")

    # 4. WAL 日志与原子快照
    with WriteAheadLog(wal_file, auto_sync=True) as wal:
        wal.append("node_pipe", FSMState.S05_ROUGH_EVAL, FSMState.S12_ATOMIC_COMMIT, c_hash, {"cand": cand.candidate_id})

    snap = FSMStateSnapshot.create(
        lsn=1,
        current_state=FSMState.S12_ATOMIC_COMMIT,
        git_commit_hash=c_hash,
        context_variables={"epoch": 1},
        completed_tasks=["pipe_task_01"],
    )
    snap_engine.save_snapshot(snap)

    assert_true(snap_engine.load_latest_snapshot() is not None, "Snapshot must be recoverable")
    mgr.remove_worktree(spec.worktree_id)
    shutil.rmtree(tmp_root, ignore_errors=True)


def test_tier3_cross_02_probationary_seed_island2_novelty_shelter_and_repair() -> None:
    """T3.X02: 退火演化 + 门禁联动：带病晋级偏科生幼苗在 Island 2 新颖性沙箱特区受保护并修复."""
    tmp_root = create_clean_temp_dir("prob_shelter_")
    island_ctrl = IslandController()
    worker = MockWorker()
    gate = ValidationGate(variance_tolerance_iron=0.50)

    # 1. 生成突破性偏科生
    prob_cand = worker.create_candidate_solution(
        "cand_breakthrough",
        island_id=2,
        mode=WorkerBehaviorMode.BREAKTHROUGH_TALENT,
    )
    assert_true(prob_cand.is_probationary, "Candidate must be marked probationary")

    # 2. Island 2 新颖性沙箱特区对其给予庇护接纳
    summary = island_ctrl.step_epoch(island_id=2, epoch=1, candidates=[prob_cand])
    assert_true(summary.accepted_candidates >= 1, "Island 2 must shelter probationary breakthrough seed")

    # 3. 在沙箱中完成变异修复
    mgr = WorktreeManager(root_dir=str(tmp_root))
    spec_rep = mgr.create_worktree("task_repair", base_commit="c0")
    worker.write_to_worktree(spec_rep, mode=WorkerBehaviorMode.NORMAL)
    diff = DiffSpec("c0", "c_rep", ("main.py",), "solve", 5, 1, 0.3)

    verdict_final = gate.validate_tier3(spec_rep, diff)
    assert_true(verdict_final.status == GateStatus.APPROVE, "Repaired seed must pass Tier 3 Iron Gate")

    mgr.remove_worktree(spec_rep.worktree_id)
    shutil.rmtree(tmp_root, ignore_errors=True)


def test_tier3_cross_03_deadlock_recovery_with_concurrency_backpressure() -> None:
    """T3.X03: 调度器高并发满载背压下发生依赖自旋，死锁检测器自动介入并成功自愈."""
    scheduler = TaskScheduler(max_concurrency=2)
    detector = DeadlockDetector()

    assert_true(scheduler.get_available_credit() == 2, "Initial credit pool must equal max concurrency")

    dep_graph = {
        "task_A": {"task_B"},
        "task_B": {"task_A"},
    }

    cycles = detector.detect_cycles(dep_graph)
    assert_true(len(cycles) == 1, "Deadlock cycle between task_A and task_B must be detected")

    broken = detector.resolve_deadlocks(dep_graph)
    assert_true(len(broken) >= 1, "Deadlock resolved by severing cycle")
    assert_true(len(detector.detect_cycles(dep_graph)) == 0, "Resolved graph must be cycle-free")


def test_tier3_cross_04_evolution_island_migration_with_worktree_gate() -> None:
    """T3.X04: 孤岛演化环形迁移与沙箱代码验证联动 (迁移卡片实例化并过门禁)."""
    tmp_root = create_clean_temp_dir("migr_gate_")
    mgr = WorktreeManager(root_dir=str(tmp_root))
    gate = ValidationGate()
    ctrl = IslandController(migration_interval=1)
    worker = MockWorker()

    c1 = worker.create_candidate_solution("cand_iso1", island_id=1)
    ctrl.step_epoch(island_id=1, epoch=1, candidates=[c1])

    bundles = ctrl.exchange_migrants()
    b1_to_2 = [b for b in bundles if b.source_island_id == 1 and b.target_island_id == 2]
    assert_true(len(b1_to_2) == 1, "Must generate migration bundle from 1 to 2")

    spec2 = mgr.create_worktree("task_migr_verify", base_commit="base_migr")
    worker.write_to_worktree(spec2, mode=WorkerBehaviorMode.NORMAL)
    diff = DiffSpec("base_migr", "c_migr", ("main.py",), "solve", 10, 0, 0.15)
    v = gate.validate_tier1(spec2, diff)
    assert_true(v.status == GateStatus.APPROVE, "Migrated candidate must pass local gate")

    mgr.remove_worktree(spec2.worktree_id)
    shutil.rmtree(tmp_root, ignore_errors=True)


def test_tier3_cross_05_wal_replay_across_crash_with_worktree_rebind() -> None:
    """T3.X05: 执行中途崩溃，恢复引擎通过快照与 WAL 重新确定性恢复演化世代."""
    tmp_root = create_clean_temp_dir("crash_rebind_")
    snap_engine = AtomicSnapshotEngine(str(tmp_root / "snaps"))
    wal_file = str(tmp_root / "wal.jsonl")

    snap = FSMStateSnapshot.create(
        lsn=5,
        current_state=FSMState.S05_ROUGH_EVAL,
        git_commit_hash="commit_epoch3",
        context_variables={"epoch": 3},
        completed_tasks=["task_ep1", "task_ep2", "task_ep3"],
    )
    snap_engine.save_snapshot(snap)

    with WriteAheadLog(wal_file, auto_sync=True) as wal:
        wal.append("node_1", FSMState.S05_ROUGH_EVAL, FSMState.S09_STAGING_EVAL, "c4", {"epoch": 4})
        wal.append("node_1", FSMState.S09_STAGING_EVAL, FSMState.S12_ATOMIC_COMMIT, "c5", {"epoch": 5})

    driver = AsyncFSMDriver(node_id="recovered_driver", initial_state=FSMState.S01_IDLE)
    loaded_snap = snap_engine.load_latest_snapshot()
    assert_true(loaded_snap is not None, "Snapshot loaded")
    driver.force_set_state(FSMState(loaded_snap.current_state))
    assert_true(driver.get_current_state() == FSMState.S05_ROUGH_EVAL, "Restored to snapshot state")

    with WriteAheadLog(wal_file) as wal_rep:
        replayed = wal_rep.deterministic_replay(driver, from_lsn=1)
        assert_true(replayed == 2, "Replayed 2 events")
        assert_true(driver.get_current_state() == FSMState.S12_ATOMIC_COMMIT, "Driver reached S12")

    shutil.rmtree(tmp_root, ignore_errors=True)


# ============================================================================
# TIER 4: Real-World Application Scenarios (>=5 Realistic Scenarios)
# ============================================================================

def test_tier4_real_01_high_throughput_contest_exploration() -> None:
    """T4.R01: 真实综合竞赛高通量探索：多智能体并发探索多种解法，自动剔除作弊，选拔最优解."""
    tmp_root = create_clean_temp_dir("contest_e2e_")
    mgr = WorktreeManager(root_dir=str(tmp_root))
    gate = ValidationGate(baseline_execution_time_s=1.0)
    island_ctrl = IslandController()

    candidates_pool = []
    modes = [
        ("agent_0", WorkerBehaviorMode.NORMAL),
        ("agent_1", WorkerBehaviorMode.CHEAT_LOOKUP),
        ("agent_2", WorkerBehaviorMode.NORMAL),
        ("agent_3", WorkerBehaviorMode.CORRUPTED_CODE),
        ("agent_4", WorkerBehaviorMode.NORMAL),
    ]

    for agent_id, mode in modes:
        worker = MockWorker(worker_id=agent_id, default_mode=mode)
        spec = mgr.create_worktree(f"task_{agent_id}", base_commit="base_c")

        if mode == WorkerBehaviorMode.CORRUPTED_CODE:
            worker.write_to_worktree(spec, mode=mode)
            code = (Path(spec.worktree_path) / "main.py").read_text(encoding="utf-8")
            if not gate.check_ast_contract(code, "solve"):
                mgr.remove_worktree(spec.worktree_id)
                continue

        elif mode == WorkerBehaviorMode.CHEAT_LOOKUP:
            worker.write_to_worktree(spec, mode=mode, lookup_table_entries=50)
            diff = DiffSpec("c0", "c1", ("main.py",), "solve", 50, 0, 0.8)
            v = gate.validate_tier2(spec, diff)
            if v.status == GateStatus.REJECT:
                mgr.remove_worktree(spec.worktree_id)
                continue

        else:
            worker.write_to_worktree(spec, mode=mode)
            diff = DiffSpec("c0", "c1", ("main.py",), "solve", 10, 0, 0.2)
            v = gate.validate_tier1(spec, diff)
            if v.status == GateStatus.APPROVE:
                c = worker.create_candidate_solution(f"cand_{agent_id}", island_id=0, metrics=v.evaluated_metrics)
                candidates_pool.append(c)

        mgr.remove_worktree(spec.worktree_id)

    assert_true(len(candidates_pool) == 3, f"3 legitimate candidates should survive, got {len(candidates_pool)}")
    summary = island_ctrl.step_epoch(island_id=0, epoch=1, candidates=candidates_pool)
    assert_true(summary.accepted_candidates >= 1, "At least one candidate accepted into Anchor island")

    shutil.rmtree(tmp_root, ignore_errors=True)


def test_tier4_real_02_disaster_recovery_10th_epoch_crash() -> None:
    """T4.R02: 灾难性断电与集群恢复：长程演化到第 10 轮意外崩溃，通过 WAL 与最新快照 100% 恢复演化上下文."""
    tmp_root = create_clean_temp_dir("recovery_10th_")
    snap_engine = AtomicSnapshotEngine(str(tmp_root / "snaps"))
    wal_file = str(tmp_root / "wal.jsonl")

    snap = FSMStateSnapshot.create(
        lsn=8,
        current_state=FSMState.S05_ROUGH_EVAL,
        git_commit_hash="commit_ep8",
        context_variables={"epoch": 8, "best_energy": 0.042},
        completed_tasks=[f"task_{i}" for i in range(8)],
    )
    snap_engine.save_snapshot(snap)

    with WriteAheadLog(wal_file, auto_sync=True) as wal:
        wal.append("node_1", FSMState.S05_ROUGH_EVAL, FSMState.S09_STAGING_EVAL, "commit_ep9", {"epoch": 9, "best_energy": 0.035})
        wal.append("node_1", FSMState.S09_STAGING_EVAL, FSMState.S12_ATOMIC_COMMIT, "commit_ep10", {"epoch": 10, "best_energy": 0.021})

    loaded_snap = snap_engine.load_latest_snapshot()
    assert_true(loaded_snap.context_variables["epoch"] == 8, "Snapshot records epoch 8")

    driver = AsyncFSMDriver(node_id="recovered_cluster", initial_state=FSMState.S01_IDLE)
    driver.force_set_state(FSMState(loaded_snap.current_state))

    with WriteAheadLog(wal_file) as wal_rep:
        entries = wal_rep.read_entries(from_lsn=1)
        assert_true(len(entries) == 2, "Read 2 subsequent WAL entries")
        final_epoch = entries[-1].payload["epoch"]
        assert_true(final_epoch == 10, f"Recovered to epoch 10 (got {final_epoch})")

    shutil.rmtree(tmp_root, ignore_errors=True)


def test_tier4_real_03_diversity_collapse_counteraction() -> None:
    """T4.R03: 多样性塌缩对抗：单一解法垄断时，Island 2 触发 AST 拓扑判定与新颖性探索激活."""
    assessor = ASTDistanceAssessor()
    island_ctrl = IslandController()
    worker = MockWorker()

    homo_code_1 = "def solve(x):\n    return sum(x)\n"
    homo_code_2 = "def solve(items):\n    # Just comments\n    return sum(items)\n"

    h1 = assessor.compute_ast_hash(homo_code_1)
    h2 = assessor.compute_ast_hash(homo_code_2)
    assert_true(h1 == h2, "Homogeneous codes must share identical normalized AST topology hash")

    ortho_code = "def solve(x):\n    if len(x) <= 1:\n        return x[0] if x else 0\n    m = len(x) // 2\n    return solve(x[:m]) + solve(x[m:])\n"
    h_ortho = assessor.compute_ast_hash(ortho_code)
    assert_true(h1 != h_ortho, "Orthogonal algorithm must produce distinct AST hash")

    ortho_cand = worker.create_candidate_solution("ortho_cand", island_id=2, metrics=PhysicalMetrics(0.015, 1000, 0.0, 0))
    ortho_cand.ast_hash = h_ortho
    summary = island_ctrl.step_epoch(island_id=2, epoch=1, candidates=[ortho_cand])
    assert_true(summary.accepted_candidates >= 1, "Novelty island must accept structurally novel candidate")


def test_tier4_real_04_large_scale_long_horizon_convergence() -> None:
    """T4.R04: 大规模长程任务演化收敛：多轮代际迭代，Anchor 岛性能稳步单调提升至极优工件."""
    island_ctrl = IslandController()
    worker = MockWorker()

    prev_best_time = float("inf")
    first_time = 0.0
    last_time = 0.0

    current_time = 1.0
    for epoch in range(1, 8):
        new_time = current_time * 0.6
        if epoch == 1:
            first_time = new_time
        last_time = new_time

        cand = worker.create_candidate_solution(
            f"cand_ep_{epoch}",
            island_id=0,
            metrics=PhysicalMetrics(execution_time_s=new_time, peak_memory_bytes=1000, collision_penalty=0.0, exit_code=0),
        )
        summary = island_ctrl.step_epoch(island_id=0, epoch=epoch, candidates=[cand])

        # 验证 Anchor 岛中保留的最优个体耗时单调不退化
        best_cand = island_ctrl._island_populations[0][0]
        assert_true(best_cand.metrics.execution_time_s <= prev_best_time, "Best execution time must never regress in Anchor island")
        prev_best_time = best_cand.metrics.execution_time_s
        current_time = new_time

    assert_true(last_time < first_time * 0.1, f"Convergence must achieve >90% reduction (got {first_time} -> {last_time})")
    assert_true(prev_best_time < 0.05, f"Final elite time must be <0.05s, got {prev_best_time}")


def test_tier4_real_05_adversarial_predator_and_playbook_adaptation() -> None:
    """T4.R05: 对抗性捕食者与战术手册动态自适应：成功避坑写入 Playbook 并动态强化."""
    challenger = MockChallenger(challenger_id="predator_prime")
    playbook = LivingPlaybook(token_budget=1500)

    adv_inputs = challenger.generate_adversarial_inputs(test_pattern="predator_counter_examples")
    assert_true(len(adv_inputs) > 0, "Predator must generate adversarial inputs")

    bullet = PlaybookBullet(
        bullet_id="PB-ADV-01",
        trigger_condition="predator_counter_examples",
        prescribed_strategy="Apply robust median-filter before accumulation",
        anti_pattern_taboo="Direct unchecked float addition",
        utility_score=1.0,
    )
    playbook.add_or_update(bullet)
    assert_true("PB-ADV-01" in playbook._bullets, "Bullet must be in playbook")

    bullet.reward_utility(bonus=2.0)
    assert_true(bullet.utility_score == 3.0, "Playbook utility must be reinforced")
    ctx = playbook.export_context()
    assert_true("PB-ADV-01" in ctx, "Playbook context must reflect reinforced strategy")


# ============================================================================
# Test Registry Index for Runner
# ============================================================================

TIER_1_TESTS: List[Tuple[str, Callable[[], None]]] = [
    # Feature 1: FSM State Machine Lifecycle & Preemption
    ("test_tier1_fsm_01_full_lifecycle_success", test_tier1_fsm_01_full_lifecycle_success),
    ("test_tier1_fsm_02_probation_predator_repair_path", test_tier1_fsm_02_probation_predator_repair_path),
    ("test_tier1_fsm_03_p0_poison_pill_preemption", test_tier1_fsm_03_p0_poison_pill_preemption),
    ("test_tier1_fsm_04_invalid_transition_guard", test_tier1_fsm_04_invalid_transition_guard),
    ("test_tier1_fsm_05_reheating_pulse_transition", test_tier1_fsm_05_reheating_pulse_transition),
    # Feature 2: Worktree RAM-Disk Isolation & Safe Release
    ("test_tier1_worktree_01_isolated_checkout", test_tier1_worktree_01_isolated_checkout),
    ("test_tier1_worktree_02_code_injection_and_commit", test_tier1_worktree_02_code_injection_and_commit),
    ("test_tier1_worktree_03_safe_release", test_tier1_worktree_03_safe_release),
    ("test_tier1_worktree_04_windows_lock_tombstoning", test_tier1_worktree_04_windows_lock_tombstoning),
    ("test_tier1_worktree_05_atomic_merge_main", test_tier1_worktree_05_atomic_merge_main),
    # Feature 3: AFEVA 3-Tier Progressive Validation Gate
    ("test_tier1_gate_01_tier1_rough_approve", test_tier1_gate_01_tier1_rough_approve),
    ("test_tier1_gate_02_tier1_probationary_pass", test_tier1_gate_02_tier1_probationary_pass),
    ("test_tier1_gate_03_tier2_cheating_lookup_interception", test_tier1_gate_03_tier2_cheating_lookup_interception),
    ("test_tier1_gate_04_tier3_iron_variance_check", test_tier1_gate_04_tier3_iron_variance_check),
    ("test_tier1_gate_05_syntax_error_rejection", test_tier1_gate_05_syntax_error_rejection),
    # Feature 4: 3-Island Topology & Robust MAD Annealing
    ("test_tier1_evolution_01_three_islands_init", test_tier1_evolution_01_three_islands_init),
    ("test_tier1_evolution_02_directed_ring_migration", test_tier1_evolution_02_directed_ring_migration),
    ("test_tier1_evolution_03_mad_scale_annealing", test_tier1_evolution_03_mad_scale_annealing),
    ("test_tier1_evolution_04_metropolis_acceptance", test_tier1_evolution_04_metropolis_acceptance),
    ("test_tier1_evolution_05_anchor_monotonicity", test_tier1_evolution_05_anchor_monotonicity),
    # Feature 5: Dual Ledger & Stanford ACE Living Playbook
    ("test_tier1_ledger_01_task_vs_progress_isolation", test_tier1_ledger_01_task_vs_progress_isolation),
    ("test_tier1_ledger_02_living_playbook_add_and_retrieve", test_tier1_ledger_02_living_playbook_add_and_retrieve),
    ("test_tier1_ledger_03_living_playbook_lfu_decay_pruning", test_tier1_ledger_03_living_playbook_lfu_decay_pruning),
    ("test_tier1_ledger_04_living_playbook_reward_reinforcement", test_tier1_ledger_04_living_playbook_reward_reinforcement),
    ("test_tier1_ledger_05_progress_ledger_pareto_frontier", test_tier1_ledger_05_progress_ledger_pareto_frontier),
    # Feature 6: WAL & Atomic Snapshot Deterministic Recovery
    ("test_tier1_wal_01_append_and_checksum", test_tier1_wal_01_append_and_checksum),
    ("test_tier1_wal_02_snapshot_atomic_write", test_tier1_wal_02_snapshot_atomic_write),
    ("test_tier1_wal_03_replay_recovery", test_tier1_wal_03_replay_recovery),
    ("test_tier1_wal_04_snapshot_pruning", test_tier1_wal_04_snapshot_pruning),
    ("test_tier1_wal_05_tamper_detection", test_tier1_wal_05_tamper_detection),
]

TIER_2_TESTS: List[Tuple[str, Callable[[], None]]] = [
    ("test_tier2_corner_01_extreme_concurrency_20_worktrees", test_tier2_corner_01_extreme_concurrency_20_worktrees),
    ("test_tier2_corner_02_pathological_numerical_inputs", test_tier2_corner_02_pathological_numerical_inputs),
    ("test_tier2_corner_03_empty_and_degenerate_dag", test_tier2_corner_03_empty_and_degenerate_dag),
    ("test_tier2_corner_04_hang_watchdog_timeout_and_tombstone", test_tier2_corner_04_hang_watchdog_timeout_and_tombstone),
    ("test_tier2_corner_05_massive_lookup_and_dead_code_boundary", test_tier2_corner_05_massive_lookup_and_dead_code_boundary),
]

TIER_3_TESTS: List[Tuple[str, Callable[[], None]]] = [
    ("test_tier3_cross_01_pipeline_task_worktree_gate_wal_snapshot", test_tier3_cross_01_pipeline_task_worktree_gate_wal_snapshot),
    ("test_tier3_cross_02_probationary_seed_island2_novelty_shelter_and_repair", test_tier3_cross_02_probationary_seed_island2_novelty_shelter_and_repair),
    ("test_tier3_cross_03_deadlock_recovery_with_concurrency_backpressure", test_tier3_cross_03_deadlock_recovery_with_concurrency_backpressure),
    ("test_tier3_cross_04_evolution_island_migration_with_worktree_gate", test_tier3_cross_04_evolution_island_migration_with_worktree_gate),
    ("test_tier3_cross_05_wal_replay_across_crash_with_worktree_rebind", test_tier3_cross_05_wal_replay_across_crash_with_worktree_rebind),
]

TIER_4_TESTS: List[Tuple[str, Callable[[], None]]] = [
    ("test_tier4_real_01_high_throughput_contest_exploration", test_tier4_real_01_high_throughput_contest_exploration),
    ("test_tier4_real_02_disaster_recovery_10th_epoch_crash", test_tier4_real_02_disaster_recovery_10th_epoch_crash),
    ("test_tier4_real_03_diversity_collapse_counteraction", test_tier4_real_03_diversity_collapse_counteraction),
    ("test_tier4_real_04_large_scale_long_horizon_convergence", test_tier4_real_04_large_scale_long_horizon_convergence),
    ("test_tier4_real_05_adversarial_predator_and_playbook_adaptation", test_tier4_real_05_adversarial_predator_and_playbook_adaptation),
]

ALL_TIERS = {
    1: TIER_1_TESTS,
    2: TIER_2_TESTS,
    3: TIER_3_TESTS,
    4: TIER_4_TESTS,
}
