"""
Asynchronous Concurrent FSM Driver Engine, Local Causal Join Barriers, Priority Preemption, and Graceful Self-Healing.
Author: worker_m2 (Implementation Engineering Group)
Status: Production Ready
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
import time
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set

from .contracts import (
    CausalDeadlockException,
    FSMState,
    IFSMDriver,
    InvalidTransitionException,
)
from .events import EventPriority, FSMEvent, create_poison_pill_event
from .ledger import DualLedger
from .scheduler import CancellationToken, TaskScheduler
from .snapshot import AtomicSnapshotEngine, FSMStateSnapshot
from .state import can_transition, get_state_category, validate_transition
from .wal import WriteAheadLog

__all__ = [
    "LocalJoinBarrier",
    "AsyncFSMDriver",
]

logger = logging.getLogger("AFEVA.Engine")


# ============================================================================
# 1. 局部因果汇聚门控 (Local Join Barrier - 破除全局代际木桶效应)
# ============================================================================

class LocalJoinBarrier:
    """
    局部因果汇聚门控 (Local Join Barrier).
    彻底废除全局代际硬锁 (Epoch Lock)，实行精细化因果依赖汇聚：
    1. 每个任务仅订阅其直接因果前驱集合 Pred(v)；
    2. 当且仅当前驱全部完备时，毫秒级释放下游任务；
    3. 非相关长尾分支的慢跑、重试在数学上完全不阻塞当前就绪分支的高速推进。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # task_id -> set of pending predecessor task_ids
        self._pending_deps: Dict[str, Set[str]] = {}
        # task_id -> set of initial required predecessor task_ids
        self._required_deps: Dict[str, Set[str]] = {}
        # predecessor_id -> list of waiting task_ids
        self._downstream_subscribers: Dict[str, Set[str]] = {}
        # predecessor_id -> artifact CAS hash
        self._satisfied_artifacts: Dict[str, str] = {}

    def register_barrier(self, task_id: str, required_predecessors: Set[str]) -> None:
        """登记一个下游任务的因果屏障门控"""
        with self._lock:
            preds = set(required_predecessors)
            self._required_deps[task_id] = preds
            # 过滤掉已经提前完成的前驱
            unresolved = {p for p in preds if p not in self._satisfied_artifacts}
            self._pending_deps[task_id] = unresolved

            for p in unresolved:
                self._downstream_subscribers.setdefault(p, set()).add(task_id)

    def notify_completed(self, predecessor_id: str, result_artifact_hash: str = "", artifact_hash: Optional[str] = None) -> List[str]:
        """
        通知某个前驱任务已完成。
        自动解冻并返回所有在此刻因果依赖全部得到满足的下游任务列表。
        :return: 刚刚被完全释放、可以立即执行的下游任务 ID 列表
        """
        art_hash = artifact_hash or result_artifact_hash or "UNKNOWN_HASH"
        unblocked_tasks: List[str] = []
        with self._lock:
            self._satisfied_artifacts[predecessor_id] = art_hash
            subscribers = self._downstream_subscribers.pop(predecessor_id, set())

            for downstream_id in subscribers:
                if downstream_id in self._pending_deps:
                    self._pending_deps[downstream_id].discard(predecessor_id)
                    if len(self._pending_deps[downstream_id]) == 0:
                        # 全部依赖已就绪，释放该任务！
                        unblocked_tasks.append(downstream_id)

        return unblocked_tasks

    def is_ready(self, task_id: str) -> bool:
        """判定该任务是否已越过因果屏障门控"""
        with self._lock:
            if task_id not in self._pending_deps:
                return True
            return len(self._pending_deps[task_id]) == 0

    def get_pending_dependencies(self, task_id: str) -> Set[str]:
        """获取尚未解除的挂起前驱集合"""
        with self._lock:
            return set(self._pending_deps.get(task_id, set()))

    def unregister_barrier(self, task_id: str) -> None:
        """移除门控登记"""
        with self._lock:
            self._pending_deps.pop(task_id, None)
            self._required_deps.pop(task_id, None)
            for subs in self._downstream_subscribers.values():
                subs.discard(task_id)


# ============================================================================
# 2. 异步并发状态机主驱动引擎 (AsyncFSMDriver)
# ============================================================================

