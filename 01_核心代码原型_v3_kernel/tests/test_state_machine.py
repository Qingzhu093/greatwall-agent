"""
Comprehensive Verification Suite for Milestone 2: Core State Machine Engine & Scheduling Primitives.
Target Repository: tests/test_state_machine.py
Includes:
1. Imports and type check
2. 14-state FSM state matrix, categories, and guard validators
3. Event priority min-heap queue & causal tokens
4. WAL append-only, SHA-256 integrity, deterministic replay, and crash recovery
5. Atomic snapshot engine, .tmp write, os.replace, checksum verification, and pruning
6. DualLedger (TaskLedger, ProgressLedger Pareto frontier) and LivingPlaybook LFU-Decay
7. TaskScheduler credit backpressure, WatchdogMonitor heartbeats, and DeadlockDetector:
   - Monotonic causal rank verification
   - Tarjan SCC single-cycle detection and breaking
   - Self-loop dependency deadlock detection (size-1 SCC) and severing
   - Multi-cycle composite topology (figure-8 / shared-vertex SCC) multi-iteration breaking
   - Semantic spin progress metric (Psi_progress)
8. AsyncFSMDriver lifecycle, hook triggers, LocalJoinBarrier, and P0 poison pill failover
9. Diamond barrier DAG, TaskScheduler concurrent execution, and event loop priority preemption
"""

import asyncio
import heapq
import os
import shutil
import sys
import tempfile
import time
from typing import Dict, List, Set, Tuple

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import src
import src.core as core
from src.core import (
    # State & FSM
    FSMState,
    StateCategory,
    AsyncFSMDriver,
    LocalJoinBarrier,
    VALID_TRANSITIONS,
    can_transition,
    validate_transition,
    register_transition_guard,
    get_state_category,
    # Events
    FSMEvent,
    EventPriority,
    CausalToken,
    create_poison_pill_event,
    create_heartbeat_event,
    create_causal_event,
    create_stage_gate_event,
    create_reheating_event,
    create_tick_event,
    TaskDispatchPayload,
    GateVerdictPayload,
    PoisonPillPayload,
    # Persistence
    WriteAheadLog,
    WALEntry,
    AtomicSnapshotEngine,
    FSMStateSnapshot,
    # Ledger & Playbook
    DualLedger,
    TaskLedger,
    ProgressLedger,
    LivingPlaybook,
    PlaybookBullet,
    # Scheduling & Guards
    TaskScheduler,
    WatchdogMonitor,
    DeadlockDetector,
    CancellationToken,
    ScheduledTask,
    # Contracts
    PhysicalMetrics,
    BehavioralProfile,
    WorktreeSpec,
    DiffSpec,
    GateVerdict,
    GateStatus,
    ForensicAuditVerdict,
    AuditCode,
    CandidateSolution,
    EpochSummary,
    # Exceptions
    AFEVASystemError,
    InvalidTransitionException,
    CausalDeadlockException,
    AttentionDilutionAlert,
    WALCorruptionError,
    SnapshotError,
)


def log_test(name: str):
    print(f"\n[RUNNING] {name}...")


def assert_true(cond: bool, msg: str):
    if not cond:
        raise AssertionError(f"Check failed: {msg}")


def assert_eq(a, b, desc: str):
    if a != b:
        raise AssertionError(f"Check failed: {desc} (expected {b}, got {a})")


def test_imports_and_types():
    log_test("test_imports_and_types")
    assert_true(src.__version__ == "2.4.0", "Version must be 2.4.0")
    assert_true(len(FSMState) >= 14, "FSMState must contain at least 14 states")
    for s in FSMState:
        cat = s.category
        assert_true(isinstance(cat, StateCategory), f"State {s} must have a valid StateCategory")
    print("  -> All core modules, classes, and enums imported and typed cleanly.")


