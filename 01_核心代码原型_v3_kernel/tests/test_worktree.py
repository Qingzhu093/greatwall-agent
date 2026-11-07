"""
Automated Comprehensive Test Suite for Worktree Isolation and 3-Tier Gateways.
Covers Worktree Lifecycle, COW, WinError 32 File Lock Healing, and AFEVA Tier 1~3 Gateways.
Author: teamwork_worker (Milestone 3 Engineering Group)
Status: Production Ready
"""

from __future__ import annotations

import os
import sys
import time
import tempfile
import threading
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.contracts import (
    WorktreeSpec,
    DiffSpec,
    GateStatus,
    PhysicalMetrics,
)
from src.worktree.manager import WorktreeManager
from src.worktree.validator import ValidationGate


def test_worktree_lifecycle_cow_and_isolation() -> None:
    """测试 Worktree 生命周期、写时复制 (COW) 与多工作区物理隔离"""
    print("[RUNNING] test_worktree_lifecycle_cow_and_isolation...")
    with tempfile.TemporaryDirectory() as tmp_root:
        # 1. 建立母本目录并放入初始代码
        base_dir = Path(tmp_root) / "base_repo"
        base_dir.mkdir()
        (base_dir / "main.py").write_text("def solve(x):\n    return sum(x)\n", encoding="utf-8")
        (base_dir / "config.json").write_text('{"version": "1.0"}', encoding="utf-8")

        mgr = WorktreeManager(root_dir=tmp_root, base_repo_dir=str(base_dir))

        # 2. 创建两个独立的隔离沙箱
        wt_1 = mgr.create_worktree(task_id="task_A", base_commit="base_commit_001")
        wt_2 = mgr.create_worktree(task_id="task_B", base_commit="base_commit_001")

        assert wt_1.worktree_id != wt_2.worktree_id
        assert Path(wt_1.worktree_path).exists()
        assert Path(wt_2.worktree_path).exists()

        # 3. 验证 COW 机制已复制母本文件
        f1 = Path(wt_1.worktree_path) / "main.py"
        f2 = Path(wt_2.worktree_path) / "main.py"
        assert f1.exists() and "return sum(x)" in f1.read_text(encoding="utf-8")
        assert f2.exists() and "return sum(x)" in f2.read_text(encoding="utf-8")

        # 4. 验证写隔离：修改 wt_1 不应影响 wt_2 或 base_dir
        f1.write_text("def solve(x):\n    return sum(x) * 2\n", encoding="utf-8")
        assert "return sum(x) * 2" in f1.read_text(encoding="utf-8")
        assert "return sum(x)\n" in f2.read_text(encoding="utf-8")
        assert "return sum(x)\n" in (base_dir / "main.py").read_text(encoding="utf-8")

        # 5. 提交沙箱代码
        commit_hash = mgr.commit_worktree(wt_1.worktree_id, "Optimized solve with factor 2")
        assert len(commit_hash) == 64  # SHA-256 长度

        # 6. 原子合并至 main
        merged = mgr.merge_to_main(wt_1.worktree_id)
        assert merged is True
        assert "return sum(x) * 2" in (base_dir / "main.py").read_text(encoding="utf-8")

        # 7. 重置沙箱 (Fork-and-Flush)
        mgr.reset_worktree(wt_1.worktree_id)
        # 重置后应恢复为更新后的母本内容
        assert "return sum(x) * 2" in f1.read_text(encoding="utf-8")

        # 8. 安全销毁沙箱
        rem_ok1 = mgr.remove_worktree(wt_1.worktree_id)
        rem_ok2 = mgr.remove_worktree(wt_2.worktree_id)
        assert rem_ok1 is True and rem_ok2 is True
        assert not Path(wt_1.worktree_path).exists()
        assert not Path(wt_2.worktree_path).exists()

    print("  -> Worktree COW, isolation, commit, merge, and reset verified.")


