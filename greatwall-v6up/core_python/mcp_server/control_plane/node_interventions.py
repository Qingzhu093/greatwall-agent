"""设施控制面子域：运行中节点人工接管（45% 暂停让权 -> 直连对话/改码 -> SHA-256 对账 -> 恢复/提前交班）。"""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from ...evaluators.isolated_runner import compute_recursive_dir_sha256, sha256_file
from ..db_schema import (
    ALLOWED_INTERVENTION_ACTORS,
    ERR_INVALID_INPUT,
    ERR_LOCKED,
    ERR_NOT_FOUND,
    FailClosedError,
    rw_immediate_tx,
    utc_now_iso,
)
from .effects_outbox import cancel_stale_effects_for_target, enqueue_runtime_effect
from .workspace_sync import safe_resolve_in_worktree


def _compute_live_artifact_hashes(conn: sqlite3.Connection, node: sqlite3.Row) -> dict[str, Any]:
    """实时计算节点候选主文件与 tools/ 目录 SHA-256，并与最近一条有效正式观测收据逐字节比对。"""
    wt_abs = str(node["worktree_abs_path"] or "").strip()
    cand_rel = str(node["candidate_rel_path"] or "").strip()

    curr_cand_sha = ""
    curr_tools_sha = ""
    if wt_abs and Path(wt_abs).is_dir():
        if cand_rel:
            try:
                fp = safe_resolve_in_worktree(wt_abs, cand_rel)
                if fp.is_file():
                    curr_cand_sha = sha256_file(fp)
            except FailClosedError:
                curr_cand_sha = ""
        curr_tools_sha = compute_recursive_dir_sha256(Path(wt_abs) / "tools")

    last_obs = conn.execute(
        """
        SELECT obs_id, candidate_entry_sha256, tools_dir_sha256, obs_status
        FROM observations
        WHERE node_id = ?
          AND obs_status IN ('VALID_PASS', 'MEASURED_REJECTION', 'VALID_UNDECIDED')
        ORDER BY created_at DESC LIMIT 1
        """,
        (str(node["node_id"]),),
    ).fetchone()

    prev_cand_sha = str(last_obs["candidate_entry_sha256"] if last_obs else (node["last_reconciled_candidate_sha256"] or ""))
    prev_tools_sha = str(last_obs["tools_dir_sha256"] if last_obs else (node["last_reconciled_tools_sha256"] or ""))

    dirty = False
    if last_obs is not None:
        if (curr_cand_sha and curr_cand_sha != prev_cand_sha) or (curr_tools_sha and curr_tools_sha != prev_tools_sha):
            dirty = True
    elif prev_cand_sha or prev_tools_sha:
        if curr_cand_sha != prev_cand_sha or curr_tools_sha != prev_tools_sha:
            dirty = True

    return {
        "last_valid_obs_id": str(last_obs["obs_id"]) if last_obs else None,
        "prev_candidate_sha256": prev_cand_sha,
        "curr_candidate_sha256": curr_cand_sha,
        "prev_tools_sha256": prev_tools_sha,
        "curr_tools_sha256": curr_tools_sha,
        "artifact_dirty": dirty,
    }