def test_fsm_state_matrix_and_guards():
    log_test("test_fsm_state_matrix_and_guards")
    # Valid normal transitions
    assert_true(can_transition(FSMState.S01_IDLE, FSMState.S02_SEEDING, context={"task_id": "T1"}), "S01 -> S02 should be allowed with task_id")
    assert_true(can_transition(FSMState.S02_SEEDING, FSMState.S03_BLIND_IDEATION), "S02 -> S03 should be allowed")
    assert_true(can_transition(FSMState.S03_BLIND_IDEATION, FSMState.S04_CODE_SYNTHESIS), "S03 -> S04 should be allowed")
    assert_true(can_transition(FSMState.S04_CODE_SYNTHESIS, FSMState.S05_ROUGH_EVAL), "S04 -> S05 should be allowed")
    assert_true(can_transition(FSMState.S05_ROUGH_EVAL, FSMState.S06_PROBATION), "S05 -> S06 should be allowed for probation")
    assert_true(can_transition(FSMState.S05_ROUGH_EVAL, FSMState.S09_STAGING_EVAL), "S05 -> S09 should be allowed for direct pass")
    assert_true(can_transition(FSMState.S05_ROUGH_EVAL, FSMState.S14_APOPTOSIS_FLUSH), "S05 -> S14 should be allowed for reject")
    assert_true(can_transition(FSMState.S11_IRON_EVAL, FSMState.S12_ATOMIC_COMMIT, context={"iron_pass": True}), "S11 -> S12 should pass with iron_pass")

    # Reheating transitions
    assert_true(can_transition(FSMState.S05_ROUGH_EVAL, FSMState.S13_REHEATING_PULSE), "S05 -> S13 reheating pulse allowed")
    assert_true(can_transition(FSMState.S13_REHEATING_PULSE, FSMState.S03_BLIND_IDEATION), "S13 -> S03 allowed after reheating")

    # Invalid transitions
    assert_true(not can_transition(FSMState.S01_IDLE, FSMState.S12_ATOMIC_COMMIT), "S01 -> S12 must NOT be allowed directly")
    assert_true(not can_transition(FSMState.S04_CODE_SYNTHESIS, FSMState.S12_ATOMIC_COMMIT), "S04 -> S12 must NOT be allowed directly")

    # Exception check
    try:
        validate_transition(FSMState.S01_IDLE, FSMState.S12_ATOMIC_COMMIT)
        assert_true(False, "Should have raised InvalidTransitionException")
    except InvalidTransitionException:
        pass

    # Emergency transition rule: P0 / Emergency can transition any state to S14_APOPTOSIS_FLUSH or S14_FAILED
    assert_true(can_transition(FSMState.S04_CODE_SYNTHESIS, FSMState.S14_APOPTOSIS_FLUSH, is_emergency=True), "Emergency S04 -> S14 must be allowed")
    assert_true(can_transition(FSMState.S08_HYBRID_REPAIR, FSMState.S14_FAILED, is_emergency=True), "Emergency S08 -> S14_FAILED must be allowed")

    # Custom guard registration test
    def custom_guard(from_s, to_s, ctx):
        return ctx.get("secret_key") == "OPEN_SESAME"

    register_transition_guard(FSMState.S06_PROBATION, FSMState.S07_PREDATOR_PAIRING, custom_guard)
    assert_true(not can_transition(FSMState.S06_PROBATION, FSMState.S07_PREDATOR_PAIRING, context={}), "Guard should reject without secret_key")
    assert_true(can_transition(FSMState.S06_PROBATION, FSMState.S07_PREDATOR_PAIRING, context={"secret_key": "OPEN_SESAME"}), "Guard should accept with secret_key")
    print("  -> FSM transition matrix, categories, and guard validators passed.")


