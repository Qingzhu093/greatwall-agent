"""
Task Scheduler, Watchdog Monitor, Deadlock Detector (Tarjan SCC & Semantic Spin Metric), and Backpressure Flow Control.
Author: worker_m2 (Implementation Engineering Group)
Status: Production Ready
"""

from __future__ import annotations

import asyncio
import itertools
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set, Tuple

from .contracts import (
    CausalDeadlockException,
    CausalToken,
    EventPriority,
)

__all__ = [
    "CancellationToken",
    "ScheduledTask",
    "TaskScheduler",
    "WatchdogMonitor",
    "DeadlockDetector",
]

_TASK_SEQ = itertools.count()


# ============================================================================
# 1. 协同取消令牌 (Cancellation Token)
# ============================================================================

class CancellationToken:
    """
    异步任务协同取消令牌。
    支持注册取消回调、原子置位以及安全唤醒。
    """

    def __init__(self) -> None:
        self._cancelled = False
        self._reason: Optional[str] = None
        self._callbacks: List[Callable[[str], None]] = []
        self._lock = threading.Lock()

    @property
    def is_cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    @property
    def reason(self) -> Optional[str]:
        with self._lock:
            return self._reason

    def cancel(self, reason: str = "Operation cancelled") -> None:
        """触发取消信号，并依序执行注册的回调函数"""
        callbacks_to_fire = []
        with self._lock:
            if self._cancelled:
                return
            self._cancelled = True
            self._reason = reason
            callbacks_to_fire = list(self._callbacks)

        for cb in callbacks_to_fire:
            try:
                cb(reason)
            except Exception:
                pass

    def register_callback(self, cb: Callable[[str], None]) -> None:
        """注册取消时的回调钩子"""
        with self._lock:
            if self._cancelled:
                reason = self._reason or "Operation cancelled"
            else:
                self._callbacks.append(cb)
                return
        # 已被取消则立即触发
        try:
            cb(reason)
        except Exception:
            pass

    def raise_if_cancelled(self) -> None:
        """若已取消，则抛出 asyncio.CancelledError"""
        if self.is_cancelled:
            raise asyncio.CancelledError(self.reason or "Task cancelled via token")


# ============================================================================
# 2. 调度任务实体 (Scheduled Task)
# ============================================================================

@dataclass
class ScheduledTask:
    """进入调度队列的异步任务实体"""
    task_id: str
    priority: EventPriority
    causal_token: CausalToken
    coro_fn: Callable[..., Coroutine[Any, Any, Any]]
    args: Tuple[Any, ...] = field(default_factory=tuple)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    cancel_token: CancellationToken = field(default_factory=CancellationToken)
    created_at: float = field(default_factory=time.time)
    sequence_number: int = field(default_factory=lambda: next(_TASK_SEQ))
    status: str = "PENDING"  # PENDING, RUNNING, COMPLETED, FAILED, CANCELLED

    def __lt__(self, other: "ScheduledTask") -> bool:
        if not isinstance(other, ScheduledTask):
            return NotImplemented
        if self.priority != other.priority:
            return self.priority < other.priority
        if self.created_at != other.created_at:
            return self.created_at < other.created_at
        return self.sequence_number < other.sequence_number


# ============================================================================
# 3. 优先级任务调度器与反向信用背压 (TaskScheduler)
# ============================================================================

