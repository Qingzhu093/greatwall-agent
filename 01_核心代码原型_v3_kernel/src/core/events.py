"""
Typed Asynchronous Events, Priority Enums, Payloads, and Event Factory Primitives for AFEVA Architecture.
Author: worker_m2 (Implementation Engineering Group)
Status: Production Ready
"""

from __future__ import annotations

import itertools
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from .contracts import (
    CausalToken,
    EventPriority,
    FSMState,
    GateStatus,
    GateVerdict,
    PhysicalMetrics,
)

__all__ = [
    "EventPriority",
    "CausalToken",
    "FSMEvent",
    "TaskDispatchPayload",
    "GateVerdictPayload",
    "PoisonPillPayload",
    "HeartbeatPayload",
    "ReheatingPayload",
    "CausalDataflowPayload",
    "create_poison_pill_event",
    "create_heartbeat_event",
    "create_causal_event",
    "create_stage_gate_event",
    "create_tick_event",
    "create_reheating_event",
]

# Monotonic sequence counter for priority queue tie-breaking
_SEQUENCE_GENERATOR = itertools.count()


# ============================================================================
# 1. 强类型事件有效载荷 (Typed Event Payloads)
# ============================================================================

@dataclass(frozen=True)
class TaskDispatchPayload:
    """任务派发载荷"""
    task_id: str
    worktree_id: str
    instructions: str
    timeout_s: float = 300.0
    extra_params: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GateVerdictPayload:
    """门禁评测载荷"""
    status: GateStatus
    tier_level: int
    diagnostics: Tuple[str, ...]
    evaluated_metrics: Optional[PhysicalMetrics] = None
    is_probationary: bool = False


@dataclass(frozen=True)
class PoisonPillPayload:
    """级联毒丸清算载荷 (P0 级)"""
    reason: str
    source_node: str
    affected_tokens: Tuple[str, ...]
    quarantine_ast_hash: Optional[str] = None
    fatal_exception: Optional[str] = None


@dataclass(frozen=True)
class HeartbeatPayload:
    """心跳健康状态载荷"""
    task_id: str
    progress: float
    status_msg: str = "ALIVE"
    memory_usage_bytes: int = 0
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class ReheatingPayload:
    """退火重加热脉冲载荷"""
    island_id: int
    boost_amount: float
    plateau_epochs: int
    reason: str


@dataclass(frozen=True)
class CausalDataflowPayload:
    """因果数据流就绪载荷"""
    artifact_cas_hash: str
    producer_task_id: str
    consumer_task_ids: Tuple[str, ...]
    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# 2. 强类型状态机异步事件实体 (FSMEvent)
# ============================================================================

@dataclass
class FSMEvent:
    """
    强类型状态机异步事件实体。
    支持标准 PriorityQueue / heapq 最小堆排序：
    1. 优先级数值越小越优先 (P0 < P1 < P2 < P3)
    2. 物理时间戳早的优先
    3. 全局单调自增序号作为严格保序 tie-breaker (确保 FIFO 单调保序)
    """
    event_id: str
    priority: EventPriority
    event_type: str
    source_state: FSMState
    target_state_hint: Optional[FSMState]
    causal_token: CausalToken
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    sequence_number: int = field(default_factory=lambda: next(_SEQUENCE_GENERATOR))

    def __lt__(self, other: "FSMEvent") -> bool:
        """优先队列排序比较魔术方法"""
        if not isinstance(other, FSMEvent):
            return NotImplemented
        if self.priority != other.priority:
            return self.priority < other.priority
        if self.timestamp != other.timestamp:
            return self.timestamp < other.timestamp
        return self.sequence_number < other.sequence_number

    def is_poison_pill(self) -> bool:
        """判定该事件是否为 P0 级毒丸清算事件"""
        return self.priority == EventPriority.P0_CRITICAL_POISON or "POISON" in self.event_type.upper()


# ============================================================================
# 3. 便捷事件工场函数 (Event Factory Functions)
# ============================================================================

def _generate_default_token(causal_level: int = 0, is_speculative: bool = False) -> CausalToken:
    """生成默认因果令牌"""
    return CausalToken(
        token_id=f"tok_{uuid.uuid4().hex[:12]}",
        causal_level=causal_level,
        parent_token_ids=(),
        payload_cas_hash=f"sha256:{uuid.uuid4().hex}{uuid.uuid4().hex}",
        is_speculative=is_speculative,
    )


def create_poison_pill_event(
    source_state: FSMState,
    reason: str,
    affected_tokens: Tuple[str, ...] = (),
    quarantine_ast_hash: Optional[str] = None,
    fatal_exception: Optional[str] = None,
    token: Optional[CausalToken] = None,
) -> FSMEvent:
    """创建 P0 级级联毒丸抢占事件"""
    tok = token or _generate_default_token(causal_level=999)
    payload_obj = PoisonPillPayload(
        reason=reason,
        source_node=source_state.value,
        affected_tokens=affected_tokens,
        quarantine_ast_hash=quarantine_ast_hash,
        fatal_exception=fatal_exception,
    )
    return FSMEvent(
        event_id=f"evt_poison_{uuid.uuid4().hex[:8]}",
        priority=EventPriority.P0_CRITICAL_POISON,
        event_type="EVT_POISON_PILL",
        source_state=source_state,
        target_state_hint=FSMState.S14_APOPTOSIS_FLUSH,
        causal_token=tok,
        payload={"poison": payload_obj, "reason": reason},
    )


