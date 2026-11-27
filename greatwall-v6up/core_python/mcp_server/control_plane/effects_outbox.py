"""设施控制面子域：事务后宿主副作用队列（runtime_effects Outbox + 租约领单 + 崩溃认领 + 代数收敛）。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from ..db_schema import (
    ALLOWED_RUNTIME_EFFECT_KINDS,
    ALLOWED_RUNTIME_EFFECT_STATUSES,
    ALLOWED_RUNTIME_EFFECT_TARGETS,
    ERR_INVALID_INPUT,
    ERR_NOT_FOUND,
    FailClosedError,
    rw_immediate_tx,
    utc_now_iso,
)


def _iso_plus_seconds(sec: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=max(1, int(sec)))).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def enqueue_runtime_effect(
    conn: sqlite3.Connection,
    *,
    effect_key: str,
    kind: str,
    target_type: str,
    target_id: str,
    target_generation: int = 1,
    external_handle_id: str = "",
    payload: dict[str, Any] | None = None,
    due_at: str = "",
    supersede_older_kinds: tuple[str, ...] = (),
) -> dict[str, Any]:
    """在当前或新开的写事务内幂等插入副作用任务，并按需取消同目标旧代数排队任务。"""
    key = str(effect_key or "").strip()
    kind_u = str(kind or "").strip().upper()
    ttype_u = str(target_type or "").strip().upper()
    tid = str(target_id or "").strip()
    if not key or not tid:
        raise FailClosedError(ERR_INVALID_INPUT, "effect_key 与 target_id 不能为空")
    if kind_u not in ALLOWED_RUNTIME_EFFECT_KINDS:
        raise FailClosedError(ERR_INVALID_INPUT, f"非法副作用 kind={kind!r}")
    if ttype_u not in ALLOWED_RUNTIME_EFFECT_TARGETS:
        raise FailClosedError(ERR_INVALID_INPUT, f"非法副作用 target_type={target_type!r}")

    now = utc_now_iso()
    eff_due = str(due_at or now)
    gen = max(1, int(target_generation or 1))
    payload_str = json.dumps(payload or {}, ensure_ascii=False)

    with rw_immediate_tx(conn):
        existing = conn.execute(
            "SELECT seq, status, target_generation FROM runtime_effects WHERE effect_key = ?",
            (key,),
        ).fetchone()
        if existing is not None:
            return {
                "seq": int(existing["seq"]),
                "effect_key": key,
                "status": str(existing["status"]),
                "idempotent_hit": True,
            }

        cur = conn.execute(
            """
            INSERT INTO runtime_effects(
                effect_key, kind, target_type, target_id, target_generation,
                external_handle_id, payload_json, status, due_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?)
            """,
            (key, kind_u, ttype_u, tid, gen, str(external_handle_id or ""), payload_str, eff_due, now, now),
        )
        new_seq = int(cur.lastrowid)

        if supersede_older_kinds:
            ph = ",".join("?" for _ in supersede_older_kinds)
            conn.execute(
                f"""
                UPDATE runtime_effects
                SET status = 'CANCELLED', superseded_by_seq = ?, updated_at = ?, completed_at = ?
                WHERE target_type = ? AND target_id = ?
                  AND kind IN ({ph})
                  AND status = 'PENDING'
                  AND seq < ?
                  AND target_generation <= ?
                """,
                (new_seq, now, now, ttype_u, tid, *supersede_older_kinds, new_seq, gen),
            )

    return {
        "seq": new_seq,
        "effect_key": key,
        "kind": kind_u,
        "target_type": ttype_u,
        "target_id": tid,
        "target_generation": gen,
        "status": "PENDING",
        "idempotent_hit": False,
    }


def cancel_stale_effects_for_target(
    conn: sqlite3.Connection,
    *,
    target_type: str,
    target_id: str,
    below_generation: int,
    kinds: tuple[str, ...] | None = None,
) -> int:
    """取消指定目标低于最新代数的全部 PENDING 副作用（防并发竞态偷跑）。"""
    now = utc_now_iso()
    ttype_u = str(target_type or "").strip().upper()
    with rw_immediate_tx(conn):
        if kinds:
            ph = ",".join("?" for _ in kinds)
            cur = conn.execute(
                f"""
                UPDATE runtime_effects
                SET status = 'CANCELLED', updated_at = ?, completed_at = ?
                WHERE target_type = ? AND target_id = ? AND status = 'PENDING'
                  AND target_generation < ? AND kind IN ({ph})
                """,
                (now, now, ttype_u, str(target_id), int(below_generation), *kinds),
            )
        else:
            cur = conn.execute(
                """
                UPDATE runtime_effects
                SET status = 'CANCELLED', updated_at = ?, completed_at = ?
                WHERE target_type = ? AND target_id = ? AND status = 'PENDING'
                  AND target_generation < ?
                """,
                (now, now, ttype_u, str(target_id), int(below_generation)),
            )
    return int(cur.rowcount or 0)


def claim_runtime_effects(
    conn: sqlite3.Connection,
    *,
    owner_instance_id: str,
    lease_sec: int = 60,
    limit: int = 16,
    kinds: list[str] | None = None,
) -> dict[str, Any]:
    """原子领取到期 PENDING 或租约已过期（崩溃残留）的 RUNNING 副作用，写入 60s 租约。"""
    owner = str(owner_instance_id or "").strip()
    if not owner:
        raise FailClosedError(ERR_INVALID_INPUT, "owner_instance_id 不能为空")
    max_n = max(1, min(64, int(limit or 16)))
    now = utc_now_iso()
    lease_until = _iso_plus_seconds(lease_sec)

    kind_filter_sql = ""
    kind_params: list[Any] = []
    if kinds:
        valid = [str(k).strip().upper() for k in kinds if str(k).strip().upper() in ALLOWED_RUNTIME_EFFECT_KINDS]
        if valid:
            kind_filter_sql = f"AND kind IN ({','.join('?' for _ in valid)})"
            kind_params.extend(valid)

    claimed: list[dict[str, Any]] = []
    with rw_immediate_tx(conn):
        rows = conn.execute(
            f"""
            SELECT * FROM runtime_effects
            WHERE (
                (status = 'PENDING' AND (due_at = '' OR due_at <= ?))
                OR (status = 'RUNNING' AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?)
            )
            {kind_filter_sql}
            ORDER BY
                CASE kind
                    WHEN 'NOTIFY_CHIEF' THEN 0
                    WHEN 'CANCEL_NODE_SESSION' THEN 1
                    WHEN 'DRAIN_AND_STOP_NODE' THEN 2
                    WHEN 'NOTIFY_POLICY_CHANGED' THEN 3
                    WHEN 'WAKE_BLOCKED_BRANCH' THEN 4
                    ELSE 5
                END,
                seq ASC
            LIMIT ?
            """,
            (now, now, *kind_params, max_n),
        ).fetchall()

        for r in rows:
            seq = int(r["seq"])
            was_expired_running = str(r["status"]) == "RUNNING"
            conn.execute(
                """
                UPDATE runtime_effects
                SET status = 'RUNNING',
                    owner_instance_id = ?,
                    claimed_at = ?,
                    lease_expires_at = ?,
                    attempts = attempts + 1,
                    updated_at = ?
                WHERE seq = ?
                """,
                (owner, now, lease_until, now, seq),
            )
            item = dict(r)
            item["status"] = "RUNNING"
            item["owner_instance_id"] = owner
            item["claimed_at"] = now
            item["lease_expires_at"] = lease_until
            item["attempts"] = int(r["attempts"] or 0) + 1
            item["recovered_from_expired_lease"] = was_expired_running
            try:
                item["payload"] = json.loads(item.get("payload_json") or "{}")
            except Exception:
                item["payload"] = {}
            claimed.append(item)

    return {"owner_instance_id": owner, "claimed": claimed, "count": len(claimed)}


def runtime_effect_is_current(
    conn: sqlite3.Connection, seq: int, effect_key: str, target_generation: int,
) -> bool:
    row = conn.execute(
        """SELECT e.kind,e.target_type,e.status,e.payload_json,n.control_generation,n.question_id
           FROM runtime_effects e LEFT JOIN lineage_nodes n
             ON e.target_type='NODE' AND n.node_id=e.target_id
           WHERE e.seq=? AND e.effect_key=? AND e.target_generation=?""",
        (seq, effect_key, target_generation),
    ).fetchone()
    if row is None or row["status"] != "RUNNING":
        return False
    if row["target_type"] == "NODE" and row["kind"] in ("SPAWN_PAIR", "DRAIN_AND_STOP_NODE", "CANCEL_NODE_SESSION"):
        return row["control_generation"] == target_generation
    if row["kind"] == "NOTIFY_POLICY_CHANGED":
        payload = json.loads(row["payload_json"])
        revision = payload.get("new_spec_revision")
        if revision is not None:
            state = conn.execute("SELECT active_spec_revision FROM subproblem_runtime_state WHERE question_id=?",
                                 (payload.get("question_id") or row["question_id"],)).fetchone()
            return state is not None and state["active_spec_revision"] == revision
    return True


def renew_runtime_effect_lease(
    conn: sqlite3.Connection,
    *,
    seq: int,
    owner_instance_id: str,
    lease_sec: int = 60,
) -> dict[str, Any]:
    now = utc_now_iso()
    lease_until = _iso_plus_seconds(lease_sec)
    with rw_immediate_tx(conn):
        cur = conn.execute(
            """
            UPDATE runtime_effects
            SET lease_expires_at = ?, updated_at = ?
            WHERE seq = ? AND status = 'RUNNING' AND owner_instance_id = ?
            """,
            (lease_until, now, int(seq), str(owner_instance_id)),
        )
    return {"seq": int(seq), "renewed": cur.rowcount == 1, "lease_expires_at": lease_until}


def complete_runtime_effect(
    conn: sqlite3.Connection,
    *,
    seq: int,
    owner_instance_id: str,
    status: str = "DONE",
    last_error: str = "",
    retry_delay_sec: int = 0,
    external_handle_id: str | None = None,
    effect_key: str | None = None,
    target_generation: int | None = None,
    claim_attempt: int | None = None,
) -> dict[str, Any]:
    """标记副作用完成、取消、失败或延迟退避重试（仅允许当前租约持有者结案）。"""
    st_u = str(status or "DONE").strip().upper()
    if st_u not in ALLOWED_RUNTIME_EFFECT_STATUSES:
        raise FailClosedError(ERR_INVALID_INPUT, f"非法副作用状态 {status!r}")
    now = utc_now_iso()

    with rw_immediate_tx(conn):
        row = conn.execute("SELECT * FROM runtime_effects WHERE seq = ?", (int(seq),)).fetchone()
        if row is None:
            raise FailClosedError(ERR_NOT_FOUND, f"runtime_effects seq={seq} 不存在")
        if str(row["status"]) in ("DONE", "CANCELLED"):
            return {"seq": int(seq), "status": str(row["status"]), "idempotent": True}
        if str(row["owner_instance_id"] or "") and str(row["owner_instance_id"]) != str(owner_instance_id):
            return {
                "seq": int(seq),
                "status": str(row["status"]),
                "updated": False,
                "reason": "lease_owner_mismatch",
            }

        if effect_key is not None and (
            row["effect_key"] != effect_key or row["target_generation"] != target_generation
            or row["attempts"] != claim_attempt or row["status"] != "RUNNING"
        ):
            return {"seq": int(seq), "status": str(row["status"]), "updated": False, "reason": "claim_mismatch"}
        if effect_key is not None and not runtime_effect_is_current(conn, seq, effect_key, target_generation):
            st_u = "CANCELLED"

        eff_handle = str(external_handle_id) if external_handle_id is not None else str(row["external_handle_id"] or "")
        if st_u == "PENDING" and retry_delay_sec > 0:
            next_due = _iso_plus_seconds(retry_delay_sec)
            conn.execute(
                """
                UPDATE runtime_effects
                SET status = 'PENDING', owner_instance_id = '', lease_expires_at = NULL,
                    due_at = ?, last_error = ?, external_handle_id = ?, updated_at = ?
                WHERE seq = ?
                """,
                (next_due, str(last_error or "")[:800], eff_handle, now, int(seq)),
            )
        else:
            comp_at = now if st_u in ("DONE", "CANCELLED", "FAILED") else None
            conn.execute(
                """
                UPDATE runtime_effects
                SET status = ?, last_error = ?, external_handle_id = ?,
                    lease_expires_at = NULL, updated_at = ?, completed_at = COALESCE(?, completed_at)
                WHERE seq = ?
                """,
                (st_u, str(last_error or "")[:800], eff_handle, now, comp_at, int(seq)),
            )
    return {"seq": int(seq), "status": st_u, "updated": True}
