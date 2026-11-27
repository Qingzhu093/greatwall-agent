"""GreatWall v0.3.1 科研总控总览、溯源、影响预演和确认单。

设计边界（ARCH_PAPER_01 §5）：
1. 物理零代码编辑、零终端、零裸写业务库权；
2. 四级 Inline & Spill + 强外键 Chain of Recall：每个只读查询强制内联下一跳关联外键 ID 与原始 session_id 锚点；
3. 零副作用推测预演（chief_preview_impact）：仅只读计算影响面与排雷查重，绝不擅自开重型分支；
4. 确认单仅写入 `PENDING_HUMAN`，日常直执在 tools_operator 模块校验人类授权。
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .control_plane.proposals import create_control_proposal
from .control_plane.subproblem_locks import find_latest_spec_full_goal_l3
from .db_schema import (
    ERR_INVALID_INPUT,
    ERR_NOT_FOUND,
    FailClosedError,
    sanitize_fts5_query,
)
from .mcp_core_helpers import (
    build_tool_receipt,
    enforce_role_tool_permission,
)


from .control_plane.operator_ops import recent_receipts
from .control_plane.operator_policy import active_arrangements, effective_policy, epoch_id, runtime_slots, validate_arrangement, scoped_to


def tool_chief_get_overview_snapshot(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    question_id: str = "ALL",
) -> dict[str, Any]:
    """Inline & Spill 轻量总览：每子题 1 行核心态 + 最新总览/提案/圆桌关联 ID。"""
    enforce_role_tool_permission(conn, caller_role, "chief_get_overview_snapshot", session_id=session_id)
    qf = str(question_id or "ALL").strip()
    p0 = conn.execute("SELECT * FROM parse0_contract WHERE contract_id = 'active'").fetchone()
    closure = conn.execute("SELECT status, delivery_mode, latest_delivery_id FROM project_closure_state WHERE id = 1").fetchone()

    q_sql = "SELECT * FROM subproblem_runtime_state ORDER BY question_id ASC"
    q_params: tuple[Any, ...] = ()
    if qf.upper() != "ALL":
        q_sql = "SELECT * FROM subproblem_runtime_state WHERE question_id = ?"
        q_params = (qf,)

    arrangements = active_arrangements(conn)
    slots = runtime_slots(conn)
    subproblems: list[dict[str, Any]] = []
    for r in conn.execute(q_sql, q_params).fetchall():
        qid = str(r["question_id"])
        latest_sv = conn.execute(
            "SELECT survey_id, revision, total_chars, created_at FROM subproblem_living_surveys WHERE question_id = ? ORDER BY revision DESC LIMIT 1",
            (qid,),
        ).fetchone()
        active_branches = [
            {
                "branch_id": str(b["branch_id"]),
                "node_id": str(b["node_id"]),
                "branch_kind": str(b["branch_kind"]),
                "node_status": str(b["node_status"]),
                "control_state": str(b["control_state"]),
                "companion_session_id": str(b["companion_session_id"]),
            }
            for b in conn.execute(
                """
                SELECT branch_id, node_id, branch_kind, node_status, control_state, companion_session_id
                FROM lineage_nodes
                WHERE question_id = ? AND node_status IN ('EXPLORING','ACTIVE_REVISING','AWAITING_TRIAGE','PENDING_REVIEW','BLOCKED_L4B')
                ORDER BY updated_at DESC LIMIT 12
                """,
                (qid,),
            ).fetchall()
        ]
        open_gaps = [
            str(g["gap_id"])
            for g in conn.execute("SELECT gap_id FROM open_lemma_gaps WHERE question_id = ? AND status = 'OPEN'", (qid,)).fetchall()
        ]
        subproblems.append(
            {
                "question_id": qid,
                **effective_policy(arrangements, qid, base=dict(r)),
                "desired_state": str(r["desired_state"]),
                "dispatch_state": str(r["dispatch_state"]),
                "active_spec_revision": int(r["active_spec_revision"] or 0),
                "solved_entry_id": r["solved_entry_id"],
                "baseline_entry_id": r["baseline_entry_id"],
                "completed_waves": int(r["completed_waves"] or 0),
                "spent_tokens": int(r["spent_tokens"] or 0),
                "question_token_budget": int(r["question_token_budget"] or 0),
                "block_reason_code": str(r["block_reason_code"] or ""),
                "latest_survey_id": str(latest_sv["survey_id"]) if latest_sv else None,
                "latest_survey_revision": int(latest_sv["revision"]) if latest_sv else 0,
                "open_gap_ids": open_gaps,
                "active_branches": active_branches,
            }
        )

    pending_proposals = [
        {
            "proposal_id": str(p["proposal_id"]),
            "action_type": str(p["action_type"]),
            "target_id": str(p["target_id"]),
            "rationale_preview": str(p["rationale_md"])[:180],
            "created_at": str(p["created_at"]),
        }
        for p in conn.execute(
            "SELECT proposal_id, action_type, target_id, rationale_md, created_at FROM control_proposals WHERE status = 'PENDING_HUMAN' ORDER BY created_at ASC"
        ).fetchall()
    ]
    active_confs = [
        {
            "conference_id": str(c["conference_id"]),
            "question_id": str(c["question_id"]),
            "wave_no": int(c["wave_no"]),
            "status": str(c["status"]),
            "linked_survey_id": c["linked_survey_id"],
            "chair_session_id": str(c["chair_session_id"] or ""),
        }
        for c in conn.execute(
            "SELECT conference_id, question_id, wave_no, status, linked_survey_id, chair_session_id FROM wave_conferences WHERE status NOT IN ('COMPLETED','CANCELLED','EXPIRED','FAILED')"
        ).fetchall()
    ]

    return build_tool_receipt(
        conn=conn,
        tool_name="chief_get_overview_snapshot",
        question_id=qf,
        next_step_guidance="已按 Inline & Spill 返回骨架视图；如需深查任一条证据或原会话锚点，请调用 chief_trace_entity。",
        data={
            "epoch_id": epoch_id(conn),
            "active_arrangements": arrangements if qf == "ALL" else [
                row for row in arrangements if row["scope_type"] == "PROJECT" or row["target_id"] == qf
            ],
            "operation_receipts": recent_receipts(conn, 10),
            "handbacks": [dict(row) for row in conn.execute(
                """SELECT handback_id,question_id,source_node_id,origin_human_mandate,created_at,human_request_md
                   FROM handback_records WHERE epoch_id=? AND status='PENDING_CHIEF'
                   AND (?='ALL' OR question_id=?) ORDER BY created_at LIMIT 10""", (epoch_id(conn), qf, qf),
            )],
            "operator_slot_ledger": {
                "working": [row for row in slots if row["control_state"] == "AUTO_RUNNING" and row["node_status"] != "RETIRED" and (qf == "ALL" or row["question_id"] == qf)],
                "draining": [row for row in slots if (row["control_state"] != "AUTO_RUNNING" or row["node_status"] == "RETIRED") and (qf == "ALL" or row["question_id"] == qf)],
                "hibernated_or_human": [b["node_id"] for state in subproblems for b in state["active_branches"] if b["control_state"] in ("HIBERNATED","HUMAN_ACTIVE")],
            },
            "stage": str(p0["stage"]) if p0 else "UNINITIALIZED",
            "autonomy_mode": effective_policy(arrangements).get("autonomy_mode", str(p0["autonomy_mode"]) if p0 else "WAVE_CONFIRM"),
            "latest_spec_revision": int(p0["latest_spec_revision"] or 0) if p0 else 0,
            "closure": dict(closure) if closure else {"status": "OPEN"},
            "subproblems": subproblems,
            "pending_proposals": pending_proposals,
            "active_conferences": active_confs,
        },
    )


def tool_chief_trace_entity(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    entity_type: str,
    entity_id: str,
) -> dict[str, Any]:
    """强外键 Chain of Recall 多跳查账：返回目标详情并强制内联下一跳外键 ID 与原 session 锚点。"""
    enforce_role_tool_permission(conn, caller_role, "chief_trace_entity", session_id=session_id)
    et = str(entity_type or "").strip().lower()
    eid = str(entity_id or "").strip()
    if not eid:
        raise FailClosedError(ERR_INVALID_INPUT, "entity_id 不能为空")

    data: dict[str, Any] = {}
    qid = "ALL"

    if et == "question":
        row = conn.execute("SELECT * FROM subproblem_runtime_state WHERE question_id = ?", (eid,)).fetchone()
        if row is None:
            raise FailClosedError(ERR_NOT_FOUND, f"子题 {eid!r} 不存在")
        qid = eid
        sv = conn.execute(
            "SELECT * FROM subproblem_living_surveys WHERE question_id = ? ORDER BY revision DESC LIMIT 1",
            (eid,),
        ).fetchone()
        l3_ids = [
            str(r["entry_id"])
            for r in conn.execute(
                "SELECT entry_id FROM internal_research_ledger WHERE question_id = ? AND ledger_type = 'L3_VERIFIED' AND is_active = 1 ORDER BY created_at DESC LIMIT 20",
                (eid,),
            ).fetchall()
        ]
        gap_ids = [
            str(r["gap_id"])
            for r in conn.execute("SELECT gap_id FROM open_lemma_gaps WHERE question_id = ? AND status = 'OPEN'", (eid,)).fetchall()
        ]
        conf_ids = [
            str(r["conference_id"])
            for r in conn.execute("SELECT conference_id FROM wave_conferences WHERE question_id = ? ORDER BY wave_no DESC LIMIT 5", (eid,)).fetchall()
        ]
        data = {
            "entity_type": "question",
            "state": dict(row),
            "latest_survey": dict(sv) if sv else None,
            "next_hop_ids": {"l3_entry_ids": l3_ids, "open_gap_ids": gap_ids, "conference_ids": conf_ids},
        }
    elif et == "entry":
        row = conn.execute("SELECT * FROM internal_research_ledger WHERE entry_id = ?", (eid,)).fetchone()
        if row is None:
            raise FailClosedError(ERR_NOT_FOUND, f"馆藏条目 {eid!r} 不存在")
        qid = str(row["question_id"])
        rev = (
            conn.execute("SELECT review_id, source_node_id, review_status, final_verdict FROM review_queue WHERE review_id = ?", (row["verified_review_id"],)).fetchone()
            if row["verified_review_id"]
            else None
        )
        data = {
            "entity_type": "entry",
            "entry": {
                "entry_id": str(row["entry_id"]),
                "question_id": qid,
                "ledger_type": str(row["ledger_type"]),
                "l3_entry_kind": row["l3_entry_kind"],
                "goal_coverage": row["goal_coverage"],
                "publish_tier": str(row["publish_tier"]),
                "verified_spec_revision": int(row["verified_spec_revision"] or 0),
                "title": str(row["title"]),
                "abstract_md": str(row["abstract_md"]),
                "exact_verified_scope_md": row["exact_verified_scope_md"],
                "exact_refuted_scope_md": row["exact_refuted_scope_md"],
                "body_preview_md": str(row["body_proof_or_code_md"] or "")[:1200],
            },
            "next_hop_ids": {
                "review_id": str(row["verified_review_id"] or ""),
                "source_node_id": str(rev["source_node_id"]) if rev else "",
                "bound_obs_ids": json.loads(row["bound_obs_ids_json"] or "[]"),
            },
        }
    elif et == "review":
        row = conn.execute("SELECT * FROM review_queue WHERE review_id = ?", (eid,)).fetchone()
        if row is None:
            raise FailClosedError(ERR_NOT_FOUND, f"审稿单 {eid!r} 不存在")
        qid = str(row["question_id"])
        linked_entries = [
            str(r["entry_id"])
            for r in conn.execute("SELECT entry_id FROM internal_research_ledger WHERE verified_review_id = ?", (eid,)).fetchall()
        ]
        data = {
            "entity_type": "review",
            "review": {
                "review_id": str(row["review_id"]),
                "question_id": qid,
                "source_node_id": str(row["source_node_id"]),
                "source_type": str(row["source_type"]),
                "review_status": str(row["review_status"]),
                "spec_revision": int(row["spec_revision"] or 0),
                "final_verdict": row["final_verdict"],
                "stage1_ledger": json.loads(row["stage1_ledger_json"] or "[]"),
                "revision_requests": json.loads(row["revision_requests_json"] or "[]"),
            },
            "next_hop_ids": {
                "source_node_id": str(row["source_node_id"]),
                "bound_obs_ids": json.loads(row["bound_obs_ids_json"] or "[]"),
                "linked_entry_ids": linked_entries,
            },
        }
    elif et == "node":
        row = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (eid,)).fetchone()
        if row is None:
            raise FailClosedError(ERR_NOT_FOUND, f"节点 {eid!r} 不存在")
        qid = str(row["question_id"])
        brf = conn.execute("SELECT briefing_id FROM lineage_briefings WHERE node_id = ? ORDER BY created_at DESC LIMIT 1", (eid,)).fetchone()
        revs = [str(r["review_id"]) for r in conn.execute("SELECT review_id FROM review_queue WHERE source_node_id = ?", (eid,)).fetchall()]
        intvs = [dict(r) for r in conn.execute("SELECT intervention_id, action, artifact_dirty, created_at FROM node_interventions WHERE node_id = ? ORDER BY created_at DESC LIMIT 5", (eid,)).fetchall()]
        data = {
            "entity_type": "node",
            "node": {
                "node_id": eid,
                "question_id": qid,
                "branch_id": str(row["branch_id"]),
                "family_id": str(row["family_id"] or ""),
                "generation": int(row["generation"] or 1),
                "branch_kind": str(row["branch_kind"] or "PURE"),
                "node_status": str(row["node_status"]),
                "control_state": str(row["control_state"] or "AUTO_RUNNING"),
                "mechanism_summary": str(row["mechanism_summary"] or ""),
                "evidence_grade": str(row["evidence_grade"]),
                "worktree_abs_path": str(row["worktree_abs_path"]),
                "human_modified": bool(int(row["human_modified"] or 0)),
                "artifact_dirty_since_last_obs": bool(int(row["artifact_dirty_since_last_obs"] or 0)),
                "column_a_preview": str(row["column_a_facts_md"] or "")[:800],
                "will_preview": str(row["will_md"] or "")[:500],
            },
            "recent_interventions": intvs,
            "next_hop_ids": {
                "parent_node_id": row["parent_node_id"],
                "briefing_id": str(brf["briefing_id"]) if brf else None,
                "companion_session_id": str(row["companion_session_id"] or f"gw-comp-{eid}"),
                "explorer_session_hint": f"gw-exp-{eid}",
                "bound_obs_ids": json.loads(row["bound_obs_ids_json"] or "[]"),
                "review_ids": revs,
            },
        }
    elif et == "conference":
        row = conn.execute("SELECT * FROM wave_conferences WHERE conference_id = ?", (eid,)).fetchone()
        if row is None:
            raise FailClosedError(ERR_NOT_FOUND, f"圆桌会议 {eid!r} 不存在")
        qid = str(row["question_id"])
        data = {
            "entity_type": "conference",
            "conference": {
                "conference_id": eid,
                "question_id": qid,
                "wave_no": int(row["wave_no"]),
                "status": str(row["status"]),
                "minutes_md": str(row["minutes_md"] or "")[:1500],
                "verdict": json.loads(row["verdict_json"] or "{}") if row["verdict_json"] else None,
            },
            "next_hop_ids": {
                "chair_session_id": str(row["chair_session_id"] or ""),
                "linked_survey_id": row["linked_survey_id"],
                "participants": json.loads(row["participant_nodes_json"] or "[]"),
            },
        }
    elif et == "proposal":
        row = conn.execute("SELECT * FROM control_proposals WHERE proposal_id = ?", (eid,)).fetchone()
        if row is None:
            raise FailClosedError(ERR_NOT_FOUND, f"提案 {eid!r} 不存在")
        data = {"entity_type": "proposal", "proposal": dict(row), "next_hop_ids": {"target_id": str(row["target_id"])}}
    elif et == "gap":
        row = conn.execute("SELECT * FROM open_lemma_gaps WHERE gap_id = ?", (eid,)).fetchone()
        if row is None:
            raise FailClosedError(ERR_NOT_FOUND, f"引理悬赏 {eid!r} 不存在")
        qid = str(row["question_id"])
        data = {
            "entity_type": "gap",
            "gap": dict(row),
            "next_hop_ids": {"blocked_node_id": str(row["blocked_node_id"]), "fulfilled_by_entry_id": row["fulfilled_by_entry_id"]},
        }
    elif et == "obs":
        row = conn.execute("SELECT * FROM observations WHERE obs_id = ?", (eid,)).fetchone()
        if row is None:
            raise FailClosedError(ERR_NOT_FOUND, f"观测 {eid!r} 不存在")
        qid = str(row["question_id"])
        data = {
            "entity_type": "obs",
            "obs": {
                "obs_id": eid,
                "question_id": qid,
                "node_id": str(row["node_id"]),
                "instrument_id": str(row["instrument_id"]),
                "instrument_version": int(row["instrument_version"]),
                "obs_status": str(row["obs_status"]),
                "tracks": json.loads(row["tracks_json"] or "{}"),
                "details_preview": str(row["details_text"] or "")[:800],
            },
            "next_hop_ids": {"node_id": str(row["node_id"]), "revalidated_from_obs_id": row["revalidated_from_obs_id"]},
        }
    else:
        raise FailClosedError(ERR_INVALID_INPUT, f"不支持的 entity_type={entity_type!r}")

    return build_tool_receipt(
        conn=conn,
        tool_name="chief_trace_entity",
        question_id=qid,
        next_step_guidance="可顺着 next_hop_ids 继续展开下一跳，或在回复末尾附带原始 session 锚点供人类一键跳转。",
        data=data,
    )


def tool_chief_get_wave_digest(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    question_id: str,
    conference_id: str | None = None,
) -> dict[str, Any]:
    """读取子题最新 1500 字总览与对应波次圆桌纪要/调整建议。"""
    enforce_role_tool_permission(conn, caller_role, "chief_get_wave_digest", session_id=session_id)
    qid = str(question_id or "").strip()
    if conference_id:
        conf = conn.execute("SELECT * FROM wave_conferences WHERE conference_id = ?", (str(conference_id),)).fetchone()
    else:
        conf = conn.execute(
            "SELECT * FROM wave_conferences WHERE question_id = ? ORDER BY wave_no DESC LIMIT 1",
            (qid,),
        ).fetchone()
    sv = conn.execute(
        "SELECT * FROM subproblem_living_surveys WHERE question_id = ? ORDER BY revision DESC LIMIT 1",
        (qid,),
    ).fetchone()
    return build_tool_receipt(
        conn=conn,
        tool_name="chief_get_wave_digest",
        question_id=qid,
        next_step_guidance="请用 3–5 句人话向人类提炼核心变化与待决策项，绝不照抄长篇原文。",
        data={
            "question_id": qid,
            "latest_living_survey": dict(sv) if sv else None,
            "latest_conference": {
                "conference_id": str(conf["conference_id"]),
                "wave_no": int(conf["wave_no"]),
                "status": str(conf["status"]),
                "minutes_md": str(conf["minutes_md"] or ""),
                "verdict": json.loads(conf["verdict_json"] or "{}") if conf["verdict_json"] else None,
                "chair_session_id": str(conf["chair_session_id"] or ""),
            }
            if conf
            else None,
        },
    )


def tool_chief_preview_impact(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    preview_kind: str,
    question_id: str = "ALL",
    query_text: str = "",
    target_id: str | None = None,
    arrangement: dict | None = None,
) -> dict[str, Any]:
    """零副作用推测预演：只读测算改题影响面、排雷雷达查重或波次调整受影响分支。"""
    enforce_role_tool_permission(conn, caller_role, "chief_preview_impact", session_id=session_id)
    pk = str(preview_kind or "").strip().lower()
    qid = str(question_id or "ALL").strip()

    if pk == "run_arrangement":
        scope, target, patch, end_kind, expires = validate_arrangement(arrangement or {})
        scope_row = {"scope_type": scope, "target_id": target}
        slots = [row for row in runtime_slots(conn) if scoped_to(scope_row, row["question_id"], row["node_id"])]
        result = {
            "preview_kind": pk, "scope_type": scope, "target_id": target, "patch": patch,
            "ends_on_kind": end_kind, "expires_at": expires, "in_flight_nodes": slots,
        }
    elif pk == "ruling_amendment":
        target_qs = (
            [str(r["question_id"]) for r in conn.execute("SELECT question_id FROM subproblem_runtime_state ORDER BY question_id").fetchall()]
            if qid.upper() == "ALL"
            else [qid]
        )
        impacted: list[dict[str, Any]] = []
        for q in target_qs:
            qrow = conn.execute("SELECT * FROM subproblem_runtime_state WHERE question_id = ?", (q,)).fetchone()
            if qrow is None:
                continue
            in_flight = [
                str(n["node_id"])
                for n in conn.execute(
                    "SELECT node_id FROM lineage_nodes WHERE question_id = ? AND node_status IN ('EXPLORING','ACTIVE_REVISING')",
                    (q,),
                ).fetchall()
            ]
            current_full = find_latest_spec_full_goal_l3(conn, q)
            impacted.append(
                {
                    "question_id": q,
                    "current_spec_revision": int(qrow["active_spec_revision"] or 0),
                    "will_reopen_from_solved": str(qrow["dispatch_state"]) == "STOPPED_SOLVED",
                    "current_solved_entry_id": current_full["entry_id"] if current_full else None,
                    "in_flight_nodes_receiving_policy_notice": in_flight,
                }
            )
        result = {"preview_kind": pk, "impacted_subproblems": impacted}

    elif pk == "avoidance_check":
        fts_q = sanitize_fts5_query(query_text)
        matches: list[dict[str, Any]] = []
        if fts_q:
            rows = conn.execute(
                """
                SELECT r.entry_id, r.question_id, r.radar_kind, r.title, r.scope_md
                FROM v_library_avoidance_radar r
                JOIN internal_research_fts f ON f.entry_id = r.entry_id
                WHERE internal_research_fts MATCH ?
                  AND (? = 'ALL' OR r.question_id = ?)
                LIMIT 10
                """,
                (fts_q, qid, qid),
            ).fetchall()
            matches = [dict(r) for r in rows]
        else:
            rows = conn.execute(
                "SELECT entry_id, question_id, radar_kind, title, scope_md FROM v_library_avoidance_radar WHERE (? = 'ALL' OR question_id = ?) ORDER BY created_at DESC LIMIT 10",
                (qid, qid),
            ).fetchall()
            matches = [dict(r) for r in rows]
        result = {"preview_kind": pk, "query_text": query_text, "matched_avoidance_records": matches}

    elif pk == "wave_verdict":
        cid = str(target_id or "").strip()
        conf = conn.execute("SELECT * FROM wave_conferences WHERE conference_id = ?", (cid,)).fetchone()
        if conf is None:
            raise FailClosedError(ERR_NOT_FOUND, f"圆桌会议 {cid!r} 不存在")
        verdict = json.loads(conf["verdict_json"] or "{}") if conf["verdict_json"] else {}
        result = {"preview_kind": pk, "conference_id": cid, "status": str(conf["status"]), "planned_actions": verdict.get("actions") or []}

    elif pk == "subproblem_budget":
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT question_id, dispatch_state, spent_tokens, question_token_budget, completed_waves, max_waves, min_commitment_sec FROM subproblem_runtime_state WHERE (? = 'ALL' OR question_id = ?)",
                (qid, qid),
            ).fetchall()
        ]
        result = {"preview_kind": pk, "budgets": rows}
    else:
        raise FailClosedError(ERR_INVALID_INPUT, f"不支持的 preview_kind={preview_kind!r}")

    return build_tool_receipt(
        conn=conn,
        tool_name="chief_preview_impact",
        question_id=qid,
        next_step_guidance="零副作用预演完成；若人类确认推进，再调用 chief_propose_control_action 生成正式确认单。",
        data=result,
    )


def tool_chief_propose_control_action(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    action_type: str,
    target_id: str,
    rationale_md: str,
    payload: dict[str, Any] | None = None,
    human_action_question: str = "",
) -> dict[str, Any]:
    """生成 8 类宪章正门确认单写入 control_proposals（带单问题 human_action 确认卡元数据）。"""
    enforce_role_tool_permission(conn, caller_role, "chief_propose_control_action", session_id=session_id)
    payload = dict(payload or {})
    if str(action_type).upper() == "ADVANCE_EPOCH":
        payload["expected_epoch_id"] = epoch_id(conn)
    prop = create_control_proposal(
        conn,
        proposed_by="gw_chief",
        action_type=action_type,
        target_id=target_id,
        payload=payload or {},
        rationale_md=rationale_md,
    )
    question_line = str(human_action_question or "").strip() or f"是否确认执行 {prop['action_type']}（目标：{prop['target_id']}）？"
    return build_tool_receipt(
        conn=conn,
        tool_name="chief_propose_control_action",
        question_id=str((payload or {}).get("question_id") or "ALL"),
        next_step_guidance="提案单已生成并进入 PENDING_HUMAN，等待人类在原生 Action Card 或右侧 UI 面板一键确认。",
        data={
            **prop,
            "human_action": {
                "proposal_id": prop["proposal_id"],
                "action_type": prop["action_type"],
                "target_id": prop["target_id"],
                "question": question_line,
                "rationale_md": prop["rationale_md"],
                "buttons": [
                    {"id": "approve", "label": "确认执行", "decision": "APPROVE"},
                    {"id": "reject", "label": "取消驳回", "decision": "REJECT"},
                ],
            },
        },
    )