def create_heartbeat_event(
    task_id: str,
    progress: float,
    status_msg: str = "ALIVE",
    memory_usage_bytes: int = 0,
    source_state: FSMState = FSMState.S04_CODE_SYNTHESIS,
    token: Optional[CausalToken] = None,
) -> FSMEvent:
    """创建看门狗心跳或超时事件"""
    tok = token or _generate_default_token(causal_level=1)
    payload_obj = HeartbeatPayload(
        task_id=task_id,
        progress=progress,
        status_msg=status_msg,
        memory_usage_bytes=memory_usage_bytes,
    )
    is_timeout = (status_msg == "TIMEOUT")
    prio = EventPriority.P1_WATCHDOG_HEARTBEAT if is_timeout else EventPriority.P3_BACKGROUND_TICK
    return FSMEvent(
        event_id=f"evt_hb_{uuid.uuid4().hex[:8]}",
        priority=prio,
        event_type="EVT_WATCHDOG_TIMEOUT" if is_timeout else "EVT_WATCHDOG_HEARTBEAT",
        source_state=source_state,
        target_state_hint=FSMState.S14_APOPTOSIS_FLUSH if is_timeout else None,
        causal_token=tok,
        payload={"heartbeat": payload_obj, "task_id": task_id, "is_timeout": is_timeout},
    )


def create_causal_event(
    event_type: str,
    source_state: FSMState,
    target_state_hint: Optional[FSMState],
    token: CausalToken,
    payload: Optional[Dict[str, Any]] = None,
    priority: EventPriority = EventPriority.P2_CAUSAL_DATAFLOW,
) -> FSMEvent:
    """创建常规因果数据流就绪事件"""
    return FSMEvent(
        event_id=f"evt_causal_{uuid.uuid4().hex[:8]}",
        priority=priority,
        event_type=event_type,
        source_state=source_state,
        target_state_hint=target_state_hint,
        causal_token=token,
        payload=payload or {},
    )


def create_stage_gate_event(
    source_state: FSMState,
    target_state_hint: Optional[FSMState],
    verdict: GateVerdict,
    token: CausalToken,
) -> FSMEvent:
    """创建 P1 级阶梯门禁裁决事件"""
    verdict_payload = GateVerdictPayload(
        status=verdict.status,
        tier_level=verdict.tier_level,
        diagnostics=verdict.diagnostics,
        evaluated_metrics=verdict.evaluated_metrics,
        is_probationary=verdict.is_probationary,
    )
    return FSMEvent(
        event_id=f"evt_gate_{uuid.uuid4().hex[:8]}",
        priority=EventPriority.P1_STAGE_GATE_EVAL,
        event_type=f"EVT_TIER{verdict.tier_level}_VERDICT",
        source_state=source_state,
        target_state_hint=target_state_hint,
        causal_token=token,
        payload={"verdict": verdict, "verdict_payload": verdict_payload},
    )


def create_reheating_event(
    island_id: int,
    boost_amount: float,
    reason: str,
    plateau_epochs: int = 3,
    source_state: FSMState = FSMState.S05_ROUGH_EVAL,
    token: Optional[CausalToken] = None,
) -> FSMEvent:
    """创建重加热脉冲事件"""
    tok = token or _generate_default_token(causal_level=1)
    payload_obj = ReheatingPayload(
        island_id=island_id,
        boost_amount=boost_amount,
        plateau_epochs=plateau_epochs,
        reason=reason,
    )
    return FSMEvent(
        event_id=f"evt_reheat_{uuid.uuid4().hex[:8]}",
        priority=EventPriority.P1_STAGE_GATE_EVAL,
        event_type="EVT_STALL_DETECTED",
        source_state=source_state,
        target_state_hint=FSMState.S13_REHEATING_PULSE,
        causal_token=tok,
        payload={"reheating": payload_obj, "boost_amount": boost_amount},
    )


def create_tick_event(
    source_state: FSMState = FSMState.S01_IDLE,
    payload: Optional[Dict[str, Any]] = None,
    token: Optional[CausalToken] = None,
) -> FSMEvent:
    """创建后台 P3 周期驱动事件"""
    tok = token or _generate_default_token(causal_level=0)
    return FSMEvent(
        event_id=f"evt_tick_{uuid.uuid4().hex[:8]}",
        priority=EventPriority.P3_BACKGROUND_TICK,
        event_type="EVT_BACKGROUND_TICK",
        source_state=source_state,
        target_state_hint=None,
        causal_token=tok,
        payload=payload or {},
    )