def test_events_and_priority_queue():
    log_test("test_events_and_priority_queue")
    tok = CausalToken(
        token_id="tok_test_01",
        causal_level=1,
        parent_token_ids=(),
        payload_cas_hash="sha256:abc123",
        is_speculative=False,
    )
    assert_true(not tok.is_expired(), "New token should not be expired")

    # Test EventPriority ordering: P0 < P1 < P2 < P3
    assert_true(EventPriority.P0_CRITICAL_POISON < EventPriority.P1_STAGE_GATE_EVAL, "P0 must precede P1")
    assert_true(EventPriority.P1_STAGE_GATE_EVAL < EventPriority.P2_WORKER_PROGRESS, "P1 must precede P2")
    assert_true(EventPriority.P2_WORKER_PROGRESS < EventPriority.P3_BACKGROUND_TICK, "P2 must precede P3")

    p0_evt = create_poison_pill_event(source_state=FSMState.S04_CODE_SYNTHESIS, reason="Dead code cheat detected", token=tok)
    p1_evt = create_heartbeat_event(task_id="T01", progress=0.5, status_msg="TIMEOUT", token=tok)
    p2_evt = create_causal_event("EVT_SYNTHESIS_DONE", FSMState.S04_CODE_SYNTHESIS, FSMState.S05_ROUGH_EVAL, token=tok)
    p3_evt = create_tick_event(token=tok)

    # Priority queue order
    q = []
    heapq.heappush(q, p3_evt)
    heapq.heappush(q, p1_evt)
    heapq.heappush(q, p0_evt)
    heapq.heappush(q, p2_evt)

    popped = [heapq.heappop(q) for _ in range(4)]
    assert_true(popped[0].priority == EventPriority.P0_CRITICAL_POISON, "P0 must pop first")
    assert_true(popped[1].priority == EventPriority.P1_WATCHDOG_HEARTBEAT, "P1 must pop second")
    assert_true(popped[2].priority == EventPriority.P2_CAUSAL_DATAFLOW, "P2 must pop third")
    assert_true(popped[3].priority == EventPriority.P3_BACKGROUND_TICK, "P3 must pop fourth")
    print("  -> EventPriority and min-heap ordering verified.")


