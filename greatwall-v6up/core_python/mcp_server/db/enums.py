"""GreatWall Agent v0.3 全仓权威枚举与统一错误码（Single Source of Truth）。"""

from __future__ import annotations

from typing import Any

# ============================================================================
# 统一错误码
# ============================================================================
ERR_AUTH = "ERR_AUTH"
ERR_INVALID_INPUT = "ERR_INVALID_INPUT"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_CONFLICT = "ERR_CONFLICT"
ERR_LOCKED = "ERR_LOCKED"
ERR_INVARIANT = "ERR_INVARIANT"
ERR_EXECUTION = "ERR_EXECUTION"
ERR_STORAGE = "ERR_STORAGE"
ERR_STALE_EPOCH = "ERR_STALE_EPOCH"
ERR_MISSING_MODEL_BINDING = "MISSING_MODEL_BINDING"
ERR_HUMAN_STOP_NOT_RECORDED = "HUMAN_STOP_NOT_RECORDED"

CORE_ERROR_CODES = frozenset(
    {
        ERR_AUTH,
        ERR_INVALID_INPUT,
        ERR_NOT_FOUND,
        ERR_CONFLICT,
        ERR_LOCKED,
        ERR_INVARIANT,
        ERR_EXECUTION,
        ERR_STORAGE,
        ERR_STALE_EPOCH,
        ERR_MISSING_MODEL_BINDING,
        ERR_HUMAN_STOP_NOT_RECORDED,
    }
)


