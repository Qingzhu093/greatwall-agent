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
    ERR_INVALID_INPUT,
    ERR_LOCKED,
    FailClosedError,
)
from .mcp_core_helpers import load_runtime_config, next_prefixed_id, record_declared_refs


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
    return bool(rev["non_blocking"])


def validate_review_score(name: str, score: int | None) -> None:
    if type(score) is not int or not 1 <= score <= 10:
        raise FailClosedError(ERR_INVALID_INPUT, f"{name} 必须是 1–10 的整数")


def require_unclosed_stage2(conn: sqlite3.Connection, review_id: str) -> None:
    row = conn.execute("SELECT review_status FROM review_queue WHERE review_id = ?", (review_id,)).fetchone()
    if row["review_status"] != "STAGE2_UNBLIND":
        raise FailClosedError(ERR_LOCKED, f"审稿单 {review_id} 已有终判")


def review_author(conn: sqlite3.Connection, review: sqlite3.Row) -> tuple[str | None, str | None, str | None]:
    if review["source_type"] == "COMPOSITE_FULL_GOAL":
        return None, None, None
    node = conn.execute(
        "SELECT node_id, branch_id, family_id FROM lineage_nodes WHERE node_id = ?",
        (review["source_node_id"],),
    ).fetchone()
    return tuple(node) if node is not None else (review["source_node_id"], None, None)


def build_peer_calibration_pack(conn: sqlite3.Connection, question_id: str) -> dict[str, Any]:
    contract = conn.execute(
        "SELECT goal_and_completion_md, latest_ruling_summary_md FROM parse0_contract WHERE contract_id = 'active'"
    ).fetchone()
    papers = conn.execute(
        """
        SELECT entry_id, title, scope_md, author_family_id, rigor_score, novelty_score,
               significance_score, overall_score, publish_tier, verified_spec_revision
        FROM v_library_mini_papers_catalog
        WHERE question_id = ? AND ledger_type = 'L3_VERIFIED'
        """,
        (question_id,),
    )
    gaps = conn.execute(
        """
        SELECT gap_id, blocked_node_id, formal_statement_md, verification_spec_md
        FROM open_lemma_gaps WHERE question_id = ? AND status = 'OPEN' AND gap_tier = 'LOAD_BEARING'
        ORDER BY created_at
        """,
        (question_id,),
    )
    radar = conn.execute("SELECT * FROM v_library_avoidance_radar WHERE question_id = ?", (question_id,))
    return {
        "goal_and_completion_md": contract["goal_and_completion_md"] if contract else "",
        "latest_ruling_summary_md": contract["latest_ruling_summary_md"] if contract else "",
        "papers": [dict(row) for row in papers],
        "open_lemma_gaps": [dict(row) for row in gaps],
        "avoidance_radar": [dict(row) for row in radar],
    }


def composite_entries(conn: sqlite3.Connection, review: sqlite3.Row) -> list[dict[str, Any]]:
    ids = json.loads(review["composite_entry_ids_json"])
    result = [dict(row) for row in conn.execute(
        """
        SELECT * FROM internal_research_ledger
        WHERE entry_id IN (SELECT value FROM json_each(?)) AND question_id = ?
          AND ledger_type = 'L3_VERIFIED' AND is_active = 1 AND publish_tier != 'MARGINAL_NOTE'
          AND verified_spec_revision >= ? AND rigor_score >= 7
        ORDER BY entry_id
        """,
        (review["composite_entry_ids_json"], review["question_id"],
         get_subproblem_active_spec_revision(conn, review["question_id"])),
    )]
    if len(ids) < 2 or len(result) != len(ids):
        raise FailClosedError(ERR_LOCKED, "组合完备核验须包含至少两篇当前口径且严密性达标的有效 L3")
    return result


def validate_library_citations(
    conn: sqlite3.Connection, ids: list[str], *, question_id: str | None = None,
) -> list[str]:
    unique_ids = list(dict.fromkeys(ids))
    for ref in unique_ids:
        row = conn.execute(
            """
            SELECT question_id FROM internal_research_ledger WHERE entry_id = ? AND is_active = 1
            UNION ALL SELECT question_id FROM external_literature_cards WHERE ref_id = ?
            """,
            (ref, ref),
        ).fetchone()
        if row is None:
            raise FailClosedError(ERR_INVALID_INPUT, f"引用 {ref!r} 不存在或已失效")
        if question_id is not None and row["question_id"] not in (question_id, "ALL"):
            raise FailClosedError(ERR_INVALID_INPUT, f"引用 {ref!r} 超出子题 {question_id} 专题范围")
    return unique_ids


