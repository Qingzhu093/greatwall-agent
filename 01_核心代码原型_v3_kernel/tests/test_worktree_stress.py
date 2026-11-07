"""
Automated High-Stress Concurrency & Empirical Adversarial Test Suite for AFEVA Worktree & Gateways.
Permanently consolidated from Milestone 3 empirical challenge probes.

Test Coverage:
1. 24+ Concurrent Worktree COW Physical Isolation, SHA-256 Merkle Hash Uniqueness & Merge Conflict Interception;
2. Windows NTFS WinError 32 File Lock Healing, Atomic Tombstoning & Immediate Reborn;
3. AFEVA Tier 2 Forensic Lookup Table Cheat (50+ entries) 100% One-Vote Veto;
4. AFEVA Tier 1 Breakthrough Raw Talent Strict PROBATIONARY_PASS Shelter;
5. AFEVA Tier 3 Iron Gate Determinism, Flaky Rejection & Noise Shield Ceiling Verification.

Author: teamwork_worker (Milestone 3 Remediation Engineering)
Status: Production Ready
"""

from __future__ import annotations

import os
import sys
import time
import uuid
import shutil
import tempfile
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple, Set, Any

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.contracts import (
    WorktreeSpec,
    DiffSpec,
    GateStatus,
    GateVerdict,
    PhysicalMetrics,
    WorktreeLockException,
    MergeConflictException,
    LeaseExpiredException,
)
from src.worktree.manager import WorktreeManager
from src.worktree.validator import ValidationGate


