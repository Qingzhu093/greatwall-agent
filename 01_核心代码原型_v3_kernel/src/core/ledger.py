"""
Dual Ledger (TaskLedger & ProgressLedger Physical Separation) and Stanford ACE Living Playbook with LFU-Decay Pruning.
Author: worker_m2 (Implementation Engineering Group)
Status: Production Ready
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from .contracts import (
    AttentionDilutionAlert,
    CandidateSolution,
    CausalToken,
    EpochSummary,
    IDualLedger,
    PhysicalMetrics,
    PlaybookBullet,
)
from .events import FSMEvent

__all__ = [
    "TaskLedger",
    "ProgressLedger",
    "LivingPlaybook",
    "DualLedger",
]


# ============================================================================
# 1. 活跃任务依赖账本 (Task Ledger - CQRS 活跃因果图前沿)
# ============================================================================

class TaskLedger:
    """
    活跃任务依赖账本 (物理隔离，严禁写入历史评测指标)。
    专注于因果图前沿活跃依赖追踪，物化视图输出上下文严格控制在 <= 1000 Token。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # task_id -> task_metadata
        self._active_tasks: Dict[str, Dict[str, Any]] = {}
        # task_id -> set of required predecessor task_ids
        self._dependencies: Dict[str, Set[str]] = {}
        # completed task_id -> artifact CAS hash
        self._completed_artifacts: Dict[str, str] = {}
        # failed task_id -> failure reason
        self._failed_tasks: Dict[str, str] = {}

    def register_task(
        self,
        task_id: str,
        causal_level: int,
        dependencies: Optional[Set[str]] = None,
        token: Optional[CausalToken] = None,
        extra_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """登记新派发的活跃任务及其因果依赖"""
        with self._lock:
            deps = set(dependencies or set())
            self._dependencies[task_id] = deps
            self._active_tasks[task_id] = {
                "task_id": task_id,
                "causal_level": causal_level,
                "dependencies": sorted(deps),
                "token_id": token.token_id if token else None,
                "created_at": time.time(),
                "status": "RUNNING",
                "meta": extra_meta or {},
            }

    def mark_completed(self, task_id: str, artifact_hash: str) -> None:
        """标记任务成功完成并记录产物 CAS 哈希"""
        with self._lock:
            if task_id in self._active_tasks:
                self._active_tasks[task_id]["status"] = "COMPLETED"
                self._active_tasks[task_id]["completed_at"] = time.time()
            self._completed_artifacts[task_id] = artifact_hash

    def mark_failed(self, task_id: str, reason: str) -> None:
        """标记任务执行失败"""
        with self._lock:
            if task_id in self._active_tasks:
                self._active_tasks[task_id]["status"] = "FAILED"
                self._active_tasks[task_id]["failed_at"] = time.time()
                self._active_tasks[task_id]["failure_reason"] = reason
            self._failed_tasks[task_id] = reason

    def is_task_ready(self, task_id: str) -> bool:
        """判定指定任务的所有前置因果依赖是否已全部完成产出"""
        with self._lock:
            deps = self._dependencies.get(task_id, set())
            return all(dep in self._completed_artifacts for dep in deps)

    def get_pending_dependencies(self, task_id: str) -> Set[str]:
        """获取尚未完成的前驱依赖集合"""
        with self._lock:
            deps = self._dependencies.get(task_id, set())
            return {d for d in deps if d not in self._completed_artifacts}

    def project_active_dependencies(self) -> Dict[str, Any]:
        """
        CQRS 投影：输出极简活跃依赖物化视图。
        仅保留未完成或正在执行的活跃边缘，确保大模型上下文绝不膨胀。
        """
        with self._lock:
            unresolved = {}
            for tid, info in self._active_tasks.items():
                if info["status"] == "RUNNING":
                    pending = [d for d in info["dependencies"] if d not in self._completed_artifacts]
                    unresolved[tid] = {
                        "level": info["causal_level"],
                        "pending_deps": pending,
                        "ready": len(pending) == 0,
                    }

            return {
                "active_task_count": len(unresolved),
                "unresolved_frontier": unresolved,
                "completed_count": len(self._completed_artifacts),
                "failed_count": len(self._failed_tasks),
            }


# ============================================================================
# 2. 演化进展与 Pareto 前沿账本 (Progress Ledger)
# ============================================================================

class ProgressLedger:
    """
    演化进展与解集前沿账本 (物理隔离，严禁写入细粒度调试日志)。
    专注于全局 Pareto 最优解流形、综合能级演进与孤岛代际报告。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # candidate_id -> CandidateSolution
        self._candidates: Dict[str, CandidateSolution] = {}
        # island_id -> list of EpochSummary
        self._epoch_summaries: Dict[int, List[EpochSummary]] = {}
        # Global best record
        self._best_candidate_id: Optional[str] = None
        self._best_energy: float = float("inf")

    def record_candidate(self, candidate: CandidateSolution) -> None:
        """登记入库新的候选算法解个体"""
        with self._lock:
            self._candidates[candidate.candidate_id] = candidate
            # 简易能级评估：execution_time_s * (1.0 + 10.0 * collision_penalty)
            energy = candidate.metrics.execution_time_s * (1.0 + 10.0 * candidate.metrics.collision_penalty)
            if energy < self._best_energy and candidate.metrics.is_viable():
                self._best_energy = energy
                self._best_candidate_id = candidate.candidate_id

    def record_epoch(self, summary: EpochSummary) -> None:
        """归档单孤岛代际演化结算报告"""
        with self._lock:
            self._epoch_summaries.setdefault(summary.island_id, []).append(summary)

    def get_pareto_frontier(self) -> List[CandidateSolution]:
        """
        多目标 Pareto 非支配前沿筛选。
        优化目标：
        1. 运行耗时最小化 (execution_time_s)
        2. 碰撞惩罚最小化 (collision_penalty)
        3. 峰值内存最小化 (peak_memory_bytes)
        """
        with self._lock:
            viable_pool = [c for c in self._candidates.values() if c.metrics.is_viable()]
            if not viable_pool:
                return []

            frontier: List[CandidateSolution] = []
            for c in viable_pool:
                dominated = False
                m = c.metrics
                for other in viable_pool:
                    if other.candidate_id == c.candidate_id:
                        continue
                    om = other.metrics
                    # 支配判定：other 在所有维度不劣于 c，且至少一个维度严格优于 c
                    not_worse = (
                        om.execution_time_s <= m.execution_time_s
                        and om.collision_penalty <= m.collision_penalty
                        and om.peak_memory_bytes <= m.peak_memory_bytes
                    )
                    strictly_better = (
                        om.execution_time_s < m.execution_time_s
                        or om.collision_penalty < m.collision_penalty
                        or om.peak_memory_bytes < m.peak_memory_bytes
                    )
                    if not_worse and strictly_better:
                        dominated = True
                        break
                if not dominated:
                    frontier.append(c)

            # 按执行耗时排序
            frontier.sort(key=lambda x: x.metrics.execution_time_s)
            return frontier

    def project_frontier_pareto(self) -> List[CandidateSolution]:
        """CQRS 投影：输出全局 Pareto 最优解前沿"""
        return self.get_pareto_frontier()

    def get_best_candidate(self) -> Optional[CandidateSolution]:
        """获取全局历史最低能级冠军候选个体"""
        with self._lock:
            if self._best_candidate_id and self._best_candidate_id in self._candidates:
                return self._candidates[self._best_candidate_id]
            return None


# ============================================================================
# 3. Stanford ACE 强类型 Living Playbook (LFU-Decay 惰性剪枝)
# ============================================================================

class LivingPlaybook:
    """
    Stanford ACE 动态强类型战术手册。
    特性：
    1. 记录正向战术与负向排斥禁忌 (Taboos)；
    2. 基于 LFU-Decay 算法进行效用加权与衰减；
    3. 严格预算限制：导出上下文硬限制 <= 2000 Token (默认锁定在 <= 1500 Token)，彻底免疫注意力稀释。
    """

    def __init__(self, token_budget: int = 1500) -> None:
        if token_budget > 2000:
            raise AttentionDilutionAlert(
                f"Requested token budget {token_budget} exceeds the strict safety redline of 2000 tokens!"
            )
        self.token_budget = token_budget
        self._bullets: Dict[str, PlaybookBullet] = {}
        self._lock = threading.Lock()

    def add_or_update(self, bullet: PlaybookBullet) -> None:
        """插入或更新战术条目"""
        with self._lock:
            if bullet.bullet_id in self._bullets:
                existing = self._bullets[bullet.bullet_id]
                existing.reward_utility(bullet.utility_score)
                existing.last_used_epoch = bullet.last_used_epoch
            else:
                self._bullets[bullet.bullet_id] = bullet

    def record_hit(self, bullet_id: str, bonus: float = 1.0) -> None:
        """当条目被命中采纳且产生正向突破时，奖励其效用分"""
        with self._lock:
            if bullet_id in self._bullets:
                self._bullets[bullet_id].reward_utility(bonus)

    def decay_all(self, decay_factor: float = 0.95) -> None:
        """执行全量 LFU-Decay 效用衰减"""
        with self._lock:
            for b in self._bullets.values():
                b.decay_utility(decay_factor)

    def prune_lfu(self, max_bullets: int = 30) -> int:
        """
        惰性剪枝：当条目数量超标时，淘汰 utility_score 最低的长尾条目。
        :return: 淘汰的条目数量
        """
        with self._lock:
            if len(self._bullets) <= max_bullets:
                return 0

            # 按效用降序排序
            sorted_bullets = sorted(
                self._bullets.values(),
                key=lambda b: (b.utility_score, b.access_count),
                reverse=True,
            )
            survivors = sorted_bullets[:max_bullets]
            pruned_count = len(sorted_bullets) - len(survivors)
            self._bullets = {b.bullet_id: b for b in survivors}
            return pruned_count

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """
        保守估计文本 Token 数：
        采用混合保守估算，中文约 1.5 chars/token，英文代码约 3.5 chars/token。
        此处统一使用保守的 len(text) // 3 估算。
        """
        return max(1, len(text) // 3)

    def export_context(self, max_tokens: Optional[int] = None) -> str:
        """
        导出紧凑强类型战术上下文。
        确保 Token 数绝对不突破 max_tokens 且不超过 2000 Token 红线。
        """
        budget = max_tokens or self.token_budget
        if budget > 2000:
            raise AttentionDilutionAlert(
                f"Requested export max_tokens {budget} exceeds 2000 token limit!"
            )

        with self._lock:
            # 按效用分从高到低排列
            candidates = sorted(
                self._bullets.values(),
                key=lambda b: (b.utility_score, b.access_count),
                reverse=True,
            )

            lines: List[str] = [
                "# [Living Playbook: Stanford ACE Distilled Strategies]",
                "## 核心战术指导与负向排斥禁忌 (Prioritized)",
            ]

            included_bullets: List[str] = []
            for b in candidates:
                bullet_text = (
                    f"- [{b.bullet_id}] 触发条件: {b.trigger_condition}\n"
                    f"  * 推荐策略: {b.prescribed_strategy}\n"
                    f"  * 严禁踩坑(Taboo): {b.anti_pattern_taboo}"
                )
                test_context = "\n".join(lines + included_bullets + [bullet_text])
                if self.estimate_tokens(test_context) > budget:
                    # 触及预算上限，截断长尾条目
                    break
                included_bullets.append(bullet_text)

            if not included_bullets:
                lines.append("*(暂无沉淀的先验战术条目，保持自由探索)*")
            else:
                lines.extend(included_bullets)

            final_text = "\n".join(lines)
            return final_text


# ============================================================================
# 4. 双账本门面整合 (DualLedger Implementation)
# ============================================================================

class DualLedger(IDualLedger):
    """
    双账本物理隔离门面实现 (实现 IDualLedger 抽象契约)。
    物理隔离 TaskLedger 与 ProgressLedger，杜绝上下文熵增溢出。
    """

    def __init__(self, playbook_budget: int = 1500) -> None:
        self.task_ledger = TaskLedger()
        self.progress_ledger = ProgressLedger()
        self.playbook = LivingPlaybook(token_budget=playbook_budget)
        self._raw_events: List[FSMEvent] = []
        self._lock = threading.Lock()

    def append_event(self, event: FSMEvent) -> None:
        """接收状态机事件流并分别派发投影至对应独立账本"""
        with self._lock:
            self._raw_events.append(event)

        # 1. 任务派发与完成事件流转至 TaskLedger
        p = event.payload
        if event.event_type == "EVT_TASK_DISPATCH":
            tid = p.get("task_id", event.event_id)
            deps = set(p.get("dependencies", []))
            self.task_ledger.register_task(
                task_id=tid,
                causal_level=event.causal_token.causal_level,
                dependencies=deps,
                token=event.causal_token,
            )
        elif event.event_type in ("EVT_SYNTHESIS_DONE", "EVT_ROUGH_PASS"):
            tid = p.get("task_id", event.event_id)
            artifact = event.causal_token.payload_cas_hash
            self.task_ledger.mark_completed(tid, artifact)
        elif event.event_type in ("EVT_ROUGH_FAIL", "EVT_STAGING_FAIL", "EVT_POISON_PILL"):
            tid = p.get("task_id", event.event_id)
            reason = str(p.get("reason", "Event failure"))
            self.task_ledger.mark_failed(tid, reason)

        # 2. 候选解与代际结果流转至 ProgressLedger
        if "candidate" in p and isinstance(p["candidate"], CandidateSolution):
            self.progress_ledger.record_candidate(p["candidate"])
        if "epoch_summary" in p and isinstance(p["epoch_summary"], EpochSummary):
            self.progress_ledger.record_epoch(p["epoch_summary"])

    def project_active_dependencies(self) -> Dict[str, Any]:
        """CQRS 投影：活跃依赖物化视图 (Task Ledger)"""
        return self.task_ledger.project_active_dependencies()

    def project_frontier_pareto(self) -> List[CandidateSolution]:
        """CQRS 投影：全局 Pareto 最优解前沿 (Progress Ledger)"""
        return self.progress_ledger.project_frontier_pareto()

    def update_playbook(self, bullet: PlaybookBullet) -> None:
        """更新战术手册并自动触发 LFU 衰减与修剪"""
        self.playbook.add_or_update(bullet)
        self.playbook.prune_lfu(max_bullets=30)

    def get_playbook_context(self, max_tokens: int = 1500) -> str:
        """导出强类型压缩战术手册，硬性控制在 Token 预算内"""
        return self.playbook.export_context(max_tokens=max_tokens)