def test_wal_logging_and_replay():
    log_test("test_wal_logging_and_replay")
    tmp_dir = tempfile.mkdtemp(prefix="afeva_wal_test_")
    wal_file = os.path.join(tmp_dir, "test_wal.jsonl")

    try:
        with WriteAheadLog(wal_file, auto_sync=True) as wal:
            e1 = wal.append("node_1", FSMState.S01_IDLE, FSMState.S02_SEEDING, "commit_01", {"task_id": "T1"})
            e2 = wal.append("node_1", FSMState.S02_SEEDING, FSMState.S03_BLIND_IDEATION, "commit_02", {"seed": 42})
            e3 = wal.append("node_1", FSMState.S03_BLIND_IDEATION, FSMState.S04_CODE_SYNTHESIS, "commit_03", {"model": "Q3"})

            assert_true(e1.lsn == 1, "LSN must be 1")
            assert_true(e2.lsn == 2, "LSN must be 2")
            assert_true(e3.lsn == 3, "LSN must be 3")
            assert_true(wal.current_lsn == 3, "current_lsn must be 3")

            entries = wal.read_entries(from_lsn=1)
            assert_true(len(entries) == 3, "Should read 3 entries")
            for ent in entries:
                assert_true(ent.verify_integrity(), f"Entry {ent.lsn} checksum must verify")

        # Test deterministic replay on driver
        driver = AsyncFSMDriver(node_id="replay_driver", initial_state=FSMState.S01_IDLE)
        with WriteAheadLog(wal_file) as wal2:
            count = wal2.deterministic_replay(driver, from_lsn=1)
            assert_true(count == 3, f"Expected 3 replayed steps, got {count}")
            assert_true(driver.get_current_state() == FSMState.S04_CODE_SYNTHESIS, f"Driver should be in S04_CODE_SYNTHESIS, got {driver.get_current_state()}")

        # Test truncation
        with WriteAheadLog(wal_file) as wal3:
            pruned = wal3.truncate_before(up_to_lsn=3)
            assert_true(pruned == 2, f"Expected 2 pruned entries, got {pruned}")
            remaining = wal3.read_entries(from_lsn=0)
            assert_true(len(remaining) == 1, f"Expected 1 remaining entry, got {len(remaining)}")
            assert_true(remaining[0].lsn == 3, "Remaining entry must be LSN 3")

        # Test tampering corruption detection
        with open(wal_file, "a", encoding="utf-8") as f:
            f.write('{"lsn": 4, "timestamp": 123.0, "node_id": "x", "from_state": "S01_IDLE", "to_state": "S02_SEEDING", "commit_hash": "c", "payload": {"foo": "bar"}, "payload_checksum": "corrupted_checksum"}\n')

        try:
            with WriteAheadLog(wal_file) as wal_corrupt:
                wal_corrupt.read_entries()
            assert_true(False, "Should have raised WALCorruptionError on corrupted checksum")
        except WALCorruptionError:
            pass

        print("  -> WAL append-only, cryptographic checksum, deterministic replay, and truncation verified.")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_atomic_snapshot_engine():
    log_test("test_atomic_snapshot_engine")
    tmp_dir = tempfile.mkdtemp(prefix="afeva_snap_test_")

    try:
        engine = AtomicSnapshotEngine(tmp_dir)

        snap1 = FSMStateSnapshot.create(
            lsn=10,
            current_state=FSMState.S05_ROUGH_EVAL,
            git_commit_hash="c3a4f8e123456789abcdef",
            context_variables={"temperature": 0.88, "epoch": 2},
            completed_tasks=["task_01", "task_02"],
        )
        assert_true(snap1.verify_integrity(), "Snapshot self-checksum must verify")

        path1 = engine.save_snapshot(snap1)
        assert_true(os.path.exists(path1), "Snapshot file must exist")
        assert_true(os.path.exists(engine.latest_link_path), "latest_snapshot.json must exist")

        # Load back
        loaded = engine.load_latest_snapshot()
        assert_true(loaded is not None, "Loaded snapshot must not be None")
        assert_true(loaded.lsn == 10, "Loaded LSN must match")
        assert_true(loaded.git_commit_hash == snap1.git_commit_hash, "Commit hash must match")
        assert_true(loaded.current_state == FSMState.S05_ROUGH_EVAL.value, "State must match")

        # Save higher LSN snapshot
        snap2 = FSMStateSnapshot.create(
            lsn=20,
            current_state=FSMState.S12_ATOMIC_COMMIT,
            git_commit_hash="d999999999999999abcdef",
            context_variables={"temperature": 0.50, "epoch": 5},
            completed_tasks=["task_01", "task_02", "task_03"],
        )
        engine.save_snapshot(snap2)

        loaded2 = engine.load_latest_snapshot()
        assert_true(loaded2.lsn == 20, "Latest snapshot must now be LSN 20")

        # Prune test
        snaps = engine.list_snapshots()
        assert_true(len(snaps) == 2, "Should have 2 snapshots listed")
        pruned = engine.prune_snapshots(keep_count=1)
        assert_true(pruned == 1, "Pruned 1 snapshot")
        assert_true(len(engine.list_snapshots()) == 1, "Should have 1 snapshot remaining")

        print("  -> Atomic snapshot write, rename, checksum verification, and pruning verified.")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_dual_ledger_and_living_playbook():
    log_test("test_dual_ledger_and_living_playbook")
    dual_ledger = DualLedger(playbook_budget=1500)

    # 1. Test TaskLedger
    dual_ledger.task_ledger.register_task("task_A", causal_level=1, dependencies=set())
    dual_ledger.task_ledger.register_task("task_B", causal_level=2, dependencies={"task_A"})

    assert_true(dual_ledger.task_ledger.is_task_ready("task_A"), "task_A has no deps, should be ready")
    assert_true(not dual_ledger.task_ledger.is_task_ready("task_B"), "task_B depends on task_A, should not be ready")

    dual_ledger.task_ledger.mark_completed("task_A", artifact_hash="sha256:art_A")
    assert_true(dual_ledger.task_ledger.is_task_ready("task_B"), "task_B should be ready after task_A completed")

    proj_active = dual_ledger.project_active_dependencies()
    assert_true(proj_active["completed_count"] == 1, "Completed count should be 1")

    # 2. Test ProgressLedger & Pareto frontier
    c1 = CandidateSolution(
        candidate_id="c1",
        parent_id=None,
        island_id=0,
        ast_hash="ast_01",
        source_code_cas_hash="cas_01",
        metrics=PhysicalMetrics(execution_time_s=100.0, peak_memory_bytes=1000, collision_penalty=0.0, exit_code=0),
    )
    # c2: faster but higher collision
    c2 = CandidateSolution(
        candidate_id="c2",
        parent_id="c1",
        island_id=1,
        ast_hash="ast_02",
        source_code_cas_hash="cas_02",
        metrics=PhysicalMetrics(execution_time_s=50.0, peak_memory_bytes=2000, collision_penalty=0.05, exit_code=0),
    )
    # c3: completely dominated by c1 (slower, more memory, more collision)
    c3 = CandidateSolution(
        candidate_id="c3",
        parent_id="c1",
        island_id=0,
        ast_hash="ast_03",
        source_code_cas_hash="cas_03",
        metrics=PhysicalMetrics(execution_time_s=200.0, peak_memory_bytes=3000, collision_penalty=0.1, exit_code=0),
    )

    dual_ledger.progress_ledger.record_candidate(c1)
    dual_ledger.progress_ledger.record_candidate(c2)
    dual_ledger.progress_ledger.record_candidate(c3)

    pareto = dual_ledger.project_frontier_pareto()
    pareto_ids = {c.candidate_id for c in pareto}
    assert_true("c1" in pareto_ids and "c2" in pareto_ids, "c1 and c2 must be in Pareto frontier")
    assert_true("c3" not in pareto_ids, "Dominated c3 must NOT be in Pareto frontier")

    # 3. Test Stanford ACE LivingPlaybook
    playbook = LivingPlaybook(token_budget=1500)
    for i in range(10):
        pb = PlaybookBullet(
            bullet_id=f"PB-{i:03d}",
            trigger_condition=f"Dense pairwise Euclidean loops with N={i*100}",
            prescribed_strategy="Use np.einsum('ijk,ijk->ij', delta, delta) vectorized broadcasting",
            anti_pattern_taboo="Never write nested Python for loops over particles",
            utility_score=1.0 + i * 0.5,
        )
        playbook.add_or_update(pb)

    # LFU-Decay
    playbook.decay_all(decay_factor=0.9)
    # Prune
    pruned_count = playbook.prune_lfu(max_bullets=5)
    assert_true(pruned_count == 5, f"Expected 5 pruned bullets, got {pruned_count}")

    ctx = playbook.export_context(max_tokens=1500)
    assert_true("PB-009" in ctx, "Highest utility bullet must be retained")
    tokens = LivingPlaybook.estimate_tokens(ctx)
    assert_true(tokens <= 1500, f"Context tokens {tokens} must be <= 1500")

    # Redline test: request > 2000 tokens raises AttentionDilutionAlert
    try:
        LivingPlaybook(token_budget=2500)
        assert_true(False, "Should have raised AttentionDilutionAlert for budget > 2000")
    except AttentionDilutionAlert:
        pass

    print("  -> DualLedger (TaskLedger, ProgressLedger) and LivingPlaybook LFU-Decay passed.")