def test_stress_24_concurrent_worktree_isolation_and_conflict_interception(worker_count: int = 24) -> None:
    """
    实证测试 1：24+ 工作区并发 COW 写时复制隔离、SHA-256 哈希唯一性与主干合并冲突拦截 (Reject Blind Overwrite)
    """
    print(f"[RUNNING] test_stress_{worker_count}_concurrent_worktree_isolation_and_conflict_interception...")
    t0 = time.perf_counter()

    with tempfile.TemporaryDirectory() as tmp_root:
        base_dir = Path(tmp_root) / "seed_master_repo"
        base_dir.mkdir(parents=True, exist_ok=True)
        (base_dir / "main.py").write_text(
            '"""Genesis Seed Algorithm"""\n'
            'def solve(inputs):\n'
            '    return sum(inputs)\n',
            encoding="utf-8"
        )
        (base_dir / "meta.cfg").write_text('{"epoch": 0, "genesis": true}', encoding="utf-8")

        mgr = WorktreeManager(root_dir=tmp_root, base_repo_dir=str(base_dir))

        worktrees: Dict[int, WorktreeSpec] = {}
        commit_hashes: Dict[int, str] = {}
        isolation_errors: List[str] = []

        # 阶段 1: 并发创建 24 个工作区并在同一相对路径 main.py 注入各 Worker 独立签名
        def create_and_mutate_worker(idx: int) -> Tuple[int, WorktreeSpec, str]:
            spec = mgr.create_worktree(task_id=f"stress_agent_{idx:02d}", base_commit="c_genesis")
            wt_path = Path(spec.worktree_path)

            # 验证 COW 初始状态与母本一致
            main_code = (wt_path / "main.py").read_text(encoding="utf-8")
            if "Genesis Seed Algorithm" not in main_code:
                raise ValueError(f"Worker {idx} failed to receive initial genesis seed.")

            # 各自独立修改相同相对路径 main.py
            unique_marker = f"# WORKER_SIGNATURE_{idx:03d}_{uuid.uuid4().hex[:8]}"
            mutated_code = (
                f'"""Agent {idx} Specialized Optimization"""\n'
                f'{unique_marker}\n'
                f'def solve(inputs):\n'
                f'    return sum(inputs) + {idx * 100}\n'
            )
            (wt_path / "main.py").write_text(mutated_code, encoding="utf-8")

            # 提交并生成唯一 Commit Hash
            c_hash = mgr.commit_worktree(spec.worktree_id, f"Agent {idx} unique optimization")
            return idx, spec, c_hash

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(create_and_mutate_worker, i) for i in range(worker_count)]
            for fut in as_completed(futures):
                idx, spec, c_hash = fut.result()
                worktrees[idx] = spec
                commit_hashes[idx] = c_hash

        # 阶段 2: 验证物理读写隔离 (无交叉污染)
        for i, spec_i in worktrees.items():
            path_i = Path(spec_i.worktree_path)
            content_i = (path_i / "main.py").read_text(encoding="utf-8")
            expected_sig = f"# WORKER_SIGNATURE_{i:03d}_"
            if expected_sig not in content_i:
                isolation_errors.append(f"Worker {i} lost its own signature.")

            for other in range(worker_count):
                if other == i:
                    continue
                other_sig = f"# WORKER_SIGNATURE_{other:03d}_"
                if other_sig in content_i:
                    isolation_errors.append(f"Isolation leak: Worker {i} polluted by Worker {other}!")

        assert len(isolation_errors) == 0, f"Physical isolation checks failed: {isolation_errors}"

        # 阶段 3: 验证 SHA-256 Commit Hashes 的全局唯一性
        unique_hashes = set(commit_hashes.values())
        assert len(unique_hashes) == worker_count, (
            f"Commit hash collision! Expected {worker_count} unique hashes, got {len(unique_hashes)}"
        )
        for ch in unique_hashes:
            assert len(ch) == 64, f"Commit hash {ch} is not a valid 64-char SHA-256."

        # 阶段 4: 并发合并与冲突拦截实证 (Reject Blind Overwrite)
        # 所有 24 个工作区均修改了同一个 main.py 且基于相同的基底 c_genesis。
        # 必须仅有 1 个工作区成功并入主干，其余 23 个必须触发 MergeConflictException 被坚决拒绝！
        merge_success_count = 0
        conflict_intercept_count = 0

        def merge_worker(idx: int) -> bool:
            try:
                return mgr.merge_to_main(worktrees[idx].worktree_id)
            except MergeConflictException as e:
                return False
            except Exception as e:
                return False

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            merge_futures = [executor.submit(merge_worker, i) for i in range(worker_count)]
            for fut in as_completed(merge_futures):
                if fut.result():
                    merge_success_count += 1
                else:
                    conflict_intercept_count += 1

        assert merge_success_count == 1, (
            f"Blind Overwrite defect: Expected exactly 1 successful merge, got {merge_success_count}"
        )
        assert conflict_intercept_count == worker_count - 1, (
            f"Conflict interception failed: Expected {worker_count - 1} rejections, got {conflict_intercept_count}"
        )

        # 阶段 5: 正交三路合并验证 (修改不同文件的两个分支应允许无冲突安全并入)
        current_head = mgr.get_main_head()
        wt_ortho_1 = mgr.create_worktree("ortho_1", base_commit=current_head)
        wt_ortho_2 = mgr.create_worktree("ortho_2", base_commit=current_head)

        (Path(wt_ortho_1.worktree_path) / "feature_a.py").write_text("def feat_a(): return 'A'\n", encoding="utf-8")
        mgr.commit_worktree(wt_ortho_1.worktree_id, "Add feature A")
        (Path(wt_ortho_2.worktree_path) / "feature_b.py").write_text("def feat_b(): return 'B'\n", encoding="utf-8")
        mgr.commit_worktree(wt_ortho_2.worktree_id, "Add feature B")

        # 即使主干被 wt_ortho_1 推进，wt_ortho_2 的修改属于正交文件集合，三路合并仍应成功
        res1 = mgr.merge_to_main(wt_ortho_1.worktree_id)
        res2 = mgr.merge_to_main(wt_ortho_2.worktree_id)
        assert res1 is True and res2 is True, "Orthogonal multi-file 3-way merge should succeed"
        assert (base_dir / "feature_a.py").exists()
        assert (base_dir / "feature_b.py").exists()

        # 清理
        for wt in list(worktrees.values()) + [wt_ortho_1, wt_ortho_2]:
            mgr.remove_worktree(wt.worktree_id, force=True)

    elapsed = time.perf_counter() - t0
    print(f"  -> 24 Worktrees COW, Hash Uniqueness & Conflict Interception verified in {elapsed:.3f}s.")


