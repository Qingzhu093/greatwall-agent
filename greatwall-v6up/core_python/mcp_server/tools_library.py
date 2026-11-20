"""V6-Up (v2.2) library_surveyor (3) 与 library_verifier (5) 图书馆采编/两阶段盲审 8 工具。"""
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
# 角色 4：library_surveyor（3 个窄工具）
# ==============================================================================


def tool_get_survey_requests(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    question_id: str = "ALL",
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "get_survey_requests", session_id=session_id)
    q_filter = (question_id or "ALL").strip()
    if q_filter.upper() == "ALL":
        reqs = [dict(r) for r in conn.execute("SELECT * FROM survey_requests WHERE status = 'PENDING' ORDER BY created_at ASC").fetchall()]
        ext = [dict(r) for r in conn.execute("SELECT ref_id, question_id, title, read_depth FROM external_literature_cards ORDER BY created_at ASC").fetchall()]
    else:
        reqs = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM survey_requests WHERE question_id = ? AND status = 'PENDING' ORDER BY created_at ASC",
                (q_filter,),
            ).fetchall()
        ]
        ext = [
            dict(r)
            for r in conn.execute(
                "SELECT ref_id, question_id, title, read_depth FROM external_literature_cards WHERE question_id = ? OR question_id = 'GLOBAL' ORDER BY created_at ASC",
                (q_filter,),
            ).fetchall()
        ]

    gate = check_stage2_closure_gate_data(conn)
    stage3_bundle: dict[str, Any] | None = None
    if gate["closure_allowed"]:
        l3s = [
            dict(r)
            for r in conn.execute(
                "SELECT entry_id, question_id, source_type, title, abstract_md, exact_verified_scope_md, body_proof_or_code_md, bound_obs_ids_json FROM internal_research_ledger WHERE ledger_type = 'L3_VERIFIED' AND ledger_status = 'active' ORDER BY question_id, entry_id"
            ).fetchall()
        ]
        l2s = [
            dict(r)
            for r in conn.execute(
                "SELECT entry_id, question_id, source_type, title, abstract_md, exact_refuted_scope_md FROM internal_research_ledger WHERE ledger_type = 'L2_FAILURE_RECORD' ORDER BY question_id, entry_id"
            ).fetchall()
        ]
        ext_full = [dict(r) for r in conn.execute("SELECT * FROM external_literature_cards ORDER BY ref_id").fetchall()]
        obs_all = [
            dict(r)
            for r in conn.execute(
                "SELECT obs_id, question_id, obs_status, passed, metrics_json, details_text, linguistic_prediction FROM observations WHERE obs_status = 'VALID' ORDER BY question_id, obs_id"
            ).fetchall()
        ]
        stage3_bundle = {
            "stage3_unlocked": True,
            "l3_verified": l3s,
            "l2_failure_records": l2s,
            "external_literature_cards": ext_full,
            "valid_observations": obs_all,
        }
        guidance = "Stage 2 结题硬锁已全绿解锁 Stage 3！请基于 stage3_synthesis_bundle 撰写正式学术论文并调 export_stage3_final_delivery 导出五件套。"
    else:
        guidance = f"当前有 {len(reqs)} 条待采编查新请求（现有外藏卡 {len(ext)} 张）。请调 publish_external_literature_card 入库新 [R###] 卡片。"

    return build_tool_receipt(
        conn=conn,
        tool_name="get_survey_requests",
        question_id=q_filter,
        next_step_guidance=guidance,
        data={
            "pending_requests": reqs,
            "existing_external_cards": ext,
            "stage2_closure_gate": gate,
            "stage3_synthesis_bundle": stage3_bundle,
        },
    )


