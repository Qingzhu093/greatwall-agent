"""GreatWall Agent v0.3 中央图书馆三角色工具（external_surveyor / library_chronicler / conference_chair）+ 圆桌发言工具。

物理分权红线（ARCH_PAPER_04 §2）：
1. `external_surveyor`（唯一联网）：绝对物理禁读任何院内 L3/L2/草稿，仅读写脱敏查新单与外藏 [R###]；
2. `library_chronicler`（零外网零代码）：读内藏硬账本与圆桌纪要，发布 <=1500 字《子题全局总览》，Stage 3 组装并原子冻结五件套；
3. `conference_chair`（零外网零代码）：第 2 拍落盘交锋纪要切 SURVEY_REFRESHING，第 4 拍读最新总览签发 6 类宏观调整单。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from .control_plane.delivery_freeze import export_stage3_deliverables_v03
from .control_plane.wave_engine import (
    append_conference_statement,
    build_wave_hard_ledger,
    submit_wave_verdict_decision,
)
from .db_schema import (
    ALLOWED_READ_DEPTHS,
    ALLOWED_SUPPORT_SCOPES,
    ALLOWED_SURVEY_OUTCOMES,
    ERR_INVALID_INPUT,
    ERR_LOCKED,
    ERR_NOT_FOUND,
    FailClosedError,
    rw_immediate_tx,
    utc_now_iso,
)
from .mcp_core_helpers import (
    build_tool_receipt,
    enforce_role_tool_permission,
)


# ============================================================================
# 1. external_surveyor（2 个：唯一可连外网，物理零院内成果泄露）
# ============================================================================
def tool_get_survey_requests(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    question_id: str = "ALL",
) -> dict[str, Any]:
    """仅返回脱敏后的外部查新请求与已有外藏 [R###] 列表（严禁返回任何院内 L3/L2 或分支草稿！）。"""
    enforce_role_tool_permission(conn, caller_role, "get_survey_requests", session_id=session_id)
    qf = str(question_id or "ALL").strip()
    if qf.upper() == "ALL":
        reqs = [
            dict(r)
            for r in conn.execute(
                "SELECT req_id, question_id, topic_query, reason, status, created_at FROM survey_requests WHERE status = 'PENDING' ORDER BY created_at ASC"
            ).fetchall()
        ]
        ext_cards = [
            dict(r)
            for r in conn.execute(
                "SELECT ref_id, question_id, title, read_depth, support_scope, source_citation, created_at FROM external_literature_cards ORDER BY ref_id"
            ).fetchall()
        ]
    else:
        reqs = [
            dict(r)
            for r in conn.execute(
                "SELECT req_id, question_id, topic_query, reason, status, created_at FROM survey_requests WHERE status = 'PENDING' AND question_id = ? ORDER BY created_at ASC",
                (qf,),
            ).fetchall()
        ]
        ext_cards = [
            dict(r)
            for r in conn.execute(
                "SELECT ref_id, question_id, title, read_depth, support_scope, source_citation, created_at FROM external_literature_cards WHERE question_id = ? ORDER BY ref_id",
                (qf,),
            ).fetchall()
        ]

    return build_tool_receipt(
        conn=conn,
        tool_name="get_survey_requests",
        question_id=qf,
        next_step_guidance=f"现有 {len(reqs)} 条待采编外部查新请求与 {len(ext_cards)} 张外藏 [R###] 卡（严格物理隔离院内成果）。",
        data={"pending_requests": reqs, "existing_external_cards": ext_cards},
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
    """入库外藏参考卡 [R###]（CARD_PUBLISHED）或对不存在来源诚实结案（UNAVAILABLE_REPORT，绝不造伪卡）。"""
    enforce_role_tool_permission(conn, caller_role, "publish_external_literature_card", session_id=session_id)
    out_u = str(outcome or "CARD_PUBLISHED").strip().upper()
    if out_u not in ALLOWED_SURVEY_OUTCOMES:
        raise FailClosedError(ERR_INVALID_INPUT, f"非法 outcome={outcome!r}")
    now = utc_now_iso()

    if out_u == "UNAVAILABLE_REPORT":
        reason_clean = str(unavailable_reason_md or "").strip()
        if len(reason_clean) < 10:
            raise FailClosedError(ERR_INVALID_INPUT, "UNAVAILABLE_REPORT 必须提供 >=10 字的 unavailable_reason_md")
        req_ids = [str(r).strip() for r in (fulfilled_request_ids or []) if str(r).strip()]
        if not req_ids:
            raise FailClosedError(ERR_INVALID_INPUT, "UNAVAILABLE_REPORT 必须提供非空 fulfilled_request_ids")
        closed_reqs: list[str] = []
        with rw_immediate_tx(conn):
            for req_id in req_ids:
                cur = conn.execute(
                    """
                    UPDATE survey_requests
                    SET status = 'CLOSED_UNAVAILABLE', fulfilled_ref_id = NULL, resolution_note = ?, updated_at = ?
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
            next_step_guidance=f"已诚实结案 {len(closed_reqs)} 条无解查新单（未插伪卡）。",
            data={"outcome": "UNAVAILABLE_REPORT", "ref_id": None, "closed_unavailable_request_ids": closed_reqs},
        )

    rid = str(ref_id or "").strip()
    abs_clean = str(abstract_md or "").strip()
    if not rid:
        raise FailClosedError(ERR_INVALID_INPUT, "ref_id 不能为空")
    if len(abs_clean) < 60 or len(abs_clean) > 1500:
        raise FailClosedError(ERR_INVALID_INPUT, f"abstract_md 长度须在 60–1500 字之间（实收 {len(abs_clean)} 字）")
    if not str(exact_preconditions_md or "").strip() or not str(formulas_or_operators_md or "").strip():
        raise FailClosedError(ERR_INVALID_INPUT, "exact_preconditions_md 与 formulas_or_operators_md 不能为空")
    if read_depth not in ALLOWED_READ_DEPTHS:
        raise FailClosedError(ERR_INVALID_INPUT, f"非法 read_depth={read_depth!r}")
    if support_scope not in ALLOWED_SUPPORT_SCOPES:
        raise FailClosedError(ERR_INVALID_INPUT, f"非法 support_scope={support_scope!r}")
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
                question_id = excluded.question_id, title = excluded.title,
                abstract_md = excluded.abstract_md, exact_preconditions_md = excluded.exact_preconditions_md,
                formulas_or_operators_md = excluded.formulas_or_operators_md, read_depth = excluded.read_depth,
                support_scope = excluded.support_scope, source_citation = excluded.source_citation
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
        next_step_guidance=f"外藏参考卡 {rid} 已入库（标注为未复验外部先验，核销 {len(fulfilled)} 条查新单）。",
        data={"outcome": "CARD_PUBLISHED", "ref_id": rid, "is_unverified_external": True, "fulfilled_request_ids": fulfilled},
    )


# ============================================================================
# 2. library_chronicler（3 个：零外网零代码，1500 字总览 + Stage 3 冻结终稿）
# ============================================================================
def tool_get_chronicler_snapshot(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    question_id: str = "ALL",
    conference_id: str | None = None,
) -> dict[str, Any]:
    """零外网只读拉取硬账本、圆桌交锋纪要、全量已审 L3/L2、排雷视图与活跃悬赏缺口。"""
    enforce_role_tool_permission(conn, caller_role, "get_chronicler_snapshot", session_id=session_id)
    qf = str(question_id or "ALL").strip()
    p0 = conn.execute("SELECT * FROM parse0_contract WHERE contract_id = 'active'").fetchone()

    where_q = "" if qf.upper() == "ALL" else " AND question_id = ?"
    q_args: tuple[Any, ...] = () if qf.upper() == "ALL" else (qf,)

    l3 = [
        dict(r)
        for r in conn.execute(
            f"SELECT * FROM internal_research_ledger WHERE ledger_type = 'L3_VERIFIED' AND is_active = 1{where_q} ORDER BY question_id, entry_id",
            q_args,
        ).fetchall()
    ]
    l2 = [
        dict(r)
        for r in conn.execute(
            f"SELECT * FROM internal_research_ledger WHERE ledger_type = 'L2_FAILURE_RECORD' AND is_active = 1{where_q} ORDER BY question_id, entry_id",
            q_args,
        ).fetchall()
    ]
    ext = [
        dict(r)
        for r in conn.execute(
            f"SELECT * FROM external_literature_cards WHERE 1=1{where_q} ORDER BY ref_id",
            q_args,
        ).fetchall()
    ]
    gaps = [
        dict(r)
        for r in conn.execute(
            f"SELECT * FROM open_lemma_gaps WHERE status = 'OPEN'{where_q} ORDER BY question_id, created_at ASC",
            q_args,
        ).fetchall()
    ]
    conf = None
    if conference_id:
        crow = conn.execute("SELECT * FROM wave_conferences WHERE conference_id = ?", (str(conference_id),)).fetchone()
        if crow:
            conf = dict(crow)
    hard_ledger = build_wave_hard_ledger(conn, qf) if qf.upper() != "ALL" else None
    prev_survey = (
        conn.execute("SELECT * FROM subproblem_living_surveys WHERE question_id = ? ORDER BY revision DESC LIMIT 1", (qf,)).fetchone()
        if qf.upper() != "ALL"
        else None
    )

    return build_tool_receipt(
        conn=conn,
        tool_name="get_chronicler_snapshot",
        question_id=qf,
        next_step_guidance="请严守四条纪律：① <=1500 字导览索引；② 保留反例证据；③ Explicit Gaps 只写客观问题缺口、严禁泄露他派私有思路；④ 不直接核销悬赏。",
        data={
            "goal_and_completion_md": str(p0["goal_and_completion_md"]) if p0 else "",
            "required_questions": json.loads(p0["subquestions_json"]) if p0 else [],
            "hard_ledger": hard_ledger,
            "conference": conf,
            "previous_living_survey": dict(prev_survey) if prev_survey else None,
            "l3_verified": l3,
            "l2_failures": l2,
            "external_literature": ext,
            "open_lemma_gaps": gaps,
        },
    )


def tool_publish_living_survey(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    question_id: str,
    sec1_baseline_and_instruments_md: str,
    sec2_l3_lemma_tree_md: str,
    sec3_avoidance_radar_md: str,
    sec4_explicit_gaps_md: str,
    conference_id: str | None = None,
    trigger_reason: str = "WAVE_CONFERENCE",
) -> dict[str, Any]:
    """发布子题唯一《子题全局总览与明确缺口导览》（硬限 <= 1500 字），并联动圆桌推进至 ADJUDICATING。"""
    enforce_role_tool_permission(conn, caller_role, "publish_living_survey", session_id=session_id)
    qid = str(question_id or "").strip()
    qrow = conn.execute("SELECT question_id FROM subproblem_runtime_state WHERE question_id = ?", (qid,)).fetchone()
    if qrow is None:
        raise FailClosedError(ERR_NOT_FOUND, f"子题 {qid!r} 不存在")

    secs = [
        str(sec1_baseline_and_instruments_md or "").strip(),
        str(sec2_l3_lemma_tree_md or "").strip(),
        str(sec3_avoidance_radar_md or "").strip(),
        str(sec4_explicit_gaps_md or "").strip(),
    ]
    if any(len(s) < 2 for s in secs):
        raise FailClosedError(ERR_INVALID_INPUT, "总览四栏均不能为空")
    total_chars = sum(len(s) for s in secs)
    if total_chars > 1500:
        raise FailClosedError(
            ERR_INVALID_INPUT,
            f"《子题全局总览》总字数超限：{total_chars} > 1500 字！请精简为高密度导览索引（全量悬赏已存在 open_lemma_gaps，只需列 Top 索引编号）。",
        )

    now = utc_now_iso()
    with rw_immediate_tx(conn):
        max_rev_row = conn.execute(
            "SELECT COALESCE(MAX(revision), 0) AS m FROM subproblem_living_surveys WHERE question_id = ?",
            (qid,),
        ).fetchone()
        new_rev = int(max_rev_row["m"] or 0) + 1
        survey_id = f"sv_{qid.lower()}_r{new_rev}"
        conn.execute(
            """
            INSERT INTO subproblem_living_surveys(
                survey_id, question_id, revision,
                sec1_baseline_and_instruments_md, sec2_l3_lemma_tree_md,
                sec3_avoidance_radar_md, sec4_explicit_gaps_md,
                total_chars, trigger_reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (survey_id, qid, new_rev, secs[0], secs[1], secs[2], secs[3], total_chars, str(trigger_reason or "WAVE_CONFERENCE"), now),
        )
        if conference_id:
            conn.execute(
                """
                UPDATE wave_conferences
                SET linked_survey_id = ?, status = 'ADJUDICATING'
                WHERE conference_id = ? AND question_id = ? AND status = 'SURVEY_REFRESHING'
                """,
                (survey_id, str(conference_id), qid),
            )

    return build_tool_receipt(
        conn=conn,
        tool_name="publish_living_survey",
        question_id=qid,
        next_step_guidance=f"总览 {survey_id}（v{new_rev}，{total_chars}/1500 字）已发布；若绑定波次圆桌已切至 ADJUDICATING 唤醒裁判拍板。",
        data={"survey_id": survey_id, "question_id": qid, "revision": new_rev, "total_chars": total_chars},
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
    cancel_event: Any = None,
) -> dict[str, Any]:
    """零外网对内综述官导出 Stage 3 五件套并原子锁定外部不可变冻结目录。"""
    enforce_role_tool_permission(conn, caller_role, "export_stage3_final_delivery", session_id=session_id)
    res = export_stage3_deliverables_v03(
        conn,
        workspace_root=workspace_root,
        delivery_mode=delivery_mode,
        formal_paper_md=formal_paper_md,
        selected_l3_ids_by_question=selected_l3_ids_by_question,
        remaining_gaps_by_question=remaining_gaps_by_question,
        reproduction_candidate_nodes=reproduction_candidate_nodes,
        cancel_event=cancel_event,
    )
    return build_tool_receipt(
        conn=conn,
        tool_name="export_stage3_final_delivery",
        question_id="ALL",
        next_step_guidance=(
            f"五件套已导出 {res['delivery_id']} (SHA={res['delivery_sha256'][:12]}) 并原子锁定外部不可变冻结目录；"
            "现交由 library_verifier 只读该冻结副本核验并一步原子终签 CLOSED_VERIFIED。"
        ),
        data=res,
    )


# ============================================================================
# 3. conference_chair（3 个）+ lineage_companion 圆桌发言（1 个）
# ============================================================================
def tool_submit_conference_statement(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    conference_id: str,
    node_id: str,
    round_no: int,
    statement_md: str,
    target_node_ids: list[str] | None = None,
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "submit_conference_statement", session_id=session_id, node_id=node_id)
    res = append_conference_statement(
        conn,
        conference_id=conference_id,
        node_id=node_id,
        round_no=round_no,
        statement_md=statement_md,
        target_node_ids=target_node_ids,
    )
    return build_tool_receipt(
        conn=conn,
        tool_name="submit_conference_statement",
        question_id="ALL",
        node_id=node_id,
        next_step_guidance=f"第 {round_no} 轮圆桌发言已记录（会议现处于 {res['status']}）。",
        data=res,
    )


def tool_get_conference_dossier(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    conference_id: str,
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "get_conference_dossier", session_id=session_id)
    conf = conn.execute("SELECT * FROM wave_conferences WHERE conference_id = ?", (str(conference_id),)).fetchone()
    if conf is None:
        raise FailClosedError(ERR_NOT_FOUND, f"圆桌会议 {conference_id!r} 不存在")
    qid = str(conf["question_id"])
    hard_ledger = build_wave_hard_ledger(conn, qid)
    sv = conn.execute(
        "SELECT * FROM subproblem_living_surveys WHERE question_id = ? ORDER BY revision DESC LIMIT 1",
        (qid,),
    ).fetchone()
    return build_tool_receipt(
        conn=conn,
        tool_name="get_conference_dossier",
        question_id=qid,
        next_step_guidance=(
            "请审阅 2 轮交锋并调用 record_conference_minutes 落盘纪要。"
            if str(conf["status"]) in ("ROUND_1_CRITIQUE", "ROUND_2_REBUTTAL")
            else "请盯着最新《子题全局总览》中的 Explicit Gaps 谨慎调用 submit_conference_verdict 签发树结构调整单。"
        ),
        data={
            "conference": {
                "conference_id": str(conf["conference_id"]),
                "question_id": qid,
                "wave_no": int(conf["wave_no"]),
                "status": str(conf["status"]),
                "participants": json.loads(conf["participant_nodes_json"] or "[]"),
                "critiques_ledger": json.loads(conf["critiques_ledger_json"] or "[]"),
                "minutes_md": str(conf["minutes_md"] or ""),
                "linked_survey_id": conf["linked_survey_id"],
            },
            "hard_ledger": hard_ledger,
            "latest_living_survey": dict(sv) if sv else None,
        },
    )


def tool_record_conference_minutes(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    conference_id: str,
    minutes_md: str,
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "record_conference_minutes", session_id=session_id)
    conf = conn.execute("SELECT * FROM wave_conferences WHERE conference_id = ?", (str(conference_id),)).fetchone()
    if conf is None:
        raise FailClosedError(ERR_NOT_FOUND, f"圆桌会议 {conference_id!r} 不存在")
    if str(conf["status"]) not in ("ROUND_1_CRITIQUE", "ROUND_2_REBUTTAL"):
        raise FailClosedError(ERR_LOCKED, f"会议 {conference_id!r} 状态为 {conf['status']}，不可落盘第 2 拍纪要")
    clean_min = str(minutes_md or "").strip()
    if len(clean_min) < 30:
        raise FailClosedError(ERR_INVALID_INPUT, "圆桌纪要 minutes_md 至少 30 字")
    with rw_immediate_tx(conn):
        conn.execute(
            "UPDATE wave_conferences SET minutes_md = ?, status = 'SURVEY_REFRESHING' WHERE conference_id = ?",
            (clean_min[:4000], str(conference_id)),
        )
    return build_tool_receipt(
        conn=conn,
        tool_name="record_conference_minutes",
        question_id=str(conf["question_id"]),
        next_step_guidance="第 2 拍圆桌交锋纪要已落盘并切至 SURVEY_REFRESHING，待综述官刷新总览后将原地唤醒你执行第 4 拍拍板。",
        data={"conference_id": str(conference_id), "status": "SURVEY_REFRESHING"},
    )


def tool_submit_conference_verdict(
    conn: sqlite3.Connection,
    workspace_root: str,
    caller_role: str,
    session_id: str,
    conference_id: str,
    actions: list[dict[str, Any]],
    rationale_md: str,
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "submit_conference_verdict", session_id=session_id)
    res = submit_wave_verdict_decision(
        conn,
        workspace_root=workspace_root,
        conference_id=conference_id,
        verdict_payload={"actions": actions, "rationale_md": rationale_md},
        rationale_md=rationale_md,
    )
    return build_tool_receipt(
        conn=conn,
        tool_name="submit_conference_verdict",
        question_id=str(res.get("question_id") or "ALL"),
        next_step_guidance=(
            f"宏观调整单已提交并进入 {res['status']}（提案 {res.get('proposal_id')} 待人类 2 分钟把关）。"
            if res.get("status") == "PENDING_HUMAN_APPROVAL"
            else f"AUTOPILOT 低风险宏观调整单已落地完成（执行 {len(res.get('executed') or [])} 项，跳过 {len(res.get('skipped') or [])} 项）。"
        ),
        data=res,
    )
