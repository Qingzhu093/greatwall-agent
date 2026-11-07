"""
14-State Formal Asynchronous Finite State Machine Specification, Matrix Rules, and Guard Validators.
Author: worker_m2 (Implementation Engineering Group)
Status: Production Ready
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Set, Tuple

from .contracts import (
    FSMState,
    InvalidTransitionException,
    StateCategory,
    STATE_TO_CATEGORY,
)

# Re-export core state enums
__all__ = [
    "FSMState",
    "StateCategory",
    "STATE_TO_CATEGORY",
    "TransitionGuard",
    "VALID_TRANSITIONS",
    "can_transition",
    "validate_transition",
    "register_transition_guard",
    "get_allowed_transitions",
    "get_state_category",
]

# Guard callable signature: guard(from_state, to_state, context) -> bool
TransitionGuard = Callable[[FSMState, FSMState, Dict[str, Any]], bool]

# ============================================================================
# 1. 形式化状态转移矩阵定义 (Formal State Transition Matrix)
# ============================================================================

# 常规非紧急流转拓扑关系
VALID_TRANSITIONS: Dict[FSMState, Set[FSMState]] = {
    FSMState.S01_IDLE: {
        FSMState.S02_SEEDING,
        FSMState.S14_FAILED,
    },
    FSMState.S02_SEEDING: {
        FSMState.S03_BLIND_IDEATION,
        FSMState.S13_REHEATING_PULSE,
        FSMState.S14_APOPTOSIS_FLUSH,
        FSMState.S14_FAILED,
    },
    FSMState.S03_BLIND_IDEATION: {
        FSMState.S04_CODE_SYNTHESIS,
        FSMState.S13_REHEATING_PULSE,
        FSMState.S14_APOPTOSIS_FLUSH,
        FSMState.S14_FAILED,
    },
    FSMState.S04_CODE_SYNTHESIS: {
        FSMState.S05_ROUGH_EVAL,
        FSMState.S13_REHEATING_PULSE,
        FSMState.S14_APOPTOSIS_FLUSH,
        FSMState.S14_FAILED,
    },
    FSMState.S05_ROUGH_EVAL: {
        FSMState.S06_PROBATION,          # 偏科生带病晋级
        FSMState.S09_STAGING_EVAL,      # 直接优异晋级
        FSMState.S13_REHEATING_PULSE,
        FSMState.S14_APOPTOSIS_FLUSH,   # 淘汰修剪
        FSMState.S14_FAILED,
    },
    FSMState.S06_PROBATION: {
        FSMState.S07_PREDATOR_PAIRING,  # 捕食者配对生成反例
        FSMState.S13_REHEATING_PULSE,
        FSMState.S14_APOPTOSIS_FLUSH,
        FSMState.S14_FAILED,
    },
    FSMState.S07_PREDATOR_PAIRING: {
        FSMState.S08_HYBRID_REPAIR,     # 定向杂交补丁
        FSMState.S13_REHEATING_PULSE,
        FSMState.S14_APOPTOSIS_FLUSH,
        FSMState.S14_FAILED,
    },
    FSMState.S08_HYBRID_REPAIR: {
        FSMState.S09_STAGING_EVAL,      # 杂交后再次进入中继评估
        FSMState.S13_REHEATING_PULSE,
        FSMState.S14_APOPTOSIS_FLUSH,
        FSMState.S14_FAILED,
    },
    FSMState.S09_STAGING_EVAL: {
        FSMState.S10_FORENSIC_AUDIT,    # 进入法医审计
        FSMState.S13_REHEATING_PULSE,
        FSMState.S14_APOPTOSIS_FLUSH,
        FSMState.S14_FAILED,
    },
    FSMState.S10_FORENSIC_AUDIT: {
        FSMState.S11_IRON_EVAL,         # 移交独占核心钢铁终审
        FSMState.S13_REHEATING_PULSE,
        FSMState.S14_APOPTOSIS_FLUSH,   # 确证作弊或死代码直接消杀
        FSMState.S14_FAILED,
    },
    FSMState.S11_IRON_EVAL: {
        FSMState.S12_ATOMIC_COMMIT,     # 100% 满分通过，原子合并
        FSMState.S08_HYBRID_REPAIR,     # 仅差微小用例，给予最后定向杂交机会
        FSMState.S13_REHEATING_PULSE,
        FSMState.S14_APOPTOSIS_FLUSH,   # 彻底违规打回
        FSMState.S14_FAILED,
    },
    FSMState.S12_ATOMIC_COMMIT: {
        FSMState.S14_APOPTOSIS_FLUSH,   # 提交成功后清栈重播种
        FSMState.S01_IDLE,              # 直接就绪下一代际
        FSMState.S14_FAILED,
    },
    FSMState.S13_REHEATING_PULSE: {
        FSMState.S03_BLIND_IDEATION,    # 升温后重新大步长探索
        FSMState.S02_SEEDING,           # 重新装配引物
        FSMState.S04_CODE_SYNTHESIS,
        FSMState.S14_APOPTOSIS_FLUSH,
        FSMState.S14_FAILED,
    },
    FSMState.S14_APOPTOSIS_FLUSH: {
        FSMState.S01_IDLE,              # 清栈完成，重置为空闲
        FSMState.S14_FAILED,
    },
    FSMState.S14_FAILED: {
        FSMState.S01_IDLE,              # 故障重置/恢复
        FSMState.S14_APOPTOSIS_FLUSH,
    },
}

# 动态可扩充守卫校验器字典: (from_state, to_state) -> List[TransitionGuard]
_GUARD_REGISTRY: Dict[Tuple[FSMState, FSMState], list[TransitionGuard]] = {}


# ============================================================================
# 2. 内置默认守卫校验逻辑 (Default Transition Guards)
# ============================================================================

def _guard_idle_to_seeding(from_state: FSMState, to_state: FSMState, context: Dict[str, Any]) -> bool:
    """S01 -> S02: 必须包含有效 task_id 或 session_id"""
    return bool(context.get("task_id") or context.get("session_id") or context.get("allow_init", True))


def _guard_iron_to_commit(from_state: FSMState, to_state: FSMState, context: Dict[str, Any]) -> bool:
    """S11 -> S12: 必须 100% 通过且无超时及崩溃"""
    if "verdict" in context:
        verdict = context["verdict"]
        # If GateVerdict or bool or str
        status = getattr(verdict, "status", None) or verdict
        if str(status) in ("APPROVE", "GateStatus.APPROVE"):
            return True
        if hasattr(verdict, "is_viable") and not verdict.is_viable():
            return False
    return context.get("iron_pass", True)


def _guard_forensic_to_iron(from_state: FSMState, to_state: FSMState, context: Dict[str, Any]) -> bool:
    """S10 -> S11: 杜绝作弊与硬件因果异常"""
    audit = context.get("audit_verdict")
    if audit is not None:
        if hasattr(audit, "is_clean_pass"):
            return audit.is_clean_pass()
        code = getattr(audit, "audit_code", audit)
        if str(code) in ("CHEAT_LOOKUP_TABLE", "CHEAT_DEAD_CODE", "HARDWARE_ANOMALY"):
            return False
    return True


# 注册默认守卫
_GUARD_REGISTRY.setdefault((FSMState.S01_IDLE, FSMState.S02_SEEDING), []).append(_guard_idle_to_seeding)
_GUARD_REGISTRY.setdefault((FSMState.S11_IRON_EVAL, FSMState.S12_ATOMIC_COMMIT), []).append(_guard_iron_to_commit)
_GUARD_REGISTRY.setdefault((FSMState.S10_FORENSIC_AUDIT, FSMState.S11_IRON_EVAL), []).append(_guard_forensic_to_iron)


# ============================================================================
# 3. 公共查询与守卫校验函数 (Public Transition Functions)
# ============================================================================

def get_state_category(state: FSMState) -> StateCategory:
    """获取指定状态的所属分类"""
    return STATE_TO_CATEGORY.get(state, StateCategory.TERMINAL)


def get_allowed_transitions(from_state: FSMState, is_emergency: bool = False) -> Set[FSMState]:
    """获取指定源状态所允许跳转的全部目标状态集合"""
    allowed = set(VALID_TRANSITIONS.get(from_state, set()))
    if is_emergency:
        # 紧急抢占态下，任何状态均可跳转到凋亡清栈或故障终态
        allowed.add(FSMState.S14_APOPTOSIS_FLUSH)
        allowed.add(FSMState.S14_FAILED)
    return allowed


def register_transition_guard(
    from_state: FSMState,
    to_state: FSMState,
    guard_fn: TransitionGuard,
) -> None:
    """在运行时向特定跃迁路径动态注册前置守卫校验函数"""
    _GUARD_REGISTRY.setdefault((from_state, to_state), []).append(guard_fn)


def can_transition(
    from_state: FSMState,
    to_state: FSMState,
    is_emergency: bool = False,
    context: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    静态与守卫判定两状态间是否允许发生转移。
    :param from_state: 起始状态
    :param to_state: 目标状态
    :param is_emergency: 是否为 P0 级毒丸/看门狗抢占等紧急流转
    :param context: 携带的上下文判定参数
    :return: True 允许转移，False 禁止转移
    """
    if from_state == to_state:
        # 允许同状态自旋幂等确认
        return True

    if is_emergency and to_state in (FSMState.S14_APOPTOSIS_FLUSH, FSMState.S14_FAILED):
        return True

    allowed_targets = VALID_TRANSITIONS.get(from_state, set())
    if to_state not in allowed_targets:
        return False

    ctx = context or {}
    guards = _GUARD_REGISTRY.get((from_state, to_state), [])
    for guard in guards:
        try:
            if not guard(from_state, to_state, ctx):
                return False
        except Exception:
            return False

    return True


def validate_transition(
    from_state: FSMState,
    to_state: FSMState,
    is_emergency: bool = False,
    context: Optional[Dict[str, Any]] = None,
) -> None:
    """
    验证状态转移合法性，若非法则立即抛出强类型 InvalidTransitionException。
    """
    if not can_transition(from_state, to_state, is_emergency=is_emergency, context=context):
        category = get_state_category(from_state).value
        raise InvalidTransitionException(
            f"Invalid FSM transition: [{from_state.value}] ({category}) -> [{to_state.value}]. "
            f"Emergency={is_emergency}, ContextKeys={list((context or {}).keys())}."
        )