def tool_publish_external_literature_card(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    ref_id: str,
    question_id: str,
    title: str,
    abstract_md: str,
    exact_preconditions_md: str,
    formulas_or_operators_md: str,
    read_depth: str,
    support_scope: str,
    source_citation: str,
    fulfilled_request_ids: list[str] | None = None,
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "publish_external_literature_card", session_id=session_id)
    rid = (ref_id or "").strip()
    if not rid:
        raise FailClosedError(ERR_INVALID_INPUT, "ref_id 不能为空")
    abs_clean = (abstract_md or "").strip()
    if len(abs_clean) < 60 or len(abs_clean) > 1500:
        raise FailClosedError(
            ERR_INVALID_INPUT,
            f"abstract_md 长度必须为 60–1500 字的独立高密度摘要（实收 {len(abs_clean)} 字，建议 120–500 字，严禁空洞敷衍或 [:120] 伪摘要）",
        )
    if not (exact_preconditions_md or "").strip() or not (formulas_or_operators_md or "").strip():
        raise FailClosedError(ERR_INVALID_INPUT, "exact_preconditions_md 与 formulas_or_operators_md 不能为空（离线亦须提供完整定理/算子公式）")
    if read_depth not in ALLOWED_READ_DEPTHS:
        raise FailClosedError(
            ERR_INVALID_INPUT,
            f"非法 read_depth: {read_depth!r}，仅允许英文枚举 {sorted(ALLOWED_READ_DEPTHS)}",
        )
    if support_scope not in ALLOWED_SUPPORT_SCOPES:
        raise FailClosedError(
            ERR_INVALID_INPUT,
            f"非法 support_scope: {support_scope!r}，仅允许英文枚举 {sorted(ALLOWED_SUPPORT_SCOPES)}",
        )

    req_ids_clean = [str(r).strip() for r in (fulfilled_request_ids or []) if str(r).strip()]
    now = utc_now_iso()
    fulfilled_actual: list[str] = []
    with rw_immediate_tx(conn):
        conn.execute(
            """
            INSERT INTO external_literature_cards(
                ref_id, question_id, title, abstract_md, exact_preconditions_md,
                formulas_or_operators_md, read_depth, support_scope, source_citation, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                question_id.strip(),
                title.strip(),
                abs_clean,
                exact_preconditions_md.strip(),
                formulas_or_operators_md.strip(),
                read_depth,
                support_scope,
                source_citation.strip(),
                now,
            ),
        )
        # 精确核销指定的查新请求 ID，严禁按 question_id 批量误消同题其它 PENDING 单
        for req_id in req_ids_clean:
            cur = conn.execute(
                "UPDATE survey_requests SET status = 'FULFILLED', updated_at = ? WHERE request_id = ? AND status = 'PENDING'",
                (now, req_id),
            )
            if cur.rowcount and cur.rowcount > 0:
                fulfilled_actual.append(req_id)
        record_fact_edge(
            conn,
            src_id=session_id or "library_surveyor",
            dst_id=rid,
            edge_type="PRODUCED",
            metadata={"question_id": question_id, "read_depth": read_depth, "fulfilled_request_ids": fulfilled_actual},
        )

    return build_tool_receipt(
        conn=conn,
        tool_name="publish_external_literature_card",
        question_id=question_id,
        next_step_guidance=f"外藏卡片 [{rid}] 已写入 external_literature_cards，全员探索者自 0% 起即可通过 query_library_catalog 拉取。",
        data={
            "ref_id": rid,
            "question_id": question_id,
            "read_depth": read_depth,
            "fulfilled_request_ids": fulfilled_actual,
        },
    )


def tool_export_stage3_final_delivery(
    conn: sqlite3.Connection,
    workspace_root: str,
    caller_role: str,
    session_id: str,
    formal_paper_md: str,
    selected_l3_ids_by_question: dict[str, list[str]],
    reproduction_candidate_nodes: list[str],
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "export_stage3_final_delivery", session_id=session_id)
    out = export_stage3_deliverables(
        conn=conn,
        workspace_root=workspace_root,
        formal_paper_md=formal_paper_md,
        selected_l3_ids_by_question=selected_l3_ids_by_question,
        reproduction_candidate_nodes=reproduction_candidate_nodes,
    )
    return build_tool_receipt(
        conn=conn,
        tool_name="export_stage3_final_delivery",
        question_id="ALL",
        next_step_guidance="Stage 3 五件套已安全导出至 final_delivery/，控制面将立即拉起 library_verifier + supervisory_committee 执行终局逐行核对。",
        data=out,
    )


# ==============================================================================
# 角色 5：library_verifier（5 个纯 DB 零磁盘窄工具）
# ==============================================================================


def tool_get_blind_manuscript(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    review_id: str,
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "get_blind_manuscript", session_id=session_id)
    eff_sid = _require_reviewer_session(session_id, "Stage 1 盲审拉取")
    rev = conn.execute("SELECT * FROM review_queue WHERE review_id = ?", (review_id,)).fetchone()
    if rev is None:
        raise FailClosedError(ERR_NOT_FOUND, f"盲审单 {review_id!r} 不存在")
    if str(rev["review_status"]) != "STAGE1_BLIND":
        raise FailClosedError(ERR_LOCKED, f"盲审单 {review_id!r} 状态为 {rev['review_status']}，Stage 1 盲态拉取仅限 STAGE1_BLIND")
    if eff_sid in _parse_proposer_sessions(rev["proposer_session_id"]):
        raise FailClosedError(ERR_CONFLICT, "SELF_REVIEW_FORBIDDEN: 严禁提议/打捞会话自审自己提交的手稿或引理！")

    qid = str(rev["question_id"])
    obs_ids = json.loads(rev["bound_obs_ids_json"] or "[]")
    blind_obs: list[dict[str, Any]] = []
    for oid in obs_ids:
        orow = conn.execute(
            "SELECT obs_id, question_id, obs_status, passed, metrics_json, details_text, linguistic_prediction, domain_hook_sha256 FROM observations WHERE obs_id = ?",
            (oid,),
        ).fetchone()
        if orow is not None:
            blind_obs.append(
                {
                    "obs_id": str(orow["obs_id"]),
                    "question_id": str(orow["question_id"]),
                    "obs_status": str(orow["obs_status"]),
                    "passed": bool(orow["passed"]),
                    "metrics": json.loads(orow["metrics_json"] or "{}"),
                    "details": str(orow["details_text"]),
                    "linguistic_prediction": str(orow["linguistic_prediction"]),
                }
            )

    referenced_cards = _extract_referenced_cards_for_blind_review(
        conn,
        [str(rev["manuscript_title"]), str(rev["column_a_snapshot_md"]), *(o["details"] for o in blind_obs)],
        obs_ids,
    )

    ep = conn.execute("SELECT contracts_json FROM epoch_config WHERE config_id = 'active'").fetchone()
    contracts = json.loads(ep["contracts_json"]) if ep and ep["contracts_json"] else {}
    q_contract = contracts.get(qid, {}) if isinstance(contracts, dict) else {}

    # 物理屏蔽：绝不返回 source_node_id、branch_id、comparable_rank_score、column_b_snapshot_md、will_md、proposer_session_id
    return build_tool_receipt(
        conn=conn,
        tool_name="get_blind_manuscript",
        question_id=qid,
        next_step_guidance="已拉取 Stage 1 盲态手稿 A 栏 + sanitized_code_diff_md + 原始 [Obs###] 收据 + 引用卡片 read_depth。请按 OpenAI CDC 7 类漏洞清单与 Station 6 步法则调 submit_stage1_blind_ledger 锁定不可逆账本。",
        data={
            "review_id": review_id,
            "question_id": qid,
            "source_type": str(rev["source_type"]),
            "manuscript_title": str(rev["manuscript_title"]),
            "question_contract": q_contract,
            "column_a_snapshot_md": str(rev["column_a_snapshot_md"]),
            "sanitized_code_diff_md": str(rev["sanitized_code_diff_md"]),
            "blind_observations": blind_obs,
            "referenced_library_cards": referenced_cards,
        },
    )


def tool_submit_stage1_blind_ledger(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    review_id: str,
    question_id: str,
    ledger_items: list[dict[str, Any]],
    stage1_verdict: str,
    reject_failure_reason: str | None = None,
    exact_refuted_scope_md: str | None = None,
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "submit_stage1_blind_ledger", session_id=session_id)
    eff_sid = _require_reviewer_session(session_id, "Stage 1 盲审定稿")
    rev = conn.execute("SELECT * FROM review_queue WHERE review_id = ?", (review_id,)).fetchone()
    if rev is None:
        raise FailClosedError(ERR_NOT_FOUND, f"盲审单 {review_id!r} 不存在")
    if str(rev["review_status"]) != "STAGE1_BLIND" or rev["stage1_locked_at"] is not None:
        raise FailClosedError(ERR_LOCKED, f"STAGE1_LEDGER_IMMUTABLE: {review_id!r} Stage 1 已锁定或已完结")
    if str(rev["question_id"]) != question_id:
        raise FailClosedError(ERR_INVALID_INPUT, f"question_id 不匹配：{question_id!r} != {rev['question_id']!r}")
    if eff_sid in _parse_proposer_sessions(rev["proposer_session_id"]):
        raise FailClosedError(ERR_CONFLICT, "SELF_REVIEW_FORBIDDEN: 异会话盲审拦截，严禁自审！")

    src_node = conn.execute(
        "SELECT branch_id, family_id FROM lineage_nodes WHERE node_id = ?", (rev["source_node_id"],)
    ).fetchone()
    fam_id = str(src_node["family_id"]) if src_node else ""

    if not isinstance(ledger_items, list) or len(ledger_items) == 0:
        raise FailClosedError(ERR_INVALID_INPUT, "ledger_items 必须为非空 Evidence Ledger 列表")
    for i, it in enumerate(ledger_items):
        if not isinstance(it, dict) or not str(it.get("claim", "")).strip() or not str(it.get("evidence_location_and_quote", "")).strip():
            raise FailClosedError(ERR_INVALID_INPUT, f"ledger_items[{i}] 缺少 claim 或 evidence_location_and_quote")

    verdict_u = (stage1_verdict or "").strip().upper()
    if verdict_u not in ("PASS", "REJECT"):
        raise FailClosedError(ERR_INVALID_INPUT, f"stage1_verdict 仅允许 PASS 或 REJECT，实收 {stage1_verdict!r}")

    if verdict_u == "PASS":
        for i, it in enumerate(ledger_items):
            if not bool(it.get("is_verified")) or "no direct evidence found" in str(it.get("evidence_location_and_quote", "")).lower():
                raise FailClosedError(
                    ERR_INVARIANT,
                    f"Station 6 步法则阻断：ledger_items[{i}] 未获直接实证却试图判 PASS",
                )

    now = utc_now_iso()
    created_l2_id: str | None = None
    with rw_immediate_tx(conn):
        if verdict_u == "REJECT":
            if not (reject_failure_reason or "").strip() or not (exact_refuted_scope_md or "").strip():
                raise FailClosedError(ERR_INVALID_INPUT, "Stage 1 REJECT 必须填写 reject_failure_reason 与 exact_refuted_scope_md")
            conn.execute(
                """
                UPDATE review_queue
                SET reviewer_session_id = ?,
                    stage1_ledger_json = ?,
                    stage1_verdict = 'REJECT',
                    reject_failure_reason = ?,
                    exact_refuted_scope_md = ?,
                    stage1_locked_at = ?,
                    review_status = 'CLOSED_REJECTED_TO_L2',
                    final_verdict = 'REJECT',
                    final_locked_at = ?
                WHERE review_id = ?
                """,
                (
                    session_id,
                    json.dumps(ledger_items, ensure_ascii=False),
                    reject_failure_reason.strip(),
                    exact_refuted_scope_md.strip(),
                    now,
                    now,
                    review_id,
                ),
            )
            created_l2_id = _next_ledger_id(conn, "L2_FAILURE_RECORD")
            conn.execute(
                """
                INSERT INTO internal_research_ledger(
                    entry_id, question_id, ledger_type, source_type, method_family_id,
                    title, abstract_md, exact_refuted_scope_md, body_proof_or_code_md,
                    bound_obs_ids_json, verified_review_id, created_at
                ) VALUES (?, ?, 'L2_FAILURE_RECORD', 'STAGE1_BLIND_REJECT', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_l2_id,
                    question_id,
                    fam_id,
                    f"[{question_id}] {rev['manuscript_title']} (Stage 1 盲审证伪)",
                    f"Stage 1 盲审依不可逆 Evidence Ledger 短路驳回：{reject_failure_reason.strip()}",
                    exact_refuted_scope_md.strip(),
                    json.dumps(ledger_items, ensure_ascii=False),
                    str(rev["bound_obs_ids_json"]),
                    review_id,
                    now,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE review_queue
                SET reviewer_session_id = ?,
                    stage1_ledger_json = ?,
                    stage1_verdict = 'PASS',
                    stage1_locked_at = ?,
                    review_status = 'STAGE2_UNBLIND'
                WHERE review_id = ?
                """,
                (session_id, json.dumps(ledger_items, ensure_ascii=False), now, review_id),
            )

    if verdict_u == "REJECT":
        guidance = f"Stage 1 盲审 REJECT 已不可逆锁定，系统已同事务短路生成内藏失败雷达 [{created_l2_id}] 结案。请结束回合。"
    else:
        guidance = "Stage 1 Evidence Ledger 已锁定并进入 STAGE2_UNBLIND。请立即调 get_unblinded_manuscript_and_peers 进入 Stage 2 解盲横审。"

    return build_tool_receipt(
        conn=conn,
        tool_name="submit_stage1_blind_ledger",
        question_id=question_id,
        next_step_guidance=guidance,
        data={
            "review_id": review_id,
            "stage1_verdict": verdict_u,
            "stage1_locked_at": now,
            "short_circuited_l2_id": created_l2_id,
        },
    )


def tool_get_unblinded_manuscript_and_peers(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    review_id: str,
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "get_unblinded_manuscript_and_peers", session_id=session_id)
    # 兼容 Stage 3 Comparator 仅需横向汇总的场景
    if review_id == "STAGE3_COMPARATOR":
        l3_rows = []
        for r in conn.execute(
            "SELECT entry_id, question_id, title, abstract_md, exact_verified_scope_md, bound_obs_ids_json FROM internal_research_ledger WHERE ledger_type = 'L3_VERIFIED' AND ledger_status = 'active' ORDER BY question_id, entry_id"
        ).fetchall():
            d = dict(r)
            obs_list = json.loads(d.get("bound_obs_ids_json") or "[]")
            scores: list[float] = []
            if obs_list:
                oph = ",".join("?" for _ in obs_list)
                for orow in conn.execute(
                    f"SELECT comparable_rank_score FROM observations WHERE obs_id IN ({oph}) AND comparable_rank_score IS NOT NULL",
                    obs_list,
                ).fetchall():
                    scores.append(float(orow["comparable_rank_score"]))
            d["best_comparable_rank_score"] = max(scores) if scores else None
            l3_rows.append(d)
        l3_rows.sort(
            key=lambda x: (
                str(x["question_id"]),
                -(x["best_comparable_rank_score"]) if x["best_comparable_rank_score"] is not None else float("inf"),
                str(x["entry_id"]),
            )
        )
        return build_tool_receipt(
            conn=conn,
            tool_name="get_unblinded_manuscript_and_peers",
            question_id="ALL",
            next_step_guidance="已拉取全卷 active L3_VERIFIED 条目及可比排序分供 Stage 3 Comparator 横向择优排序。",
            data={"comparator_l3_entries": l3_rows},
        )

    eff_sid = _require_reviewer_session(session_id, "Stage 2 解盲横审")
    rev = conn.execute("SELECT * FROM review_queue WHERE review_id = ?", (review_id,)).fetchone()
    if rev is None:
        raise FailClosedError(ERR_NOT_FOUND, f"审稿单 {review_id!r} 不存在")
    if rev["stage1_locked_at"] is None or str(rev["review_status"]) != "STAGE2_UNBLIND":
        raise FailClosedError(
            ERR_LOCKED,
            f"Stage 2 解盲门禁阻断：必须先调 submit_stage1_blind_ledger 锁定 PASS 账本 (当前状态 {rev['review_status']})",
        )
    if eff_sid in _parse_proposer_sessions(rev["proposer_session_id"]):
        raise FailClosedError(ERR_CONFLICT, "SELF_REVIEW_FORBIDDEN: 严禁提议/探索会话解盲终审自己脉络的手稿！")

    qid = str(rev["question_id"])
    src_nid = str(rev["source_node_id"])
    src_node = conn.execute("SELECT branch_id, family_id FROM lineage_nodes WHERE node_id = ?", (src_nid,)).fetchone()
    src_bid = str(src_node["branch_id"]) if src_node else ""

    fact_reconciliation = _audit_node_unread_citations(conn, src_nid)
    peer_l3 = [
        dict(r)
        for r in conn.execute(
            "SELECT entry_id, title, abstract_md, exact_verified_scope_md FROM internal_research_ledger WHERE question_id = ? AND ledger_type = 'L3_VERIFIED' AND ledger_status = 'active'",
            (qid,),
        ).fetchall()
    ]
    peer_active_branches = [
        {
            "branch_id": str(r["branch_id"]),
            "family_id": str(r["family_id"]),
            "latest_bottleneck": str(r["column_b_hypothesis_md"] or ""),
        }
        for r in conn.execute(
            "SELECT branch_id, family_id, column_b_hypothesis_md FROM lineage_nodes WHERE question_id = ? AND branch_id != ? AND node_status IN ('EXPLORING', 'BLOCKED_L4B', 'AWAITING_TRIAGE') ORDER BY updated_at DESC LIMIT 6",
            (qid, src_bid),
        ).fetchall()
    ]

    return build_tool_receipt(
        conn=conn,
        tool_name="get_unblinded_manuscript_and_peers",
        question_id=qid,
        next_step_guidance="已解盲 B 栏机理、FACT_LOG 引用对账与 Cross-Draft 同题横向快照。请恪守单向降级锁调用 submit_stage2_unblind_verdict。",
        data={
            "review_id": review_id,
            "question_id": qid,
            "author_branch_id": src_bid,
            "stage1_locked_ledger": json.loads(rev["stage1_ledger_json"] or "[]"),
            "column_b_snapshot_md": str(rev["column_b_snapshot_md"]),
            "fact_log_reconciliation": fact_reconciliation,
            "cross_draft_existing_l3": peer_l3,
            "cross_draft_sibling_branches": peer_active_branches,
        },
    )


def tool_submit_stage2_unblind_verdict(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    review_id: str,
    final_verdict: str,
    title: str,
    abstract_md: str,
    exact_verified_scope_md: str | None = None,
    exact_refuted_scope_md: str | None = None,
    cross_draft_comparison_notes: str = "",
    cross_pollinate_nomination: dict[str, Any] | None = None,
    edge_type_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "submit_stage2_unblind_verdict", session_id=session_id)
    eff_sid = _require_reviewer_session(session_id, "Stage 2 终审落盘")
    rev = conn.execute("SELECT * FROM review_queue WHERE review_id = ?", (review_id,)).fetchone()
    if rev is None:
        raise FailClosedError(ERR_NOT_FOUND, f"审稿单 {review_id!r} 不存在")
    if rev["stage1_locked_at"] is None or str(rev["stage1_verdict"]) != "PASS" or str(rev["review_status"]) != "STAGE2_UNBLIND":
        raise FailClosedError(
            ERR_LOCKED,
            f"单向降级锁拦截：{review_id!r} 不处于可终审 Stage 2 状态 (stage1_verdict={rev['stage1_verdict']}, review_status={rev['review_status']})",
        )
    if eff_sid in _parse_proposer_sessions(rev["proposer_session_id"]):
        raise FailClosedError(ERR_CONFLICT, "SELF_REVIEW_FORBIDDEN: 严禁提议者自审")

    fv = (final_verdict or "").strip().upper()
    if fv not in ("PASS", "PASS_WITH_NARROWED_SCOPE", "REJECT"):
        raise FailClosedError(ERR_INVALID_INPUT, f"非法 final_verdict: {final_verdict!r}")
    if not (title or "").strip() or len((abstract_md or "").strip()) < 40:
        raise FailClosedError(ERR_INVALID_INPUT, "title 与 >=40 字独立 abstract_md 必填")
    if fv in ("PASS", "PASS_WITH_NARROWED_SCOPE") and not (exact_verified_scope_md or "").strip():
        raise FailClosedError(ERR_INVALID_INPUT, "PASS / PASS_WITH_NARROWED_SCOPE 必须明确 exact_verified_scope_md")
    if fv == "REJECT" and not (exact_refuted_scope_md or "").strip():
        raise FailClosedError(ERR_INVALID_INPUT, "Stage 2 REJECT 必须填写 exact_refuted_scope_md")

    qid = str(rev["question_id"])
    src_nid = str(rev["source_node_id"])
    src_node = conn.execute("SELECT family_id FROM lineage_nodes WHERE node_id = ?", (src_nid,)).fetchone()
    fam_id = str(src_node["family_id"]) if src_node else ""
    bound_obs = json.loads(rev["bound_obs_ids_json"] or "[]")
    obs_hook_sha = ""
    obs_epoch_ver = 1
    if bound_obs:
        orow = conn.execute(
            "SELECT domain_hook_sha256, eval_epoch_version FROM observations WHERE obs_id = ?", (bound_obs[0],)
        ).fetchone()
        if orow is not None:
            obs_hook_sha = str(orow["domain_hook_sha256"])
            obs_epoch_ver = int(orow["eval_epoch_version"])

    now = utc_now_iso()
    created_entry_id: str

    with rw_immediate_tx(conn):
        # 拍板 4：若 Stage 2 需要将探索者默认 REQUIRED_PREMISE 引用降级为 INDEPENDENT_SUPPORT / MOTIVATING_REF
        if isinstance(edge_type_overrides, dict) and bound_obs:
            oph = ",".join("?" for _ in bound_obs)
            for ref_dst, new_etype in edge_type_overrides.items():
                nt = str(new_etype).strip().upper()
                if nt not in ALLOWED_CLAIMED_EDGE_TYPES:
                    raise FailClosedError(
                        ERR_INVALID_INPUT,
                        f"edge_type_overrides 包含非法边类型: {new_etype!r}，仅允许 {sorted(ALLOWED_CLAIMED_EDGE_TYPES)}",
                    )
                conn.execute(
                    f"""
                    UPDATE epistemic_edges
                    SET edge_type = ?
                    WHERE edge_track = 'CLAIM_DECLARED' AND dst_id = ? AND src_id IN ({oph})
                    """,
                    (nt, str(ref_dst), *bound_obs),
                )

        if fv in ("PASS", "PASS_WITH_NARROWED_SCOPE"):
            conn.execute(
                """
                UPDATE review_queue
                SET review_status = 'CLOSED_ACCEPTED_TO_L3',
                    final_verdict = ?,
                    stage2_comparison_notes = ?,
                    cross_pollinate_json = ?,
                    final_locked_at = ?
                WHERE review_id = ?
                """,
                (
                    fv,
                    cross_draft_comparison_notes.strip(),
                    json.dumps(cross_pollinate_nomination, ensure_ascii=False) if cross_pollinate_nomination else None,
                    now,
                    review_id,
                ),
            )
            created_entry_id = _next_ledger_id(conn, "L3_VERIFIED")
            depends_on = sorted(
                {
                    *(
                        str(r["dst_id"])
                        for oid in bound_obs
                        for r in conn.execute(
                            "SELECT dst_id FROM epistemic_edges WHERE src_id = ? AND edge_track = 'CLAIM_DECLARED'",
                            (oid,),
                        ).fetchall()
                    ),
                    *bound_obs,
                }
            )
            # 注意：L3_VERIFIED 物理剥离作者/branch_id 与排名分，只存经证实科学契约
            conn.execute(
                """
                INSERT INTO internal_research_ledger(
                    entry_id, question_id, ledger_type, source_type, method_family_id,
                    title, abstract_md, exact_verified_scope_md, body_proof_or_code_md,
                    bound_obs_ids_json, depends_on_ids_json, domain_hook_sha256,
                    eval_epoch_version, verified_review_id, created_at
                ) VALUES (?, ?, 'L3_VERIFIED', ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_entry_id,
                    qid,
                    str(rev["source_type"]),
                    title.strip(),
                    abstract_md.strip(),
                    exact_verified_scope_md.strip(),
                    str(rev["column_a_snapshot_md"]),
                    json.dumps(bound_obs, ensure_ascii=False),
                    json.dumps(depends_on, ensure_ascii=False),
                    obs_hook_sha,
                    obs_epoch_ver,
                    review_id,
                    now,
                ),
            )
            conn.execute("UPDATE epoch_config SET consecutive_non_l1_handoffs = 0, updated_at = ? WHERE config_id = 'active'", (now,))
        else:
            conn.execute(
                """
                UPDATE review_queue
                SET review_status = 'CLOSED_REJECTED_TO_L2',
                    final_verdict = 'REJECT',
                    exact_refuted_scope_md = ?,
                    stage2_comparison_notes = ?,
                    final_locked_at = ?
                WHERE review_id = ?
                """,
                (
                    exact_refuted_scope_md.strip(),
                    cross_draft_comparison_notes.strip(),
                    now,
                    review_id,
                ),
            )
            created_entry_id = _next_ledger_id(conn, "L2_FAILURE_RECORD")
            conn.execute(
                """
                INSERT INTO internal_research_ledger(
                    entry_id, question_id, ledger_type, source_type, method_family_id,
                    title, abstract_md, exact_refuted_scope_md, body_proof_or_code_md,
                    bound_obs_ids_json, domain_hook_sha256, eval_epoch_version, verified_review_id, created_at
                ) VALUES (?, ?, 'L2_FAILURE_RECORD', 'STAGE2_UNBLIND_REJECT', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_entry_id,
                    qid,
                    fam_id,
                    title.strip(),
                    abstract_md.strip(),
                    exact_refuted_scope_md.strip(),
                    str(rev["column_b_snapshot_md"]),
                    json.dumps(bound_obs, ensure_ascii=False),
                    obs_hook_sha,
                    obs_epoch_ver,
                    review_id,
                    now,
                ),
            )

    ready_candidates = [
        dict(r)
        for r in conn.execute(
            "SELECT node_id, question_id, reopen_condition FROM lineage_nodes WHERE question_id = ? AND node_status = 'BLOCKED_L4B'",
            (qid,),
        ).fetchall()
    ]
    guidance = (
        f"Stage 2 终审 {fv} 已同事务自动入库内藏 [{created_entry_id}]！"
        + (f" 控制面将唤醒 logistics_coordinator 核对 Ready Queue ({len(ready_candidates)} 个阻塞分支)。" if fv != "REJECT" and ready_candidates else "")
    )
    return build_tool_receipt(
        conn=conn,
        tool_name="submit_stage2_unblind_verdict",
        question_id=qid,
        next_step_guidance=guidance,
        data={
            "review_id": review_id,
            "final_verdict": fv,
            "created_ledger_entry_id": created_entry_id,
            "ledger_type": "L3_VERIFIED" if fv != "REJECT" else "L2_FAILURE_RECORD",
            "ready_queue_check_count": len(ready_candidates),
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
    bound_obs_ids: list[str],
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "propose_salvaged_lemma", session_id=session_id)
    node = conn.execute("SELECT node_id, question_id, sanitized_code_diff_md FROM lineage_nodes WHERE node_id = ?", (source_node_id,)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"源节点 {source_node_id!r} 不存在")
    if str(node["question_id"]) != question_id:
        raise FailClosedError(ERR_INVALID_INPUT, f"question_id 与源节点不匹配 ({question_id!r} != {node['question_id']!r})")
    if not bound_obs_ids:
        raise FailClosedError(ERR_INVALID_INPUT, "打捞引理必须绑定至少 1 条真实存在的 [Obs###]")
    for oid in bound_obs_ids:
        if conn.execute("SELECT 1 FROM observations WHERE obs_id = ?", (oid,)).fetchone() is None:
            raise FailClosedError(ERR_NOT_FOUND, f"绑定观测 {oid!r} 不存在")

    eff_proposer = _require_reviewer_session(session_id, "Auditor 打捞提议")
    now = utc_now_iso()
    with rw_immediate_tx(conn):
        rev_id = _next_id(conn, "review_queue", "review_id", "rev_", 3)
        conn.execute(
            """
            INSERT INTO review_queue(
                review_id, source_node_id, question_id, source_type, proposer_session_id,
                review_status, manuscript_title, salvage_abstract_md, column_a_snapshot_md,
                column_b_snapshot_md, sanitized_code_diff_md, bound_obs_ids_json, created_at
            ) VALUES (?, ?, ?, 'AUDITOR_SALVAGED_LEMMA', ?, 'STAGE1_BLIND', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rev_id,
                source_node_id,
                question_id,
                eff_proposer,
                title.strip(),
                abstract_md.strip(),
                column_a_self_contained_proof_md.strip(),
                column_b_scope_notes_md.strip(),
                str(node["sanitized_code_diff_md"] or ""),
                json.dumps(bound_obs_ids, ensure_ascii=False),
                now,
            ),
        )
    return build_tool_receipt(
        conn=conn,
        tool_name="propose_salvaged_lemma",
        question_id=question_id,
        next_step_guidance=f"打捞自包含引理已直入标准盲审队列 {rev_id} (STAGE1_BLIND)，控制面将强制拉起另一独立 library_verifier 会话执行两阶段复审。",
        data={"review_id": rev_id, "source_type": "AUDITOR_SALVAGED_LEMMA", "proposer_session_id": session_id},
    )


