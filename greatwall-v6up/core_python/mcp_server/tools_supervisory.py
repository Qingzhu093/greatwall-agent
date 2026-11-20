"""V6-Up (v2.2) supervisory_committee（监察委员会）4 个超然只读零公文窄工具。"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import tempfile
import uuid
from pathlib import Path
from typing import Any

from evaluators.isolated_runner import (
    run_stage_b_revaluation,
    sha256_file,
)
from .control_plane_service import (
    backup_retained_candidate_snapshot,
    check_stage2_closure_gate_data,
    export_stage3_deliverables,
    get_question_dependency_status,
    restore_retained_candidate_snapshot,
)
from .db_schema import (
    ALLOWED_CLAIMED_EDGE_TYPES,
    ALLOWED_READ_DEPTHS,
    ALLOWED_SUPPORT_SCOPES,
    ERR_AUTH,
    ERR_CONFLICT,
    ERR_INVALID_INPUT,
    ERR_INVARIANT,
    ERR_LOCKED,
    ERR_NOT_FOUND,
    FailClosedError,
    propagate_dependency_recheck,
    resolve_storage_paths,
    rw_immediate_tx,
    utc_now_iso,
)
from .mcp_core_helpers import (
    VALID_FORK_MODES,
    VALID_STAGNATION_LANES,
    build_tool_receipt,
    check_mechanism_similarity,
    compute_adversarial_qp,
    compute_bb_epsilon,
    core_python_root,
    enforce_role_tool_permission,
    load_runtime_config,
    record_fact_edge,
    validate_baseline_isolation_ast,
)
from .governance_common import (
    _SQL_WRITE_FORBIDDEN_RE,
    _audit_node_unread_citations,
    _collect_proposer_sessions,
    _extract_referenced_cards_for_blind_review,
    _next_id,
    _next_ledger_id,
    _parse_proposer_sessions,
    _require_reviewer_session,
)

# ==============================================================================
# 角色 7：supervisory_committee（4 个超然只读零公文窄工具）
# ==============================================================================


def tool_get_supervisory_audit_snapshot(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "get_supervisory_audit_snapshot", session_id=session_id)
    hooks = [dict(r) for r in conn.execute("SELECT question_id, fidelity_max_error_pct, eval_epoch_version FROM domain_hooks_by_question").fetchall()]
    ep = conn.execute("SELECT consecutive_non_l1_handoffs, required_questions_json FROM epoch_config WHERE config_id = 'active'").fetchone()
    non_l1 = int(ep["consecutive_non_l1_handoffs"]) if ep else 0

    all_nodes = conn.execute("SELECT node_id FROM lineage_nodes").fetchall()
    unread_nodes: list[dict[str, Any]] = []
    for nr in all_nodes:
        nid = str(nr["node_id"])
        rec = _audit_node_unread_citations(conn, nid)
        if rec["unread_claimed_refs"]:
            unread_nodes.append({"node_id": nid, "unread_refs": rec["unread_claimed_refs"]})

    unauth_attempts = [
        dict(r)
        for r in conn.execute(
            "SELECT src_id, dst_id, metadata_json, created_at FROM epistemic_edges WHERE edge_track = 'FACT_LOG' AND edge_type = 'UNAUTHORIZED_TOOL_ATTEMPT' ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
    ]
    reval_backlog = int(
        conn.execute("SELECT COUNT(*) AS cnt FROM pending_revalidation_queue WHERE status = 'PENDING'").fetchone()["cnt"] or 0
    )
    gate = check_stage2_closure_gate_data(conn)

    return build_tool_receipt(
        conn=conn,
        tool_name="get_supervisory_audit_snapshot",
        question_id="ALL",
        next_step_guidance="审计快照就绪。严禁在磁盘写任何 *_AUDIT.md 文件，请直接调用 check_stage2_closure_gate 与 record_compliance_check 写 SQLite。",
        data={
            "hooks_fidelity": hooks,
            "unread_citation_nodes": unread_nodes,
            "unauthorized_tool_attempts": unauth_attempts,
            "consecutive_non_l1_handoffs": non_l1,
            "pending_revalidation_backlog": reval_backlog,
            "closure_gate_summary": gate,
        },
    )


def tool_check_stage2_closure_gate(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "check_stage2_closure_gate", session_id=session_id)
    gate = check_stage2_closure_gate_data(conn)
    guidance = (
        "全卷所有必答子题均已具备 >=1 条 L3_VERIFIED 黄金结论且无待重评积压，可调 record_compliance_check(status='PASSED') 放行 Stage 3！"
        if gate["closure_allowed"]
        else f"HARD LOCK ({gate['gate_code']}): 必答子题 {gate['blocking_questions_zero_l3']} 尚无 L3_VERIFIED！请立即调用 record_compliance_check(status='BLOCKED') 并严禁宣布结题！"
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
    blocking_questions_zero_l3: list[str],
    unread_citation_nodes: list[str],
    notes: str,
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "record_compliance_check", session_id=session_id)
    st_u = (stage or "").strip().upper()
    stat_u = (status or "").strip().upper()
    if st_u not in ("STAGE1_GATE", "STAGE2_HEARTBEAT", "STAGE2_CLOSURE_GATE", "STAGE3_FINAL_AUDIT"):
        raise FailClosedError(ERR_INVALID_INPUT, f"非法 stage: {stage!r}")
    if stat_u not in ("PASSED", "ALERT", "BLOCKED"):
        raise FailClosedError(ERR_INVALID_INPUT, f"非法 status: {status!r}")

    if st_u == "STAGE2_CLOSURE_GATE" and stat_u == "PASSED":
        gate = check_stage2_closure_gate_data(conn)
        if not gate["closure_allowed"]:
            raise FailClosedError(
                ERR_LOCKED,
                f"结题硬锁拦截 (P9/P27)：存在 0 L3 子题 {gate['blocking_questions_zero_l3']}，严禁签发 PASSED！",
            )

    alert_id = f"ca_{uuid.uuid4().hex[:10]}"
    now = utc_now_iso()
    with rw_immediate_tx(conn):
        conn.execute(
            """
            INSERT INTO compliance_alerts(
                alert_id, stage, status, blocking_questions_zero_l3_json, unread_citation_nodes_json, notes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert_id,
                st_u,
                stat_u,
                json.dumps(blocking_questions_zero_l3 or [], ensure_ascii=False),
                json.dumps(unread_citation_nodes or [], ensure_ascii=False),
                (notes or "").strip(),
                now,
            ),
        )
        if st_u == "STAGE1_GATE" and stat_u == "PASSED":
            conn.execute("UPDATE epoch_config SET stage = 'STAGE2_EVOLVE', updated_at = ? WHERE config_id = 'active'", (now,))
        elif st_u == "STAGE3_FINAL_AUDIT" and stat_u == "PASSED":
            conn.execute("UPDATE epoch_config SET stage = 'CLOSED', updated_at = ? WHERE config_id = 'active'", (now,))

    return build_tool_receipt(
        conn=conn,
        tool_name="record_compliance_check",
        question_id="ALL",
        next_step_guidance="合规核验已写入 SQLite compliance_alerts（零磁盘 .md 公文）。请直接输出 1 行状态并结束会话。",
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
    enforce_role_tool_permission(conn, caller_role, "register_saved_graph_query", session_id=session_id)
    qname = (query_name or "").strip()
    sql = (sql_select or "").strip().rstrip(";")
    if not qname or not sql:
        raise FailClosedError(ERR_INVALID_INPUT, "query_name 与 sql_select 不能为空")
    if ";" in sql or _SQL_WRITE_FORBIDDEN_RE.search(sql) or not re.match(r"^\s*SELECT\b", sql, re.IGNORECASE):
        raise FailClosedError(ERR_AUTH, "仅允许单条只读 SELECT 语句，严禁写子句或多语句注入")

    try:
        conn.execute(f"EXPLAIN QUERY PLAN {sql}", {"branch_id": "test", "question_id": "Q1"}).fetchall()
    except sqlite3.Error as exc:
        raise FailClosedError(ERR_INVALID_INPUT, f"SQL EXPLAIN QUERY PLAN 预检失败: {exc}")

    now = utc_now_iso()
    with rw_immediate_tx(conn):
        conn.execute(
            """
            INSERT INTO saved_graph_queries(query_name, author_role, author_session_id, description, sql_select, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(query_name) DO UPDATE SET
                description = excluded.description,
                sql_select = excluded.sql_select
            """,
            (qname, caller_role, session_id, description.strip(), sql, now),
        )
    return build_tool_receipt(
        conn=conn,
        tool_name="register_saved_graph_query",
        question_id="ALL",
        next_step_guidance=f"A 档只读 SQL 视图 {qname!r} 已通过 EXPLAIN QUERY PLAN 预检并注册。",
        data={"query_name": qname},
    )