def test_scheduler_watchdog_and_deadlocks():
    log_test("test_scheduler_watchdog_and_deadlocks")

    # 1. Test TaskScheduler Credit Backpressure
    scheduler = TaskScheduler(max_concurrency=4)
    assert_true(scheduler.get_available_credit() == 4, "Initial credit must be 4")
    granted = scheduler.request_credit(2)
    assert_true(granted == 2, "Granted 2 credits")

    # 2. Test WatchdogMonitor heartbeat & timeout
    timeouts_caught = []
    watchdog = WatchdogMonitor(
        check_interval_s=0.1,
        default_timeout_s=0.2,
        on_timeout_cb=lambda tid, reason: timeouts_caught.append((tid, reason)),
    )
    cancel_tok = CancellationToken()
    watchdog.register_task("task_hung", timeout_s=0.15, cancel_token=cancel_tok)
    time.sleep(0.05)
    watchdog.record_heartbeat("task_hung")
    time.sleep(0.08)
    # Still within 0.15s from last heartbeat
    timed_out = watchdog.check_timeouts()
    assert_true(len(timed_out) == 0, "Task should not be timed out yet")

    time.sleep(0.18)
    timed_out2 = watchdog.check_timeouts()
    assert_true("task_hung" in timed_out2, "task_hung should have timed out")
    assert_true(cancel_tok.is_cancelled, "Cancellation token should be triggered")
    assert_true(len(timeouts_caught) == 1, "Timeout callback should be invoked")

    # 3. Test DeadlockDetector: Monotonic causal ranks
    detector = DeadlockDetector(semantic_spin_threshold=0.05)
    detector.register_causal_rank("u", 1)
    detector.register_causal_rank("v", 2)
    detector.verify_monotonic_causality("u", "v")  # 1 < 2 OK

    try:
        detector.verify_monotonic_causality("v", "u")  # 2 >= 1 Violation!
        assert_true(False, "Should have raised CausalDeadlockException")
    except CausalDeadlockException:
        pass

    # 4. Tarjan SCC Deadlock Cycle Detection & Breaking (Single Cycle)
    # Cycle: A -> B -> C -> A
    cycle_graph = {
        "A": {"B"},
        "B": {"C"},
        "C": {"A"},
        "D": set(),
    }
    cycles = detector.detect_cycles(cycle_graph)
    assert_true(len(cycles) == 1, "Should detect 1 cycle")
    assert_true(set(cycles[0]) == {"A", "B", "C"}, "Cycle should contain A, B, C")

    severed = detector.resolve_deadlocks(cycle_graph)
    assert_true(len(severed) >= 1, "Should sever at least 1 edge")
    cycles_after = detector.detect_cycles(cycle_graph)
    assert_true(len(cycles_after) == 0, "No cycles should remain after resolution")

    # 5. DeadlockDetector: Self-Loop Deadlock Detection & Breaking (Finding 2)
    # Case: A -> A (Size-1 SCC with self-dependency)
    self_loop_graph = {"A": {"A"}, "B": {"C"}, "C": set()}
    self_loop_cycles = detector.detect_cycles(self_loop_graph)
    assert_true(len(self_loop_cycles) == 1, "detect_cycles must detect size-1 self-loop deadlocks")
    assert_true(self_loop_cycles[0] == ["A"], "Detected cycle must be ['A']")
    severed_self = detector.resolve_deadlocks(self_loop_graph)
    assert_true(("A", "A") in severed_self, "resolve_deadlocks must sever self-loop edge ('A', 'A')")
    assert_true(len(detector.detect_cycles(self_loop_graph)) == 0, "Self loop must be fully eliminated")

    # 6. DeadlockDetector: Multi-Cycle Figure-8 Topology Breaking (Finding 1)
    # Two cycles sharing node C: A -> B -> C -> A and C -> D -> E -> C
    fig8_graph = {
        "A": {"B"},
        "B": {"C"},
        "C": {"A", "D"},
        "D": {"E"},
        "E": {"C"},
    }
    cycles_fig8_before = detector.detect_cycles(fig8_graph)
    assert_true(len(cycles_fig8_before) >= 1, "Figure-8 must be detected as cyclic deadlocks")
    severed_fig8 = detector.resolve_deadlocks(fig8_graph, max_iterations=50)
    assert_true(len(severed_fig8) >= 2, f"Figure-8 requires at least 2 edges severed to eliminate both cycles, got {len(severed_fig8)}")
    cycles_fig8_after = detector.detect_cycles(fig8_graph)
    assert_true(len(cycles_fig8_after) == 0, f"All cycles in composite figure-8 must be eliminated, remaining: {len(cycles_fig8_after)}")

    # 7. Semantic Spin Metric: Psi_progress = Delta Phenotype / (Delta AST + epsilon)
    # Branch 1: good progress (high phenotype improvement per AST change)
    for _ in range(3):
        detector.record_semantic_progress("branch_good", phenotype_delta=10.0, ast_distance=5.0)
    assert_true(not detector.is_semantic_spinning("branch_good"), "branch_good should not be spinning")

    # Branch 2: busywork spin (huge AST changes, zero phenotype improvement)
    for _ in range(3):
        detector.record_semantic_progress("branch_spinning", phenotype_delta=0.0001, ast_distance=20.0)
    assert_true(detector.is_semantic_spinning("branch_spinning"), "branch_spinning should be detected as spinning")

    print("  -> TaskScheduler backpressure, Watchdog timeout, Tarjan SCC self-loop & figure-8 composite deadlock resolution, and semantic spin metric passed.")