def test_stress_winerror32_atomic_tombstoning_and_reborn() -> None:
    """
    实证测试 2：Windows NTFS WinError 32 文件锁自愈、Atomic Tombstoning 逃逸与沙箱即时重生
    """
    print("[RUNNING] test_stress_winerror32_atomic_tombstoning_and_reborn...")
    t0 = time.perf_counter()

    with tempfile.TemporaryDirectory() as tmp_root:
        mgr = WorktreeManager(root_dir=tmp_root)
        task_id = "adversarial_lock_victim"

        # 1. 创建受害者沙箱并在深层目录注入 64KB 锁定文件
        wt = mgr.create_worktree(task_id=task_id, base_commit="commit_alpha")
        wt_path = Path(wt.worktree_path)

        sub_dir = wt_path / "deep_module" / "cache"
        sub_dir.mkdir(parents=True, exist_ok=True)
        locked_file = sub_dir / "active_runtime.dll"
        locked_file.write_bytes(b"CRITICAL_LOCKED_MEMORY_MAPPED_BYTES" * 1024)

        # 模拟常驻进程保持独占读写句柄
        held_handle = open(locked_file, "r+b")

        try:
            # 2. 调用 remove_worktree 销毁沙箱
            removed = mgr.remove_worktree(wt.worktree_id, force=False)
            assert removed is True, "remove_worktree should report True upon atomic tombstoning evacuation"

            # 3. 验证原沙箱物理路径已彻底脱离活跃沙箱命名空间
            assert not wt_path.exists(), f"Worktree path '{wt_path}' should be evacuated from namespace"

            # 4. 验证墓碑目录成功接管锁定遗骸
            tombstones = list(mgr.tombstone_dir.iterdir())
            assert len(tombstones) > 0, "Tombstone directory should hold evacuated locked artifact"

            # 5. 验证同名 task_id 能够立即成功创建新工作树，无锁冲突与路径阻塞
            wt_reborn = mgr.create_worktree(task_id=task_id, base_commit="commit_alpha")
            reborn_path = Path(wt_reborn.worktree_path)
            assert reborn_path.exists()
            assert reborn_path != wt_path or not (reborn_path / "deep_module" / "cache" / "active_runtime.dll").exists()

            test_file = reborn_path / "test_reborn.py"
            test_file.write_text("print('Reborn Success')\n", encoding="utf-8")
            assert test_file.exists()

            mgr.remove_worktree(wt_reborn.worktree_id)
        finally:
            held_handle.close()

        # 句柄释放后触发延迟清理消杀
        mgr.cleanup_expired_worktrees()

    elapsed = time.perf_counter() - t0
    print(f"  -> WinError 32 healing, Atomic Tombstoning & Reborn verified in {elapsed:.3f}s.")


