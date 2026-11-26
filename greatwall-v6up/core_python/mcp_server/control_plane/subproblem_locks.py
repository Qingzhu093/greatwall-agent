"""设施控制面子域：子题级最新口径统一判定与三道停工锁（subproblem_runtime_state）。

核心不变量（裁决 4）：
1. 盲审终审、子题锁一停派、全卷结项门禁三处 100% 共用 `find_latest_spec_full_goal_l3` 与 `get_subproblem_active_spec_revision`；
2. 改 Q1 口径时仅递增 Q1 的 `active_spec_revision`，绝对不连坐 Q2 的已达标状态；
3. 锁一（硬证据通关）随时立刻停派；锁二（语义饱和暂停）严格受最低投入窗约束；锁三（Token/波次硬上限 + 全员阻塞自报）兜底。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from ..db_schema import (
    ALLOWED_SUBPROBLEM_DESIRED_STATES,
    ERR_INVALID_INPUT,
    ERR_NOT_FOUND,
    FailClosedError,
    rw_immediate_tx,
    utc_now_iso,
)
from .effects_outbox import enqueue_runtime_effect


def _parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def get_subproblem_active_spec_revision(conn: sqlite3.Connection, question_id: str) -> int:
    """读取子题当前生效口径版本（优先 subproblem_runtime_state，缺失时回退 parse0_contract.latest_spec_revision）。"""
    row = conn.execute(
        "SELECT active_spec_revision FROM subproblem_runtime_state WHERE question_id = ?",
        (str(question_id),),
    ).fetchone()
    if row is not None:
        return int(row["active_spec_revision"] or 0)
    p0 = conn.execute("SELECT latest_spec_revision FROM parse0_contract WHERE contract_id = 'active'").fetchone()
    return int(p0["latest_spec_revision"] or 0) if p0 is not None else 0


def find_latest_spec_full_goal_l3(
    conn: sqlite3.Connection,
    question_id: str,
    *,
    required_spec_revision: int | None = None,
) -> dict[str, Any] | None:
    """三处共用的唯一判定函数：查询匹配该子题当前生效口径的活跃 FULL_GOAL L3（含全局不可能 BARRIER_PROOF）。"""
    eff_rev = (
        int(required_spec_revision)
        if required_spec_revision is not None
        else get_subproblem_active_spec_revision(conn, question_id)
    )
    row = conn.execute(
        """
        SELECT entry_id, question_id, l3_entry_kind, goal_coverage, publish_tier,
               verified_spec_revision, title, created_at
        FROM internal_research_ledger
        WHERE question_id = ?
          AND ledger_type = 'L3_VERIFIED'
          AND is_active = 1
          AND goal_coverage = 'FULL_GOAL'
          AND verified_spec_revision >= ?
        ORDER BY verified_spec_revision DESC, created_at DESC
        LIMIT 1
        """,
        (str(question_id), eff_rev),
    ).fetchone()
    return dict(row) if row is not None else None


def ensure_subproblem_rows(
    conn: sqlite3.Connection,
    subquestions: list[str],
    *,
    min_commitment_sec: int = 0,
    total_budget: dict[str, Any] | None = None,
    active_spec_revision: int = 0,
    started_at: str = "",
) -> list[str]:
    """确保 Parse 0 声明的每道子题在 subproblem_runtime_state 中均已原子建行。"""
    now = utc_now_iso()
    st = started_at or now
    tb = total_budget if isinstance(total_budget, dict) else {}
    q_budget_map = tb.get("per_question_token_budget") if isinstance(tb.get("per_question_token_budget"), dict) else {}
    default_q_budget = max(
        0,
        int(tb.get("question_token_budget", tb.get("max_tokens_per_subproblem", 0)) or 0),
    )
    default_max_waves = max(
        0,
        int(tb.get("max_waves", tb.get("max_waves_per_subproblem", 0)) or 0),
    )
    drain_grace = max(5, int(tb.get("drain_grace_sec", 60) or 60))

    ensured: list[str] = []
    with rw_immediate_tx(conn):
        for raw_q in subquestions:
            qid = str(raw_q).strip()
            if not qid:
                continue
            q_tok = max(0, int(q_budget_map.get(qid, default_q_budget) or 0))
            conn.execute(
                """
                INSERT OR IGNORE INTO subproblem_runtime_state(
                    question_id, contract_id, desired_state, dispatch_state,
                    active_spec_revision, started_at, min_commitment_sec,
                    question_token_budget, max_waves, drain_grace_sec, updated_at
                ) VALUES (?, 'active', 'ACTIVE', 'DISPATCHING', ?, ?, ?, ?, ?, ?, ?)
                """,
                (qid, int(active_spec_revision), st, max(0, int(min_commitment_sec or 0)), q_tok, default_max_waves, drain_grace, now),
            )
            ensured.append(qid)
    return ensured


def set_subproblem_state(
    conn: sqlite3.Connection,
    *,
    question_id: str,
    desired_state: str,
    actor_source: str = "human_ui",
    reason: str = "",
) -> dict[str, Any]:
    """人类/授权提案幂等切换单道子题 desired_state（ACTIVE / PAUSED / CLOSED）。"""
    qid = str(question_id or "").strip()
    ds = str(desired_state or "").strip().upper()
    if ds not in ALLOWED_SUBPROBLEM_DESIRED_STATES:
        raise FailClosedError(ERR_INVALID_INPUT, f"非法 desired_state={desired_state!r}")

    row = conn.execute("SELECT * FROM subproblem_runtime_state WHERE question_id = ?", (qid,)).fetchone()
    if row is None:
        raise FailClosedError(ERR_NOT_FOUND, f"子题 {qid!r} 尚未在 subproblem_runtime_state 初始化")

    now = utc_now_iso()
    new_gen = int(row["dispatch_generation"] or 1) + 1
    if ds == "CLOSED":
        new_dispatch = "CLOSED"
    elif ds == "PAUSED":
        new_dispatch = "PAUSED_HUMAN"
    else:
        solved = find_latest_spec_full_goal_l3(conn, qid, required_spec_revision=int(row["active_spec_revision"] or 0))
        new_dispatch = "STOPPED_SOLVED" if solved is not None else "DISPATCHING"

    with rw_immediate_tx(conn):
        conn.execute(
            """
            UPDATE subproblem_runtime_state
            SET desired_state = ?,
                dispatch_state = ?,
                dispatch_generation = ?,
                block_reason_code = CASE WHEN ? = 'DISPATCHING' THEN '' ELSE block_reason_code END,
                block_detail_md = CASE WHEN ? = 'DISPATCHING' THEN '' ELSE ? END,
                updated_at = ?
            WHERE question_id = ?
            """,
            (ds, new_dispatch, new_gen, new_dispatch, new_dispatch, str(reason or "")[:600], now, qid),
        )
        if new_dispatch in ("PAUSED_HUMAN", "CLOSED", "STOPPED_SOLVED"):
            # 为该子题所有在跑探索节点入队优雅停工副作用
            active_nodes = conn.execute(
                "SELECT node_id, control_generation FROM lineage_nodes WHERE question_id = ? AND node_status IN ('EXPLORING','ACTIVE_REVISING')",
                (qid,),
            ).fetchall()
            for n in active_nodes:
                enqueue_runtime_effect(
                    conn,
                    effect_key=f"drain:{n['node_id']}:qgen{new_gen}",
                    kind="DRAIN_AND_STOP_NODE",
                    target_type="NODE",
                    target_id=str(n["node_id"]),
                    target_generation=int(n["control_generation"] or 1),
                    payload={"question_id": qid, "reason": f"SUBPROBLEM_{new_dispatch}", "grace_sec": int(row["drain_grace_sec"] or 60)},
                    supersede_older_kinds=("SPAWN_PAIR",),
                )

    return {
        "question_id": qid,
        "desired_state": ds,
        "dispatch_state": new_dispatch,
        "dispatch_generation": new_gen,
        "actor_source": actor_source,
    }


def record_subproblem_tokens(conn: sqlite3.Connection, *, question_id: str, delta_tokens: int) -> dict[str, Any] | None:
    if delta_tokens <= 0:
        return None
    now = utc_now_iso()
    qid = str(question_id)
    with rw_immediate_tx(conn):
        conn.execute(
            """
            UPDATE subproblem_runtime_state
            SET spent_tokens = spent_tokens + ?, updated_at = ?
            WHERE question_id = ?
            """,
            (int(delta_tokens), now, qid),
        )
    # 累计 Token 后立即复核三道停工锁（确保超过 question_token_budget 即刻切 PAUSED_BLOCKED 停派）
    return evaluate_subproblem_locks(conn, question_id=qid)


def evaluate_subproblem_locks(
    conn: sqlite3.Connection,
    *,
    question_id: str | None = None,
    semantic_saturation_requested: bool = False,
    saturation_reason_md: str = "",
) -> dict[str, Any]:
    """独立结算子题三道停工锁并按需投递 DRAIN_AND_STOP_NODE / NOTIFY_CHIEF 副作用。"""
    results: list[dict[str, Any]] = []

    with rw_immediate_tx(conn):
        if question_id:
            rows = conn.execute(
                "SELECT * FROM subproblem_runtime_state WHERE question_id = ?",
                (str(question_id),),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM subproblem_runtime_state ORDER BY question_id ASC").fetchall()
        now = utc_now_iso()
        now_dt = datetime.now(timezone.utc)
        for r in rows:
            qid = str(r["question_id"])
            desired = str(r["desired_state"])
            prev_dispatch = str(r["dispatch_state"])
            active_rev = int(r["active_spec_revision"] or 0)
            new_dispatch = prev_dispatch
            solved_id = r["solved_entry_id"]
            solved_rev = r["solved_at_spec_revision"]
            block_code = str(r["block_reason_code"] or "")
            block_detail = str(r["block_detail_md"] or "")
            notify_reason = ""

            if desired == "CLOSED":
                new_dispatch = "CLOSED"
            elif desired == "PAUSED":
                new_dispatch = "PAUSED_HUMAN"
            else:
                # 锁一：硬证据通关（最新生效口径 FULL_GOAL 解或原题全局不可能 BARRIER_PROOF）随时立刻停派
                solved = find_latest_spec_full_goal_l3(conn, qid, required_spec_revision=active_rev)
                if solved is not None:
                    new_dispatch = "STOPPED_SOLVED"
                    solved_id = str(solved["entry_id"])
                    solved_rev = int(solved["verified_spec_revision"])
                    block_code = ""
                    block_detail = ""
                    if prev_dispatch != "STOPPED_SOLVED":
                        notify_reason = f"SUBPROBLEM_SOLVED:{solved_id}"
                else:
                    # 若因改题升版导致原本 STOPPED_SOLVED 不再匹配最新口径，切回 DISPATCHING
                    if prev_dispatch == "STOPPED_SOLVED":
                        new_dispatch = "DISPATCHING"
                        solved_id = None
                        solved_rev = None

                    # 锁三 A：硬 Token / 硬波次天花板保险丝
                    tok_budget = int(r["question_token_budget"] or 0)
                    spent_tok = int(r["spent_tokens"] or 0)
                    max_waves = int(r["max_waves"] or 0)
                    done_waves = int(r["completed_waves"] or 0)

                    if tok_budget > 0 and spent_tok >= tok_budget:
                        new_dispatch = "PAUSED_BLOCKED"
                        block_code = "TOKEN_BUDGET_EXHAUSTED"
                        block_detail = f"子题 {qid} 已耗 Token ({spent_tok}) 达到上限 ({tok_budget})。"
                        if prev_dispatch != "PAUSED_BLOCKED":
                            notify_reason = "TOKEN_BUDGET_EXHAUSTED"
                    elif max_waves > 0 and done_waves >= max_waves:
                        new_dispatch = "PAUSED_BLOCKED"
                        block_code = "MAX_WAVES_EXHAUSTED"
                        block_detail = f"子题 {qid} 已完成波次 ({done_waves}) 达到硬天花板 ({max_waves})。"
                        if prev_dispatch != "PAUSED_BLOCKED":
                            notify_reason = "MAX_WAVES_EXHAUSTED"
                    else:
                        # 锁三 B：全员阻塞自报（无活枝、无在审、有 BLOCKED_L4B 且无待处理分诊）
                        live_cnt = int(
                            conn.execute(
                                """
                                SELECT COUNT(*) AS cnt FROM lineage_nodes
                                WHERE question_id = ? AND node_status IN ('EXPLORING','ACTIVE_REVISING','AWAITING_TRIAGE','PENDING_REVIEW')
                                """,
                                (qid,),
                            ).fetchone()["cnt"]
                            or 0
                        )
                        blocked_cnt = int(
                            conn.execute(
                                "SELECT COUNT(*) AS cnt FROM lineage_nodes WHERE question_id = ? AND node_status = 'BLOCKED_L4B'",
                                (qid,),
                            ).fetchone()["cnt"]
                            or 0
                        )
                        if live_cnt == 0 and blocked_cnt > 0:
                            new_dispatch = "PAUSED_BLOCKED"
                            block_code = "ALL_BRANCHES_BLOCKED"
                            block_detail = f"子题 {qid} 当前全部 {blocked_cnt} 条分支均因缺引理挂起（BLOCKED_L4B），无任何活枝可派，请人类介入或提供引理线索。"
                            if prev_dispatch != "PAUSED_BLOCKED":
                                notify_reason = "ALL_BRANCHES_BLOCKED"
                        elif semantic_saturation_requested and question_id == qid:
                            # 锁二：大外环语义暂停，严格受最低投入时间窗约束
                            min_sec = int(r["min_commitment_sec"] or 0)
                            start_dt = _parse_iso(str(r["started_at"] or ""))
                            elapsed = (now_dt - start_dt).total_seconds() if start_dt else float(min_sec)
                            if elapsed >= float(min_sec):
                                new_dispatch = "PAUSED_SATURATED"
                                block_code = "EXPLICIT_GAPS_EXHAUSTED"
                                block_detail = saturation_reason_md or "已满最低投入窗且大外环确认明确缺口穷尽，等待人类拍板。"
                                notify_reason = "PAUSED_SATURATED"

            changed = new_dispatch != prev_dispatch or solved_id != r["solved_entry_id"] or block_code != str(r["block_reason_code"] or "")
            new_gen = int(r["dispatch_generation"] or 1) + (1 if new_dispatch != prev_dispatch else 0)
            if changed:
                conn.execute(
                    """
                    UPDATE subproblem_runtime_state
                    SET dispatch_state = ?,
                        solved_entry_id = ?,
                        solved_at_spec_revision = ?,
                        block_reason_code = ?,
                        block_detail_md = ?,
                        dispatch_generation = ?,
                        updated_at = ?
                    WHERE question_id = ?
                    """,
                    (new_dispatch, solved_id, solved_rev, block_code, block_detail, new_gen, now, qid),
                )
            if new_dispatch in ("STOPPED_SOLVED", "PAUSED_SATURATED", "PAUSED_BLOCKED") and prev_dispatch != new_dispatch:
                active_nodes = conn.execute(
                    "SELECT node_id, control_generation FROM lineage_nodes WHERE question_id = ? AND node_status IN ('EXPLORING','ACTIVE_REVISING')",
                    (qid,),
                ).fetchall()
                for n in active_nodes:
                    enqueue_runtime_effect(
                        conn,
                        effect_key=f"drain:{n['node_id']}:lock:{new_dispatch}:g{new_gen}",
                        kind="DRAIN_AND_STOP_NODE",
                        target_type="NODE",
                        target_id=str(n["node_id"]),
                        target_generation=int(n["control_generation"] or 1),
                        payload={"question_id": qid, "reason": new_dispatch, "grace_sec": int(r["drain_grace_sec"] or 60)},
                        supersede_older_kinds=("SPAWN_PAIR",),
                    )
            if notify_reason:
                enqueue_runtime_effect(
                    conn,
                    effect_key=f"chief:{qid}:{notify_reason}:g{new_gen}",
                    kind="NOTIFY_CHIEF",
                    target_type="QUESTION",
                    target_id=qid,
                    target_generation=new_gen,
                    payload={
                        "event_category": "MILESTONE" if new_dispatch == "STOPPED_SOLVED" else "BLOCK_ALERT",
                        "question_id": qid,
                        "dispatch_state": new_dispatch,
                        "reason": notify_reason,
                        "detail": block_detail,
                        "solved_entry_id": solved_id,
                    },
                )

            results.append(
                {
                    "question_id": qid,
                    "desired_state": desired,
                    "prev_dispatch_state": prev_dispatch,
                    "dispatch_state": new_dispatch,
                    "active_spec_revision": active_rev,
                    "solved_entry_id": solved_id,
                    "block_reason_code": block_code,
                    "changed": changed,
                }
            )

    return {"evaluated": results}
