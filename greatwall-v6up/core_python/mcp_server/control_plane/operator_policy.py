"""Versioned operator policy and common branch admission."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from ..db.enums import ALLOWED_AUTONOMY_MODES, ALLOWED_DISPATCH_POLICIES, ALLOWED_DRAIN_MODES
from ..db_schema import ERR_INVALID_INPUT, ERR_LOCKED, FailClosedError, utc_now_iso
from ..mcp_core_helpers import load_runtime_config


DEFAULT_POLICY = {
    "priority_weight": 100,
    "max_active_branches": 3,
    "dispatch_policy": "NORMAL",
}
DRAIN_BY_POLICY = {"NO_NEW_DISPATCH": "FINISH_CURRENT_TURN", "PAUSED_ALL": "IMMEDIATE_YIELD"}
OCCUPIED_BRANCHES = """
    SELECT DISTINCT n.branch_id FROM lineage_nodes n
    LEFT JOIN operator_runtime_slots s ON s.node_id = n.node_id
    WHERE n.question_id = ? AND (
        s.node_id IS NOT NULL OR (
            n.node_status IN ('EXPLORING','ACTIVE_REVISING','AWAITING_TRIAGE','PENDING_REVIEW')
            AND n.control_state NOT IN ('HIBERNATED','HUMAN_ACTIVE')
        )
    )
