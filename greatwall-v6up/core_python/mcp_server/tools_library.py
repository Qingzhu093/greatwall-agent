"""长城 V6-Up (v3.0) 中央图书馆 8 个单一职责窄工具（library_surveyor 3 个 + library_verifier 5 个）。"""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from .control_plane_service import (
    export_stage3_deliverables,
    stage_blind_review_sandbox,
)
from .db_schema import (
    ALLOWED_CLAIMED_EDGE_TYPES,
    ALLOWED_FINAL_VERDICTS,
    ALLOWED_GOAL_COVERAGES,
    ALLOWED_L3_ENTRY_KINDS,
    ALLOWED_READ_DEPTHS,
    ALLOWED_STAGE1_VERDICTS,
    ALLOWED_SUPPORT_SCOPES,
    ALLOWED_SURVEY_OUTCOMES,
    ERR_CONFLICT,
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
    load_runtime_config,
    next_prefixed_id,
)

# ==============================================================================
# 角色 4：library_surveyor（3 个窄工具）
# ==============================================================================


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


# ==============================================================================
# 角色 5：library_verifier（5 个窄工具，独立空白盲审沙箱跑证）
# ==============================================================================


def _require_non_self_review(
    session_id: str,
    proposer_session_id: str,
    *,
    conn: sqlite3.Connection | None = None,
    source_node_id: str = "",
) -> None:
    sid = str(session_id or "").strip()
    if not sid:
        raise FailClosedError(ERR_CONFLICT, "SELF_REVIEW_FORBIDDEN: 审稿会话缺少合法 session_id，严禁匿名自审！")
    if sid == str(proposer_session_id or "").strip():
        raise FailClosedError(ERR_CONFLICT, "SELF_REVIEW_FORBIDDEN: 异会话盲审强拦截，严禁提议/打捞会话自审自己提交的手稿或引理！")
    if conn is not None and source_node_id:
        prior = conn.execute(
            "SELECT 1 FROM epistemic_edges WHERE source_id = ? AND session_id = ? AND edge_track = 'FACT_LOG' LIMIT 1",
            (source_node_id, sid),
        ).fetchone()
        if prior is not None:
            raise FailClosedError(ERR_CONFLICT, "SELF_REVIEW_FORBIDDEN: 异会话盲审强拦截，严禁曾参与该节点探索或交接的会话自审该节点手稿！")


def tool_get_blind_manuscript(
    conn: sqlite3.Connection,
    workspace_root: str,
    caller_role: str,
    session_id: str,
    review_id: str,
) -> dict[str, Any]:
    """Stage 1 盲态拉取：在独立空白沙箱中仅挂载 A 栏、脱敏代码/证明/反例文件与客观 [Obs###]。"""
    enforce_role_tool_permission(conn, caller_role, "get_blind_manuscript", session_id=session_id)
    rev = conn.execute("SELECT * FROM review_queue WHERE review_id = ?", (review_id,)).fetchone()
    if rev is None:
        raise FailClosedError(ERR_NOT_FOUND, f"盲审单 {review_id!r} 不存在")
    if str(rev["review_status"]) != "STAGE1_BLIND":
        raise FailClosedError(ERR_LOCKED, f"盲审单 {review_id!r} 当前状态为 {rev['review_status']}，Stage 1 盲态拉取仅限 STAGE1_BLIND")
    _require_non_self_review(session_id, str(rev["proposer_session_id"]), conn=conn, source_node_id=str(rev["source_node_id"] or ""))

    staged = stage_blind_review_sandbox(conn, workspace_root=workspace_root, review_id=review_id)
    obs_ids = json.loads(rev["bound_obs_ids_json"] or "[]")
    obs_list: list[dict[str, Any]] = []
    if obs_ids:
        ph = ",".join("?" for _ in obs_ids)
        for o in conn.execute(
            f"SELECT obs_id, instrument_id, instrument_version, tier, obs_status, tracks_json, details_text FROM observations WHERE obs_id IN ({ph})",
            tuple(obs_ids),
        ).fetchall():
            obs_list.append(
                {
                    "obs_id": str(o["obs_id"]),
                    "instrument_id": str(o["instrument_id"]),
                    "instrument_version": int(o["instrument_version"]),
                    "tier": str(o["tier"]),
                    "obs_status": str(o["obs_status"]),
                    "tracks": json.loads(o["tracks_json"] or "{}"),
                    "details": str(o["details_text"] or ""),
                }
            )

    rev_spec = int(rev["spec_revision"] or 0) if "spec_revision" in rev.keys() else 0
    return build_tool_receipt(
        conn=conn,
        tool_name="get_blind_manuscript",
        question_id=str(rev["question_id"]),
        next_step_guidance=f"请按手稿绑定口径 spec_revision=v{rev_spec} 在独立空白盲审沙箱内实跑验证脚本/SymPy/Lean 4，排查 7 类结构漏洞并填写 Evidence Ledger，调 submit_stage1_blind_ledger。",
        data={
            "review_id": review_id,
            "question_id": str(rev["question_id"]),
            "source_type": str(rev["source_type"]),
            "spec_revision": rev_spec,
            "manuscript_title": str(rev["manuscript_title"]),
            "column_a_snapshot_md": str(rev["column_a_snapshot_md"]),
            "sanitized_code_diff_md": str(rev["sanitized_code_diff_md"]),
            "observations": obs_list,
            "blind_sandbox_abs_path": staged["sandbox_abs_path"],
            "staged_files": staged["staged_files"],
        },
    )


