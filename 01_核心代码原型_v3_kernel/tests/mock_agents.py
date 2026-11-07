"""
Programmable Mock Agent & Simulation Probe Cluster for AFEVA Architecture (F12).
Provides MockWorker, MockChallenger, and MockAuditor for high-fidelity state machine
concurrency scheduling, adversarial challenge injection, and forensic auditing.

Author: teamwork_worker (Milestone 4 Engineering Group)
Status: Production Ready
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import sys
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Type

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.contracts import (
    AuditCode,
    BehavioralProfile,
    CandidateSolution,
    CausalToken,
    DiffSpec,
    EventPriority,
    ForensicAuditVerdict,
    FSMState,
    GateStatus,
    GateVerdict,
    IForensicAuditor,
    PhysicalMetrics,
    WorktreeSpec,
)
from src.core.events import FSMEvent
from src.core.scheduler import CancellationToken, TaskScheduler, WatchdogMonitor


# ============================================================================
# 1. 探针行为枚举 (Worker Behavior Modes)
# ============================================================================

class WorkerBehaviorMode(str, Enum):
    """MockWorker 参数化注入行为模式"""
    NORMAL = "NORMAL"                                  # 正常提交：合法 AST 与优良物理指标
    HANG = "HANG"                                      # 极端延迟/挂起：模拟死循环无响应，触发看门狗超时
    CRASH = "CRASH"                                    # 异常崩溃：抛出未捕获异常 (如 MemoryError, SystemExit)
    CORRUPTED_CODE = "CORRUPTED_CODE"                  # 代码破坏：注入语法错误 SyntaxError 或不可解析 AST
    CHEAT_LOOKUP = "CHEAT_LOOKUP"                      # 查表作弊：注入 >30 entries 巨大映射字典，触发 Tier 2 一票否决
    BREAKTHROUGH_TALENT = "BREAKTHROUGH_TALENT"        # 突破性偏科生：加速比 >= 15% 但带微瑕，触发 Tier 1 PROBATIONARY_PASS


# ============================================================================
# 2. MockWorker: 可编程 Worker 探针
# ============================================================================

class MockWorker:
    """
    可编程仿真 Worker 探针集群核心。
    支持在沙箱中动态生成不同特征的代码构件，并配合 TaskScheduler 与 WatchdogMonitor
    进行并发调度、心跳测试、崩溃捕获与门禁检验。
    """

    def __init__(
        self,
        worker_id: Optional[str] = None,
        default_mode: WorkerBehaviorMode = WorkerBehaviorMode.NORMAL,
        failure_exception: Type[Exception] = MemoryError,
    ) -> None:
        self.worker_id = worker_id or f"worker_{uuid.uuid4().hex[:8]}"
        self.default_mode = default_mode
        self.failure_exception = failure_exception
        self.executed_tasks: List[str] = []
        self.heartbeat_history: List[Tuple[str, float]] = []

    def generate_code(
        self,
        mode: Optional[WorkerBehaviorMode] = None,
        speedup_factor: float = 1.3,
        lookup_table_entries: int = 50,
        custom_identifier: Optional[str] = None,
    ) -> str:
        """
        根据指定行为模式生成对应的 Python 源码。
        """
        active_mode = mode or self.default_mode
        cid = custom_identifier or self.worker_id

        if active_mode == WorkerBehaviorMode.NORMAL:
            return (
                f'"""Generated Normal Algorithm by {cid}"""\n'
                f'import math\n\n'
                f'def solve(inputs):\n'
                f'    """Compute standard sum with boundary guard."""\n'
                f'    if not inputs:\n'
                f'        return 0\n'
                f'    return sum(inputs)\n'
            )

        elif active_mode == WorkerBehaviorMode.HANG:
            return (
                f'"""Generated Infinite Spin Algorithm by {cid}"""\n'
                f'import time\n\n'
                f'def solve(inputs):\n'
                f'    # Simulated infinite loop hang\n'
                f'    while True:\n'
                f'        time.sleep(0.05)\n'
                f'    return sum(inputs)\n'
            )

        elif active_mode == WorkerBehaviorMode.CRASH:
            return (
                f'"""Generated Crashing Algorithm by {cid}"""\n'
                f'def solve(inputs):\n'
                f'    # Intentionally trigger fatal MemoryError / panic\n'
                f'    raise MemoryError("Fatal: Out of Memory simulated by MockWorker {cid}")\n'
            )

        elif active_mode == WorkerBehaviorMode.CORRUPTED_CODE:
            # 注入破坏性语法错误 (缺少右括号和不合法的表达式)
            return (
                f'"""Corrupted Algorithm by {cid}"""\n'
                f'def solve(inputs:\n'
                f'    return sum(inputs + \n'
            )

        elif active_mode == WorkerBehaviorMode.CHEAT_LOOKUP:
            # 构造包含大量固定键值对的硬编码超大字典 (测试 Tier 2 静态法医一票否决)
            entries_lines = [f'        {i}: {i * 10},' for i in range(lookup_table_entries)]
            dict_str = "{\n" + "\n".join(entries_lines) + "\n    }"
            return (
                f'"""Generated Lookup-Table Cheat Algorithm by {cid}"""\n\n'
                f'# Static forensic fraud payload: Massive lookup table ({lookup_table_entries} entries)\n'
                f'_PRECOMPUTED_TABLE = {dict_str}\n\n'
                f'def solve(inputs):\n'
                f'    if not inputs:\n'
                f'        return 0\n'
                f'    total = 0\n'
                f'    for item in inputs:\n'
                f'        total += _PRECOMPUTED_TABLE.get(item, item)\n'
                f'    return total\n'
            )

        elif active_mode == WorkerBehaviorMode.BREAKTHROUGH_TALENT:
            # 突破性偏科生：极速算法，加速比 >= 15%，但在特定负数边界上带有微小微瑕
            # 该微瑕在 execute_test_suite 时通过 solve 逻辑体现 (例如边界值返回轻微偏差点)
            return (
                f'"""Generated Breakthrough Talent Algorithm by {cid}"""\n\n'
                f'def solve(inputs):\n'
                f'    # Ultra-fast vectorized accumulator\n'
                f'    if not inputs:\n'
                f'        return 0\n'
                f'    # Edge case micro-flaw: slightly biased on extreme negative values\n'
                f'    if len(inputs) > 0 and inputs[0] == -999999:\n'
                f'        return None  # Triggers collision_penalty=0.5 in Tier 1\n'
                f'    return sum(inputs)\n'
            )

        else:
            raise ValueError(f"Unsupported WorkerBehaviorMode: {active_mode}")

    def write_to_worktree(
        self,
        worktree_spec: WorktreeSpec,
        mode: Optional[WorkerBehaviorMode] = None,
        filename: str = "main.py",
        **kwargs: Any,
    ) -> Path:
        """
        在指定沙箱物理目录中写入对应模式的代码文件。
        """
        code = self.generate_code(mode=mode, **kwargs)
        target_path = Path(worktree_spec.worktree_path) / filename
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(code, encoding="utf-8")
        return target_path

    def simulate_execution(
        self,
        task_id: str,
        mode: Optional[WorkerBehaviorMode] = None,
        watchdog: Optional[WatchdogMonitor] = None,
        cancel_token: Optional[CancellationToken] = None,
        hang_duration_s: float = 2.0,
    ) -> PhysicalMetrics:
        """
        模拟 Worker 真实执行动作。
        支持心跳上报、挂起模拟、异常触发以及指标生成。
        """
        active_mode = mode or self.default_mode
        self.executed_tasks.append(task_id)

        if active_mode == WorkerBehaviorMode.HANG:
            # 模拟 Agent 挂起，坚决不上报心跳
            t_end = time.time() + hang_duration_s
            while time.time() < t_end:
                if cancel_token and cancel_token.is_cancelled:
                    raise self.failure_exception(f"Worker {self.worker_id} cancelled during hang: {cancel_token.reason}")
                time.sleep(0.02)
            return PhysicalMetrics(
                execution_time_s=hang_duration_s,
                peak_memory_bytes=10_000_000,
                collision_penalty=0.0,
                exit_code=0,
                is_timeout=True,
            )

        elif active_mode == WorkerBehaviorMode.CRASH:
            # 直接抛出崩溃异常
            raise self.failure_exception(f"Worker {self.worker_id} crashed during task {task_id}")

        elif active_mode == WorkerBehaviorMode.CORRUPTED_CODE:
            raise SyntaxError(f"Worker {self.worker_id} produced uncompilable syntax in task {task_id}")

        elif active_mode == WorkerBehaviorMode.BREAKTHROUGH_TALENT:
            if watchdog:
                watchdog.record_heartbeat(task_id)
                self.heartbeat_history.append((task_id, time.time()))
            # 返回加速 20% 但带有 0.2 惩罚的指标
            return PhysicalMetrics(
                execution_time_s=0.008,  # 基准通常 >= 0.010
                peak_memory_bytes=9_500_000,
                collision_penalty=0.2,   # 轻微边界瑕疵
                exit_code=0,
                is_timeout=False,
            )

        else:
            # 正常提交：正常上报心跳并返回优秀物理指标
            if watchdog:
                watchdog.record_heartbeat(task_id)
                self.heartbeat_history.append((task_id, time.time()))
            return PhysicalMetrics(
                execution_time_s=0.005,
                peak_memory_bytes=10_000_000,
                collision_penalty=0.0,
                exit_code=0,
                is_timeout=False,
            )

    def create_candidate_solution(
        self,
        candidate_id: Optional[str] = None,
        island_id: int = 1,
        mode: Optional[WorkerBehaviorMode] = None,
        metrics: Optional[PhysicalMetrics] = None,
        generation: int = 1,
    ) -> CandidateSolution:
        """
        便捷构造一个强类型 CandidateSolution 实体。
        """
        cid = candidate_id or f"cand_{uuid.uuid4().hex[:8]}"
        code = self.generate_code(mode=mode)
        ast_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
        cas_hash = f"sha256:{hashlib.sha256((code + '_cas').encode('utf-8')).hexdigest()}"

        eval_metrics = metrics or self.simulate_execution(task_id=cid, mode=mode)
        is_prob = (mode == WorkerBehaviorMode.BREAKTHROUGH_TALENT or eval_metrics.collision_penalty > 0.0)

        return CandidateSolution(
            candidate_id=cid,
            parent_id=None,
            island_id=island_id,
            ast_hash=ast_hash,
            source_code_cas_hash=cas_hash,
            metrics=eval_metrics,
            behavior=BehavioralProfile(
                operational_intensity=1.5,
                memory_growth_slope=0.1,
                lyapunov_sensitivity=0.02,
                behavior_coords=(1, 2, 3),
            ),
            generation=generation,
            is_probationary=is_prob,
        )


# ============================================================================
# 3. MockChallenger: 对抗性反例审查者
# ============================================================================

class MockChallenger:
    """
    可编程对抗性质询者 (Challenger)。
    支持生成极端测试工况、恶劣边界输入、退化拓扑，并对被测候选解生成结构化裁决。
    """

    def __init__(
        self,
        challenger_id: Optional[str] = None,
        default_verdict_status: GateStatus = GateStatus.APPROVE,
    ) -> None:
        self.challenger_id = challenger_id or f"challenger_{uuid.uuid4().hex[:8]}"
        self.default_verdict_status = default_verdict_status
        self.recorded_challenges: List[Dict[str, Any]] = []

    def generate_adversarial_inputs(self, test_pattern: str = "float_extremes") -> List[Any]:
        """
        生成高难度极端对抗数据集。
        """
        if test_pattern == "float_extremes":
            # 包含病态浮点数、极小扰动、极大极小量
            return [
                0.0,
                -0.0,
                1e-12,
                -1e-12,
                1e9,
                -1e9,
                float("inf"),
                float("-inf"),
                1.7976931348623157e+308,  # 最大正浮点数
            ]

        elif test_pattern == "massive_array":
            # 巨型密集数组压力测试
            return list(range(-50_000, 50_000))

        elif test_pattern == "degenerate_empty":
            # 退化空值与全零输入
            return [[], [0], [0] * 1000]

        elif test_pattern == "predator_counter_examples":
            # 捕食者对抗反例 (包含突刺异质边界)
            return [-999999, 0, 999999, -1, 1, -2147483648, 2147483647]

        else:
            return list(range(100))

    def evaluate_candidate(
        self,
        candidate: CandidateSolution,
        target_status: Optional[GateStatus] = None,
        diagnostics: Optional[Tuple[str, ...]] = None,
    ) -> GateVerdict:
        """
        生成形式化门禁裁决书。
        """
        status = target_status or self.default_verdict_status
        diag = diagnostics or (f"Evaluated by {self.challenger_id}: status={status.value}",)

        verdict = GateVerdict(
            status=status,
            tier_level=2,
            diagnostics=diag,
            recommended_action="Proceed" if status == GateStatus.APPROVE else "Reject / Retry",
            evaluated_metrics=candidate.metrics,
            is_probationary=(status == GateStatus.PROBATIONARY_PASS),
            timestamp=time.time(),
        )
        self.recorded_challenges.append({
            "candidate_id": candidate.candidate_id,
            "verdict": verdict,
            "timestamp": time.time(),
        })
        return verdict


# ============================================================================
# 4. MockAuditor: 对抗性法医完整性审计员
# ============================================================================

class MockAuditor(IForensicAuditor):
    """
    对抗性法医审计员仿真实现。
    严格实现 IForensicAuditor 契约，支持静态 AST 查表扫描、死代码检测、
    物理方差可重现性全息回放，以及沙箱工作区目录纯净度检验。
    """

    def __init__(
        self,
        auditor_id: Optional[str] = None,
        max_lookup_table_entries: int = 30,
        variance_tolerance: float = 0.01,
        forbidden_extensions: Optional[Set[str]] = None,
    ) -> None:
        self.auditor_id = auditor_id or f"auditor_{uuid.uuid4().hex[:8]}"
        self.max_lookup_table_entries = max_lookup_table_entries
        self.variance_tolerance = variance_tolerance
        self.forbidden_extensions = forbidden_extensions or {".exe", ".bat", ".cmd", ".dll", ".so", ".bin", ".sh"}
        self.audit_log: List[ForensicAuditVerdict] = []

    def audit_candidate(
        self,
        worktree_spec: WorktreeSpec,
        claimed_metrics: PhysicalMetrics,
    ) -> ForensicAuditVerdict:
        """
        对被测工作区开展深度法医调查与完整性取证。
        """
        wt_path = Path(worktree_spec.worktree_path)
        notes: List[str] = []

        # 1. 目录纯净度法医静态检验 (拒绝未经授权的可执行文件或木马脚本)
        for root, _, files in os.walk(wt_path):
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext in self.forbidden_extensions:
                    v_tainted = ForensicAuditVerdict(
                        audit_code=AuditCode.HARDWARE_ANOMALY,
                        is_deterministic=False,
                        hardware_causality_verified=False,
                        dead_code_ratio=0.0,
                        replay_variances=(1.0, 1.0, 1.0),
                        audit_notes=f"Forensic Security Violation: Forbidden binary or script artifact '{fname}' detected.",
                        timestamp=time.time(),
                    )
                    self.audit_log.append(v_tainted)
                    return v_tainted

        # 2. 查表硬编码作弊扫描 (CHEAT_LOOKUP_TABLE)
        for py_file in wt_path.glob("*.py"):
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Dict):
                        if len(node.keys) > self.max_lookup_table_entries:
                            v_cheat = ForensicAuditVerdict(
                                audit_code=AuditCode.CHEAT_LOOKUP_TABLE,
                                is_deterministic=False,
                                hardware_causality_verified=False,
                                dead_code_ratio=0.0,
                                replay_variances=(0.0, 0.0, 0.0),
                                audit_notes=f"Forensic Fraud Confirmed: Dict with {len(node.keys)} entries in {py_file.name}.",
                                timestamp=time.time(),
                            )
                            self.audit_log.append(v_cheat)
                            return v_cheat
            except SyntaxError as se:
                v_err = ForensicAuditVerdict(
                    audit_code=AuditCode.CHEAT_DEAD_CODE,
                    is_deterministic=False,
                    hardware_causality_verified=False,
                    dead_code_ratio=1.0,
                    replay_variances=(1.0, 1.0, 1.0),
                    audit_notes=f"Syntax error during audit: {se}",
                    timestamp=time.time(),
                )
                self.audit_log.append(v_err)
                return v_err

        # 3. 全息重现性检验
        is_det = self.verify_determinism(str(wt_path), runs=3)
        if not is_det:
            v_nondet = ForensicAuditVerdict(
                audit_code=AuditCode.NON_DETERMINISTIC,
                is_deterministic=False,
                hardware_causality_verified=True,
                dead_code_ratio=0.0,
                replay_variances=(0.05, 0.04, 0.06),
                audit_notes="Physical variance ratio exceeded tolerance limit (> 1%).",
                timestamp=time.time(),
            )
            self.audit_log.append(v_nondet)
            return v_nondet

        # 4. 全部法医项合格，发放 CLEAN_PASS 证书
        v_clean = ForensicAuditVerdict(
            audit_code=AuditCode.CLEAN_PASS,
            is_deterministic=True,
            hardware_causality_verified=True,
            dead_code_ratio=0.0,
            replay_variances=(0.001, 0.002, 0.001),
            audit_notes="Forensic audit passed cleanly: Zero cheating, high determinism, clean workspace.",
            timestamp=time.time(),
        )
        self.audit_log.append(v_clean)
        return v_clean

    def verify_determinism(self, worktree_path: str, runs: int = 3) -> bool:
        """
        在洁净环境中多次重放，校验物理指标方差是否严格在容差阈值内。
        """
        # 简单检查代码文件中是否包含强制注入的非确定性标记
        wt = Path(worktree_path)
        for py_file in wt.glob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8")
                if "# INJECT_NON_DETERMINISTIC" in content:
                    return False
            except Exception:
                pass
        return True

    def strip_dead_code(self, source_code: str) -> str:
        """
        利用 AST 遍历剥离明显的死代码块 (如 if False: ... 或孤立常量表达式)。
        """
        try:
            tree = ast.parse(source_code)
            new_body = []
            for stmt in tree.body:
                # 过滤形如 `if False:` 的装饰性死分支
                if isinstance(stmt, ast.If):
                    if isinstance(stmt.test, ast.Constant) and stmt.test.value is False:
                        continue
                new_body.append(stmt)
            tree.body = new_body
            return ast.unparse(tree)
        except Exception:
            return source_code

    def profile_behavior(self, worktree_path: str, inputs: Any) -> BehavioralProfile:
        """
        动态采集被测代码的计算强度、内存增长斜率与混沌敏感度画像。
        """
        return BehavioralProfile(
            operational_intensity=2.1,
            memory_growth_slope=0.05,
            lyapunov_sensitivity=0.001,
            behavior_coords=(2, 3, 1),
            timestamp=time.time(),
        )
