"""控制面子域 4：纯规则并发调度快照、分支前置校验、学派聚拢告警、拓扑健康与终局门禁。

后续阶段引入“子题达标收敛止盈与动态算力配额”等全局调度规则时，应优先演进本模块。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from ..db_schema import (
    ALLOWED_DELIVERY_MODES,
    ERR_INVALID_INPUT,
    FailClosedError,
)
from ..mcp_core_helpers import (
    load_runtime_config,
    resolve_effective_context_window,
)
from .lifecycle_ops import (
    _parse_iso_utc,
    compute_missing_initial_instruments,
)


def check_branch_requires_satisfied(conn: sqlite3.Connection, requires_list: list[str]) -> tuple[bool, list[str]]:
    """分支级确定性前置检查（仅支持 `L3-###` 与 `OBS:<instrument_id>:PASS`；只锁单分支，绝不跨分支并集）。"""
    unmet: list[str] = []
    for raw_req in requires_list or []:
        req = str(raw_req or "").strip()
        if not req:
            continue
        if req.startswith("L3-"):
            row = conn.execute(
                "SELECT 1 FROM internal_research_ledger WHERE entry_id = ? AND ledger_type = 'L3_VERIFIED' AND is_active = 1",
                (req,),
            ).fetchone()
            if row is None:
                unmet.append(req)
        elif req.startswith("OBS:") and req.endswith(":PASS"):
            inst_id = req[len("OBS:"):-len(":PASS")].strip()
            active_inst = conn.execute(
                "SELECT version FROM instruments WHERE instrument_id = ? AND is_active = 1 ORDER BY version DESC LIMIT 1",
                (inst_id,),
            ).fetchone()
            if active_inst is not None:
                row = conn.execute(
                    "SELECT 1 FROM observations WHERE instrument_id = ? AND instrument_version = ? AND obs_status = 'VALID_PASS' LIMIT 1",
                    (inst_id, int(active_inst["version"])),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT 1 FROM observations WHERE instrument_id = ? AND obs_status = 'VALID_PASS' LIMIT 1",
                    (inst_id,),
                ).fetchone()
            if row is None:
                unmet.append(req)
        else:
            unmet.append(req)
    return len(unmet) == 0, unmet


def get_question_order_status(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """计算可选全局策略题序 `question_order` 解锁态（默认空 = 全子题并发推进）。"""
    p0 = conn.execute("SELECT subquestions_json, question_order_json FROM parse0_contract WHERE contract_id = 'active'").fetchone()
    req_qs = json.loads(p0["subquestions_json"]) if p0 else ["Q1"]
    q_order = json.loads(p0["question_order_json"]) if p0 else []

    full_l3_counts = {
        str(r["question_id"]): int(r["cnt"] or 0)
        for r in conn.execute(
            """
            SELECT question_id, COUNT(*) AS cnt
            FROM internal_research_ledger
            WHERE ledger_type = 'L3_VERIFIED' AND is_active = 1 AND goal_coverage = 'FULL_GOAL'
            GROUP BY question_id
            """
        ).fetchall()
    }
    any_l3_counts = {
        str(r["question_id"]): int(r["cnt"] or 0)
        for r in conn.execute(
            """
            SELECT question_id, COUNT(*) AS cnt
            FROM internal_research_ledger
            WHERE ledger_type = 'L3_VERIFIED' AND is_active = 1
            GROUP BY question_id
            """
        ).fetchall()
    }

    status_map: dict[str, dict[str, Any]] = {}
    for q in req_qs:
        unmet_prev: list[str] = []
        if q in q_order:
            idx = q_order.index(q)
            for prev_q in q_order[:idx]:
                if full_l3_counts.get(prev_q, 0) < 1:
                    unmet_prev.append(prev_q)
        status_map[q] = {
            "unmet_order_questions": unmet_prev,
            "unlocked": len(unmet_prev) == 0,
            "full_goal_l3_count": full_l3_counts.get(q, 0),
            "total_l3_count": any_l3_counts.get(q, 0),
        }
    return status_map


def compute_family_concentration_alerts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """无豁免刚性聚拢检测：`branch_count_in_family >= 2 && share > 0.50` 立即告警（严禁高产豁免）。"""
    cfg = load_runtime_config()
    min_branches = int(cfg.get("family_concentration_min_branches_in_family", 2))
    share_threshold = float(cfg.get("family_concentration_share_threshold", 0.50))

    # 统计每个子题每个活跃分支（取每分支最新状态处于 EXPLORING/ACTIVE_REVISING/AWAITING_TRIAGE/PENDING_REVIEW 的活跃脉）
    rows = conn.execute(
        """
        SELECT question_id, branch_id, family_id
        FROM lineage_nodes
        WHERE node_status IN ('EXPLORING', 'ACTIVE_REVISING', 'AWAITING_TRIAGE', 'PENDING_REVIEW')
        GROUP BY question_id, branch_id
        """
    ).fetchall()

    by_q: dict[str, dict[str, set[str]]] = {}
    for r in rows:
        q = str(r["question_id"])
        b = str(r["branch_id"])
        fam = str(r["family_id"] or "unclassified")
        by_q.setdefault(q, {}).setdefault(fam, set()).add(b)

    alerts: list[dict[str, Any]] = []
    for q, fam_map in sorted(by_q.items()):
        total_active = sum(len(bs) for bs in fam_map.values())
        if total_active < min_branches:
            continue
        for fam, bs in sorted(fam_map.items()):
            cnt = len(bs)
            share = cnt / float(total_active)
            if cnt >= min_branches and share > share_threshold:
                alerts.append(
                    {
                        "question_id": q,
                        "family_id": fam,
                        "branch_count_in_family": cnt,
                        "total_active_branches": total_active,
                        "share": round(share, 4),
                        "branches": sorted(bs),
                    }
                )
    return alerts


def compute_topology_and_revision_health(
    conn: sqlite3.Connection,
    *,
    question_filter: str = "ALL",
    slot_cap: int | None = None,
) -> dict[str, Any]:
    """纯查 SQLite (<15ms) 计算全卷或指定子题的 Worktree 拓扑健康度、断代分支、孤儿盲审返工单与缺编正交学派。

    消除第六轮暴露的四大治理盲区：
    1. 断代分支（`stalled_or_aborted_branches`）：最新节点为 `CLOSED`（含被 `abort_node` 中止）且所在子题尚未取得 `FULL_GOAL L3`；
    2. 孤儿盲审返工单（`orphaned_blind_review_revisions`）：盲审判了 `REVISE`（`CLOSED_REVISE`）要求定向返工，但原分支被中止或断代、当前无活跃节点承接；
    3. 缺编正交学派与单线独苗退化（`understaffed_questions`）：子题已注册 >=2 个 `ACTIVE` 学派且有空闲槽位，但在跑活跃学派数 < min(2, 已登记活跃学派数)；
    4. 并发槽位利用率（`slot_utilization`）：`active_branches_count` / `slot_cap` / `free_slots`。
    """
    cfg = load_runtime_config()
    eff_slot_cap = int(slot_cap or cfg.get("max_concurrent_workers", 6))
    qf = str(question_filter or "ALL").strip()
    order_status = get_question_order_status(conn)

    # 1. 已注册方法学派
    if qf.upper() == "ALL":
        fam_rows = conn.execute("SELECT * FROM method_families ORDER BY question_id, family_id").fetchall()
    else:
        fam_rows = conn.execute(
            "SELECT * FROM method_families WHERE question_id = ? ORDER BY family_id",
            (qf,),
        ).fetchall()

    active_families_by_q: dict[str, list[str]] = {}
    for fr in fam_rows:
        if str(fr["family_status"] or "ACTIVE") == "ACTIVE":
            active_families_by_q.setdefault(str(fr["question_id"]), []).append(str(fr["family_id"]))

    # 2. 按 branch_id 聚合每条分支的最新一代节点状态
    if qf.upper() == "ALL":
        all_nodes = conn.execute(
            """
            SELECT node_id, question_id, branch_id, family_id, parent_node_id, generation,
                   spec_revision, node_status, worktree_abs_path, retained_snapshot_abs_path,
                   mechanism_summary, evidence_grade, candidate_rel_path, revise_count,
                   inplace_repair_count, last_revision_requests_json, pending_handoff_reason,
                   pressure_tokens, effective_context_window, first_reflection_unlocked,
                   created_at, updated_at
            FROM lineage_nodes
            ORDER BY generation ASC, created_at ASC
            """
        ).fetchall()
    else:
        all_nodes = conn.execute(
            """
            SELECT node_id, question_id, branch_id, family_id, parent_node_id, generation,
                   spec_revision, node_status, worktree_abs_path, retained_snapshot_abs_path,
                   mechanism_summary, evidence_grade, candidate_rel_path, revise_count,
                   inplace_repair_count, last_revision_requests_json, pending_handoff_reason,
                   pressure_tokens, effective_context_window, first_reflection_unlocked,
                   created_at, updated_at
            FROM lineage_nodes
            WHERE question_id = ?
            ORDER BY generation ASC, created_at ASC
            """,
            (qf,),
        ).fetchall()

    latest_by_branch: dict[str, dict[str, Any]] = {}
    branch_has_live_node: set[str] = set()
    live_statuses = ("EXPLORING", "ACTIVE_REVISING", "AWAITING_TRIAGE", "PENDING_REVIEW")
    for r in all_nodes:
        d = dict(r)
        bid = str(d["branch_id"])
        latest_by_branch[bid] = d
        if str(d["node_status"]) in live_statuses:
            branch_has_live_node.add(bid)

    # 统计总活跃探索分支槽位（全卷口径）
    total_live_branches = int(
        conn.execute(
            """
            SELECT COUNT(DISTINCT branch_id) AS cnt
            FROM lineage_nodes
            WHERE node_status IN ('EXPLORING', 'ACTIVE_REVISING', 'AWAITING_TRIAGE', 'PENDING_REVIEW')
            """
        ).fetchone()["cnt"]
        or 0
    )
    free_slots = max(0, eff_slot_cap - total_live_branches)

    # 3. 检索所有 CLOSED_REVISE 盲审单，判断是否已被后续活跃分支承接
    if qf.upper() == "ALL":
        rev_rows = conn.execute(
            """
            SELECT r.review_id, r.question_id, r.source_node_id, r.manuscript_title,
                   r.final_verdict, r.revision_requests_json, r.updated_at,
                   n.branch_id, n.family_id, n.retained_snapshot_abs_path, n.worktree_abs_path
            FROM review_queue r
            LEFT JOIN lineage_nodes n ON n.node_id = r.source_node_id
            WHERE r.review_status = 'CLOSED_REVISE'
            ORDER BY r.updated_at DESC
            """
        ).fetchall()
    else:
        rev_rows = conn.execute(
            """
            SELECT r.review_id, r.question_id, r.source_node_id, r.manuscript_title,
                   r.final_verdict, r.revision_requests_json, r.updated_at,
                   n.branch_id, n.family_id, n.retained_snapshot_abs_path, n.worktree_abs_path
            FROM review_queue r
            LEFT JOIN lineage_nodes n ON n.node_id = r.source_node_id
            WHERE r.review_status = 'CLOSED_REVISE' AND r.question_id = ?
            ORDER BY r.updated_at DESC
            """,
            (qf,),
        ).fetchall()

    # 判断某个 source_node_id 是否已有后代节点送过新盲审或正处于活跃态
    active_parent_ids = {
        str(r["parent_node_id"])
        for r in all_nodes
        if r["parent_node_id"] and str(r["node_status"]) in live_statuses
    }
    reviewed_source_nodes = {
        str(r["source_node_id"])
        for r in conn.execute("SELECT source_node_id FROM review_queue").fetchall()
    }

    orphaned_revisions: list[dict[str, Any]] = []
    orphaned_by_branch: dict[str, dict[str, Any]] = {}
    for rr in rev_rows:
        rqid = str(rr["question_id"])
        if order_status.get(rqid, {}).get("full_goal_l3_count", 0) > 0:
            continue
        rbid = str(rr["branch_id"] or "")
        src_nid = str(rr["source_node_id"])
        if rbid in branch_has_live_node or src_nid in active_parent_ids:
            continue
        # 检查是否有后代节点已经重新送审
        descendant_resubmitted = any(
            str(n["parent_node_id"] or "") == src_nid and str(n["node_id"]) in reviewed_source_nodes
            for n in all_nodes
        )
        if descendant_resubmitted:
            continue
        try:
            reqs_list = json.loads(rr["revision_requests_json"] or "[]")
        except Exception:
            reqs_list = []
        item = {
            "review_id": str(rr["review_id"]),
            "question_id": rqid,
            "source_node_id": src_nid,
            "branch_id": rbid,
            "family_id": str(rr["family_id"] or ""),
            "manuscript_title": str(rr["manuscript_title"] or ""),
            "revision_requests": reqs_list,
            "retained_snapshot_abs_path": rr["retained_snapshot_abs_path"],
            "worktree_abs_path": rr["worktree_abs_path"],
            "respawn_guidance": (
                f"调用 fork_branch(question_id={rqid!r}, parent_node_id={src_nid!r}, "
                f"fork_mode='lateral', target_family_id={str(rr['family_id'] or '')!r}) "
                f"即可继承其快照与 {rr['review_id']} 返工单继续冲刺二审"
            ),
        }
        orphaned_revisions.append(item)
        if rbid:
            orphaned_by_branch[rbid] = item

    # 4. 整理断代/被中止分支列表
    stalled_branches: list[dict[str, Any]] = []
    live_families_by_q: dict[str, set[str]] = {}
    live_branches_by_q: dict[str, list[str]] = {}

    for bid, latest in sorted(latest_by_branch.items()):
        qid = str(latest["question_id"])
        fid = str(latest["family_id"] or "")
        st = str(latest["node_status"])
        if st in live_statuses:
            if fid:
                live_families_by_q.setdefault(qid, set()).add(fid)
            live_branches_by_q.setdefault(qid, []).append(bid)
            continue
        if st == "CLOSED" and order_status.get(qid, {}).get("full_goal_l3_count", 0) == 0:
            try:
                rev_reqs = json.loads(latest.get("last_revision_requests_json") or "[]")
            except Exception:
                rev_reqs = []
            orphan_rev = orphaned_by_branch.get(bid)
            if orphan_rev and not rev_reqs:
                rev_reqs = orphan_rev.get("revision_requests") or []
            stalled_branches.append(
                {
                    "branch_id": bid,
                    "question_id": qid,
                    "family_id": fid,
                    "last_node_id": str(latest["node_id"]),
                    "last_generation": int(latest["generation"] or 1),
                    "last_node_status": st,
                    "close_reason": str(latest.get("pending_handoff_reason") or "CLOSED_OR_ABORTED"),
                    "retained_snapshot_abs_path": latest.get("retained_snapshot_abs_path"),
                    "worktree_abs_path": latest.get("worktree_abs_path"),
                    "pending_blind_review_id": orphan_rev["review_id"] if orphan_rev else None,
                    "pending_revision_requests": rev_reqs,
                }
            )

    # 5. 检查各解锁子题是否存在“正交学派缺编 / 单线独苗退化”
    understaffed_questions: list[dict[str, Any]] = []
    check_qs = sorted(active_families_by_q.keys()) if qf.upper() == "ALL" else [qf]
    for q in check_qs:
        q_info = order_status.get(q, {})
        if not q_info.get("unlocked", True) or q_info.get("full_goal_l3_count", 0) > 0:
            continue
        reg_fams = active_families_by_q.get(q, [])
        live_fams = sorted(live_families_by_q.get(q, set()))
        missing_fams = [f for f in reg_fams if f not in live_fams]
        live_b_list = live_branches_by_q.get(q, [])
        # 当注册了 >=2 个活跃学派，但当前在跑分支数退化为 <=1（独苗或全空），且有空闲槽位时告警
        is_degenerated = len(reg_fams) >= 2 and len(live_b_list) < min(2, len(reg_fams)) and free_slots > 0
        if missing_fams and (is_degenerated or len(live_b_list) == 0):
            understaffed_questions.append(
                {
                    "question_id": q,
                    "registered_active_families": reg_fams,
                    "active_families_in_flight": live_fams,
                    "missing_active_family_ids": missing_fams,
                    "active_branch_count": len(live_b_list),
                    "free_explorer_slots": free_slots,
                    "single_branch_monopoly": len(live_b_list) == 1 and len(reg_fams) >= 2,
                }
            )

    return {
        "slot_utilization": {
            "active_branches_count": total_live_branches,
            "slot_cap": eff_slot_cap,
            "free_slots": free_slots,
        },
        "stalled_or_aborted_branches": stalled_branches,
        "orphaned_blind_review_revisions": orphaned_revisions,
        "understaffed_questions": understaffed_questions,
    }


def check_stage2_closure_gate_data(
    conn: sqlite3.Connection,
    *,
    mode: str = "FULL",
    human_aborted: bool = False,
) -> dict[str, Any]:
    """CDC 双段式终局门禁核验（严格验证 `FULL_GOAL`、`min_commitment_window` 与控制面真源 `human_stop_requested_at`）。"""
    eff_mode = str(mode or "FULL").strip().upper()
    if eff_mode not in ALLOWED_DELIVERY_MODES:
        raise FailClosedError(ERR_INVALID_INPUT, f"非法结题模式 mode={mode!r}，仅允许 {sorted(ALLOWED_DELIVERY_MODES)}")

    p0 = conn.execute("SELECT * FROM parse0_contract WHERE contract_id = 'active'").fetchone()
    req_qs = json.loads(p0["subquestions_json"]) if p0 else []
    min_window_sec = int(p0["min_commitment_window_sec"] or 0) if p0 else 0
    signed_dt = _parse_iso_utc(str(p0["human_signed_at"])) if p0 else None
    elapsed_sec = 0.0
    if signed_dt is not None:
        elapsed_sec = max(0.0, (datetime.now(timezone.utc) - signed_dt).total_seconds())

    closure = conn.execute("SELECT * FROM project_closure_state WHERE id = 1").fetchone()
    human_stop_ts = str(closure["human_stop_requested_at"] or "").strip() if closure else ""

    full_rows = conn.execute(
        """
        SELECT question_id, COUNT(*) AS cnt
        FROM internal_research_ledger
        WHERE ledger_type = 'L3_VERIFIED' AND is_active = 1 AND goal_coverage = 'FULL_GOAL'
        GROUP BY question_id
        """
    ).fetchall()
    full_counts = {str(r["question_id"]): int(r["cnt"] or 0) for r in full_rows}

    all_l3_rows = conn.execute(
        """
        SELECT question_id, COUNT(*) AS cnt
        FROM internal_research_ledger
        WHERE ledger_type = 'L3_VERIFIED' AND is_active = 1
        GROUP BY question_id
        """
    ).fetchall()
    all_l3_counts = {str(r["question_id"]): int(r["cnt"] or 0) for r in all_l3_rows}

    blocking_qs = [q for q in req_qs if full_counts.get(q, 0) < 1]
    pending_reval = conn.execute(
        "SELECT queue_id, obs_id, question_id FROM pending_revalidation_queue WHERE status = 'PENDING'"
    ).fetchall()
    pending_reviews = conn.execute(
        "SELECT review_id, question_id, review_status FROM review_queue WHERE review_status IN ('STAGE1_BLIND', 'STAGE2_UNBLIND')"
    ).fetchall()

    window_satisfied = elapsed_sec >= float(min_window_sec)
    # 计算总预算耗尽状态（依据 Parse 0 total_budget_json 配置的上限，未配置默认不视为耗尽）
    total_budget = json.loads(p0["total_budget_json"] or "{}") if p0 else {}
    if not isinstance(total_budget, dict):
        total_budget = {}
    used_handoffs = int(
        conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM lineage_nodes
            WHERE node_status IN ('AWAITING_TRIAGE','PENDING_REVIEW','BLOCKED_L4B','SEALED','CLOSED')
               OR (column_a_facts_md IS NOT NULL AND TRIM(column_a_facts_md) != '')
            """
        ).fetchone()["cnt"]
        or 0
    )
    used_official_evals = int(
        conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM observations
            WHERE tier IN ('official','heavy') AND revalidated_from_obs_id IS NULL
            """
        ).fetchone()["cnt"]
        or 0
    )
    max_handoffs = total_budget.get("max_total_handoffs")
    max_evals = total_budget.get("max_official_evals")
    max_wall_clock = total_budget.get("max_wall_clock_sec")
    budget_exhausted = False
    if isinstance(max_handoffs, (int, float)) and max_handoffs > 0 and used_handoffs >= int(max_handoffs):
        budget_exhausted = True
    if isinstance(max_evals, (int, float)) and max_evals > 0 and used_official_evals >= int(max_evals):
        budget_exhausted = True
    if isinstance(max_wall_clock, (int, float)) and max_wall_clock > 0 and elapsed_sec >= float(max_wall_clock):
        budget_exhausted = True

    closure_allowed = False
    gate_code = "GATE_BLOCKED"

    if eff_mode == "PARTIAL_ON_HUMAN_STOP" or human_aborted:
        # 严格校验控制面真实写入的 human_stop_requested_at，绝不轻信 Agent 伪造 human_aborted=true！
        if not human_stop_ts:
            closure_allowed = False
            gate_code = "HUMAN_STOP_NOT_RECORDED"
        else:
            closure_allowed = True
            gate_code = "GATE_PASSED_HUMAN_STOP"
    elif eff_mode == "PARTIAL_ON_BUDGET":
        if not window_satisfied:
            closure_allowed = False
            gate_code = "GATE_BLOCKED_MIN_COMMITMENT_WINDOW"
        elif not budget_exhausted:
            closure_allowed = False
            gate_code = "GATE_BLOCKED_BUDGET_NOT_EXHAUSTED"
        else:
            closure_allowed = True
            gate_code = "GATE_PASSED_PARTIAL_BUDGET"
    else:  # FULL
        if not req_qs:
            closure_allowed = False
            gate_code = "GATE_BLOCKED_NO_CONTRACT"
        elif blocking_qs:
            closure_allowed = False
            gate_code = "GATE_BLOCKED_MISSING_FULL_GOAL_L3"
        elif pending_reval:
            closure_allowed = False
            gate_code = "GATE_BLOCKED_PENDING_REVAL"
        else:
            closure_allowed = True
            gate_code = "GATE_PASSED_FULL"

    return {
        "mode": eff_mode,
        "closure_allowed": closure_allowed,
        "gate_code": gate_code,
        "required_questions": req_qs,
        "full_goal_l3_counts": {q: full_counts.get(q, 0) for q in req_qs},
        "total_l3_counts": {q: all_l3_counts.get(q, 0) for q in req_qs},
        "blocking_questions_missing_full_goal": blocking_qs,
        "min_commitment_window_sec": min_window_sec,
        "elapsed_sec": round(elapsed_sec, 2),
        "commitment_window_satisfied": window_satisfied,
        "budget_exhausted": budget_exhausted,
        "budget_usage": {"used_handoffs": used_handoffs, "used_official_evals": used_official_evals, "limits": total_budget},
        "human_stop_requested_at": human_stop_ts or None,
        "pending_reviews": [dict(r) for r in pending_reviews],
        "pending_revalidation": [dict(r) for r in pending_reval],
    }


def schedule_control_plane_snapshot(
    conn: sqlite3.Connection,
    max_concurrent_workers: int | None = None,
    *,
    workspace_root: str = "",
) -> dict[str, Any]:
    """纯查 SQLite（<50ms，零写盘零哈希副作用）生成两级公平调度快照（严禁在此轮询中动态导入/运行任何 Python 仪器！）。"""
    _ = workspace_root
    cfg = load_runtime_config()
    hard_cap = int(cfg.get("max_concurrent_workers_hard_cap", 10))
    wanted = int(max_concurrent_workers or cfg.get("max_concurrent_workers", 6))
    slot_cap = max(1, min(hard_cap, wanted))

    p0 = conn.execute("SELECT * FROM parse0_contract WHERE contract_id = 'active'").fetchone()
    req_qs = json.loads(p0["subquestions_json"]) if p0 else []
    q_order = json.loads(p0["question_order_json"]) if p0 else []
    initial_instruments = json.loads(p0["initial_instruments_json"] or "[]") if p0 else []
    shared_inputs = json.loads(p0["shared_inputs_json"] or "[]") if (p0 and "shared_inputs_json" in p0.keys()) else []
    stage1_works_checked = bool(int(p0["stage1_works_checked"] or 0)) if (p0 and "stage1_works_checked" in p0.keys()) else False
    latest_spec_revision = int(p0["latest_spec_revision"] or 0) if (p0 and "latest_spec_revision" in p0.keys()) else 0
    latest_ruling_summary_md = str(p0["latest_ruling_summary_md"] or "") if (p0 and "latest_ruling_summary_md" in p0.keys()) else ""
    missing_initial_instruments = compute_missing_initial_instruments(conn) if p0 else []
    goal_md = str(p0["goal_and_completion_md"] or "") if p0 else ""
    stage = str(p0["stage"]) if p0 else "STAGE1_PARSE0"
    non_l1 = int(p0["consecutive_non_l1_handoffs"] or 0) if p0 else 0
    has_parse0_signed = bool(p0 and str(p0["human_signed_at"] or "").strip() and goal_md.strip())

    closure_row = conn.execute("SELECT * FROM project_closure_state WHERE id = 1").fetchone()
    closure_state = dict(closure_row) if closure_row else {
        "status": "OPEN",
        "verifier_final_audit_passed": 0,
        "human_stop_requested_at": None,
        "latest_delivery_id": None,
        "latest_delivery_sha256": None,
    }
    human_stop_active = bool(closure_state.get("human_stop_requested_at"))

    order_status = get_question_order_status(conn)

    # 查询待分诊分支集合（AWAITING_TRIAGE 硬锁：同分支有待分诊节点时严禁抢跑启动下代）
    awaiting_triage = [
        dict(r)
        for r in conn.execute(
            """
            SELECT node_id, question_id, branch_id, family_id, evidence_grade, mechanism_summary
            FROM lineage_nodes
            WHERE node_status = 'AWAITING_TRIAGE'
            ORDER BY updated_at ASC
            """
        ).fetchall()
    ]
    triage_locked_branches = {str(r["branch_id"]) for r in awaiting_triage}

    active_nodes = [
        dict(r)
        for r in conn.execute(
            """
            SELECT node_id, question_id, branch_id, family_id, generation, node_status,
                   worktree_abs_path, requires_json, premise_revoked, pressure_tokens,
                   effective_context_window, spec_revision,
                   first_reflection_unlocked, last_revision_requests_json, lane_assignment,
                   will_md, explorer_will_md, pending_handoff_mode, pending_handoff_reason, updated_at
            FROM lineage_nodes
            WHERE node_status IN ('EXPLORING', 'ACTIVE_REVISING')
            ORDER BY created_at ASC
            """
        ).fetchall()
    ]

    # 批量取回各节点最新一条五段看板正文并格式化为 briefing_snapshot_md（确保探索者 100% 收到正文）
    latest_briefings: dict[str, str] = {}
    for br in conn.execute(
        """
        SELECT node_id, sec1_mechanism, sec2_verified_baseline, sec3_bottleneck,
               sec4_dead_ends, sec5_immediate_will, created_at
        FROM lineage_briefings
        ORDER BY created_at ASC
        """
    ).fetchall():
        bnid = str(br["node_id"])
        latest_briefings[bnid] = "\n\n".join(
            [
                f"#### 1. 核心机制\n{br['sec1_mechanism']}",
                f"#### 2. 已证实基线与返工要求\n{br['sec2_verified_baseline']}",
                f"#### 3. 当前瓶颈\n{br['sec3_bottleneck']}",
                f"#### 4. 关键死胡同\n{br['sec4_dead_ends']}",
                f"#### 5. 本代首要遗嘱 (Immediate Will)\n{br['sec5_immediate_will']}",
            ]
        )

    need_briefing: list[dict[str, Any]] = []
    ready_to_run: list[dict[str, Any]] = []
    pending_handoff_nodes: list[dict[str, Any]] = []
    blocked_by_requires: list[dict[str, Any]] = []

    for node in active_nodes:
        nid = str(node["node_id"])
        bid = str(node["branch_id"])
        qid = str(node["question_id"])
        # 若探索者已写完遗嘱或异常中断等待伴随落库，归入待伴随恢复队列，严禁重复派发探索者
        if node.get("pending_handoff_mode"):
            pending_handoff_nodes.append(node)
            continue
        # AWAITING_TRIAGE 同分支防抢跑硬锁
        if bid in triage_locked_branches:
            continue
        # 策略题序未解锁
        if not order_status.get(qid, {}).get("unlocked", True):
            blocked_by_requires.append({**node, "blocked_reason": "question_order_locked"})
            continue
        # 分支级确定性 requires（仅锁本分支）
        reqs = json.loads(node.get("requires_json") or "[]")
        sat, unmet = check_branch_requires_satisfied(conn, reqs)
        if not sat:
            blocked_by_requires.append({**node, "unmet_requires": unmet})
            continue
        if nid not in latest_briefings:
            need_briefing.append(node)
        else:
            ready_to_run.append({**node, "briefing_snapshot_md": latest_briefings[nid]})

    # 两级公平排序：先按子题活跃数均衡，再在子题内按学派活跃数均衡
    q_counts: dict[str, int] = {}
    qf_counts: dict[tuple[str, str], int] = {}
    for r in ready_to_run:
        q = str(r["question_id"])
        f = str(r["family_id"] or "unclassified")
        q_counts[q] = q_counts.get(q, 0) + 1
        qf_counts[(q, f)] = qf_counts.get((q, f), 0) + 1
    ready_to_run.sort(
        key=lambda r: (
            q_counts.get(str(r["question_id"]), 0),
            qf_counts.get((str(r["question_id"]), str(r["family_id"] or "unclassified")), 0),
            str(r["node_id"]),
        )
    )

    blind_reviews = [
        dict(r)
        for r in conn.execute(
            """
            SELECT review_id, question_id, source_node_id, source_type, review_status, proposer_session_id
            FROM review_queue
            WHERE review_status IN ('STAGE1_BLIND', 'STAGE2_UNBLIND')
            ORDER BY created_at ASC
            """
        ).fetchall()
    ]
    pending_surveys = [
        dict(r)
        for r in conn.execute(
            "SELECT req_id, question_id, node_id, topic_query, reason FROM survey_requests WHERE status = 'PENDING' ORDER BY created_at ASC"
        ).fetchall()
    ]
    open_works = [
        dict(r)
        for r in conn.execute(
            "SELECT ticket_id, question_id, ticket_type, instrument_id, payload_json, updated_at FROM works_engineering_queue WHERE status = 'OPEN' ORDER BY created_at ASC"
        ).fetchall()
    ]
    pending_reval = [
        dict(r)
        for r in conn.execute(
            "SELECT queue_id, obs_id, question_id, target_instrument_id, target_version, updated_at FROM pending_revalidation_queue WHERE status = 'PENDING' ORDER BY created_at ASC"
        ).fetchall()
    ]
    unhealthy_instruments = [
        dict(r)
        for r in conn.execute(
            "SELECT instrument_id, version, question_id, instrument_role, consecutive_error_count, updated_at FROM instruments WHERE is_active = 1 AND health_status = 'UNHEALTHY'"
        ).fetchall()
    ]
    active_instruments = [
        dict(r)
        for r in conn.execute(
            """
            SELECT instrument_id, version, question_id, instrument_role,
                   artifact_schema, health_status, default_spec_json, updated_at
            FROM instruments
            WHERE is_active = 1
            ORDER BY instrument_id, version
            """
        ).fetchall()
    ]
    active_instruments_fingerprint = [
        f"{r['instrument_id']}:v{r['version']}:{r['health_status']}:{r['updated_at']}"
        for r in active_instruments
    ]
    ambiguous_alerts = [
        dict(r)
        for r in conn.execute(
            "SELECT alert_id, stage, notes, created_at FROM compliance_alerts WHERE status = 'ALERT_AMBIGUOUS_SPEC' ORDER BY created_at DESC LIMIT 10"
        ).fetchall()
    ]
    external_lit_count = int(conn.execute("SELECT COUNT(*) AS cnt FROM external_literature_cards").fetchone()["cnt"] or 0)
    family_concentration_alerts = compute_family_concentration_alerts(conn)
    topology_health = compute_topology_and_revision_health(conn, question_filter="ALL", slot_cap=slot_cap)
    orphaned_revisions = topology_health.get("orphaned_blind_review_revisions") or []
    understaffed_questions = topology_health.get("understaffed_questions") or []
    stalled_branches = topology_health.get("stalled_or_aborted_branches") or []

    # 读取最近一条监察委 STAGE2_HEARTBEAT 合规告警（若状态为 ALERT，用于闭环唤醒后勤/工造司）
    latest_hb_row = conn.execute(
        """
        SELECT alert_id, stage, status, blocking_questions_json, notes, created_at
        FROM compliance_alerts
        WHERE stage = 'STAGE2_HEARTBEAT'
        ORDER BY created_at DESC LIMIT 1
        """
    ).fetchone()
    active_supervisory_alert: dict[str, Any] | None = None
    if latest_hb_row is not None and str(latest_hb_row["status"]).upper() == "ALERT":
        active_supervisory_alert = dict(latest_hb_row)

    # 判断已解锁但既无 FULL_GOAL L3 也无在研/待分诊/待盲审节点的子题
    in_flight_qs = {
        *(str(r["question_id"]) for r in active_nodes),
        *(str(r["question_id"]) for r in awaiting_triage),
        *(str(r["question_id"]) for r in blind_reviews),
    }
    questions_needing_branch = [
        q for q in req_qs
        if order_status.get(q, {}).get("unlocked", True)
        and order_status.get(q, {}).get("full_goal_l3_count", 0) == 0
        and q not in in_flight_qs
    ]

    # Stage 3 两步联合终核待办检测（DELIVERY_EXPORTED 且尚未通过匹配当前版本的终核）
    latest_did = str(closure_state.get("latest_delivery_id") or "")
    latest_sha = str(closure_state.get("latest_delivery_sha256") or "")
    audited_did = str(closure_state.get("verifier_audited_delivery_id") or "")
    audited_sha = str(closure_state.get("verifier_audited_delivery_sha256") or "")
    verifier_matched = (
        int(closure_state.get("verifier_final_audit_passed") or 0) == 1
        and bool(latest_did)
        and audited_did == latest_did
        and audited_sha == latest_sha
    )
    stage3_revision_pending = closure_state.get("status") == "REVISION_REQUESTED"
    stage3_final_audit_pending = (
        closure_state.get("status") == "DELIVERY_EXPORTED"
        and bool(latest_did)
        and not verifier_matched
    )
    stage3_supervisory_sign_pending = (
        closure_state.get("status") == "DELIVERY_EXPORTED"
        and verifier_matched
    )

    if human_stop_active:
        closure_gate = check_stage2_closure_gate_data(conn, mode="PARTIAL_ON_HUMAN_STOP", human_aborted=True)
    else:
        closure_gate = check_stage2_closure_gate_data(conn, mode="FULL", human_aborted=False)
        if not closure_gate["closure_allowed"] and closure_gate.get("budget_exhausted"):
            budget_gate = check_stage2_closure_gate_data(conn, mode="PARTIAL_ON_BUDGET", human_aborted=False)
            if budget_gate["closure_allowed"]:
                closure_gate = budget_gate

    stop_new_dispatch = bool(human_stop_active or closure_gate.get("closure_allowed"))

    return {
        "initialized": True,
        "stage": stage,
        "parse0_signed": has_parse0_signed,
        "stage1_works_checked": stage1_works_checked,
        "initial_instruments": initial_instruments,
        "missing_initial_instruments": missing_initial_instruments,
        "latest_spec_revision": latest_spec_revision,
        "latest_ruling_summary_md": latest_ruling_summary_md,
        "goal_and_completion_md": goal_md,
        "required_questions": req_qs,
        "question_order": q_order,
        "shared_inputs_rel_paths": shared_inputs,
        "question_order_status": order_status,
        "questions_needing_branch": questions_needing_branch,
        "understaffed_questions": [] if stop_new_dispatch else understaffed_questions,
        "orphaned_blind_review_revisions": [] if stop_new_dispatch else orphaned_revisions,
        "stalled_or_aborted_branches": stalled_branches,
        "slot_utilization": topology_health.get("slot_utilization") or {"active_branches_count": 0, "slot_cap": slot_cap, "free_slots": slot_cap},
        "active_supervisory_alert": active_supervisory_alert,
        "external_literature_count": external_lit_count,
        "active_instruments": active_instruments,
        "active_instruments_fingerprint": active_instruments_fingerprint,
        "slot_cap": slot_cap,
        "triage_locked_branches": sorted(triage_locked_branches),
        "family_concentration_alerts": family_concentration_alerts,
        "ambiguous_spec_alerts": ambiguous_alerts,
        "unhealthy_instruments": unhealthy_instruments,
        "pending_surveys": pending_surveys,
        "open_works_tickets": open_works,
        "pending_revalidation": pending_reval,
        "awaiting_triage": awaiting_triage,
        "pending_reviews": blind_reviews,
        "pending_handoff_nodes": pending_handoff_nodes,
        "explorers_needing_briefing": [] if stop_new_dispatch else need_briefing,
        "explorers_ready_to_run": [] if stop_new_dispatch else ready_to_run[:slot_cap],
        "blocked_by_requires_nodes": blocked_by_requires,
        "stagnation_triggered": non_l1 >= int(cfg.get("stagnation_consecutive_non_l1_handoffs", 8)),
        "human_stop_active": human_stop_active,
        "closure_state": closure_state,
        "closure_gate": closure_gate,
        "stage3_revision_pending": stage3_revision_pending,
        "stage3_final_audit_pending": stage3_final_audit_pending,
        "stage3_supervisory_sign_pending": stage3_supervisory_sign_pending,
    }


def uninitialized_schedule_snapshot(max_concurrent_workers: int | None = None) -> dict[str, Any]:
    """工作区尚未建库时返回的纯只读空快照（零写盘、零建目录、零建库）。"""
    cfg = load_runtime_config()
    hard_cap = int(cfg.get("max_concurrent_workers_hard_cap", 10))
    wanted = int(max_concurrent_workers or cfg.get("max_concurrent_workers", 6))
    slot_cap = max(1, min(hard_cap, wanted))
    return {
        "initialized": False,
        "stage": "STAGE1_PARSE0",
        "parse0_signed": False,
        "stage1_works_checked": False,
        "initial_instruments": [],
        "missing_initial_instruments": [],
        "latest_spec_revision": 0,
        "latest_ruling_summary_md": "",
        "goal_and_completion_md": "",
        "required_questions": [],
        "question_order": [],
        "shared_inputs_rel_paths": [],
        "question_order_status": {},
        "questions_needing_branch": [],
        "understaffed_questions": [],
        "orphaned_blind_review_revisions": [],
        "stalled_or_aborted_branches": [],
        "slot_utilization": {"active_branches_count": 0, "slot_cap": slot_cap, "free_slots": slot_cap},
        "active_supervisory_alert": None,
        "external_literature_count": 0,
        "active_instruments": [],
        "active_instruments_fingerprint": [],
        "slot_cap": slot_cap,
        "triage_locked_branches": [],
        "family_concentration_alerts": [],
        "ambiguous_spec_alerts": [],
        "unhealthy_instruments": [],
        "pending_surveys": [],
        "open_works_tickets": [],
        "pending_revalidation": [],
        "awaiting_triage": [],
        "pending_reviews": [],
        "pending_handoff_nodes": [],
        "explorers_needing_briefing": [],
        "explorers_ready_to_run": [],
        "blocked_by_requires_nodes": [],
        "stagnation_triggered": False,
        "human_stop_active": False,
        "closure_state": {"status": "OPEN"},
        "closure_gate": {
            "mode": "FULL",
            "closure_allowed": False,
            "gate_code": "GATE_BLOCKED_NO_CONTRACT",
            "required_questions": [],
            "full_goal_l3_counts": {},
            "total_l3_counts": {},
            "blocking_questions_missing_full_goal": [],
            "min_commitment_window_sec": 0,
            "elapsed_sec": 0.0,
            "commitment_window_satisfied": True,
            "budget_exhausted": False,
            "budget_usage": {"used_handoffs": 0, "used_official_evals": 0, "limits": {}},
            "human_stop_requested_at": None,
            "pending_reviews": [],
            "pending_revalidation": [],
        },
        "stage3_revision_pending": False,
        "stage3_final_audit_pending": False,
        "stage3_supervisory_sign_pending": False,
    }

