"""GreatWall v0.3 中央图书馆·独立空白沙箱两阶段盲审与一步终签（library_verifier 5 个窄工具）。

v0.3 核心升级：
- 裁决 3：Stage 1 新增 `PARTIAL_PASS` 推进至 `STAGE2_UNBLIND`；`ACCEPT_NARROWED` 同事务收编 1 条 L3(PARTIAL_OR_LEMMA) + 1 条 L2_FAILURE_RECORD；
- 裁决 3：Stage 3 终核通过外部不可变冻结目录验证后，写锁外算哈希、写锁内毫秒级比对一致**一步原子结项**；
- 裁决 4：子题级 `active_spec_revision` 防连坐判定，在写锁内实时核对避免并发改题漏洞；
- 裁决 2：`LOCAL_LEMMA_SUBMISSION` 一次性盲审绝不锁死也不修改原分支状态；
- 支持 `publish_tier`（达标与基线两步分离）、`fulfilled_gap_ids` 核销唤醒、`exploit_ticket_payload` 反作弊发单。
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .control_plane.blind_sandbox import stage_blind_review_sandbox
from .control_plane.delivery_freeze import finalize_stage3_closure_on_verifier_accept
from .control_plane.scheduler_rules import check_stage2_closure_gate_data
from .control_plane.subproblem_locks import (
    evaluate_subproblem_locks,
    get_subproblem_active_spec_revision,
)
from .db_schema import (
    ALLOWED_CLAIMED_EDGE_TYPES,
    ALLOWED_FINAL_VERDICTS,
    ALLOWED_GOAL_COVERAGES,
    ALLOWED_L3_ENTRY_KINDS,
    ALLOWED_PUBLISH_TIERS,
    ALLOWED_STAGE1_VERDICTS,
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
    next_prefixed_id,
)
from .tools_verifier_helpers import (
    apply_revise_or_exhaust as _apply_revise_or_exhaust,
    archive_to_l2_and_seal as _archive_to_l2_and_seal,
    build_peer_calibration_pack,
    composite_entries,
    enqueue_exploit_ticket_if_present,
    fulfill_open_gaps_and_wake_branches,
    record_publication_citations,
    require_unclosed_stage2,
    review_author,
    validate_library_citations,
    validate_review_score,
    is_local_lemma_review,
    require_non_self_review as _require_non_self_review,
)


def tool_get_blind_manuscript(
    conn: sqlite3.Connection,
    workspace_root: str,
    caller_role: str,
    session_id: str,
    review_id: str,
) -> dict[str, Any]:
    """Stage 1 盲态拉取：在独立空白沙箱中仅挂载 A 栏、脱敏代码/证明与客观 [Obs###]。"""
    enforce_role_tool_permission(conn, caller_role, "get_blind_manuscript", session_id=session_id)
    rev = conn.execute("SELECT * FROM review_queue WHERE review_id = ?", (review_id,)).fetchone()
    if rev is None:
        raise FailClosedError(ERR_NOT_FOUND, f"盲审单 {review_id!r} 不存在")
    if str(rev["review_status"]) != "STAGE1_BLIND":
        raise FailClosedError(ERR_LOCKED, f"盲审单 {review_id!r} 当前状态为 {rev['review_status']}，Stage 1 仅限 STAGE1_BLIND")
    _require_non_self_review(session_id, str(rev["proposer_session_id"]), conn=conn, source_node_id=str(rev["source_node_id"] or ""))

    staged = stage_blind_review_sandbox(conn, workspace_root=workspace_root, review_id=review_id)
    obs_ids = json.loads(rev["bound_obs_ids_json"] or "[]")
    obs_list: list[dict[str, Any]] = []
    if obs_ids:
        ph = ",".join("?" for _ in obs_ids)
        for o in conn.execute(
            f"SELECT obs_id, instrument_id, instrument_version, tier, obs_status, tracks_json, details_text, frozen_code_snapshot_path FROM observations WHERE obs_id IN ({ph})",
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
                    "code_snapshot_rel_path": f"obs_snapshots/{o['obs_id']}" if o["frozen_code_snapshot_path"] else None,
                }
            )

    rev_spec = int(rev["spec_revision"] or 0)
    return build_tool_receipt(
        conn=conn,
        tool_name="get_blind_manuscript",
        question_id=str(rev["question_id"]),
        next_step_guidance=(
            f"请按手稿绑定口径 spec_revision=v{rev_spec} 在独立空白沙箱实跑检验，排查 7 类结构漏洞并填写 Evidence Ledger；"
            "若主结论击穿但局部引理严密，可判 PARTIAL_PASS 推进至 Stage 2 降级收编。"
        ),
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


def tool_submit_stage1_blind_ledger(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    review_id: str,
    question_id: str,
    ledger_items: list[dict[str, Any]],
    stage1_verdict: str,
    rigor_score: int,
    revision_or_refutation_reason: str | None = None,
    exact_refuted_scope_md: str | None = None,
    exploit_ticket_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """锁定 Stage 1 不可逆 Evidence Ledger，按 PASS / PARTIAL_PASS / REVISE / REFUTED 分流。"""
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
    validate_review_score("rigor_score", rigor_score)
    if sv in ("PASS", "PARTIAL_PASS") and rigor_score < 7:
        raise FailClosedError(ERR_INVALID_INPUT, f"{sv} 要求 rigor_score >= 7")
    if sv == "PASS" and any(item.get("is_verified") is False for item in ledger_items):
        raise FailClosedError(ERR_INVALID_INPUT, "主声称有未验证证据，局部严密时须用 PARTIAL_PASS，否则退修")
    ledger_json = json.dumps({"stage1_verdict": sv, "ledger_items": ledger_items}, ensure_ascii=False)

    if sv in ("PASS", "PARTIAL_PASS"):
        with rw_immediate_tx(conn):
            conn.execute(
                """
                UPDATE review_queue
                SET stage1_ledger_json = ?, stage1_locked_at = ?, rigor_score = ?, review_status = 'STAGE2_UNBLIND', updated_at = ?
                WHERE review_id = ?
                """,
                (ledger_json, now, rigor_score, now, review_id),
            )
            exploit_tid = enqueue_exploit_ticket_if_present(
                conn, question_id=question_id, review_id=review_id, exploit_ticket_payload=exploit_ticket_payload, now=now
            )
        msg = (
            "Stage 1 盲审账本已锁定为 PARTIAL_PASS（主结论有缺口但局部引理严密）！请立即调 get_unblinded_manuscript_and_peers 进入 Stage 2 裁定 ACCEPT_NARROWED 同事务收编 L3+L2。"
            if sv == "PARTIAL_PASS"
            else "Stage 1 盲审账本已永久锁定并 PASS！请立即调用 get_unblinded_manuscript_and_peers 进入 Stage 2 解盲横审。"
        )
        return build_tool_receipt(
            conn=conn,
            tool_name="submit_stage1_blind_ledger",
            question_id=question_id,
            next_step_guidance=msg,
            data={"review_id": review_id, "stage1_verdict": sv, "rigor_score": rigor_score, "review_status": "STAGE2_UNBLIND", "exploit_ticket_id": exploit_tid},
        )

    if sv == "REVISE":
        reason = str(revision_or_refutation_reason or "").strip()
        if not reason:
            raise FailClosedError(ERR_INVALID_INPUT, "Stage 1 判 REVISE 必须提供具体可操作的 revision_or_refutation_reason")
        with rw_immediate_tx(conn):
            conn.execute(
                "UPDATE review_queue SET stage1_ledger_json = ?, stage1_locked_at = ?, rigor_score = ?, updated_at = ? WHERE review_id = ?",
                (ledger_json, now, rigor_score, now, review_id),
            )
            r_info = _apply_revise_or_exhaust(conn, rev=rev, revision_items=[reason], reason_text=reason, now=now)
            exploit_tid = enqueue_exploit_ticket_if_present(
                conn, question_id=question_id, review_id=review_id, exploit_ticket_payload=exploit_ticket_payload, now=now
            )
        return build_tool_receipt(
            conn=conn,
            tool_name="submit_stage1_blind_ledger",
            question_id=question_id,
            next_step_guidance=(
                "一次性局部引理盲审未通过，意见已留档，原推进分支不受任何打断。"
                if r_info.get("local_lemma_one_shot")
                else (
                    f"Stage 1 判 REVISE 但已满最大返工轮次，已归档 L2 ({r_info.get('created_l2_id')}) 并置 SEALED。"
                    if r_info["exhausted_to_l2"]
                    else f"Stage 1 判 REVISE（累计返工 {r_info['revise_count']} 次），原分支已切回 ACTIVE_REVISING。"
                )
            ),
            data={"review_id": review_id, "stage1_verdict": "REVISE", "exploit_ticket_id": exploit_tid, **r_info},
        )

    # REFUTED
    reason = str(revision_or_refutation_reason or "").strip()
    scope_ref = str(exact_refuted_scope_md or "").strip()
    if not reason or not scope_ref:
        raise FailClosedError(ERR_INVALID_INPUT, "Stage 1 判 REFUTED 必须填写 revision_or_refutation_reason 与 exact_refuted_scope_md")
    with rw_immediate_tx(conn):
        conn.execute(
            """
            UPDATE review_queue
            SET stage1_ledger_json = ?, stage1_locked_at = ?, rigor_score = ?, final_locked_at = ?,
                review_status = 'CLOSED_REFUTED', final_verdict = 'REFUTED', updated_at = ?
            WHERE review_id = ?
            """,
            (ledger_json, now, rigor_score, now, now, review_id),
        )
        l2_id = _archive_to_l2_and_seal(
            conn,
            rev=rev,
            l2_category="REFUTED",
            title=f"[证伪否定] {rev['manuscript_title']}",
            abstract_md=reason,
            refuted_scope=scope_ref,
            now=now,
            seal_source_node=not is_local_lemma_review(rev),
            rigor_score=rigor_score,
        )
        exploit_tid = enqueue_exploit_ticket_if_present(
            conn, question_id=question_id, review_id=review_id, exploit_ticket_payload=exploit_ticket_payload, now=now
        )
    return build_tool_receipt(
        conn=conn,
        tool_name="submit_stage1_blind_ledger",
        question_id=question_id,
        next_step_guidance=f"Stage 1 实测证伪短路结案，已归档 {l2_id} (REFUTED)。",
        data={
            "review_id": review_id,
            "stage1_verdict": "REFUTED",
            "created_l2_id": l2_id,
            "node_status": "UNCHANGED" if is_local_lemma_review(rev) else "SEALED",
            "exploit_ticket_id": exploit_tid,
        },
    )


def tool_get_unblinded_manuscript_and_peers(
    conn: sqlite3.Connection,
    workspace_root: str,
    caller_role: str,
    session_id: str,
    review_id: str,
) -> dict[str, Any]:
    """Stage 2 解盲横审拉取（附带本题 OPEN 悬赏缺口与子题生效口径），或 Stage 3 冻结包终核。"""
    enforce_role_tool_permission(conn, caller_role, "get_unblinded_manuscript_and_peers", session_id=session_id)

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
                SELECT entry_id, question_id, l3_entry_kind, goal_coverage, verified_spec_revision,
                       title, exact_verified_scope_md, exact_refuted_scope_md
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
            next_step_guidance="请在空白沙箱核查不可变冻结包五件套未夸大任何 L3 边界且复现一致，调 submit_stage2_unblind_verdict(ACCEPT) 将直接一步原子结项。",
            data={
                "mode": "STAGE3_FINAL_AUDIT",
                "review_id": review_id,
                "delivery_id": target_did,
                "delivery_sha256": str(closure["latest_delivery_sha256"]),
                "frozen_delivery_dir_abs_path": str(closure["frozen_delivery_dir_abs_path"] or ""),
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
            SELECT entry_id, l3_entry_kind, goal_coverage, publish_tier, verified_spec_revision, title, abstract_md, exact_verified_scope_md
            FROM internal_research_ledger
            WHERE question_id = ? AND ledger_type = 'L3_VERIFIED' AND is_active = 1
            ORDER BY entry_id
            """,
            (qid,),
        ).fetchall()
    ]
    open_gaps = [
        dict(r)
        for r in conn.execute(
            "SELECT gap_id, blocked_node_id, formal_statement_md, verification_spec_md FROM open_lemma_gaps WHERE question_id = ? AND status = 'OPEN' AND gap_tier = 'LOAD_BEARING' ORDER BY created_at ASC",
            (qid,),
        ).fetchall()
    ]
    peer_in_review = [
        dict(r)
        for r in conn.execute(
            "SELECT review_id, source_type, review_status, manuscript_title FROM review_queue WHERE question_id = ? AND review_id != ? AND review_status IN ('STAGE1_BLIND', 'STAGE2_UNBLIND')",
            (qid, review_id),
        ).fetchall()
    ]
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

    active_spec_rev = get_subproblem_active_spec_revision(conn, qid)
    p0_rev_row = conn.execute("SELECT latest_ruling_summary_md FROM parse0_contract WHERE contract_id = 'active'").fetchone()
    latest_ruling_summary = str(p0_rev_row["latest_ruling_summary_md"] or "") if p0_rev_row else ""
    rev_spec = int(rev["spec_revision"] or 0)
    spec_outdated = rev_spec < active_spec_rev

    ledger = json.loads(rev["stage1_ledger_json"] or "[]")
    ledger_items = ledger["ledger_items"] if isinstance(ledger, dict) else ledger
    composite = composite_entries(conn, rev) if rev["source_type"] == "COMPOSITE_FULL_GOAL" else []

    return build_tool_receipt(
        conn=conn,
        tool_name="get_unblinded_manuscript_and_peers",
        question_id=qid,
        next_step_guidance=(
            f"注意：该手稿绑定旧口径 v{rev_spec} < 本子题 {qid} 当前生效口径 v{active_spec_rev}，禁止标为 FULL_GOAL！"
            if spec_outdated
            else f"请结合 B 栏、同题 L3 及 {len(open_gaps)} 条 OPEN 悬赏缺口调 submit_stage2_unblind_verdict 下达终判（若满足任一悬赏请填 fulfilled_gap_ids）。"
        ),
        data={
            "review_id": review_id,
            "question_id": qid,
            "source_type": str(rev["source_type"]),
            "spec_revision": rev_spec,
            "active_spec_revision": active_spec_rev,
            "spec_revision_outdated": spec_outdated,
            "latest_ruling_summary_md": latest_ruling_summary,
            "column_b_snapshot_md": str(rev["column_b_snapshot_md"]),
            "stage1_ledger": ledger_items,
            "rigor_score": rev["rigor_score"],
            "declared_citations": json.loads(rev["declared_citations_json"]),
            "peer_calibration_pack": build_peer_calibration_pack(conn, qid),
            "composite_entries_full": composite,
            "peer_l3_entries": peer_l3,
            "open_lemma_gaps": open_gaps,
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
    publish_tier: str | None = None,
    is_equivalent_reduction: bool = False,
    title: str = "",
    abstract_md: str = "",
    exact_verified_scope_md: str | None = None,
    exact_refuted_scope_md: str | None = None,
    narrowed_l2_title: str | None = None,
    revision_requests: list[str] | None = None,
    cross_draft_comparison_notes: str = "",
    fulfilled_gap_ids: list[str] | None = None,
    exploit_ticket_payload: dict[str, Any] | None = None,
    edge_type_overrides: dict[str, str] | None = None,
    novelty_score: int | None = None,
    significance_score: int | None = None,
    reviewer_comment_md: str = "",
    tags: list[str] | None = None,
    confirmed_citations: list[str] | None = None,
) -> dict[str, Any]:
    """Stage 2 终判与 Stage 3 不可变冻结目录一步原子终签。"""
    enforce_role_tool_permission(conn, caller_role, "submit_stage2_unblind_verdict", session_id=session_id)
    fv = str(final_verdict or "").strip().upper()
    if fv not in ALLOWED_FINAL_VERDICTS:
        raise FailClosedError(ERR_INVALID_INPUT, f"非法 final_verdict={final_verdict!r}，仅允许 {sorted(ALLOWED_FINAL_VERDICTS)}")

    now = utc_now_iso()

    # 分支 1：Stage 3 不可变冻结目录一步原子终签（裁决 3）
    if str(review_id).startswith("STAGE3_FINAL_AUDIT:"):
        target_did = str(review_id).split(":", 1)[1].strip()
        if fv in ("ACCEPT", "ACCEPT_NARROWED"):
            closed = finalize_stage3_closure_on_verifier_accept(conn, target_delivery_id=target_did)
            return build_tool_receipt(
                conn=conn,
                tool_name="submit_stage2_unblind_verdict",
                question_id="ALL",
                next_step_guidance=f"五件套冻结包 {target_did} 已通过终核并原子结项（CLOSED_VERIFIED），全卷子题已置 CLOSED！",
                data={"mode": "STAGE3_FINAL_AUDIT", **closed},
            )
        rev_notes = "; ".join(str(x) for x in (revision_requests or []) if str(x).strip()) or str(abstract_md or "请修正边界表述与复现一致性")
        returned_to_stage2 = False
        next_closure_status = "REVISION_REQUESTED"
        with rw_immediate_tx(conn):
            closure = conn.execute("SELECT * FROM project_closure_state WHERE id = 1").fetchone()
            if closure is None or str(closure["status"]) != "DELIVERY_EXPORTED":
                raise FailClosedError(ERR_LOCKED, "当前项目不处于 DELIVERY_EXPORTED 状态")
            if not target_did or target_did != str(closure["latest_delivery_id"] or ""):
                raise FailClosedError(ERR_CONFLICT, f"终核退修拦截：审定版本 {target_did!r} != 当前最新版本 {closure['latest_delivery_id']!r}")

            # 统一判断冻结包是否已因改题升版或撤回 L3 丧失结项资格：若失效则退回 STAGE2_EVOLVE / OPEN，避免死锁在 Stage 3
            manifest_mode = "FULL"
            manifest_q_revs: dict[str, int] = {}
            frozen_raw = str(closure["frozen_delivery_dir_abs_path"] or "").strip()
            if frozen_raw:
                manifest_fp = Path(frozen_raw) / "delivery_manifest.json"
                if manifest_fp.is_file():
                    try:
                        m_obj = json.loads(manifest_fp.read_text(encoding="utf-8"))
                        if isinstance(m_obj, dict):
                            if m_obj.get("delivery_mode"):
                                manifest_mode = str(m_obj["delivery_mode"]).strip().upper()
                            if isinstance(m_obj.get("subproblem_spec_revisions"), dict):
                                manifest_q_revs = {str(k): int(v or 0) for k, v in m_obj["subproblem_spec_revisions"].items()}
                    except Exception:
                        pass

            gate_now = check_stage2_closure_gate_data(
                conn, mode=manifest_mode, human_aborted=(manifest_mode == "PARTIAL_ON_HUMAN_STOP")
            )
            stale_qs: list[str] = []
            if manifest_mode == "FULL":
                for qid_chk in gate_now.get("required_questions") or []:
                    cur_q_rev = get_subproblem_active_spec_revision(conn, str(qid_chk))
                    frozen_q_rev = manifest_q_revs.get(str(qid_chk), -1)
                    if frozen_q_rev >= 0 and cur_q_rev != frozen_q_rev:
                        stale_qs.append(f"{qid_chk}(v{frozen_q_rev}->v{cur_q_rev})")

            if (not gate_now["closure_allowed"]) or stale_qs:
                returned_to_stage2 = True
                next_closure_status = "OPEN"

            cur = conn.execute(
                """
                UPDATE project_closure_state
                SET status = ?, verifier_final_audit_passed = 0,
                    verifier_revision_notes = ?, updated_at = ?
                WHERE id = 1 AND status = 'DELIVERY_EXPORTED' AND latest_delivery_id = ?
                """,
                (next_closure_status, rev_notes[:2000], now, target_did),
            )
            if cur.rowcount != 1:
                raise FailClosedError(ERR_CONFLICT, f"终核退修版本冲突：{target_did!r} 状态已变更")
            if returned_to_stage2:
                conn.execute(
                    "UPDATE parse0_contract SET stage = 'STAGE2_EVOLVE', updated_at = ? WHERE contract_id = 'active'",
                    (now,),
                )
        return build_tool_receipt(
            conn=conn,
            tool_name="submit_stage2_unblind_verdict",
            question_id="ALL",
            next_step_guidance=(
                "检测到终核期间结项资格已因口径升版/变更失效，已退回 STAGE2_EVOLVE / OPEN 恢复探索补齐新口径成果。"
                if returned_to_stage2
                else "终核退修已置为 REVISION_REQUESTED，派回 library_chronicler 修正并重导新版本冻结包。"
            ),
            data={
                "mode": "STAGE3_FINAL_AUDIT",
                "delivery_id": target_did,
                "closure_status": next_closure_status,
                "returned_to_stage2": returned_to_stage2,
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

    qid = str(rev["question_id"])
    bound_obs = json.loads(rev["bound_obs_ids_json"] or "[]")
    local_lemma = is_local_lemma_review(rev)

    rigor = rev["rigor_score"]
    for field, score in (("novelty_score", novelty_score), ("significance_score", significance_score)):
        if score is not None or (rigor is not None and fv in ("ACCEPT", "ACCEPT_NARROWED", "REJECT_DUPLICATE")):
            validate_review_score(field, score)
    composite = rev["source_type"] == "COMPOSITE_FULL_GOAL"
    reduction_percentages = re.findall(r"(?<![\d.+−-])(\d+(?:\.\d+)?)\s*[%％]", cross_draft_comparison_notes)
    substantial_reduction = is_equivalent_reduction and any(20 <= float(p) <= 100 for p in reduction_percentages)
    if novelty_score is not None and novelty_score <= 3 and not substantial_reduction:
        fv = "REJECT_DUPLICATE"
    if fv == "REJECT_DUPLICATE":
        with rw_immediate_tx(conn):
            require_unclosed_stage2(conn, review_id)
            conn.execute(
                """
                UPDATE review_queue SET review_status = 'CLOSED_DUPLICATE', final_verdict = 'REJECT_DUPLICATE',
                    final_locked_at = ?, novelty_score = ?, significance_score = ?, updated_at = ?
                WHERE review_id = ?
                """,
                (now, novelty_score, significance_score, now, review_id),
            )
            if not local_lemma:
                conn.execute("UPDATE lineage_nodes SET node_status = 'SEALED', updated_at = ? WHERE node_id = ?",
                             (now, rev["source_node_id"]))
        return build_tool_receipt(
            conn=conn, tool_name="submit_stage2_unblind_verdict", question_id=qid,
            next_step_guidance="查重退稿，审稿单已结案。",
            data={"review_id": review_id, "review_status": "CLOSED_DUPLICATE", "final_verdict": fv},
        )

    if fv == "REVISE":
        req_items = [str(x).strip() for x in (revision_requests or []) if str(x).strip()]
        if not req_items:
            raise FailClosedError(ERR_INVALID_INPUT, "Stage 2 判 REVISE 必须提供非空 revision_requests")
        with rw_immediate_tx(conn):
            require_unclosed_stage2(conn, review_id)
            conn.execute("UPDATE review_queue SET novelty_score = ?, significance_score = ? WHERE review_id = ?",
                         (novelty_score, significance_score, review_id))
            r_info = _apply_revise_or_exhaust(conn, rev=rev, revision_items=req_items, reason_text="; ".join(req_items), now=now)
            exploit_tid = enqueue_exploit_ticket_if_present(
                conn, question_id=qid, review_id=review_id, exploit_ticket_payload=exploit_ticket_payload, now=now
            )
        return build_tool_receipt(
            conn=conn,
            tool_name="submit_stage2_unblind_verdict",
            question_id=qid,
            next_step_guidance=(
                "局部引理一次性盲审未通过，意见已留档，原推进分支不受任何打断。"
                if r_info.get("local_lemma_one_shot")
                else f"Stage 2 判 REVISE（累计返工 {r_info['revise_count']} 次）。"
            ),
            data={"review_id": review_id, "final_verdict": "REVISE", "exploit_ticket_id": exploit_tid, **r_info},
        )

    if fv == "REFUTED":
        ref_scope = str(exact_refuted_scope_md or "").strip()
        if not ref_scope:
            raise FailClosedError(ERR_INVALID_INPUT, "Stage 2 判 REFUTED 必须填写 exact_refuted_scope_md")
        with rw_immediate_tx(conn):
            require_unclosed_stage2(conn, review_id)
            conn.execute(
                """UPDATE review_queue SET review_status = 'CLOSED_REFUTED', final_verdict = 'REFUTED',
                       final_locked_at = ?, novelty_score = ?, significance_score = ?, updated_at = ? WHERE review_id = ?""",
                (now, novelty_score, significance_score, now, review_id),
            )
            l2_id = _archive_to_l2_and_seal(
                conn,
                rev=rev,
                l2_category="REFUTED",
                title=str(title or "").strip() or f"[证伪否定] {rev['manuscript_title']}",
                abstract_md=str(abstract_md or "").strip() or ref_scope,
                refuted_scope=ref_scope,
                now=now,
                seal_source_node=not local_lemma,
                novelty_score=novelty_score, significance_score=significance_score, reviewer_comment_md=reviewer_comment_md,
            )
            exploit_tid = enqueue_exploit_ticket_if_present(
                conn, question_id=qid, review_id=review_id, exploit_ticket_payload=exploit_ticket_payload, now=now
            )
        return build_tool_receipt(
            conn=conn,
            tool_name="submit_stage2_unblind_verdict",
            question_id=qid,
            next_step_guidance=f"Stage 2 判 REFUTED，已入库 {l2_id}。",
            data={"review_id": review_id, "final_verdict": "REFUTED", "created_l2_id": l2_id, "exploit_ticket_id": exploit_tid},
        )

    # ACCEPT / ACCEPT_NARROWED
    kind_u = str(l3_entry_kind or "").strip().upper()
    cov_u = str(goal_coverage or "").strip().upper()
    ptier_u = str(publish_tier or "BASELINE_UPDATE").strip().upper()
    if kind_u not in ALLOWED_L3_ENTRY_KINDS:
        raise FailClosedError(ERR_INVALID_INPUT, f"ACCEPT* 必须提供合法 l3_entry_kind {sorted(ALLOWED_L3_ENTRY_KINDS)}")
    if cov_u not in ALLOWED_GOAL_COVERAGES:
        raise FailClosedError(ERR_INVALID_INPUT, f"ACCEPT* 必须提供合法 goal_coverage {sorted(ALLOWED_GOAL_COVERAGES)}")
    if ptier_u not in ALLOWED_PUBLISH_TIERS:
        raise FailClosedError(ERR_INVALID_INPUT, f"非法 publish_tier={publish_tier!r}，仅允许 {sorted(ALLOWED_PUBLISH_TIERS)}")
    ledger = json.loads(rev["stage1_ledger_json"])
    if isinstance(ledger, dict) and ledger["stage1_verdict"] == "PARTIAL_PASS" and fv != "ACCEPT_NARROWED":
        raise FailClosedError(ERR_INVALID_INPUT, "PARTIAL_PASS 须使用 ACCEPT_NARROWED 录用局部结论")
    if significance_score is not None and significance_score <= 4:
        ptier_u = "MARGINAL_NOTE"
    if ptier_u == "BASELINE_UPDATE" and significance_score is not None and significance_score < 7:
        raise FailClosedError(ERR_INVALID_INPUT, "BASELINE_UPDATE 要求 significance_score >= 7")
    if composite and (fv != "ACCEPT" or cov_u != "FULL_GOAL" or ptier_u == "MARGINAL_NOTE"):
        raise FailClosedError(ERR_INVALID_INPUT, "组合完备稿录用须通过完整目标核验（ACCEPT、FULL_GOAL）")
    overall = round(0.40 * rigor + 0.25 * novelty_score + 0.35 * significance_score, 1) if rigor is not None else None

    if (fv == "ACCEPT_NARROWED" or bool(is_equivalent_reduction)) and cov_u == "FULL_GOAL":
        raise FailClosedError(
            ERR_INVALID_INPUT,
            "防伪完成硬护栏：ACCEPT_NARROWED 或 is_equivalent_reduction=true 严禁标为 FULL_GOAL！请设为 PARTIAL_OR_LEMMA 或 EQUIVALENT_REDUCTION。",
        )

    clean_title = str(title or "").strip()
    clean_abs = str(abstract_md or "").strip()
    clean_scope = str(exact_verified_scope_md or "").strip()
    clean_refuted = str(exact_refuted_scope_md or "").strip()
    if not clean_title or len(clean_abs) < 40 or not clean_scope:
        raise FailClosedError(ERR_INVALID_INPUT, "ACCEPT* 必须填写非空 title、>=40 字独立 abstract_md 及 exact_verified_scope_md")
    if fv == "ACCEPT_NARROWED" and not clean_refuted:
        raise FailClosedError(ERR_INVALID_INPUT, "ACCEPT_NARROWED 必须提供 exact_refuted_scope_md 以同事务落库主命题失灵边界 L2")

    rev_spec = int(rev["spec_revision"] or 0)
    created_narrowed_l2_id: str | None = None
    woken_gaps: list[dict[str, Any]] = []
    exploit_tid: str | None = None

    with rw_immediate_tx(conn):
        require_unclosed_stage2(conn, review_id)
        children = composite_entries(conn, rev) if composite else []
        citations = validate_library_citations(conn, [*(confirmed_citations or []), *(r["entry_id"] for r in children)])
        # 裁决 4：在单写者写锁内部实时校验子题级 active_spec_revision（防并发改题与防跨题连坐！）
        active_spec_rev = get_subproblem_active_spec_revision(conn, qid)
        if rev_spec < active_spec_rev and cov_u == "FULL_GOAL":
            raise FailClosedError(
                ERR_INVALID_INPUT,
                f"子题口径防伪完成硬护栏：该手稿绑定旧口径 v{rev_spec} < 子题 {qid} 当前生效口径 v{active_spec_rev}，禁止标为 FULL_GOAL！",
            )

        if isinstance(edge_type_overrides, dict):
            for ref_dst, new_etype in edge_type_overrides.items():
                nt = str(new_etype).strip().upper()
                if nt not in ALLOWED_CLAIMED_EDGE_TYPES:
                    raise FailClosedError(ERR_INVALID_INPUT, f"edge_type_overrides 包含非法边类型: {new_etype!r}")
                if bound_obs:
                    oph = ",".join("?" for _ in bound_obs)
                    conn.execute(
                        f"UPDATE epistemic_edges SET edge_type = ? WHERE edge_track = 'CLAIM_DECLARED' AND target_id = ? AND source_id IN ({oph})",
                        (nt, str(ref_dst), *bound_obs),
                    )

        conn.execute(
            """UPDATE review_queue SET review_status = 'CLOSED_ACCEPTED', final_verdict = ?, final_locked_at = ?,
                   novelty_score = ?, significance_score = ?, updated_at = ? WHERE review_id = ?""",
            (fv, now, novelty_score, significance_score, now, review_id),
        )

        entry_id = next_prefixed_id(conn, "internal_research_ledger", "entry_id", "L3-")
        conn.execute(
            """
            INSERT INTO internal_research_ledger(
                entry_id, question_id, ledger_type, l3_entry_kind, goal_coverage, l2_category,
                title, abstract_md, exact_verified_scope_md, exact_refuted_scope_md,
                body_proof_or_code_md, bound_obs_ids_json, verified_review_id,
                verified_spec_revision, publish_tier, is_active, created_at,
                author_node_id, author_branch_id, author_family_id, tags_json, cited_entries_json,
                rigor_score, novelty_score, significance_score, overall_score, reviewer_comment_md
            ) VALUES (?, ?, 'L3_VERIFIED', ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id,
                qid,
                kind_u,
                cov_u,
                clean_title,
                clean_abs,
                clean_scope,
                clean_refuted or None,
                str(rev["column_a_snapshot_md"] or ""),
                json.dumps(bound_obs, ensure_ascii=False),
                review_id,
                rev_spec,
                ptier_u,
                now,
                *review_author(conn, rev),
                json.dumps(tags or [], ensure_ascii=False), json.dumps(citations, ensure_ascii=False),
                rigor, novelty_score, significance_score, overall, reviewer_comment_md,
            ),
        )

        record_publication_citations(conn, entry_id, citations, session_id, composite=composite)

        # 裁决 3：ACCEPT_NARROWED 同事务追加 1 条 L2_FAILURE_RECORD 忠实记录主命题失灵边界
        if fv == "ACCEPT_NARROWED" and clean_refuted:
            created_narrowed_l2_id = _archive_to_l2_and_seal(
                conn,
                rev=rev,
                l2_category="REFUTED",
                title=str(narrowed_l2_title or "").strip() or f"[缩窄失灵边界] {clean_title}",
                abstract_md=clean_refuted,
                refuted_scope=clean_refuted,
                now=now,
                seal_source_node=False,
                novelty_score=novelty_score, significance_score=significance_score, reviewer_comment_md=reviewer_comment_md,
            )

        if isinstance(edge_type_overrides, dict):
            for ref_dst, new_etype in edge_type_overrides.items():
                nt = str(new_etype).strip().upper()
                if ref_dst in citations:
                    if not composite:
                        conn.execute(
                            "UPDATE epistemic_edges SET edge_type = ? WHERE source_id = ? AND target_id = ? AND edge_track = 'CLAIM_DECLARED'",
                            (nt, entry_id, ref_dst),
                        )
                    continue
                conn.execute(
                    """
                    INSERT INTO epistemic_edges(edge_id, source_id, target_id, edge_track, edge_type, session_id, metadata_json, created_at)
                    VALUES (?, ?, ?, 'CLAIM_DECLARED', ?, ?, '{}', ?)
                    """,
                    (f"ce_{uuid.uuid4().hex[:12]}", entry_id, str(ref_dst), nt, session_id, now),
                )

        if not local_lemma:
            conn.execute("UPDATE lineage_nodes SET node_status = 'SEALED', updated_at = ? WHERE node_id = ?", (now, str(rev["source_node_id"])))

        # 清零无 L3 停滞计数；若 publish_tier 为 BASELINE_UPDATE 且口径不低于子题生效口径，同步更新 baseline_entry_id
        q_rev_row = conn.execute(
            "SELECT active_spec_revision FROM subproblem_runtime_state WHERE question_id = ?",
            (qid,),
        ).fetchone()
        active_q_rev = int(q_rev_row["active_spec_revision"] or 0) if q_rev_row else 0
        if ptier_u == "BASELINE_UPDATE" and rev_spec >= active_q_rev:
            conn.execute(
                """
                UPDATE subproblem_runtime_state
                SET completed_nodes_since_last_l3 = 0,
                    baseline_entry_id = ?,
                    updated_at = ?
                WHERE question_id = ?
                """,
                (entry_id, now, qid),
            )
        elif ptier_u != "MARGINAL_NOTE":
            conn.execute(
                "UPDATE subproblem_runtime_state SET completed_nodes_since_last_l3 = 0, updated_at = ? WHERE question_id = ?",
                (now, qid),
            )

        if ptier_u != "MARGINAL_NOTE":
            woken_gaps = fulfill_open_gaps_and_wake_branches(
                conn, question_id=qid, fulfilled_gap_ids=fulfilled_gap_ids, fulfilled_by_l3_id=entry_id, now=now,
            )
        exploit_tid = enqueue_exploit_ticket_if_present(
            conn, question_id=qid, review_id=review_id, exploit_ticket_payload=exploit_ticket_payload, now=now
        )

    # 锁一即刻停派检查（FULL_GOAL 且匹配子题生效口径时立刻停派同题并入队 DRAIN）
    lock_eval = evaluate_subproblem_locks(conn, question_id=qid)

    return build_tool_receipt(
        conn=conn,
        tool_name="submit_stage2_unblind_verdict",
        question_id=qid,
        next_step_guidance=(
            f"审稿单 {review_id} 终判 {fv}，已入库 {entry_id} ({kind_u}/{cov_u}/{ptier_u}, v{rev_spec})"
            + (f" 与失灵边界 {created_narrowed_l2_id}" if created_narrowed_l2_id else "")
            + (f"，核销并唤醒 {len(woken_gaps)} 条悬赏缺口" if woken_gaps else "")
            + "。"
        ),
        data={
            "review_id": review_id,
            "final_verdict": fv,
            "created_l3_id": entry_id,
            "created_narrowed_l2_id": created_narrowed_l2_id,
            "l3_entry_kind": kind_u,
            "goal_coverage": cov_u,
            "publish_tier": ptier_u,
            "overall_score": overall,
            "verified_spec_revision": rev_spec,
            "fulfilled_gaps": woken_gaps,
            "exploit_ticket_id": exploit_tid,
            "subproblem_lock_eval": lock_eval.get("evaluated", []),
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
    """沉船遗产打捞：强校验原分支不处于在研/返工态，生成新 STAGE1_BLIND 交异会话复验。"""
    enforce_role_tool_permission(conn, caller_role, "propose_salvaged_lemma", session_id=session_id)
    node = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (source_node_id,)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"源节点 {source_node_id!r} 不存在")
    if str(node["question_id"]) != str(question_id):
        raise FailClosedError(ERR_INVALID_INPUT, f"question_id 与源节点不匹配 ({question_id!r} != {node['question_id']!r})")
    if str(node["node_status"]) in ("ACTIVE_REVISING", "EXPLORING", "PENDING_REVIEW"):
        raise FailClosedError(
            ERR_LOCKED,
            f"AUDITOR_SALVAGE_FORBIDDEN: 源节点 {source_node_id!r} 当前处于 {node['node_status']}，严禁打捞在研或返工中分支！",
        )

    clean_obs = [str(o).strip() for o in (bound_obs_ids or []) if str(o).strip()]
    for oid in clean_obs:
        if conn.execute("SELECT 1 FROM observations WHERE obs_id = ?", (oid,)).fetchone() is None:
            raise FailClosedError(ERR_NOT_FOUND, f"绑定观测 {oid!r} 不存在")

    if not str(title or "").strip() or not str(column_a_self_contained_proof_md or "").strip():
        raise FailClosedError(ERR_INVALID_INPUT, "title 与 column_a_self_contained_proof_md 不能为空")

    rev_id = next_prefixed_id(conn, "review_queue", "review_id", "rev_")
    node_spec = int(node["spec_revision"] or 0)
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
        next_step_guidance=f"沉船遗产引理已建独立盲审单 {rev_id}（STAGE1_BLIND），须由另一独立 library_verifier 会话在空白沙箱复验通过后入 L3。",
        data={"created_review_id": rev_id, "source_node_id": source_node_id, "review_status": "STAGE1_BLIND"},
    )
