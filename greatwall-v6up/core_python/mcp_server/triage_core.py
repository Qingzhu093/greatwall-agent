"""GreatWall v0.3 共享中观分诊确定性执行内核（供 submit_node_handoff 直落与 logistics_coordinator 共用）。"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .control_plane_service import (
    backup_retained_candidate_snapshot,
    compute_family_concentration_alerts,
    evaluate_subproblem_locks,
    get_subproblem_active_spec_revision,
    restore_retained_candidate_snapshot,
    sync_approved_public_inputs,
    sync_public_instruments_and_skills_to_worktree,
)
from .db_schema import (
    ALLOWED_TRIAGE_ACTIONS,
    ALLOWED_TRIAGE_LEVELS,
    ERR_INVALID_INPUT,
    ERR_INVARIANT,
    ERR_LOCKED,
    ERR_NOT_FOUND,
    FailClosedError,
    rw_immediate_tx,
    utc_now_iso,
)
from .mcp_core_helpers import load_runtime_config, next_prefixed_id

_AUTO_TRIAGE_ALLOWED_LEVELS = frozenset(
    {"ROUTINE_CONTINUATION", "LEVEL_1", "LEVEL_2", "LEVEL_4A", "LEVEL_4B"}
)

_LEVEL_DEFAULT_ACTION = {
    "ROUTINE_CONTINUATION": "CONTINUE",
    "LEVEL_1": "SUBMIT_BLIND_REVIEW",
    "LEVEL_2": "INPLACE_REPAIR",
    "LEVEL_3": "SPAWN_PROTECTED",
    "LEVEL_4A": "SEAL_BARRIER",
    "LEVEL_4B": "PAUSE_TO_READY_QUEUE",
}


def has_verifiable_carrier(conn: sqlite3.Connection, node: sqlite3.Row) -> tuple[bool, str]:
    """按科学主张形态核验可核验载体完整性（数值 Obs / 实体产物 / >=60字自包含推导并行）。"""
    obs_ids = json.loads(node["bound_obs_ids_json"] or "[]")
    if obs_ids:
        ph = ",".join("?" for _ in obs_ids)
        valid_obs = conn.execute(
            f"""
            SELECT obs_id, obs_status FROM observations
            WHERE obs_id IN ({ph}) AND obs_status IN ('VALID_PASS', 'VALID_UNDECIDED', 'MEASURED_REJECTION')
            """,
            tuple(obs_ids),
        ).fetchall()
        if valid_obs:
            return True, f"绑定有效观测收据 {len(valid_obs)} 条"

    cand_rel = str(node["candidate_rel_path"] or "").strip()
    wt_abs = str(node["worktree_abs_path"] or "").strip()
    if cand_rel and wt_abs and (Path(wt_abs) / cand_rel).is_file():
        return True, f"具备实体可核验产物文件 {cand_rel}"

    col_a = str(node["column_a_facts_md"] or "").strip()
    if len(col_a) >= 60:
        return True, f"具备自包含解析推导 A 栏正文 ({len(col_a)} 字)"

    return False, "缺少可核验载体（需至少齐备其一：有效 official/heavy [Obs###]、实体脚本/反例/证明文件、或 >=60 字自包含 A 栏推导）"


def evaluate_auto_triage_eligibility(
    conn: sqlite3.Connection,
    *,
    node: sqlite3.Row,
    recommended_triage: dict[str, Any] | None,
) -> tuple[bool, str, dict[str, Any]]:
    """裁决 2：判定 70% 交班附带的 recommended_triage 是否满足确定性控制面直落条件。"""
    if not isinstance(recommended_triage, dict):
        return False, "未提供 recommended_triage", {}

    qid = str(node["question_id"])
    fid = str(recommended_triage.get("assigned_family_id") or node["family_id"] or "").strip()
    if not fid:
        return False, "节点无已归类 family_id，须由 logistics_coordinator 归类", {}
    fam = conn.execute("SELECT 1 FROM method_families WHERE family_id = ? AND question_id = ?", (fid, qid)).fetchone()
    if fam is None:
        return False, f"学派 {fid!r} 尚未在子题 {qid} 登记，须由 logistics_coordinator 建档", {}

    # 存在 >50% 同族聚拢告警时不直落，交由 logistics_coordinator 正交分流
    conc_alerts = [a for a in compute_family_concentration_alerts(conn) if str(a.get("question_id")) == qid]
    if conc_alerts:
        return False, f"子题 {qid} 触发 >50% 学派聚拢告警，须由 logistics_coordinator 协调正交分流", {}

    lvl = str(recommended_triage.get("triage_level") or "").strip().upper()
    if lvl not in _AUTO_TRIAGE_ALLOWED_LEVELS:
        return False, f"triage_level={lvl!r} 不在确定性直落范围（如 LEVEL_3 反常保护须由 logistics_coordinator 评估）", {}

    act = str(recommended_triage.get("action") or _LEVEL_DEFAULT_ACTION.get(lvl, "")).strip().upper()
    if act not in ALLOWED_TRIAGE_ACTIONS:
        return False, f"非法 action={act!r}", {}

    rationale = str(recommended_triage.get("rationale") or "").strip()
    if not rationale:
        return False, "recommended_triage 缺少 rationale", {}

    cfg = load_runtime_config()
    if lvl == "LEVEL_2":
        max_repairs = int(cfg.get("level2_max_inplace_repairs", 3))
        if int(node["inplace_repair_count"] or 0) >= max_repairs:
            return False, f"原地修补已满 {max_repairs} 次，交由 logistics_coordinator 评估", {}
        has_cand_err = conn.execute(
            "SELECT 1 FROM observations WHERE node_id = ? AND obs_status = 'CANDIDATE_ERROR' LIMIT 1",
            (str(node["node_id"]),),
        ).fetchone()
        if has_cand_err is None:
            return False, "LEVEL_2 直落要求本节点存在确凿 CANDIDATE_ERROR 观测，交由 logistics_coordinator 复核", {}

    if lvl == "LEVEL_1":
        ok_c, note_c = has_verifiable_carrier(conn, node)
        if not ok_c:
            return False, f"LEVEL_1 直落载体未齐备（{note_c}），交由 logistics_coordinator 裁定", {}

    if lvl == "LEVEL_4A":
        bp = str(recommended_triage.get("barrier_proof_md") or "").strip()
        if len(bp) < 15:
            return False, "LEVEL_4A 缺少 >=15 字 barrier_proof_md", {}

    if lvl == "LEVEL_4B":
        if not str(recommended_triage.get("reopen_condition") or "").strip():
            return False, "LEVEL_4B 缺少 reopen_condition", {}

    return (
        True,
        "OK",
        {
            "assigned_family_id": fid,
            "triage_level": lvl,
            "action": act,
            "rationale": rationale,
            "barrier_proof_md": recommended_triage.get("barrier_proof_md"),
            "reopen_condition": recommended_triage.get("reopen_condition"),
            "blocking_gap_formal_statement": recommended_triage.get("blocking_gap_formal_statement"),
        },
    )


def execute_triage_core(
    conn: sqlite3.Connection,
    *,
    workspace_root: str,
    session_id: str,
    node_id: str,
    assigned_family_id: str,
    triage_level: str,
    action: str,
    rationale: str,
    barrier_proof_md: str | None = None,
    reopen_condition: str | None = None,
    blocking_gap_formal_statement: str | None = None,
) -> dict[str, Any]:
    """执行六去向中观分诊的确定性状态落盘、快照托管、悬赏缺口登记与停工锁检查。"""
    node = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
    if str(node["node_status"]) != "AWAITING_TRIAGE":
        raise FailClosedError(ERR_LOCKED, f"节点 {node_id!r} 状态为 {node['node_status']}，仅 AWAITING_TRIAGE 可分诊")

    lvl = str(triage_level or "").strip().upper()
    act = str(action or _LEVEL_DEFAULT_ACTION.get(lvl, "")).strip().upper()
    if lvl not in ALLOWED_TRIAGE_LEVELS:
        raise FailClosedError(ERR_INVALID_INPUT, f"非法 triage_level={triage_level!r}，仅允许 {sorted(ALLOWED_TRIAGE_LEVELS)}")
    if act not in ALLOWED_TRIAGE_ACTIONS:
        raise FailClosedError(ERR_INVALID_INPUT, f"非法 action={action!r}，仅允许 {sorted(ALLOWED_TRIAGE_ACTIONS)}")
    if not str(rationale or "").strip():
        raise FailClosedError(ERR_INVALID_INPUT, "分诊必须提供清晰的 rationale")

    qid = str(node["question_id"])
    bid = str(node["branch_id"])
    fid = str(assigned_family_id or node["family_id"] or "").strip()
    if not fid:
        raise FailClosedError(ERR_INVALID_INPUT, "assigned_family_id 不能为空")
    fam = conn.execute("SELECT 1 FROM method_families WHERE family_id = ? AND question_id = ?", (fid, qid)).fetchone()
    if fam is None:
        raise FailClosedError(ERR_NOT_FOUND, f"方法学派 {fid!r} 尚未在子题 {qid} 登记，请先调 register_method_family")

    cfg = load_runtime_config()
    max_repairs = int(cfg.get("level2_max_inplace_repairs", 3))
    now = utc_now_iso()
    node_spec_rev = int(node["spec_revision"] or 0)
    active_q_spec_rev = get_subproblem_active_spec_revision(conn, qid)
    p0_rev = conn.execute("SELECT shared_inputs_json FROM parse0_contract WHERE contract_id = 'active'").fetchone()
    shared_rels = json.loads(p0_rev["shared_inputs_json"] or "[]") if p0_rev else []
    cur_prot_left = max(0, int(node["protection_generations_left"] or 0))
    next_prot_left = max(0, cur_prot_left - 1)
    branch_kind = str(node["branch_kind"] or "PURE")
    raw_budget = node["branch_budget_nodes_left"] if "branch_budget_nodes_left" in node.keys() else None
    has_node_budget = raw_budget is not None
    next_budget_left = max(0, int(raw_budget) - 1) if has_node_budget else None

    # 前置依赖 L3 已被撤回时，自然交接自动转 LEVEL_4B 暂停
    if int(node["premise_revoked"] or 0) == 1 and lvl not in ("LEVEL_4A", "LEVEL_4B"):
        lvl = "LEVEL_4B"
        act = "PAUSE_TO_READY_QUEUE"
        reopen_condition = reopen_condition or "前置依赖 L3 已被撤回重审，待上游 L3 恢复或切换新前提后重启"

    if lvl == "LEVEL_1" or act == "SUBMIT_BLIND_REVIEW":
        ok_carrier, carrier_note = has_verifiable_carrier(conn, node)
        if not ok_carrier:
            raise FailClosedError(ERR_INVARIANT, f"LEVEL_1 送审准入拦截：{carrier_note}")
        snap_path = backup_retained_candidate_snapshot(
            workspace_root=workspace_root,
            branch_id=bid,
            worktree_abs_path=str(node["worktree_abs_path"]),
            candidate_rel_path=node["candidate_rel_path"],
        )
        rev_id = next_prefixed_id(conn, "review_queue", "review_id", "rev_")
        with rw_immediate_tx(conn):
            conn.execute(
                """
                UPDATE lineage_nodes
                SET family_id = ?, node_status = 'PENDING_REVIEW', retained_snapshot_abs_path = ?, updated_at = ?
                WHERE node_id = ?
                """,
                (fid, snap_path, now, node_id),
            )
            conn.execute(
                """
                INSERT INTO review_queue(
                    review_id, question_id, source_node_id, source_type, proposer_session_id,
                    review_status, manuscript_title, spec_revision, column_a_snapshot_md, column_b_snapshot_md,
                    bound_obs_ids_json, artifact_rel_path, sanitized_code_diff_md, created_at, updated_at
                ) VALUES (?, ?, ?, 'LEVEL1_MANUSCRIPT', ?, 'STAGE1_BLIND', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rev_id,
                    qid,
                    node_id,
                    session_id or f"triage_{node_id}",
                    str(node["mechanism_summary"] or f"{qid} Candidate Manuscript"),
                    node_spec_rev,
                    str(node["column_a_facts_md"] or ""),
                    str(node["column_b_hypothesis_md"] or ""),
                    str(node["bound_obs_ids_json"] or "[]"),
                    node["candidate_rel_path"],
                    str(node["sanitized_code_diff_md"] or ""),
                    now,
                    now,
                ),
            )
            conn.execute("UPDATE parse0_contract SET consecutive_non_l1_handoffs = 0, updated_at = ? WHERE contract_id = 'active'", (now,))
        return {
            "question_id": qid,
            "node_id": node_id,
            "guidance": f"已备份物理快照并冻结分支为 PENDING_REVIEW，生成盲审单 {rev_id}（{carrier_note}）。",
            "data": {
                "node_id": node_id,
                "triage_level": "LEVEL_1",
                "created_review_id": rev_id,
                "spec_revision": node_spec_rev,
                "retained_snapshot_abs_path": snap_path,
            },
        }

    if lvl == "LEVEL_4A" or act == "SEAL_BARRIER":
        bp = str(barrier_proof_md or "").strip()
        if len(bp) < 15:
            raise FailClosedError(ERR_INVALID_INPUT, "LEVEL_4A 严密证伪/结构阻碍证明必须提供 >= 15 字的 barrier_proof_md")
        snap_path = backup_retained_candidate_snapshot(
            workspace_root=workspace_root,
            branch_id=bid,
            worktree_abs_path=str(node["worktree_abs_path"]),
            candidate_rel_path=node["candidate_rel_path"],
        )
        rev_id = next_prefixed_id(conn, "review_queue", "review_id", "rev_")
        col_a_combined = (str(node["column_a_facts_md"] or "") + "\n\n### 结构阻碍 / 反例证明\n" + bp).strip()
        with rw_immediate_tx(conn):
            conn.execute(
                """
                UPDATE lineage_nodes
                SET family_id = ?, node_status = 'PENDING_REVIEW', retained_snapshot_abs_path = ?, updated_at = ?
                WHERE node_id = ?
                """,
                (fid, snap_path, now, node_id),
            )
            conn.execute(
                """
                INSERT INTO review_queue(
                    review_id, question_id, source_node_id, source_type, proposer_session_id,
                    review_status, manuscript_title, spec_revision, column_a_snapshot_md, column_b_snapshot_md,
                    bound_obs_ids_json, artifact_rel_path, sanitized_code_diff_md, created_at, updated_at
                ) VALUES (?, ?, ?, 'LEVEL4A_BARRIER', ?, 'STAGE1_BLIND', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rev_id,
                    qid,
                    node_id,
                    session_id or f"triage_{node_id}",
                    f"[Barrier/Counterexample] {node['mechanism_summary'] or qid}",
                    node_spec_rev,
                    col_a_combined,
                    str(node["column_b_hypothesis_md"] or ""),
                    str(node["bound_obs_ids_json"] or "[]"),
                    node["candidate_rel_path"],
                    str(node["sanitized_code_diff_md"] or ""),
                    now,
                    now,
                ),
            )
            conn.execute("UPDATE parse0_contract SET consecutive_non_l1_handoffs = consecutive_non_l1_handoffs + 1, updated_at = ? WHERE contract_id = 'active'", (now,))
        return {
            "question_id": qid,
            "node_id": node_id,
            "guidance": f"LEVEL_4A 阻碍/反例证明已冻结为 PENDING_REVIEW 并送盲审 {rev_id}。",
            "data": {"node_id": node_id, "triage_level": "LEVEL_4A", "created_review_id": rev_id, "node_status": "PENDING_REVIEW"},
        }

    if lvl == "LEVEL_4B" or act == "PAUSE_TO_READY_QUEUE":
        rc = str(reopen_condition or "").strip()
        if not rc:
            raise FailClosedError(ERR_INVALID_INPUT, "LEVEL_4B 条件阻塞必须填写 reopen_condition 以供 Ready Queue 唤醒")
        gap_stmt = str(blocking_gap_formal_statement or rc).strip()
        gap_id = next_prefixed_id(conn, "open_lemma_gaps", "gap_id", "gap_")
        with rw_immediate_tx(conn):
            conn.execute(
                "UPDATE lineage_nodes SET family_id = ?, node_status = 'BLOCKED_L4B', reopen_condition = ?, updated_at = ? WHERE node_id = ?",
                (fid, rc, now, node_id),
            )
            conn.execute(
                """
                INSERT INTO open_lemma_gaps(
                    gap_id, question_id, blocked_node_id,
                    formal_statement_md, verification_spec_md, status, created_at
                ) VALUES (?, ?, ?, ?, '', 'OPEN', ?)
                """,
                (gap_id, qid, node_id, gap_stmt, now),
            )
            conn.execute("UPDATE parse0_contract SET consecutive_non_l1_handoffs = consecutive_non_l1_handoffs + 1, updated_at = ? WHERE contract_id = 'active'", (now,))
        evaluate_subproblem_locks(conn, question_id=qid)
        return {
            "question_id": qid,
            "node_id": node_id,
            "guidance": f"分支 {bid} 已挂入 Ready Queue (BLOCKED_L4B) 并向全馆公开发布悬赏缺口 {gap_id}。",
            "data": {"node_id": node_id, "triage_level": "LEVEL_4B", "node_status": "BLOCKED_L4B", "reopen_condition": rc, "created_gap_id": gap_id},
        }

    if lvl == "LEVEL_2" or act == "INPLACE_REPAIR":
        cur_repairs = int(node["inplace_repair_count"] or 0)
        orig_fid = str(node["family_id"] or "").strip()
        eff_repair_fid = fid
        if orig_fid and orig_fid != fid:
            rem_in_orig = conn.execute(
                """
                SELECT COUNT(DISTINCT branch_id) AS cnt FROM lineage_nodes
                WHERE question_id = ? AND family_id = ? AND branch_id != ?
                  AND node_status IN ('EXPLORING', 'ACTIVE_REVISING', 'AWAITING_TRIAGE', 'PENDING_REVIEW')
                """,
                (qid, orig_fid, bid),
            ).fetchone()
            if int(rem_in_orig["cnt"] or 0) == 0:
                eff_repair_fid = orig_fid

        if has_node_budget and int(next_budget_left or 0) <= 0:
            with rw_immediate_tx(conn):
                conn.execute(
                    "UPDATE lineage_nodes SET family_id = ?, node_status = 'SEALED', branch_budget_nodes_left = 0, updated_at = ? WHERE node_id = ?",
                    (eff_repair_fid, now, node_id),
                )
            return {
                "question_id": qid,
                "node_id": node_id,
                "guidance": f"分支 {bid} ({branch_kind}) 班次预算配额已耗尽，停止原地续班并已封存 {node_id}。",
                "data": {"closed_node_id": node_id, "next_node_id": None, "budget_exhausted": True, "node_status": "SEALED"},
            }

        if node["retained_snapshot_abs_path"]:
            restore_retained_candidate_snapshot(str(node["retained_snapshot_abs_path"]), str(node["worktree_abs_path"]))
        sync_approved_public_inputs(
            workspace_root,
            str(node["worktree_abs_path"]),
            shared_rels,
            spec_revision=active_q_spec_rev,
            question_id=qid,
        )
        sync_public_instruments_and_skills_to_worktree(conn, workspace_root, str(node["worktree_abs_path"]))

        next_node_id = f"node_{qid.lower()}_{uuid.uuid4().hex[:8]}"
        exhausted = cur_repairs >= max_repairs
        with rw_immediate_tx(conn):
            conn.execute(
                "UPDATE lineage_nodes SET family_id = ?, node_status = 'CLOSED', updated_at = ? WHERE node_id = ?",
                (eff_repair_fid, now, node_id),
            )
            if exhausted:
                de_id = f"de_{uuid.uuid4().hex[:10]}"
                conn.execute(
                    """
                    INSERT INTO lineage_dead_ends(dead_end_id, question_id, branch_id, node_id, category, scope_condition_md, failure_mechanism_md, bound_obs_id, created_at)
                    VALUES (?, ?, ?, ?, 'IMPL_FAILURE', ?, ?, NULL, ?)
                    """,
                    (de_id, qid, bid, node_id, f"LEVEL_2 原地修补满 {max_repairs} 次失败", str(rationale).strip(), now),
                )
            conn.execute(
                """
                INSERT INTO lineage_nodes(
                    node_id, question_id, branch_id, family_id, parent_node_id, generation, node_status,
                    worktree_abs_path, retained_snapshot_abs_path, requires_json, revise_count,
                    inplace_repair_count, last_revision_requests_json, spec_revision,
                    branch_kind, protection_generations_left, branch_budget_nodes_left, companion_session_id,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'EXPLORING', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    next_node_id,
                    qid,
                    bid,
                    eff_repair_fid,
                    node_id,
                    int(node["generation"]) + 1,
                    str(node["worktree_abs_path"]),
                    node["retained_snapshot_abs_path"],
                    str(node["requires_json"] or "[]"),
                    int(node["revise_count"] or 0),
                    0 if exhausted else cur_repairs + 1,
                    str(node["last_revision_requests_json"] or "[]"),
                    active_q_spec_rev,
                    branch_kind,
                    next_prot_left,
                    next_budget_left,
                    f"gw-comp-{next_node_id}",
                    now,
                    now,
                ),
            )
            conn.execute("UPDATE parse0_contract SET consecutive_non_l1_handoffs = consecutive_non_l1_handoffs + 1, updated_at = ? WHERE contract_id = 'active'", (now,))
        return {
            "question_id": qid,
            "node_id": next_node_id,
            "guidance": (
                f"原地修补满 {max_repairs} 次已写入本脉 lineage_dead_ends(IMPL_FAILURE)（未污染图书馆 L2）并回退重启 {next_node_id}。"
                if exhausted
                else f"已启动第 {cur_repairs + 1}/{max_repairs} 次 LEVEL_2 原地修补节点 {next_node_id}。"
            ),
            "data": {"closed_node_id": node_id, "next_node_id": next_node_id, "assigned_family_id": eff_repair_fid, "repair_exhausted": exhausted},
        }

    if lvl == "LEVEL_3" or act == "SPAWN_PROTECTED":
        prot_bid = f"b_{qid.lower()}_prot_{uuid.uuid4().hex[:6]}"
        prot_wt = Path(os.path.realpath(workspace_root)) / "worktrees" / prot_bid
        prot_wt.mkdir(parents=True, exist_ok=True)
        snap_path = backup_retained_candidate_snapshot(
            workspace_root=workspace_root,
            branch_id=bid,
            worktree_abs_path=str(node["worktree_abs_path"]),
            candidate_rel_path=node["candidate_rel_path"],
        )
        restore_retained_candidate_snapshot(snap_path, str(prot_wt))
        sync_approved_public_inputs(workspace_root, prot_wt, shared_rels, spec_revision=active_q_spec_rev, question_id=qid)
        sync_public_instruments_and_skills_to_worktree(conn, workspace_root, prot_wt)
        prot_nid = f"node_{qid.lower()}_{uuid.uuid4().hex[:8]}"
        default_prot = int(cfg.get("default_protection_generations", 2))
        with rw_immediate_tx(conn):
            conn.execute(
                "UPDATE lineage_nodes SET family_id = ?, node_status = 'CLOSED', retained_snapshot_abs_path = ?, updated_at = ? WHERE node_id = ?",
                (fid, snap_path, now, node_id),
            )
            conn.execute(
                """
                INSERT INTO lineage_nodes(
                    node_id, question_id, branch_id, family_id, parent_node_id, generation, node_status,
                    worktree_abs_path, retained_snapshot_abs_path, requires_json, spec_revision,
                    branch_kind, protection_generations_left, companion_session_id,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, 'EXPLORING', ?, ?, ?, ?, 'PURE', ?, ?, ?, ?)
                """,
                (
                    prot_nid,
                    qid,
                    prot_bid,
                    fid,
                    node_id,
                    str(prot_wt),
                    snap_path,
                    str(node["requires_json"] or "[]"),
                    active_q_spec_rev,
                    default_prot,
                    f"gw-comp-{prot_nid}",
                    now,
                    now,
                ),
            )
        return {
            "question_id": qid,
            "node_id": prot_nid,
            "guidance": f"已为反常/特异突破单开受保护支线 {prot_bid} ({prot_nid}，保护期 {default_prot} 代)。",
            "data": {"closed_node_id": node_id, "protected_branch_id": prot_bid, "next_node_id": prot_nid},
        }

    # ROUTINE_CONTINUATION / CONTINUE
    snap_path = backup_retained_candidate_snapshot(
        workspace_root=workspace_root,
        branch_id=bid,
        worktree_abs_path=str(node["worktree_abs_path"]),
        candidate_rel_path=node["candidate_rel_path"],
    )
    if has_node_budget and int(next_budget_left or 0) <= 0:
        with rw_immediate_tx(conn):
            conn.execute(
                "UPDATE lineage_nodes SET family_id = ?, node_status = 'SEALED', retained_snapshot_abs_path = ?, branch_budget_nodes_left = 0, updated_at = ? WHERE node_id = ?",
                (fid, snap_path, now, node_id),
            )
            conn.execute("UPDATE parse0_contract SET consecutive_non_l1_handoffs = consecutive_non_l1_handoffs + 1, updated_at = ? WHERE contract_id = 'active'", (now,))
        return {
            "question_id": qid,
            "node_id": node_id,
            "guidance": f"分支 {bid} ({branch_kind}) 班次预算配额已耗尽，已刷新快照并封存收口 {node_id}（如需保留请经下一轮圆桌显式立项）。",
            "data": {"closed_node_id": node_id, "next_node_id": None, "budget_exhausted": True, "retained_snapshot_abs_path": snap_path},
        }

    sync_approved_public_inputs(
        workspace_root,
        str(node["worktree_abs_path"]),
        shared_rels,
        spec_revision=active_q_spec_rev,
        question_id=qid,
    )
    sync_public_instruments_and_skills_to_worktree(conn, workspace_root, str(node["worktree_abs_path"]))
    next_node_id = f"node_{qid.lower()}_{uuid.uuid4().hex[:8]}"
    with rw_immediate_tx(conn):
        conn.execute(
            "UPDATE lineage_nodes SET family_id = ?, node_status = 'CLOSED', retained_snapshot_abs_path = ?, updated_at = ? WHERE node_id = ?",
            (fid, snap_path, now, node_id),
        )
        conn.execute(
            """
            INSERT INTO lineage_nodes(
                node_id, question_id, branch_id, family_id, parent_node_id, generation, node_status,
                worktree_abs_path, retained_snapshot_abs_path, requires_json, revise_count,
                inplace_repair_count, last_revision_requests_json, spec_revision,
                branch_kind, protection_generations_left, branch_budget_nodes_left, companion_session_id,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'EXPLORING', ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                next_node_id,
                qid,
                bid,
                fid,
                node_id,
                int(node["generation"]) + 1,
                str(node["worktree_abs_path"]),
                snap_path,
                str(node["requires_json"] or "[]"),
                int(node["revise_count"] or 0),
                str(node["last_revision_requests_json"] or "[]"),
                active_q_spec_rev,
                branch_kind,
                next_prot_left,
                next_budget_left,
                f"gw-comp-{next_node_id}",
                now,
                now,
            ),
        )
        conn.execute("UPDATE parse0_contract SET consecutive_non_l1_handoffs = consecutive_non_l1_handoffs + 1, updated_at = ? WHERE contract_id = 'active'", (now,))

    return {
        "question_id": qid,
        "node_id": next_node_id,
        "guidance": f"已刷新物理快照并创建下一代节点 {next_node_id}（等待伴随重写行前看板）。",
        "data": {"closed_node_id": node_id, "next_node_id": next_node_id, "retained_snapshot_abs_path": snap_path},
    }