def test_stress_tier2_forensic_anti_cheat_one_vote_veto() -> None:
    """
    实证测试 3：AFEVA Tier 2 法医查作弊对抗实证 (50+ 字典查表作弊 100% 一票否决)
    """
    print("[RUNNING] test_stress_tier2_forensic_anti_cheat_one_vote_veto...")
    t0 = time.perf_counter()

    with tempfile.TemporaryDirectory() as tmp_root:
        gate = ValidationGate()
        diff_spec = DiffSpec(
            source_commit="c0",
            target_commit="c1",
            modified_files=("main.py",),
            ast_scope_name="solve",
            lines_added=55,
            lines_deleted=0,
            orthogonal_distance=0.3
        )

        # 1. 注入 50 个 entries 的静态查表作弊代码
        wt_cheat = WorktreeSpec("wt_cheat_50", str(Path(tmp_root) / "cheat_50"), "b_cheat", "c0")
        Path(wt_cheat.worktree_path).mkdir(parents=True, exist_ok=True)
        dict_entries = ", ".join(f"{i}: {i ** 2 + 7}" for i in range(50))
        cheat_source = (
            '"""Adversarial Cheat Candidate with 50-entry static table"""\n'
            f'LOOKUP_TABLE = {{{dict_entries}}}\n\n'
            'def solve(inputs):\n'
            '    return [LOOKUP_TABLE.get(x, 0) for x in inputs]\n'
        )
        (Path(wt_cheat.worktree_path) / "main.py").write_text(cheat_source, encoding="utf-8")

        v_cheat = gate.validate_tier2(wt_cheat, diff_spec)
        assert v_cheat.status == GateStatus.REJECT, f"Tier 2 failed to reject 50-entry table: {v_cheat.status}"
        assert v_cheat.tier_level == 2
        assert v_cheat.is_probationary is False
        assert any("CHEAT_LOOKUP_TABLE" in d or "Forensic Alert" in d for d in v_cheat.diagnostics)

        # 2. 对照实验：注入 20 个 entries 正常配置字典 (<= 30 entries)
        wt_legit = WorktreeSpec("wt_legit_20", str(Path(tmp_root) / "legit_20"), "b_legit", "c0")
        Path(wt_legit.worktree_path).mkdir(parents=True, exist_ok=True)
        legit_entries = ", ".join(f"{i}: {i * 3}" for i in range(20))
        legit_source = (
            'CONFIG_MAP = {' + legit_entries + '}\n'
            'def solve(inputs):\n'
            '    return sum(CONFIG_MAP.get(x % 20, 0) for x in inputs)\n'
        )
        (Path(wt_legit.worktree_path) / "main.py").write_text(legit_source, encoding="utf-8")

        v_legit = gate.validate_tier2(wt_legit, diff_spec)
        assert v_legit.status == GateStatus.APPROVE

    elapsed = time.perf_counter() - t0
    print(f"  -> Tier 2 forensic anti-cheat one-vote veto verified in {elapsed:.3f}s.")


def test_stress_tier1_breakthrough_talent_probationary_pass() -> None:
    """
    实证测试 4：AFEVA Tier 1 突破性偏科生带病晋级 (PROBATIONARY_PASS) 保护实证
    """
    print("[RUNNING] test_stress_tier1_breakthrough_talent_probationary_pass...")
    t0 = time.perf_counter()

    with tempfile.TemporaryDirectory() as tmp_root:
        gate = ValidationGate(baseline_execution_time_s=2.0, speedup_threshold_rough=0.15)
        diff_spec = DiffSpec("c0", "c1", ("main.py",), "solve", 15, 3, 0.4)

        wt_talent = WorktreeSpec("wt_talent", str(Path(tmp_root) / "talent_sandbox"), "b_talent", "c0")
        Path(wt_talent.worktree_path).mkdir(parents=True, exist_ok=True)

        # 极速算法，但在特定边界输入返回 None (产生 0 < collision_penalty = 0.5 < 0.8 微瑕疵)
        talent_code = (
            'def solve(inputs):\n'
            '    if len(inputs) > 50:\n'
            '        return None\n'
            '    return sum(inputs)\n'
        )
        (Path(wt_talent.worktree_path) / "main.py").write_text(talent_code, encoding="utf-8")

        verdict = gate.validate_tier1(wt_talent, diff_spec)
        assert verdict.status == GateStatus.PROBATIONARY_PASS, f"Expected PROBATIONARY_PASS, got {verdict.status}"
        assert verdict.is_probationary is True
        assert any("Probationary Promotion" in d for d in verdict.diagnostics)
        assert "Hold in Probation Pool" in verdict.recommended_action

    elapsed = time.perf_counter() - t0
    print(f"  -> Tier 1 probationary shelter verified in {elapsed:.3f}s.")