def _archive_to_l2_and_seal(
    conn: sqlite3.Connection,
    *,
    rev: sqlite3.Row,
    l2_category: str,
    title: str,
    abstract_md: str,
    refuted_scope: str,
    now: str,
) -> str:
    entry_id = next_prefixed_id(conn, "internal_research_ledger", "entry_id", "L2-")
    conn.execute(
        """
        INSERT INTO internal_research_ledger(
            entry_id, question_id, ledger_type, l3_entry_kind, goal_coverage, l2_category,
            title, abstract_md, exact_verified_scope_md, exact_refuted_scope_md,
            body_proof_or_code_md, bound_obs_ids_json, verified_review_id, is_active, created_at
        ) VALUES (?, ?, 'L2_FAILURE_RECORD', NULL, NULL, ?, ?, ?, NULL, ?, ?, ?, ?, 1, ?)
        """,
        (
            entry_id,
            str(rev["question_id"]),
            l2_category,
            title or str(rev["manuscript_title"]),
            abstract_md or refuted_scope,
            refuted_scope,
            str(rev["column_a_snapshot_md"] or ""),
            str(rev["bound_obs_ids_json"] or "[]"),
            str(rev["review_id"]),
            now,
        ),
    )
    conn.execute(
        "UPDATE lineage_nodes SET node_status = 'SEALED', updated_at = ? WHERE node_id = ?",
        (now, str(rev["source_node_id"])),
    )
    return entry_id


def _apply_revise_or_exhaust(
    conn: sqlite3.Connection,
    *,
    rev: sqlite3.Row,
    revision_items: list[str],
    reason_text: str,
    now: str,
) -> dict[str, Any]:
    """Stage 1 与 Stage 2 共用唯一 revise_count（<=2 轮退回原分支 ACTIVE_REVISING；第 3 次直入 L2 并置 SEALED）。"""
    cfg = load_runtime_config()
    max_revise = int(cfg.get("max_revise_rounds_before_l2", 2))
    node = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (rev["source_node_id"],)).fetchone()
    cur_revise = int(node["revise_count"] or 0) if node is not None else 0

    if cur_revise < max_revise and node is not None:
        new_revise = cur_revise + 1
        conn.execute(
            """
            UPDATE review_queue
            SET review_status = 'CLOSED_REVISE', final_verdict = 'REVISE',
                final_locked_at = ?, revision_requests_json = ?, updated_at = ?
            WHERE review_id = ?
            """,
            (now, json.dumps(revision_items, ensure_ascii=False), now, rev["review_id"]),
        )
        # 原分支从 PENDING_REVIEW 恢复为 ACTIVE_REVISING（供伴随重写看板置顶高亮异议并返工，期间严禁 Auditor 插手！）
        conn.execute(
            """
            UPDATE lineage_nodes
            SET node_status = 'ACTIVE_REVISING', revise_count = ?, last_revision_requests_json = ?, updated_at = ?
            WHERE node_id = ?
            """,
            (new_revise, json.dumps(revision_items, ensure_ascii=False), now, node["node_id"]),
        )
        # 同时清理该节点的旧看板，强制伴随在返工前按新 REVISE 异议重压缩行前看板
        conn.execute("DELETE FROM lineage_briefings WHERE node_id = ?", (node["node_id"],))
        return {"exhausted_to_l2": False, "revise_count": new_revise, "node_status": "ACTIVE_REVISING"}

    # 第 3 次送审仍无法通过：服务端直接结案置 SEALED 并写入 L2(UNRESOLVED_OBJECTION)
    conn.execute(
        """
        UPDATE review_queue
        SET review_status = 'CLOSED_REFUTED', final_verdict = 'REFUTED',
            final_locked_at = ?, revision_requests_json = ?, updated_at = ?
        WHERE review_id = ?
        """,
        (now, json.dumps(revision_items, ensure_ascii=False), now, rev["review_id"]),
    )
    l2_id = _archive_to_l2_and_seal(
        conn,
        rev=rev,
        l2_category="UNRESOLVED_OBJECTION",
        title=f"[REVISE超限] {rev['manuscript_title']}",
        abstract_md=reason_text or "; ".join(revision_items) or "超过最大返工轮次仍未解决审稿异议",
        refuted_scope=reason_text or "; ".join(revision_items) or "返工超限未解异议",
        now=now,
    )
    return {"exhausted_to_l2": True, "revise_count": cur_revise + 1, "created_l2_id": l2_id, "node_status": "SEALED"}