def _insert_intervention(
    conn: sqlite3.Connection,
    *,
    node_id: str,
    question_id: str,
    action: str,
    actor_source: str,
    hashes: dict[str, Any] | None = None,
    cross_branch_note: str = "",
    details: dict[str, Any] | None = None,
    now: str,
) -> str:
    iid = f"intv_{uuid.uuid4().hex[:10]}"
    h = hashes or {}
    actor = actor_source if actor_source in ALLOWED_INTERVENTION_ACTORS else "control_plane"
    conn.execute(
        """
        INSERT INTO node_interventions(
            intervention_id, node_id, question_id, action, actor_source,
            prev_candidate_sha256, curr_candidate_sha256,
            prev_tools_sha256, curr_tools_sha256,
            artifact_dirty, cross_branch_note, details_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            iid,
            node_id,
            question_id,
            action,
            actor,
            str(h.get("prev_candidate_sha256") or ""),
            str(h.get("curr_candidate_sha256") or ""),
            str(h.get("prev_tools_sha256") or ""),
            str(h.get("curr_tools_sha256") or ""),
            1 if h.get("artifact_dirty") else 0,
            str(cross_branch_note or "")[:600],
            json.dumps(details or {}, ensure_ascii=False),
            now,
        ),
    )
    return iid


def pause_node(
    conn: sqlite3.Connection,
    *,
    node_id: str,
    actor_source: str = "human_ui",
    reason: str = "HUMAN_PAUSE",
) -> dict[str, Any]:
    """暂停节点：半秒内禁止新自动回合（切 PAUSE_DRAINING，递增 control_generation，取消旧 SPAWN_PAIR）。"""
    node = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (str(node_id),)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
    if str(node["node_status"]) not in ("EXPLORING", "ACTIVE_REVISING"):
        raise FailClosedError(ERR_LOCKED, f"节点 {node_id!r} 状态为 {node['node_status']}，仅在研节点支持暂停接管")

    now = utc_now_iso()
    new_gen = int(node["control_generation"] or 1) + 1
    hashes = _compute_live_artifact_hashes(conn, node)

    with rw_immediate_tx(conn):
        conn.execute(
            """
            UPDATE lineage_nodes
            SET control_state = 'PAUSE_DRAINING',
                control_generation = ?,
                last_reconciled_candidate_sha256 = ?,
                last_reconciled_tools_sha256 = ?,
                updated_at = ?
            WHERE node_id = ?
            """,
            (new_gen, hashes["curr_candidate_sha256"], hashes["curr_tools_sha256"], now, str(node_id)),
        )
        cancel_stale_effects_for_target(
            conn,
            target_type="NODE",
            target_id=str(node_id),
            below_generation=new_gen,
            kinds=("SPAWN_PAIR",),
        )
        iid = _insert_intervention(
            conn,
            node_id=str(node_id),
            question_id=str(node["question_id"]),
            action="PAUSE_REQUESTED",
            actor_source=actor_source,
            hashes=hashes,
            details={"reason": str(reason or "HUMAN_PAUSE"), "control_generation": new_gen},
            now=now,
        )
        enqueue_runtime_effect(
            conn,
            effect_key=f"drain:{node_id}:pause:g{new_gen}",
            kind="DRAIN_AND_STOP_NODE",
            target_type="NODE",
            target_id=str(node_id),
            target_generation=new_gen,
            payload={"reason": "PAUSE_REQUESTED", "keep_session_for_human": True},
            supersede_older_kinds=("SPAWN_PAIR",),
        )

    return {
        "node_id": str(node_id),
        "control_state": "PAUSE_DRAINING",
        "control_generation": new_gen,
        "intervention_id": iid,
    }


def mark_node_yielded(
    conn: sqlite3.Connection,
    *,
    node_id: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """当在途旧回合与后台作业归静默后，正式标注机器已让出操作权（HUMAN_ACTIVE）。"""
    node = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (str(node_id),)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
    now = utc_now_iso()
    with rw_immediate_tx(conn):
        conn.execute(
            "UPDATE lineage_nodes SET control_state = 'HUMAN_ACTIVE', updated_at = ? WHERE node_id = ?",
            (now, str(node_id)),
        )
        iid = _insert_intervention(
            conn,
            node_id=str(node_id),
            question_id=str(node["question_id"]),
            action="CONTROL_YIELDED",
            actor_source="control_plane",
            details={"yielded_at": now, **(details or {})},
            now=now,
        )
    return {"node_id": str(node_id), "control_state": "HUMAN_ACTIVE", "yielded_at": now, "intervention_id": iid}


def record_human_chat_detected(
    conn: sqlite3.Connection,
    *,
    node_id: str,
    session_id: str = "",
    message_preview: str = "",
) -> dict[str, Any]:
    """检测到人类在探索子会话中亲手发言，立即触发对话让权（不与人类抢麦）。"""
    node = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (str(node_id),)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
    now = utc_now_iso()
    new_gen = int(node["control_generation"] or 1) + 1
    with rw_immediate_tx(conn):
        conn.execute(
            """
            UPDATE lineage_nodes
            SET control_state = 'HUMAN_ACTIVE',
                personal_turn_active = 1,
                control_generation = ?,
                updated_at = ?
            WHERE node_id = ?
            """,
            (new_gen, now, str(node_id)),
        )
        iid = _insert_intervention(
            conn,
            node_id=str(node_id),
            question_id=str(node["question_id"]),
            action="HUMAN_CHAT_DETECTED",
            actor_source="control_plane",
            details={"session_id": session_id, "preview": str(message_preview or "")[:200]},
            now=now,
        )
    return {
        "node_id": str(node_id),
        "control_state": "HUMAN_ACTIVE",
        "personal_turn_active": 1,
        "control_generation": new_gen,
        "intervention_id": iid,
    }


def resume_node(
    conn: sqlite3.Connection,
    *,
    node_id: str,
    actor_source: str = "human_ui",
    cross_branch_note: str = "",
) -> dict[str, Any]:
    """人类点击「交还托管」：强制执行候选文件与 tools/ SHA-256 对账，旧观测永久保留，切回 AUTO_RUNNING。"""
    node = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (str(node_id),)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
    if str(node["node_status"]) not in ("EXPLORING", "ACTIVE_REVISING"):
        raise FailClosedError(ERR_LOCKED, f"节点 {node_id!r} 状态为 {node['node_status']}，不可恢复托管")

    now = utc_now_iso()
    hashes = _compute_live_artifact_hashes(conn, node)
    dirty = bool(hashes["artifact_dirty"])
    new_gen = int(node["control_generation"] or 1) + 1

    with rw_immediate_tx(conn):
        conn.execute(
            """
            UPDATE lineage_nodes
            SET control_state = 'AUTO_RUNNING',
                personal_turn_active = 0,
                control_generation = ?,
                human_modified = CASE WHEN ? = 1 THEN 1 ELSE human_modified END,
                artifact_dirty_since_last_obs = CASE WHEN ? = 1 THEN 1 ELSE artifact_dirty_since_last_obs END,
                last_reconciled_candidate_sha256 = ?,
                last_reconciled_tools_sha256 = ?,
                updated_at = ?
            WHERE node_id = ?
            """,
            (
                new_gen,
                1 if dirty else 0,
                1 if dirty else 0,
                hashes["curr_candidate_sha256"],
                hashes["curr_tools_sha256"],
                now,
                str(node_id),
            ),
        )
        _insert_intervention(
            conn,
            node_id=str(node_id),
            question_id=str(node["question_id"]),
            action="CODE_RECONCILED",
            actor_source=actor_source,
            hashes=hashes,
            cross_branch_note=cross_branch_note,
            details={"last_valid_obs_id": hashes["last_valid_obs_id"]},
            now=now,
        )
        iid = _insert_intervention(
            conn,
            node_id=str(node_id),
            question_id=str(node["question_id"]),
            action="RESUME_REQUESTED",
            actor_source=actor_source,
            hashes=hashes,
            cross_branch_note=cross_branch_note,
            details={"control_generation": new_gen, "artifact_dirty": dirty},
            now=now,
        )
        enqueue_runtime_effect(
            conn,
            effect_key=f"spawn:{node_id}:resume:g{new_gen}",
            kind="SPAWN_PAIR",
            target_type="NODE",
            target_id=str(node_id),
            target_generation=new_gen,
            external_handle_id=f"gw-exp-{node_id}",
            payload={
                "question_id": str(node["question_id"]),
                "resumed_after_human": True,
                "artifact_dirty": dirty,
                "cross_branch_note": str(cross_branch_note or "")[:600],
            },
        )

    return {
        "node_id": str(node_id),
        "control_state": "AUTO_RUNNING",
        "control_generation": new_gen,
        "artifact_dirty": dirty,
        "reconcile": hashes,
        "intervention_id": iid,
    }


def authorize_early_handoff(
    conn: sqlite3.Connection,
    *,
    node_id: str,
    actor_source: str = "human_ui",
    reason: str = "HUMAN_EARLY_HANDOFF",
    cross_branch_note: str = "",
) -> dict[str, Any]:
    """人类显式授权未满 70% 的在研节点走标准两步清醒交班（先做 SHA-256 对账，杜绝脏数据混入 A 栏）。"""
    node = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (str(node_id),)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
    if str(node["node_status"]) not in ("EXPLORING", "ACTIVE_REVISING"):
        raise FailClosedError(ERR_LOCKED, f"节点 {node_id!r} 状态为 {node['node_status']}，无法授权提前交班")
    if actor_source not in ("human_ui", "chief_approved"):
        raise FailClosedError(ERR_INVALID_INPUT, "authorize_early_handoff 必须由真实人类授权触发")

    now = utc_now_iso()
    hashes = _compute_live_artifact_hashes(conn, node)
    dirty = bool(hashes["artifact_dirty"])
    new_gen = int(node["control_generation"] or 1) + 1

    with rw_immediate_tx(conn):
        conn.execute(
            """
            UPDATE lineage_nodes
            SET control_state = 'EARLY_HANDOFF_READY',
                personal_turn_active = 0,
                control_generation = ?,
                human_modified = CASE WHEN ? = 1 THEN 1 ELSE human_modified END,
                artifact_dirty_since_last_obs = CASE WHEN ? = 1 THEN 1 ELSE artifact_dirty_since_last_obs END,
                last_reconciled_candidate_sha256 = ?,
                last_reconciled_tools_sha256 = ?,
                updated_at = ?
            WHERE node_id = ?
            """,
            (
                new_gen,
                1 if dirty else 0,
                1 if dirty else 0,
                hashes["curr_candidate_sha256"],
                hashes["curr_tools_sha256"],
                now,
                str(node_id),
            ),
        )
        iid = _insert_intervention(
            conn,
            node_id=str(node_id),
            question_id=str(node["question_id"]),
            action="EARLY_HANDOFF_AUTHORIZED",
            actor_source=actor_source,
            hashes=hashes,
            cross_branch_note=cross_branch_note,
            details={"reason": str(reason or "HUMAN_EARLY_HANDOFF"), "artifact_dirty": dirty},
            now=now,
        )

    return {
        "node_id": str(node_id),
        "control_state": "EARLY_HANDOFF_READY",
        "control_generation": new_gen,
        "artifact_dirty": dirty,
        "reconcile": hashes,
        "intervention_id": iid,
    }
