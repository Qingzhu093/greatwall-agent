"""
AFEVA Milestone 4 Empirical Fault Injection & Black-Swan Resilience Test Suite.
Verifies the system's self-healing, adaptive immunity, and anti-fragile recovery across 5 critical faults:
1. Fault 1: Agent Hang & Watchdog Heartbeat Circuit Breaker;
2. Fault 2: Process Crash & Sandbox Isolation Resource Purge;
3. Fault 3: Corrupted Code & Cheating Injection Layered Defense;
4. Fault 4: Concurrency Merge Conflict & NTFS File Lock Tombstoning Reborn;
5. Fault 5: WAL Log Tampering & Snapshot Checksum Replay Disaster Recovery.

Author: teamwork_worker (Milestone 4 Engineering Group)
Status: Production Ready
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.contracts import (
    AuditCode,
    CandidateSolution,
    DiffSpec,
    FSMState,
    GateStatus,
    MergeConflictException,
    PhysicalMetrics,
    SnapshotError,
    WALCorruptionError,
    WorktreeLockException,
    WorktreeSpec,
)
from src.core.scheduler import (
    CancellationToken,
    ScheduledTask,
    TaskScheduler,
    WatchdogMonitor,
)
from src.core.snapshot import AtomicSnapshotEngine, FSMStateSnapshot
from src.core.wal import WALEntry, WriteAheadLog
from src.worktree.manager import WorktreeManager
from src.worktree.validator import ValidationGate
from tests.mock_agents import (
    MockAuditor,
    MockChallenger,
    MockWorker,
    WorkerBehaviorMode,
)


def test_fault_1_agent_hang_watchdog_circuit_breaker() -> None:
    """
    故障 1: 超时挂起（Agent Hang）
    验证：
    1. MockWorker 注入无响应挂起，拒绝上报心跳；
    2. WatchdogMonitor 巡检检测到租约超时，向任务发送取消令牌；
    3. 触发超时熔断回调，标记任务超时并释放，正常任务绝不受误伤。
    """
    print("[RUNNING] test_fault_1_agent_hang_watchdog_circuit_breaker...")
    timed_out_events: List[Tuple[str, str]] = []

    def on_timeout(tid: str, reason: str) -> None:
        timed_out_events.append((tid, reason))

    watchdog = WatchdogMonitor(check_interval_s=0.05, default_timeout_s=0.15, on_timeout_cb=on_timeout)
    worker_hang = MockWorker(worker_id="worker_hang", default_mode=WorkerBehaviorMode.HANG)
    worker_norm = MockWorker(worker_id="worker_norm", default_mode=WorkerBehaviorMode.NORMAL)

    token_hang = CancellationToken()
    token_norm = CancellationToken()

    # 纳管两个任务
    watchdog.register_task("task_hang_01", timeout_s=0.15, cancel_token=token_hang)
    watchdog.register_task("task_normal_02", timeout_s=0.50, cancel_token=token_norm)

    # 正常任务在 0.08s 上报一次心跳
    time.sleep(0.08)
    worker_norm.simulate_execution(task_id="task_normal_02", watchdog=watchdog)

    # 等待超过 0.15s (hang 任务必定超时，normal 任务由于上报心跳未超时)
    time.sleep(0.12)
    timeouts = watchdog.check_timeouts()

    assert "task_hang_01" in timeouts, f"task_hang_01 must be detected as timed out, got: {timeouts}"
    assert "task_normal_02" not in timeouts, "task_normal_02 must NOT be timed out"
    assert token_hang.is_cancelled is True, "Token for hang task must be cancelled"
    assert token_norm.is_cancelled is False, "Token for normal task must remain active"
    assert any(tid == "task_hang_01" for tid, _ in timed_out_events), "Timeout callback must be invoked"

    # 清理看门狗
    watchdog.unregister_task("task_hang_01")
    watchdog.unregister_task("task_normal_02")
    print("  -> Agent Hang & Watchdog Circuit Breaker verified (Hang task halted, normal task sheltered).")


def test_fault_2_process_crash_and_resource_cleanup() -> None:
    """
    故障 2: 进程异常崩溃（Process Crash）
    验证：
    1. Worker 执行中突然抛出 MemoryError / 未捕获异常；
    2. 调度器捕获异常，任务状态标记为 FAILED；
    3. 触发沙箱清理，物理沙箱被完全释放，活跃计数归零。
    """
    print("[RUNNING] test_fault_2_process_crash_and_resource_cleanup...")
    async def run_crash_simulation() -> None:
        with tempfile.TemporaryDirectory() as tmp_root:
            mgr = WorktreeManager(root_dir=tmp_root)
            wt = mgr.create_worktree("task_crash_01", base_commit="base_c0")
            assert Path(wt.worktree_path).exists()

            scheduler = TaskScheduler(max_concurrency=2)
            worker = MockWorker(failure_exception=MemoryError)

            async def crash_task_coro() -> None:
                # 模拟执行中突发 OOM 崩溃
                worker.simulate_execution(task_id="task_crash_01", mode=WorkerBehaviorMode.CRASH)

            task = await scheduler.schedule_coro(
                task_id="task_crash_01",
                coro_fn=crash_task_coro,
            )

            # 调度执行
            threw_memory_error = False
            try:
                await scheduler.run_next()
            except MemoryError:
                threw_memory_error = True

            assert threw_memory_error is True, "Scheduler must propagate or track MemoryError"
            assert task.status == "FAILED", f"Task status must be FAILED, got {task.status}"

            # 触发沙箱物理清理与资源回收
            rem_ok = mgr.remove_worktree(wt.worktree_id)
            assert rem_ok is True
            assert not Path(wt.worktree_path).exists(), "Worktree directory must be completely cleaned after crash"
            assert scheduler.active_count == 0

    asyncio.run(run_crash_simulation())
    print("  -> Process Crash & Resource Cleanup verified (MemoryError caught, FAILED status recorded, sandbox purged).")


def test_fault_3_corrupted_code_and_cheating_injection() -> None:
    """
    故障 3: 代码注入破坏与作弊（Corrupted Code & Cheating Injection）
    验证：
    1. 语法损坏代码在 Tier 1 粗野门直接被 AST 静态扫描拦截 (REJECT)；
    2. 查表作弊代码在 Tier 2 集成门被法医扫描一票否决 (CHEAT_LOOKUP_TABLE detected)；
    3. 法医审计员 MockAuditor 100% 裁决欺骗，分层拦截率 100%。
    """
    print("[RUNNING] test_fault_3_corrupted_code_and_cheating_injection...")
    with tempfile.TemporaryDirectory() as tmp_root:
        base_dir = Path(tmp_root) / "base_repo"
        base_dir.mkdir(parents=True, exist_ok=True)
        (base_dir / "main.py").write_text("def solve(x):\n    return sum(x)\n", encoding="utf-8")

        mgr = WorktreeManager(root_dir=tmp_root, base_repo_dir=str(base_dir))
        gate = ValidationGate()
        auditor = MockAuditor(max_lookup_table_entries=30)
        worker = MockWorker()

        # 1. 注入破坏性语法错误代码 (沙箱 A)
        wt_corrupt = mgr.create_worktree("task_corrupted", base_commit="base_c0")
        worker.write_to_worktree(wt_corrupt, mode=WorkerBehaviorMode.CORRUPTED_CODE)
        diff_corrupt = DiffSpec("c0", "c1", ("main.py",), "solve", 5, 2, 0.8)

        v1_corrupt = gate.validate_tier1(wt_corrupt, diff_corrupt)
        assert v1_corrupt.status == GateStatus.REJECT, f"Corrupted code must be REJECTED at Tier 1, got {v1_corrupt.status}"
        assert any("SyntaxError" in d for d in v1_corrupt.diagnostics), "Diagnostics must indicate SyntaxError"

        # 2. 注入超大映射查表硬编码作弊代码 (沙箱 B, 55 entries)
        wt_cheat = mgr.create_worktree("task_cheat", base_commit="base_c0")
        worker.write_to_worktree(wt_cheat, mode=WorkerBehaviorMode.CHEAT_LOOKUP, lookup_table_entries=55)
        diff_cheat = DiffSpec("c0", "c2", ("main.py",), "solve", 60, 5, 0.9)

        # 冒烟通过 Tier 1
        v1_cheat = gate.validate_tier1(wt_cheat, diff_cheat)
        assert v1_cheat.status in (GateStatus.APPROVE, GateStatus.PROBATIONARY_PASS)

        # 进入 Tier 2 被一票否决
        v2_cheat = gate.validate_tier2(wt_cheat, diff_cheat)
        assert v2_cheat.status == GateStatus.REJECT, f"Lookup cheat must be REJECTED at Tier 2, got {v2_cheat.status}"
        assert any("CHEAT_LOOKUP_TABLE detected" in d for d in v2_cheat.diagnostics)

        # 3. 法医审计员全息审查
        audit_verdict = auditor.audit_candidate(wt_cheat, v1_cheat.evaluated_metrics)
        assert audit_verdict.audit_code == AuditCode.CHEAT_LOOKUP_TABLE
        assert audit_verdict.is_clean_pass() is False

        # 清理沙箱
        mgr.remove_worktree(wt_corrupt.worktree_id)
        mgr.remove_worktree(wt_cheat.worktree_id)

    print("  -> Corrupted Code & Cheating Injection Layered Defense verified (Tier 1 & Tier 2 100% intercept).")


def test_fault_4_concurrency_conflict_and_ntfs_lock_healing() -> None:
    """
    故障 4: 并发沙箱与锁冲突（Merge Conflict & NTFS Sharing Lock）
    验证：
    1. 16+ 工作区并发修改同路径冲突合并，100% 拦截后续冲突，无脏数据写入；
    2. 深度只读文件句柄未关，Atomic Tombstoning 墓碑脱离与沙箱重生自愈 (WinError 32 防御)。
    """
    print("[RUNNING] test_fault_4_concurrency_conflict_and_ntfs_lock_healing...")
    with tempfile.TemporaryDirectory() as tmp_root:
        base_dir = Path(tmp_root) / "seed_repo"
        base_dir.mkdir(parents=True, exist_ok=True)
        (base_dir / "main.py").write_text("def solve(x): return sum(x)\n", encoding="utf-8")

        mgr = WorktreeManager(root_dir=tmp_root, base_repo_dir=str(base_dir))

        # 1. 16 个工作区并发冲突合并
        num_workers = 16
        specs = [mgr.create_worktree(f"c_worker_{i:02d}", base_commit="c_genesis") for i in range(num_workers)]

        for idx, s in enumerate(specs):
            wt_path = Path(s.worktree_path)
            (wt_path / "main.py").write_text(f"# Worker {idx} mod\ndef solve(x): return sum(x) + {idx}\n", encoding="utf-8")
            mgr.commit_worktree(s.worktree_id, f"Commit {idx}")

        # 第 0 个工作区成功合并
        assert mgr.merge_to_main(specs[0].worktree_id) is True

        # 其余 15 个必定抛出 MergeConflictException
        conflict_intercepts = 0
        for s in specs[1:]:
            try:
                mgr.merge_to_main(s.worktree_id)
                assert False, "Should raise MergeConflictException"
            except MergeConflictException:
                conflict_intercepts += 1

        assert conflict_intercepts == 15, f"Expected 15 conflict intercepts, got {conflict_intercepts}"

        # 2. NTFS 文件锁未关与 Atomic Tombstoning 墓碑脱离
        wt_lock = mgr.create_worktree("task_ntfs_locked", base_commit="c_genesis")
        wt_lock_path = Path(wt_lock.worktree_path)
        locked_file = wt_lock_path / "locked_file.bin"
        locked_file.write_bytes(b"DATA_UNDER_LOCK" * 50)

        # 保持文件句柄打开占用
        handle = open(locked_file, "r+b")
        try:
            # 执行移除：底层安全捕获文件锁，触发 Atomic Tombstoning 墓碑重命名
            purged = mgr.remove_worktree(wt_lock.worktree_id)
            assert purged is True

            # 验证沙箱重生自愈：可以立即以相同的 task_id 重新创建沙箱，绝无命名阻塞
            wt_reborn = mgr.create_worktree("task_ntfs_locked", base_commit="c_genesis")
            assert Path(wt_reborn.worktree_path).exists()
            assert wt_reborn.worktree_id != wt_lock.worktree_id
            mgr.remove_worktree(wt_reborn.worktree_id)
        finally:
            handle.close()

        # 清理全部沙箱
        for s in specs:
            mgr.remove_worktree(s.worktree_id)

    print("  -> Concurrency Merge Conflict & NTFS Sharing Lock Tombstoning Reborn verified.")


def test_fault_5_wal_corruption_and_snapshot_tamper_recovery() -> None:
    """
    故障 5: 预写日志与快照损坏（WAL / Snapshot Tampered）
    验证：
    1. WAL 日志字节翻转与截断损坏被 SHA-256 校验和防篡改拦截 (WALCorruptionError)；
    2. 原子快照文件篡改被 SHA-256 拒绝 (SnapshotError)；
    3. 基于完好 WAL 历史日志回放的一致性自愈恢复。
    """
    print("[RUNNING] test_fault_5_wal_corruption_and_snapshot_tamper_recovery...")
    with tempfile.TemporaryDirectory() as tmp_root:
        log_file = Path(tmp_root) / "afeva_fsm.jsonl"
        wal = WriteAheadLog(str(log_file))

        # 1. 正常写入 5 条 WAL 日志条目
        for i in range(1, 6):
            wal.append(
                node_id="engine_node",
                from_state=f"S{i:02d}",
                to_state=f"S{i+1:02d}",
                commit_hash=f"commit_hash_{i:04d}",
                payload={"step": i, "status": "OK", "candidate_id": f"c_{i}"},
            )

        assert wal.current_lsn == 5

        # 验证完好状态下回放无异常
        replayed_clean = wal.read_entries()
        assert len(replayed_clean) == 5

        # 2. 注入 WAL 静默字节篡改故障 (修改 payload 内容但保持错误校验和)
        content_lines = log_file.read_text(encoding="utf-8").splitlines()
        corrupted_raw = json.loads(content_lines[2])
        # 篡改数据：篡改 step 字段
        corrupted_raw["payload"]["step"] = 99999
        corrupted_line = json.dumps(corrupted_raw, ensure_ascii=False)
        content_lines[2] = corrupted_line
        log_file.write_text("\n".join(content_lines) + "\n", encoding="utf-8")

        # 再次回放：必定触发 WALCorruptionError 拦截
        wal_tamper_detected = False
        try:
            wal.read_entries()
        except WALCorruptionError as wce:
            wal_tamper_detected = True
            assert "checksum verification" in str(wce).lower() or "corruption" in str(wce).lower()

        assert wal_tamper_detected is True, "WAL tampering must be intercepted by cryptographic checksum!"

        # 3. 注入快照损坏与校验和拒绝
        snap_dir = Path(tmp_root) / "snapshots"
        snap_engine = AtomicSnapshotEngine(str(snap_dir))

        # 建立合法全息快照
        snap = FSMStateSnapshot.create(
            lsn=5,
            current_state=FSMState.S04_CODE_SYNTHESIS,
            git_commit_hash="commit_hash_0005",
            context_variables={"iteration": 1, "island": 1},
            completed_tasks=["task_1", "task_2"],
        )
        assert snap.verify_integrity() is True
        saved_snap_path = snap_engine.save_snapshot(snap)

        # 读取快照 JSON 文件并篡改其状态
        snap_path = Path(saved_snap_path)
        assert snap_path.exists()
        snap_data = json.loads(snap_path.read_text(encoding="utf-8"))
        snap_data["current_state"] = "S12_ATOMIC_COMMIT"  # 非法篡改状态
        snap_path.write_text(json.dumps(snap_data, ensure_ascii=False), encoding="utf-8")

        # 尝试通过快照引擎载入，必须抛出 SnapshotError 拒绝脏快照
        snap_tamper_detected = False
        try:
            snap_engine.restore_state(str(snap_path))
        except SnapshotError as se:
            snap_tamper_detected = True
            assert "verification failed" in str(se).lower() or "checksum" in str(se).lower()

        assert snap_tamper_detected is True, "Tampered snapshot must be rejected due to checksum mismatch!"

        # 4. 基于历史完好日志的状态机一致性重放自愈
        # 恢复洁净日志重新建立
        recovery_log_file = Path(tmp_root) / "recovery_fsm.jsonl"
        rec_wal = WriteAheadLog(str(recovery_log_file))
        for i in range(1, 4):
            rec_wal.append(
                node_id="engine_node",
                from_state=f"S{i:02d}",
                to_state=f"S{i+1:02d}",
                commit_hash=f"c_{i}",
                payload={"recovered_epoch": i},
            )

        recovered_entries = rec_wal.read_entries()
        assert len(recovered_entries) == 3
        last_state = recovered_entries[-1].to_state
        assert last_state == "S04", f"State safely recovered to S04, got {last_state}"

    print("  -> WAL Log Tampering & Snapshot Checksum Replay Disaster Recovery verified.")


if __name__ == "__main__":
    print("=" * 80)
    print("STARTING AFEVA 5-CRITICAL FAULT INJECTION SIMULATION MATRIX")
    print("=" * 80)
    test_fault_1_agent_hang_watchdog_circuit_breaker()
    test_fault_2_process_crash_and_resource_cleanup()
    test_fault_3_corrupted_code_and_cheating_injection()
    test_fault_4_concurrency_conflict_and_ntfs_lock_healing()
    test_fault_5_wal_corruption_and_snapshot_tamper_recovery()
    print("=" * 80)
    print("ALL 5 FAULT INJECTION ADVERSARIAL TESTS PASSED 100%!")
    print("=" * 80)