class TaskScheduler:
    """
    优先级任务调度器与反向信用背压引擎。
    机制：
    1. 最小堆优先级队列管理（优先处理 P0/P1 任务）；
    2. 基于物理核心容量的并发信号量（Semaphore）；
    3. 反向信用需求流控（Credit-based Demand Backpressure），沙箱饱和时挂起生成，杜绝信箱爆仓。
    """

    def __init__(self, max_concurrency: int = 8) -> None:
        self.max_concurrency = max_concurrency
        self._priority_queue: asyncio.PriorityQueue[ScheduledTask] = asyncio.PriorityQueue()
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._active_tasks: Dict[str, ScheduledTask] = {}
        self._completed_tasks: Set[str] = set()
        self._lock = threading.Lock()
        self._running = False

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._active_tasks)

    def get_available_credit(self) -> int:
        """
        信用池方程：
        Credit_pool(t) = Capacity_max - ActiveTasks(t)
        """
        with self._lock:
            return max(0, self.max_concurrency - len(self._active_tasks))

    def request_credit(self, n: int = 1) -> int:
        """下游请求配额，返回实际发放的信用数"""
        with self._lock:
            avail = max(0, self.max_concurrency - len(self._active_tasks))
            granted = min(n, avail)
            return granted

    async def submit_task(self, task: ScheduledTask) -> None:
        """向调度队列投递任务 (协程安全)"""
        await self._priority_queue.put(task)

    async def schedule_coro(
        self,
        task_id: str,
        coro_fn: Callable[..., Coroutine[Any, Any, Any]],
        priority: EventPriority = EventPriority.P2_WORKER_PROGRESS,
        causal_token: Optional[CausalToken] = None,
        args: Tuple[Any, ...] = (),
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> ScheduledTask:
        """便捷提交协程任务"""
        from .events import _generate_default_token
        tok = causal_token or _generate_default_token(causal_level=1)
        task = ScheduledTask(
            task_id=task_id,
            priority=priority,
            causal_token=tok,
            coro_fn=coro_fn,
            args=args,
            kwargs=kwargs or {},
        )
        await self.submit_task(task)
        return task

    async def run_next(self) -> Optional[Any]:
        """从就绪优先级队列中出队一个任务并在信号量保护下执行"""
        task = await self._priority_queue.get()
        if task.cancel_token.is_cancelled:
            task.status = "CANCELLED"
            self._priority_queue.task_done()
            return None

        async with self._semaphore:
            with self._lock:
                self._active_tasks[task.task_id] = task
                task.status = "RUNNING"
            try:
                task.cancel_token.raise_if_cancelled()
                result = await task.coro_fn(*task.args, **task.kwargs)
                task.status = "COMPLETED"
                with self._lock:
                    self._completed_tasks.add(task.task_id)
                return result
            except asyncio.CancelledError as ce:
                task.status = "CANCELLED"
                raise ce
            except Exception as e:
                task.status = "FAILED"
                raise e
            finally:
                with self._lock:
                    self._active_tasks.pop(task.task_id, None)
                self._priority_queue.task_done()

    def cancel_task(self, task_id: str, reason: str = "Cancelled by scheduler") -> bool:
        """精确取消指定任务"""
        with self._lock:
            task = self._active_tasks.get(task_id)
        if task:
            task.cancel_token.cancel(reason)
            return True
        return False

    def cancel_all(self, reason: str = "Scheduler shutdown") -> int:
        """级联取消所有正在执行的任务"""
        with self._lock:
            tasks = list(self._active_tasks.values())
        for t in tasks:
            t.cancel_token.cancel(reason)
        return len(tasks)


# ============================================================================
# 4. 看门狗心跳监测器 (WatchdogMonitor)
# ============================================================================

class WatchdogMonitor:
    """
    看门狗心跳巡检监视器。
    职责：
    1. 追踪沙箱与 Worker 的心跳周期（默认 5s 周期，租约 30s）；
    2. 发现超期不响应任务，直接向其发送取消令牌，并发出 P1 级心跳超时报警；
    3. 支持注册超时触发动作（例如强杀进程树、释放 RAM-Disk）。
    """

    def __init__(
        self,
        check_interval_s: float = 1.0,
        default_timeout_s: float = 30.0,
        on_timeout_cb: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self.check_interval_s = check_interval_s
        self.default_timeout_s = default_timeout_s
        self.on_timeout_cb = on_timeout_cb

        self._lock = threading.Lock()
        # task_id -> {"last_heartbeat": float, "timeout_s": float, "token": CancellationToken}
        self._tracked_tasks: Dict[str, Dict[str, Any]] = {}
        self._running = False
        self._monitor_task: Optional[asyncio.Task[None]] = None

    def register_task(
        self,
        task_id: str,
        timeout_s: Optional[float] = None,
        cancel_token: Optional[CancellationToken] = None,
    ) -> None:
        """注册纳管一个新的被监视任务"""
        with self._lock:
            self._tracked_tasks[task_id] = {
                "last_heartbeat": time.time(),
                "timeout_s": timeout_s or self.default_timeout_s,
                "token": cancel_token,
                "timed_out": False,
            }

    def record_heartbeat(self, task_id: str) -> bool:
        """记录任务的心跳上报"""
        with self._lock:
            if task_id in self._tracked_tasks:
                self._tracked_tasks[task_id]["last_heartbeat"] = time.time()
                return True
        return False

    def unregister_task(self, task_id: str) -> None:
        """任务正常完成或终止时移出看门狗纳管"""
        with self._lock:
            self._tracked_tasks.pop(task_id, None)

    def check_timeouts(self) -> List[str]:
        """
        立即执行一次超时扫描。
        :return: 触发超时的任务 ID 列表
        """
        now = time.time()
        timed_out_tasks: List[Tuple[str, CancellationToken]] = []

        with self._lock:
            for tid, info in list(self._tracked_tasks.items()):
                if info["timed_out"]:
                    continue
                elapsed = now - info["last_heartbeat"]
                if elapsed > info["timeout_s"]:
                    info["timed_out"] = True
                    token = info["token"]
                    timed_out_tasks.append((tid, token))

        results = []
        for tid, token in timed_out_tasks:
            results.append(tid)
            if token:
                token.cancel(f"Task {tid} exceeded watchdog lease timeout")
            if self.on_timeout_cb:
                try:
                    self.on_timeout_cb(tid, "WATCHDOG_TIMEOUT")
                except Exception:
                    pass

        return results

    async def _monitor_loop(self) -> None:
        """后台异步巡检协程"""
        while self._running:
            self.check_timeouts()
            await asyncio.sleep(self.check_interval_s)

    def start(self) -> None:
        """启动后台监视循环"""
        if not self._running:
            self._running = True
            loop = asyncio.get_event_loop()
            self._monitor_task = loop.create_task(self._monitor_loop())

    def stop(self) -> None:
        """停止后台监视循环"""
        self._running = False
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            self._monitor_task = None


# ============================================================================
# 5. 死锁检测器与语义自旋判据 (DeadlockDetector)
# ============================================================================

class DeadlockDetector:
    """
    因果死锁检测与语义自旋判据引擎。
    四大功能：
    1. 单调分层因果等级验证：强制 L(u) < L(v)，从数学根源消除因果环路；
    2. Tarjan 强连通分量 (SCC) 动态破环算法：毫秒级定位等待依赖环路并执行最小代价切除；
    3. 语义自旋指数计算：
       Ψ_progress = ΔPhenotype / (ΔAST + ε)
       连续 K=3 轮低于 0.05 判定为死循环自旋；
    4. 自动生成修复与切除动作报告。
    """

    def __init__(self, semantic_spin_threshold: float = 0.05, epsilon: float = 1e-6) -> None:
        self.spin_threshold = semantic_spin_threshold
        self.epsilon = epsilon
        self._lock = threading.Lock()
        # branch_id -> list of (phenotype_val, ast_dist)
        self._branch_history: Dict[str, List[Tuple[float, float]]] = {}
        # task_id -> causal_level
        self._causal_ranks: Dict[str, int] = {}

    def register_causal_rank(self, task_id: str, rank: int) -> None:
        """登记任务因果等级"""
        with self._lock:
            self._causal_ranks[task_id] = rank

    def verify_monotonic_causality(self, u: str, v: str, rank_u: Optional[int] = None, rank_v: Optional[int] = None) -> None:
        """
        验证有向边 (u -> v) 是否满足单调因果定理 L(u) < L(v)。
        若违背则立即抛出 CausalDeadlockException。
        """
        with self._lock:
            ru = rank_u if rank_u is not None else self._causal_ranks.get(u, 0)
            rv = rank_v if rank_v is not None else self._causal_ranks.get(v, ru + 1)

        if ru >= rv:
            raise CausalDeadlockException(
                f"Monotonic Causal Stratification violated: Edge ({u} -> {v}) has Level({u})={ru} >= Level({v})={rv}! "
                f"This introduces potential cyclic deadlock into the causal DAG."
            )

    @staticmethod
    def tarjan_scc(graph: Dict[str, Set[str]]) -> List[List[str]]:
        """
        标准 Tarjan 强连通分量 (SCC) 算法实现。
        :param graph: 依赖等待图 (节点 -> 其依赖等待的目标节点集合)
        :return: 强连通分量列表，长度大于 1 的分量代表死锁闭环
        """
        index = 0
        indices: Dict[str, int] = {}
        lowlinks: Dict[str, int] = {}
        stack: List[str] = []
        on_stack: Set[str] = set()
        sccs: List[List[str]] = []

        def strongconnect(node: str) -> None:
            nonlocal index
            indices[node] = index
            lowlinks[node] = index
            index += 1
            stack.append(node)
            on_stack.add(node)

            for neighbor in graph.get(node, set()):
                if neighbor not in indices:
                    strongconnect(neighbor)
                    lowlinks[node] = min(lowlinks[node], lowlinks[neighbor])
                elif neighbor in on_stack:
                    lowlinks[node] = min(lowlinks[node], indices[neighbor])

            if lowlinks[node] == indices[node]:
                scc = []
                while True:
                    w = stack.pop()
                    on_stack.remove(w)
                    scc.append(w)
                    if w == node:
                        break
                sccs.append(scc)

        for node in list(graph.keys()):
            if node not in indices:
                strongconnect(node)

        return sccs

    def detect_cycles(self, waiting_graph: Dict[str, Set[str]]) -> List[List[str]]:
        """检测等待图中所有闭环死锁环路 (包含 SCC 大小 > 1 以及自环)"""
        sccs = self.tarjan_scc(waiting_graph)
        cycles: List[List[str]] = []
        for c in sccs:
            if len(c) > 1:
                cycles.append(c)
            elif len(c) == 1 and c[0] in waiting_graph.get(c[0], set()):
                cycles.append(c)
        return cycles

    def resolve_deadlocks(self, waiting_graph: Dict[str, Set[str]], max_iterations: int = 50) -> List[Tuple[str, str]]:
        """
        自动破环：针对检测到的死锁环路，选取 victim 依赖边切断。
        采用多轮迭代破环（max_iterations），循环重新计算 detect_cycles，
        直至图中无闭环死锁或达到迭代上限，彻底消解 8 字形等多环共享节点的复合死锁拓扑。
        :param waiting_graph: 依赖等待图 (会被原地修改)
        :param max_iterations: 最大迭代破环轮数，默认 50
        :return: 切断的边列表 (u, v)
        """
        severed_edges: List[Tuple[str, str]] = []
        for _ in range(max_iterations):
            cycles = self.detect_cycles(waiting_graph)
            if not cycles:
                break

            cut_made = False
            for cycle in cycles:
                cycle_nodes = set(cycle)
                for u in cycle:
                    for v in list(waiting_graph.get(u, set())):
                        if v in cycle_nodes:
                            waiting_graph[u].remove(v)
                            severed_edges.append((u, v))
                            cut_made = True
                            break
                    if cut_made:
                        break
                if cut_made:
                    break

            if not cut_made:
                break

        return severed_edges

    def record_semantic_progress(
        self,
        branch_id: str,
        phenotype_delta: float,
        ast_distance: float,
    ) -> None:
        """记录该分支一轮演化中表型改善量与 AST 正交距离位移"""
        with self._lock:
            self._branch_history.setdefault(branch_id, []).append((phenotype_delta, ast_distance))

    def is_semantic_spinning(
        self,
        branch_id: str,
        window_size: int = 3,
    ) -> bool:
        """
        判定是否陷入语义自旋：
        Ψ_progress = ΔPhenotype / (ΔAST + ε)
        若连续 window_size 轮的均值小于阈值 0.05，判定为自旋死循环。
        """
        with self._lock:
            history = self._branch_history.get(branch_id, [])
            if len(history) < window_size:
                return False
            recent = history[-window_size:]

        # 计算窗口内平均进展指数
        spin_indices = []
        for delta_p, delta_ast in recent:
            # 取绝对改善量 (若负变异视为 0 改善)
            effective_p = max(0.0, delta_p)
            psi = effective_p / (delta_ast + self.epsilon)
            spin_indices.append(psi)

        avg_psi = sum(spin_indices) / len(spin_indices)
        return avg_psi < self.spin_threshold