class FailClosedError(Exception):
    """Fail-Closed 结构化阻断异常。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code if code in CORE_ERROR_CODES else ERR_INVALID_INPUT
        self.message = message

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error_code": self.code,
            "error": self.message,
        }


# ============================================================================
# 仪器科学工程枚举
# ============================================================================
ALLOWED_INSTRUMENT_ROLES = frozenset({"VERDICT", "PROBE", "ENV"})
ALLOWED_INSTRUMENT_TIERS = frozenset({"probe", "official", "heavy"})
ALLOWED_INSTRUMENT_STATUSES = frozenset({"OK", "CANDIDATE_ERROR", "INSTRUMENT_ERROR", "INFRA_ERROR"})
ALLOWED_VERDICTS = frozenset({"PASS", "FAIL", "UNDECIDED"})
ALLOWED_OBS_STATUSES = frozenset(
    {
        "VALID_PASS",
        "MEASURED_REJECTION",
        "VALID_UNDECIDED",
        "CANDIDATE_ERROR",
        "INSTRUMENT_ERROR",
        "INFRA_ERROR",
        "PENDING_REVALIDATION",
        "SUPERSEDED_REVALIDATED",
        "INCOMPATIBLE",
    }
)
ALLOWED_WORKS_TICKET_TYPES = frozenset(
    {"INSTRUMENT_ERROR", "PAIN_POINT", "DUPLICATE_TOOL", "EXPLOIT", "DISCRIMINATOR"}
)
ALLOWED_TICKET_RESOLUTIONS = frozenset({"RESOLVED", "WONTFIX", "DUPLICATE"})

# ============================================================================
# 后勤工程与单分支接力枚举
# ============================================================================
ALLOWED_NODE_STATUSES = frozenset(
    {"EXPLORING", "AWAITING_TRIAGE", "PENDING_REVIEW", "ACTIVE_REVISING", "BLOCKED_L4B", "SEALED", "CLOSED", "RETIRED"}
)
ALLOWED_BRANCH_KINDS = frozenset({"PURE", "PROTECTED", "SYNTHESIS", "HUMAN_SEEDED"})
ALLOWED_NODE_CONTROL_STATES = frozenset(
    {"AUTO_RUNNING", "PAUSE_DRAINING", "HUMAN_ACTIVE", "EARLY_HANDOFF_READY", "HIBERNATED", "DRAIN_AFTER_TURN", "DRAIN_AFTER_HANDOFF"}
)
ALLOWED_EVIDENCE_GRADES = frozenset({"NONE", "ARTIFACT_ONLY", "MEASURED"})
ALLOWED_DEAD_END_CATEGORIES = frozenset({"SCIENTIFIC_REFUTATION", "IMPL_FAILURE", "ENV_FAILURE"})
ALLOWED_COMPANION_MODES = frozenset({"PRE_SPAWN", "REFLECT_37", "HANDOFF_70", "CRASH_RECOVERY", "CONFERENCE_PARTICIPANT"})
ALLOWED_VERDICT_3STATE = frozenset({"SUFFICIENT_EVIDENCE", "MINIMAL_EXPERIMENT_NEXT", "NEED_CONTROL_GROUP"})
ALLOWED_TRIAGE_LEVELS = frozenset({"ROUTINE_CONTINUATION", "LEVEL_1", "LEVEL_2", "LEVEL_3", "LEVEL_4A", "LEVEL_4B"})
ALLOWED_TRIAGE_ACTIONS = frozenset(
    {"CONTINUE", "SUBMIT_BLIND_REVIEW", "INPLACE_REPAIR", "SPAWN_PROTECTED", "SEAL_BARRIER", "PAUSE_TO_READY_QUEUE"}
)
ALLOWED_FORK_MODES = frozenset({"orthogonal", "lateral", "cross_pollinate", "synthesis", "human_seeded"})
ALLOWED_LEMMA_GAP_STATUSES = frozenset({"OPEN", "FULFILLED", "CANCELLED"})

# ============================================================================
# 图书馆工程、盲审与宏观大外环枚举
# ============================================================================
ALLOWED_READ_DEPTHS = frozenset({"full_text", "specified_sections", "abstract_only"})
ALLOWED_SUPPORT_SCOPES = frozenset(
    {
        "DIRECT_PROOF_OR_EXACT_MEASUREMENT",
        "CONDITIONALLY_VERIFIED",
        "NEGATIVE_REFUTATION",
        "HEURISTIC_CORRELATION",
        "BACKGROUND_REFERENCE",
    }
)
ALLOWED_SURVEY_OUTCOMES = frozenset({"CARD_PUBLISHED", "UNAVAILABLE_REPORT"})
ALLOWED_SURVEY_STATUSES = frozenset({"PENDING", "FULFILLED", "CLOSED_UNAVAILABLE"})
ALLOWED_L3_ENTRY_KINDS = frozenset({"POS_THEOREM", "NEG_COUNTEREXAMPLE", "BARRIER_PROOF"})
ALLOWED_GOAL_COVERAGES = frozenset({"FULL_GOAL", "PARTIAL_OR_LEMMA", "EQUIVALENT_REDUCTION"})
ALLOWED_PUBLISH_TIERS = frozenset({"BASELINE_UPDATE", "VERIFIED_INCREMENTAL"})
ALLOWED_L2_CATEGORIES = frozenset({"REFUTED", "UNRESOLVED_OBJECTION"})
ALLOWED_REVIEW_SOURCE_TYPES = frozenset(
    {"LEVEL1_MANUSCRIPT", "LEVEL4A_BARRIER", "AUDITOR_SALVAGED_LEMMA", "LOCAL_LEMMA_SUBMISSION"}
)
# 裁决 3：Stage 1 新增 PARTIAL_PASS，用于主结论击穿但含已验真局部引理时直通 Stage 2 降级收编
ALLOWED_STAGE1_VERDICTS = frozenset({"PASS", "PARTIAL_PASS", "REVISE", "REFUTED"})
ALLOWED_FINAL_VERDICTS = frozenset({"ACCEPT", "ACCEPT_NARROWED", "REVISE", "REFUTED"})
ALLOWED_CLAIMED_EDGE_TYPES = frozenset({"REQUIRED_PREMISE", "INDEPENDENT_SUPPORT", "MOTIVATING_REF"})
ALLOWED_FACT_EDGE_TYPES = frozenset({"READ", "RETRIEVED", "USED_TOOL"})
ALLOWED_WAVE_STATUSES = frozenset(
    {
        "ASSEMBLING",
        "ROUND_1_CRITIQUE",
        "ROUND_2_REBUTTAL",
        "SURVEY_REFRESHING",
        "ADJUDICATING",
        "PENDING_HUMAN_APPROVAL",
        "COMPLETED",
        "CANCELLED",
        "EXPIRED",
        "FAILED",
    }
)
ALLOWED_WAVE_VERDICT_ACTIONS = frozenset(
    {"OPEN_NEW_BRANCH", "PROTECT", "SPAWN_SYNTHESIS", "HIBERNATE", "DISCRIMINATOR", "PAUSE_FOR_HUMAN"}
)

# ============================================================================
# 设施工程、子题停工锁与 Super-agent 人机协同枚举
# ============================================================================
ALLOWED_AUTONOMY_MODES = frozenset({"WAVE_CONFIRM", "AUTOPILOT"})
ALLOWED_SUBPROBLEM_DESIRED_STATES = frozenset({"ACTIVE", "PAUSED", "CLOSED"})
ALLOWED_SUBPROBLEM_DISPATCH_STATES = frozenset(
    {
        "DISPATCHING",
        "STOPPED_SOLVED",
        "PAUSED_SATURATED",
        "PAUSED_HUMAN",
        "PAUSED_BLOCKED",
        "CLOSED",
    }
)
ALLOWED_METRIC_DIRECTIONS = frozenset({"HIGHER_BETTER", "LOWER_BETTER", "QUALITATIVE"})
ALLOWED_INTERVENTION_ACTIONS = frozenset(
    {
        "PAUSE_REQUESTED",
        "CONTROL_YIELDED",
        "HUMAN_CHAT_DETECTED",
        "CODE_RECONCILED",
        "RESUME_REQUESTED",
        "EARLY_HANDOFF_AUTHORIZED", "ADVISOR_NOTE_SENT", "NODE_HIBERNATED", "NODE_RETIRED", "NODE_REACTIVATED",
    }
)
ALLOWED_INTERVENTION_ACTORS = frozenset({"human_ui", "control_plane", "chief_approved", "chief_direct"})
ALLOWED_RUNTIME_EFFECT_KINDS = frozenset(
    {
        "SPAWN_PAIR",
        "DRAIN_AND_STOP_NODE",
        "CANCEL_NODE_SESSION",
        "WAKE_BLOCKED_BRANCH",
        "REFRESH_LIVING_SURVEY",
        "RUN_WAVE_CONFERENCE",
        "NOTIFY_POLICY_CHANGED",
        "NOTIFY_CHIEF",
        "DELIVER_BRANCH_NOTE",
        "DELIVER_HANDBACK_RECEIPT",
    }
)
ALLOWED_RUNTIME_EFFECT_TARGETS = frozenset({"NODE", "QUESTION", "PROJECT"})
ALLOWED_RUNTIME_EFFECT_STATUSES = frozenset({"PENDING", "RUNNING", "DONE", "CANCELLED", "FAILED"})
ALLOWED_PROPOSAL_ACTIONS = frozenset(
    {
        "SET_SUBPROBLEM_STATE",
        "AUTHORIZE_EARLY_HANDOFF",
        "AMEND_RULING_DRAFT",
        "AUTHORIZE_PARTIAL_DELIVERY",
        "APPROVE_WAVE_VERDICT",
        "SEED_HUMAN_BRANCH",
        "SUBMIT_WORKS_OR_SURVEY_TICKET",
        "SET_AUTONOMY_MODE",
        "ADVANCE_EPOCH",
    }
)
ALLOWED_PROPOSAL_STATUSES = frozenset(
    {"PENDING_HUMAN", "APPROVED_EXECUTED", "REJECTED", "EXPIRED", "SUPERSEDED"}
)
ALLOWED_DISPATCH_POLICIES = frozenset({"NORMAL", "NO_NEW_DISPATCH", "PAUSED_ALL"})
ALLOWED_DRAIN_MODES = frozenset({"FINISH_CURRENT_TURN", "FINISH_CURRENT_HANDOFF", "IMMEDIATE_YIELD"})
ALLOWED_OPERATION_STATUSES = frozenset({"SETTLED", "DRAINING", "PARTIAL_FAILED", "SUPERSEDED"})
ALLOWED_DELIVERY_MODES = frozenset({"FULL", "PARTIAL_ON_BUDGET", "PARTIAL_ON_HUMAN_STOP"})
ALLOWED_COMPLIANCE_STAGES = frozenset({"PARSE0_GATE", "AMBIGUOUS_SPEC_ALERT", "CLOSURE_GATE"})
ALLOWED_COMPLIANCE_STATUSES = frozenset({"PASSED", "ALERT_AMBIGUOUS_SPEC", "ALERT", "BLOCKED"})
