"""控制面子域 4：纯规则并发调度快照、分支前置校验、学派聚拢告警、拓扑健康与终局门禁。

底层纯只读 SQL 汇总已拆分至 `snapshot_queries.py`，本模块专注纯调度规则计算与快照组装。
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
from ..mcp_core_helpers import load_runtime_config
from .lifecycle_ops import (
    _parse_iso_utc,
    compute_missing_initial_instruments,
)
from .snapshot_queries import (
    fetch_active_branch_family_rows,
    fetch_active_parse0_row,
    fetch_closure_gate_raw_data,
    fetch_closure_state_row,
    fetch_l3_counts_by_question,
    fetch_parse0_subquestions_and_order,
    fetch_snapshot_queues_and_tables,
    fetch_subproblem_states,
    fetch_topology_raw_data,
    fetch_v03_queues,
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
    req_qs, q_order = fetch_parse0_subquestions_and_order(conn)
    full_l3_counts, any_l3_counts = fetch_l3_counts_by_question(conn)

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

    rows = fetch_active_branch_family_rows(conn)
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
    """纯查 SQLite (<15ms) 计算全卷或指定子题的 Worktree 拓扑健康度、断代分支、孤儿盲审返工单与缺编正交学派。"""
    cfg = load_runtime_config()
    eff_slot_cap = int(slot_cap or cfg.get("max_concurrent_workers", 6))
    qf = str(question_filter or "ALL").strip()
    order_status = get_question_order_status(conn)

    raw = fetch_topology_raw_data(conn, question_filter=qf)
    fam_rows = raw["fam_rows"]
    all_nodes = raw["all_nodes"]
    rev_rows = raw["rev_rows"]
    total_live_branches = raw["total_live_branches"]
    reviewed_source_nodes = raw["reviewed_source_nodes"]

    active_families_by_q: dict[str, list[str]] = {}
    for fr in fam_rows:
        if str(fr["family_status"] or "ACTIVE") == "ACTIVE":
            active_families_by_q.setdefault(str(fr["question_id"]), []).append(str(fr["family_id"]))

    latest_by_branch: dict[str, dict[str, Any]] = {}
    branch_has_live_node: set[str] = set()
    live_statuses = ("EXPLORING", "ACTIVE_REVISING", "AWAITING_TRIAGE", "PENDING_REVIEW")
    for d in all_nodes:
        bid = str(d["branch_id"])
        latest_by_branch[bid] = d
        if str(d["node_status"]) in live_statuses:
            branch_has_live_node.add(bid)

    free_slots = max(0, eff_slot_cap - total_live_branches)

    active_parent_ids = {
        str(r["parent_node_id"])
        for r in all_nodes
        if r["parent_node_id"] and str(r["node_status"]) in live_statuses
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

    raw = fetch_closure_gate_raw_data(conn)
    p0 = raw["p0"]
    closure = raw["closure"]
    full_counts = raw["full_counts"]
    all_l3_counts = raw["all_l3_counts"]
    pending_reval = raw["pending_reval"]
    pending_reviews = raw["pending_reviews"]
    used_handoffs = raw["used_handoffs"]
    used_official_evals = raw["used_official_evals"]

    req_qs = json.loads(p0["subquestions_json"]) if p0 else []
    min_window_sec = int(p0["min_commitment_window_sec"] or 0) if p0 else 0
    signed_dt = _parse_iso_utc(str(p0["human_signed_at"])) if p0 else None
    elapsed_sec = 0.0
    if signed_dt is not None:
        elapsed_sec = max(0.0, (datetime.now(timezone.utc) - signed_dt).total_seconds())

    human_stop_ts = str(closure["human_stop_requested_at"] or "").strip() if closure else ""
    blocking_qs = [q for q in req_qs if full_counts.get(q, 0) < 1]
    window_satisfied = elapsed_sec >= float(min_window_sec)

    total_budget = json.loads(p0["total_budget_json"] or "{}") if p0 else {}
    if not isinstance(total_budget, dict):
        total_budget = {}
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
    else:
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
        "pending_reviews": pending_reviews,
        "pending_revalidation": pending_reval,
    }


def schedule_control_plane_snapshot(
    conn: sqlite3.Connection,
    max_concurrent_workers: int | None = None,
    *,
    workspace_root: str = "",
) -> dict[str, Any]:
    """纯查 SQLite（<50ms，零写盘零哈希副作用）生成两级公平调度快照。"""
    _ = workspace_root
    cfg = load_runtime_config()
    hard_cap = int(cfg.get("max_concurrent_workers_hard_cap", 10))
    wanted = int(max_concurrent_workers or cfg.get("max_concurrent_workers", 6))
    slot_cap = max(1, min(hard_cap, wanted))

    p0 = fetch_active_parse0_row(conn)
    req_qs = json.loads(p0["subquestions_json"]) if p0 else []
    q_order = json.loads(p0["question_order_json"]) if p0 else []
    initial_instruments = json.loads(p0["initial_instruments_json"] or "[]") if p0 else []
    shared_inputs = json.loads(p0.get("shared_inputs_json") or "[]") if p0 else []
    stage1_works_checked = bool(int(p0.get("stage1_works_checked") or 0)) if p0 else False
    latest_spec_revision = int(p0.get("latest_spec_revision") or 0) if p0 else 0
    latest_ruling_summary_md = str(p0.get("latest_ruling_summary_md") or "") if p0 else ""
    autonomy_mode = str(p0.get("autonomy_mode") or "WAVE_CONFIRM") if p0 else "WAVE_CONFIRM"
    missing_initial_instruments = compute_missing_initial_instruments(conn) if p0 else []
    goal_md = str(p0["goal_and_completion_md"] or "") if p0 else ""
    stage = str(p0["stage"]) if p0 else "STAGE1_PARSE0"
    has_parse0_signed = bool(p0 and str(p0["human_signed_at"] or "").strip() and goal_md.strip())

    closure_state = fetch_closure_state_row(conn) or {
        "status": "OPEN",
        "verifier_final_audit_passed": 0,
        "human_stop_requested_at": None,
        "latest_delivery_id": None,
        "latest_delivery_sha256": None,
        "frozen_delivery_dir_abs_path": "",
    }
    human_stop_active = bool(closure_state.get("human_stop_requested_at"))
    order_status = get_question_order_status(conn)
    subproblem_states = fetch_subproblem_states(conn)
    v03_q = fetch_v03_queues(conn)

    qdata = fetch_snapshot_queues_and_tables(conn)
    awaiting_triage = qdata["awaiting_triage"]
    triage_locked_branches = {str(r["branch_id"]) for r in awaiting_triage}
    active_nodes = qdata["active_nodes"]
    latest_briefings = qdata["latest_briefings"]

    need_briefing: list[dict[str, Any]] = []
    ready_to_run: list[dict[str, Any]] = []
    pending_handoff_nodes: list[dict[str, Any]] = []
    blocked_by_requires: list[dict[str, Any]] = []
    human_paused_nodes: list[dict[str, Any]] = []
    early_handoff_nodes: list[dict[str, Any]] = []

    for node in active_nodes:
        nid = str(node["node_id"])
        bid = str(node["branch_id"])
        qid = str(node["question_id"])
        ctrl_st = str(node.get("control_state") or "AUTO_RUNNING")
        q_state = subproblem_states.get(qid, {})
        q_dispatch = str(q_state.get("dispatch_state") or "DISPATCHING")

        if node.get("pending_handoff_mode"):
            pending_handoff_nodes.append(node)
            continue
        if ctrl_st == "EARLY_HANDOFF_READY":
            early_handoff_nodes.append(node)
            continue
        if ctrl_st in ("PAUSE_DRAINING", "HUMAN_ACTIVE") or int(node.get("personal_turn_active") or 0) == 1:
            human_paused_nodes.append(node)
            continue
        if q_dispatch != "DISPATCHING":
            continue
        if bid in triage_locked_branches:
            continue
        if not order_status.get(qid, {}).get("unlocked", True):
            blocked_by_requires.append({**node, "blocked_reason": "question_order_locked"})
            continue
        reqs = json.loads(node.get("requires_json") or "[]")
        sat, unmet = check_branch_requires_satisfied(conn, reqs)
        if not sat:
            blocked_by_requires.append({**node, "unmet_requires": unmet})
            continue
        if nid not in latest_briefings:
            need_briefing.append(node)
        else:
            ready_to_run.append({**node, "briefing_snapshot_md": latest_briefings[nid]})

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

    blind_reviews = qdata["blind_reviews"]
    active_instruments = qdata["active_instruments"]
    active_instruments_fingerprint = [
        f"{r['instrument_id']}:v{r['version']}:{r['health_status']}:{r['updated_at']}"
        for r in active_instruments
    ]
    family_concentration_alerts = compute_family_concentration_alerts(conn)
    topology_health = compute_topology_and_revision_health(conn, question_filter="ALL", slot_cap=slot_cap)
    orphaned_revisions = topology_health.get("orphaned_blind_review_revisions") or []
    understaffed_questions = topology_health.get("understaffed_questions") or []
    stalled_branches = topology_health.get("stalled_or_aborted_branches") or []

    latest_hb_row = qdata["latest_hb_row"]
    active_supervisory_alert: dict[str, Any] | None = None
    if latest_hb_row is not None and str(latest_hb_row["status"]).upper() == "ALERT":
        active_supervisory_alert = latest_hb_row

    in_flight_qs = {
        *(str(r["question_id"]) for r in active_nodes),
        *(str(r["question_id"]) for r in awaiting_triage),
        *(str(r["question_id"]) for r in blind_reviews),
    }
    questions_needing_branch = [
        q for q in req_qs
        if order_status.get(q, {}).get("unlocked", True)
        and order_status.get(q, {}).get("full_goal_l3_count", 0) == 0
        and str(subproblem_states.get(q, {}).get("dispatch_state") or "DISPATCHING") == "DISPATCHING"
        and q not in in_flight_qs
    ]

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

    if human_stop_active:
        closure_gate = check_stage2_closure_gate_data(conn, mode="PARTIAL_ON_HUMAN_STOP", human_aborted=True)
    else:
        closure_gate = check_stage2_closure_gate_data(conn, mode="FULL", human_aborted=False)
        if not closure_gate["closure_allowed"] and closure_gate.get("budget_exhausted"):
            budget_gate = check_stage2_closure_gate_data(conn, mode="PARTIAL_ON_BUDGET", human_aborted=False)
            if budget_gate["closure_allowed"]:
                closure_gate = budget_gate

    stop_new_dispatch = bool(human_stop_active or closure_gate.get("closure_allowed"))

    subproblem_runtime_list = [subproblem_states[q] for q in sorted(subproblem_states.keys())]
    living_surveys_dict = v03_q["living_surveys"]
    living_surveys_list = [living_surveys_dict[q] for q in sorted(living_surveys_dict.keys())]
    active_confs = v03_q["active_conferences"]

    return {
        "initialized": True,
        "stage": stage,
        "autonomy_mode": autonomy_mode,
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
        "subproblem_states": subproblem_states,
        "subproblem_runtime_state": subproblem_runtime_list,
        "questions_needing_branch": questions_needing_branch,
        "understaffed_questions": [] if stop_new_dispatch else understaffed_questions,
        "orphaned_blind_review_revisions": [] if stop_new_dispatch else orphaned_revisions,
        "stalled_or_aborted_branches": stalled_branches,
        "slot_utilization": topology_health.get("slot_utilization") or {"active_branches_count": 0, "slot_cap": slot_cap, "free_slots": slot_cap},
        "active_supervisory_alert": active_supervisory_alert,
        "external_literature_count": qdata["external_lit_count"],
        "active_instruments": active_instruments,
        "active_instruments_fingerprint": active_instruments_fingerprint,
        "slot_cap": slot_cap,
        "triage_locked_branches": sorted(triage_locked_branches),
        "family_concentration_alerts": family_concentration_alerts,
        "ambiguous_spec_alerts": qdata["ambiguous_alerts"],
        "unhealthy_instruments": qdata["unhealthy_instruments"],
        "pending_surveys": qdata["pending_surveys"],
        "open_works_tickets": qdata["open_works"],
        "pending_revalidation": qdata["pending_reval"],
        "awaiting_triage": awaiting_triage,
        "pending_reviews": blind_reviews,
        "pending_handoff_nodes": pending_handoff_nodes,
        "early_handoff_nodes": early_handoff_nodes,
        "human_paused_nodes": human_paused_nodes,
        "explorers_needing_briefing": [] if stop_new_dispatch else need_briefing,
        "explorers_ready_to_run": [] if stop_new_dispatch else ready_to_run[:slot_cap],
        "blocked_by_requires_nodes": blocked_by_requires,
        "pending_proposals": v03_q["pending_proposals"],
        "active_conferences": active_confs,
        "active_wave_conferences": active_confs,
        "open_lemma_gaps": v03_q["open_lemma_gaps"],
        "living_surveys": living_surveys_dict,
        "living_surveys_list": living_surveys_list,
        "pending_effects_count": v03_q["pending_effects_count"],
        "human_stop_active": human_stop_active,
        "closure_state": closure_state,
        "closure_gate": closure_gate,
        "stage3_revision_pending": stage3_revision_pending,
        "stage3_final_audit_pending": stage3_final_audit_pending,
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
        "autonomy_mode": "WAVE_CONFIRM",
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
        "subproblem_states": {},
        "subproblem_runtime_state": [],
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
        "early_handoff_nodes": [],
        "human_paused_nodes": [],
        "explorers_needing_briefing": [],
        "explorers_ready_to_run": [],
        "blocked_by_requires_nodes": [],
        "pending_proposals": [],
        "active_conferences": [],
        "active_wave_conferences": [],
        "open_lemma_gaps": [],
        "living_surveys": {},
        "living_surveys_list": [],
        "pending_effects_count": 0,
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
    }