"""


def epoch_id(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT epoch_id FROM parse0_contract WHERE contract_id='active'").fetchone()
    return int(row["epoch_id"]) if row else 1


def scoped_to(row: dict[str, Any], question_id: str = "", node_id: str = "") -> bool:
    return (
        row["scope_type"] == "PROJECT"
        or row["scope_type"] == "QUESTION" and bool(question_id) and row["target_id"] == question_id
        or row["scope_type"] == "NODE" and bool(node_id) and row["target_id"] == node_id
    )


def runtime_slots(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(
        """SELECT s.*, n.question_id, n.branch_id, n.node_status, n.control_state
           FROM operator_runtime_slots s JOIN lineage_nodes n ON n.node_id = s.node_id
           ORDER BY s.started_at, s.node_id"""
    )]


def active_arrangements(conn: sqlite3.Connection, *, persist_expiry: bool = False) -> list[dict[str, Any]]:
    now = utc_now_iso()
    live = {row["node_id"] for row in runtime_slots(conn)}
    active = []
    for entry in conn.execute(
        "SELECT * FROM run_arrangements WHERE epoch_id=? AND status='ACTIVE' ORDER BY arrangement_version", (epoch_id(conn),),
    ).fetchall():
        row = dict(entry)
        row["patch"] = json.loads(row.pop("patch_json"))
        row["watch_node_ids"] = json.loads(row.pop("watch_node_ids_json"))
        timed_out = row["ends_on_kind"] == "AT_TIME" and row["expires_at"] <= now
        batch_done = row["ends_on_kind"] == "AFTER_INFLIGHT_BATCH" and not live.intersection(row["watch_node_ids"])
        if timed_out or batch_done:
            if persist_expiry:
                conn.execute(
                    "UPDATE run_arrangements SET status='EXPIRED', updated_at=?, resolved_at=? WHERE arrangement_id=?",
                    (now, now, row["arrangement_id"]),
                )
            continue
        active.append(row)
    return active


def drain_arrangement(arrangements: list[dict], question_id: str, node_id: str) -> tuple[dict | None, str | None]:
    for row in reversed(arrangements):
        if not scoped_to(row, question_id, node_id):
            continue
        patch = row["patch"]
        if "inflight_drain_mode" in patch or "dispatch_policy" in patch:
            return row, patch.get("inflight_drain_mode") or DRAIN_BY_POLICY.get(patch.get("dispatch_policy"))
    return None, None


def effective_policy(
    arrangements: list[dict[str, Any]], question_id: str = "", node_id: str = "",
    *, base: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {key: (base or {}).get(key, default) for key, default in DEFAULT_POLICY.items()}
    for row in arrangements:
        if scoped_to(row, question_id, node_id):
            result.update(row["patch"])
    return result


def worker_slot_cap(policy: dict, requested: int | None = None) -> int:
    config = load_runtime_config()
    wanted = policy.get("max_concurrent_workers", requested or config["max_concurrent_workers"])
    return max(1, min(config["max_concurrent_workers_hard_cap"], int(wanted)))


def check_question_branch_quota(
    conn: sqlite3.Connection, question_id: str, *, family_id: str = "",
    replacing_branch_id: str = "", human_named: bool = False,
) -> dict[str, Any]:
    state = conn.execute("SELECT * FROM subproblem_runtime_state WHERE question_id=?", (question_id,)).fetchone()
    policy = effective_policy(active_arrangements(conn), question_id, base=dict(state) if state else None)
    if state and state["dispatch_state"] != "DISPATCHING" and state["block_reason_code"] != "ALL_BRANCHES_BLOCKED":
        raise FailClosedError(ERR_LOCKED, f"{question_id} 当前由 {state['dispatch_state']} 锁定")
    if conn.execute("SELECT 1 FROM project_closure_state WHERE id=1 AND human_stop_requested_at IS NOT NULL").fetchone():
        raise FailClosedError(ERR_LOCKED, "全院已收工，不能派发新分支")
    if policy["dispatch_policy"] != "NORMAL":
        if not (human_named and policy["dispatch_policy"] == "NO_NEW_DISPATCH"):
            raise FailClosedError(ERR_LOCKED, f"{question_id} 当前派发策略为 {policy['dispatch_policy']}")
    if family_id and conn.execute(
        "SELECT 1 FROM method_families WHERE family_id=? AND family_status='ARCHIVED'", (family_id,),
    ).fetchone():
        raise FailClosedError(ERR_LOCKED, f"学派 {family_id} 已归档，请先显式恢复")
    branches = {row["branch_id"] for row in conn.execute(OCCUPIED_BRANCHES, (question_id,))}
    if len(branches - {replacing_branch_id}) >= policy["max_active_branches"]:
        raise FailClosedError(ERR_LOCKED, f"{question_id} 活跃分支已达到上限 {policy['max_active_branches']}")
    return policy


def validate_arrangement(arrangement: dict[str, Any]) -> tuple[str, str, dict[str, Any], str, str | None]:
    scope = str(arrangement.get("scope_type") or "").upper()
    target = str(arrangement.get("target_id") or "").strip()
    if scope not in ("PROJECT", "QUESTION", "NODE") or not target or (scope == "PROJECT" and target != "ALL"):
        raise FailClosedError(ERR_INVALID_INPUT, "运行安排需要有效的 scope_type 与 target_id")
    limits = {"priority_weight": (-10000, 10000), "max_active_branches": (1, 100),
              "max_concurrent_workers": (1, load_runtime_config()["max_concurrent_workers_hard_cap"])}
    choices = {
        "dispatch_policy": ALLOWED_DISPATCH_POLICIES,
        "inflight_drain_mode": ALLOWED_DRAIN_MODES,
        "autonomy_mode": ALLOWED_AUTONOMY_MODES,
    }
    patch = {key: arrangement[key] for key in limits.keys() | choices.keys() if arrangement.get(key) is not None}
    if not patch:
        raise FailClosedError(ERR_INVALID_INPUT, "运行安排至少需要一个调度字段")
    for key, value in patch.items():
        if key in limits and (type(value) is not int or not limits[key][0] <= value <= limits[key][1]):
            raise FailClosedError(ERR_INVALID_INPUT, f"{key} 超出范围 {limits[key]}")
        if key in choices and value not in choices[key]:
            raise FailClosedError(ERR_INVALID_INPUT, f"{key} 不支持 {value!r}")
    if scope != "PROJECT" and patch.keys() & {"max_concurrent_workers", "autonomy_mode"}:
        raise FailClosedError(ERR_INVALID_INPUT, "全局并发与自动化模式需要 PROJECT 范围")
    if scope == "NODE" and patch.keys() & {"priority_weight", "max_active_branches"}:
        raise FailClosedError(ERR_INVALID_INPUT, "子题优先级与分支上限需要 PROJECT 或 QUESTION 范围")
    ends = str(arrangement.get("ends_on_kind") or "MANUAL").upper()
    if ends not in ("MANUAL", "AT_TIME", "AFTER_INFLIGHT_BATCH"):
        raise FailClosedError(ERR_INVALID_INPUT, "不支持的安排到期类型")
    expires = None
    if ends == "AT_TIME":
        try:
            at = datetime.fromisoformat(str(arrangement.get("expires_at") or "").replace("Z", "+00:00"))
            if at.utcoffset() is None:
                raise ValueError("timezone required")
            expires = at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            if expires <= utc_now_iso():
                raise ValueError("expiry must be in the future")
        except ValueError as exc:
            raise FailClosedError(ERR_INVALID_INPUT, "expires_at 需要带时区且晚于当前时间") from exc
    return scope, target, patch, ends, expires