def record_publication_citations(
    conn: sqlite3.Connection, entry_id: str, citations: list[str], session_id: str, *, composite: bool,
) -> None:
    record_declared_refs(
        conn, source_id=entry_id, declared_refs=citations, session_id=session_id,
        default_edge_type="REQUIRED_PREMISE" if composite else "MOTIVATING_REF",
    )


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
    rigor_score: int | None = None,
    novelty_score: int | None = None,
    significance_score: int | None = None,
    reviewer_comment_md: str = "",
) -> str:
    entry_id = next_prefixed_id(conn, "internal_research_ledger", "entry_id", "L2-")
    conn.execute(
        """
        INSERT INTO internal_research_ledger(
            entry_id, question_id, ledger_type, l3_entry_kind, goal_coverage, publish_tier, l2_category,
            title, abstract_md, exact_verified_scope_md, exact_refuted_scope_md,
            body_proof_or_code_md, bound_obs_ids_json, verified_review_id,
            verified_spec_revision, is_active, created_at, author_node_id, author_branch_id, author_family_id,
            rigor_score, novelty_score, significance_score, reviewer_comment_md
        ) VALUES (?, ?, 'L2_FAILURE_RECORD', NULL, NULL, '', ?, ?, ?, NULL, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)
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
            *review_author(conn, rev),
            rigor_score if rigor_score is not None else rev["rigor_score"],
            novelty_score, significance_score, reviewer_comment_md,
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
        latest = conn.execute(
            """
            SELECT target.node_id
            FROM lineage_nodes author
            JOIN lineage_nodes target ON target.branch_id = author.branch_id AND target.question_id = author.question_id
            WHERE author.node_id = ?
            ORDER BY target.generation DESC LIMIT 1
            """,
            (rev["source_node_id"],),
        ).fetchone()
        if latest is not None:
            item = {"review_id": rev["review_id"], "revision_requests": revision_items, "created_at": now}
            conn.execute(
                """
                UPDATE lineage_nodes SET pending_review_feedback_json =
                    json_insert(pending_review_feedback_json, '$[#]', json(?)) WHERE node_id = ?
                """,
                (json.dumps(item, ensure_ascii=False), latest["node_id"]),
            )
            enqueue_runtime_effect(
                conn, effect_key=f"review_feedback:{rev['review_id']}", kind="DELIVER_BRANCH_NOTE",
                target_type="NODE", target_id=latest["node_id"],
                payload={"message": f"快照稿 {rev['review_id']} 已退修，请查阅分支待处理审稿意见。"},
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
            "SELECT * FROM open_lemma_gaps WHERE gap_id = ? AND question_id = ? AND status = 'OPEN' AND gap_tier = 'LOAD_BEARING'",
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
            # 清理已失效（被撤回 is_active=0）的旧前置，并把刚核销的新 L3 注入下代依赖与交接遗嘱
            try:
                old_reqs = json.loads(blk_node["requires_json"] or "[]")
                if not isinstance(old_reqs, list):
                    old_reqs = []
            except Exception:
                old_reqs = []
            cleaned_reqs: list[str] = []
            for req in old_reqs:
                r_str = str(req or "").strip()
                if not r_str:
                    continue
                if r_str.startswith("L3-"):
                    l3_row = conn.execute(
                        "SELECT is_active FROM internal_research_ledger WHERE entry_id = ? AND ledger_type = 'L3_VERIFIED'",
                        (r_str,),
                    ).fetchone()
                    if l3_row is not None and int(l3_row["is_active"] or 0) == 0:
                        continue
                if r_str not in cleaned_reqs:
                    cleaned_reqs.append(r_str)
            if fulfilled_by_l3_id and fulfilled_by_l3_id not in cleaned_reqs:
                cleaned_reqs.append(fulfilled_by_l3_id)

            gap_stmt = str(gap["formal_statement_md"] or "").strip()[:300]
            prev_will = str(blk_node["will_md"] or "").strip()
            wake_will = (
                f"[悬赏缺口 {gid} 已由 {fulfilled_by_l3_id} 核销唤醒]\n"
                f"核销引理：{fulfilled_by_l3_id}（原缺口：{gap_stmt}）。请直接检索并复用 {fulfilled_by_l3_id} 继续推进。"
                + (f"\n原节点遗嘱：{prev_will}" if prev_will else "")
            )[:1800]

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
                    branch_kind, protection_generations_left, branch_budget_nodes_left, companion_session_id,
                    will_md, reopen_condition, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'EXPLORING', ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    json.dumps(cleaned_reqs, ensure_ascii=False),
                    int(blk_node["revise_count"] or 0),
                    str(blk_node["last_revision_requests_json"] or "[]"),
                    active_spec_rev,
                    str(blk_node["branch_kind"] or "PURE"),
                    max(1, int(blk_node["protection_generations_left"] or 0)),
                    blk_node["branch_budget_nodes_left"] if "branch_budget_nodes_left" in blk_node.keys() else None,
                    f"gw-comp-{next_node_id}",
                    wake_will,
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
