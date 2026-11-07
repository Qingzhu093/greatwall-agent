"""
Core State Machine, Scheduling Primitives, WAL, Snapshot, and Ledger Subsystem for AFEVA Architecture.
Author: worker_m2 (Implementation Engineering Group)
Status: Production Ready
"""

from __future__ import annotations

# Contracts, Enums, Dataclasses, Exceptions, ABCs
from .contracts import (
    AFEVASystemError,
    AttentionDilutionAlert,
    AuditCode,
    BehavioralProfile,
    CandidateSolution,
    CausalDeadlockException,
    CausalToken,
    DiffSpec,
    EpochSummary,
    EventPriority,
    ForensicAuditVerdict,
    ForensicCheatingDetected,
    FSMState,
    GateStatus,
    GateVerdict,
    IASTDistanceAssessor,
    IAnnealingController,
    IDualLedger,
    IFSMDriver,
    IForensicAuditor,
    IIslandController,
    InvalidTransitionException,
    IslandRole,
    IValidationGate,
    IWorktreeManager,
    LeaseExpiredException,
    MigrationBundle,
    PhysicalMetrics,
    PlaybookBullet,
    SnapshotError,
    StateCategory,
    STATE_TO_CATEGORY,
    WALCorruptionError,
    WorktreeLockException,
    MergeConflictException,
    WorktreeSpec,
)

# State Machine Transitions & Guards
from .state import (
    VALID_TRANSITIONS,
    TransitionGuard,
    can_transition,
    get_allowed_transitions,
    get_state_category,
    register_transition_guard,
    validate_transition,
)

# Events & Payloads
from .events import (
    CausalDataflowPayload,
    FSMEvent,
    GateVerdictPayload,
    HeartbeatPayload,
    PoisonPillPayload,
    ReheatingPayload,
    TaskDispatchPayload,
    create_causal_event,
    create_heartbeat_event,
    create_poison_pill_event,
    create_reheating_event,
    create_stage_gate_event,
    create_tick_event,
)

# Write-Ahead Log
from .wal import (
    WALEntry,
    WriteAheadLog,
)

# Snapshot Engine
from .snapshot import (
    AtomicSnapshotEngine,
    FSMStateSnapshot,
)

# Dual Ledger & Stanford ACE Playbook
from .ledger import (
    DualLedger,
    LivingPlaybook,
    ProgressLedger,
    TaskLedger,
)

# Scheduler & Deadlock / Watchdog Detection
from .scheduler import (
    CancellationToken,
    DeadlockDetector,
    ScheduledTask,
    TaskScheduler,
    WatchdogMonitor,
)

# Concurrent Engine & Barriers
from .engine import (
    AsyncFSMDriver,
    LocalJoinBarrier,
)

__all__ = [
    # Contracts & Enums
    "FSMState",
    "StateCategory",
    "STATE_TO_CATEGORY",
    "EventPriority",
    "GateStatus",
    "AuditCode",
    "IslandRole",
    "PhysicalMetrics",
    "BehavioralProfile",
    "WorktreeSpec",
    "DiffSpec",
    "PlaybookBullet",
    "CandidateSolution",
    "EpochSummary",
    "MigrationBundle",
    "GateVerdict",
    "ForensicAuditVerdict",
    "CausalToken",
    # Exceptions
    "AFEVASystemError",
    "WorktreeLockException",
    "MergeConflictException",
    "InvalidTransitionException",
    "CausalDeadlockException",
    "ForensicCheatingDetected",
    "AttentionDilutionAlert",
    "LeaseExpiredException",
    "WALCorruptionError",
    "SnapshotError",
    # ABCs
    "IFSMDriver",
    "IWorktreeManager",
    "IValidationGate",
    "IAnnealingController",
    "IASTDistanceAssessor",
    "IIslandController",
    "IDualLedger",
    "IForensicAuditor",
    # State Logic
    "VALID_TRANSITIONS",
    "TransitionGuard",
    "can_transition",
    "validate_transition",
    "register_transition_guard",
    "get_allowed_transitions",
    "get_state_category",
    # Events
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
    # WAL
    "WALEntry",
    "WriteAheadLog",
    # Snapshot
    "FSMStateSnapshot",
    "AtomicSnapshotEngine",
    # Ledger
    "TaskLedger",
    "ProgressLedger",
    "LivingPlaybook",
    "DualLedger",
    # Scheduler
    "CancellationToken",
    "ScheduledTask",
    "TaskScheduler",
    "WatchdogMonitor",
    "DeadlockDetector",
    # Engine
    "LocalJoinBarrier",
    "AsyncFSMDriver",
]