def tool_submit_stage1_blind_ledger(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    review_id: str,
    question_id: str,
    ledger_items: list[dict[str, Any]],
    stage1_verdict: str,
    revision_or_refutation_reason: str | None = None,
    exact_refuted_scope_md: str | None = None,
) -> dict[str, Any]:
    """锁定 Stage 1 不可逆 Evidence Ledger，并按 PASS / REVISE / REFUTED 精准分流。"""
    enforce_role_tool_permission(conn, caller_role, "submit_stage1_blind_ledger", session_id=session_id)
    rev = conn.execute("SELECT * FROM review_queue WHERE review_id = ?", (review_id,)).fetchone()
    if rev is None:
        raise FailClosedError(ERR_NOT_FOUND, f"盲审单 {review_id!r} 不存在")
    if rev["stage1_locked_at"] is not None or str(rev["review_status"]) != "STAGE1_BLIND":
        raise FailClosedError(ERR_LOCKED, f"STAGE1_LEDGER_IMMUTABLE: {review_id!r} Stage 1 已锁定或已完结")
    if str(rev["question_id"]) != str(question_id):
        raise FailClosedError(ERR_INVALID_INPUT, f"question_id 不匹配：{question_id!r} != {rev['question_id']!r}")
    _require_non_self_review(session_id, str(rev["proposer_session_id"]), conn=conn, source_node_id=str(rev["source_node_id"] or ""))

    if not isinstance(ledger_items, list) or not ledger_items:
        raise FailClosedError(ERR_INVALID_INPUT, "ledger_items 必须为非空 Evidence Ledger 列表")
    for idx, it in enumerate(ledger_items):
        if not isinstance(it, dict) or not str(it.get("claim", "")).strip() or not str(it.get("evidence_location_and_quote", "")).strip():
            raise FailClosedError(ERR_INVALID_INPUT, f"ledger_items[{idx}] 缺少 claim 或 evidence_location_and_quote")

    sv = str(stage1_verdict or "").strip().upper()
    if sv not in ALLOWED_STAGE1_VERDICTS:
        raise FailClosedError(ERR_INVALID_INPUT, f"stage1_verdict 仅允许 {sorted(ALLOWED_STAGE1_VERDICTS)}，实收 {stage1_verdict!r}")

    now = utc_now_iso()
    ledger_json = json.dumps(ledger_items, ensure_ascii=False)

    if sv == "PASS":
        with rw_immediate_tx(conn):
            conn.execute(
                """
                UPDATE review_queue
                SET stage1_ledger_json = ?, stage1_locked_at = ?, review_status = 'STAGE2_UNBLIND', updated_at = ?
                WHERE review_id = ?
                """,
                (ledger_json, now, now, review_id),
            )
        return build_tool_receipt(
            conn=conn,
            tool_name="submit_stage1_blind_ledger",
            question_id=question_id,
            next_step_guidance="Stage 1 盲审账本已永久锁定并 PASS！请立即调用 get_unblinded_manuscript_and_peers 进入 Stage 2 解盲横审。",
            data={"review_id": review_id, "stage1_verdict": "PASS", "review_status": "STAGE2_UNBLIND"},
        )

    if sv == "REVISE":
        reason = str(revision_or_refutation_reason or "").strip()
        if not reason:
            raise FailClosedError(ERR_INVALID_INPUT, "Stage 1 判 REVISE 必须提供具体可操作的 revision_or_refutation_reason")
        with rw_immediate_tx(conn):
            conn.execute(
                "UPDATE review_queue SET stage1_ledger_json = ?, stage1_locked_at = ?, updated_at = ? WHERE review_id = ?",
                (ledger_json, now, now, review_id),
            )
            r_info = _apply_revise_or_exhaust(conn, rev=rev, revision_items=[reason], reason_text=reason, now=now)
        return build_tool_receipt(
            conn=conn,
            tool_name="submit_stage1_blind_ledger",
            question_id=question_id,
            next_step_guidance=(
                f"Stage 1 判 REVISE 但已满最大返工轮次，已直接归档 L2 ({r_info.get('created_l2_id')}) 并置 SEALED。"
                if r_info["exhausted_to_l2"]
                else f"Stage 1 判 REVISE（累计返工 {r_info['revise_count']} 次），已将异议退回原分支切回 ACTIVE_REVISING。"
            ),
            data={"review_id": review_id, "stage1_verdict": "REVISE", **r_info},
        )

    # REFUTED 短路直入 L2
    reason = str(revision_or_refutation_reason or "").strip()
    scope_ref = str(exact_refuted_scope_md or "").strip()
    if not reason or not scope_ref:
        raise FailClosedError(ERR_INVALID_INPUT, "Stage 1 判 REFUTED 必须填写 revision_or_refutation_reason 与 exact_refuted_scope_md")
    with rw_immediate_tx(conn):
        conn.execute(
            """
            UPDATE review_queue
            SET stage1_ledger_json = ?, stage1_locked_at = ?, final_locked_at = ?,
                review_status = 'CLOSED_REFUTED', final_verdict = 'REFUTED', updated_at = ?
            WHERE review_id = ?
            """,
            (ledger_json, now, now, now, review_id),
        )
        l2_id = _archive_to_l2_and_seal(
            conn,
            rev=rev,
            l2_category="REFUTED",
            title=f"[证伪否定] {rev['manuscript_title']}",
            abstract_md=reason,
            refuted_scope=scope_ref,
            now=now,
        )
    return build_tool_receipt(
        conn=conn,
        tool_name="submit_stage1_blind_ledger",
        question_id=question_id,
        next_step_guidance=f"Stage 1 实测证伪短路结案，已归档 {l2_id} (REFUTED) 并置分支 SEALED（已解锁 Auditor 异会话打捞）。",
        data={"review_id": review_id, "stage1_verdict": "REFUTED", "created_l2_id": l2_id, "node_status": "SEALED"},
    )


