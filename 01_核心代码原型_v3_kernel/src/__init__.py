"""
AFEVA: Anti-Fragile Epistemic & Verification Architecture for Ultra-Long Horizon Multi-Agent Systems.
Author: worker_m2 (Implementation Engineering Group)
Status: Production Ready
"""

from __future__ import annotations

import src.core as core

from .core import (
    # Core FSM & State
    FSMState,
    StateCategory,
    AsyncFSMDriver,
    LocalJoinBarrier,
    VALID_TRANSITIONS,
    can_transition,
    validate_transition,
    # Events
    FSMEvent,
    EventPriority,
    CausalToken,
    # Persistence
    WriteAheadLog,
    WALEntry,
    AtomicSnapshotEngine,
    FSMStateSnapshot,
    # Ledger & Playbook
    DualLedger,
    TaskLedger,
    ProgressLedger,
    LivingPlaybook,
    PlaybookBullet,
    # Scheduling & Guards
    TaskScheduler,
    WatchdogMonitor,
    DeadlockDetector,
    CancellationToken,
    # Contracts
    PhysicalMetrics,
    BehavioralProfile,
    WorktreeSpec,
    DiffSpec,
    GateVerdict,
    GateStatus,
    ForensicAuditVerdict,
    AuditCode,
    CandidateSolution,
    EpochSummary,
    # Exceptions
    AFEVASystemError,
    InvalidTransitionException,
    CausalDeadlockException,
    WorktreeLockException,
    MergeConflictException,
    AttentionDilutionAlert,
    WALCorruptionError,
    SnapshotError,
)

__version__ = "2.4.0"

__all__ = [
    "core",
    "__version__",
    "FSMState",
    "StateCategory",
    "AsyncFSMDriver",
    "LocalJoinBarrier",
    "VALID_TRANSITIONS",
    "can_transition",
    "validate_transition",
    "FSMEvent",
    "EventPriority",
    "CausalToken",
    "WriteAheadLog",
    "WALEntry",
    "AtomicSnapshotEngine",
    "FSMStateSnapshot",
    "DualLedger",
    "TaskLedger",
    "ProgressLedger",
    "LivingPlaybook",
    "PlaybookBullet",
    "TaskScheduler",
    "WatchdogMonitor",
    "DeadlockDetector",
    "CancellationToken",
    "PhysicalMetrics",
    "BehavioralProfile",
    "WorktreeSpec",
    "DiffSpec",
    "GateVerdict",
    "GateStatus",
    "ForensicAuditVerdict",
    "AuditCode",
    "CandidateSolution",
    "EpochSummary",
    "AFEVASystemError",
    "InvalidTransitionException",
    "CausalDeadlockException",
    "WorktreeLockException",
    "MergeConflictException",
    "AttentionDilutionAlert",
    "WALCorruptionError",
    "SnapshotError",
    # Worktree & Validation
    "WorktreeManager",
    "ValidationGate",
    # Evolution & Annealing
    "AnnealingController",
    "ASTDistanceAssessor",
    "IslandController",
]

# Export submodules
import src.worktree as worktree
import src.evolution as evolution
from src.worktree import WorktreeManager, ValidationGate
from src.evolution import AnnealingController, ASTDistanceAssessor, IslandController

