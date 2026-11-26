"""GreatWall v0.3 盲审官内部辅助模块：异会话防自审、L2 归档、悬赏核销唤醒与 EXPLOIT 工单。"""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from .control_plane.effects_outbox import enqueue_runtime_effect
from .control_plane.subproblem_locks import get_subproblem_active_spec_revision
from .db_schema import (
    ERR_CONFLICT,
    FailClosedError,
)
from .mcp_core_helpers import load_runtime_config, next_prefixed_id


def require_non_self_review(
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


def is_local_lemma_review(rev: sqlite3.Row) -> bool:
    """裁决 2：从活节点独立拆交的局部引理走一次性盲审，绝不锁死也不打断继续推进的原分支。"""
    return str(rev["source_type"] or "").strip().upper() == "LOCAL_LEMMA_SUBMISSION"


def archive_to_l2_and_seal(
    conn: sqlite3.Connection,
    *,
    rev: sqlite3.Row,
    l2_category: str,
    title: str,
    abstract_md: str,
    refuted_scope: str,
    now: str,
    seal_source_node: bool = True,
) -> str:
    entry_id = next_prefixed_id(conn, "internal_research_ledger", "entry_id", "L2-")
    conn.execute(
        """
        INSERT INTO internal_research_ledger(
            entry_id, question_id, ledger_type, l3_entry_kind, goal_coverage, l2_category,
            title, abstract_md, exact_verified_scope_md, exact_refuted_scope_md,
            body_proof_or_code_md, bound_obs_ids_json, verified_review_id,
            verified_spec_revision, is_active, created_at
        ) VALUES (?, ?, 'L2_FAILURE_RECORD', NULL, NULL, ?, ?, ?, NULL, ?, ?, ?, ?, ?, 1, ?)
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
            int(rev["spec_revision"] or 0),
            now,
        ),
    )
    if seal_source_node and not is_local_lemma_review(rev):
        conn.execute(
            "UPDATE lineage_nodes SET node_status = 'SEALED', updated_at = ? WHERE node_id = ?",
            (now, str(rev["source_node_id"])),
        )
    return entry_id


def apply_revise_or_exhaust(
    conn: sqlite3.Connection,
    *,
    rev: sqlite3.Row,
    revision_items: list[str],
    reason_text: str,
    now: str,
) -> dict[str, Any]:
    """处理 REVISE 退修；若为 LOCAL_LEMMA_SUBMISSION 则走一次性结单，绝不打断已推进的原分支（裁决 2）。"""
    if is_local_lemma_review(rev):
        conn.execute(
            """
            UPDATE review_queue
            SET review_status = 'CLOSED_REVISE', final_verdict = 'REVISE',
                final_locked_at = ?, revision_requests_json = ?, updated_at = ?
            WHERE review_id = ?
            """,
            (now, json.dumps(revision_items, ensure_ascii=False), now, rev["review_id"]),
        )
        return {
            "exhausted_to_l2": False,
            "local_lemma_one_shot": True,
            "revise_count": 0,
            "node_status": "UNCHANGED",
        }

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
        conn.execute(
            """
            UPDATE lineage_nodes
            SET node_status = 'ACTIVE_REVISING', revise_count = ?, last_revision_requests_json = ?,
                briefing_sealed_at = NULL, updated_at = ?
            WHERE node_id = ?
            """,
            (new_revise, json.dumps(revision_items, ensure_ascii=False), now, node["node_id"]),
        )
        conn.execute("DELETE FROM lineage_briefings WHERE node_id = ?", (node["node_id"],))
        return {"exhausted_to_l2": False, "revise_count": new_revise, "node_status": "ACTIVE_REVISING"}

    conn.execute(
        """
        UPDATE review_queue
        SET review_status = 'CLOSED_REFUTED', final_verdict = 'REFUTED',
            final_locked_at = ?, revision_requests_json = ?, updated_at = ?
        WHERE review_id = ?
        """,
        (now, json.dumps(revision_items, ensure_ascii=False), now, rev["review_id"]),
    )
    l2_id = archive_to_l2_and_seal(
        conn,
        rev=rev,
        l2_category="UNRESOLVED_OBJECTION",
        title=f"[REVISE超限] {rev['manuscript_title']}",
        abstract_md=reason_text or "; ".join(revision_items) or "超过最大返工轮次仍未解决审稿异议",
        refuted_scope=reason_text or "; ".join(revision_items) or "返工超限未解异议",
        now=now,
        seal_source_node=True,
    )
    return {"exhausted_to_l2": True, "revise_count": cur_revise + 1, "created_l2_id": l2_id, "node_status": "SEALED"}


def enqueue_exploit_ticket_if_present(
    conn: sqlite3.Connection,
    *,
    question_id: str,
    review_id: str,
    exploit_ticket_payload: dict[str, Any] | None,
    now: str,
) -> str | None:
    """盲审发现评测器漏洞/反作弊漏洞时同事务签发 EXPLOIT 工单交工造司修补。"""
    if not isinstance(exploit_ticket_payload, dict) or not exploit_ticket_payload:
        return None
    tid = f"tkt_{uuid.uuid4().hex[:10]}"
    inst_id = str(exploit_ticket_payload.get("instrument_id") or "").strip() or None
    payload = {"source": "library_verifier", "review_id": review_id, **exploit_ticket_payload}
    conn.execute(
        """
        INSERT INTO works_engineering_queue(ticket_id, question_id, ticket_type, instrument_id, payload_json, status, created_at, updated_at)
        VALUES (?, ?, 'EXPLOIT', ?, ?, 'OPEN', ?, ?)
        """,
        (tid, question_id, inst_id, json.dumps(payload, ensure_ascii=False), now, now),
    )
    return tid


def fulfill_open_gaps_and_wake_branches(
    conn: sqlite3.Connection,
    *,
    question_id: str,
    fulfilled_gap_ids: list[str] | None,
    fulfilled_by_l3_id: str,
    now: str,
) -> list[dict[str, Any]]:
    """原子核销 open_lemma_gaps 并自动唤醒受阻的 BLOCKED_L4B 分支（建新代 EXPLORING + 投递 WAKE_BLOCKED_BRANCH）。"""
    clean_ids = [str(g).strip() for g in (fulfilled_gap_ids or []) if str(g).strip()]
    if not clean_ids:
        return []

    woken: list[dict[str, Any]] = []
    active_spec_rev = get_subproblem_active_spec_revision(conn, question_id)
    for gid in clean_ids:
        gap = conn.execute(
            "SELECT * FROM open_lemma_gaps WHERE gap_id = ? AND question_id = ? AND status = 'OPEN'",
            (gid, question_id),
        ).fetchone()
        if gap is None:
            continue
        conn.execute(
            """
            UPDATE open_lemma_gaps
            SET status = 'FULFILLED', fulfilled_by_entry_id = ?, fulfilled_at = ?
            WHERE gap_id = ?
            """,
            (fulfilled_by_l3_id, now, gid),
        )
        blk_nid = str(gap["blocked_node_id"] or "").strip()
        blk_node = (
            conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ? AND node_status = 'BLOCKED_L4B'", (blk_nid,)).fetchone()
            if blk_nid
            else None
        )
        next_node_id = None
        if blk_node is not None:
            next_node_id = f"node_{question_id.lower()}_{uuid.uuid4().hex[:8]}"
            conn.execute(
                "UPDATE lineage_nodes SET node_status = 'CLOSED', updated_at = ? WHERE node_id = ?",
                (now, blk_nid),
            )
            conn.execute(
                """
                INSERT INTO lineage_nodes(
                    node_id, question_id, branch_id, family_id, parent_node_id, generation, node_status,
                    worktree_abs_path, retained_snapshot_abs_path, mechanism_summary, requires_json,
                    revise_count, inplace_repair_count, last_revision_requests_json, spec_revision,
                    branch_kind, protection_generations_left, companion_session_id,
                    reopen_condition, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'EXPLORING', ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    next_node_id,
                    question_id,
                    str(blk_node["branch_id"]),
                    blk_node["family_id"],
                    blk_nid,
                    int(blk_node["generation"]) + 1,
                    str(blk_node["worktree_abs_path"]),
                    blk_node["retained_snapshot_abs_path"],
                    str(blk_node["mechanism_summary"] or "")[:99],
                    str(blk_node["requires_json"] or "[]"),
                    int(blk_node["revise_count"] or 0),
                    str(blk_node["last_revision_requests_json"] or "[]"),
                    active_spec_rev,
                    str(blk_node["branch_kind"] or "PURE"),
                    max(1, int(blk_node["protection_generations_left"] or 0)),
                    f"gw-comp-{next_node_id}",
                    f"悬赏缺口 {gid} 已由 {fulfilled_by_l3_id} 核销唤醒",
                    now,
                    now,
                ),
            )
            enqueue_runtime_effect(
                conn,
                effect_key=f"wake_gap:{gid}:{next_node_id}",
                kind="WAKE_BLOCKED_BRANCH",
                target_type="NODE",
                target_id=next_node_id,
                payload={"gap_id": gid, "fulfilled_by_l3_id": fulfilled_by_l3_id, "previous_node_id": blk_nid, "question_id": question_id},
            )
            # 若子题此前因 ALL_BRANCHES_BLOCKED 暂停，自动恢复 DISPATCHING
            conn.execute(
                """
                UPDATE subproblem_runtime_state
                SET dispatch_state = 'DISPATCHING', block_reason_code = '', block_detail_md = '', updated_at = ?
                WHERE question_id = ? AND desired_state = 'ACTIVE' AND dispatch_state = 'PAUSED_BLOCKED'
                  AND block_reason_code = 'ALL_BRANCHES_BLOCKED'
                """,
                (now, question_id),
            )
        woken.append({"gap_id": gid, "woken_node_id": next_node_id, "fulfilled_by_l3_id": fulfilled_by_l3_id})
    return woken
