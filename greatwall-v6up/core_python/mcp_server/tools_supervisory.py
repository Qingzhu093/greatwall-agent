"""长城 V6-Up (v3.0) supervisory_committee（监察委员会）4 个超然只读/合规窄工具。"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .control_plane_service import (
    check_stage2_closure_gate_data,
    compute_delivery_dir_sha256,
    compute_family_concentration_alerts,
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
    """纯查 SQLite (<50ms) 返回全局流程审计快照：Parse 0、仪器健康、口径红灯、学派聚拢、最短投入时间与两步终局状态。"""
    enforce_role_tool_permission(conn, caller_role, "get_supervisory_audit_snapshot", session_id=session_id)

    p0 = conn.execute("SELECT * FROM parse0_contract WHERE contract_id = 'active'").fetchone()
    closure_row = conn.execute("SELECT * FROM project_closure_state WHERE id = 1").fetchone()
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

    return build_tool_receipt(
        conn=conn,
        tool_name="get_supervisory_audit_snapshot",
        question_id="ALL",
        next_step_guidance="纯只读审计快照已就绪；请严格遵循流程正义与零 .md 落盘原则调用 record_compliance_check 写库。",
        data={
            "parse0_signed": bool(p0 and str(p0["human_signed_at"] or "").strip()),
            "stage": str(p0["stage"]) if p0 else "STAGE1_PARSE0",
            "consecutive_non_l1_handoffs": int(p0["consecutive_non_l1_handoffs"] or 0) if p0 else 0,
            "unhealthy_instruments": unhealthy,
            "ambiguous_spec_alerts": ambiguous_alerts,
            "family_concentration_alerts": conc_alerts,
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
    """CDC 双段式终局门禁校验（FULL / PARTIAL_ON_BUDGET / PARTIAL_ON_HUMAN_STOP）。"""
    enforce_role_tool_permission(conn, caller_role, "check_stage2_closure_gate", session_id=session_id)
    gate = check_stage2_closure_gate_data(conn, mode=mode, human_aborted=bool(human_aborted))
    if not gate["closure_allowed"]:
        guidance = f"终局门禁暂未放行 ({gate['gate_code']})；严禁未满最短投入时间或伪造 human_aborted 提前收工。"
    else:
        guidance = f"终局门禁已放行 ({gate['gate_code']})，可通知 library_surveyor 导出 Stage 3 五件套。"
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
    """写入 SQLite `compliance_alerts`（零 .md 落盘；CLOSURE_GATE(PASSED) 强校验绑定导出版本与磁盘实时哈希防审 A 放 B / 磁盘篡改）。"""
    enforce_role_tool_permission(conn, caller_role, "record_compliance_check", session_id=session_id)
    st_u = str(stage or "").strip().upper()
    stat_u = str(status or "").strip().upper()
    if st_u not in ALLOWED_COMPLIANCE_STAGES:
        raise FailClosedError(ERR_INVALID_INPUT, f"非法 stage={stage!r}，仅允许 {sorted(ALLOWED_COMPLIANCE_STAGES)}")
    if stat_u not in ALLOWED_COMPLIANCE_STATUSES:
        raise FailClosedError(ERR_INVALID_INPUT, f"非法 status={status!r}，仅允许 {sorted(ALLOWED_COMPLIANCE_STATUSES)}")

    now = utc_now_iso()
    p0 = conn.execute("SELECT * FROM parse0_contract WHERE contract_id = 'active'").fetchone()

    if st_u == "PARSE0_GATE" and stat_u == "PASSED":
        if p0 is None or not str(p0["human_signed_at"] or "").strip() or not str(p0["goal_and_completion_md"] or "").strip():
            raise FailClosedError(ERR_LOCKED, "PARSE0_GATE 阻断：尚未签署包含非空目标与完成判据的 Parse 0 六项启动表单")
        with rw_immediate_tx(conn):
            conn.execute(
                "UPDATE parse0_contract SET stage = 'STAGE2_EVOLVE', updated_at = ? WHERE contract_id = 'active'",
                (now,),
            )

    elif st_u == "CLOSURE_GATE" and stat_u == "PASSED":
        closure = conn.execute("SELECT * FROM project_closure_state WHERE id = 1").fetchone()
        if closure is None or str(closure["status"]) != "DELIVERY_EXPORTED":
            raise FailClosedError(
                ERR_LOCKED,
                f"CLOSURE_GATE 硬拦截：当前 project_closure_state={closure['status'] if closure else None!r}，必须先导出五件套至 DELIVERY_EXPORTED",
            )
        latest_did = str(closure["latest_delivery_id"] or "")
        latest_sha = str(closure["latest_delivery_sha256"] or "")
        aud_did = str(closure["verifier_audited_delivery_id"] or "")
        aud_sha = str(closure["verifier_audited_delivery_sha256"] or "")
        aud_pass = int(closure["verifier_final_audit_passed"] or 0)
        if not (aud_pass == 1 and latest_did and aud_did == latest_did and aud_sha == latest_sha):
            raise FailClosedError(
                ERR_LOCKED,
                f"CLOSURE_GATE 版本绑定硬拦截（防审 A 放 B）：盲审终核记录 (passed={aud_pass}, id={aud_did!r}, sha={aud_sha[:10]!r}) "
                f"与当前最新导出版本 (id={latest_did!r}, sha={latest_sha[:10]!r}) 不匹配！请先由 library_verifier 完成 STAGE3_FINAL_AUDIT:{latest_did}。",
            )
        # 实时重算磁盘 final_delivery/ 整包 SHA-256，防终核后磁盘文件被篡改或缺失
        if workspace_root:
            delivery_dir = Path(os.path.realpath(workspace_root)) / "final_delivery"
            if not delivery_dir.is_dir():
                raise FailClosedError(ERR_LOCKED, f"CLOSURE_GATE 硬拦截：交付目录 {delivery_dir} 不存在！")
            live_sha = compute_delivery_dir_sha256(delivery_dir)
            if live_sha != latest_sha:
                raise FailClosedError(
                    ERR_LOCKED,
                    f"CLOSURE_GATE 磁盘完整性硬拦截（交付包内容已变化）：磁盘实时 SHA-256 ({live_sha[:12]}) != 审定绑定 SHA-256 ({latest_sha[:12]})，必须重新导出并重走终核！",
                )
        with rw_immediate_tx(conn):
            conn.execute(
                """
                UPDATE project_closure_state
                SET status = 'CLOSED_VERIFIED', supervisory_signed_at = ?, updated_at = ?
                WHERE id = 1
                """,
                (now, now),
            )
            conn.execute(
                "UPDATE parse0_contract SET stage = 'CLOSED_VERIFIED', updated_at = ? WHERE contract_id = 'active'",
                (now,),
            )

    alert_id = f"ca_{uuid.uuid4().hex[:10]}"
    with rw_immediate_tx(conn):
        conn.execute(
            """
            INSERT INTO compliance_alerts(alert_id, stage, status, blocking_questions_json, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                alert_id,
                st_u,
                stat_u,
                json.dumps([str(q) for q in (blocking_questions or [])], ensure_ascii=False),
                str(notes or "").strip(),
                now,
            ),
        )

    guidance = (
        "已写入 ALERT_AMBIGUOUS_SPEC 红灯告警留待人类核查；无人值守总线继续按原已签口径运行不停机。"
        if stat_u == "ALERT_AMBIGUOUS_SPEC"
        else (
            "联合终核版本匹配校验通过，项目已正式晋升为 CLOSED_VERIFIED！"
            if (st_u == "CLOSURE_GATE" and stat_u == "PASSED")
            else f"合规记录 {alert_id} ({st_u}={stat_u}) 已写入 SQLite。"
        )
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