async def async_test_driver_and_local_join_barrier():
    log_test("async_test_driver_and_local_join_barrier")

    # 1. LocalJoinBarrier
    barrier = LocalJoinBarrier()
    barrier.register_barrier("task_downstream", required_predecessors={"task_1", "task_2"})
    assert_true(not barrier.is_ready("task_downstream"), "Downstream task should not be ready")

    # Only task 1 completes
    unblocked = barrier.notify_completed("task_1", artifact_hash="hash_1")
    assert_true(len(unblocked) == 0, "task_downstream should still be waiting for task 2")

    # Task 2 completes
    unblocked2 = barrier.notify_completed("task_2", artifact_hash="hash_2")
    assert_true("task_downstream" in unblocked2, "task_downstream must be unblocked")
    assert_true(barrier.is_ready("task_downstream"), "task_downstream is now ready")

    # 2. AsyncFSMDriver lifecycle
    tmp_dir = tempfile.mkdtemp(prefix="afeva_engine_test_")
    wal_path = os.path.join(tmp_dir, "wal.jsonl")
    snap_dir = os.path.join(tmp_dir, "snapshots")

    wal = WriteAheadLog(wal_path)
    snap_engine = AtomicSnapshotEngine(snap_dir)
    ledger = DualLedger()
    driver = AsyncFSMDriver(
        node_id="test_worker_1",
        initial_state=FSMState.S01_IDLE,
        wal=wal,
        snapshot_engine=snap_engine,
        ledger=ledger,
    )

    entered_states = []
    exited_states = []

    def hook_enter(state, from_state, evt):
        entered_states.append(state)

    def hook_exit(from_state, to_state, evt):
        exited_states.append(from_state)

    driver.register_state_hook(FSMState.S02_SEEDING, on_enter=hook_enter, on_exit=hook_exit)
    driver.register_state_hook(FSMState.S03_BLIND_IDEATION, on_enter=hook_enter, on_exit=hook_exit)
    driver.register_state_hook(FSMState.S04_CODE_SYNTHESIS, on_enter=hook_enter, on_exit=hook_exit)

    # Transition 1: S01 -> S02
    e1 = create_causal_event(
        event_type="EVT_INIT_TASK",
        source_state=FSMState.S01_IDLE,
        target_state_hint=FSMState.S02_SEEDING,
        token=CausalToken("tok1", 1, (), "hash1"),
        payload={"task_id": "T001", "session_id": "SESS_1"},
    )
    s2 = await driver.transition(e1)
    assert_true(s2 == FSMState.S02_SEEDING, "State should be S02_SEEDING")
    assert_true(driver.get_current_state() == FSMState.S02_SEEDING, "Current state must be S02_SEEDING")

    # Transition 2: S02 -> S03
    e2 = create_causal_event(
        event_type="EVT_PRIMING_DONE",
        source_state=FSMState.S02_SEEDING,
        target_state_hint=FSMState.S03_BLIND_IDEATION,
        token=CausalToken("tok2", 2, ("tok1",), "hash2"),
        payload={"priming": "OK"},
    )
    s3 = await driver.transition(e2)
    assert_true(s3 == FSMState.S03_BLIND_IDEATION, "State should be S03_BLIND_IDEATION")

    # Transition 3: S03 -> S04
    e3 = create_causal_event(
        event_type="EVT_PROPOSAL_READY",
        source_state=FSMState.S03_BLIND_IDEATION,
        target_state_hint=FSMState.S04_CODE_SYNTHESIS,
        token=CausalToken("tok3", 3, ("tok2",), "hash3"),
        payload={"code_path": "worktree/main.py"},
    )
    s4 = await driver.transition(e3)
    assert_true(s4 == FSMState.S04_CODE_SYNTHESIS, "State should be S04_CODE_SYNTHESIS")

    assert_true(FSMState.S02_SEEDING in entered_states, "S02 enter hook called")
    assert_true(FSMState.S02_SEEDING in exited_states, "S02 exit hook called")
    assert_true(FSMState.S03_BLIND_IDEATION in entered_states, "S03 enter hook called")

    # Test P0 Poison Pill preemption: immediately cancels in-flight tasks and forces transition to S14_APOPTOSIS_FLUSH
    poison_evt = create_poison_pill_event(
        source_state=FSMState.S04_CODE_SYNTHESIS,
        reason="Lookup table cheat detected in forensic audit",
    )
    s14 = await driver.transition(poison_evt)
    assert_true(s14 == FSMState.S14_APOPTOSIS_FLUSH, "State must transition to S14_APOPTOSIS_FLUSH upon poison pill")
    assert_true(driver.get_current_state() == FSMState.S14_APOPTOSIS_FLUSH, "Current state must be S14_APOPTOSIS_FLUSH")

    # Test Graceful Shutdown
    await driver.shutdown(save_snapshot=True)
    latest_snap = snap_engine.load_latest_snapshot()
    assert_true(latest_snap is not None, "Shutdown snapshot must be recorded")
    assert_true(latest_snap.current_state == FSMState.S14_APOPTOSIS_FLUSH.value, "Snapshot must record S14 state")

    shutil.rmtree(tmp_dir, ignore_errors=True)
    print("  -> AsyncFSMDriver full lifecycle, hooks, LocalJoinBarrier, P0 poison pill, and shutdown passed.")