def tool_get_unblinded_manuscript_and_peers(
    conn: sqlite3.Connection,
    workspace_root: str,
    caller_role: str,
    session_id: str,
    review_id: str,
) -> dict[str, Any]:
    """Stage 2 解盲横审拉取，或 Stage 3 终核模式 (`STAGE3_FINAL_AUDIT:<delivery_id>`) 五件套核查。"""
    enforce_role_tool_permission(conn, caller_role, "get_unblinded_manuscript_and_peers", session_id=session_id)

    # Stage 3 终核模式
    if str(review_id).startswith("STAGE3_FINAL_AUDIT:"):
        target_did = str(review_id).split(":", 1)[1].strip()
        closure = conn.execute("SELECT * FROM project_closure_state WHERE id = 1").fetchone()
        if closure is None or str(closure["status"]) != "DELIVERY_EXPORTED":
            raise FailClosedError(ERR_LOCKED, "当前项目未处于 DELIVERY_EXPORTED 待终核状态")
        if not target_did or target_did != str(closure["latest_delivery_id"] or ""):
            raise FailClosedError(
                ERR_CONFLICT,
                f"终核版本不匹配：请求 {target_did!r} != 当前最新导出版本 {closure['latest_delivery_id']!r}",
            )
        staged = stage_blind_review_sandbox(conn, workspace_root=workspace_root, review_id=review_id)
        l3_scopes = [
            dict(r)
            for r in conn.execute(
                """
                SELECT entry_id, question_id, l3_entry_kind, goal_coverage, title, exact_verified_scope_md, exact_refuted_scope_md
                FROM internal_research_ledger
                WHERE ledger_type = 'L3_VERIFIED' AND is_active = 1
                ORDER BY question_id, entry_id
                """
            ).fetchall()
        ]
        return build_tool_receipt(
            conn=conn,
            tool_name="get_unblinded_manuscript_and_peers",
            question_id="ALL",
            next_step_guidance="请在空白沙箱核查五件套总报告未夸大任何 L3 的 exact_verified_scope_md 且复现脚本一致，然后调 submit_stage2_unblind_verdict 落签 ACCEPT 或 REVISE。",
            data={
                "mode": "STAGE3_FINAL_AUDIT",
                "review_id": review_id,
                "delivery_id": target_did,
                "delivery_sha256": str(closure["latest_delivery_sha256"]),
                "blind_sandbox_abs_path": staged["sandbox_abs_path"],
                "staged_files": staged["staged_files"],
                "verified_l3_scopes": l3_scopes,
            },
        )

    rev = conn.execute("SELECT * FROM review_queue WHERE review_id = ?", (review_id,)).fetchone()
    if rev is None:
        raise FailClosedError(ERR_NOT_FOUND, f"审稿单 {review_id!r} 不存在")
    if str(rev["review_status"]) != "STAGE2_UNBLIND" or rev["stage1_locked_at"] is None:
        raise FailClosedError(ERR_LOCKED, f"审稿单 {review_id!r} 尚未通过并锁定 Stage 1 盲审，禁止提前解盲")
    _require_non_self_review(session_id, str(rev["proposer_session_id"]), conn=conn, source_node_id=str(rev["source_node_id"] or ""))

    qid = str(rev["question_id"])
    peer_l3 = [
        dict(r)
        for r in conn.execute(
            """
            SELECT entry_id, l3_entry_kind, goal_coverage, title, abstract_md, exact_verified_scope_md
            FROM internal_research_ledger
            WHERE question_id = ? AND ledger_type = 'L3_VERIFIED' AND is_active = 1
            ORDER BY entry_id
            """,
            (qid,),
        ).fetchall()
    ]
    peer_in_review = [
        dict(r)
        for r in conn.execute(
            """
            SELECT review_id, source_type, review_status, manuscript_title
            FROM review_queue
            WHERE question_id = ? AND review_id != ? AND review_status IN ('STAGE1_BLIND', 'STAGE2_UNBLIND')
            """,
            (qid, review_id),
        ).fetchall()
    ]
    # 参考性 FACT_LOG（明确标注仅作参考，严禁因常规公理缺 READ 边而拒稿）
    fact_reads = [
        dict(r)
        for r in conn.execute(
            "SELECT source_id, target_id, edge_type, created_at FROM epistemic_edges WHERE source_id = ? AND edge_track = 'FACT_LOG' ORDER BY created_at ASC",
            (rev["source_node_id"],),
        ).fetchall()
    ]
    declared_edges = [
        dict(r)
        for r in conn.execute(
            "SELECT source_id, target_id, edge_type FROM epistemic_edges WHERE edge_track = 'CLAIM_DECLARED' AND source_id IN (SELECT obs_id FROM observations WHERE node_id = ?)",
            (rev["source_node_id"],),
        ).fetchall()
    ]

    p0_rev_row = conn.execute(
        "SELECT latest_spec_revision, latest_ruling_summary_md FROM parse0_contract WHERE contract_id = 'active'"
    ).fetchone()
    latest_spec_rev = int(p0_rev_row["latest_spec_revision"] or 0) if p0_rev_row else 0
    latest_ruling_summary = str(p0_rev_row["latest_ruling_summary_md"] or "") if p0_rev_row else ""
    rev_spec = int(rev["spec_revision"] or 0) if "spec_revision" in rev.keys() else 0
    spec_outdated = rev_spec < latest_spec_rev

    return build_tool_receipt(
        conn=conn,
        tool_name="get_unblinded_manuscript_and_peers",
        question_id=qid,
        next_step_guidance=(
            f"注意：该手稿绑定旧口径 v{rev_spec} < 最新裁决口径 v{latest_spec_rev}；若成立请标明成立口径（exact_verified_scope_md）且禁标最新 FULL_GOAL！"
            if spec_outdated
            else "请结合 B 栏、同题 Cross-Draft 快照与参考性 FACT_LOG，调 submit_stage2_unblind_verdict 下达终审裁决与精确边界。"
        ),
        data={
            "review_id": review_id,
            "question_id": qid,
            "spec_revision": rev_spec,
            "latest_spec_revision": latest_spec_rev,
            "spec_revision_outdated": spec_outdated,
            "latest_ruling_summary_md": latest_ruling_summary,
            "column_b_snapshot_md": str(rev["column_b_snapshot_md"]),
            "stage1_ledger": json.loads(rev["stage1_ledger_json"] or "[]"),
            "peer_l3_entries": peer_l3,
            "peer_in_review": peer_in_review,
            "informational_fact_log_reads": fact_reads,
            "declared_reference_edges": declared_edges,
        },
    )