class AsyncFSMDriver(IFSMDriver):
    """
    形式化 14 状态异步并发驱动引擎标准实现。
    特性保障：
    1. 严格实现 IFSMDriver 抽象基类；
    2. 基于 PriorityQueue 的四级优先级抢占事件循环；
    3. P0 级毒丸级联清算与 SIGKILL 快速熔断；
    4. 每次内存状态跃迁前强制同步预写 WAL，杜绝静默丢失；
    5. 局部因果就绪门控 (LocalJoinBarrier) 协同驱动；
    6. 状态进入 / 退出回调动作 (on_enter, on_exit)，支持同步与异步协程；
    7. 优雅关机与原子快照自愈恢复。
    """

    def __init__(
        self,
        node_id: str = "driver_main",
        initial_state: FSMState = FSMState.S01_IDLE,
        wal: Optional[WriteAheadLog] = None,
        snapshot_engine: Optional[AtomicSnapshotEngine] = None,
        ledger: Optional[DualLedger] = None,
        scheduler: Optional[TaskScheduler] = None,
    ) -> None:
        self.node_id = node_id
        self._current_state = initial_state
        self.wal = wal
        self.snapshot_engine = snapshot_engine
        self.ledger = ledger
        self.scheduler = scheduler or TaskScheduler()
        self.barrier = LocalJoinBarrier()

        self._event_queue: asyncio.PriorityQueue[FSMEvent] = asyncio.PriorityQueue()
        self._state_hooks: Dict[FSMState, Dict[str, List[Callable[..., Any]]]] = {}
        self._running = False
        self._loop_task: Optional[asyncio.Task[None]] = None
        self._cancel_token = CancellationToken()
        self._lock = threading.Lock()
        self._state_history: List[Tuple[float, FSMState, FSMState, str]] = []

    def get_current_state(self) -> FSMState:
        """获取当前引擎所处的状态机状态"""
        with self._lock:
            return self._current_state

    def force_set_state(self, new_state: FSMState, context: Optional[Dict[str, Any]] = None) -> None:
        """供 WAL 重放与快照恢复专用的直接置位方法 (绕过常规守卫与 WAL 追加写)"""
        with self._lock:
            old = self._current_state
            self._current_state = new_state
            self._state_history.append((time.time(), old, new_state, "FORCE_REPLAY"))

    def register_state_hook(
        self,
        state: FSMState,
        on_enter: Optional[Callable[..., Any]] = None,
        on_exit: Optional[Callable[..., Any]] = None,
    ) -> None:
        """为特定状态注册进入与退出回调函数 (支持同步函数与异步协程)"""
        hooks = self._state_hooks.setdefault(state, {"on_enter": [], "on_exit": []})
        if on_enter:
            hooks["on_enter"].append(on_enter)
        if on_exit:
            hooks["on_exit"].append(on_exit)

    async def _execute_hooks(self, hook_list: List[Callable[..., Any]], *args: Any, **kwargs: Any) -> None:
        """执行一组状态钩子回调"""
        for hook in hook_list:
            try:
                if inspect.iscoroutinefunction(hook):
                    await hook(*args, **kwargs)
                else:
                    hook(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error in state hook {hook}: {e}", exc_info=True)

    async def submit_event(self, event: FSMEvent) -> None:
        """
        向引擎优先级事件队列提交新事件 (线程安全 / 协程安全)。
        P0 级毒丸事件将直接触发异步抢占，打断当前所有投机工作。
        """
        if event.priority == EventPriority.P0_CRITICAL_POISON:
            # 立即触发抢占回调
            logger.warning(f"P0 Critical Poison event received: {event.event_type}, reason={event.payload.get('reason')}")
            self.scheduler.cancel_all(reason=f"Poison Pill P0: {event.payload.get('reason', 'Aborted')}")

        await self._event_queue.put(event)

    async def transition(self, event: FSMEvent) -> FSMState:
        """
        执行确定性单步状态转移。
        执行流程：
        1. 守卫校验 (validate_transition)；
        2. 触发原状态的 on_exit 回调；
        3. 写入 WAL 预写日志并物理刷盘；
        4. 推进内存状态并记录历史；
        5. 触发新状态的 on_enter 回调；
        6. 向 DualLedger 投影事件。
        """
        with self._lock:
            from_state = self._current_state

        target_state = event.target_state_hint or from_state
        is_emergency = event.is_poison_pill()

        # 1. 守卫检验
        validate_transition(from_state, target_state, is_emergency=is_emergency, context=event.payload)

        # 2. 触发 on_exit 钩子
        exit_hooks = self._state_hooks.get(from_state, {}).get("on_exit", [])
        if exit_hooks:
            await self._execute_hooks(exit_hooks, from_state, target_state, event)

        # 3. WAL 预写日志持久化 (内存变更前必须落盘)
        current_lsn = 0
        if self.wal:
            entry = self.wal.append(
                node_id=self.node_id,
                from_state=from_state,
                to_state=target_state,
                commit_hash=event.payload.get("commit_hash", "HEAD"),
                payload=event.payload,
            )
            current_lsn = entry.lsn

        # 4. 内存状态推进
        with self._lock:
            self._current_state = target_state
            self._state_history.append((time.time(), from_state, target_state, event.event_type))

        logger.info(
            f"FSM Transition: [{from_state.value}] -> [{target_state.value}] "
            f"via ({event.event_type}, Prio={event.priority.name}, LSN={current_lsn})"
        )

        # 5. 触发新状态 on_enter 钩子
        enter_hooks = self._state_hooks.get(target_state, {}).get("on_enter", [])
        if enter_hooks:
            await self._execute_hooks(enter_hooks, target_state, from_state, event)

        # 6. 账本投影
        if self.ledger:
            self.ledger.append_event(event)

        return target_state

    async def run_cycle(self) -> None:
        """单步事件循环调度周期"""
        self._cancel_token.raise_if_cancelled()
        try:
            # 等待优先级最高的事件出队
            event = await self._event_queue.get()
            try:
                await self.transition(event)
            finally:
                self._event_queue.task_done()
        except asyncio.CancelledError:
            raise
        except InvalidTransitionException as ite:
            logger.error(f"Transition guard rejected: {ite}")
            # 转移非法，自动向 S14 故障转移
            err_evt = create_poison_pill_event(
                source_state=self.get_current_state(),
                reason=f"InvalidTransition: {ite}",
                fatal_exception=str(ite),
            )
            await self.transition(err_evt)
        except Exception as ex:
            logger.error(f"Unhandled error in FSM cycle: {ex}", exc_info=True)
            err_evt = create_poison_pill_event(
                source_state=self.get_current_state(),
                reason=f"EngineCycleError: {ex}",
                fatal_exception=str(ex),
            )
            await self.transition(err_evt)

    async def _driver_loop(self) -> None:
        """主驱动协程持续消费优先级事件"""
        while self._running and not self._cancel_token.is_cancelled:
            try:
                await self.run_cycle()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Fatal error in driver loop: {e}", exc_info=True)
                break

    def start(self) -> None:
        """启动后台事件循环主驱动协程"""
        if not self._running:
            self._running = True
            loop = asyncio.get_event_loop()
            self._loop_task = loop.create_task(self._driver_loop())

    async def shutdown(self, save_snapshot: bool = True) -> None:
        """
        优雅关机清栈：
        1. 停止接收新事件；
        2. 级联取消所有活跃异步任务；
        3. 保存崩溃恢复原子快照；
        4. 状态跃迁至 S14_APOPTOSIS_FLUSH。
        """
        self._running = False
        self._cancel_token.cancel("Driver shutdown")

        # 取消正在调度的工作
        self.scheduler.cancel_all(reason="Engine shutdown initiated")

        # 转移至凋亡清栈终态
        if self.get_current_state() not in (FSMState.S14_APOPTOSIS_FLUSH, FSMState.S14_FAILED):
            flush_evt = create_poison_pill_event(
                source_state=self.get_current_state(),
                reason="Normal graceful apoptosis shutdown",
            )
            try:
                await self.transition(flush_evt)
            except Exception:
                self.force_set_state(FSMState.S14_APOPTOSIS_FLUSH)

        # 原子落盘终态快照
        if save_snapshot and self.snapshot_engine:
            lsn = self.wal.current_lsn if self.wal else 0
            snap = FSMStateSnapshot.create(
                lsn=lsn,
                current_state=self.get_current_state(),
                git_commit_hash="FINAL_SHUTDOWN",
                context_variables={"shutdown_time": time.time(), "node_id": self.node_id},
            )
            self.snapshot_engine.save_snapshot(snap)

        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