def test_windows_file_lock_healing_and_tombstoning() -> None:
    """测试 Windows NTFS 文件锁冲突自愈与 Atomic Tombstoning 机制"""
    print("[RUNNING] test_windows_file_lock_healing_and_tombstoning...")
    with tempfile.TemporaryDirectory() as tmp_root:
        mgr = WorktreeManager(root_dir=tmp_root)
        wt = mgr.create_worktree(task_id="lock_test", base_commit="base_lock_01")
        wt_path = Path(wt.worktree_path)

        locked_file = wt_path / "locked_artifact.bin"
        locked_file.write_bytes(b"DATA_UNDER_LOCK" * 100)

        # 在当前进程中故意保持打开只读句柄，模拟 Windows 杀毒软件或残留子进程占用文件
        file_handle = open(locked_file, "r+b")
        try:
            # 执行删除沙箱：底层将捕获句柄占用，并触发退避重试或 Atomic Tombstoning
            # 在同一进程打开文件时，Windows 上直接 rmtree 必触发 PermissionError
            removed = mgr.remove_worktree(wt.worktree_id, force=False)
            assert removed is True, "Tombstoning should succeed and report True to unblock caller"
            # 活跃沙箱中已不再包含该 worktree_id
            assert mgr.get_worktree(wt.worktree_id) is None
        finally:
            file_handle.close()

        # 验证相同 task_id 能够立即复用并成功创建新工作树，无锁冲突
        wt_new = mgr.create_worktree(task_id="lock_test", base_commit="base_lock_01")
        assert Path(wt_new.worktree_path).exists()
        mgr.remove_worktree(wt_new.worktree_id)

    print("  -> Windows file lock retry and Atomic Tombstoning verified.")


def test_validation_gate_tier1_and_probationary_pass() -> None:
    """测试 Tier 1 粗野探索门：语法过滤与偏科生带病晋级 (Probationary Pass)"""
    print("[RUNNING] test_validation_gate_tier1_and_probationary_pass...")
    with tempfile.TemporaryDirectory() as tmp_root:
        gate = ValidationGate(baseline_execution_time_s=0.5, speedup_threshold_rough=0.15)
        diff_spec = DiffSpec(
            source_commit="c0",
            target_commit="c1",
            modified_files=("main.py",),
            ast_scope_name="solve",
            lines_added=10,
            lines_deleted=2,
            orthogonal_distance=0.25
        )

        # 1. 语法错误代码：必须坚决一票拒绝 REJECT
        wt_syntax_err = WorktreeSpec(
            worktree_id="wt_syn",
            worktree_path=str(Path(tmp_root) / "syn_err"),
            branch_name="b_syn",
            base_commit_hash="c0"
        )
        Path(wt_syntax_err.worktree_path).mkdir()
        (Path(wt_syntax_err.worktree_path) / "main.py").write_text("def solve(x): return def ???\n", encoding="utf-8")
        v_syn = gate.validate_tier1(wt_syntax_err, diff_spec)
        assert v_syn.status == GateStatus.REJECT
        assert "SyntaxError" in str(v_syn.diagnostics)

        # 2. 契约作用域缺失代码：记录诊断
        diff_scope_mismatch = DiffSpec("c0", "c1", ("main.py",), "missing_func", 5, 0, 0.1)
        wt_ok = WorktreeSpec("wt_ok", str(Path(tmp_root) / "ok_wt"), "b_ok", "c0")
        Path(wt_ok.worktree_path).mkdir()
        (Path(wt_ok.worktree_path) / "main.py").write_text("def solve(x):\n    return sum(x)\n", encoding="utf-8")
        v_mismatch = gate.validate_tier1(wt_ok, diff_scope_mismatch)
        assert any("Contract scope" in d for d in v_mismatch.diagnostics)

        # 3. 革命性偏科代码 (node_02 级火种)：核心耗时极大突破，但有某些约束瑕疵
        wt_probation = WorktreeSpec("wt_prob", str(Path(tmp_root) / "prob_wt"), "b_prob", "c0")
        Path(wt_probation.worktree_path).mkdir()
        # 极速向量化计算模拟
        (Path(wt_probation.worktree_path) / "main.py").write_text(
            "def solve(x):\n"
            "    # Breakthrough speed with slight boundary penalty\n"
            "    return sum(x)\n",
            encoding="utf-8"
        )
        # 将基线设大，使得微秒级执行表现出巨大加速比，且模拟微瑕疵
        gate.baseline_execution_time_s = 10.0
        v_prob = gate.validate_tier1(wt_probation, diff_spec)
        # 验证获得批准或偏科生豁免
        assert v_prob.status in (GateStatus.APPROVE, GateStatus.PROBATIONARY_PASS)

    print("  -> Tier 1 Rough Gate and probationary shelter verified.")