def tool_submit_stage2_unblind_verdict(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    review_id: str,
    final_verdict: str,
    l3_entry_kind: str | None = None,
    goal_coverage: str | None = None,
    is_equivalent_reduction: bool = False,
    title: str = "",
    abstract_md: str = "",
    exact_verified_scope_md: str | None = None,
    exact_refuted_scope_md: str | None = None,
    revision_requests: list[str] | None = None,
    cross_draft_comparison_notes: str = "",
    cross_pollinate_nomination: dict[str, Any] | None = None,
    edge_type_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Stage 2 三态终判（及 Stage 3 终核落签 `STAGE3_FINAL_AUDIT:<delivery_id>`）。"""
    enforce_role_tool_permission(conn, caller_role, "submit_stage2_unblind_verdict", session_id=session_id)
    fv = str(final_verdict or "").strip().upper()
    if fv not in ALLOWED_FINAL_VERDICTS:
        raise FailClosedError(ERR_INVALID_INPUT, f"非法 final_verdict={final_verdict!r}，仅允许 {sorted(ALLOWED_FINAL_VERDICTS)}")

    now = utc_now_iso()

    # 分支 1：Stage 3 绑定版本终核模式（防“审 A 放 B”）
    if str(review_id).startswith("STAGE3_FINAL_AUDIT:"):
        target_did = str(review_id).split(":", 1)[1].strip()
        closure = conn.execute("SELECT * FROM project_closure_state WHERE id = 1").fetchone()
        if closure is None or str(closure["status"]) != "DELIVERY_EXPORTED":
            raise FailClosedError(ERR_LOCKED, "当前项目不处于 DELIVERY_EXPORTED 状态")
        if not target_did or target_did != str(closure["latest_delivery_id"] or ""):
            raise FailClosedError(
                ERR_CONFLICT,
                f"终核落签拦截：审定版本 {target_did!r} != 当前最新导出版本 {closure['latest_delivery_id']!r}（已过期）",
            )
        if fv in ("ACCEPT", "ACCEPT_NARROWED"):
            with rw_immediate_tx(conn):
                conn.execute(
                    """
                    UPDATE project_closure_state
                    SET verifier_audited_delivery_id = ?,
                        verifier_audited_delivery_sha256 = ?,
                        verifier_final_audit_passed = 1,
                        updated_at = ?
                    WHERE id = 1
                    """,
                    (target_did, str(closure["latest_delivery_sha256"]), now),
                )
            return build_tool_receipt(
                conn=conn,
                tool_name="submit_stage2_unblind_verdict",
                question_id="ALL",
                next_step_guidance=f"五件套版本 {target_did} 已通过盲审终核绑定落签！现可由 supervisory_committee 签发 CLOSURE_GATE(PASSED) 晋升 CLOSED_VERIFIED。",
                data={
                    "mode": "STAGE3_FINAL_AUDIT",
                    "delivery_id": target_did,
                    "delivery_sha256": str(closure["latest_delivery_sha256"]),
                    "verifier_final_audit_passed": True,
                },
            )
        # REVISE / REFUTED 退回馆员修正并重导：切换 status='REVISION_REQUESTED' 阻断审稿器死循环重审同一稿
        rev_notes = "; ".join(str(x) for x in (revision_requests or []) if str(x).strip()) or str(abstract_md or "请修正边界表述与复现一致性")
        with rw_immediate_tx(conn):
            conn.execute(
                """
                UPDATE project_closure_state
                SET status = 'REVISION_REQUESTED',
                    verifier_final_audit_passed = 0,
                    verifier_revision_notes = ?,
                    updated_at = ?
                WHERE id = 1
                """,
                (rev_notes[:2000], now),
            )
        return build_tool_receipt(
            conn=conn,
            tool_name="submit_stage2_unblind_verdict",
            question_id="ALL",
            next_step_guidance="终核发现边界夸大或复现不一致，已置为 REVISION_REQUESTED 派回 library_surveyor 修正并重新导出新版本五件套。",
            data={
                "mode": "STAGE3_FINAL_AUDIT",
                "delivery_id": target_did,
                "closure_status": "REVISION_REQUESTED",
                "verifier_final_audit_passed": False,
                "revision_requests": revision_requests or [rev_notes],
            },
        )

    # 分支 2：常规 Stage 2 盲审终判
    rev = conn.execute("SELECT * FROM review_queue WHERE review_id = ?", (review_id,)).fetchone()
    if rev is None:
        raise FailClosedError(ERR_NOT_FOUND, f"审稿单 {review_id!r} 不存在")
    if str(rev["review_status"]) != "STAGE2_UNBLIND" or rev["stage1_locked_at"] is None:
        raise FailClosedError(ERR_LOCKED, f"审稿单 {review_id!r} 未处于 STAGE2_UNBLIND，不可下达终判")
    _require_non_self_review(session_id, str(rev["proposer_session_id"]), conn=conn, source_node_id=str(rev["source_node_id"] or ""))

    # 由服务端权威从 review_queue 派生 question_id（杜绝串题入库）
    qid = str(rev["question_id"])
    bound_obs = json.loads(rev["bound_obs_ids_json"] or "[]")

    if fv == "REVISE":
        req_items = [str(x).strip() for x in (revision_requests or []) if str(x).strip()]
        if not req_items:
            raise FailClosedError(ERR_INVALID_INPUT, "Stage 2 判 REVISE 必须提供非空 revision_requests 具体修改要求")
        with rw_immediate_tx(conn):
            r_info = _apply_revise_or_exhaust(conn, rev=rev, revision_items=req_items, reason_text="; ".join(req_items), now=now)
        return build_tool_receipt(
            conn=conn,
            tool_name="submit_stage2_unblind_verdict",
            question_id=qid,
            next_step_guidance=(
                f"Stage 2 判 REVISE 但已满最大返工轮次，已归档 L2 ({r_info.get('created_l2_id')}) 并置 SEALED。"
                if r_info["exhausted_to_l2"]
                else f"Stage 2 判 REVISE（累计返工 {r_info['revise_count']} 次），原分支已切回 ACTIVE_REVISING 返工。"
            ),
            data={"review_id": review_id, "final_verdict": "REVISE", **r_info},
        )

    if fv == "REFUTED":
        ref_scope = str(exact_refuted_scope_md or "").strip()
        if not ref_scope:
            raise FailClosedError(ERR_INVALID_INPUT, "Stage 2 判 REFUTED 必须填写 exact_refuted_scope_md")
        with rw_immediate_tx(conn):
            conn.execute(
                """
                UPDATE review_queue
                SET review_status = 'CLOSED_REFUTED', final_verdict = 'REFUTED', final_locked_at = ?, updated_at = ?
                WHERE review_id = ?
                """,
                (now, now, review_id),
            )
            l2_id = _archive_to_l2_and_seal(
                conn,
                rev=rev,
                l2_category="REFUTED",
                title=str(title or "").strip() or f"[证伪否定] {rev['manuscript_title']}",
                abstract_md=str(abstract_md or "").strip() or ref_scope,
                refuted_scope=ref_scope,
                now=now,
            )
        return build_tool_receipt(
            conn=conn,
            tool_name="submit_stage2_unblind_verdict",
            question_id=qid,
            next_step_guidance=f"Stage 2 判 REFUTED，已入库 {l2_id} 并置原分支 SEALED（解锁 Auditor 异会话打捞）。",
            data={"review_id": review_id, "final_verdict": "REFUTED", "created_l2_id": l2_id},
        )

    # ACCEPT / ACCEPT_NARROWED -> 严格写入 L3_VERIFIED
    kind_u = str(l3_entry_kind or "").strip().upper()
    cov_u = str(goal_coverage or "").strip().upper()
    if kind_u not in ALLOWED_L3_ENTRY_KINDS:
        raise FailClosedError(ERR_INVALID_INPUT, f"ACCEPT* 必须提供合法 l3_entry_kind {sorted(ALLOWED_L3_ENTRY_KINDS)}，实收 {l3_entry_kind!r}")
    if cov_u not in ALLOWED_GOAL_COVERAGES:
        raise FailClosedError(ERR_INVALID_INPUT, f"ACCEPT* 必须提供合法 goal_coverage {sorted(ALLOWED_GOAL_COVERAGES)}，实收 {goal_coverage!r}")
    if (fv == "ACCEPT_NARROWED" or bool(is_equivalent_reduction)) and cov_u == "FULL_GOAL":
        raise FailClosedError(
            ERR_INVALID_INPUT,
            "防伪完成硬护栏：ACCEPT_NARROWED 缩窄特例或 is_equivalent_reduction=true 伪等价归约严禁标为 FULL_GOAL！请设为 PARTIAL_OR_LEMMA 或 EQUIVALENT_REDUCTION。",
        )
    p0_rev_row = conn.execute(
        "SELECT latest_spec_revision FROM parse0_contract WHERE contract_id = 'active'"
    ).fetchone()
    latest_spec_rev = int(p0_rev_row["latest_spec_revision"] or 0) if p0_rev_row else 0
    rev_spec = int(rev["spec_revision"] or 0) if "spec_revision" in rev.keys() else 0
    if rev_spec < latest_spec_rev and cov_u == "FULL_GOAL":
        raise FailClosedError(
            ERR_INVALID_INPUT,
            f"版本口径防伪完成硬护栏：该手稿绑定旧口径 spec_revision=v{rev_spec} < 最新公开裁决 v{latest_spec_rev}，禁止标为最新 FULL_GOAL！请在 exact_verified_scope_md 标明成立口径（如 v{rev_spec}）并设为 PARTIAL_OR_LEMMA。",
        )
    clean_title = str(title or "").strip()
    clean_abs = str(abstract_md or "").strip()
    clean_scope = str(exact_verified_scope_md or "").strip()
    if not clean_title or len(clean_abs) < 40 or not clean_scope:
        raise FailClosedError(ERR_INVALID_INPUT, "ACCEPT* 必须填写非空 title、>=40 字独立 abstract_md 及 exact_verified_scope_md")

    with rw_immediate_tx(conn):
        # 1. 处理 edge_type_overrides（升级或调整上游承重前提边）
        if isinstance(edge_type_overrides, dict):
            for ref_dst, new_etype in edge_type_overrides.items():
                nt = str(new_etype).strip().upper()
                if nt not in ALLOWED_CLAIMED_EDGE_TYPES:
                    raise FailClosedError(
                        ERR_INVALID_INPUT,
                        f"edge_type_overrides 包含非法边类型: {new_etype!r}，仅允许 {sorted(ALLOWED_CLAIMED_EDGE_TYPES)}",
                    )
                if bound_obs:
                    oph = ",".join("?" for _ in bound_obs)
                    conn.execute(
                        f"UPDATE epistemic_edges SET edge_type = ? WHERE edge_track = 'CLAIM_DECLARED' AND target_id = ? AND source_id IN ({oph})",
                        (nt, str(ref_dst), *bound_obs),
                    )

        # 2. 先锁定审稿单终审状态（供 trg_l3_require_verified_review 触发器放行）
        conn.execute(
            """
            UPDATE review_queue
            SET review_status = 'CLOSED_ACCEPTED', final_verdict = ?, final_locked_at = ?, updated_at = ?
            WHERE review_id = ?
            """,
            (fv, now, now, review_id),
        )

        # 3. 剥离作者身份写入 L3_VERIFIED（受 trg_l3_require_verified_review + uq_l3_verified_review 保护）
        entry_id = next_prefixed_id(conn, "internal_research_ledger", "entry_id", "L3-")
        conn.execute(
            """
            INSERT INTO internal_research_ledger(
                entry_id, question_id, ledger_type, l3_entry_kind, goal_coverage, l2_category,
                title, abstract_md, exact_verified_scope_md, exact_refuted_scope_md,
                body_proof_or_code_md, bound_obs_ids_json, verified_review_id, is_active, created_at
            ) VALUES (?, ?, 'L3_VERIFIED', ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                entry_id,
                qid,
                kind_u,
                cov_u,
                clean_title,
                clean_abs,
                clean_scope,
                str(exact_refuted_scope_md or "").strip() or None,
                str(rev["column_a_snapshot_md"] or ""),
                json.dumps(bound_obs, ensure_ascii=False),
                review_id,
                now,
            ),
        )
        # 将认证的 REQUIRED_PREMISE 同样绑定到新 L3 条目，以便日后精准级联重审
        if isinstance(edge_type_overrides, dict):
            for ref_dst, new_etype in edge_type_overrides.items():
                nt = str(new_etype).strip().upper()
                conn.execute(
                    """
                    INSERT INTO epistemic_edges(edge_id, source_id, target_id, edge_track, edge_type, session_id, metadata_json, created_at)
                    VALUES (?, ?, ?, 'CLAIM_DECLARED', ?, ?, '{}', ?)
                    """,
                    (f"ce_{uuid.uuid4().hex[:12]}", entry_id, str(ref_dst), nt, session_id, now),
                )

        conn.execute(
            "UPDATE lineage_nodes SET node_status = 'SEALED', updated_at = ? WHERE node_id = ?",
            (now, str(rev["source_node_id"])),
        )

    return build_tool_receipt(
        conn=conn,
        tool_name="submit_stage2_unblind_verdict",
        question_id=qid,
        next_step_guidance=f"审稿单 {review_id} 终判 {fv}，已正式入库 {entry_id} ({kind_u} / {cov_u}) 并置原分支 SEALED。",
        data={
            "review_id": review_id,
            "final_verdict": fv,
            "created_l3_id": entry_id,
            "l3_entry_kind": kind_u,
            "goal_coverage": cov_u,
            "cross_pollinate_nomination": cross_pollinate_nomination,
        },
    )


