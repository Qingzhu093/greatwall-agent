"""长城 V6-Up (v3.0) 中央图书馆·采编与 Stage 3 汇编工具（library_surveyor 3 个窄工具）。"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .control_plane.delivery_and_jobs import export_stage3_deliverables
from .db_schema import (
    ALLOWED_READ_DEPTHS,
    ALLOWED_SUPPORT_SCOPES,
    ALLOWED_SURVEY_OUTCOMES,
    ERR_INVALID_INPUT,
    FailClosedError,
    rw_immediate_tx,
    utc_now_iso,
)
from .mcp_core_helpers import (
    build_tool_receipt,
    enforce_role_tool_permission,
    next_prefixed_id,
)


def tool_get_survey_requests(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    question_id: str = "ALL",
) -> dict[str, Any]:
    """返回 Stage 1-2 查新请求队列，并在 Stage 3 同步提供全量已审 L3 / L2 / [R###] 综合数据包。"""
    enforce_role_tool_permission(conn, caller_role, "get_survey_requests", session_id=session_id)
    qf = str(question_id or "ALL").strip()

    if qf.upper() == "ALL":
        reqs = [dict(r) for r in conn.execute("SELECT * FROM survey_requests WHERE status = 'PENDING' ORDER BY created_at ASC").fetchall()]
    else:
        reqs = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM survey_requests WHERE status = 'PENDING' AND question_id = ? ORDER BY created_at ASC",
                (qf,),
            ).fetchall()
        ]

    l3_entries = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM internal_research_ledger WHERE ledger_type = 'L3_VERIFIED' AND is_active = 1 ORDER BY question_id, entry_id"
        ).fetchall()
    ]
    l2_entries = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM internal_research_ledger WHERE ledger_type = 'L2_FAILURE_RECORD' AND is_active = 1 ORDER BY question_id, entry_id"
        ).fetchall()
    ]
    ext_cards = [dict(r) for r in conn.execute("SELECT * FROM external_literature_cards ORDER BY ref_id").fetchall()]
    p0 = conn.execute("SELECT * FROM parse0_contract WHERE contract_id = 'active'").fetchone()

    return build_tool_receipt(
        conn=conn,
        tool_name="get_survey_requests",
        question_id=qf,
        next_step_guidance=f"现有 {len(reqs)} 条待采编查新请求、{len(l3_entries)} 条活跃已审 L3 条目与 {len(ext_cards)} 张外藏 [R###] 卡片。",
        data={
            "pending_requests": reqs,
            "stage3_synthesis_bundle": {
                "goal_and_completion_md": str(p0["goal_and_completion_md"]) if p0 else "",
                "required_questions": json.loads(p0["subquestions_json"]) if p0 else [],
                "l3_verified": l3_entries,
                "l2_failures": l2_entries,
                "external_literature": ext_cards,
            },
        },
    )