async def async_test_advanced_concurrency_and_diamond_barrier():
    log_test("async_test_advanced_concurrency_and_diamond_barrier")

    # 1. Diamond Barrier Test: A -> B, A -> C; B & C -> D
    barrier = LocalJoinBarrier()
    barrier.register_barrier("B", {"A"})
    barrier.register_barrier("C", {"A"})
    barrier.register_barrier("D", {"B", "C"})

    assert_true(not barrier.is_ready("B"), "B not ready before A")
    assert_true(not barrier.is_ready("C"), "C not ready before A")
    assert_true(not barrier.is_ready("D"), "D not ready before B & C")

    # A finishes
    ready_after_A = barrier.notify_completed("A", artifact_hash="hash_A")
    assert_true(set(ready_after_A) == {"B", "C"}, "Both B and C should unblock after A")
    assert_true(barrier.is_ready("B") and barrier.is_ready("C"), "B and C are ready")

    # B finishes
    ready_after_B = barrier.notify_completed("B", artifact_hash="hash_B")
    assert_true(len(ready_after_B) == 0, "D should not be ready with only B finished")

    # C finishes
    ready_after_C = barrier.notify_completed("C", artifact_hash="hash_C")
    assert_true("D" in ready_after_C, "D must unblock when C finishes")
    assert_true(barrier.is_ready("D"), "D is now ready")

    # 2. Concurrency in TaskScheduler
    scheduler = TaskScheduler(max_concurrency=3)
    results = []

    async def worker(n: int):
        await asyncio.sleep(0.02)
        results.append(n)
        return n * 10

    for i in range(6):
        await scheduler.schedule_coro(f"t_{i}", worker, args=(i,))

    worker_tasks = [asyncio.create_task(scheduler.run_next()) for _ in range(6)]
    out = await asyncio.gather(*worker_tasks)
    assert_true(len(out) == 6, "All 6 tasks should complete")
    assert_true(set(results) == {0, 1, 2, 3, 4, 5}, "All workers executed")

    # 3. Priority Preemption with Event Queue in run_cycle
    driver = AsyncFSMDriver(node_id="cycle_driver", initial_state=FSMState.S01_IDLE)

    # Submit lower priority tick
    tick = create_tick_event(source_state=FSMState.S01_IDLE)
    # Submit P0 Poison Pill
    p0 = create_poison_pill_event(source_state=FSMState.S01_IDLE, reason="Urgent halt")

    await driver.submit_event(tick)
    await driver.submit_event(p0)

    # run_cycle should pop P0 first despite being submitted second!
    await driver.run_cycle()
    assert_true(driver.get_current_state() == FSMState.S14_APOPTOSIS_FLUSH, "P0 must be popped first and transition driver to S14")

    print("  -> Diamond barrier DAG, TaskScheduler concurrent workers, and priority preemption in event loop verified.")


def main():
    print("================================================================================")
    print("  AFEVA Milestone 2 Core Concurrency Engine & State Machine Test Suite")
    print("  Location: tests/test_state_machine.py")
    print("================================================================================")
    start_time = time.time()

    test_imports_and_types()
    test_fsm_state_matrix_and_guards()
    test_events_and_priority_queue()
    test_wal_logging_and_replay()
    test_atomic_snapshot_engine()
    test_dual_ledger_and_living_playbook()
    test_scheduler_watchdog_and_deadlocks()
    asyncio.run(async_test_driver_and_local_join_barrier())
    asyncio.run(async_test_advanced_concurrency_and_diamond_barrier())

    elapsed = time.time() - start_time
    print("\n================================================================================")
    print(f"  ALL TESTS PASSED SUCCESSFULLY! Elapsed: {elapsed:.2f}s")
    print("================================================================================")


if __name__ == "__main__":
    main()
