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
    """纯查 SQLite (<50ms) 返回全局流程审计快照：Parse 0、仪器与探针真实健康度、口径红灯、学派聚拢、断代分支与孤儿返工单、单线退化告警、最短投入时间与两步终局状态。"""
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
    topology_health = compute_topology_and_revision_health(conn, question_filter="ALL")

    latest_spec_rev = int(p0["latest_spec_revision"] or 0) if (p0 and "latest_spec_revision" in p0.keys()) else 0
    latest_ruling_summary = str(p0["latest_ruling_summary_md"] or "") if (p0 and "latest_ruling_summary_md" in p0.keys()) else ""
    active_node_revs = [
        dict(r)
        for r in conn.execute(
            """
            SELECT node_id, question_id, branch_id, family_id, generation, node_status,
                   spec_revision, pressure_tokens, effective_context_window, first_reflection_unlocked
            FROM lineage_nodes
            WHERE node_status IN ('EXPLORING','ACTIVE_REVISING','AWAITING_TRIAGE','PENDING_REVIEW')
            ORDER BY updated_at DESC LIMIT 30
            """
        ).fetchall()
    ]

    # 仪器与探针真实运行遥测（避免工造司升版重置 consecutive_error_count 后掩盖前线真实失败率）
    probe_stats_row = conn.execute(
        """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN status = 'OK' THEN 1 ELSE 0 END) AS ok_cnt,
               SUM(CASE WHEN status != 'OK' THEN 1 ELSE 0 END) AS err_cnt
        FROM probe_diagnostic_logs
        """
    ).fetchone()
    probe_total = int(probe_stats_row["total"] or 0) if probe_stats_row else 0
    probe_ok = int(probe_stats_row["ok_cnt"] or 0) if probe_stats_row else 0
    probe_err = int(probe_stats_row["err_cnt"] or 0) if probe_stats_row else 0

    obs_inst_errors = int(
        conn.execute("SELECT COUNT(*) AS cnt FROM observations WHERE obs_status = 'INSTRUMENT_ERROR'").fetchone()["cnt"]
        or 0
    )
    open_works_tickets = [
        dict(r)
        for r in conn.execute(
            "SELECT ticket_id, question_id, ticket_type, instrument_id, payload_json, created_at FROM works_engineering_queue WHERE status = 'OPEN' ORDER BY created_at DESC LIMIT 10"
        ).fetchall()
    ]
    inst_counts_by_q = [
        dict(r)
        for r in conn.execute(
            """
            SELECT question_id,
                   COUNT(DISTINCT instrument_id) AS distinct_instruments,
                   COUNT(*) AS total_versions
            FROM instruments
            GROUP BY question_id
            """
        ).fetchall()
    ]
    instrument_telemetry = {
        "probe_calls_total": probe_total,
        "probe_calls_ok": probe_ok,
        "probe_calls_error": probe_err,
        "official_instrument_errors_total": obs_inst_errors,
        "open_works_tickets_count": len(open_works_tickets),
        "open_works_tickets": open_works_tickets,
        "instrument_versions_by_question": inst_counts_by_q,
    }

    # 汇总结构化异常清单（watchdog_anomalies），让 0 工具监察委一眼看清流程失真并签发 ALERT
    watchdog_anomalies: list[dict[str, Any]] = []
    blocking_qs_set: set[str] = set()

    for orph in topology_health.get("orphaned_blind_review_revisions") or []:
        qid_o = str(orph.get("question_id") or "Q1")
        blocking_qs_set.add(qid_o)
        watchdog_anomalies.append(
            {
                "anomaly_type": "ORPHANED_BLIND_REVIEW_REVISION",
                "question_id": qid_o,
                "review_id": orph.get("review_id"),
                "source_node_id": orph.get("source_node_id"),
                "branch_id": orph.get("branch_id"),
                "family_id": orph.get("family_id"),
                "summary": f"盲审单 {orph.get('review_id')} 判为 REVISE 待返工，但原分支 {orph.get('branch_id')} ({orph.get('source_node_id')}) 已被中止或断代，当前无活跃节点承接返工单！需唤醒 Logistics 执行 fork_branch 续接。",
            }
        )

    for us in topology_health.get("understaffed_questions") or []:
        qid_u = str(us.get("question_id") or "Q1")
        blocking_qs_set.add(qid_u)
        watchdog_anomalies.append(
            {
                "anomaly_type": "SINGLE_BRANCH_DEGENERATION_OR_UNDERSTAFFED_FAMILIES",
                "question_id": qid_u,
                "active_branch_count": us.get("active_branch_count"),
                "missing_active_family_ids": us.get("missing_active_family_ids"),
                "free_explorer_slots": us.get("free_explorer_slots"),
                "summary": (
                    f"子题 {qid_u} 已登记 {len(us.get('registered_active_families') or [])} 个正交学派，"
                    f"但当前仅 {us.get('active_branch_count')} 条分支在跑（空闲槽位 {us.get('free_explorer_slots')} 个），"
                    f"正交学派 {us.get('missing_active_family_ids')} 断代缺编！需唤醒 Logistics 补齐多路 Worktree。"
                ),
            }
        )

    if unhealthy:
        for u in unhealthy:
            qid_i = str(u.get("question_id") or "Q1")
            if qid_i != "ALL":
                blocking_qs_set.add(qid_i)
        watchdog_anomalies.append(
            {
                "anomaly_type": "UNHEALTHY_INSTRUMENT_CIRCUIT_BROKEN",
                "instruments": [u["instrument_id"] for u in unhealthy],
                "summary": f"存在 {len(unhealthy)} 台连续报错熔断的 UNHEALTHY 仪器，需工造司修复升版。",
            }
        )

    if probe_total >= 3 and probe_ok == 0:
        watchdog_anomalies.append(
            {
                "anomaly_type": "PROBE_100PCT_FAILURE_RATE",
                "probe_calls_total": probe_total,
                "probe_calls_error": probe_err,
                "summary": f"前线探索者累计调用 {probe_total} 次 tier='probe' 全部失败（0 次成功），存在仪器派发契约摩擦。",
            }
        )

    if watchdog_anomalies:
        guidance = (
            f"检测到 {len(watchdog_anomalies)} 项流程/拓扑异常（{[a['anomaly_type'] for a in watchdog_anomalies]}）！"
            f"请调用 record_compliance_check(stage='STAGE2_HEARTBEAT', status='ALERT', blocking_questions={sorted(blocking_qs_set)!r}, notes='...') 登记告警以驱动后勤/工造司闭环纠偏。"
        )
    else:
        guidance = "纯只读审计快照已就绪；请严格遵循流程正义与零 .md 落盘原则调用 record_compliance_check 写库。"

    return build_tool_receipt(
        conn=conn,
        tool_name="get_supervisory_audit_snapshot",
        question_id="ALL",
        next_step_guidance=guidance,
        data={
            "parse0_signed": bool(p0 and str(p0["human_signed_at"] or "").strip()),
            "stage": str(p0["stage"]) if p0 else "STAGE1_PARSE0",
            "latest_spec_revision": latest_spec_rev,
            "latest_ruling_summary_md": latest_ruling_summary,
            "active_node_spec_revisions": active_node_revs,
            "consecutive_non_l1_handoffs": int(p0["consecutive_non_l1_handoffs"] or 0) if p0 else 0,
            "unhealthy_instruments": unhealthy,
            "instrument_and_probe_telemetry": instrument_telemetry,
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

    alert_id = f"ca_{uuid.uuid4().hex[:10]}"
    if st_u == "PARSE0_GATE" and stat_u == "PASSED":
        with rw_immediate_tx(conn):
            p0 = conn.execute("SELECT * FROM parse0_contract WHERE contract_id = 'active'").fetchone()
            if p0 is None or not str(p0["human_signed_at"] or "").strip() or not str(p0["goal_and_completion_md"] or "").strip():
                raise FailClosedError(ERR_LOCKED, "PARSE0_GATE 阻断：尚未签署包含非空目标与完成判据的 Parse 0 六项启动表单")
            conn.execute(
                "UPDATE parse0_contract SET stage = 'STAGE2_EVOLVE', updated_at = ? WHERE contract_id = 'active'",
                (now,),
            )
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

    elif st_u == "CLOSURE_GATE" and stat_u == "PASSED":
        # 严格单写者原子签发：在写锁内部核对版本绑定、实时重算磁盘 SHA-256 并带条件提交，物理杜绝并发“审 A 放 B”！
        with rw_immediate_tx(conn):
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
            cur = conn.execute(
                """
                UPDATE project_closure_state
                SET status = 'CLOSED_VERIFIED', supervisory_signed_at = ?, updated_at = ?
                WHERE id = 1
                  AND status = 'DELIVERY_EXPORTED'
                  AND latest_delivery_id = ?
                  AND latest_delivery_sha256 = ?
                  AND verifier_final_audit_passed = 1
                  AND verifier_audited_delivery_id = ?
                  AND verifier_audited_delivery_sha256 = ?
                """,
                (now, now, latest_did, latest_sha, latest_did, latest_sha),
            )
            if cur.rowcount != 1:
                raise FailClosedError(ERR_LOCKED, "CLOSURE_GATE 并发版本冲突：交付状态已变更，请重新核验最新交付版本。")
            conn.execute(
                "UPDATE parse0_contract SET stage = 'CLOSED_VERIFIED', updated_at = ? WHERE contract_id = 'active'",
                (now,),
            )
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
    else:
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