def tool_propose_salvaged_lemma(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    source_node_id: str,
    question_id: str,
    title: str,
    abstract_md: str,
    column_a_self_contained_proof_md: str,
    column_b_scope_notes_md: str,
    bound_obs_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Auditor 废墟引理打捞：强校验原分支不处于 ACTIVE_REVISING 返工期，生成新 STAGE1_BLIND 交异会话复验。"""
    enforce_role_tool_permission(conn, caller_role, "propose_salvaged_lemma", session_id=session_id)
    node = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (source_node_id,)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"源节点 {source_node_id!r} 不存在")
    if str(node["question_id"]) != str(question_id):
        raise FailClosedError(ERR_INVALID_INPUT, f"question_id 与源节点不匹配 ({question_id!r} != {node['question_id']!r})")
    if str(node["node_status"]) in ("ACTIVE_REVISING", "EXPLORING", "PENDING_REVIEW"):
        raise FailClosedError(
            ERR_LOCKED,
            f"AUDITOR_SALVAGE_FORBIDDEN: 源节点 {source_node_id!r} 当前处于 {node['node_status']}（严禁在原分支返工/在研期间由 Auditor 插手打捞！）",
        )

    clean_obs = [str(o).strip() for o in (bound_obs_ids or []) if str(o).strip()]
    for oid in clean_obs:
        if conn.execute("SELECT 1 FROM observations WHERE obs_id = ?", (oid,)).fetchone() is None:
            raise FailClosedError(ERR_NOT_FOUND, f"绑定观测 {oid!r} 不存在")

    if not str(title or "").strip() or not str(column_a_self_contained_proof_md or "").strip():
        raise FailClosedError(ERR_INVALID_INPUT, "title 与 column_a_self_contained_proof_md 不能为空")

    rev_id = next_prefixed_id(conn, "review_queue", "review_id", "rev_")
    node_spec = int(node["spec_revision"] or 0) if "spec_revision" in node.keys() else 0
    now = utc_now_iso()
    with rw_immediate_tx(conn):
        conn.execute(
            """
            INSERT INTO review_queue(
                review_id, question_id, source_node_id, source_type, proposer_session_id,
                review_status, manuscript_title, spec_revision, column_a_snapshot_md, column_b_snapshot_md,
                bound_obs_ids_json, artifact_rel_path, sanitized_code_diff_md, created_at, updated_at
            ) VALUES (?, ?, ?, 'AUDITOR_SALVAGED_LEMMA', ?, 'STAGE1_BLIND', ?, ?, ?, ?, ?, ?, '', ?, ?)
            """,
            (
                rev_id,
                question_id,
                source_node_id,
                str(session_id or f"auditor_{uuid.uuid4().hex[:6]}"),
                title.strip(),
                node_spec,
                column_a_self_contained_proof_md.strip(),
                str(column_b_scope_notes_md or "").strip(),
                json.dumps(clean_obs, ensure_ascii=False),
                node["candidate_rel_path"],
                now,
                now,
            ),
        )

    return build_tool_receipt(
        conn=conn,
        tool_name="propose_salvaged_lemma",
        question_id=question_id,
        next_step_guidance=f"打捞引理已生成独立盲审单 {rev_id}（STAGE1_BLIND），须由另一独立 library_verifier 会话在空白沙箱复验通过后方可入 L3。",
        data={"created_review_id": rev_id, "source_node_id": source_node_id, "review_status": "STAGE1_BLIND"},
    )