def tool_publish_external_literature_card(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    question_id: str,
    ref_id: str | None = None,
    title: str | None = None,
    abstract_md: str | None = None,
    exact_preconditions_md: str | None = None,
    formulas_or_operators_md: str | None = None,
    read_depth: str | None = None,
    support_scope: str | None = None,
    source_citation: str | None = None,
    fulfilled_request_ids: list[str] | None = None,
    outcome: str = "CARD_PUBLISHED",
    unavailable_reason_md: str | None = None,
) -> dict[str, Any]:
    """入库左翼外藏 [R###]（outcome='CARD_PUBLISHED'），或对客观不存在/违背合规边界的查新委托做无卡结案（outcome='UNAVAILABLE_REPORT'，绝不插入伪 [R###]）。"""
    enforce_role_tool_permission(conn, caller_role, "publish_external_literature_card", session_id=session_id)

    out_u = str(outcome or "CARD_PUBLISHED").strip().upper()
    if out_u not in ALLOWED_SURVEY_OUTCOMES:
        raise FailClosedError(
            ERR_INVALID_INPUT,
            f"非法 outcome={outcome!r}，仅允许 {sorted(ALLOWED_SURVEY_OUTCOMES)}",
        )

    now = utc_now_iso()

    # 分支 1：客观不存在或违背合规边界 -> 不向 external_literature_cards 插入任何伪卡，仅将 survey_requests 置为 CLOSED_UNAVAILABLE
    if out_u == "UNAVAILABLE_REPORT":
        reason_clean = str(unavailable_reason_md or "").strip()
        if len(reason_clean) < 10:
            raise FailClosedError(
                ERR_INVALID_INPUT,
                "outcome='UNAVAILABLE_REPORT' 时必须提供 >= 10 字的 unavailable_reason_md（写明已查范围与不可得原因）",
            )
        req_ids = [str(r).strip() for r in (fulfilled_request_ids or []) if str(r).strip()]
        if not req_ids:
            raise FailClosedError(
                ERR_INVALID_INPUT,
                "outcome='UNAVAILABLE_REPORT' 必须提供非空 fulfilled_request_ids 以结案对应的 survey_requests",
            )
        closed_reqs: list[str] = []
        with rw_immediate_tx(conn):
            for req_id in req_ids:
                cur = conn.execute(
                    """
                    UPDATE survey_requests
                    SET status = 'CLOSED_UNAVAILABLE',
                        fulfilled_ref_id = NULL,
                        resolution_note = ?,
                        updated_at = ?
                    WHERE req_id = ? AND status = 'PENDING'
                    """,
                    (reason_clean[:1500], now, req_id),
                )
                if cur.rowcount > 0:
                    closed_reqs.append(req_id)
        return build_tool_receipt(
            conn=conn,
            tool_name="publish_external_literature_card",
            question_id=question_id,
            next_step_guidance=(
                f"已将 {len(closed_reqs)} 条无解查新单诚实结案为 CLOSED_UNAVAILABLE（未向 external_literature_cards 插入任何伪 [R###] 卡片）。"
            ),
            data={
                "outcome": "UNAVAILABLE_REPORT",
                "ref_id": None,
                "closed_unavailable_request_ids": closed_reqs,
                "resolution_note": reason_clean[:1500],
            },
        )

    # 分支 2：CARD_PUBLISHED -> 严格校验 5 枚举 support_scope、read_depth 与 60-1500 字独立摘要
    rid = str(ref_id or "").strip()
    if not rid:
        raise FailClosedError(ERR_INVALID_INPUT, "ref_id 不能为空（建议格式 R001 / R002）")
    abs_clean = str(abstract_md or "").strip()
    if len(abs_clean) < 60 or len(abs_clean) > 1500:
        raise FailClosedError(
            ERR_INVALID_INPUT,
            f"abstract_md 长度必须为 60–1500 字符的独立高密度摘要（实收 {len(abs_clean)} 字，推荐 120–300 字，严禁空洞敷衍或 [:120] 伪摘要）",
        )
    if not str(exact_preconditions_md or "").strip() or not str(formulas_or_operators_md or "").strip():
        raise FailClosedError(ERR_INVALID_INPUT, "exact_preconditions_md 与 formulas_or_operators_md 不能为空")
    if read_depth not in ALLOWED_READ_DEPTHS:
        raise FailClosedError(
            ERR_INVALID_INPUT,
            f"非法 read_depth: {read_depth!r}，仅允许英文枚举 {sorted(ALLOWED_READ_DEPTHS)}",
        )
    if support_scope not in ALLOWED_SUPPORT_SCOPES:
        raise FailClosedError(
            ERR_INVALID_INPUT,
            f"非法 support_scope: {support_scope!r}，仅允许严格 5 选 1 英文枚举 {sorted(ALLOWED_SUPPORT_SCOPES)}",
        )
    if not str(source_citation or "").strip():
        raise FailClosedError(ERR_INVALID_INPUT, "source_citation 不能为空")

    fulfilled: list[str] = []
    with rw_immediate_tx(conn):
        conn.execute(
            """
            INSERT INTO external_literature_cards(
                ref_id, question_id, title, abstract_md, exact_preconditions_md,
                formulas_or_operators_md, read_depth, support_scope, source_citation,
                is_unverified_external, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(ref_id) DO UPDATE SET
                question_id = excluded.question_id,
                title = excluded.title,
                abstract_md = excluded.abstract_md,
                exact_preconditions_md = excluded.exact_preconditions_md,
                formulas_or_operators_md = excluded.formulas_or_operators_md,
                read_depth = excluded.read_depth,
                support_scope = excluded.support_scope,
                source_citation = excluded.source_citation
            """,
            (
                rid,
                question_id,
                str(title or "").strip(),
                abs_clean,
                str(exact_preconditions_md).strip(),
                str(formulas_or_operators_md).strip(),
                read_depth,
                support_scope,
                str(source_citation).strip(),
                now,
            ),
        )
        for req_id in fulfilled_request_ids or []:
            cur = conn.execute(
                "UPDATE survey_requests SET status = 'FULFILLED', fulfilled_ref_id = ?, updated_at = ? WHERE req_id = ? AND status = 'PENDING'",
                (rid, now, str(req_id).strip()),
            )
            if cur.rowcount > 0:
                fulfilled.append(str(req_id).strip())

    return build_tool_receipt(
        conn=conn,
        tool_name="publish_external_literature_card",
        question_id=question_id,
        next_step_guidance=f"外藏参考卡 {rid} 已入库（标注为未复验外部参考先验，已精准核销 {len(fulfilled)} 条查新单）。",
        data={"outcome": "CARD_PUBLISHED", "ref_id": rid, "is_unverified_external": True, "fulfilled_request_ids": fulfilled},
    )


def tool_export_stage3_final_delivery(
    conn: sqlite3.Connection,
    workspace_root: str,
    caller_role: str,
    session_id: str,
    delivery_mode: str,
    formal_paper_md: str,
    selected_l3_ids_by_question: dict[str, list[str]],
    remaining_gaps_by_question: dict[str, str],
    reproduction_candidate_nodes: list[str],
) -> dict[str, Any]:
    """导出 Stage 3 五件套（生成确定性 delivery_id/sha256，重置终核状态置 DELIVERY_EXPORTED 等待两步联合终核）。"""
    enforce_role_tool_permission(conn, caller_role, "export_stage3_final_delivery", session_id=session_id)
    res = export_stage3_deliverables(
        conn,
        workspace_root=workspace_root,
        delivery_mode=delivery_mode,
        formal_paper_md=formal_paper_md,
        selected_l3_ids_by_question=selected_l3_ids_by_question,
        remaining_gaps_by_question=remaining_gaps_by_question,
        reproduction_candidate_nodes=reproduction_candidate_nodes,
    )
    return build_tool_receipt(
        conn=conn,
        tool_name="export_stage3_final_delivery",
        question_id="ALL",
        next_step_guidance=(
            f"五件套已导出为 {res['delivery_id']} (SHA={res['delivery_sha256'][:12]}) 并置 DELIVERY_EXPORTED；"
            "等待 library_verifier(STAGE3_FINAL_AUDIT) 与 supervisory_committee 绑定该版本联合终核后方晋升 CLOSED_VERIFIED。"
        ),
        data=res,
    )