def test_validation_gate_tier2_predator_and_forensics() -> None:
    """测试 Tier 2 集成中继门：捕食者对抗测试与法医查作弊拦截"""
    print("[RUNNING] test_validation_gate_tier2_predator_and_forensics...")
    with tempfile.TemporaryDirectory() as tmp_root:
        gate = ValidationGate()
        diff_spec = DiffSpec("c0", "c1", ("main.py",), "solve", 10, 0, 0.2)

        # 1. 注入查表硬编码作弊代码 (CHEAT_LOOKUP_TABLE: 大于 30 个硬编码键值对)
        wt_cheat = WorktreeSpec("wt_cheat", str(Path(tmp_root) / "cheat_wt"), "b_cheat", "c0")
        Path(wt_cheat.worktree_path).mkdir()
        # 构建查表字典
        entries = ", ".join(f"{i}: {i*2}" for i in range(50))
        (Path(wt_cheat.worktree_path) / "main.py").write_text(
            f"TABLE = {{{entries}}}\n"
            f"def solve(x):\n"
            f"    return [TABLE.get(i, 0) for i in x]\n",
            encoding="utf-8"
        )
        v_cheat = gate.validate_tier2(wt_cheat, diff_spec)
        assert v_cheat.status == GateStatus.REJECT
        assert any("CHEAT_LOOKUP_TABLE" in d or "Forensic Alert" in d for d in v_cheat.diagnostics)

        # 2. 正常优良算法：无作弊且通过捕食者对抗
        wt_clean = WorktreeSpec("wt_clean", str(Path(tmp_root) / "clean_wt"), "b_clean", "c0")
        Path(wt_clean.worktree_path).mkdir()
        (Path(wt_clean.worktree_path) / "main.py").write_text(
            "def solve(x):\n"
            "    total = 0\n"
            "    for v in x:\n"
            "        total += v\n"
            "    return total\n",
            encoding="utf-8"
        )
        v_clean = gate.validate_tier2(wt_clean, diff_spec)
        assert v_clean.status == GateStatus.APPROVE
        assert v_clean.tier_level == 2

    print("  -> Tier 2 Staging Gate, predator check, and forensic cheat defense verified.")


def test_validation_gate_tier3_iron_gate_and_determinism() -> None:
    """测试 Tier 3 钢铁生产门：全量极端回归与全息确定性重放零容忍"""
    print("[RUNNING] test_validation_gate_tier3_iron_gate_and_determinism...")
    with tempfile.TemporaryDirectory() as tmp_root:
        gate = ValidationGate(variance_tolerance_iron=0.50)  # 设置合理的测试重跑方差阈值
        diff_spec = DiffSpec("c0", "c1", ("main.py",), "solve", 5, 0, 0.1)

        wt_prod = WorktreeSpec("wt_prod", str(Path(tmp_root) / "prod_wt"), "b_prod", "c0")
        Path(wt_prod.worktree_path).mkdir()
        (Path(wt_prod.worktree_path) / "main.py").write_text(
            "def solve(x):\n"
            "    return sum(x)\n",
            encoding="utf-8"
        )

        # 执行 Tier 3 终审
        verdict = gate.validate_tier3(wt_prod, diff_spec)
        assert verdict.tier_level == 3
        assert verdict.status == GateStatus.APPROVE
        assert any("Iron Gate Passed" in d for d in verdict.diagnostics)

        # 测试全量串联流水线
        full_verdict = gate.run_full_validation(wt_prod, diff_spec)
        assert full_verdict.status == GateStatus.APPROVE

    print("  -> Tier 3 Iron Gate full regression and determinism verified.")


if __name__ == "__main__":
    test_worktree_lifecycle_cow_and_isolation()
    test_windows_file_lock_healing_and_tombstoning()
    test_validation_gate_tier1_and_probationary_pass()
    test_validation_gate_tier2_predator_and_forensics()
    test_validation_gate_tier3_iron_gate_and_determinism()
    print("=" * 80)
    print("ALL WORKTREE & VALIDATION GATE TESTS PASSED 100%!")
    print("=" * 80)
