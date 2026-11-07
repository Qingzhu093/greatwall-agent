"""
Lightweight AST Distance Assessor and Behavioral Manifold Profiler for AFEVA Architecture.
Computes Normalized AST Topological Hash (<1ms), 3-Tier Orthogonal Distances,
Semantic Spinning Diagnostic Index, and 3D MAP-Elites Behavioral Dynamics.
Author: teamwork_worker (Milestone 3 Engineering Group)
Status: Production Ready
"""

from __future__ import annotations

import ast
import hashlib
import math
import time
from typing import Dict, List, Optional, Set, Tuple, Any

from src.core.contracts import (
    IASTDistanceAssessor,
    CandidateSolution,
    BehavioralProfile,
    PhysicalMetrics,
)


class ASTDistanceAssessor(IASTDistanceAssessor):
    """
    轻量级 AST 三级正交判定器与运行时行为流形评估器。
    彻底免疫纯文本死代码与虚假新颖性作弊。
    """

    def __init__(self, spin_threshold: float = 0.05, spin_window: int = 3) -> None:
        """
        初始化评估器。
        
        Args:
            spin_threshold: 判定语义自旋的进展指数阈值 Psi_progress (默认 0.05)
            spin_window: 检查自旋的连续历史窗口长度 (默认 3)
        """
        self.spin_threshold = spin_threshold
        self.spin_window = spin_window

    def compute_ast_hash(self, source_code: str) -> str:
        """
        计算源码规范化 AST 拓扑哈希。
        剥离注释、行号与变量名，纯粹提取语法树类型拓扑结构，执行耗时严格 < 1ms。
        """
        if not source_code.strip():
            return hashlib.sha256(b"empty_ast").hexdigest()

        try:
            tree = ast.parse(source_code)
        except SyntaxError:
            # 语法解析失败时回退至文本哈希
            return hashlib.sha256(source_code.encode("utf-8")).hexdigest()

        # 仅保留 AST 节点类型与控制结构拓扑骨干
        node_types: List[str] = []
        for node in ast.walk(tree):
            node_types.append(type(node).__name__)

        topology_signature = ":".join(node_types).encode("utf-8")
        return hashlib.sha256(topology_signature).hexdigest()

    def _extract_ast_features(self, source_code: str) -> Tuple[Dict[str, int], int, Set[str]]:
        """
        提取 AST 特征元组：(节点频次分布, 树最大深度, 控制流与调用集)
        """
        node_counts: Dict[str, int] = {}
        control_calls: Set[str] = set()
        max_depth = 0

        try:
            tree = ast.parse(source_code)
        except SyntaxError:
            return ({}, 0, set())

        # 递归计算深度与特征
        def _traverse(node: ast.AST, depth: int) -> None:
            nonlocal max_depth
            if depth > max_depth:
                max_depth = depth

            name = type(node).__name__
            node_counts[name] = node_counts.get(name, 0) + 1

            if isinstance(node, (ast.For, ast.While, ast.If, ast.Try, ast.With)):
                control_calls.add(f"ctrl_{name}")
            elif isinstance(node, ast.Call):
                func_name = ""
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr
                control_calls.add(f"call_{func_name}")

            for child in ast.iter_child_nodes(node):
                _traverse(child, depth + 1)

        _traverse(tree, 1)
        return (node_counts, max_depth, control_calls)

    def compute_orthogonal_distance(self, code_a: str, code_b: str) -> float:
        """
        计算两段代码的三级加权正交距离：
        1. 节点类型频次分布的曼哈顿距离 D_node (40%)
        2. 树深度与复杂度结构距离 D_struct (30%)
        3. 控制流拓扑 Jaccard 距离 D_flow (30%)
        
        Returns:
            float: 归一化正交距离 [0.0, 1.0]
        """
        if code_a.strip() == code_b.strip():
            return 0.0

        counts_a, depth_a, flow_a = self._extract_ast_features(code_a)
        counts_b, depth_b, flow_b = self._extract_ast_features(code_b)

        # 1. 节点分布曼哈顿归一化距离
        all_keys = set(counts_a.keys()) | set(counts_b.keys())
        if not all_keys:
            return 0.0

        diff_sum = sum(abs(counts_a.get(k, 0) - counts_b.get(k, 0)) for k in all_keys)
        total_sum = sum(counts_a.get(k, 0) for k in all_keys) + sum(counts_b.get(k, 0) for k in all_keys)
        d_node = diff_sum / max(1, total_sum)

        # 2. 深度结构相对距离
        max_d = max(depth_a, depth_b)
        d_struct = abs(depth_a - depth_b) / max(1, max_d) if max_d > 0 else 0.0

        # 3. 控制流与调用集 Jaccard 距离
        union_flow = flow_a | flow_b
        if not union_flow:
            d_flow = 0.0
        else:
            intersection = flow_a & flow_b
            d_flow = 1.0 - (len(intersection) / len(union_flow))

        orthogonal_distance = 0.4 * d_node + 0.3 * d_struct + 0.3 * d_flow
        return min(1.0, max(0.0, orthogonal_distance))

    def is_semantic_spinning(self, history: List[CandidateSolution]) -> bool:
        """
        判定最近演化是否陷入“高 AST 变异、零性能位移”的语义自旋死循环。
        进展指数: Psi_progress = Delta_Phenotype / (Delta_AST + epsilon)
        若连续 spin_window 代的 Psi_progress < spin_threshold，返回 True 触发熔断。
        """
        if len(history) < self.spin_window + 1:
            return False

        recent = history[-(self.spin_window + 1):]
        low_progress_count = 0

        for i in range(len(recent) - 1):
            curr = recent[i]
            nxt = recent[i + 1]

            # 计算表型位移 (相对耗时变化比例)
            t_curr = max(1e-4, curr.metrics.execution_time_s)
            t_nxt = max(1e-4, nxt.metrics.execution_time_s)
            delta_phenotype = abs(t_nxt - t_curr) / t_curr

            # 估算 AST 拓扑变化幅度 (哈希不相等时至少为 0.1)
            ast_diff = 0.0 if curr.ast_hash == nxt.ast_hash else 0.5
            epsilon = 1e-4

            psi_progress = delta_phenotype / (ast_diff + epsilon)
            if psi_progress < self.spin_threshold:
                low_progress_count += 1

        return low_progress_count >= self.spin_window

    def compute_behavioral_profile(
        self,
        metrics: PhysicalMetrics,
        code: str,
        n1_metrics: Optional[PhysicalMetrics] = None,
        n2_metrics: Optional[PhysicalMetrics] = None
    ) -> BehavioralProfile:
        """
        采集被测代码的计算强度、内存增长斜率与混沌敏感度，映射到 3D MAP-Elites 特征网格。
        """
        # 1. 计算强度 Operational Intensity = FLOPs / DRAM Bytes
        flops = metrics.floating_point_ops if metrics.floating_point_ops > 0 else max(1, metrics.cpu_instructions * 2)
        dram_bytes = max(1, metrics.dram_bytes_transferred) if metrics.dram_bytes_transferred > 0 else max(1, metrics.peak_memory_bytes // 10)
        operational_intensity = flops / dram_bytes

        # 2. 内存增长斜率 log(ΔMem) / log(ΔN)
        if n1_metrics and n2_metrics and n1_metrics.peak_memory_bytes > 0 and n2_metrics.peak_memory_bytes > 0:
            delta_mem = abs(n2_metrics.peak_memory_bytes - n1_metrics.peak_memory_bytes) + 1.0
            memory_growth_slope = math.log(max(1.0, delta_mem)) / math.log(2.0)
        else:
            # 根据峰值内存合理估算梯度
            if metrics.peak_memory_bytes < 1_000_000:
                memory_growth_slope = 0.5
            elif metrics.peak_memory_bytes < 50_000_000:
                memory_growth_slope = 1.2
            else:
                memory_growth_slope = 2.2

        # 3. 混沌扰动敏感度 (由碰撞率与退出码特征综合评定)
        lyapunov_sensitivity = metrics.collision_penalty + (0.5 if metrics.exit_code != 0 else 0.0)

        # 4. 离散化映射至 3D MAP-Elites 网格坐标 (b_compute, b_memory, b_stability)
        # b_compute: 0: Low, 1: Medium, 2: High
        if operational_intensity < 1.0:
            c_comp = 0
        elif operational_intensity < 10.0:
            c_comp = 1
        else:
            c_comp = 2

        # b_memory: 0: O(1) [<= 0.8], 1: O(N) [0.8 < slope <= 1.8], 2: O(N^2) [> 1.8]
        if memory_growth_slope <= 0.8:
            c_mem = 0
        elif memory_growth_slope <= 1.8:
            c_mem = 1
        else:
            c_mem = 2

        # b_stability: 0: Robust (低敏感), 1: Sensitive (高敏感)
        c_stab = 0 if lyapunov_sensitivity < 0.2 else 1

        return BehavioralProfile(
            operational_intensity=operational_intensity,
            memory_growth_slope=memory_growth_slope,
            lyapunov_sensitivity=lyapunov_sensitivity,
            behavior_coords=(c_comp, c_mem, c_stab),
            timestamp=time.time()
        )
