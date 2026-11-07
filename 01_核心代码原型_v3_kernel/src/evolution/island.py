"""
Multi-Island Evolutionary Dynamics and Sparse Directed Ring Migration Controller for AFEVA Architecture.
Maintains Island 0 (Anchor), Island 1 (Anneal), and Island 2 (Novelty),
orchestrating Pareto frontier selection and 0 -> 1 -> 2 -> 0 migration topology.
Author: teamwork_worker (Milestone 3 Engineering Group)
Status: Production Ready
"""

from __future__ import annotations

import math
import time
import hashlib
import statistics
from typing import Dict, List, Optional, Set, Tuple, Any

from src.core.contracts import (
    IIslandController,
    IslandRole,
    CandidateSolution,
    EpochSummary,
    MigrationBundle,
    PhysicalMetrics,
)
from src.evolution.annealer import AnnealingController


class IslandController(IIslandController):
    """
    多孤岛演化拓扑与稀疏有向环迁移总线控制器。
    """

    def __init__(self, migration_interval: int = 5, island_capacity: int = 15) -> None:
        """
        初始化多孤岛控制器。
        
        Args:
            migration_interval: 周期性迁移间隔代数 (默认 5 代)
            island_capacity: 各孤岛常驻种群容量上限 (默认 15)
        """
        self.migration_interval = migration_interval
        self.island_capacity = island_capacity

        self._island_roles: Dict[int, IslandRole] = {}
        self._island_populations: Dict[int, List[CandidateSolution]] = {}
        self._annealers: Dict[int, AnnealingController] = {}
        self._occupied_behavior_grids: Dict[int, Set[Tuple[int, int, int]]] = {}
        self._current_epoch: int = 0

        # 初始化默认三孤岛拓扑
        self.initialize_islands(3, [
            {"island_id": 0, "role": IslandRole.ISLAND_0_ANCHOR},
            {"island_id": 1, "role": IslandRole.ISLAND_1_ANNEAL},
            {"island_id": 2, "role": IslandRole.ISLAND_2_NOVELTY},
        ])

    def initialize_islands(self, island_count: int, configs: List[Dict[str, Any]]) -> None:
        """
        初始化异构孤岛拓扑。
        """
        self._island_roles.clear()
        self._island_populations.clear()
        self._annealers.clear()
        self._occupied_behavior_grids.clear()

        for cfg in configs:
            iid = cfg.get("island_id", 0)
            role = cfg.get("role", IslandRole.ISLAND_1_ANNEAL)
            if isinstance(role, str):
                role = IslandRole(role)

            self._island_roles[iid] = role
            self._island_populations[iid] = []
            self._occupied_behavior_grids[iid] = set()

            # 为各孤岛装配针对性退火动力学配置
            if role == IslandRole.ISLAND_0_ANCHOR:
                # 锚点岛：绝对贪心 (T=0)
                self._annealers[iid] = AnnealingController(
                    initial_temperature=0.0,
                    min_temperature=0.0
                )
            elif role == IslandRole.ISLAND_1_ANNEAL:
                # 激进退火岛：自适应无量纲 MAD，正常温度
                self._annealers[iid] = AnnealingController(
                    cooling_schedule="exponential",
                    cooling_rate=0.88
                )
            else:
                # 新颖性岛：高质量多样性特区
                self._annealers[iid] = AnnealingController(
                    initial_temperature=1.5,
                    cooling_schedule="exponential",
                    cooling_rate=0.95
                )

    def get_island_role(self, island_id: int) -> IslandRole:
        """获取指定孤岛的角色定位"""
        return self._island_roles.get(island_id, IslandRole.ISLAND_1_ANNEAL)

    def _is_pareto_dominated(self, a: CandidateSolution, b: CandidateSolution) -> bool:
        """判定解 a 是否被解 b 严格 Pareto 支配 (三目标最小化: 耗时, 内存, 碰撞率)"""
        m_a = (a.metrics.execution_time_s, float(a.metrics.peak_memory_bytes), a.metrics.collision_penalty)
        m_b = (b.metrics.execution_time_s, float(b.metrics.peak_memory_bytes), b.metrics.collision_penalty)

        all_le = (m_b[0] <= m_a[0] and m_b[1] <= m_a[1] and m_b[2] <= m_a[2])
        at_least_one_lt = (m_b[0] < m_a[0] or m_b[1] < m_a[1] or m_b[2] < m_a[2])
        return all_le and at_least_one_lt

    def _select_pareto_frontier(self, population: List[CandidateSolution]) -> List[CandidateSolution]:
        """提取种群中的非支配 Pareto 前沿解"""
        frontier: List[CandidateSolution] = []
        for cand in population:
            dominated = False
            for other in population:
                if cand.candidate_id != other.candidate_id and self._is_pareto_dominated(cand, other):
                    dominated = True
                    break
            if not dominated:
                frontier.append(cand)
        return frontier

    def _calculate_vendi_score(self, population: List[CandidateSolution]) -> float:
        """
        计算孤岛当前多样性 Vendi Score (基于哈希与正交离散坐标的香农-雷尼表型熵)。
        """
        if not population:
            return 1.0

        signatures = [
            f"{c.ast_hash[:8]}_{c.behavior.behavior_coords if c.behavior else (0,0,0)}"
            for c in population
        ]
        counts: Dict[str, int] = {}
        for s in signatures:
            counts[s] = counts.get(s, 0) + 1

        total = len(signatures)
        entropy = 0.0
        for cnt in counts.values():
            p = cnt / total
            if p > 0:
                entropy -= p * math.log(p)

        return math.exp(entropy)

    def step_epoch(
        self,
        island_id: int,
        epoch: int,
        candidates: List[CandidateSolution]
    ) -> EpochSummary:
        """
        推进指定孤岛完成一个代际的演化与本地归档。
        """
        start_time = time.perf_counter()
        self._current_epoch = epoch
        role = self.get_island_role(island_id)
        annealer = self._annealers[island_id]

        pop = self._island_populations.setdefault(island_id, [])
        accepted_count = 0
        rejected_count = 0

        # 获取当前岛内基准解
        current_best = pop[0] if pop else (candidates[0] if candidates else None)

        for cand in candidates:
            cand.island_id = island_id
            if current_best is None:
                pop.append(cand)
                current_best = cand
                accepted_count += 1
                continue

            accepted = False
            if role == IslandRole.ISLAND_0_ANCHOR:
                # 锚点岛：绝对贪心 (纯指标改善)
                delta = annealer.compute_dimensionless_delta(current_best.metrics, cand.metrics)
                if delta <= 0.0:
                    accepted = True
            elif role == IslandRole.ISLAND_1_ANNEAL:
                # 激进退火岛：Metropolis 概率接纳
                accepted = annealer.evaluate_acceptance(current_best.metrics, cand.metrics, epoch)
            else:
                # 新颖性岛：行为网格占领与正交踏脚石保护
                coords = cand.behavior.behavior_coords if cand.behavior else (0, 0, 0)
                occupied = self._occupied_behavior_grids[island_id]
                if coords not in occupied:
                    # 发现空白行为网格，制度化接纳为踏脚石
                    occupied.add(coords)
                    accepted = True
                else:
                    # 依据退火准则决定是否替换
                    accepted = annealer.evaluate_acceptance(current_best.metrics, cand.metrics, epoch)

            if accepted:
                pop.append(cand)
                accepted_count += 1
                # 更新当前最优指针 (按综合能量)
                if annealer.compute_dimensionless_delta(current_best.metrics, cand.metrics) < 0:
                    current_best = cand
            else:
                rejected_count += 1

        # 执行降温步进
        annealer.step_cooling()

        # 种群淘汰与换血：优先保留 Pareto 前沿个体
        if len(pop) > self.island_capacity:
            frontier = self._select_pareto_frontier(pop)
            non_frontier = [c for c in pop if c not in frontier]
            # 按综合能量对非前沿个体排序，择优补足容量
            non_frontier.sort(key=lambda c: annealer.compute_dimensionless_energy(c.metrics))
            needed = max(0, self.island_capacity - len(frontier))
            self._island_populations[island_id] = frontier + non_frontier[:needed]
        else:
            self._island_populations[island_id] = pop

        # 结算本代指标：与各孤岛自身的退火/能量计算进行绑定，精准选取能量最优解
        pop_current = self._island_populations.get(island_id, [])
        if pop_current:
            best_cand = min(pop_current, key=lambda c: annealer.compute_dimensionless_energy(c.metrics))
            best_id = best_cand.candidate_id
            best_energy = annealer.compute_dimensionless_energy(best_cand.metrics)
            # 保持 pop[0] 始终对齐为孤岛退火最优个体
            pop_current.remove(best_cand)
            pop_current.insert(0, best_cand)
        else:
            best_cand = None
            best_id = "none"
            best_energy = 0.0

        # 检测平原死锁并重加热
        annealer.record_epoch_best(best_energy)

        diversity = self._calculate_vendi_score(self._island_populations[island_id])
        elapsed = time.perf_counter() - start_time

        return EpochSummary(
            island_id=island_id,
            epoch_number=epoch,
            total_candidates=len(candidates),
            accepted_candidates=accepted_count,
            rejected_candidates=rejected_count,
            best_candidate_id=best_id,
            best_energy=best_energy,
            island_diversity_vendi=diversity,
            elapsed_seconds=elapsed,
            timestamp=time.time()
        )

    def exchange_migrants(self) -> List[MigrationBundle]:
        """
        执行稀疏有向环迁移总线的数据交换：0 -> 1 -> 2 -> 0。
        仅交换轻量级不可变表型卡片，附带防重放数字签名。
        """
        bundles: List[MigrationBundle] = []
        islands = sorted(self._island_populations.keys())
        if len(islands) < 2:
            return bundles

        # 0 -> 1 -> 2 -> 0 有向环拓扑
        ring_pairs = [(islands[i], islands[(i + 1) % len(islands)]) for i in range(len(islands))]

        for src_id, dst_id in ring_pairs:
            src_pop = self._island_populations.get(src_id, [])
            if not src_pop:
                continue

            # 选取前沿最优或新颖性个体作为迁移样本 (取 1~2 个)
            migrants_to_send = src_pop[:2]
            summaries: List[Dict[str, Any]] = []

            for cand in migrants_to_send:
                summary_card = {
                    "candidate_id": cand.candidate_id,
                    "ast_hash": cand.ast_hash,
                    "metrics": {
                        "execution_time_s": cand.metrics.execution_time_s,
                        "peak_memory_bytes": cand.metrics.peak_memory_bytes,
                        "collision_penalty": cand.metrics.collision_penalty,
                        "exit_code": cand.metrics.exit_code,
                    },
                    "behavior_coords": cand.behavior.behavior_coords if cand.behavior else (0, 0, 0),
                    "generation": cand.generation,
                    "origin_island": src_id
                }
                summaries.append(summary_card)

            # 生成防重放防篡改环拓扑数字签名
            sig_material = f"{src_id}->{dst_id}:{self._current_epoch}:{[s['candidate_id'] for s in summaries]}"
            signature = hashlib.sha256(sig_material.encode("utf-8")).hexdigest()

            bundle = MigrationBundle(
                source_island_id=src_id,
                target_island_id=dst_id,
                epoch=self._current_epoch,
                migrant_summaries=tuple(summaries),
                topology_signature=signature
            )
            bundles.append(bundle)

            # 注入目标孤岛 (物理克隆实体注入)
            dst_pop = self._island_populations.setdefault(dst_id, [])
            for m_cand in migrants_to_send:
                # 复制并重构孤岛归属
                migrant_clone = CandidateSolution(
                    candidate_id=f"migrant_{m_cand.candidate_id[:8]}",
                    parent_id=m_cand.candidate_id,
                    island_id=dst_id,
                    ast_hash=m_cand.ast_hash,
                    source_code_cas_hash=m_cand.source_code_cas_hash,
                    metrics=m_cand.metrics,
                    behavior=m_cand.behavior,
                    temperature_at_birth=m_cand.temperature_at_birth,
                    mutation_operator_used="P-Migration",
                    generation=m_cand.generation + 1
                )
                dst_pop.append(migrant_clone)

        return bundles