def test_stress_tier3_iron_gate_regression_and_noise_shield_ceiling() -> None:
    """
    实证测试 5：AFEVA Tier 3 钢铁生产门全量回归、确定性零容忍与底噪天花板判定
    """
    print("[RUNNING] test_stress_tier3_iron_gate_regression_and_noise_shield_ceiling...")
    t0 = time.perf_counter()

    with tempfile.TemporaryDirectory() as tmp_root:
        gate = ValidationGate(variance_tolerance_iron=0.01)
        diff_spec = DiffSpec("c0", "c1", ("main.py",), "solve", 10, 0, 0.1)

        # 1. 确定性满分代码通过
        wt_perfect = WorktreeSpec("wt_perfect", str(Path(tmp_root) / "perfect_wt"), "b_perfect", "c0")
        Path(wt_perfect.worktree_path).mkdir(parents=True, exist_ok=True)
        perfect_code = (
            'def solve(inputs):\n'
            '    s = 0\n'
            '    for x in inputs:\n'
            '        s += x\n'
            '    return s\n'
        )
        (Path(wt_perfect.worktree_path) / "main.py").write_text(perfect_code, encoding="utf-8")
        v_perfect = gate.validate_tier3(wt_perfect, diff_spec)
        assert v_perfect.status == GateStatus.APPROVE
        assert any("Iron Gate Passed" in d for d in v_perfect.diagnostics)

        # 2. 注入在 Level 3 下必然失败的回归错误代码
        wt_bug = WorktreeSpec("wt_bug", str(Path(tmp_root) / "bug_wt"), "b_bug", "c0")
        Path(wt_bug.worktree_path).mkdir(parents=True, exist_ok=True)
        (Path(wt_bug.worktree_path) / "main.py").write_text(
            'def solve(inputs):\n'
            '    if len(inputs) > 1000:\n'
            '        return None\n'
            '    return sum(inputs)\n',
            encoding="utf-8"
        )
        v_bug = gate.validate_tier3(wt_bug, diff_spec)
        assert v_bug.status == GateStatus.REJECT

        # 3. 验证极短耗时但高相对方差 (>= 10%) 个体被综合底噪判据拦截，绝不盲目放行
        wt_high_var = WorktreeSpec("wt_high_var", str(Path(tmp_root) / "high_var_wt"), "b_high_var", "c0")
        Path(wt_high_var.worktree_path).mkdir(parents=True, exist_ok=True)
        high_var_code = (
            'import time, random\n'
            'def solve(inputs):\n'
            '    time.sleep(random.uniform(0.0001, 0.0015))\n'
            '    return sum(inputs)\n'
        )
        (Path(wt_high_var.worktree_path) / "main.py").write_text(high_var_code, encoding="utf-8")
        v_high_var = gate.validate_tier3(wt_high_var, diff_spec)
        assert v_high_var.status == GateStatus.REJECT, "High-variance jitter (> 10%) should be rejected, not blindly shielded"
        assert any("exceeded effective tolerance" in d for d in v_high_var.diagnostics)

    elapsed = time.perf_counter() - t0
    print(f"  -> Tier 3 Iron Gate regression & determinism verified in {elapsed:.3f}s.")


if __name__ == "__main__":
    suite_start = time.perf_counter()
    print("=" * 80)
    print("STARTING WORKTREE EMPIRICAL STRESS TEST SUITE")
    print("=" * 80)

    test_stress_24_concurrent_worktree_isolation_and_conflict_interception(24)
    test_stress_winerror32_atomic_tombstoning_and_reborn()
    test_stress_tier2_forensic_anti_cheat_one_vote_veto()
    test_stress_tier1_breakthrough_talent_probationary_pass()
    test_stress_tier3_iron_gate_regression_and_noise_shield_ceiling()

    total_time = time.perf_counter() - suite_start
    print("=" * 80)
    print(f"ALL 5 EMPIRICAL STRESS TESTS PASSED 100% IN {total_time:.3f}s!")
    print("=" * 80)
    sys.exit(0)
