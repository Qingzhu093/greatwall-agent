"""GreatWall v0.3 supervisory_committee（监察委员会）4 个超然只读/合规窄工具。

v0.3 收口（裁决 3）：
- 正式退役 `v0.2` 周期性 `STAGE2_HEARTBEAT` 巡检会话（由 `gw_chief` 与确定性规则告警承接）；
- 取消 Stage 3 冗余二次放行（Stage 3 终签由 `library_verifier` 对不可变冻结包验证后一步原子结项）；
- 聚焦 Stage 1 `PARSE0_GATE` 立项放行与中途 `AMBIGUOUS_SPEC_ALERT` 口径歧义裁决。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from .control_plane_service import (
    check_stage2_closure_gate_data,
    compute_family_concentration_alerts,
    compute_topology_and_revision_health,
)
from .db_schema import (
    ALLOWED_COMPLIANCE_STAGES,
    ALLOWED_COMPLIANCE_STATUSES,
    ERR_AUTH,
    ERR_INVALID_INPUT,
    ERR_LOCKED,
    FailClosedError,
    rw_immediate_tx,
    utc_now_iso,
)
from .mcp_core_helpers import (
    _SQL_WRITE_FORBIDDEN_RE,
    build_tool_receipt,
    enforce_role_tool_permission,
)


def tool_get_supervisory_audit_snapshot(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
) -> dict[str, Any]:
    """纯只读 (<50ms) 返回 Parse 0 契约、各子题口径状态、仪器熔断与合规告警快照。"""
    enforce_role_tool_permission(conn, caller_role, "get_supervisory_audit_snapshot", session_id=session_id)

    p0 = conn.execute("SELECT * FROM parse0_contract WHERE contract_id = 'active'").fetchone()
    closure_row = conn.execute("SELECT * FROM project_closure_state WHERE id = 1").fetchone()
    subproblems = [
        dict(r)
        for r in conn.execute(
            "SELECT question_id, desired_state, dispatch_state, active_spec_revision, solved_entry_id, block_reason_code FROM subproblem_runtime_state ORDER BY question_id"
        ).fetchall()
    ]
    unhealthy = [
        dict(r)
        for r in conn.execute(
            "SELECT instrument_id, version, question_id, instrument_role, consecutive_error_count FROM instruments WHERE is_active = 1 AND health_status = 'UNHEALTHY'"
        ).fetchall()
    ]
    ambiguous_alerts = [
        dict(r)
        for r in conn.execute(
            "SELECT alert_id, stage, notes, created_at FROM compliance_alerts WHERE status = 'ALERT_AMBIGUOUS_SPEC' ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
    ]
    recent_checks = [
        dict(r)
        for r in conn.execute("SELECT * FROM compliance_alerts ORDER BY created_at DESC LIMIT 15").fetchall()
    ]
    conc_alerts = compute_family_concentration_alerts(conn)
    gate_full = check_stage2_closure_gate_data(conn, mode="FULL", human_aborted=False)
    topology_health = compute_topology_and_revision_health(conn, question_filter="ALL")

    watchdog_anomalies: list[dict[str, Any]] = []
    if topology_health.get("orphaned_blind_review_revisions"):
        watchdog_anomalies.append(
            {
                "anomaly_type": "ORPHANED_BLIND_REVIEW_REVISION",
                "count": len(topology_health["orphaned_blind_review_revisions"]),
                "items": topology_health["orphaned_blind_review_revisions"],
            }
        )
    if topology_health.get("understaffed_questions"):
        watchdog_anomalies.append(
            {
                "anomaly_type": "SINGLE_BRANCH_DEGENERATION_OR_UNDERSTAFFED_FAMILIES",
                "count": len(topology_health["understaffed_questions"]),
                "items": topology_health["understaffed_questions"],
            }
        )
    guidance = (
        "检测到拓扑或孤儿返工异常，请按需调 record_compliance_check(status='ALERT') 或提请 gw-chief 协调修复。"
        if watchdog_anomalies
        else "纯只读快照已就绪；请聚焦 Stage 1 PARSE0_GATE 立项审核或中途口径歧义 AMBIGUOUS_SPEC_ALERT 裁决（零 .md 落盘）。"
    )

    return build_tool_receipt(
        conn=conn,
        tool_name="get_supervisory_audit_snapshot",
        question_id="ALL",
        next_step_guidance=guidance,
        data={
            "parse0_signed": bool(p0 and str(p0["human_signed_at"] or "").strip()),
            "stage": str(p0["stage"]) if p0 else "STAGE1_PARSE0",
            "latest_spec_revision": int(p0["latest_spec_revision"] or 0) if p0 else 0,
            "latest_ruling_summary_md": str(p0["latest_ruling_summary_md"] or "") if p0 else "",
            "subproblem_runtime_state": subproblems,
            "unhealthy_instruments": unhealthy,
            "ambiguous_spec_alerts": ambiguous_alerts,
            "family_concentration_alerts": conc_alerts,
            "topology_and_slot_health": topology_health,
            "watchdog_anomalies": watchdog_anomalies,
            "project_closure_state": dict(closure_row) if closure_row else {},
            "closure_gate_full": gate_full,
            "recent_compliance_alerts": recent_checks,
        },
    )


def tool_check_stage2_closure_gate(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    mode: str = "FULL",
    human_aborted: bool = False,
) -> dict[str, Any]:
    """校验各子题当前生效口径下的结项门禁（FULL / PARTIAL_ON_BUDGET / PARTIAL_ON_HUMAN_STOP）。"""
    enforce_role_tool_permission(conn, caller_role, "check_stage2_closure_gate", session_id=session_id)
    gate = check_stage2_closure_gate_data(conn, mode=mode, human_aborted=bool(human_aborted))
    guidance = (
        f"终局门禁已放行 ({gate['gate_code']})，可通知 library_chronicler 导出并冻结 Stage 3 五件套，交由 library_verifier 一步终签。"
        if gate["closure_allowed"]
        else f"终局门禁暂未放行 ({gate['gate_code']})。"
    )
    return build_tool_receipt(
        conn=conn,
        tool_name="check_stage2_closure_gate",
        question_id="ALL",
        next_step_guidance=guidance,
        data=gate,
    )


def tool_record_compliance_check(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    stage: str,
    status: str,
    blocking_questions: list[str] | None = None,
    notes: str = "",
    workspace_root: str = "",
) -> dict[str, Any]:
    """写入 SQLite compliance_alerts（聚焦 PARSE0_GATE 立项放行与 AMBIGUOUS_SPEC_ALERT 口径歧义告警）。"""
    enforce_role_tool_permission(conn, caller_role, "record_compliance_check", session_id=session_id)
    st_u = str(stage or "").strip().upper()
    stat_u = str(status or "").strip().upper()
    if st_u not in ALLOWED_COMPLIANCE_STAGES:
        raise FailClosedError(ERR_INVALID_INPUT, f"非法 stage={stage!r}，仅允许 {sorted(ALLOWED_COMPLIANCE_STAGES)}")
    if stat_u not in ALLOWED_COMPLIANCE_STATUSES:
        raise FailClosedError(ERR_INVALID_INPUT, f"非法 status={status!r}，仅允许 {sorted(ALLOWED_COMPLIANCE_STATUSES)}")
    if st_u == "CLOSURE_GATE":
        raise FailClosedError(
            ERR_LOCKED,
            "v0.3 裁决 3 已取消 supervisory_committee 二次 CLOSURE_GATE 放行：Stage 3 终签由 library_verifier 核查外部冻结包后一步原子结项。",
        )

    now = utc_now_iso()
    alert_id = f"ca_{uuid.uuid4().hex[:10]}"

    if st_u == "PARSE0_GATE" and stat_u == "PASSED":
        with rw_immediate_tx(conn):
            p0 = conn.execute("SELECT * FROM parse0_contract WHERE contract_id = 'active'").fetchone()
            if p0 is None or not str(p0["human_signed_at"] or "").strip() or not str(p0["goal_and_completion_md"] or "").strip():
                raise FailClosedError(ERR_LOCKED, "PARSE0_GATE 阻断：尚未签署包含非空目标与完成判据的 Parse 0 启动表单")
            try:
                declared_insts = json.loads(p0["initial_instruments_json"] or "[]")
            except Exception:
                declared_insts = []
            if declared_insts:
                if int(p0["stage1_works_checked"] or 0) != 1:
                    raise FailClosedError(
                        ERR_LOCKED,
                        "PARSE0_GATE 阻断：Parse 0 声明了初始科研仪器，须待 works_engineer 完成注册并落标 stage1_works_checked=1 后方可放行！",
                    )
                active_ids = {
                    str(r["instrument_id"]).strip().lower()
                    for r in conn.execute("SELECT instrument_id FROM instruments WHERE is_active = 1").fetchall()
                }
                missing_ids = []
                for item in declared_insts:
                    raw_id = str((item.get("instrument_id") or item.get("id") or "") if isinstance(item, dict) else item).strip().lower()
                    if not raw_id:
                        continue
                    cands = {raw_id, f"inst_{raw_id}", raw_id[5:] if raw_id.startswith("inst_") else raw_id}
                    if not (cands & active_ids):
                        missing_ids.append(raw_id)
                if missing_ids:
                    raise FailClosedError(
                        ERR_LOCKED,
                        f"PARSE0_GATE 阻断：以下声明的初始仪器尚未激活就绪，严禁提前进入 Stage 2: {missing_ids}",
                    )
            conn.execute(
                "UPDATE parse0_contract SET stage = 'STAGE2_EVOLVE', updated_at = ? WHERE contract_id = 'active'",
                (now,),
            )
            conn.execute(
                "INSERT INTO compliance_alerts(alert_id, stage, status, blocking_questions_json, notes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (alert_id, st_u, stat_u, json.dumps([str(q) for q in (blocking_questions or [])], ensure_ascii=False), str(notes or "").strip(), now),
            )
    else:
        with rw_immediate_tx(conn):
            conn.execute(
                "INSERT INTO compliance_alerts(alert_id, stage, status, blocking_questions_json, notes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (alert_id, st_u, stat_u, json.dumps([str(q) for q in (blocking_questions or [])], ensure_ascii=False), str(notes or "").strip(), now),
            )

    guidance = (
        "已写入 ALERT_AMBIGUOUS_SPEC 口径红灯告警留待人类经 gw-chief 确认修订；无人值守总线继续按原已签口径运行不停机。"
        if stat_u == "ALERT_AMBIGUOUS_SPEC"
        else f"合规记录 {alert_id} ({st_u}={stat_u}) 已写入 SQLite。"
    )
    return build_tool_receipt(
        conn=conn,
        tool_name="record_compliance_check",
        question_id="ALL",
        next_step_guidance=guidance,
        data={"alert_id": alert_id, "stage": st_u, "status": stat_u},
    )


def tool_register_saved_graph_query(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    query_name: str,
    description: str,
    sql_select: str,
) -> dict[str, Any]:
    """单条只读 SELECT + EXPLAIN QUERY PLAN 预检后注册共享只读图视图。"""
    enforce_role_tool_permission(conn, caller_role, "register_saved_graph_query", session_id=session_id)
    qn = str(query_name or "").strip()
    sql = str(sql_select or "").strip()
    if not qn or not sql:
        raise FailClosedError(ERR_INVALID_INPUT, "query_name 与 sql_select 不能为空")
    if _SQL_WRITE_FORBIDDEN_RE.search(sql) or ";" in sql.rstrip(";") or not sql.upper().startswith("SELECT"):
        raise FailClosedError(ERR_AUTH, "仅允许单条只读 SELECT 语句，严禁写子句或多语句注入")

    try:
        conn.execute(f"EXPLAIN QUERY PLAN {sql}").fetchall()
    except sqlite3.DatabaseError as exc:
        raise FailClosedError(ERR_INVALID_INPUT, f"SQL EXPLAIN QUERY PLAN 预检失败: {exc}")

    now = utc_now_iso()
    with rw_immediate_tx(conn):
        conn.execute(
            """
            INSERT INTO saved_graph_queries(query_name, description, sql_select, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(query_name) DO UPDATE SET
                description = excluded.description,
                sql_select = excluded.sql_select
            """,
            (qn, str(description or "").strip(), sql, now),
        )
    return build_tool_receipt(
        conn=conn,
        tool_name="register_saved_graph_query",
        question_id="ALL",
        next_step_guidance=f"只读图查询视图 {qn!r} 已通过 EXPLAIN 校验并注册。",
        data={"query_name": qn},
    )
